# Contract: Completions Proto Schema

**File**: `proto/vllm_grpc/v1/completions.proto`
**Version**: Phase 6
**Status**: Authoritative design-time spec — implement exactly as written

---

## Full Proto Text

```proto
syntax = "proto3";

package vllm_grpc.v1;

service CompletionsService {
  rpc Complete       (CompletionRequest) returns (CompletionResponse);
  rpc CompleteStream (CompletionRequest) returns (stream CompletionStreamChunk);
}

message CompletionRequest {
  string model      = 1;
  int32  max_tokens = 2;
  optional float temperature = 3;
  optional float top_p       = 4;
  optional int64 seed        = 5;
  oneof input {
    string prompt        = 6;
    bytes  prompt_embeds = 7;
  }
}

message CompletionResponse {
  string generated_text    = 1;
  string finish_reason     = 2;
  int32  prompt_tokens     = 3;
  int32  completion_tokens = 4;
}

// One message per output token in a streaming response.
// finish_reason is "" on non-final chunks; "stop" or "length" on the final chunk.
message CompletionStreamChunk {
  string delta_text    = 1;
  string finish_reason = 2;
  int32  token_index   = 3;
}
```

---

## Field Semantics

### CompletionRequest.input (oneof)

Exactly one branch MUST be set:

| Branch | Type | Content |
|---|---|---|
| `prompt` | string | Plain UTF-8 text; tokenised server-side |
| `prompt_embeds` | bytes | Raw `torch.save()` output — `torch.Tensor` of dtype float32/bfloat16/float16, shape `[seq_len, hidden_size]` for the loaded model |

Setting both or neither is a client error; the frontend MUST return `INVALID_ARGUMENT` gRPC status.

### CompletionResponse

`generated_text` carries the complete generated string. `finish_reason` is `"stop"` (EOS token hit) or `"length"` (`max_tokens` limit hit).

### CompletionStreamChunk

`delta_text` is the incremental token string for this chunk. The final chunk has `finish_reason != ""` and `delta_text == ""`. All preceding chunks have `finish_reason == ""`.

---

## RPC Contracts

### Complete (unary)

- **Request timeout**: 120 s (frontend-side); caller may set shorter.
- **Error status codes**:
  - `INVALID_ARGUMENT` — neither or both `oneof input` branches set; invalid shape/dtype for `prompt_embeds`
  - `INTERNAL` — engine error during generation
  - `CANCELLED` — client cancelled the call

### CompleteStream (server-streaming)

- **Cancellation**: When the client cancels, the frontend MUST detect via `context.is_active()` before each yield and cancel the engine generation task within 2 s.
- **Error during stream**: The stream terminates with a non-OK gRPC status; no final `CompletionStreamChunk` is sent.
- **Normal termination**: The final chunk has `finish_reason != ""` and `delta_text == ""`; the stream closes with OK status.
