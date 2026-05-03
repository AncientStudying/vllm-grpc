# ADR 0003: Streaming Chat Completions Design

**Date**: 2026-05-02  
**Status**: Accepted  
**Branch**: `009-streaming-chat`

## Context

Phase 5 adds server-streaming gRPC, SSE streaming via the proxy, and a streaming API to `VllmGrpcClient`. Several design choices were made that affect correctness, performance, and testability.

## Decisions

### 1. Chunk Granularity: One Proto Message Per Output Token

**Decision**: `ChatStreamChunk` carries a single token's delta. The RPC yields one message per token from `engine.generate()`.

**Rationale**: Minimises TTFT — the client receives each token the moment the engine emits it. Simpler implementation: one `yield` per engine output. Consistent with the OpenAI SSE convention where each `data:` event carries one token.

**Alternative considered**: Batching N tokens per chunk reduces gRPC framing overhead at high throughput but increases TTFT and complicates TPOT measurement. Rejected because TTFT is the primary metric this phase aims to measure.

### 2. Error Encoding: gRPC Status Codes → SSE Error Event

**Decision**: Mid-stream errors in the frontend surface as gRPC status codes (`INTERNAL` with a human-readable `details()` string). The proxy translates this to a final SSE error event (`data: {"error": {...}}\n\n`) and closes the stream without `data: [DONE]`. The client library re-raises `grpc.aio.AioRpcError` from the async generator.

**Rationale**: gRPC status codes are the correct mechanism for signalling RPC errors. Using a separate error field on every `ChatStreamChunk` would add proto complexity for a rare code path. The SSE error event before stream close lets HTTP clients detect errors even after the `200 OK` header is sent.

**Alternative considered**: Silent truncation (no `[DONE]`, no error event). Rejected — FR-008 requires typed exceptions, not silent truncation.

### 3. Back-Pressure Model: Native Async Generator Yield

**Decision**: No explicit token buffering at any layer. The Python `yield` in the frontend servicer's `CompleteStream` async generator naturally pauses until the gRPC framework writes the chunk to the HTTP/2 stream and flow control credits are available. This propagates back-pressure from the client through the proxy to the engine.

**Rationale**: All layers are async generators or async iterators. `yield` suspends execution, making back-pressure an emergent property at zero implementation cost. No separate queue or semaphore is needed, satisfying FR-006 ("MUST NOT buffer output tokens unboundedly").

**Alternative considered**: Asyncio bounded queue between engine and gRPC writer — adds configurable parameters and implementation complexity with no benefit over native flow control.

### 4. Cancellation Semantics: asyncio CancelledError Chain

**Decision**: Cancellation propagates as a chain of `asyncio.CancelledError`:

1. **Client → Proxy**: FastAPI's `Request.is_disconnected()` is polled between SSE chunks. On disconnect, the proxy's SSE generator returns, causing `StreamingResponse` to stop iterating. The gRPC call object's `.cancel()` is called.
2. **Proxy → Frontend**: `grpc.aio` propagates the RPC cancellation to the servicer's context. The servicer's `CompleteStream` async generator receives `asyncio.CancelledError` at its next `yield`.
3. **Frontend → Engine**: `asyncio.CancelledError` propagates into `async for output in engine.generate(...)`, cancelling the in-progress vLLM request.

The 2-second cancellation budget (SC-003) is satisfied because all layers are non-blocking asyncio code; cancellation propagates within a single event loop cycle.

**Alternative considered**: Explicit `asyncio.Task.cancel()` with a watchdog timer — unnecessary given asyncio's natural propagation through async generators.
