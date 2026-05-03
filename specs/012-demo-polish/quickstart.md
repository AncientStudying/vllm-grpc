# Quickstart Notes: Phase 7 — Demo Polish

## End-User Demo Experience

After Phase 7, a new viewer can:

```bash
# 1. Clone and bootstrap
git clone <repo-url> vllm-grpc && cd vllm-grpc
make bootstrap

# 2. Start the gRPC frontend (terminal 1) — requires vLLM
make run-frontend

# 3. Start the REST proxy (terminal 2)
make run-proxy

# 4. Run demo scripts (any terminal)
bash demo/curl-rest.sh          # OpenAI REST via proxy (curl)
uv run python demo/openai-sdk.py   # OpenAI REST via proxy (openai SDK)
uv run python demo/grpc-direct.py  # native gRPC, no proxy
uv run python demo/streaming.py    # SSE streaming via proxy
```

## Prerequisites (Viewer Machine)

- macOS M2 (or Linux with CUDA) with `uv` installed
- `make` (macOS: `xcode-select --install`)
- For GPU benchmarking only: Modal credentials (`modal token new`)
- No GPU required for the local demo path (CPU-only vLLM on M2 is sufficient for Qwen3-0.6B)

## Verification

All four `demo/` scripts should return a deterministic completion with `seed=42` when the model is loaded.

Expected failure mode: if the proxy or frontend is not running, demo scripts print a clear error and exit non-zero (not a Python traceback).
