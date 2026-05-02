# Research: Phase 3.2 — Local Proxy → Modal gRPC Tunnel

**Branch**: `006-modal-grpc-tunnel` | **Date**: 2026-05-02

---

## R-001: modal.forward() Compatibility with gRPC / HTTP/2

**Decision**: Use `modal.forward(port, unencrypted=True)` to expose the gRPC frontend port as an external TCP address. This is expected to pass gRPC/HTTP/2 frames correctly and must be confirmed empirically on first run.

**Rationale**: `modal.forward(port, unencrypted=True)` creates a raw TCP tunnel — it does not inspect or transform the bytes that traverse it. gRPC uses HTTP/2 framing; HTTP/2 PING frames used for keep-alive are raw TCP bytes and should pass through a raw TCP tunnel unchanged. The `unencrypted=True` flag explicitly suppresses Modal's TLS wrapper, which is required because the proxy's gRPC client uses `grpc.aio.insecure_channel()`.

**Function shape constraint**: Phase 3.1 research (R-001) flagged the generator-yield-inside-forward pattern as potentially unreliable — a generator that `yield`s may suspend its frame, and it was unclear whether Modal would keep the `modal.forward()` context manager open during suspension. Phase 3.2 avoids this by using a **blocking (non-generator) function**: the function opens `modal.forward()`, publishes the address, then sleeps in a polling loop until a stop signal or timeout. The context manager's `__exit__` is not called until the function returns, so the tunnel stays open for the entire sleep duration.

**Known risk — idle TCP timeout**: Modal may impose an idle TCP timeout on unencrypted tunnels. If the gRPC channel sits idle between requests, the tunnel could drop. gRPC's client-side keepalive counters this, but the default keepalive interval (2 hours for gRPC-core) may exceed Modal's timeout. **If the tunnel drops mid-session, the mitigation is to set `GRPC_ARG_KEEPALIVE_TIME_MS` and `GRPC_ARG_KEEPALIVE_TIMEOUT_MS` on the proxy's channel options** — this is a proxy-side configuration and requires no code changes to the frontend. This is documented as a follow-on step if idle timeout is observed.

**Alternatives considered**:
- Generator+yield pattern — rejected (R-001 uncertainty, Phase 3.1 precedent)
- `modal.web_endpoint()` — HTTP-only, does not support raw gRPC over HTTP/2
- TLS tunnel (`unencrypted=False`) — would require `grpc.aio.secure_channel()` in the proxy, which is a proxy code change; rejected per FR-003
- External tunnel service (ngrok) — adds a dependency outside Modal; rejected for simplicity

---

## R-002: modal.Dict for Cross-Process State Communication

**Decision**: Use `modal.Dict.from_name("vllm-grpc-serve", create_if_missing=True)` to pass the tunnel address and teardown signal between the Modal container function and the local entrypoint.

**Rationale**: `modal.Dict` is a persistent key-value store accessible from both inside Modal containers and from local Python processes (via the Modal SDK). It is the canonical mechanism for sharing state between a spawned function and its orchestrator. The local entrypoint writes nothing — it only reads — while the serve function writes the tunnel address once on startup and checks the stop signal on a 5-second polling loop.

**Schema**:
- `"frontend_addr"` (str): The tunnel address as `"<host>:<port>"`. Written by the serve function after the gRPC server is healthy and the tunnel is open. Read by the local entrypoint to print `FRONTEND_ADDR`.
- `"cold_start_s"` (float): Elapsed seconds from function start to gRPC server healthy. Informational.
- `"stop_signal"` (bool): Set to `True` by the local entrypoint on Ctrl+C. Checked by the serve function to trigger graceful shutdown.

**`mypy --strict` note**: `modal.Dict`'s `__getitem__`, `__setitem__`, and `__delitem__` are dynamically typed. Accesses will require `# type: ignore[assignment]` or similar annotations. These are documented in the implementation and explicitly justified.

**Alternatives considered**:
- `modal.Queue` — suitable for stream-style data, but `Dict` is simpler for a single shared-state value
- Environment variables — cannot be set after the function starts
- Printing to stdout and parsing in the local entrypoint — fragile; stdout buffering and container log streaming add latency

---

## R-003: Long-Lived Function Lifecycle with spawn()

**Decision**: Use `serve_frontend.spawn()` from the local entrypoint to start the serve function as a background task. The local entrypoint then polls `modal.Dict` for the tunnel address, prints it, and blocks waiting for Ctrl+C.

**Rationale**: `function.remote()` blocks the local entrypoint until the function returns. Since the serve function must stay alive for the duration of developer testing (potentially 10–30 minutes), `remote()` would leave the terminal blocked with no address output until the function exits — unusable. `function.spawn()` returns a `modal.FunctionCall` handle immediately, allowing the local entrypoint to poll for the address and print it while the container is still starting.

**Teardown**: When the developer presses Ctrl+C, the local entrypoint catches `KeyboardInterrupt`, sets `stop_signal=True` in `modal.Dict`, and exits. The serve function checks this flag in its polling loop, exits the `with modal.forward()` block, kills the frontend subprocess, clears the Dict entries, and returns. The container is reclaimed by Modal at that point.

**Runaway cost guard**: If the local entrypoint exits abnormally (terminal closed, crash), the spawned function will continue running until its `timeout=3600` (1 hour) is reached. This is documented in the ADR. A future improvement could add a heartbeat mechanism, but for Phase 3.2 the fixed timeout is sufficient.

**Function timeout budget**: The function uses `timeout=3600`. Cold start is ~130 s; subtract 60 s safety buffer → the sleep loop runs for at most 3410 s (~56 min). This is more than enough for a single-request smoke test.

**Alternatives considered**:
- `modal serve` mode — keeps the app alive and re-invokes functions on demand; suitable for persistent services, but adds complexity and isn't compatible with the one-shot `modal run` invocation pattern used by all other scripts in this project
- Generator function yielding the address — rejected (R-001 generator concern)
- `modal.Cls` with lifecycle hooks — more complex than needed for a one-shot serve script
