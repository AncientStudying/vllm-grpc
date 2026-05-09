# Quickstart: Milestone 2 Ground-Truth Workflow

**Feature**: 014-m2-ground-truth-research
**Audience**: a maintainer or contributor who has just pulled the M2 changes and wants to bring `cross-repo.json` up from absent to current.

This is the cold-start procedure. It mirrors the workflow document at the repo root and serves as the **independent test path** for User Stories 1, 3, and 4 in `spec.md`.

---

## Prerequisites

- Python 3.12 environment (the repo's `pyproject.toml` requires `>=3.12,<3.13`).
- `uv` installed: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- Network access for the first build (graphify clones two upstream repos).
- ~1 GB free disk under `~/.graphify/repos/` for the upstream caches.

You do NOT need a GPU for M2. You do NOT need vLLM running. The milestone is documentation + tooling.

---

## Step 1 — Install graphify

```bash
pip install graphifyy           # double-y on the package name
graphify install
```

(Mirrors the workflow doc's "One-time install" section.)

## Step 2 — Bootstrap the project

```bash
git clone <repo-url> vllm-grpc && cd vllm-grpc
make bootstrap                  # installs deps + generates protobuf stubs
```

This is the standard project bootstrap — unchanged by M2.

## Step 3 — Wire up Claude Code's graphify integration

```bash
graphify claude install         # writes graphify section to CLAUDE.md +
                                # PreToolUse hook
graphify hook install           # post-commit / post-checkout auto-rebuild
```

After this step, every `git commit` and `git checkout` triggers a project-graph rebuild via graphify's own hooks (SHA256-cache-aware, so cheap).

## Step 4 — Build `cross-repo.json` for the first time

```bash
/ground-truth-refresh           # the single-invocation skill
```

What you should see (illustrative; exact times vary on first build because both upstream graphs are cold):

```text
vLLM @ 0.20.1 (uv.lock)
grpcio @ 1.80.0 (uv.lock)
building vLLM graph @ 0.20.1 (cold)            ... ok
building grpcio graph @ 1.80.0 (cold)          ... ok
local graph rebuilt
merged → /Users/<user>/projects/vllm-grpc/cross-repo.json
done — 0 rebuilt, 0 skipped, 3 cold (4m12s)
```

(Exact versions track `uv.lock`'s pins for `vllm` and `grpcio`; the ones above were current as of the most recent FR-019b validation pass.)

`cross-repo.json` is now present at the repo root and gitignored.

## Step 5 — Verify with three queries

These verifications correspond to the User Story 1 independent test (spec.md). The query strategy follows the `## Codebase navigation` block in [`CLAUDE.md`](../../CLAUDE.md): cross-repo *paths* go against `cross-repo.json`; repo-specific questions go against the individual upstream graph.

```bash
# (a) cross-repo.json loadable + cross-repo path query
graphify path "ChatServicer" "AsyncLLM" --graph cross-repo.json

# (b) vLLM-internals query — query the vLLM graph directly
graphify query "how does AsyncLLM dispatch generate" \
  --graph ~/.graphify/repos/vllm-project/vllm/graphify-out/graph.json \
  --budget 1500

# (c) grpcio channel-options query — query the targeted Python wrapper graph
#     directly, with concrete identifiers via `path` / `explain` (preferred
#     over natural-language `query` per CLAUDE.md)
graphify path "Channel" "_RPCState" \
  --graph ~/.graphify/repos/grpc/grpc/src/python/grpcio/graphify-out/graph.json

graphify explain "_channel.py" \
  --graph ~/.graphify/repos/grpc/grpc/src/python/grpcio/graphify-out/graph.json
```

Pass criteria:
- (a) `graphify path` returns a multi-hop chain spanning the project + vLLM repos (confirms `cross-repo.json` is loadable AND that the merge connected the three subgraphs).
- (b) returns at least one god node near `LLMEngine`, `AsyncLLM`, scheduler, or model executor (SC-002).
- (c) `path` returns a usable call chain reaching `_RPCState`; `explain "_channel.py"` returns a high-degree god node whose neighbors include `Channel`, the four `*MultiCallable` types, and the rendezvous classes (SC-002).

**Note on the historical recipe.** Earlier drafts of this quickstart suggested running `graphify query "<natural-language question>" --graph cross-repo.json` for (b) and (c). That works for vLLM but is unreliable for grpcio: the merged graph's BFS-from-question expands by edge density, with no provenance weighting, so a ~32× size imbalance between vLLM (~55K nodes) and the targeted grpcio Python wrappers (~1.7K nodes) crowds the smaller subgraph out of the answer. Querying the individual upstream graph removes the imbalance. CLAUDE.md is the canonical reference for which graph to query for which question shape.

## Step 6 — Verify the post-commit hook

```bash
# Use a throwaway untracked file so this works even if you have other
# uncommitted edits — `git reset --hard` would wipe those.
date > .hook-probe && git add .hook-probe && git commit -m "test: post-commit hook"

# Soft reset so the working tree and any unrelated staged work stay intact.
git reset --soft HEAD^ && git restore --staged .hook-probe && rm .hook-probe
```

Inspect `graphify-out/graph.json` — its mtime should reflect the commit you just made and rolled back. (User Story 1 acceptance scenario 4.)

**Why a real file rather than `git commit --allow-empty`:** the post-commit hook short-circuits when `git diff --name-only HEAD~1 HEAD` is empty (`if [ -z "$CHANGED" ]; then exit 0`), so an empty commit will NOT trigger the rebuild. The hook also writes `graph.json` (and `graph.html`, `GRAPH_REPORT.md`) but does NOT write `graphify-out/manifest.json` — check `graph.json`'s mtime, not `manifest.json`'s.

---

## Re-running the refresh skill (the steady-state cadence)

Re-running on an unchanged tree should be cheap:

```bash
/ground-truth-refresh
# vLLM graph cache current @ 0.20.0 — skipped
# grpcio graph cache current @ 1.80.0 — skipped
# local graph cache current — no changed files
# merged → /Users/<user>/projects/vllm-grpc/cross-repo.json
# done — 0 rebuilt, 3 skipped (1.2s)
```

This is User Story 3 acceptance scenario 2 (only-local-changes case is similar — local rebuilds, upstream cache reused).

---

## What changes when `uv.lock` bumps vLLM or grpcio

Imagine `uv.lock` now pins `vllm==0.21.0`:

```bash
/ground-truth-refresh
# vLLM @ 0.21.0 (uv.lock)
# grpcio @ 1.80.0 (uv.lock)
# rebuilding vLLM graph @ 0.21.0 (was 0.20.0)   ... ok
# grpcio graph cache current @ 1.80.0 — skipped
# local graph rebuilt
# merged → /Users/<user>/projects/vllm-grpc/cross-repo.json
# done — 1 rebuilt, 1 skipped, 0 cold (1m48s)
```

This is User Story 1 acceptance scenario 2 and FR-019b in action.

---

## Verifying `make check` is unchanged

```bash
make check
```

Should pass — M2 introduces no Python source, no proto edits, and no test changes (FR-025, SC-006, R-010). If it fails, the failure is unrelated to M2.

---

## Cross-reference checks (User Stories 2 and 4)

A 2-minute read of `docs/PLAN.md` should let a cold reader identify:

1. M1 is delivered, with a pointer to `docs/benchmarks/summary.md`.
2. M2 is the active formalization milestone, linking to `ground-truth-workflow-for-associated-projects.md`.
3. M3 mock-model approach with canonical `hidden_size` 2048 / 4096 / 8192; real model not required.
4. M4 corpus expansion; M5 model expansion that validates M3 against real models.
5. The Phase 1–7 historical content is below a clearly marked boundary.

(SC-003, SC-004.)

A side-by-side read of `README.md` and `docs/PLAN.md` should show the same M2–M5 research questions in both, with no contradictions (FR-024, SC-004).

---

## Failure recoveries

- **`/ground-truth-refresh` reports "graphify not installed"** → `pip install graphifyy && graphify install`, then re-run.
- **`/ground-truth-refresh` reports "not in vllm-grpc working tree"** → `cd` into the repo root, then re-run.
- **vLLM clone fails (network)** → re-run when network is back; the skill leaves any prior `cross-repo.json` in place rather than producing a malformed merge.
- **`vLLM not pinned — skipping`** → either pin vLLM in `pyproject.toml`'s `[project] dependencies` or in `uv.lock`, then re-run. (vLLM is currently loaded via `--with vllm` per the project comment, which is the documented reason it may not be pinned.)
- **`make check` regresses after the docs edits** → the only Python file these edits should touch is none. If a regression appears, it is incidental and should be fixed before merging M2.
