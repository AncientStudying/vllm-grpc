# Three-Way Benchmark Comparison: REST / gRPC-proxy / gRPC-direct

## Run Metadata

**REST**:  
- Timestamp: 2026-05-03T19:27:43.200012+00:00  
- Git SHA: 720a95a579bfb23e8c3b1177a94624e0c0a8c4cb  
- Host: Mac  
- GPU: A10G  
- Cold start: 125.2s  

**gRPC-proxy**:  
- Timestamp: 2026-05-03T19:30:54.685592+00:00  
- Git SHA: 720a95a579bfb23e8c3b1177a94624e0c0a8c4cb  
- Host: Mac  
- GPU: A10G  
- Cold start: 175.3s  

**gRPC-direct**:  
- Timestamp: 2026-05-03T19:31:09.785940+00:00  
- Git SHA: 720a95a579bfb23e8c3b1177a94624e0c0a8c4cb  
- Host: Mac  
- GPU: A10G  
- Cold start: 175.3s  

## Concurrency = 1

| metric | concurrency | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|-------------|------|------------|-----------|-------------|-----------|
| Latency P50 (ms) | 1 | 106.33 | 334.68 | +214.8% | 143.60 | +35.0% |
| Latency P95 (ms) | 1 | 160.91 | 1591.16 | +888.9% | 271.69 | +68.9% |
| Latency P99 (ms) | 1 | 191.70 | 2404.47 | +1154.3% | 318.04 | +65.9% |
| Throughput (rps) | 1 | 8.65 | 1.77 | -79.5% | 5.98 | -30.8% |
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
| Latency P50 (ms) | 4 | 118.64 | 250.31 | +111.0% | 221.45 | +86.7% |
| Latency P95 (ms) | 4 | 165.51 | 404.28 | +144.3% | 338.75 | +104.7% |
| Latency P99 (ms) | 4 | 165.70 | 404.53 | +144.1% | 338.77 | +104.4% |
| Throughput (rps) | 4 | 7.39 | 3.49 | -52.7% | 3.90 | -47.3% |
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
| Latency P50 (ms) | 8 | 175.64 | 404.31 | +130.2% | 424.14 | +141.5% |
| Latency P95 (ms) | 8 | 178.17 | 405.35 | +127.5% | 424.53 | +138.3% |
| Latency P99 (ms) | 8 | 178.53 | 405.48 | +127.1% | 424.54 | +137.8% |
| Throughput (rps) | 8 | 6.16 | 2.82 | -54.2% | 2.66 | -56.7% |
| TTFT P50 (ms) | 8 | N/A | N/A | — | N/A | — |
| TTFT P95 (ms) | 8 | N/A | N/A | — | N/A | — |
| TTFT P99 (ms) | 8 | N/A | N/A | — | N/A | — |
| TPOT P50 (ms) | 8 | N/A | N/A | — | N/A | — |
| TPOT P95 (ms) | 8 | N/A | N/A | — | N/A | — |
| TPOT P99 (ms) | 8 | N/A | N/A | — | N/A | — |
| Request bytes (mean) | 8 | 506 | 506 | +0.0% | 419 | -17.3% |
| Response bytes (mean) | 8 | 611 | 330 | -46.0% | 65 | -89.4% |
