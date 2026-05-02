# Contract: ServeResult (serve_frontend return value)

**Feature**: Phase 3.2 — Local Proxy → Modal gRPC Tunnel
**Returned by**: `serve_frontend()` when the container function exits

---

## Schema

```python
class ServeResult(TypedDict):
    ok: bool
    cold_start_s: float
    error: str | None
```

| Field | Type | Description |
|---|---|---|
| `ok` | `bool` | `True` if function completed cleanly (stop signal or natural timeout). `False` if gRPC server failed to start. |
| `cold_start_s` | `float` | Seconds from function entry to gRPC server healthy. 0.0 if server never became healthy. |
| `error` | `str \| None` | Error description if `ok=False`; `None` otherwise. |

---

## Examples

**Successful run (stop signal received)**:
```json
{"ok": true, "cold_start_s": 130.2, "error": null}
```

**Failed startup (gRPC server timeout)**:
```json
{"ok": false, "cold_start_s": 600.0, "error": "gRPC server did not become healthy within 600s"}
```

---

## Notes

- The local `main()` entrypoint does not wait for `ServeResult` — it uses `spawn()` and communicates via `modal.Dict`. `ServeResult` is available via the `FunctionCall` handle if needed for debugging, but is not used in the normal workflow.
- `cold_start_s` in `ServeResult` is the same value written to `modal.Dict["cold_start_s"]`.
