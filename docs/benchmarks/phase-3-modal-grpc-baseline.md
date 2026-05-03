# Benchmark Summary

**Run**: 2026-05-03T17:10:11.239216+00:00  
**Commit**: 6c90747592147f4cfe4ae4a35f7bd4d2d2741db3  
**Host**: Mac  
**GPU**: A10G  
**Cold start**: 95.1s  

## Concurrency = 1

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 275.33 | 273.52 | +0.7% |
| Latency P95 (ms) | 893.49 | 278.53 | +220.8% |
| Latency P99 (ms) | 1293.27 | 278.81 | +363.8% |
| Throughput (rps) | 2.59 | 3.68 | -29.7% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| TTFT P50 (ms) | N/A | N/A | N/A |
| TTFT P95 (ms) | N/A | N/A | N/A |
| TTFT P99 (ms) | N/A | N/A | N/A |
| TPOT P50 (ms) | N/A | N/A | N/A |
| TPOT P95 (ms) | N/A | N/A | N/A |
| TPOT P99 (ms) | N/A | N/A | N/A |
| Proxy ms P50 | 0.181 | N/A | N/A |
| Proxy ms P95 | 0.258 | N/A | N/A |
| Proxy ms P99 | 0.277 | N/A | N/A |

## Concurrency = 4

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 175.67 | 182.44 | -3.7% |
| Latency P95 (ms) | 346.22 | 323.85 | +6.9% |
| Latency P99 (ms) | 346.43 | 324.39 | +6.8% |
| Throughput (rps) | 4.42 | 4.55 | -2.8% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| TTFT P50 (ms) | N/A | N/A | N/A |
| TTFT P95 (ms) | N/A | N/A | N/A |
| TTFT P99 (ms) | N/A | N/A | N/A |
| TPOT P50 (ms) | N/A | N/A | N/A |
| TPOT P95 (ms) | N/A | N/A | N/A |
| TPOT P99 (ms) | N/A | N/A | N/A |
| Proxy ms P50 | 0.045 | N/A | N/A |
| Proxy ms P95 | 0.137 | N/A | N/A |
| Proxy ms P99 | 0.158 | N/A | N/A |

## Concurrency = 8

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 510.49 | 377.19 | +35.3% |
| Latency P95 (ms) | 511.22 | 378.96 | +34.9% |
| Latency P99 (ms) | 511.24 | 379.11 | +34.9% |
| Throughput (rps) | 2.32 | 3.04 | -23.6% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| TTFT P50 (ms) | N/A | N/A | N/A |
| TTFT P95 (ms) | N/A | N/A | N/A |
| TTFT P99 (ms) | N/A | N/A | N/A |
| TPOT P50 (ms) | N/A | N/A | N/A |
| TPOT P95 (ms) | N/A | N/A | N/A |
| TPOT P99 (ms) | N/A | N/A | N/A |
| Proxy ms P50 | 0.031 | N/A | N/A |
| Proxy ms P95 | 0.166 | N/A | N/A |
| Proxy ms P99 | 0.168 | N/A | N/A |
