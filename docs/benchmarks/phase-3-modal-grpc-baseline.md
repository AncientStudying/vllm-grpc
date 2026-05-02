# Benchmark Summary

**Run**: 2026-05-02T12:40:39.803520+00:00  
**Commit**: 99faf976b662d70d501820b7a87cdc49644be09b  
**Host**: Mac  

## Concurrency = 1

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 664.15 | 663.27 | +0.1% |
| Latency P95 (ms) | 1187.68 | 756.74 | +56.9% |
| Latency P99 (ms) | 1461.30 | 770.43 | +89.7% |
| Throughput (rps) | 1.30 | 1.45 | -10.5% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| Proxy ms P50 | 0.242 | N/A | N/A |
| Proxy ms P95 | 0.383 | N/A | N/A |
| Proxy ms P99 | 0.415 | N/A | N/A |

## Concurrency = 4

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 717.24 | 662.95 | +8.2% |
| Latency P95 (ms) | 722.87 | 669.78 | +7.9% |
| Latency P99 (ms) | 723.00 | 669.92 | +7.9% |
| Throughput (rps) | 1.43 | 1.51 | -4.9% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| Proxy ms P50 | 0.050 | N/A | N/A |
| Proxy ms P95 | 0.157 | N/A | N/A |
| Proxy ms P99 | 0.167 | N/A | N/A |

## Concurrency = 8

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 811.21 | 661.34 | +22.7% |
| Latency P95 (ms) | 812.58 | 661.99 | +22.7% |
| Latency P99 (ms) | 812.76 | 662.15 | +22.7% |
| Throughput (rps) | 1.25 | 1.52 | -17.6% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| Proxy ms P50 | 0.037 | N/A | N/A |
| Proxy ms P95 | 0.122 | N/A | N/A |
| Proxy ms P99 | 0.122 | N/A | N/A |
