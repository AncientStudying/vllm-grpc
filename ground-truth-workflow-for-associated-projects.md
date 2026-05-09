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
graphify clone https://github.com/vllm-project/vllm
# Lands at ~/.graphify/repos/vllm-project/vllm/
# Produces graphify-out/{graph.json, graph.html, GRAPH_REPORT.md}
```

Pin to whichever vLLM version this project depends on; only rebuild when
the dependency bumps. Stale graphs on a fast-moving upstream are the main
failure mode.

### Build the grpcio reference graph

```bash
graphify clone https://github.com/grpc/grpc
# Lands at ~/.graphify/repos/grpc/grpc/
# Produces graphify-out/{graph.json, graph.html, GRAPH_REPORT.md}
```

Pin to the grpcio version this project depends on (resolved version in the
project lockfile) and rebuild only on bump. The grpcio repo is large but
most M3-relevant code lives in the Python wrappers
(`src/python/grpcio/`) plus the channel-options and HTTP/2 layers in
C-core; AST extraction handles the Python side cleanly.

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
  ~/.graphify/repos/grpc/grpc/graphify-out/graph.json \
  --out cross-repo.json
```

Re-run the merge whenever any of the three sides rebuilds — operates on
JSON, fast.

---

## Querying from Claude Code

```bash
# Semantic query against the merged graph, capped at 1500 tokens
/graphify query "how vLLM dispatches a generate request to the engine" \
  --graph cross-repo.json --budget 1500

# Channel-side wire question (M3 territory)
/graphify query "how grpcio enforces max_message_size on streaming responses" \
  --graph cross-repo.json --budget 1500

# Shortest path between two concepts (great for wiring gRPC → vLLM internals)
/graphify path "GrpcServer" "LLMEngine" --graph cross-repo.json

# Plain-language explanation of a node
/graphify explain "AsyncLLMEngine" --graph cross-repo.json
```

For local-only questions (this project's own gRPC/proto layer), the
PreToolUse hook handles it automatically — no explicit `/graphify` command
needed.

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
| `git pull` on a clone | Manual `graphify .` (cheap with cache) |
| vLLM dependency bump in this project | Rebuild vLLM graph + re-merge |
| grpcio dependency bump in this project | Rebuild grpcio graph + re-merge |
| Substantial local refactor | Verify hook fired; if not, manual rebuild |

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
