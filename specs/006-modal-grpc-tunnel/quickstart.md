# Quickstart: Phase 3.2 — Local Proxy → Modal gRPC Tunnel

**Purpose**: End-to-end walkthrough of bringing up the gRPC frontend on Modal A10G and connecting a locally-running proxy to it over the network.

**Prerequisites**:
- `modal token new` completed (Modal authentication)
- `make download-weights` completed (model weights pre-staged in the Modal Volume)
- `uv sync --all-packages` completed (local Python environment bootstrapped)

---

## Step 1: Start the gRPC Frontend on Modal

Open a terminal. Run:

```bash
make modal-serve-frontend
```

You will see output similar to:

```
[INFO] Deploying gRPC frontend to Modal A10G...
[INFO] cold_start_s = 131.4
[OK]   export FRONTEND_ADDR=tcp.modal.run:12345
[INFO] Set FRONTEND_ADDR and run: make run-proxy
[INFO] Press Ctrl+C to tear down.
```

**Keep this terminal open** — pressing Ctrl+C tears down the Modal container.

**Expected timing**: The `FRONTEND_ADDR` line appears within ~3 minutes (cold start: container provision + vLLM engine init, weights pre-staged). If no address appears after 600 s, the command exits with an error.

---

## Step 2: Start the Proxy Locally

Open a **second terminal**. Copy the `FRONTEND_ADDR` value from Step 1 and run:

```bash
export FRONTEND_ADDR=tcp.modal.run:12345   # replace with your actual address
make run-proxy
```

The proxy starts on `localhost:8000`. You should see uvicorn startup logs.

**Verify the proxy reached the cloud frontend**:

```bash
curl -s http://localhost:8000/healthz | python -m json.tool
```

Expected: `{"status": "ok"}` — the proxy's `/healthz` calls `Health.Ping` on the cloud gRPC frontend; a 200 response confirms the tunnel is working.

---

## Step 3: Send a Smoke-Test Request

In the second terminal:

```bash
bash scripts/curl/chat-nonstreaming-modal.sh
```

Expected output (formatted JSON):

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "<think>\nOkay, the user is asking what 2 + 2 is..."
      },
      "finish_reason": "length"
    }
  ]
}
```

A non-empty `content` field confirms the full path: local proxy → gRPC tunnel → Modal A10G → vLLM → response.

---

## Step 4: Tear Down

In the **first terminal** (where `make modal-serve-frontend` is running), press **Ctrl+C**.

```
^C
[INFO] Sending teardown signal...
[INFO] Container will stop within 30s. Exiting.
```

The Modal container stops automatically. No manual cleanup required.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No `FRONTEND_ADDR` after 10 min | vLLM failed to start in container | Check `modal logs` for the container; most common cause is out-of-memory or CUDA error |
| `curl: (7) Failed to connect` | Proxy not running or wrong port | Check `make run-proxy` output; confirm `PROXY_PORT` env var |
| `upstream connect error` from proxy | Tunnel dropped or container stopped | Check first terminal; restart `make modal-serve-frontend` if needed |
| `healthz` returns 500 | Proxy can reach tunnel but gRPC frontend crashed | Check container logs; frontend stderr is printed to container stdout |
| `stop_signal` not received | local entrypoint crashed abnormally | Container runs until 1-hour timeout; manually stop via Modal dashboard |

---

## SC-003: Expected Completion

The `content` field should begin with a chain-of-thought reasoning prefix (Qwen3 style):

```
<think>
Okay, the user is asking what 2 + 2 is...
```

This matches the Phase 3.1 gRPC path result, confirming the bridge does not alter generation.
