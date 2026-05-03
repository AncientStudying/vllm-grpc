# Feature Specification: Enable Prompt Embeddings in gRPC Frontend

**Feature Branch**: `011-enable-prompt-embeds`
**Created**: 2026-05-03
**Status**: Draft
**Input**: Phase 6.1 — enable `enable_prompt_embeds=True` in `AsyncEngineArgs` so the gRPC-direct and proxy completion-embeds paths produce real inference results.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — gRPC-Direct Prompt-Embedding Completion (Priority: P1)

A developer using `VllmGrpcClient` sends a pre-computed prompt-embedding tensor directly to the gRPC frontend and receives a generated text completion. This is the primary value claim of Phase 6: bypassing the tokenizer with a raw embedding tensor sent over gRPC as binary bytes, with no base64 expansion.

**Why this priority**: The gRPC-direct path is the purest wire-efficiency demonstration. If the engine rejects the tensor, neither the latency numbers nor the wire-size comparison are meaningful.

**Independent Test**: Can be fully tested by sending a `CompletionRequest` with `prompt_embeds` set via `VllmGrpcClient.completions.complete(prompt_embeds=tensor)` against a live Modal-deployed frontend and confirming a non-empty generated text is returned.

**Acceptance Scenarios**:

1. **Given** a running gRPC frontend with `enable_prompt_embeds` enabled, **When** a client sends a `CompletionRequest` containing a valid float32 2-D tensor as `prompt_embeds`, **Then** the frontend returns a `CompletionResponse` with non-empty `generated_text` and `success=True`.
2. **Given** a running gRPC frontend, **When** a client sends a `CompletionRequest` with a malformed tensor (wrong dtype or wrong rank), **Then** the frontend returns a gRPC `INVALID_ARGUMENT` error without crashing.

---

### User Story 2 — Proxy Path Prompt-Embedding Completion (Priority: P2)

A developer using the OpenAI-compatible REST proxy sends a JSON completion request with `prompt_embeds` as a base64-encoded tensor in the request body. The proxy decodes it, forwards it as binary bytes via gRPC, and the frontend passes it to the vLLM engine.

**Why this priority**: The proxy path is the compatibility story — it allows standard OpenAI SDK clients to send prompt embeddings without writing gRPC code. It depends on P1 (the engine must accept embeddings).

**Independent Test**: Can be fully tested by sending `POST /v1/completions` with `{"prompt_embeds": "<base64>", "model": "...", "max_tokens": 50}` via curl or the `openai` SDK and confirming a completion is returned.

**Acceptance Scenarios**:

1. **Given** a running proxy connected to a prompt-embeddings-enabled frontend, **When** a REST client sends a completion request with a valid base64-encoded tensor as `prompt_embeds`, **Then** the proxy returns an OpenAI-format JSON completion response with generated text.
2. **Given** a running proxy, **When** a client sends `prompt_embeds` and `prompt` simultaneously, **Then** the proxy returns HTTP 422 with a clear error message.

---

### Edge Cases

- What happens when the tensor shape does not match the model's hidden dimension? → The engine raises an error; the frontend propagates it as gRPC `INTERNAL`.
- What happens when the tensor is all zeros or all NaN? → The engine processes it as-is (no frontend-level validation beyond dtype/rank checks already implemented).
- What happens when a text-prompt completion request is made with `enable_prompt_embeds=True` enabled in the engine? → Text-prompt requests are unaffected; the flag is additive.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The gRPC frontend MUST initialize vLLM's engine with prompt-embedding support enabled so that `{"prompt_embeds": tensor}` input is accepted by the v1 engine's renderer.
- **FR-002**: The gRPC frontend MUST accept `CompletionRequest` messages with a valid 2-D float tensor in the `prompt_embeds` field and return a `CompletionResponse` with generated text.
- **FR-003**: The gRPC frontend MUST accept `CompletionRequest` messages with a plain text `prompt` field and continue to work correctly (backward compatibility).
- **FR-004**: The proxy path MUST continue to correctly decode base64-encoded tensor bytes and forward them as binary in the gRPC `prompt_embeds` field (no change needed — already implemented).
- **FR-005**: The existing tensor validation (dtype must be float32/bfloat16/float16; tensor must be 2-D) MUST remain in place and return `INVALID_ARGUMENT` on violation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The `grpc-direct | completion-embeds` benchmark row shows `success=True` and a real `resp_bytes_mean` value (not N/A) when run against a Modal A10G deployment.
- **SC-002**: The `proxy | completion-embeds` benchmark row shows `success=True` and a real `resp_bytes_mean` value (not N/A).
- **SC-003**: All existing benchmark rows (`grpc-direct | text`, `proxy | text`, `rest`) continue to show `success=True` — no regressions.
- **SC-004**: `make check` (ruff + mypy --strict + pytest) passes green with no new errors.
- **SC-005**: The wire-size comparison between the REST (base64) path and the gRPC-direct (binary) path for prompt embeddings shows the expected ~33% reduction in request bytes for the gRPC-direct path.

## Assumptions

- The installed vLLM version on Modal (0.20.0) exposes `enable_prompt_embeds` as a valid `AsyncEngineArgs` parameter. This was confirmed by inspecting the locally-installed vLLM 0.19.0 (`AsyncEngineArgs.__init__` signature includes `enable_prompt_embeds: bool = False`).
- `AsyncLLMEngine` in vLLM 0.19/0.20 is a direct alias for `AsyncLLM` (the v1 engine). This was confirmed by reading `vllm/engine/async_llm_engine.py`: `AsyncLLMEngine = AsyncLLM`.
- The existing tensor decoding, validation, and proto encoding in Phase 6 are correct and require no changes.
- Enabling `enable_prompt_embeds=True` does not affect the behavior of text-prompt or token-ID-prompt completion requests.
- The benchmark corpus (pre-computed `.pt` files in `tools/benchmark/corpus/completions_embeds/`) is already in place from Phase 6 and does not need regeneration.
