# Benchmark Summary

**Run**: 2026-05-02T19:56:14.102223+00:00  
**Commit**: 8e482e1364d4a08a1d754ed44bbf1f52f8c6a671  
**Host**: Mac  
**GPU**: A10G  
**Cold start**: 125.2s  

## Concurrency = 1

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 330.62 | 335.58 | -1.5% |
| Latency P95 (ms) | 1109.90 | 350.47 | +216.7% |
| Latency P99 (ms) | 1614.66 | 353.10 | +357.3% |
| Throughput (rps) | 2.12 | 3.11 | -31.9% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| Proxy ms P50 | 0.168 | N/A | N/A |
| Proxy ms P95 | 0.214 | N/A | N/A |
| Proxy ms P99 | 0.216 | N/A | N/A |

## Concurrency = 4

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 336.06 | 340.93 | -1.4% |
| Latency P95 (ms) | 352.45 | 342.53 | +2.9% |
| Latency P99 (ms) | 352.63 | 342.57 | +2.9% |
| Throughput (rps) | 2.94 | 2.95 | -0.4% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| Proxy ms P50 | 0.062 | N/A | N/A |
| Proxy ms P95 | 0.105 | N/A | N/A |
| Proxy ms P99 | 0.107 | N/A | N/A |

## Concurrency = 8

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) | 597.40 | 341.50 | +74.9% |
| Latency P95 (ms) | 598.48 | 342.61 | +74.7% |
| Latency P99 (ms) | 598.76 | 342.66 | +74.7% |
| Throughput (rps) | 1.96 | 2.93 | -33.1% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 330 | 330 | +0.0% |
| Proxy ms P50 | 0.024 | N/A | N/A |
| Proxy ms P95 | 0.131 | N/A | N/A |
| Proxy ms P99 | 0.134 | N/A | N/A |
