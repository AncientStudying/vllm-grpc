# Contract: `vllm_grpc_bench --m3` CLI

**Feature**: 015-m3-protobuf-grpc-tuning
**Path**: `tools/benchmark/src/vllm_grpc_bench/__main__.py` (extended) + `m3_sweep.py` (new orchestrator)

This contract defines the user-facing CLI entrypoint for the M3 sweep. It augments the existing `python -m vllm_grpc_bench` CLI; existing modes (corpus runners used in M1) are not touched.

## Synopsis

```text
python -m vllm_grpc_bench --m3 \
    [--axis {max_message_size,keepalive,compression,http2_framing,all}] \
    [--width {2048|4096|8192|all|<positive_integer>}] \
    [--path {embed,chat_stream,both}] \
    [--iters-per-cell N]                  (default: 30) \
    [--out-dir docs/benchmarks]           (default; report files written here) \
    [--smoke]                             (default: off; runs 1 iter/cell, no CI math, exits success on any non-error) \
    [--seed N]                            (default: 0) \
    [--p2-revision NAME]                  (P2 only; activates --frozen-channel automatically) \
    [--frozen-channel NAME]               (P2 only; required when --p2-revision is set) \
    [--reanalyze EXISTING_JSON]           (Phase A / US3; see § Reanalyze mode)
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Sweep completed; report written; no harness-level errors |
| 2 | Argument validation failed (e.g., `--p2-revision` without `--frozen-channel`) |
| 3 | At least one cell failed all 30 iterations (recorded as `not_measurable` in the report; the run still produces output but exits 3 to flag operator attention) |
| 4 | I/O error writing report |
| 1 | Unhandled exception (bug; should not occur in production paths) |

Exit codes 0 and 3 both produce a complete report; the difference is whether any cell silently failed. CI (Constitution IV) treats both as merge-eligible; operator review is the gate, not exit code.

## Behaviour

1. Constructs the cartesian product of `axis × width × path`, restricted by CLI flags. `--axis all` (default) expands to the four P1 axes. `--width` accepts the three canonical values (2048, 4096, 8192), `all` (their union), or **any positive integer** for exploratory off-canonical runs (per spec Edge Case "Embedding width above the canonical set"); off-canonical widths produce `Sample`s and `RunCohort`s flagged as `off_canonical=True` so the report can mark them as exploratory and not used as primary recommendations.
2. For each cell:
    a. Spawns a `MockEngine` with the cell's `MockEngineConfig`.
    b. Brings up `frontend.main`'s servicers in-process with the cell's `ChannelConfig.server_options`.
    c. Brings up the proxy or direct-grpc client with the cell's `ChannelConfig.client_options`.
    d. Drives `--iters-per-cell` RPCs through the appropriate path, recording one `Sample` per iteration.
    e. Tears down the channel and server (avoids cross-cell contamination).
3. Aggregates `Sample`s into `RunCohort`s; computes `Recommendation`s per axis using the SC-003 statistical rule.
4. Emits two files per run: `m3-channel-tuning.md` (human-readable) and `m3-channel-tuning.json` (machine-readable). For P2 runs, the filenames are `m3-schema-tuning.{md,json}`.
5. The JSON layout MUST match the schema captured in `data-model.md` so downstream tooling and the cross-link in `summary.md` remain stable.

## Smoke mode

`--smoke` runs exactly one iteration per cell and **does not compute CI**. It exists for CI use (`make check` in PRs that touch the bench) to catch wiring regressions cheaply. Smoke runs do not produce a `Recommendation` and do not write to `docs/benchmarks/`; they write a transient report to `bench-results/m3-smoke-<timestamp>.json` (gitignored) and exit 0 if all cells return at least one non-error sample.

## Reanalyze mode (Phase A / US3)

`--reanalyze <existing-json>` reads a previously-collected M3 sweep JSON, computes time-axis verdicts using the new metric paths (`metric="time"` for embed cohorts; `metric="ttft"` for chat_stream cohorts per FR-014), and writes a sibling `<stem>-time.json` next to the input with the new recommendations and a `p1_frozen_config_time` field paralleling `p1_frozen_config`. **No new sweeps are executed**; this is a pure data re-analysis of cohort-level statistics already present in the input JSON.

Behaviour:

1. The input JSON MUST be the FULL sweep output (with per-iteration `samples` arrays preserved) — TTFT verdicts are computed from `samples[i].time_to_first_token_seconds`. Slim JSONs (the `docs/benchmarks/` companion files that strip samples) work for the embed `metric="time"` path but produce `not_measurable` chat_stream verdicts. The full data is normally retained under `bench-results/m3-full/`.
2. Recommendations are produced via `build_recommendations(metric="time")` filtered to embed cells, concatenated with `build_recommendations(metric="ttft")` (chat_stream-only). Per FR-005 / R-12, the time-axis builder uses **immediate-predecessor M1_BASELINE pairing** in cohort run-order rather than the bytes path's "first M1_BASELINE in group" — this works around the cross-batch baseline drift documented in `research.md` R-12.
3. Per FR-005, the time-axis builder may emit a new `noise_bounded` verdict when the predecessor pairing claims a win but the win does not survive at least one alternative same-cell M1_BASELINE — the conclusion is unstable across baselines and re-measures under M4's shared-baseline harness (FR-013).
4. `p1_frozen_config_time` is computed as the union of each axis's winning config if `recommend`, else `default` for that axis. Any axis with at least one `noise_bounded` verdict falls back to `default` (we cannot freeze a config we couldn't defensibly verdict).
5. Output filename: `<stem>-time.json` next to the input. Cohort `samples` arrays are stripped from the output (slim format) to match the publishable companion JSON shape.

Exit codes for `--reanalyze`:

| Code | Meaning |
|---|---|
| 0 | Re-analysis completed; sibling JSON written |
| 3 | Input JSON not found, malformed, or has no cohorts/axes |
| 4 | I/O error writing the output JSON |

## CLI compatibility / non-goals

- The existing M1 modes of `vllm_grpc_bench` (driven by `--corpus`, `--target`, etc.) are unchanged. M3 mode is gated behind `--m3`.
- No interactive prompts; the CLI is batch-friendly for CI.
- No remote-machine support (one host per run; no SSH/RPC orchestration).

## Test obligations

- `tests/test_m3_sweep_smoke.py` MUST verify `--smoke --axis max_message_size --width 2048 --path embed` returns exit 0 and writes the expected smoke artefact.
- An argument-validation unit test MUST verify exit 2 on `--p2-revision foo` without `--frozen-channel`.
