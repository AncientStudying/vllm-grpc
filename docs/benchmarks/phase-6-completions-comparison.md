# Phase 6 Completions Benchmark: Wire-Size and Latency

## Methodology

- **Native REST**: vLLM's own OpenAI-compatible REST endpoint; text prompts only
- **Proxy REST**: gRPC proxy REST facade; base64-encodes `torch.save()` bytes for embeds
- **gRPC-direct**: raw proto `bytes` field, no base64 encoding
- Baseline for text completions is native REST (the conventional approach).
- Baseline for embed completions is proxy REST (no native REST path exists).

## Wire-Size by Path and Input Type

| path | input_type | req_bytes_mean | resp_bytes_mean | Δ vs baseline |
|------|------------|----------------|-----------------|---------------|
| native | completion-text | 377 | 700 | baseline |
| proxy | completion-text | 377 | 532 | +0.0% vs native-REST |
| grpc-direct | completion-text | 329 | 279 | -12.8% vs native-REST |
| proxy | completion-embeds | 606479 | N/A | baseline |
| grpc-direct | completion-embeds | 454807 | N/A | -25.0% vs proxy-REST |

## Latency and Throughput by Path, Input Type, and Concurrency

| path | input_type | concurrency | latency_p50_ms | latency_p95_ms | latency_p99_ms | throughput_rps |
|------|------------|-------------|----------------|----------------|----------------|----------------|
| native | completion-text | 1 | 306.50 | 391.71 | 551.62 | 3.16 |
| native | completion-text | 4 | 408.97 | 504.56 | 504.76 | 2.34 |
| native | completion-text | 8 | 407.02 | 12994.01 | 12994.50 | 0.18 |
| proxy | completion-text | 1 | 413.71 | 421.64 | 424.29 | 2.42 |
| proxy | completion-text | 4 | 305.85 | 497.29 | 497.70 | 2.93 |
| proxy | completion-text | 8 | 370.84 | 491.11 | 491.18 | 2.57 |
| grpc-direct | completion-text | 1 | 266.31 | 345.21 | 391.83 | 3.59 |
| grpc-direct | completion-text | 4 | 307.74 | 515.69 | 515.71 | 2.91 |
| grpc-direct | completion-text | 8 | 360.64 | 488.83 | 488.94 | 2.62 |
| proxy | completion-embeds | 1 | N/A | N/A | N/A | N/A |
| proxy | completion-embeds | 4 | N/A | N/A | N/A | N/A |
| proxy | completion-embeds | 8 | N/A | N/A | N/A | N/A |
| grpc-direct | completion-embeds | 1 | N/A | N/A | N/A | N/A |
| grpc-direct | completion-embeds | 4 | N/A | N/A | N/A | N/A |
| grpc-direct | completion-embeds | 8 | N/A | N/A | N/A | N/A |
