# Three-Way Benchmark Comparison: REST / gRPC-proxy / gRPC-direct

## Run Metadata

**REST**:  
- Timestamp: 2026-05-03T00:35:23.330227+00:00  
- Git SHA: 14eccd46c01c4583f3b865fd1459c769cc2c3a6a  
- Host: Mac  
- GPU: A10G  
- Cold start: 150.2s  

**gRPC-proxy**:  
- Timestamp: 2026-05-03T00:38:12.013260+00:00  
- Git SHA: 14eccd46c01c4583f3b865fd1459c769cc2c3a6a  
- Host: Mac  
- GPU: A10G  
- Cold start: 155.2s  

**gRPC-direct**:  
- Timestamp: 2026-05-03T00:38:24.150203+00:00  
- Git SHA: 14eccd46c01c4583f3b865fd1459c769cc2c3a6a  
- Host: Mac  
- GPU: A10G  
- Cold start: 155.2s  

## Concurrency = 1

| metric | concurrency | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|-------------|------|------------|-----------|-------------|-----------|
| Latency P50 (ms) | 1 | 112.97 | 274.09 | +142.6% | 115.03 | +1.8% |
| Latency P95 (ms) | 1 | 167.11 | 1034.72 | +519.2% | 216.08 | +29.3% |
| Latency P99 (ms) | 1 | 197.27 | 1529.18 | +675.2% | 252.48 | +28.0% |
| Throughput (rps) | 1 | 8.14 | 2.44 | -70.0% | 7.49 | -8.0% |
| Request bytes (mean) | 1 | 506 | 506 | +0.0% | 419 | -17.3% |
| Response bytes (mean) | 1 | 611 | 330 | -46.0% | 65 | -89.4% |

## Concurrency = 4

| metric | concurrency | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|-------------|------|------------|-----------|-------------|-----------|
| Latency P50 (ms) | 4 | 123.27 | 193.63 | +57.1% | 197.72 | +60.4% |
| Latency P95 (ms) | 4 | 226.75 | 369.06 | +62.8% | 312.36 | +37.8% |
| Latency P99 (ms) | 4 | 227.04 | 369.32 | +62.7% | 312.43 | +37.6% |
| Throughput (rps) | 4 | 6.28 | 4.10 | -34.7% | 4.58 | -27.1% |
| Request bytes (mean) | 4 | 506 | 506 | +0.0% | 419 | -17.3% |
| Response bytes (mean) | 4 | 611 | 330 | -46.0% | 65 | -89.4% |

## Concurrency = 8

| metric | concurrency | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|-------------|------|------------|-----------|-------------|-----------|
| Latency P50 (ms) | 8 | 228.87 | 631.39 | +175.9% | 377.88 | +65.1% |
| Latency P95 (ms) | 8 | 231.11 | 632.01 | +173.5% | 378.04 | +63.6% |
| Latency P99 (ms) | 8 | 231.76 | 632.09 | +172.7% | 378.08 | +63.1% |
| Throughput (rps) | 8 | 4.80 | 1.89 | -60.7% | 3.05 | -36.5% |
| Request bytes (mean) | 8 | 506 | 506 | +0.0% | 419 | -17.3% |
| Response bytes (mean) | 8 | 611 | 330 | -46.0% | 65 | -89.4% |
