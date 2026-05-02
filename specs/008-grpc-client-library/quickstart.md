# Quickstart: Phase 4.2 — Direct gRPC Client Library

## Scenario 1 — Call the gRPC Frontend Directly

**Who**: A developer with a running gRPC frontend (local or Modal TCP tunnel).

**Goal**: Send a chat completion request and receive a typed response without touching protobuf or running a proxy.

```python
import asyncio
from vllm_grpc_client import VllmGrpcClient

async def main():
    async with VllmGrpcClient("localhost:50051", timeout=30.0) as client:
        result = await client.chat.complete(
            messages=[{"role": "user", "content": "Say hello."}],
            model="Qwen/Qwen3-0.6B",
            max_tokens=10,
            temperature=0.0,
            seed=42,
        )
    print(result.content)           # "Hello! How can I help you?"
    print(result.finish_reason)     # "stop"
    print(result.completion_tokens) # 7

asyncio.run(main())
```

**Validation**: Run twice with the same seed — both responses must have identical `content`.

**Connection error**: If the frontend is unreachable, `grpc.aio.AioRpcError` with `StatusCode.UNAVAILABLE` is raised within the configured timeout. The `async with` block still closes cleanly.

---

## Scenario 2 — gRPC-Direct Benchmark Target

**Who**: A developer running `make bench-modal` for Phase 4.2.

**Goal**: Add gRPC-direct to an existing benchmark run and produce a three-way comparison.

```python
# Excerpt from scripts/python/bench_modal.py (gRPC phase)
grpc_direct_results = await run_grpc_target(
    addr=grpc_addr,          # "host:port" from modal.Dict
    samples=corpus_samples,
    concurrency=max_concurrency,
    timeout=60.0,
)
```

**Wire bytes**: `request_bytes` is the protobuf serialized size of `ChatCompleteRequest`; `response_bytes` is the protobuf serialized size of `ChatCompleteResponse`. Both are directly comparable to the JSON byte counts in REST and proxy runs.

**Comparison report** (`docs/benchmarks/phase-4.2-three-way-comparison.md`):

```
| metric          | concurrency | REST  | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|-----------------|-------------|-------|------------|-----------|-------------|-----------|
| latency_p50_ms  | 1           | 106   | 664        | +526%     | TBD         | TBD       |
| throughput_rps  | 8           | 18.4  | 12.1       | -34%      | TBD         | TBD       |
| ...             | ...         | ...   | ...        | ...       | ...         | ...       |
```

---

## Scenario 3 — Remove Type Suppressions from Gen Package

**Who**: A developer adding a new consumer of generated stubs.

**Goal**: Import generated protobuf types with full type-checker coverage — no `# type: ignore[import-untyped]`.

**Before** (`packages/proxy/src/vllm_grpc_proxy/grpc_client.py`):

```python
from vllm_grpc import chat_pb2  # type: ignore[import-untyped]
from vllm_grpc import chat_pb2_grpc  # type: ignore[import-untyped]
```

**After** (once `py.typed` is added to `packages/gen/src/vllm_grpc/py.typed`):

```python
from vllm_grpc import chat_pb2
from vllm_grpc import chat_pb2_grpc
```

**Validation**: `mypy --strict packages/proxy packages/frontend packages/client` — zero errors referencing missing type information from `vllm_grpc`.

**Remaining suppressions** (not removed by this phase): `# type: ignore[misc]` and `# type: ignore[type-arg]` in the frontend for grpcio servicer inheritance patterns. These are grpcio's own typing gaps, out of scope.
