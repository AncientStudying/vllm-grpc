"""M6.2 production RPC driver — parameterized over ``max_tokens`` + ``ignore_eos`` + prompt source.

Per FR-028 copy-then-refactor: mirrors :mod:`m6_1_rpc_driver`'s M6.1.2 driver
shape (``provide_m6_1_2_rpc_driver``) but adds the four M6.2 kwargs that the
M6.1.x driver surface cannot thread:

* ``max_tokens`` — outer-axis cap (one of ``M6_2_MAX_TOKENS_AXIS``).
* ``ignore_eos`` — ``True`` only in KV-pressure sub-probe blocks (FR-036).
* ``prompt`` — corpus-derived chat prompt for interior-cap + sub-probe regimes
  (FR-034). ``None`` falls back to the synthetic seed-derived prompt.
* ``prompt_embeds_override`` — corpus-derived embed bytes for interior-cap +
  sub-probe regimes (FR-035). ``None`` falls back to the synthetic random
  tensor.

The M6.1.x dispatchers (`_drive_grpc_chat_stream`, `_drive_grpc_embed_m6_1`,
etc.) hardcode the M6.1.x request-builder calls and have no plumbing for the
M6.2 args. Per the project's copy-then-refactor convention (M6.1.3 plan
§254), M6.2 ships its own dispatchers in this module rather than mutating
the M6.1.x ones.

The request builders themselves (`_build_chat_grpc_request`,
`_build_chat_rest_payload`, `_build_embed_grpc_request`,
`_build_embed_rest_payload_m6_1`) already carry the M6.2 kwargs as
keyword-only with M6.1.x defaults (T007 / T008). This module just calls them
with the M6.2-side values.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import grpc
import httpx

from vllm_grpc_bench.channel_config import M1_BASELINE, MAX_MSG_16MIB, ChannelConfig
from vllm_grpc_bench.m3_sweep import _client_kwargs
from vllm_grpc_bench.m3_types import RTTRecord
from vllm_grpc_bench.m6_1_2_types import M6_1_2CohortKind
from vllm_grpc_bench.m6_1_rpc_driver import (
    _build_embed_grpc_request,
    _build_embed_rest_payload_m6_1,
    _normalize_rest_url_for_httpx,
    _resolve_rpc_index,
)
from vllm_grpc_bench.m6_1_types import M6_1Cell
from vllm_grpc_bench.m6_engine_cost import (
    parse_grpc_trailing_metadata,
    parse_rest_response,
)
from vllm_grpc_bench.m6_rpc_driver import (
    _build_chat_grpc_request,
    _build_chat_rest_payload,
    _rest_rtt_probe,
)
from vllm_grpc_bench.m6_sweep import RPCResult
from vllm_grpc_bench.modal_endpoint import RESTGRPCEndpoints
from vllm_grpc_bench.rtt_probe import measure_rtt

__all__ = [
    "M6_2RPCDriver",
    "provide_m6_2_rpc_driver",
]


_DEFAULT_RTT_PROBE_N: int = 32


M6_2RPCDriver = Callable[
    [M6_1_2CohortKind, M6_1Cell, int],
    Awaitable[RPCResult],
]
"""Async per-RPC dispatcher with the M6.2 kwargs.

The concrete signature (see :func:`provide_m6_2_rpc_driver`) is::

    async def driver(
        cohort: M6_1_2CohortKind,
        cell: M6_1Cell,
        seed: int,
        *,
        max_tokens: int,
        ignore_eos: bool = False,
        prompt: str | None = None,
        prompt_embeds_override: bytes | None = None,
    ) -> RPCResult

Python's ``Callable`` typing alias cannot express the keyword-only kwargs, so
we type the alias on the positional surface only. Concrete callers thread the
kwargs explicitly.
"""


# --- gRPC dispatchers --------------------------------------------------------


async def _drive_grpc_chat_stream_m6_2(
    channel: grpc.aio.Channel,
    seed: int,
    metadata: tuple[tuple[str, str], ...],
    timeout_s: float,
    *,
    max_tokens: int,
    ignore_eos: bool,
    prompt: str | None,
) -> RPCResult:
    """M6.2 chat_stream gRPC dispatcher — threads max_tokens / ignore_eos / prompt.

    Mirrors :func:`m6_rpc_driver._drive_grpc_chat_stream` but passes the M6.2
    kwargs to :func:`_build_chat_grpc_request`. The frontend reads
    ``ChatCompleteRequest.ignore_eos`` per T003a and routes it into
    ``SamplingParams.ignore_eos``.
    """
    from vllm_grpc.v1 import chat_pb2_grpc

    stub = chat_pb2_grpc.ChatServiceStub(channel)
    req = _build_chat_grpc_request(
        seed,
        max_tokens=max_tokens,
        ignore_eos=ignore_eos,
        prompt=prompt,
    )
    t0 = time.perf_counter()
    first_chunk_at: float | None = None
    call = None
    try:
        call = stub.CompleteStream(req, timeout=timeout_s, metadata=metadata)
        async for chunk in call:
            if chunk.delta_content and first_chunk_at is None:
                first_chunk_at = time.perf_counter()
    except grpc.RpcError as exc:
        return RPCResult(
            success=False,
            wall_clock_ms=None,
            ttft_ms=None,
            engine_cost=None,
            failure_reason=f"grpc chat: {exc.code()} {exc.details()}"[:120],
        )
    wall_ms = (time.perf_counter() - t0) * 1000.0
    ttft_ms = (first_chunk_at - t0) * 1000.0 if first_chunk_at else None
    try:
        md = await call.trailing_metadata() if call is not None else None
    except Exception:  # noqa: BLE001
        md = None
    engine_cost = parse_grpc_trailing_metadata(md, "chat_stream") if md is not None else None
    from vllm_grpc_bench.m6_1_1_timing import extract_grpc_timings, timing_checkpoint_to_payload

    md_dict = {k: v for k, v in md} if md is not None else None
    m6_1_1_payload = timing_checkpoint_to_payload(
        extract_grpc_timings(md_dict) if md_dict is not None else None
    )
    return RPCResult(
        success=True,
        wall_clock_ms=wall_ms,
        ttft_ms=ttft_ms,
        engine_cost=engine_cost,
        failure_reason=None,
        m6_1_1_timing_payload=m6_1_1_payload,
    )


async def _drive_grpc_embed_m6_2(
    channel: grpc.aio.Channel,
    cell: M6_1Cell,
    seq_len: int,
    rpc_index: int,
    base_seed: int,
    metadata: tuple[tuple[str, str], ...],
    timeout_s: float,
    *,
    max_tokens: int,
    ignore_eos: bool,
    prompt_embeds_override: bytes | None,
) -> RPCResult:
    """M6.2 embed gRPC dispatcher — threads max_tokens / ignore_eos / corpus embed bytes."""
    from vllm_grpc.v1 import completions_pb2_grpc

    stub = completions_pb2_grpc.CompletionsServiceStub(channel)
    req = _build_embed_grpc_request(
        seq_len,
        cell.hidden_size,
        rpc_index,
        base_seed,
        max_tokens=max_tokens,
        ignore_eos=ignore_eos,
        prompt_embeds_override=prompt_embeds_override,
    )
    t0 = time.perf_counter()
    call = stub.Complete(req, timeout=timeout_s, metadata=metadata)
    try:
        _ = await call
    except grpc.RpcError as exc:
        return RPCResult(
            success=False,
            wall_clock_ms=None,
            ttft_ms=None,
            engine_cost=None,
            failure_reason=f"grpc embed: {exc.code()} {exc.details()}"[:120],
        )
    wall_ms = (time.perf_counter() - t0) * 1000.0
    try:
        md = await call.trailing_metadata()
    except Exception:  # noqa: BLE001
        md = None
    engine_cost = parse_grpc_trailing_metadata(md, "embed") if md is not None else None
    from vllm_grpc_bench.m6_1_1_timing import extract_grpc_timings, timing_checkpoint_to_payload

    md_dict = {k: v for k, v in md} if md is not None else None
    m6_1_1_payload = timing_checkpoint_to_payload(
        extract_grpc_timings(md_dict) if md_dict is not None else None
    )
    return RPCResult(
        success=True,
        wall_clock_ms=wall_ms,
        ttft_ms=None,
        engine_cost=engine_cost,
        failure_reason=None,
        m6_1_1_timing_payload=m6_1_1_payload,
    )


# --- REST dispatchers --------------------------------------------------------


async def _drive_rest_chat_stream_m6_2(
    client: httpx.AsyncClient,
    base_url: str,
    auth: dict[str, str],
    seed: int,
    timeout_s: float,
    *,
    max_tokens: int,
    ignore_eos: bool,
    prompt: str | None,
) -> RPCResult:
    """M6.2 chat_stream REST dispatcher — threads max_tokens / ignore_eos / prompt."""
    body = _build_chat_rest_payload(
        seed,
        max_tokens=max_tokens,
        ignore_eos=ignore_eos,
        prompt=prompt,
    )
    body_bytes = json.dumps(body).encode()
    t0 = time.perf_counter()
    first_chunk_at: float | None = None
    try:
        async with client.stream(
            "POST",
            f"{base_url}/v1/chat/completions",
            content=body_bytes,
            headers={**auth, "content-type": "application/json"},
            timeout=timeout_s,
        ) as resp:
            if resp.status_code != 200:
                return RPCResult(
                    success=False,
                    wall_clock_ms=None,
                    ttft_ms=None,
                    engine_cost=None,
                    failure_reason=f"rest chat: {resp.status_code}"[:120],
                )
            async for line in resp.aiter_lines():
                if not line.startswith("data:") or "[DONE]" in line:
                    continue
                if first_chunk_at is None:
                    first_chunk_at = time.perf_counter()
    except httpx.HTTPError as exc:
        return RPCResult(
            success=False,
            wall_clock_ms=None,
            ttft_ms=None,
            engine_cost=None,
            failure_reason=f"rest chat: {type(exc).__name__}: {exc}"[:120],
        )
    wall_ms = (time.perf_counter() - t0) * 1000.0
    ttft_ms = (first_chunk_at - t0) * 1000.0 if first_chunk_at else None
    return RPCResult(
        success=True,
        wall_clock_ms=wall_ms,
        ttft_ms=ttft_ms,
        engine_cost=None,
        failure_reason=None,
    )


async def _drive_rest_embed_m6_2(
    client: httpx.AsyncClient,
    base_url: str,
    auth: dict[str, str],
    cell: M6_1Cell,
    seq_len: int,
    rpc_index: int,
    base_seed: int,
    timeout_s: float,
    *,
    max_tokens: int,
    ignore_eos: bool,
    prompt_embeds_override: bytes | None,
) -> RPCResult:
    """M6.2 embed REST dispatcher — threads max_tokens / ignore_eos / corpus embed bytes."""
    body = _build_embed_rest_payload_m6_1(
        seq_len,
        cell.hidden_size,
        rpc_index,
        base_seed,
        max_tokens=max_tokens,
        ignore_eos=ignore_eos,
        prompt_embeds_override=prompt_embeds_override,
    )
    body_bytes = json.dumps(body).encode()
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            f"{base_url}/v1/embeddings",
            content=body_bytes,
            headers={**auth, "content-type": "application/json"},
            timeout=timeout_s,
        )
    except httpx.HTTPError as exc:
        return RPCResult(
            success=False,
            wall_clock_ms=None,
            ttft_ms=None,
            engine_cost=None,
            failure_reason=f"rest embed: {type(exc).__name__}: {exc}"[:120],
        )
    wall_ms = (time.perf_counter() - t0) * 1000.0
    if resp.status_code != 200:
        return RPCResult(
            success=False,
            wall_clock_ms=None,
            ttft_ms=None,
            engine_cost=None,
            failure_reason=f"rest embed: {resp.status_code}"[:120],
        )
    try:
        payload = resp.json()
    except (ValueError, json.JSONDecodeError):
        payload = {}
    engine_cost = parse_rest_response(payload, "embed") if isinstance(payload, dict) else None
    return RPCResult(
        success=True,
        wall_clock_ms=wall_ms,
        ttft_ms=None,
        engine_cost=engine_cost,
        failure_reason=None,
    )


# --- Driver context manager --------------------------------------------------


def _open_grpc_channel(target: str, cfg: ChannelConfig) -> grpc.aio.Channel:
    return grpc.aio.insecure_channel(target, **_client_kwargs(cfg))


@asynccontextmanager
async def provide_m6_2_rpc_driver(
    endpoints: RESTGRPCEndpoints,
    *,
    seq_len: int,
    base_seed: int = 42,
    rtt_probe_n: int = _DEFAULT_RTT_PROBE_N,
    rpc_timeout_s: float = 120.0,
) -> AsyncIterator[
    tuple[
        Callable[..., Awaitable[RPCResult]],
        dict[M6_1_2CohortKind, RTTRecord],
    ]
]:
    """Open gRPC channels + httpx client; yield ``(driver, rtt_distribution)``.

    Mirrors :func:`m6_1_rpc_driver.provide_m6_1_2_rpc_driver` (4-cohort
    matrix, same channel configurations, same RTT probe semantics) but yields
    a driver callable whose per-RPC signature accepts the four M6.2 kwargs
    (`max_tokens`, `ignore_eos`, `prompt`, `prompt_embeds_override`) per
    block. The cohort × cell × seed positional shape is unchanged so the
    M6.2 sweep orchestrator's existing dispatch machinery applies verbatim.

    ``rpc_timeout_s`` defaults to 120 s (vs M6.1.x's 90 s) to leave headroom
    for the ``max_tokens=2048`` axis point at chat_stream c=8 — a 50-token
    chat reply typically completes in ~1-2 s, but a 2048-token reply at c=8
    queue saturation can approach 90 s on the smaller A10G.
    """
    token = os.environ.get(endpoints.auth_token_env_var, "")
    if not token:
        raise RuntimeError(
            f"environment variable {endpoints.auth_token_env_var!r} is not "
            "set; the M6.2 RPC driver requires the bearer token to be "
            "readable at RPC dispatch time"
        )
    grpc_metadata: tuple[tuple[str, str], ...] = (("authorization", f"Bearer {token}"),)
    rest_auth = {"authorization": f"Bearer {token}"}

    if endpoints.rest_https_edge_url is None:
        raise RuntimeError(
            "M6.2 RPC driver requires endpoints.rest_https_edge_url; did the Modal deploy succeed?"
        )
    if endpoints.rest_plain_tcp_url is None:
        raise RuntimeError(
            "M6.2 RPC driver requires endpoints.rest_plain_tcp_url; "
            "the Modal deploy must be launched with with_rest_plain_tcp=True"
        )
    rest_https_edge_base = _normalize_rest_url_for_httpx(endpoints.rest_https_edge_url)
    rest_plain_tcp_base = _normalize_rest_url_for_httpx(endpoints.rest_plain_tcp_url)

    default_channel = _open_grpc_channel(endpoints.grpc_url, M1_BASELINE)
    tuned_channel = _open_grpc_channel(endpoints.grpc_url, MAX_MSG_16MIB)
    rest_client = httpx.AsyncClient(
        http2=False,
        limits=httpx.Limits(max_keepalive_connections=8, max_connections=8),
    )
    try:
        rtt: dict[M6_1_2CohortKind, RTTRecord] = {
            "default_grpc": await measure_rtt(
                default_channel, n=rtt_probe_n, metadata=grpc_metadata
            ),
            "tuned_grpc_multiplexed": await measure_rtt(
                tuned_channel, n=rtt_probe_n, metadata=grpc_metadata
            ),
            "rest_https_edge": await _rest_rtt_probe(
                rest_client, rest_https_edge_base, n=rtt_probe_n
            ),
            "rest_plain_tcp": await _rest_rtt_probe(
                rest_client, rest_plain_tcp_base, n=rtt_probe_n
            ),
        }

        async def driver(
            cohort: M6_1_2CohortKind,
            cell: M6_1Cell,
            seed: int,
            *,
            max_tokens: int,
            ignore_eos: bool = False,
            prompt: str | None = None,
            prompt_embeds_override: bytes | None = None,
        ) -> RPCResult:
            rpc_index = _resolve_rpc_index(seed, base_seed)
            if cohort in ("rest_https_edge", "rest_plain_tcp"):
                rest_base = (
                    rest_https_edge_base if cohort == "rest_https_edge" else rest_plain_tcp_base
                )
                if cell.path == "embed":
                    return await _drive_rest_embed_m6_2(
                        rest_client,
                        rest_base,
                        rest_auth,
                        cell,
                        seq_len,
                        rpc_index,
                        base_seed,
                        rpc_timeout_s,
                        max_tokens=max_tokens,
                        ignore_eos=ignore_eos,
                        prompt_embeds_override=prompt_embeds_override,
                    )
                return await _drive_rest_chat_stream_m6_2(
                    rest_client,
                    rest_base,
                    rest_auth,
                    seed,
                    rpc_timeout_s,
                    max_tokens=max_tokens,
                    ignore_eos=ignore_eos,
                    prompt=prompt,
                )
            channel = default_channel if cohort == "default_grpc" else tuned_channel
            if cell.path == "embed":
                return await _drive_grpc_embed_m6_2(
                    channel,
                    cell,
                    seq_len,
                    rpc_index,
                    base_seed,
                    grpc_metadata,
                    rpc_timeout_s,
                    max_tokens=max_tokens,
                    ignore_eos=ignore_eos,
                    prompt_embeds_override=prompt_embeds_override,
                )
            return await _drive_grpc_chat_stream_m6_2(
                channel,
                seed,
                grpc_metadata,
                rpc_timeout_s,
                max_tokens=max_tokens,
                ignore_eos=ignore_eos,
                prompt=prompt,
            )

        yield driver, rtt
    finally:
        with contextlib.suppress(Exception):
            await rest_client.aclose()
        with contextlib.suppress(Exception):
            await default_channel.close(grace=5.0)
        with contextlib.suppress(Exception):
            await tuned_channel.close(grace=5.0)
