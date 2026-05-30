---

description: "Task list for v0.0.0 — Post-M6.2 Housekeeping (re-derived 2026-05-26 after FR-003 exception clarification)"
---

# Tasks: v0.0.0 — Post-M6.2 Housekeeping

**Input**: Design documents from `specs/028-post-m6.2-cleanup-v0.0.0/`
**Prerequisites**: spec.md ✅ (amended 2026-05-26 with 4 added clarifications), plan.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅. No `contracts/` directory (intentional — no external interface).

**Tests**: This is a repo-maintenance feature, not a code feature. No new test files are written. Verification happens through the existing `make check` gate (FR-013 + FR-014 — M6.2 fake-backed CLI tests `test_m6_2_validate_cli.py` + `test_m6_2_publish_cli.py` are part of `make test`) and direct file-state inspection (`ls`, `git ls-files`, `git check-ignore`). Tasks below mark verification commands inline; they are not test files.

**Organization**: Tasks are grouped by the three user stories from spec.md. The plan packages them into five PR commits + one post-merge tag; the task numbering follows that commit order so an implementer can work top-to-bottom without back-references.

**Key constraint** (per 2026-05-26 clarification — FR-003 exception): The 9 baseline-chain JSONs that `tools/benchmark/src/` reads at runtime MUST NOT be deleted. See data-model.md Entity 2 for the audit anchor command. These 9 files are explicitly excluded from the deletion-target list in T007–T009.

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

**Purpose**: Capture the pre-cleanup baseline that SC-002 (≥50 fewer tracked files) compares against, and confirm preconditions hold.

- [X] T001 Record baseline tracked-file count and directory sizes by running `git ls-files | wc -l | tee /tmp/v0.0.0-file-count-baseline.txt` (the SC-002 primary metric per the 2026-05-26 clarification) and `du -sh docs/benchmarks/ tests/integration/ scripts/python/ scripts/setup/ M6_2-ANALYSIS-FRAMING-DRAFT.md logs/ 2>&1 | tee /tmp/v0.0.0-size-baseline.txt` (headline framing only — NOT the SC-002 floor). Expected file count: ≈1180 tracked files; expected sizes: `docs/benchmarks 3.4M`, `tests/integration 152K`, `scripts/python 360K`, `scripts/setup 4K`, `M6_2-ANALYSIS-FRAMING-DRAFT.md 16K`, `logs 52K`. **DONE 2026-05-26 (resumed cycle)**.
- [X] T002 [P] Verify all 16 milestone tags are present locally by running `git fetch --tags origin && git tag --list 'milestone/*' | wc -l`; expected output is `16`. Abort the run and fix tag fetching if fewer. **DONE 2026-05-26**: 16 tags present.
- [X] T003 [P] Re-confirm `summary.md` reference line numbers haven't shifted since spec authoring by running `grep -n "summary\.md" ANALYSIS.md docs/PLAN.md`; expected hits at `ANALYSIS.md:5`, `ANALYSIS.md:14`, `ANALYSIS.md:64`, `docs/PLAN.md:869`. If any line number has shifted, update the Phase 3 ANALYSIS / PLAN edit tasks to point at the new line numbers before proceeding. **DONE**: hits at exact expected line numbers.
- [X] T004 [P] Confirm `make check` exit code 0 (or no-regression-vs-`fea31c0`) on the current `chore/post-m6.2-cleanup-v0.0.0` branch HEAD by running `make check`. **NOTE per FR-013 framing**: "no regression vs `fea31c0`" — pre-existing failures inherited from `fea31c0` are acceptable. **DONE 2026-05-26 (resumed cycle, post-FR-003 exception restoration)**: 1575 passed / 0 failed / 2 skipped. The previously-failing M4 tests (`test_m4_schema_e2e.py`, `test_m4_sweep_e2e.py`) have been deleted in the staged worktree, so the gate is currently green.
- [X] T005 [P] Confirm the M6.2 fake-backed validate smoke (the `--m6_2-validate --m6_2-skip-deploy` stub-backed CLI tests `test_m6_2_validate_cli.py` + `test_m6_2_publish_cli.py` exercised by `make test`) passes on the current branch HEAD. **DONE**: both M6.2 CLI tests passed within the 1575 passing tests in T004.
- [X] T005a [P] **NEW (post-clarify gate)**: Verify the FR-003 exception list is satisfied — the 9 baseline-chain JSONs MUST exist on disk before commit 1 lands. Run `for f in m3-channel-tuning-time.json m4-time-axis-tuning.json m5-cross-host-validation.json m5_1-rest-vs-grpc.json m5_2-transport-vs-tuning.json m6-real-engine-mini-validation.json m6_1-real-prompt-embeds.json m6_1_1-engine-cost-instrumentation.json m6_1_3-attribution-closure.json; do test -e "docs/benchmarks/$f" || echo "MISSING: $f"; done`. Expected: no output. Then validate the audit anchor: `grep -hoE 'docs/benchmarks/[^"'\'']+\.json' tools/benchmark/src/vllm_grpc_bench/*.py | sort -u | while read p; do test -e "$p" && echo "$p"; done | grep -v 'm6_2-' | wc -l` returns `9`. **DONE 2026-05-26**: all 9 baseline-chain JSONs verified present.

**Checkpoint**: Baseline captured at `/tmp/v0.0.0-file-count-baseline.txt`; toolchain green; tags present; FR-003 exception list verified. Cleanup work can begin.

---

## Phase 2: Foundational

**Purpose**: None. This is a maintenance feature with no shared infrastructure to build — every deletion + edit operates on existing files. The phase is intentionally empty so the task numbering follows commit order.

**⚠️ No blocking prerequisites beyond Phase 1's preconditions.**

---

## Phase 3: User Story 1 — Operator finds a clean working tree on `main` (Priority: P1) 🎯 MVP

**Goal**: Remove the ~37 pre-M6.2 milestone `.md` writeups + 2 output-only JSONs + 1 events sidecar + 13 phase-* files + summary.md in `docs/benchmarks/`, 5 obsolete integration tests, 2 stale scripts, and the root draft note. Plus rewrite the four `summary.md` references. **Retain the 9 baseline-chain JSONs per FR-003 exception**. Ships as **Commit 1** of the PR (45 file-index removals + 4 doc edits).

**Independent Test**: `ls docs/benchmarks/` after Commit 1 returns `m6_2-*` files + the 9 FR-003 exception JSONs only. `ls tests/integration/` returns only the six retained files. `ls M6_2-ANALYSIS-FRAMING-DRAFT.md scripts/python/reprocess_m5_supersede.py scripts/setup/phase2-env.sh` all return "No such file or directory". `grep -nE "\]\(docs/benchmarks/summary\.md\)|\]\(summary\.md\)" ANALYSIS.md docs/PLAN.md` returns no output. `make check` stays green.

### Implementation for User Story 1

- [ ] T006 [P] [US1] Delete the root draft note: `git rm M6_2-ANALYSIS-FRAMING-DRAFT.md`. (Covers FR-002; data-model row 1.)
- [ ] T007 [P] [US1] Delete the 18 `docs/benchmarks/phase-*` files (rows 2–19 of `data-model.md` Entity 1) by running `git rm` on `phase-3-*`, `phase-4.2-*`, `phase-5-*`, `phase-6-*` per quickstart.md Step 1. (Covers FR-003 phase-* partial.)
- [ ] T008 [P] [US1] Delete the M3 / M4 / M5.x `.md` writeups + `m3-channel-tuning.json` (M3 bytes-axis output, not chain input) + `m5_2-transport-vs-tuning.events.jsonl.gz` (rows 20–27 of `data-model.md` Entity 1) via `git rm`. **EXPLICITLY EXCLUDE** the 9 FR-003 exception JSONs (`m3-channel-tuning-time.json`, `m4-time-axis-tuning.json`, `m5-cross-host-validation.json`, `m5_1-rest-vs-grpc.json`, `m5_2-transport-vs-tuning.json`). (Covers FR-003 M3-M5 partial.)
- [ ] T009 [P] [US1] Delete the M6 / M6.0a / M6.1 / M6.1.1 / M6.1.2 / M6.1.3 `.md` writeups + 2 output-only `.json` (`m6_1_2-methodology-discipline.json`, `m6_1_3-attribution-closure-validate.json`, per the 2026-05-26 Q3 clarification) (rows 28–37 of `data-model.md` Entity 1) via `git rm`. **EXPLICITLY EXCLUDE** the 4 FR-003 exception JSONs from this milestone range (`m6-real-engine-mini-validation.json`, `m6_1-real-prompt-embeds.json`, `m6_1_1-engine-cost-instrumentation.json`, `m6_1_3-attribution-closure.json`). NOT delete any `m6_2-*` file. (Covers FR-003 M6.x partial.)
- [ ] T010 [P] [US1] Delete `docs/benchmarks/summary.md` (row 38 of `data-model.md` Entity 1) via `git rm docs/benchmarks/summary.md`. (Covers the FR-003 extension from the 2026-05-26 clarification.)
- [ ] T011 [P] [US1] Delete the obsolete integration tests (rows 39–43 of `data-model.md` Entity 1) by running `git rm tests/integration/test_m4_schema_e2e.py tests/integration/test_m4_sweep_e2e.py tests/integration/test_m5_modal_smoke.py tests/integration/test_m5_1_modal_smoke.py tests/integration/test_m5_2_modal_smoke.py`. (Covers FR-004.)
- [ ] T012 [P] [US1] Delete the two stale scripts (rows 44–45 of `data-model.md` Entity 1): `git rm scripts/python/reprocess_m5_supersede.py scripts/setup/phase2-env.sh`. (Covers FR-005 and FR-006.)
- [ ] T013 [US1] Rewrite `ANALYSIS.md` line 5 per `data-model.md` Entity 4 row 1 (drop "now lives as a one-line redirect"; add "recoverable from any milestone tag through `milestone/m6.1.3-attribution`"). Use the Edit tool on `ANALYSIS.md`. (Covers FR-003a partial. Must run **before** T014 / T015 because they edit the same file.)
- [ ] T014 [US1] Rewrite `ANALYSIS.md` line 14 per `data-model.md` Entity 4 row 2 (remove the markdown link to `summary.md`; preserve "(folded in below)"; reroute the phase-* source-data citation). Edit `ANALYSIS.md`. (Sequential after T013 — same file.)
- [ ] T015 [US1] Rewrite `ANALYSIS.md` line 64 per `data-model.md` Entity 4 row 3 (replace the parenthetical to acknowledge the deleted summary.md and cite `milestone/m3-grpc-tuning-r1` for the pre-fold-in text). Edit `ANALYSIS.md`. (Sequential after T014.)
- [ ] T016 [P] [US1] Remove the entire `docs/PLAN.md` line 869 bullet per `data-model.md` Entity 4 row 4 ("- A short benchmark write-up at `docs/benchmarks/summary.md`…"). Edit `docs/PLAN.md`. (Parallelizable with T013–T015 — different file.)
- [ ] T017 [US1] **NEW (post-clarify gate)**: Verify FR-003 exception is intact AND deletion is complete by running these checks in quickstart.md Step 1's verification block:
  1. `test ! -e M6_2-ANALYSIS-FRAMING-DRAFT.md && echo "FR-002 OK"` (root draft gone).
  2. For each of the 9 FR-003 exception JSONs: `test -e docs/benchmarks/$f && echo "FR-003 exception OK: $f"` (all 9 MUST exist; abort if any missing).
  3. `ls docs/benchmarks/ | grep -cE '^(phase-|m3-|m4-|m5-|m5_1-|m5_2-|m6-|m6_0a-|m6_1-|m6_1_1-|m6_1_2-|m6_1_3-)|^summary\.md$'` returns `9` (the 9 baseline-chain JSONs match the prefix patterns but are correctly retained).
  4. `ls tests/integration/ | grep -v __pycache__` returns exactly the 6 retained files.
  5. `grep -nE "\]\(docs/benchmarks/summary\.md\)|\]\(summary\.md\)" ANALYSIS.md docs/PLAN.md README.md` returns no output (no broken markdown links).
  
  Abort the commit if any check fails.
- [ ] T018 [US1] Run `make check`; expect exit code 0. **NOTE**: this is the post-deletion gate — the two M4 obsolete tests in the deletion set should now be gone, so the suite should be fully green (1575+ passed / 0 failed / 0–2 skipped). (Covers FR-013 / SC-005 + FR-014 / SC-006.)
- [ ] T019 [US1] Create Commit 1 with the message body from `quickstart.md` Step 1 (single-line subject `"v0.0.0(1/5): trim pre-M6.2 milestone artifacts + obsolete tests"` + multi-paragraph body listing the FR-003 exception explicitly + the path → tag map reference). Stage all the deletions + ANALYSIS/PLAN edits with `git add -u` only (do NOT use `git add .` — avoid bundling other untracked items like the next phase's checkpoint un-tracking).

**Checkpoint**: Commit 1 lands cleanly. `git log -1 --stat` shows 45 file-index deletions + 4 documentation edits (3 in ANALYSIS.md, 1 in docs/PLAN.md). Zero changes outside the deletion / edit set. The 9 FR-003 exception JSONs are still tracked. US1 acceptance scenarios 1–6 all pass.

---

## Phase 4: User Story 2 — Operator stops accidentally committing local sweep logs (Priority: P2)

**Goal**: Un-track the `logs/` directory and the M6.2 checkpoint file, then add `.gitignore` rules. Ships as **Commits 2, 3, and 4** of the PR.

**Independent Test**: After Commit 4, `git ls-files logs/` returns empty; `git ls-files docs/benchmarks/` contains no `*.checkpoint.jsonl` entries; `git check-ignore -v logs/probe.log` and `git check-ignore -v docs/benchmarks/anything.checkpoint.jsonl` both match the new rules; the M6.2 checkpoint file still exists on disk locally; M6.2 final `.json` and `.md` outputs remain tracked.

### Implementation for User Story 2

- [ ] T020 [US2] Un-track the `logs/` directory by running `git rm -r --cached logs/` from repo root. The 13 entries (11 M4 logs + `m4-full.current` + `m4-full.pid`) leave the index but stay on disk. (Covers FR-008 logs portion; data-model rows 46–58.)
- [ ] T021 [US2] Verify the logs un-tracking with `git ls-files logs/ | wc -l` (expected `0`) and `ls logs/ | wc -l` (expected `13`).
- [ ] T022 [US2] Create Commit 2 with message subject `"v0.0.0(2/5): un-track logs/ (M4 sweep stdout captures)"` and the body from `quickstart.md` Step 2.
- [ ] T023 [US2] Un-track the M6.2 sweep checkpoint by running `git rm --cached docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl`. The file stays on disk. (Covers FR-008 checkpoint portion; data-model row 59.)
- [ ] T024 [US2] Verify the checkpoint un-tracking with `git ls-files docs/benchmarks/ | grep checkpoint` (expected: empty) and `test -e docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl && echo "On-disk OK"`.
- [ ] T025 [US2] Create Commit 3 with message subject `"v0.0.0(3/5): un-track M6.2 sweep checkpoint"` and the body from `quickstart.md` Step 3.
- [ ] T026 [US2] Append the `.gitignore` rules per `data-model.md` Entity 3 by running:
  ```bash
  cat >> .gitignore <<'EOF'

  # v0.0.0 housekeeping (per spec FR-007)
  logs/
  **/*.checkpoint.jsonl
  EOF
  ```
  (Covers FR-007.)
- [ ] T027 [US2] Verify the new rules:
  - `git check-ignore -v logs/probe.log` → expect match on `logs/`.
  - `git check-ignore -v docs/benchmarks/anything.checkpoint.jsonl` → expect match on `**/*.checkpoint.jsonl`.
  - `git check-ignore -v docs/benchmarks/m6_2-token-budget.json` → expect no output (M6.2 final output MUST NOT be ignored).
- [ ] T028 [US2] Run `make check`; expect exit code 0. (FR-013 / SC-005 toolchain gate before Commit 4.)
- [ ] T029 [US2] Create Commit 4 with message subject `"v0.0.0(4/5): gitignore logs/ and checkpoint files"` and the body from `quickstart.md` Step 4. Stage only `.gitignore` with `git add .gitignore`.

**Checkpoint**: Commits 2, 3, and 4 all on branch. US2 acceptance scenarios 1–3 all pass.

---

## Phase 5: User Story 3 — Reader discovers how to recover historical material (Priority: P3)

**Goal**: Append a `## Repo housekeeping` section to `ANALYSIS.md` documenting the `v*` / `milestone/*` dual-track convention, the FR-003 exception (9 baseline-chain JSONs stay tracked), and the canonical `git show <tag>:<path>` recovery incantation. Ships as **Commit 5** of the PR.

**Independent Test**: After Commit 5, `grep -n "^## Repo housekeeping$" ANALYSIS.md` returns exactly one match. A reader following the subsection's `git show milestone/m5.2-transport-tuning:docs/benchmarks/m5_2-transport-vs-tuning.md` example successfully retrieves the deleted M5.2 narrative in well under 30 seconds (SC-007).

### Implementation for User Story 3

- [ ] T030 [US3] Append the new `## Repo housekeeping` section to the end of `ANALYSIS.md` using the content shape from `research.md` § R7 / `quickstart.md` Step 5. The text MUST mention the FR-003 exception (the 9 baseline-chain JSONs stay tracked because the sweep harness reads them at runtime). Insert AFTER the last existing milestone narrative section. (Covers FR-009, FR-010, FR-011.)
- [ ] T031 [US3] Verify section presence and end-of-document placement: `MATCH_LINE=$(grep -n "^## Repo housekeeping$" ANALYSIS.md | cut -d: -f1)` and `TOTAL_LINES=$(wc -l < ANALYSIS.md)`; expect exactly one match line within the last 20% of the file (`MATCH_LINE × 5 ≥ TOTAL_LINES × 4`). Enforces FR-011 (subsection MUST NOT interrupt milestone narrative).
- [ ] T032 [US3] Verify the documented recovery command works by running `time git show milestone/m5.2-transport-tuning:docs/benchmarks/m5_2-transport-vs-tuning.md | head -1`; expect M5.2 report's first line returned in sub-second wall-clock time. Proves the 30-second SC-007 ceiling holds with margin.
- [ ] T033 [US3] Run `make check`; expect exit code 0. (FR-013 / SC-005 toolchain gate before Commit 5.)
- [ ] T034 [US3] Create Commit 5 with message subject `"v0.0.0(5/5): ANALYSIS.md \"Repo housekeeping\" section"` and the body from `quickstart.md` Step 5. Stage only `ANALYSIS.md` with `git add ANALYSIS.md`.

**Checkpoint**: All five PR commits on the branch. The branch is ready to push and open a PR against `main`. US3 acceptance scenarios 1–3 all pass.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final verification gates, PR submission, and the post-merge `v0.0.0` tag creation.

- [X] T035 [P] Compute the SC-002 cleanup-commit deletion count (per 2026-05-26 Q5 reframe): identify the commit just before `v0.0.0(1/5)` (the `[Spec Kit] Re-derive plan/tasks/runbook` commit), then run `pre_cleanup=$(git log --oneline --grep="Re-derive plan/tasks" --format=%H | head -1); git diff --diff-filter=D --name-only $pre_cleanup..HEAD | wc -l`. Confirm ≥40. **Measured 2026-05-26**: 47 cleanup-commit deletions. SC-002 satisfied with margin.
- [X] T036 [P] Spot-check tag recovery for at least one representative file per milestone tag: `git show milestone/m3-grpc-tuning-r1:docs/benchmarks/m3-channel-tuning.md | head -1`, `git show milestone/m4-time-axis:docs/benchmarks/m4-time-axis-tuning.md | head -1`, `git show milestone/m5.2-transport-tuning:docs/benchmarks/m5_2-transport-vs-tuning.md | head -1`, `git show milestone/m6.1.3-attribution:docs/benchmarks/m6_1_3-attribution-closure.md | head -1`, `git show milestone/m5-cross-host:logs/m4-full.current | head -1`. All MUST return content. (SC-004 verification.) **Note (2026-05-26 Q5)**: `logs/m4-full.current` was the ONLY logs/ file ever tracked, and was first added AFTER `milestone/m4-time-axis` (M4 closed before this file existed in the index). Use `milestone/m5-cross-host` or later as the recovery tag — NOT `milestone/m4-time-axis`. The 11 `logs/m4-full-<timestamp>.log` files were always on-disk-only (sweep stdout captures), never committed, and therefore not tag-recoverable; FR-012 applies only to tracked files. **Measured 2026-05-26**: all 5 spot-checks return content.
- [ ] T037 [P] Run final pre-push verification:
  1. `make check` exit code 0 (FR-013 / SC-005 + FR-014 / SC-006).
  2. `git status` clean.
  3. FR-001 source-preservation check: `git diff --name-only fea31c0..HEAD -- tools/benchmark/src/ packages/ proto/ frontend/ | wc -l` returns `0` (confirms no source file modified by Commits 1–5).
  4. FR-003 exception still satisfied: rerun the audit anchor `grep -hoE 'docs/benchmarks/[^"'\'']+\.json' tools/benchmark/src/vllm_grpc_bench/*.py | sort -u | while read p; do test -e "$p" && echo "$p"; done | grep -v 'm6_2-' | wc -l` returns `9`.
- [ ] T038 Push the branch to origin: `git push -u origin chore/post-m6.2-cleanup-v0.0.0`.
- [ ] T039 Open the PR via `gh pr create --base main --title "v0.0.0 — Post-M6.2 housekeeping" --body "$(cat …)"` using the PR body template from `quickstart.md` Step 7 (which names the FR-003 exception explicitly). Capture the PR URL.
- [X] T040 **[POST-MERGE]** After the PR merges to `main`, switch to `main` and pull: `git checkout main && git pull origin main`. Confirm the merge commit hash. **DONE 2026-05-29**: on `main`, fast-forwarded to merge commit `8c75ea0`.
- [X] T041 **[POST-MERGE]** Create the annotated `v0.0.0` tag on the merge commit using the message body from `research.md` § R8 / `quickstart.md` Step 8 (which mentions the FR-003 exception in the body): `git tag -a v0.0.0 -m "$(cat …)"`. (Covers FR-015.) **DONE 2026-05-29**: annotated tag `v0.0.0` (object `ed1013a`) created on merge commit `8c75ea0`.
- [X] T042 **[POST-MERGE]** Push the new tag: `git push origin v0.0.0`. **DONE 2026-05-29**: pushed (`* [new tag] v0.0.0 -> v0.0.0`).
- [X] T043 **[POST-MERGE]** Final SC-008 verification: `git ls-remote --tags origin v0.0.0 milestone/m6.2-token-budget`. Expect both tags present on origin. Capture for release notes. **DONE 2026-05-29**: both present on origin — `v0.0.0` → `ed1013a`, `milestone/m6.2-token-budget` → `8b5b131`.
- [X] T044 **[POST-MERGE]** Final SC-003 verification: clone the repo into a scratch directory on a sweep-naive machine and confirm `git status` clean: `git clone https://github.com/AncientStudying/vllm-grpc.git /tmp/v000-fresh && cd /tmp/v000-fresh && git status`. Expect "nothing to commit, working tree clean." Remove the scratch clone after verification. **DONE 2026-05-29**: fresh clone verified clean; scratch clone removed after verification.

**Checkpoint**: All eight success criteria (SC-001 through SC-008) verified. Both annotated tags live on origin. The branch is merged. v0.0.0 ships.

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (Setup)**: T001 must complete first (baseline measurement); T002–T005a can run in parallel after T001.
- **Phase 2 (Foundational)**: Empty.
- **Phase 3 (US1)**: Depends on Phase 1 checkpoint. Commit 1 = 45 file deletions + 4 doc edits.
- **Phase 4 (US2)**: Depends on Phase 3 (Commit 1) being on the branch. Commits 2–4 = un-trackings + gitignore.
- **Phase 5 (US3)**: Depends on Phase 4 (Commits 2–4) being on the branch — US3 documents the housekeeping convention that includes the gitignore mechanism added by US2. Commit 5 = ANALYSIS subsection.
- **Phase 6 (Polish)**: Depends on Phases 3–5.
  - T035–T037 (pre-push verification) run in parallel.
  - T038 (push) before T039 (PR open).
  - T040–T044 (`[POST-MERGE]`) are gated by the PR merge event.

### User-story dependencies (sequential, not parallel)

This feature is unusual in that the three user stories are NOT independent in *execution* order even though each is *independently testable* per the spec. The three stories share the same five-commit PR shape, and each commit builds on the previous one's tree state:

- **US1 (P1)** ships in Commit 1 — the working-tree foundation that US2/US3 build on.
- **US2 (P2)** ships in Commits 2, 3, 4 — operates on the post-US1 tree state.
- **US3 (P3)** ships in Commit 5 — references the housekeeping convention finalized by US2.

One operator executes Phases 1–6 top-to-bottom.

### Within each user story

- Verification (`make check`, `git ls-files` / `git check-ignore` checks) runs **before** the corresponding commit. A red gate aborts the commit.
- Edits to the same file are sequential (T013 → T014 → T015 on `ANALYSIS.md`); edits to different files are parallel-marked.
- `git add` is always scoped (`git add -u`, `git add <specific-files>`) — never `git add .`.

### Parallel opportunities

- **Phase 1**: T002–T005a in parallel after T001.
- **Phase 3** deletions: T006–T012 in parallel (different file sets). T013–T015 sequential within `ANALYSIS.md`. T016 parallel with T013–T015 (different file).
- **Phase 6** pre-push verifications: T035, T036, T037 in parallel.

---

## Implementation Strategy

### MVP (User Story 1 only)

Phase 1 → Phase 3 → STOP. After Commit 1 lands, the repository is materially cleaner: 45 files removed, `git status` quiet. US2 and US3 are improvements on top — skippable for an experimental short-PR if needed.

### Incremental delivery

Each commit is a complete, independently-revertable increment:

- Commit 1 (US1) → cleaner working tree.
- Commit 2 (US2-partial) → `logs/` un-tracked.
- Commit 3 (US2-partial) → checkpoint un-tracked.
- Commit 4 (US2-partial) → `.gitignore` rules.
- Commit 5 (US3) → housekeeping subsection.
- Commit 6 (Polish) → `v0.0.0` tag pushed.

### Single-operator strategy (canonical here)

One operator runs Phase 1 → Phase 3 → Phase 4 → Phase 5 → Phase 6 in sequence. Total time: ~10–15 minutes for the local work, dominated by `make check` runtime (which dominates Phases 3, 4, 5 verification steps). Post-merge tasks (T040–T044) add ~5 minutes after the PR merges.

---

## Notes

- `[P]` tasks operate on different files — safe to interleave or parallelize.
- `[Story]` label maps each task to one of US1 (clean tree), US2 (logs + checkpoint ignore), US3 (ANALYSIS doc pointer).
- No test files are written; verification is via `make check`, the M6.2 fake-backed CLI tests (already part of `make test`), and direct filesystem inspection.
- Every commit message follows the format `v0.0.0(N/5): <subject>` with a multi-paragraph body. Bodies are in `quickstart.md` Steps 1–5.
- The post-merge tag (T041) uses the message body from `research.md` § R8. Annotated tag, not lightweight.
- If a verification gate fails (T017, T018, T021, T024, T027, T028, T031, T032, T033, T035, T036, T037), **stop**, fix the root cause, and re-run the gate. Do not advance past a red gate.
- **FR-003 exception is the most error-prone aspect of this task list.** Every deletion task (T007–T009) MUST NOT touch the 9 baseline-chain JSONs. T005a (pre-flight) and T017 (post-deletion) gates verify the exception holds. T037 (pre-push) reverifies one final time.

---

## Resume context (2026-05-26 cycle — post-clarify)

The /speckit-implement cycle paused mid-Phase-3 to run /speckit-clarify after discovering the FR-003 fixture-coupling gap. After clarify + re-plan + re-tasks:

- **Worktree state**: 45 deletions staged + ANALYSIS.md / docs/PLAN.md / tasks.md (this file) modified. Spec.md committed in `2023145`.
- **What's already done (against the amended tasks above)**: T001–T005, T005a, and the deletion / edit content of T006–T016. The deletions match the new manifest (the 9 FR-003 exception JSONs were restored in the worktree before clarify).
- **Resume at**: T017 (verify FR-003 exception + deletion completeness gate), T018 (`make check`), T019 (Commit 1).
- The new tasks.md content takes priority over earlier session notes; this regenerated structure has 45 tasks (T001–T005a, T006–T019, T020–T029, T030–T034, T035–T044 — 44 sequential IDs plus T005a inserted).
