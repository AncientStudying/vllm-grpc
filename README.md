# vllm-grpc

A Protobuf/gRPC frontend for vLLM that replaces the OpenAI REST wire format with protobuf-over-gRPC, demonstrating reduced wire and parsing overhead for LLM inference workloads.

See [`docs/PLAN.md`](docs/PLAN.md) for the full project plan and phase roadmap.

---

## Prerequisites

- macOS (M2) or Linux
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `make` — macOS: `xcode-select --install`; Linux: pre-installed

---

## Quick Start

```bash
# 1. Clone
git clone <repo-url> vllm-grpc && cd vllm-grpc

# 2. Bootstrap — installs dependencies and generates protobuf stubs
make bootstrap

# 3. Start the gRPC frontend (terminal 1)
make run-frontend

# 4. Start the REST proxy (terminal 2)
make run-proxy

# 5. Verify the end-to-end ping
curl -s http://localhost:8000/healthz
# → {"status":"ok"}

# 6. Send a chat completion
bash scripts/curl/chat-nonstreaming.sh
# or with the openai Python SDK:
uv run python scripts/python/chat-nonstreaming.py
```

---

## Development Commands

```bash
make bootstrap      # Install deps + generate proto stubs (run after clone)
make proto          # Regenerate protobuf stubs only
make lint           # ruff check + format check
make typecheck      # mypy --strict
make test           # pytest
make check          # lint + typecheck + test
make run-proxy      # Start REST proxy on :8000
make run-frontend   # Start gRPC server on :50051
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXY_PORT` | `8000` | REST proxy listen port |
| `FRONTEND_PORT` | `50051` | gRPC frontend listen port |
| `FRONTEND_ADDR` | `localhost:50051` | Proxy → frontend address |
| `MODEL_NAME` | `Qwen/Qwen3-0.6B` | Model loaded by the frontend |

---

## Repository Structure

```
proto/                     # Protobuf source of truth
  vllm_grpc/v1/
    health.proto
    chat.proto             # Phase 3: ChatService (non-streaming completion)
packages/
  gen/                     # Generated stubs (built by make proto, not committed)
  proxy/                   # FastAPI REST proxy (POST /v1/chat/completions, GET /healthz)
  frontend/                # grpc.aio server (ChatService.Complete, Health.Ping)
scripts/
  curl/
    chat-nonstreaming.sh   # curl chat completion example
  python/
    chat-nonstreaming.py   # openai SDK chat completion example
tests/integration/         # FakeChatServicer bridge test (no GPU required)
docs/
  PLAN.md                  # Project plan and phase roadmap
  decisions/               # ADRs
  benchmarks/              # Phase benchmark results
specs/                     # spec-kit planning artifacts
```

---

## Spec Kit

This project uses [spec-kit](https://github.com/safishamsi/spec-kit) via Claude Code for per-phase planning.

To start a new planning cycle:

```
/specify   → create feature specification
/plan      → generate implementation plan + research
/tasks     → generate ordered task list
/implement → execute the task list
```

Artifacts are written to `specs/<NNN>-<feature-name>/`.

---

## Graphify

Re-index the knowledge graph at the start of each phase:

```bash
graphify  # produces HTML graph in docs/graphs/
```

---

## CI

GitHub Actions runs on every push and PR to `main`:

- **ci.yml** — lint (`ruff`), type-check (`mypy --strict`), tests (`pytest`)
- **proto.yml** — verifies committed stubs match proto sources (`make proto` + `git diff --exit-code`)
