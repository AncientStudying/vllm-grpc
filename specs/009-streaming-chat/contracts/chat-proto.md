# Contract: `proto/vllm_grpc/v1/chat.proto` (Phase 5 update)

**Status**: Authoritative design-time spec. Actual `.proto` file must match exactly before any implementation code references generated stubs.

---

## Full updated proto

```protobuf
syntax = "proto3";

package vllm_grpc.v1;

service ChatService {
  // Unary — unchanged from Phase 4.2
  rpc Complete (ChatCompleteRequest) returns (ChatCompleteResponse);

  // Server-streaming — NEW in Phase 5
  // One ChatStreamChunk per output token. Final chunk has finish_reason != "".
  rpc CompleteStream (ChatCompleteRequest) returns (stream ChatStreamChunk);
}

// Unchanged from Phase 4.2
message ChatMessage {
  string role    = 1;
  string content = 2;
}

// Unchanged from Phase 4.2
message ChatCompleteRequest {
  repeated ChatMessage messages    = 1;
  string               model       = 2;
  int32                max_tokens  = 3;
  optional float       temperature = 4;
  optional float       top_p       = 5;
  optional int64       seed        = 6;
}

// Unchanged from Phase 4.2
message ChatCompleteResponse {
  ChatMessage message           = 1;
  string      finish_reason     = 2;
  int32       prompt_tokens     = 3;
  int32       completion_tokens = 4;
}

// NEW in Phase 5 — one per output token in a streaming response
message ChatStreamChunk {
  string delta_content = 1;  // incremental text; empty on the final chunk
  string finish_reason = 2;  // "" on non-final; "stop" or "length" on final
  int32  token_index   = 3;  // zero-based; strictly increasing within a stream
}
```

---

## Change summary

| Item | Change |
|------|--------|
| `ChatStreamChunk` message | **Added** |
| `CompleteStream` RPC | **Added** (server-streaming) |
| All other messages / RPCs | Unchanged |

---

## Constraints

- `make proto` MUST be run and generate clean stubs before any code in `frontend`, `proxy`, or `client` references `chat_pb2.ChatStreamChunk` or `chat_pb2_grpc.ChatServiceStub.CompleteStream`.
- CI proto-stub check (`make proto` produces no diff) MUST pass.
- Generated stubs MUST NOT be committed to the repository (Constitution I).
