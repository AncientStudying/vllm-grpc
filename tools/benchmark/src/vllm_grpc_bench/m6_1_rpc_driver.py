"""M6.1 production RPC driver — real-prompt-embeds engine path.

Mirrors :mod:`vllm_grpc_bench.m6_rpc_driver` with one change: the embed-cell
request builder ships ``torch.save`` bytes in ``CompletionRequest.prompt_embeds``
(instead of M6's raw float32 ``tensor.tobytes()``). The frontend's existing
``_resolve_prompt_embeds_input`` dispatch routes the ZIP-magic-prefixed bytes
to ``decode_embeds`` → ``{"prompt_embeds": tensor}`` → real prompt-embeds
inference via ``enable_prompt_embeds=True``.

The chat_stream request builder is re-exported from
:mod:`vllm_grpc_bench.m6_rpc_driver` unchanged (FR-005 — chat_stream wire format
identical to M6).
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import grpc
import httpx
from vllm_grpc.v1 import completions_pb2

from vllm_grpc_bench.channel_config import M1_BASELINE, MAX_MSG_16MIB, ChannelConfig
from vllm_grpc_bench.m3_sweep import _client_kwargs
from vllm_grpc_bench.m3_types import RTTRecord
from vllm_grpc_bench.m6_1_2_types import M6_1_2CohortKind
from vllm_grpc_bench.m6_1_seed import build_torch_generator_for_rpc
from vllm_grpc_bench.m6_1_types import (
    M6_1_CHAT_MAX_TOKENS,
    M6_1_PROMPT_EMBED_HIDDEN_SIZE,
    EngineCostSpan,
    M6_1Cell,
    M6_1CohortKind,
)
from vllm_grpc_bench.m6_engine_cost import (
    parse_grpc_trailing_metadata,
    parse_rest_response,
)
from vllm_grpc_bench.m6_rpc_driver import (
    _build_chat_grpc_request,
    _build_chat_prompt,
    _build_chat_rest_payload,
    _drive_grpc_chat_stream,
    _drive_rest_chat_stream,
    _rest_rtt_probe,
)
from vllm_grpc_bench.m6_sweep import RPCDriver, RPCResult
from vllm_grpc_bench.modal_endpoint import RESTGRPCEndpoints
from vllm_grpc_bench.rtt_probe import measure_rtt

_DEFAULT_RTT_PROBE_N: int = 32


def _normalize_rest_url_for_httpx(url: str) -> str:
    """Convert Modal's published REST URLs into an httpx-compatible scheme.

    Modal's ``modal.forward(unencrypted=True)`` publishes plain-TCP
    tunnels as ``tcp+plaintext://host:port``; httpx only accepts HTTP or
    HTTPS, so rewrite the scheme to ``http://`` (plain TCP without TLS
    *is* plain HTTP from the client's perspective). HTTPS edge URLs and
    bare ``host:port`` forms pass through unchanged or get an ``http://``
    prefix respectively.

    M5.2 documents the same transform at ``m5_2_sweep.py:1280-1283``.
    """
    if url.startswith("tcp+plaintext://"):
        return "http://" + url[len("tcp+plaintext://") :]
    if url.startswith(("http://", "https://")):
        return url
    # Bare host:port — assume plain HTTP. Matches the M5.2 fallback.
    return "http://" + url


def _resolve_rpc_index(seed: int, base_seed: int) -> int:
    """Convert a per-RPC sampling seed into a non-negative ``rpc_index``.

    Measurement RPCs use ``seed = base_seed + rpc_index`` (FR-019), so
    ``seed - base_seed`` recovers the index. Smoke + warmup RPCs pass
    ``seed=0`` by convention (FR-015 / FR-012 — they're not part of the
    indexed sequence), which would otherwise produce a negative index and
    crash ``build_torch_generator_for_rpc``. Clamping to 0 means smoke +
    warmup RPCs share a single deterministic tensor — fine, because those
    paths are wiring validation, not measurement.
    """
    return max(0, seed - base_seed)


# Re-export chat_stream builders for callers that want symmetry with M6.
__all__ = [
    "_build_chat_grpc_request",
    "_build_chat_prompt",
    "_build_chat_rest_payload",
    "_build_embed_grpc_request",
    "_build_embed_rest_payload_m6_1",
    "build_torch_save_bytes",
    "provide_m6_1_2_rpc_driver",
    "provide_m6_1_rpc_driver",
]


# --- Embed request builders --------------------------------------------------


def build_torch_save_bytes(
    seq_len: int,
    hidden_size: int,
    rpc_index: int,
    base_seed: int,
) -> bytes:
    """Build the ``torch.save`` bytes for one M6.1 embed RPC (FR-002 / FR-028).

    Returns the raw ZIP-magic-prefixed bytes that ship in
    ``CompletionRequest.prompt_embeds`` (gRPC) OR get base64-wrapped for
    the REST shim.
    """
    import torch

    g = build_torch_generator_for_rpc(rpc_index, base_seed=base_seed)
    tensor = torch.randn((seq_len, hidden_size), dtype=torch.float16, generator=g)
    buf = io.BytesIO()
    torch.save(tensor, buf)
    return buf.getvalue()


def _build_embed_grpc_request(
    seq_len: int,
    hidden_size: int,
    rpc_index: int,
    base_seed: int,
    seed: int | None = None,
) -> completions_pb2.CompletionRequest:
    """Build a gRPC embed request for M6.1.

    The ``seed`` field is the ``SamplingParams.seed`` (FR-019). If omitted,
    defaults to ``base_seed + rpc_index`` so callers that don't care about
    differentiation between sampling-seed and tensor-seed don't have to
    compute it twice.
    """
    payload = build_torch_save_bytes(seq_len, hidden_size, rpc_index, base_seed)
    sampling_seed = seed if seed is not None else base_seed + rpc_index
    return completions_pb2.CompletionRequest(
        prompt_embeds=payload,
        max_tokens=10,
        seed=sampling_seed,
    )


def _build_embed_rest_payload_m6_1(
    seq_len: int,
    hidden_size: int,
    rpc_index: int,
    base_seed: int,
    seed: int | None = None,
) -> dict[str, Any]:
    """Build the REST embed payload for M6.1 (FR-003).

    Emits ``input_kind="prompt_embedding_torch_b64"`` and the base64-encoded
    ``torch.save`` bytes. The REST shim deserialises via ``decode_embeds`` and
    routes through ``enable_prompt_embeds=True``.
    """
    raw = build_torch_save_bytes(seq_len, hidden_size, rpc_index, base_seed)
    encoded = base64.b64encode(raw).decode("ascii")
    sampling_seed = seed if seed is not None else base_seed + rpc_index
    return {
        "model": "mock",
        "input_kind": "prompt_embedding_torch_b64",
        "input": encoded,
        "hidden_size": hidden_size,
        "max_tokens": 10,
        "seed": sampling_seed,
    }


# --- gRPC + REST driver primitives ------------------------------------------


async def _drive_grpc_embed_m6_1(
    channel: grpc.aio.Channel,
    cell: M6_1Cell,
    seq_len: int,
    rpc_index: int,
    base_seed: int,
    metadata: tuple[tuple[str, str], ...],
    timeout_s: float,
) -> RPCResult:
    from vllm_grpc.v1 import completions_pb2_grpc

    stub = completions_pb2_grpc.CompletionsServiceStub(channel)
    req = _build_embed_grpc_request(seq_len, cell.hidden_size, rpc_index, base_seed)
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
    engine_cost: EngineCostSpan | None = (
        parse_grpc_trailing_metadata(md, "embed") if md is not None else None
    )
    # M6.1.1 (FR-011 audit-only): extract 4-checkpoint timing from the same
    # trailing metadata. Best-effort — None on pre-M6.1.1 servers.
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


async def _drive_rest_embed_m6_1(
    client: httpx.AsyncClient,
    base_url: str,
    auth: dict[str, str],
    cell: M6_1Cell,
    seq_len: int,
    rpc_index: int,
    base_seed: int,
    timeout_s: float,
) -> RPCResult:
    body = _build_embed_rest_payload_m6_1(seq_len, cell.hidden_size, rpc_index, base_seed)
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
    # M6.1.1 (FR-011 audit-only): same JSONResponse body carries m6_1_1_timings.
    from vllm_grpc_bench.m6_1_1_timing import extract_rest_timings, timing_checkpoint_to_payload

    m6_1_1_payload = timing_checkpoint_to_payload(
        extract_rest_timings(payload) if isinstance(payload, dict) else None
    )
    return RPCResult(
        success=True,
        wall_clock_ms=wall_ms,
        ttft_ms=None,
        engine_cost=engine_cost,
        failure_reason=None,
        m6_1_1_timing_payload=m6_1_1_payload,
    )


# --- Driver context manager --------------------------------------------------


def _open_grpc_channel(target: str, cfg: ChannelConfig) -> grpc.aio.Channel:
    return grpc.aio.insecure_channel(target, **_client_kwargs(cfg))


@asynccontextmanager
async def provide_m6_1_rpc_driver(
    endpoints: RESTGRPCEndpoints,
    *,
    seq_len: int,
    base_seed: int = 42,
    rtt_probe_n: int = _DEFAULT_RTT_PROBE_N,
    rpc_timeout_s: float = 90.0,
) -> AsyncIterator[tuple[RPCDriver, dict[M6_1CohortKind, RTTRecord]]]:
    """Open gRPC channels + httpx client; yield ``(driver, rtt_distribution)``.

    The driver maintains the shared ``rpc_index`` counter via the closure
    (per-cell allocation is done by the sweep orchestrator) — this context
    manager simply wires the channels and exposes a per-RPC dispatcher.
    """
    token = os.environ.get(endpoints.auth_token_env_var, "")
    if not token:
        raise RuntimeError(
            f"environment variable {endpoints.auth_token_env_var!r} is not "
            "set; the M6.1 RPC driver requires the bearer token to be "
            "readable at RPC dispatch time"
        )
    grpc_metadata: tuple[tuple[str, str], ...] = (("authorization", f"Bearer {token}"),)
    rest_auth = {"authorization": f"Bearer {token}"}

    if endpoints.rest_https_edge_url is None:
        raise RuntimeError(
            "M6.1 RPC driver requires endpoints.rest_https_edge_url; did the Modal deploy succeed?"
        )
    rest_base = endpoints.rest_https_edge_url

    default_channel = _open_grpc_channel(endpoints.grpc_url, M1_BASELINE)
    tuned_channel = _open_grpc_channel(endpoints.grpc_url, MAX_MSG_16MIB)
    rest_client = httpx.AsyncClient(
        http2=False,
        limits=httpx.Limits(max_keepalive_connections=8, max_connections=8),
    )
    try:
        rtt: dict[M6_1CohortKind, RTTRecord] = {
            "default_grpc": await measure_rtt(
                default_channel, n=rtt_probe_n, metadata=grpc_metadata
            ),
            "tuned_grpc_multiplexed": await measure_rtt(
                tuned_channel, n=rtt_probe_n, metadata=grpc_metadata
            ),
            "rest_https_edge": await _rest_rtt_probe(rest_client, rest_base, n=rtt_probe_n),
        }

        async def driver(cohort: M6_1CohortKind, cell: M6_1Cell, seed: int) -> RPCResult:
            rpc_index = _resolve_rpc_index(seed, base_seed)
            if cohort == "rest_https_edge":
                if cell.path == "embed":
                    return await _drive_rest_embed_m6_1(
                        rest_client,
                        rest_base,
                        rest_auth,
                        cell,
                        seq_len,
                        rpc_index,
                        base_seed,
                        rpc_timeout_s,
                    )
                return await _drive_rest_chat_stream(
                    rest_client, rest_base, rest_auth, seed, rpc_timeout_s
                )
            channel = default_channel if cohort == "default_grpc" else tuned_channel
            if cell.path == "embed":
                return await _drive_grpc_embed_m6_1(
                    channel,
                    cell,
                    seq_len,
                    rpc_index,
                    base_seed,
                    grpc_metadata,
                    rpc_timeout_s,
                )
            return await _drive_grpc_chat_stream(channel, seed, grpc_metadata, rpc_timeout_s)

        yield driver, rtt
    finally:
        with contextlib.suppress(Exception):
            await rest_client.aclose()
        with contextlib.suppress(Exception):
            await default_channel.close(grace=5.0)
        with contextlib.suppress(Exception):
            await tuned_channel.close(grace=5.0)


_ = (uuid, M6_1_CHAT_MAX_TOKENS, M6_1_PROMPT_EMBED_HIDDEN_SIZE)


# --- M6.1.2 driver: 4-cohort dispatch (US2 / FR-017) -------------------------


@asynccontextmanager
async def provide_m6_1_2_rpc_driver(
    endpoints: RESTGRPCEndpoints,
    *,
    seq_len: int,
    base_seed: int = 42,
    rtt_probe_n: int = _DEFAULT_RTT_PROBE_N,
    rpc_timeout_s: float = 90.0,
) -> AsyncIterator[
    tuple[
        Callable[[M6_1_2CohortKind, M6_1Cell, int], Awaitable[RPCResult]],
        dict[M6_1_2CohortKind, RTTRecord],
    ]
]:
    """M6.1.2 4-cohort driver — adds ``rest_plain_tcp`` to M6.1's 3 cohorts.

    Mirrors :func:`provide_m6_1_rpc_driver` (M6.1) but accepts the wider
    :data:`M6_1_2CohortKind` Literal and dispatches a 4th case for
    ``rest_plain_tcp`` (Story 2, restored from M5.2). The 3 inherited
    branches are byte-equivalent to the M6.1 driver's branches per FR-017.

    Both REST cohorts share a single ``httpx.AsyncClient`` — they only
    differ in the base URL passed to ``_drive_rest_embed_m6_1`` /
    ``_drive_rest_chat_stream``. The REST shim path (``rest_cohort.py`` +
    ``rest_shim.py``) handles the plain-TCP transport unchanged.
    """
    token = os.environ.get(endpoints.auth_token_env_var, "")
    if not token:
        raise RuntimeError(
            f"environment variable {endpoints.auth_token_env_var!r} is not "
            "set; the M6.1.2 RPC driver requires the bearer token to be "
            "readable at RPC dispatch time"
        )
    grpc_metadata: tuple[tuple[str, str], ...] = (("authorization", f"Bearer {token}"),)
    rest_auth = {"authorization": f"Bearer {token}"}

    if endpoints.rest_https_edge_url is None:
        raise RuntimeError(
            "M6.1.2 RPC driver requires endpoints.rest_https_edge_url; "
            "did the Modal deploy succeed?"
        )
    if endpoints.rest_plain_tcp_url is None:
        raise RuntimeError(
            "M6.1.2 RPC driver requires endpoints.rest_plain_tcp_url; "
            "the Modal deploy must be launched with with_rest_plain_tcp=True"
        )
    rest_https_edge_base = _normalize_rest_url_for_httpx(endpoints.rest_https_edge_url)
    # Modal publishes the plain-TCP tunnel as ``tcp+plaintext://host:port``
    # (raw ``modal.forward(unencrypted=True)`` form); httpx only speaks
    # HTTP/HTTPS, so rewrite the scheme to ``http://``. M5.2 documents
    # the same transform at m5_2_sweep.py:1280-1283.
    rest_plain_tcp_base = _normalize_rest_url_for_httpx(endpoints.rest_plain_tcp_url)

    # M6.1.2 reuses M6.1.1's M1_BASELINE / MAX_MSG_16MIB wire shapes
    # verbatim (FR-024 cell-by-cell comparability). A prior attempt to
    # add 60s client keepalive failed in live testing — Modal's gRPC
    # frontend rejected the pings with ENHANCE_YOUR_CALM GOAWAY. The
    # tunnel-idle defense is the cohort-iteration reorder in
    # cohorts_at_concurrency (gRPC FIRST within each cell), not keepalive.
    # See channel_config.py for the full discussion.
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

        async def driver(cohort: M6_1_2CohortKind, cell: M6_1Cell, seed: int) -> RPCResult:
            rpc_index = _resolve_rpc_index(seed, base_seed)
            if cohort in ("rest_https_edge", "rest_plain_tcp"):
                rest_base = (
                    rest_https_edge_base if cohort == "rest_https_edge" else rest_plain_tcp_base
                )
                if cell.path == "embed":
                    return await _drive_rest_embed_m6_1(
                        rest_client,
                        rest_base,
                        rest_auth,
                        cell,
                        seq_len,
                        rpc_index,
                        base_seed,
                        rpc_timeout_s,
                    )
                return await _drive_rest_chat_stream(
                    rest_client, rest_base, rest_auth, seed, rpc_timeout_s
                )
            channel = default_channel if cohort == "default_grpc" else tuned_channel
            if cell.path == "embed":
                return await _drive_grpc_embed_m6_1(
                    channel,
                    cell,
                    seq_len,
                    rpc_index,
                    base_seed,
                    grpc_metadata,
                    rpc_timeout_s,
                )
            return await _drive_grpc_chat_stream(channel, seed, grpc_metadata, rpc_timeout_s)

        yield driver, rtt
    finally:
        with contextlib.suppress(Exception):
            await rest_client.aclose()
        with contextlib.suppress(Exception):
            await default_channel.close(grace=5.0)
        with contextlib.suppress(Exception):
            await tuned_channel.close(grace=5.0)


# Type alias for the M6.1.2 driver callable. Mirrors :data:`RPCDriver` but
# accepts the wider :data:`M6_1_2CohortKind` Literal.
M6_1_2RPCDriver = Callable[[M6_1_2CohortKind, M6_1Cell, int], Awaitable[RPCResult]]
