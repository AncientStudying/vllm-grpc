# Contract: VllmGrpcClient Completions API

**Package**: `vllm_grpc_client`
**Module**: `vllm_grpc_client.completions`
**Status**: Authoritative — implementation must match exactly

---

## Public Types

```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class CompletionResult:
    generated_text: str
    finish_reason: str          # "stop" or "length"
    prompt_tokens: int
    completion_tokens: int

@dataclass(frozen=True)
class CompletionStreamChunk:
    delta_text: str
    finish_reason: str | None   # None on non-final chunks; "stop"/"length" on final
    token_index: int
```

Both types are exported from `vllm_grpc_client.__init__`.

---

## CompletionsClient

```python
class CompletionsClient:
    def __init__(self, channel: grpc.aio.Channel) -> None: ...

    async def complete(
        self,
        model: str,
        max_tokens: int,
        *,
        prompt: str | None = None,
        prompt_embeds: "torch.Tensor | None" = None,
        temperature: float | None = None,
        top_p: float | None = None,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> CompletionResult: ...

    async def complete_stream(
        self,
        model: str,
        max_tokens: int,
        *,
        prompt: str | None = None,
        prompt_embeds: "torch.Tensor | None" = None,
        temperature: float | None = None,
        top_p: float | None = None,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[CompletionStreamChunk]: ...
```

---

## Invariants

### Input constraint
Exactly one of `prompt` or `prompt_embeds` must be provided. Passing neither or both raises `ValueError` before any network call is made.

### Tensor encoding
When `prompt_embeds` is provided, the client serialises it via `torch.save(tensor, buf)` and populates the proto `bytes` field with the raw bytes. **No base64 encoding.** The `torch` import is deferred to call time; callers who only use text prompts do not pay the torch import cost.

### Async generator (complete_stream)
- The caller MUST iterate to exhaustion or explicitly break. On break/GC, the underlying gRPC call is cancelled via `call.cancel()` in a `finally` block.
- `CompletionStreamChunk.finish_reason` is `None` on all non-final chunks and `"stop"` or `"length"` on the single final chunk.
- `grpc.aio.AioRpcError` propagates directly to the caller; it is not caught or wrapped.

---

## VllmGrpcClient integration

```python
class VllmGrpcClient:
    @property
    def completions(self) -> CompletionsClient:
        """Returns a CompletionsClient bound to the open channel."""
        ...
```

Usage pattern:
```python
async with VllmGrpcClient("host:50051") as client:
    # Text prompt
    result = await client.completions.complete(
        model="Qwen/Qwen3-0.6B",
        max_tokens=50,
        prompt="The meaning of life is",
        seed=42,
    )
    print(result.generated_text)

    # Prompt embeddings (no proxy needed)
    import torch
    tensor = torch.load("corpus/sample.pt")
    result = await client.completions.complete(
        model="Qwen/Qwen3-0.6B",
        max_tokens=50,
        prompt_embeds=tensor,
        seed=42,
    )
```
