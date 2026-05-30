# ADR 0007 — `m3_sweep` is not pure legacy: relocate live servicers, widen the FR-018 fence (v0.0.1, T020)

**Status:** accepted (2026-05-30) · corrects data-model Entity 7 (“delete `m3_sweep`”) and the T020 reporter-writer deletion list

## Context

T020 (hoist-then-delete) treated every `m[0-9]*` source module as legacy and slated
it for `git rm` (data-model Entity 7, SC-001). Two of those modules turned out to
carry **live** code that the `mypy --strict` forcing-function surfaced the moment they
were deleted:

1. **`m3_sweep` holds the live gRPC servicers.** `M3ChatServicer` /
   `M3CompletionsServicer` (production-shape servicers wrapping `MockEngine` without
   vllm/torch deps) + `serve_in_process` / `serve_in_process_adapter` are imported by
   the two Modal bench-server deploy scripts
   (`scripts/python/modal_bench_grpc_server.py`,
   `scripts/python/modal_bench_rest_grpc_server.py`) and by `test_endpoint_provider`.
   The scripts are reachable from the **retained** `modal_endpoint.py`
   (`from scripts.python.modal_bench_grpc_server import app, serve_bench`), so the
   servicers are live deploy infrastructure, not legacy. The scripts live **outside
   the FR-018 edit fence** (`scripts/python/` is not in the T030 allow-list).

2. **The reporter M1 writers are live.** ADR 0006 kept `bench` (M1 proxy-vs-native)
   as the no-arg default; that path writes its output via `reporter.write_json` /
   `write_csv` / `write_summary_md`. The T020 task text listed those three as
   “deleted (M1)” — but they are consumed by the retained `bench` CLI path, so they
   are **not** orphaned.

## Decision

**(a) Relocate the live servicers into a de-prefixed home and widen the fence.**
Move `M3ChatServicer` → `ChatServicer`, `M3CompletionsServicer` → `CompletionsServicer`,
`_BenchHealthServicer`, `_request_prompt_text`, `_completion_prompt`,
`serve_in_process`, `serve_in_process_adapter` into a new retained module
`tools/benchmark/src/vllm_grpc_bench/grpc_servicers.py`. The dead M1/M3 sweep +
aggregation machinery in `m3_sweep` (CITATIONS, `plan_cells`, `_aggregate`,
`build_recommendations`, the `_drive_*_cell` drivers, the JSON (de)serializers, …) is
deleted with the rest of `m3_sweep`. Repoint the two Modal scripts +
`test_endpoint_provider` at `grpc_servicers` with the de-prefixed names. `m3_sweep.py`
is then deleted → **zero m-prefixed source modules (SC-001 ✓)**.

This requires editing two files under `scripts/python/`. **Widen the FR-018 edit fence**
to admit `scripts/python/modal_bench_grpc_server.py` +
`scripts/python/modal_bench_rest_grpc_server.py`, exactly as ADR 0006 widened it to admit
the `Makefile`: the de-prefix legitimately touches them because they import the relocated
package symbol. The fence’s hard exclusions (`.proto`, `vllm`, `packages/*`,
other-`specs`) are untouched. T030’s scope grep is updated accordingly.

**(b) Keep the live M1 reporter writers.** `write_json` / `write_csv` /
`write_summary_md` (+ their helpers `_to_dict`, `_delta`, `_row`, `_fmt_legacy`,
`_meta_section`, `_CROSS_METRIC_LABELS`, `_SINGLE_TARGET_METRICS`,
`_TARGET_DISPLAY_NAMES`) stay in `reporter.py` alongside the already-narrowed
`write_cross_run_md` / `write_three_way_md` (ADR 0006). Only the truly-orphaned
M4/M5/M5.1/M5.2 writers + `write_wire_size_comparison_md` + the `m3_types` /
`m5_2_regen` imports they pulled were deleted (`reporter.py`: 2830 → ~1380 lines,
milestone-import-clean).

## Consequences / spec reconciliation

- **data-model Entity 7 corrected** — `m3_sweep` is *not* deleted wholesale; its live
  servicer surface relocates to `grpc_servicers.py` first. New retained module added to
  Entity 3.
- **FR-018 edit-fence widened** (ADR 0006 precedent) to the two bench-server scripts.
  T030’s grep allow-list gains `scripts/python/modal_bench_grpc_server.py` +
  `scripts/python/modal_bench_rest_grpc_server.py`.
- **T020 reporter-writer deletion list corrected** — the M1 `write_json` / `write_csv` /
  `write_summary_md` are KEPT (live via `bench`), not deleted. Only M4/M5/M5.1/M5.2
  writers + `write_wire_size_comparison_md` are gone.
- **T028 audit input** — `m6_1_torch_pin` was confirmed orphaned (only `m6_1_sweep`,
  now deleted, imported it) and removed with the legacy batch; `compare.py` / `ci.py`
  remain (non-m-prefixed, used by live paths).
- **Symbol de-prefix** — `M3ChatServicer`/`M3CompletionsServicer` → `ChatServicer`/
  `CompletionsServicer` is a *true* de-prefix done here (not deferred to T028a) because
  the rename was forced by the relocation; the out-of-fence scripts now import the clean
  names.
- **Test slice pulled forward** — `test_endpoint_provider`’s third case
  (`_measure_cell`, M4-sweep machinery) covered deleted code and was removed; its two
  `serve_in_process` parity cases were repointed and pass.

BC: deploy scripts now import `vllm_grpc_bench.grpc_servicers.{ChatServicer,
CompletionsServicer}`; recover the old `m3_sweep` surface via the `milestone/m*` tags.
