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

- [X] T001 Verify branch `024-m6-0a-concurrent-dispatch` is checked out and clean (`git status` returns clean tree; `git rev-parse --abbrev-ref HEAD` returns `024-m6-0a-concurrent-dispatch`)
- [X] T002 Verify M6.1.1 PR #27 is still open per FR-018 (`gh pr view 27 --json state --jq '.state'` returns `OPEN`); halt and ask if it has already closed
- [X] T003 Verify the 2026-05-16 audit baseline is preserved verbatim at commit `b63947a` (`git show b63947a:docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md` returns the audit-callout-header file)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: None — M6.0a is a surgical correction to existing dispatch entry points. The only "shared infrastructure" already exists (M5.1's `asyncio.gather` pattern at `m5_1_grpc_cohort.py:387`, the M6.1.1 reporter + sweep wiring on the M6.1.1 branch, and the audit baseline at `b63947a`). No foundational tasks needed.

**Checkpoint**: Phase 2 vacuous. User story work begins immediately.

---

## Phase 3: User Story 1 — Restore Real Concurrent Dispatch in the M6 Harness (Priority: P1) 🎯 MVP / PR-1

**Goal**: Replace the sequential `await` dispatch in M6 / M6.1 / M6.1.1 measurement and warmup loops with `asyncio.gather`-based concurrent dispatch (peak in-flight = c per FR-001), preserving seed determinism (FR-002) and the round-robin per-c-batch index allocator (M6 / M6.1 only). Lands the regression test (FR-003 / FR-004) and the `dispatch_mode` strict-superset emission (FR-007).

**Independent Test** (FR-003 + Acceptance Scenario 1.1 / 1.2 / 1.3): `pytest tools/benchmark/tests/test_m6_concurrent_dispatch.py -v` reports peak in-flight equal to cell.concurrency for `(c=1, c=4, c=8) × (m6, m6_1, m6_1_1)` — 9 parametrisations. Failure blocks M6.1.1 PR #27 merge (FR-004).

### Tests for User Story 1 (regression-test-first per project convention)

- [X] T004 [P] [US1] Create the `_ConcurrencyProbe` fake driver and 9-parametrisation peak-in-flight test in `tools/benchmark/tests/test_m6_concurrent_dispatch.py` (per [contracts/dispatch.md](./contracts/dispatch.md) "In-Flight Concurrency Probe (Test Driver)" section + [research.md](./research.md) § R-4); test asserts `probe.peak == c` for `c ∈ {1, 4, 8}` across all three measurement-loop entry points (`_run_measurement`, `_run_measurement_m6_1`, `_measure_cell`)
- [X] T005 [P] [US1] Add warmup-symmetry test to `tools/benchmark/tests/test_m6_concurrent_dispatch.py` covering `c=4` × all three warmup entry points (`_run_warmup`, `_run_warmup_m6_1`, `_measure_cell` warmup loop) — asserts FR-005a
- [X] T006 [P] [US1] Add seed-determinism test to `tools/benchmark/tests/test_m6_concurrent_dispatch.py` covering `c ∈ {1, 4}` × all three entry points — records `(cohort, seed)` tuples emitted by the probe, asserts the *set* equals the pre-fix harness's known-good seed sequence (per FR-002 + Acceptance Scenario 1.4)
- [X] T007 [US1] Run the new test file against the **current (sequential)** harness and confirmed 9 of 18 parametrisations FAIL (peak c≥4 + warmup tests; the c=1 peak cases and seed-set tests pass under both dispatch modes by design — peak=1 trivially holds at c=1, and the seed set is dispatch-mode-invariant). The 9 failures validate the test detects the bug before the fix is applied. (Tasks.md original claim of "all 18 FAIL" was imprecise; 9/9 split is structurally correct.)

### Implementation for User Story 1

- [X] T008 [P] [US1] Patch `tools/benchmark/src/vllm_grpc_bench/m6_sweep.py` two entry points:
  - `_run_warmup` (line 189): replace sequential inner loop with per-(cohort × c-batch) `asyncio.gather(*(_warmup_one() for _ in range(size)))` (preserve the inner retry-until-success loop unchanged); pattern per [contracts/dispatch.md](./contracts/dispatch.md) "Reference Implementation Pattern".
  - `_run_measurement` (line 219): replace `for idx in batch_indices: await _run_one_rpc_with_retry(...)` with per-cohort `await asyncio.gather(*(...))`; preserve `batch_indices` allocation and `compute_rpc_seed(idx, base_seed)` cohort-symmetric mapping (FR-002).
- [X] T009 [P] [US1] Patch `tools/benchmark/src/vllm_grpc_bench/m6_1_sweep.py` two entry points:
  - `_run_warmup_m6_1` (line 141): same pattern as T008's `_run_warmup` fix.
  - `_run_measurement_m6_1` (line 160): same pattern as T008's `_run_measurement` fix.
- [X] T010 [P] [US1] Patch `tools/benchmark/src/vllm_grpc_bench/m6_1_1_sweep.py` `_measure_cell` (line 233):
  - Warmup loop (lines 257–259): per-cohort `asyncio.gather(*(driver(cohort, m6_1_cell, 0) for _ in range(n_warmup)))` (FR-005a symmetric dispatch).
  - Measurement loop (lines 263–268): per-cohort `asyncio.Semaphore(cell.concurrency)`-bounded `asyncio.gather` over `range(n_measurement)` (steady c-in-flight stream); pattern per [contracts/dispatch.md](./contracts/dispatch.md) "Reference Implementation Pattern" M6.1.1 section.
- [X] T011 [P] [US1] Update `concurrency` field docstring on `M6Cell` in `tools/benchmark/src/vllm_grpc_bench/m6_types.py`: revise from "metadata tag for round-robin sequencing" → "actual in-flight parallelism (peak concurrent RPCs per cohort within a c-batch)" (FR-006)
- [X] T012 [P] [US1] Update `concurrency` field docstring on `M6_1Cell` in `tools/benchmark/src/vllm_grpc_bench/m6_1_types.py` (same revision as T011, FR-006) — implemented as an inline alias comment since `M6_1Cell` is `= M6Cell`; the canonical docstring lives on `M6Cell`.
- [X] T013 [P] [US1] Update `concurrency` field docstring on `M6_1_1Cell` in `tools/benchmark/src/vllm_grpc_bench/m6_1_1_types.py` (same revision as T011, FR-006) — same alias-comment treatment.
- [X] T014 [US1] Extend `tools/benchmark/src/vllm_grpc_bench/m6_1_1_reporter.py` to inject a top-level `dispatch_mode: "concurrent"` key into every manifest before `json.dumps` is called; place adjacent to `schema_version` for discoverability per [contracts/output.md](./contracts/output.md) "Emission Rules"; value is unconditional `"concurrent"` (no parameter, no runtime branching — FR-007 strict-superset). Markdown methodology section gains a "Dispatch mode: concurrent" line.
- [X] T015 [US1] Ran the new test file against the **corrected (post-T008–T014) harness** and confirmed all 18 parametrisations PASS.
- [X] T016 [US1] Ran the local lint chain: `ruff check` (clean), `ruff format --check` (165 files clean), `mypy --strict` on the 8 M6.0a-modified files (0 errors). Full-repo `mypy --strict` shows 95 errors total — identical to baseline (0 introduced by M6.0a).
- [X] T017 [US1] Ran the full existing M6 / M6.1 / M6.1.1 unit-test suite: 407 passes. 2 pre-existing failures (`test_torch_pin_bypass_allows_dispatch_attempt`, `test_drift_not_reproduced_confirmed_writes_supersedence`) exist on the M6.0a branch base unrelated to M6.0a. `test_m6_1_1_reporter.py::test_json_has_all_top_level_keys_under_phase_2_pending` legitimately required updating to include the new `dispatch_mode` key (M6.0a FR-007 strict-superset).
- [X] T018 [US1] Pushed branch (`git push -u origin 024-m6-0a-concurrent-dispatch`) at commit `f3ad158`. **PR creation deliberately deferred** at operator request — PR-1 will be opened later when M6.1.1 PR #27 closure timing is confirmed.
- [ ] T019 [US1] After PR-1 merges to `main`, post a cross-link comment on M6.1.1 PR #27 noting the unblock (e.g., "M6.0a PR-1 (#NN) is merged — PR #27 can now rebase on main and proceed to merge gate") — **deferred until PR-1 is opened and merged**

**Checkpoint**: PR-1 merged. M6.1.1 PR #27 is unblocked. The corrected harness emits `dispatch_mode: "concurrent"` on every future M6.1.1 run. US1 complete; US2 may begin.

---

## Phase 4: User Story 2 — Re-run M6.1.1 Phase 1 Under Corrected Dispatch (Priority: P2) / PR-2 first half

**Goal**: Use the corrected harness to run a fresh M6.1.1 Phase 1 sweep against Modal A10G eu-west-1 with audit-baseline version pinning (FR-008), producing the canonical artifact at `docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}` annotated with `dispatch_mode: "concurrent"` (FR-007) and the Phase 2 verdict bucket recorded as a single explicit manifest field (FR-010).

**Independent Test** (FR-008 + FR-010 + Acceptance Scenarios 2.1 / 2.2 / 2.3 / 2.4 / 2.5 / 2.6): the resulting manifest contains `dispatch_mode: "concurrent"`, chat_stream per-cohort `engine_ttft_ms` spreads are reported for `c=1` / `c=4` / `c=8`, and `phase_2_outcome` falls in exactly one of three buckets (`"below 5 %"` / `"at or above 10 %"` / `"intermediate per FR-010 classifier output"`).

### Implementation for User Story 2

- [X] T020 [US2] Lockfile parity confirmed: `git diff b63947a -- uv.lock` is empty (the M6.0a-branch lockfile is already byte-identical to the audit baseline). `uv sync --frozen --all-groups` + `uv pip install -e tools/benchmark` re-installed all workspace + investigation-group packages on the freshly synced env. Verified `torch==2.11.0`; vllm is Modal-side only (not in client venv). **Lessons learned (documented in [[feedback_uv_sync_groups]]-equivalent dispatch-correction note)**: plain `uv sync --frozen` does NOT pull the `investigation` group that supplies `transformers` + `vllm-metal`; the FR-008 lockfile-parity command on macOS is `uv sync --frozen --all-groups`.
- [X] T021 [US2] Modal authentication verified by operator (sweep started successfully against `eu-west-1`).
- [X] T022 [US2] Corrected harness sanity-checked: `dispatch_mode` emission grep returned 3 matches in `m6_1_1_reporter.py:388-394`; torch pin gate confirmed `torch.__version__ == _EXPECTED_TORCH_VERSION == "2.11.0"`; `pytest tools/benchmark/tests/test_m6_concurrent_dispatch.py -q` returned 18 passed in 0.46s on the freshly-synced env.
- [X] T023 [US2] Modal sweep ran 2026-05-17 01:56-02:10 UTC. Cold-start 256.4s (4.27 min), sweep proper 15.6 min wall-clock, total 50/50 successes on all 18 cell × cohort pairs. Cost $0.29 (Modal dashboard). Within SC-002 (≤ 45 min) and SC-006 (≤ $1) budgets.
- [X] T024 [US2] Markdown artifact verified at `docs/benchmarks/m6_1_1-engine-cost-instrumentation.md`: methodology section contains `**Dispatch mode**: concurrent (peak in-flight = c, per M6.0a)` line; multi-point timing table populated with 18 rows (6 cells × 3 cohorts).
- [X] T025 [US2] JSON artifact verified at `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json`: `jq -r '.dispatch_mode'` returns `"concurrent"`; `jq -r '.schema_version'` returns `"m6_1_1.v1"` (unchanged per FR-007); `jq '.phase_2_outcome'` returns `null` (this is a `--m6_1_1-diagnose` Phase 1 run, not `--m6_1_1` Phase 2 — `phase_2_outcome` legitimately null under `phase_2_pending`); 16 top-level keys present including `dispatch_mode` adjacent to `schema_version`.
- [X] T026 [US2] chat_stream per-cohort `engine_ttft_ms` recorded for the dispatch-correction note. **Audit baseline** (sequential dispatch): c=1 spread 19.5%, c=4 spread 6.0%, c=8 spread 8.4%. **M6.0a-corrected** (concurrent dispatch): c=1 spread 13.6% (range 41.22–47.14ms, mean 43.55ms); c=4 spread 15.9% (range 74.01–87.01ms, mean 81.78ms); c=8 spread 16.4% (range 86.93–102.21ms, mean 93.34ms). Side-by-side table lives in [`docs/benchmarks/m6_0a-dispatch-correction.md`](../../docs/benchmarks/m6_0a-dispatch-correction.md) § 4.
- [X] T027 [US2] SC-005 spot-check skipped — the per-cohort spread data in T026 already provides strong evidence the corrected harness produces well-formed engine-cost numbers, and SC-005 was marked optional. Skip documented in the dispatch-correction note's caveat section.

**Checkpoint**: PR-2's data exists. The corrected-dispatch artifact lands at the canonical path with `dispatch_mode: "concurrent"`. The Phase 2 verdict bucket is recorded. US2 complete; US3 may begin.

---

## Phase 5: User Story 3 — Publish the Dispatch-Correction Note (Priority: P3) / PR-2 second half

**Goal**: Author `docs/benchmarks/m6_0a-dispatch-correction.md` (the standalone explainer per FR-012 / FR-013) and add the methodology-supersedence cross-link annotation to M6.1's published narrative (FR-016). Ship PR-2 with both the corrected-dispatch artifact from US2 and the dispatch-correction note from US3.

**Independent Test** (FR-012 + FR-013 + SC-007): the dispatch-correction note exists at the spec-mandated path, contains a side-by-side per-cohort spread table comparing audit baseline vs corrected run, and the four mandated cross-links (audit baseline, corrected run, PR #27, PLAN.md M6.0a section) all resolve. A reader can determine in ≤ 5 min which M6.x findings are dispatch-sensitive vs robust (SC-007).

### Implementation for User Story 3

- [X] T028 [P] [US3] Authored `docs/benchmarks/m6_0a-dispatch-correction.md` with the 6 mandated sections + side-by-side spread table + dispatch-sensitive-vs-robust 3-row table + bulleted cross-links to audit baseline, corrected run, PR #27, PLAN.md M6.0a section, and the M6.0a spec directory.
- [X] T029 [P] [US3] Added "## Methodology Supersedence (M6.0a — Dispatch-Correction)" section to `docs/benchmarks/m6_1-real-prompt-embeds.md` per FR-016 — one-paragraph forward pointer placed between the existing "Methodology Notes" and "Operator Reproducibility" sections. Body content of original M6.1 narrative unchanged otherwise.
- [X] T030 [US3] All four cross-links verified: (a) audit baseline file exists (7175 bytes); (b) corrected-run `.md` + `.json` both exist; (c) PR #27 `gh pr view` returns state OPEN; (d) `docs/PLAN.md` contains the M6.0a section heading (line 188).
- [X] T031 [US3] Audit baseline byte-identical to `b63947a`: `git diff b63947a -- docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md` returns empty.
- [X] T032 [US3] Local lint chain clean (4 gates): `ruff check` (all passed), `ruff format --check` (165 files clean), `mypy --strict` on 8 M6.0a files (0 errors), `pytest test_m6_concurrent_dispatch.py + test_m6_1_1_reporter.py` (47 passed).
- [X] T033 [US3] Files to stage are: `docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}`, `docs/benchmarks/m6_0a-dispatch-correction.md`, `docs/benchmarks/m6_1-real-prompt-embeds.md`, plus the documentation-artifact updates (ANALYSIS.md, README.md, docs/PLAN.md, specs/024-m6-0a-concurrent-dispatch/tasks.md). Memory file `project_status.md` and new `feedback_pr_creation_deferred.md` are outside the repo (in `~/.claude/`).
- [X] T034 [US3] Commit + push completed at branch `024-m6-0a-concurrent-dispatch`. **PR creation deliberately deferred** per operator's earlier `commit this and push. no PR` instruction — re-applies to PR-2; PR will be opened later. See [[feedback_pr_creation_deferred]].

**Checkpoint**: PR-2 open. The full M6.0a deliverable (harness fix + regression test + corrected artifact + dispatch-correction note + M6.1 annotation) is on `main` once PR-2 merges. M6.0a complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Confirm all success criteria are closed and update durable project state.

- [X] T035 SC-001 closed: `test_m6_concurrent_dispatch.py` reports 18/18 passed in 0.18s.
- [X] T036 SC-002 closed: 15.6 min wall-clock for the corrected re-run (cold-start 4.27 min + sweep 11.3 min), well under 45 min.
- [X] T037 SC-003: `phase_2_outcome = null` because this is a Phase 1 (`--m6_1_1-diagnose`) run; the spec's three-bucket criterion applies to Phase 2 (`--m6_1_1`) runs. Per-cell `phase_1_classifications` are recorded as `channel_dependent_batching × 3` (FR-010 classifier output, classifier-degenerate per audit baseline header).
- [X] T038 SC-004 partially closed: dispatch-correction note cross-linked from PLAN.md M6.0a section (delivered annotation + cross-link to `docs/benchmarks/m6_0a-dispatch-correction.md`). PR #27 review-thread cross-link comment **deferred** until PR-1 is opened — see [[feedback_pr_creation_deferred]].
- [X] T039 SC-005 closed (deferred / acknowledged): T027 spot-check skipped per task description allowance. Skip noted in dispatch-correction note caveats.
- [X] T040 SC-006 closed: Modal compute cost confirmed by operator at **$0.29** for the corrective re-run, well under $1.
- [X] T041 SC-007 closed: dispatch-correction note authored with explicit "Implication for M6.x findings" 3-row table (M6 main = dispatch-robust; M6.1 main = dispatch-robust; M6.1 per-cohort drift sub-finding = dispatch-sensitive but classifier-degenerate). Reader can determine in ≤ 5 min which M6.x findings need re-interpretation.
- [X] T042 [P] Updated `~/.claude/projects/-Users-bsansom-projects-vllm-grpc/memory/project_status.md` to reflect M6.0a delivery + M6.1.1 Phase 2 blocker + classifier degeneracy. New memory `feedback_pr_creation_deferred.md` captures the push-vs-PR-gate distinction surfaced during this milestone.
- [X] T043 [P] Updated `docs/PLAN.md` M6.0a section heading from `(planned, blocks M6.1.1 closure)` to `(delivered 2026-05-17)` with a delivery callout summarising headline finding + cost + classifier-degeneracy caveat. Original planning narrative preserved as `#### Original planning narrative (pre-delivery)` subsection.
- [X] T044 [P] FR-014 / FR-015 harness-only scope verified: `git diff b63947a -- proxy/ frontend/ client/ proto/ scripts/python/modal_bench_rest_grpc_server.py packages/frontend/ docs/benchmarks/m6.md docs/benchmarks/m6-real-engine-mini-validation.md` returns empty. `git diff b63947a -- docs/benchmarks/m6_1-real-prompt-embeds.md` contains only the FR-016 cross-link annotation block (additive paragraph between Methodology Notes and Operator Reproducibility).

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
