# Phase 6 Completions Benchmark: Wire-Size and Latency

## Methodology

- **Native REST**: vLLM's own OpenAI-compatible REST endpoint (text and embeds)
- **Proxy REST**: gRPC proxy REST facade; base64-encodes `torch.save()` bytes for embeds
- **gRPC-direct**: raw proto `bytes` field, no base64 encoding
- Baseline for text completions is native REST (the conventional approach).
- Baseline for embed completions is native REST (isolates protocol from proxy overhead).

## Wire-Size by Path and Input Type

| path | input_type | req_bytes_mean | resp_bytes_mean | Δ vs baseline |
|------|------------|----------------|-----------------|---------------|
| native | completion-text | 377 | 702 | baseline |
| proxy | completion-text | 377 | 533 | +0.0% vs native-REST |
| grpc-direct | completion-text | 329 | 278 | -12.8% vs native-REST |
| native | completion-embeds | 606479 | 687 | baseline |
| proxy | completion-embeds | 606479 | 537 | +0.0% vs native-REST |
| grpc-direct | completion-embeds | 454807 | 280 | -25.0% vs native-REST |

## Latency and Throughput by Path, Input Type, and Concurrency

| path | input_type | concurrency | latency_p50_ms | latency_p95_ms | latency_p99_ms | throughput_rps |
|------|------------|-------------|----------------|----------------|----------------|----------------|
| native | completion-text | 1 | 305.86 | 364.31 | 481.03 | 3.22 |
| native | completion-text | 4 | 316.95 | 407.80 | 408.15 | 2.89 |
| native | completion-text | 8 | 405.98 | 11876.97 | 11877.17 | 0.20 |
| proxy | completion-text | 1 | 459.58 | 475.39 | 475.52 | 2.17 |
| proxy | completion-text | 4 | 399.62 | 587.11 | 587.81 | 2.30 |
| proxy | completion-text | 8 | 427.88 | 565.86 | 566.68 | 2.17 |
| grpc-direct | completion-text | 1 | 317.16 | 358.44 | 465.12 | 3.05 |
| grpc-direct | completion-text | 4 | 386.12 | 581.23 | 581.37 | 2.43 |
| grpc-direct | completion-text | 8 | 466.68 | 565.10 | 565.11 | 2.10 |
| native | completion-embeds | 1 | 460.11 | 1015.61 | 1017.38 | 1.91 |
| native | completion-embeds | 4 | 559.06 | 2481.35 | 2562.06 | 1.05 |
| native | completion-embeds | 8 | 755.59 | 2927.25 | 3450.09 | 0.76 |
| proxy | completion-embeds | 1 | 865.37 | 1089.60 | 1178.38 | 1.15 |
| proxy | completion-embeds | 4 | 732.93 | 3084.95 | 3229.32 | 0.87 |
| proxy | completion-embeds | 8 | 1039.51 | 1810.90 | 1822.52 | 0.93 |
| grpc-direct | completion-embeds | 1 | 452.22 | 902.85 | 1142.70 | 1.83 |
| grpc-direct | completion-embeds | 4 | 1495.15 | 6165.14 | 6203.63 | 0.40 |
| grpc-direct | completion-embeds | 8 | 1060.88 | 2614.80 | 2978.10 | 0.66 |
