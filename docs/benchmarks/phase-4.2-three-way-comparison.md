# Three-Way Benchmark Comparison: REST / gRPC-proxy / gRPC-direct

## Run Metadata

**REST**:  
- Timestamp: 2026-05-02T19:53:32.079730+00:00  
- Git SHA: 8e482e1364d4a08a1d754ed44bbf1f52f8c6a671  
- Host: Mac  
- GPU: A10G  
- Cold start: 95.1s  

**gRPC-proxy**:  
- Timestamp: 2026-05-02T19:56:14.102223+00:00  
- Git SHA: 8e482e1364d4a08a1d754ed44bbf1f52f8c6a671  
- Host: Mac  
- GPU: A10G  
- Cold start: 125.2s  

**gRPC-direct**:  
- Timestamp: 2026-05-02T19:56:28.705873+00:00  
- Git SHA: 8e482e1364d4a08a1d754ed44bbf1f52f8c6a671  
- Host: Mac  
- GPU: A10G  
- Cold start: 125.2s  

## Concurrency = 1

| metric | concurrency | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|-------------|------|------------|-----------|-------------|-----------|
| Latency P50 (ms) | 1 | 206.33 | 330.62 | +60.2% | 131.85 | -36.1% |
| Latency P95 (ms) | 1 | 305.05 | 1109.90 | +263.8% | 266.87 | -12.5% |
| Latency P99 (ms) | 1 | 368.47 | 1614.66 | +338.2% | 310.45 | -15.7% |
| Throughput (rps) | 1 | 4.49 | 2.12 | -52.8% | 6.42 | +42.9% |
| Request bytes (mean) | 1 | 506 | 506 | +0.0% | 419 | -17.3% |
| Response bytes (mean) | 1 | 611 | 330 | -46.0% | 65 | -89.4% |

## Concurrency = 4

| metric | concurrency | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|-------------|------|------------|-----------|-------------|-----------|
| Latency P50 (ms) | 4 | 218.44 | 336.06 | +53.8% | 208.52 | -4.5% |
| Latency P95 (ms) | 4 | 406.22 | 352.45 | -13.2% | 344.30 | -15.2% |
| Latency P99 (ms) | 4 | 406.87 | 352.63 | -13.3% | 344.34 | -15.4% |
| Throughput (rps) | 4 | 3.45 | 2.94 | -15.0% | 3.93 | +13.7% |
| Request bytes (mean) | 4 | 506 | 506 | +0.0% | 419 | -17.3% |
| Response bytes (mean) | 4 | 611 | 330 | -46.0% | 65 | -89.4% |

## Concurrency = 8

| metric | concurrency | REST | gRPC-proxy | Δ vs REST | gRPC-direct | Δ vs REST |
|--------|-------------|------|------------|-----------|-------------|-----------|
| Latency P50 (ms) | 8 | 403.65 | 597.40 | +48.0% | 329.23 | -18.4% |
| Latency P95 (ms) | 8 | 408.31 | 598.48 | +46.6% | 329.54 | -19.3% |
| Latency P99 (ms) | 8 | 408.35 | 598.76 | +46.6% | 329.58 | -19.3% |
| Throughput (rps) | 8 | 2.74 | 1.96 | -28.3% | 3.30 | +20.8% |
| Request bytes (mean) | 8 | 506 | 506 | +0.0% | 419 | -17.3% |
| Response bytes (mean) | 8 | 611 | 330 | -46.0% | 65 | -89.4% |
