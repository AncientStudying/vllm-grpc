# Benchmark Comparison: REST vs gRPC

## Run Metadata

**REST**:  
- Timestamp: 2026-05-02T12:39:11.078160+00:00  
- Git SHA: 99faf976b662d70d501820b7a87cdc49644be09b  
- Host: Mac  
- GPU: A10G  
- Cold start: 95.1s  

**gRPC**:  
- Timestamp: 2026-05-02T12:40:39.803520+00:00  
- Git SHA: 99faf976b662d70d501820b7a87cdc49644be09b  
- Host: Mac  
- GPU: A10G  
- Cold start: 75.1s  

## Concurrency = 1

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 105.58 | 664.15 | +529.1% |
| Latency P95 (ms) | 147.24 | 1187.68 | +706.6% |
| Latency P99 (ms) | 155.16 | 1461.30 | +841.8% |
| Throughput (rps) | 8.78 | 1.30 | -85.2% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -46.0% |

## Concurrency = 4

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 117.33 | 717.24 | +511.3% |
| Latency P95 (ms) | 172.81 | 722.87 | +318.3% |
| Latency P99 (ms) | 173.18 | 723.00 | +317.5% |
| Throughput (rps) | 7.28 | 1.43 | -80.3% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -46.0% |

## Concurrency = 8

| Metric | REST | gRPC | Δ |
|--------|------|------|---|
| Latency P50 (ms) | 186.68 | 811.21 | +334.5% |
| Latency P95 (ms) | 190.41 | 812.58 | +326.7% |
| Latency P99 (ms) | 190.65 | 812.76 | +326.3% |
| Throughput (rps) | 5.64 | 1.25 | -77.8% |
| Request bytes (mean) | 506 | 506 | +0.0% |
| Response bytes (mean) | 611 | 330 | -46.0% |
