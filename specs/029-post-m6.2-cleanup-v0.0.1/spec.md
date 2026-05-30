# Feature Specification: v0.0.1 — Bench-harness refactor

**Feature Branch**: `chore/post-m6.2-cleanup-v0.0.1`
**Created**: 2026-05-29
**Status**: Draft
**Input**: User description: "v0.0.1 as described in docs/PLAN.md"

## Overview

Collapse the benchmark harness under `tools/benchmark/src/vllm_grpc_bench/` from a stratified, milestone-prefixed archaeological dig into a single, milestone-agnostic, forward-evolving codebase. Today the harness is 84 source modules and 137 test files, the great majority frozen scaffolding from delivered milestones (M3, M4, M5, M5.1, M5.2, M6, M6.1, M6.1.1, M6.1.2, M6.1.3). The only live milestone code (the M6.2 sweep) still reaches into legacy modules for a handful of types and helpers, so naive deletion breaks the harness.

This beat is **forward-only**. Breaking backward compatibility is an explicit, accepted goal — module names, import paths, the CLI module surface, and even the prompt bytes a cohort sends may change. The recovery path for anything removed or changed is the corresponding `milestone/m*` annotated tag (all 16 tags, M2 through M6.2, were pushed to origin in `v0.0.0`). Because recovery is guaranteed by tags, the live tree is optimized purely for a clean forward codebase — it carries **no** backward-compat shims, re-export aliases, dead enum members, dual code paths, or milestone prefixes "just in case."

The work, in dependency order:

1. **Hoist & unify** the still-used symbols out of legacy modules into new generic homes (`types.py`, `prompts.py`, `timing.py`, `exceptions.py`), collapsing duplicates as it goes — one `CohortKind`, one chat-prompt builder, one schema-error type.
2. **De-prefix** the live `m6_2_*` family to milestone-agnostic names (`sweep.py`, `rpc_driver.py`, `validate.py`, …), merging `m6_2_types` → `types.py`, `m6_2_reporter` → the consolidated `reporter.py`, and `m6_2_prompt_source` → `prompts.py`. After this the harness reads as *the* harness, not "the m6.2 harness."
3. **Consolidate** report generation: the seven report generators (`reporter.py` plus six `m*_reporter.py`) collapse to a single `reporter.py`; thin single-purpose helper modules merge where it improves cohesion.
4. **Delete** all now-orphaned legacy modules and their tests; **rename** the retained test suite to match the de-prefixed modules.

The end state lands at roughly the PLAN's ~25 source modules and ~35 test files — a target only reachable *because* of the de-prefix and report-consolidation steps. This is the second beat on the `v*` semver track (`v*` = codebase state; `milestone/*` = research deliverables).

This remains a **structural** refactor of the bench harness only: no `.proto` changes, no `vllm` dependency changes, no runtime `packages/*` changes, and no change to *what the harness measures* (sweep methodology, metric definitions, and published report data content are preserved). PyPI release prep and `packages/*` work stay deferred to `v0.1.0`.

## Clarifications

### Session 2026-05-29

- Q: When collapsing `M5_2CohortKind` (6 members) and `M6_1_2CohortKind` (4 members) into one `CohortKind`, which member set? → A: The 4-member live set (`rest_https_edge`, `rest_plain_tcp`, `default_grpc`, `tuned_grpc_multiplexed`). The two historical members (`tuned_grpc_channels`, `tuned_grpc`) are dropped — no live code uses them, and they are recoverable via the M5.2 milestone tag. No speculative vocabulary is retained (Principle III).
- Q: The two chat-prompt builders are both live but diverge — `build_chat_prompt(iteration, cell_id)` (M5.2 format, used by shared `rest_cohort`) and `_build_chat_prompt(seed)` (M6 seed+digest format, used by the live `m6_2` path). Keep both or unify? → A: Unify to ONE seed+digest builder in `prompts.py`; repoint `rest_cohort` to it. This is a deliberate backward-compatibility break — the prompt bytes the REST cohort sends change. Acceptable per the forward-only philosophy; the M5.2 prompt convention is recoverable via the M5.2 milestone tag.
- Q: Keep the live family named `m6_2_*`, or de-prefix it to generic names? → A: De-prefix the entire 11-module `m6_2_*` family to milestone-agnostic names (`m6_2_sweep` → `sweep`, etc.), merging `m6_2_types` → `types.py`, `m6_2_reporter` → the consolidated `reporter.py`, `m6_2_prompt_source` → `prompts.py`. Import paths and the CLI module surface change by design. This is the step that turns the tree milestone-agnostic and reaches the ~25-module target.
- Q: Fold the `v0.0.0`-deferred harness simplification (report-generator consolidation, test-suite simplification) into `v0.0.1`, or defer again? → A: Fold it in. `v0.0.1` consolidates the seven report generators into a single `reporter.py`, merges thin single-purpose helper modules where cohesion improves, and renames the retained tests to match the de-prefixed modules. Task count exceeds the PLAN's ~17 estimate; this is the depth the PLAN's ~25-module / ~35-test target actually requires.
- Q: The legacy `--mN` CLI flags die automatically with their deleted sweeps. Should the ~16 surviving `--m6_2-*` operator flags de-prefix too, or stay? → A: De-prefix them to generic flags (`--m6_2-modal-region` → `--modal-region`, etc.); the `--m6_2` selector is dropped since the de-prefixed sweep is the only remaining one (it becomes the default invocation). Operator command lines change — an accepted BC break; old invocations recoverable via the M6.2 milestone tag. All legacy `--m3`…`--m6_1_3` flags and their dispatch branches are removed with the deleted code.
- Q: Published data artifacts are milestone-named (`m6_2-token-budget.{json,md}`), sit in the FR-003 baseline chain, and are referenced by `ANALYSIS.md`. Keep those names, or de-prefix output filenames too? → A: Keep milestone-named artifacts. The *code* de-prefixes; the *data deliverables* keep their milestone identity. The reporter's default output paths for the retained baseline-chain artifacts stay milestone-named so the existing `m6_2-token-budget.json` is not orphaned and `ANALYSIS.md` references stay valid. Clean separation: code = generic, research deliverables = milestone-tagged.
- Q: Realistic module landing is ~30 unless ~5 shared modules are merged. How hard is the ~25 target? → A: Invariant-gated; the count is directional.

### Session 2026-05-29 (implementation discovery)

- Q: `symmetric_prompts.py` is live (imported by `m6_2_prompt_source`/`m6_2_types`/`m6_2_validate`) yet branches on the two cohort members the 4-member `CohortKind` (Q1) drops (`tuned_grpc_channels`, `tuned_grpc`), so a 4-member collapse breaks it under `mypy --strict`. Keep 4-member or revert to 6? → A: Keep the 4-member `CohortKind` and **strip the dead `tuned_grpc_channels`/`tuned_grpc` branches from `symmetric_prompts`** (forward-only). Those branches are vestigial M5.2 5-cohort-topology logic; the forward 4-cohort harness (universe = `M6_1_2_COHORTS`) never emits either member, so the branches are dead. This confirms Q1 and adds a `symmetric_prompts` simplification to scope (the M5.2 5-cohort symmetry logic is recoverable via the M5.2 tag). The hard gate is the invariants (zero milestone-prefixed modules, exactly one reporter, exactly one chat-prompt builder, no BC shims, four generic homes) plus merging thin modules only where cohesion genuinely improves. ~25 is the direction, not a pass/fail number — no contrived merges to hit an arbitrary count.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The harness is a single milestone-agnostic codebase (Priority: P1)

A maintainer opens `tools/benchmark/src/vllm_grpc_bench/` and finds a forward-only codebase organized by *function*, not by milestone: generic homes (`types.py`, `prompts.py`, `timing.py`, `exceptions.py`), a single `reporter.py`, and de-prefixed sweep/driver/validate modules. No module name carries a milestone prefix; no live module imports a milestone-prefixed module. The hoist collapsed the duplicates: exactly one `CohortKind` (4 members), exactly one chat-prompt builder, exactly one schema-error type, one report generator.

**Why this priority**: This is the entire point of the beat — turning "the m6.2 harness with M3–M6.1.x scaffolding bolted on" into "the harness." It is the prerequisite for deletion (the live code must stop importing legacy symbols first) and it is the visible value: a codebase ready to grow M7's corpus axis and M8's model axis without dragging milestone strata along.

**Independent Test**: After the hoist + unify + de-prefix, grep every live module — no import resolves to a milestone-prefixed module (`m3_*`/`m4_*`/`m5*`/`m6*`), and no live module *is* milestone-prefixed. `prompts.py` defines a single chat-prompt builder; `reporter.py` is the only report-generation module. `make lint typecheck test` is green and `python -m vllm_grpc_bench.validate` (the de-prefixed validate entry point) completes end-to-end against `fake_server`.

**Acceptance Scenarios**:

1. **Given** the hoist + unify step is complete, **When** a maintainer inspects the package, **Then** `types.py`, `prompts.py`, `timing.py`, and `exceptions.py` exist and define the hoisted symbols (FR-002), with `CohortKind` carrying exactly the 4 live members.
2. **Given** the unify step is complete, **When** the maintainer greps for chat-prompt construction, **Then** exactly one builder exists (the seed+digest form) and `rest_cohort` calls it — the M5.2 `iteration×cell_id` builder is gone.
3. **Given** the de-prefix step is complete, **When** the maintainer lists the package, **Then** no live module name matches a milestone prefix, and the former `m6_2_*` modules appear under generic names (`sweep`, `rpc_driver`, `validate`, `resume`, `crossover`, `null_anchor`, `anchor_trajectory`, `sub_probe`), with `m6_2_types`/`m6_2_reporter`/`m6_2_prompt_source` merged into `types.py`/`reporter.py`/`prompts.py`.
4. **Given** the consolidation step is complete, **When** the maintainer counts report generators, **Then** exactly one (`reporter.py`) exists.
5. **Given** US1 is complete (before legacy deletion), **When** `mypy --strict` and `ruff` run, **Then** both pass with no new errors and no newly-added suppressions, and `python -m vllm_grpc_bench.validate` completes end-to-end against `fake_server`.

---

### User Story 2 - Legacy is gone and the tree hits the target counts (Priority: P2)

A contributor sees a lean tree: every frozen milestone module and its tests are deleted, the retained tests are renamed to match the de-prefixed modules, and the counts have dropped from 84 source modules / 137 test files to approximately ~25 / ~35.

**Why this priority**: This is the headline payoff — it shrinks the diff surface M7 and M8 read against. It depends on US1 (nothing live may still import the legacy code, and the de-prefix must have happened) so it ships second.

**Independent Test**: After deletion, `ls tools/benchmark/src/vllm_grpc_bench/` shows zero milestone-prefixed modules; `ls tools/benchmark/tests/` shows zero milestone-prefixed test files and the retained tests carry generic names. Source-module count is ~25 (≤ ~27) and test-file count ~35. `make lint typecheck test` is green and the `validate` smoke completes — proving nothing live depended on the deleted code.

**Acceptance Scenarios**:

1. **Given** the deletion step is complete, **When** `ls tools/benchmark/src/vllm_grpc_bench/` runs, **Then** no module matches any milestone prefix (`m3_*`, `m4_*`, `m5*`, `m6_*`, `m6_1*`, `m6_1_1*`, `m6_1_2*`, `m6_1_3*`, and the former `m6_2_*` — all either de-prefixed or deleted).
2. **Given** the deletion + rename step is complete, **When** `ls tools/benchmark/tests/` runs, **Then** no test file carries a milestone prefix; retained tests are named for the modules they cover (e.g. `test_sweep.py`, `test_reporter.py`).
3. **Given** the final branch state, **When** the source-module and test-file counts are measured, **Then** they are approximately ~25 and ~35 respectively, reported as the headline reduction.
4. **Given** the deletion step is complete, **When** `make lint typecheck test` runs, **Then** the full suite passes with no regressions versus the pre-refactor baseline.

---

### User Story 3 - Any legacy harness or result is recoverable on demand (Priority: P3)

A researcher who later needs the exact M5.2 (or any earlier) harness, its result data, or its prompt convention checks out the matching `milestone/m*` annotated tag and finds everything intact at that point in history. Because every removal and BC break in this beat is backed by a tag, breaking compatibility on `main` loses nothing recoverable.

**Why this priority**: This is the safety net that makes the aggressive deletion and the BC breaks defensible rather than destructive. It is guaranteed by the milestone tags created in `v0.0.0`, so it is an invariant to verify rather than functionality to build — hence lowest priority, but a required gate.

**Independent Test**: After the merge, `git checkout milestone/m5.2-transport-tuning` then `ls tools/benchmark/src/vllm_grpc_bench/m5_2_*` still lists the legacy M5.2 harness; `git show milestone/m5.2-transport-tuning:tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py` returns historical content.

**Acceptance Scenarios**:

1. **Given** a removed legacy module `<path>` committed under tag `milestone/m<N>`, **When** a researcher runs `git show milestone/m<N>:<path>`, **Then** the historical content is returned intact.
2. **Given** the merge commit on `main`, **When** a researcher checks out `milestone/m5.2-transport-tuning` and lists `m5_2_*`, **Then** the legacy M5.2 modules (and the M5.2 prompt builder) are present at that tag.
3. **Given** the merge commit, **When** a reader opens `ANALYSIS.md`, **Then** a short subsection documents the refactor, the deliberate backward-compatibility breaks (renamed modules, unified prompt format, dropped cohort members), and the tag-based recovery path.

---

### Edge Cases

- **Hidden legacy dependency surfaces during rewrite**: a live module imports a legacy symbol the hoist list (FR-002) does not yet name — for example `_client_kwargs`, which `m6_2_rpc_driver` imports from `m3_sweep` and which the PLAN's enumeration omits. The hoist set is extended to cover every such symbol (or the symbol confirmed dead and its call site removed) before the legacy module is deleted; FR-002 is a floor, not a closed list.
- **`__main__` imports a legacy module directly**: the CLI imports `m3_sweep` at runtime in places; these references are repointed at the hoisted homes (or removed if dead) so no legacy module survives by virtue of a CLI import.
- **De-prefix name collision**: `m6_2_reporter` collides with the existing `reporter.py` and `m6_2_types` with the new `types.py`; these are *merges* (content folded into the generic module), not renames-in-place.
- **Behavior change is intended where stated**: unifying the prompt builder changes the bytes `rest_cohort` sends. This is an accepted BC break, not a regression — it is documented in `ANALYSIS.md` and recoverable via the M5.2 tag. The sweep *methodology* and *metric definitions* are still preserved.
- **No backward-compat shims**: the refactor must not leave alias modules, re-export stubs, or deprecated-name forwarders. A consumer pinned to an old import path is expected to use a milestone tag instead.
- **Code names de-prefix, data pointers do not**: the modules become generic (`reporter.py`, `sweep.py`, `validate.py`), but the milestone-named *paths the harness reads and validates against* stay verbatim — baseline-chain inputs, the published `m6_2-token-budget.{json,md}` deliverable, and the validate module's hardcoded canonical-path constants. The reason is scope, not preference: re-targeting the harness to a new milestone's data is M7 work, out of scope here. Implementers must not "tidy" these paths to match the generic code names — it orphans retained artifacts and breaks `m6_2_validate` and `ANALYSIS.md` references (FR-019).
- **CLI default invocation**: dropping the `--m6_2` selector means the de-prefixed sweep is what runs by default. The CLI must still expose validate/smoke/resume as de-prefixed flags (e.g. `--validate`), and removing the legacy `--mN` flags must not leave argparse referencing deleted handlers.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The harness MUST gain four generic home modules under `tools/benchmark/src/vllm_grpc_bench/`: `types.py`, `prompts.py`, `timing.py`, `exceptions.py`.
- **FR-002**: The generic homes MUST receive every still-used symbol the live code imports from legacy modules. This includes at least: `types.py` ← `EndpointTuple`, `RTTRecord`, `RunCohort` (from `m3_types`), a single `CohortKind` carrying exactly the 4 live members (`rest_https_edge`, `rest_plain_tcp`, `default_grpc`, `tuned_grpc_multiplexed`), `M6_1_CELLS` (from `m6_1_types`), `M6_1_2_COHORTS` (from `m6_1_2_types`); `prompts.py` ← `DEFAULT_CHAT_MAX_TOKENS` and the single unified chat-prompt builder (FR-003); `timing.py` ← `extract_rest_timings` (from `m6_1_1_timing`); `exceptions.py` ← the schema-validation error (from `m5_2_regen`), renamed `SchemaValidationFailed`. Any additional live-code import of a legacy symbol discovered during the rewrite (e.g. `_client_kwargs`) MUST also be hoisted.
- **FR-003**: The two chat-prompt builders MUST be unified into a single builder in `prompts.py` (the seed+digest form). `rest_cohort` MUST be repointed to it; the M5.2 `iteration×cell_id` builder MUST be removed. The change to the REST cohort's prompt bytes is an accepted backward-compatibility break.
- **FR-004**: The live `m6_2_*` module family MUST be de-prefixed to milestone-agnostic names (e.g. `m6_2_sweep` → `sweep`, `m6_2_rpc_driver` → `rpc_driver`, `m6_2_validate` → `validate`, and likewise `resume`, `crossover`, `null_anchor`, `anchor_trajectory`, `sub_probe`). `m6_2_types`, `m6_2_reporter`, and `m6_2_prompt_source` MUST be merged into `types.py`, `reporter.py`, and `prompts.py` respectively rather than renamed standalone.
- **FR-005**: All report generation MUST be consolidated into a single `reporter.py`. The six `m*_reporter.py` modules MUST be removed (the live M6.2 reporter folded into `reporter.py`, the rest deleted).
- **FR-006**: All milestone-prefixed legacy source modules MUST be deleted: `m3_*.py`, `m4_*.py`, `m5*_*.py`, the `m6_*` family, `m6_1*_*.py`, `m6_1_1_*.py`, `m6_1_2_*.py`, `m6_1_3_*.py`. After FR-004, no `m6_2_*` module remains either (de-prefixed or merged).
- **FR-007**: Legacy test files MUST be deleted and the retained tests MUST be renamed to match the de-prefixed modules they cover (no test file may carry a milestone prefix on the final branch).
- **FR-008**: The refactor MUST be performed incrementally and remain bisectable: `mypy --strict` and `ruff` MUST pass after each module-level step (hoist, unify, de-prefix/merge, delete).
- **FR-009**: The refactor MUST NOT leave any backward-compatibility affordance — no alias modules, re-export shims, deprecated-name forwarders, or retained milestone-prefixed members. Backward compatibility is provided solely by `milestone/m*` tags.
- **FR-010**: On the final branch state, no live or retained-test module MAY import a deleted or renamed-away module, and no live module name MAY carry a milestone prefix. A residual reference is a defect that fails the gate.
- **FR-011**: The refactor MUST preserve *what the harness measures* — sweep methodology, metric definitions, and the data content/shape of published reports are unchanged. The default output filenames of the retained baseline-chain artifacts (e.g. `docs/benchmarks/m6_2-token-budget.{json,md}`) MUST also be preserved (FR-019). Only structure, module/symbol names, import paths, the CLI flag/module surface (FR-018a), and the REST-cohort prompt bytes (FR-003) change.
- **FR-018a**: The operator-facing CLI surface MUST be de-prefixed. All legacy milestone flags (`--m3` … `--m6_1_3`) and their dispatch branches MUST be removed along with the deleted sweeps. The surviving `--m6_2-*` flags MUST be renamed to generic forms (e.g. `--m6_2-modal-region` → `--modal-region`, `--m6_2-n` → `--n`); the `--m6_2` selector MUST be dropped. **[Reconciled in T018 / ADR 0006:** the de-prefixed sweep is exposed as a **`sweep` subcommand** rather than the no-arg default — the no-arg default + `compare*` subcommands remain the retained `bench`/`compare` tooling (Entity 3/8, README/Makefile). The binding invariant is "zero `--m[0-9]` flags," not "sweep is the default."**]** This is an accepted backward-compatibility break; old invocations are recoverable via the M6.2 milestone tag.
- **FR-019**: Code names de-prefix, but the harness's **data pointers** stay milestone-named — because v0.0.1 is a structural refactor that preserves *what the harness operates on*, and the harness is currently configured for the delivered M6.2 milestone. Re-targeting the harness to a new milestone's artifacts is research work (M7), explicitly out of v0.0.1's scope. Concretely, three classes of milestone-named path MUST be preserved verbatim: (a) **baseline inputs** the sweep reads (e.g. the default `docs/benchmarks/m6_1_3-attribution-closure.json` anchor and the rest of the M3→M6.1.x chain) — these are *other* delivered milestones' frozen outputs and are not ours to rename; (b) the **published canonical deliverable** `docs/benchmarks/m6_2-token-budget.{json,md}` on disk; (c) the **hardcoded canonical/validate path constants** in the validate module (e.g. `_CANONICAL_JSON = "docs/benchmarks/m6_2-token-budget.json"`, `_VALIDATE_JSON = "…-validate.json"`) — `m6_2_validate` *compares against* the published canonical file, so de-prefixing the constant would point it at a nonexistent file. Implementers MUST NOT "tidy" any of these to match the now-generic code names; doing so orphans the retained baseline-chain artifacts and breaks `m6_2_validate` and `ANALYSIS.md` references.
- **FR-012**: All three CI gates MUST pass on the final branch state — lint + format (`ruff`), type-check (`mypy --strict`), unit tests — with no suppressions added to mask refactor fallout.
- **FR-013**: The de-prefixed validate entry point (`python -m vllm_grpc_bench.validate`, formerly `m6_2_validate`) against `fake_server` MUST complete end-to-end on the final branch state.
- **FR-014**: Every deleted legacy module, benchmark artifact, and changed convention MUST remain recoverable via its corresponding `milestone/m*` annotated tag; no milestone tag is moved or deleted by this beat.
- **FR-015**: `ANALYSIS.md` MUST gain a short subsection documenting the refactor, the deliberate backward-compatibility breaks (renamed modules, unified prompt format, dropped cohort members), and the tag-based recovery path. An ADR MUST also be recorded under `docs/decisions/` capturing the non-obvious architectural choices (per the constitution's Development Workflow), citing `research.md` for detail.
- **FR-016**: Every dangling reference to a removed or renamed module in `docs/`, CLI help / `__main__.py`, or other retained text MUST be repointed or removed so the final tree references no removed/old-named module path.
- **FR-017**: The beat MUST produce an annotated tag `v0.0.1` on the merge commit, the branch `chore/post-m6.2-cleanup-v0.0.1`, and a PR closing the refactor.
- **FR-018**: The beat MUST NOT touch `.proto` files, the `vllm` dependency, runtime `packages/*`, or `specs/*` history (the canonical research record is kept in full).

### Key Entities

- **Generic home module**: A new, milestone-agnostic module (`types.py`, `prompts.py`, `timing.py`, `exceptions.py`) owning a category of still-used symbols formerly scattered across legacy modules.
- **De-prefixed live module**: A former `m6_2_*` module renamed to a milestone-agnostic name (or merged into a generic home); the forward-evolving harness code.
- **Consolidated reporter**: The single `reporter.py` that absorbs all prior report-generation modules.
- **Unified chat-prompt builder**: The single seed+digest prompt builder in `prompts.py` replacing the two divergent legacy builders.
- **Legacy module**: A milestone-prefixed source module whose milestone is delivered and frozen; deleted once its still-used symbols are hoisted. After this beat, none remain on `main`.
- **Milestone tag**: An annotated `milestone/m*` tag marking a delivered research deliverable; the sole recovery path for any removed module, artifact, or changed convention.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After the refactor, `tools/benchmark/src/vllm_grpc_bench/` contains **zero** modules whose name carries a milestone prefix (`m3`/`m4`/`m5`/`m6` families, *including* the former `m6_2_*`), verifiable by glob; the four generic homes and the consolidated `reporter.py` are present.
- **SC-002**: The harness source-module count drops substantially from 84 toward the ~25 direction (and test files from 137 toward ~35), reported as the headline reduction. The pass/fail gate is the invariants (SC-001, SC-003, SC-004), not an exact count — thin modules are merged only where cohesion genuinely improves, with no contrived merges to hit a number.
- **SC-003**: Exactly one chat-prompt builder exists in the harness and exactly one report-generation module (`reporter.py`) exists; `CohortKind` carries exactly the 4 live members.
- **SC-004**: A search of every retained module (live source and tests) for imports of any milestone-prefixed module returns **zero** matches, and a search for backward-compat aliases / re-export shims of old names returns **zero** matches.
- **SC-005**: `make lint typecheck test` passes on the final branch state with no new failures relative to the pre-refactor baseline and no newly-added lint/type suppressions.
- **SC-006**: `python -m vllm_grpc_bench.validate` against `fake_server` completes end-to-end on the final branch state.
- **SC-007**: For at least `milestone/m5.2-transport-tuning`, checking out the tag and listing its `m5_2_*` modules shows the legacy harness (and the M5.2 prompt builder) intact, and `git show <tag>:<removed-path>` returns historical content — proving recoverability of everything broken on `main`.
- **SC-008**: An annotated `v0.0.1` tag exists on the merge commit and `ANALYSIS.md` contains the refactor subsection, including the backward-compatibility-break note and recovery path.
- **SC-009**: The CLI exposes no milestone-prefixed flag — `python -m vllm_grpc_bench --help` (and `… sweep --help`) show zero `--m<N>`/`--m6_2-*` flags; the de-prefixed sweep runs via the `sweep` subcommand (ADR 0006 — see FR-018a), and a search for legacy `--mN` dispatch branches returns zero.
- **SC-010**: The milestone-named data pointers resolve after the refactor: (a) the published canonical deliverable `docs/benchmarks/m6_2-token-budget.{json,md}` and every baseline-chain input the sweep defaults to (e.g. `m6_1_3-attribution-closure.json`) still exist on disk; (b) the de-prefixed `validate` smoke resolves its hardcoded canonical path against that existing published file and runs to completion, writing its own output only to the `-validate.{json,md}` paths (never overwriting the canonical deliverable); (c) every `ANALYSIS.md` reference to a benchmark artifact still resolves to an existing file.

## Assumptions

- **Forward-only is the governing philosophy**: Breaking backward compatibility (module renames, import-path changes, CLI module-surface changes, the unified prompt format, dropped cohort members) is an accepted, intended outcome. Recovery is provided entirely by `milestone/m*` tags; the live tree carries no compatibility shims.
- **`m6_2` is the live milestone, and it is de-prefixed**: The former `m6_2_*` family is the forward-evolving harness; it is renamed to generic names / merged into generic homes, not retained under its milestone prefix.
- **Shared M3-era modules stay (repointed)**: `channel_config`, `corpus`, `compare`, and the `_client_kwargs` / prompt helpers from `m3_sweep` are imported by live code; their still-used symbols are hoisted and the modules either retained (if genuinely generic, e.g. `corpus`, `channel_config`) or absorbed (e.g. the live bits of `m3_sweep`). Which specific shared modules survive vs. merge is a `/speckit-plan` determination guided by the ~25-module target.
- **Measured starting state**: 84 source modules (66 milestone-prefixed, of which 11 are the `m6_2_*` family) and 137 test files (117 milestone-prefixed), as of this branch.
- **Hoist list is a floor**: FR-002 enumerates the symbols known today; any additional live import of a legacy symbol found during `/speckit-plan` or implementation is added before the owning legacy module is deleted. The binding rule is "no live import of a milestone-prefixed module remains," not "exactly these symbols."
- **Milestone tags exist and are pushed**: All 16 `milestone/m*` tags (M2 through M6.2) were created and pushed to origin in `v0.0.0`; this beat does not create or move them.
- **Measurement-preserving, not byte-preserving**: The harness still measures the same things with the same metric definitions and report schema; only structure, names, and the deliberately-changed REST-cohort prompt bytes differ.
- **Single PR, bisectable commits**: The work lands as one PR on `chore/post-m6.2-cleanup-v0.0.1` with bisectable commits (hoist, unify, de-prefix/merge, report consolidation, deletion + test rename, docs + tag). Task count exceeds the PLAN's ~17 estimate because the de-prefix and consolidation steps were folded in.
