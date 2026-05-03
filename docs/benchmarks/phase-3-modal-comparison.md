# Benchmark Comparison: REST vs gRPC

## Run Metadata

**REST**:  
- Timestamp: 2026-05-03T17:08:14.941882+00:00  
- Git SHA: 6c90747592147f4cfe4ae4a35f7bd4d2d2741db3  
- Host: Mac  
- GPU: A10G  
- Cold start: 151.3s  

**gRPC**:  
- Timestamp: 2026-05-03T17:10:11.239216+00:00  
- Git SHA: 6c90747592147f4cfe4ae4a35f7bd4d2d2741db3  
- Host: Mac  
- GPU: A10G  
- Cold start: 95.1s  

## Concurrency = 1

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 110.55 | 275.33 | +149.1% |
| Latency P95 (ms) | 188.17 | 893.49 | +374.8% |
| Latency P99 (ms) | 193.65 | 1293.27 | +567.8% |
| Throughput (rps) | 8.00 | 2.59 | -67.7% |
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
| Latency P50 (ms) | 120.63 | 175.67 | +45.6% |
| Latency P95 (ms) | 214.83 | 346.22 | +61.2% |
| Latency P99 (ms) | 215.43 | 346.43 | +60.8% |
| Throughput (rps) | 6.50 | 4.42 | -32.0% |
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
| Latency P50 (ms) | 402.42 | 510.49 | +26.9% |
| Latency P95 (ms) | 403.79 | 511.22 | +26.6% |
| Latency P99 (ms) | 403.86 | 511.24 | +26.6% |
| Throughput (rps) | 2.89 | 2.32 | -19.7% |
| TTFT P50 (ms) | N/A | N/A | — |
| TTFT P95 (ms) | N/A | N/A | — |
| TTFT P99 (ms) | N/A | N/A | — |
| TPOT P50 (ms) | N/A | N/A | — |
| TPOT P95 (ms) | N/A | N/A | — |
| TPOT P99 (ms) | N/A | N/A | — |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -46.0% |
