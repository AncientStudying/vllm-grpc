# Quickstart: Phase 6.1

No changes to the developer quickstart. The frontend startup command is unchanged.

## Verifying the Fix

### 1. Local checks (no GPU required)

```bash
make check   # ruff + mypy --strict + pytest
```

Unit tests mock the vLLM engine and exercise the servicer logic. They pass without a GPU.

### 2. Smoke test — vLLM native REST (Modal A10G)

```bash
modal run scripts/python/verify_prompt_embeds_modal.py
```

Confirms vLLM 0.20.0 on A10G accepts `prompt_embeds` through the OpenAI REST layer.

### 3. End-to-end benchmark (Modal A10G)

```bash
make bench-modal
```

After the updated frontend wheel is deployed, the `grpc-direct | completion-embeds` and
`proxy | completion-embeds` rows should show `success=True` and real latency/wire-size numbers.

## Expected Benchmark Change

| Path | Before fix | After fix |
|------|-----------|-----------|
| `grpc-direct \| completion-embeds` | `success=False`, `resp_bytes=N/A` | `success=True`, real numbers |
| `proxy \| completion-embeds` | `success=False`, `resp_bytes=N/A` | `success=True`, real numbers |
| `grpc-direct \| text` | `success=True` | `success=True` (unchanged) |
| `proxy \| text` | `success=True` | `success=True` (unchanged) |
| `rest` | `success=True` | `success=True` (unchanged) |
