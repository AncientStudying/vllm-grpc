# Three-Way Benchmark Comparison: REST / gRPC-proxy / gRPC-direct

## Run Metadata

**REST**:  
- Timestamp: 2026-05-03T16:11:37.977528+00:00  
- Git SHA: 5deae6c26db531cdd00efbd1c3c294e58f3be125  
- Host: Mac  
- GPU: A10G  
- Cold start: 161.0s  

**gRPC-proxy**:  
- Timestamp: 2026-05-03T16:13:57.971581+00:00  
- Git SHA: 5deae6c26db531cdd00efbd1c3c294e58f3be125  
- Host: Mac  
- GPU: A10G  
- Cold start: 105.3s  

**gRPC-direct**:  
- Timestamp: 2026-05-03T16:14:09.589516+00:00  
- Git SHA: 5deae6c26db531cdd00efbd1c3c294e58f3be125  
- Host: Mac  
- GPU: A10G  
- Cold start: 105.3s  

## Concurrency = 1

| metric | concurrency | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|-------------|------|------------|-----------|-------------|-----------|
| Latency P50 (ms) | 1 | 316.73 | 255.79 | -19.2% | 116.81 | -63.1% |
| Latency P95 (ms) | 1 | 630.01 | 1092.25 | +73.4% | 212.26 | -66.3% |
| Latency P99 (ms) | 1 | 772.75 | 1628.29 | +110.7% | 250.08 | -67.6% |
| Throughput (rps) | 1 | 2.57 | 2.48 | -3.5% | 7.43 | +189.6% |
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
| Latency P50 (ms) | 4 | 411.48 | 190.07 | -53.8% | 184.59 | -55.1% |
| Latency P95 (ms) | 4 | 818.12 | 330.31 | -59.6% | 300.16 | -63.3% |
| Latency P99 (ms) | 4 | 826.04 | 330.86 | -59.9% | 300.26 | -63.7% |
| Throughput (rps) | 4 | 1.82 | 4.52 | +149.1% | 4.45 | +144.9% |
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
| Latency P50 (ms) | 8 | 805.07 | 520.95 | -35.3% | 304.90 | -62.1% |
| Latency P95 (ms) | 8 | 815.13 | 521.92 | -36.0% | 305.26 | -62.6% |
| Latency P99 (ms) | 8 | 816.50 | 522.12 | -36.1% | 305.29 | -62.6% |
| Throughput (rps) | 8 | 1.41 | 2.27 | +61.1% | 3.73 | +164.0% |
| TTFT P50 (ms) | 8 | N/A | N/A | — | N/A | — |
| TTFT P95 (ms) | 8 | N/A | N/A | — | N/A | — |
| TTFT P99 (ms) | 8 | N/A | N/A | — | N/A | — |
| TPOT P50 (ms) | 8 | N/A | N/A | — | N/A | — |
| TPOT P95 (ms) | 8 | N/A | N/A | — | N/A | — |
| TPOT P99 (ms) | 8 | N/A | N/A | — | N/A | — |
| Request bytes (mean) | 8 | 506 | 506 | +0.0% | 419 | -17.3% |
| Response bytes (mean) | 8 | 611 | 330 | -46.0% | 65 | -89.4% |
