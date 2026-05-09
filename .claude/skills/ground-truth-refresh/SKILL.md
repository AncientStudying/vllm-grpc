---
name: "ground-truth-refresh"
description: "Rebuild the project, vLLM, and grpcio knowledge graphs and merge them into cross-repo.json. Auto-detects vLLM and grpcio versions from uv.lock (falling back to pyproject.toml). Honors graphify's SHA256 cache so re-invocation on an unchanged tree is cheap; auto-rebuilds upstream graphs when the lockfile pin diverges from the cached version."
compatibility: "Requires the graphify CLI on PATH (pip install graphifyy && graphify install). Run from the repo root of vllm-grpc."
metadata:
  author: "vllm-grpc"
  source: "specs/014-m2-ground-truth-research/contracts/skill-commands.md"
user-invocable: true
disable-model-invocation: false
---

## Purpose

Refresh the cross-repo knowledge graph that powers vLLM-internals and
grpcio-channel queries. This is the canonical staleness recovery path
named in `CLAUDE.md` and in the **Rebuild cadence** table of
`ground-truth-workflow-for-associated-projects.md`. One invocation drives
the documented sequence end-to-end:

1. Verify working directory is the `vllm-grpc` repo.
2. Verify `graphify` is on PATH.
3. Resolve target vLLM and grpcio versions from `uv.lock` (fall back to
   `pyproject.toml`).
4. Per-upstream drift check vs the cached graph's manifest; auto-rebuild
   on drift.
5. Refresh the project local graph (`graphify .`).
6. Merge the three graphs into `cross-repo.json`.
7. Print a final status block including the absolute path to
   `cross-repo.json`.

## Outline

Execute these steps in order. Surface each step as a discrete entry on
stdout (one line per outcome). On any precondition or step failure, exit
non-zero with an actionable message — do not let raw shell errors
(`command not found`, `No such file or directory`) be the visible output.

### Step 1 — Verify working directory

Run from the repo root:

```bash
test -f ./pyproject.toml && python3 -c \
  'import tomllib,sys;d=tomllib.load(open("pyproject.toml","rb"));sys.exit(0 if d.get("project",{}).get("name")=="vllm-grpc" else 1)'
```

(`tomllib` is in the Python 3.11+ standard library; the project requires
Python 3.12 per `pyproject.toml`.)

If the check fails (file missing OR `[project] name != "vllm-grpc"`),
emit and exit non-zero:

```text
Refusing to refresh: not in the vllm-grpc working tree (expected
pyproject.toml with name=vllm-grpc). cd to the repo root and re-run.
```

### Step 2 — Verify graphify is installed

```bash
command -v graphify >/dev/null 2>&1
```

If absent, emit and exit non-zero:

```text
graphify not installed. Run:
  pip install graphifyy && graphify install
See `ground-truth-workflow-for-associated-projects.md` §Setup for the
broader install context (Claude Code integration, post-commit hook).
```

### Step 3 — Resolve target versions from `uv.lock`

Parse `uv.lock` for the `vllm` and `grpcio` package entries. The lockfile
records the version that the project's `[dependency-groups] graph-targets`
group pins (FR-019c — `pyproject.toml` carries
`grpcio==1.80.0` and `vllm==0.20.0; sys_platform == 'linux'`).

For each target, emit one of:

```text
vLLM @ 0.20.0 (uv.lock)
grpcio @ 1.80.0 (uv.lock)
```

If `uv.lock` is unreadable, fall back to reading the lower bound from
`pyproject.toml`'s `[dependency-groups] graph-targets` and emit:

```text
vLLM @ 0.20.0 (pyproject.toml fallback)
grpcio @ 1.80.0 (pyproject.toml fallback)
```

If the package is pinned in **neither** `uv.lock` **nor**
`pyproject.toml`'s `graph-targets` group, emit:

```text
vLLM not pinned in lockfile or pyproject — skipping vLLM upstream graph.
Recovery: add `vllm==<version>` to [dependency-groups] graph-targets in
pyproject.toml, run `uv lock`, then re-invoke /ground-truth-refresh.
```

(Same shape for grpcio if it goes missing.) After a normal-state setup
this branch is a recovery path, not the default.

### Step 4 — Per-upstream drift check + auto-rebuild

For each resolved upstream (`vllm-project/vllm`, `grpc/grpc`):

1. Read the **cached version** from the sidecar file
   `~/.graphify/repos/<owner>/<repo>[/<subpath>]/graphify-out/.target-version.txt`.
   If absent, treat as no cache (cold).
2. Compare against the lockfile-resolved version from Step 3.

Emit one of:

- `vLLM graph cache current @ 0.20.0 — skipped` (sidecar matches)
- `building vLLM graph @ 0.20.0 (cold)` (no sidecar — first build)
- `rebuilding vLLM graph @ 0.21.0 (was 0.20.0)` (sidecar disagrees with lockfile)

vLLM is indexed from the repo root because its source tree is already
domain-tight (every node under `vllm/` is on-thesis). grpcio is a
multi-language monorepo (~55K nodes total: 55% C++ core, 12% C++ tests,
6% Ruby/PHP/Objective-C/C# bindings, only ~10% Python wrappers), so the
skill indexes only the Python wrapper subtree at `src/python/grpcio/`
(~1.7K nodes, 97% reduction). Channel options, RPC state machinery, and
the Python-side wire surface all live there; deep C-core (HTTP/2
framing, completion queues) is read at source per the workflow doc's
"Known gaps" section.

**Cold path** — clone at the resolved tag in one step. `graphify clone`
requires the URL first, then flags. Tag-format fallback: try
`v<version>` first; if `graphify clone --branch v<version>` fails, fall
back to a plain clone followed by `git -C <clone> fetch origin tag
<version> && git -C <clone> checkout <version>` for upstreams that
don't use the `v` prefix.

```bash
# vLLM (whole repo indexed)
graphify clone https://github.com/vllm-project/vllm --branch v0.20.0
graphify update ~/.graphify/repos/vllm-project/vllm
echo "0.20.0" > ~/.graphify/repos/vllm-project/vllm/graphify-out/.target-version.txt

# grpcio (Python wrapper subtree indexed)
graphify clone https://github.com/grpc/grpc --branch v1.80.0
graphify update ~/.graphify/repos/grpc/grpc/src/python/grpcio
echo "1.80.0" > ~/.graphify/repos/grpc/grpc/src/python/grpcio/graphify-out/.target-version.txt
```

The sidecar lives **inside the indexed subpath's `graphify-out/`** so
vLLM (parent = subpath) and grpcio (parent ≠ subpath) follow the same
rule.

**Drift path** — fetch the new tag in the existing clone, check out,
re-extract, update the sidecar:

```bash
# vLLM drift example: 0.20.0 → 0.20.2
git -C ~/.graphify/repos/vllm-project/vllm fetch origin tag v0.20.2 --no-tags
git -C ~/.graphify/repos/vllm-project/vllm checkout v0.20.2 \
  || git -C ~/.graphify/repos/vllm-project/vllm checkout 0.20.2
graphify update ~/.graphify/repos/vllm-project/vllm
echo "0.20.2" > ~/.graphify/repos/vllm-project/vllm/graphify-out/.target-version.txt

# grpcio drift example: 1.80.0 → 1.80.2 (same shape, indexed subpath)
git -C ~/.graphify/repos/grpc/grpc fetch origin tag v1.80.2 --no-tags
git -C ~/.graphify/repos/grpc/grpc checkout v1.80.2 \
  || git -C ~/.graphify/repos/grpc/grpc checkout 1.80.2
graphify update ~/.graphify/repos/grpc/grpc/src/python/grpcio
echo "1.80.2" > ~/.graphify/repos/grpc/grpc/src/python/grpcio/graphify-out/.target-version.txt
```

The SHA256 cache keeps re-extraction cheap for files unchanged between
versions; only post-tag-diff files re-extract.

**Edge case — graphify's "refusing to overwrite" guardrail.** If
`graphify update` reports `new graph has N nodes but existing graph.json
has M. Refusing to overwrite — you may be missing chunk files from a
previous session.`, the existing graph.json was built against a
significantly different ref (e.g. main HEAD vs a release tag). Recovery:
delete the stale `graphify-out/graph.json` and re-run `graphify update`.
Skill emits this as `<repo> graph cache stale (size mismatch) — purging
and rebuilding @ <version>`.

### Step 5 — Refresh the project local graph

```bash
graphify .
```

Emit one of:

- `local graph rebuilt`
- `local graph cache current — no changed files`

### Step 6 — Merge into `cross-repo.json`

```bash
graphify merge-graphs \
  ./graphify-out/graph.json \
  ~/.graphify/repos/vllm-project/vllm/graphify-out/graph.json \
  ~/.graphify/repos/grpc/grpc/src/python/grpcio/graphify-out/graph.json \
  --out cross-repo.json
```

The grpcio path points at the Python wrapper subtree's
`graphify-out/`, not the repo root's — see Step 4 for why grpcio is
indexed at `src/python/grpcio/` instead of the whole repo.

If a target was reported `not pinned — skipping` in Step 3, omit that
graph from the merge command and note its absence in the final status.

On success emit:

```text
merged → /Users/<user>/projects/vllm-grpc/cross-repo.json
```

(The path MUST be absolute so the user can copy/paste it.)

### Step 7 — Final status block

Single line summarizing per-step outcomes:

```text
done — 1 rebuilt, 1 skipped, 0 cold (1m48s)
```

Counts: `rebuilt` (drift-driven), `skipped` (cache current), `cold`
(no prior cache).

## Failure handling (FR-020)

If Step 4 fails (network unavailable for `graphify clone`, or
`graphify update` exits non-zero), report the failing upstream, the
underlying graphify exit code, and a suggested next step:

```text
Failed: rebuilding grpcio graph @ 1.81.0 (was 1.80.0). graphify exit 2.
Try `graphify clone https://github.com/grpc/grpc` manually to inspect.
Existing cross-repo.json (if any) was left untouched.
```

If Step 6 (`merge-graphs`) fails, leave any prior `cross-repo.json` in
place rather than emit a malformed merge.

## What this skill explicitly does NOT do

- Does not install graphify. The user installs it once via the workflow
  doc's setup step.
- Does not edit `uv.lock` or `pyproject.toml`. Version resolution is
  read-only.
- Does not run `--deep` mode. The default AST graph is enough for M2;
  see `ground-truth-workflow-for-associated-projects.md` §Cost shape.
- Does not commit, push, or otherwise mutate git state.
- Does not consult `cross-repo.json` itself — it produces it. Querying
  belongs to `/graphify query` and the PreToolUse hook.

## References

- Spec: `specs/014-m2-ground-truth-research/spec.md`
- Workflow doc: `ground-truth-workflow-for-associated-projects.md`
- Contract: `specs/014-m2-ground-truth-research/contracts/skill-commands.md`
- Behavior in detail: `specs/014-m2-ground-truth-research/data-model.md` §7
