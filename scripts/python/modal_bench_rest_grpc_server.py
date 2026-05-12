#!/usr/bin/env python3
"""M5.1 — dual-protocol cross-host gRPC + REST bench server on Modal (CPU-only).

Hosts the M4 ``MockEngine`` behind both:

* M3 production-shape gRPC servicers (``M3CompletionsServicer`` /
  ``M3ChatServicer`` + ``HealthServicer``) on port 50051 (plain-TCP tunnel
  per M5's ALPN-incompatibility finding for Modal's HTTPS edge).
* A FastAPI REST shim (built by ``vllm_grpc_bench.rest_shim.build_rest_shim``)
  on port 8000 (Modal-managed HTTPS edge) exposing OpenAI-compatible
  endpoints per
  ``specs/018-m5-1-rest-vs-grpc/contracts/m5_1-rest-shim-endpoints.md``.

Both servers share a single in-container ``MockEngine`` instance so the
engine variable is held constant across protocols. Bearer-token auth on
both sides reads the same ``MODAL_BENCH_TOKEN`` value.

The function blocks until the harness sets ``teardown=True`` on the shared
``modal.Dict``, then stops both servers cleanly.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from typing import Any

import modal

_APP_NAME = "vllm-grpc-bench-rest-grpc-mock"
_GRPC_PORT = 50051
_REST_PORT = 8000
_DICT_NAME = "vllm-grpc-bench-rest-grpc-mock-handshake"
_TEARDOWN_POLL_S = 0.5
_FUNCTION_TIMEOUT_S = 60 * 60 * 12

# Modal Image: CPU-only debian-slim + harness packages + FastAPI/uvicorn.
_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "grpcio==1.80.0",
        "grpcio-tools",
        "numpy",
        "protobuf",
        "fastapi",
        "uvicorn[standard]",
    )
    .add_local_dir("proto", "/build/proto", copy=True)
    .add_local_dir("packages/gen", "/build/packages/gen", copy=True)
    .add_local_dir("tools/benchmark", "/build/tools/benchmark", copy=True)
    .run_commands(
        "pip install --no-deps /build/packages/gen",
        "pip install --no-deps /build/tools/benchmark",
    )
)

app = modal.App(_APP_NAME)


@app.function(image=_image, timeout=_FUNCTION_TIMEOUT_S)
async def serve_bench(token: str, region: str) -> dict[str, object]:
    """Serve the M5.1 dual-protocol bench app until the harness signals teardown."""
    import grpc
    from vllm_grpc.v1 import (
        chat_pb2_grpc,
        completions_pb2_grpc,
        health_pb2,
        health_pb2_grpc,
    )
    from vllm_grpc_bench.m3_sweep import M3ChatServicer, M3CompletionsServicer
    from vllm_grpc_bench.mock_engine import MockEngine, MockEngineConfig
    from vllm_grpc_bench.rest_shim import build_rest_shim

    class _HealthServicer(health_pb2_grpc.HealthServicer):  # type: ignore[misc]
        async def Ping(  # noqa: N802
            self,
            request: health_pb2.HealthRequest,
            context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
        ) -> health_pb2.HealthResponse:
            return health_pb2.HealthResponse(message="ok")

    class _BearerTokenInterceptor(grpc.aio.ServerInterceptor):  # type: ignore[type-arg]
        def __init__(self, expected: str) -> None:
            self._expected = f"Bearer {expected}"

        async def intercept_service(  # type: ignore[no-untyped-def]
            self,
            continuation,
            handler_call_details,  # noqa: ANN001
        ):
            md = dict(handler_call_details.invocation_metadata or ())
            if md.get("authorization", "") != self._expected:

                async def _unauth(request: Any, context: Any) -> Any:
                    await context.abort(grpc.StatusCode.UNAUTHENTICATED, "bearer token rejected")

                return grpc.unary_unary_rpc_method_handler(_unauth)
            return await continuation(handler_call_details)

    engine = MockEngine(
        MockEngineConfig(
            hidden_size=4096,
            seed=0,
            tokens_per_second=200.0,
            max_tokens_per_stream=2048,
            pace_tokens=False,
        )
    )

    grpc_server = grpc.aio.server(interceptors=[_BearerTokenInterceptor(token)])
    chat_pb2_grpc.add_ChatServiceServicer_to_server(M3ChatServicer(engine), grpc_server)
    completions_pb2_grpc.add_CompletionsServiceServicer_to_server(
        M3CompletionsServicer(engine), grpc_server
    )
    health_pb2_grpc.add_HealthServicer_to_server(_HealthServicer(), grpc_server)
    grpc_server.add_insecure_port(f"[::]:{_GRPC_PORT}")
    await grpc_server.start()

    import uvicorn

    shim = build_rest_shim(engine, expected_token=token)
    uv_config = uvicorn.Config(
        shim,
        host="0.0.0.0",
        port=_REST_PORT,
        workers=1,
        log_level="warning",
        loop="asyncio",
    )
    rest_server = uvicorn.Server(uv_config)
    rest_task = asyncio.create_task(rest_server.serve())

    d = modal.Dict.from_name(_DICT_NAME, create_if_missing=True)
    started = time.monotonic()
    try:
        # Both protocols use plain-TCP modal.forward to eliminate the
        # routing asymmetry that arises if REST goes through Modal's HTTPS
        # edge (TLS-terminated, anycast-routed near client) while gRPC
        # goes direct via plain TCP. The smoke run measured a ~2× RTT gap
        # (REST ~185 ms, gRPC ~360 ms) on identical hardware in the same
        # region — that's tunnel-routing asymmetry, not protocol cost.
        # Forcing REST through plain-TCP too holds the network path
        # constant so the per-cell verdict reflects protocol cost alone.
        # This voids the spec's "Modal-managed TLS for REST" assumption
        # (FR-019) — intentional per Constitution V; documented in the
        # methodology section of the M5.1 report.
        async with modal.forward.aio(_GRPC_PORT, unencrypted=True) as grpc_tunnel:
            grpc_host, grpc_port = grpc_tunnel.tcp_socket
            grpc_endpoint = f"tcp+plaintext://{grpc_host}:{grpc_port}"
            async with modal.forward.aio(_REST_PORT, unencrypted=True) as rest_tunnel:
                rest_host, rest_port = rest_tunnel.tcp_socket
                rest_endpoint = f"http://{rest_host}:{rest_port}"
                # M5.2 (T018): expose the FastAPI shim a second time as a
                # plain-TCP tunnel so the M5.2 rest_plain_tcp cohort can
                # measure REST over the same TCP-only path the gRPC cohort
                # uses. The HTTPS-edge ``rest_endpoint`` above stays in
                # place for the rest_https_edge cohort and for M5.1
                # back-compat. The two REST tunnels terminate on the same
                # FastAPI shim, so the in-container engine code path is
                # held constant per FR-002. This is the ONLY Modal-side
                # change M5.2 makes.
                async with modal.forward.aio(_REST_PORT, unencrypted=True) as tcp_tunnel:
                    tcp_host, tcp_port = tcp_tunnel.tcp_socket
                    rest_plain_tcp_endpoint = f"tcp+plaintext://{tcp_host}:{tcp_port}"
                    await d.put.aio("grpc", grpc_endpoint)
                    await d.put.aio("rest", rest_endpoint)
                    await d.put.aio("rest_plain_tcp_url", rest_plain_tcp_endpoint)
                    await d.put.aio("token", token)
                    await d.put.aio("region", region)
                    await d.put.aio("ready", True)
                    while not await d.get.aio("teardown", default=False):
                        if time.monotonic() - started > _FUNCTION_TIMEOUT_S - 30:
                            break
                        await asyncio.sleep(_TEARDOWN_POLL_S)
    finally:
        rest_server.should_exit = True
        with contextlib.suppress(Exception):
            await asyncio.wait_for(rest_task, timeout=10.0)
        await grpc_server.stop(grace=5.0)
        for key in (
            "grpc",
            "rest",
            "rest_plain_tcp_url",
            "token",
            "region",
            "ready",
            "teardown",
        ):
            with contextlib.suppress(Exception):
                await d.pop.aio(key)

    return {"ok": True, "wallclock_s": time.monotonic() - started}


@app.local_entrypoint()
def main(token: str = "", region: str = "eu-west-1") -> None:
    if not token:
        print(
            "ERROR: pass --token=<bearer-token> (see specs/018-m5-1-rest-vs-grpc/quickstart.md)",
            file=sys.stderr,
        )
        sys.exit(2)
    print(f"[INFO] deploying {_APP_NAME!r} to region={region!r} …")
    serve_bench.remote(token=token, region=region)
