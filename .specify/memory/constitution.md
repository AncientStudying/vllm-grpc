<!--
SYNC IMPACT REPORT
==================
Version change: (none) → 1.0.0
Status: Initial ratification — created from template

Principles defined (5):
  I.   Proto-First
  II.  Library Dependency, Not Fork
  III. Phase Discipline
  IV.  CI is the Merge Gate
  V.   Honest Measurement

Sections added: Core Principles, Development Workflow, Quality Standards, Governance
Sections removed: N/A (first version)

Templates reviewed:
  ✅ .specify/templates/spec-template.md     — no changes required
  ✅ .specify/templates/plan-template.md     — Constitution Check section references these principles
  ✅ .specify/templates/tasks-template.md    — no changes required

Follow-up TODOs: none
-->

# vllm-grpc Constitution

## Core Principles

### I. Proto-First

The `.proto` schema files under `proto/vllm_grpc/` are the single source of truth for
every wire format used in this project. Rules:

- All message shapes and RPC signatures MUST be defined in `.proto` files before
  any implementation code references them.
- Generated Python stubs MUST be produced at build time from `.proto` sources and
  MUST NOT be committed to the repository.
- Any change to the wire format MUST start with a `.proto` edit — never by editing
  generated stubs or hand-writing equivalent Python classes.
- The `make proto` (or equivalent) task MUST be the only mechanism that produces stubs;
  CI MUST verify that running it produces no diff against what is already on disk.

### II. Library Dependency, Not Fork

This project treats `vllm` as an ordinary published library dependency. Rules:

- No vLLM source code is copied, patched, vendored, or forked into this repository.
- The `frontend` package MUST depend on `vllm` via its public `pyproject.toml`
  dependency declaration, pinned to a compatible version range.
- If a vLLM upstream change breaks this project, the fix MUST be made here (adapter
  code, version pin update) — never inside a patched copy of vLLM.
- This constraint exists to follow the architectural pattern of sibling packages in
  the `vllm-project` org (e.g., AIBrix) and to inherit engine improvements automatically.

### III. Phase Discipline

The project evolves through numbered phases defined in `docs/PLAN.md`. Rules:

- Features, RPCs, endpoints, and abstractions MUST only be built in the phase where
  they are explicitly listed as deliverables.
- No phase N+1 functionality MUST enter a phase N branch.
- Speculative abstractions — code written "because we'll need it later" — are
  prohibited unless they appear in the current phase's deliverables.
- If a design decision is marked as deferred in `docs/PLAN.md`, the decision MUST NOT
  be made during an earlier phase without explicit agreement.

### IV. CI is the Merge Gate

Automated CI is the non-negotiable quality gate for every merge to `main`. Rules:

- All three CI jobs MUST pass before any PR is merged: (a) lint + type-check,
  (b) unit tests, (c) proto stub compile check.
- `ruff` MUST be used for linting and formatting; `mypy --strict` MUST be used for
  type-checking. Disabling or suppressing either tool's errors MUST be justified
  in a code comment and reviewed explicitly.
- The `--no-verify` git flag and CI skip directives MUST NOT be used to merge
  failing code.
- Tests MUST pass in CI (not just locally) before a phase is marked complete.

### V. Honest Measurement

Performance results are first-class artifacts of this project. Rules:

- All benchmark numbers MUST be committed alongside the code that produces them,
  in `docs/benchmarks/`.
- No metric may be selectively omitted because it is neutral or negative relative
  to the thesis.
- Benchmark methodology MUST be documented (corpus, concurrency, hardware, vLLM
  version) so results are reproducible from scratch.
- If the wire-overhead thesis turns out to be unsupported by data, that MUST be
  reported honestly — the goal is accurate measurement, not confirming a narrative.

## Development Workflow

- Each phase begins with a spec-kit `/specify` → `/plan` → `/tasks` cycle before
  any implementation code is written.
- Design artifacts (spec.md, plan.md, tasks.md) MUST be committed before the first
  implementation commit of a phase.
- `docs/decisions/` MUST receive an ADR for any non-obvious architectural choice
  made during implementation.
- Graphify MUST be re-indexed at the start of each new phase to keep the knowledge
  graph current.

## Quality Standards

- Every module imported at runtime by `proxy` or `frontend` MUST pass `mypy --strict`
  with zero errors.
- Unit tests MUST cover translation logic (JSON ↔ protobuf, protobuf → SamplingParams)
  for every new RPC added.
- Integration tests MUST exercise the full proxy → frontend path for every new
  end-to-end capability.
- The `README.md` MUST be updated before a phase is merged to `main` if the
  onboarding instructions change.

## Governance

- This constitution supersedes all other development guidelines for this project.
- Amendments require: (a) a version bump per semver, (b) an updated Sync Impact
  Report in this file's HTML comment, and (c) a review of affected templates and
  downstream artifacts.
- All PRs to `main` MUST be reviewed against these principles.
- Complexity violations (e.g., adding a fourth package to the workspace) MUST be
  justified in the plan's Complexity Tracking table before implementation begins.

**Version**: 1.0.0 | **Ratified**: 2026-04-28 | **Last Amended**: 2026-04-28
