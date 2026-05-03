# Benchmark Summary

**Run**: 2026-05-03T16:13:57.971581+00:00  
**Commit**: 5deae6c26db531cdd00efbd1c3c294e58f3be125  
**Host**: Mac  
**GPU**: A10G  
**Cold start**: 105.3s  

## Concurrency = 1

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 255.79 | 246.57 | +3.7% |
| Latency P95 (ms) | 1092.25 | 266.62 | +309.7% |
| Latency P99 (ms) | 1628.29 | 270.29 | +502.4% |
| Throughput (rps) | 2.48 | 3.99 | -37.9% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| TTFT P50 (ms) | N/A | N/A | N/A |
| TTFT P95 (ms) | N/A | N/A | N/A |
| TTFT P99 (ms) | N/A | N/A | N/A |
| TPOT P50 (ms) | N/A | N/A | N/A |
| TPOT P95 (ms) | N/A | N/A | N/A |
| TPOT P99 (ms) | N/A | N/A | N/A |
| Proxy ms P50 | 0.203 | N/A | N/A |
| Proxy ms P95 | 0.253 | N/A | N/A |
| Proxy ms P99 | 0.260 | N/A | N/A |

## Concurrency = 4

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 190.07 | 254.89 | -25.4% |
| Latency P95 (ms) | 330.31 | 268.13 | +23.2% |
| Latency P99 (ms) | 330.86 | 268.73 | +23.1% |
| Throughput (rps) | 4.52 | 3.87 | +16.9% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| TTFT P50 (ms) | N/A | N/A | N/A |
| TTFT P95 (ms) | N/A | N/A | N/A |
| TTFT P99 (ms) | N/A | N/A | N/A |
| TPOT P50 (ms) | N/A | N/A | N/A |
| TPOT P95 (ms) | N/A | N/A | N/A |
| TPOT P99 (ms) | N/A | N/A | N/A |
| Proxy ms P50 | 0.056 | N/A | N/A |
| Proxy ms P95 | 0.131 | N/A | N/A |
| Proxy ms P99 | 0.142 | N/A | N/A |

## Concurrency = 8

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 520.95 | 294.90 | +76.7% |
| Latency P95 (ms) | 521.92 | 341.74 | +52.7% |
| Latency P99 (ms) | 522.12 | 341.82 | +52.7% |
| Throughput (rps) | 2.27 | 3.61 | -37.0% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| TTFT P50 (ms) | N/A | N/A | N/A |
| TTFT P95 (ms) | N/A | N/A | N/A |
| TTFT P99 (ms) | N/A | N/A | N/A |
| TPOT P50 (ms) | N/A | N/A | N/A |
| TPOT P95 (ms) | N/A | N/A | N/A |
| TPOT P99 (ms) | N/A | N/A | N/A |
| Proxy ms P50 | 0.040 | N/A | N/A |
| Proxy ms P95 | 0.136 | N/A | N/A |
| Proxy ms P99 | 0.140 | N/A | N/A |
