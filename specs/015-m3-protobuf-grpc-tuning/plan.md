# Implementation Plan: M3 — Protobuf & gRPC Tuning

**Branch**: `015-m3-protobuf-grpc-tuning` | **Date**: 2026-05-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/015-m3-protobuf-grpc-tuning/spec.md`

## Summary

M3 produces defensible wire-size and decode-time numbers for two tuning axes — gRPC channel-level settings (P1) and protobuf message-shape changes (P2) — driven by a CPU-only mock vLLM stand-in with configurable embedding width (canonical: 2048, 4096, 8192). P2 is gated on all four P1 channel axes (`max_message_size`, keepalive, compression, HTTP/2 framing) having a recorded outcome. Wins are defined statistically: a recommendation must exceed the upper bound of the 95% confidence interval of the M1-baseline measurement at the same workload, which forces repeated runs per cell. Streaming workloads use the M1 prompt corpus augmented with at least one long-stream synthetic prompt so keepalive and HTTP/2 framing regressions are observable. Every recommendation cites cloned grpcio or vLLM source via the M2 ground-truth workflow.

The technical approach reuses the existing uv workspace (proxy + frontend + client + bench tools): channel options are made injectable on both server (`grpc.aio.server`) and client (`grpc.aio.insecure_channel`) sides; a new `MockEngine` is added under `tools/benchmark/` exposing the slice of the vLLM `engine` interface the existing servicers consume; and a new benchmark mode (`vllm_grpc_bench --m3`) drives the four-axis sweep at three canonical embedding widths with enough repetitions to estimate the per-cell 95% CI. The published M3 report lands under `docs/benchmarks/m3-*` in the same JSON+markdown format the M1 summary already uses.

## Technical Context

**Language/Version**: Python 3.12 (`requires-python = ">=3.12,<3.13"` in `pyproject.toml`)
**Primary Dependencies**: `grpcio==1.80.0` (pinned in `[dependency-groups] graph-targets`), `vllm` 0.20.1 on Linux / `vllm-metal` 0.2.0 on macOS (used only for type-shape parity, not invoked by the mock), `protobuf` (transitive via grpcio-tools), `FastAPI` (proxy), `httpx` (bench client), `numpy` (mock embedding tensors and CI math)
**Storage**: N/A on the runtime path. Benchmark results land as JSON under `docs/benchmarks/` (committed); raw per-iteration timing arrays land transiently under `bench-results/` (gitignored)
**Testing**: `pytest` for unit and integration tests (`make check` runs the full suite — current baseline is 145 passed, 4 skipped per the M2 audit). New M3 tests follow the existing pattern in `packages/*/tests/` and `tools/benchmark/tests/`
**Target Platform**: macOS (Apple Silicon M2/M3) and Linux x86-64, both CPU-only. Per the M3 milestone framing, GPU is removed from the loop; the mock model is dummy-weighted so no vLLM execution happens
**Project Type**: Python `uv` workspace with multiple packages — `packages/{client,frontend,gen,proxy}` and `tools/benchmark`. M3 adds work to `tools/benchmark` and small surgical changes to `packages/{client,frontend,proxy}` to make channel options injectable
**Performance Goals**: M3 *establishes* performance numbers; it does not target a specific p95 or throughput. The empirical questions M3 answers (per spec SC-001 to SC-005) are: which channel axis settings reduce wire bytes or decode time vs. M1 baseline beyond the 95% CI of the baseline measurement, and at what `hidden_size` does the default `max_message_size` first become binding for the embed path
**Constraints**:
- All four channel axes (`max_message_size`, keepalive, compression, HTTP/2 framing) must each have a recorded outcome before P2 begins (FR-008)
- Win threshold = exceed upper bound of 95% CI of M1 baseline at same workload (SC-003)
- Streaming workload = M1 corpus + ≥1 long-stream synthetic prompt (FR-011)
- Constitution I (Proto-First): P2 schema candidates must be defined as `.proto` edits with `make proto` regenerating stubs; no hand-written equivalents
- Constitution V (Honest Measurement): no metric may be selectively omitted; "no winner found" must be reported with supporting numbers (already reflected in spec SC-003 / FR-008)
**Scale/Scope**:
- 3 canonical embedding widths × 2 paths (embed + streaming chat) × 4 channel axes × ≥2 configurations per axis = ~48 P1 cells, multiplied by repetition count needed to estimate 95% CI (target n≥30 per cell — see research.md)
- ≥1 P2 proto candidate measured at hidden_size 4096 (per AS3)
- Total expected M3 runtime budget: bounded by CPU only, target ≤4 hours for the full P1 sweep so iteration is not painful

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | M3 alignment | Notes |
|-----------|--------------|-------|
| **I. Proto-First** | ✅ Pass | P1 (channel-level) does not touch `.proto` files. P2 schema candidates are explicit `.proto` edits regenerated via `make proto`. No hand-written stubs. |
| **II. Library Dependency, Not Fork** | ✅ Pass | M3 adds a `MockEngine` that imitates the slice of vLLM the project's servicers consume; it does **not** vendor or patch vLLM. The real vLLM dependency is preserved in `pyproject.toml`. |
| **III. Phase Discipline** | ✅ Pass | M3 deliverables match the README "Milestone 3 — Protobuf & gRPC Tuning" section. The hygiene task that was originally bundled in the spec input was confirmed already-landed in M2 and removed from M3 scope. No M4/M5 functionality is being pulled forward. |
| **IV. CI is the Merge Gate** | ✅ Pass | New code is exercised by unit + integration tests; `make check` is the merge gate. M3 tests must run under CPU-only with the mock engine, so they're CI-eligible (unlike M1's GPU-bound benchmarks which were Modal-only). |
| **V. Honest Measurement** | ✅ Pass — *strengthened* | The 95%-CI win threshold (SC-003) and the explicit "no winner found / not measurable" recordable outcomes (FR-008) are the most rigorous reading of "honest measurement" the project has codified. M3 cannot quietly omit a non-result. |

**Gate result**: ✅ Pass on initial check. No complexity-tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/015-m3-protobuf-grpc-tuning/
├── plan.md              # This file
├── research.md          # Phase 0 — channel options, CI methodology, mock-engine surface
├── data-model.md        # Phase 1 — ChannelConfig, MockEngineConfig, BenchmarkRun, etc.
├── quickstart.md        # Phase 1 — how a contributor reproduces the M3 sweep locally
├── contracts/
│   ├── mock-engine-interface.md     # The vLLM-engine slice the mock must satisfy
│   └── m3-bench-cli.md              # `vllm_grpc_bench --m3` CLI signature & exit codes
├── checklists/
│   └── requirements.md              # Created in /speckit-specify
└── tasks.md             # Created by /speckit-tasks (NOT this command)
```

### Source Code (repository root)

```text
proto/vllm_grpc/v1/
├── chat.proto                       # P2: candidate edits land here (packed scalars, oneof layout)
├── completions.proto                # P2: candidate edits land here (streaming chunk granularity)
└── health.proto                     # untouched

packages/
├── frontend/src/vllm_grpc_frontend/
│   ├── main.py                      # MODIFIED: grpc.aio.server() now takes options=ChannelConfig.server_options()
│   ├── chat_servicer.py             # untouched (mock engine satisfies the same interface)
│   └── completions_servicer.py      # untouched
├── proxy/src/vllm_grpc_proxy/
│   └── grpc_client.py               # MODIFIED: insecure_channel() now takes options=ChannelConfig.client_options()
├── client/src/vllm_grpc_client/
│   └── client.py                    # MODIFIED: same — direct-grpc client honours ChannelConfig
├── gen/                             # auto-regenerated when P2 lands
└── proxy, frontend, client tests    # MODIFIED: per-package unit tests for the new options plumbing

tools/benchmark/
├── src/vllm_grpc_bench/
│   ├── __main__.py                  # MODIFIED: add `--m3` mode that drives the channel-axis sweep
│   ├── runner.py                    # MODIFIED: per-cell repetition + 95%-CI accumulator
│   ├── reporter.py                  # MODIFIED: M3 report layout (per-cell CI, axis-by-axis)
│   ├── mock_engine.py               # NEW: dummy-weighted vLLM stand-in (configurable hidden_size)
│   ├── channel_config.py            # NEW: ChannelConfig dataclass + named presets (M1-baseline, candidates per axis)
│   ├── ci.py                        # NEW: 95%-CI estimator (Welch's, scipy-free numpy implementation)
│   └── m3_sweep.py                  # NEW: orchestrates the four-axis × three-width × two-path sweep
├── corpus/
│   ├── chat_nonstreaming.json       # untouched
│   ├── completions_text.json        # untouched
│   ├── completions_embeds/          # untouched
│   └── m3_long_stream.json          # NEW: ≥1 long-stream synthetic prompt (FR-011)
└── tests/
    ├── test_mock_engine.py          # NEW
    ├── test_channel_config.py       # NEW
    ├── test_ci.py                   # NEW
    └── test_m3_sweep_smoke.py       # NEW: 1-iteration smoke run, no real measurement

docs/benchmarks/
├── summary.md                       # MODIFIED: cross-link to M3 report; M3 numbers added to comparison table
├── m3-channel-tuning.md             # NEW: P1 report — per-axis, per-width, per-path
├── m3-channel-tuning.json           # NEW: machine-readable P1 results
├── m3-schema-tuning.md              # NEW: P2 report (deferred until P1 closes)
└── m3-schema-tuning.json            # NEW: machine-readable P2 results
```

**Structure Decision**: Reuse the existing `uv` workspace and the `tools/benchmark` package (which already houses `runner.py`, `reporter.py`, `corpus.py`, `metrics.py`, and a `fake_server.py`). The mock engine is added under `tools/benchmark/src/vllm_grpc_bench/mock_engine.py` rather than creating a new top-level package because (a) it is exclusively a benchmark fixture, (b) `tools/benchmark` already has the right `pyproject.toml` and test scaffolding, and (c) keeping the mock close to the benchmark prevents it from being mistaken for a production engine. Channel options become injectable in `packages/{frontend,proxy,client}` via a single `ChannelConfig` dataclass also exported from `tools/benchmark` (the canonical home, since the bench is the sole consumer of non-default channel configs). The M1 report gets a cross-link rather than rewrites; M3's numbers stand alongside as a peer report.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No constitution violations. Table omitted.
