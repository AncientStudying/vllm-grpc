# Benchmark Summary

**Run**: 2026-05-02T19:53:32.079730+00:00  
**Commit**: 8e482e1364d4a08a1d754ed44bbf1f52f8c6a671  
**Host**: Mac  
**GPU**: A10G  
**Cold start**: 95.1s  

## Concurrency = 1

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 210.06 | 206.33 | +1.8% |
| Latency P95 (ms) | 825.45 | 305.05 | +170.6% |
| Latency P99 (ms) | 1212.43 | 368.47 | +229.0% |
| Throughput (rps) | 3.12 | 4.49 | -30.5% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 611 | +0.0% |
| Proxy ms P50 | N/A | N/A | N/A |
| Proxy ms P95 | N/A | N/A | N/A |
| Proxy ms P99 | N/A | N/A | N/A |

## Concurrency = 4

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 217.86 | 218.44 | -0.3% |
| Latency P95 (ms) | 410.13 | 406.22 | +1.0% |
| Latency P99 (ms) | 410.27 | 406.87 | +0.8% |
| Throughput (rps) | 3.44 | 3.45 | -0.4% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 611 | +0.0% |
| Proxy ms P50 | N/A | N/A | N/A |
| Proxy ms P95 | N/A | N/A | N/A |
| Proxy ms P99 | N/A | N/A | N/A |

## Concurrency = 8

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 644.54 | 403.65 | +59.7% |
| Latency P95 (ms) | 645.72 | 408.31 | +58.1% |
| Latency P99 (ms) | 645.72 | 408.35 | +58.1% |
| Throughput (rps) | 1.79 | 2.74 | -34.5% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 611 | +0.0% |
| Proxy ms P50 | N/A | N/A | N/A |
| Proxy ms P95 | N/A | N/A | N/A |
| Proxy ms P99 | N/A | N/A | N/A |
