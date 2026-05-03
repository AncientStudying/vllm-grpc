# Quickstart: Phase 6 — Completions API with Prompt Embeddings

**Audience**: Developer working with the vllm-grpc bridge
**Environment**: Modal A10G for GPU inference; macOS/Linux for local unit/integration tests

---

## Prerequisites

1. `uv sync --frozen --all-packages` (installs all workspace deps)
2. `make proto` (regenerates stubs including new completions.proto)
3. Modal token: `modal token new` (one-time browser login)
4. Model weights downloaded: `make download-weights` (or pre-existing volume)

---

## Running the Stack Locally (unit/integration tests only)

Local runs use the `FakeCompletionsServicer` — no GPU or vLLM required.

```bash
make test          # all packages
make typecheck     # mypy --strict
make lint          # ruff
```

---

## Text-Prompt Completions via Proxy (curl)

Start the proxy and frontend (real or fake):

```bash
# Terminal 1 — gRPC frontend (requires vLLM; use Modal for real inference)
make run-frontend

# Terminal 2 — REST proxy
make run-proxy
```

Send a text completion:

```bash
curl -s http://localhost:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3-0.6B",
    "prompt": "The capital of France is",
    "max_tokens": 10,
    "seed": 42
  }' | python3 -m json.tool
```

---

## Streaming Text Completions via Proxy (curl)

```bash
curl -N http://localhost:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3-0.6B",
    "prompt": "The capital of France is",
    "max_tokens": 10,
    "seed": 42,
    "stream": true
  }'
```

Tokens arrive incrementally; stream terminates with `data: [DONE]`.

---

## Prompt-Embedding Completions via Proxy (Python)

```python
import base64
import io
import httpx
import torch

# Generate a prompt embedding tensor (Qwen3-0.6B hidden_size=1024)
# In production: use the tokenizer + model.embed_tokens for a real prompt
seq_len, hidden_size = 8, 1024
tensor = torch.zeros(seq_len, hidden_size, dtype=torch.float32)

buf = io.BytesIO()
torch.save(tensor, buf)
embed_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

with httpx.Client() as client:
    resp = client.post(
        "http://localhost:8000/v1/completions",
        json={
            "model": "Qwen/Qwen3-0.6B",
            "prompt_embeds": embed_b64,
            "max_tokens": 10,
            "seed": 42,
        },
        timeout=120.0,
    )
resp.raise_for_status()
print(resp.json()["choices"][0]["text"])
```

---

## Direct gRPC via Client Library (Python)

```python
import asyncio
import torch
from vllm_grpc_client import VllmGrpcClient

async def main() -> None:
    async with VllmGrpcClient("localhost:50051") as client:
        # Text prompt
        result = await client.completions.complete(
            model="Qwen/Qwen3-0.6B",
            max_tokens=10,
            prompt="The capital of France is",
            seed=42,
        )
        print("Text:", result.generated_text)

        # Prompt embeddings — no base64, raw bytes on the wire
        tensor = torch.zeros(8, 1024, dtype=torch.float32)
        result = await client.completions.complete(
            model="Qwen/Qwen3-0.6B",
            max_tokens=10,
            prompt_embeds=tensor,
            seed=42,
        )
        print("Embeds:", result.generated_text)

asyncio.run(main())
```

---

## Modal Benchmark (GPU)

```bash
# Generate the embeddings corpus first (one-time)
uv run python scripts/python/gen_embed_corpus.py

# Run the full three-way + completions benchmark on Modal A10G
make bench-modal
```

Results are written to `docs/benchmarks/phase-6-completions-comparison.md`.

---

## Generating Real Prompt Embeddings

To generate real (non-zero) embeddings from a text prompt:

```python
import io
import torch
from transformers import AutoTokenizer, AutoModel

model_name = "Qwen/Qwen3-0.6B"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModel.from_pretrained(model_name)
model.eval()

prompt = "The capital of France is"
inputs = tokenizer(prompt, return_tensors="pt")
with torch.no_grad():
    embeds = model.embed_tokens(inputs["input_ids"]).squeeze(0)  # [seq_len, hidden_size]

buf = io.BytesIO()
torch.save(embeds, buf)
# buf.getvalue() → raw bytes for gRPC; base64.b64encode(buf.getvalue()) → for REST
```
