# Specification Quality Checklist: M6.1 — Real-Prompt-Embeddings Engine Path

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-05-15
**Feature**: [spec.md](../spec.md)

## Content Quality

- [X] No implementation details (languages, frameworks, APIs)
- [X] Focused on user value and business needs
- [X] Written for non-technical stakeholders
- [X] All mandatory sections completed

## Requirement Completeness

- [X] No [NEEDS CLARIFICATION] markers remain
- [X] Requirements are testable and unambiguous
- [X] Success criteria are measurable
- [X] Success criteria are technology-agnostic (no implementation details)
- [X] All acceptance scenarios are defined
- [X] Edge cases are identified
- [X] Scope is clearly bounded
- [X] Dependencies and assumptions identified

## Feature Readiness

- [X] All functional requirements have clear acceptance criteria
- [X] User scenarios cover primary flows
- [X] Feature meets measurable outcomes defined in Success Criteria
- [X] No implementation details leak into specification

## Notes

- The spec is intentionally framed as a strict variant of M6 (same matrix, same classifier, same hardware, same conventions) with one operative variable changed (embed cohort engine code path). This is the milestone's central design principle — see Background § non-normative summary.
- Some FRs reference specific code-path identifiers (`CompletionsServicer._resolve_prompt_embeds_input`, `decode_embeds`, `input_kind="prompt_embedding_torch_b64"`, `input_kind="prompt_embedding_b64"`, `enable_prompt_embeds=True`, `torch.save`, gRPC `prompt_embeds` proto field). These are not implementation prescriptions — they name the existing observable surfaces in the deployed M6 frontend so the spec is testable against the actual codebase. Per the M6 precedent (which uses identical naming), `/speckit-clarify` can re-evaluate whether any of these need renaming.
- SC-001's 90-minute runtime budget is a hypothesis (carry-over from M6's published runtime, justified because the real prompt-embeds engine path replaces the text-digest hashing step rather than adding work). If the implementation discovers the prompt-embeds forward is materially heavier than text-prompt completion at h=4096 on A10G, SC-001 may need updating during planning.
- The "Engine path differential" section (US2 / FR-020) is the milestone's most consequential new deliverable beyond M6's verdict structure. Its acceptance criteria are intentionally explicit (per-cohort classifier-metric deltas, per-cell engine_cost delta, 95% CI half-widths, units) so the reporter implementation can be validated against the spec.
- All 28 FRs map to at least one of US1 / US2 / US3 / Edge Cases. FRs that don't correspond to a user-visible behaviour (e.g. FR-014 engine lifecycle, FR-027 RunMeta) are present because they are load-bearing reproducibility / operator-experience constraints rather than because they fail the "user value" test — they prevent quietly broken runs.
- Items marked incomplete (none in this draft) would require spec updates before `/speckit-clarify` or `/speckit-plan`.
