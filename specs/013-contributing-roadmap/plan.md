# Implementation Plan: Phase 7.1 — Contributing Guide and Project Roadmap

**Branch**: `013-contributing-roadmap` | **Date**: 2026-05-03 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/013-contributing-roadmap/spec.md`

## Summary

Two documentation deliverables: a new `CONTRIBUTING.md` at the repository root covering dev setup, the CI gate, branch naming, PR conventions, and issue reporting; and a `## Roadmap` section added to `README.md` describing Milestone 1 (current, complete) and the research goals of Milestones 2–4.

## Technical Context

**Language/Version**: Markdown only
**Primary Dependencies**: None — no code changes
**Storage**: N/A
**Testing**: `make check` continues to pass (markdown files are not in ruff/mypy/pytest scope); manual review that links are valid
**Target Platform**: N/A
**Project Type**: Documentation only — no new packages, no proto changes, no new modules
**Performance Goals**: N/A
**Constraints**: `make check` must stay green; `CONTRIBUTING.md` must not duplicate README quickstart; roadmap must not promise delivery dates
**Scale/Scope**: 1 new file (`CONTRIBUTING.md`); 1 section added to `README.md`

## Constitution Check

### I. Proto-First ✅ Compliant

No proto changes. All RPC schemas are unchanged.

### II. Library Dependency, Not Fork ✅ Compliant

No vLLM source touched.

### III. Phase Discipline ✅ Compliant

Contributing guide and roadmap are explicitly Phase 7.1 deliverables. No Phase 8 content introduced.

### IV. CI is the Merge Gate ✅ Required

`make check` (ruff + mypy --strict + pytest) must pass. Markdown files are not in scope for any of these tools — verified by confirming no Python files are modified.

### V. Honest Measurement ✅ N/A

No benchmark numbers added or changed. Milestone descriptions reference research goals, not performance claims.

## Project Structure

```text
CONTRIBUTING.md                    ← NEW: developer contribution guide
README.md                          ← MODIFY: add ## Roadmap section
specs/013-contributing-roadmap/    ← this spec
```

No new packages, no proto files, no Python changes.

---

## Phase 0 Research — Complete

See `research.md`. Key decisions:

- `CONTRIBUTING.md` lives at the root; references existing `make` targets without duplicating quickstart
- Branch naming: `NNN-short-description` sequential prefix (observed in all existing branches)
- Roadmap section placed between "Benchmark Headlines" and "Development Commands" in README
- Milestone descriptions: one-sentence goal + research questions; no delivery dates

---

## Phase 1 Design — Complete

### Data Model

Not applicable — no new entities.

### Contracts

Not applicable — no new interfaces.

### Implementation Detail

#### `CONTRIBUTING.md`

Structure:

```
# Contributing to vllm-grpc

Thank you for your interest...

## Development Setup
  - Prerequisites: uv, make (same as README)
  - make bootstrap
  - macOS/Linux only note

## Running the Test Suite
  - make check (ruff + mypy --strict + pytest)
  - make bench-ci for offline benchmark smoke test

## Branch Naming
  - NNN-short-description convention
  - Examples from existing branches

## Pull Requests
  - CI must pass
  - Description explains the why (not just what)
  - One concern per PR

## Reporting Issues
  - GitHub Issues
  - What to include: repro steps, OS, Python version, make check output

## Spec-Kit Workflow (for planned phases)
  - Brief note: /speckit-specify → /plan → /tasks before code
  - Link to README spec-kit section
```

#### `README.md` — Roadmap section

Inserted between `## Benchmark Headlines` and `## Development Commands`:

```
## Roadmap

### Milestone 1 — Foundation (current release)
Three access paths benchmarked on Modal A10G. Summary + links.

### Milestone 2 — Parameter Tuning
vLLM serving parameters + grpcio channel settings.
Research questions: max message size / latency, continuous batching interaction,
channel config for minimum TTFT.

### Milestone 3 — Corpus Expansion
Larger, more varied prompts (short/long, multi-turn, code, structured data).
Research questions: wire-size delta vs prompt length, TPOT variance across types.

### Milestone 4 — Model Expansion
Additional models (different sizes + architecture families).
Research questions: larger model shift on latency story, output-length effects
on response-byte delta.
```

---

## Post-Design Constitution Re-Check

All five principles remain satisfied. No code touched.
