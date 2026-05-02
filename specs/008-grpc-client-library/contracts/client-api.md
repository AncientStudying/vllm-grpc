# Contract: vllm_grpc_client Public API

## Package Identity

- Package name: `vllm-grpc-client` (distribution) / `vllm_grpc_client` (import)
- Workspace path: `packages/client/`
- Runtime dependencies: `grpcio>=1.65`, `vllm-grpc-gen` (workspace)
- Ships `py.typed`; passes `mypy --strict` with zero suppressions for gen imports

---

## VllmGrpcClient

### Constructor

```python
VllmGrpcClient(addr: str, timeout: float = 30.0)
```

- `addr`: gRPC server address in `"host:port"` form (no scheme prefix)
- `timeout`: default per-call timeout in seconds; individual calls may override

### Context manager protocol

```python
async with VllmGrpcClient("localhost:50051") as client:
    ...
# channel is opened on __aenter__, closed on __aexit__
# __aexit__ is called even if the body raises; channel is always closed
```

### Sub-clients

```python
client.chat  # → ChatClient instance, bound to the shared channel
```

---

## ChatClient

Exposed as `VllmGrpcClient.chat`. Not instantiated directly by callers.

### complete()

```python
result = await client.chat.complete(
    messages:    list[dict[str, str]],  # required; each dict has "role" and "content"
    model:       str,                   # required
    max_tokens:  int,                   # required
    temperature: float | None = None,   # omitted if None
    top_p:       float | None = None,   # omitted if None
    seed:        int | None   = None,   # omitted if None
    timeout:     float | None = None,   # overrides client default when set
) -> ChatCompleteResult
```

**Behavior:**
- Maps `messages` → `repeated ChatMessage` in protobuf (role + content per item)
- Calls `ChatService.Complete` unary RPC
- Returns `ChatCompleteResult`; raises on error (see Error Handling below)

---

## ChatCompleteResult

```python
@dataclass
class ChatCompleteResult:
    content:           str   # assistant turn text
    role:              str   # always "assistant"
    finish_reason:     str   # "stop" | "length" | ...
    prompt_tokens:     int
    completion_tokens: int
```

Callers never import or construct protobuf message types directly.

---

## Error Handling

| Condition | Raised exception |
|-----------|-----------------|
| Server unreachable or connection refused | `grpc.aio.AioRpcError` with `StatusCode.UNAVAILABLE` |
| Call exceeds timeout | `grpc.aio.AioRpcError` with `StatusCode.DEADLINE_EXCEEDED` |
| Server returns non-OK status | `grpc.aio.AioRpcError` with the server's status code |
| Channel used after `__aexit__` | `RuntimeError` |

Callers are responsible for catching `grpc.aio.AioRpcError`. The library does not retry.

---

## Usage Example

```python
from vllm_grpc_client import VllmGrpcClient

async with VllmGrpcClient("tcp-tunnel-host:12345", timeout=60.0) as client:
    result = await client.chat.complete(
        messages=[{"role": "user", "content": "Say hello."}],
        model="Qwen/Qwen3-0.6B",
        max_tokens=10,
        temperature=0.0,
        seed=42,
    )
    print(result.content)           # e.g. "Hello! How can I help you?"
    print(result.completion_tokens) # e.g. 7
```
