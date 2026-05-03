# vLLM Embedding Input Limitation

## Observed Behavior

The Phase 6 `gRPC-direct | completion-embeds` path fails at runtime: `resp_bytes_mean` is N/A
and all results record `success=False`.  The gRPC frontend receives the request, decodes the
tensor from `prompt_embeds`, and then calls:

```python
engine_input = {"prompt_embeds": tensor}
async for output in self._engine.generate(engine_input, params, request_id=request_id):
```

The engine raises an internal error, which the frontend catches and propagates as a gRPC
`INTERNAL` status.

## Impact

- `grpc-direct | completion-embeds | req_bytes=454807 | resp_bytes=N/A` — request bytes are
  still valid (the proto is serialized correctly before the call), but no response is produced.
- The `base64_overhead_pct` for the embed path can still be computed from request bytes alone
  (33.3%), but latency and throughput numbers for the gRPC-direct embed path are meaningless
  (all failed).
- The proxy embed path also fails for the same reason: the proxy forwards the tensor to the
  same gRPC frontend, which then fails inside vLLM.

## Root Cause

**Original diagnosis (incorrect):** vLLM's embedding-as-input API was assumed to be unstable
in 0.20.0 and not part of the public `AsyncLLMEngine` interface.

**Actual root cause:** In vLLM 0.19+, `AsyncLLMEngine` is a direct alias for `AsyncLLM`
(the v1 engine). The v1 engine supports `{"prompt_embeds": tensor}` input, but only when
`enable_prompt_embeds=True` is passed to `AsyncEngineArgs`. Without this flag,
`vllm/renderers/embed_utils.py` raises a hard error on any request that carries
`prompt_embeds`. The proto encoding, proxy base64-decode, tensor deserialization in
`completions_translate.py`, and the `{"prompt_embeds": tensor}` dict format in
`completions.py` are all correct as written.

## Required Fix

Add `enable_prompt_embeds=True` to `AsyncEngineArgs` in
`packages/frontend/src/vllm_grpc_frontend/main.py`. No other files need to change.

```python
# Before
engine = AsyncLLMEngine.from_engine_args(AsyncEngineArgs(model=model_name))

# After
engine = AsyncLLMEngine.from_engine_args(
    AsyncEngineArgs(model=model_name, enable_prompt_embeds=True)
)
```

## Status

Fixed 2026-05-03 via Phase 6.1.  See
`packages/frontend/src/vllm_grpc_frontend/main.py` and
`specs/011-phase-6.1/` for the speckit artifacts.
