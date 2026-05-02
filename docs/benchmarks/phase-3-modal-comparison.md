# Benchmark Comparison: REST vs gRPC

## Run Metadata

**REST**:  
- Timestamp: 2026-05-02T19:53:32.079730+00:00  
- Git SHA: 8e482e1364d4a08a1d754ed44bbf1f52f8c6a671  
- Host: Mac  
- GPU: A10G  
- Cold start: 95.1s  

**gRPC**:  
- Timestamp: 2026-05-02T19:56:14.102223+00:00  
- Git SHA: 8e482e1364d4a08a1d754ed44bbf1f52f8c6a671  
- Host: Mac  
- GPU: A10G  
- Cold start: 125.2s  

## Concurrency = 1

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 206.33 | 330.62 | +60.2% |
| Latency P95 (ms) | 305.05 | 1109.90 | +263.8% |
| Latency P99 (ms) | 368.47 | 1614.66 | +338.2% |
| Throughput (rps) | 4.49 | 2.12 | -52.8% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -46.0% |

## Concurrency = 4

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 218.44 | 336.06 | +53.8% |
| Latency P95 (ms) | 406.22 | 352.45 | -13.2% |
| Latency P99 (ms) | 406.87 | 352.63 | -13.3% |
| Throughput (rps) | 3.45 | 2.94 | -15.0% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -46.0% |

## Concurrency = 8

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 403.65 | 597.40 | +48.0% |
| Latency P95 (ms) | 408.31 | 598.48 | +46.6% |
| Latency P99 (ms) | 408.35 | 598.76 | +46.6% |
| Throughput (rps) | 2.74 | 1.96 | -28.3% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -46.0% |
