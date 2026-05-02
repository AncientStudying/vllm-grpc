# Research: Streaming Chat Completions (Phase 5)

**Branch**: `009-streaming-chat` | **Date**: 2026-05-02

All unknowns resolved from existing codebase patterns, grpcio documentation, and OpenAI SSE wire-format specification. No external dependencies were unknown going into this phase.

---

## Decision 1: Proto chunk granularity and message shape

**Decision**: One `ChatStreamChunk` proto message per output token delta. Fields: `delta_content` (string), `finish_reason` (string, empty on non-final chunks), `token_index` (int32).

**Rationale**: Lowest possible TTFT — client sees each token the moment the engine emits it. Simple implementation: one `yield` per engine token. Consistent with the spec assumption (FR-004, spec §Assumptions). `finish_reason` reuses the empty-string sentinel that OpenAI itself uses on the wire, keeping the proto schema minimal.

**Alternatives considered**:
- Batching N tokens per chunk: reduces gRPC overhead at high throughput but increases TTFT, complicates benchmarking, and conflicts with FR-004's "yield as produced" requirement.
- Separate `is_last: bool` field: redundant with `finish_reason != ""`.
- Including `role` in every chunk: redundant (role is always "assistant"); moved to the SSE encoding layer in the proxy.

---

## Decision 2: Role encoding in streaming responses

**Decision**: Role ("assistant") is emitted only on the first SSE chunk by the proxy, encoded as `{"delta": {"role": "assistant", "content": ""}}`. The proto `ChatStreamChunk` carries no role field — role is a protocol-level constant for all assistant responses.

**Rationale**: Avoids shipping the role string on every chunk over gRPC. The proxy has full knowledge of the convention and applies it at SSE encoding time. Matches the OpenAI SSE wire format exactly (first chunk has role delta, subsequent chunks have content delta only).

**Alternatives considered**: Include `role` in the proto chunk — adds bytes to every message for a value that never changes.

---

## Decision 3: Error encoding in mid-stream failures

**Decision**: Frontend surfaces mid-stream errors as gRPC status codes (`INTERNAL` with a text `details()` string). The proxy translates this to closing the SSE stream without emitting `data: [DONE]`, then writes a final `data: {"error": {"message": "...", "type": "internal_error"}}\n\n`. The client library surfaces gRPC errors as a typed `grpc.aio.AioRpcError` re-raised from the async generator (or wrapped in a `VllmGrpcError` if the caller catches it).

**Rationale**: Fulfills FR-008 ("typed exceptions, not silent truncation"). Proxy error handling follows the same pattern as the existing non-streaming router (`chat_router.py`). SSE error event before stream close lets HTTP clients detect errors even after `200 OK` header is sent.

**Alternatives considered**: Silent truncation (no `[DONE]`, no error event) — rejected by FR-008. Including error in the proto chunk as a separate `error` field — adds proto complexity for a rare path; gRPC status codes are the correct mechanism.

---

## Decision 4: Cancellation model

**Decision**: Three-layer cancellation chain:

1. **Proxy → gRPC**: When `request.is_disconnected()` is detected (polled in an `asyncio.wait` with the SSE generator), the proxy's `StreamingResponse` generator raises `asyncio.CancelledError`. The proxy's gRPC call (`grpc.aio.UnaryStreamCall`) is cancelled via `.cancel()`.
2. **gRPC → frontend**: `grpc.aio` propagates the RPC cancellation as a `CANCELLED` status to the servicer. The servicer's `CompleteStream` async generator receives `asyncio.CancelledError` (injected by grpcio's aio layer at the next `yield`).
3. **Frontend → engine**: `asyncio.CancelledError` propagates into `async for output in engine.generate(...)`, causing the generator to be garbage-collected / cancelled. vLLM's `AsyncLLM` cancels the in-progress request internally.

**2-second budget**: The entire chain is `asyncio`-based and non-blocking; cancellation propagates within a single event loop tick. The 2-second budget (SC-003) is easily satisfied.

**Rationale**: Uses the natural cancellation semantics of asyncio and grpcio-aio. No polling loops required. The `context.is_active()` check in the frontend is a defence-in-depth guard for edge cases where the framework's propagation is delayed.

**Alternatives considered**: Explicit `asyncio.Task.cancel()` with a 2-second timeout watchdog — unnecessary complexity given asyncio's natural propagation.

---

## Decision 5: Back-pressure model

**Decision**: No explicit buffering at any layer. Back-pressure propagates naturally:

- Client reads SSE events slowly → TCP recv buffer fills → HTTP server's `send()` blocks → `StreamingResponse` generator's `yield` blocks → gRPC `async for chunk in call` blocks → grpcio HTTP/2 flow control credits exhaust → frontend's `yield chunk` (in `CompleteStream`) blocks → vLLM `engine.generate()` iteration pauses.

**Rationale**: All layers are async generators or async iterators. The Python `yield` keyword naturally suspends at each layer. No token buffering means constant memory usage regardless of client speed. Satisfies FR-006 ("MUST NOT buffer output tokens unboundedly").

**Alternatives considered**: Asyncio queue with bounded size — adds complexity and a configurable parameter with no benefit over native back-pressure.

---

## Decision 6: TTFT and TPOT measurement approach

**Decision**:

- **HTTP targets (proxy, native)**: Use `httpx.AsyncClient.stream("POST", ...)` context manager. Iterate `response.aiter_lines()`. Record `t_first` when the first `data: {...}` line (not `[DONE]`) is received. Record `t_each[]` for each subsequent `data:` line. TTFT = `t_first - t_request`. TPOT = `(t_last - t_first) / (token_count - 1)` if `token_count > 1`.
- **gRPC-direct target**: Iterate `client.chat.complete_stream(...)`. Record `t_first` on first yielded `StreamChunk`. TTFT = `t_first - t_request`. TPOT computed the same way.
- Store `ttft_ms`, `tpot_ms`, `token_count` in extended `RequestResult`. Compute P50/P95/P99 per target in `compute_summaries()`.

**Rationale**: Direct measurement at the API layer, not the network layer. `httpx` streaming is already a dependency. Consistent with how the existing runner measures end-to-end latency.

**Alternatives considered**: Packet-capture TTFT (via pcap) — too invasive and platform-dependent. Proxy-side header injection for TTFT — only covers the proxy path, not native or gRPC-direct.

---

## Decision 7: `VllmGrpcClient.chat.complete_stream()` API design

**Decision**:

```python
async def complete_stream(
    self,
    messages: list[dict[str, str]],
    model: str,
    max_tokens: int,
    temperature: float | None = None,
    top_p: float | None = None,
    seed: int | None = None,
    timeout: float | None = None,
) -> AsyncIterator[StreamChunk]:
    ...
```

Returns `AsyncIterator[StreamChunk]` where `StreamChunk` is a dataclass with:
- `delta_content: str` — incremental text for this chunk
- `finish_reason: str | None` — `None` on non-final chunks, `"stop"`/`"length"` on final
- `token_index: int` — zero-based position of this token

The method is an `async def` that `yield`s chunks, making it an async generator. Abandoning the generator mid-iteration (leaving the `async for` loop without `break` exhaustion) is handled via `asynccontextmanager` / generator finalizer calling `.cancel()` on the underlying gRPC call.

**Rationale**: Idiomatic Python async generator pattern. No context manager required from the caller. Consistent with `complete()` method shape. Fulfills FR-007.

**Alternatives considered**: Return a wrapper object with `.cancel()` — adds boilerplate for callers who just want `async for`. Use `contextlib.asynccontextmanager` — unnecessary since Python finalizes async generators automatically (PEP 525).

---

## Decision 8: Fake server extension for CI streaming tests

**Decision**: Extend `fake_server.py` with a `--streaming` flag (or detect `"stream": true` in the request body). When streaming, emit 3 synthetic SSE chunks with `asyncio.sleep(0.001)` between them, then `data: [DONE]`. The TTFT measurement in CI should be non-zero but deterministic.

**Rationale**: CI must be able to test the streaming benchmark runner code paths without a real GPU. The existing `bench-ci` target uses `fake_server.py`. Extending it preserves the existing CI pattern.

**Alternatives considered**: Separate fake streaming server module — unnecessary indirection; the existing module is simple enough to extend.

---

## Decision 9: gRPC servicer async generator pattern

**Decision**: Use the `grpcio` async generator servicer pattern for server-streaming RPCs:

```python
async def CompleteStream(
    self,
    request: chat_pb2.ChatCompleteRequest,
    context: grpc.aio.ServicerContext,
) -> AsyncIterator[chat_pb2.ChatStreamChunk]:
    ...
    async for output in self._engine.generate(...):
        if not context.is_active():
            return
        yield output_to_stream_chunk(output, token_index)
        token_index += 1
```

The `grpcio` aio layer handles calling this method as an async generator and writing each yielded message to the gRPC stream.

**Rationale**: The cleanest grpcio-aio pattern. The servicer base class stubs out server-streaming RPCs to accept async generators. No need to call `context.write()` manually.

**Alternatives considered**: `context.write()` loop — equivalent but more verbose; loses the `yield` back-pressure semantics.
