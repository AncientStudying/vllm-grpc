---

description: "Task list for v0.0.0 — Post-M6.2 Housekeeping"
---

# Tasks: v0.0.0 — Post-M6.2 Housekeeping

**Input**: Design documents from `specs/028-post-m6.2-cleanup-v0.0.0/`
**Prerequisites**: spec.md ✅, plan.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅. No contracts/ directory (intentional — no external interface).

**Tests**: This is a repo-maintenance feature, not a code feature. No new test files are written. Verification happens through the existing `make lint typecheck test` gate (FR-013), the M6.2 fake-backed smoke (FR-014), and direct file-state inspection (`ls`, `git ls-files`, `git check-ignore`). Tasks below mark verification commands inline; they are not test files.

**Organization**: Tasks are grouped by the three user stories from spec.md. The plan packages them into five PR commits + one post-merge tag; the task numbering follows that commit order so an implementer can work top-to-bottom without back-references.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1 / US2 / US3)
- Include exact file paths in descriptions

## Path Conventions

- Repository root: `/Users/bsansom/projects/vllm-grpc/` (absolute) or `.` (relative when noted).
- Spec/plan artifacts live under `specs/028-post-m6.2-cleanup-v0.0.0/`.
- All deletion targets are under `docs/`, `tests/`, `scripts/`, `logs/`, or repo root per `data-model.md` Entity 1.
- No source-code paths (under `tools/benchmark/src/`, `packages/`, `proto/`, `frontend/`) are touched (FR-001).

---

## Phase 1: Setup (Pre-cleanup verification + baseline)

**Purpose**: Capture the pre-cleanup baseline that SC-002 (≥3 MB reduction) compares against, and confirm preconditions hold.

- [ ] T001 Record baseline directory sizes by running `du -sh docs/benchmarks/ tests/integration/ scripts/python/ scripts/setup/ M6_2-ANALYSIS-FRAMING-DRAFT.md logs/ 2>&1 | tee /tmp/v0.0.0-baseline.txt`; confirm the total is ≈3.5 MB.
- [ ] T002 [P] Verify all 16 milestone tags are present locally by running `git fetch --tags origin && git tag --list 'milestone/*' | wc -l`; expected output is `16`. Abort the run and fix tag fetching if fewer.
- [ ] T003 [P] Re-confirm `summary.md` reference line numbers haven't shifted since spec authoring by running `grep -n "summary\.md" ANALYSIS.md docs/PLAN.md`; expected hits at `ANALYSIS.md:5`, `ANALYSIS.md:14`, `ANALYSIS.md:64`, `docs/PLAN.md:869`. If any line number has shifted, update the Phase 3 ANALYSIS / PLAN edit tasks to point at the new line numbers before proceeding.
- [ ] T004 [P] Confirm `make lint typecheck test` passes on the current `chore/post-m6.2-cleanup-v0.0.0` branch HEAD before any cleanup begins by running `make lint typecheck test`; abort if anything is red so a pre-existing failure isn't blamed on this branch's work.
- [ ] T005 [P] Confirm the M6.2 fake-backed validate smoke passes on the current branch HEAD by running the project's fake-backed M6.2 smoke (e.g. `python -m vllm_grpc_bench --m6_2-validate-fake` or `make test-m6.2-fake` depending on the harness CLI exposed in `tools/benchmark/`); abort if red.

**Checkpoint**: Baseline captured at `/tmp/v0.0.0-baseline.txt`; toolchain green; tags present. Cleanup work can begin.

---

## Phase 2: Foundational

**Purpose**: None. This is a maintenance feature with no shared infrastructure to build — every deletion + edit operates on existing files. The phase is intentionally empty so the task numbering follows commit order.

**⚠️ No blocking prerequisites beyond Phase 1's preconditions.**

---

## Phase 3: User Story 1 — Operator finds a clean working tree on `main` (Priority: P1) 🎯 MVP

**Goal**: Remove the ~50 pre-M6.2 milestone artifacts, obsolete integration tests, stale scripts, and the root draft note from the working tree, plus rewrite the four `summary.md` references that would otherwise dangle. Ships as **Commit 1** of the PR.

**Independent Test**: `ls docs/benchmarks/` after Commit 1 returns only `m6_2-*` files; `ls tests/integration/` returns only the six retained files; `ls M6_2-ANALYSIS-FRAMING-DRAFT.md scripts/python/reprocess_m5_supersede.py scripts/setup/phase2-env.sh` all return "No such file or directory"; `grep -n "summary\.md" ANALYSIS.md docs/PLAN.md` returns no output; `make lint typecheck test` and the M6.2 fake-backed smoke both stay green.

### Implementation for User Story 1

- [ ] T006 [P] [US1] Delete the root draft note: `git rm M6_2-ANALYSIS-FRAMING-DRAFT.md`. (Covers FR-002; data-model row 1.)
- [ ] T007 [P] [US1] Delete the 18 pre-M3 `docs/benchmarks/phase-*` files (rows 2–19 of `data-model.md` Entity 1) by running the multi-arg `git rm` command from `quickstart.md` Step 1 covering `phase-3-*`, `phase-4.2-*`, `phase-5-*`, `phase-6-*`. (Covers FR-003 partial.)
- [ ] T008 [P] [US1] Delete the M3/M4/M5 milestone benchmark files (rows 20–32 of `data-model.md` Entity 1): the `m3-channel-tuning*`, `m4-time-axis-tuning*`, `m5-cross-host-validation*`, `m5_1-rest-vs-grpc*`, `m5_2-transport-vs-tuning*` set via `git rm`. (Covers FR-003 continued.)
- [ ] T009 [P] [US1] Delete the M6 / M6.0a / M6.1 / M6.1.1 / M6.1.2 / M6.1.3 milestone benchmark files (rows 33–46 of `data-model.md` Entity 1) via `git rm`, including `m6_0a-dispatch-correction.md`, the `m6-real-engine-mini-validation*`, `m6_1-real-prompt-embeds*`, `m6_1_1-*`, `m6_1_2-*`, `m6_1_3-*` sets. Be careful NOT to delete any `m6_2-*` file (those are M6.2 retained). (Covers FR-003 final.)
- [ ] T010 [P] [US1] Delete `docs/benchmarks/summary.md` (row 47 of `data-model.md` Entity 1) via `git rm docs/benchmarks/summary.md`. (Covers the FR-003 extension from the 2026-05-26 clarification.)
- [ ] T011 [P] [US1] Delete the obsolete integration tests (rows 48–52 of `data-model.md` Entity 1) by running `git rm tests/integration/test_m4_schema_e2e.py tests/integration/test_m4_sweep_e2e.py tests/integration/test_m5_modal_smoke.py tests/integration/test_m5_1_modal_smoke.py tests/integration/test_m5_2_modal_smoke.py`. (Covers FR-004.)
- [ ] T012 [P] [US1] Delete the two stale scripts (rows 53–54 of `data-model.md` Entity 1): `git rm scripts/python/reprocess_m5_supersede.py scripts/setup/phase2-env.sh`. (Covers FR-005 and FR-006.)
- [ ] T013 [US1] Rewrite `ANALYSIS.md` line 5 per `data-model.md` Entity 3 row 1 (drop "now lives as a one-line redirect"; add "recoverable from any milestone tag through `milestone/m6.1.3-attribution`"). Use the Edit tool on `ANALYSIS.md`. (Covers FR-003a partial. Must run **before** T014 / T015 because they edit the same file.)
- [ ] T014 [US1] Rewrite `ANALYSIS.md` line 14 per `data-model.md` Entity 3 row 2 (remove the markdown link to `summary.md`; preserve "(folded in below)"; reroute the phase-* source-data citation through the new housekeeping subsection). Edit `ANALYSIS.md`. (Sequential after T013 — same file.)
- [ ] T015 [US1] Rewrite `ANALYSIS.md` line 64 per `data-model.md` Entity 3 row 3 (replace the parenthetical to acknowledge the deleted summary.md and cite `milestone/m3-grpc-tuning-r1` for the pre-fold-in text). Edit `ANALYSIS.md`. (Sequential after T014.)
- [ ] T016 [P] [US1] Remove the entire `docs/PLAN.md` line 869 bullet per `data-model.md` Entity 3 row 4 ("- A short benchmark write-up at `docs/benchmarks/summary.md`…"). Edit `docs/PLAN.md`. (Parallelizable with T013–T015 — different file.)
- [ ] T017 [US1] Verify deletion completeness by running these checks in `quickstart.md` Step 1's verification block: `test ! -e M6_2-ANALYSIS-FRAMING-DRAFT.md && echo "FR-002 OK"`; `ls docs/benchmarks/ | grep -cE '^(phase-|m3-|m4-|m5-|m5_1-|m5_2-|m6-|m6_0a-|m6_1-|m6_1_1-|m6_1_2-|m6_1_3-)|^summary\.md$'` returns `0` (note: prefix alternatives are anchored only at start-of-string — trailing `$` would make each prefix require an exact match, silently disarming the gate; `m6_0a-` is included explicitly because `m6-` only matches a literal `m6-` hyphen, not the `m6_0a-` underscore form); `ls tests/integration/` shows exactly six files (`__init__.py`, `conftest.py`, `fake_frontend.py`, `test_chat_bridge.py`, `test_completions_bridge.py`, `test_grpc_client.py`); `grep -n "benchmarks/summary\.md" ANALYSIS.md docs/PLAN.md README.md` returns no output. Abort the commit if any check fails.
- [ ] T018 [US1] Run `make lint typecheck test`; expect exit code 0. (Covers FR-013 / SC-005 partial — this is the toolchain gate immediately before Commit 1.)
- [ ] T019 [US1] Run the M6.2 fake-backed smoke (the same invocation used in T005); expect exit code 0. (Covers FR-014 / SC-006 partial.)
- [ ] T020 [US1] Create Commit 1 with the message body from `quickstart.md` Step 1 (single-line subject "`v0.0.0(1/5): trim pre-M6.2 milestone artifacts + obsolete tests`" + multi-paragraph body listing the path → tag map reference). Stage all the deletions + ANALYSIS/PLAN edits with `git add -u` only (do NOT use `git add .` — avoid bundling other untracked items like the next phase's checkpoint un-tracking).

**Checkpoint**: Commit 1 lands cleanly. `git log -1 --stat` shows ~52 file changes (47 deletions + ANALYSIS edits + PLAN edit) and zero changes outside the deletion / edit set. US1 acceptance scenarios 1–6 all pass.

---

## Phase 4: User Story 2 — Operator stops accidentally committing local sweep logs (Priority: P2)

**Goal**: Un-track the `logs/` directory and the M6.2 checkpoint file that the `after_specify` auto-commit bundled, then add `.gitignore` rules so neither pattern can re-enter the index. Ships as **Commits 2, 3, and 4** of the PR.

**Independent Test**: After Commit 4, `git ls-files logs/` returns empty; `git ls-files docs/benchmarks/` contains no `*.checkpoint.jsonl` entries; `git check-ignore -v logs/probe.log` and `git check-ignore -v docs/benchmarks/anything.checkpoint.jsonl` both successfully match the new rules; the M6.2 checkpoint file still exists on disk locally; M6.2 final `.json` and `.md` outputs remain tracked.

### Implementation for User Story 2

- [ ] T021 [US2] Un-track the `logs/` directory by running `git rm -r --cached logs/` from repo root. The directory and its 13 entries (11 M4 logs + `m4-full.current` + `m4-full.pid`) leave the index but stay on disk. (Covers FR-008 logs portion.)
- [ ] T022 [US2] Verify the logs un-tracking with `git ls-files logs/ | wc -l` (expected `0`) and `ls logs/ | wc -l` (expected `13` — files still on disk locally).
- [ ] T023 [US2] Create Commit 2 with message subject "`v0.0.0(2/5): un-track logs/ (M4 sweep stdout captures)`" and the body from `quickstart.md` Step 2.
- [ ] T024 [US2] Un-track the M6.2 sweep checkpoint by running `git rm --cached docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl`. The file stays on disk. (Covers FR-008 checkpoint portion.)
- [ ] T025 [US2] Verify the checkpoint un-tracking with `git ls-files docs/benchmarks/ | grep checkpoint` (expected: empty output) and `test -e docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl && echo "On-disk OK"` (expected: `On-disk OK`).
- [ ] T026 [US2] Create Commit 3 with message subject "`v0.0.0(3/5): un-track M6.2 sweep checkpoint`" and the body from `quickstart.md` Step 3.
- [ ] T027 [US2] Append the `.gitignore` rules per `data-model.md` Entity 2 by running `cat >> .gitignore <<'EOF' \n\n# v0.0.0 housekeeping (per spec FR-007)\nlogs/\n**/*.checkpoint.jsonl\nEOF`. (Covers FR-007.)
- [ ] T028 [US2] Verify the new rules with `git check-ignore -v logs/probe.log` (expect a match line citing `.gitignore:<line> logs/`); `git check-ignore -v docs/benchmarks/anything.checkpoint.jsonl` (expect a match line citing `.gitignore:<line> **/*.checkpoint.jsonl`); `git check-ignore -v docs/benchmarks/m6_2-token-budget.json` (expect **no output** — the M6.2 final `.json` MUST NOT be ignored).
- [ ] T029 [US2] Run `make lint typecheck test`; expect exit code 0. (FR-013 / SC-005 partial — the toolchain gate before Commit 4.)
- [ ] T030 [US2] Create Commit 4 with message subject "`v0.0.0(4/5): gitignore logs/ and checkpoint files`" and the body from `quickstart.md` Step 4. Stage only `.gitignore` with `git add .gitignore`.

**Checkpoint**: Commits 2, 3, and 4 all on branch. `git ls-remote` is not yet involved — these are local commits ahead of `origin/chore/post-m6.2-cleanup-v0.0.0`. US2 acceptance scenarios 1–3 all pass.

---

## Phase 5: User Story 3 — Reader discovers how to recover historical material (Priority: P3)

**Goal**: Append a `## Repo housekeeping` section to `ANALYSIS.md` documenting the `v*` / `milestone/*` dual-track convention and the canonical `git show <tag>:<path>` recovery incantation. Ships as **Commit 5** of the PR.

**Independent Test**: After Commit 5, `grep -n "^## Repo housekeeping$" ANALYSIS.md` returns exactly one match. A reader following the subsection's `git show milestone/m5.2-transport-tuning:docs/benchmarks/m5_2-transport-vs-tuning.md` example successfully retrieves the deleted M5.2 report in well under 30 seconds (SC-007).

### Implementation for User Story 3

- [ ] T031 [US3] Append the new `## Repo housekeeping` section to the end of `ANALYSIS.md` using the content shape from `research.md` § R7 (verbatim — ~15 lines covering the two tag tracks + the recovery command + a pointer to `git tag --list 'milestone/*'`). Insert AFTER the last existing milestone narrative section but BEFORE any closing footer if one exists. (Covers FR-009, FR-010, FR-011.)
- [ ] T032 [US3] Verify section presence and placement by running `MATCH_LINE=$(grep -n "^## Repo housekeeping$" ANALYSIS.md | cut -d: -f1)` and `TOTAL_LINES=$(wc -l < ANALYSIS.md)`; expect exactly one match line, and confirm `MATCH_LINE` is within the last 20% of the file (i.e., `MATCH_LINE × 5 ≥ TOTAL_LINES × 4`). The placement check enforces FR-011 (the subsection must not interrupt the milestone-by-milestone narrative — end-of-document placement satisfies this).
- [ ] T033 [US3] Verify the documented recovery command works by running `time git show milestone/m5.2-transport-tuning:docs/benchmarks/m5_2-transport-vs-tuning.md | head -1`; expect the M5.2 report's first line returned in sub-second wall-clock time. This proves the 30-second SC-007 ceiling holds with margin.
- [ ] T034 [US3] Run `make lint typecheck test`; expect exit code 0. (FR-013 / SC-005 partial — toolchain gate before Commit 5; lint should not care about markdown but the gate is the gate.)
- [ ] T035 [US3] Create Commit 5 with message subject "`v0.0.0(5/5): ANALYSIS.md \"Repo housekeeping\" section`" and the body from `quickstart.md` Step 5. Stage only `ANALYSIS.md` with `git add ANALYSIS.md`.

**Checkpoint**: All five PR commits on the branch. The branch is ready to push and open a PR against `main`. US3 acceptance scenarios 1–3 all pass.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final verification gates, PR submission, and the post-merge `v0.0.0` tag creation (Commit 6 of the conceptual six-step sequence).

- [ ] T036 [P] Compute the working-tree reduction by running `du -sh docs/benchmarks/ tests/integration/ scripts/python/ scripts/setup/ logs/ 2>&1 | tee /tmp/v0.0.0-after.txt`; compare against `/tmp/v0.0.0-baseline.txt` (from T001). Confirm the delta is ≥3 MB. (SC-002 verification.)
- [ ] T037 [P] Spot-check tag recovery for at least one representative file per milestone tag by running `git show milestone/m3-grpc-tuning-r1:docs/benchmarks/m3-channel-tuning.md | head -1`, `git show milestone/m4-time-axis:docs/benchmarks/m4-time-axis-tuning.md | head -1`, `git show milestone/m5.2-transport-tuning:docs/benchmarks/m5_2-transport-vs-tuning.md | head -1`, `git show milestone/m6.1.3-attribution:docs/benchmarks/m6_1_3-attribution-closure.md | head -1`, `git show milestone/m4-time-axis:logs/m4-full-20260510-103956.log | head -1`. All must return content. (SC-004 verification.)
- [ ] T038 [P] Run a final pre-push verification of the entire branch: (a) `make lint typecheck test` exit code 0; (b) M6.2 fake-backed smoke exit code 0; (c) `git status` clean; (d) `git diff --name-only fea31c0..HEAD -- tools/benchmark/src/ packages/ proto/ frontend/ | wc -l` returns `0` (FR-001 source-preservation invariant — confirms no file under the protected source trees was modified by any of Commits 1–5). (Last-chance FR-001 / FR-013 / FR-014 / SC-005 / SC-006 gate.)
- [ ] T039 Push the branch to origin: `git push -u origin chore/post-m6.2-cleanup-v0.0.0`.
- [ ] T040 Open the PR via `gh pr create --base main --title "v0.0.0 — Post-M6.2 housekeeping" --body "$(cat …)"` using the PR body template from `quickstart.md` Step 7. Capture the PR URL for the implementer's records.
- [ ] T041 **[POST-MERGE]** After the PR merges to `main`, switch to `main` and pull: `git checkout main && git pull origin main`. Confirm the merge commit hash and that the branch is fast-forwarded.
- [ ] T042 **[POST-MERGE]** Create the annotated `v0.0.0` tag on the merge commit using the message body from `research.md` § R8 and `quickstart.md` Step 8: `git tag -a v0.0.0 -m "$(cat …)"`. (Covers FR-015.)
- [ ] T043 **[POST-MERGE]** Push the new tag to origin: `git push origin v0.0.0`.
- [ ] T044 **[POST-MERGE]** Final SC-008 verification: `git ls-remote --tags origin v0.0.0 milestone/m6.2-token-budget`. Expect both tags present on origin. Capture the output for the cleanup PR's release notes.
- [ ] T045 **[POST-MERGE]** Final SC-003 verification: clone the repo into a scratch directory on a sweep-naive machine and confirm `git status` is clean: `git clone https://github.com/AncientStudying/vllm-grpc.git /tmp/v000-fresh && cd /tmp/v000-fresh && git status`. Expect "nothing to commit, working tree clean." Remove the scratch clone after verification.

**Checkpoint**: All eight success criteria (SC-001 through SC-008) verified. Both annotated tags (`v0.0.0` and `milestone/m6.2-token-budget`) live on origin. The branch is merged. v0.0.0 ships.

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (Setup)**: No dependencies. T001 must complete first (baseline measurement); T002–T005 can run in parallel after T001.
- **Phase 2 (Foundational)**: Empty. Phase 3 may begin once Phase 1 checkpoint is satisfied.
- **Phase 3 (US1)**: Depends on Phase 1 checkpoint. Cannot begin until baseline is captured and toolchain is confirmed green.
- **Phase 4 (US2)**: Depends on Phase 3 (Commit 1) being on the branch — otherwise Commit 2's `git rm -r --cached logs/` lands in a tree that still has the un-cleaned deletion noise, which complicates the per-commit verification.
- **Phase 5 (US3)**: Depends on Phase 4 (Commits 2–4) being on the branch — US3 documents the housekeeping convention that includes the gitignore mechanism added by US2.
- **Phase 6 (Polish)**: Depends on Phases 3–5 (Commits 1–5) being on the branch.
  - T036–T038 (pre-push verification) run in parallel.
  - T039 (push) must complete before T040 (PR open).
  - T041–T045 (`[POST-MERGE]`) are gated by the PR merge event — these are not done in the same session as the cleanup work; they are the operator's post-merge runbook.

### User-story dependencies (sequential, not parallel)

This feature is unusual in that the three user stories are NOT independent in *execution* order even though each is *independently testable* per the spec. The reason: all three stories share the same five-commit PR shape (per the 2026-05-26 commit-shape clarification), and each commit builds on the previous one's tree state. So:

- **US1 (P1)** ships in Commit 1 — the working-tree foundation that US2/US3 build on.
- **US2 (P2)** ships in Commits 2, 3, 4 — operates on the post-US1 tree state.
- **US3 (P3)** ships in Commit 5 — references the housekeeping convention finalized by US2's gitignore rules.

A parallel-team-strategy interpretation does NOT apply here. One operator executes Phases 1–6 top-to-bottom.

### Within each user story

- Verification (`make lint typecheck test`, M6.2 smoke, `git ls-files` / `git check-ignore`) runs **before** the corresponding commit, not after. A red gate aborts the commit.
- Edits to the same file are sequential (T013 → T014 → T015 on `ANALYSIS.md`); edits to different files are parallel-marked.
- `git add` is always scoped (`git add -u`, `git add <specific-files>`) — never `git add .` (that's how the `after_specify` hook bundled the checkpoint file unintentionally).

### Parallel opportunities

- **Phase 1**: T002–T005 in parallel after T001.
- **Phase 3** deletions: T006–T012 in parallel (different file sets). T013–T015 sequential within `ANALYSIS.md`. T016 parallel with T013–T015 (different file).
- **Phase 6** pre-push verifications: T036, T037, T038 in parallel.

---

## Parallel Example: Phase 3 (User Story 1) deletions

The seven deletion task groups touch disjoint path sets and can be executed concurrently in a single batched session:

```bash
# All seven `git rm` operations can be issued together; final commit is a single staging step.
git rm M6_2-ANALYSIS-FRAMING-DRAFT.md &
git rm docs/benchmarks/phase-3-modal-comparison.md docs/benchmarks/phase-3-modal-grpc-baseline.json … &  # T007
git rm docs/benchmarks/m3-channel-tuning.json docs/benchmarks/m3-channel-tuning.md … &  # T008
git rm docs/benchmarks/m6_0a-dispatch-correction.md docs/benchmarks/m6_1_3-attribution-closure.md … &  # T009
git rm docs/benchmarks/summary.md &  # T010
git rm tests/integration/test_m4_schema_e2e.py tests/integration/test_m4_sweep_e2e.py tests/integration/test_m5_modal_smoke.py tests/integration/test_m5_1_modal_smoke.py tests/integration/test_m5_2_modal_smoke.py &  # T011
git rm scripts/python/reprocess_m5_supersede.py scripts/setup/phase2-env.sh &  # T012
wait
```

(In practice, `git rm` is fast enough that running them sequentially is fine; the `[P]` marker is more semantic than performance-critical here.)

---

## Implementation Strategy

### MVP (User Story 1 only)

Phase 1 → Phase 3 → STOP. After Commit 1 lands, the repository is materially cleaner: 52 files removed, ~3 MB reduction, `git status` quiet. US2 and US3 are improvements on top — necessary for the full v0.0.0 beat but skippable for an experimental short-PR if needed.

### Incremental delivery

Each commit is a complete, independently-revertable increment:

- Commit 1 (US1) → cleaner working tree.
- Commit 2 (US2-partial) → `logs/` un-tracked.
- Commit 3 (US2-partial) → checkpoint un-tracked.
- Commit 4 (US2-partial) → `.gitignore` rules.
- Commit 5 (US3) → housekeeping subsection.
- Commit 6 (Polish) → `v0.0.0` tag pushed.

Reverting any single commit leaves the prior state functional (e.g., reverting Commit 4 alone re-enables tracking of any new `logs/` or checkpoint files but doesn't undo the deletions; reverting Commit 1 restores the pre-cleanup tree).

### Single-operator strategy (canonical here)

One operator runs Phase 1 → Phase 3 → Phase 4 → Phase 5 → Phase 6 in sequence. Total time: ~10–15 minutes for the local work, dominated by `make lint typecheck test` runtime (which dominates Phases 3, 4, 5 verification steps). Post-merge tasks (Phase 6 T041–T045) add ~5 minutes after the PR merges.

---

## Notes

- `[P]` tasks operate on different files — safe to interleave or parallelize.
- `[Story]` label maps each task to one of US1 (clean tree), US2 (logs + checkpoint ignore), US3 (ANALYSIS doc pointer).
- No test files are written; the verification is via the existing `make lint typecheck test` gate, the M6.2 fake-backed smoke, and direct filesystem inspection.
- Every commit message follows the format `v0.0.0(N/5): <subject>` with a multi-paragraph body. The exact bodies are in `quickstart.md` Steps 1–5.
- The post-merge tag (T042) uses the message body from `research.md` § R8. Do not lightweight-tag — annotated tags are the project convention.
- If a verification gate (T017, T018, T019, T022, T025, T028, T029, T032, T033, T034, T036, T037, T038) fails, **stop**, fix the root cause, and re-run the gate. Do not advance past a red gate.
