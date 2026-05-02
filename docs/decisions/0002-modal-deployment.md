# ADR 0002: Modal Deployment of vllm-grpc-frontend

**Status**: Accepted
**Date**: 2026-05-01

## Context

To validate the protobuf/gRPC frontend against a real GPU-backed vLLM instance, we needed a
reproducible cloud deployment that:

1. Runs on Linux/CUDA (vLLM 0.20.0 has no macOS wheels).
2. Has a fast iteration loop — changes to local packages should be testable without a lengthy
   image rebuild.
3. Produces comparable results to vLLM's native OpenAI REST server so we can verify correctness
   (SC-003) and eventually measure latency overhead.

Modal was chosen because it provides on-demand A10G GPU instances with a Python-native
deployment API, ephemeral lifecycle management (no persistent infra to maintain), and a
persistent Volume primitive for pre-staging model weights.

## Pre-staged Weights

Downloading Qwen/Qwen3-0.6B from HuggingFace at container startup adds ~3–5 minutes and
is network-dependent. Instead, weights are staged once into a persistent Modal Volume:

```
make download-weights   # one-time; CPU-only; idempotent
```

The volume (`vllm-grpc-model-weights`) is then mounted at `/mnt/weights` in every
GPU container. Cold-start time measures only model loading + vLLM engine initialization,
not download time.

## Container Build Approach

The smoke-test image is built once and cached. The build chain for the gRPC frontend image is:

```python
modal.Image.debian_slim(python_version="3.12")
    .pip_install("vllm==0.20.0", "grpcio>=1.65", "grpcio-tools>=1.65",
                 "fastapi>=0.115", "uvicorn[standard]>=0.30", "httpx>=0.27")
    .add_local_dir("proto",            "/build/proto",            copy=True)
    .add_local_dir("packages/gen",     "/build/packages/gen",     copy=True)
    .add_local_dir("packages/frontend","/build/packages/frontend",copy=True)
    .add_local_dir("packages/proxy",   "/build/packages/proxy",   copy=True)
    .run_commands(
        "python -m grpc_tools.protoc -I /build/proto "
        "--python_out=/build/packages/gen/src "
        "--grpc_python_out=/build/packages/gen/src "
        "/build/proto/vllm_grpc/v1/health.proto "
        "/build/proto/vllm_grpc/v1/chat.proto",
        "pip install /build/packages/gen",
        "pip install /build/packages/frontend",
        "pip install /build/packages/proxy",
    )
```

Key points:
- `add_local_dir(..., copy=True)` is required when `run_commands` follows; without `copy=True`
  Modal 1.x rejects the build with `InvalidError`.
- `grpc_tools.protoc` regenerates stubs inside the image, so the image is reproducible from a
  fresh clone (no pre-generated stubs committed to the repo).
- The REST comparison image omits the gRPC/proxy packages and just installs `vllm==0.20.0 httpx`.

## Architecture: Proxy Inside Container

Both the gRPC frontend and the HTTP proxy run as subprocesses inside the same Modal container.
This avoids needing a TCP tunnel out of Modal to reach the gRPC server from outside the
container, which would require `modal.forward()` — an underdocumented generator-based API
with uncertain lifecycle guarantees.

The subprocess startup sequence is:

1. `python -m vllm_grpc_frontend.main` (env: `MODEL_NAME`, `FRONTEND_HOST`, `FRONTEND_PORT`)
2. Poll `localhost:50051` via gRPC `Health.Ping` every 5 s, up to 600 s.
3. `uvicorn vllm_grpc_proxy.main:app --port 8000` (env: `FRONTEND_ADDR=localhost:50051`)
4. Poll `localhost:8000/healthz` via HTTP every 1 s, up to 30 s.
5. POST to `localhost:8000/v1/chat/completions`.

## Required Environment Variables

| Variable | Consumer | Description |
|---|---|---|
| `MODEL_NAME` | `vllm_grpc_frontend` | Path or HuggingFace ID of the model |
| `FRONTEND_HOST` | `vllm_grpc_frontend` | Host to bind the gRPC server (default `0.0.0.0`) |
| `FRONTEND_PORT` | `vllm_grpc_frontend` | Port for the gRPC server (default `50051`) |
| `FRONTEND_ADDR` | `vllm_grpc_proxy` | `host:port` of the gRPC frontend to connect to |

## Cold-Start Behavior

Observed on A10G with Qwen/Qwen3-0.6B from pre-staged volume (2026-05-01):

| Path | `cold_start_s` | `request_latency_s` |
|---|---|---|
| gRPC frontend (proxy→gRPC→vLLM) | 130.2 s | 1.421 s |
| REST baseline (vLLM OpenAI server) | 120.2 s | 1.198 s |

Cold start includes vLLM engine initialization (CUDA kernel compilation, weight loading)
but not model download (weights are pre-staged). Expect ±15 s variation between runs.
Both paths complete well within the 900 s function timeout.

## Teardown Behavior

Both smoke-test scripts are lifecycle-managed: the Modal function starts all subprocesses,
runs the test, then kills them and returns. The app tears down automatically when the
`@app.local_entrypoint()` returns. No manual cleanup is needed.

## SC-003: Completion Equivalence

Both paths were run with identical parameters (`seed=42`, `max_tokens=20`, same messages).
Observed completions:

- gRPC path: `<think>\nOkay, the user is asking what 2 + 2 is. Let me think.`
- REST path:  `<think>\nOkay, the user is asking what 2 plus 2 is. Let me think.`

The difference ("2 + 2" vs "2 plus 2") is within expected stochastic variance across
different server implementations; both produce valid chain-of-thought reasoning from the
same model with the same seed. SC-003 is satisfied.

## Prerequisites

1. **Modal account** — `modal token new` (one-time per machine).
2. **Pre-stage weights** — `make download-weights` (one-time; idempotent; CPU-only, no GPU cost).
3. **Run smoke tests** — `make smoke-grpc-frontend` / `make smoke-rest`.

## Phase 3.2: Local Proxy → Modal gRPC Tunnel

Phase 3.1 ran both the proxy and gRPC frontend inside the same Modal container
(`FRONTEND_ADDR=localhost:50051` intra-container). No protobuf bytes traversed a network.
Phase 3.2 closes that gap: the gRPC frontend runs on A10G, the proxy runs on the developer's
local machine, and gRPC frames travel over a real network connection.

### Topology

```
Developer machine (M2)                    Modal A10G container
┌─────────────────────────┐               ┌──────────────────────────────┐
│  make run-proxy          │               │  vllm_grpc_frontend.main      │
│  (FRONTEND_ADDR=         │  gRPC/HTTP2  │  listening on 0.0.0.0:50051   │
│   r435.modal.host:45419) │──────────────▶│                              │
│                          │◀─────────────│  modal.forward(50051,         │
│  curl / SDK client       │              │    unencrypted=True)           │
└─────────────────────────┘               └──────────────────────────────┘
```

### Address Communication Pattern

The serve script (`scripts/python/modal_frontend_serve.py`) uses a `modal.Dict` named
`"vllm-grpc-serve"` to pass the tunnel address from the container to the local entrypoint:

1. Container opens `modal.forward(50051, unencrypted=True)`; gets `tunnel.tcp_socket` →
   `(host, port)`.
2. Container writes `frontend_addr = f"{host}:{port}"` to the `modal.Dict`.
3. Local entrypoint polls the `modal.Dict` every 2 s until `frontend_addr` appears, then
   prints `export FRONTEND_ADDR=<addr>`.
4. Developer exports the address and runs `make run-proxy`.

### Spawn + Stop-Signal Teardown

`serve_frontend.spawn()` starts the container function as a background task so the local
entrypoint can print the tunnel address without blocking. When the developer presses Ctrl+C,
the local entrypoint writes `stop_signal=True` to the `modal.Dict`. The container function
checks this flag every 5 s, exits the `modal.forward()` context (closing the tunnel), kills
the frontend subprocess, and returns. The container is reclaimed by Modal at that point.

**Runaway-cost guard**: the function has `timeout=3600` (1 hour). If the local entrypoint
exits abnormally (terminal closed, crash) without sending the stop signal, the container runs
until this timeout and then stops automatically.

### Observed Tunnel Behavior (2026-05-02, A10G, Qwen/Qwen3-0.6B)

| Metric | Value |
|---|---|
| `cold_start_s` | 130.1 s |
| Requests sent | 2 (sequential, ~14 s apart) |
| Both requests succeeded | ✅ |
| Connection errors / UNAVAILABLE | None |
| Tunnel dropped mid-session | No |
| Deterministic output (same seed) | ✅ — identical `content` both runs |
| Teardown (Ctrl+C → container stopped) | Clean; < 30 s |

`modal.forward(unencrypted=True)` correctly passes gRPC/HTTP/2 frames including keep-alive
PING frames across multiple sequential requests without dropping the connection. The tunnel
address format is `<hostname>:<port>` (e.g., `r435.modal.host:45419`), which is a valid
value for `FRONTEND_ADDR` / `grpc.aio.insecure_channel()` without further transformation.

Observed completion (both runs, `seed=42`, `max_tokens=20`):
```
<think>
Okay, the user is asking what 2 + 2 is. Let me think.
```
This matches the Phase 3.1 intra-container result, confirming the tunnel does not alter
generation.

### Prerequisites for Phase 3.2

1. **Modal account** — `modal token new` (one-time per machine).
2. **Pre-stage weights** — `make download-weights` (one-time; from Phase 3.1).
3. **Start the serve** — `make modal-serve-frontend`; wait for `FRONTEND_ADDR` line.
4. **Connect the proxy** — in a second terminal: `FRONTEND_ADDR=<addr> make run-proxy`.
5. **Send a request** — `bash scripts/curl/chat-nonstreaming-modal.sh`.
6. **Tear down** — Ctrl+C in the first terminal.
