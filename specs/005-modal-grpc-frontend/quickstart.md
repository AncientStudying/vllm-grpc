# Quickstart: Modal gRPC Frontend Deployment

**Phase 3.1** | Prereqs: `modal token new` completed, uv workspace bootstrapped (`make bootstrap`)

---

## Step 1 — Pre-stage Model Weights (one time)

Downloads `Qwen/Qwen3-0.6B` into a persistent Modal Volume. Safe to re-run; skips download if weights already present.

```bash
make download-weights
# or directly:
uv run --with modal modal run scripts/python/modal_download_weights.py
```

Expected output:
```
[OK] Weights already present at /mnt/weights — skipping download.
# or, first run:
[...] Downloading Qwen/Qwen3-0.6B to /mnt/weights ...
[OK] Download complete. Volume committed.
```

Estimated time (first run): 3–5 minutes (network-dependent). Subsequent runs: ~10 seconds.

---

## Step 2 — Run gRPC Frontend Smoke Test

Deploys the `vllm-grpc-frontend` on Modal A10G, starts the proxy inside the container, sends a single chat completion request end-to-end, and tears everything down.

```bash
make smoke-grpc-frontend
# or directly:
uv run --with modal modal run scripts/python/modal_frontend_smoke.py
```

Expected output:
```
[INFO] Container provisioning...
[INFO] Loading model from /mnt/weights ...
[INFO] gRPC server ready (cold_start_s=87.3)
[INFO] Proxy started.
[INFO] Sending smoke-test request (seed=42, max_tokens=20)...
[OK]  completion_text = "The answer is 4."
[OK]  request_latency_s = 1.54
[OK]  Smoke test PASSED. Tearing down.
```

Exit code 0 = pass. Exit code 1 = failure (error message on stderr).

---

## Step 3 — Run REST Comparison Target Smoke Test

Deploys vLLM's native OpenAI REST server on Modal A10G, sends a direct HTTP chat completion request, and tears down.

```bash
make smoke-rest
# or directly:
uv run --with modal modal run scripts/python/modal_vllm_rest.py
```

Expected output mirrors Step 2. Compare `completion_text` between this and Step 2 — they MUST match for SC-003.

---

## Step 4 — Verify Token Equivalence (SC-003)

Both smoke tests use `seed=42`, `max_tokens=20`, and the same prompt. Compare the `completion_text` values printed by Steps 2 and 3. They must be identical.

---

## Manual External Proxy Test (Optional)

For developers who want to validate the proxy running locally (not inside Modal) pointing at a remote gRPC frontend, use `modal.forward` in interactive mode (not covered by the automated smoke test scripts). This is advanced usage and is documented in `docs/decisions/0002-modal-deployment.md`.

The automated smoke test already validates the full proxy→gRPC→vLLM code path (proxy runs as a subprocess inside the Modal container). For purposes of FR-004 / SC-005, no code changes are required to switch `FRONTEND_ADDR` from localhost to a remote address — the proxy uses `grpc.aio.insecure_channel(os.environ.get("FRONTEND_ADDR", "localhost:50051"))` with no hardcoded assumptions about the host.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `NotFoundError: Volume vllm-grpc-model-weights not found` | Step 1 not run | Run `make download-weights` |
| `CUDA out of memory` | A10G VRAM exhausted | Check `max_model_len` — lower if needed |
| `ModuleNotFoundError: vllm_grpc_frontend` | Image build failed | Check `modal run` output for pip install errors |
| `gRPC server did not become healthy within 600s` | Model load timeout | Re-run; if persistent, check A10G availability in your Modal workspace |
| Smoke test hangs | Proxy did not start | Check uvicorn logs in Modal function output |

---

## Makefile Targets (reference)

```makefile
download-weights:     # One-time: stage Qwen/Qwen3-0.6B into Modal Volume
smoke-grpc-frontend:  # Lifecycle-managed gRPC frontend smoke test
smoke-rest:           # Lifecycle-managed REST comparison target smoke test
```
