# Contract: `VllmGrpcClient` Streaming API

**Package**: `vllm-grpc-client` (`packages/client`)  
**Module**: `vllm_grpc_client.chat`

---

## `StreamChunk` dataclass

```python
@dataclass
class StreamChunk:
    delta_content: str       # incremental text; empty string on the final chunk
    finish_reason: str | None  # None on non-final; "stop" or "length" on final
    token_index: int         # zero-based; strictly increasing within a stream
```

**Exported from** `vllm_grpc_client` (`__init__.py`).

---

## `ChatClient.complete_stream()` method

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

**Returns**: An async generator that yields `StreamChunk` objects, one per output token. The final chunk has `finish_reason` set and `delta_content == ""`.

**Usage**:

```python
async with VllmGrpcClient("host:50051") as client:
    content = ""
    async for chunk in client.chat.complete_stream(
        messages=[{"role": "user", "content": "Hello!"}],
        model="Qwen/Qwen3-0.6B",
        max_tokens=100,
        seed=42,
    ):
        if chunk.delta_content:
            content += chunk.delta_content
            print(chunk.delta_content, end="", flush=True)
```

---

## Error behaviour

| Condition | Behaviour |
|-----------|-----------|
| Mid-stream gRPC error | `grpc.aio.AioRpcError` raised from the `async for` loop |
| Server unavailable at call time | `grpc.aio.AioRpcError` with `StatusCode.UNAVAILABLE` raised before first chunk |
| Generator abandoned mid-iteration | Underlying gRPC call is cancelled via generator finalizer; server-side generation stops within 2s |

**Contract**: The generator MUST NOT return silently on error — it MUST raise. Callers can catch `grpc.aio.AioRpcError` for typed error handling.

---

## `VllmGrpcClient` public surface (full, post-Phase-5)

```python
class VllmGrpcClient:
    def __init__(self, addr: str, timeout: float | None = None) -> None: ...
    async def __aenter__(self) -> VllmGrpcClient: ...
    async def __aexit__(self, *args: object) -> None: ...

    @property
    def chat(self) -> ChatClient: ...


class ChatClient:
    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float | None = None,
        top_p: float | None = None,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> ChatCompleteResult: ...  # unchanged from Phase 4.2

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float | None = None,
        top_p: float | None = None,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[StreamChunk]: ...  # NEW in Phase 5
```

---

## Exports from `vllm_grpc_client`

```python
from vllm_grpc_client import VllmGrpcClient, StreamChunk, ChatCompleteResult
```

---

## mypy compliance

All new types (`StreamChunk`, `complete_stream` signature) MUST pass `mypy --strict` with zero errors. The return type `AsyncIterator[StreamChunk]` must be imported from `collections.abc` (not `typing`) for Python 3.12 compatibility.
