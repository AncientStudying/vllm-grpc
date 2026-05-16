# Specification Quality Checklist: M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-05-16
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Validation Notes

- **Content Quality — minor caveat acknowledged**: This is a research / methodology-diagnosis milestone, not a user-facing product feature. The spec necessarily refers to technical concepts (per-cohort `engine_ttft_ms`, gRPC trailing metadata, FastAPI SSE events) because the *subject* of the milestone is an instrumentation-methodology gap. The spec language stays at the level of *what* the milestone produces (a classified diagnosis, then a fix-or-document outcome) and *why* (closing a methodology gap before M6.2 / M7 / M8 build on top). Implementation-level details (which file to edit, which Python module's bracketing changes, etc.) are deferred to `/speckit-plan`.
- **Success Criteria check — SC-003 and SC-009 reference quantitative numerical thresholds (`5%`, `500 µs`)** but these are *outcome* thresholds the operator/reader can verify against the published JSON, not implementation choices. They satisfy "measurable" and "technology-agnostic" (the same 5% threshold would apply if the harness were rewritten in a different language).
- **Out-of-scope boundaries (FR-029 through FR-034)** are explicit so subsequent `/speckit-clarify` rounds and `/speckit-plan` do not drift into M6.2 (token-budget axis), M7 (corpus), or M8 (multi-model) territory.

## Clarify Round 1 Resolutions (Session 2026-05-16)

Five clarifications recorded; sections touched: Clarifications (new), FR-010 (classifier formalised), FR-014 / FR-015 / FR-015a / FR-015b / FR-017 / FR-018 / FR-021 / FR-031 (Phase 2 workflow tightened), SC-008 (M6.2 anchor reference), Edge Cases (chat_stream control drift handling).

| # | Topic | Resolution |
|---|---|---|
| Q1 | FR-010 classifier threshold computation | Magnitude-equivalence: `spread(seg_x) / spread(engine_ttft) ≥ 0.80`; `drift_not_reproduced` short-circuits via `spread(engine_ttft) / mean(engine_ttft) < 0.05` |
| Q2 | Phase 2(a) ↔ `chat_stream_control_drift_warning` interaction | Publish fresh `chat_stream_baseline_post_symmetrisation` (FR-015a); M6.1's chat_stream verdicts preserved as-published |
| Q3 | Mixed Phase 1 classifications across cells | Refuse to advance (exit code `3`); operator re-runs `--m6_1_1-diagnose` once before any Phase 2 path |
| Q4 | `drift_not_reproduced` on all three chat_stream cells | Re-confirm with second Phase 1; if confirmed, preserve M6.1's flag + `methodology_supersedence` annotation; no code or doc change |
| Q5 | Phase 2(a) verification scope | Full M6.1 matrix at n=100; new embed regression check (FR-015b) — pass/fail gate against M6.1's published embed means within ±5% |

## Clarify Round 2 Resolutions (Session 2026-05-16)

Four clarifications recorded; sections touched: Clarifications (round 2 subsection), FR-012 (perturbation budget is now a hard gate, exit code `4`), FR-015a (sentinel-object shape under non-Phase-2(a)), FR-015c (new — fresh embed baseline section parallel to chat_stream), FR-017 / FR-018 (heterogeneous Phase 2 disallowed; `split_required` exit code `5`), FR-021 (schema enumeration updated to include `split_required` and embed baseline), FR-022 (sentinel-object shape), SC-008 (embed null-anchor added), Edge Cases (housekeeping for round-1 stale text), Acceptance Scenarios US2 (updated AC1 / AC4; added AC5 for mixed-classification path).

| # | Topic | Resolution |
|---|---|---|
| Q1 | Sentinel value for `chat_stream_baseline_post_symmetrisation` under non-Phase-2(a) outcomes | Explicit sentinel object `{phase_2_path, baseline_source, pointer, cells?}`; consumers dispatch on `baseline_source` alone |
| Q2 | Downstream effect of operator-acknowledged embed regression | Publish fresh `embed_baseline_post_symmetrisation` section (FR-015c) parallel to chat_stream baseline; M6.1's verdicts preserved with per-row supersedence note on affected rows |
| Q3 | Perturbation budget exceeded handling | Block classification with exit code `4`; classifier ratio bias from perturbation could flip borderline classifications — treat as a hard correctness gate |
| Q4 | Heterogeneous Phase 2 (per-cell fix + doc inside one milestone)? | Disallowed; persistent divergence after re-confirmation forces `phase_2_path = "split_required"` (exit code `5`) and milestone split into successor sub-milestones |

### Housekeeping (silent fixes alongside round 2)

- Removed stale `--m6_1_1-smoke` reference from FR-013 (smoke is out of scope per FR-028).
- Updated US2 acceptance scenarios 3, 4, 5 to reflect the FR-017 / FR-018 exit-code-`3` and exit-code-`5` workflows.
- Updated Edge Cases lines 82 and 89 to reflect the round-1 re-run rule and the round-2 `split_required` rule.
- Updated Key Entities → Phase 2(a) Verification Run to reflect the embed baseline (FR-015c) and regression check (FR-015b).
- Normalized FR-015a / FR-015c wording so the JSON key is *always* present with the sentinel-object shape under non-Phase-2(a) outcomes (round-2 Q1 / Q2 strict-superset rule).

## Notes

- All checklist items pass after rounds 1 and 2.
- Per project memory `feedback_thorough_clarify_cycles`, the user may invoke a third clarify round before `/speckit-plan` — if so, do a fresh honest scan focused on the round-2 additions (sentinel-object schema, `split_required` workflow, embed baseline parallel to chat_stream).
- If the user proceeds directly to `/speckit-plan`, the spec is ready: 5 exit codes are deterministic (`1` missing baseline, `2` torch mismatch, `3` re-run needed, `4` perturbation budget exceeded, `5` milestone split required); 4 deterministic classifier outcomes; explicit sentinel-object schema for downstream M6.2 dispatch.
