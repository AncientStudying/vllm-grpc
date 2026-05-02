# Data Model: Phase 3.2 — Local Proxy → Modal gRPC Tunnel

**Branch**: `006-modal-grpc-tunnel` | **Date**: 2026-05-02

---

## Entities

### ServeResult

Returned by `serve_frontend()` when the function exits (after stop signal or timeout).

| Field | Type | Description |
|---|---|---|
| `ok` | bool | True if the function started, tunneled, and shut down cleanly |
| `cold_start_s` | float | Seconds from function start to gRPC server healthy |
| `error` | str \| None | Error message if `ok` is False; None otherwise |

### TunnelState

Key-value pairs stored in `modal.Dict` during the serve lifecycle. See `contracts/tunnel-state.md` for the full schema.

| Key | Type | Written by | Read by | Lifecycle |
|---|---|---|---|---|
| `"frontend_addr"` | str | serve function (container) | local entrypoint | Created when tunnel opens; deleted on clean shutdown |
| `"cold_start_s"` | float | serve function (container) | local entrypoint (informational) | Created when tunnel opens; deleted on clean shutdown |
| `"stop_signal"` | bool | local entrypoint (on Ctrl+C) | serve function (polling loop) | Created on teardown trigger; deleted on clean shutdown |

---

## State Transitions

### Serve Function (container-side)

```
INIT
  │  Start gRPC frontend subprocess
  ▼
STARTING
  │  Poll Health.Ping every 5 s, up to 600 s
  ├─ timeout ──► EXIT(ok=False, error="gRPC server did not become healthy within 600s")
  ▼
HEALTHY
  │  cold_start_s recorded
  │  Open modal.forward(50051, unencrypted=True)
  │  Write frontend_addr + cold_start_s to modal.Dict
  ▼
SERVING
  │  Sleep loop, check stop_signal every 5 s
  │  Check remaining time budget every 5 s
  ├─ stop_signal=True ──► STOPPING
  ├─ time budget exhausted ──► STOPPING
  ▼
STOPPING
  │  Exit modal.forward() context (tunnel closes)
  │  Kill frontend subprocess
  │  Delete dict keys
  ▼
EXIT(ok=True)
```

### Local Entrypoint (developer machine)

```
START
  │  Clear stale dict entries
  │  spawn serve_frontend()
  ▼
WAITING_FOR_ADDR
  │  Poll modal.Dict["frontend_addr"] every 2 s, up to 600 s
  ├─ timeout ──► EXIT(1)
  ▼
READY
  │  Print cold_start_s
  │  Print "export FRONTEND_ADDR=<addr>"
  │  Print instructions
  ▼
BLOCKING (waiting for Ctrl+C)
  │  KeyboardInterrupt
  ▼
TEARDOWN
  │  Set modal.Dict["stop_signal"] = True
  │  Print teardown message
  ▼
EXIT(0)
```

---

## Notes

- `frontend_addr` uses the format `"<host>:<port>"` — this is a valid value for `FRONTEND_ADDR` / `grpc.aio.insecure_channel()` without further transformation.
- `cold_start_s` is the time from container function start (not local invocation start) to gRPC server healthy. It excludes local entrypoint startup time and Modal provisioning time.
- There is no persistent storage of `ServeResult` — it is returned by the Modal function but not committed to disk. Timing is printed to stdout by the local entrypoint.
