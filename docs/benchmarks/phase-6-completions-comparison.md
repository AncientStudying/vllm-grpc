# Completions Benchmark: Wire-Size and Latency (M1)

## Methodology

- **Native REST**: vLLM's own OpenAI-compatible REST endpoint (text and embeds)
- **Proxy REST**: gRPC proxy REST facade; base64-encodes `torch.save()` bytes for embeds
- **gRPC-direct**: raw proto `bytes` field, no base64 encoding
- Baseline for text completions is native REST (the conventional approach).
- Baseline for embed completions is native REST (isolates protocol from proxy overhead).

## Wire-Size Summary

| path | input_type | req_bytes_mean | resp_bytes_mean | Δ vs baseline |
|------|------------|----------------|-----------------|---------------|
