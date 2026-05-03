# Feature Specification: Completions API with Prompt Embeddings (Phase 6)

**Feature Branch**: `010-phase-6`
**Created**: 2026-05-03
**Status**: Draft
**Input**: User description: "phase 6"

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Non-Streaming Completions via Proxy (Priority: P1)

A developer sends `POST /v1/completions` to the proxy with either a plain text prompt or pre-computed prompt embedding tensors and receives a complete, non-streaming OpenAI-compatible completion response. Both input forms produce token-identical results when using a deterministic seed.

**Why this priority**: This is the foundational deliverable for Phase 6 — the Completions API endpoint is the final major API surface the project committed to supporting, and the prompt-embeddings path is the centrepiece wire-efficiency claim for this phase (binary tensor encoding vs JSON base64 expansion).

**Independent Test**: Run the proxy and frontend on Modal A10G. Send `POST /v1/completions` with (a) a plain text prompt and (b) pre-computed embeddings for the same prompt. Verify both return identical token sequences with `seed=42`.

**Acceptance Scenarios**:

1. **Given** the proxy and frontend are deployed, **When** a client sends `POST /v1/completions` with a plain text prompt, **Then** the response is an OpenAI-compatible completion object with `choices[0].text` populated.
2. **Given** the proxy and frontend are deployed, **When** a client sends `POST /v1/completions` with pre-computed prompt embedding tensors in the request body, **Then** the response is identical to the text-prompt response for the same input with the same seed.
3. **Given** a completions request with prompt embeddings, **When** the response is inspected at the network level, **Then** the embedding payload travels as raw binary bytes over the protobuf wire format (not JSON base64).
4. **Given** an invalid embedding shape or type, **When** the request is submitted, **Then** a clear error response is returned describing the problem without crashing the server.

---

### User Story 2 — Streaming Completions via Proxy (Priority: P2)

A developer sends `POST /v1/completions` with `"stream": true` and receives incremental token deltas via SSE as the model generates, for both text-prompt and prompt-embedding input forms.

**Why this priority**: The project's streaming infrastructure from Phase 5 is the reusable foundation here. Streaming completions via the proxy completes the API surface parity goal and allows streaming latency measurements for the prompt-embedding path.

**Independent Test**: Run `curl -N .../v1/completions` with `"stream": true` and a text prompt. Verify SSE deltas arrive incrementally. Concatenate the `text` fields from all deltas and confirm they equal the non-streaming response for the same seed.

**Acceptance Scenarios**:

1. **Given** the proxy and frontend are running, **When** a client sends a streaming completions request with a text prompt, **Then** SSE delta events arrive before generation is complete (first token visible before full response).
2. **Given** a streaming completions request with prompt embeddings, **When** the stream is consumed, **Then** token deltas arrive incrementally and concatenate to the same result as non-streaming with the same seed.
3. **Given** a streaming completions request in progress, **When** all tokens are generated, **Then** the stream terminates with `data: [DONE]` and the connection closes cleanly.
4. **Given** a streaming request in progress, **When** the client disconnects mid-stream, **Then** the backend generation task is cancelled within 2 seconds.

---

### User Story 3 — Direct gRPC Access via Client Library (Priority: P3)

A Python developer uses the `VllmGrpcClient` library to send completions requests — including native binary prompt embedding tensors — directly to the gRPC frontend, bypassing the REST proxy entirely.

**Why this priority**: The client library must support the completions path to complete the "three access paths" story (REST-native, gRPC via proxy, gRPC direct). The direct path also provides the cleanest wire-size comparison: tensor bytes in vs token strings out, with no base64 encoding anywhere in the call chain.

**Independent Test**: Instantiate `VllmGrpcClient`, call `client.completions.complete(prompt_embeds=...)` with pre-computed embeddings, verify the returned completion matches the proxy-path result for the same seed. No proxy process required.

**Acceptance Scenarios**:

1. **Given** a running frontend, **When** a developer calls `client.completions.complete(prompt="...")`, **Then** a typed completion object is returned without constructing any protobuf messages directly.
2. **Given** pre-computed embedding tensors, **When** a developer calls `client.completions.complete(prompt_embeds=...)`, **Then** the embeddings are sent as raw binary — no base64 encoding — and the result matches the proxy-path output for the same seed.
3. **Given** a mid-request server error, **When** the call returns, **Then** a typed exception is raised with a meaningful message rather than a silent empty result.
4. **Given** the client is used as a context manager, **When** the context exits, **Then** the underlying connection is torn down cleanly with no resource leaks.

---

### User Story 4 — Wire-Size Efficiency Benchmark (Priority: P4)

The benchmark harness measures and reports wire size (bytes per request and per response) for text-prompt versus prompt-embedding inputs across all three access paths (REST-native, gRPC via proxy, gRPC direct), demonstrating the binary encoding efficiency advantage for the embedding path.

**Why this priority**: This is the centrepiece measurement for Phase 6's contribution to the wire-overhead thesis. JSON base64-encodes binary tensors with ~33% bloat; protobuf sends them as raw bytes. The benchmark must report this honestly regardless of outcome.

**Independent Test**: Run `make bench-modal` with both a text-prompt corpus and a prompt-embedding corpus. Verify `docs/benchmarks/phase-6-completions-comparison.md` contains wire-size numbers for both input types across all three paths.

**Acceptance Scenarios**:

1. **Given** a completed benchmark run, **When** the report is generated, **Then** wire-size numbers (bytes per request and per response) are present for text-prompt and prompt-embedding inputs across REST-native, gRPC-proxy, and gRPC-direct paths.
2. **Given** wire-size numbers for prompt embeddings, **When** compared between the REST-native path (base64) and the gRPC paths (binary), **Then** the protobuf encoding advantage is quantified and honestly reported.
3. **Given** latency numbers for the prompt-embedding path, **When** compared against the Phase 5 streaming baselines, **Then** the completions latency is within an explainable range.

---

### Edge Cases

- What happens when `prompt_embeds` is provided alongside `prompt`? The system must reject ambiguous dual-input requests with a clear error.
- What happens when the embedding tensor has the wrong shape for the loaded model (e.g., hidden-dim mismatch)? A descriptive error must be returned, not a crash.
- What happens when the embedding tensor is serialised as the wrong dtype? The system must surface the error at decode time, before passing to the engine.
- What happens when `max_tokens` is not provided? The request must use a safe default and not hang indefinitely.
- What happens when streaming and non-streaming completions requests are concurrent? Both must coexist without interference with chat completion traffic.
- What happens when the Modal deployment cold-starts mid-request? Cold-start latency must be excluded from reported benchmark numbers and noted in run metadata.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST expose `POST /v1/completions` via the proxy, accepting a plain text `prompt` field and returning an OpenAI-compatible completion response.
- **FR-002**: The system MUST accept pre-computed prompt embedding tensors as an alternative input form on `POST /v1/completions`; the proxy MUST forward embeddings to the frontend as raw binary (not re-encoded as text).
- **FR-003**: `POST /v1/completions` with `"stream": true` MUST produce OpenAI-compatible SSE deltas for both text-prompt and prompt-embedding inputs, terminating with `data: [DONE]`.
- **FR-004**: Prompt-embedding requests with the same seed MUST produce token-identical output to text-prompt requests constructed from the same token sequence.
- **FR-005**: The gRPC client library MUST expose a `completions.complete()` method that accepts either a plain text prompt or a native embedding tensor and returns a typed completion object; callers MUST NOT construct protobuf messages directly.
- **FR-006**: The client library MUST transmit embedding tensors as raw binary bytes with no intermediate base64 encoding in the client-to-frontend path.
- **FR-007**: Mid-request server errors MUST surface as typed exceptions from the client library, not as silent empty results.
- **FR-008**: Invalid embedding inputs (wrong shape, wrong dtype, simultaneous `prompt` + `prompt_embeds`) MUST return descriptive error responses without crashing the server.
- **FR-009**: Client disconnection during a streaming completions request MUST cancel the backend generation task within 2 seconds.
- **FR-010**: The benchmark harness MUST report wire-size bytes per request and per response for text-prompt and prompt-embedding inputs across all three access paths (REST-native, gRPC-proxy, gRPC-direct).
- **FR-011**: `mypy --strict` MUST pass across all modified packages with no new suppressions.
- **FR-012**: The completions API MUST coexist with the chat completions API without mutual interference under concurrent load.
- **FR-013**: The CI benchmark PR comment MUST include Modal baseline summaries from all completed phases (Phase 4.2 non-streaming three-way comparison, Phase 5 streaming comparison, Phase 6 completions comparison), not only the most recent phase.

### Key Entities

- **Text Prompt**: A plain string submitted as the completion input; tokenised server-side.
- **Prompt Embedding Tensor**: A pre-computed float-point tensor of shape `[seq_len, hidden_size]` representing the full embedding sequence; bypasses server-side tokenisation.
- **CompletionRequest**: The full set of completion parameters including the input form (text or embeddings), generation controls (`max_tokens`, `temperature`, `seed`, etc.), and streaming flag.
- **CompletionResponse**: A non-streaming OpenAI-compatible response containing the generated text, token counts, finish reason, and request metadata.
- **CompletionChunk**: A single SSE delta event in a streaming completions response, carrying an incremental token string and finish reason.
- **WireSize**: The measured byte count of a serialised request or response on the network, used to quantify encoding efficiency.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A text-prompt and the equivalent prompt-embedding request for the same input and seed produce token-identical completions, verified for at least 10 distinct inputs.
- **SC-002**: Wire size of a prompt-embedding request via the gRPC-direct path is strictly smaller than the equivalent request via the REST-native path (which base64-encodes the embedding); the difference is reported in the benchmark with an honest methodology note.
- **SC-003**: Streaming completions via the proxy begin delivering tokens before the full completion is generated (TTFT < total response latency), for both text-prompt and prompt-embedding inputs.
- **SC-004**: Client library completions requests complete end-to-end against the Modal A10G frontend without any proxy process running.
- **SC-005**: `make bench-modal` produces `docs/benchmarks/phase-6-completions-comparison.md` with wire-size and latency columns for both input types across all three paths, without manual steps beyond a single command.
- **SC-006**: All packages pass `mypy --strict` with zero new suppressions after Phase 6 changes.
- **SC-007**: Concurrent completions and chat completions requests (at least 4 concurrent each) complete without error or interference.

## Assumptions

- The compute environment is Modal A10G (CUDA), as decided in Phase 2 (ADR 0001). Prompt embedding support requires a CUDA GPU backend; macOS is excluded for GPU-accelerated embedding inference.
- vLLM's V1 engine is the target. V0 was removed in vLLM 0.11.0; the prompt-embeds feature is available via the `--enable-prompt-embeds` server flag on the target version (vLLM 0.20.0 on Linux/CUDA).
- Prompt embeddings are pre-computed by the client before being sent. The bridge does not perform its own embedding computation — it only transmits and decodes.
- The embedding tensor wire format follows vLLM's existing convention: a serialised float-point tensor transmitted as raw bytes. The proxy accepts the tensor from clients and passes it through without re-encoding.
- Streaming completions reuse the Phase 5 server-streaming RPC pattern without structural changes to the frontend or proxy streaming machinery.
- The Completions proto schema lives in a new `completions.proto` file, separate from the existing `chat.proto`.
- The benchmark corpus for prompt embeddings is generated from the same chat-template-formatted token IDs used for the text-prompt baseline, so text-prompt and embedding inputs are directly comparable.
- Cold-start latency for Modal deployments is excluded from all reported benchmark numbers and recorded separately in run metadata.
- Mobile, browser, and non-Python consumers are out of scope. The target audience is Python ML practitioners.
