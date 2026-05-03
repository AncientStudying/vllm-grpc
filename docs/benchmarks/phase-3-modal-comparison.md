# Benchmark Comparison: REST vs gRPC

## Run Metadata

**REST**:  
- Timestamp: 2026-05-03T19:27:43.200012+00:00  
- Git SHA: 720a95a579bfb23e8c3b1177a94624e0c0a8c4cb  
- Host: Mac  
- GPU: A10G  
- Cold start: 125.2s  

**gRPC**:  
- Timestamp: 2026-05-03T19:30:54.685592+00:00  
- Git SHA: 720a95a579bfb23e8c3b1177a94624e0c0a8c4cb  
- Host: Mac  
- GPU: A10G  
- Cold start: 175.3s  

## Concurrency = 1

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 106.33 | 334.68 | +214.8% |
| Latency P95 (ms) | 160.91 | 1591.16 | +888.9% |
| Latency P99 (ms) | 191.70 | 2404.47 | +1154.3% |
| Throughput (rps) | 8.65 | 1.77 | -79.5% |
| TTFT P50 (ms) | N/A | N/A | — |
| TTFT P95 (ms) | N/A | N/A | — |
| TTFT P99 (ms) | N/A | N/A | — |
| TPOT P50 (ms) | N/A | N/A | — |
| TPOT P95 (ms) | N/A | N/A | — |
| TPOT P99 (ms) | N/A | N/A | — |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -46.0% |

## Concurrency = 4

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 118.64 | 250.31 | +111.0% |
| Latency P95 (ms) | 165.51 | 404.28 | +144.3% |
| Latency P99 (ms) | 165.70 | 404.53 | +144.1% |
| Throughput (rps) | 7.39 | 3.49 | -52.7% |
| TTFT P50 (ms) | N/A | N/A | — |
| TTFT P95 (ms) | N/A | N/A | — |
| TTFT P99 (ms) | N/A | N/A | — |
| TPOT P50 (ms) | N/A | N/A | — |
| TPOT P95 (ms) | N/A | N/A | — |
| TPOT P99 (ms) | N/A | N/A | — |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -46.0% |

## Concurrency = 8

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 175.64 | 404.31 | +130.2% |
| Latency P95 (ms) | 178.17 | 405.35 | +127.5% |
| Latency P99 (ms) | 178.53 | 405.48 | +127.1% |
| Throughput (rps) | 6.16 | 2.82 | -54.2% |
| TTFT P50 (ms) | N/A | N/A | — |
| TTFT P95 (ms) | N/A | N/A | — |
| TTFT P99 (ms) | N/A | N/A | — |
| TPOT P50 (ms) | N/A | N/A | — |
| TPOT P95 (ms) | N/A | N/A | — |
| TPOT P99 (ms) | N/A | N/A | — |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -46.0% |
