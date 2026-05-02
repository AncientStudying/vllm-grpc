# Implementation Plan: Phase 4 — Metrics and Benchmark Harness

**Branch**: `004-benchmark-harness` | **Date**: 2026-05-01 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/004-benchmark-harness/spec.md`

## Summary

Build the measurement infrastructure for this project: a standalone benchmark harness (`tools/benchmark/`) that replays a fixed request corpus against two endpoints (the proxy bridge and vLLM's native OpenAI server) head-to-head, measures latency (P50/P95/P99), wire bytes, throughput, and proxy translation time, and emits CSV/JSON reports plus a markdown comparison summary. Commit the Phase 3 non-streaming baseline. Add a GitHub Actions workflow that runs the harness against stub servers on PRs touching proxy or frontend, and posts a regression comment.

## Technical Context

**Language/Version**: Python 3.12 (workspace-wide)

**Primary Dependencies**:
- `httpx>=0.27` — async HTTP client for sending benchmark requests (already in dev group)
- `psutil>=5.9` — optional process-level CPU accounting; used if needed for extended metrics
- `pytest>=8` + `pytest-asyncio>=0.23` — test framework (already in dev group)
- `ruff>=0.4` — lint + format (already in dev group)
- `mypy>=1.10` — type-checking (already in dev group)
- No new runtime dependencies for the proxy changes (timing uses `time.perf_counter()` from stdlib)

**Storage**: Files only — `results.json`, `results.csv`, `summary.md` written per run; baseline JSON files committed to `docs/benchmarks/`.

**Testing**: pytest with `httpx.MockTransport` (or a lightweight asyncio `FakeHTTPServer`) for CI stub endpoints; unit tests for metrics, reporting, and comparison logic.

**Target Platform**: macOS ARM64 (M2 Pro, 32 GB) for live benchmarks; Linux x86_64 (GitHub Actions) for CI stub benchmarks. The harness is platform-agnostic.

**Project Type**: Standalone CLI tool (`tools/benchmark/`) added as a uv workspace member; small addition to the existing `proxy` package (timing middleware); new GitHub Actions workflow.

**Performance Goals**: Full live benchmark run (10 requests × 3 concurrency levels × 2 targets) completes in under 5 minutes on the development machine. CI smoke test completes in under 60 seconds.

**Constraints**:
- `mypy --strict` zero errors on `tools/benchmark/src` and updated `packages/proxy/src`
- `ruff` clean
- No proto changes — this phase adds no new RPCs or message types
- No Phase 5+ features (streaming, TTFT/TPOT metrics) are introduced
- The `X-Bench-Proxy-Ms` header is additive and must not break existing proxy tests
- CI baseline (`-ci-baseline.json`) must be committed before the benchmark CI workflow can detect regressions

**Scale/Scope**: One new workspace package (`vllm-grpc-bench`), one new proxy middleware module, one new GitHub Actions workflow, two new baseline files in `docs/benchmarks/`, and one `Makefile` extension.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Proto-First | ✅ PASS | No `.proto` changes in this phase; the harness communicates over HTTP REST only |
| II. Library Dependency, Not Fork | ✅ PASS | `vllm` is used only at runtime by the existing frontend; the harness has no vllm dependency |
| III. Phase Discipline | ✅ PASS | Deliverables match `docs/PLAN.md §Phase 4` exactly; no streaming metrics (Phase 5), no prompt_embeds (Phase 6) |
| IV. CI is the Merge Gate | ✅ PASS | `ruff` + `mypy --strict` + `pytest` extended to cover `tools/benchmark/src`; benchmark CI workflow is informational (PR comment) and does not block merge on its own |
| V. Honest Measurement | ✅ PASS | Central to this phase; `RunMeta.git_sha` + `hostname` baked into every results file; methodology documented in `quickstart.md`; no metric selectively omitted |

**Post-design re-check**: All principles pass. The FakeHTTPServer CI strategy avoids a live model while still exercising the harness end-to-end. The distinction between `phase-3-baseline.json` (real) and `phase-3-ci-baseline.json` (stub) is clearly documented.

## Project Structure

### Documentation (this feature)

```text
specs/004-benchmark-harness/
├── plan.md              # This file
├── research.md          # Phase 0 output (complete)
├── data-model.md        # Phase 1 output (complete)
├── quickstart.md        # Phase 1 output (complete)
├── contracts/           # Phase 1 output (complete)
│   ├── cli.md           # CLI argument contract
│   └── proxy-timing-header.md  # X-Bench-Proxy-Ms header contract
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
tools/
└── benchmark/
    ├── pyproject.toml                     ← NEW: vllm-grpc-bench workspace member
    ├── src/
    │   └── vllm_grpc_bench/
    │       ├── __init__.py                ← NEW
    │       ├── __main__.py                ← NEW: CLI entry point (argparse)
    │       ├── corpus.py                  ← NEW: loads RequestSample list from JSON
    │       ├── runner.py                  ← NEW: async request runner (httpx + asyncio)
    │       ├── metrics.py                 ← NEW: RequestResult, RunSummary, BenchmarkRun, RunMeta
    │       ├── reporter.py                ← NEW: JSON / CSV / markdown output
    │       └── compare.py                 ← NEW: ComparisonReport + regression detection
    ├── corpus/
    │   └── chat_nonstreaming.json         ← NEW: 10 fixed RequestSample fixtures
    └── tests/
        ├── __init__.py                    ← NEW
        ├── conftest.py                    ← NEW: FakeHTTPServer fixture
        ├── test_corpus.py                 ← NEW: corpus loading + validation
        ├── test_metrics.py                ← NEW: percentile calc + aggregation
        ├── test_reporter.py               ← NEW: JSON/CSV/markdown output format
        ├── test_compare.py                ← NEW: regression detection logic
        └── test_runner.py                 ← NEW: end-to-end run with FakeHTTPServer

packages/proxy/src/vllm_grpc_proxy/
├── chat_router.py                         ← EXTEND: add perf_counter timing, emit X-Bench-Proxy-Ms
└── [all other files unchanged]

packages/proxy/tests/
└── test_chat_endpoint.py                  ← EXTEND: assert X-Bench-Proxy-Ms header present in response

docs/benchmarks/
├── phase-3-baseline.json                  ← NEW: real run results (committed manually from dev machine)
├── phase-3-baseline.md                    ← NEW: real run summary (committed manually)
├── phase-3-ci-baseline.json               ← NEW: CI stub run results (committed after first CI run)
└── phase-3-ci-baseline.md                 ← NEW: CI stub run summary

.github/workflows/
└── benchmark.yml                          ← NEW: PR regression comment workflow

pyproject.toml                             ← EXTEND: add "tools/benchmark" to workspace.members

Makefile                                   ← EXTEND: add bench, bench-ci, bench-compare targets
```

**Structure Decision**: Adds `tools/benchmark` as a fourth uv workspace member. The `tools/` location (distinct from `packages/`) signals this is a developer tool, not a deployed service — consistent with the project's `tools/` convention in `docs/PLAN.md §4`. The harness has its own `pyproject.toml` to allow independent dependency management and isolated mypy type-checking.

## Complexity Tracking

> *Constitution III (Phase Discipline) requires justification for adding a new workspace member.*

| Decision | Why Needed | Simpler Alternative Rejected Because |
|----------|------------|--------------------------------------|
| New workspace member `vllm-grpc-bench` | Needs independent dep declaration (`psutil`, dev-only) and isolated mypy scope | A single-file script under `scripts/python/` cannot declare its own deps or be type-checked in isolation; the harness is multi-module with tests |
