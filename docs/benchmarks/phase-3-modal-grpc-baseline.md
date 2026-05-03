# Benchmark Summary

**Run**: 2026-05-03T19:30:54.685592+00:00  
**Commit**: 720a95a579bfb23e8c3b1177a94624e0c0a8c4cb  
**Host**: Mac  
**GPU**: A10G  
**Cold start**: 175.3s  

## Concurrency = 1

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 334.68 | 330.60 | +1.2% |
| Latency P95 (ms) | 1591.16 | 342.72 | +364.3% |
| Latency P99 (ms) | 2404.47 | 343.88 | +599.2% |
| Throughput (rps) | 1.77 | 3.17 | -44.0% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| TTFT P50 (ms) | N/A | N/A | N/A |
| TTFT P95 (ms) | N/A | N/A | N/A |
| TTFT P99 (ms) | N/A | N/A | N/A |
| TPOT P50 (ms) | N/A | N/A | N/A |
| TPOT P95 (ms) | N/A | N/A | N/A |
| TPOT P99 (ms) | N/A | N/A | N/A |
| Proxy ms P50 | 0.180 | N/A | N/A |
| Proxy ms P95 | 0.239 | N/A | N/A |
| Proxy ms P99 | 0.241 | N/A | N/A |

## Concurrency = 4

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 250.31 | 248.76 | +0.6% |
| Latency P95 (ms) | 404.28 | 401.45 | +0.7% |
| Latency P99 (ms) | 404.53 | 401.52 | +0.8% |
| Throughput (rps) | 3.49 | 3.58 | -2.4% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| TTFT P50 (ms) | N/A | N/A | N/A |
| TTFT P95 (ms) | N/A | N/A | N/A |
| TTFT P99 (ms) | N/A | N/A | N/A |
| TPOT P50 (ms) | N/A | N/A | N/A |
| TPOT P95 (ms) | N/A | N/A | N/A |
| TPOT P99 (ms) | N/A | N/A | N/A |
| Proxy ms P50 | 0.059 | N/A | N/A |
| Proxy ms P95 | 0.153 | N/A | N/A |
| Proxy ms P99 | 0.160 | N/A | N/A |

## Concurrency = 8

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 404.31 | 698.84 | -42.1% |
| Latency P95 (ms) | 405.35 | 700.37 | -42.1% |
| Latency P99 (ms) | 405.48 | 700.46 | -42.1% |
| Throughput (rps) | 2.82 | 1.68 | +67.5% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| TTFT P50 (ms) | N/A | N/A | N/A |
| TTFT P95 (ms) | N/A | N/A | N/A |
| TTFT P99 (ms) | N/A | N/A | N/A |
| TPOT P50 (ms) | N/A | N/A | N/A |
| TPOT P95 (ms) | N/A | N/A | N/A |
| TPOT P99 (ms) | N/A | N/A | N/A |
| Proxy ms P50 | 0.028 | N/A | N/A |
| Proxy ms P95 | 0.130 | N/A | N/A |
| Proxy ms P99 | 0.138 | N/A | N/A |
