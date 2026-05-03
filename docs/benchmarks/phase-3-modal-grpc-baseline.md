# Benchmark Summary

**Run**: 2026-05-03T00:38:12.013260+00:00  
**Commit**: 14eccd46c01c4583f3b865fd1459c769cc2c3a6a  
**Host**: Mac  
**GPU**: A10G  
**Cold start**: 155.2s  

## Concurrency = 1

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 274.09 | 270.81 | +1.2% |
| Latency P95 (ms) | 1034.72 | 279.73 | +269.9% |
| Latency P99 (ms) | 1529.18 | 282.10 | +442.1% |
| Throughput (rps) | 2.44 | 3.77 | -35.2% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| TTFT P50 (ms) | N/A | N/A | N/A |
| TTFT P95 (ms) | N/A | N/A | N/A |
| TTFT P99 (ms) | N/A | N/A | N/A |
| TPOT P50 (ms) | N/A | N/A | N/A |
| TPOT P95 (ms) | N/A | N/A | N/A |
| TPOT P99 (ms) | N/A | N/A | N/A |
| Proxy ms P50 | 0.199 | N/A | N/A |
| Proxy ms P95 | 0.236 | N/A | N/A |
| Proxy ms P99 | 0.243 | N/A | N/A |

## Concurrency = 4

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 193.63 | 277.13 | -30.1% |
| Latency P95 (ms) | 369.06 | 304.59 | +21.2% |
| Latency P99 (ms) | 369.32 | 321.82 | +14.8% |
| Throughput (rps) | 4.10 | 3.55 | +15.6% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.1% |
| TTFT P50 (ms) | N/A | N/A | N/A |
| TTFT P95 (ms) | N/A | N/A | N/A |
| TTFT P99 (ms) | N/A | N/A | N/A |
| TPOT P50 (ms) | N/A | N/A | N/A |
| TPOT P95 (ms) | N/A | N/A | N/A |
| TPOT P99 (ms) | N/A | N/A | N/A |
| Proxy ms P50 | 0.044 | N/A | N/A |
| Proxy ms P95 | 0.107 | N/A | N/A |
| Proxy ms P99 | 0.129 | N/A | N/A |

## Concurrency = 8

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 631.39 | 313.46 | +101.4% |
| Latency P95 (ms) | 632.01 | 314.79 | +100.8% |
| Latency P99 (ms) | 632.09 | 314.85 | +100.8% |
| Throughput (rps) | 1.89 | 3.64 | -48.1% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| TTFT P50 (ms) | N/A | N/A | N/A |
| TTFT P95 (ms) | N/A | N/A | N/A |
| TTFT P99 (ms) | N/A | N/A | N/A |
| TPOT P50 (ms) | N/A | N/A | N/A |
| TPOT P95 (ms) | N/A | N/A | N/A |
| TPOT P99 (ms) | N/A | N/A | N/A |
| Proxy ms P50 | 0.038 | N/A | N/A |
| Proxy ms P95 | 0.115 | N/A | N/A |
| Proxy ms P99 | 0.124 | N/A | N/A |
