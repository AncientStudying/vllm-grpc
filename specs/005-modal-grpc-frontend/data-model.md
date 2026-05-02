# Data Model: Modal gRPC Frontend Deployment

**Branch**: `005-modal-grpc-frontend` | **Date**: 2026-05-01

This phase introduces no new proto messages, database tables, or persistent data schemas. The data model covers the runtime entities — Modal cloud resources and the timing data collected during smoke tests.

---

## Entity: ModalWeightVolume

A named persistent Modal cloud storage volume that holds pre-staged model weights.

| Field | Type | Notes |
|-------|------|-------|
| `name` | `str` | `"vllm-grpc-model-weights"` — fixed name; shared by gRPC frontend and REST comparison target |
| `mount_path` | `str` | `"/mnt/weights"` — fixed mount point inside Modal containers |
| `contents` | directory | `Qwen/Qwen3-0.6B` in HuggingFace `snapshot_download` layout (`config.json`, `model.safetensors`, `tokenizer.json`, etc.) |
| `committed` | bool | Must be `True` after download; uncommitted writes are not visible to other functions |

**Lifecycle**:
- Created once by `modal_download_weights.py` (idempotent; skips if `/mnt/weights/config.json` already exists)
- Read-only during gRPC frontend and REST server functions
- Persists across all invocations; survives Modal app restarts

---

## Entity: SmokeTestResult

Returned by each Modal smoke-test function. Used to confirm functional correctness and to record cold-start timing for the ADR.

| Field | Type | Notes |
|-------|------|-------|
| `ok` | `bool` | `True` if smoke test passed end-to-end |
| `error` | `str \| None` | Error description if `ok=False`; `None` otherwise |
| `cold_start_s` | `float` | Seconds from function invocation to server ready (excludes model download — weights are pre-staged) |
| `request_latency_s` | `float` | Seconds for the single smoke-test chat completion request |
| `completion_text` | `str \| None` | First choice content from the response; used to confirm non-empty output and cross-check gRPC vs REST equivalence |
| `model` | `str` | Model path used (`"/mnt/weights"`) |
| `seed` | `int` | Seed used for the test request (`42`) |
| `max_tokens` | `int` | Max tokens requested (`20`) |

---

## Entity: ModalGrpcFrontendImage

The Modal container image definition for the gRPC frontend smoke test. Not a persisted entity — rebuilt when source files change (Modal's content-hash layer caching applies).

| Component | Value |
|-----------|-------|
| Base | `debian_slim(python_version="3.12")` |
| Runtime packages | `vllm==0.20.0`, `grpcio>=1.65`, `grpcio-tools>=1.65` |
| Proxy packages | `fastapi>=0.115`, `uvicorn[standard]>=0.30` |
| Local source | `proto/`, `packages/gen/`, `packages/frontend/`, `packages/proxy/` |
| Build commands | `grpcio_tools.protoc` (generate stubs), `pip install packages/gen`, `pip install packages/frontend`, `pip install packages/proxy` |
| GPU | `A10G` |
| Timeout | 600 s |
| Volume | `ModalWeightVolume` at `/mnt/weights` |

---

## Entity: ModalRestImage

The Modal container image definition for the REST comparison target smoke test.

| Component | Value |
|-----------|-------|
| Base | `debian_slim(python_version="3.12")` |
| Runtime packages | `vllm==0.20.0`, `httpx` |
| Local source | None (vLLM native OpenAI server; no workspace packages needed) |
| GPU | `A10G` |
| Timeout | 600 s |
| Volume | `ModalWeightVolume` at `/mnt/weights` |

---

## State Transitions: Weight Volume

```
MISSING ──[run modal_download_weights.py]──▶ COMMITTED
COMMITTED ──[read by gRPC / REST functions]──▶ COMMITTED  (read-only, no state change)
COMMITTED ──[re-run modal_download_weights.py]──▶ COMMITTED  (idempotent, no-op)
```

---

## Relationships

```
modal_download_weights.py ──creates/updates──▶ ModalWeightVolume
modal_frontend_smoke.py ──mounts (read-only)──▶ ModalWeightVolume
modal_vllm_rest.py ──mounts (read-only)──▶ ModalWeightVolume
modal_frontend_smoke.py ──builds──▶ ModalGrpcFrontendImage
modal_vllm_rest.py ──builds──▶ ModalRestImage
modal_frontend_smoke.py ──returns──▶ SmokeTestResult
modal_vllm_rest.py ──returns──▶ SmokeTestResult
```
