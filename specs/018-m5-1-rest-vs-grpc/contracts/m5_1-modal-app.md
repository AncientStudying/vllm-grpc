# Contract: M5.1 Modal app (`modal_bench_rest_grpc_server.py`)

The dual-protocol cross-host gRPC + REST server M5.1 deploys to Modal. Parallel to M5's `modal_bench_grpc_server.py`; reuses the CPU-only image and `BearerTokenInterceptor`, adds the FastAPI shim under the same `modal.App`.

## App name

`vllm-grpc-bench-rest-grpc-mock`

Single Modal app, deployed once per harness run, torn down on harness exit.

## Image

```text
modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_pyproject("/repo/pyproject.toml")  # workspace deps
    .pip_install(
        # additive Modal-image deps for the REST side; both already
        # present in packages/proxy/'s deps so no new workspace edits:
        "fastapi",
        "uvicorn[standard]",
    )
    .copy_local_dir("/repo")
```

Workspace packages install with `--no-deps` (matches M5's documented constraint — workspace siblings don't resolve under plain pip inside Modal image builds).

## Container processes

A single Modal function entry point starts both servers concurrently on the same asyncio loop:

```python
async def _serve():
    engine = MockEngine(...)   # singleton, shared by both protocols

    # gRPC server (port 50051, plain-TCP per Modal ALPN constraint)
    grpc_server = grpc.aio.server(interceptors=[BearerTokenInterceptor(...)])
    add_M3CompletionsServicer_to_server(M3CompletionsServicer(engine), grpc_server)
    add_M3ChatServicer_to_server(M3ChatServicer(engine), grpc_server)
    add_HealthServicer_to_server(HealthServicer(), grpc_server)
    grpc_server.add_insecure_port("[::]:50051")
    await grpc_server.start()

    # REST shim (port 8000, uvicorn workers=1, Modal-managed TLS)
    app = build_rest_shim(engine)   # FastAPI app with /v1/chat/completions, /v1/embeddings, /healthz
    rest_server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8000, workers=1, log_level="warning"))
    rest_task = asyncio.create_task(rest_server.serve())

    await asyncio.gather(grpc_server.wait_for_termination(), rest_task)
```

Both servers share the same `MockEngine` instance (research.md R-1, R-8). Uvicorn is pinned to a single worker so the singleton invariant holds.

## Exposed tunnel ports

Two `modal.forward()` calls inside the function:

```python
with modal.forward(8000) as rest_tunnel, modal.forward(50051, unencrypted=True) as grpc_tunnel:
    # rest_tunnel.url   → "https://<random>.modal.host"
    # grpc_tunnel.url   → "tcp://<random>.modal.host:50051"
    # Write both to modal.Dict so the harness can read them.
    endpoint_dict["rest"] = rest_tunnel.url
    endpoint_dict["grpc"] = f"tcp+plaintext://{grpc_tunnel.host}:{grpc_tunnel.port}"
    endpoint_dict["ready"] = True
    await _serve()
```

REST uses Modal's HTTPS-terminated edge (default). gRPC uses plain-TCP per M5's documented ALPN-incompatibility finding for Modal's HTTPS edge.

## Authentication

- **gRPC**: server registers `BearerTokenInterceptor` (reused from M5's implementation) at server-construction time. The interceptor reads `authorization: Bearer <token>` from incoming RPC metadata and rejects with `UNAUTHENTICATED` on mismatch.
- **REST**: FastAPI middleware short-circuits any request without a valid `Authorization: Bearer <token>` header to HTTP 401. The middleware runs **before** the request body is parsed (fail-fast per research.md R-8). `/healthz` is excluded from the auth middleware so the RTT probe doesn't pay bearer-validation cost.

The expected token is read from the `MODAL_BENCH_TOKEN` Modal Secret at container startup. The harness writes the same token value to both protocols at boot time; the harness's REST cohort runner attaches it as `Authorization: Bearer <token>` and the gRPC cohort runner attaches it as call metadata.

## Env vars / secrets

Required at deploy time:
- `MODAL_BENCH_TOKEN` (Modal Secret): the bearer token for both protocols' auth.

Optional:
- `M5_1_LOG_LEVEL` (default: `WARNING`): uvicorn + grpc server log verbosity.
- `M5_1_MAX_TOKENS_PER_REQUEST` (default: `1024`): cap on chat completion token count, defense-in-depth against runaway prompts. MockEngine has no real cap so this is a shim-side guard.

## Handshake with harness

The harness's `modal_endpoint.provide_endpoint(variant="rest_grpc")` performs the following:

1. Calls `app.run.aio()` to deploy the Modal app.
2. Polls `endpoint_dict["ready"]` until true (timeout 60s; exit code 3 on miss).
3. Reads `endpoint_dict["grpc"]` and `endpoint_dict["rest"]` URLs.
4. Yields both URLs + the bearer token to the M5.1 sweep orchestrator.
5. On context exit, calls `app.stop.aio()` to tear down. Modal's container is reclaimed within ~5s of return.

Reuses M5's `modal.Dict` pattern; only the dict key set is expanded (M5 wrote `grpc` only; M5.1 writes `grpc` + `rest`). Backward compatibility: an M5 consumer reading the same dict ignores the `rest` key.

## Failure modes

| Failure | Symptom | Recovery |
|---------|---------|----------|
| Modal token missing at container startup | container exits before tunnels open | exit code 4 in harness |
| FastAPI shim port collision with gRPC | one server fails to bind | container exits; exit code 3 in harness |
| Modal HTTPS edge ALPN regression (gRPC over TLS) | grpc handshake fails with "missing ALPN" | already handled by plain-TCP forward; would only re-emerge if M5.1 ever re-enabled `unencrypted=False` for gRPC (forbidden by spec assumptions) |
| Bearer-token mismatch (harness token != container token) | every cohort 401/UNAUTHENTICATED | harness emits a clear error on first cohort; exit code 4 |
| MockEngine async deadlock under concurrent REST + gRPC load | both servers stall | uvicorn `workers=1` + grpc.aio single-server pattern verified by M5; if seen, indicates a MockEngine regression — not an M5.1 concern |

## Local smoke test (Modal-secrets-gated)

`tests/integration/test_m5_1_modal_smoke.py` exercises the full deploy → both-probes → one tiny REST cohort + one tiny gRPC cohort → teardown loop, default-skipped when `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` are absent. Run wall-clock: ~90s. Verifies:
- Both tunnel URLs are emitted by `provide_endpoint`.
- A bearer-authenticated REST `/healthz` returns 200.
- A bearer-authenticated gRPC `Health.Ping` returns OK.
- A 10-sample REST chat_stream cohort emits 10 TTFT values and 10 shim-overhead values.
- A 10-sample gRPC chat_stream cohort emits 10 TTFT values.
- `app.stop.aio()` completes within 10s.
- `modal app list` does not show the app handle afterward.
