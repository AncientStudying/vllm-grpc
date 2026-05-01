# Contract: Proxy REST API (POST /v1/chat/completions)

**Server**: `vllm_grpc_proxy` (FastAPI + uvicorn)
**Default port**: 8000 (configurable via `PROXY_PORT` env var)

---

## Endpoint

```
POST /v1/chat/completions
Content-Type: application/json
```

OpenAI-compatible. Clients using the `openai` Python SDK with `base_url` pointed at the proxy
should work without modification (non-streaming only in this phase).

---

## Request Body

```json
{
  "model":      "Qwen/Qwen3-0.6B",
  "messages": [
    { "role": "system",    "content": "You are a helpful assistant." },
    { "role": "user",      "content": "What is 2 + 2?" }
  ],
  "max_tokens":  128,
  "temperature": 0.7,
  "top_p":       1.0,
  "seed":        42
}
```

### Field Reference

| Field       | Type    | Required | Notes |
|-------------|---------|----------|-------|
| model       | string  | yes      | Model identifier; echoed in response |
| messages    | array   | yes      | Ordered list of `{role, content}` objects; minimum 1 |
| max_tokens  | integer | yes      | Must be > 0 |
| temperature | float   | no       | Range 0.0–2.0; default 1.0 |
| top_p       | float   | no       | Range 0.0–1.0; default 1.0 |
| seed        | integer | no       | Enables deterministic output when set |
| stream      | boolean | no       | `true` → 501 Not Implemented |

Unknown fields are silently ignored.

---

## Successful Response (HTTP 200)

```json
{
  "id":      "chatcmpl-3f2a1b4c-...",
  "object":  "chat.completion",
  "created": 1746000000,
  "model":   "Qwen/Qwen3-0.6B",
  "choices": [
    {
      "index": 0,
      "message": {
        "role":    "assistant",
        "content": "2 + 2 = 4."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens":     32,
    "completion_tokens": 10,
    "total_tokens":      42
  }
}
```

---

## Error Responses

| Condition | Status | Response body |
|---|---|---|
| `stream: true` | 501 | `{"error": {"message": "Streaming not yet implemented", "type": "not_implemented_error"}}` |
| `messages` empty or missing | 422 | FastAPI validation error JSON |
| `max_tokens` ≤ 0 | 422 | FastAPI validation error JSON |
| Frontend unreachable | 502 | `{"error": {"message": "Frontend unavailable", "type": "gateway_error"}}` |
| Frontend deadline exceeded | 504 | `{"error": {"message": "Frontend timed out", "type": "gateway_error"}}` |
| Unexpected server error | 500 | `{"error": {"message": "Internal server error", "type": "internal_error"}}` |

---

## Additional Endpoints (unchanged from Phase 1)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/healthz` | Returns `{"status": "ok"}` if frontend is reachable |
