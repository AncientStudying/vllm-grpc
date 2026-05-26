# Feature Specification: v0.0.0 — Post-M6.2 Housekeeping

**Feature Branch**: `chore/post-m6.2-cleanup-v0.0.0`
**Created**: 2026-05-26
**Status**: Draft
**Input**: User description: "v0.0.0 as documented in docs/PLAN.md"

## Overview

Trim accumulated milestone-specific result data, one-shot draft notes, obsolete integration tests, and stale operator scripts from the `main` working tree ahead of M7. The goal is to **reduce noise** in the working tree and shrink the diff surface that M7 (corpus expansion) and M8 (model expansion) will need to read against — not to refactor any production source code.

This is the first beat on the project's parallel `v*` semver track. `v*` tags mark *codebase state* (maintenance, release readiness); `milestone/*` tags mark *research deliverables*. `v0.0.0` signals "pre-release / pre-PyPI": everything works on `main` but nothing is published, and the schema/API may still change without notice.

Every file slated for deletion is fully recoverable via the corresponding `milestone/m*` annotated tag (all 16 milestone tags from M2 through M6.2 are pushed to origin as of 2026-05-26). Readers needing historical benchmark numbers, sweep harnesses, or pre-cleanup integration scaffolding check out the matching tag.

## Clarifications

### Session 2026-05-26

- Q: How should `*.checkpoint.jsonl` files (specifically the now-tracked `docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl`) be handled? → A: Gitignore `**/*.checkpoint.jsonl` globally and untrack the M6.2 file. Checkpoints are mid-sweep runtime state, not published artifacts; the canonical M6.2 outputs are the `.json` + `.md` pair.
- Q: How should `docs/benchmarks/summary.md` (a 6-line redirect stub pointing readers at `ANALYSIS.md`, in place since M5.2) be handled? → A: Delete it; rely on README + `ANALYSIS.md` discoverability. The two internal references (`docs/PLAN.md`, `ANALYSIS.md`) that link to it MUST be updated to remove the dangling reference.
- Q: What commit/PR shape should the cleanup take? → A: One PR containing N bisectable commits, one per FR group (working-tree deletions, `logs/` un-tracking, checkpoint un-tracking, ANALYSIS housekeeping subsection, `.gitignore` rules, `v0.0.0` tag creation). Single review surface; each piece independently revertable; matches the spec's existing "bisectable and reversible" assumption.
- Q: Should FR-003 carve out an exception for `docs/benchmarks/*.json` files that `tools/benchmark/src/` reads as runtime baseline inputs (discovered during /speckit-implement when 9 such files were found in the M3→M6.2 baseline chain via default-path constants like `_M5_REPORT_PATH`, `_M5_1_PUBLISHED_PATH`, `M3_TIME_REPORT_PATH`, and the M6/M6.1/M6.1.1/M6.1.2/M6.1.3/M6.2 baseline-default CLI args in `__main__.py`)? → A: Yes — narrow explicit allow-list. FR-003 keeps its pattern-based prohibition but adds an explicit retention list of exactly 9 JSON files (the M3→M6.2 baseline chain). Audit anchor: a reviewer can verify the list against `grep -hoE 'docs/benchmarks/[^"'\'']+\.json' tools/benchmark/src/vllm_grpc_bench/*.py`. Any future addition to the list requires a deliberate spec amendment. FR-001 source preservation remains unchanged — the carve-out is in FR-003 (which files to delete), not in FR-001 (which paths to leave alone).
- Q: Should the 9 retained JSONs' companion `.md` writeups (e.g., `m5_2-transport-vs-tuning.md` alongside the retained `m5_2-transport-vs-tuning.json`) also be retained for co-location, or deleted as originally planned? → A: Delete all 9 `.md` companions. Rationale: their narrative content is already folded into `ANALYSIS.md` (the canonical narrative cross-reference); FR-012 guarantees recoverability via milestone tags; nothing in `tools/benchmark/src/` reads them. The cleanup's principle holds — narrative lives in `ANALYSIS.md`, data lives either tracked (chain JSONs forced by FR-001) or in milestone tags (everything else). No FR-003 amendment needed: the exception covers only the 9 `.json` files; the matching `.md` writeups remain in FR-003's pattern-based deletion set.
- Q: Should `m6_1_2-methodology-discipline.json` and `m6_1_3-attribution-closure-validate.json` (M6.1.2 / M6.1.3 published outputs with no downstream baseline-chain consumer) stay deleted, or be retained alongside the 9-JSON chain? → A: Delete both. Rationale: keeps FR-003's exception list crisp ("source-code runtime inputs only"); both files are recoverable via `milestone/m6.1.2-methodology` and `milestone/m6.1.3-attribution` per FR-012. Retaining them would loosen the rule from "runtime-input" to "milestone-output-or-input", a fuzzier criterion. No FR-003 amendment needed: both files match `m6_1_2-*` / `m6_1_3-*` patterns and stay in the pattern-based deletion set.
- Q: With the FR-003 exception retaining 9 JSONs (~936 KB), the measured size reduction drops to ~1.86 MB — below SC-002's original ≥2.5 MB floor. How should SC-002 be recalibrated? → A: Switch SC-002 to a file-count metric (file cleanup is the primary value of the beat; disk-size reduction is incidental). New floor: ≥50 fewer tracked files visible in a fresh clone vs `fea31c0`. Actual reduction is ~67 file-index removals (1 root draft + 45 `docs/benchmarks/` deletions + 5 obsolete integration tests + 2 stale scripts + 13 `logs/` un-trackings + 1 checkpoint un-tracking); the ≥50 floor preserves ~25% headroom matching the original ≥2.5 MB / ~3.5 MB-headline ratio. Headline framing shifts from "~3.5 MB working-tree reduction" to "~67 fewer tracked files in a fresh clone, ~2 MB of milestone-era `.md` writeups + obsolete tests + scripts removed, 9 baseline-chain JSONs retained per FR-003 exception".

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator finds a clean working tree on `main` (Priority: P1)

A maintainer (or returning contributor) clones the repo or pulls `main` and looks at `docs/benchmarks/`, `tests/integration/`, `scripts/python/`, and `scripts/setup/`. Today these directories contain a chronological accumulation of every milestone's outputs and one-shot tools (~67 tracked files comprising `phase-*` / `m3-*` / `m4-*` / `m5*-` / `m6-*` / `m6_1*-` / `m6_1_1*-` / `m6_1_2*-` / `m6_1_3*-` artifact pairs, M4-era smoke tests, the M5 supersede reprocessor, the long-defunct Phase 2 env script, plus a root-level `M6_2-ANALYSIS-FRAMING-DRAFT.md` whose content is already merged into `ANALYSIS.md`). After this story ships, the working tree retains: (a) the current milestone's artifacts (`m6_2-*`), (b) the 9 baseline-chain JSONs that `tools/benchmark/src/` reads at runtime per the FR-003 exception (`m3-channel-tuning-time.json`, `m4-time-axis-tuning.json`, `m5-cross-host-validation.json`, `m5_1-rest-vs-grpc.json`, `m5_2-transport-vs-tuning.json`, `m6-real-engine-mini-validation.json`, `m6_1-real-prompt-embeds.json`, `m6_1_1-engine-cost-instrumentation.json`, `m6_1_3-attribution-closure.json`), and (c) the still-active integration tests (`test_grpc_client.py`, `test_chat_bridge.py`, `test_completions_bridge.py`, plus their `conftest.py` / `fake_frontend.py` fixtures).

**Why this priority**: This is the entire reason `v0.0.0` exists. Without it, the diff surface for M7 and M8 includes ~67 tracked files of milestone-era noise that is irrelevant to forward work but still appears in every `git status`, every IDE file-tree, every `grep`. The two larger follow-ups (`v0.0.1` bench-harness refactor and `v0.1.0` PyPI release) both assume `v0.0.0` has shipped first.

**Independent Test**: Check out `main` after the merge; run `ls docs/benchmarks/`, `ls tests/integration/`, `ls scripts/python/`, `ls scripts/setup/`, `ls` at repo root. None of the deletion-target patterns (listed in FR-002 through FR-006) appear. `git checkout milestone/m5.2-transport-tuning -- docs/benchmarks/m5_2-transport-vs-tuning.md` still surfaces the deleted M5.2 report at that tag, proving the recovery path. `make lint typecheck test` is green; running the M6.2 validate harness against `fake_server` still completes end-to-end (no source-code change was made).

**Acceptance Scenarios**:

1. **Given** the merge commit is checked out on `main`, **When** the maintainer lists `docs/benchmarks/`, **Then** the directory contains exactly (a) `m6_2-*` files (M6.2 outputs, the current milestone) and (b) the 9 baseline-chain JSONs named in FR-003's exception list — no `.md` writeups for the deleted milestones, no `phase-*` files, no `summary.md`, and no `m6_1_2-methodology-discipline.json` / `m6_1_3-attribution-closure-validate.json` (output-only JSONs outside the chain).
2. **Given** the merge commit, **When** `ls tests/integration/` is run, **Then** only `__init__.py`, `conftest.py`, `fake_frontend.py`, `test_grpc_client.py`, `test_chat_bridge.py`, and `test_completions_bridge.py` remain (no `test_m4_*` or `test_m5*_modal_smoke.py`).
3. **Given** the merge commit, **When** `ls scripts/python/reprocess_m5_supersede.py` or `ls scripts/setup/phase2-env.sh` is run, **Then** both return "No such file or directory."
4. **Given** the merge commit, **When** the maintainer runs `ls M6_2-ANALYSIS-FRAMING-DRAFT.md` at repo root, **Then** the file is absent.
5. **Given** any deleted file `<path>` was previously committed under milestone tag `milestone/m<N>`, **When** the maintainer runs `git show milestone/m<N>:<path>`, **Then** the historical file content is returned intact.
6. **Given** the merge commit, **When** `make lint typecheck test` is run, **Then** the full suite passes with no regressions vs the pre-cleanup baseline.

---

### User Story 2 - Operator stops accidentally committing local sweep logs (Priority: P2)

When an operator runs the M4-era full sweep harness locally (and any future harness that follows the same convention), the tooling writes per-run sweep logs into `logs/` at the repo root. Today this directory contains 11 M4 sweep logs from 2026-05-10 (52 KB total) plus `m4-full.current` and `m4-full.pid` markers, all currently tracked by git. The directory is not in `.gitignore`, so any new sweep log lands in the next commit's `git status` output and risks accidental inclusion. After this story ships, `logs/` is ignored by git and the historical tracked contents are removed from the index (but recoverable via the `milestone/m4-time-axis` tag).

**Why this priority**: Lower than US1 because nobody is currently running M4 sweeps — the cost of leaving `logs/` tracked is small. But it's part of the same cleanup beat, has zero risk, and prevents an entire class of future "oops, committed a 50 MB sweep log" mistakes for M7/M8 operators.

**Independent Test**: After the merge, run `git check-ignore logs/anything.log` — it returns `logs/anything.log` (proving the ignore pattern matches). Run `git ls-files logs/` — it returns no results (proving the historical files are no longer tracked). The directory may still exist locally for operators who have run sweeps, but a fresh clone will not contain it.

**Acceptance Scenarios**:

1. **Given** the merge commit on a fresh clone, **When** the cloner runs `ls logs/`, **Then** the directory is absent (was removed from the index, never re-added).
2. **Given** an operator on the merge commit, **When** they run a sweep that writes `logs/m7-full.log`, **Then** the file does not appear in `git status` (it matches a `.gitignore` rule).
3. **Given** the merge commit, **When** `git show milestone/m4-time-axis:logs/m4-full-20260510-103956.log` is run, **Then** the historical log content is returned intact.

---

### User Story 3 - Reader discovers how to recover historical material (Priority: P3)

A contributor (or LLM agent) reading `ANALYSIS.md` reaches a section discussing an M3 / M4 / M5.x / M6.x finding and wonders where the underlying benchmark report or sweep harness lives. Today the report would be a sibling file in `docs/benchmarks/`; after US1 ships, it has been deleted. Without guidance, the reader has no obvious way to discover that `milestone/m5.2-transport-tuning` exists and contains the M5.2 report. After this story ships, `ANALYSIS.md` carries a short "Repo housekeeping" subsection naming the convention (`v*` for codebase state, `milestone/*` for research deliverables) and explicitly pointing readers at the milestone tags as the recovery path.

**Why this priority**: P3 because the information is technically discoverable via `git tag --list 'milestone/*'`, but P3 still ships in this beat because (a) it's tiny — a 5-10 line subsection — and (b) deferring it means M7/M8 spec authors writing against `ANALYSIS.md` will have to re-derive the recovery path themselves.

**Independent Test**: After the merge, open `ANALYSIS.md` and search for "housekeeping" or "milestone tag". The subsection exists, names both tag conventions, and links to the milestone tag list with a one-line `git show <tag>:<path>` example. A reader who has never touched the cleanup beat can read the subsection and immediately recover any historical artifact named in any earlier section.

**Acceptance Scenarios**:

1. **Given** the merge commit, **When** the reader opens `ANALYSIS.md` and searches for "Repo housekeeping" (or equivalent heading), **Then** a subsection exists that names both the `v*` semver track and the `milestone/*` deliverable track.
2. **Given** that subsection, **When** a reader follows its guidance to recover a deleted file (e.g., the M3 channel-tuning report), **Then** the documented command (`git show milestone/m3-grpc-tuning-r1:docs/benchmarks/m3-channel-tuning.md`) successfully returns the file content.
3. **Given** the merge commit, **When** the reader opens `ANALYSIS.md`, **Then** the new subsection is placed near the end of the document (or in a clearly-titled "Repository Structure" / "Reading this document" area) so it does not interrupt the narrative flow of milestone findings.

---

### Edge Cases

- **A deletion-target pattern matches a file the operator wants to keep.** Mitigated by enumerating exact deletion paths in FR-002 through FR-006 (and the implementation manifest in the plan phase), not by glob-only deletion at merge time. The `m6_2-*` family is the **negation**: any file beginning with `m6_2-` must be retained.
- **An M6.2 artifact untracked at cleanup time gets caught up in cleanup.** Today `docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl` is tracked (it was bundled into the spec commit by the `after_specify` auto-commit hook). Per the 2026-05-26 clarification, `**/*.checkpoint.jsonl` is gitignored globally and this file is untracked via `git rm --cached` (FR-007 / FR-008). The retention pattern in FR-003 still excludes `m6_2-*` from deletion — the checkpoint file's `.json` and `.md` siblings (the canonical M6.2 outputs) stay tracked.
- **A reader on `main` looks for a deleted file via its old path.** The `ANALYSIS.md` housekeeping subsection (US3) is the structural mitigation; if US3 is descoped or deferred, US1 still ships but readers must run `git log --all --diff-filter=D -- <path>` to discover the deletion commit and the tag-recovery path.
- **CI tries to run a deleted integration test.** Mitigated by acceptance gate FR-013 (`make lint typecheck test` green at merge); the deleted tests are not in any CI workflow today, but the gate catches regressions if a workflow still references one.
- **A future operator wants to re-run an M5.2 smoke test against Modal.** They check out `milestone/m5.2-transport-tuning`, recover the smoke test, and run it from that worktree. The cleanup explicitly does not preserve a "best of historical smokes" merged into the new tree; that's `v0.0.1`'s job.
- **The M6.2 milestone tag already exists.** Verified: `milestone/m6.2-token-budget` is present at `fea31c0` and pushed to origin. The "create the tag" item from `docs/PLAN.md` § v0.0.0 is **already complete** and the spec carries it as an Assumption rather than a Requirement.

## Requirements *(mandatory)*

### Functional Requirements

#### Source preservation invariants

- **FR-001**: The cleanup MUST NOT modify any file under `tools/benchmark/src/`, `packages/`, `proto/`, or `frontend/` source trees. (`v0.0.1` is the dedicated harness-refactor beat; `v0.1.0` is the dedicated `packages/` release-prep beat.)

#### Working-tree deletions (US1)

- **FR-002**: The repository root MUST NOT contain `M6_2-ANALYSIS-FRAMING-DRAFT.md` after merge. (Content is already merged into `ANALYSIS.md`, confirmed by 31+ grep hits for "m6.2" / "token budget" in the merged document.)
- **FR-003**: `docs/benchmarks/` MUST NOT contain any file whose name matches the patterns `phase-*`, `m3-*`, `m4-*`, `m5-*`, `m5_1-*`, `m5_2-*`, `m6-*`, `m6_0a-*`, `m6_1-*`, `m6_1_1-*`, `m6_1_2-*`, `m6_1_3-*` after merge — note the patterns are non-anchored on the trailing separator, so `m6-*` already matches `m6_0a-dispatch-correction.md` by virtue of the leading `m6` prefix; `m6_0a-*` is listed explicitly to remove glob-interpretation ambiguity. Files beginning with `m6_2-` (the current milestone) MUST be retained. Additionally, `docs/benchmarks/summary.md` (a 6-line redirect stub pointing at `ANALYSIS.md`) MUST also be deleted — per the 2026-05-26 clarification, README and `ANALYSIS.md` are sufficient discoverability. **Exception — baseline-input JSONs (per 2026-05-26 clarification)**: the following 9 files MUST be retained because `tools/benchmark/src/` reads them at runtime via default-path constants (FR-001 forbids editing those defaults): `docs/benchmarks/m3-channel-tuning-time.json`, `docs/benchmarks/m4-time-axis-tuning.json`, `docs/benchmarks/m5-cross-host-validation.json`, `docs/benchmarks/m5_1-rest-vs-grpc.json`, `docs/benchmarks/m5_2-transport-vs-tuning.json`, `docs/benchmarks/m6-real-engine-mini-validation.json`, `docs/benchmarks/m6_1-real-prompt-embeds.json`, `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json`, `docs/benchmarks/m6_1_3-attribution-closure.json`. These constitute the M3→M6.2 baseline chain (each milestone's published JSON is the next milestone's baseline input). Audit anchor: `grep -hoE 'docs/benchmarks/[^"'\'']+\.json' tools/benchmark/src/vllm_grpc_bench/*.py | sort -u` returns this list (plus M6.2's own outputs, which are retained under the `m6_2-*` rule). Any future addition to this list requires a deliberate spec amendment.
- **FR-003a**: The two existing internal references to `docs/benchmarks/summary.md` (in `docs/PLAN.md` and `ANALYSIS.md`) MUST be updated to remove the dangling reference. A reference may be removed entirely or rewritten to point at `ANALYSIS.md` directly, whichever preserves the surrounding sentence's meaning.
- **FR-004**: `tests/integration/` MUST NOT contain `test_m4_schema_e2e.py`, `test_m4_sweep_e2e.py`, `test_m5_modal_smoke.py`, `test_m5_1_modal_smoke.py`, or `test_m5_2_modal_smoke.py` after merge. The files `__init__.py`, `conftest.py`, `fake_frontend.py`, `test_grpc_client.py`, `test_chat_bridge.py`, and `test_completions_bridge.py` MUST be retained.
- **FR-005**: `scripts/python/reprocess_m5_supersede.py` MUST NOT exist after merge. (Was a one-shot M5 supersedence reprocessor; output already published in M5.x reports.)
- **FR-006**: `scripts/setup/phase2-env.sh` MUST NOT exist after merge. (Was a Phase 2 dev-env bootstrap; the project's environment is now driven by `uv` and the root `Makefile` / `pyproject.toml`.)

#### `logs/` and checkpoint cleanup (US2)

- **FR-007**: `.gitignore` MUST include rules that (a) cause any path under `logs/` to be ignored by git (e.g., `logs/`), and (b) cause any path matching `**/*.checkpoint.jsonl` to be ignored by git. The checkpoint pattern is global because sweep harnesses across milestones write checkpoint files alongside their final `.json` outputs.
- **FR-008**: No file under `logs/` MUST be tracked in the repository's index after merge. (`git ls-files logs/` returns no results.) Additionally, no file matching `**/*.checkpoint.jsonl` MUST be tracked after merge — specifically `docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl` (currently tracked from the `after_specify` auto-commit bundling) MUST be untracked via `git rm --cached` while remaining on disk.

#### Documentation pointer (US3)

- **FR-009**: `ANALYSIS.md` MUST contain a subsection (heading text at the author's discretion; suggested: "Repo housekeeping" or "Recovering historical material") that names both the `v*` semver track (codebase state) and the `milestone/*` track (research deliverables).
- **FR-010**: The subsection added in FR-009 MUST include at least one concrete `git show milestone/<tag>:<path>` example that, when run against the repository as of the merge commit, successfully returns historical file content.
- **FR-011**: The subsection added in FR-009 MUST NOT be placed in a position that interrupts the milestone-by-milestone narrative flow (i.e., not inserted between adjacent milestone findings sections). Placement near the end of the document or in an existing "structure" / "how to read" area is preferred.

#### Recoverability invariants

- **FR-012**: Every file deleted by FR-002 through FR-008 MUST be recoverable via an existing annotated milestone tag at the commit immediately preceding the cleanup. Concretely, the union of files deleted MUST be a subset of the files reachable from `milestone/m2-ground-truth` through `milestone/m6.2-token-budget` on the merge-base commit.

#### Quality / merge gates

- **FR-013**: `make lint typecheck test` MUST pass on the merge commit with no regressions vs `main` at `fea31c0`. (The repository's standard pre-merge gate.)
- **FR-014**: The M6.2 validate harness (`python -m vllm_grpc_bench.m6_2_validate` against `fake_server`, or the project's equivalent fake-backed smoke) MUST complete end-to-end on the merge commit, proving that no source-code path used by the current milestone was touched.

#### Tag and release outputs

- **FR-015**: An annotated git tag `v0.0.0` MUST be created on the merge commit. The tag message MUST identify the cleanup beat ("Post-M6.2 housekeeping — first cut of the v* semver track" or equivalent).
- **FR-016**: The annotated git tag `milestone/m6.2-token-budget` (already created at `fea31c0` on 2026-05-26) MUST continue to be reachable from the merge commit's ancestry, MUST remain pushed to origin, and MUST be referenced in the v0.0.0 tag message or release notes as the M6.2 research-deliverable counterpart.

### Key Entities *(include if feature involves data)*

- **Annotated git tag (`v0.0.0`)**: Marks the codebase-state checkpoint. Distinct from `milestone/*` research tags. Created on the merge commit. Pushed to origin.
- **Milestone tag set (`milestone/m2-…` through `milestone/m6.2-…`)**: The 16 pre-existing annotated tags that serve as the recovery path for every file deleted by this cleanup.
- **Deletion manifest (implicit)**: The concrete enumeration of file paths slated for removal — derived from FR-002 through FR-006 plus the per-file decisions on edge cases (notably `summary.md` in `docs/benchmarks/`, the M6.2 checkpoint untracking, and the FR-003 exception list retaining 9 baseline-chain JSONs). Lives in the plan/tasks artifacts, not in source.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After merge, the count of tracked files matching any pre-M6.2 deletion-target pattern from FR-002 through FR-006 (root draft, `docs/benchmarks/` pre-M6.2 milestone files, obsolete `tests/integration/` files, the two stale scripts) is **zero**.
- **SC-002**: After merge, the count of tracked files (visible in `git ls-files`) decreases by **at least 50** relative to the pre-cleanup baseline at `fea31c0`. (Per the 2026-05-26 clarification, file-cleanup is the primary value of v0.0.0; size reduction is incidental. Actual reduction is ~67 file-index removals: 1 root draft + 45 `docs/benchmarks/` deletions + 5 obsolete integration tests + 2 stale scripts + 13 `logs/` un-trackings + 1 checkpoint un-tracking. The ≥50 floor preserves ~25% headroom matching the original size-based ratio. Headline framing: "~67 fewer tracked files in a fresh clone; ~2 MB of milestone-era `.md` writeups + obsolete tests + scripts removed; 9 baseline-chain JSONs retained per FR-003 exception".)
- **SC-003**: After merge, a fresh `git clone` of the repository produces a working tree whose `git status` is clean (no untracked files coming from `logs/` or elsewhere) on a machine that has never run a sweep.
- **SC-004**: After merge, running `git show <tag>:<deleted-path>` succeeds for **every** path deleted by FR-002 through FR-006, where `<tag>` is the milestone tag corresponding to the file's owning milestone (verified by spot-checking at least one file per milestone tag named in the tag list).
- **SC-005**: After merge, `make lint typecheck test` completes in the same green state as on `main` at `fea31c0` (no new failures, no skipped tests that weren't already skipped).
- **SC-006**: After merge, the M6.2 fake-backed validate sweep completes without error against `fake_server`, proving zero functional regression in the current milestone's runtime path.
- **SC-007**: After merge, a reader who lands on `ANALYSIS.md` and follows the new housekeeping subsection's guidance can recover any deleted milestone-era benchmark report within **30 seconds** of reading — measured by following the documented `git show` command verbatim.
- **SC-008**: After merge, both `v0.0.0` and `milestone/m6.2-token-budget` annotated tags are reachable from the merge commit's history and are pushed to `origin`.

## Assumptions

- **The M6.2 research-deliverable tag is already in place.** `milestone/m6.2-token-budget` was created at `fea31c0` on 2026-05-26 and pushed to origin (see git tag list and recent session work). The spec carries the tag-creation item from `docs/PLAN.md` § v0.0.0 scope (1) as already-complete background, not as an open requirement; FR-016 only asserts the tag remains in place.
- **All 15 prior milestone tags (`milestone/m2-…` through `milestone/m6.1.3-…`) are pushed to origin** and serve as the canonical recovery path for every file slated for deletion. Verified at spec-time via `git tag --list 'milestone/*'`.
- **`docs/benchmarks/summary.md`** is a 6-line redirect stub. Per the 2026-05-26 clarification (binding), it is deleted alongside the milestone-prefixed files, and the two internal references (`docs/PLAN.md`, `ANALYSIS.md`) are updated to remove the dangling link. README + `ANALYSIS.md` provide sufficient discoverability of milestone findings going forward.
- **`docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl`** was untracked at initial spec authoring but became tracked when the `after_specify` auto-commit hook ran `git add .`. Per the 2026-05-26 clarification (binding), checkpoint files are not published artifacts: the global pattern `**/*.checkpoint.jsonl` is added to `.gitignore` (FR-007) and the existing tracked file is untracked via `git rm --cached` (FR-008). The file itself stays on disk for the operator who has the in-progress sweep state; future sweeps' checkpoints will be ignored automatically.
- **No CI workflow currently runs the deleted M4 / M5 integration smoke tests.** The repository's primary CI was already trimmed of M1-era benchmark posting in a prior commit (`60d0867`, `4931c4c`). FR-013 (the standard `make lint typecheck test` gate) will catch any remaining workflow reference if one exists.
- **The current milestone's tracked artifacts (`m6_2-*` family in `docs/benchmarks/`)** stay in place and continue to be the canonical M6.2 published outputs. Any future re-runs append; no re-publication is triggered by this cleanup.
- **The `tools/benchmark/` Python source tree is out of scope for this beat.** `v0.0.1` is the dedicated bench-harness refactor beat where ~93 modules collapse to ~25; this spec must not anticipate any of that work.
- **The `packages/` workspace and `proto/` schema are out of scope for this beat.** `v0.1.0` is the dedicated PyPI release prep beat where `pyproject.toml` metadata is filled in and a release workflow is added; this spec must not anticipate any of that work.
- **The cleanup is bisectable and reversible.** Per the 2026-05-26 clarification (binding), the cleanup ships as one PR with N ordered commits — one per FR group (working-tree deletions, `logs/` un-tracking, checkpoint un-tracking, ANALYSIS housekeeping subsection, `.gitignore` rules, `v0.0.0` tag creation). Each commit is small enough that `git revert` of any single piece is safe and meaningful.
- **No `specs/*` directory contents are touched.** The historical specs (`specs/001-*` through `specs/027-m6-2-token-budget`) are the canonical research record and stay in full as documentation.

## Dependencies

- **Inputs**:
  - `docs/PLAN.md` § "v0.0.0 — Post-M6.2 housekeeping (planned)" — authoritative scope and acceptance gates.
  - The 16 pre-existing annotated milestone tags (`milestone/m2-ground-truth` through `milestone/m6.2-token-budget`) — recovery path for deleted files.
  - `ANALYSIS.md` (target of the FR-009 / FR-010 / FR-011 documentation edit).
  - `.gitignore` (target of the FR-007 edit).

- **Sequenced after**: M6.2 — Token-Budget Characterization (delivered 2026-05-26, merged via PR #32).

- **Blocks**:
  - **`v0.0.1` — Bench-harness refactor**: the harness refactor's tag-based recovery argument depends on the v0.0.0 cleanup having shipped first (and on the M6.2 tag being in place).
  - **`v0.1.0` — First PyPI release**: release prep assumes a clean working tree under `v0.0.0` baseline.
  - **M7 — Corpus Expansion**: M7 spec authoring is easier against the cleaned tree (smaller `grep` surface, less risk of cargo-culting M3/M4/M5.x conventions that are obsolete under M6.x dispatch + classifier discipline).

- **Does not block**: Any external consumer; there are no external consumers yet (pre-PyPI).
