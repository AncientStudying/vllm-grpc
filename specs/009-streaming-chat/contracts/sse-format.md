# Contract: OpenAI-Compatible SSE Delta Wire Format

The proxy MUST produce SSE events that conform to the OpenAI chat completions streaming wire format, as consumed by the `openai` Python SDK and `curl -N`.

---

## Headers

```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

`X-Accel-Buffering: no` disables nginx buffering (required when the proxy is behind nginx in production-like deployments).

---

## Event sequence

Each event is a line starting with `data: ` followed by a JSON object, terminated with `\n\n` (two newlines).

### First chunk — role delta

```
data: {"id":"chatcmpl-<uuid>","object":"chat.completion.chunk","created":<unix>,"model":"<model>","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

```

### Middle chunks — content delta (one per token)

```
data: {"id":"chatcmpl-<uuid>","object":"chat.completion.chunk","created":<unix>,"model":"<model>","choices":[{"index":0,"delta":{"content":"<token>"},"finish_reason":null}]}

```

`<uuid>` and `<created>` are fixed for the duration of a single streaming response (generated once at the start of the stream).

### Final chunk — finish reason

```
data: {"id":"chatcmpl-<uuid>","object":"chat.completion.chunk","created":<unix>,"model":"<model>","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

```

`finish_reason` is `"stop"` or `"length"` depending on what the frontend emits.

### Stream terminator

```
data: [DONE]

```

MUST be the last line emitted. MUST always be present — including when `max_tokens=1` and on empty-output edge cases. MUST NOT be present if the stream is terminated due to an error.

---

## Error during stream

When the proxy detects a gRPC error mid-stream (after the `200 OK` header has been sent), it MUST emit an error event and close:

```
data: {"error":{"message":"<human-readable>","type":"internal_error"}}

```

No `data: [DONE]` follows an error event. Clients should treat absence of `[DONE]` as an indicator of abnormal termination.

---

## Mapping from `ChatStreamChunk` proto

| Proto field | SSE destination |
|-------------|----------------|
| `delta_content` | `choices[0].delta.content` (omitted if empty, i.e., on final chunk) |
| `finish_reason` | `choices[0].finish_reason` (`null` while `""`, actual value on final chunk) |
| `token_index` | Not included in SSE (internal ordering only) |

Role ("assistant") is injected by the proxy on the first SSE chunk — not present in the proto.

---

## Constraints

- `id` and `created` MUST be identical across all chunks of a single stream.
- `finish_reason` MUST be `null` (JSON null) on all chunks except the final one.
- The final delta chunk MUST have `delta: {}` (empty object) and `finish_reason: "stop"` or `"length"`.
- `data: [DONE]` MUST follow the final delta chunk.
- The proxy MUST set `Content-Type: text/event-stream` before streaming begins — FastAPI's `StreamingResponse` handles this via `media_type`.
