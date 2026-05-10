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
| Latency P50 (ms) | 307 | 435 | +42% | 295 | −4% |
| Latency P95 (ms) | 451 | 447 | −1% | 406 | −10% |
| Throughput (rps) | 3.11 | 2.29 | −26% | 3.23 | +4% |

### Latency — Embed Completions, Concurrency = 1

| Metric | Native REST | Proxy REST | Δ vs native | gRPC-direct | Δ vs native |
|--------|-------------|------------|-------------|-------------|-------------|
| Latency P50 (ms) | 463 | 668 | +44% | 432 | −7% |
| Latency P95 (ms) | 855 | 913 | +7% | 615 | −28% |
| Throughput (rps) | 2.02 | 1.42 | −30% | 2.27 | +13% |

### Latency — Text Completions, Concurrency = 8 ⚠️

| Metric | Native REST | Proxy REST | Δ vs native | gRPC-direct | Δ vs native |
|--------|-------------|------------|-------------|-------------|-------------|
| Latency P50 (ms) | 379 | 424 | +12% | 419 | +10% |
| Latency P95 (ms) | **13,598** | 537 | −96% | 552 | −96% |
| Throughput (rps) | **0.18** | 2.24 | +1169% | 2.23 | +1161% |

> ⚠️ Native REST at c=8 text completions experienced server-side queue saturation in this run: P95 latency spiked to 13.6 s and throughput collapsed to 0.18 rps while proxy and gRPC-direct both remained stable (~535 ms P95, ~2.2 rps). The Δ vs native values in this row reflect a degraded baseline and do not represent a stable protocol comparison. See `phase-6-completions-native.json` for raw results.

**Interpretation:** The headline result is wire-size reduction for embed requests: a 455 KB gRPC payload replaces a 606 KB REST payload (−25%), because native REST base64-encodes raw tensor bytes while gRPC transmits them directly. Response bytes are 59–60% smaller via gRPC-direct across all concurrencies and request types. At c=1, gRPC-direct latency is slightly *below* native REST for both text (−4%) and embed (−7%) completions — unlike Phase 4.2 chat where the channel setup added ~35 ms overhead, the completions path has less per-request setup cost. Proxy adds 42–44% latency at c=1 due to the REST→gRPC translation hop. At c=8, native REST text completions showed queue saturation (P95 = 13.6 s); treat those Δ values as an artifact of a degraded baseline, not a framework result. Embed completions at c=8 remain stable across all three paths.

---

*All results from Modal A10G runs. Source JSON files in `docs/benchmarks/`.*

---

## 4. M3 — gRPC Channel-Level Tuning (Phase 015)

**Methodology** (CPU-only, mock vLLM engine — distinct from §1–§3 GPU runs above)
- Sweep: 4 channel axes × 3 canonical widths × 2 paths × 30 iters/cell
- Source: [`m3-channel-tuning.md`](./m3-channel-tuning.md) | [`m3-channel-tuning.json`](./m3-channel-tuning.json)
- SC-003 win bar: candidate bytes 95% CI strictly below baseline 95% CI

| Axis | Width range | Path | Verdict | Notes |
|---|---|---|---|---|
| `max_message_size` | 2048 / 4096 / 8192 | embed + chat_stream | no_winner (all 6 cells) | default 4 MiB never binds; embed payload is ~524 KB at h=8192 |
| `keepalive` | 2048 / 4096 / 8192 | embed + chat_stream | no_winner (all 6 cells) | aggressive 10 s pings completed long-stream cohort with no drops |
| `compression` | 2048 / 4096 / 8192 | embed + chat_stream | no_winner (all 6 cells) | gzip costs +18–39% time on dense-float embeds with no wire-byte win |
| `http2_framing` | 2048 / 4096 / 8192 | embed + chat_stream | no_winner (all 6 cells) | BDP-probe cannot manifest a win on loopback CPU-only mock |

**P1 frozen channel config (FR-008):** `M1_BASELINE` (all axes default — no candidate cleared SC-003). This is the configuration US2 (P2 schema-level tuning) measures against.

**Cross-comparison caveat:** the M3 numbers above are **not** comparable to §1–§3 above. M3 runs CPU-only with a mock engine to isolate channel/protocol effects from model-execution effects, while §1–§3 benchmark the live vLLM engine on Modal A10G. M3's "delta vs M1" is computed against the M3 in-batch baseline (also CPU-mock), not against the GPU numbers in §2.
