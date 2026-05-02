# Implementation Plan: Phase 4.1 — Real Comparative Baselines (Modal)

**Branch**: `007-modal-real-baselines` | **Date**: 2026-05-02 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/007-modal-real-baselines/spec.md`

## Summary

Replace the stub-run baseline files committed in Phase 4 with real GPU-backed numbers from Modal A10G. The two endpoints (vLLM native REST and proxy → gRPC frontend) cannot run simultaneously because Modal functions are ephemeral; `bench_modal.py` orchestrates them sequentially. A new `compare_cross()` function in the harness compares the two result files after both runs complete. Three new fields on `RunMeta` (`modal_function_id`, `gpu_type`, `cold_start_s`) provide full traceability. Cold-start time is excluded from reported latency percentiles but visible in run metadata.

## Technical Context

**Language/Version**: Python 3.12 (workspace-wide)

**Primary Dependencies**:
- `modal>=0.73` — already in `[dependency-groups.dev]`; used for `modal.forward()`, `modal.Dict`, `@app.function.spawn()`
- `httpx>=0.27` — already in `tools/benchmark`; used inside both serve functions for health polling
- `vllm==0.20.0` — installed inside Modal container only; not a local dep (see ADR 0001)
- `grpcio>=1.65` — already in frontend; used inside gRPC serve function for `Health.Ping` polling
- `vllm-grpc-bench` (workspace member) — imported directly from `bench_modal.py` local entrypoint for harness calls

**Storage**:
- `modal.Dict` named `"vllm-grpc-bench-modal"` (ephemeral coordination between serve functions and local entrypoint)
- `modal.Volume` named `"vllm-grpc-model-weights"` (pre-staged model weights; read-only from this phase)
- `docs/benchmarks/` (committed baseline files; written after first successful run)

**Testing**: No new pytest tests. Manual smoke: `make bench-modal` produces all five output files with valid metric values. `ruff` + `mypy --strict` on `bench_modal.py` and the extended harness modules.

**Target Platform**: Modal A10G (NVIDIA, 24 GB VRAM, vLLM 0.20.0 / CUDA) for serve functions; macOS ARM64 (M2 Pro) for local entrypoint and proxy subprocess.

**Project Type**: One new standalone script (`scripts/python/bench_modal.py`), extensions to two harness modules (`metrics.py`, `compare.py`, `__main__.py`), one new Makefile target, five committed baseline/report files.

**Performance Goals**: Total `make bench-modal` wall-clock time ≤ 30 minutes for two cold starts + two harness runs. Offline `compare-cross` completes in under 30 seconds (SC-004).

**Constraints**:
- No proto changes (Constitution I)
- No vLLM fork (Constitution II)
- No Phase 5 streaming work or Phase 4.2+ functionality (Constitution III)
- `ruff` clean + `mypy --strict` on all new `.py` files (Constitution IV); `# type: ignore` suppressions for `modal.Dict` dynamic API are explicitly justified
- No metric selectively omitted from the comparison report (Constitution V / FR-004)
- Cold-start time excluded from per-request P50/P95/P99 but recorded in `RunMeta.cold_start_s` (FR-002)
- Both runs must use identical corpus and concurrency settings (R-006)

**Scale/Scope**: One new script (~200 lines), three extended harness module files (~100 lines added total), one new Makefile target, five benchmark/report files committed. No new workspace packages.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Proto-First | ✅ PASS | No `.proto` changes. Image build regenerates stubs from existing sources (same as Phase 3.1/3.2). |
| II. Library Dependency, Not Fork | ✅ PASS | `vllm==0.20.0` installed in Modal container via `pip_install`; no source patches. |
| III. Phase Discipline | ✅ PASS | Deliverables match `docs/PLAN.md §Phase 4.1` exactly. No Phase 5 streaming work enters this branch. |
| IV. CI is the Merge Gate | ⚠️ PARTIAL | `ruff` + `mypy --strict` on new/extended files run in CI. Full `make bench-modal` requires GPU + Modal auth and is a **manual pre-merge gate**. Consistent with Phase 3.1/3.2 precedent. CI regression check uses committed baselines (no live GPU needed). |
| V. Honest Measurement | ✅ PASS | All metrics present for both REST and gRPC; cold-start clearly separated. No metric selectively omitted. |

**Post-design re-check**: All principles pass. The `compare_cross()` function produces an honest side-by-side report with no metric filtering.

## Project Structure

### Documentation (this feature)

```text
specs/007-modal-real-baselines/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output (complete)
├── data-model.md        # Phase 1 output (complete)
├── quickstart.md        # Phase 1 output (complete)
├── contracts/           # Phase 1 output (complete)
│   ├── bench-modal-script.md
│   └── harness-cli-extension.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
scripts/
└── python/
    └── bench_modal.py              ← NEW: orchestration script (FR-001, FR-002, FR-003, FR-008)

tools/
└── benchmark/
    └── src/vllm_grpc_bench/
        ├── metrics.py              ← EXTEND: RunMeta + 3 optional fields; new CrossRunReport, CrossRunRow dataclasses
        ├── compare.py              ← EXTEND: add compare_cross() function
        └── __main__.py             ← EXTEND: add compare-cross subcommand with --result-a/--result-b flags

docs/
└── benchmarks/
    ├── phase-3-modal-rest-baseline.json   ← NEW: committed after first successful run (FR-006)
    ├── phase-3-modal-rest-baseline.md     ← NEW
    ├── phase-3-modal-grpc-baseline.json   ← NEW: committed after first successful run (FR-006)
    ├── phase-3-modal-grpc-baseline.md     ← NEW
    └── phase-3-modal-comparison.md        ← NEW: head-to-head report (FR-004, SC-002)

Makefile                                   ← EXTEND: add bench-modal target; update .PHONY
```

**No new workspace packages.** Follows the `scripts/python/` convention from Phase 3.1/3.2.

**No proxy or frontend package code changes.** The proxy is started as a subprocess by `bench_modal.py` using the existing `FRONTEND_ADDR` env var mechanism.

### bench_modal.py — Internal Structure

```text
# Modal app definition
app = modal.App("vllm-grpc-bench-modal")

# Shared constants
_VLLM_VERSION, _MODEL_PATH, _REST_PORT, _GRPC_PORT, _FUNCTION_TIMEOUT_S
_STOP_CHECK_INTERVAL_S, _ADDR_POLL_TIMEOUT_S, _DICT_NAME
_CORPUS_PATH, _CONCURRENCY  ← enforced identical for both runs

# serve_rest_for_bench() — @app.function(gpu="A10G")
#   Starts vLLM REST subprocess, polls /health, opens modal.forward(REST_PORT),
#   writes rest_addr + rest_cold_start_s to modal.Dict, blocks until rest_stop set

# serve_grpc_for_bench() — @app.function(gpu="A10G")
#   Starts gRPC frontend subprocess, polls Health.Ping, opens modal.forward(GRPC_PORT),
#   writes grpc_addr + grpc_cold_start_s to modal.Dict, blocks until grpc_stop set

# @app.local_entrypoint() main()
#   1. Run REST phase: spawn → poll addr → run harness → save → stop
#   2. Run gRPC phase: spawn → poll addr → start proxy → run harness → stop proxy → stop
#   3. compare_cross() → write comparison report
#   4. Write docs/benchmarks/ files
```

## Complexity Tracking

*(No Constitution violations — no Complexity Tracking entry required.)*
