# Contract: M5 Modal App (`scripts/python/modal_bench_grpc_server.py`)

This contract defines the Modal app the M5 harness deploys to host the cross-host gRPC server. The app's job is to run M4's `MockEngine` + M3's `M3CompletionsServicer` / `M3ChatServicer` inside a Modal container, expose the gRPC port via `modal.forward()` with Modal-terminated TLS, register an application-level bearer-token interceptor on the servicers, and publish the tunnel URL + bearer token via `modal.Dict` so the harness can pick them up.

## App name and lifecycle

- **App name**: `vllm-grpc-bench-mock` (per research.md OP-1).
- **Lifecycle**: app-runtime — deployed by the harness via `app.run()` async context manager (research.md R-2), torn down on `app.run()` exit. No persistent state survives a successful run.
- **Concurrency**: one container; `max_inputs=1` and `keep_warm=0` so cold-start cost is paid once per deploy (research.md R-5 handles cold-start via the harness's warm-up cohort).
- **Visibility**: app NOT registered as a deployed app (no `modal deploy`); it lives only during the `app.run()` context.

## Container image

```python
modal.Image.debian_slim(python_version="3.12").pip_install(
    "grpcio==1.80.0",
    "grpcio-tools",      # for protobuf descriptor loading
    "numpy",             # for mock embedding tensors
    "protobuf",
).add_local_python_source("vllm_grpc_frontend", "vllm_grpc_gen", "vllm_grpc_bench")
```

The image is CPU-only (per Clarifications Q2 — no `gpu=...` argument to `@app.function`). The local sources picked up are:
- `vllm_grpc_frontend` — provides `M3CompletionsServicer` and `M3ChatServicer` (M3's production servicer classes).
- `vllm_grpc_gen` — provides the proto-derived stubs.
- `vllm_grpc_bench` — provides `MockEngine` (M4's mock).

Schema-candidate stubs from `proto/vllm_grpc/v1/m4-candidates/` are picked up via `vllm_grpc_gen` since `make proto` registers them under the same package layout.

## Function signature

```python
import modal
import secrets
import asyncio
from typing import Any

_APP_NAME = "vllm-grpc-bench-mock"
_GRPC_PORT = 50051
_DICT_NAME = "vllm-grpc-bench-mock-handshake"
_HANDSHAKE_TIMEOUT_S = 120.0

app = modal.App(_APP_NAME)


@app.function(image=_image, timeout=60 * 60 * 12)  # 12-hour container timeout
async def serve_bench(token: str, region: str) -> None:
    """Serve the M5 mock-engine gRPC server until the harness signals teardown.

    Registers BOTH the M3 production-shape servicers (for US1 channel-sweep
    cohorts) AND the three M4 candidate-shape servicers (for US2 schema-
    candidate cohorts) on a single gRPC port. Candidate proto services
    live in a distinct proto namespace (`vllm_grpc/v1/m4_candidates/`)
    and have non-colliding service names, so simultaneous registration
    is conflict-free and avoids a Modal redeploy between US1 and US2.
    """
    engine = MockEngine(...)
    server = grpc.aio.server(interceptors=[BearerTokenInterceptor(token)])

    # ── M3 production-shape servicers (US1 channel-sweep cohorts) ──────────────
    from vllm_grpc_frontend.servicers import M3CompletionsServicer, M3ChatServicer
    chat_pb2_grpc.add_M3ChatServicer_to_server(M3ChatServicer(engine), server)
    completions_pb2_grpc.add_M3CompletionsServicer_to_server(
        M3CompletionsServicer(engine), server
    )

    # ── M4 candidate-shape servicers (US2 schema-candidate cohorts) ────────────
    from vllm_grpc_bench.candidate_servicers import (
        PackedTokenIdsServicer,
        OneofFlattenedInputServicer,
        ChunkGranularityServicer,
    )
    packed_token_ids_pb2_grpc.add_PackedTokenIdsServicer_to_server(
        PackedTokenIdsServicer(engine), server
    )
    oneof_flattened_input_pb2_grpc.add_OneofFlattenedInputServicer_to_server(
        OneofFlattenedInputServicer(engine), server
    )
    chunk_granularity_pb2_grpc.add_ChunkGranularityServicer_to_server(
        ChunkGranularityServicer(engine), server
    )

    server.add_insecure_port(f"[::]:{_GRPC_PORT}")  # Modal's tunnel will TLS-terminate.
    await server.start()

    # ── Open Modal TLS-terminated tunnel and publish the address ──────────────
    async with modal.forward.aio(_GRPC_PORT, unencrypted=False) as tunnel:
        d = modal.Dict.from_name(_DICT_NAME, create_if_missing=True)
        await d.put.aio("endpoint", tunnel.url)              # e.g., "tcp://r3.modal.host:54321"
        await d.put.aio("token", token)
        await d.put.aio("region", region)
        await d.put.aio("ready", True)

        # Block until harness signals teardown.
        while not await d.get.aio("teardown", default=False):
            await asyncio.sleep(0.5)

    await server.stop(grace=5.0)
```

The function takes the `token` and `region` as arguments so the harness controls both; the function does not generate them. Region is informational (Modal apps can be region-affined at app-config time; the function records it in the handshake dict). The harness selects which service to call per cohort via standard gRPC client routing — no separate channel, no separate endpoint, no second Modal deploy.

## Servicers registered

All servicers live on a single Modal-tunneled gRPC port (50051). The production-shape services and the M4 candidate-shape services have distinct fully-qualified service names (different proto packages), so simultaneous registration is conflict-free.

| Servicer | Source proto | Used by |
|----------|--------------|---------|
| `M3CompletionsServicer` | `proto/vllm_grpc/v1/completions.proto` | US1 channel-sweep cohorts (embed path) |
| `M3ChatServicer` | `proto/vllm_grpc/v1/chat.proto` | US1 channel-sweep cohorts (chat_stream path) |
| `PackedTokenIdsServicer` | `proto/vllm_grpc/v1/m4-candidates/packed_token_ids.proto` | US2 schema candidate (a) |
| `OneofFlattenedInputServicer` | `proto/vllm_grpc/v1/m4-candidates/oneof_flattened_input.proto` | US2 schema candidate (b) |
| `ChunkGranularityServicer` | `proto/vllm_grpc/v1/m4-candidates/chunk_granularity.proto` | US2 schema candidate (c) |

## Bearer-token interceptor

```python
class BearerTokenInterceptor(grpc.aio.ServerInterceptor):
    """Application-level bearer-token validation on every RPC.

    Rejects any RPC whose `authorization` metadata header does not match the
    per-deploy bearer token. Rejected calls return UNAUTHENTICATED before the
    servicer touches the request, so unauthorized traffic does not contaminate
    the timing window.
    """
    def __init__(self, expected_token: str) -> None:
        self._expected = expected_token

    async def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], Awaitable[grpc.aio.RpcMethodHandler]],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.aio.RpcMethodHandler:
        metadata = dict(handler_call_details.invocation_metadata or ())
        auth = metadata.get("authorization", "")
        if auth != f"Bearer {self._expected}":
            return _unauthenticated_handler()
        return await continuation(handler_call_details)
```

Bearer-token rejection during the sweep is treated as a hard error by the harness (per research.md OP-3 — the harness exits with code 7). The Modal-side server itself does not exit on rejection; it just refuses the call.

## modal.Dict handshake protocol

| Key | Type | Written by | Read by | Purpose |
|------|------|------------|---------|---------|
| `endpoint` | string | server | harness | Tunnel URL (e.g., `tcp://r3.modal.host:54321`). Format: `tcp://<host>:<port>` or `grpcs://<host>:<port>` depending on Modal version. |
| `token` | string | server | harness | Bearer token (echo of harness-supplied value; harness verifies match). |
| `region` | string | server | harness | Selected Modal region. |
| `ready` | bool | server | harness | Set to `true` after tunnel is open and dict keys are published. |
| `teardown` | bool | harness | server | Set to `true` when harness wants the server to exit cleanly. |

The harness polls `ready == true` (with timeout `_HANDSHAKE_TIMEOUT_S = 120s`); if not ready within that window, the harness exits with code 3 (handshake failed) and tears down via `app.run()` context exit.

## Harness-side handshake (`modal_endpoint.provide_endpoint`)

```python
@asynccontextmanager
async def provide_endpoint(
    engine: MockEngine,
    channel_config: ChannelConfig,
    *,
    region: str = "us-east-1",
    token_env: str = "MODAL_BENCH_TOKEN",
) -> AsyncIterator[EndpointTuple]:
    """Deploy the Modal bench app, capture endpoint + token, yield EndpointTuple.

    The `engine` and `channel_config` arguments are accepted for EndpointProvider
    Protocol parity with `serve_in_process_adapter`; the cross-host server is
    configured server-side via its own MockEngineConfig (driven from the channel
    sweep's per-cell config metadata).
    """
    token = os.environ[token_env]
    async with app.run.aio():
        # Kick off the serve_bench function in the background.
        serve_call = serve_bench.spawn.aio(token=token, region=region)

        # Wait for handshake.
        d = modal.Dict.from_name(_DICT_NAME, create_if_missing=True)
        endpoint, region_actual = await _wait_for_handshake(d, _HANDSHAKE_TIMEOUT_S)

        try:
            yield (endpoint, grpc.ssl_channel_credentials(), (("authorization", f"Bearer {token}"),))
        finally:
            # Signal teardown via dict; serve_bench will exit cleanly.
            await d.put.aio("teardown", True)
            await serve_call            # wait for serve_bench to return
```

## What the contract guarantees

1. **TLS is terminated at Modal's tunnel edge.** The gRPC client connects via `grpc.aio.secure_channel(...)` with `grpc.ssl_channel_credentials()`. TLS overhead is uniform across every RPC in the sweep and does not vary with any of the four channel axes.
2. **Bearer-token auth is enforced server-side.** Unauthorized RPCs return `UNAUTHENTICATED` before reaching the servicer. The harness attaches the token via call metadata on every RPC.
3. **CPU-only instance.** No GPU. Container scheduling jitter is bounded by Modal CPU instance characteristics (typically tighter than A10G GPU instances under the project's existing M1 provisioning).
4. **No persistent state.** The Modal app is `app.run()`-scoped; teardown is automatic on context exit. The `modal.Dict` named `vllm-grpc-bench-mock-handshake` is cleared by the harness on entry to avoid stale handshake state from a previous failed run.
5. **No data path through Modal's API plane.** Once the tunnel is open, gRPC RPCs flow directly client → Modal tunnel edge → container, not through Modal's control API. Rate-limit risk from Modal's API plane is therefore confined to the deploy/teardown handshake (a handful of API calls per run), not the per-RPC sweep traffic.

## What the contract does NOT guarantee

- **Region-pinning honored exactly.** Modal may schedule containers in a nearby zone within the requested region; the harness records the actual region returned by Modal in the JSON's `m5_modal_region`, which may differ from the harness's requested region.
- **Tunnel format stable across Modal versions.** The harness handles both `tcp://` and `grpcs://` tunnel URLs by stripping the scheme and using the resulting `host:port` for `grpc.aio.secure_channel`.
- **Modal-side container resource bounds.** CPU and memory bounds are Modal-default for the CPU-only instance class; the harness does not request specific bounds. The `server_bound` classifier (research.md R-4) catches the case where resource limits make the container the bottleneck.
