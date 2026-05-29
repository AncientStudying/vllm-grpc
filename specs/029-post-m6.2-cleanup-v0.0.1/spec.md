# Feature Specification: v0.0.1 — Bench-harness refactor

**Feature Branch**: `chore/post-m6.2-cleanup-v0.0.1`
**Created**: 2026-05-29
**Status**: Draft
**Input**: User description: "v0.0.1 as described in docs/PLAN.md"

## Overview

Collapse the benchmark harness under `tools/benchmark/src/vllm_grpc_bench/` from its current stratified, milestone-prefixed layout into a single forward-evolving codebase. Today the harness is an archaeological dig: 84 source modules and 137 test files, the great majority of which are frozen scaffolding from delivered milestones (M3, M4, M5, M5.1, M5.2, M6, M6.1, M6.1.1, M6.1.2, M6.1.3). The current milestone's sweep code still depends on a handful of types and helpers buried inside those legacy modules, so the legacy code cannot simply be deleted — naive deletion breaks the live harness.

This beat does the work in three ordered moves: (A) **hoist** the still-used types and helpers out of legacy modules into new generic homes; (B) **rewrite imports** so the live code (the current-milestone sweep plus the genuinely shared infrastructure) points at the generic homes; (C) **delete** the now-orphaned legacy modules and their tests. The net effect is a harness that reads as one coherent codebase ready to grow into M7's corpus axis and M8's model axis, rather than a stratified pile that drags every prior milestone's wiring along with it.

This is the second beat on the project's parallel `v*` semver track. `v*` tags mark *codebase state* (maintenance, release readiness); `milestone/*` tags mark *research deliverables*. Every legacy module and test deleted here is fully recoverable: all 16 milestone tags (M2 through M6.2) were pushed to origin as of 2026-05-26, so any contributor wanting the old M3 / M5.2 / M6.1.x harness checks out the matching `milestone/m*` tag.

This is a **structural** refactor only. No wire format changes (`.proto` files untouched), no `vllm` dependency changes, no runtime `packages/*` changes, and no change to the measured behavior of the retained sweep code. PyPI release prep and `packages/*` work are deferred to `v0.1.0`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Live harness runs entirely from generic homes (Priority: P1)

A maintainer needs the still-used types and helpers that the live harness depends on to live in clearly-named generic modules (`types.py`, `prompts.py`, `timing.py`, `exceptions.py`) instead of being scattered across milestone-prefixed legacy modules (`m3_types`, `m5_2_regen`, `m6_1_types`, `m6_1_2_types`, `m6_1_1_timing`, `m3_sweep`, `m6_rpc_driver`). After this story ships, the current-milestone sweep modules and the shared infrastructure import these symbols from the new generic homes; no live module reaches into a milestone-prefixed legacy module for them. The harness produces byte-identical results to before — only the import graph changed.

**Why this priority**: This is the load-bearing prerequisite for the deletion. Until the live code stops importing types and helpers out of legacy modules, the legacy modules cannot be removed. On its own this story already delivers value: it untangles the cross-milestone import dependency that makes the harness hard to read and reason about, even before a single file is deleted.

**Independent Test**: After the hoist + import rewrite, grep the live (non-legacy, non-test) modules for imports of the hoisted symbols — they resolve to `types.py` / `prompts.py` / `timing.py` / `exceptions.py`, not to any `m*_` module. Run `make lint typecheck test` (green) and `python -m vllm_grpc_bench.m6_2_validate` against `fake_server` (completes end-to-end), proving the rewrite preserved behavior.

**Acceptance Scenarios**:

1. **Given** the hoist step is complete, **When** a maintainer inspects `tools/benchmark/src/vllm_grpc_bench/`, **Then** `types.py`, `prompts.py`, `timing.py`, and `exceptions.py` exist and define the hoisted symbols enumerated in FR-002.
2. **Given** the import-rewrite step is complete, **When** the maintainer greps the current-milestone sweep modules and the shared-infrastructure modules for the hoisted symbols, **Then** every reference imports from the new generic home, and none imports from a milestone-prefixed legacy module.
3. **Given** the hoist + rewrite is complete (before any deletion), **When** `mypy --strict` and `ruff` are run, **Then** both pass with no new errors.
4. **Given** the hoist + rewrite is complete, **When** `python -m vllm_grpc_bench.m6_2_validate` runs against `fake_server`, **Then** it completes end-to-end with no behavior change versus the pre-refactor baseline.

---

### User Story 2 - Legacy modules and tests are gone, harness is lean (Priority: P2)

A contributor opening the harness sees a forward-only codebase: the generic homes, the genuinely shared infrastructure, and the current milestone's sweep code — and nothing else. The frozen milestone modules (`m3_*`, `m4_*`, `m5*_*`, the `m6_*` family, `m6_1*_*`, `m6_1_1_*`, `m6_1_2_*`, `m6_1_3_*`) and their matching test files are removed from the working tree. Module count drops from 84 toward the PLAN's ~25 target and test-file count from 137 toward ~35.

**Why this priority**: This is the headline payoff of the beat — the reason it shrinks the diff surface M7 and M8 read against. It depends on US1 (the live code must stop importing legacy symbols first), so it ships second, but it is the visible outcome that justifies the work.

**Independent Test**: After the deletion, `ls tools/benchmark/src/vllm_grpc_bench/` shows zero modules matching the legacy deletion patterns in FR-004 (the current-milestone `m6_2_*` family is retained); `ls tools/benchmark/tests/` shows zero test files matching the corresponding legacy patterns. `make lint typecheck test` is green and the `m6_2_validate` smoke still completes — proving nothing live depended on the deleted code.

**Acceptance Scenarios**:

1. **Given** the deletion step is complete, **When** `ls tools/benchmark/src/vllm_grpc_bench/` is run, **Then** no module matches `m3_*`, `m4_*`, `m5*_*`, `m6_sweep`/`m6_types`/`m6_reporter`/`m6_smoke`/`m6_seed`/`m6_supersede`/`m6_engine_cost`/`m6_rpc_driver`, `m6_1_*`, `m6_1_1_*`, `m6_1_2_*`, or `m6_1_3_*`, and the `m6_2_*` family is still present.
2. **Given** the deletion step is complete, **When** `ls tools/benchmark/tests/` is run, **Then** no test file matches the legacy patterns `test_m3_*`, `test_m4_*`, `test_m5*`, `test_m6_*`, `test_m6_1*`, `test_m6_1_1_*`, `test_m6_1_2_*`, or `test_m6_1_3_*`, and `test_m6_2_*` files remain.
3. **Given** the deletion step is complete, **When** `make lint typecheck test` is run, **Then** the full suite passes with no regressions versus the pre-refactor baseline.
4. **Given** the deletion step is complete, **When** `python -m vllm_grpc_bench.m6_2_validate` runs against `fake_server`, **Then** it completes end-to-end.

---

### User Story 3 - A legacy harness is recoverable on demand (Priority: P3)

A researcher who later needs the exact M5.2 (or any earlier milestone's) harness or its result data checks out the matching `milestone/m*` annotated tag and finds the legacy modules and benchmark artifacts intact at that point in history. The deletion on `main` removes the files from the forward-evolving tree without losing the ability to reconstruct any prior milestone's measurement environment.

**Why this priority**: This is the safety net that makes the deletion defensible rather than destructive. It is largely guaranteed by the milestone tags created in `v0.0.0`, so it is an invariant to verify rather than new functionality to build — hence lowest priority. But the verification is a required acceptance gate.

**Independent Test**: After the merge, `git checkout milestone/m5.2-transport-tuning` followed by `ls tools/benchmark/src/vllm_grpc_bench/m5_2_*` still lists the legacy M5.2 harness modules; `git show milestone/m5.2-transport-tuning:tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py` returns the historical file content.

**Acceptance Scenarios**:

1. **Given** a deleted legacy module `<path>` that was committed under milestone tag `milestone/m<N>`, **When** a researcher runs `git show milestone/m<N>:<path>`, **Then** the historical content is returned intact.
2. **Given** the merge commit on `main`, **When** a researcher checks out `milestone/m5.2-transport-tuning` and lists `tools/benchmark/src/vllm_grpc_bench/m5_2_*`, **Then** the legacy M5.2 modules are present at that tag.
3. **Given** the merge commit, **When** a reader opens `ANALYSIS.md`, **Then** a short subsection documents the refactor and names the tag-based recovery path for legacy harnesses.

---

### Edge Cases

- **Hidden legacy dependency surfaces during rewrite**: a live module turns out to import a legacy symbol the PLAN's hoist list (FR-002) does not name. The hoist set must be extended to cover it (or the symbol confirmed dead and the importing call site updated) before the corresponding legacy module can be deleted; the symbol-collapse details are resolved in `/speckit-clarify`.
- **Symbol name collision on collapse**: `M5_2CohortKind` and `M6_1_2CohortKind` are collapsed into a single `CohortKind`, and `M5_2SchemaValidationFailed` is renamed to `SchemaValidationFailed`. If the two cohort enums carry different member sets, the collapse must reconcile them (resolved in `/speckit-clarify`).
- **A legacy test imports a hoisted symbol**: legacy tests are deleted wholesale with their modules; any retained test that referenced a hoisted symbol must be repointed at the generic home, not left importing a deleted module.
- **Deletion leaves a dangling reference in docs or CLI help**: any `docs/` text or `__main__.py` CLI surface that names a deleted module must be updated so no dangling reference ships.
- **`m6_2_*` retained but still importing a deleted module**: the current-milestone family must be fully repointed at generic homes in US1; if any `m6_2_*` module still imports a legacy module at deletion time, the deletion would break the live harness and the gate fails.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The harness MUST gain four new generic home modules under `tools/benchmark/src/vllm_grpc_bench/`: `types.py`, `prompts.py`, `timing.py`, and `exceptions.py`.
- **FR-002**: The generic homes MUST receive the still-used symbols hoisted from legacy modules, at minimum: `types.py` ← `EndpointTuple`, `RTTRecord`, `RunCohort` (from `m3_types`), a single `CohortKind` collapsed from `M5_2CohortKind` and `M6_1_2CohortKind`, `M6_1_CELLS` (from `m6_1_types`), and `M6_1_2_COHORTS` (from `m6_1_2_types`); `prompts.py` ← `DEFAULT_CHAT_MAX_TOKENS` and `build_chat_prompt` (from `m3_sweep`) and `_build_chat_prompt` (from `m6_rpc_driver`), collapsed where the bodies have converged; `timing.py` ← `extract_rest_timings` (from `m6_1_1_timing`); `exceptions.py` ← `M5_2SchemaValidationFailed` (from `m5_2_regen`), renamed `SchemaValidationFailed`.
- **FR-003**: Every live module — the current-milestone `m6_2_*` family plus the shared-infrastructure modules (`runner`, `metrics`, `reporter`, `rest_cohort`, `modal_endpoint`, `ttft`, `symmetric_prompts`, `rtt_probe`, and the others not matching a legacy deletion pattern) — MUST import the hoisted symbols from their new generic homes, with no live import remaining to a milestone-prefixed legacy module for those symbols.
- **FR-004**: The import rewrite MUST be performed incrementally (one module at a time) with `mypy --strict` and `ruff` passing after each module is repointed, so the rewrite is bisectable.
- **FR-005**: The legacy source modules MUST be deleted: `m3_*.py`, `m4_*.py`, `m5*_*.py`, the `m6_*` family (`m6_sweep`, `m6_types`, `m6_reporter`, `m6_smoke`, `m6_seed`, `m6_supersede`, `m6_engine_cost`, `m6_rpc_driver`), `m6_1*_*.py`, `m6_1_1_*.py`, `m6_1_2_*.py`, and `m6_1_3_*.py`. The current-milestone `m6_2_*` family MUST be retained.
- **FR-006**: The legacy test files matching the deleted modules MUST be deleted (`test_m3_*`, `test_m4_*`, `test_m5*`, `test_m6_*`, `test_m6_1*`, `test_m6_1_1_*`, `test_m6_1_2_*`, `test_m6_1_3_*`), while `test_m6_2_*` files and tests covering retained shared infrastructure are kept.
- **FR-007**: The refactor MUST NOT change the measured behavior of the retained sweep code. The structural moves (hoist, import rewrite, deletion) are behavior-preserving; no sweep semantics, metric definitions, or report shapes change.
- **FR-008**: After the deletion, no retained module (live source or retained test) MAY import any deleted legacy module. A residual import is a defect that fails the gate.
- **FR-009**: All three CI gates MUST pass on the final branch state: lint + format (`ruff`), type-check (`mypy --strict`), and the unit-test suite — with no suppressions added to mask refactor fallout.
- **FR-010**: `python -m vllm_grpc_bench.m6_2_validate` against `fake_server` MUST complete end-to-end on the final branch state.
- **FR-011**: Every deleted legacy module and benchmark artifact MUST remain recoverable via its corresponding `milestone/m*` annotated tag; no milestone tag is moved or deleted by this beat.
- **FR-012**: `ANALYSIS.md` MUST gain a short subsection documenting the harness refactor and naming the tag-based recovery path for legacy harnesses.
- **FR-013**: Any dangling reference to a deleted module in `docs/`, CLI help (`__main__.py`), or other retained text MUST be removed or repointed so the final tree contains no reference to a deleted module path.
- **FR-014**: The beat MUST produce: an annotated tag `v0.0.1` on the merge commit, the branch `chore/post-m6.2-cleanup-v0.0.1`, and a PR closing the refactor.
- **FR-015**: The beat MUST NOT touch `.proto` files, the `vllm` dependency, runtime `packages/*`, or `specs/*` history (the canonical research record is kept in full).

### Key Entities

- **Generic home module**: A new, milestone-agnostic module (`types.py`, `prompts.py`, `timing.py`, `exceptions.py`) that owns a category of still-used symbols formerly scattered across legacy modules.
- **Hoisted symbol**: A type alias, constant, class, or helper function that the live harness still uses, relocated (and sometimes collapsed/renamed) from a legacy module into a generic home.
- **Legacy module**: A milestone-prefixed source module (`m3_*`, `m4_*`, `m5*`, `m6_*`/`m6_1*`/`m6_1_1*`/`m6_1_2*`/`m6_1_3*`) whose milestone is delivered and frozen; slated for deletion once its still-used symbols are hoisted. Excludes the current-milestone `m6_2_*` family.
- **Shared infrastructure module**: A non-milestone-prefixed live module (e.g., `runner`, `metrics`, `reporter`, `rest_cohort`, `modal_endpoint`, `ttft`, `symmetric_prompts`, `rtt_probe`) retained and repointed at the generic homes.
- **Milestone tag**: An annotated `milestone/m*` tag marking a delivered research deliverable; the recovery path for any deleted legacy module or artifact.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After the refactor, `tools/benchmark/src/vllm_grpc_bench/` contains **zero** modules matching the legacy deletion patterns of FR-005 (verifiable by glob), while the four generic homes and the `m6_2_*` family are present.
- **SC-002**: After the refactor, `tools/benchmark/tests/` contains **zero** test files matching the legacy patterns of FR-006, while `test_m6_2_*` and shared-infrastructure tests remain.
- **SC-003**: The harness source-module count drops from 84 to approximately the PLAN's ~25 target (≤ 30), and the test-file count from 137 to approximately ~35 — reported as the headline reduction.
- **SC-004**: A search of every retained module for imports of any deleted legacy module returns **zero** matches (the de-tangle is complete).
- **SC-005**: `make lint typecheck test` passes on the final branch state with no new failures relative to the pre-refactor baseline and no newly-added lint/type suppressions.
- **SC-006**: `python -m vllm_grpc_bench.m6_2_validate` against `fake_server` completes end-to-end on the final branch state.
- **SC-007**: For each named milestone (at minimum `milestone/m5.2-transport-tuning`), checking out the tag and listing its milestone-prefixed modules shows the legacy harness intact, and `git show <tag>:<deleted-path>` returns historical content — proving recoverability.
- **SC-008**: An annotated `v0.0.1` tag exists on the merge commit and `ANALYSIS.md` contains the refactor + recovery-path subsection.

## Assumptions

- **Current-milestone family retained**: The `m6_2_*` modules are the live, forward-evolving milestone code and are retained (and repointed at generic homes), not deleted. The PLAN's Step C deletion list deliberately omits `m6_2_*`.
- **Shared infrastructure retained**: The 18 non-milestone-prefixed modules (e.g., `runner`, `metrics`, `reporter`, `rest_cohort`, `modal_endpoint`, `ttft`, `symmetric_prompts`, `rtt_probe`, `mock_engine`, `fake_server`, `io`, `ci`, `compare`, `corpus`, `channel_config`, `rest_shim`, `__main__`, `__init__`) are retained. Whether any M3-era shared module (e.g., `channel_config`, `corpus`, `compare`) is itself dead and additionally deletable is a `/speckit-plan` discovery; the conservative default is to keep them.
- **Measured starting state**: As of this branch, the harness has 84 source modules (66 milestone-prefixed, of which 11 are the retained `m6_2_*` family ⇒ ~55 legacy modules to delete) and 137 test files (117 milestone-prefixed). The PLAN's "~93 modules → ~25" framing is approximate; the precise end-state count is reconciled in `/speckit-clarify` and `/speckit-plan`, and SC-001/SC-002 are stated as pattern-based (zero legacy modules) rather than an exact total to stay crisply verifiable.
- **Symbol-collapse details deferred to `/speckit-clarify`**: The exact reconciliation of `M5_2CohortKind` + `M6_1_2CohortKind` → `CohortKind`, the `SchemaValidationFailed` rename, and the `build_chat_prompt` / `_build_chat_prompt` collapse (where bodies have converged) surface as clarification questions per the PLAN's stated speckit cycle.
- **Hoist list may grow**: The PLAN enumerates ~6 type aliases and ~3 helpers as the transitive legacy dependencies of the live code. If `/speckit-plan` discovers additional live-code imports of legacy symbols, the hoist set in FR-002 is extended accordingly before deletion — the requirement is "no live import of a legacy module remains," not "exactly these nine symbols."
- **Milestone tags exist and are pushed**: All 16 `milestone/m*` tags (M2 through M6.2) were created and pushed to origin in `v0.0.0`; recoverability (US3) relies on them and this beat does not create or move them.
- **Behavior-preserving**: This is a pure structural refactor. No `.proto`, `vllm`-dependency, runtime `packages/*`, or sweep-semantics changes; the measured outputs of the retained harness are unchanged.
- **Single PR**: The work lands as one PR on `chore/post-m6.2-cleanup-v0.0.1` with bisectable commits (hoist, per-module import rewrites, deletion batches, docs + tag), matching the PLAN's ~17-task estimate.
