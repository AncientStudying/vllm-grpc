# Tasks: Phase 7.1 — Contributing Guide and Project Roadmap

**Input**: Design documents from `specs/013-contributing-roadmap/`
**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅

**Organization**: Tasks grouped by user story. Both user stories are independent (different files) and can be implemented in parallel after the baseline check.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

---

## Phase 1: Setup

**Purpose**: Confirm baseline health before any changes.

- [x] T001 Run `make check` to confirm ruff + mypy --strict + pytest pass clean before any edits — repo root

---

## Phase 2: User Story 1 — New Contributor Understands How to Participate (Priority: P1)

**Goal**: `CONTRIBUTING.md` exists at the repository root and covers all four topics: dev setup, test suite, branch naming, PR process, and issue reporting.

**Independent Test**: Read `CONTRIBUTING.md` cold and confirm a developer can run `make check` and open a PR without any additional guidance.

- [x] T002 [P] [US1] Create `CONTRIBUTING.md` at the repository root with sections: (1) Development Setup — prerequisites (`uv`, `make`) and `make bootstrap`; note macOS/Linux only; link to README quickstart rather than duplicating it; (2) Running the Test Suite — `make check` (ruff + mypy --strict + pytest) and `make bench-ci` for the offline benchmark smoke test; (3) Branch Naming — `NNN-short-description` sequential convention with examples (`013-contributing-roadmap`); (4) Pull Requests — CI must pass, description explains the why, one concern per PR; (5) Reporting Issues — GitHub Issues, what to include (repro steps, OS, Python version, `make check` output); (6) Spec-Kit Workflow — brief note that planned phases use `/speckit-specify → /plan → /tasks` before code; link to README spec-kit section — `CONTRIBUTING.md`

---

## Phase 3: User Story 2 — Visitor Understands Where the Project Is Headed (Priority: P2)

**Goal**: README.md contains a `## Roadmap` section between `## Benchmark Headlines` and `## Development Commands` that clearly labels the current release as Milestone 1 and describes the research goals of Milestones 2–4 without promising delivery dates.

**Independent Test**: Read the roadmap section and confirm: Milestone 1 is labelled as the current release with a link to `docs/benchmarks/summary.md`; each of M2–M4 states a distinct research goal; no dates or commitments appear.

- [x] T003 [P] [US2] Add `## Roadmap` section to `README.md` between `## Benchmark Headlines` and `## Development Commands` with four sub-sections: (1) `### Milestone 1 — Foundation (current release)` — three access paths benchmarked on Modal A10G, headline wire-size findings, link to `docs/benchmarks/summary.md`; (2) `### Milestone 2 — Parameter Tuning` — research goal: tuning vLLM serving parameters and grpcio channel settings; include 2–3 research questions (max message size vs embed latency, continuous batching interaction with gRPC streaming, channel config for minimum TTFT); (3) `### Milestone 3 — Corpus Expansion` — research goal: re-run with a larger, more varied corpus covering short/long prompts, multi-turn conversations, and domain-specific content; include 2 research questions (wire-size delta vs prompt length, TPOT variance across prompt types); (4) `### Milestone 4 — Model Expansion` — research goal: repeat M1/M2 benchmarks with at least two additional models of different sizes and architecture families; include 2 research questions (larger model effect on latency story, output-length effects on response-byte delta) — `README.md`

---

## Phase 4: Polish

**Purpose**: Final quality gate.

- [x] T004 Run `make check` to confirm ruff + mypy --strict + pytest all pass after changes — repo root

---

## Dependencies & Execution Order

- T001 (baseline check) → T002 and T003 can run in parallel → T004 (final check)
- T002 and T003 are fully independent (different files)

## Parallel Opportunities

```
T001
├── T002  [CONTRIBUTING.md]   ─┐
└── T003  [README.md roadmap] ─┤ both independent
                                ↓
                              T004
```

## Implementation Strategy

Both tasks (T002, T003) are short — each is a single file edit. Run them in parallel after T001 passes.

**MVP**: T002 alone (CONTRIBUTING.md) satisfies P1 and is immediately useful to contributors.
