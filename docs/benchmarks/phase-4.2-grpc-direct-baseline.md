# Benchmark Summary

**Run**: 2026-05-02T19:56:28.705873+00:00  
**Commit**: 8e482e1364d4a08a1d754ed44bbf1f52f8c6a671  
**Host**: Mac  
**GPU**: A10G  
**Cold start**: 125.2s  

## Concurrency = 1

| Metric | gRPC-direct |
|--------|-------------|
| Latency P50 (ms) | 131.85 |
| Latency P95 (ms) | 266.87 |
| Latency P99 (ms) | 310.45 |
| Throughput (rps) | 6.42 |
| Request bytes (mean) | 419 |
| Response bytes (mean) | 65 |

## Concurrency = 4

| Metric | gRPC-direct |
|--------|-------------|
| Latency P50 (ms) | 208.52 |
| Latency P95 (ms) | 344.30 |
| Latency P99 (ms) | 344.34 |
| Throughput (rps) | 3.93 |
| Request bytes (mean) | 419 |
| Response bytes (mean) | 65 |

## Concurrency = 8

| Metric | gRPC-direct |
|--------|-------------|
| Latency P50 (ms) | 329.23 |
| Latency P95 (ms) | 329.54 |
| Latency P99 (ms) | 329.58 |
| Throughput (rps) | 3.30 |
| Request bytes (mean) | 419 |
| Response bytes (mean) | 65 |
