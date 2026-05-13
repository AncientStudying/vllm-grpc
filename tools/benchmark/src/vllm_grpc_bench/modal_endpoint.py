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

    M5.2 (T019) adds two optional fields populated when the caller passes
    ``with_rest_plain_tcp=True``:

    * ``rest_plain_tcp_url`` — the FastAPI shim's plain-TCP URL (the M5.2
      ``rest_plain_tcp`` cohort consumes this; effectively an alias for
      ``rest_url`` since M5.1 also forwards REST over plain-TCP).
    * ``rest_https_edge_url`` — the FastAPI shim's HTTPS-edge URL (the
      M5.2 ``rest_https_edge`` cohort consumes this; a SECOND uvicorn
      instance binds the shim on a separate in-container port so Modal
      can forward it as HTTPS-edge without conflicting with port 8000's
      plain-TCP forward).

    Defaults of ``None`` preserve M5.1's call signature.
    """

    grpc_url: str
    rest_url: str
    auth_token_env_var: str
    rest_plain_tcp_url: str | None = None
    rest_https_edge_url: str | None = None


class ModalDeployError(RuntimeError):
    """Raised when the Modal handshake fails (publishing, timeout, env)."""


def _strip_scheme(endpoint: str) -> str:
    """Normalize tunnel URLs to ``host:port``.

    Modal's ``modal.forward(unencrypted=False)`` may publish either
    ``tcp://host:port`` or ``grpcs://host:port`` depending on the Modal SDK
    version (contract m5-modal-app.md, "What the contract does NOT
    guarantee"). M5.1's ``serve_bench`` writes ``tcp+plaintext://host:port``
    for the gRPC tunnel (matches the harness's documentation of the plain-
    TCP-with-no-TLS choice forced by Modal's HTTPS edge ALPN constraint).
    gRPC channels accept the bare ``host:port`` form.
    """
    # Longest prefix first so ``tcp+plaintext://`` wins over ``tcp://``.
    for prefix in ("tcp+plaintext://", "tcp://", "grpcs://", "https://", "grpc://"):
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
    with_rest_plain_tcp: bool = False,
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
            for key in (
                "grpc",
                "rest",
                "rest_plain_tcp_url",
                "rest_https_edge_url",
                "token",
                "region",
                "ready",
                "teardown",
            ):
                with contextlib.suppress(Exception):
                    await d.pop.aio(key)
            (
                grpc_url,
                rest_url,
                rest_plain_tcp_url,
                rest_https_edge_url,
            ) = await _wait_for_rest_grpc_handshake(
                d,
                _M5_1_HANDSHAKE_TIMEOUT_S,
                expected_token=token,
                with_rest_plain_tcp=with_rest_plain_tcp,
            )
            try:
                yield RESTGRPCEndpoints(
                    grpc_url=_strip_scheme(grpc_url),
                    rest_url=rest_url,
                    auth_token_env_var=token_env,
                    rest_plain_tcp_url=rest_plain_tcp_url,
                    rest_https_edge_url=rest_https_edge_url,
                )
            finally:
                with contextlib.suppress(Exception):
                    await d.put.aio("teardown", True)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(serve_call.get.aio(), timeout=30.0)
    finally:
        output_ctx.__exit__(None, None, None)


async def refresh_rest_grpc_urls(
    cached: RESTGRPCEndpoints,
    *,
    poll_timeout_s: float = 90.0,
    poll_interval_s: float = 2.0,
) -> RESTGRPCEndpoints | None:
    """Re-read the Modal handshake Dict for fresh URLs after a suspected
    preemption event.

    When Modal preempts a running Function and restarts it on a new worker,
    the new ``serve_bench`` invocation writes new tunnel URLs to the same
    shared ``modal.Dict`` (per the Modal docs at
    https://modal.com/docs/guide/preemption — "Your Function will be
    restarted with the same input"). This helper polls that Dict for up to
    ``poll_timeout_s`` seconds, returning a new ``RESTGRPCEndpoints`` once
    the Dict's URLs differ from ``cached``'s URLs.

    Returns ``None`` if:
    * No fresh URLs appear within the timeout (probably not preemption —
      either Modal worker is still healthy or the new worker failed to
      start). The caller should treat the original ConnectError as a real
      failure.
    * The Dict isn't readable (e.g., shared Modal session went away).

    The cached endpoints' bearer-token env var name is preserved on the
    returned bundle; only the URLs are updated.
    """
    try:
        import modal

        d = modal.Dict.from_name(_M5_1_DICT_NAME, create_if_missing=False)
    except Exception:  # noqa: BLE001 — modal import or dict lookup
        return None

    deadline = time.monotonic() + poll_timeout_s
    while time.monotonic() < deadline:
        try:
            grpc_raw = await d.get.aio("grpc", default="")  # type: ignore[attr-defined]
            rest_raw = await d.get.aio("rest", default="")  # type: ignore[attr-defined]
            tcp_raw = await d.get.aio("rest_plain_tcp_url", default="")  # type: ignore[attr-defined]
            edge_raw = await d.get.aio("rest_https_edge_url", default="")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 — Dict access can fail in transit
            await asyncio.sleep(poll_interval_s)
            continue
        if not (
            isinstance(grpc_raw, str)
            and isinstance(rest_raw, str)
            and isinstance(tcp_raw, str)
            and isinstance(edge_raw, str)
            and grpc_raw
            and rest_raw
        ):
            await asyncio.sleep(poll_interval_s)
            continue
        # Fresh URLs are detected when the gRPC URL differs from the
        # cached one. The gRPC URL is the most stable handshake key (REST
        # URLs may match transiently if anycast routes to the same edge POP).
        cached_grpc_target = _strip_scheme(cached.grpc_url)
        new_grpc_target = _strip_scheme(grpc_raw)
        if new_grpc_target == cached_grpc_target:
            await asyncio.sleep(poll_interval_s)
            continue
        return RESTGRPCEndpoints(
            grpc_url=new_grpc_target,
            rest_url=rest_raw,
            auth_token_env_var=cached.auth_token_env_var,
            rest_plain_tcp_url=tcp_raw or None,
            rest_https_edge_url=edge_raw or None,
        )
    return None


async def _wait_for_rest_grpc_handshake(
    d: object,
    timeout_s: float,
    *,
    expected_token: str,
    with_rest_plain_tcp: bool = False,
) -> tuple[str, str, str | None, str | None]:
    """Poll the M5.1 handshake dict for ``ready==True``; return
    ``(grpc_url, rest_url, rest_plain_tcp_url, rest_https_edge_url)``.

    When ``with_rest_plain_tcp=True`` the function additionally waits for
    the ``rest_plain_tcp_url`` AND ``rest_https_edge_url`` keys (M5.2's
    third and fourth tunnels) and raises if either is missing once
    ``ready=True``.

    M5.1 callers leave ``with_rest_plain_tcp=False`` and read only the
    first two URLs; the trailing two elements are ``None``.
    """
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
            rest_plain_tcp: str | None = None
            rest_https_edge: str | None = None
            if with_rest_plain_tcp:
                raw_tcp = await d.get.aio("rest_plain_tcp_url", default="")  # type: ignore[attr-defined]
                if not isinstance(raw_tcp, str) or not raw_tcp:
                    raise ModalDeployError(
                        "M5.2 Modal handshake completed but rest_plain_tcp_url is empty; "
                        "is scripts/python/modal_bench_rest_grpc_server.py up to date?"
                    )
                rest_plain_tcp = raw_tcp
                raw_edge = await d.get.aio("rest_https_edge_url", default="")  # type: ignore[attr-defined]
                if not isinstance(raw_edge, str) or not raw_edge:
                    raise ModalDeployError(
                        "M5.2 Modal handshake completed but rest_https_edge_url is empty; "
                        "is scripts/python/modal_bench_rest_grpc_server.py up to date?"
                    )
                rest_https_edge = raw_edge
            return grpc_url, rest_url, rest_plain_tcp, rest_https_edge
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
