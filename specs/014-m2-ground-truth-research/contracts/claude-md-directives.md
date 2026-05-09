# Contract: `CLAUDE.md` Directives

**Feature**: 014-m2-ground-truth-research
**Contract type**: Instructions read by Claude Code at session start; defines navigation behavior for code-reading questions.

This contract documents what `CLAUDE.md` MUST contain after this feature ships, and what each directive promises to a reader (the next Claude Code session, or a contributor reading `CLAUDE.md` to understand how the project expects code questions to be answered).

---

## Sections in order

```text
1. SPECKIT block (markers + plan pointer)
2. Codebase navigation (four directives)
3. Refresh skill reference
4. (graphify-managed) PreToolUse hook section — added by `graphify claude install`,
   not edited by this feature
```

## 1. SPECKIT block

```markdown
<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
at specs/014-m2-ground-truth-research/plan.md
<!-- SPECKIT END -->
```

- Pointer updated as part of Phase 1's "agent context update" step.
- Markers MUST remain in place; the speckit tooling round-trips between them.

## 2. Codebase navigation directives (FR-006)

The four directives below, copy-pasted from the workflow document so the canonical wording lives in one place:

```markdown
## Codebase navigation

- For questions about vLLM internals (engine, scheduler, model executor,
  KV cache, sampling, worker), consult `cross-repo.json` via
  `/graphify query` before reading vLLM source files directly.
- For questions about grpcio channel behavior (max_message_size, keepalive,
  compression, HTTP/2 framing, streaming flow control), consult the same
  `cross-repo.json` first; fall back to grpcio C-core source only when the
  Python wrappers don't answer it.
- For questions about this project's own gRPC/proto layer, the local
  `graphify-out/graph.json` is sufficient — the PreToolUse hook handles it.
- `.proto` definitions are NOT in the graph. When proto-level questions
  come up, read the relevant `.proto` file directly rather than querying
  the graph.
```

Validation: any audit of `CLAUDE.md` MUST find all four bullets, in this order, with the directives intact (FR-006 a/b/c/d).

## 3. Refresh skill reference (FR-022)

```markdown
## Keeping the cross-repo graph current

If `cross-repo.json` is suspected stale (lockfile bumped, upstream pulled,
substantial local refactor), run `/ground-truth-refresh` rather than
running graphify commands by hand. The skill auto-detects target versions
from `uv.lock` (falling back to `pyproject.toml`), surfaces per-step
progress, and reuses graphify's SHA256 cache so re-invocation on an
unchanged tree is cheap. See
`ground-truth-workflow-for-associated-projects.md` for the underlying
commands and rebuild cadence.
```

Validation: the slash-command name MUST match the directory under `.claude/skills/` (Phase 0 R-009: `/ground-truth-refresh`).

## 4. graphify-managed PreToolUse hook section

This section is created by `graphify claude install` (the workflow doc's setup step) and is not hand-edited by this feature. The feature's contract is that the hook is run *once* during initial setup, after which graphify maintains its own block in `CLAUDE.md`. If a contributor wipes `CLAUDE.md`, they would need to re-run `graphify claude install`.

## Compatibility

`CLAUDE.md` is read by Claude Code at session start. The four directives are the project's public statement that:

- Code-navigation questions are not answered by blind `Glob`/`Grep` when a graph is available.
- Specific gaps (`.proto`, CUDA kernels) are documented exceptions.
- Staleness has a single recovery path (`/ground-truth-refresh`), not a multi-step recipe to remember.

This contract is satisfied by the file content — there is no runtime check. The independent test for this contract is User Story 4's "Without prior context, follow the workflow document and reach `cross-repo.json`": if a cold reader cannot locate the four directives in `CLAUDE.md` after that walkthrough, the contract has regressed.
