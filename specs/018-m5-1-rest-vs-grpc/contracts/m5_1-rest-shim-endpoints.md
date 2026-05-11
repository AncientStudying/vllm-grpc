# Contract: M5.1 FastAPI REST shim endpoints

The FastAPI shim inside the M5.1 Modal app exposes three endpoints. All are HTTP/1.1; the shim does not negotiate HTTP/2. The shim is internal to the M5.1 measurement run — it is **not** a production REST API. It exists solely to give the REST cohort a methodologically clean path into the same MockEngine the gRPC servicers use.

## `POST /v1/chat/completions`

OpenAI-compatible chat completion. Behavior depends on `stream` field in the request body.

### Request (JSON)

```json
{
  "model": "mock",
  "messages": [
    {"role": "user", "content": "<prompt string>"}
  ],
  "stream": true,
  "max_tokens": 512,
  "temperature": 1.0
}
```

- `model` is always `"mock"`; the field exists for OpenAI-API shape compatibility but the shim ignores it (MockEngine is the only engine).
- `messages` carries a single user-role message; the shim concatenates `content` strings into a flat prompt for MockEngine.generate.
- `stream` MUST be `true` for M5.1 chat_stream cohorts (per Clarifications 2026-05-11). The shim accepts `stream: false` (returns a single JSON response) for completeness but M5.1 cohorts always set `true`.
- `max_tokens`, `temperature` honored; defaults match MockEngine's defaults.

### Response (SSE when `stream: true`)

```text
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
Transfer-Encoding: chunked

data: {"id":"...","choices":[{"delta":{"role":"assistant","content":"<chunk1>"},"index":0}]}

data: {"id":"...","choices":[{"delta":{"content":"<chunk2>"},"index":0}]}

...

data: [DONE]

```

- Each SSE event carries one MockEngine-emitted chunk.
- The harness's REST cohort runner records the wall-clock to the **first non-empty `data:` line** as TTFT.
- The final event is `data: [DONE]` (OpenAI convention); the harness uses receipt of `[DONE]` as the cohort's "request complete" anchor.

### Response (JSON when `stream: false`)

OpenAI-compatible single-response shape. Not used by M5.1 cohorts; available for ad-hoc validation only.

## `POST /v1/embeddings`

> **Methodology note (corrected 2026-05-11):** despite the OpenAI-style URL,
> this endpoint calls `MockEngine.generate` (not `MockEngine.encode`) with a
> prompt-embedding-shaped input. This holds the engine operation constant
> across protocols — gRPC's `CompletionsService.Complete` calls
> `engine.generate` with `prompt_embeds`, so REST must too or the
> protocol-comparison verdict conflates engine work with transport work.
> The URL stays `/v1/embeddings` for continuity with the contract path /
> existing test wiring; the operation is "completion-from-embedding", not
> "return embedding".

Endpoint accepting either a text input or a base64-encoded prompt-embedding tensor. M5.1's embed cohort exercises the latter (matches M1's Phase-6 methodology of "given embedding input, generate a short completion").

### Request (JSON)

```json
{
  "model": "mock",
  "input_kind": "prompt_embedding_b64",
  "input": "<base64-encoded raw float32 tensor bytes>",
  "hidden_size": 4096,
  "max_tokens": 10
}
```

- `input_kind: "prompt_embedding_b64"` MUST be set for M5.1 cohorts. The shim base64-decodes `input`, hashes the raw bytes via `blake2b(digest_size=8)` (matching `M3CompletionsServicer._completion_prompt`), and passes the resulting `embeds:<8-char-hex>` token to `MockEngine.generate` along with `max_tokens` sampling params.
- `input_kind: "text"` is accepted (the raw text becomes the engine prompt) but not used by M5.1 cohorts.
- `hidden_size` MUST be 2048, 4096, or 8192. The cohort runner ships a `(seq_len=16, hidden_size)` float32 tensor (matches `_build_embed_request`'s gRPC-side default), so the request body's base64 payload is `16 × hidden_size × 4` raw bytes plus base64 expansion. The field name is per-token-position width; the engine work depends on `max_tokens` not `hidden_size`.
- `max_tokens` defaults to 10 and matches M3's default for the `Complete` RPC so the per-cohort engine cost is identical across protocols.

### Response (JSON)

```json
{
  "model": "mock",
  "generated_text": "<completion text from MockEngine.generate>",
  "finish_reason": "stop"
}
```

The harness's REST cohort runner records:
- Wall-clock from request-send-completion to response-recv-completion (cohort's per-request wall-clock).
- Shim overhead: server-side wall-clock from FastAPI handler entry to the final `MockEngine.generate` chunk being yielded.
- Request bytes (`request_bytes_median` field on `RESTCohortRecord`): the JSON body length (~10 KB at h=4096 owing to the base64-encoded tensor).
- Response bytes (`response_bytes_median` field): the JSON response length (small — completion text + finish_reason only).

## Response headers (timing instrumentation)

Both `POST /v1/chat/completions` and `POST /v1/embeddings` MUST emit the following response header, carrying the FastAPI handler's intra-process overhead (handler-entry to `MockEngine.{generate,embed}`-return wall-clock, in milliseconds, six-decimal precision):

```text
X-Shim-Overhead-Ms: 0.382451
```

- The header name is **`X-Shim-Overhead-Ms`** (case-insensitive per HTTP/1.1, but the shim emits the canonical PascalCase form).
- For SSE `/v1/chat/completions` responses, the shim emits the header on the initial `200 OK` response line, **before** any `data:` event is sent (so the harness reads it from `response.headers` once the headers are received, regardless of subsequent streaming).
- The harness's REST cohort runner (`rest_cohort.run_rest_cohort`) reads this header per-request and aggregates median + p95 into `RESTCohortRecord.shim_overhead_ms_median` / `shim_overhead_ms_p95`.
- `/healthz` MUST NOT emit this header (the probe doesn't measure shim overhead).
- The header value units are milliseconds (not seconds, not microseconds). Mismatch is a contract violation.

## `GET /healthz`

Lightweight liveness endpoint. No bearer-auth gating (the auth middleware excludes this path). Used by the harness's RTT probe (research.md R-3).

### Request

```text
GET /healthz HTTP/1.1
```

### Response

```json
{"ok": true}
```

Response is intentionally tiny so RTT probes pay minimal serialization cost.

## Authentication

All `/v1/*` endpoints require `Authorization: Bearer <token>` matching the `MODAL_BENCH_TOKEN` value. Missing or mismatched token returns HTTP 401 with body `{"error": "unauthorized"}`. The FastAPI middleware short-circuits the request **before** the body is parsed (research.md R-8) so auth failures cost the harness no extra time.

`/healthz` is **not** gated by bearer auth (the auth middleware skips it). This is deliberate: the RTT probe (which runs frequently) should not pay bearer-validation overhead.

## Error responses

| HTTP code | When |
|-----------|------|
| 400 | Malformed JSON in request body |
| 401 | Missing or mismatched bearer token |
| 422 | Pydantic validation failure (e.g., `hidden_size: 1024` on embed) |
| 500 | MockEngine raised an exception (harness treats this as cohort-irrecoverable, exit code 7) |

Error response bodies are always a single-field JSON: `{"error": "<short message>"}`. No traceback is exposed (the Modal logs carry the traceback).

## Out of scope for M5.1

- Streaming `/v1/embeddings` (no SSE for embeddings; the M1 baseline did not stream embed responses either).
- `model` field validation (the field is accepted-then-ignored).
- OpenAI's `n` field for multi-completion (M5.1 sends single completions only).
- Function-calling, tool-use, vision, anything beyond a single user-role message.
- HTTPS-edge TLS configuration (Modal-managed; the shim does not configure TLS).
