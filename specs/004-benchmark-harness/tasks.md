# Tasks: Phase 4 — Metrics and Benchmark Harness

**Input**: Design documents from `specs/004-benchmark-harness/`
**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**Organization**: Tasks are grouped by user story. Each phase is independently completable and testable.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no blocking dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Scaffold the `vllm-grpc-bench` workspace member and extend CI to cover it.

- [X] T001 Update `pyproject.toml` root: add `"tools/benchmark"` to `[tool.uv.workspace].members`
- [X] T002 [P] Create `tools/benchmark/pyproject.toml` for package `vllm-grpc-bench`: `requires-python = ">=3.12"`, runtime deps `httpx>=0.27` and `psutil>=5.9`; `[build-system]` hatchling; packages path `src/vllm_grpc_bench`
- [X] T003 [P] Create `tools/benchmark/src/vllm_grpc_bench/__init__.py` (empty) and `tools/benchmark/src/vllm_grpc_bench/py.typed` marker
- [X] T004 [P] Create `tools/benchmark/tests/__init__.py` (empty) and `tools/benchmark/corpus/` directory (empty placeholder)
- [X] T005 [P] Extend `Makefile`: add `NATIVE_PORT ?= 8001` variable; add `bench`, `bench-ci`, `bench-compare` targets (bodies TBD in US1/US3); extend `typecheck` target to include `tools/benchmark/src`; extend `test` target to include `tools/benchmark/tests`
- [X] T006 [P] Extend `.github/workflows/ci.yml` typecheck job: add `tools/benchmark/src` to the `mypy --strict` invocation; extend test job to include `tools/benchmark/tests`

**Checkpoint**: `uv sync --all-packages` succeeds; `uv run mypy --strict tools/benchmark/src` reports "no source files found" (empty package, zero errors). ✅

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Request corpus and data-model types that every user story depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T007 Create `tools/benchmark/corpus/chat_nonstreaming.json` — JSON array of 10 `RequestSample` objects: 3 short-prompt (1–2 sentence), 4 medium-prompt (paragraph), 3 long-prompt (3+ paragraphs); all with `"model": "Qwen/Qwen3-0.6B"`, `"max_tokens": 10`, `"temperature": 0.0`, `"seed": 42`; IDs `sample-001` through `sample-010`
- [X] T008 [P] Implement `tools/benchmark/src/vllm_grpc_bench/corpus.py`: `RequestSample` dataclass (fields per data-model.md); `load_corpus(path: Path) -> list[RequestSample]` that reads JSON file, validates minimum one sample present, raises `ValueError` on empty corpus
- [X] T009 [P] Implement `tools/benchmark/src/vllm_grpc_bench/metrics.py`: all dataclasses from data-model.md (`RequestResult`, `RunSummary`, `BenchmarkRun`, `RunMeta`, `ComparisonReport`, `RegressionEntry`); helper `_percentile(values: list[float], p: float) -> float | None` (returns `None` if list empty); `compute_summaries(results: list[RequestResult]) -> list[RunSummary]` grouping by `(target, concurrency)` and computing all P50/P95/P99 fields; `build_run_meta(config: BenchmarkConfig) -> RunMeta` capturing timestamp, git SHA from subprocess, hostname
- [X] T010 [P] Write `tools/benchmark/tests/test_corpus.py`: test `load_corpus()` with valid 10-sample fixture, with empty array (expect ValueError), with malformed JSON (expect error), verify `RequestSample` fields match expected values
- [X] T011 [P] Write `tools/benchmark/tests/test_metrics.py`: test `_percentile()` with empty list (None), single value (value), sorted/unsorted lists; test `compute_summaries()` — all-success results produce non-None P50, all-error results produce None latencies, `proxy_ms` is None when no header; test `build_run_meta()` populates all required fields

**Checkpoint**: `uv run pytest tools/benchmark/tests/test_corpus.py tools/benchmark/tests/test_metrics.py -v` passes with zero errors. ✅

---

## Phase 3: User Story 1 — Run Head-to-Head Benchmark (Priority: P1) 🎯 MVP

**Goal**: A developer runs a single command and gets a head-to-head report comparing proxy bridge vs. native server across all five metric categories.

**Independent Test**: `make bench PROXY_URL=http://localhost:8000 NATIVE_URL=http://localhost:8001` produces `bench-results/results.json`, `results.csv`, and `summary.md` in under 5 minutes. The markdown summary includes rows for latency P50/P95/P99, wire bytes, throughput, and proxy translation time, with a Δ column.

- [X] T012 [P] [US1] Create `tools/benchmark/tests/conftest.py` with `fake_http_server` pytest fixture: lightweight asyncio HTTP server (use `httpx.MockTransport` wrapping an async handler, or `asyncio.start_server`) that returns a fixed pre-recorded OpenAI-format JSON response for any `POST /v1/chat/completions`; optionally emits `X-Bench-Proxy-Ms: 1.500` header when `include_proxy_header=True` (configurable via fixture parameter); default response delay of 5 ms
- [X] T013 [P] [US1] Implement `tools/benchmark/src/vllm_grpc_bench/runner.py`: `run_target(target: Literal["proxy", "native"], url: str, samples: list[RequestSample], concurrency: int, timeout: float) -> list[RequestResult]` — uses `httpx.AsyncClient`, issues `concurrency` concurrent `POST /v1/chat/completions` requests via `asyncio.gather()`, records `time.perf_counter()` around each individual call for `latency_ms`, measures `request_bytes` from serialized JSON body, reads `response_bytes` from response body, reads `X-Bench-Proxy-Ms` header into `proxy_ms` (None if absent), sets `success=False` and captures `error` on non-2xx or timeout
- [X] T014 [P] [US1] Implement `tools/benchmark/src/vllm_grpc_bench/reporter.py`: `write_json(run: BenchmarkRun, output_dir: Path) -> Path` writes `results.json`; `write_csv(run: BenchmarkRun, output_dir: Path) -> Path` writes `results.csv` with columns `target,concurrency,sample_id,latency_ms,request_bytes,response_bytes,proxy_ms,success`; `write_summary_md(run: BenchmarkRun, output_dir: Path) -> Path` writes `summary.md` with one row per `(metric, concurrency)` showing proxy value, native value, and Δ = `(proxy − native) / native` formatted as a percentage
- [X] T015 [US1] Implement `tools/benchmark/src/vllm_grpc_bench/__main__.py`: argparse CLI with `run` (default) and `compare` subcommands; `run` wires `BenchmarkConfig` from CLI flags (per `contracts/cli.md`) through `load_corpus()` → `run_target()` (for each target and concurrency level) → `compute_summaries()` → `write_json()` + `write_csv()` + `write_summary_md()`; exits with code 3 on endpoint-unreachable errors, code 2 on bad arguments
- [X] T016 [US1] Write `tools/benchmark/tests/test_runner.py`: uses `fake_http_server` fixture; test `run_target()` with `include_proxy_header=True` — verify all `RequestResult` have non-None `latency_ms`, correct `request_bytes` (matches serialized sample), non-None `response_bytes`, non-None `proxy_ms`; test with `include_proxy_header=False` — verify `proxy_ms` is None; test concurrency=4 — verify 4 results returned per sample
- [X] T017 [P] [US1] Write `tools/benchmark/tests/test_reporter.py`: unit tests with a synthetic `BenchmarkRun` (no server needed); verify `results.json` is valid JSON matching `BenchmarkRun` schema fields; verify `results.csv` has expected column names and one data row per result; verify `summary.md` contains "proxy" and "native" strings and a Δ column header
- [X] T018 [US1] Extend `packages/proxy/src/vllm_grpc_proxy/chat_router.py`: add `time.perf_counter()` timestamps `t0` (before `openai_request_to_proto(req)`) and `t1` (after), then `t2` (before `proto_response_to_openai_dict(...)`) and `t3` (after); compute `proxy_ms = (t1 - t0 + t3 - t2) * 1000`; add `headers={"X-Bench-Proxy-Ms": f"{proxy_ms:.3f}"}` to the `JSONResponse(...)` call; apply to successful responses only (2xx path)
- [X] T019 [US1] Extend `packages/proxy/tests/test_chat_endpoint.py`: add assertion that a successful `POST /v1/chat/completions` response includes `X-Bench-Proxy-Ms` header; assert the value is parseable as a positive float; ensure existing test assertions still pass

**Checkpoint**: `uv run pytest tools/benchmark/tests/ packages/proxy/tests/ -v` passes. ✅

---

## Phase 4: User Story 2 — Capture and Commit Phase 3 Baseline (Priority: P2)

**Goal**: Phase 3 non-streaming benchmark numbers are committed to the repository as the permanent reference baseline.

**Independent Test**: `docs/benchmarks/phase-3-baseline.json` exists, is valid JSON, and contains non-empty `summaries` and `meta.git_sha` fields. `docs/benchmarks/phase-3-baseline.md` exists and contains a populated comparison table.

- [X] T020 [US2] Complete `Makefile` `bench` target body: `bench` should run `uv run python -m vllm_grpc_bench --proxy-url http://localhost:$(PROXY_PORT) --native-url http://localhost:$(NATIVE_PORT) --output-dir bench-results`; run `make bench` locally with both servers running and verify the run completes in under 5 minutes and all three output files are written to `bench-results/`
- [ ] T021 [US2] Commit real-run baseline: copy `bench-results/results.json` to `docs/benchmarks/phase-3-baseline.json`; copy `bench-results/summary.md` to `docs/benchmarks/phase-3-baseline.md`; commit both files with message `[Bench] Add Phase 3 non-streaming benchmark baseline` (requires live vLLM + GPU)
- [X] T022 [US2] Complete `Makefile` `bench-ci` target body and commit CI baseline: `bench-ci` should start two `FakeHTTPServer` instances (one at localhost:8900, one at localhost:8901) and run the harness against them, writing to `bench-ci-results/`; run `make bench-ci` to produce CI baseline results; copy `bench-ci-results/results.json` to `docs/benchmarks/phase-3-ci-baseline.json`; copy `bench-ci-results/summary.md` to `docs/benchmarks/phase-3-ci-baseline.md`; commit both files with message `[Bench] Add Phase 3 CI stub benchmark baseline`

**Checkpoint**: `docs/benchmarks/phase-3-ci-baseline.json` committed. `python -m vllm_grpc_bench compare docs/benchmarks/phase-3-ci-baseline.json docs/benchmarks/phase-3-ci-baseline.json` exits code 0. ✅

---

## Phase 5: User Story 3 — Automated Regression Detection on PRs (Priority: P3)

**Goal**: Pull requests touching proxy or frontend code automatically receive a benchmark comparison comment showing any performance changes against the committed CI baseline.

**Independent Test**: Open a sample PR modifying a comment in `packages/proxy/src/vllm_grpc_proxy/__init__.py`; the `benchmark.yml` workflow runs and posts a PR comment containing a comparison table and a note that CI results use a stub backend.

- [X] T023 [P] [US3] Implement `tools/benchmark/src/vllm_grpc_bench/compare.py`: `compare(baseline: BenchmarkRun, new_run: BenchmarkRun, threshold: float) -> ComparisonReport` — iterates `RunSummary` pairs matched by `(target, concurrency)`, computes `delta_pct = (new - baseline) / baseline` for each non-None metric field, creates `RegressionEntry` for any `delta_pct > threshold`; `has_regression = len(regressions) > 0`; wire `compare` subcommand in `__main__.py`: loads two JSON files, calls `compare()`, prints markdown table of regressions to stdout, exits code 1 if `has_regression`
- [X] T024 [P] [US3] Write `tools/benchmark/tests/test_compare.py`: test with identical baseline and new run → no regressions, exit code 0; test with one metric 11% worse → one regression, exit code 1; test with one metric 9% worse → no regression (below threshold); test with metric present in baseline but absent in new run → no regression (None fields skipped); test `has_regression=False` when all improvements (negative Δ)
- [X] T025 [US3] Create `.github/workflows/benchmark.yml`: trigger `on: pull_request` with `paths: ["packages/proxy/**", "packages/frontend/**"]`; steps: checkout, setup-uv, `uv sync --all-packages`, make proto, start two FakeHTTPServer processes (`python -m vllm_grpc_bench.fake_server --port 8900 &` and `--port 8901 &`), wait for ports to be ready, run `python -m vllm_grpc_bench --proxy-url http://localhost:8900 --native-url http://localhost:8901 --output-dir bench-ci-results`, run `python -m vllm_grpc_bench compare docs/benchmarks/phase-3-ci-baseline.json bench-ci-results/results.json > comparison.md || true`, post PR comment via `actions/github-script` with the comparison.md content plus header "**Benchmark CI** (stub backend)" and sentinel `<!-- benchmark-ci-comment -->`; upsert comment (find existing by sentinel, update or create)
- [X] T026 [US3] Add `fake_server` entry point to `tools/benchmark/src/vllm_grpc_bench/fake_server.py`: standalone asyncio HTTP server that accepts `--port` CLI arg and serves the same pre-recorded OpenAI JSON response as the `conftest.py` fixture; used by `benchmark.yml` and the `bench-ci` Makefile target
- [ ] T027 [US3] Validate `benchmark.yml` by opening a draft PR that modifies a comment in `packages/proxy/src/vllm_grpc_proxy/__init__.py`; confirm the benchmark workflow runs and posts a comment; close the draft PR (requires GitHub Actions, deferred to live validation)

**Checkpoint**: `make bench-compare BASELINE=docs/benchmarks/phase-3-ci-baseline.json RESULTS=bench-ci-results/results.json` exits 0 with no regressions. ✅

---

## Phase 6: User Story 4 — Harness Extensibility (Priority: P4)

**Goal**: A developer can follow the written guide in `quickstart.md` to add a new metric in under 30 minutes.

**Independent Test**: Follow the extension guide steps 1–6 to add `response_tokens` (parsed from the response JSON body's `usage.completion_tokens` field) as a new metric; run `make bench-ci` and verify `response_tokens` appears in the CSV and summary; revert.

- [X] T028 [US4] Validate the extension guide by following `specs/004-benchmark-harness/quickstart.md §6 "Add a New Metric"`: add `response_tokens: int | None` to `RequestResult` in `metrics.py`; populate it in `runner.py` by parsing `response_body_json["usage"]["completion_tokens"]`; add `response_tokens_mean: float | None` to `RunSummary` and compute it in `compute_summaries()`; add it to the CSV writer and markdown table in `reporter.py`; write a test for the new field in `test_metrics.py`; run `make bench-ci` and confirm `response_tokens` appears in the output; then revert all changes (the metric itself is a validation exercise, not a Phase 4 deliverable)

**Checkpoint**: Extension guide works as written. Revert confirmed (`git diff` clean after revert). ✅

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Verify full-workspace quality gates, documentation accuracy, and end-to-end timing SLO.

- [X] T029 Run `make check` (ruff + mypy + pytest) across the full workspace including `tools/benchmark/` and confirm zero lint errors, zero type errors, zero test failures
- [X] T030 [P] Run `make bench` locally with both servers running and confirm total elapsed time is under 5 minutes; run `make bench-ci` and confirm it completes in under 60 seconds; record both times in a code comment at the top of `tools/benchmark/src/vllm_grpc_bench/__main__.py`
- [X] T031 [P] Review `README.md` and add a one-line reference to the `bench` Makefile target under the developer commands section if onboarding instructions reference Make targets

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Requires Phase 1 complete (workspace member must exist before installing corpus/metrics)
- **Phase 3 (US1)**: Requires Phase 2 complete (corpus and metrics dataclasses must exist)
- **Phase 4 (US2)**: Requires Phase 3 complete (`make bench` target + runner + reporter fully implemented)
- **Phase 5 (US3)**: Requires Phase 4 complete (CI baseline must be committed before regression detection can function)
- **Phase 6 (US4)**: Requires Phase 3 complete (harness code structure must exist to validate extensibility)
- **Phase 7 (Polish)**: Requires Phases 1–6 complete

### User Story Dependencies

- **US1 (P1)**: Can start after Phase 2 — no dependencies on other user stories
- **US2 (P2)**: Depends on US1 complete — needs `make bench` to run a real benchmark
- **US3 (P3)**: Depends on US2 complete — needs committed CI baseline to compare against
- **US4 (P4)**: Depends on US1 complete — needs harness code structure to validate extensibility

### Within Each Phase

- All tasks marked `[P]` within a phase can run in parallel
- Tasks without `[P]` depend on same-phase `[P]` tasks where noted in description
- Proxy changes (T018–T019) can run in parallel with harness development (T012–T017) since they touch different packages

---

## Parallel Opportunities

```bash
# Phase 1: All setup tasks run in parallel
T002 tools/benchmark/pyproject.toml
T003 __init__.py + py.typed
T004 tests/__init__.py + corpus/
T005 Makefile targets
T006 ci.yml extensions

# Phase 2: Both implementations + both test files in parallel
T008 corpus.py
T009 metrics.py
T010 test_corpus.py
T011 test_metrics.py

# Phase 3: Runner, reporter, conftest, and proxy changes in parallel
T012 conftest.py (FakeHTTPServer)
T013 runner.py
T014 reporter.py
T018 proxy chat_router.py (X-Bench-Proxy-Ms)

# Phase 5: compare.py, tests, and fake_server.py in parallel
T023 compare.py + __main__ compare subcommand
T024 test_compare.py
T026 fake_server.py
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T006)
2. Complete Phase 2: Foundational — corpus + data model (T007–T011)
3. Complete Phase 3: US1 — end-to-end benchmark run (T012–T019)
4. **STOP and VALIDATE**: Run `make bench` against live servers, verify report is produced
5. Baseline and automation follow in US2–US3

### Incremental Delivery

1. Setup + Foundational → workspace compiles, tests pass
2. US1 → `make bench` produces a real head-to-head report (MVP!)
3. US2 → Phase 3 baseline committed, permanent reference established
4. US3 → PRs automatically get regression comments
5. US4 → extensibility validated, harness is future-proof

### Parallel Team Strategy (single developer)

Because all Phase 3 tasks touch different files (`conftest.py`, `runner.py`, `reporter.py`, `chat_router.py`), they can be batched into a single AI coding session and implemented as a group, then validated together.

---

## Notes

- `[P]` tasks touch different files and have no inter-task dependencies within the same phase
- Each checkpoint is an explicit gate: do not proceed to the next phase until the checkpoint passes
- The proxy `X-Bench-Proxy-Ms` header (T018) is additive — existing proxy tests should need only an assertion extension (T019), not a rewrite
- The `fake_server.py` module (T026) doubles as both a CI server and the `bench-ci` local stub server; build it before `benchmark.yml` to keep T025 clean
- The CI baseline files must be committed (T022) before `benchmark.yml` can perform regression comparison; if they don't exist, the compare step exits cleanly per FR-012
- T021 (real-run baseline) and T027 (live GitHub Actions PR validation) require live infrastructure (GPU + GitHub Actions) and are deferred to live validation by the developer
