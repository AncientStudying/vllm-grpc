# Contract: Completions SSE Wire Format

**Endpoint**: `POST /v1/completions` with `"stream": true`
**Media type**: `text/event-stream`
**Status**: Authoritative — proxy must produce exactly this format

---

## Event Sequence

```
data: {chunk_event}\n\n
data: {chunk_event}\n\n
...
data: {final_chunk_event}\n\n
data: [DONE]\n\n
```

There is **no** initial role-delta event (unlike chat completions streaming).

---

## Content-Delta Event (non-final)

```json
{
  "id": "cmpl-{uuid}",
  "object": "text_completion",
  "created": {unix_timestamp},
  "model": "{model_name}",
  "choices": [
    {
      "text": "{token_string}",
      "index": 0,
      "logprobs": null,
      "finish_reason": null
    }
  ]
}
```

---

## Final-Chunk Event

```json
{
  "id": "cmpl-{uuid}",
  "object": "text_completion",
  "created": {unix_timestamp},
  "model": "{model_name}",
  "choices": [
    {
      "text": "",
      "index": 0,
      "logprobs": null,
      "finish_reason": "stop"
    }
  ]
}
```

`finish_reason` is `"stop"` (EOS) or `"length"` (`max_tokens` exhausted). `text` is `""` on the final chunk.

---

## [DONE] Terminator

```
data: [DONE]\n\n
```

Always emitted after the final chunk event, including on error (see below — error replaces all chunks but still omits `[DONE]`).

---

## Error Event

When a gRPC error occurs, emit a single error event and **do not** emit `[DONE]`:

```json
{
  "error": {
    "message": "{grpc_status_details_or_default}",
    "type": "server_error",
    "code": null
  }
}
```

---

## HTTP Headers (required)

```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

---

## Invariants

- `id` is the same UUID-based string for all events in a single stream.
- `created` is the same Unix timestamp for all events in a single stream (set at stream start).
- `object` is always `"text_completion"` (not `"chat.completion.chunk"`).
- The concatenation of all `choices[0].text` values across non-final events equals the `generated_text` field of the equivalent non-streaming `CompletionResponse` for the same seed.
