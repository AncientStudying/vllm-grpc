# Phase 1 — Data Model: Milestone 2 Ground-Truth Workflow

**Feature**: 014-m2-ground-truth-research
**Date**: 2026-05-09

This feature has no traditional database schema. Its "entities" are documents, on-disk artifacts, and Claude Code surfaces. This file enumerates each, the fields each carries, the relationships between them, and the validation rules implied by the functional requirements.

---

## Entities

### 1. `cross-repo.json` — merged knowledge graph artifact

**Path**: `<repo>/cross-repo.json` (repo root).
**Producer**: `graphify merge-graphs ./graphify-out/graph.json ~/.graphify/repos/vllm-project/vllm/graphify-out/graph.json ~/.graphify/repos/grpc/grpc/graphify-out/graph.json --out cross-repo.json` — invoked by the refresh skill.
**Consumer**: Claude Code (via `graphify query --graph cross-repo.json`), maintainer (read-only).
**Lifecycle**: Built locally; gitignored; rebuilt on every full-refresh skill invocation. Not a CI artifact.

**Fields** (graphify-managed; this feature does not define the schema, it consumes it):
- Nodes (god nodes, communities) spanning three source graphs.
- Edges (call paths, AST relationships).
- Per-node provenance: which source graph contributed each node.

**Relationships**:
- Composed from three source graphs:
  1. Project graph at `<repo>/graphify-out/graph.json`.
  2. Upstream vLLM graph at `~/.graphify/repos/vllm-project/vllm/graphify-out/graph.json`.
  3. Upstream grpcio graph at `~/.graphify/repos/grpc/grpc/graphify-out/graph.json`.

**Validation rules**:
- MUST exist after a successful refresh-skill invocation (FR-018 reports the path on success).
- MUST be gitignored (FR-003, clarified 2026-05-09).
- Vendor-version drift between lockfile and the version recorded in either upstream graph's manifest MUST cause a rebuild on the next refresh-skill invocation (FR-019b).

**State transitions**:
- *absent* → *present-and-current*: full-refresh skill run from cold (all three graphs built, then merged).
- *present-and-current* → *stale*: lockfile updated for vLLM or grpcio without re-running refresh; or local commits without the graphify post-commit hook running.
- *stale* → *present-and-current*: refresh-skill invocation auto-detects drift and rebuilds the affected upstream(s) plus the local graph, then re-merges.

---

### 2. Project local graph — `<repo>/graphify-out/graph.json`

**Path**: `<repo>/graphify-out/graph.json` (and sibling `graph.html`, `GRAPH_REPORT.md`, `cost.json`, `manifest.json`, `cache/`).
**Producer**: `graphify .` invoked by the refresh skill, or by graphify's post-commit / post-checkout hook (FR-004).
**Consumer**: Claude Code's PreToolUse hook (handles project-local queries automatically per FR-005); refresh skill (input to merge step).
**Lifecycle**: Built locally; gitignored; rebuilt automatically on commit/checkout via graphify's hooks once `graphify hook install` has been run.

**Validation rules**:
- The project's `graphify-out/` directory MUST be gitignored (FR-003 clarification).
- Hook installation (`graphify hook install`) is a one-time setup step listed in the workflow doc and surfaced in the refresh skill's prerequisite check.

---

### 3. Upstream graphs — `~/.graphify/repos/<owner>/<repo>/graphify-out/graph.json`

**Paths**:
- `~/.graphify/repos/vllm-project/vllm/graphify-out/graph.json` (vLLM)
- `~/.graphify/repos/grpc/grpc/graphify-out/graph.json` (grpcio)

**Producer**: `graphify clone <github-url>` (first build) and `graphify update <path>` (subsequent rebuilds), both invoked by the refresh skill on demand.
**Consumer**: Refresh skill (input to merge step).
**Lifecycle**: Cached under the user's home directory; not in the repo's filesystem; reused across projects that share the same upstreams; rebuilt only when the lockfile-resolved version diverges from the manifest-recorded version (R-002, FR-019b).

**Validation rules**:
- Each upstream's checked-out version MUST track the lockfile-resolved version (R-001).
- A drift between resolved version and cached version MUST trigger an automatic rebuild surfaced as a per-step entry (FR-019b: e.g., "rebuilding vLLM graph @ 0.21.0 (was 0.20.0)").

---

### 4. Workflow document — `ground-truth-workflow-for-associated-projects.md`

**Path**: `<repo>/ground-truth-workflow-for-associated-projects.md` (repository root, per spec.md §Assumptions).
**Producer**: Maintainer-edited; this feature appends/edits sections.
**Consumer**: Maintainers and contributors following the workflow; Claude Code reading link references from `README.md`, `docs/PLAN.md`, and `CLAUDE.md`.

**Sections required by FR**:
- One-time install (FR-001 through FR-005 setup steps already documented).
- Build the vLLM reference graph (FR-001).
- Build the grpcio reference graph (FR-002).
- Build the local graph + Claude Code integration + post-commit hook (FR-003 through FR-005).
- Merge into a cross-repo graph (FR-003) — call out the gitignore policy for the produced `cross-repo.json` and the project's `graphify-out/`.
- Querying from Claude Code (already documented).
- Cost shape, known gaps (already documented; reaffirmed by FR-006d, FR-015).
- CLAUDE.md additions (the four directives quoted in FR-006).
- **Rebuild cadence table** — FR-007 lists required trigger rows; FR-021 requires each row to name the refresh skill.
- Versions resolved from `uv.lock` / `pyproject.toml` — note added per FR-019a.
- Auto-rebuild on lockfile drift — note added per FR-019b.

**Validation rules**:
- The README's M2 link MUST resolve to this file at this path (FR-023). The path is already used in `README.md`, so the constraint is preserved-as-is.
- Cadence table rows MUST cover: local commit, `git pull`, vLLM dependency bump, grpcio dependency bump, substantial local refactor (FR-007).
- Each cadence row MUST name the skill to invoke (FR-021).

---

### 5. `docs/PLAN.md` — project plan (forward-looking + history)

**Path**: `<repo>/docs/PLAN.md`.
**Sections after this feature**:
1. Status banner / metadata (existing, lightly updated).
2. §0 Document Purpose (existing).
3. **NEW** §1 Milestone Roadmap (canonical, M1–M5) — added by this feature; mirrors README.
4. **NEW** §2 boundary heading: "Phase History (preserved as completed-work record)".
5. Existing §1 Project Overview through §8 Working with Claude Code, renumbered as §3 onward to sit under the §2 boundary.

(Numbering scheme is illustrative — the actual headings can use different markup; the spec only requires a clearly marked boundary, not a specific renumbering.)

**Required content per FR**:
- M1: marked delivered; references `docs/benchmarks/summary.md` for headline numbers (FR-010).
- M2: described as the formalization of cross-repo ground-truth research; links to `ground-truth-workflow-for-associated-projects.md` (FR-011).
- M3: protobuf and gRPC tuning driven by a mock model with configurable `hidden_size` (canonical 2048 / 4096 / 8192); states real model weights are not required because embed payload size is determined by `hidden_size` rather than total parameter count (FR-012).
- M4: corpus expansion across longer prompts, multi-turn context, and structurally varied content (FR-013 part 1).
- M5: model expansion validating the wire-overhead thesis across different sizes/architectures, and validating that mock-derived M3 findings hold against real models (FR-013 part 2).
- M2 entry MUST flag the same known gap the README does (FR-015): graphify does not parse `.proto` files.

**Validation rules**:
- The new milestone overlay's M2–M5 descriptions MUST not contradict README.md (FR-024); side-by-side read shows the same research questions (SC-004).
- The boundary between forward-looking and historical content MUST be visually clear (spec.md §Edge Cases).
- A cold reader MUST be able to identify M1 delivered + M2–M5 open questions in under 2 minutes (SC-003).

---

### 6. `CLAUDE.md` — Claude Code project instructions

**Path**: `<repo>/CLAUDE.md`.
**Sections after this feature** (in order):
1. SPECKIT block (between `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers) — pointer updated to `specs/014-m2-ground-truth-research/plan.md`.
2. **NEW** Codebase navigation — the four directives from FR-006:
   - (a) consult `cross-repo.json` for vLLM-internals questions before reading vLLM source.
   - (b) consult `cross-repo.json` for grpcio channel-behavior questions before reading grpcio source.
   - (c) for the project's own gRPC/proto layer, the local graph + PreToolUse hook is sufficient.
   - (d) `.proto` definitions are NOT in the graph; read `proto/` directly.
3. **NEW** Refresh skill reference — points at `/ground-truth-refresh` as the canonical staleness recovery (FR-022).
4. (Eventually) graphify-managed PreToolUse hook section — added by `graphify claude install` per the workflow doc; not hand-edited by this feature.

**Validation rules**:
- All four FR-006 directives MUST be present and unambiguous.
- The refresh-skill reference MUST name the actual skill that resolves to `/ground-truth-refresh` per R-009.

---

### 7. Refresh skill — `.claude/skills/ground-truth-refresh/SKILL.md`

**Path**: `<repo>/.claude/skills/ground-truth-refresh/SKILL.md`.
**Producer**: This feature creates it.
**Consumer**: Claude Code's slash-command runtime; the maintainer invoking `/ground-truth-refresh`.
**Format**: Same Markdown-with-frontmatter shape as the existing `speckit-*` skills under `.claude/skills/`.

**Frontmatter fields**:
- `name`: `"ground-truth-refresh"`.
- `description`: one-line description suitable for the slash-command list (e.g., "Rebuild project + upstream graphs and merge into cross-repo.json — auto-detects vLLM and grpcio versions from uv.lock.").
- `argument-hint`: optional; not required for M2.
- `compatibility`: project requires graphify CLI installed.
- `user-invocable`: `true`.
- `disable-model-invocation`: `false` (Claude Code may invoke when staleness is suspected).

**Body steps** (per FR-016 through FR-020 and the contracts/ files):
1. Verify working directory: `pyproject.toml` exists at `$PWD` and `[project] name == "vllm-grpc"`. Else exit with actionable message (R-004, FR-020).
2. Verify graphify presence: `command -v graphify`. Else exit with `pip install graphifyy && graphify install` instruction and a pointer to `ground-truth-workflow-for-associated-projects.md` (R-005, FR-020).
3. Resolve target versions: read `uv.lock` for `vllm` and `grpcio`; fall back to `pyproject.toml` when lockfile is absent. Record the resolution source in the per-step output (R-001, FR-019a).
4. Compare resolved versions against `~/.graphify/repos/<owner>/<repo>/graphify-out/manifest.json`. For each upstream:
   - If cached version matches, mark "skipped (cache current)".
   - If different, run `graphify clone` (first time) or check out the new tag and re-extract; surface as "rebuilding <repo> graph @ <new> (was <old>)" (R-002, FR-019b).
   - If the package is not present in the lockfile or pyproject (e.g., vLLM via `--with`), report "skipped: not pinned" with actionable next step (R-001 tail).
5. Run `graphify .` against the project to refresh the local graph. Honor SHA256 cache (FR-019).
6. Run `graphify merge-graphs ... --out cross-repo.json` to produce the merged artifact (FR-003, FR-018).
7. Print final status block: per-step outcome (success / failure / skipped / rebuilt) plus the absolute path to `cross-repo.json`.

**Validation rules**:
- Single invocation MUST drive all of (3)–(6) (FR-017).
- Each step MUST report success / failure / skipped (FR-018).
- SHA256 cache MUST be honored — re-invocation on an unchanged tree completes substantially faster than a cold first build (FR-019, SC-009).
- Missing prerequisites MUST be reported actionably (FR-020).

---

### 8. `.gitignore` updates

**Path**: `<repo>/.gitignore`.
**New entries** (added under or near the existing "graphify output" comment block):

```text
# Cross-repo merged graph (locally rebuilt via /ground-truth-refresh)
/cross-repo.json

# Project local graph artifacts (locally rebuilt via graphify hooks or /ground-truth-refresh)
/graphify-out/
```

The existing more-specific entries (`graphify-out/cache/`, `graphify-out/manifest.json`, `docs/graphs/`) become redundant once `/graphify-out/` is fully ignored, but are left in place for backward compatibility (no behavioral change).

**Validation rules**:
- After the edit, `git status` on a fresh `graphify .` + merge MUST show no untracked entries under `graphify-out/` and no `cross-repo.json` (FR-003).

---

## Cross-entity relationships

```text
uv.lock ──(read by)──► refresh skill ──(invokes)──► graphify CLI
                              │
                              ├──(produces / refreshes)──► graphify-out/graph.json     (project local)
                              ├──(produces / refreshes)──► ~/.graphify/repos/.../graph.json (vLLM)
                              ├──(produces / refreshes)──► ~/.graphify/repos/.../graph.json (grpcio)
                              └──(merges into)─────────► cross-repo.json

cross-repo.json ──(consulted by)──► Claude Code via graphify query (per CLAUDE.md directives)
ground-truth-workflow-for-associated-projects.md ──(linked from)──► README.md, CLAUDE.md, docs/PLAN.md
docs/PLAN.md ──(canonical M1–M5 framing kept aligned with)──► README.md
```

No state transitions cross processes (no databases, no cross-machine state). All transitions are local file system events triggered by either the refresh skill or graphify's own hooks.
