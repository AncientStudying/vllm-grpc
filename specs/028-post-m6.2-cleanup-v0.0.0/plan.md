# Implementation Plan: v0.0.0 — Post-M6.2 Housekeeping

**Branch**: `chore/post-m6.2-cleanup-v0.0.0` (spec slot `028-post-m6.2-cleanup-v0.0.0`)
**Date**: 2026-05-26
**Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/028-post-m6.2-cleanup-v0.0.0/spec.md`

## Summary

Trim ~3.5 MB of milestone-specific result data, one-shot draft notes, obsolete integration tests, and stale operator scripts from the `main` working tree. Ship as one PR with five ordered, bisectable commits (one per FR group) plus a sixth post-merge `v0.0.0` annotated tag; leave all `tools/benchmark/src/`, `packages/`, `proto/`, `frontend/` source untouched (those are `v0.0.1` / `v0.1.0` territory). Every deleted path stays reachable through the pre-existing `milestone/m2-…` through `milestone/m6.2-…` annotated tags, so the operation is fully reversible without history rewriting.

**Approach**: a deletion manifest (concrete file list, 45 files in `docs/benchmarks/` + 5 in `tests/integration/` + 2 stale scripts + 1 root draft + 13 `logs/` index entries + 1 checkpoint) drives the `git rm`s. `.gitignore` gains two rules (`logs/`, `**/*.checkpoint.jsonl`). `ANALYSIS.md` gains a short "Repo housekeeping" subsection near the end of the document; the three dangling `docs/benchmarks/summary.md` references in `ANALYSIS.md` and the one in `docs/PLAN.md` are rewritten or removed. After merge, `v0.0.0` is created as an annotated tag and pushed to origin alongside the already-present `milestone/m6.2-token-budget`.

## Technical Context

**Language/Version**: N/A — no application source code is modified. The repo's overall language is Python 3.12 (per `pyproject.toml`), but v0.0.0 changes only documentation, configuration (`.gitignore`), tests-as-files (deletions), and git metadata.
**Primary Dependencies**: `git` (≥2.20 for safe `git rm --cached` semantics), POSIX shell utilities (`rm`, `find`). No new Python dependencies.
**Storage**: Filesystem + git object database. No data store.
**Testing**: `make lint typecheck test` (existing CI gate — full pass required, per FR-013). M6.2 fake-backed validate smoke (`python -m vllm_grpc_bench --m6_2 --fake-server` or equivalent — per FR-014).
**Target Platform**: Developer workstation (macOS / Linux); CI runners (Linux). No runtime platform impact since no runtime code is changed.
**Project Type**: Repo maintenance / housekeeping beat (`v*` semver track, distinct from `milestone/*` research track).
**Performance Goals**: One-shot operation. Time-to-completion is measured in operator-minutes, not in service latency. SC-007 sets the only performance-shaped gate: a reader can recover any deleted file in ≤30 s using the documented `git show` command.
**Constraints**:
  - No file under `tools/benchmark/src/`, `packages/`, `proto/`, `frontend/` may be modified (FR-001).
  - Every deleted file MUST remain reachable from an existing `milestone/m*` tag (FR-012).
  - `make lint typecheck test` MUST stay green (FR-013).
  - M6.2 fake-backed smoke MUST stay green (FR-014).
  - History is NOT rewritten; recovery is via tags, not via deep `git log` archaeology.
**Scale/Scope**: 67 file deletions/un-trackings total (45 in `docs/benchmarks/`, 5 in `tests/integration/`, 1 in `scripts/python/`, 1 in `scripts/setup/`, 1 at repo root, 13 in `logs/`, 1 checkpoint), 2 `.gitignore` rules added, 1 `ANALYSIS.md` subsection added, 4 reference rewrites for `summary.md` (3 in `ANALYSIS.md`, 1 in `docs/PLAN.md`), 1 new annotated tag (`v0.0.0`). Working-tree reduction floor: ≥3 MB (SC-002).

No `NEEDS CLARIFICATION` items — all candidate ambiguities were resolved in the spec's `## Clarifications` § 2026-05-26 session.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| **I. Proto-First** | N/A | No `.proto` edits and no runtime code that consumes `.proto` is touched. |
| **II. Library Dependency, Not Fork** | N/A | No `vllm` imports are added or removed; no upstream code is touched. |
| **III. Phase Discipline** | **PASS** | v0.0.0 is the canonical post-M6.2 housekeeping beat per `docs/PLAN.md` § "v0.0.0 — Post-M6.2 housekeeping (planned)". No `v0.0.1` (bench-harness refactor) or `v0.1.0` (PyPI release) functionality leaks into this scope — FR-001 enforces source preservation; the spec's `Out of scope` / Assumptions sections explicitly defer both follow-ups. No M7 / M8 anticipatory work is performed. |
| **IV. CI is the Merge Gate** | **PASS** | FR-013 (`make lint typecheck test` green) and SC-005 (no new failures vs `fea31c0`) preserve the CI gate. The deletion of CI-uninvolved integration tests (the M4 / M5 smokes are not referenced by any active CI workflow per Assumptions) does not weaken the gate. |
| **V. Honest Measurement** | **PASS** | The `docs/benchmarks/` deletions remove only the *copy of record* on `main`; the underlying numbers stay reachable from milestone tags (FR-012). No benchmark result is "buried" — the recovery path is documented in the new `ANALYSIS.md` housekeeping subsection (FR-009 / FR-010) so any reader following the ANALYSIS narrative can fetch the source data with one command. |

**Post-Phase 1 re-check**: Re-evaluated below after design artifacts are written — no new violations introduced. PASS.

## Project Structure

### Documentation (this feature)

```text
specs/028-post-m6.2-cleanup-v0.0.0/
├── spec.md              # /speckit-specify + /speckit-clarify output (already on disk)
├── plan.md              # This file (/speckit-plan output)
├── research.md          # Phase 0 output — deletion manifest derivation, reference-audit findings, tag→path recovery map
├── data-model.md        # Phase 1 output — entity table (deletion manifest entries, tags, gitignore rules)
├── quickstart.md        # Phase 1 output — operator runbook for executing the cleanup locally + verifying gates
├── checklists/
│   └── requirements.md  # already on disk from /speckit-specify
└── tasks.md             # Phase 2 output (created later by /speckit-tasks — NOT created here)
```

**No `contracts/` directory.** This feature exposes no external interface: no new RPC, no new CLI command, no new public API. The "interface" is the developer workflow (read README → run cleanup → verify gates), which lives in `quickstart.md`. Per the plan template's guidance ("Skip if project is purely internal"), `contracts/` is intentionally omitted.

### Source Code (repository root)

This beat touches **no source code**. The changes are confined to:

```text
.
├── .gitignore                                  # +2 rules: `logs/`, `**/*.checkpoint.jsonl`
├── ANALYSIS.md                                 # +new "Repo housekeeping" subsection; rewrite/remove 3 summary.md refs
├── M6_2-ANALYSIS-FRAMING-DRAFT.md              # DELETE
├── docs/
│   ├── PLAN.md                                 # rewrite/remove 1 summary.md ref (Phase History section)
│   └── benchmarks/                             # DELETE 45 files (44 milestone-prefixed + summary.md); keep m6_2-* (8 files) and m6_2-*.checkpoint.jsonl untracked
├── tests/
│   └── integration/                            # DELETE 5 files (M4 + M5 smokes); keep 6 (grpc / chat / completions bridges + fixtures)
├── scripts/
│   ├── python/reprocess_m5_supersede.py        # DELETE
│   └── setup/phase2-env.sh                     # DELETE
└── logs/                                       # `git rm -r --cached` 13 index entries; directory stays on disk via .gitignore
```

**Structure Decision**: Repository-maintenance feature operating entirely on existing top-level directories. No new directories or modules; no rearrangement of `tools/benchmark/src/`, `packages/`, `proto/`, or `frontend/` (those are out-of-scope per FR-001 and explicitly reserved for `v0.0.1` / `v0.1.0`).

## Phase 0 — Research

See [`research.md`](./research.md) for the full output. Summary of resolved unknowns:

- **Concrete deletion manifest in `docs/benchmarks/`**: 45 files (44 milestone-prefixed + `summary.md`), totalling ~2.6 MB. Enumerated by glob match against the FR-003 patterns plus the FR-003a / clarification addition.
- **Concrete deletion manifest in `tests/integration/`**: 5 files (`test_m4_schema_e2e.py`, `test_m4_sweep_e2e.py`, `test_m5_modal_smoke.py`, `test_m5_1_modal_smoke.py`, `test_m5_2_modal_smoke.py`). The 6 retained files (`__init__.py`, `conftest.py`, `fake_frontend.py`, `test_grpc_client.py`, `test_chat_bridge.py`, `test_completions_bridge.py`) account for ~144 KB.
- **Reference audit for `summary.md`**: 3 references in `ANALYSIS.md` (lines 5, 14, 64) + 1 reference in `docs/PLAN.md` (line 869). Per the clarification, all four are rewritten to point at `ANALYSIS.md § M1` (or removed where the reference is structural-only — `docs/PLAN.md` line 869 is Phase-History prose and can be removed without loss).
- **Tag→path recovery map**: 16 milestone tags cover every deletion-target path. Spot-check verified at spec-time (`milestone/m5.2-transport-tuning` resolves `docs/benchmarks/m5_2-transport-vs-tuning.md`; analogous for M3 / M4 / M5 / M5.1 / M6 / M6.1 / M6.1.1 / M6.1.2 / M6.1.3).
- **`logs/` baseline**: 11 M4 sweep logs (52 KB) + 2 marker files (`m4-full.current`, `m4-full.pid`) = 13 index entries. Recoverable via `milestone/m4-time-axis`.
- **`.gitignore` audit**: today's file has 82 lines. The two new rules (`logs/` and `**/*.checkpoint.jsonl`) are appended in a new `# v0.0.0 housekeeping (per spec FR-007)` section near the end.
- **`ANALYSIS.md` housekeeping subsection placement**: appended as a new top-level `## Repo housekeeping` section at the end of the document. This satisfies FR-011 (do not interrupt milestone narrative).
- **`v0.0.0` tag message format**: matches the project's existing milestone-tag convention (single-line subject + body explaining the beat + cross-reference to `milestone/m6.2-token-budget`).

## Phase 1 — Design

### Data model

See [`data-model.md`](./data-model.md). The "data model" for this feature is the **deletion manifest entity** (a tuple of `{ path, owning_milestone_tag, retention_decision, size_bytes }`) plus three supporting tables: gitignore rules, ANALYSIS reference rewrites, and tag artifacts.

### Contracts

Intentionally omitted — no external interface. See "Project Structure" above and Phase 1 of the plan template ("Skip if project is purely internal").

### Quickstart

See [`quickstart.md`](./quickstart.md). The runbook documents the six-commit sequence in execution order:

1. **Commit 1 — Working-tree deletions (US1 / FR-002–FR-006, FR-003a)**: `git rm` for the milestone-prefixed `docs/benchmarks/` files, `summary.md`, the M4/M5 integration smokes, the two stale scripts, the root draft note. Rewrite/remove the four `summary.md` references in `ANALYSIS.md` / `docs/PLAN.md`.
2. **Commit 2 — `logs/` un-tracking (US2 / FR-008)**: `git rm -r --cached logs/`.
3. **Commit 3 — Checkpoint un-tracking (US2 / FR-008)**: `git rm --cached docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl`.
4. **Commit 4 — `.gitignore` rules (US2 / FR-007)**: append `logs/` and `**/*.checkpoint.jsonl` rules.
5. **Commit 5 — ANALYSIS housekeeping subsection (US3 / FR-009, FR-010, FR-011)**: append the new `## Repo housekeeping` section.
6. **Commit 6 — `v0.0.0` annotated tag (FR-015, FR-016)**: operator-driven `git tag -a v0.0.0` post-merge with a tag message that names the cleanup beat and cross-references `milestone/m6.2-token-budget`.

Each commit is small enough to revert individually. Commits 1–5 ship in the cleanup PR; commit 6 (the tag) is created against the merge commit after the PR lands.

### Agent context update

`CLAUDE.md` carries `<!-- SPECKIT START -->` … `<!-- SPECKIT END -->` markers at lines 1–5. The block between is updated to reference this plan file (`specs/028-post-m6.2-cleanup-v0.0.0/plan.md`) so the next session inherits the active-feature pointer.

## Post-Phase 1 Constitution re-check

| Principle | Re-evaluation |
|---|---|
| I. Proto-First | Still N/A. No design artifact references proto. |
| II. Library Dependency, Not Fork | Still N/A. |
| III. Phase Discipline | Still PASS. `data-model.md`, `research.md`, and `quickstart.md` all stay within v0.0.0's documented scope; no anticipatory tasks for `v0.0.1` or `v0.1.0` slipped in. |
| IV. CI is the Merge Gate | Still PASS. `quickstart.md`'s verification step explicitly runs `make lint typecheck test` before committing each file group; CI re-runs the same suite on PR. |
| V. Honest Measurement | Still PASS. The data model explicitly tracks `owning_milestone_tag` for every deletion target, making the recovery-path argument auditable from the artifacts themselves. |

**Result**: PASS. No Complexity Tracking entries required.

## Complexity Tracking

No constitutional violations to justify. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| _(none)_  | _(none)_   | _(none)_                             |
