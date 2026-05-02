# Contract: SmokeTestResult Return Value

**Version**: 1.0 | **Phase**: 3.1

## Schema

Both `modal_frontend_smoke.py` and `modal_vllm_rest.py` return a `dict` with this shape:

```python
{
    "ok": bool,                     # True = smoke test passed
    "error": str | None,            # None if ok=True; error message if ok=False
    "cold_start_s": float,          # function invocation → server ready (excludes model download)
    "request_latency_s": float,     # time for the single smoke-test completion request
    "completion_text": str | None,  # choices[0].message.content (or choices[0].text for completions)
    "model": str,                   # "/mnt/weights"
    "seed": int,                    # 42
    "max_tokens": int,              # 20
}
```

## Exit Codes

The `@app.local_entrypoint()` exits with:
- `sys.exit(0)` if `result["ok"] is True`
- `sys.exit(1)` otherwise; error message printed to stderr

## Invariants

- If `ok=True`, then `completion_text` is a non-empty string.
- If `ok=False`, then `error` is a non-empty string describing the failure stage (e.g., `"server startup timeout"`, `"HTTP 500: ..."`, `"gRPC error: "`).
- `cold_start_s` is always populated (even on failure, up to the point of failure).
- `request_latency_s` is `0.0` if the request was never sent (failure before step 5).

## Cross-Script Comparison

For the SC-003 equivalence check (gRPC vs REST produce same output), both scripts MUST be run with identical parameters:
- `seed=42`
- `max_tokens=20`
- `model="/mnt/weights"` (same weight volume)
- Same prompt: `"What is 2 + 2?"` with system prompt `"You are a helpful assistant."`

The `completion_text` fields from both results MUST match (token-level equivalence).
