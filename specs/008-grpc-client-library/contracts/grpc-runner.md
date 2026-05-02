# Contract: gRPC-Direct Benchmark Runner

## Scope

Changes to `tools/benchmark/src/vllm_grpc_bench/runner.py` required by Phase 4.2.

---

## Target Literal Extension

```python
# Before
Target = Literal["proxy", "native"]

# After
Target = Literal["proxy", "native", "grpc-direct"]
```

The `target` field on `RequestResult` uses this literal. Existing `"proxy"` and `"native"` values are unchanged.

---

## run_grpc_target()

```python
async def run_grpc_target(
    addr:        str,                  # "host:port" — no scheme prefix
    samples:     list[RequestSample],
    concurrency: int,
    timeout:     float,
) -> list[RequestResult]
```

**Behavior:**

- Opens a single `VllmGrpcClient(addr, timeout=timeout)` channel before launching concurrent requests; closes it after all requests complete.
- Drives concurrency using the same semaphore-bounded `asyncio.gather` pattern as `run_target()`.
- Sets `target="grpc-direct"` on every returned `RequestResult`.
- Measures wire bytes as protobuf serialized sizes:
  - `request_bytes  = len(ChatCompleteRequest(...).SerializeToString())`
  - `response_bytes = len(response_proto.SerializeToString())`
- Does not retry on error; failed requests set `error=True` on the `RequestResult`.

**Imports required:**

```python
from vllm_grpc_client import VllmGrpcClient
from vllm_grpc import chat_pb2
```

`VllmGrpcClient` is sourced from `packages/client` (workspace dep). `chat_pb2` is sourced from `vllm-grpc-gen` (already a dep of the benchmark tool).

---

## RequestResult fields (unchanged contract)

`run_grpc_target()` returns `RequestResult` instances. All fields have identical semantics to those produced by `run_target()`:

| Field | Type | Value |
|-------|------|-------|
| `target` | `str` | `"grpc-direct"` |
| `latency_ms` | `float` | Wall-clock time from request start to response receipt |
| `prompt_tokens` | `int` | From `ChatCompleteResult.prompt_tokens` |
| `completion_tokens` | `int` | From `ChatCompleteResult.completion_tokens` |
| `request_bytes` | `int` | Serialized protobuf request size |
| `response_bytes` | `int` | Serialized protobuf response size |
| `error` | `bool` | `True` if `AioRpcError` raised |

---

## Benchmark Tool Dependency Update

`tools/benchmark/pyproject.toml` gains one new workspace dependency:

```toml
[project]
dependencies = [
    ...
    "vllm-grpc-client",  # NEW — workspace dep
]
```
