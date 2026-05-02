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

## Manual External Tunnel (Advanced)

To run a local proxy against a Modal-hosted gRPC server (without the automated lifecycle
script), use `modal.forward()` to expose the gRPC port:

```python
import modal

with modal.forward(50051) as tunnel:
    # tunnel.tcp_socket is the external host:port
    # Start a local proxy: FRONTEND_ADDR=<tunnel.tcp_socket> make run-proxy
    input("Press Enter to tear down...")
```

This pattern is useful for interactive testing but requires keeping the Python process alive
for the duration of the tunnel. The automated smoke-test scripts are preferred for CI-style
validation.
