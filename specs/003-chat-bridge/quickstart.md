# Quickstart: Phase 3 — Minimal Non-Streaming Chat Completion Bridge

**Goal**: Bring up proxy + frontend locally and issue a chat completion in under 2 minutes.

**Prerequisites**: `uv` and Python 3.12 installed. No GPU or cloud account required — the
`FakeChatServicer` integration test exercises the full translation path with a hardcoded response.

---

## Run the bridge (FakeChatServicer, no GPU required)

Exercises the full proxy → gRPC → servicer → OpenAI JSON translation path with a hardcoded
response — no GPU or cloud account needed.

```bash
make bootstrap
make test                    # runs all unit + integration tests including the bridge test
```

To run only the integration test:

```bash
uv run pytest tests/integration/test_chat_bridge.py -v
```

---

## Environment Variables

| Variable         | Default          | Description                                      |
|------------------|------------------|--------------------------------------------------|
| `FRONTEND_ADDR`  | `localhost:50051` | gRPC address the proxy connects to              |
| `FRONTEND_PORT`  | `50051`           | Port the frontend gRPC server listens on        |
| `PROXY_PORT`     | `8000`            | Port the proxy HTTP server listens on           |
| `MODEL_NAME`     | `Qwen/Qwen3-0.6B` | Model loaded by the frontend at startup         |

---

## Makefile Targets

| Target             | Description                                              |
|--------------------|----------------------------------------------------------|
| `make bootstrap`   | `uv sync --all-packages` + `make proto`                  |
| `make proto`       | Compile `health.proto` + `chat.proto` → stubs            |
| `make lint`        | `ruff check` + `ruff format --check`                     |
| `make typecheck`   | `mypy --strict packages/proxy/src packages/frontend/src` |
| `make test`        | Unit tests + integration tests (no GPU required)         |
| `make check`       | `make lint typecheck test`                               |
| `make run-proxy`   | Start FastAPI proxy on `PROXY_PORT`                      |
| `make run-frontend`| Start gRPC frontend on `FRONTEND_PORT` (local vllm)      |

---

## Troubleshooting

**`make proto` fails with "No module named grpc_tools"**
Run `make bootstrap` first — it syncs the dev dependency group which includes `grpcio-tools`.

**Proxy returns 502 "Frontend unavailable"**
The frontend is not running or `FRONTEND_ADDR` points to the wrong address. Check `make run-frontend` output.

**`mypy` reports errors in generated stubs**
Generated files (`chat_pb2.py` etc.) are covered by the `ignore_errors = true` override in
`pyproject.toml [tool.mypy.overrides]`. If new stub modules are generated, add them to that
override list.

**`make run-frontend` downloads model weights on first run**
Qwen3-0.6B weights are fetched from Hugging Face on first start. Run `make run-frontend` once
to cache them; subsequent starts are fast.
