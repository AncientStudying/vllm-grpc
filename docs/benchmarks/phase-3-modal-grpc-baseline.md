# Benchmark Summary

**Run**: 2026-05-03T23:41:57.484425+00:00  
**Commit**: 50be64179f39a052b98a70a4d51f1a29c9b30540  
**Host**: Mac  
**GPU**: A10G  
**Cold start**: 130.2s  

## Concurrency = 1

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 285.47 | 278.19 | +2.6% |
| Latency P95 (ms) | 1152.50 | 284.34 | +305.3% |
| Latency P99 (ms) | 1659.62 | 286.22 | +479.8% |
| Throughput (rps) | 2.27 | 3.60 | -37.0% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| TTFT P50 (ms) | N/A | N/A | N/A |
| TTFT P95 (ms) | N/A | N/A | N/A |
| TTFT P99 (ms) | N/A | N/A | N/A |
| TPOT P50 (ms) | N/A | N/A | N/A |
| TPOT P95 (ms) | N/A | N/A | N/A |
| TPOT P99 (ms) | N/A | N/A | N/A |
| Proxy ms P50 | 0.186 | N/A | N/A |
| Proxy ms P95 | 0.260 | N/A | N/A |
| Proxy ms P99 | 0.266 | N/A | N/A |

## Concurrency = 4

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 245.85 | 248.39 | -1.0% |
| Latency P95 (ms) | 359.26 | 374.07 | -4.0% |
| Latency P99 (ms) | 359.38 | 374.30 | -4.0% |
| Throughput (rps) | 3.92 | 3.87 | +1.3% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| TTFT P50 (ms) | N/A | N/A | N/A |
| TTFT P95 (ms) | N/A | N/A | N/A |
| TTFT P99 (ms) | N/A | N/A | N/A |
| TPOT P50 (ms) | N/A | N/A | N/A |
| TPOT P95 (ms) | N/A | N/A | N/A |
| TPOT P99 (ms) | N/A | N/A | N/A |
| Proxy ms P50 | 0.061 | N/A | N/A |
| Proxy ms P95 | 0.222 | N/A | N/A |
| Proxy ms P99 | 0.261 | N/A | N/A |

## Concurrency = 8

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 373.91 | 680.66 | -45.1% |
| Latency P95 (ms) | 376.19 | 682.12 | -44.8% |
| Latency P99 (ms) | 376.35 | 682.30 | -44.8% |
| Throughput (rps) | 3.02 | 1.74 | +74.3% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| TTFT P50 (ms) | N/A | N/A | N/A |
| TTFT P95 (ms) | N/A | N/A | N/A |
| TTFT P99 (ms) | N/A | N/A | N/A |
| TPOT P50 (ms) | N/A | N/A | N/A |
| TPOT P95 (ms) | N/A | N/A | N/A |
| TPOT P99 (ms) | N/A | N/A | N/A |
| Proxy ms P50 | 0.033 | N/A | N/A |
| Proxy ms P95 | 0.154 | N/A | N/A |
| Proxy ms P99 | 0.173 | N/A | N/A |
