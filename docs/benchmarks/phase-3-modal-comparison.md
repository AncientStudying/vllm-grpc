# Benchmark Comparison: REST vs gRPC

## Run Metadata

**REST**:  
- Timestamp: 2026-05-03T23:39:30.583599+00:00  
- Git SHA: 50be64179f39a052b98a70a4d51f1a29c9b30540  
- Host: Mac  
- GPU: A10G  
- Cold start: 155.2s  

**gRPC**:  
- Timestamp: 2026-05-03T23:41:57.484425+00:00  
- Git SHA: 50be64179f39a052b98a70a4d51f1a29c9b30540  
- Host: Mac  
- GPU: A10G  
- Cold start: 130.2s  

## Concurrency = 1

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 104.60 | 285.47 | +172.9% |
| Latency P95 (ms) | 192.11 | 1152.50 | +499.9% |
| Latency P99 (ms) | 200.88 | 1659.62 | +726.2% |
| Throughput (rps) | 8.27 | 2.27 | -72.6% |
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
| Latency P50 (ms) | 118.85 | 245.85 | +106.9% |
| Latency P95 (ms) | 172.84 | 359.26 | +107.9% |
| Latency P99 (ms) | 173.16 | 359.38 | +107.5% |
| Throughput (rps) | 7.43 | 3.92 | -47.3% |
| TTFT P50 (ms) | N/A | N/A | — |
| TTFT P95 (ms) | N/A | N/A | — |
| TTFT P99 (ms) | N/A | N/A | — |
| TPOT P50 (ms) | N/A | N/A | — |
| TPOT P95 (ms) | N/A | N/A | — |
| TPOT P99 (ms) | N/A | N/A | — |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -45.9% |

## Concurrency = 8

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 181.36 | 373.91 | +106.2% |
| Latency P95 (ms) | 183.43 | 376.19 | +105.1% |
| Latency P99 (ms) | 183.46 | 376.35 | +105.1% |
| Throughput (rps) | 6.02 | 3.02 | -49.7% |
| TTFT P50 (ms) | N/A | N/A | — |
| TTFT P95 (ms) | N/A | N/A | — |
| TTFT P99 (ms) | N/A | N/A | — |
| TPOT P50 (ms) | N/A | N/A | — |
| TPOT P95 (ms) | N/A | N/A | — |
| TPOT P99 (ms) | N/A | N/A | — |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -46.0% |
