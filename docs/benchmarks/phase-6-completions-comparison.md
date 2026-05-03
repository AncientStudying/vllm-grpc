# Wire-Size Comparison: REST vs gRPC-Direct

## Methodology

- REST path: JSON body with base64-encoded `torch.save()` bytes (~33% overhead)
- gRPC-direct path: raw `bytes` field, no base64 encoding
- All paths use identical tensor content; overhead is encoding only

## Wire-Size by Path and Input Type

| path | input_type | req_bytes_mean | resp_bytes_mean | base64_overhead_pct |
|------|------------|---------------|-----------------|---------------------|
| proxy | completion-text | 377 | N/A | 14.7% |
| grpc-direct | completion-text | 329 | 272 | baseline (REST is +14.7%) |
| proxy | completion-embeds | 606479 | N/A | 33.3% |
| grpc-direct | completion-embeds | 454807 | N/A | baseline (REST is +33.3%) |
