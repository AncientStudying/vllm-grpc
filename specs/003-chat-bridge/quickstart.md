# Quickstart: Phase 3 — Minimal Non-Streaming Chat Completion Bridge

**Goal**: Bring up proxy + frontend locally and issue a chat completion in under 2 minutes.

**Prerequisites**: `uv` and Python 3.12 installed (Phase 1 deliverable). For a live model run,
a Modal account with the Phase 2 Modal app deployed (ADR 0001). For CI / local testing without
a GPU, the `FakeChatServicer` integration test can be run with no external dependencies.

---

## Option A — Live Demo (Modal A10G + Real Model)

This option runs the actual Qwen3-0.6B model on Modal and times in under 2 minutes from cold.

### Step 1 — Install dependencies

```bash
make bootstrap   # uv sync --all-packages && make proto
```

### Step 2 — Start the frontend (deploys to Modal, blocks)

```bash
make run-frontend-modal
# or directly:
MODAL_APP=vllm-grpc-frontend uv run modal serve packages/frontend/src/vllm_grpc_frontend/modal_entry.py
```

The frontend prints the gRPC endpoint address when ready (e.g., `grpc.modal.run:50051`).

### Step 3 — Start the proxy (local)

In a second terminal:

```bash
FRONTEND_ADDR=<address from step 2> make run-proxy
# Proxy listens on http://localhost:8000
```

### Step 4 — Issue a chat completion

```bash
bash scripts/curl/chat-nonstreaming.sh
# or:
uv run python scripts/python/chat-nonstreaming.py
```

Expected output:

```
2 + 2 = 4.
```

---

## Option B — Local CI Demo (FakeChatServicer, No GPU)

For development without a Modal account or GPU. Exercises the full translation path with a
hardcoded response.

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

**Qwen3-0.6B takes >2 minutes to load on first run**
The 2-minute demo target assumes the model weights are already downloaded. First-run model
download from Hugging Face is not counted against the demo time. Run `make run-frontend` once
to cache weights, then time from a warm start.
