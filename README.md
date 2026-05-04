# vllm-grpc

A Protobuf/gRPC frontend for vLLM that demonstrates wire-size and protocol overhead tradeoffs for LLM inference. The core thesis: replacing the OpenAI JSON wire format with protobuf-over-gRPC reduces response size by up to 89% for chat completions and 25% for embed request payloads.

---

## What is this?

vLLM's default interface is an OpenAI-compatible REST API. JSON is human-readable but verbose: a typical chat completion response is 611 bytes of JSON wrapping ~10 tokens of actual text. Protobuf encodes the same response in 65 bytes.

This project builds a gRPC frontend that sits in front of vLLM and exposes a proto-defined `ChatService` and `CompletionsService`. It then measures the wire overhead across three access paths:

1. **REST via proxy** — the mainstream path; any OpenAI client just works
2. **gRPC via proxy** — REST client → proxy → gRPC frontend (same client, adds proxy RTT)
3. **gRPC-direct** — `VllmGrpcClient` speaks proto directly to the frontend, no proxy

The project is a structured measurement exercise, not a production system. Every phase commits benchmark JSON to `docs/benchmarks/` so results are reproducible.

---

## Three Access Paths

```
                          ┌──────────────────────┐
REST client ────────────► │                      │
                          │   gRPC proxy (:8000) │ ──► gRPC frontend (:50051) ──► vLLM
OpenAI SDK  ────────────► │   (FastAPI)          │
                          └──────────────────────┘

VllmGrpcClient ─────────────────────────────────► gRPC frontend (:50051) ──► vLLM
```

| Path | Client | Wire format | Proxy hop | When to use |
|------|--------|-------------|-----------|-------------|
| REST via proxy | curl, openai SDK | JSON | Yes | Drop-in for any existing OpenAI client |
| gRPC via proxy | same REST clients | JSON → gRPC (proxy translates) | Yes | Baseline comparison for proxy overhead |
| gRPC-direct | `VllmGrpcClient` | Protobuf | No | Smallest wire size; measures protocol overhead without proxy |

The **gRPC-direct** path is where the wire-size thesis is tested: it removes the proxy and sends raw proto bytes, isolating the protocol difference from the proxy overhead.

---

## Prerequisites

- macOS (M2/M3) or Linux x86-64
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `make` — macOS: `xcode-select --install`; Linux: pre-installed
- A running vLLM-compatible model (the gRPC frontend loads it via `MODEL_NAME`)

For GPU benchmarks on Modal: a Modal account with `modal token new`.

---

## Quick Start

```bash
# 1. Clone and bootstrap
git clone <repo-url> vllm-grpc && cd vllm-grpc
make bootstrap          # install deps + generate protobuf stubs

# 2. Start the gRPC frontend (terminal 1 — requires a GPU or CPU-only vLLM)
make run-frontend       # listens on :50051

# 3. Start the REST proxy (terminal 2)
make run-proxy          # listens on :8000

# 4. Run demo scripts
bash demo/curl-rest.sh                 # REST via curl
uv run python demo/openai-sdk.py       # REST via openai SDK
uv run python demo/grpc-direct.py      # gRPC-direct (no proxy)
uv run python demo/streaming.py        # streaming SSE via proxy
```

Each demo script reads an environment variable for the endpoint address:

| Script | Variable | Default |
|--------|----------|---------|
| `demo/curl-rest.sh` | `PROXY_BASE_URL` | `http://localhost:8000` |
| `demo/openai-sdk.py` | `PROXY_BASE_URL` | `http://localhost:8000/v1` |
| `demo/grpc-direct.py` | `FRONTEND_ADDR` | `localhost:50051` |
| `demo/streaming.py` | `PROXY_BASE_URL` | `http://localhost:8000/v1` |

---

## Benchmark Headlines

All runs on Modal A10G GPU, vLLM 0.20.0, model `Qwen/Qwen3-0.6B`. Full numbers and methodology in [`docs/benchmarks/summary.md`](docs/benchmarks/summary.md).

**Wire size** is where gRPC-direct wins cleanly and structurally: chat completion response bytes drop from 611 B (REST JSON) to 65 B (gRPC proto) — an 89% reduction. Embed request payloads drop 25% because gRPC transmits raw tensor bytes while REST base64-encodes them. **Latency** is more nuanced: at c=1, gRPC-direct adds ~35% latency over REST (35 ms) due to channel setup, while gRPC-proxy adds ~215% because of the local-to-Modal tunnel hop. At c=8, all three paths converge as the model's inference queue dominates. The honest summary: gRPC is the right choice when you need compact wire representation; REST remains the latency leader at low concurrency.

---

## Roadmap

### Milestone 1 — Foundation (current release)

Three access paths (REST via proxy, gRPC via proxy, gRPC-direct) implemented and benchmarked end-to-end on Modal A10G. Headline finding: gRPC-direct reduces response bytes by **89%** for chat completions and **25%** for embed request payloads. See [`docs/benchmarks/summary.md`](docs/benchmarks/summary.md) for full numbers and methodology.

### Milestone 2 — Parameter Tuning

Investigate whether adjusting vLLM serving parameters and grpcio channel settings materially changes the latency or throughput story measured in Milestone 1.

- Does increasing the grpcio max message size reduce latency for large embed payloads?
- Does vLLM's continuous batching interact differently with gRPC streaming vs REST SSE?
- What channel configuration minimises TTFT at high concurrency?

### Milestone 3 — Corpus Expansion

Re-run all three access paths against a larger, more varied prompt corpus covering short and long prompts, multi-turn conversations, and domain-specific content (code, structured data). Determine whether the Milestone 1 wire-size and latency findings hold across input diversity.

- Do wire-size deltas change with longer prompts or multi-turn context windows?
- Does streaming TPOT variance increase with structurally different prompt types?

### Milestone 4 — Model Expansion

Repeat the Milestone 1 and 2 benchmarks with at least two additional models of different sizes and architecture families. Determine whether the wire-overhead thesis is model-agnostic or depends on tokeniser and output characteristics.

- Does a larger model (7B+) shift the latency story relative to wire-size gains?
- Do models with different default output lengths change the response-byte delta?

---

## Development Commands

```bash
make bootstrap          # Install deps + generate proto stubs (run after clone)
make proto              # Regenerate protobuf stubs only
make lint               # ruff check + format check
make typecheck          # mypy --strict
make test               # pytest
make check              # lint + typecheck + test (CI gate)
make run-frontend       # Start gRPC server on :50051
make run-proxy          # Start REST proxy on :8000
make bench              # Head-to-head benchmark (requires proxy + native servers running)
make bench-ci           # Benchmark smoke test with stub servers (no live model needed)
make bench-modal        # Full A10G benchmark run on Modal (requires Modal token + weights)
make regen-bench-reports  # Regenerate docs/benchmarks/*.md from committed JSON files
make download-weights   # Download model weights to Modal volume
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXY_PORT` | `8000` | REST proxy listen port |
| `FRONTEND_PORT` | `50051` | gRPC frontend listen port |
| `FRONTEND_ADDR` | `localhost:50051` | Proxy → frontend address |
| `MODEL_NAME` | `Qwen/Qwen3-0.6B` | Model loaded by the frontend |
| `PROXY_BASE_URL` | `http://localhost:8000` | Base URL used by demo scripts |

---

## Repository Structure

```
proto/                         # Protobuf source of truth
  vllm_grpc/v1/
    health.proto               # Health.Ping RPC
    chat.proto                 # ChatService: Complete + CompleteStream
    completions.proto          # CompletionsService: Complete + CompleteStream (prompt embeds)

packages/
  gen/                         # Generated stubs (built by make proto, not committed)
  proxy/                       # FastAPI REST proxy → gRPC translator
  frontend/                    # grpc.aio gRPC server (ChatService + CompletionsService)
  client/                      # VllmGrpcClient: Python gRPC-direct client library

demo/                          # Annotated runnable examples (all four access paths)
  curl-rest.sh                 # REST via curl
  openai-sdk.py                # REST via openai SDK
  grpc-direct.py               # gRPC-direct via VllmGrpcClient
  streaming.py                 # Streaming SSE via proxy

tools/benchmark/               # Benchmark harness (vllm_grpc_bench package)

scripts/
  curl/                        # curl one-liners
  python/
    bench_modal.py             # Modal A10G orchestration (Phase 3–6 benchmark runs)
    regen_bench_reports.py     # Regenerate .md reports from committed JSON

tests/integration/             # End-to-end bridge tests (no GPU required)

docs/
  PLAN.md                      # Project plan and phase roadmap
  decisions/                   # Architecture decision records
  benchmarks/                  # Committed benchmark JSON + generated comparison reports
    summary.md                 # Headline numbers across all phases

specs/                         # spec-kit planning artifacts (per-phase)
```

---

## CI

GitHub Actions runs on every push and PR to `main`:

- **ci.yml** — lint (`ruff`), type-check (`mypy --strict`), tests (`pytest`)
- **proto.yml** — verifies committed stubs match proto sources (`make proto` + `git diff --exit-code`)
