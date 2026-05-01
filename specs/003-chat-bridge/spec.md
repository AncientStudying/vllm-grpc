# Feature Specification: Phase 3 — Minimal Non-Streaming Chat Completion Bridge

**Feature Branch**: `003-chat-bridge`
**Created**: 2026-04-30
**Status**: Draft
**Input**: User description: "Phase 3 — Minimal Non-Streaming Chat Completion Bridge (from docs/PLAN.md)"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - End-to-End Non-Streaming Chat Completion (Priority: P1)

A developer sends a standard non-streaming chat completion request to the proxy server. The proxy translates it into an internal binary format, forwards it to the language model frontend, and returns an OpenAI-compatible JSON response. This is the core architectural proof: the full proxy → frontend → model → proxy round-trip works end-to-end.

**Why this priority**: This is the "early successful demonstration" milestone for the entire project. All other deliverables in this phase are supporting evidence for this one working scenario. No later phase can be planned or trusted without it.

**Independent Test**: Start proxy and frontend, issue `POST /v1/chat/completions` with a single user message and no streaming flag. Receive an OpenAI-compatible response with a non-empty `choices[0].message.content`.

**Acceptance Scenarios**:

1. **Given** proxy and frontend are both running, **When** a POST request is sent to `/v1/chat/completions` with a single user message, model name, max_tokens, and no `stream` field, **Then** the response is valid OpenAI-compatible JSON containing at least one choice with a non-empty content string.
2. **Given** proxy and frontend are both running, **When** the same request is sent twice with a fixed `seed` value, **Then** both responses contain identical `choices[0].message.content` strings.
3. **Given** the system is under load (two sequential requests), **When** each request completes, **Then** the response fields `id`, `model`, `usage.prompt_tokens`, `usage.completion_tokens`, and `choices[0].finish_reason` are all populated.

---

### User Story 2 - OpenAI SDK Compatibility (Priority: P2)

A developer points the `openai` Python SDK at the proxy by setting `base_url` to the proxy's address. They call `client.chat.completions.create()` exactly as they would against the real OpenAI API (non-streaming). The proxy accepts the request and returns a response the SDK can parse without errors.

**Why this priority**: SDK compatibility validates that the proxy's JSON surface is correct, not just superficially similar. It also demonstrates the core value proposition — existing OpenAI client code works unchanged.

**Independent Test**: Run `scripts/python/chat-nonstreaming.py` against a live proxy + frontend. The script completes without raising an `openai.APIError` and prints the model's reply.

**Acceptance Scenarios**:

1. **Given** proxy is running, **When** the Python example script runs with `base_url` pointing at the proxy, **Then** `client.chat.completions.create()` returns without error and the completion text is printed.
2. **Given** the Python example script runs with a fixed `seed`, **When** run twice, **Then** the printed completion is identical both times.

---

### User Story 3 - Streaming Rejection (Priority: P3)

A developer sends a chat completion request with `stream: true`. The proxy immediately returns a clear, human-readable error indicating that streaming is not yet implemented in this phase — it does not crash, hang, or return a garbled response.

**Why this priority**: Streaming is explicitly deferred to Phase 5. Without a clear rejection, a developer debugging a streaming-enabled client would see a confusing failure rather than an actionable message.

**Independent Test**: Send `POST /v1/chat/completions` with `"stream": true`. Receive an HTTP error response (4xx or 501) with a JSON body containing an `error.message` field that references "not yet implemented" or similar.

**Acceptance Scenarios**:

1. **Given** proxy is running, **When** a request with `"stream": true` is sent, **Then** the response is an HTTP 501 with a JSON body containing a human-readable error message.
2. **Given** the streaming rejection path is exercised, **When** the error response is received, **Then** the proxy continues running normally and can serve subsequent non-streaming requests.

---

### User Story 4 - Fast Local Demo (Priority: P3)

A developer checks out the repository on a fresh M2 MacBook Pro and, following documented instructions, brings up proxy and frontend and issues the first successful chat completion in under 2 minutes.

**Why this priority**: The Phase 3 exit criterion in `docs/PLAN.md` explicitly requires a sub-2-minute cold-start demo. This validates that the setup is not fragile or underdocumented.

**Independent Test**: Time the sequence: install deps → start frontend → start proxy → run `scripts/curl/chat-nonstreaming.sh`. Total wall-clock time is under 2 minutes from a state where only `uv` and Python 3.12 are installed.

**Acceptance Scenarios**:

1. **Given** only `uv` and Python 3.12 are installed, **When** the documented startup sequence is followed, **Then** a successful chat completion is produced in under 2 minutes.
2. **Given** the curl example script is run against a live proxy + frontend, **Then** it prints a non-empty completion and exits 0.

---

### Edge Cases

- What happens if the frontend is not running when the proxy receives a request — does the proxy return a clean 502/503 or crash?
- What if the model returns an empty completion (finish_reason = length, zero tokens)? Does the proxy handle it gracefully?
- What if a request omits optional fields (`temperature`, `top_p`, `seed`) — are defaults applied correctly?
- What if `max_tokens` is set to a value larger than the model's context window?
- What if the `messages` array is empty or contains only a system message with no user turn?
- What if the `model` field names a model not loaded in the frontend?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The proxy MUST accept `POST /v1/chat/completions` requests and return OpenAI-compatible JSON responses.
- **FR-002**: The proxy MUST support the following request fields: `messages` (each with `role` and `content`), `model`, `max_tokens`, `temperature`, `top_p`, `seed`. All fields beyond this set MUST be ignored without error.
- **FR-003**: The proxy MUST reject any request containing `"stream": true` with an HTTP 501 status and a JSON body containing a human-readable `error.message`.
- **FR-004**: The proxy MUST translate accepted requests into the project's binary wire format and forward them to the frontend via the internal RPC channel; it MUST translate the frontend's response back into OpenAI-compatible JSON.
- **FR-005**: The frontend MUST accept translated requests, apply the sampling configuration from the request (model, max_tokens, temperature, top_p, seed), call the language model, and return the completion in the project's binary wire format.
- **FR-006**: The binary wire format MUST be defined in a schema file (`proto/vllm_grpc/v1/chat.proto`) before any implementation code references it; generated code MUST NOT be committed.
- **FR-007**: Unit tests MUST cover the translation from OpenAI JSON to the binary wire format, and from the binary wire format back to OpenAI JSON, in the proxy package.
- **FR-008**: Unit tests MUST cover the translation from the binary wire format to sampling parameters, and from the model output to the binary wire format response, in the frontend package.
- **FR-009**: An integration test MUST start proxy and frontend together, send a non-streaming chat request, and assert a valid OpenAI-compatible response is returned.
- **FR-010**: A curl example script (`scripts/curl/chat-nonstreaming.sh`) MUST demonstrate a successful non-streaming completion against a live proxy + frontend.
- **FR-011**: A Python example script (`scripts/python/chat-nonstreaming.py`) MUST demonstrate a successful non-streaming completion using the `openai` SDK with `base_url` pointed at the proxy.
- **FR-012**: With a fixed `seed`, two identical requests through the bridge MUST produce identical `choices[0].message.content` values.

### Key Entities

- **ChatMessage**: A single turn in the conversation; has a `role` (one of `user`, `assistant`, `system`) and a `content` string.
- **ChatCompletionRequest**: The full incoming request; contains an ordered list of `ChatMessage` objects and sampling parameters (`model`, `max_tokens`, `temperature`, `top_p`, `seed`).
- **ChatCompletionResponse**: The outgoing OpenAI-compatible response; contains a `choices` array where `choices[0].message` is a `ChatMessage` and `choices[0].finish_reason` is a string; also carries token usage counts.
- **BridgeRequest / BridgeResponse**: The internal binary-format equivalents of request and response, defined in the proto schema. These are the only representations that cross the proxy → frontend boundary.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A single-turn, non-streaming chat request through the bridge produces a non-empty, coherent completion — confirmed by the integration test and the curl/Python example scripts.
- **SC-002**: Two identical requests with a fixed `seed` produce identical `choices[0].message.content` — verified by the integration test.
- **SC-003**: A request with `stream: true` returns an HTTP 501 and a human-readable error message — verified by a dedicated test case.
- **SC-004**: Proxy and frontend start and serve a first request in under 2 minutes on the documented hardware, measured from the state where only `uv` and Python 3.12 are installed.
- **SC-005**: All unit tests and the integration test pass in CI (lint + type-check + tests, no GPU required).

## Assumptions

- The target language model is Qwen/Qwen3-0.6B. For local development the frontend connects to the Modal A10G environment chosen in ADR 0001; CI uses a lightweight stub or recorded fixture so no GPU is required for automated runs.
- `uv` and Python 3.12 are pre-installed on the dev machine (Phase 1 deliverable).
- No authentication is implemented; the proxy accepts all requests from any caller on the local network.
- Only the six request fields listed in FR-002 are required. Fields such as `n`, `logprobs`, `function_call`, `tools`, `response_format`, and others are out of scope for this phase and ignored without error.
- Multi-turn conversation history is passed through as-is from the caller; the proxy and frontend do not manage server-side conversation state.
- The `messages` array contains at least one message; the system validates this and returns an error for empty arrays.
- The proto schema file and generated stub build step are already partially scaffolded in Phase 1; this phase extends them for the chat service.
- `ruff` (lint + format) and `mypy --strict` are the enforced quality gates, consistent with the project constitution.
