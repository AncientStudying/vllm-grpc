# Tasks: Phase 4.1 — Real Comparative Baselines (Modal)

**Input**: Design documents from `specs/007-modal-real-baselines/`
**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**Organization**: Tasks are grouped by user story. Each phase is independently completable and testable.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no blocking dependencies)
- **[Story]**: Which user story this task belongs to (US1–US3)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the new Makefile target so the bench-modal command is available before any code is written.

- [X] T001 Add `bench-modal` target to `Makefile`: `uv run --with modal modal run scripts/python/bench_modal.py`; extend `.PHONY` line to include `bench-modal`

**Checkpoint**: `make bench-modal` fails with "No module named bench_modal" (expected — script doesn't exist yet). `make check` still passes unchanged.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Extend the harness data model with Modal-specific fields and the new cross-run report types. All user story work depends on this phase.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 [P] Extend `tools/benchmark/src/vllm_grpc_bench/metrics.py`:
  - Add three optional fields to `RunMeta` dataclass (after existing fields, default `None`): `modal_function_id: str | None = None`, `gpu_type: str | None = None`, `cold_start_s: float | None = None`
  - Update `build_run_meta()` to accept and pass through these three keyword args with `None` defaults
  - Add `CrossRunRow` dataclass: fields `metric: str`, `concurrency: int`, `value_a: float | None`, `value_b: float | None`, `delta_pct: float | None`
  - Add `CrossRunReport` dataclass: fields `label_a: str`, `label_b: str`, `rows: list[CrossRunRow]`, `meta_a: RunMeta`, `meta_b: RunMeta`
  - (Per `specs/007-modal-real-baselines/data-model.md §Modified Entities` and `§New Entities`)

- [X] T003 [P] Update `_deserialize_run()` in `tools/benchmark/src/vllm_grpc_bench/__main__.py`:
  - Change the three new `RunMeta` fields to use `.get()`: `modal_function_id=meta_d.get("modal_function_id")`, `gpu_type=meta_d.get("gpu_type")`, `cold_start_s=float(v) if (v := meta_d.get("cold_start_s")) is not None else None`
  - Existing `results.json` files without these keys must still deserialize without error

**Checkpoint**: `uv run mypy --strict tools/benchmark/src` passes with zero errors. Existing `tools/benchmark/tests/` test suite still passes (`uv run pytest tools/benchmark/tests -v`).

---

## Phase 3: User Story 1 — Run End-to-End GPU Benchmarks with One Command (Priority: P1) 🎯 MVP

**Goal**: `make bench-modal` runs both REST and gRPC Modal deployments sequentially, collects harness results, and writes all five output files with no manual steps between them.

**Independent Test**: Run `make bench-modal` with valid Modal credentials. Verify that `docs/benchmarks/phase-3-modal-rest-baseline.json`, `phase-3-modal-grpc-baseline.json`, and `phase-3-modal-comparison.md` are all created with valid, non-zero metric values and that no manual step was required between the REST and gRPC runs.

- [X] T004 [P] [US1] Add `compare_cross(run_a: BenchmarkRun, run_b: BenchmarkRun, label_a: str, label_b: str) -> CrossRunReport` to `tools/benchmark/src/vllm_grpc_bench/compare.py`:
  - Build a lookup of `run_a` summaries by concurrency (ignoring `target` field)
  - For each concurrency level in `run_b` summaries, find the matching `run_a` summary
  - Extract metrics per the table in `data-model.md §CrossRunRow`: `latency_p50/p95/p99_ms`, `throughput_rps`, `request_bytes_mean`, `response_bytes_mean` — from the dominant target of each run (`native` for REST run, `proxy` for gRPC run)
  - Compute `delta_pct = (value_b - value_a) / value_a` where both values are non-None and `value_a != 0`; otherwise `None`
  - Return `CrossRunReport(label_a=label_a, label_b=label_b, rows=[...], meta_a=run_a.meta, meta_b=run_b.meta)`

- [X] T005 [P] [US1] Add `write_cross_run_md(report: CrossRunReport, output_path: Path) -> Path` to `tools/benchmark/src/vllm_grpc_bench/reporter.py`:
  - Write a markdown document with: title line, run metadata section (label, timestamp, git_sha, hostname, gpu_type, cold_start_s for each run), then one table per concurrency level with columns `Metric | {label_a} | {label_b} | Δ`
  - All six metrics must appear in each table (per FR-004 — no metric selectively omitted); if a value is `None`, write `—`
  - `delta_pct` formatted as `+12.3%` / `-5.1%` / `—`
  - Returns `output_path` after writing

- [X] T006 [US1] Create `scripts/python/bench_modal.py` with module-level constants and shared Modal infrastructure:
  - Copy module-level constants from `contracts/bench-modal-script.md §Module-Level Constants`: `_VLLM_VERSION`, `_MODEL_PATH`, `_REST_PORT`, `_GRPC_PORT`, `_FUNCTION_TIMEOUT_S`, `_STOP_CHECK_INTERVAL_S`, `_ADDR_POLL_TIMEOUT_S`, `_DICT_NAME`, `_CORPUS_PATH`, `_CONCURRENCY`
  - Define `app = modal.App("vllm-grpc-bench-modal")`
  - Define `_MODEL_VOLUME = modal.Volume.from_name("vllm-grpc-model-weights", create_if_missing=False)`
  - Define `_rest_image`: `modal.Image.debian_slim(python_version="3.12").pip_install(f"vllm=={_VLLM_VERSION}", "httpx>=0.27")` (mirrors `modal_vllm_rest.py`)
  - Define `_grpc_image`: same image construction as `modal_frontend_serve.py` (pip_install vllm + grpcio + grpcio-tools, add_local_dir for proto and packages, run_commands to build stubs and pip-install gen + frontend)

- [X] T007 [P] [US1] Implement `serve_rest_for_bench()` as `@app.function(gpu="A10G", image=_rest_image, volumes={_MODEL_PATH: _MODEL_VOLUME}, timeout=_FUNCTION_TIMEOUT_S)` in `scripts/python/bench_modal.py`:
  - At function start, record `t_start = time.monotonic()`
  - Start vLLM REST subprocess: `python -m vllm.entrypoints.openai.api_server --model _MODEL_PATH --port _REST_PORT`
  - Poll `http://localhost:{_REST_PORT}/health` with httpx every 5 s, up to `_REST_STARTUP_POLLS` (120) times; if process exits early or timeout reached, raise `RuntimeError`
  - On healthy: compute `cold_start_s = time.monotonic() - t_start`
  - Open `with modal.forward(_REST_PORT, unencrypted=True) as tunnel:`; write `modal.Dict.from_name(_DICT_NAME)["rest_addr"] = tunnel.tcp_socket` and `["rest_cold_start_s"] = cold_start_s`
  - Block in sleep loop (`time.sleep(_STOP_CHECK_INTERVAL_S)`) checking `modal.Dict.from_name(_DICT_NAME).get("rest_stop")`; exit loop and return when stop signal is set

- [X] T008 [P] [US1] Implement `serve_grpc_for_bench()` as `@app.function(gpu="A10G", image=_grpc_image, volumes={_MODEL_PATH: _MODEL_VOLUME}, timeout=_FUNCTION_TIMEOUT_S)` in `scripts/python/bench_modal.py`:
  - Mirrors Phase 3.2 `serve_frontend()` in `modal_frontend_serve.py`: start gRPC frontend subprocess, poll `Health.Ping` with grpcio, compute `cold_start_s`, open `modal.forward(_GRPC_PORT, unencrypted=True)`, write `grpc_addr` and `grpc_cold_start_s` to `modal.Dict.from_name(_DICT_NAME)`, block on `grpc_stop` key
  - Add `# type: ignore` where required for `modal.Dict` dynamic API; each suppression must have a comment per Constitution IV

- [X] T009 [US1] Implement `@app.local_entrypoint() def main()` in `scripts/python/bench_modal.py` — full orchestration per `contracts/bench-modal-script.md §Execution Flow`:
  - **REST phase**: `f_rest = serve_rest_for_bench.spawn()` → poll `modal.Dict.from_name(_DICT_NAME).get("rest_addr")` with `_ADDR_POLL_TIMEOUT_S` timeout (on timeout: set `rest_stop`, exit code 1) → print tunnel address → run harness via `subprocess.run(["uv", "run", "-m", "vllm_grpc_bench", "--proxy-url", rest_addr, "--native-url", rest_addr, "--corpus", _CORPUS_PATH, "--concurrency", _CONCURRENCY, "--output-dir", "bench-results"])` → copy `bench-results/results.json` to `bench-results/results-rest.json` → set `rest_stop`
  - **gRPC phase**: `f_grpc = serve_grpc_for_bench.spawn()` → poll `grpc_addr` → start proxy subprocess (`FRONTEND_ADDR=<grpc_addr> uv run uvicorn vllm_grpc_proxy.main:app --host 0.0.0.0 --port 8000`) → run harness (proxy-url and native-url both `http://localhost:8000`) → copy `bench-results/results.json` to `bench-results/results-grpc.json` → kill proxy → set `grpc_stop`
  - Load both JSON files via `_deserialize_run()`; attach `modal_function_id`, `gpu_type`, `cold_start_s` from `modal.Dict` to each `RunMeta`
  - Call `compare_cross(rest_run, grpc_run, label_a="REST", label_b="gRPC")`
  - Write all five files in `docs/benchmarks/` (per contracts/bench-modal-script.md §Output Files)
  - Error handling: on any failure, send stop signals to both Modal functions (if spawned), do NOT write partial output files, exit code 1

**Checkpoint**: `uv run modal run scripts/python/bench_modal.py` completes both phases, writes five output files in `docs/benchmarks/`, and exits 0. (Requires Modal credentials + pre-staged weights — manual pre-merge gate consistent with Phase 3.1/3.2.)

---

## Phase 4: User Story 2 — Compare Two Existing Result Files Offline (Priority: P2)

**Goal**: `python -m vllm_grpc_bench compare-cross --result-a X --result-b Y` produces a comparison report from local files in under 30 seconds without contacting Modal or any network.

**Independent Test**: Run the compare-cross subcommand with two existing result files on disk. Verify the report is written in under 30 seconds with no network calls and that the process exits 0. Run again with a non-existent file path and verify exit code 2.

- [X] T010 [US2] Add `compare-cross` subcommand to `tools/benchmark/src/vllm_grpc_bench/__main__.py` — per `contracts/harness-cli-extension.md §New Subcommand`:
  - Add a `compare-cross` subparser under `_build_parser()` with `--result-a PATH` (required), `--result-b PATH` (required), `--label-a LABEL` (default `"run-a"`), `--label-b LABEL` (default `"run-b"`), `--output PATH` (optional)
  - In `main()`: if `args.subcommand == "compare-cross"`, validate both paths exist (exit 2 if not), call `_deserialize_run()` on each, call `compare_cross(run_a, run_b, ...)`, call `write_cross_run_md(report, output_path)` if `--output` set or print report to stdout, exit 0
  - Import `compare_cross` from `vllm_grpc_bench.compare` and `write_cross_run_md` from `vllm_grpc_bench.reporter`

**Checkpoint**: `python -m vllm_grpc_bench compare-cross --result-a docs/benchmarks/phase-3-ci-baseline.json --result-b docs/benchmarks/phase-3-ci-baseline.json --label-a A --label-b B` produces a valid (all-Δ-0%) report and exits 0 in under 30 seconds. (Uses the already-committed CI baseline for a self-comparison smoke test.)

---

## Phase 5: User Story 3 — Detect Benchmark Regressions in CI (Priority: P3)

**Goal**: CI posts a PR comment that includes the committed Modal REST vs gRPC comparison as context, so reviewers can see real GPU numbers alongside the stub regression check.

**Independent Test**: Open a sample PR touching `packages/proxy/src/` or `packages/frontend/src/`. Verify CI posts a comment that includes both the stub regression section (existing Phase 4 behaviour) and a Modal cross-run summary section generated from the committed baseline files.

- [X] T011 [US3] Update `.github/workflows/benchmark.yml` to add a `modal-baseline-summary` step after the existing regression check:
  - Step runs: `python -m vllm_grpc_bench compare-cross --result-a docs/benchmarks/phase-3-modal-rest-baseline.json --result-b docs/benchmarks/phase-3-modal-grpc-baseline.json --label-a REST --label-b gRPC --output /tmp/modal-cross-summary.md`
  - If either baseline file is absent, the step exits 0 with a message "Modal baselines not yet committed — skipping Modal summary"
  - Append `/tmp/modal-cross-summary.md` content as a new section in the PR comment body (after the existing stub regression section)
  - No GPU credentials needed — this step reads local files only

**Checkpoint**: CI workflow syntax is valid (`act --list` or `gh act` passes). Step exits 0 when both baseline files exist. Step exits 0 gracefully when files are absent.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Lint/type-check gate, then live run to produce and commit the actual baseline files.

- [X] T012 [P] Run `make check` against all files modified in this phase; confirm `ruff` and `mypy --strict` pass with zero errors for `scripts/python/bench_modal.py` and the three extended harness modules (`metrics.py`, `compare.py`, `reporter.py`, `__main__.py`)

- [X] T013 Manual gate — run `make bench-modal` on the developer machine with valid Modal credentials and pre-staged weights; verify all five output files are produced in `docs/benchmarks/` with non-zero metric values; review `phase-3-modal-comparison.md` to confirm no metric is missing and the report is honest

- [X] T014 [P] Commit the five baseline/report files to `docs/benchmarks/`: `phase-3-modal-rest-baseline.json`, `phase-3-modal-rest-baseline.md`, `phase-3-modal-grpc-baseline.json`, `phase-3-modal-grpc-baseline.md`, `phase-3-modal-comparison.md`

- [ ] T015 Manual gate — open a sample PR touching `packages/proxy/src/vllm_grpc_proxy/chat_router.py`; confirm CI benchmark job posts a comment that includes both the stub regression section and the Modal cross-run summary section populated from T014's committed files; confirm CI exits 0

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user story phases
- **Phase 3 (US1)**: Depends on Phase 2
- **Phase 4 (US2)**: Depends on Phase 2; can overlap with Phase 3 (different files)
- **Phase 5 (US3)**: Depends on Phase 4 (compare-cross CLI must exist for CI step)
- **Phase 6 (Polish)**: Depends on Phases 3–5 complete; T013/T014/T015 are sequential

### User Story Dependencies

- **US1 (P1)**: Can start after Phase 2 — no dependencies on other user stories
- **US2 (P2)**: Can start after Phase 2 — no dependencies on US1 (uses same harness types but via separate code path in `__main__.py`)
- **US3 (P3)**: Depends on US2 complete (CI step invokes compare-cross CLI)

### Within Each Phase

- All `[P]` tasks within a phase can run in parallel
- T006 → T007, T008 (sequential within bench_modal.py) → T009
- T004, T005 can run in parallel with T006–T008 (different files)
- T003 can run in parallel with T002 (different files; both foundational)

---

## Parallel Opportunities

```bash
# Phase 2: both foundational tasks in parallel
T002  tools/benchmark/src/vllm_grpc_bench/metrics.py   (RunMeta + CrossRunReport types)
T003  tools/benchmark/src/vllm_grpc_bench/__main__.py  (backward-compat deserializer)

# Phase 3: compare_cross + write_cross_run_md in parallel, then bench_modal.py scaffold
T004  tools/benchmark/src/vllm_grpc_bench/compare.py   (compare_cross function)
T005  tools/benchmark/src/vllm_grpc_bench/reporter.py  (write_cross_run_md function)

# Phase 3 bench_modal.py serve functions (same file, sequential in practice)
T007  serve_rest_for_bench()   in scripts/python/bench_modal.py
T008  serve_grpc_for_bench()   in scripts/python/bench_modal.py
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 2: Foundational (T002, T003)
3. Complete Phase 3: US1 (T004–T009)
4. **STOP and VALIDATE**: Run `make bench-modal` — verify all five output files produced
5. Polish (T012 lint gate) before proceeding to US2/US3

### Incremental Delivery

1. Setup + Foundational → types and deserializer ready
2. US1 → `make bench-modal` produces real GPU numbers (MVP!)
3. US2 → offline compare-cross available for report iteration
4. US3 → CI comment enriched with Modal context
5. Polish → lint gate + committed baselines + live CI validation

### Parallel Strategy (single developer / AI coding session)

Because T002–T005 all touch different files, batch them in a single coding session:
- T002: `metrics.py` extensions
- T003: `__main__.py` deserializer fix
- T004: `compare.py` compare_cross
- T005: `reporter.py` write_cross_run_md

Then build `bench_modal.py` in sequence (T006 → T007 → T008 → T009) since they all touch the same file.

---

## Notes

- `[P]` tasks touch different files and have no inter-task dependencies within the same phase
- T007 and T008 are both in `bench_modal.py` — mark `[P]` conceptually (independent functions) but implement sequentially in one session to avoid edit conflicts
- T013 and T015 require live Modal credentials and GPU — they are manual pre-merge gates consistent with Phase 3.1/3.2 precedent
- Do not write partial output files on failure (FR-008): T009 must validate each phase's harness exit code before proceeding
- All `modal.Dict` dynamic API accesses requiring `# type: ignore` must have an explanatory comment (Constitution IV)
- The CI step in T011 must handle the missing-baseline case gracefully (exits 0) so CI does not fail before T014 is merged
