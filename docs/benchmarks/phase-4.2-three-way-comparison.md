# Three-Way Benchmark Comparison: REST / gRPC-proxy / gRPC-direct

## Run Metadata

**REST**:  
- Timestamp: 2026-05-03T23:39:30.583599+00:00  
- Git SHA: 50be64179f39a052b98a70a4d51f1a29c9b30540  
- Host: Mac  
- GPU: A10G  
- Cold start: 155.2s  

**gRPC-proxy**:  
- Timestamp: 2026-05-03T23:41:57.484425+00:00  
- Git SHA: 50be64179f39a052b98a70a4d51f1a29c9b30540  
- Host: Mac  
- GPU: A10G  
- Cold start: 130.2s  

**gRPC-direct**:  
- Timestamp: 2026-05-03T23:42:10.456416+00:00  
- Git SHA: 50be64179f39a052b98a70a4d51f1a29c9b30540  
- Host: Mac  
- GPU: A10G  
- Cold start: 130.2s  

## Concurrency = 1

| metric | concurrency | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|-------------|------|------------|-----------|-------------|-----------|
| Latency P50 (ms) | 1 | 104.60 | 285.47 | +172.9% | 151.71 | +45.0% |
| Latency P95 (ms) | 1 | 192.11 | 1152.50 | +499.9% | 229.46 | +19.4% |
| Latency P99 (ms) | 1 | 200.88 | 1659.62 | +726.2% | 266.90 | +32.9% |
| Throughput (rps) | 1 | 8.27 | 2.27 | -72.6% | 6.42 | -22.3% |
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
| Latency P50 (ms) | 4 | 118.85 | 245.85 | +106.9% | 240.76 | +102.6% |
| Latency P95 (ms) | 4 | 172.84 | 359.26 | +107.9% | 362.96 | +110.0% |
| Latency P99 (ms) | 4 | 173.16 | 359.38 | +107.5% | 363.04 | +109.7% |
| Throughput (rps) | 4 | 7.43 | 3.92 | -47.3% | 3.91 | -47.4% |
| TTFT P50 (ms) | 4 | N/A | N/A | — | N/A | — |
| TTFT P95 (ms) | 4 | N/A | N/A | — | N/A | — |
| TTFT P99 (ms) | 4 | N/A | N/A | — | N/A | — |
| TPOT P50 (ms) | 4 | N/A | N/A | — | N/A | — |
| TPOT P95 (ms) | 4 | N/A | N/A | — | N/A | — |
| TPOT P99 (ms) | 4 | N/A | N/A | — | N/A | — |
| Request bytes (mean) | 4 | 506 | 506 | +0.0% | 419 | -17.3% |
| Response bytes (mean) | 4 | 611 | 330 | -45.9% | 65 | -89.4% |

## Concurrency = 8

| metric | concurrency | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|-------------|------|------------|-----------|-------------|-----------|
| Latency P50 (ms) | 8 | 181.36 | 373.91 | +106.2% | 355.99 | +96.3% |
| Latency P95 (ms) | 8 | 183.43 | 376.19 | +105.1% | 356.26 | +94.2% |
| Latency P99 (ms) | 8 | 183.46 | 376.35 | +105.1% | 356.31 | +94.2% |
| Throughput (rps) | 8 | 6.02 | 3.02 | -49.7% | 3.20 | -46.8% |
| TTFT P50 (ms) | 8 | N/A | N/A | — | N/A | — |
| TTFT P95 (ms) | 8 | N/A | N/A | — | N/A | — |
| TTFT P99 (ms) | 8 | N/A | N/A | — | N/A | — |
| TPOT P50 (ms) | 8 | N/A | N/A | — | N/A | — |
| TPOT P95 (ms) | 8 | N/A | N/A | — | N/A | — |
| TPOT P99 (ms) | 8 | N/A | N/A | — | N/A | — |
| Request bytes (mean) | 8 | 506 | 506 | +0.0% | 419 | -17.3% |
| Response bytes (mean) | 8 | 611 | 330 | -46.0% | 65 | -89.4% |
