# Contract: `cross-repo.json` Artifact

**Feature**: 014-m2-ground-truth-research
**Contract type**: On-disk artifact path, lifecycle, and consumer expectations.

This contract documents what `cross-repo.json` is, where it lives, who produces and consumes it, and the invariants the refresh skill maintains.

---

## Path

```text
<repo>/cross-repo.json
```

Repository root. Absolute path on the dev machine: `/Users/<user>/projects/vllm-grpc/cross-repo.json`.

The README does not link this file directly (it is locally produced); the workflow document references the path in the `graphify merge-graphs --out cross-repo.json` example.

## Producers

Single producer:

- The `/ground-truth-refresh` skill (Phase 0 R-009) — wraps `graphify merge-graphs`.

A maintainer can equivalently run the four graphify commands by hand from the workflow doc, but the skill is the documented and recommended path (FR-021, FR-022).

## Consumers

- **Claude Code via `/graphify query --graph cross-repo.json`** — the primary consumer. CLAUDE.md directives (FR-006a, FR-006b) instruct Claude Code to consult this artifact for vLLM-internals and grpcio-channel-behavior questions before reading upstream source.
- **Maintainers** — open `graphify-out/graph.html` (the per-graph HTML) for visual inspection; `cross-repo.json` itself is JSON and not typically read by hand.

## Lifecycle

| Event | Result |
|-------|--------|
| Fresh clone, never refreshed | absent |
| First `/ground-truth-refresh` invocation | created — all three graphs built, then merged |
| Re-invocation, no upstream version change, no local commits | unchanged on disk (graphify cache returns identical bytes for identical inputs) |
| Re-invocation, upstream version bumped in `uv.lock` | rebuilt — drift detected in step 2, affected upstream rebuilt, merge re-run |
| Local commit (with `graphify hook install` set up) | local graph rebuilt automatically; merge step still requires `/ground-truth-refresh` to bring `cross-repo.json` to current |
| `git pull` introducing local code changes | same as local commit — local rebuild is automatic, merge requires explicit refresh |

## Gitignore policy

- `cross-repo.json` MUST be gitignored (FR-003, clarification 2026-05-09).
- The project's `graphify-out/` directory MUST be gitignored (same clarification).
- The implementation adds `/cross-repo.json` and `/graphify-out/` to `.gitignore` and verifies with `git status` that these paths do not appear as untracked after a refresh.

## Schema

Schema is owned by graphify; this feature does not redefine it. The refresh skill produces whatever shape `graphify merge-graphs` writes given the three input graphs. Consumers query through `graphify query --graph cross-repo.json` rather than parsing the JSON directly.

## Invariants

After a successful refresh-skill invocation:

1. The file exists at the documented path.
2. Its contents merge exactly the three source graphs identified in step 1 of the skill (project + vLLM + grpcio).
3. The version of each upstream represented in the file matches the lockfile-resolved version (R-001, R-002), or is reported as "not pinned — skipped" in the skill's per-step output.
4. The local graph component reflects the project's tree as of the most recent `graphify .` invocation (either the skill itself or the post-commit hook).

## Failure modes

- **Network unavailable, upstream not yet cached**: `graphify clone` fails. Skill reports the failing upstream and exits non-zero. `cross-repo.json` is NOT updated; any existing `cross-repo.json` is left in place. (Spec edge case: distinguish "local rebuild succeeded, upstream skipped" from "everything failed.")
- **Lockfile missing AND pyproject.toml missing**: Skill exits non-zero in step 1; `cross-repo.json` not touched.
- **graphify merge-graphs fails**: Skill reports the failure and the underlying exit code. Existing `cross-repo.json` is left in place.

## Stability

The path `<repo>/cross-repo.json` is stable across the M2 lifetime. If a future milestone moves the file (e.g., into `graphify-out/`), the workflow doc, CLAUDE.md, and the refresh skill would all be updated together — the documents are deliberately the only places the path appears, so a path change is a single coordinated edit.
