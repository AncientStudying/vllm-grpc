# Three-Way Benchmark Comparison: REST / gRPC-proxy / gRPC-direct

## Run Metadata

**REST**:  
- Timestamp: 2026-05-03T17:08:14.941882+00:00  
- Git SHA: 6c90747592147f4cfe4ae4a35f7bd4d2d2741db3  
- Host: Mac  
- GPU: A10G  
- Cold start: 151.3s  

**gRPC-proxy**:  
- Timestamp: 2026-05-03T17:10:11.239216+00:00  
- Git SHA: 6c90747592147f4cfe4ae4a35f7bd4d2d2741db3  
- Host: Mac  
- GPU: A10G  
- Cold start: 95.1s  

**gRPC-direct**:  
- Timestamp: 2026-05-03T17:10:22.700958+00:00  
- Git SHA: 6c90747592147f4cfe4ae4a35f7bd4d2d2741db3  
- Host: Mac  
- GPU: A10G  
- Cold start: 95.1s  

## Concurrency = 1

| metric | concurrency | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|-------------|------|------------|-----------|-------------|-----------|
| Latency P50 (ms) | 1 | 110.55 | 275.33 | +149.1% | 117.80 | +6.6% |
| Latency P95 (ms) | 1 | 188.17 | 893.49 | +374.8% | 218.90 | +16.3% |
| Latency P99 (ms) | 1 | 193.65 | 1293.27 | +567.8% | 259.81 | +34.2% |
| Throughput (rps) | 1 | 8.00 | 2.59 | -67.7% | 7.51 | -6.0% |
| TTFT P50 (ms) | 1 | N/A | N/A | — | N/A | — |
| TTFT P95 (ms) | 1 | N/A | N/A | — | N/A | — |
| TTFT P99 (ms) | 1 | N/A | N/A | — | N/A | — |
| TPOT P50 (ms) | 1 | N/A | N/A | — | N/A | — |
| TPOT P95 (ms) | 1 | N/A | N/A | — | N/A | — |
| TPOT P99 (ms) | 1 | N/A | N/A | — | N/A | — |
| Request bytes (mean) | 1 | 506 | 506 | +0.0% | 419 | -17.3% |
| Response bytes (mean) | 1 | 611 | 330 | -46.0% | 65 | -89.4% |

## Concurrency = 4

| metric | concurrency | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|-------------|------|------------|-----------|-------------|-----------|
| Latency P50 (ms) | 4 | 120.63 | 175.67 | +45.6% | 153.82 | +27.5% |
| Latency P95 (ms) | 4 | 214.83 | 346.22 | +61.2% | 325.91 | +51.7% |
| Latency P99 (ms) | 4 | 215.43 | 346.43 | +60.8% | 325.96 | +51.3% |
| Throughput (rps) | 4 | 6.50 | 4.42 | -32.0% | 4.77 | -26.7% |
| TTFT P50 (ms) | 4 | N/A | N/A | — | N/A | — |
| TTFT P95 (ms) | 4 | N/A | N/A | — | N/A | — |
| TTFT P99 (ms) | 4 | N/A | N/A | — | N/A | — |
| TPOT P50 (ms) | 4 | N/A | N/A | — | N/A | — |
| TPOT P95 (ms) | 4 | N/A | N/A | — | N/A | — |
| TPOT P99 (ms) | 4 | N/A | N/A | — | N/A | — |
| Request bytes (mean) | 4 | 506 | 506 | +0.0% | 419 | -17.3% |
| Response bytes (mean) | 4 | 611 | 330 | -46.0% | 65 | -89.4% |

## Concurrency = 8

| metric | concurrency | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|-------------|------|------------|-----------|-------------|-----------|
| Latency P50 (ms) | 8 | 402.42 | 510.49 | +26.9% | 321.96 | -20.0% |
| Latency P95 (ms) | 8 | 403.79 | 511.22 | +26.6% | 322.32 | -20.2% |
| Latency P99 (ms) | 8 | 403.86 | 511.24 | +26.6% | 322.33 | -20.2% |
| Throughput (rps) | 8 | 2.89 | 2.32 | -19.7% | 3.52 | +21.6% |
| TTFT P50 (ms) | 8 | N/A | N/A | — | N/A | — |
| TTFT P95 (ms) | 8 | N/A | N/A | — | N/A | — |
| TTFT P99 (ms) | 8 | N/A | N/A | — | N/A | — |
| TPOT P50 (ms) | 8 | N/A | N/A | — | N/A | — |
| TPOT P95 (ms) | 8 | N/A | N/A | — | N/A | — |
| TPOT P99 (ms) | 8 | N/A | N/A | — | N/A | — |
| Request bytes (mean) | 8 | 506 | 506 | +0.0% | 419 | -17.3% |
| Response bytes (mean) | 8 | 611 | 330 | -46.0% | 65 | -89.4% |
