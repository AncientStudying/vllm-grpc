# Ground-Truth Workflow for Associated Projects

Reference document for using Graphify to give Claude Code efficient
navigation across this project (`vllm-grpc`) and its two upstream sources
of truth: [`vllm`](https://github.com/vllm-project/vllm) (the inference
engine) and [`grpcio`](https://github.com/grpc/grpc) (the wire stack).

## Goal

Pre-compile this project plus both upstream codebases into knowledge graphs
so Claude Code consults graph structure (god nodes, call paths, communities)
before falling back to `Glob`/`Grep`. Reduces orientation-token overhead,
especially for questions that span the gRPC/proto layer into vLLM internals
or down into grpcio channel/HTTP/2 mechanics.

The two upstream repos play complementary roles:

- **vLLM** — ground truth for engine, scheduler, model executor, KV cache,
  sampling, worker, and continuous-batching behavior. Use when reasoning
  about how a generate call flows through the engine, or what a vLLM
  parameter actually does end-to-end.
- **grpcio** — ground truth for channel options, HTTP/2 framing,
  `max_message_size` enforcement, keepalive, compression, and streaming
  flow control. Use when reasoning about why a wire-tuning knob behaves
  the way it does — central for the new Milestone 3 (proto + gRPC tuning).

The local `vllm-grpc` repo is the third graph in the merge.

---

## Setup

### One-time install

```bash
pip install graphifyy           # note: double-y on the package name
graphify install
```

### Build the vLLM reference graph

```bash
graphify clone https://github.com/vllm-project/vllm --branch v0.20.0
# Lands at ~/.graphify/repos/vllm-project/vllm/ in detached-HEAD at v0.20.0

graphify update ~/.graphify/repos/vllm-project/vllm
echo "0.20.0" > ~/.graphify/repos/vllm-project/vllm/graphify-out/.target-version.txt
# Produces graphify-out/{graph.json, graph.html, GRAPH_REPORT.md, .target-version.txt}
```

`graphify clone --branch <tag>` lands the clone at the tagged ref in
detached-HEAD state (URL must come first, flags follow); `graphify
update <path>` runs the AST extraction. The `.target-version.txt`
sidecar is what the `/ground-truth-refresh` skill reads to detect drift
on subsequent refreshes — without it, every refresh would treat the
upstream as cold. Pin to whichever vLLM version this project's
`uv.lock` resolves; rebuild only when the lockfile bumps. Stale graphs
on a fast-moving upstream are the main failure mode, and the sidecar is
the single source of truth for "what version is cached."

### Build the grpcio reference graph

```bash
graphify clone https://github.com/grpc/grpc --branch v1.80.0
# Lands at ~/.graphify/repos/grpc/grpc/ in detached-HEAD at v1.80.0

graphify update ~/.graphify/repos/grpc/grpc/src/python/grpcio
echo "1.80.0" > ~/.graphify/repos/grpc/grpc/src/python/grpcio/graphify-out/.target-version.txt
# Produces ~/.graphify/repos/grpc/grpc/src/python/grpcio/graphify-out/
#   {graph.json, graph.html, GRAPH_REPORT.md, .target-version.txt}
```

The sidecar lives inside the **indexed subpath's** `graphify-out/`
(matching where the graph itself lands), not the clone's repo root.
Pin to the grpcio version this project depends on (resolved version in
the project lockfile) and rebuild only on bump.

**Why we target `src/python/grpcio/` rather than the repo root.** grpcio
is a multi-language monorepo. Indexing the whole tree produces ~55,500
nodes — but only ~10% of them are Python wrappers; the rest is C++ core
(55%), C++ tests (12%), Ruby / PHP / Objective-C / C# bindings (6%),
vendored protobuf C runtime (`third_party/upb`, ~3%), and build tooling.
For the M3 wire-tuning surface — channel options, RPC state machinery,
streaming flow control as exposed to Python — that breadth crowds out
the relevant nodes during BFS query expansion. Indexing only
`src/python/grpcio/` produces ~1,700 nodes (97% reduction) covering
`Channel`, `Server`, `_RPCState`, `UnaryUnaryMultiCallable` and friends
cleanly, with no Ruby/PHP/Obj-C noise. Deep C-core (HTTP/2 transport,
completion queues, low-level flow control) is "needs source-level
reading" per the Known gaps section below — graphify wouldn't add value
there even if we did index it.

### Build this project's graph and install the Claude Code integration

```bash
cd ~/path/to/vllm-grpc
graphify claude install   # writes CLAUDE.md directive + PreToolUse hook
graphify .                # build local graph
graphify hook install     # post-commit / post-checkout auto-rebuild
```

### Merge into a cross-repo graph

```bash
graphify merge-graphs \
  ./graphify-out/graph.json \
  ~/.graphify/repos/vllm-project/vllm/graphify-out/graph.json \
  ~/.graphify/repos/grpc/grpc/src/python/grpcio/graphify-out/graph.json \
  --out cross-repo.json
```

(The grpcio source path is the Python wrapper subtree, not the repo
root — see "Build the grpcio reference graph" above.)

Re-run the merge whenever any of the three sides rebuilds — operates on
JSON, fast.

`cross-repo.json` and the project's `graphify-out/` directory are
gitignored: they are locally-built artifacts, rebuilt cheaply via the
`/ground-truth-refresh` skill (see "Rebuild cadence" below). Treat them
as derived state — never commit them, and never rely on a teammate
having the same graph bytes.

### Versions resolved from `uv.lock`

The `/ground-truth-refresh` skill auto-detects the target vLLM and
grpcio versions from `uv.lock` (falling back to `pyproject.toml` only
when the lockfile is unreadable). No manual `--vllm-version` or
`--grpcio-version` arguments are required — refreshes stay in sync
with project dependencies automatically.

The project pins these targets in `pyproject.toml`'s
`[dependency-groups] graph-targets`:

```toml
graph-targets = [
    "grpcio==1.80.0",
    "vllm==0.20.0; sys_platform == 'linux'",
]
```

The `sys_platform == 'linux'` marker on vLLM keeps `uv lock` working on
the M2 dev machine (vLLM 0.20.0 has CUDA-only wheels with no macOS
support); the lockfile still records the pinned version for graphify's
upstream clone.

### Auto-rebuild on lockfile drift

When the lockfile-resolved version differs from the cached upstream
graph's recorded version, the refresh skill automatically rebuilds the
affected upstream and surfaces the rebuild as a per-step entry, e.g.
`rebuilding vLLM graph @ 0.21.0 (was 0.20.0)`. The cache miss is the
expensive step; the merge that follows operates on JSON and is fast.

---

## Querying from Claude Code

The canonical reference for which graph to query for which question shape
is the `## Codebase navigation` block in [`CLAUDE.md`](CLAUDE.md). In
short: cross-repo *path* questions go against `cross-repo.json`;
repo-specific questions go against the individual upstream graph
(`~/.graphify/repos/<owner>/<repo>/graphify-out/graph.json`, or
`.../src/python/grpcio/graphify-out/graph.json` for grpcio); project-local
questions are handled automatically by graphify's PreToolUse hook. See
CLAUDE.md for concrete commands.

---

## Cost shape

| Pass | What it does | Cost |
|------|--------------|------|
| 1. AST extraction | tree-sitter parses code locally | **0 tokens** (CPU only) |
| 2. Audio/video transcription | faster-whisper, local | 0 tokens |
| 3. Semantic extraction | LLM reads docs/PDFs/images | **costs API tokens** |
| `--deep` mode | LLM infers semantic edges across all code | **costs significant tokens** |

**Recommendations for vLLM- and grpcio-scale repos:**
- Skip `--deep` on first build of either upstream. Default AST graph is usually enough.
- Skip docs/PDFs initially unless needed for the question.
- SHA256 cache means rebuilds only re-process changed files.

---

## Known gaps for this project

### CUDA kernels (`.cu` / `.cuh`) — not parsed
Tree-sitter grammar isn't wired in. vLLM's PagedAttention, fused MoE, and
quantization kernels won't appear as nodes. The `.cpp` wrapper layer **is**
parsed, so Python → C++ binding edges still work. Mostly irrelevant for
gRPC-layer work.

### grpcio C-core (`.c` / `.cc`) — partially reachable
Python wrappers and Cython glue layers are parsed; the deep C-core
(HTTP/2 transport, completion queues, low-level flow control) needs
source-level reading. For most M3 wire-tuning questions this is fine —
channel options surface in the Python layer with documented effects.
When framing-level detail matters, read the C-core directly rather than
relying on the graph.

### Protobuf (`.proto`) — not parsed
This is the bigger gap for vllm-grpc:
- `.proto` files contribute no structural edges to the graph.
- Generated `_pb2.py` / `_pb2_grpc.py` **are** parsed (they're Python), so
  edges into and out of generated code work — just not back to the source.
- **Workaround:** keep a short `proto/README.md` describing the service
  surface in prose. Pass 3 semantic extraction will pull that in as a doc
  node and link it to nearby code.

---

## CLAUDE.md additions

After `graphify claude install` writes its section, append this directive:

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

---

## Rebuild cadence

| Trigger | Action |
|---------|--------|
| Local commit / branch switch | Auto-handled by `graphify hook install` |
| `git pull` on a clone | `/ground-truth-refresh` (cheap when nothing drifted; the SHA256 cache is honored) |
| vLLM dependency bump in this project | `/ground-truth-refresh` (skill detects the lockfile drift and rebuilds the vLLM graph automatically) |
| grpcio dependency bump in this project | `/ground-truth-refresh` (same — skill auto-rebuilds the grpcio graph on drift) |
| Substantial local refactor | `/ground-truth-refresh` (verify the hook fired; the skill is the recovery path if it didn't) |

---

## Health check before committing to the workflow

1. Build only the vLLM graph in default mode.
2. Open `~/.graphify/repos/vllm-project/vllm/graphify-out/graph.html` in a
   browser.
3. Look at the god nodes (top-connected). If they match intuition for
   vLLM's architecture (engine, scheduler, model_executor, worker,
   sampler) the graph will be useful.
4. Repeat for grpcio. Expect god nodes around `Channel`, `Server`,
   `_channel`, `_server`, plus the cython glue layer.
5. If they look noisy or surprising, decide whether `--deep` is worth the
   API cost before committing to it.

---

## References

- Graphify repo: https://github.com/safishamsi/graphify
- Claude Code integration page: https://graphify.net/graphify-claude-code-integration.html
- vLLM repo: https://github.com/vllm-project/vllm
- grpcio repo: https://github.com/grpc/grpc
- Tracking issues: native MCP integration (#146), behavior on small repos (#580)
