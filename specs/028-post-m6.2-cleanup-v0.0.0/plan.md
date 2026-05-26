# Implementation Plan: v0.0.0 — Post-M6.2 Housekeeping

**Branch**: `chore/post-m6.2-cleanup-v0.0.0` (spec slot `028-post-m6.2-cleanup-v0.0.0`)
**Date**: 2026-05-26 (re-derived after 2026-05-26 clarify cycle adding FR-003 exception)
**Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/028-post-m6.2-cleanup-v0.0.0/spec.md`

## Summary

Trim ~59 tracked files of milestone-specific result data, one-shot draft notes, obsolete integration tests, and stale operator scripts from the `main` working tree. Ship as one PR with five ordered, bisectable commits (one per FR group) plus a sixth post-merge `v0.0.0` annotated tag; leave all `tools/benchmark/src/`, `packages/`, `proto/`, `frontend/` source untouched (those are `v0.0.1` / `v0.1.0` territory). Every deleted path stays reachable through the pre-existing `milestone/m2-…` through `milestone/m6.2-…` annotated tags, so the operation is fully reversible without history rewriting.

**Approach**: a deletion manifest (concrete file list, 21 `.md` writeups + 1 `.gz` events sidecar + 2 output-only `.json` + 12 `phase-*` JSON + `summary.md` = 37 `docs/benchmarks/` deletions, plus 1 root draft + 5 integration tests + 2 stale scripts + 13 `logs/` index entries + 1 checkpoint = **59 file-index removals total**) drives the `git rm`s. **The FR-003 exception (per 2026-05-26 clarification) retains 9 `docs/benchmarks/*.json` files** that `tools/benchmark/src/` reads at runtime via default-path constants (the M3→M6.2 baseline chain): `m3-channel-tuning-time.json`, `m4-time-axis-tuning.json`, `m5-cross-host-validation.json`, `m5_1-rest-vs-grpc.json`, `m5_2-transport-vs-tuning.json`, `m6-real-engine-mini-validation.json`, `m6_1-real-prompt-embeds.json`, `m6_1_1-engine-cost-instrumentation.json`, `m6_1_3-attribution-closure.json`. `.gitignore` gains two rules (`logs/`, `**/*.checkpoint.jsonl`). `ANALYSIS.md` gains a short "Repo housekeeping" subsection near the end of the document; the three dangling `docs/benchmarks/summary.md` references in `ANALYSIS.md` and the one in `docs/PLAN.md` are rewritten or removed. After merge, `v0.0.0` is created as an annotated tag and pushed to origin alongside the already-present `milestone/m6.2-token-budget`.

## Technical Context

**Language/Version**: N/A — no application source code is modified. The repo's overall language is Python 3.12 (per `pyproject.toml`), but v0.0.0 changes only documentation, configuration (`.gitignore`), tests-as-files (deletions), and git metadata.
**Primary Dependencies**: `git` (≥2.20 for safe `git rm --cached` semantics), POSIX shell utilities (`rm`, `find`). No new Python dependencies.
**Storage**: Filesystem + git object database. No data store.
**Testing**: `make lint typecheck test` (existing CI gate — full pass required, per FR-013). M6.2 fake-backed validate smoke covered by `tools/benchmark/tests/test_m6_2_validate_cli.py` + `test_m6_2_publish_cli.py` (the `--m6_2-validate --m6_2-skip-deploy` stub-backed CLI smokes), run as part of `make test` (per FR-014).
**Target Platform**: Developer workstation (macOS / Linux); CI runners (Linux). No runtime platform impact since no runtime code is changed.
**Project Type**: Repo maintenance / housekeeping beat (`v*` semver track, distinct from `milestone/*` research track).
**Performance Goals**: One-shot operation. Time-to-completion is measured in operator-minutes, not in service latency. SC-007 sets the only performance-shaped gate: a reader can recover any deleted file in ≤30 s using the documented `git show` command.
**Constraints**:
  - No file under `tools/benchmark/src/`, `packages/`, `proto/`, `frontend/` may be modified (FR-001).
  - Every deleted file MUST remain reachable from an existing `milestone/m*` tag (FR-012).
  - `make lint typecheck test` MUST stay green at no-regression-vs-`fea31c0` (FR-013, SC-005).
  - M6.2 fake-backed smoke MUST stay green (FR-014, SC-006).
  - **The 9 baseline-chain JSONs in FR-003's exception list MUST NOT be deleted** (per 2026-05-26 clarify cycle — they are runtime inputs to `tools/benchmark/src/`).
  - History is NOT rewritten; recovery is via tags, not via deep `git log` archaeology.
**Scale/Scope**: 59 file-index removals total (after the FR-003 exception retains 9 JSONs):
  - 37 in `docs/benchmarks/` (21 `.md` writeups + 1 `.gz` sidecar + 2 output-only `.json` (`m6_1_2-methodology-discipline.json`, `m6_1_3-attribution-closure-validate.json`) + 12 `phase-*` JSON files + `summary.md`)
  - 5 in `tests/integration/` (the M4 / M5 obsolete smokes)
  - 1 in `scripts/python/` (`reprocess_m5_supersede.py`)
  - 1 in `scripts/setup/` (`phase2-env.sh`)
  - 1 at repo root (`M6_2-ANALYSIS-FRAMING-DRAFT.md`)
  - 13 in `logs/` (un-tracked, files stay on disk)
  - 1 checkpoint (`docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl` — un-tracked, file stays on disk)
  
  Plus 2 `.gitignore` rules added, 1 `ANALYSIS.md` subsection added, 4 reference rewrites for `summary.md` (3 in `ANALYSIS.md`, 1 in `docs/PLAN.md`), 1 new annotated tag (`v0.0.0`).
  
  **Working-tree reduction floor**: ≥50 fewer tracked files (SC-002, per 2026-05-26 clarify cycle — switched from size-MB to file-count metric).

No `NEEDS CLARIFICATION` items — all candidate ambiguities were resolved in the spec's `## Clarifications` § 2026-05-26 session (3 original Q&A + 4 added during /speckit-implement discovery cycle = 7 total).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| **I. Proto-First** | N/A | No `.proto` edits and no runtime code that consumes `.proto` is touched. |
| **II. Library Dependency, Not Fork** | N/A | No `vllm` imports are added or removed; no upstream code is touched. |
| **III. Phase Discipline** | **PASS** | v0.0.0 is the canonical post-M6.2 housekeeping beat per `docs/PLAN.md` § "v0.0.0 — Post-M6.2 housekeeping (planned)". No `v0.0.1` (bench-harness refactor) or `v0.1.0` (PyPI release) functionality leaks into this scope — FR-001 enforces source preservation; the FR-003 exception is *driven by* phase-discipline (we can't delete files the current phase's source code depends on without violating FR-001 by editing those defaults). The spec's `Out of scope` / Assumptions sections explicitly defer both follow-ups. No M7 / M8 anticipatory work is performed. |
| **IV. CI is the Merge Gate** | **PASS** | FR-013 (`make lint typecheck test` green) and SC-005 (no new failures vs `fea31c0`) preserve the CI gate. The deletion of CI-uninvolved integration tests (the M4 / M5 smokes are not referenced by any active CI workflow per Assumptions) does not weaken the gate. *Validated 2026-05-26 during /speckit-implement: post-deletion `make check` passes 1575 / 0 failed / 2 skipped, no regressions vs `fea31c0`.* |
| **V. Honest Measurement** | **PASS** | The `docs/benchmarks/` deletions remove only the `.md` *narrative copies* on `main`; the underlying numbers stay reachable from milestone tags (FR-012), AND **the 9 baseline-chain JSONs (the actual numeric source data) stay tracked** under the FR-003 exception, strengthening Honest Measurement: anyone running the M5.1 / M5.2 / M6 / M6.1 / M6.1.1 / M6.1.2 / M6.1.3 / M6.2 sweep can immediately read the baseline data without an extra `git show` step. No benchmark result is "buried" — the recovery path for narratives is documented in the new `ANALYSIS.md` housekeeping subsection (FR-009 / FR-010). |

**Post-Phase 1 re-check**: Re-evaluated below after design artifacts are written — no new violations introduced. PASS.

## Project Structure

### Documentation (this feature)

```text
specs/028-post-m6.2-cleanup-v0.0.0/
├── spec.md              # /speckit-specify + /speckit-clarify output (amended 2026-05-26 with FR-003 exception)
├── plan.md              # This file (/speckit-plan output, re-derived 2026-05-26 post-clarify)
├── research.md          # Phase 0 output — deletion manifest derivation, FR-003 exception audit, reference-audit findings, tag→path recovery map
├── data-model.md        # Phase 1 output — entity table (deletion manifest entries, retained JSONs, tags, gitignore rules)
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
│   └── benchmarks/                             # DELETE 37 files (21 .md writeups + 1 .gz events sidecar + 2 output-only .json + 12 phase-* JSON + summary.md); RETAIN: M6.2 outputs (~7 files) AND the 9 baseline-chain JSONs in FR-003's exception list
├── tests/
│   └── integration/                            # DELETE 5 files (M4 + M5 smokes); keep 6 (grpc / chat / completions bridges + fixtures)
├── scripts/
│   ├── python/reprocess_m5_supersede.py        # DELETE
│   └── setup/phase2-env.sh                     # DELETE
└── logs/                                       # `git rm -r --cached` 13 index entries; directory stays on disk via .gitignore
```

**Structure Decision**: Repository-maintenance feature operating entirely on existing top-level directories. No new directories or modules; no rearrangement of `tools/benchmark/src/`, `packages/`, `proto/`, or `frontend/` (those are out-of-scope per FR-001 and explicitly reserved for `v0.0.1` / `v0.1.0`).

## Phase 0 — Research

See [`research.md`](./research.md) for the full output. Summary of resolved unknowns (post-clarify):

- **Concrete deletion manifest in `docs/benchmarks/`**: 37 files (21 `.md` writeups for the M3–M6.1.3 milestones + 1 `.gz` events sidecar + 2 output-only `.json` (`m6_1_2-methodology-discipline.json`, `m6_1_3-attribution-closure-validate.json`) + 12 `phase-*` JSON files + `summary.md`). The FR-003 exception retains 9 baseline-chain JSONs.
- **FR-003 exception audit** (new in 2026-05-26 clarify cycle): Enumerated 9 `docs/benchmarks/*.json` files that `tools/benchmark/src/` opens at runtime via default-path constants. Audit anchor: `grep -hoE 'docs/benchmarks/[^"'\'']+\.json' tools/benchmark/src/vllm_grpc_bench/*.py | sort -u`. List matches the M3→M6.2 baseline chain exactly.
- **Concrete deletion manifest in `tests/integration/`**: 5 files (`test_m4_schema_e2e.py`, `test_m4_sweep_e2e.py`, `test_m5_modal_smoke.py`, `test_m5_1_modal_smoke.py`, `test_m5_2_modal_smoke.py`). The 6 retained files (`__init__.py`, `conftest.py`, `fake_frontend.py`, `test_grpc_client.py`, `test_chat_bridge.py`, `test_completions_bridge.py`) account for ~144 KB.
- **Reference audit for `summary.md`**: 3 references in `ANALYSIS.md` (lines 5, 14, 64) + 1 reference in `docs/PLAN.md` (line 869). Per the clarification, all four are rewritten / removed.
- **Tag→path recovery map**: 16 milestone tags cover every deletion-target path. Spot-check verified.
- **`logs/` baseline**: 13 index entries (11 M4 sweep logs + `m4-full.current` + `m4-full.pid`). Recoverable via `milestone/m4-time-axis`.
- **`.gitignore` audit**: today's file has 82 lines. The two new rules (`logs/` and `**/*.checkpoint.jsonl`) are appended in a new `# v0.0.0 housekeeping (per spec FR-007)` section near the end.
- **`ANALYSIS.md` housekeeping subsection placement**: appended as a new top-level `## Repo housekeeping` section at the end of the document. Satisfies FR-011.
- **`v0.0.0` tag message format**: matches the project's existing milestone-tag convention.

## Phase 1 — Design

### Data model

See [`data-model.md`](./data-model.md). The "data model" for this feature is the **deletion manifest entity** (a tuple of `{ path, owning_milestone_tag, retention_decision, size_bytes }`) plus four supporting tables: **retained JSONs (FR-003 exception)**, gitignore rules, ANALYSIS reference rewrites, and tag artifacts.

### Contracts

Intentionally omitted — no external interface. See "Project Structure" above and Phase 1 of the plan template ("Skip if project is purely internal").

### Quickstart

See [`quickstart.md`](./quickstart.md). The runbook documents the six-commit sequence in execution order:

1. **Commit 1 — Working-tree deletions (US1 / FR-002–FR-006, FR-003a)**: `git rm` for the milestone-prefixed `docs/benchmarks/` `.md` files + 2 output-only JSONs + 1 events sidecar + 13 `phase-*` files + `summary.md`, the M4/M5 integration smokes, the two stale scripts, the root draft note. **Explicitly NOT deleted**: the 9 baseline-chain JSONs (FR-003 exception). Rewrite/remove the four `summary.md` references in `ANALYSIS.md` / `docs/PLAN.md`.
2. **Commit 2 — `logs/` un-tracking (US2 / FR-008)**: `git rm -r --cached logs/`.
3. **Commit 3 — Checkpoint un-tracking (US2 / FR-008)**: `git rm --cached docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl`.
4. **Commit 4 — `.gitignore` rules (US2 / FR-007)**: append `logs/` and `**/*.checkpoint.jsonl` rules.
5. **Commit 5 — ANALYSIS housekeeping subsection (US3 / FR-009, FR-010, FR-011)**: append the new `## Repo housekeeping` section.
6. **Commit 6 — `v0.0.0` annotated tag (FR-015, FR-016)**: operator-driven `git tag -a v0.0.0` post-merge.

Each commit is small enough to revert individually. Commits 1–5 ship in the cleanup PR; commit 6 (the tag) is created against the merge commit after the PR lands.

### Agent context update

`CLAUDE.md` does not currently carry `<!-- SPECKIT START -->` … `<!-- SPECKIT END -->` markers (the project's CLAUDE.md is plain-text navigation guide). The active-feature pointer is the spec directory `specs/028-post-m6.2-cleanup-v0.0.0/`; no agent-context file edit is performed by this re-plan cycle.

## Post-Phase 1 Constitution re-check

| Principle | Re-evaluation |
|---|---|
| I. Proto-First | Still N/A. No design artifact references proto. |
| II. Library Dependency, Not Fork | Still N/A. |
| III. Phase Discipline | Still PASS. `data-model.md`, `research.md`, and `quickstart.md` all stay within v0.0.0's documented scope. The FR-003 exception is itself a phase-discipline enforcement (preserving runtime inputs the current milestone depends on). |
| IV. CI is the Merge Gate | Still PASS. `quickstart.md`'s verification step explicitly runs `make lint typecheck test` before committing each file group; CI re-runs the same suite on PR. Pre-validated by 2026-05-26 /speckit-implement discovery cycle (1575/0/2 green). |
| V. Honest Measurement | Still PASS. The data model explicitly tracks `owning_milestone_tag` for every deletion target, making the recovery-path argument auditable from the artifacts themselves. The FR-003 exception STRENGTHENS Honest Measurement by keeping numeric source data on `main`. |

**Result**: PASS. No Complexity Tracking entries required.

## Complexity Tracking

No constitutional violations to justify. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| _(none)_  | _(none)_   | _(none)_                             |
