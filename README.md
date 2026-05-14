# vllm-grpc

A Protobuf/gRPC frontend for vLLM that measures wire-size and protocol-overhead tradeoffs for LLM inference. The core thesis: replacing the OpenAI JSON wire format with protobuf-over-gRPC reduces response size by up to 89% for chat completions and 25% for embed request payloads.

---

## What is this?

vLLM's default interface is an OpenAI-compatible REST API. JSON is human-readable but verbose: a typical chat completion response is 611 bytes of JSON wrapping ~10 tokens of actual text. Protobuf encodes the same response in 65 bytes.

This project builds a gRPC frontend that sits in front of vLLM and exposes a proto-defined `ChatService` and `CompletionsService`. It measures wire overhead across three access paths and commits benchmark JSON to `docs/benchmarks/` so results are reproducible. It is a structured measurement exercise, not a production system.

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
| REST via proxy | curl, openai SDK | JSON | Yes | Drop-in for any OpenAI client |
| gRPC via proxy | same REST clients | JSON → gRPC (proxy translates) | Yes | Baseline for proxy overhead |
| gRPC-direct | `VllmGrpcClient` | Protobuf | No | Smallest wire size; isolates protocol overhead |

The gRPC-direct path is where the wire-size thesis is tested: raw proto bytes, no proxy.

---

## Prerequisites

- macOS (M2/M3) or Linux x86-64
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `make` — macOS: `xcode-select --install`; Linux: pre-installed
- A vLLM-compatible model (the frontend loads it via `MODEL_NAME`)
- For Modal GPU benchmarks: `modal token new`

---

## Quick Start

```bash
git clone <repo-url> vllm-grpc && cd vllm-grpc
make bootstrap                              # install deps + generate proto stubs
make run-frontend                           # terminal 1 — gRPC server on :50051
make run-proxy                              # terminal 2 — REST proxy on :8000

# Demo scripts (any terminal)
bash demo/curl-rest.sh                      # REST via curl
uv run python demo/openai-sdk.py            # REST via openai SDK
uv run python demo/grpc-direct.py           # gRPC-direct (no proxy)
uv run python demo/streaming.py             # streaming SSE via proxy
```

Each demo reads an environment variable for the endpoint:

| Script | Variable | Default |
|--------|----------|---------|
| `demo/curl-rest.sh` | `PROXY_BASE_URL` | `http://localhost:8000` |
| `demo/openai-sdk.py` | `PROXY_BASE_URL` | `http://localhost:8000/v1` |
| `demo/grpc-direct.py` | `FRONTEND_ADDR` | `localhost:50051` |
| `demo/streaming.py` | `PROXY_BASE_URL` | `http://localhost:8000/v1` |

---

## Benchmark Headlines

The structural, topology-immune wins from M1 (Modal A10G, vLLM 0.20.0, `Qwen/Qwen3-0.6B`): gRPC-direct cuts chat completion response bytes by **89%** (611 B → 65 B) and embed request bytes by **25%** (raw float32 vs base64 JSON). Latency results vary by deployment topology — same-fabric (M5.1) vs managed-edge-provider (M5.2) findings apply to different audiences. See [`ANALYSIS.md`](ANALYSIS.md) for the per-milestone narrative, the topology guide, and CI-bounded numbers under each network shape.

---

## Roadmap

Milestone-by-milestone findings live in [`ANALYSIS.md`](ANALYSIS.md); per-milestone benchmark reports under [`docs/benchmarks/`](docs/benchmarks/) are the source-data record.

- **M1** — Three access paths benchmarked on Modal A10G; 89% chat / 25% embed wire-size wins. [`ANALYSIS.md § M1`](ANALYSIS.md#m1--foundation).
- **M2** — Cross-repo ground-truth research practice formalised (vLLM + grpcio). [`ANALYSIS.md § M2`](ANALYSIS.md#m2--cross-repo-ground-truth-research).
- **M3** — Four-axis channel sweep at canonical embed widths; bytes uniformly `no_winner`, time axis surfaced 4 wins (PR #17, PR #19). [`ANALYSIS.md § M3`](ANALYSIS.md#m3--protobuf--grpc-tuning).
- **M4** — Time-axis harness redesign + definitive sweep; `max-msg-16mib` recommend at `embed/h=2048`. [`ANALYSIS.md § M4`](ANALYSIS.md#m4--time-axis-channel--schema-tuning).
- **M5** — Cross-host re-run resolved M4's loopback caveat; 5 channel-config wins at `embed/h=2048` (-23% to -25%). [`ANALYSIS.md § M5`](ANALYSIS.md#m5--cross-host-time-axis-validation).
- **M5.1** — REST vs gRPC head-to-head on the **same-fabric** topology (enterprise/homelab audience). [`ANALYSIS.md § M5.1`](ANALYSIS.md#m51--rest-vs-grpc-head-to-head-on-real-wire).
- **M5.2** — REST vs gRPC across HTTPS-edge and plain-TCP; **managed-edge-provider** topology (hobbyist tenant audience). [`ANALYSIS.md § M5.2`](ANALYSIS.md#m52--rest-transport-path--grpc-tuning-surface).
- **M6** — Corpus expansion (upcoming): longer prompts, multi-turn, domain-specific content.
- **M7** — Model expansion (upcoming): real vLLM re-validation on multiple model sizes.

The [Topology guide](ANALYSIS.md#topology-guide--which-milestone-result-applies-to-your-deployment) in `ANALYSIS.md` names which M5-era milestone applies to which deployment shape.

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
make bench              # Head-to-head benchmark (requires proxy + frontend running)
make bench-ci           # Benchmark smoke test with stub servers
make bench-modal        # Full A10G benchmark run on Modal
make regen-bench-reports  # Regenerate docs/benchmarks/*.md from committed JSON
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
    completions.proto          # CompletionsService: Complete + CompleteStream

packages/
  gen/                         # Generated stubs (built by make proto, not committed)
  proxy/                       # FastAPI REST proxy → gRPC translator
  frontend/                    # grpc.aio gRPC server (ChatService + CompletionsService)
  client/                      # VllmGrpcClient: Python gRPC-direct client library

demo/                          # Annotated runnable examples (curl, openai-sdk, grpc-direct, streaming)

tools/benchmark/               # Benchmark harness (vllm_grpc_bench package)

scripts/python/
  bench_modal.py               # Modal A10G orchestration (Phase 3–6 benchmark runs)
  modal_bench_*.py             # M5/M5.1/M5.2 Modal apps (gRPC + REST endpoints)
  regen_bench_reports.py       # Regenerate .md reports from committed JSON + sidecars
  gen_chat_corpus.py           # Generate ShareGPT V3 chat corpus (pinned)

tests/integration/             # End-to-end bridge tests (no GPU required)

docs/
  PLAN.md                      # Project plan and phase roadmap
  decisions/                   # Architecture decision records
  benchmarks/                  # Per-milestone benchmark reports + JSON + sidecars
ANALYSIS.md                    # Top-level milestone-by-milestone findings (M1–M5.2)

specs/                         # spec-kit planning artifacts (per-feature)
```

---

## CI

GitHub Actions runs on every push and PR to `main`:

- **ci.yml** — three jobs gated independently: `lint` (`ruff check` + `ruff format --check`), `typecheck` (`mypy --strict packages/proxy/src packages/frontend/src tools/benchmark/src`), `test` (`pytest packages/proxy/tests packages/frontend/tests tools/benchmark/tests`).
- **proto.yml** — verifies committed stubs match proto sources (`make proto` + `git diff --exit-code`).
- **benchmark.yml** — operator-driven full benchmark runs on Modal.
