# Feature Specification: Streaming Chat Completions (Phase 5)

**Feature Branch**: `009-streaming-chat`  
**Created**: 2026-05-02  
**Status**: Draft  

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Streaming via Proxy (Priority: P1)

An OpenAI SDK or curl client sends `POST /v1/chat/completions` with `"stream": true` to the proxy. The proxy forwards it as a server-streaming gRPC call to the frontend, which drives the vLLM generation loop and yields token chunks. The proxy re-encodes each chunk as an OpenAI SSE delta and streams them back to the client, terminating with `data: [DONE]`.

**Why this priority**: This is the core streaming use case — making the existing REST surface support streaming so the project fulfills its compatibility promise. It is the most user-visible deliverable and unblocks TTFT/TPOT benchmarking.

**Independent Test**: Start the proxy and frontend locally. Run `curl -N .../v1/chat/completions` with `"stream": true` and `seed: 42`. Verify SSE deltas arrive incrementally and the concatenated content matches the non-streaming response for the same seed.

**Acceptance Scenarios**:

1. **Given** the proxy and frontend are running, **When** a client sends a streaming chat completion request, **Then** SSE delta events arrive before generation is complete (first token visible before full response).
2. **Given** a streaming request in progress, **When** all tokens are generated, **Then** the stream terminates with `data: [DONE]` and the connection closes cleanly.
3. **Given** a streaming request, **When** the concatenated `delta.content` fields are assembled, **Then** the result is identical to the non-streaming response for the same seed and parameters.
4. **Given** a streaming request in progress, **When** the client disconnects mid-stream, **Then** the gRPC stream is cancelled and server-side generation stops (verifiable in logs).

---

### User Story 2 — Direct gRPC Streaming via Client Library (Priority: P2)

A Python developer uses `VllmGrpcClient` to stream completions directly from the gRPC frontend, bypassing the proxy. They iterate over an async generator that yields typed chunk objects as tokens arrive.

**Why this priority**: Direct-gRPC streaming is needed for the TTFT/TPOT benchmark comparison (proxy path vs direct-gRPC path). It also demonstrates the client library's value for Python-native consumers who want streaming without HTTP overhead.

**Independent Test**: Instantiate `VllmGrpcClient("host:port")`, call `client.chat.complete_stream(messages, seed=42)`, iterate the async generator, concatenate chunk content. Verify result matches the non-streaming response for the same seed.

**Acceptance Scenarios**:

1. **Given** a running frontend, **When** a developer calls `client.chat.complete_stream(...)`, **Then** chunk objects arrive incrementally before generation completes.
2. **Given** a streaming generator in progress, **When** the generator is abandoned mid-iteration, **Then** the server-side generation task is cancelled.
3. **Given** a mid-stream server error, **When** the generator is iterated, **Then** a typed exception is raised with a meaningful message rather than a silent empty result.

---

### User Story 3 — TTFT and TPOT Benchmark Metrics (Priority: P3)

The benchmark harness measures Time-to-First-Token (TTFT) and Time-per-Output-Token (TPOT) for both the proxy path and the direct-gRPC client path against the vLLM-native SSE baseline, across the standard concurrency levels.

**Why this priority**: Without streaming metrics the project's wire-overhead thesis is incomplete. TTFT and TPOT measure incremental delivery latency — the dimension streaming actually benefits users — and provide the final comparison column the project set out to produce.

**Independent Test**: Run `make bench-modal` with streaming enabled. Verify `docs/benchmarks/phase-5-streaming-comparison.md` exists and contains TTFT and TPOT columns for REST-native, gRPC-proxy, and gRPC-direct at each concurrency level.

**Acceptance Scenarios**:

1. **Given** a completed streaming benchmark run, **When** the report is generated, **Then** TTFT (ms) and TPOT (ms/token) are present for all three targets at each concurrency level.
2. **Given** TTFT and TPOT numbers, **When** compared to the non-streaming baseline, **Then** they are within an explainable range — honest reporting required, equal or better than REST-native preferred.

---

### Edge Cases

- What happens when generation produces zero tokens (empty response)? The stream must still terminate with `data: [DONE]`.
- What happens when `max_tokens=1`? A single delta chunk plus `[DONE]` must be produced.
- What happens when the frontend crashes mid-stream? The proxy must surface a 500 error to the client rather than hanging or emitting a partial stream without `[DONE]`.
- What happens when gRPC flow control back-pressures the stream? The AsyncLLM iteration must pause rather than buffer unboundedly.
- What happens when streaming and non-streaming requests are concurrent? Both must coexist without interference.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST support `"stream": true` on `POST /v1/chat/completions` via the proxy, producing OpenAI-compatible SSE deltas in the same format as vLLM's native server.
- **FR-002**: The proxy MUST terminate every SSE stream with `data: [DONE]` and close the connection cleanly — including on error.
- **FR-003**: The frontend MUST expose a server-streaming RPC for chat completions, yielding one protobuf chunk message per output token.
- **FR-004**: The frontend MUST drive token generation as an async generator and yield chunks as they are produced, not buffer the full response.
- **FR-005**: When a client disconnects or cancels mid-stream, the frontend MUST cancel the in-progress generation task and release resources within 2 seconds.
- **FR-006**: gRPC flow control MUST propagate back-pressure from a slow consumer to the generation loop; the frontend MUST NOT buffer output tokens unboundedly.
- **FR-007**: The `VllmGrpcClient` library MUST expose `complete_stream(messages, ...)` as an async generator yielding typed chunk objects, usable with `async for` without constructing protobuf messages directly.
- **FR-008**: Mid-stream server errors MUST surface as typed exceptions from the `complete_stream` generator, not as silently truncated output.
- **FR-009**: The benchmark harness MUST record TTFT and TPOT for each streaming request across all three target paths (REST-native, gRPC-proxy, gRPC-direct).
- **FR-010**: The streaming path MUST produce token-identical output to the non-streaming path for the same request with a fixed seed.
- **FR-011**: Streaming and non-streaming requests MUST be handled concurrently without interference.
- **FR-012**: An ADR in `docs/decisions/` MUST document the streaming design choices: chunk granularity, error encoding, back-pressure model, and cancellation semantics.

### Key Entities

- **StreamChunk**: A single incremental response unit. Carries: delta content (string), finish reason (null until final chunk), token index. Maps to both a protobuf chunk message and an OpenAI SSE `data:` event.
- **TTFTSample**: Benchmark measurement — elapsed time from request dispatch to receipt of the first non-empty delta. Recorded per request; summarised as P50/P95/P99.
- **TPOTSample**: Benchmark measurement — per-token delivery interval, computed as `(last_token_time − first_token_time) / (token_count − 1)`. Recorded per request; summarised as P50/P95/P99.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A streaming request via the proxy produces its first token before full generation completes — TTFT is strictly less than total response latency for all test requests.
- **SC-002**: Concatenated streaming output matches non-streaming output for the same seed in 100% of test cases.
- **SC-003**: Server-side generation stops within 2 seconds of client disconnect (verifiable in logs).
- **SC-004**: TTFT via gRPC-direct is equal to or lower than TTFT via the proxy path at each concurrency level.
- **SC-005**: The benchmark report contains TTFT P50/P95/P99 and TPOT P50/P95/P99 for all three paths, committed to `docs/benchmarks/phase-5-streaming-comparison.md`.
- **SC-006**: `mypy --strict` passes across all updated packages with zero errors.
- **SC-007**: All existing non-streaming tests continue to pass after streaming is introduced.

## Assumptions

- vLLM's `AsyncLLM.generate()` already yields tokens incrementally as an async generator — no patching of vLLM internals is required.
- The existing Modal A10G deployment can be reused for streaming benchmarks without changes to the deploy configuration.
- Chunk granularity is one token per protobuf message (not batched); this is documented in the streaming ADR and can be revisited if overhead is significant.
- The OpenAI SSE wire format produced by the proxy must match what the `openai` Python SDK and `curl` clients expect: role delta on the first chunk, content delta on subsequent chunks, empty delta with `finish_reason` on the final chunk.
- TLS is out of scope for this phase; streaming uses the same insecure gRPC channel as non-streaming.
- `/v1/completions` streaming is out of scope for this phase — only chat completions streaming is in scope. Completions streaming is deferred to Phase 6.
- The non-streaming gRPC path (Phase 4.2) remains the reference implementation; streaming extends it without replacing it.
