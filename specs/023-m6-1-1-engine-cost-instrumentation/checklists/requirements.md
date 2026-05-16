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

## Notes

- All checklist items pass after round 1 clarifications.
- Per project memory `feedback_thorough_clarify_cycles`, expect a second clarify round before `/speckit-plan` — do a fresh honest scan on re-invocation (including terminology-drift housekeeping across newly added FR-015a / FR-015b / FR-017 / FR-018).
