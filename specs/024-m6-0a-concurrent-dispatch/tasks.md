---
description: "Task list for M6.0a — Concurrent Dispatch Restoration"
---

# Tasks: M6.0a — Concurrent Dispatch Restoration

**Input**: Design documents from `/specs/024-m6-0a-concurrent-dispatch/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Regression tests are explicitly mandated by FR-003 / FR-004 of the spec; test tasks below are required, not optional.

**Organization**: Tasks are grouped by user story. The two-PR sequence (FR-018) maps as: **PR-1 = US1** (harness fix unblocks M6.1.1 PR #27); **PR-2 = US2 + US3** (corrected re-run + dispatch-correction note, after Modal compute completes).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1 / US2 / US3)
- Exact file paths in every description

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm branch state and prerequisites.

- [ ] T001 Verify branch `024-m6-0a-concurrent-dispatch` is checked out and clean (`git status` returns clean tree; `git rev-parse --abbrev-ref HEAD` returns `024-m6-0a-concurrent-dispatch`)
- [ ] T002 Verify M6.1.1 PR #27 is still open per FR-018 (`gh pr view 27 --json state --jq '.state'` returns `OPEN`); halt and ask if it has already closed
- [ ] T003 Verify the 2026-05-16 audit baseline is preserved verbatim at commit `b63947a` (`git show b63947a:docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md` returns the audit-callout-header file)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: None — M6.0a is a surgical correction to existing dispatch entry points. The only "shared infrastructure" already exists (M5.1's `asyncio.gather` pattern at `m5_1_grpc_cohort.py:387`, the M6.1.1 reporter + sweep wiring on the M6.1.1 branch, and the audit baseline at `b63947a`). No foundational tasks needed.

**Checkpoint**: Phase 2 vacuous. User story work begins immediately.

---

## Phase 3: User Story 1 — Restore Real Concurrent Dispatch in the M6 Harness (Priority: P1) 🎯 MVP / PR-1

**Goal**: Replace the sequential `await` dispatch in M6 / M6.1 / M6.1.1 measurement and warmup loops with `asyncio.gather`-based concurrent dispatch (peak in-flight = c per FR-001), preserving seed determinism (FR-002) and the round-robin per-c-batch index allocator (M6 / M6.1 only). Lands the regression test (FR-003 / FR-004) and the `dispatch_mode` strict-superset emission (FR-007).

**Independent Test** (FR-003 + Acceptance Scenario 1.1 / 1.2 / 1.3): `pytest tools/benchmark/tests/test_m6_concurrent_dispatch.py -v` reports peak in-flight equal to cell.concurrency for `(c=1, c=4, c=8) × (m6, m6_1, m6_1_1)` — 9 parametrisations. Failure blocks M6.1.1 PR #27 merge (FR-004).

### Tests for User Story 1 (regression-test-first per project convention)

- [ ] T004 [P] [US1] Create the `_ConcurrencyProbe` fake driver and 9-parametrisation peak-in-flight test in `tools/benchmark/tests/test_m6_concurrent_dispatch.py` (per [contracts/dispatch.md](./contracts/dispatch.md) "In-Flight Concurrency Probe (Test Driver)" section + [research.md](./research.md) § R-4); test asserts `probe.peak == c` for `c ∈ {1, 4, 8}` across all three measurement-loop entry points (`_run_measurement`, `_run_measurement_m6_1`, `_measure_cell`)
- [ ] T005 [P] [US1] Add warmup-symmetry test to `tools/benchmark/tests/test_m6_concurrent_dispatch.py` covering `c=4` × all three warmup entry points (`_run_warmup`, `_run_warmup_m6_1`, `_measure_cell` warmup loop) — asserts FR-005a
- [ ] T006 [P] [US1] Add seed-determinism test to `tools/benchmark/tests/test_m6_concurrent_dispatch.py` covering `c ∈ {1, 4}` × all three entry points — records `(cohort, seed)` tuples emitted by the probe, asserts the *set* equals the pre-fix harness's known-good seed sequence (per FR-002 + Acceptance Scenario 1.4)
- [ ] T007 [US1] Run the new test file against the **current (sequential)** harness and confirm all 18 parametrisations FAIL (`pytest tools/benchmark/tests/test_m6_concurrent_dispatch.py -v` returns 18 failures; this validates the test detects the bug before the fix is applied)

### Implementation for User Story 1

- [ ] T008 [P] [US1] Patch `tools/benchmark/src/vllm_grpc_bench/m6_sweep.py` two entry points:
  - `_run_warmup` (line 189): replace sequential inner loop with per-(cohort × c-batch) `asyncio.gather(*(_warmup_one() for _ in range(size)))` (preserve the inner retry-until-success loop unchanged); pattern per [contracts/dispatch.md](./contracts/dispatch.md) "Reference Implementation Pattern".
  - `_run_measurement` (line 219): replace `for idx in batch_indices: await _run_one_rpc_with_retry(...)` with per-cohort `await asyncio.gather(*(...))`; preserve `batch_indices` allocation and `compute_rpc_seed(idx, base_seed)` cohort-symmetric mapping (FR-002).
- [ ] T009 [P] [US1] Patch `tools/benchmark/src/vllm_grpc_bench/m6_1_sweep.py` two entry points:
  - `_run_warmup_m6_1` (line 141): same pattern as T008's `_run_warmup` fix.
  - `_run_measurement_m6_1` (line 160): same pattern as T008's `_run_measurement` fix.
- [ ] T010 [P] [US1] Patch `tools/benchmark/src/vllm_grpc_bench/m6_1_1_sweep.py` `_measure_cell` (line 233):
  - Warmup loop (lines 257–259): per-cohort `asyncio.gather(*(driver(cohort, m6_1_cell, 0) for _ in range(n_warmup)))` (FR-005a symmetric dispatch).
  - Measurement loop (lines 263–268): per-cohort `asyncio.Semaphore(cell.concurrency)`-bounded `asyncio.gather` over `range(n_measurement)` (steady c-in-flight stream); pattern per [contracts/dispatch.md](./contracts/dispatch.md) "Reference Implementation Pattern" M6.1.1 section.
- [ ] T011 [P] [US1] Update `concurrency` field docstring on `M6Cell` in `tools/benchmark/src/vllm_grpc_bench/m6_types.py`: revise from "metadata tag for round-robin sequencing" → "actual in-flight parallelism (peak concurrent RPCs per cohort within a c-batch)" (FR-006)
- [ ] T012 [P] [US1] Update `concurrency` field docstring on `M6_1Cell` in `tools/benchmark/src/vllm_grpc_bench/m6_1_types.py` (same revision as T011, FR-006)
- [ ] T013 [P] [US1] Update `concurrency` field docstring on `M6_1_1Cell` in `tools/benchmark/src/vllm_grpc_bench/m6_1_1_types.py` (same revision as T011, FR-006)
- [ ] T014 [US1] Extend `tools/benchmark/src/vllm_grpc_bench/m6_1_1_reporter.py` to inject a top-level `dispatch_mode: "concurrent"` key into every manifest before `json.dumps` is called; place adjacent to `schema_version` for discoverability per [contracts/output.md](./contracts/output.md) "Emission Rules"; value is unconditional `"concurrent"` (no parameter, no runtime branching — FR-007 strict-superset)
- [ ] T015 [US1] Run the new test file against the **corrected (post-T008–T014) harness** and confirm all 18 parametrisations PASS (`pytest tools/benchmark/tests/test_m6_concurrent_dispatch.py -v` returns 18 successes); failure here means the dispatch fix is incomplete or seed determinism broke
- [ ] T016 [US1] Run the local lint chain per `feedback_local_lint_chain` memory: `ruff check tools/benchmark && ruff format --check tools/benchmark && mypy --strict tools/benchmark/src/vllm_grpc_bench tools/benchmark/tests && pytest tools/benchmark/tests -x`; all four gates must pass before pushing PR-1
- [ ] T017 [US1] Run the full existing M6 / M6.1 / M6.1.1 unit-test suite to confirm no regression: `pytest tools/benchmark/tests -k "m6 or m6_1 or m6_1_1" -v`; all pre-existing tests must continue to pass (per [research.md](./research.md) § R-6: none assert sequential dispatch, so no breakage expected)
- [ ] T018 [US1] Push branch and open PR-1 per [quickstart.md](./quickstart.md) Step 6: `git push -u origin 024-m6-0a-concurrent-dispatch`; `gh pr create --base main --title "M6.0a PR-1: Restore concurrent dispatch in M6 / M6.1 / M6.1.1 measurement loops" --body "..."` (full body template in quickstart.md)
- [ ] T019 [US1] After PR-1 merges to `main`, post a cross-link comment on M6.1.1 PR #27 noting the unblock (e.g., "M6.0a PR-1 (#NN) is merged — PR #27 can now rebase on main and proceed to merge gate")

**Checkpoint**: PR-1 merged. M6.1.1 PR #27 is unblocked. The corrected harness emits `dispatch_mode: "concurrent"` on every future M6.1.1 run. US1 complete; US2 may begin.

---

## Phase 4: User Story 2 — Re-run M6.1.1 Phase 1 Under Corrected Dispatch (Priority: P2) / PR-2 first half

**Goal**: Use the corrected harness to run a fresh M6.1.1 Phase 1 sweep against Modal A10G eu-west-1 with audit-baseline version pinning (FR-008), producing the canonical artifact at `docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}` annotated with `dispatch_mode: "concurrent"` (FR-007) and the Phase 2 verdict bucket recorded as a single explicit manifest field (FR-010).

**Independent Test** (FR-008 + FR-010 + Acceptance Scenarios 2.1 / 2.2 / 2.3 / 2.4 / 2.5 / 2.6): the resulting manifest contains `dispatch_mode: "concurrent"`, chat_stream per-cohort `engine_ttft_ms` spreads are reported for `c=1` / `c=4` / `c=8`, and `phase_2_outcome` falls in exactly one of three buckets (`"below 5 %"` / `"at or above 10 %"` / `"intermediate per FR-010 classifier output"`).

### Implementation for User Story 2

- [ ] T020 [US2] Pin the local environment to audit-baseline dependency versions per [quickstart.md](./quickstart.md) Step 1 + [research.md](./research.md) § R-5: `git checkout b63947a -- uv.lock && uv sync --frozen`; verify `uv pip show vllm` returns `Version: 0.20.1` and `uv pip show torch` returns `Version: 2.11.0` (FR-008 audit-baseline parity)
- [ ] T021 [US2] Confirm Modal authentication is valid for `eu-west-1` per [quickstart.md](./quickstart.md) Step 2: `modal token current` returns a non-empty token; export the project's standard secret env var (`MODAL_BENCH_TOKEN` or equivalent) if not already set
- [ ] T022 [US2] Confirm the M6.0a-corrected harness is the active code (PR-1 merged to main and pulled, OR working from the M6.0a branch with PR-1's changes in place): `grep -q "dispatch_mode" tools/benchmark/src/vllm_grpc_bench/m6_1_1_reporter.py && echo OK` and `pytest tools/benchmark/tests/test_m6_concurrent_dispatch.py -q` returns success
- [ ] T023 [US2] Run the corrected-dispatch Phase 1 sweep per [quickstart.md](./quickstart.md) Step 3: `python -m vllm_grpc_bench --m6_1_1-diagnose --m6_1_1-modal-region=eu-west-1 2>&1 | tee /tmp/m6_0a-rerun.log`; wall-clock budget ≤ 45 min (SC-002); Modal cost budget ≤ $1 (SC-006); monitor `M6_1_1ProgressReporter` per-pair progress lines on stderr
- [ ] T024 [US2] Verify the markdown artifact emitted at `docs/benchmarks/m6_1_1-engine-cost-instrumentation.md` per [quickstart.md](./quickstart.md) Step 4: file exists; methodology section contains a "Dispatch mode: concurrent" line; multi-point timing table is populated for all 6 cells × 3 cohorts
- [ ] T025 [US2] Verify the JSON artifact emitted at `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` per [contracts/output.md](./contracts/output.md) "JSON Schema Sketch": `jq -r '.dispatch_mode' docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` returns `"concurrent"`; `jq -r '.phase_2_outcome' returns` one of the three FR-010 buckets; `jq -r '.schema_version' returns` the unchanged M6.1.1 value (no version bump per FR-007)
- [ ] T026 [US2] Record the chat_stream per-cohort `engine_ttft_ms` spread values for each cell (`c=1`, `c=4`, `c=8`) extracted from the new artifact, alongside the audit-baseline values from `docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md` (audit shows 19.5 % at c=1, 6.0 % at c=4, 8.4 % at c=8); save the side-by-side table to a scratch file for use in US3's dispatch-correction note (FR-009)
- [ ] T027 [US2] **Optional SC-005 spot-check**: pick any one M6 or M6.1 published cell, run it under the corrected harness, and verify the resulting mean falls within the published 95 % CI for that cell. Confirms no regression in main-verdict reproducibility. Cell choice is operator's; recommend `(chat_stream, h=4096, c=1)` from M6.1's published narrative (most-cited cell)

**Checkpoint**: PR-2's data exists. The corrected-dispatch artifact lands at the canonical path with `dispatch_mode: "concurrent"`. The Phase 2 verdict bucket is recorded. US2 complete; US3 may begin.

---

## Phase 5: User Story 3 — Publish the Dispatch-Correction Note (Priority: P3) / PR-2 second half

**Goal**: Author `docs/benchmarks/m6_0a-dispatch-correction.md` (the standalone explainer per FR-012 / FR-013) and add the methodology-supersedence cross-link annotation to M6.1's published narrative (FR-016). Ship PR-2 with both the corrected-dispatch artifact from US2 and the dispatch-correction note from US3.

**Independent Test** (FR-012 + FR-013 + SC-007): the dispatch-correction note exists at the spec-mandated path, contains a side-by-side per-cohort spread table comparing audit baseline vs corrected run, and the four mandated cross-links (audit baseline, corrected run, PR #27, PLAN.md M6.0a section) all resolve. A reader can determine in ≤ 5 min which M6.x findings are dispatch-sensitive vs robust (SC-007).

### Implementation for User Story 3

- [ ] T028 [P] [US3] Author `docs/benchmarks/m6_0a-dispatch-correction.md` per [data-model.md](./data-model.md) § "Dispatch-Correction Note": 6 sections (What broke / The fix / The regression test / Before vs after / Implication for M6.x findings / Cross-links); side-by-side per-cohort spread table populated from T026's scratch data; dispatch-sensitive-vs-robust 3-row table per spec § "Why this matters" / [data-model.md](./data-model.md) entity 6; bulleted cross-links to audit baseline, corrected run, PR #27, and `docs/PLAN.md#m60a--concurrent-dispatch-restoration-planned-blocks-m611-closure`
- [ ] T029 [P] [US3] Add the methodology-supersedence cross-link annotation to `docs/benchmarks/m6_1-real-prompt-embeds.md` per [quickstart.md](./quickstart.md) Step 6: locate the per-cohort drift section (the one that originally fired `engine_cost_drift_warning` in M6.1's published narrative); append a one-line forward-pointer paragraph to the dispatch-correction note (FR-016)
- [ ] T030 [US3] Verify all four cross-links in `docs/benchmarks/m6_0a-dispatch-correction.md` resolve: (a) `./m6_1_1-audit-2026-05-16-seq-dispatch.md` exists, (b) `./m6_1_1-engine-cost-instrumentation.md` exists (created by T024), (c) PR #27 URL resolves via `gh pr view 27`, (d) `../PLAN.md#m60a--concurrent-dispatch-restoration-planned-blocks-m611-closure` exists in PLAN.md
- [ ] T031 [US3] Verify the audit baseline file is byte-identical to its `b63947a` version per FR-011: `git diff b63947a -- docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md` returns empty (no edits to the audit body during US2 / US3)
- [ ] T032 [US3] Run the local lint chain (PR-2 contains no new code beyond the docs; this primarily verifies doc-link checks): `ruff check tools/benchmark && ruff format --check tools/benchmark && mypy --strict tools/benchmark/src/vllm_grpc_bench tools/benchmark/tests && pytest tools/benchmark/tests -x`; all four gates pass
- [ ] T033 [US3] Stage PR-2 files: `git add docs/benchmarks/m6_1_1-engine-cost-instrumentation.md docs/benchmarks/m6_1_1-engine-cost-instrumentation.json docs/benchmarks/m6_0a-dispatch-correction.md docs/benchmarks/m6_1-real-prompt-embeds.md`
- [ ] T034 [US3] Commit + push + open PR-2 per [quickstart.md](./quickstart.md) Step 8 with the title `M6.0a PR-2: Corrected-dispatch artifact + dispatch-correction note` and body template from quickstart.md

**Checkpoint**: PR-2 open. The full M6.0a deliverable (harness fix + regression test + corrected artifact + dispatch-correction note + M6.1 annotation) is on `main` once PR-2 merges. M6.0a complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Confirm all success criteria are closed and update durable project state.

- [ ] T035 Verify SC-001 closed: `pytest tools/benchmark/tests/test_m6_concurrent_dispatch.py -v` reports 18 passes (3 concurrency levels × 3 entry points × 2 base parametrisations: peak + warmup + seed-determinism subsets)
- [ ] T036 Verify SC-002 closed: review T023's `/tmp/m6_0a-rerun.log` wall-clock entry; confirm ≤ 45 min
- [ ] T037 Verify SC-003 closed: confirm `phase_2_outcome` recorded in the corrected-dispatch JSON manifest is one of the three FR-010 buckets (`"below 5 %"` / `"at or above 10 %"` / `"intermediate per FR-010 classifier output"`)
- [ ] T038 Verify SC-004 closed: dispatch-correction note is cross-linked from PR #27 review thread (post a comment on PR #27 with a link to the note when PR-2 merges); cross-link added to PLAN.md M6.0a section if not already present
- [ ] T039 Verify SC-005 closed: T027's optional spot-check passed (or document an exception in the dispatch-correction note if the spot-check was deferred / negative)
- [ ] T040 Verify SC-006 closed: total Modal compute cost for the corrective re-run ≤ $1 (check Modal usage dashboard)
- [ ] T041 Verify SC-007 closed: a colleague (or self-test after a 5-minute break to simulate fresh reader) reads only `docs/benchmarks/m6_0a-dispatch-correction.md` and its cross-links and produces a correct dispatch-sensitive-vs-robust classification of M6 / M6.1 / M6.1.1 findings; if they cannot, revise the note's "Implication for M6.x findings" section
- [ ] T042 [P] Update `~/.claude/projects/-Users-bsansom-projects-vllm-grpc/memory/project_status.md` (or whichever memory file tracks current state) to reflect M6.0a closure and M6.1.1 PR #27 merge status
- [ ] T043 [P] Update `docs/PLAN.md` M6.0a section to mark the milestone delivered with the date both PRs merged
- [ ] T044 [P] Verify FR-014 / FR-015 harness-only scope via `git diff main -- proxy/ frontend/ client/ proto/ scripts/python/modal_bench_rest_grpc_server.py packages/frontend/src/vllm_grpc_frontend/ docs/benchmarks/m6.md`; expect empty diff (no edits to engine / model / Modal endpoint / M6 main-verdict files). For `docs/benchmarks/m6_1-real-prompt-embeds.md` the diff is allowed but MUST contain only the FR-016 cross-link annotation block — review with `git diff main -- docs/benchmarks/m6_1-real-prompt-embeds.md` and confirm scope.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — runs immediately.
- **Foundational (Phase 2)**: Vacuous — nothing blocks user stories.
- **US1 (Phase 3)**: Depends on Setup. **Blocks** US2 (PR-2 cannot run the corrected sweep until PR-1's harness fix is in `main`).
- **US2 (Phase 4)**: Depends on US1 complete (PR-1 merged). Runs the Modal sweep; produces the "after" data.
- **US3 (Phase 5)**: Depends on US2 complete (US3's note table needs the corrected-run numbers). Authors the dispatch-correction note.
- **Polish (Phase 6)**: Depends on all of US1 + US2 + US3.

### User Story Dependencies

- **US1 → US2 → US3**: linear because the two-PR sequence is gated on Modal compute completion.
- **No parallel-team opportunity**: a single operator runs the entire pipeline. Modal compute (T023, ~30–45 min) is the only "wait" — the operator can author T028 in parallel with the sweep if confident of the verdict bucket, but the side-by-side spread table requires real numbers from T026.

### Within Each User Story

- **US1**: T004 + T005 + T006 (test authoring, all [P], different test functions in one file but `pytest` parses them independently) → T007 (run tests, expect 18 failures) → T008 + T009 + T010 + T011 + T012 + T013 + T014 (implementation tasks, all [P] across different files) → T015 (run tests, expect 18 passes) → T016 (local lint chain) → T017 (regression suite) → T018 (push + PR-1) → T019 (PR #27 cross-link).
- **US2**: T020 (lockfile pin) → T021 (Modal token check) → T022 (corrected harness sanity check) → T023 (Modal sweep) → T024 + T025 (artifact verification) → T026 (record numbers) → T027 (optional spot-check).
- **US3**: T028 + T029 ([P]) → T030 (cross-link verification) → T031 (audit verbatim check) → T032 (lint chain) → T033 → T034 (push + PR-2).

### Parallel Opportunities

- **Within US1 tests**: T004, T005, T006 can be added to the same file in any order (the test file has separate test functions).
- **Within US1 implementation**: T008, T009, T010, T011, T012, T013, T014 are all in different files (or different unrelated functions) and can be authored in parallel.
- **Within US3**: T028 and T029 touch different files and can be authored in parallel.
- **Within Polish**: T042 and T043 are independent memory / docs updates.

---

## Parallel Example: User Story 1 implementation

```bash
# These edits touch different files and can be authored in parallel:
Task: "Patch m6_sweep.py: _run_warmup and _run_measurement (T008)"
Task: "Patch m6_1_sweep.py: _run_warmup_m6_1 and _run_measurement_m6_1 (T009)"
Task: "Patch m6_1_1_sweep.py: _measure_cell warmup + measurement (T010)"
Task: "Update concurrency docstring in m6_types.py (T011)"
Task: "Update concurrency docstring in m6_1_types.py (T012)"
Task: "Update concurrency docstring in m6_1_1_types.py (T013)"
Task: "Inject dispatch_mode in m6_1_1_reporter.py (T014)"
```

After all seven complete, run T015 (test suite passes 18/18) → T016 (lint chain) → T017 (regression suite) → T018 (PR-1) → T019 (PR #27 cross-link comment).

---

## Implementation Strategy

### MVP First (US1 / PR-1 only)

1. Complete Phase 1 Setup (T001 – T003).
2. Phase 2 Foundational is vacuous — skip.
3. Complete Phase 3 US1 (T004 – T019).
4. **STOP and VALIDATE**: M6.1.1 PR #27 is unblocked the moment PR-1 merges.
5. Operator decision: continue immediately to US2 / PR-2, or pause M6.0a here while M6.1.1 PR #27 closes.

### Incremental Delivery (full M6.0a)

1. Setup → US1 (PR-1 merges) → unblock M6.1.1.
2. US1 → US2 (Modal sweep produces corrected artifact).
3. US2 → US3 (dispatch-correction note authored; PR-2 opens).
4. PR-2 merges → M6.0a complete; Polish phase confirms closure.

### Wall-clock budget

| Phase | Wall-clock | Modal cost |
|---|---|---|
| Phase 1 + 2 (Setup + Foundational) | ~5 min | $0 |
| US1 (PR-1 author + PR + merge) | ~1.5 h | $0 |
| US2 (lockfile pin + Modal sweep + verify) | ~1 h (incl. 30–45 min Modal compute) | ≤ $1 |
| US3 (dispatch-correction note + PR-2) | ~45 min | $0 |
| Polish | ~15 min | $0 |
| **Total M6.0a** | **~3.5 h operator + ~30–45 min Modal** | **≤ $1** |

---

## Notes

- [P] tasks = different files, no dependencies.
- [Story] label maps each task to its user story; the two-PR boundary is US1 (PR-1) vs US2+US3 (PR-2).
- Per the `feedback_check_merged_before_repro` memory: before starting T008–T014 verify the corrected dispatch isn't *already* on `main` from an out-of-band fix (`git log main --grep="dispatch" --grep="asyncio.gather" --since="2026-05-15"`). If a sibling fix has landed, halt and reassess scope.
- Per the `feedback_local_lint_chain` memory: T016 and T032 run ALL FOUR gates (ruff check, ruff format --check, mypy --strict, pytest) as separate invocations — do not chain them with `&&` if it would hide intermediate failures. The example commands in quickstart.md chain them for brevity but a failing intermediate gate halts execution either way.
- Per the `feedback_no_client_references_in_docs` memory: the dispatch-correction note (T028) frames the bug in generic methodology language ("the harness inherited M5.x's matrix but dropped concurrent dispatch") rather than referencing any client / use-case context.
- Per the `feedback_smoke_warmup_seed_zero` memory: the warmup-symmetry test (T005) and seed-determinism test (T006) must handle the seed=0 smoke/warmup convention; the corrected harness preserves the existing `max(0, seed - base_seed)` clamp pattern verbatim per spec § Assumptions.
- Per the `feedback_topology_aware_framing` memory: the dispatch-correction note's "Implication for M6.x findings" table (T028) frames M6.1's per-cohort drift sub-finding as "dispatch-sensitive — re-interpreted under M6.0a" rather than "supersedes M6.1"; M6.1's main verdicts are unaffected.
- Per the `feedback_thorough_clarify_cycles` memory: the spec underwent 2 rounds of clarification before this task list (6 Q/A bullets total); the task list inherits those decisions verbatim and does not introduce new ambiguity.
