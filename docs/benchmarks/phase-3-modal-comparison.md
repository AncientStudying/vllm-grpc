# Benchmark Comparison: REST vs gRPC

## Run Metadata

**REST**:  
- Timestamp: 2026-05-03T00:35:23.330227+00:00  
- Git SHA: 14eccd46c01c4583f3b865fd1459c769cc2c3a6a  
- Host: Mac  
- GPU: A10G  
- Cold start: 150.2s  

**gRPC**:  
- Timestamp: 2026-05-03T00:38:12.013260+00:00  
- Git SHA: 14eccd46c01c4583f3b865fd1459c769cc2c3a6a  
- Host: Mac  
- GPU: A10G  
- Cold start: 155.2s  

## Concurrency = 1

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 112.97 | 274.09 | +142.6% |
| Latency P95 (ms) | 167.11 | 1034.72 | +519.2% |
| Latency P99 (ms) | 197.27 | 1529.18 | +675.2% |
| Throughput (rps) | 8.14 | 2.44 | -70.0% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -46.0% |

## Concurrency = 4

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 123.27 | 193.63 | +57.1% |
| Latency P95 (ms) | 226.75 | 369.06 | +62.8% |
| Latency P99 (ms) | 227.04 | 369.32 | +62.7% |
| Throughput (rps) | 6.28 | 4.10 | -34.7% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -46.0% |

## Concurrency = 8

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 228.87 | 631.39 | +175.9% |
| Latency P95 (ms) | 231.11 | 632.01 | +173.5% |
| Latency P99 (ms) | 231.76 | 632.09 | +172.7% |
| Throughput (rps) | 4.80 | 1.89 | -60.7% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -46.0% |
