# Data Model: Phase 3 — Minimal Non-Streaming Chat Completion Bridge

**Branch**: `003-chat-bridge`
**Date**: 2026-04-30

## Overview

Phase 3 introduces no persistent storage. All data is transient — a single request/response cycle
per call. The data model describes the shapes flowing through each layer of the bridge and the
translation rules between them.

---

## Entities

### ChatMessage

A single turn in a conversation.

| Field   | Type     | Constraints                          | Source                    |
|---------|----------|--------------------------------------|---------------------------|
| role    | string   | one of `"user"`, `"assistant"`, `"system"` | caller-supplied (proxy) / frontend-generated (response) |
| content | string   | non-empty                            | caller-supplied / model output |

**Note**: Additional roles (`tool`, `function`) are not supported in this phase and will be
ignored without error if present in the request.

---

### ChatCompleteRequest (internal proto representation)

The request crossing the proxy → frontend gRPC boundary.

| Field       | Type              | Required | Default  | Notes                          |
|-------------|-------------------|----------|----------|--------------------------------|
| messages    | list[ChatMessage] | yes      | —        | Minimum 1 message              |
| model       | string            | yes      | —        | Model name, echoed in response |
| max_tokens  | int32             | yes      | —        | Must be > 0                    |
| temperature | float (optional)  | no       | 1.0      | Applied by frontend if absent  |
| top_p       | float (optional)  | no       | 1.0      | Applied by frontend if absent  |
| seed        | int64 (optional)  | no       | None     | None → non-deterministic       |

---

### ChatCompleteResponse (internal proto representation)

The response crossing the frontend → proxy gRPC boundary.

| Field             | Type       | Notes                             |
|-------------------|------------|-----------------------------------|
| message           | ChatMessage | role always `"assistant"` |
| finish_reason     | string     | `"stop"` or `"length"`            |
| prompt_tokens     | int32      | Count of tokens in the prompt     |
| completion_tokens | int32      | Count of newly generated tokens   |

---

### OpenAIChatRequest (external REST representation at proxy)

The JSON body the proxy accepts on `POST /v1/chat/completions`. Validated by the proxy before
translation to proto.

| Field       | Type              | Required | Validation                        |
|-------------|-------------------|----------|-----------------------------------|
| model       | string            | yes      | non-empty                         |
| messages    | list[object]      | yes      | minimum 1 item; each has `role` + `content` |
| max_tokens  | integer           | yes      | > 0                               |
| temperature | float             | no       | 0.0 – 2.0                         |
| top_p       | float             | no       | 0.0 – 1.0                         |
| seed        | integer           | no       | any int64                         |
| stream      | boolean           | no       | if `true` → 501 Not Implemented   |

Fields not listed above are accepted but silently ignored.

---

### OpenAIChatResponse (external REST representation at proxy)

The JSON body the proxy returns for a successful non-streaming request.

| Field                        | Type    | Source                                      |
|------------------------------|---------|---------------------------------------------|
| id                           | string  | `"chatcmpl-" + uuid4()` (proxy-generated)  |
| object                       | string  | literal `"chat.completion"`                 |
| created                      | integer | `int(time.time())` at response construction |
| model                        | string  | echoed from request `model` field           |
| choices[0].index             | integer | always `0`                                  |
| choices[0].message.role      | string  | `"assistant"`                               |
| choices[0].message.content   | string  | `ChatCompleteResponse.message.content`      |
| choices[0].finish_reason     | string  | `ChatCompleteResponse.finish_reason`        |
| usage.prompt_tokens          | integer | `ChatCompleteResponse.prompt_tokens`        |
| usage.completion_tokens      | integer | `ChatCompleteResponse.completion_tokens`    |
| usage.total_tokens           | integer | `prompt_tokens + completion_tokens`         |

---

## Translation Rules

### Layer 1: OpenAIChatRequest → ChatCompleteRequest (proxy)

```
messages        → messages (ChatMessage list, preserving order)
model           → model
max_tokens      → max_tokens
temperature     → temperature (omit if not present in JSON)
top_p           → top_p (omit if not present in JSON)
seed            → seed (omit if not present in JSON)
```

Validation failures (empty messages, max_tokens ≤ 0, stream: true) return HTTP error responses
before any gRPC call is made.

### Layer 2: ChatCompleteRequest → vLLM Inputs (frontend)

```
messages                → tokenizer.apply_chat_template(messages, tokenize=False,
                          add_generation_prompt=True) → prompt string
max_tokens              → SamplingParams(max_tokens=...)
temperature             → SamplingParams(temperature=...) [default 1.0 if absent]
top_p                   → SamplingParams(top_p=...)       [default 1.0 if absent]
seed                    → SamplingParams(seed=...)         [omit if absent]
model                   → AsyncLLM model name (validated at startup)
```

### Layer 3: RequestOutput → ChatCompleteResponse (frontend)

```
output.outputs[0].text          → message.content
"assistant"                     → message.role
output.outputs[0].finish_reason → finish_reason
len(output.prompt_token_ids)    → prompt_tokens
len(output.outputs[0].token_ids)→ completion_tokens
```

### Layer 4: ChatCompleteResponse → OpenAIChatResponse (proxy)

```
message.content            → choices[0].message.content
message.role               → choices[0].message.role
finish_reason              → choices[0].finish_reason
prompt_tokens              → usage.prompt_tokens
completion_tokens          → usage.completion_tokens
uuid4()                    → id (proxy-generated)
int(time.time())           → created (proxy-generated)
request.model              → model (echoed from request)
```

---

## State Transitions

This phase has no state machine. Each `POST /v1/chat/completions` is a fully independent
stateless request. The proxy and frontend hold no per-request state between calls.

The only startup state is:
- **Frontend**: `AsyncLLM` instance + tokenizer, loaded once at `serve()` startup.
- **Proxy**: `GrpcChatClient` instance, created once at app startup (reused across requests).
