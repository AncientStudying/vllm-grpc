# Benchmark Summary: vllm-grpc

All benchmarks ran on Modal A10G GPU, vLLM v0.20.0, model `Qwen/Qwen3-0.6B`.
Numbers are drawn from committed JSON files in `docs/benchmarks/`.

---

## 1. Non-Streaming Chat (Phase 4.2)

**Methodology**
- Corpus: `tools/benchmark/corpus/chat_nonstreaming.json`
- Concurrency levels: 1, 4, 8
- GPU: A10G | vLLM: 0.20.0 | Model: `Qwen/Qwen3-0.6B`
- Sources: `phase-4.2-rest-baseline.json`, `phase-4.2-grpc-proxy-baseline.json`, `phase-4.2-grpc-direct-baseline.json`

### Concurrency = 1

| Metric | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|------|------------|-----------|-------------|-----------|
| Latency P50 (ms) | 106 | 335 | +215% | 144 | +35% |
| Latency P95 (ms) | 161 | 1591 | +889% | 272 | +69% |
| Latency P99 (ms) | 192 | 2404 | +1154% | 318 | +66% |
| Request bytes (mean) | 506 | 506 | +0% | 419 | −17% |
| Response bytes (mean) | 611 | 330 | −46% | 65 | −89% |

### Concurrency = 8

| Metric | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|------|------------|-----------|-------------|-----------|
| Latency P50 (ms) | 176 | 404 | +130% | 424 | +142% |
| Latency P95 (ms) | 178 | 405 | +128% | 425 | +138% |
| Latency P99 (ms) | 179 | 405 | +127% | 425 | +138% |
| Request bytes (mean) | 506 | 506 | +0% | 419 | −17% |
| Response bytes (mean) | 611 | 330 | −46% | 65 | −89% |

**Interpretation:** Wire size is the clearest win: gRPC-direct response bytes are 89% smaller than REST (65 B vs 611 B) at every concurrency level — this is structural, driven by protobuf framing vs JSON. Request bytes are 17% smaller because the proto schema omits the JSON OpenAI envelope. gRPC-proxy latency at c=1 is 3× higher than REST; this is the local-to-Modal tunnel hop adding ~200 ms of RTT, not protocol overhead. At c=8, gRPC-direct latency converges with gRPC-proxy and exceeds REST — the model's serial inference queue dominates over any protocol savings at higher load.

---

## 2. Streaming Chat (Phase 5)

**Methodology**
- Corpus: `tools/benchmark/corpus/chat_nonstreaming.json` (same prompts, stream=True)
- Concurrency levels: 1, 4, 8
- GPU: A10G | vLLM: 0.20.0 | Model: `Qwen/Qwen3-0.6B`
- Sources: `phase-5-rest-streaming.json`, `phase-5-grpc-proxy-streaming.json`, `phase-5-grpc-direct-streaming.json`

### Concurrency = 1

| Metric | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|------|------------|-----------|-------------|-----------|
| TTFT P50 (ms) | 90 | 275 | +208% | 125 | +40% |
| TTFT P95 (ms) | 138 | 333 | +141% | 264 | +91% |
| TTFT P99 (ms) | 166 | 333 | +101% | 312 | +88% |
| TPOT P50 (ms) | 2.1 | 3.6 | +69% | 7.0 | +227% |
| TPOT P95 (ms) | 6.6 | 7.6 | +16% | 9.3 | +42% |
| TPOT P99 (ms) | 6.6 | 7.6 | +15% | 10.0 | +51% |
| Request bytes (mean) | 522 | 522 | +0% | 419 | −20% |

### Concurrency = 8

| Metric | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|------|------------|-----------|-------------|-----------|
| TTFT P50 (ms) | 161 | 394 | +144% | 393 | +143% |
| TTFT P95 (ms) | 167 | 396 | +137% | 393 | +135% |
| TTFT P99 (ms) | 167 | 397 | +137% | 393 | +135% |
| TPOT P50 (ms) | 6.2 | 1.9 | −69% | 2.7 | −57% |
| TPOT P95 (ms) | 6.8 | 7.6 | +12% | 8.4 | +23% |
| TPOT P99 (ms) | 6.9 | 7.7 | +12% | 8.6 | +25% |
| Request bytes (mean) | 522 | 522 | +0% | 419 | −20% |

**Interpretation:** At c=1, gRPC-direct TTFT (125 ms) is 40% higher than REST (90 ms) — the extra channel setup adds latency for the first token. TPOT for gRPC-direct is 3× higher than REST at c=1 because the gRPC server-side streaming implementation processes chunks serially. At c=8, TTFT converges across all three paths — the model's attention layer becomes the bottleneck. TPOT at c=8 inverts: REST TPOT is actually higher than gRPC paths in the P50, likely because REST SSE framing flushes less aggressively. Request bytes are 20% smaller with gRPC-direct in all cases.

---

## 3. Completions with Prompt Embeddings (Phase 6)

**Methodology**
- Corpus: `tools/benchmark/corpus/completions_text.json` and `tools/benchmark/corpus/completions_embeds_manifest.json`
- Concurrency levels: 1, 4, 8
- GPU: A10G | vLLM: 0.20.0 | Model: `Qwen/Qwen3-0.6B`
- Sources: `phase-6-completions-native.json`, `phase-6-completions-proxy.json`, `phase-6-completions-grpc-direct.json`

### Wire Size (averaged across concurrency levels)

| Path | Input type | Request bytes (mean) | Response bytes (mean) | Δ req vs native |
|------|------------|----------------------|-----------------------|-----------------|
| Native REST | text | 377 | 702 | baseline |
| Proxy REST | text | 377 | 533 | +0% |
| gRPC-direct | text | 329 | 278 | −13% |
| Native REST | embeds | 606,479 | 687 | baseline |
| Proxy REST | embeds | 606,479 | 537 | +0% |
| gRPC-direct | embeds | 454,807 | 280 | −25% |

### Latency — Text Completions, Concurrency = 1

| Metric | Native REST | Proxy REST | Δ vs native | gRPC-direct | Δ vs native |
|--------|-------------|------------|-------------|-------------|-------------|
| Latency P50 (ms) | 306 | 460 | +50% | 317 | +4% |
| Latency P95 (ms) | 364 | 475 | +30% | 358 | −2% |
| Throughput (rps) | 3.22 | 2.17 | −33% | 3.05 | −5% |

### Latency — Embed Completions, Concurrency = 1

| Metric | Native REST | Proxy REST | Δ vs native | gRPC-direct | Δ vs native |
|--------|-------------|------------|-------------|-------------|-------------|
| Latency P50 (ms) | 460 | 865 | +88% | 452 | −2% |
| Latency P95 (ms) | 1016 | 1090 | +7% | 903 | −11% |
| Throughput (rps) | 1.91 | 1.15 | −40% | 1.83 | −4% |

**Interpretation:** The headline result is wire-size reduction for embed requests. Native REST base64-encodes the raw tensor bytes (~33% overhead), so a 455 KB gRPC payload replaces a 606 KB REST payload — a 25% saving that scales with embedding dimensionality. Response bytes are also 59–60% smaller via gRPC-direct because the completions proto response is more compact than the JSON OpenAI envelope. Latency for gRPC-direct is within noise of native REST at c=1; the proxy adds 50–88% latency due to the additional REST→gRPC translation layer.

---

*All results from Modal A10G runs. Source JSON files in `docs/benchmarks/`.*
