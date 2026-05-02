# Quickstart: Streaming Chat Completions (Phase 5)

Quick reference for testing and using the streaming features introduced in Phase 5.

---

## Prerequisites

```bash
make bootstrap   # uv sync + make proto (regenerates stubs with CompleteStream)
```

Start the frontend and proxy locally (requires GPU; use Modal for actual runs):

```bash
make run-frontend   # grpc on :50051
make run-proxy      # REST on :8000
```

---

## 1. Streaming via proxy (curl)

```bash
curl -N http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3-0.6B",
    "messages": [{"role": "user", "content": "Count to five."}],
    "max_tokens": 50,
    "seed": 42,
    "stream": true
  }'
```

Expected output: SSE events arriving token-by-token, ending with `data: [DONE]`.

**Verify first-token-before-completion**: The first `data:` line should appear before the stream closes — observable as a visible delay between events.

**Verify seed consistency**: Run the same request with `"stream": false` and compare the concatenated `delta.content` fields to the non-streaming `choices[0].message.content`.

---

## 2. Streaming via proxy (openai Python SDK)

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="unused")

content = ""
for chunk in client.chat.completions.create(
    model="Qwen/Qwen3-0.6B",
    messages=[{"role": "user", "content": "Count to five."}],
    max_tokens=50,
    seed=42,
    stream=True,
):
    delta = chunk.choices[0].delta.content or ""
    content += delta
    print(delta, end="", flush=True)

print()  # newline
```

---

## 3. Streaming via `VllmGrpcClient` (direct gRPC)

```python
import asyncio
from vllm_grpc_client import VllmGrpcClient

async def main() -> None:
    async with VllmGrpcClient("localhost:50051") as client:
        content = ""
        async for chunk in client.chat.complete_stream(
            messages=[{"role": "user", "content": "Count to five."}],
            model="Qwen/Qwen3-0.6B",
            max_tokens=50,
            seed=42,
        ):
            if chunk.delta_content:
                content += chunk.delta_content
                print(chunk.delta_content, end="", flush=True)
        print()

asyncio.run(main())
```

---

## 4. Streaming benchmark (Modal, A10G)

```bash
make bench-modal
```

This runs the three-way streaming benchmark (REST-native, gRPC-proxy, gRPC-direct) on an A10G GPU via Modal and writes:

```
docs/benchmarks/phase-5-streaming-comparison.md
```

The report includes TTFT P50/P95/P99 and TPOT P50/P95/P99 columns for all three targets at each concurrency level.

---

## 5. CI smoke test (no GPU required)

```bash
make bench-ci
```

Uses `fake_server.py` with `--streaming` to emit synthetic SSE chunks. Validates the benchmark runner's streaming code paths (TTFT/TPOT measurement, report generation) without a real model.

---

## 6. Client-disconnect cancellation test

Start a streaming request, then close the connection mid-stream (Ctrl-C on curl). Check the frontend logs for a cancellation log line within ~2 seconds. The frontend MUST log something like:

```
INFO: Stream cancelled for request_id=<uuid> after <N> tokens
```

---

## 7. Verifying mypy and tests

```bash
make typecheck   # mypy --strict across all packages
make test        # pytest (includes new streaming unit + integration tests)
```
