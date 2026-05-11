#!/usr/bin/env python3
"""M5 — cross-host gRPC bench server hosted on Modal (CPU-only).

Hosts the M4 ``MockEngine`` behind M3's production-shape servicers
(``M3CompletionsServicer`` / ``M3ChatServicer``) plus a tiny ``HealthServicer``
that the harness's RTT probe (``rtt_probe.measure_rtt``) drives. The gRPC
port is exposed via ``modal.forward(_GRPC_PORT, unencrypted=False)`` so
Modal terminates TLS at the tunnel edge (research.md R-1). Application-level
auth is enforced by a ``BearerTokenInterceptor`` registered on the server.

The harness drives this app via ``modal_endpoint.provide_endpoint`` (which
calls ``app.run.aio()`` and reads the tunnel URL + bearer token back from
a ``modal.Dict``). One Modal app instance hosts the entire M5 sweep — both
US1 channel cohorts and US2 schema-candidate cohorts use the same gRPC
endpoint.

The schema-candidate protos under
``proto/vllm_grpc/v1/m4-candidates/`` carry only message types (no service
definitions), so US2 measures candidate wire-byte costs by re-serializing
through the same production gRPC services — no additional servicer
registration is needed here.

The function blocks until the harness sets ``teardown=True`` on the shared
``modal.Dict``, then stops the gRPC server cleanly.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time

import modal

_APP_NAME = "vllm-grpc-bench-mock"
_GRPC_PORT = 50051
_DICT_NAME = "vllm-grpc-bench-mock-handshake"
_HANDSHAKE_TIMEOUT_S = 120.0
_TEARDOWN_POLL_S = 0.5
_FUNCTION_TIMEOUT_S = 60 * 60 * 12  # 12-hour cap (operator-overridable)

# Modal Image: CPU-only debian-slim + the harness packages.  No GPU, no vLLM
# install — the M5 server uses ``MockEngine`` (no model dependency).
_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "grpcio==1.80.0",
        "grpcio-tools",
        "numpy",
        "protobuf",
    )
    .add_local_dir("proto", "/build/proto", copy=True)
    .add_local_dir("packages/gen", "/build/packages/gen", copy=True)
    .add_local_dir("packages/frontend", "/build/packages/frontend", copy=True)
    .add_local_dir("tools/benchmark", "/build/tools/benchmark", copy=True)
    .run_commands(
        "pip install /build/packages/gen",
        "pip install /build/packages/frontend",
        "pip install /build/tools/benchmark",
    )
)

app = modal.App(_APP_NAME)


@app.function(image=_image, timeout=_FUNCTION_TIMEOUT_S)
async def serve_bench(token: str, region: str) -> dict[str, object]:
    """Serve the M5 mock-engine gRPC server until the harness signals teardown.

    Registers ``M3ChatServicer``, ``M3CompletionsServicer``, and a minimal
    ``HealthServicer`` (for the RTT probe) on a single gRPC port (50051),
    behind a ``BearerTokenInterceptor`` that gates every RPC on the
    ``authorization`` metadata header. Opens ``modal.forward(_GRPC_PORT,
    unencrypted=False)`` so Modal terminates TLS, then publishes the tunnel
    URL + token + region on the shared ``modal.Dict``.
    """
    from collections.abc import Awaitable, Callable
    from typing import Any

    import grpc
    from vllm_grpc.v1 import (
        chat_pb2_grpc,
        completions_pb2_grpc,
        health_pb2,
        health_pb2_grpc,
    )
    from vllm_grpc_bench.m3_sweep import M3ChatServicer, M3CompletionsServicer
    from vllm_grpc_bench.mock_engine import MockEngine, MockEngineConfig

    class _HealthServicer(health_pb2_grpc.HealthServicer):  # type: ignore[misc]
        async def Ping(  # noqa: N802
            self,
            request: health_pb2.HealthRequest,
            context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
        ) -> health_pb2.HealthResponse:
            return health_pb2.HealthResponse(message="ok")

    class _BearerTokenInterceptor(grpc.aio.ServerInterceptor):  # type: ignore[type-arg]
        """Reject every RPC whose ``authorization`` metadata header does not
        match the per-deploy bearer token. Unauthorized calls return
        ``UNAUTHENTICATED`` before the servicer touches the request so
        rejected traffic does not contaminate the timing window.
        """

        def __init__(self, expected: str) -> None:
            self._expected = f"Bearer {expected}"

        async def intercept_service(  # type: ignore[no-untyped-def]
            self,
            continuation,  # noqa: ANN001 — grpc.aio stubs don't expose the continuation type
            handler_call_details,  # noqa: ANN001 — grpc.aio.HandlerCallDetails
        ):
            md = dict(handler_call_details.invocation_metadata or ())
            if md.get("authorization", "") != self._expected:

                async def _unauth(request: Any, context: Any) -> Any:
                    await context.abort(grpc.StatusCode.UNAUTHENTICATED, "bearer token rejected")

                return grpc.unary_unary_rpc_method_handler(_unauth)
            return await continuation(handler_call_details)

    # MockEngine config: M3 defaults — hidden_size is set on the harness
    # side per cohort (the engine is created fresh for each cohort in
    # ``m4_sweep._measure_cell``; here we keep a single tunable engine for
    # cross-cohort reuse since cohort-specific channel/serialization is what
    # M5 measures, not engine internals).
    engine = MockEngine(
        MockEngineConfig(
            hidden_size=4096,
            seed=0,
            tokens_per_second=200.0,
            max_tokens_per_stream=2048,
            pace_tokens=False,
        )
    )

    server = grpc.aio.server(interceptors=[_BearerTokenInterceptor(token)])
    chat_pb2_grpc.add_ChatServiceServicer_to_server(M3ChatServicer(engine), server)
    completions_pb2_grpc.add_CompletionsServiceServicer_to_server(
        M3CompletionsServicer(engine), server
    )
    health_pb2_grpc.add_HealthServicer_to_server(_HealthServicer(), server)
    server.add_insecure_port(f"[::]:{_GRPC_PORT}")
    await server.start()

    d = modal.Dict.from_name(_DICT_NAME, create_if_missing=True)
    started = time.monotonic()
    try:
        with modal.forward(_GRPC_PORT, unencrypted=False) as tunnel:
            # tunnel.url for HTTPS-style endpoints; tunnel.tcp_socket for raw
            # TCP. With unencrypted=False, Modal returns a host:port the
            # client can pair with grpc.ssl_channel_credentials().
            try:
                endpoint = tunnel.url
            except AttributeError:
                host, port = tunnel.tcp_socket
                endpoint = f"{host}:{port}"
            d.put("endpoint", endpoint)
            d.put("token", token)
            d.put("region", region)
            d.put("ready", True)
            # Block until the harness signals teardown.
            while not d.get("teardown", default=False):
                if time.monotonic() - started > _FUNCTION_TIMEOUT_S - 30:
                    # Self-exit before Modal's hard cap to allow clean teardown.
                    break
                await asyncio.sleep(_TEARDOWN_POLL_S)
    finally:
        await server.stop(grace=5.0)
        # Best-effort cleanup so stale handshake state doesn't poison a future run.
        for key in ("endpoint", "token", "region", "ready", "teardown"):
            with contextlib.suppress(Exception):
                d.pop(key, None)

    return {"ok": True, "wallclock_s": time.monotonic() - started}


@app.local_entrypoint()
def main(token: str = "", region: str = "us-east-1") -> None:
    """Operator-facing entry point — useful for sanity-checking the deploy
    outside the harness. The harness imports ``app`` + ``serve_bench``
    directly and drives them via ``app.run.aio()``.
    """
    if not token:
        print(
            "ERROR: pass --token=<bearer-token> (see specs/017-.../quickstart.md)", file=sys.stderr
        )
        sys.exit(2)
    print(f"[INFO] deploying {_APP_NAME!r} to region={region!r} …")
    serve_bench.remote(token=token, region=region)
