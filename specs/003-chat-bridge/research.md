# Research: Phase 3 — Minimal Non-Streaming Chat Completion Bridge

**Branch**: `003-chat-bridge`
**Date**: 2026-04-30
**Purpose**: Resolve design questions before implementation begins.

---

## R1: Proto Message Design for `ChatService.Complete`

### Decision

```protobuf
syntax = "proto3";
package vllm_grpc.v1;

service ChatService {
  rpc Complete (ChatCompleteRequest) returns (ChatCompleteResponse);
}

message ChatMessage {
  string role    = 1;
  string content = 2;
}

message ChatCompleteRequest {
  repeated ChatMessage messages = 1;
  string               model    = 2;
  int32                max_tokens = 3;
  optional float       temperature = 4;
  optional float       top_p       = 5;
  optional int64       seed        = 6;
}

message ChatCompleteResponse {
  ChatMessage message          = 1;
  string      finish_reason    = 2;
  int32       prompt_tokens    = 3;
  int32       completion_tokens = 4;
}
```

### Rationale

`temperature`, `top_p`, and `seed` are `optional` (proto3 optional / `oneof`-backed presence
tracking) so the frontend can distinguish "caller did not set this" from "caller set it to zero."
This matters for `seed`: a missing seed means non-deterministic generation; `seed = 0` means
seed is explicitly 0 (deterministic). Using `optional` avoids a sentinel value convention.

`max_tokens` is a required positive integer with no sane "not set" semantics — a zero value
would mean "generate zero tokens" and is an error, so a plain `int32` is fine.

`role` is a plain string rather than an enum so the proto is forward-compatible if new roles
(e.g., `tool`) are added in later phases without a proto change.

The response carries only what's needed to construct an OpenAI-compatible JSON body: the
assistant message, finish reason, and token counts. ID, timestamp, and model echo are added
by the proxy using local context.

### Alternatives Considered

- **Enum for role**: Stricter but requires a proto change to add roles in Phase 6. Rejected.
- **Wrapper types (`google.protobuf.FloatValue`)**: Equivalent to `optional float` but adds a
  dependency on the `google/protobuf/wrappers.proto` import. Rejected in favour of proto3
  optional which is cleaner and natively supported in protobuf 3.15+.
- **Including system fields (id, created, model) in the response proto**: The proxy generates
  these locally; they don't need to round-trip through the frontend. Rejected to keep the RPC
  surface minimal.

---

## R2: Using `AsyncLLM.generate()` for Non-Streaming Completion

### Decision

```python
async def _generate_complete(
    engine: AsyncLLM,
    prompt: str,
    params: SamplingParams,
    request_id: str,
) -> RequestOutput:
    final: RequestOutput | None = None
    async for output in engine.generate(prompt, params, request_id=request_id):
        final = output
    assert final is not None
    return final
```

- `final.outputs[0].text` → generated text
- `final.outputs[0].finish_reason` → `"stop"` or `"length"`
- `len(final.prompt_token_ids)` → prompt token count
- `len(final.outputs[0].token_ids)` → completion token count

### Rationale

`AsyncLLM.generate()` is an `AsyncGenerator[RequestOutput, None]`. Each yielded `RequestOutput`
represents the accumulated generation state. The generator ends when `output.finished is True`.
For non-streaming, consuming the full generator and taking the last output is the correct pattern.
The frontend keeps the async generator loop minimal and immediately returns the completed output
to the gRPC servicer.

`request_id` must be unique per call; the frontend generates a UUID per RPC invocation.

### vLLM version note

The `AsyncLLM` class exists in both vLLM 0.11.0 (macOS dev) and 0.20.0 (Modal A10G). The
`generate()` async generator pattern is stable across these versions. `SamplingParams` fields
(`max_tokens`, `temperature`, `top_p`, `seed`) are present in both versions.

### Alternatives Considered

- **Using the synchronous `LLM` class**: Blocks the event loop. `AsyncLLM` is the correct choice
  for an asyncio gRPC server. Rejected.
- **Using `engine.generate()` with `request_id` None**: Not allowed; vLLM requires a non-empty
  `request_id` for request tracking. Rejected.

---

## R3: Chat Template — Translating `ChatMessage` List to a vLLM Prompt

### Decision

Use the tokenizer's `apply_chat_template()` method to convert the messages list to a prompt
string. The tokenizer is loaded once at frontend startup alongside `AsyncLLM`.

```python
from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained(model_name)

def messages_to_prompt(messages: list[dict[str, str]]) -> str:
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
```

For Qwen3-0.6B, this produces the `<|im_start|>` / `<|im_end|>` format expected by the model.

### Rationale

vLLM's own OpenAI server applies the chat template via the model's tokenizer before calling
the engine. Replicating this is the correct approach for a faithful bridge. The `transformers`
package is a transitive dependency of `vllm`, so no new dependency is added. The tokenizer is
loaded once at startup to avoid per-request overhead.

`tokenize=False` returns a string rather than token IDs, which is passed directly to
`AsyncLLM.generate()` as a `TextPrompt`.

### Alternatives Considered

- **Hardcoding the Qwen3 template**: Fragile across model versions; rejected.
- **Passing messages directly to AsyncLLM**: vLLM's low-level `generate()` takes a prompt string
  or token IDs, not a messages list; the chat template step is not optional. Rejected.
- **Using vLLM's internal tokenizer accessor**: `AsyncLLM` exposes `engine.get_tokenizer()` as
  an async method in 0.20.0 but not in 0.11.0. Rejected in favour of loading the tokenizer
  independently for cross-version compatibility.

---

## R4: Integration Test Strategy for CI (No GPU)

### Decision

Create a `FakeChatServicer` — a minimal gRPC servicer that implements `ChatService.Complete`
and returns a hardcoded `ChatCompleteResponse` without importing or starting vllm.

The integration test fixture:
1. Starts a `grpc.aio.server` with `FakeChatServicer` on an OS-assigned ephemeral port.
2. Configures the proxy app's gRPC client to connect to that port.
3. Sends an HTTP POST to the proxy via `httpx.AsyncClient(app=..., base_url=...)`.
4. Asserts the response is valid OpenAI-compatible JSON.

This exercises every translation step (JSON → proto → FakeServicer → proto → JSON) without
any GPU or vllm import in the CI environment.

A separate "live" test (marked `pytest.mark.live`, skipped in CI) can optionally be run
locally with a real frontend and Modal backend.

### Rationale

The integration test validates the complete proxy → gRPC → servicer → JSON path. The only
component replaced by a fake is the vLLM engine itself — every layer above it is real. This
gives high confidence in translation correctness while keeping CI cheap and fast.

### Alternatives Considered

- **Mocking the gRPC stub in proxy unit tests only**: Tests the proxy in isolation but not the
  gRPC wire format or servicer translation. The integration test is still needed. Rejected as
  a sole strategy.
- **Using a recorded gRPC fixture (`pytest-recording`)**: Requires a real backend run to record.
  Adds a third-party test dependency. Rejected in favour of the simpler `FakeChatServicer`.
- **Running vllm in CPU mode in CI**: vllm 0.11.0 has a broken transformers compatibility on
  macOS (per Phase 2 findings); CPU mode is not viable. Rejected.

---

## R5: OpenAI Chat Completions JSON Response Format

### Decision

The proxy constructs the response as:

```json
{
  "id": "chatcmpl-<uuid4>",
  "object": "chat.completion",
  "created": <unix_timestamp_int>,
  "model": "<model field from request>",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "<generated text>"
      },
      "finish_reason": "<stop|length>"
    }
  ],
  "usage": {
    "prompt_tokens": <int>,
    "completion_tokens": <int>,
    "total_tokens": <int>
  }
}
```

`id`, `object`, `created`, and `model` are generated by the proxy using local context (UUID,
literal string, `time.time()`, and the `model` field echoed from the request). Token counts
come from the proto response fields `prompt_tokens` and `completion_tokens`.

### Rationale

This is the minimal set of fields that the `openai` Python SDK's `ChatCompletion` Pydantic model
requires to parse successfully. Omitting optional fields (e.g., `system_fingerprint`, `logprobs`)
does not cause an SDK parse error — they default to `None`. Including only required fields keeps
the response minimal and avoids inventing values for fields the frontend doesn't compute.

### Alternatives Considered

- **Including `system_fingerprint`**: No meaningful value to include; the openai SDK tolerates
  its absence. Rejected.
- **Letting the frontend generate the response ID**: The ID is a proxy-layer concern (request
  tracking); the frontend need not know about it. Rejected.
