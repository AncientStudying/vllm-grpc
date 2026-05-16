# Implementation Plan: M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation

**Branch**: `023-m6-1-1-engine-cost-instrumentation` | **Date**: 2026-05-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/023-m6-1-1-engine-cost-instrumentation/spec.md`

## Summary

Close the methodology gap M6.1 surfaced — `engine_cost_drift_warning` fired on **all three chat_stream cells** with a consistent 14–17% per-cohort spread on `engine_ttft_ms` — **before** M6.2 (token-budget axis) opens. M6.1.1 is a two-phase narrow milestone: Phase 1 instruments four named checkpoints per chat_stream RPC on both the REST and gRPC paths and runs a 6-cell × 3-cohort × n=50 mini-sweep; the magnitude-equivalence classifier (per spec FR-010, round-1 Q1) attributes the spread to either (a) measurement-window asymmetry between the REST shim and gRPC trailing-metadata anchors → `instrumentation_artifact`, (b) the engine itself seeing different first-token latencies by cohort → `channel_dependent_batching`, (c) `drift_not_reproduced`, or (d) `inconclusive`. Phase 2 acts on Phase 1's outcome: under uniform `instrumentation_artifact` the operator applies a symmetrisation code change and runs the n=100 verification sweep, which publishes fresh `chat_stream_baseline_post_symmetrisation` + `embed_baseline_post_symmetrisation` sections (round-2 Q1 / Q2) for M6.2 to anchor against; under uniform `channel_dependent_batching` Phase 2(b) updates `contracts/instrumentation.md` with the operator-facing interpretation and flips `phase_2_path = "phase_2b_documented"`; under any persistent divergence after a confirming second `--m6_1_1-diagnose` run, the harness exits code `5` with `phase_2_path = "split_required"` (heterogeneous Phase 2 inside M6.1.1 is disallowed — round-2 Q4).

**Technical approach.** Reuse M6.1's entire harness wholesale (cell × cohort × concurrency orchestration, round-robin per-c-batch sequencer, deterministic per-RPC seed mapping, M6 baseline loader, torch-pin gate, engine-cost instrumentation contract from M6). Add 10 parallel `m6_1_1_*` modules (mirroring M6.1's `m6_1_*` naming pattern) and modify 3 shared surfaces:

1. **`scripts/python/modal_bench_rest_grpc_server.py`** (the Modal server entrypoint) — instrument the REST chat_stream handler with four `perf_counter_ns()` checkpoints (`handler_entry`, `pre_engine`, `first_chunk`, `terminal_emit`) and emit them on the terminal SSE event under a `m6_1_1_timings` sub-object (FR-007). Instrument the gRPC chat_stream servicer with the same four points and emit them as trailing-metadata keys prefixed `m6_1_1_t_` (FR-008). The existing M6 instrumentation fields (`engine_ttft_ms`, `engine_tpot_ms`) MUST be preserved exactly (FR-007 / FR-008 + Edge Cases lines 110–111).
2. **`tools/benchmark/src/vllm_grpc_bench/rest_shim.py`** + the gRPC client paths — extract the 4 timing checkpoints from the wire format (SSE sub-object on REST; trailing metadata keys on gRPC) into per-RPC event records. Reuse the M6 engine_cost extraction pattern (`m6_engine_cost.py`) so the new fields land alongside the existing engine_cost trio.
3. **`tools/benchmark/src/vllm_grpc_bench/__main__.py`** — add 13 new `--m6_1_1-*` flags (`--m6_1_1-diagnose`, `--m6_1_1`, plus auxiliary flags mirroring M6.1's CLI surface per [`contracts/cli.md`](./contracts/cli.md)). `--m6_1_1` branches internally on the most recent Phase 1 classification per round-3 Q2 (Phase 2(a) sweep under `instrumentation_artifact`; Phase 2(b) doc-validation under `channel_dependent_batching`; refuse with exit code `1` otherwise).

Under Phase 2(a), if Phase 1 returned `instrumentation_artifact`, the operator additionally applies the symmetrisation code change — **the specific change is data-driven and identified by Phase 1's per-segment table**: if `seg_ab` carries the spread on one path, that path's pre-engine bracket is moved to align with the other; if `seg_bc` carries the spread (which would be `channel_dependent_batching`, not `instrumentation_artifact`), Phase 2(a) is not the correct path. The plan describes the *shape* of the symmetrisation change but not the specific edit — the spec's "diagnose-first, fix-or-document" discipline (round-1 Q3) prohibits pre-committing to either bracketing change.

Phase 1's reports are append-only via the `phase_1_runs[]` array per round-3 Q1: re-running `--m6_1_1-diagnose` reads the existing JSON, appends the new run record, and re-writes both markdown and JSON. The Phase 2 invocation (`--m6_1_1`) overwrites the report's top-level fields with the verification outcome while preserving `phase_1_runs[]`. Five deterministic exit codes (1 missing baseline / contracts heading; 2 torch pin mismatch; 3 re-run needed; 4 perturbation budget exceeded; 5 milestone split required) match the spec's hard-gate posture (round-2 Q3 + Q4).

The published JSON is a strict superset of M6.1's `engine_cost_baseline` schema (FR-022) plus two top-level sentinel-object sections (`chat_stream_baseline_post_symmetrisation` and `embed_baseline_post_symmetrisation`) following the round-2 Q1/Q2 dispatch shape — M6.2 consumers branch on `baseline_source` alone, never `run_meta.phase_2_path`.

## Technical Context

**Language/Version**: Python 3.12 (project standard; matches M5.x / M6 / M6.1 harness, frontend, proxy, and Modal app).

**Primary Dependencies**:
- `vllm==0.20.1` (real engine — `AsyncLLM(Qwen/Qwen3-8B, dtype=fp16, enable_prompt_embeds=True, max_model_len=2048, gpu_memory_utilization=0.92)` — UNCHANGED from M6.1).
- `torch==2.11.0` (CLIENT-SIDE pin, same as M6.1 — FR-003 reuses M6.1's `m6_1_torch_pin` validator; no new pin).
- `grpcio` + `grpcio-tools` (gRPC transport — UNCHANGED).
- `FastAPI` + `uvicorn` (REST shim — extended with the 4 timing checkpoints on the chat_stream handler per FR-007).
- `modal` (deployment — UNCHANGED).
- Existing `vllm_grpc_bench` harness (extended with `m6_1_1_*` modules; reuses M6.1's `m6_1_supersede`, `m6_1_torch_pin`, `m6_1_seed`, `m6_engine_cost` unchanged).
- `vllm_grpc_frontend` (UNCHANGED — neither the dispatch in `_resolve_prompt_embeds_input` nor the engine config changes under M6.1.1's instrumentation work).

**Storage**:
- Outputs: `docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}` (FR-019 + Research R-9).
- Inputs: `docs/benchmarks/m6_1-real-prompt-embeds.json` (M6.1 baseline — FR-001 hard precondition).
- Per-RPC events JSONL sidecar: `docs/benchmarks/m6_1_1-events.jsonl` (the operator passes the path via `--m6_1_1-events-sidecar-out`; defaults are documented in `contracts/cli.md`).
- Additive annotation written to `docs/benchmarks/m6_1-real-prompt-embeds.json` (`methodology_supersedence` key per FR-023) and `docs/benchmarks/m6_1-real-prompt-embeds.md` (one-line forward pointer per FR-024).
- Under Phase 2(b): additive update to `contracts/instrumentation.md` with an `m6_1_1`-keyed heading (FR-016 + round-3 Q2 validation gate).

**Testing**: `pytest` + `pytest-asyncio` (project convention). Coverage tiers:
- **Unit tests** for the FR-010 magnitude-equivalence classifier on synthetic per-segment inputs (deterministic — every output label reachable from a constructed input vector); for the FR-012 perturbation-budget gate (success + exit-code-4 paths); for the FR-017 / FR-018 re-run gate (single-run mixed / inconclusive / drift_not_reproduced → exit code 3); for the FR-017(b) split_required gate (still-divergent on second run → exit code 5); for the sentinel-object schema serialiser (round-2 Q1 / Q2); for the FR-015b embed regression check (within-5% pass + outside-5% warning paths); for the `phase_1_runs[]` append-on-re-read pattern (round-3 Q1) including the corrupted-existing-file fallback.
- **Contract tests** for the `m6_1_1_timings` sub-object on REST's SSE terminal event (existing M6 SSE fields preserved exactly — FR-007); for the `m6_1_1_t_*` trailing metadata keys on gRPC (existing M6 keys preserved — FR-008); for the JSON schema validator over the new top-level keys.
- **Integration tests** for the full Phase 1 → Phase 2(a) wire path against a fake server (one cell × one cohort × n=2 RPCs is enough to exercise the 4-checkpoint capture + extraction + per-segment delta + classifier flow end-to-end).
- **CLI smoke**: each new exit code (1, 2, 3, 4, 5) reachable from a corresponding `argparse`-only test that bypasses the Modal deployment (mirroring M6.1's `_bypass_torch_pin` pattern documented in [`feedback_smoke_warmup_seed_zero`](../../specs/022-m6-1-real-prompt-embeds/spec.md) and the round-1 memory).

**Target Platform**: Modal A10G GPU instance in `eu-west-1` (default per FR-002; overridable via `--m6_1_1-modal-region`). Driven from operator workstation (M2 Pro MBP per M5.x / M6 / M6.1 convention); operator pre-configures `modal token new` and exports `MODAL_BENCH_TOKEN`. Client-side requires `torch==2.11.0` (FR-003 — quickstart enforces).

**Project Type**: Sibling library + benchmark harness — Python monorepo with `proxy/`, `frontend/`, `client/`, `proto/`, `tools/benchmark/`, `scripts/`, `docs/benchmarks/`. M6.1.1 is a methodology-diagnosis milestone (additive to M6.1), not a library / CLI / web-service in the conventional product sense.

**Performance Goals**:
- SC-002: Phase 1 wall-clock ≤ 45 min on Modal A10G `eu-west-1` **per `--m6_1_1-diagnose` invocation** (≤ 90 min total across both runs in the fallback paths — round 3 housekeeping).
- SC-003: Under Phase 2(a) verification, all three chat_stream cells show `engine_cost_drift_warning=false` with each cohort's `engine_ttft_ms` mean within 5% of the unweighted cohort-average.
- SC-007: Phase 1 cost ≤ $2; Phase 2(a) cost ≤ $1.50. Total milestone cost (under worst-case two-run Phase 1 + Phase 2(a)) ≤ ~$5.

**Constraints**:
- **A10G GPU memory**: unchanged from M6.1 — Qwen3-8B fp16 + KV-cache headroom for c=8 chat_stream comfortably within 24 GB. No additional memory pressure from the four timing checkpoints (timestamp-recording only).
- **FR-022 strict-superset compatibility**: M6.1.1's JSON shape MUST be readable by an M6-aware consumer (the M6 `engine_cost_baseline` section is preserved; new top-level keys appear additively with sentinel-object fallback under non-Phase-2(a) outcomes).
- **FR-021 sentinel-object dispatch**: M6.2-aware consumers branch on `baseline_source` ∈ `{m6_1_1, m6_1, documented_in_contracts, not_applicable}` only — no need to read `run_meta.phase_2_path` (round-2 Q1).
- **FR-007 / FR-008 wire-format isolation**: new instrumentation fields are namespaced (`m6_1_1_timings` sub-object on REST; `m6_1_1_t_*` prefix on gRPC trailing metadata) so M6 / M6.1 instrumentation parsers continue to work unchanged when M6.1.1's server is invoked under the M6.1 dispatch path.
- **FR-010 determinism**: classifier output is reproducible by hand from the multi-point timing table; SC-010 verifies a reader can reconstruct the classification without operator narrative.
- **FR-012 perturbation budget**: ≤ 500 µs total per RPC across the four checkpoint reads. Each `perf_counter_ns()` call on Linux/macOS measures ~50 ns in practice (Research R-2); 4 calls × 50 ns = 200 ns ≪ 500 µs budget. Failure mode is mostly hypothetical but the FR-012 hard gate (exit code 4) protects against perturbation introduced by future implementation choices (e.g., adding logging at checkpoints — explicitly forbidden by Edge Cases line 108).
- **FR-002 hardware/model fidelity to M6.1**: identical Modal region, GPU, model, engine config; the harness emits a methodology section confirming each value matches `m6_1-real-prompt-embeds.json`'s `run_meta`. Any divergence triggers FR-004 (exit code 1 + `--m6_1_1-allow-engine-mismatch` escape hatch).
- **FR-029 / FR-030 / FR-031 scope discipline**: M6.1.1 MUST NOT re-compute M6.1's `supersedes_m6_under_enable_prompt_embeds` verdicts; embed cells' `engine_forward_ms` is a pass/fail regression gate (FR-015b), never a re-classification axis.

**Scale/Scope**:
- Phase 1 mini-sweep: 6 cells × 3 cohorts × n=50 measurement RPCs = 900 RPCs + 6 cells × 3 cohorts × 10 warmup = 180 warmup. Total Phase 1 RPCs ≈ 1,080 per run; ≤ ~30 min wall-clock.
- Phase 2(a) verification sweep: 6 cells × 3 cohorts × n=100 = 1,800 RPCs + 180 warmup. Total ≈ 1,980 RPCs; ~75 min wall-clock (matches M6.1's published numbers).
- Phase 2(b) doc-only path: 0 Modal RPCs.
- Per-RPC instrumentation overhead: 4 `perf_counter_ns()` reads + 4 emit operations (REST: 4 fields on terminal SSE event; gRPC: 4 trailing metadata keys). Wire-bytes overhead per RPC ~80 bytes on gRPC, ~120 bytes on REST (JSON keys + values). Negligible vs the existing engine_cost trio.
- New JSON keys + sections in M6.1.1's report (per FR-021): `phase_1_runs[]` (variable array, full per-run records; ~50-200 KB per run depending on per-cohort sample), `chat_stream_baseline_post_symmetrisation`, `embed_baseline_post_symmetrisation`, `embed_regression_check`, `multi_point_timings`, `phase_1_classifications`, `phase_2_outcome`, `phase_2_choice`, `m6_1_baseline_pointer`, `methodology_supersedence`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against the 5 principles in `.specify/memory/constitution.md` (v1.0.0):

| Principle | Status | Notes |
|---|---|---|
| **I. Proto-First** | **PASS** | M6.1.1 makes no `.proto` edits. The four new gRPC trailing-metadata keys (`m6_1_1_t_*` per FR-008) ride on the existing trailing-metadata mechanism that M6 / M6.1 already use for `engine_ttft_ms`, `engine_tpot_ms`. Trailing metadata is a transport-level construct (HTTP/2 framing handled by `grpcio`), not a `.proto` schema concept — adding keys requires no IDL change, no stub regeneration. REST is not proto-tracked; the new `m6_1_1_timings` sub-object on the terminal SSE event is a FastAPI JSON shape change confined to `scripts/python/modal_bench_rest_grpc_server.py`. |
| **II. Library Dependency, Not Fork** | **PASS** | M6.1.1 uses `vllm==0.20.1` and `torch==2.11.0` as ordinary published dependencies — identical to M6.1. No vLLM or torch source modification. The four timing checkpoints are recorded around the existing `engine.generate(...)` boundary (no instrumentation reaches inside the engine itself, which would imply patching vLLM). Under Phase 2(a)'s symmetrisation, the code change lands inside this project's harness / shim, never inside `vllm/` or `torch/`. |
| **III. Phase Discipline** | **PASS** | M6.1.1 is a canonical milestone in [`docs/PLAN.md`](../../docs/PLAN.md) (since 2026-05-15) listed as a follow-on between M6.1 and M6.2. Spec scope matches PLAN.md M6.1.1 §: same 6-cell matrix, same Qwen3-8B model, same A10G hardware, same engine config — **exactly one variable change** (add the four-checkpoint instrumentation; the optional Phase 2(a) symmetrisation is a separate edit identified by Phase 1's data, NOT a pre-committed bundle). Out-of-scope items (`max_tokens` axis → M6.2; corpus diversity → M7; additional models → M8; embed-cell classification) are explicit per FR-031–FR-034. The bound is enforced at the JSON schema level: `phase_2_path` enum is strict (`phase_2a_verified`, `phase_2b_documented`, `phase_2_pending`, `drift_not_reproduced_confirmed`, `split_required`) — round-2 Q4 disallows heterogeneous Phase 2 to prevent a multi-variable milestone close. |
| **IV. CI is the Merge Gate** | **PASS** | All M6.1.1 code changes (new harness modules under `tools/benchmark/src/vllm_grpc_bench/`, modified `__main__.py`, modified REST shim, modified Modal server entrypoint, modified gRPC chat_stream servicer if not already in `frontend/`) MUST pass `ruff check`, `ruff format --check`, `mypy --strict`, and `pytest` per [`feedback_local_lint_chain`](../../docs/benchmarks/m6_1-real-prompt-embeds.md) memory before push. New unit tests cover all 5 exit codes (1–5) and all four classifier outcomes deterministically. The `m6_1_1_perturbation` module is unit-tested for both pass and the FR-012 exit-code-4 path so the perturbation-budget gate is regression-protected. |
| **V. Honest Measurement** | **PASS** | M6.1.1 IS a methodology-diagnosis milestone. Outputs land in `docs/benchmarks/`. SC-001 mandates a deterministic classification label per chat_stream cell (no selective omission); SC-005 / FR-022 mandate that the M6.1-aware consumer's view is preserved (strict-superset compatibility); SC-006 mandates the additive `methodology_supersedence` annotation on M6.1's published JSON + markdown so the audit trail is unbroken. The verdict_buried_by_engine / mixed / inconclusive escape hatches collapse to `split_required` per FR-017(b) / FR-018 — M6.1.1 cannot smuggle a soft "we kinda fixed it" verdict into a milestone that the data does not unambiguously support. Phase 2(a)'s `embed_regression_warning` (FR-015b) is a hard gate against silent perturbation of M6.1's embed verdicts. Under Phase 2(b), `contracts/instrumentation.md` is updated with an operator-facing interpretation of per-cohort `engine_ttft_ms` differences — published as a real finding, not a workaround. |

**Result: 5/5 PASS. No violations. Complexity Tracking is empty.**

Re-check after Phase 1 design: see "Post-Design Constitution Check" at the end of this document.

## Project Structure

### Documentation (this feature)

```text
specs/023-m6-1-1-engine-cost-instrumentation/
├── plan.md                     # This file (/speckit-plan output)
├── research.md                 # Phase 0 — research items + decisions (/speckit-plan output)
├── data-model.md               # Phase 1 — entity shapes (/speckit-plan output)
├── quickstart.md               # Phase 1 — operator playbook (/speckit-plan output)
├── contracts/
│   ├── cli.md                  # M6.1.1 CLI surface (--m6_1_1-diagnose, --m6_1_1, exit codes 1–5)
│   ├── instrumentation.md      # Four-checkpoint wire format (REST m6_1_1_timings sub-object + gRPC m6_1_1_t_* trailing metadata keys)
│   └── output.md               # Published artifact shapes (Phase 1 multi-point table + Phase 2 outcomes + sentinel-object JSON schema + supersedence annotations)
├── spec.md                     # Feature spec (existing, 11 Q/A clarifications across 3 rounds)
└── tasks.md                    # /speckit-tasks output (NOT created by /speckit-plan)
```

### Source Code (repository root — extending existing layout)

M6.1.1 is an additive extension of the M6.1 harness, not a refactor. The M6.1 modules remain unchanged in their existing semantics; M6.1.1 adds 10 parallel `m6_1_1_*` modules and modifies 4 shared surfaces (`__main__`, Modal server entrypoint, REST shim, gRPC chat_stream servicer wiring).

```text
tools/benchmark/src/vllm_grpc_bench/
├── m6_1_1_types.py             # NEW — M6.1.1 dataclasses + constants (M6_1_1Cell alias for M6_1Cell, TimingCheckpoint, PerSegmentDelta, Phase1Classification literal, Phase2Path literal, BaselineSource literal, Phase1RunRecord, MultiPointTimingsAggregate, EmbedRegressionResult, ChatStreamBaselineSentinel, EmbedBaselineSentinel, M6_1_1Run, M6_1_1RunMeta; 5 exit-code constants)
├── m6_1_1_timing.py            # NEW — client-side wire-format extractors: extract `m6_1_1_timings` sub-object from REST SSE terminal event JSON; extract `m6_1_1_t_*` keys from gRPC trailing metadata; per-RPC TimingCheckpoint record assembly; per-segment delta computation per FR-009
├── m6_1_1_perturbation.py      # NEW — FR-012 perturbation-budget gate: compute total `perf_counter_ns()` overhead per RPC from the 4 checkpoint reads (server-side audit emitted alongside the checkpoints); aggregate per (cohort, cell); raise SystemExit(4) if any pair exceeds 500 µs
├── m6_1_1_classifier.py        # NEW — FR-010 magnitude-equivalence classifier: spread(engine_ttft_ms), spread(seg_ab_ms), spread(seg_bc_ms) per cell; deterministic 4-label output per chat_stream cell (drift_not_reproduced short-circuits per round-1 Q1)
├── m6_1_1_diagnose.py          # NEW — Phase 1 mini-sweep orchestrator (parallel to m6_1_smoke.py + m6_1_sweep.py): reuses M6.1's sequencer + warmup + round-robin; embed cells run at n=50 as audit-only controls (FR-011); chat_stream cells run at n=50 with the 4-checkpoint capture; reads existing M6.1.1 JSON (if present) and appends a new Phase1RunRecord to phase_1_runs[] per round-3 Q1
├── m6_1_1_phase2.py            # NEW — Phase 2 orchestrator (round-3 Q2 dispatch): reads most-recent Phase 1 classification; under uniform `instrumentation_artifact` runs the n=100 verification sweep + embed regression check + fresh baseline emission; under uniform `channel_dependent_batching` runs m6_1_1_contracts_check.validate() and flips phase_2_path; under any other state raises SystemExit(1) with an actionable message; under FR-017 / FR-018 second-run-still-divergent, writes split_required and raises SystemExit(5)
├── m6_1_1_embed_regression.py  # NEW — FR-015b regression check: per (embed cell × cohort), `engine_forward_ms` mean compared against M6.1's published mean for that pair; ±5% pass/fail; emits embed_regression_warning flag + acknowledgement bookkeeping
├── m6_1_1_contracts_check.py   # NEW — FR-016 + round-3 Q2 validator: scan `contracts/instrumentation.md` for an `m6_1_1`-keyed heading (regex match on `^## M6.1.1: `); return pass/fail with the matched line for the report's audit trail
├── m6_1_1_supersedence.py      # NEW — FR-023 + FR-024 writers: emit `methodology_supersedence` annotation on M6.1's published JSON (additive write, M6.1's other fields unchanged) + one-line forward pointer in M6.1's published markdown chat_stream verdict section; under embed_regression_acknowledged also writes per-row supersedence notes on affected `supersedes_m6_under_enable_prompt_embeds` rows
├── m6_1_1_reporter.py          # NEW — markdown + JSON writers: 6-section markdown per FR-020; sentinel-object schema for chat_stream_baseline_post_symmetrisation / embed_baseline_post_symmetrisation per round-2 Q1 / Q2; phase_1_runs[] preservation; strict-superset compatibility with M6.1's JSON consumers per FR-022
├── __main__.py                 # MODIFY — add 13 `--m6_1_1-*` flags (see contracts/cli.md): --m6_1_1-diagnose (Phase 1), --m6_1_1 (Phase 2 branching), --m6_1_1-modal-region, --m6_1_1-modal-token-env, --m6_1_1-modal-endpoint, --m6_1_1-skip-deploy, --m6_1_1-base-seed, --m6_1_1-model, --m6_1_1-m6-1-baseline, --m6_1_1-report-out, --m6_1_1-report-json-out, --m6_1_1-events-sidecar-out, --m6_1_1-allow-engine-mismatch. Mutual-exclusion with --m6_1, --m6_1-smoke, --m6, --m6-smoke, --m5_2, --m5_1, --m5, --m4, --m3.
├── rest_shim.py                # MODIFY — when receiving the chat_stream SSE response, parse the terminal event's `m6_1_1_timings` sub-object (if present) into the per-RPC event record alongside the existing engine_cost trio. Existing M6 / M6.1 paths (no `m6_1_1_timings` sub-object) UNCHANGED — the extraction is best-effort and silently skips when the sub-object is absent.
├── m6_1_rpc_driver.py          # UNCHANGED — M6.1 embed RPC builder reused unchanged. (Phase 1 + Phase 2(a) drive embed cells at the same matrix shape M6.1 used.)
├── m6_1_torch_pin.py           # UNCHANGED — torch==2.11.0 validator reused via `m6_1_1_*` imports; same FR-003 contract as M6.1.
├── m6_1_seed.py                # UNCHANGED — per-RPC deterministic seed mapping reused; M6_1_1_BASE_SEED defaults to 42, identical to M6.1.
├── m6_1_seq_len.py             # UNCHANGED — seq_len pinning reused at sweep start.
├── m6_1_supersede.py           # UNCHANGED — M6.1 verdict classifier UNREACHED by M6.1.1's flow (M6.1.1 publishes no verdict table; only diagnoses M6.1's drift).
├── m6_1_drift_check.py         # UNCHANGED — chat_stream_control_drift_warning logic reused on Phase 2(a) verification sweep (cross-checks M6.1.1's chat_stream CIs against M6.1's published CIs; an expected non-overlap fires under symmetrised instrumentation per round-1 Q2).
├── m6_engine_cost.py           # UNCHANGED — engine_cost trio parsers (REST JSON + gRPC trailing metadata) reused verbatim alongside the new m6_1_1_timing module.
├── m6_1_sweep.py               # UNCHANGED — sequencer reused via composition by m6_1_1_diagnose + m6_1_1_phase2.
└── modal_endpoint.py           # UNCHANGED — Modal endpoint discovery shared across milestones.

tools/benchmark/
└── pyproject.toml              # UNCHANGED — M6.1 already added `torch==2.11.0`; M6.1.1 reuses the existing pin (FR-003 same validator).

scripts/python/
└── modal_bench_rest_grpc_server.py  # MODIFY — REST FastAPI chat_stream handler instrumentation:
                                #   • Capture 4 `perf_counter_ns()` checkpoints; emit them as a `m6_1_1_timings` sub-object on the terminal SSE event JSON (FR-007).
                                #   • Existing M6 engine_cost fields (`engine_ttft_ms`, `engine_tpot_ms`) preserved exactly.
                                #   • REST handler is the FastAPI route on this file; gRPC servicer instrumentation lives in the frontend package (see below) — not here.

packages/frontend/src/vllm_grpc_frontend/
├── chat.py                     # MODIFY — gRPC `ChatServicer.chat_stream` instrumentation (around the existing `engine_ttft_ms` capture at `chat.py:77-84`):
                                #   • Capture 4 `perf_counter_ns()` checkpoints; emit them as trailing-metadata keys prefixed `m6_1_1_t_` (FR-008).
                                #   • Existing M6 trailing-metadata keys (`engine-ttft-ms`, `engine-tpot-ms`) preserved exactly.
├── completions.py              # MODIFY — gRPC `CompletionsServicer` embed RPC paths (around the existing captures at `completions.py:99` + `completions.py:161-170`):
                                #   • Capture the same 4 `perf_counter_ns()` checkpoints + `perturbation_audit_ns` (FR-011 audit-only control; same wire-format emission shape as chat_stream).
                                #   • Existing M6 trailing-metadata keys (`engine-forward-ms`, `engine-ttft-ms`) preserved exactly.
                                #   • POSSIBLY ADDITIONALLY MODIFIED under Phase 2(a) `instrumentation_artifact` symmetrisation if Phase 1's data identifies the gRPC bracket as the misaligned one (operator-applied AFTER Phase 1; specific edit per `contracts/instrumentation.md` § "Phase 2(a) symmetrisation shape").
└── main.py                     # UNCHANGED — engine config identical to M6.1.

docs/benchmarks/
├── m6_1-real-prompt-embeds.json    # READ-ONLY input (FR-001 baseline) + ADDITIVE annotation: top-level `methodology_supersedence` field per FR-023 (committed by M6.1.1's PR).
├── m6_1-real-prompt-embeds.md      # ADDITIVE annotation: one-line forward pointer in chat_stream verdict section per FR-024 (committed by M6.1.1's PR).
├── m6_1_1-engine-cost-instrumentation.md    # NEW — published markdown report (6 sections per FR-020).
└── m6_1_1-engine-cost-instrumentation.json  # NEW — published JSON companion (schema_version="m6_1_1.v1" per FR-021).

contracts/                      # PROJECT-LEVEL contracts directory (not the spec-feature contracts/ above):
└── instrumentation.md          # POSSIBLY MODIFY — under Phase 2(b) `channel_dependent_batching`, M6.1.1 publishes a new section keyed `## M6.1.1: Channel-Dependent Batching Effect` (FR-016 + round-3 Q2 validation gate). Under Phase 2(a) this file is NOT modified.

CLAUDE.md                       # MODIFY — update SPECKIT plan reference between markers (Phase 1 step 3 of /speckit-plan).
```

**Structure Decision**: M6.1.1 is an additive extension of M6.1, not a refactor. M6.1 modules are read by M6.1.1 (`m6_1_torch_pin`, `m6_1_seed`, `m6_1_seq_len`, `m6_1_drift_check`, `m6_engine_cost`) but never modified. The Modal server entrypoint receives the largest single change (4 new checkpoints × 2 transports + 8 wire-format keys), but the change is purely additive: every existing M6 / M6.1 instrumentation field is preserved verbatim. The 10 new `m6_1_1_*` modules mirror M6.1's `m6_1_*` naming so a reader who knows M6.1's harness can navigate M6.1.1's by the parallel-suffix convention. The post-Phase-1 symmetrisation code change (the only mandatory edit if Phase 1 returns `instrumentation_artifact`) is *not* shipped from `/speckit-plan` — Phase 1's data identifies the specific edit, preserving the spec's "diagnose-first" discipline (round-1 Q3).

## Complexity Tracking

> Empty — Constitution Check passed 5/5 with no violations.

Per the project's `feedback_thorough_clarify_cycles` memory, the spec underwent 3 rounds of clarification (11 Q/A bullets total) before this plan was written. The plan inherits those decisions verbatim. No new external dependencies are introduced — `torch==2.11.0` is reused from M6.1's pyproject pin. The single new architectural concept (the sentinel-object dispatch schema from round-2 Q1 / Q2) is contained in `m6_1_1_types.py` + `m6_1_1_reporter.py` and is opaque to M6.1's harness.

---

## Phase 0: Outline & Research

See [`research.md`](./research.md) for the 9 research items (R-1 through R-9) and their decisions.

**Output**: `research.md` with all NEEDS CLARIFICATION resolved (none in Technical Context — the 3-round spec clarification process settled them at spec time).

## Phase 1: Design & Contracts

See [`data-model.md`](./data-model.md), [`contracts/cli.md`](./contracts/cli.md), [`contracts/instrumentation.md`](./contracts/instrumentation.md), [`contracts/output.md`](./contracts/output.md), [`quickstart.md`](./quickstart.md).

Agent context update: the SPECKIT plan reference in `/Users/bsansom/projects/vllm-grpc/CLAUDE.md` between the `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers is updated as part of Phase 1 step 3 to point at this plan's path.

**Output**: `data-model.md`, `contracts/*.md`, `quickstart.md`, updated `CLAUDE.md`.

## Post-Design Constitution Check

Re-evaluated against the 5 principles after Phase 1 design artifacts were drafted:

| Principle | Status | Post-design notes |
|---|---|---|
| I. Proto-First | **PASS** | Confirmed by [`contracts/instrumentation.md`](./contracts/instrumentation.md) — no `.proto` edits in M6.1.1. The four new gRPC trailing-metadata keys (`m6_1_1_t_*`) ride on transport-level metadata. The REST SSE sub-object is a JSON shape change confined to the Modal server entrypoint. |
| II. Library Dependency, Not Fork | **PASS** | Confirmed by [`data-model.md`](./data-model.md) — M6.1.1 reuses vLLM's `enable_prompt_embeds=True` engine path unchanged. The four checkpoints sit on either side of the `engine.generate(...)` call boundary; no instrumentation reaches inside vLLM. Under Phase 2(a), the symmetrisation code change lands inside this project's harness/shim, never inside vLLM or torch. |
| III. Phase Discipline | **PASS** | Confirmed by [`contracts/cli.md`](./contracts/cli.md) + [`contracts/output.md`](./contracts/output.md) — `--m6_1_1-*` flag namespace is parallel to `--m6_1-*` / `--m6-*`; no M6.2 (max_tokens axis), M7 (corpus), or M8 (multi-model) functionality leaks in. The strict `phase_2_path` enum prohibits heterogeneous Phase 2 (round-2 Q4) at the schema level. |
| IV. CI is the Merge Gate | **PASS** | [`quickstart.md`](./quickstart.md) operator playbook includes the local-lint-chain step before any push per [`feedback_local_lint_chain`](../../specs/022-m6-1-real-prompt-embeds/checklists/requirements.md) memory. All 5 exit codes (1–5) and all 4 classifier outcomes are unit-tested. The `_bypass_torch_pin(monkeypatch)` pattern from M6.1 is reused for tests that exercise the FR-017/FR-018/FR-012 gates without triggering the torch-pin gate ahead of them. |
| V. Honest Measurement | **PASS** | [`contracts/output.md`](./contracts/output.md) mandates: all sentinel-object keys present even under non-Phase-2(a) outcomes (no silent omission); `phase_1_runs[]` accumulates the full multi-point data for both Phase 1 runs in the second-run paths (audit reproducibility per round-3 Q1); the M6.1 supersedence annotation lands in the SAME PR as the M6.1.1 publish (no out-of-band methodology change); under Phase 2(b) the `contracts/instrumentation.md` update IS the deliverable, not a workaround. The `split_required` exit code (5) ensures M6.1.1 cannot smuggle a closure verdict into a milestone the data does not unambiguously support. |

**Result: 5/5 PASS post-design. No new complexity introduced.**
