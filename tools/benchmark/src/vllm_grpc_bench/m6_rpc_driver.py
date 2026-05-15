"""M6 production RPC driver against live Modal endpoints.

Builds an :class:`RPCDriver` callable that the sweep orchestrator
:func:`m6_sweep.run_sweep` consumes. The driver routes each
``(cohort, cell, seed)`` to the right transport:

* ``rest_https_edge`` — httpx POST to the FastAPI shim on Modal's
  TLS-terminated, anycast-routed HTTPS edge.
* ``default_grpc`` — gRPC channel built with the M1-default channel
  config (no max_message_size override, etc.).
* ``tuned_grpc_multiplexed`` — gRPC channel built with the M3-tuned
  config (``MAX_MSG_16MIB``) so the protocol comparison holds the
  tuned-channel surface constant with M5.2's published baseline.

Engine cost extraction is path-discriminated per
``contracts/instrumentation.md``:
* gRPC cohorts read ``call.trailing_metadata()`` after the response.
* REST cohort parses the top-level ``engine_cost`` JSON for embed and
  the terminal SSE event's payload for chat_stream.

RTT probes are issued before yielding the driver (FR-010) — one
``RTTRecord`` per cohort, surfaced on ``M6Run.rtt_distribution``.

The module is an async context manager so the channels + httpx client
stay open for the entire sweep + tear down cleanly on exit / exception.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import grpc
import httpx
import numpy as np
from vllm_grpc.v1 import chat_pb2, chat_pb2_grpc, completions_pb2, completions_pb2_grpc

from vllm_grpc_bench.channel_config import M1_BASELINE, MAX_MSG_16MIB, ChannelConfig
from vllm_grpc_bench.m3_sweep import _client_kwargs
from vllm_grpc_bench.m3_types import RTTRecord
from vllm_grpc_bench.m6_engine_cost import (
    parse_grpc_trailing_metadata,
    parse_rest_response,
)
from vllm_grpc_bench.m6_sweep import RPCDriver, RPCResult
from vllm_grpc_bench.m6_types import (
    M6_CHAT_MAX_TOKENS,
    EngineCostSpan,
    M6Cell,
    M6CohortKind,
)
from vllm_grpc_bench.modal_endpoint import RESTGRPCEndpoints
from vllm_grpc_bench.rtt_probe import measure_rtt

_DEFAULT_RTT_PROBE_N: int = 32
_EMBED_SEQ_LEN: int = 16  # matches M3 / rest_cohort default — apples-to-apples


# --- Request builders --------------------------------------------------------


def _build_embed_grpc_request(hidden_size: int, seed: int) -> completions_pb2.CompletionRequest:
    """Build a gRPC embed request mirroring M5.1's prompt-embedding shape."""
    rng = np.random.default_rng(seed=seed)
    tensor = rng.standard_normal((_EMBED_SEQ_LEN, hidden_size), dtype=np.float32)
    return completions_pb2.CompletionRequest(
        prompt_embeds=tensor.tobytes(),
        max_tokens=10,
        seed=seed,
    )


def _build_embed_rest_payload(hidden_size: int, seed: int) -> dict[str, Any]:
    rng = np.random.default_rng(seed=seed)
    tensor = rng.standard_normal((_EMBED_SEQ_LEN, hidden_size), dtype=np.float32)
    encoded = base64.b64encode(tensor.tobytes()).decode("ascii")
    return {
        "model": "mock",
        "input_kind": "prompt_embedding_b64",
        "input": encoded,
        "hidden_size": hidden_size,
        "max_tokens": 10,
        "seed": seed,
    }


def _build_chat_prompt(seed: int) -> str:
    """Deterministic seed-dependent prompt so the engine output varies per RPC."""
    digest = hashlib.blake2b(str(seed).encode(), digest_size=8).hexdigest()
    return f"M6 chat probe seed={seed} digest={digest}. Please respond."


def _build_chat_grpc_request(seed: int) -> chat_pb2.ChatCompleteRequest:
    return chat_pb2.ChatCompleteRequest(
        messages=[chat_pb2.ChatMessage(role="user", content=_build_chat_prompt(seed))],
        model="mock-engine",
        max_tokens=M6_CHAT_MAX_TOKENS,  # FR-005
        seed=seed,
    )


def _build_chat_rest_payload(seed: int) -> dict[str, Any]:
    return {
        "model": "mock",
        "messages": [{"role": "user", "content": _build_chat_prompt(seed)}],
        "stream": True,
        "max_tokens": M6_CHAT_MAX_TOKENS,  # FR-005
        "temperature": 1.0,
        "seed": seed,
    }


# --- gRPC driver primitives --------------------------------------------------


async def _drive_grpc_embed(
    channel: grpc.aio.Channel,
    cell: M6Cell,
    seed: int,
    metadata: tuple[tuple[str, str], ...],
    timeout_s: float,
) -> RPCResult:
    stub = completions_pb2_grpc.CompletionsServiceStub(channel)
    req = _build_embed_grpc_request(cell.hidden_size, seed)
    t0 = time.perf_counter()
    # grpc.aio unary calls don't expose ``.with_call(...)`` (that's the
    # synchronous gRPC API). The aio pattern: invoke the stub directly to
    # get a ``UnaryUnaryCall``, await it for the response, then read
    # ``trailing_metadata()`` on the same call object.
    call = stub.Complete(req, timeout=timeout_s, metadata=metadata)
    try:
        _resp = await call
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
    return RPCResult(
        success=True,
        wall_clock_ms=wall_ms,
        ttft_ms=None,
        engine_cost=engine_cost,
        failure_reason=None,
    )


async def _drive_grpc_chat_stream(
    channel: grpc.aio.Channel,
    seed: int,
    metadata: tuple[tuple[str, str], ...],
    timeout_s: float,
) -> RPCResult:
    stub = chat_pb2_grpc.ChatServiceStub(channel)
    req = _build_chat_grpc_request(seed)
    t0 = time.perf_counter()
    first_chunk_at: float | None = None
    try:
        call = stub.CompleteStream(req, timeout=timeout_s, metadata=metadata)
        async for chunk in call:
            if chunk.delta_content and first_chunk_at is None:
                first_chunk_at = time.perf_counter()
    except grpc.RpcError as exc:  # noqa: PERF203
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
        md = await call.trailing_metadata()
    except Exception:  # noqa: BLE001
        md = None
    engine_cost: EngineCostSpan | None = (
        parse_grpc_trailing_metadata(md, "chat_stream") if md is not None else None
    )
    return RPCResult(
        success=True,
        wall_clock_ms=wall_ms,
        ttft_ms=ttft_ms,
        engine_cost=engine_cost,
        failure_reason=None,
    )


# --- REST driver primitives --------------------------------------------------


async def _drive_rest_embed(
    client: httpx.AsyncClient,
    base_url: str,
    auth: dict[str, str],
    cell: M6Cell,
    seed: int,
    timeout_s: float,
) -> RPCResult:
    body = _build_embed_rest_payload(cell.hidden_size, seed)
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


async def _drive_rest_chat_stream(
    client: httpx.AsyncClient,
    base_url: str,
    auth: dict[str, str],
    seed: int,
    timeout_s: float,
) -> RPCResult:
    body = _build_chat_rest_payload(seed)
    body_bytes = json.dumps(body).encode()
    t0 = time.perf_counter()
    first_chunk_at: float | None = None
    last_data_payload: str | None = None
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
                last_data_payload = line[len("data:") :].strip()
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
    engine_cost: EngineCostSpan | None = None
    if last_data_payload:
        try:
            terminal = json.loads(last_data_payload)
        except (ValueError, json.JSONDecodeError):
            terminal = None
        if isinstance(terminal, dict):
            engine_cost = parse_rest_response(terminal, "chat_stream")
    return RPCResult(
        success=True,
        wall_clock_ms=wall_ms,
        ttft_ms=ttft_ms,
        engine_cost=engine_cost,
        failure_reason=None,
    )


# --- Channel setup -----------------------------------------------------------


def _open_grpc_channel(target: str, cfg: ChannelConfig) -> grpc.aio.Channel:
    return grpc.aio.insecure_channel(target, **_client_kwargs(cfg))


async def _rest_rtt_probe(
    client: httpx.AsyncClient, base_url: str, n: int, timeout_s: float = 5.0
) -> RTTRecord:
    """``GET /healthz`` n times against the live HTTPS-edge URL."""
    samples_ms: list[float] = []
    for _ in range(n):
        start = time.perf_counter()
        resp = await client.get(f"{base_url}/healthz", timeout=timeout_s)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if resp.status_code != 200:
            raise RuntimeError(f"REST /healthz returned {resp.status_code}; body={resp.text!r}")
        samples_ms.append(elapsed_ms)
    sorted_samples = sorted(samples_ms)
    median = sorted_samples[len(sorted_samples) // 2]
    p95_idx = max(0, int(0.95 * (len(sorted_samples) - 1)))
    p95 = sorted_samples[p95_idx]
    return RTTRecord(
        n=len(samples_ms),
        median_ms=median,
        p95_ms=p95,
        samples_ms=tuple(samples_ms),
    )


# --- Async context manager ---------------------------------------------------


@asynccontextmanager
async def provide_m6_rpc_driver(
    endpoints: RESTGRPCEndpoints,
    *,
    rtt_probe_n: int = _DEFAULT_RTT_PROBE_N,
    rpc_timeout_s: float = 90.0,
) -> AsyncIterator[tuple[RPCDriver, dict[M6CohortKind, RTTRecord]]]:
    """Open gRPC channels + httpx client, probe RTT per cohort, yield
    ``(driver, rtt_distribution)``.

    The driver stays valid for the lifetime of the async context. On
    context exit (or exception) the channels + client are torn down
    cleanly so a sweep that aborts mid-run doesn't leak Modal
    connections.
    """
    token = os.environ.get(endpoints.auth_token_env_var, "")
    if not token:
        raise RuntimeError(
            f"environment variable {endpoints.auth_token_env_var!r} is not set; "
            "the M6 RPC driver requires the bearer token to be readable at "
            "RPC dispatch time"
        )
    grpc_metadata: tuple[tuple[str, str], ...] = (("authorization", f"Bearer {token}"),)
    rest_auth = {"authorization": f"Bearer {token}"}

    if endpoints.rest_https_edge_url is None:
        raise RuntimeError(
            "M6 RPC driver requires endpoints.rest_https_edge_url; did the Modal deploy succeed?"
        )
    rest_base = endpoints.rest_https_edge_url

    default_channel = _open_grpc_channel(endpoints.grpc_url, M1_BASELINE)
    tuned_channel = _open_grpc_channel(endpoints.grpc_url, MAX_MSG_16MIB)
    rest_client = httpx.AsyncClient(
        http2=False, limits=httpx.Limits(max_keepalive_connections=8, max_connections=8)
    )
    try:
        # T036: RTT probe per cohort before the sweep opens its measurement
        # window. FR-010 mandates per-cohort RTT capture.
        rtt: dict[M6CohortKind, RTTRecord] = {
            "default_grpc": await measure_rtt(
                default_channel, n=rtt_probe_n, metadata=grpc_metadata
            ),
            "tuned_grpc_multiplexed": await measure_rtt(
                tuned_channel, n=rtt_probe_n, metadata=grpc_metadata
            ),
            "rest_https_edge": await _rest_rtt_probe(rest_client, rest_base, n=rtt_probe_n),
        }

        async def driver(cohort: M6CohortKind, cell: M6Cell, seed: int) -> RPCResult:
            if cohort == "rest_https_edge":
                if cell.path == "embed":
                    return await _drive_rest_embed(
                        rest_client, rest_base, rest_auth, cell, seed, rpc_timeout_s
                    )
                return await _drive_rest_chat_stream(
                    rest_client, rest_base, rest_auth, seed, rpc_timeout_s
                )
            channel = default_channel if cohort == "default_grpc" else tuned_channel
            if cell.path == "embed":
                return await _drive_grpc_embed(channel, cell, seed, grpc_metadata, rpc_timeout_s)
            return await _drive_grpc_chat_stream(channel, seed, grpc_metadata, rpc_timeout_s)

        yield driver, rtt
    finally:
        with contextlib.suppress(Exception):
            await rest_client.aclose()
        with contextlib.suppress(Exception):
            await default_channel.close(grace=5.0)
        with contextlib.suppress(Exception):
            await tuned_channel.close(grace=5.0)


# Suppress unused-import linter complaint for uuid (kept for future
# request_id wiring without churn).
_ = uuid


__all__ = [
    "provide_m6_rpc_driver",
]
