# Tasks: Phase 7 — Demo Polish

**Input**: Design documents from `specs/012-demo-polish/`
**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ quickstart.md ✅

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm baseline health before any changes.

- [ ] T001 Run `make check` to confirm ruff + mypy --strict + pytest pass clean on the current branch before any edits

---

## Phase 2: Foundational (Code Changes — Blocking US2 Bench Run)

**Purpose**: Three independent code changes that must be in place before the `make bench-modal` re-run can produce Phase 6 JSON files and the reformatted comparison document. US1 (demo scripts) can proceed in parallel.

**⚠️ CRITICAL**: T013 (make bench-modal) cannot run until T002–T005 and T006 are all complete.

- [ ] T002 [P] Update `write_wire_size_comparison_md` in `tools/benchmark/src/vllm_grpc_bench/reporter.py` — replace the flat latency/throughput table with `## Concurrency = N` top-level sections, `### Text Prompt Completions` and `### Prompt-Embed Completions` sub-sections, and a five-column table `| metric | native | proxy | Δ vs native | gRPC-direct | Δ vs native |` with explicit deltas matching the `write_three_way_md` style (per `specs/012-demo-polish/plan.md` Phase 1 Implementation Detail)
- [ ] T003 [P] Update `tools/benchmark/tests/test_reporter.py` — update or add a test for `write_wire_size_comparison_md` that asserts the new output contains `## Concurrency = 1`, `### Text Prompt Completions`, and a Δ column header; remove or update any assertion that references the old flat-table format
- [ ] T004 [P] Update `scripts/python/bench_modal.py` — after `completions_summaries = compute_summaries(all_completions)`, filter `all_completions` by `target` to create a `BenchmarkRun` per path and write `docs/benchmarks/phase-6-completions-{native,proxy,grpc-direct}.json`; add each JSON path to `output_paths` (per `specs/012-demo-polish/plan.md` Phase 1 Implementation Detail)
- [ ] T005 [P] Update `scripts/python/regen_bench_reports.py` — add `--phase5-rest`, `--phase5-proxy`, `--phase5-direct` (defaults: `docs/benchmarks/phase-5-{rest,grpc-proxy,grpc-direct}-streaming.json`) and `--phase6-native`, `--phase6-proxy`, `--phase6-direct` (defaults: `docs/benchmarks/phase-6-completions-{native,proxy,grpc-direct}.json`) arg groups; when Phase 5 files present regenerate `phase-5-streaming-comparison.md` via `write_three_way_md`; when Phase 6 files present combine their summaries and regenerate `phase-6-completions-comparison.md` via `write_wire_size_comparison_md`
- [ ] T006 Run `make check` to confirm ruff + mypy --strict + pytest pass after T002–T005 — `tools/benchmark/`, `scripts/python/`

**Checkpoint**: All code changes verified. Bench run and demo scripts can now proceed in parallel.

---

## Phase 3: User Story 1 — New Viewer Runs the Demo Locally (Priority: P1) 🎯 MVP

**Goal**: Four annotated, runnable `demo/` scripts covering every access path — REST via proxy (curl), REST via proxy (openai SDK), gRPC-direct (VllmGrpcClient), and SSE streaming via proxy.

**Independent Test**: Run each script against a locally-deployed frontend. Every script returns a valid completion and exits 0. Running a script without a running proxy/frontend prints a clear error and exits non-zero.

### Implementation for User Story 1

- [ ] T007 [US1] Create `demo/` directory at the repository root
- [ ] T008 [US1] Create `demo/curl-rest.sh` — bash script that sends a non-streaming chat completion to the proxy via curl; annotated with inline comments; reads `PROXY_BASE_URL` env var (default `http://localhost:8000`); `curl -sf` with explicit fail + `|| { echo "ERROR: ..."; exit 1; }` on connection failure; `seed=42`, model `Qwen/Qwen3-0.6B`
- [ ] T009 [P] [US1] Create `demo/openai-sdk.py` — openai SDK non-streaming chat completion via proxy; annotated; reads `PROXY_BASE_URL` env var; catches `openai.APIError` and exits 1 with a clear message; `seed=42`, model `Qwen/Qwen3-0.6B`; mirrors `scripts/python/chat-nonstreaming.py` pattern
- [ ] T010 [P] [US1] Create `demo/grpc-direct.py` — async script using `VllmGrpcClient` from `vllm_grpc_client`; annotated to explain the gRPC-direct path and lack of proxy; reads `FRONTEND_ADDR` env var (default `localhost:50051`); catches gRPC errors and exits 1 with a clear message; `seed=42`, model `Qwen/Qwen3-0.6B`
- [ ] T011 [P] [US1] Create `demo/streaming.py` — openai SDK streaming chat completion via proxy (`stream=True`); prints tokens as they arrive via `print(..., end="", flush=True)`; annotated; reads `PROXY_BASE_URL` env var; catches `openai.APIError` and exits 1; `seed=42`, model `Qwen/Qwen3-0.6B`
- [ ] T012 [US1] Run `ruff check demo/ && mypy --ignore-missing-imports demo/ && shellcheck demo/curl-rest.sh` and confirm all pass — `demo/`

**Checkpoint**: User Story 1 verified — all four demo scripts pass lint and are runnable end-to-end against a local frontend.

---

## Phase 4: User Story 2 — Reviewer Reads the Benchmark Summary (Priority: P2)

**Goal**: Phase 6 completions JSON files committed to `docs/benchmarks/`; `phase-6-completions-comparison.md` reformatted to match Phase 4.2/5 layout; `regen_bench_reports.py` covers all phases; `docs/benchmarks/summary.md` synthesizes headline numbers honestly across all phases.

**Independent Test**: A reviewer reads `docs/benchmarks/summary.md` and can trace every headline number to a committed JSON file. `make regen-bench-reports` regenerates phases 3–6 without errors.

### Implementation for User Story 2

- [ ] T013 [US2] Run `make bench-modal` — requires Modal GPU (A10G); produces `docs/benchmarks/phase-6-completions-{native,proxy,grpc-direct}.json` and updated `docs/benchmarks/phase-6-completions-comparison.md` — `scripts/python/bench_modal.py`
- [ ] T014 [US2] Verify `docs/benchmarks/phase-6-completions-{native,proxy,grpc-direct}.json` all exist and each contains a non-empty `summaries` array covering both `completion-text` and `completion-embeds` request types — `docs/benchmarks/`
- [ ] T015 [US2] Verify `docs/benchmarks/phase-6-completions-comparison.md` contains `## Concurrency = 1`, `### Text Prompt Completions`, `### Prompt-Embed Completions`, and `Δ vs native` column headers — confirms the new reporter format is live — `docs/benchmarks/`
- [ ] T016 [US2] Run `make regen-bench-reports` (or `uv run python scripts/python/regen_bench_reports.py`) and confirm it regenerates `phase-3-modal-*.md`, `phase-4.2-*.md`, `phase-5-streaming-comparison.md`, and `phase-6-completions-comparison.md` without errors; confirm Phase 5 and Phase 6 output matches Phase 4.2 layout — `scripts/python/regen_bench_reports.py`
- [ ] T017 [US2] Create `docs/benchmarks/summary.md` — three sections: (1) Non-Streaming Chat (Phase 4.2 A10G numbers: P50/P95/P99 latency, request bytes, and response bytes for REST / gRPC-proxy / gRPC-direct at c=1 and c=8); (2) Streaming Chat (Phase 5 A10G numbers: TTFT P50/P95/P99 and TPOT P50/P95/P99 and request bytes at c=1 and c=8); (3) Completions (Phase 6 A10G numbers: request bytes and response bytes for text and embed paths across all three targets); each section includes a methodology block (corpus path, concurrency levels, GPU type A10G, vLLM version 0.20.0, model Qwen/Qwen3-0.6B); one honest interpretation paragraph per section; every number cited traces to its source JSON file by name — `docs/benchmarks/summary.md`
- [ ] T018 [US2] Commit `docs/benchmarks/phase-6-completions-{native,proxy,grpc-direct}.json` and `docs/benchmarks/phase-6-completions-comparison.md` (run after T014 confirms JSON is valid) — `docs/benchmarks/`

**Checkpoint**: User Story 2 verified — Phase 6 JSON committed, comparison document reformatted, regen covers all phases, summary.md complete.

---

## Phase 5: User Story 3 — Viewer Understands the Project from the README (Priority: P3)

**Goal**: Rewrite `README.md` to cover the project thesis, all three access paths, the quickstart pointing at `demo/` scripts, and a one-paragraph benchmark headline summary.

**Independent Test**: A developer unfamiliar with the project reads the README and can articulate the wire-overhead thesis, understands the three access paths, and follows the quickstart to run the demo in under ten minutes.

### Implementation for User Story 3

- [ ] T019 [US3] Rewrite `README.md` with sections: (1) "What is this?" — project purpose and wire-overhead thesis; (2) "Three access paths" — REST via proxy, gRPC via proxy, gRPC-direct and why each exists; (3) "Prerequisites" — `uv`, `make`, links to install docs; (4) "Quick start" — `make bootstrap`, `make run-frontend`, `make run-proxy`, then run each `demo/` script; (5) "Benchmark headlines" — one paragraph summary of key results from `docs/benchmarks/summary.md`; (6) "Development commands" — existing `make` targets; (7) "Repository structure" — updated for Phases 4–7 packages and tools — `README.md`

**Checkpoint**: All three user stories complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final quality gate across all Phase 7 changes.

- [ ] T020 Run `make check` to confirm ruff + mypy --strict + pytest all pass after all Phase 7 changes — repo root

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — confirm baseline first
- **Foundational (Phase 2)**: Depends on Phase 1 confirmation — blocks T013 (bench run); US1 can proceed in parallel
- **User Story 1 (Phase 3)**: Depends only on T001 (baseline confirmed); independent of Foundational code changes
- **User Story 2 (Phase 4)**: Depends on T006 (make check gate after code changes); T013 requires Modal GPU
- **User Story 3 (Phase 5)**: Depends on T017 (summary.md complete) for benchmark headline content
- **Polish (Phase 6)**: Depends on all user stories complete

### User Story Dependencies

- **User Story 1 (P1)**: Independent — can start after T001
- **User Story 2 (P2)**: Depends on T002–T006 (Foundational code changes)
- **User Story 3 (P3)**: Depends on T017 (benchmark summary content) — README headline paragraph needs real numbers

### Within Each Phase

- T002, T003, T004, T005 are all parallel (different files, no mutual dependencies)
- T008, T009, T010, T011 are all parallel after T007 (different files)
- T014, T015 can run in parallel after T013
- T016 can run after T014 (needs JSON files to exist)
- T017 depends on T015 (confirms Phase 6 numbers in new format) and T016 (confirms regen works)
- T018 depends on T014 (JSON must be verified before committing)

### Parallel Opportunities

- Foundational code changes (T002–T005) and US1 demo scripts (T007–T012) can run in parallel
- T013 (bench-modal GPU run, ~30 min) and T019 (README rewrite) can overlap

---

## Parallel Example: Foundational Phase + US1

```bash
# Run these in parallel (completely independent files):
T002: Update reporter.py write_wire_size_comparison_md
T003: Update test_reporter.py
T004: Update bench_modal.py Phase 6 JSON output
T005: Update regen_bench_reports.py Phase 5+6 support

# Once T007 is done, run these in parallel:
T008: Create demo/curl-rest.sh
T009: Create demo/openai-sdk.py
T010: Create demo/grpc-direct.py
T011: Create demo/streaming.py
```

---

## Implementation Strategy

### MVP (User Story 1 Only)

1. Complete Phase 1: Confirm baseline `make check`
2. Complete T007–T012: Demo scripts created and linted
3. **STOP and VALIDATE**: All four `demo/` scripts run against a local frontend
4. Proceed to Foundational + US2 + US3

### Full Delivery

```
T001 → T002–T005 (parallel) → T006 → T013 → T014–T016 → T017 → T018
T001 → T007 → T008–T011 (parallel) → T012
T001 → T007–T012 (US1, parallel with Foundational)
T017 → T019 (README needs summary.md content)
All done → T020
```

### Modal Dependency Note

T013 requires Modal GPU time (~30 min). Everything else in US1, US3, and the Foundational code changes can be completed without Modal. T013 is the only GPU-gated task.

---

## Notes

- [P] tasks = different files or concerns, no mutual dependencies
- [US1]/[US2]/[US3] labels map tasks to spec.md user stories for traceability
- T002 and T003 are coupled: changing the reporter output format requires updating the test that checks that output
- T013 (make bench-modal) must not run until T006 passes — the code changes must be in place first
- T018 (commit Phase 6 JSON) is listed as a task because committed benchmark JSON is a first-class deliverable per Constitution principle V
