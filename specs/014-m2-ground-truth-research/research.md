# Phase 0 — Research: Milestone 2 Ground-Truth Workflow

**Feature**: 014-m2-ground-truth-research
**Date**: 2026-05-09
**Status**: Complete — all NEEDS CLARIFICATION items resolved during `/speckit-clarify` (see spec §Clarifications) or below.

This document consolidates the research needed before Phase 1 design. The Technical Context section of `plan.md` listed no NEEDS CLARIFICATION entries, so the work here focuses on **dependency questions** (graphify CLI behavior, lockfile parsing) and **integration questions** (skill packaging shape, Claude Code hook surface, gitignore policy, PLAN.md preservation strategy).

---

## R-001 — How should the refresh skill resolve the target vLLM and grpcio versions?

**Decision**: Read versions from `uv.lock` first; fall back to `pyproject.toml` (workspace `dependencies` plus the `dev` and `investigation` dependency-groups) only when the lockfile is absent or unreadable. The skill records which source was used in its per-step output.

**Rationale**:
- The clarification explicitly chose this source-of-truth (spec.md §Clarifications, 2026-05-09).
- `uv.lock` is committed to the repo (see top-level `uv.lock`) and pins concrete versions (`grpcio==1.80.0` was visible in the lockfile during planning); resolving against the lockfile keeps the cross-repo graph in sync with what the project actually imports.
- `pyproject.toml` alone gives only ranges (e.g., `grpcio-tools>=1.65`); ranges are insufficient to identify a single git tag for graphify to clone. The fallback exists so that a contributor whose lockfile is out of date or absent still gets a deterministic, if approximate, behavior — the skill resolves to the lower bound and surfaces the fallback in its per-step output so the cause is visible.
- vLLM is not currently a top-level dependency in `pyproject.toml` (it is loaded via `--with vllm` per the comment in `pyproject.toml`). The skill MUST therefore tolerate vLLM being absent from both files and emit an actionable per-step entry (e.g., "vLLM not pinned in lockfile or pyproject.toml — skipping vLLM upstream graph; pin vLLM and re-run if cross-vLLM queries are needed"). This matches FR-020 (actionable error reporting).

**Alternatives considered**:
- *Manual `--vllm-version` / `--grpcio-version` CLI flags* — rejected during clarification: pin lives in one place; manual flags drift.
- *Reading the installed package metadata via `importlib.metadata`* — rejected: requires the repo's venv to be active and the package installed; the skill must work without entering the venv first. Lockfile parsing is more robust.
- *Git submodules* — rejected: out of scope and would entangle the repo with two large upstream histories. Graphify already manages the local clones under `~/.graphify/repos/`.

---

## R-002 — How should the refresh skill detect a stale upstream cache?

**Decision**: Compare the lockfile-resolved version (from R-001) against the version recorded in the cached upstream graph's manifest at `~/.graphify/repos/<owner>/<repo>/graphify-out/manifest.json`. When they differ, the skill checks out the new version in the existing clone (or re-clones if necessary) and runs `graphify update <path>` (or `graphify .` from the repo) to rebuild. The rebuild is surfaced as a per-step entry: `"rebuilding vLLM graph @ 0.21.0 (was 0.20.0)"`.

**Rationale**:
- Spec clarification 2026-05-09 chose auto-rebuild + per-step surfacing (FR-019b).
- Graphify writes a `manifest.json` next to the graph (confirmed in this repo's `graphify-out/manifest.json`) — the skill can read whatever version-marker graphify already records there and avoid inventing parallel state.
- Surfacing the rebuild as a discrete per-step entry (FR-018) matches how the skill reports other steps; the user sees expensive work running and can correlate the cost to the lockfile bump.

**Alternatives considered**:
- *Always-rebuild-when-uncertain* — rejected: defeats SC-009 (cache reuse on unchanged trees).
- *Silent rebuild* — rejected: the user has no way to attribute time spent.
- *Version-marker file inside `.graphify/repos/<owner>/<repo>/`* — only used as fallback if graphify's own manifest does not record the version; no parallel state if graphify already covers it.

---

## R-003 — Should the refresh capability be one skill or several?

**Decision**: Ship one user-invocable full-refresh skill at `.claude/skills/ground-truth-refresh/SKILL.md` that performs the entire sequence (resolve versions → ensure upstream graphs → rebuild local graph → merge into `cross-repo.json` → report). Internally it executes the four documented graphify commands. No companion skills are split out for M2.

**Rationale**:
- FR-017 requires that the full refresh be available in **one** invocation. A single skill satisfies this most directly.
- The spec's §Assumptions explicitly defers the multi-skill-vs-one-skill question to `/speckit-plan` and only requires that a single-invocation full-refresh path exists.
- The cadence table in the workflow doc references one skill per trigger row (FR-021); one skill keeps that table simple.
- Splitting into N specialized skills (refresh-local, refresh-vllm, refresh-grpcio, refresh-all) creates four entry points the maintainer must remember. The graphify CLI already provides per-target granularity for the maintainer who wants it; the skill exists specifically to remove that branching from the daily path.
- If a future need emerges to refresh exactly one upstream (e.g., grpcio bumped, vLLM unchanged), the SHA256 cache makes the full-refresh skill's "skipped" steps cheap. Adding more skills can wait until that need is observed.

**Alternatives considered**:
- *One parameterized skill with `--target=local|vllm|grpcio|all`* — rejected: skill arguments are awkward to discover from the slash-command UI; the cache-driven full-refresh has the same effective performance.
- *Four separate skills* — rejected per above.

---

## R-004 — How does the skill detect that the working directory is the vllm-grpc repo?

**Decision**: The skill's first step verifies (a) `pyproject.toml` exists at the repo root and (b) its `[project] name` is `"vllm-grpc"`. If either check fails, the skill exits early with an actionable message ("Refusing to refresh: not in the vllm-grpc working tree (expected pyproject.toml with name=vllm-grpc). Run from the repo root.").

**Rationale**:
- FR-020 requires actionable rather than raw shell errors when the working directory is wrong.
- The edge-case in spec.md §Edge Cases ("running against an unrelated repository should refuse cleanly") is satisfied.
- Reading `pyproject.toml`'s `[project] name` is cheap and unambiguous; relying on `git remote get-url origin` is fragile because forks rename remotes.

**Alternatives considered**:
- *Relying on `graphify.json`'s `name` field* — viable; `graphify.json` is committed and contains `"name": "vllm-grpc"`. Used as a secondary signal but not the primary check, because `pyproject.toml` is the canonical project identity.

---

## R-005 — How does the skill detect that graphify is installed?

**Decision**: The skill calls `command -v graphify` (or equivalent in its shell wrapper) before any graphify invocation. If absent, it exits with the install instruction from the workflow document: `pip install graphifyy && graphify install`. The error message names the workflow doc by path so the user can read the broader setup context.

**Rationale**:
- FR-020 again — actionable next step rather than `command not found`.
- The workflow document's "One-time install" section is the canonical install reference; pointing at it avoids duplicating instructions in the skill.

**Alternatives considered**:
- *Auto-installing graphify* — rejected: skills should not silently install developer tooling. Maintaining the install step as an explicit user action keeps the system property "no daemon installs without consent."

---

## R-006 — Where should `cross-repo.json` live, and should it be gitignored?

**Decision**: At the repo root (`<repo>/cross-repo.json`). Gitignored. The repo root is the path the workflow doc already documents in its `graphify merge-graphs --out cross-repo.json` example.

**Rationale**:
- Spec clarification 2026-05-09 chose gitignore for both `cross-repo.json` and the project's `graphify-out/` directory: locally-built artifacts; the refresh skill makes rebuild cheap.
- Repo root keeps the file at the same path the workflow doc already references; moving it under `docs/` or `tools/` would require updating examples and the merge command in the cadence table.
- Gitignoring it avoids committing a multi-megabyte JSON artifact that becomes stale and bloats the git history. The cadence table already states that re-running the merge is fast.

**Alternatives considered**:
- *Commit `cross-repo.json`* — rejected during clarification.
- *Place under `graphify-out/` with the per-graph artifact* — rejected: the merged graph spans three repos and is conceptually distinct from the project's own `graphify-out/graph.json`. Keeping them at sibling paths makes the distinction visible.

---

## R-007 — How are the existing `docs/PLAN.md` Phase 1–7 contents preserved?

**Decision**: Insert a new "Milestone Roadmap (canonical, M1–M5)" section near the top of `docs/PLAN.md`, immediately after §0 Document Purpose. The section opens with one paragraph stating "M1 is delivered (see [`docs/benchmarks/summary.md`](benchmarks/summary.md)); M2 is the active milestone (see this spec); M3–M5 are upcoming research directions" and then carries the M1–M5 entries in the same one-to-two-sentence research-question form the README uses. Below that, a clearly marked H2 boundary `## Phase History (preserved as completed-work record)` introduces the existing §1–§8 content unchanged.

**Rationale**:
- FR-014 requires the boundary to be visually clear so readers don't mistake the historical phase content for a forward plan.
- Inserting near the top (before §1) means the milestone roadmap is what a cold reader sees first, satisfying SC-003 (a reader can identify M1 delivered + M2–M5 open questions in under 2 minutes).
- The §1 onward content is the contract that decided what shipped in M1 — preserving it verbatim respects the "completed-work history" framing in the spec's §Assumptions.
- FR-024 requires the M2–M5 descriptions in PLAN.md and README.md to not contradict; copying the README's research-question framing into PLAN.md (rather than rephrasing) is the simplest way to keep them aligned. When either document is updated, the matching update is mechanical.

**Alternatives considered**:
- *Replace Phase 1–7 with the milestone overlay* — rejected by spec assumption: Phase 1–7 captures decisions and trade-offs that still inform future work.
- *Move Phase 1–7 to a separate `docs/PHASE-HISTORY.md`* — out of scope for M2 and would require updating any link that points at the existing PLAN.md path; the within-document boundary is sufficient.

---

## R-008 — What goes into the CLAUDE.md updates?

**Decision**: Replace the current minimal `CLAUDE.md` (only the SPECKIT marker pointing at `specs/013-contributing-roadmap/plan.md`) with three sections, in this order:

1. **SPECKIT pointer** — updated to point at `specs/014-m2-ground-truth-research/plan.md` (Phase 1 design step).
2. **Codebase navigation** — the four-bullet directive block from the workflow doc's "CLAUDE.md additions" section (vLLM internals via `cross-repo.json`; grpcio channel behavior via `cross-repo.json`; project's own gRPC/proto layer via local graph + PreToolUse hook; `.proto` files read directly).
3. **Refresh skill reference** — one short paragraph: "If `cross-repo.json` is suspected stale (lockfile bumped, upstream pulled, substantial refactor), invoke the refresh skill rather than running graphify commands by hand. The skill auto-detects target versions from `uv.lock`, surfaces per-step progress, and reuses graphify's SHA256 cache so re-invocation on an unchanged tree is cheap." Names the slash command resolved in R-009.

The graphify-installed PreToolUse hook (added by `graphify claude install`) is a separate section graphify itself manages — the M2 work doesn't hand-edit it; it just runs `graphify claude install` once per the workflow doc.

**Rationale**:
- FR-006 enumerates the four required directives; lifting them from the workflow doc avoids drift.
- FR-022 requires the refresh skill to be referenced as the canonical staleness recovery; (3) provides that reference.
- The SPECKIT pointer is updated as part of Phase 1's "agent context update" step.

**Alternatives considered**:
- *Embed the cadence table in CLAUDE.md* — rejected: the cadence table belongs in the workflow doc (one canonical location). CLAUDE.md should point at the doc, not duplicate it.

---

## R-009 — What is the slash-command name for the refresh skill?

**Decision**: `/ground-truth-refresh`. The skill directory is `.claude/skills/ground-truth-refresh/` and its `SKILL.md` declares `user-invocable: true` (matching the existing speckit skill format).

**Rationale**:
- The slash-command name maps directly from the directory name in the existing speckit pattern (`.claude/skills/speckit-plan/` → `/speckit-plan`).
- "ground-truth-refresh" matches the language used in spec.md and the workflow doc, so a contributor reading the cadence table never has to translate between names.
- Avoids "graphify-refresh" as a name because the refresh covers more than graphify alone — it also reads the lockfile and produces the merged artifact at the project's chosen path.

**Alternatives considered**:
- `/refresh-cross-repo` — clearer about what it produces but less aligned with the spec's "ground-truth workflow" framing.
- `/m2-refresh` — too tied to the milestone number; the skill outlives M2.

---

## R-010 — Should `make check` learn anything new?

**Decision**: No. `make check` (ruff + mypy --strict + pytest) is unchanged. The documentation and skill changes do not add Python code to the workspace, so there is nothing for the existing CI gate to type-check or test. SC-006 / FR-025 verify only that the *existing* gate continues to pass after the docs and gitignore edits.

**Rationale**:
- M2 explicitly does not introduce new Python source; the skill is Markdown + shell snippets (Claude Code skill format), executed by the user via the slash-command runtime, not imported by the project.
- Adding a markdown-link-checker or a workflow-doc lint job would be a Phase 4-style investment that this milestone does not require.

**Alternatives considered**:
- *Add a docs-link-check job* — possible future work; out of scope for M2 per the principle of building only what the current phase's deliverables list (Constitution III).
- *Add a script that exercises the refresh skill in CI* — rejected: the skill's whole point is local-developer ergonomics; running it in CI would require committing graphify to CI environments and managing upstream clone caches in CI runners. The spec assumption "the project's CI does not need to depend on `cross-repo.json`" applies.

---

## Summary of decisions feeding Phase 1

| # | Topic | Decision summary |
|---|-------|------------------|
| R-001 | Version source | `uv.lock` then `pyproject.toml` fallback |
| R-002 | Drift detection | Compare lockfile vs cached manifest; auto-rebuild with per-step surfacing |
| R-003 | Skill shape | One full-refresh skill |
| R-004 | Repo identity check | `pyproject.toml [project] name == "vllm-grpc"` |
| R-005 | graphify presence check | `command -v graphify` with workflow-doc-pointing fallback message |
| R-006 | `cross-repo.json` location | Repo root; gitignored |
| R-007 | PLAN.md preservation | Milestone overlay above preserved Phase 1–7 history |
| R-008 | CLAUDE.md additions | SPECKIT pointer + 4-bullet navigation directives + refresh-skill reference |
| R-009 | Slash command | `/ground-truth-refresh` at `.claude/skills/ground-truth-refresh/` |
| R-010 | CI surface | Unchanged; no new lint/test jobs |

All NEEDS CLARIFICATION are resolved. Phase 1 design proceeds.
