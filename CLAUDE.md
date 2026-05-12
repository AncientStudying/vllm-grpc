<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
at specs/018-m5-1-rest-vs-grpc/plan.md
<!-- SPECKIT END -->

## Codebase navigation

Three graphs are wired into this project; pick by **question shape**, not by repo:

- **Cross-repo path questions** — "how does a proxy request flow from FastAPI
  through gRPC into `AsyncLLM.generate`?" or "what's the call chain from
  `ChatServicer` down to the sampler?". Query `cross-repo.json` with
  `graphify path` between identifiers in *different* repos:
    - `graphify path "ChatServicer" "AsyncLLM" --graph cross-repo.json`
    - `graphify path "CompletionsServicer" "Sampler" --graph cross-repo.json`

- **vLLM-only questions** (engine, scheduler, model executor, KV cache,
  sampling, worker, continuous batching). Query the vLLM graph directly —
  vLLM's source tree is domain-tight, so natural-language `graphify query`
  works cleanly:
    - `graphify query "how does AsyncLLM dispatch generate" --graph ~/.graphify/repos/vllm-project/vllm/graphify-out/graph.json --budget 1500`
    - `graphify explain "AsyncLLM" --graph ~/.graphify/repos/vllm-project/vllm/graphify-out/graph.json`

- **grpcio-only questions** (channel options, `max_message_size`, keepalive,
  compression, HTTP/2 framing exposed to Python, streaming flow control).
  Query the targeted Python-wrapper graph directly. Prefer
  `graphify path` / `graphify explain` with concrete identifiers
  (`Channel`, `_channel.py`, `_RPCState`, `Server`,
  `UnaryUnaryMultiCallable`) over natural-language `graphify query` — even
  on the targeted graph, BFS-from-question can drift into setup scripts:
    - `graphify path "Channel" "_RPCState" --graph ~/.graphify/repos/grpc/grpc/src/python/grpcio/graphify-out/graph.json`
    - `graphify explain "_channel.py" --graph ~/.graphify/repos/grpc/grpc/src/python/grpcio/graphify-out/graph.json`
    - For deep grpcio C-core (HTTP/2 transport, completion queues, low-level
      flow control), read source under `~/.graphify/repos/grpc/grpc/src/core/`
      directly — the graph doesn't index it.

- **Project-internal questions** (proto + proxy + frontend + client wiring).
  The local `graphify-out/graph.json` is sufficient and the PreToolUse hook
  consults it automatically — no explicit `/graphify query` needed.

- **`.proto` definitions** are NOT in any graph. Read the relevant file in
  `proto/` directly.

**Why query a single-repo graph instead of `cross-repo.json` for repo-specific
questions?** vLLM is ~55K nodes; targeted grpcio Python wrappers are ~1.7K
nodes. In the merged graph, BFS-from-question expands by edge density, so
questions about the smaller subgraph get crowded out by the larger one.
Pointing `--graph` at the individual upstream removes that imbalance.
Reserve `cross-repo.json` for the cross-repo *paths* it was built for.

## Keeping the cross-repo graph current

If `cross-repo.json` is suspected stale (lockfile bumped, upstream pulled,
substantial local refactor), run `/ground-truth-refresh` rather than
running graphify commands by hand. The skill auto-detects target versions
from `uv.lock` (falling back to `pyproject.toml`), surfaces per-step
progress, and reuses graphify's SHA256 cache so re-invocation on an
unchanged tree is cheap. See
`ground-truth-workflow-for-associated-projects.md` for the underlying
commands and rebuild cadence.

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
