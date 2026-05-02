# Contract: TunnelState (modal.Dict schema)

**Feature**: Phase 3.2 — Local Proxy → Modal gRPC Tunnel
**Dict name**: `"vllm-grpc-serve"`
**Created by**: `modal.Dict.from_name("vllm-grpc-serve", create_if_missing=True)`

---

## Keys

### `"frontend_addr"`

| Property | Value |
|---|---|
| Type | `str` |
| Format | `"<host>:<port>"` (e.g., `"tcp.modal.run:12345"`) |
| Written by | `serve_frontend()` inside the Modal container |
| Written when | Immediately after `modal.forward()` opens and the tunnel is ready |
| Read by | Local `main()` entrypoint |
| Invariant | Always a valid value for `grpc.aio.insecure_channel()` and the `FRONTEND_ADDR` env var |
| Absent when | Before the tunnel opens (function still starting), or after clean shutdown |

### `"cold_start_s"`

| Property | Value |
|---|---|
| Type | `float` |
| Format | Seconds as a Python float (e.g., `130.2`) |
| Written by | `serve_frontend()` inside the Modal container |
| Written when | Same write as `frontend_addr` (atomic from the serve function's perspective) |
| Read by | Local `main()` entrypoint (informational; printed to stdout) |
| Invariant | ≥ 0; represents elapsed time from container function entry to gRPC server healthy |

### `"stop_signal"`

| Property | Value |
|---|---|
| Type | `bool` |
| Value | Always `True` when present |
| Written by | Local `main()` entrypoint on `KeyboardInterrupt` |
| Written when | Ctrl+C received in the terminal running `make modal-serve-frontend` |
| Read by | `serve_frontend()` polling loop inside the container |
| Effect | Causes the serve function to exit its blocking loop, close the tunnel, and return |
| Absent when | Normal operation (not in teardown) |

---

## Lifecycle

1. **Before spawn**: Local entrypoint deletes all three keys (handles stale state from previous run)
2. **After `modal.forward()` opens**: Serve function writes `frontend_addr` and `cold_start_s` atomically (two writes, but local entrypoint only acts on `frontend_addr`)
3. **On stop**: Local entrypoint writes `stop_signal=True`; serve function deletes all three keys before returning
4. **On abnormal exit** (container crash, timeout): Keys may persist until the next run cleans them up

---

## Error Handling

- If `frontend_addr` does not appear within 600 s of `spawn()`, the local entrypoint exits with code 1 and prints a timeout error
- Stale `frontend_addr` from a previous crashed run is cleared by the local entrypoint at startup
