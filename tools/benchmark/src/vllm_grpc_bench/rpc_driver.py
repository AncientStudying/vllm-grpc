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

This is the de-prefixed production RPC driver home (v0.0.1). It owns its
dispatchers (`_drive_*_m6_2`) and the request builders absorbed here from the
now-legacy chat/embed drivers (`_build_chat_grpc_request`,
`_build_chat_rest_payload`, `_build_embed_grpc_request`,
`_build_embed_rest_payload_m6_1`) plus the embed seed/tensor helpers
(`_build_torch_save_bytes`, `_build_torch_generator_for_rpc`, absorbed from the
legacy per-RPC seed module). The builders carry the four kwargs (`max_tokens`,
`ignore_eos`, `prompt`, `prompt_embeds_override`) as keyword-only; the
dispatchers thread the per-block values. Cost parsers come from the
de-prefixed `engine_cost` home; timing extraction from the `timing` home;
cohort/cell types from the `types` home.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import grpc
import httpx
from vllm_grpc.v1 import chat_pb2, completions_pb2

from vllm_grpc_bench.channel_config import (
    M1_BASELINE,
    MAX_MSG_16MIB,
    ChannelConfig,
    _client_kwargs,
)
from vllm_grpc_bench.engine_cost import (
    parse_grpc_trailing_metadata,
    parse_rest_response,
)
from vllm_grpc_bench.modal_endpoint import RESTGRPCEndpoints
from vllm_grpc_bench.prompts import DEFAULT_CHAT_MAX_TOKENS, build_chat_prompt
from vllm_grpc_bench.rtt_probe import measure_rtt
from vllm_grpc_bench.types import Cell, CohortKind, RPCResult, RTTRecord

__all__ = [
    "M6_2RPCDriver",
    "provide_m6_2_rpc_driver",
]


# --- Embed seed / tensor helpers (absorbed from the legacy embed driver) -----


def _build_torch_generator_for_rpc(
    rpc_index: int,
    base_seed: int = 42,
    device: str = "cpu",
) -> Any:
    """Build a ``torch.Generator`` seeded for the given measurement RPC.

    Two generators built for the same ``rpc_index`` produce bit-identical
    output sequences under ``torch.randn(...)`` (FR-028 / SC-006).
    """
    import torch  # local import — keeps non-embed callers torch-free

    if rpc_index < 0:
        raise ValueError(f"rpc_index must be >= 0, got {rpc_index}")
    g = torch.Generator(device=device)
    g.manual_seed(base_seed + rpc_index)
    return g


def _build_torch_save_bytes(
    seq_len: int,
    hidden_size: int,
    rpc_index: int,
    base_seed: int,
) -> bytes:
    """Build the ``torch.save`` bytes for one embed RPC (FR-002 / FR-028).

    Returns the raw ZIP-magic-prefixed bytes that ship in
    ``CompletionRequest.prompt_embeds`` (gRPC) OR get base64-wrapped for the
    REST shim.
    """
    import torch

    g = _build_torch_generator_for_rpc(rpc_index, base_seed=base_seed)
    tensor = torch.randn((seq_len, hidden_size), dtype=torch.float16, generator=g)
    buf = io.BytesIO()
    torch.save(tensor, buf)
    return buf.getvalue()


def _resolve_rpc_index(seed: int, base_seed: int) -> int:
    """Convert a per-RPC sampling seed into a non-negative ``rpc_index``.

    Measurement RPCs use ``seed = base_seed + rpc_index`` (FR-019), so
    ``seed - base_seed`` recovers the index. Smoke + warmup RPCs pass
    ``seed=0`` by convention, which would otherwise produce a negative index;
    clamping to 0 means those non-measurement paths share a single
    deterministic tensor.
    """
    return max(0, seed - base_seed)


def _normalize_rest_url_for_httpx(url: str) -> str:
    """Convert Modal's published REST URLs into an httpx-compatible scheme.

    Modal's ``modal.forward(unencrypted=True)`` publishes plain-TCP tunnels as
    ``tcp+plaintext://host:port``; httpx only accepts HTTP or HTTPS, so rewrite
    the scheme to ``http://`` (plain TCP without TLS *is* plain HTTP from the
    client's perspective). HTTPS edge URLs and bare ``host:port`` forms pass
    through unchanged or get an ``http://`` prefix respectively.
    """
    if url.startswith("tcp+plaintext://"):
        return "http://" + url[len("tcp+plaintext://") :]
    if url.startswith(("http://", "https://")):
        return url
    return "http://" + url


# --- Request builders (absorbed from the legacy chat/embed drivers) ----------


def _build_chat_grpc_request(
    seed: int,
    *,
    max_tokens: int = DEFAULT_CHAT_MAX_TOKENS,
    ignore_eos: bool = False,
    prompt: str | None = None,
) -> chat_pb2.ChatCompleteRequest:
    content = prompt if prompt is not None else build_chat_prompt(seed)
    return chat_pb2.ChatCompleteRequest(
        messages=[chat_pb2.ChatMessage(role="user", content=content)],
        model="mock-engine",
        max_tokens=max_tokens,
        seed=seed,
        ignore_eos=ignore_eos,
    )


def _build_chat_rest_payload(
    seed: int,
    *,
    max_tokens: int = DEFAULT_CHAT_MAX_TOKENS,
    ignore_eos: bool = False,
    prompt: str | None = None,
) -> dict[str, Any]:
    content = prompt if prompt is not None else build_chat_prompt(seed)
    payload: dict[str, Any] = {
        "model": "mock",
        "messages": [{"role": "user", "content": content}],
        "stream": True,
        "max_tokens": max_tokens,
        "temperature": 1.0,
        "seed": seed,
    }
    if ignore_eos:
        payload["ignore_eos"] = True
    return payload


def _build_embed_grpc_request(
    seq_len: int,
    hidden_size: int,
    rpc_index: int,
    base_seed: int,
    *,
    max_tokens: int = 10,
    ignore_eos: bool = False,
    prompt_embeds_override: bytes | None = None,
    seed: int | None = None,
) -> completions_pb2.CompletionRequest:
    """Build a gRPC embed request.

    The ``seed`` field is the ``SamplingParams.seed`` (FR-019). If omitted,
    defaults to ``base_seed + rpc_index``. ``max_tokens`` / ``ignore_eos`` /
    ``prompt_embeds_override`` are keyword-only so the default call sites stay
    byte-identical while the prompt-source resolver can pass corpus-derived
    tensors and forced-cap flags.
    """
    payload = (
        prompt_embeds_override
        if prompt_embeds_override is not None
        else _build_torch_save_bytes(seq_len, hidden_size, rpc_index, base_seed)
    )
    sampling_seed = seed if seed is not None else base_seed + rpc_index
    return completions_pb2.CompletionRequest(
        prompt_embeds=payload,
        max_tokens=max_tokens,
        seed=sampling_seed,
        ignore_eos=ignore_eos,
    )


def _build_embed_rest_payload_m6_1(
    seq_len: int,
    hidden_size: int,
    rpc_index: int,
    base_seed: int,
    *,
    max_tokens: int = 10,
    ignore_eos: bool = False,
    prompt_embeds_override: bytes | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Build the REST embed payload.

    Emits ``input_kind="prompt_embedding_torch_b64"`` and the base64-encoded
    ``torch.save`` bytes. Parameterized identically to the gRPC builder so the
    prompt-source resolver can route corpus tensors + forced caps through both
    transports.
    """
    raw = (
        prompt_embeds_override
        if prompt_embeds_override is not None
        else _build_torch_save_bytes(seq_len, hidden_size, rpc_index, base_seed)
    )
    encoded = base64.b64encode(raw).decode("ascii")
    sampling_seed = seed if seed is not None else base_seed + rpc_index
    body: dict[str, Any] = {
        "model": "mock",
        "input_kind": "prompt_embedding_torch_b64",
        "input": encoded,
        "hidden_size": hidden_size,
        "max_tokens": max_tokens,
        "seed": sampling_seed,
    }
    if ignore_eos:
        body["ignore_eos"] = True
    return body


async def _rest_rtt_probe(
    client: httpx.AsyncClient, base_url: str, n: int, timeout_s: float = 5.0
) -> RTTRecord:
    """``GET /healthz`` n times against the live REST URL."""
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


_DEFAULT_RTT_PROBE_N: int = 32


M6_2RPCDriver = Callable[
    [CohortKind, Cell, int],
    Awaitable[RPCResult],
]
"""Async per-RPC dispatcher with the M6.2 kwargs.

The concrete signature (see :func:`provide_m6_2_rpc_driver`) is::

    async def driver(
        cohort: CohortKind,
        cell: Cell,
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
    from vllm_grpc_bench.timing import extract_grpc_timings, timing_checkpoint_to_payload

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
    cell: Cell,
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
    from vllm_grpc_bench.timing import extract_grpc_timings, timing_checkpoint_to_payload

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
    """M6.2 chat_stream REST dispatcher — threads max_tokens / ignore_eos / prompt.

    Captures the terminal SSE ``data:`` payload and extracts ``engine_cost`` +
    ``m6_1_1_timings`` (mirrors :func:`m6_rpc_driver._drive_rest_chat_stream`)
    so the M6.2 per-segment aggregator can decompose REST cohorts the same way
    it decomposes gRPC.
    """
    body = _build_chat_rest_payload(
        seed,
        max_tokens=max_tokens,
        ignore_eos=ignore_eos,
        prompt=prompt,
    )
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
    engine_cost = None
    m6_1_1_payload: dict[str, int | str | None] | None = None
    if last_data_payload:
        try:
            terminal = json.loads(last_data_payload)
        except (ValueError, json.JSONDecodeError):
            terminal = None
        if isinstance(terminal, dict):
            engine_cost = parse_rest_response(terminal, "chat_stream")
            from vllm_grpc_bench.timing import (
                extract_rest_timings,
                timing_checkpoint_to_payload,
            )

            m6_1_1_payload = timing_checkpoint_to_payload(extract_rest_timings(terminal))
    return RPCResult(
        success=True,
        wall_clock_ms=wall_ms,
        ttft_ms=ttft_ms,
        engine_cost=engine_cost,
        failure_reason=None,
        m6_1_1_timing_payload=m6_1_1_payload,
    )


async def _drive_rest_embed_m6_2(
    client: httpx.AsyncClient,
    base_url: str,
    auth: dict[str, str],
    cell: Cell,
    seq_len: int,
    rpc_index: int,
    base_seed: int,
    timeout_s: float,
    *,
    max_tokens: int,
    ignore_eos: bool,
    prompt_embeds_override: bytes | None,
) -> RPCResult:
    """M6.2 embed REST dispatcher — threads max_tokens / ignore_eos / corpus embed bytes.

    Mirrors :func:`m6_1_rpc_driver._drive_rest_embed_m6_1` by parsing the
    JSON response body for ``engine_cost`` + ``m6_1_1_timings`` so the M6.2
    per-segment aggregator can decompose REST embed cohorts.
    """
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
    from vllm_grpc_bench.timing import extract_rest_timings, timing_checkpoint_to_payload

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
        dict[CohortKind, RTTRecord],
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
        rtt: dict[CohortKind, RTTRecord] = {
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
            cohort: CohortKind,
            cell: Cell,
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
