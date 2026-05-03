# Tasks: Enable Prompt Embeddings in gRPC Frontend (Phase 6.1)

**Input**: Design documents from `specs/011-phase-6.1/`
**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ quickstart.md ✅

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: No new project structure, packages, or dependencies needed. All Phase 6 infrastructure is already in place.

- [x] T001 Verify `make check` passes clean on the current branch before making any changes (`packages/frontend/src/vllm_grpc_frontend/main.py`)

---

## Phase 2: Foundational (Core Fix)

**Purpose**: The single source change that unblocks both user stories.

**⚠️ CRITICAL**: Both US1 and US2 depend on this change — no user story work can be verified until T002 is complete.

- [x] T002 Add `enable_prompt_embeds=True` to `AsyncEngineArgs` in `packages/frontend/src/vllm_grpc_frontend/main.py` (line 19 — expand the single-arg call to a two-arg call as documented in `specs/011-phase-6.1/plan.md` Phase 1 Implementation Detail)

**Checkpoint**: Code change applied. Run `make check` to confirm no regressions before proceeding.

- [x] T003 Run `make check` (ruff + mypy --strict + pytest) and confirm all checks pass — `packages/frontend/src/vllm_grpc_frontend/main.py`

---

## Phase 3: User Story 1 — gRPC-Direct Prompt-Embedding Completion (Priority: P1) 🎯 MVP

**Goal**: Confirm that a `VllmGrpcClient` can send a prompt-embedding tensor directly to the deployed frontend and receive a real completion.

**Independent Test**: `make bench-modal` — the `grpc-direct | completion-embeds` row shows `success=True` and a real `resp_bytes_mean` value.

### Implementation for User Story 1

- [ ] T004 [US1] Deploy updated frontend wheel to Modal (rebuild image with the `enable_prompt_embeds=True` change) — `scripts/python/bench_modal.py` or `Makefile` bench-modal target
- [ ] T005 [US1] Run `modal run scripts/python/verify_prompt_embeds_modal.py` as a smoke test to confirm vLLM 0.20.0 on A10G accepts `prompt_embeds` — `scripts/python/verify_prompt_embeds_modal.py`
- [ ] T006 [US1] Run `make bench-modal` and confirm `grpc-direct | completion-embeds` row shows `success=True` with real latency and `resp_bytes_mean` — `tools/benchmark/`

**Checkpoint**: User Story 1 verified — gRPC-direct prompt-embedding path is functional end-to-end.

---

## Phase 4: User Story 2 — Proxy Path Prompt-Embedding Completion (Priority: P2)

**Goal**: Confirm that the proxy REST path also produces `success=True` for `completion-embeds` requests (no additional code changes needed — proxy translation is already correct).

**Independent Test**: `make bench-modal` — the `proxy | completion-embeds` row shows `success=True` and a real `resp_bytes_mean` value.

### Implementation for User Story 2

- [ ] T007 [US2] Confirm `proxy | completion-embeds` row in the bench-modal results from T006 shows `success=True` — no code changes needed; same bench run covers both paths

**Checkpoint**: User Stories 1 AND 2 verified in the same benchmark run.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Commit benchmark outputs and mark Phase 6.1 complete.

- [x] T008 Commit updated benchmark JSON/markdown outputs to `docs/benchmarks/` with real `completion-embeds` numbers — `docs/benchmarks/`
- [x] T009 [P] Update `docs/notes/vllm-embedding-input-limitation.md` status line if not already done — `docs/notes/vllm-embedding-input-limitation.md`
- [x] T010 [P] Confirm wire-size comparison: `grpc-direct | completion-embeds` request bytes are ~33% smaller than `rest | completion-embeds` request bytes (base64 overhead) — `docs/benchmarks/`

---

## Phase 6: Follow-On — Native REST Embed Baseline (Honest Measurement)

**Purpose**: The current embed latency comparison uses `proxy | completion-embeds` as the baseline,
which conflates proxy translation overhead with the encoding difference (base64 vs binary). A
`native | completion-embeds` row isolates the two factors and gives an honest latency baseline.

**Why needed**: Constitution principle V (Honest Measurement) — the latency numbers for embeds
currently cannot distinguish protocol efficiency from proxy overhead. Wire-size comparison is
already valid; latency comparison needs a clean baseline.

**Changes required**:

1. `scripts/python/bench_modal.py` — add `--enable-prompt-embeds` to the REST server startup
   args (the `_sub.Popen([..., "vllm.entrypoints.openai.api_server", ...])` call around line 129)
   so the native REST target accepts `prompt_embeds` requests.

2. `tools/benchmark/src/vllm_grpc_bench/runner.py` — add a `run_completions_native_embeds()`
   runner that sends base64-encoded tensors to the native REST `/v1/completions` endpoint
   (mirrors `run_completions_proxy_embeds()` but targets the native REST URL directly, with no
   proxy hop).

3. `scripts/python/bench_modal.py` — wire the new runner into the embed benchmark block
   alongside the existing proxy and gRPC-direct runners, producing a
   `native | completion-embeds` row in the results.

4. `tools/benchmark/src/vllm_grpc_bench/reporter.py` — verify the wire-size comparison
   table treats `native | completion-embeds` as the embed latency baseline (mirrors how
   `native | completion-text` is the text baseline).

**Tasks**:

- [x] T011 Add `--enable-prompt-embeds` to the REST server startup args in `scripts/python/bench_modal.py` (line ~129, the `_sub.Popen` args list for `vllm.entrypoints.openai.api_server`)
- [x] T012 Add `run_completions_native_embeds()` runner to `tools/benchmark/src/vllm_grpc_bench/runner.py` — mirrors `run_completions_proxy_embeds()` but targets the native REST URL with no proxy hop
- [x] T013 Wire `run_completions_native_embeds()` into the embed benchmark block in `scripts/python/bench_modal.py` alongside the existing proxy and gRPC-direct runners
- [x] T014 [P] Add a unit test for `run_completions_native_embeds()` in `tools/benchmark/tests/test_runner.py` — mirrors `test_run_completions_proxy_embeds_request_type`
- [x] T015 Run `make check` to confirm ruff + mypy --strict + pytest pass — `tools/benchmark/`
- [x] T016 Run `make bench-modal` and confirm a `native | completion-embeds` row appears in `docs/benchmarks/phase-6-completions-comparison.md` with real latency numbers
- [x] T017 Verify the three-way embed comparison is interpretable: native REST latency vs proxy REST latency (proxy overhead) and native REST latency vs gRPC-direct latency (pure protocol gain) — `docs/benchmarks/phase-6-completions-comparison.md`

**Checkpoint**: Follow-on complete when `phase-6-completions-comparison.md` contains a
`native | completion-embeds` row and the latency differences between all three embed paths
are interpretable without confounding factors.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — confirm baseline first
- **Foundational (Phase 2)**: Depends on Phase 1 confirmation — blocks both user stories
- **User Story 1 (Phase 3)**: Depends on T002 + T003 — the Modal deployment and benchmark run
- **User Story 2 (Phase 4)**: Covered by the same bench-modal run as US1 — no additional work
- **Polish (Phase 5)**: Depends on bench-modal results being available

### User Story Dependencies

- **User Story 1 (P1)**: Can proceed after T003 passes
- **User Story 2 (P2)**: Covered automatically when US1's bench-modal run completes

### Within Each Phase

- T002 (code change) must precede T003 (make check)
- T003 must pass before T004 (Modal deployment)
- T006 (bench-modal) covers verification for both US1 and US2

### Parallel Opportunities

- T009 and T010 (Polish) can run in parallel
- T004 and T005 can run sequentially (T005 is a lightweight smoke test, T006 is the full benchmark)

---

## Parallel Example: Phase 2 → Phase 3

```bash
# Sequential critical path:
T002: Edit main.py
T003: make check (confirms no regressions)
T004: Deploy updated wheel to Modal
T005: verify_prompt_embeds_modal.py (smoke test)
T006: make bench-modal (confirms both US1 + US2)

# Parallel in Polish phase:
T009: Update limitation doc
T010: Confirm wire-size numbers from T006 output
```

---

## Implementation Strategy

### MVP (User Story 1 Only)

1. Complete Phase 1: Verify baseline `make check`
2. Complete Phase 2: Apply T002 + T003
3. Complete Phase 3: T004 + T005 + T006
4. **STOP and VALIDATE**: `grpc-direct | completion-embeds` shows `success=True`
5. Proceed to Phase 4 + 5

### Full Delivery (Both Stories)

Same bench run covers both. No additional code changes after T002.

---

## Notes

- [P] tasks = different files or concerns, no mutual dependencies
- [US1]/[US2] labels map tasks to spec.md user stories for traceability
- T002 is the only source code change in this entire phase
- T003–T006 are all verification tasks; they require a Modal token and GPU time
- Commit after T003 (baseline confirmed) and again after T008 (benchmark outputs committed)
