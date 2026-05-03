# vLLM Embedding Input Limitation

## Observed Behavior

The Phase 6 `gRPC-direct | completion-embeds` path fails at runtime: `resp_bytes_mean` is N/A
and all results record `success=False`.  The gRPC frontend receives the request, decodes the
tensor from `prompt_embeds`, and then calls:

```python
engine_input = {"prompt_embeds": tensor}
async for output in self._engine.generate(engine_input, params, request_id=request_id):
```

vLLM 0.20.0 does not accept a `prompt_embeds` key in the inputs dict.  It accepts:
- `str` — raw text prompt (tokenized internally)
- `dict` with `prompt_token_ids: list[int]` — pre-tokenized token IDs

Passing a floating-point embedding tensor directly is not part of the stable vLLM API at
this version.  The engine raises an internal error, which the frontend catches and propagates
as a gRPC `INTERNAL` status.

## Impact

- `grpc-direct | completion-embeds | req_bytes=454807 | resp_bytes=N/A` — request bytes are
  still valid (the proto is serialized correctly before the call), but no response is produced.
- The `base64_overhead_pct` for the embed path can still be computed from request bytes alone
  (33.3%), but latency and throughput numbers for the gRPC-direct embed path are meaningless
  (all failed).
- The proxy embed path also fails for the same reason: the proxy forwards the tensor to the
  same gRPC frontend, which then fails inside vLLM.

## Root Cause

vLLM's embedding-as-input API is not stable in 0.20.0.  Some experimental builds expose a
`prompt_embeds` or `multi_modal_data` path, but it is not part of the public `AsyncLLMEngine`
interface at this version.

## Required Fix

Upgrade to a vLLM release that supports direct embedding input, or add a workaround in the
frontend that maps the embedding tensor to nearest-neighbor token IDs (lossy approximation).
Neither approach is trivial.

Alternatively, if the primary goal is only wire-size measurement (req_bytes), the current data
is sufficient: the 33.3% overhead is computable from the known tensor sizes regardless of
whether the downstream inference succeeds.

## Status

Noted 2026-05-03.  No fix applied.  The `run_completions_grpc_direct_embeds()` runner and the
proxy embed path remain in the codebase; they will produce accurate wire-size measurements and
will automatically start reporting latency/throughput once a vLLM version with embedding input
support is in use.
