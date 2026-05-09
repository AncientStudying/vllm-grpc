# Implementation Plan: Milestone 2 — Cross-Repo Ground-Truth Research and Plan Realignment

**Branch**: `014-m2-ground-truth-research` | **Date**: 2026-05-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/014-m2-ground-truth-research/spec.md`

## Summary

Milestone 2 formalizes cross-repo ground-truth research as a durable workflow, not a one-time setup. Three deliverables compose the milestone: (1) a queryable cross-repo knowledge graph (`cross-repo.json`) that merges the project's own graph with `vLLM` and `grpcio` upstream graphs and is wired into Claude Code via `CLAUDE.md` directives and graphify's PreToolUse / post-commit hooks; (2) a realignment of `docs/PLAN.md` so its forward-looking section mirrors the README's M1–M5 framing while preserving Phase 1–7 content as completed-work history; and (3) project-local Claude Code skills that wrap the graphify operations needed to keep `cross-repo.json` current — auto-detecting vLLM and grpcio versions from `uv.lock` (falling back to `pyproject.toml`), surfacing per-step progress, honoring the SHA256 cache on unchanged trees, and auto-rebuilding upstream graphs when the lockfile pin diverges from the cached version. Scope is documentation, configuration, and skill scaffolding — no proxy/frontend/client code is touched, no benchmarks are produced, and graphify itself is not reimplemented.

## Technical Context

**Language/Version**: Python 3.12 (project runtime); skills are Markdown + shell snippets (Claude Code skill format); workflow doc is Markdown.
**Primary Dependencies**: `graphify` CLI (installed via `pip install graphifyy` per the workflow doc; resolved at `~/.local/bin/graphify` on this dev machine). No new runtime Python dependencies are added; skills shell out to the existing `graphify` binary.
**Storage**: Local filesystem only.
- Upstream graphs cached under `~/.graphify/repos/<owner>/<repo>/graphify-out/graph.json` (graphify-managed).
- Project graph at `<repo>/graphify-out/graph.json` (graphify-managed).
- Merged artifact at `<repo>/cross-repo.json` (produced by the refresh skill via `graphify merge-graphs`).
- All three artifacts plus the project's `graphify-out/` directory are gitignored (FR-003).
**Testing**: `make check` (ruff + mypy --strict + pytest) MUST stay green (FR-025, SC-006). No new automated tests are added for the docs/skill changes; manual independent-test procedures for each user story are recorded in `quickstart.md`.
**Target Platform**: Local developer workstations — primary surface is macOS (M2 dev machine) and Linux (CI). Skills do not run in CI.
**Project Type**: Documentation + tooling extension to an existing monorepo (uv workspace at the root with `packages/{proxy,frontend,client,gen}` and `tools/benchmark`). M2 does not change the package layout.
**Performance Goals**: Refresh-skill cold first-build is bounded by graphify's own cost (large for vLLM/grpcio first clones); re-invocation on unchanged trees MUST observably reuse the SHA256 cache so the cadence is cheap (SC-009). No latency targets on the project surface — M2 is a research-tooling milestone.
**Constraints**:
- `cross-repo.json` and `graphify-out/` MUST be gitignored (clarified 2026-05-09); the refresh skill is the supported reproduction path.
- Skill MUST resolve versions from `uv.lock` (falling back to `pyproject.toml`) — no manual version arguments (FR-019a, clarified 2026-05-09).
- Lockfile-vs-cache version drift MUST trigger an automatic upstream rebuild surfaced as a per-step entry (FR-019b, clarified 2026-05-09).
- Workflow document stays at the repository root path `ground-truth-workflow-for-associated-projects.md` (assumption: README links there already).
- Phase 1–7 content in `docs/PLAN.md` is preserved as completed history rather than rewritten; the M1–M5 milestone overlay sits above it with a clearly marked boundary (FR-014).
- `.proto` files are NOT in the graph; `CLAUDE.md` MUST direct readers to `proto/` for proto-shape questions (FR-006d, FR-015).
- No new runtime tooling is introduced — skills wrap `graphify` CLI commands rather than reimplement extraction or merging.
**Scale/Scope**: Three documents touched (`docs/PLAN.md`, `CLAUDE.md`, `ground-truth-workflow-for-associated-projects.md`), one gitignore update, and one project-local skill (or small skill set) committed under `.claude/skills/`. The merged `cross-repo.json` indexes the project (~thousands of LOC) plus the two upstream repos (vLLM ≈ tens of thousands of LOC of Python + C++; grpcio similar). All graphify cost is local CPU on the AST pass; `--deep` is not enabled for M2.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against `.specify/memory/constitution.md` v1.0.0:

- **I. Proto-First** — N/A. M2 introduces no `.proto` edits and no generated stubs. The workflow document and `CLAUDE.md` directives explicitly call out `.proto` as outside the graph and direct readers to `proto/` (FR-006d, FR-015), reinforcing the principle.
- **II. Library Dependency, Not Fork** — Pass. Cloning `vLLM` and `grpcio` for indexing is a *read-only* developer aid. No vLLM or grpcio source is copied into this repo, no patches are applied, and the workflow doc explicitly pins the indexed versions to whatever this project depends on.
- **III. Phase Discipline** — Pass. M2 is the active milestone per the README roadmap. The realignment of `docs/PLAN.md` is itself one of M2's listed deliverables (FR-009 through FR-015). M3 wire-tuning, M4 corpus expansion, and M5 model expansion are described in the realigned PLAN.md but are not implemented in this feature — only described as research questions, matching the spec's out-of-scope section.
- **IV. CI is the Merge Gate** — Pass. FR-025 and SC-006 require `make check` (ruff + mypy --strict + pytest) to stay green after the documentation and skill changes. No CI suppression, no `--no-verify`, no skip directives.
- **V. Honest Measurement** — N/A for this feature directly (no benchmark numbers are produced). The realigned PLAN.md continues to point at `docs/benchmarks/summary.md` for M1's headline numbers (FR-010), preserving the "results live next to the code that produced them" rule.

**Result**: All gates pass with no violations and no NEEDS CLARIFICATION items. The spec's Clarifications section already resolved the three open questions (gitignore policy, version-detection source, drift behavior). Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/014-m2-ground-truth-research/
├── plan.md              # This file (/speckit-plan output)
├── spec.md              # Already authored (/speckit-specify + /speckit-clarify)
├── research.md          # Phase 0 output (/speckit-plan)
├── data-model.md        # Phase 1 output (/speckit-plan)
├── quickstart.md        # Phase 1 output (/speckit-plan)
├── contracts/           # Phase 1 output (/speckit-plan)
│   ├── skill-commands.md
│   ├── cross-repo-artifact.md
│   └── claude-md-directives.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

The feature touches three existing files, adds one gitignore entry block, and adds new project-local skills under `.claude/skills/`. No package source code is modified.

```text
.                                                  # repo root
├── README.md                                       # already aligned to M1–M5; not modified
├── CLAUDE.md                                       # MODIFIED: SPECKIT pointer + graphify navigation
│                                                   #           directives + refresh-skill reference
├── ground-truth-workflow-for-associated-projects.md # MODIFIED: cadence table names refresh
│                                                   #           skill(s); gitignore policy noted;
│                                                   #           lockfile-driven version resolution
│                                                   #           noted; auto-rebuild on drift noted
├── .gitignore                                      # MODIFIED: add /cross-repo.json and /graphify-out/
├── docs/
│   └── PLAN.md                                     # MODIFIED: M1–M5 forward-looking section added
│                                                   #           atop preserved Phase 1–7 history
├── proto/                                          # untouched; referenced as the proto ground
│                                                   # truth (graphify gap)
├── packages/
│   ├── proxy/                                      # untouched
│   ├── frontend/                                   # untouched
│   ├── client/                                     # untouched
│   └── gen/                                        # untouched
├── tools/benchmark/                                # untouched
├── .claude/
│   ├── settings.local.json                         # untouched
│   └── skills/
│       ├── speckit-*                               # untouched
│       └── ground-truth-refresh/                   # NEW: project-local refresh skill set
│           └── SKILL.md                            #      (full-refresh entry point per FR-017;
│                                                   #       additional companion skills if the
│                                                   #       Phase 0 research recommends a multi-
│                                                   #       skill shape, see contracts/)
├── .specify/                                       # untouched
└── graphify-out/                                   # GITIGNORED (per spec clarification);
                                                    # locally produced by `graphify .`
```

**Structure Decision**: This is a documentation-and-tooling feature on top of an existing uv-workspace monorepo. The repository structure does not change; M2 adds new content under `.claude/skills/` (refresh skill[s]) and modifies four existing files (`CLAUDE.md`, `docs/PLAN.md`, `ground-truth-workflow-for-associated-projects.md`, `.gitignore`). No new packages, modules, or test directories are introduced. The skill directory follows the same pattern already used by the `speckit-*` skills shipped with this repo (`SKILL.md` with frontmatter declaring `user-invocable: true`).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No constitution violations. Complexity tracking is empty.
