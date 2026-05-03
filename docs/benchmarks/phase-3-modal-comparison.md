# Benchmark Comparison: REST vs gRPC

## Run Metadata

**REST**:  
- Timestamp: 2026-05-03T16:11:37.977528+00:00  
- Git SHA: 5deae6c26db531cdd00efbd1c3c294e58f3be125  
- Host: Mac  
- GPU: A10G  
- Cold start: 161.0s  

**gRPC**:  
- Timestamp: 2026-05-03T16:13:57.971581+00:00  
- Git SHA: 5deae6c26db531cdd00efbd1c3c294e58f3be125  
- Host: Mac  
- GPU: A10G  
- Cold start: 105.3s  

## Concurrency = 1

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 316.73 | 255.79 | -19.2% |
| Latency P95 (ms) | 630.01 | 1092.25 | +73.4% |
| Latency P99 (ms) | 772.75 | 1628.29 | +110.7% |
| Throughput (rps) | 2.57 | 2.48 | -3.5% |
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
| Latency P50 (ms) | 411.48 | 190.07 | -53.8% |
| Latency P95 (ms) | 818.12 | 330.31 | -59.6% |
| Latency P99 (ms) | 826.04 | 330.86 | -59.9% |
| Throughput (rps) | 1.82 | 4.52 | +149.1% |
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
| Latency P50 (ms) | 805.07 | 520.95 | -35.3% |
| Latency P95 (ms) | 815.13 | 521.92 | -36.0% |
| Latency P99 (ms) | 816.50 | 522.12 | -36.1% |
| Throughput (rps) | 1.41 | 2.27 | +61.1% |
| TTFT P50 (ms) | N/A | N/A | — |
| TTFT P95 (ms) | N/A | N/A | — |
| TTFT P99 (ms) | N/A | N/A | — |
| TPOT P50 (ms) | N/A | N/A | — |
| TPOT P95 (ms) | N/A | N/A | — |
| TPOT P99 (ms) | N/A | N/A | — |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -46.0% |
