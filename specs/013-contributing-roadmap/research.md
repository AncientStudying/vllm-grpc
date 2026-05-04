# Phase 0 Research: Contributing Guide and Project Roadmap

## Decision Log

| # | Topic | Decision | Rationale |
|---|-------|----------|-----------|
| 1 | Where does CONTRIBUTING.md live? | Repository root — `CONTRIBUTING.md` | GitHub auto-links it from the "Contribute" button; standard convention |
| 2 | What make targets should CONTRIBUTING.md reference? | `make bootstrap`, `make check`, `make proto`, `make bench-ci` | These four cover setup, CI gate, proto regen, and offline bench smoke test; all other targets require a live model or Modal credentials |
| 3 | What branch naming convention does this project use? | `NNN-short-description` sequential prefix (e.g., `013-contributing-roadmap`) — derived from spec-kit init-options | Observed in all existing branches and spec directories |
| 4 | Should CONTRIBUTING.md describe the spec-kit workflow? | Yes, briefly — link to existing README spec-kit section | Contributors should know that planned phases start with `/speckit-specify` before code; no need to duplicate the full workflow |
| 5 | Should CONTRIBUTING.md duplicate the quickstart from README? | No — link to README quickstart | Avoids drift; the single source of truth is README.md |
| 6 | Where does the roadmap section go in README? | New `## Roadmap` section placed after `## Benchmark Headlines`, before `## Development Commands` | Evaluators who reach the benchmark section are already engaged; roadmap answers the natural next question "what's next?" |
| 7 | How detailed should milestone descriptions be? | One sentence goal + two to three bullet research questions per milestone | Enough to understand the direction and identify where a contributor might help; not a committed schedule |
| 8 | Should Milestone 1 list specific deliverables? | Yes — link to `docs/benchmarks/summary.md` and name the three access paths | Milestone 1 is complete so its scope is factual, not aspirational |
| 9 | Should docs/PLAN.md be updated? | No — PLAN.md describes internal phase roadmap for developers; README roadmap is user-facing and describes research milestones at a higher level of abstraction | They serve different audiences |

## Existing Content Audit

### README.md current sections (in order)
1. What is this? (thesis)
2. Three access paths
3. Prerequisites
4. Quick start
5. Benchmark headlines
6. Development commands
7. Repository structure
8. CI

Roadmap section will be inserted between "Benchmark headlines" (section 5) and "Development commands" (section 6).

### No existing CONTRIBUTING.md
Confirmed absent. Will be created fresh.

## Alternatives Considered

- **Put roadmap in docs/PLAN.md instead**: Rejected — PLAN.md is a developer-internal planning document describing implementation phases; the roadmap in README.md is a user-facing research trajectory that operates at a higher level.
- **Full milestone specs in CONTRIBUTING.md**: Rejected — CONTRIBUTING.md is about participation mechanics, not research content.
- **Combine CONTRIBUTING.md into README.md**: Rejected — README is already comprehensive; a separate file is the GitHub convention and keeps README focused on getting started.
