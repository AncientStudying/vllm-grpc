# Specification Quality Checklist: M5.1 — REST vs gRPC Head-to-Head on Real Wire

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-05-11
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs) — FastAPI / Modal / `modal.forward` are referenced as continuity constraints with M5's existing deployment, not as new implementation choices the spec is making; the FR text frames them as "the same Modal app variant M5 uses, with a REST shim added," which is methodology-continuity language, not implementation prescription
- [x] Focused on user value and business needs — every user story is framed as a maintainer-or-contributor reader of the published report or the README
- [x] Written for non-technical stakeholders — protocol-comparison framing is accessible; the technical detail lives in FRs where it belongs
- [x] All mandatory sections completed — Background, User Scenarios & Testing, Requirements, Success Criteria, Assumptions all present

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain — none added; reasonable defaults documented in Assumptions for the three judgment calls (concurrency landscape matches M1; gRPC-side uses M5's frozen-tuned-channel construction; bytes-axis is not re-derived)
- [x] Requirements are testable and unambiguous — each FR names the system, the must-behavior, and (where relevant) the artifact location or the numerical bound
- [x] Success criteria are measurable — SC-001..SC-008 each carry a time bound, an artifact location, or a verifiable property
- [x] Success criteria are technology-agnostic (no implementation details) — they cite report contents, reader experience, and operator-facing properties, not framework names
- [x] All acceptance scenarios are defined — every user story has Given/When/Then scenarios
- [x] Edge cases are identified — seven edge cases covering REST shim skew, MockEngine inference cost neutrality, server_bound on both protocols, low-RTT, partial-protocol failure, HTTP/1.1 vs HTTP/2 connection-count framing, and merge-order accidents on the README commit
- [x] Scope is clearly bounded — Background and Assumptions state what is in scope (mock-engine head-to-head on cross-host) and what is deferred (M6 corpus, M7 real model, REST-over-HTTP/2)
- [x] Dependencies and assumptions identified — 14 explicit Assumptions covering M5 closure, mock-engine continuity, corpus, HTTP/1.1 for REST, concurrency, frozen-tuned-channel construction, default-gRPC control, bytes-axis stability, single Modal deploy, TLS, auth, Constitution V, adoption-is-separate, and pre-PR README procedural enforcement

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria — FRs are grouped by section (harness reuse, tuned-gRPC, REST cohort, matrix, reporting, narrative refresh, supersession), and each user story's Independent Test enumerates the verifiable properties
- [x] User scenarios cover primary flows — US1 (the measurement headline), US2 (the narrative refresh + README-before-PR), US3 (the supersession table)
- [x] Feature meets measurable outcomes defined in Success Criteria — SC-001 maps to US1; SC-005 maps to US2; SC-004 maps to US3; SC-002/003/006/007 are operator-facing; SC-008 is the pre-PR ordering invariant the user explicitly requested
- [x] No implementation details leak into specification — Modal / FastAPI references are continuity constraints, not implementation choices

## Notes

- User's explicit request — "make sure a requirement gets into the specifications to update README.md to current state of project just before PR" — is captured by FR-017 (what to update), FR-018 (parallel updates to summary.md and PLAN.md), FR-019 (the README commit is the **last** commit before `gh pr create`), and SC-008 (the verifiable property at PR-open time). User Story 2 carries the narrative-refresh user journey and Edge Cases includes the merge-order safety case for it.
- All three guidance-document framings — README.md "Milestone 5.1 (upcoming)", docs/PLAN.md "M5.1 — REST vs gRPC Head-to-Head on Real Wire (upcoming)", and the project memory's M5-delivered status — are consistent with the spec as drafted.
- Verdict literal taxonomy (`tuned_grpc_recommend`, `rest_recommend`, `no_winner`, `comparison_unavailable`) deliberately parallels M5's verdict literals and adds one new value (`comparison_unavailable`) to handle the case where `server_bound` fires on either protocol; the JSON schema rule (FR-014) requires additive-only changes from M5's schema so M5-aware tooling continues to work unmodified.
- No [NEEDS CLARIFICATION] markers were used; the three borderline-clarification candidates (concurrency landscape, gRPC-config construction, bytes-axis re-derivation) all had reasonable defaults derivable from the M1/M5 evidence base and were resolved in Assumptions.
