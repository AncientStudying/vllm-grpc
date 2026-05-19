# Specification Quality Checklist: M6.2 — Token-Budget Characterization

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-05-19
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

## Notes

This is a deeply infrastructure-adjacent benchmark milestone — the spec leans
on conventions established by M6.0a / M6.1.1 / M6.1.2 / M6.1.3 (wire schema
`m6_1_1.v1`, 5-segment engine-cost decomposition, 4-cohort matrix,
concurrent dispatch, `network_paths` topology probe, symmetric-prompts
helper). These names appear in the spec because they are the canonical
project vocabulary the spec inherits; they are not implementation details
introduced by M6.2. The benchmark domain inherently couples the user-facing
"operator question" to the project's data shapes, so terms like
`seg_prefill_ms` or `wall_p95_ms` function as the project's stakeholder
vocabulary, similar to how a payment-systems spec would use the term
`ACH return code`.

**Clarify round 1 resolved (Session 2026-05-19):**

1. **Harness inheritance discipline** (new FR-028) — user-directed: copy + refactor the M6.1.3 `m6_1_3_*` module family; regeneration from scratch FORBIDDEN.
2. **Validate-mode `max_tokens` axis subset** (FR-001 pinned) — `{10, 50, 2048}` at n=20; interior caps rendered as `not_validated`.
3. **Crossover-detection rule** (US2 acceptance #1, CrossoverThreshold entity pinned) — symmetric mean-in-CI at 95% CI half-width.
4. **Sweep-integrity warning threshold** (FR-014, SC-004 pinned) — ≥ 3 of 48 anchor cells drift.
5. **`network_paths` re-probe cadence** (FR-009, SC-010, Edge Cases pinned) — every 4 hours in publish mode; start + end only in validate (< 8 h).
6. **Validate-mode crossover-section rendering** (FR-016, SC-005 amended) — render with axis-restricted disclaimer; coarse 4-value `crossover_max_tokens` vocabulary in validate.

**Clarify round 2 resolved (Session 2026-05-19 round 2):**

7. **Publish-sweep `n` and wall-clock budget — why 30-40 h?** — Deferred to clarify round 3, gated on validate-sweep within-cohort variance at chat_stream c=1 × max_tokens=2048. FR-004 / FR-021 / FR-023 / SC-001 now carry provisional ranges across n=100 (~40 h, ~$40) / adaptive-n (~26-28 h, ~$22-25) / n=50 (~20 h, ~$20). Publish run is BLOCKED until round 3 closes; orchestrator refuses to start `--m6_2` if `n` knob is unset.

**Still open — expected to surface in /speckit-clarify round 3 (after validate completes):**

- **Publish-mode `n` selection** (FR-004 round-3 gate) — uniform-100, adaptive-100/50, or uniform-50 — pinned against measured validate-sweep stddev at chat_stream c=1 × max_tokens=2048.
- **Validate-mode per-point sample size confirmation** (FR-004 currently n=20 pinned) — if validate-sweep CIs come back wider than expected, may need to bump validate n upward (this would also bump round-2 cost / wall-clock estimates).
- **Forward-link annotation mechanism for M6.1.3's markdown body** (FR-019) — `> **Note**:` one-liner is the M6.1.3-precedent default; confirm or amend.
- **`--m6_2-asymmetric-prompts` override flag disposition** (FR-008) — ship for diagnostic re-runs or treat as forward-reference per M6.1.3 Phase C/D pattern?
- **Sweep partial-failure recovery contract** at the high-cap × c=8 cells — does multi-cohort failure at a single (cell, `max_tokens`) point trigger sweep-level integrity warning, or fire only the per-row `failed_<reason>` markers?

Per `feedback_thorough_clarify_cycles`, the user typically runs 2-3 clarify
rounds before `/speckit-plan`. Round 1 resolved 6 high-impact items; round 2
resolved the runtime-budget question by deferring `n` to round 3 with a
clear gate. Round 3 is naturally post-validate and post-`/speckit-plan`-may-not-be-needed-before — the user can run `/speckit-plan` to scaffold tasks
that BLOCK on the round-3 `n` decision, or wait until round 3 closes.
