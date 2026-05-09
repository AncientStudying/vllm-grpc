# Contract: Refresh Skill Command Surface

**Feature**: 014-m2-ground-truth-research
**Contract type**: Slash-command interface exposed by Claude Code at the user's terminal.

This contract documents what the project promises to maintainers and contributors who invoke the ground-truth-refresh skill from Claude Code. It is the public surface; the underlying graphify command sequence is an implementation detail and may evolve.

---

## Command name

```text
/ground-truth-refresh
```

Resolves to `.claude/skills/ground-truth-refresh/SKILL.md`. The slash-command name maps directly from the directory name, matching the existing `/speckit-*` pattern in this repository.

## Arguments

None required for M2. The skill takes no arguments. (Future expansion — e.g., `--target=local|vllm|grpcio` — is explicitly out of scope per Phase 0 R-003.)

## Preconditions

The skill enforces these and reports actionably when they are not met:

1. **Working directory is the vllm-grpc repository.** Detected by reading `./pyproject.toml` and confirming `[project] name == "vllm-grpc"`. (R-004)
2. **graphify CLI is installed.** Detected by `command -v graphify`. (R-005)
3. **Lockfile is readable.** `uv.lock` is preferred; `pyproject.toml` is the fallback. Both being unreadable is a failure with an actionable message. (R-001)

If any precondition fails, the skill exits non-zero with a single-paragraph message that names the missing prerequisite and the recovery action. Raw shell errors (`command not found`, `No such file or directory`) MUST NOT be the visible output.

## Behavior (the contract)

On a successful invocation, the skill performs these steps in order, surfacing each as a discrete entry in its output:

1. **Resolve target versions** — emit either `vLLM @ <version> (uv.lock)` or `vLLM not pinned — skipping`; same for grpcio. (FR-019a)
2. **Refresh upstream graphs** — for each upstream, emit one of:
   - `vLLM graph cache current @ 0.20.0 — skipped`
   - `rebuilding vLLM graph @ 0.21.0 (was 0.20.0)` (FR-019b)
   - `building vLLM graph @ 0.20.0 (cold)` (first build for this upstream)
   - `vLLM not pinned — skipping`
3. **Refresh project local graph** — emit `local graph rebuilt` or `local graph cache current — no changed files`.
4. **Merge** — emit `merged → /<absolute path>/cross-repo.json` on success.
5. **Final status** — single line summarizing per-step outcomes, e.g., `done — 3 rebuilt, 1 skipped, 1 cold (12.4s)`.

Failure of any step MUST be reported with the failing step named, the underlying graphify exit code, and a suggested next step (e.g., "Run `graphify clone https://github.com/vllm-project/vllm` manually to inspect the failure.").

## Outputs

- **stdout**: per-step entries (one line each) plus the final status line. Human-readable.
- **side effect**: `<repo>/cross-repo.json` exists and is readable by `graphify query`.
- **exit code**: 0 on success, non-zero on any precondition or step failure.

## Idempotency

Re-invoking the skill on an unchanged tree MUST be substantially faster than a cold first build (FR-019, SC-009). The expected output on a no-op refresh is:

```text
vLLM graph cache current @ 0.20.0 — skipped
grpcio graph cache current @ 1.80.0 — skipped
local graph cache current — no changed files
merged → /Users/<user>/projects/vllm-grpc/cross-repo.json
done — 0 rebuilt, 3 skipped (1.2s)
```

(Times illustrative.)

## What the skill explicitly does NOT do

- Does not install graphify (R-005). The user is responsible for `pip install graphifyy && graphify install` once.
- Does not update `uv.lock` or `pyproject.toml`. Version resolution is read-only.
- Does not push, commit, or otherwise mutate git state.
- Does not run `--deep` mode (workflow doc recommends starting without it; spec.md §Assumptions confirms `--deep` is opt-in and out of scope for M2).
- Does not try to graph CUDA kernels or grpcio C-core (the workflow doc names these as known gaps).
- Does not consult `cross-repo.json` itself — it produces `cross-repo.json`. Querying belongs to `/graphify query` and the PreToolUse hook.

## Compatibility

The skill works on macOS and Linux developer workstations. It does not run in CI. Spec assumption: "The project's CI does not need to depend on `cross-repo.json`."
