"""Harness-side Modal handshake: deploy → capture endpoint → yield → teardown.

Implements the ``EndpointProvider`` Protocol so :func:`m4_sweep._measure_cell`
can drive cohorts against the cross-host Modal-hosted gRPC server (research.md
R-2). Two providers live here:

* :func:`provide_endpoint` — full deploy/teardown lifecycle. Imports the
  Modal app from ``scripts/python/modal_bench_grpc_server.py``, enters
  ``app.run.aio()`` (so deploy on entry, teardown on exit), spawns
  ``serve_bench`` with the operator's bearer token, polls
  ``modal.Dict("vllm-grpc-bench-mock-handshake")`` until ``ready==True``,
  and yields an ``EndpointTuple`` whose target is the published tunnel URL
  and whose call metadata carries the ``authorization: Bearer …`` header.
* :func:`static_endpoint_provider` — bypass deploy for the
  ``--m5-skip-deploy`` flow. Yields an ``EndpointTuple`` against an
  already-running Modal endpoint passed on the CLI. Used during iteration
  so an operator doesn't pay the per-run deploy cost.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vllm_grpc_bench.channel_config import ChannelConfig
from vllm_grpc_bench.m3_types import EndpointTuple

if TYPE_CHECKING:
    from vllm_grpc_bench.mock_engine import MockEngine

_DICT_NAME = "vllm-grpc-bench-mock-handshake"
_HANDSHAKE_TIMEOUT_S = 120.0
_HANDSHAKE_POLL_S = 0.5

# M5.1 dual-protocol handshake dict + timeout. Uses its own dict name so an
# M5 deploy in flight does not collide with a parallel M5.1 deploy on the
# same Modal workspace.
_M5_1_DICT_NAME = "vllm-grpc-bench-rest-grpc-mock-handshake"
_M5_1_HANDSHAKE_TIMEOUT_S = 180.0


@dataclass(frozen=True)
class RESTGRPCEndpoints:
    """Dual-protocol endpoint bundle returned by ``provide_endpoint(variant='rest_grpc')``.

    Carries both tunnel URLs plus the env-var name the bearer token was
    read from (the token value itself is *never* stored — it remains in the
    operator's environment and is read at use-site).
    """

    grpc_url: str
    rest_url: str
    auth_token_env_var: str


class ModalDeployError(RuntimeError):
    """Raised when the Modal handshake fails (publishing, timeout, env)."""


def _strip_scheme(endpoint: str) -> str:
    """Normalize tunnel URLs to ``host:port``.

    Modal's ``modal.forward(unencrypted=False)`` may publish either
    ``tcp://host:port`` or ``grpcs://host:port`` depending on the Modal SDK
    version (contract m5-modal-app.md, "What the contract does NOT
    guarantee"). gRPC channels accept the bare ``host:port`` form.
    """
    for prefix in ("tcp://", "grpcs://", "https://", "grpc://"):
        if endpoint.startswith(prefix):
            return endpoint[len(prefix) :]
    return endpoint


@asynccontextmanager
async def provide_endpoint(
    engine: MockEngine,
    channel_config: ChannelConfig,
    *,
    region: str = "us-east-1",
    token_env: str = "MODAL_BENCH_TOKEN",
) -> AsyncIterator[EndpointTuple]:
    """Deploy the Modal bench app, capture endpoint + token, yield EndpointTuple.

    ``engine`` and ``channel_config`` are accepted for ``EndpointProvider``
    Protocol parity with ``serve_in_process_adapter``. The Modal-side server
    uses its own ``MockEngine`` instance — server-side engine state is not
    cohort-coupled, so the cross-host server can reuse the same engine
    across cohorts while each cohort still varies its client-side channel
    config independently.
    """
    token = os.environ.get(token_env, "")
    if not token:
        raise ModalDeployError(
            f"environment variable {token_env!r} is not set; "
            "M5 requires a bearer token to be exported before the sweep "
            "(see specs/017-m5-cross-host-validation/quickstart.md)"
        )

    # Defer the import so the module remains importable in environments
    # without modal installed (e.g., unit-test runners that stub the harness
    # entirely). The runtime import error is mapped to ModalDeployError so
    # the harness can surface a clean message and exit code 3.
    try:
        import modal

        from scripts.python.modal_bench_grpc_server import app, serve_bench
    except ImportError as exc:
        raise ModalDeployError(
            f"failed to import Modal app module: {exc}; "
            "ensure modal is installed (`uv sync`) and the bench-server script "
            "is on PYTHONPATH"
        ) from exc

    # Surface Modal image-build and runtime logs so build failures don't
    # arrive as opaque ``RemoteError`` traces. ``enable_output()`` is safe to
    # call repeatedly and only affects this process.
    output_ctx = modal.enable_output()
    output_ctx.__enter__()
    try:
        async with app.run.aio():
            # ``spawn.aio()`` is a coroutine that *initiates* the remote
            # function call and returns a ``FunctionCall`` handle. Awaiting it
            # immediately is mandatory — without the await, the spawn never
            # happens and the harness times out waiting for a handshake that
            # the un-started function can never publish.
            serve_call = await serve_bench.spawn.aio(token=token, region=region)
            d = modal.Dict.from_name(_DICT_NAME, create_if_missing=True)
            # Clear any stale handshake state from an earlier crashed run.
            for key in ("endpoint", "token", "region", "ready", "teardown"):
                with contextlib.suppress(Exception):
                    await d.pop.aio(key)

            endpoint = await _wait_for_handshake(d, _HANDSHAKE_TIMEOUT_S, expected_token=token)
            target = _strip_scheme(endpoint)
            metadata: tuple[tuple[str, str], ...] = (("authorization", f"Bearer {token}"),)
            try:
                # Modal's gRPC-friendly tunnel is plain TCP (the HTTPS edge
                # doesn't negotiate h2 ALPN). FR-002's auth requirement is
                # satisfied at the application level by the bearer-token
                # interceptor — the harness still attaches the token as call
                # metadata on every RPC.
                yield (target, None, metadata)
            finally:
                # Signal teardown via dict so the Modal-side server exits cleanly.
                with contextlib.suppress(Exception):
                    await d.put.aio("teardown", True)
                # Wait briefly for the spawned call to drain. app.run.aio()'s exit
                # will hard-stop the function if it lingers past Modal's grace.
                # ``serve_call`` is a ``FunctionCall`` handle; ``.get.aio()``
                # awaits the remote function's return value.
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(serve_call.get.aio(), timeout=30.0)
    finally:
        output_ctx.__exit__(None, None, None)


@asynccontextmanager
async def provide_rest_grpc_endpoint(
    *,
    region: str = "eu-west-1",
    token_env: str = "MODAL_BENCH_TOKEN",
) -> AsyncIterator[RESTGRPCEndpoints]:
    """M5.1 dual-protocol deploy: deploys the FastAPI shim + gRPC server,
    captures both tunnel URLs, yields a :class:`RESTGRPCEndpoints` bundle.

    On context exit the Modal app is torn down via the shared ``modal.Dict``'s
    ``teardown=True`` signal (same pattern as the M5 gRPC-only path). The
    bearer-token value is *never* returned — only the env-var name is.
    """
    token = os.environ.get(token_env, "")
    if not token:
        raise ModalDeployError(
            f"environment variable {token_env!r} is not set; "
            "M5.1 requires a bearer token to be exported before the sweep "
            "(see specs/018-m5-1-rest-vs-grpc/quickstart.md)"
        )
    try:
        import modal

        from scripts.python.modal_bench_rest_grpc_server import app, serve_bench
    except ImportError as exc:
        raise ModalDeployError(
            f"failed to import M5.1 Modal app module: {exc}; "
            "ensure modal is installed (`uv sync`) and the M5.1 deploy script "
            "is on PYTHONPATH"
        ) from exc

    output_ctx = modal.enable_output()
    output_ctx.__enter__()
    try:
        async with app.run.aio():
            serve_call = await serve_bench.spawn.aio(token=token, region=region)
            d = modal.Dict.from_name(_M5_1_DICT_NAME, create_if_missing=True)
            for key in ("grpc", "rest", "token", "region", "ready", "teardown"):
                with contextlib.suppress(Exception):
                    await d.pop.aio(key)
            grpc_url, rest_url = await _wait_for_rest_grpc_handshake(
                d, _M5_1_HANDSHAKE_TIMEOUT_S, expected_token=token
            )
            try:
                yield RESTGRPCEndpoints(
                    grpc_url=_strip_scheme(grpc_url),
                    rest_url=rest_url,
                    auth_token_env_var=token_env,
                )
            finally:
                with contextlib.suppress(Exception):
                    await d.put.aio("teardown", True)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(serve_call.get.aio(), timeout=30.0)
    finally:
        output_ctx.__exit__(None, None, None)


async def _wait_for_rest_grpc_handshake(
    d: object, timeout_s: float, *, expected_token: str
) -> tuple[str, str]:
    """Poll the M5.1 handshake dict for ``ready==True``; return (grpc_url, rest_url)."""
    deadline = time.monotonic() + timeout_s
    last_seen: dict[str, object] = {}
    while time.monotonic() < deadline:
        ready = await d.get.aio("ready", default=False)  # type: ignore[attr-defined]
        if ready:
            grpc_url = await d.get.aio("grpc", default="")  # type: ignore[attr-defined]
            rest_url = await d.get.aio("rest", default="")  # type: ignore[attr-defined]
            echoed = await d.get.aio("token", default="")  # type: ignore[attr-defined]
            if not isinstance(grpc_url, str) or not grpc_url:
                raise ModalDeployError("M5.1 Modal handshake completed but gRPC URL is empty")
            if not isinstance(rest_url, str) or not rest_url:
                raise ModalDeployError("M5.1 Modal handshake completed but REST URL is empty")
            if echoed != expected_token:
                raise ModalDeployError(
                    "M5.1 Modal handshake completed but bearer-token echo does not match; "
                    "another Modal app may be using the shared M5.1 handshake dict"
                )
            return grpc_url, rest_url
        last_seen = {"ready": ready}
        await asyncio.sleep(_HANDSHAKE_POLL_S)
    raise ModalDeployError(
        f"M5.1 Modal handshake timed out after {timeout_s:.0f}s; last_seen={last_seen!r}"
    )


@asynccontextmanager
async def static_endpoint_provider(
    engine: MockEngine,
    channel_config: ChannelConfig,
    *,
    target: str,
    token_env: str = "MODAL_BENCH_TOKEN",
) -> AsyncIterator[EndpointTuple]:
    """``--m5-skip-deploy`` provider: yield an EndpointTuple for an already-running
    Modal endpoint without entering ``app.run.aio()``.

    The harness still attaches the bearer-token metadata so the existing
    Modal-side ``BearerTokenInterceptor`` accepts the call.
    """
    token = os.environ.get(token_env, "")
    if not token:
        raise ModalDeployError(
            f"environment variable {token_env!r} is not set; "
            "--m5-skip-deploy still requires the bearer token to be exported"
        )
    metadata: tuple[tuple[str, str], ...] = (("authorization", f"Bearer {token}"),)
    # Modal's gRPC-friendly tunnel is plain TCP; the bearer-token interceptor
    # on the Modal-side server provides FR-002 auth.
    yield (_strip_scheme(target), None, metadata)


async def _wait_for_handshake(d: object, timeout_s: float, *, expected_token: str) -> str:
    """Poll the shared Modal Dict for ``ready==True``; return the endpoint URL.

    Verifies that the token echoed back by the server matches the value the
    harness shipped, so a stray previous-run server's handshake can't be
    confused with the current one.
    """
    deadline = time.monotonic() + timeout_s
    last_seen: dict[str, object] = {}
    while time.monotonic() < deadline:
        ready = await d.get.aio("ready", default=False)  # type: ignore[attr-defined]
        if ready:
            endpoint = await d.get.aio("endpoint", default="")  # type: ignore[attr-defined]
            echoed = await d.get.aio("token", default="")  # type: ignore[attr-defined]
            if not isinstance(endpoint, str) or not endpoint:
                raise ModalDeployError("Modal handshake completed but endpoint URL is empty")
            if echoed != expected_token:
                raise ModalDeployError(
                    "Modal handshake completed but bearer-token echo does not match; "
                    "another Modal app may be using the shared handshake dict"
                )
            return endpoint
        last_seen = {"ready": ready}
        await asyncio.sleep(_HANDSHAKE_POLL_S)
    raise ModalDeployError(
        f"Modal handshake timed out after {timeout_s:.0f}s; last_seen={last_seen!r}"
    )
