# Contract: ChatService gRPC (proto/vllm_grpc/v1/chat.proto)

**Source file**: `proto/vllm_grpc/v1/chat.proto`
**Generated stubs**: `packages/gen/src/vllm_grpc/v1/chat_pb2{_grpc}.py` (gitignored)
**Build command**: `make proto`

---

## Service Definition

```protobuf
syntax = "proto3";

package vllm_grpc.v1;

service ChatService {
  rpc Complete (ChatCompleteRequest) returns (ChatCompleteResponse);
}
```

**`Complete`** — unary RPC. The proxy calls this once per non-streaming chat completion request
and awaits the full response. Streaming RPCs are not defined in this phase.

---

## Message Definitions

```protobuf
message ChatMessage {
  string role    = 1;   // "user", "assistant", or "system"
  string content = 2;   // UTF-8 text
}

message ChatCompleteRequest {
  repeated ChatMessage messages  = 1;   // ordered conversation history; min 1
  string               model     = 2;   // model name (e.g. "Qwen/Qwen3-0.6B")
  int32                max_tokens = 3;  // must be > 0
  optional float       temperature = 4; // defaults to 1.0 if absent
  optional float       top_p       = 5; // defaults to 1.0 if absent
  optional int64       seed        = 6; // absent = non-deterministic
}

message ChatCompleteResponse {
  ChatMessage message           = 1;   // role="assistant", content=generated text
  string      finish_reason     = 2;   // "stop" or "length"
  int32       prompt_tokens     = 3;   // tokens in the prompt
  int32       completion_tokens = 4;   // tokens generated
}
```

---

## Transport

- **Protocol**: gRPC over HTTP/2, insecure (no TLS in Phase 3)
- **Default port**: 50051 (configurable via `FRONTEND_PORT` env var)
- **Deadline**: proxy enforces a per-call timeout (default: 30 seconds); frontend does not set
  a server-side timeout in this phase
- **Retry**: no retries in Phase 3; proxy propagates gRPC errors as HTTP 502

---

## Error Handling

| Condition | gRPC Status | Proxy HTTP Response |
|---|---|---|
| Frontend not reachable | `UNAVAILABLE` | 502 with JSON error |
| Deadline exceeded | `DEADLINE_EXCEEDED` | 504 with JSON error |
| Model not loaded / bad request | `INVALID_ARGUMENT` | 422 with JSON error |
| Unexpected internal error | `INTERNAL` | 500 with JSON error |
