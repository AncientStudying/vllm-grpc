# Feature Specification: Contributing Guide and Project Roadmap

**Feature Branch**: `013-contributing-roadmap`
**Created**: 2026-05-03
**Status**: Draft
**Input**: User description: "A markdown file for explaining how to contribute and some updates to README.md that describe the current release as Milestone 1, Milestone 2 will involve additional testing with tuning vLLM and grpcio parameters, Milestone 3 will involve testing with a larger more varied prompt and conversation corpus, Milestone 4 testing with additional models"

## User Scenarios & Testing *(mandatory)*

### User Story 1 — New Contributor Understands How to Participate (Priority: P1)

A developer arriving at the repository for the first time wants to know how to contribute code, report issues, or run the test suite locally. They read `CONTRIBUTING.md` and can immediately take their first action (clone, run checks, open a PR) without asking questions.

**Why this priority**: Without a contributing guide, the barrier to participation is high and contributions require direct communication with the maintainer. This is the primary value of the deliverable.

**Independent Test**: Read `CONTRIBUTING.md` cold and verify it answers: how to set up the dev environment, how to run tests, what the branch/PR conventions are, and where issues are tracked.

**Acceptance Scenarios**:

1. **Given** a developer has cloned the repo, **When** they read `CONTRIBUTING.md`, **Then** they can run the full test suite without any additional guidance.
2. **Given** a developer wants to submit a change, **When** they follow the contributing guide, **Then** they know the expected branch naming convention, how to pass CI, and what to include in a PR description.
3. **Given** a developer wants to report a bug, **When** they read `CONTRIBUTING.md`, **Then** they know where and how to file an issue.

---

### User Story 2 — Visitor Understands Where the Project Is Headed (Priority: P2)

A developer or evaluator reads the README and wants to understand whether the project is active, what has been delivered, and what is planned next. The roadmap section answers this clearly in a single glance.

**Why this priority**: Without a roadmap, evaluators cannot assess project trajectory or decide whether to invest time in contributing or adopting the library.

**Independent Test**: Read the README roadmap section and verify it clearly labels the current release as Milestone 1 and describes Milestones 2–4 in enough detail to understand the project's research direction.

**Acceptance Scenarios**:

1. **Given** a visitor reads the README, **When** they reach the roadmap section, **Then** they can identify that Milestone 1 (current release) covers the three access paths and benchmark infrastructure.
2. **Given** a visitor reads the README, **When** they read the milestone descriptions, **Then** each milestone states a clear, distinct research goal (parameter tuning, corpus expansion, model expansion).
3. **Given** a developer assesses whether to contribute, **When** they read the roadmap, **Then** they can identify which milestone their interest aligns with.

---

### Edge Cases

- A contributor on Windows should not be blocked by Unix-only setup instructions — the contributing guide should note platform support.
- The roadmap should not promise specific delivery dates or outcomes, only research directions.
- `CONTRIBUTING.md` should reference existing `make` targets rather than duplicating setup instructions already in the README.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Repository MUST contain a `CONTRIBUTING.md` file at the root.
- **FR-002**: `CONTRIBUTING.md` MUST describe how to set up the development environment (pointing at `make bootstrap`).
- **FR-003**: `CONTRIBUTING.md` MUST describe how to run the test suite and linter locally (`make check`).
- **FR-004**: `CONTRIBUTING.md` MUST describe the branch naming convention used in this project.
- **FR-005**: `CONTRIBUTING.md` MUST describe what a valid pull request looks like (passing CI, description, scope).
- **FR-006**: `CONTRIBUTING.md` MUST describe how to report bugs or request features (GitHub Issues).
- **FR-007**: `README.md` MUST include a roadmap section that labels the current state as Milestone 1.
- **FR-008**: The roadmap MUST describe Milestone 2 as additional testing focused on tuning vLLM and grpcio parameters.
- **FR-009**: The roadmap MUST describe Milestone 3 as testing with a larger and more varied prompt and conversation corpus.
- **FR-010**: The roadmap MUST describe Milestone 4 as testing with additional models beyond `Qwen/Qwen3-0.6B`.
- **FR-011**: Each milestone description MUST state its primary research question or goal in one to two sentences.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer unfamiliar with the project can complete local setup and run `make check` in under 10 minutes using only `CONTRIBUTING.md` and the existing README.
- **SC-002**: The roadmap section requires no more than 60 seconds to read and leaves no ambiguity about what Milestone 1 delivered and what Milestones 2–4 will investigate.
- **SC-003**: `CONTRIBUTING.md` covers all four topics (setup, testing, branching, PR process) without cross-referencing files that do not exist.
- **SC-004**: `make check` continues to pass after all changes (no regressions introduced by documentation additions).

## Assumptions

- The contributing guide targets macOS (M2/M3) and Linux x86-64 — same platforms as the existing README.
- Windows is noted as unsupported (consistent with current README scope).
- Milestone delivery dates are intentionally omitted; the roadmap describes research directions, not a committed schedule.
- The roadmap is placed near the end of the README so the quickstart and benchmark sections remain the primary focus for new visitors.
- `CONTRIBUTING.md` links back to the README rather than duplicating the quickstart steps.
