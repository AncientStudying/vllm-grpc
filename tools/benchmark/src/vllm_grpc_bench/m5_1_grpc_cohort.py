"""M5.1 gRPC cohort runner — concurrency-aware multiplexed/channels dispatcher.

M5/M4's ``_measure_cell`` runs N RPCs serially on a single channel. M5.1
adds a concurrency dimension (c ∈ {1, 4, 8}) and two distinct gRPC
sub-cohort kinds:

* ``tuned_grpc_multiplexed`` — 1 channel, c concurrent RPCs at any moment
  (HTTP/2 streams multiplexed over a single TCP connection).
* ``tuned_grpc_channels`` — c independent channels, one serial RPC at a
  time per channel (symmetric with REST's connection-per-worker model).
* ``default_grpc`` — same as multiplexed but with the M1-default channel
  configuration (FR-007's "no multiplexed/channels split for default").
* ``tuned_grpc`` — degenerate c=1 case; collapses to single-channel
  single-RPC-at-a-time.

Per-request measurement:

* ``chat_stream``: TTFT = wall-clock from request-send to the first
  ``ChatStreamChunk`` arrival.
* ``embed``: wall-clock from request-send to ``CompletionResponse``
  receive.

Returns a list of ``Sample`` records (M3's shape) plus a derived TTFT
list for chat_stream cohorts. The caller aggregates these into a
``RunCohort`` with the M5.1 additive fields.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import grpc
from vllm_grpc.v1 import chat_pb2, chat_pb2_grpc, completions_pb2_grpc

from vllm_grpc_bench.channel_config import ChannelConfig
from vllm_grpc_bench.corpus import RequestSample
from vllm_grpc_bench.m3_sweep import (
    DEFAULT_CHAT_MAX_TOKENS,
    _build_chat_request,
    _build_embed_request,
    _classify_error,
    _client_kwargs,
    build_chat_prompt,
)
from vllm_grpc_bench.m3_types import GRPCSubCohortKind, Path_, RTTRecord, Sample
from vllm_grpc_bench.rtt_probe import measure_rtt


@dataclass(frozen=True)
class GRPCCohortResult:
    """Aggregate output of one M5.1 gRPC cohort run.

    ``warmup_samples`` (M5.2, FR-012a (g)): the per-request samples from the
    cohort's warmup pool. Aggregation ignores them; the M5.2 sidecar writer
    persists them with ``phase="warmup"`` for audit. Pre-M5.2 callers leave
    the field empty so M5.1's aggregation path is unchanged.
    """

    samples: tuple[Sample, ...]
    rtt_record: RTTRecord
    sub_cohort_kind: GRPCSubCohortKind
    channels_opened: int
    warmup_samples: tuple[Sample, ...] = ()


@asynccontextmanager
async def _open_channel(
    target: str,
    credentials: grpc.ChannelCredentials | None,
    channel_config: ChannelConfig,
) -> AsyncIterator[grpc.aio.Channel]:
    kwargs = _client_kwargs(channel_config)
    if credentials is None:
        async with grpc.aio.insecure_channel(target, **kwargs) as channel:
            yield channel
    else:
        async with grpc.aio.secure_channel(target, credentials, **kwargs) as channel:
            yield channel


async def _send_chat_rpc(
    channel: grpc.aio.Channel,
    *,
    iteration: int,
    prompt_seed: int,
    metadata: tuple[tuple[str, str], ...] | None,
    cell_id: str,
    timeout_s: float,
    max_tokens: int = DEFAULT_CHAT_MAX_TOKENS,
    sample: RequestSample | None = None,
) -> Sample:
    stub = chat_pb2_grpc.ChatServiceStub(channel)
    # M5.2 (FR-005c chat-corpus): when a corpus sample is provided, build
    # the request from the sample's messages + max_tokens + temperature +
    # seed. The fallback path (sample=None) uses the synthetic helper
    # ``build_chat_prompt`` for back-compat with pre-corpus tests.
    # ``prompt_seed`` is retained for back-compat but unused in both
    # paths (corpus path uses sample.seed; synthetic path is independent).
    _ = prompt_seed
    if sample is not None:
        req = chat_pb2.ChatCompleteRequest(
            messages=[
                chat_pb2.ChatMessage(role=m["role"], content=m["content"]) for m in sample.messages
            ],
            model="mock-engine",
            max_tokens=sample.max_tokens,
            temperature=sample.temperature,
            seed=sample.seed,
        )
    else:
        req = _build_chat_request(
            build_chat_prompt(iteration=iteration, cell_id=cell_id),
            max_tokens=max_tokens,
        )
    req_bytes = len(req.SerializeToString())
    t0 = time.perf_counter()
    arrival_times: list[float] = []
    response_bytes = 0
    tokens_emitted = 0
    error: str | None = None
    error_kind = None
    try:
        call = stub.CompleteStream(req, timeout=timeout_s, metadata=metadata)
        async for chunk in call:
            arrival_times.append(time.perf_counter())
            response_bytes += len(chunk.SerializeToString())
            if chunk.delta_content:
                tokens_emitted += 1
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        error_kind = _classify_error(exc)
    wall = time.perf_counter() - t0
    ttft = arrival_times[0] - t0 if arrival_times else None
    return Sample(
        cell_id=cell_id,
        iteration=iteration,
        request_wire_bytes=req_bytes,
        response_wire_bytes=response_bytes,
        wall_clock_seconds=wall,
        tokens_emitted=tokens_emitted if error is None else None,
        time_to_first_token_seconds=ttft,
        error=error,
        error_kind=error_kind,
    )


async def _send_embed_rpc(
    channel: grpc.aio.Channel,
    *,
    iteration: int,
    prompt_seed: int,
    hidden_size: int,
    metadata: tuple[tuple[str, str], ...] | None,
    cell_id: str,
    timeout_s: float,
) -> Sample:
    stub = completions_pb2_grpc.CompletionsServiceStub(channel)
    req = _build_embed_request(hidden_size, prompt_seed)
    req_bytes = len(req.SerializeToString())
    t0 = time.perf_counter()
    error: str | None = None
    error_kind = None
    response_bytes = 0
    try:
        resp = await stub.Complete(req, timeout=timeout_s, metadata=metadata)
        response_bytes = len(resp.SerializeToString())
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        error_kind = _classify_error(exc)
    wall = time.perf_counter() - t0
    return Sample(
        cell_id=cell_id,
        iteration=iteration,
        request_wire_bytes=req_bytes,
        response_wire_bytes=response_bytes,
        wall_clock_seconds=wall,
        error=error,
        error_kind=error_kind,
    )


async def run_grpc_cohort(
    *,
    path: Path_,
    target: str,
    credentials: grpc.ChannelCredentials | None,
    metadata: tuple[tuple[str, str], ...] | None,
    channel_config: ChannelConfig,
    sub_cohort_kind: GRPCSubCohortKind,
    concurrency: int,
    n: int,
    hidden_size: int,
    seed: int,
    timeout_s: float = 60.0,
    cell_id: str = "",
    rtt_probe_n: int = 32,
    warmup_n: int = 0,
    corpus: list[RequestSample] | None = None,
) -> GRPCCohortResult:
    """Drive ``n`` RPCs against the gRPC endpoint under the chosen sub-cohort kind.

    * ``tuned_grpc_multiplexed`` / ``default_grpc``: 1 channel; the worker
      pool dispatches ``concurrency`` concurrent RPCs at any moment until
      ``n`` complete.
    * ``tuned_grpc_channels``: ``concurrency`` channels; each channel runs
      its share of RPCs (≈ ``n / concurrency``) **serially** on its own
      channel — REST-symmetric.
    * ``tuned_grpc`` (c=1 degenerate): 1 channel, 1 RPC at a time.

    A pre-cohort RTT probe via the same channel(s) returns the RTTRecord.
    """
    if concurrency < 1:
        raise ValueError(f"run_grpc_cohort: concurrency must be >= 1 (got {concurrency})")
    if n < 1:
        raise ValueError(f"run_grpc_cohort: n must be >= 1 (got {n})")

    # Channel allocation by sub_cohort_kind.
    channels_needed = concurrency if sub_cohort_kind == "tuned_grpc_channels" else 1

    # Open channel(s) once for the entire cohort lifetime.
    async with _open_n_channels(target, credentials, channel_config, channels_needed) as channels:
        samples: list[Sample] = []

        async def _run_one(i: int, channel: grpc.aio.Channel) -> None:
            if path == "embed":
                sample = await _send_embed_rpc(
                    channel,
                    iteration=i,
                    prompt_seed=seed + i,
                    hidden_size=hidden_size,
                    metadata=metadata,
                    cell_id=cell_id,
                    timeout_s=timeout_s,
                )
            else:
                # M5.2 (FR-005c chat-corpus): pull the corpus sample by
                # iteration index so REST and gRPC see the same prompt
                # for the same i. Falls back to the synthetic helper
                # when no corpus is provided (back-compat tests).
                corpus_sample = corpus[i % len(corpus)] if corpus is not None else None
                sample = await _send_chat_rpc(
                    channel,
                    iteration=i,
                    prompt_seed=seed + i,
                    metadata=metadata,
                    cell_id=cell_id,
                    timeout_s=timeout_s,
                    sample=corpus_sample,
                )
            samples.append(sample)

        async def _drive_measurement(count: int, *, into_samples: bool) -> None:
            """Run ``count`` RPCs under the cohort's sub_cohort_kind dispatch
            pattern. If ``into_samples`` is False, samples are still appended
            via _run_one but the caller discards them afterward.
            """
            if sub_cohort_kind == "tuned_grpc_channels":
                # c channels, each runs its share of RPCs serially.
                chunks = _split_indices(count, concurrency)

                async def _channel_worker(channel_idx: int) -> None:
                    channel = channels[channel_idx]
                    for i in chunks[channel_idx]:
                        await _run_one(i, channel)

                await asyncio.gather(*(_channel_worker(i) for i in range(concurrency)))
            else:
                # multiplexed / default_grpc / tuned_grpc (c=1): single channel
                # with concurrency-wide concurrent dispatch.
                channel = channels[0]
                queue: asyncio.Queue[int] = asyncio.Queue()
                for i in range(count):
                    queue.put_nowait(i)

                async def _worker() -> None:
                    while True:
                        try:
                            i = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            return
                        try:
                            await _run_one(i, channel)
                        finally:
                            queue.task_done()

                await asyncio.gather(*(_worker() for _ in range(concurrency)))

        # Warmup phase. Pays the cold-channel HTTP/2 handshake cost on
        # RPC #1 (and on each of c channels in channels-mode) so the
        # measurement window starts on warm connections. M5.2
        # (FR-012a (g)): warmup samples are snapshotted before the
        # measurement window opens and persisted to the events sidecar
        # with phase="warmup" for audit. They never reach the cohort
        # record's aggregates.
        warmup_snapshot: tuple[Sample, ...] = ()
        if warmup_n > 0:
            await _drive_measurement(warmup_n, into_samples=False)
            warmup_snapshot = tuple(samples)
            samples.clear()
        # RTT probe goes AFTER warmup so the probe channel is warm.
        rtt = await measure_rtt(channels[0], n=rtt_probe_n, metadata=metadata)
        # Measurement phase — samples reach the aggregator.
        await _drive_measurement(n, into_samples=True)

    return GRPCCohortResult(
        samples=tuple(samples),
        rtt_record=rtt,
        sub_cohort_kind=sub_cohort_kind,
        channels_opened=channels_needed,
        warmup_samples=warmup_snapshot,
    )


def _split_indices(n: int, c: int) -> list[list[int]]:
    """Split [0, n) into c roughly equal contiguous chunks."""
    base, rem = divmod(n, c)
    chunks: list[list[int]] = []
    start = 0
    for i in range(c):
        size = base + (1 if i < rem else 0)
        chunks.append(list(range(start, start + size)))
        start += size
    return chunks


@asynccontextmanager
async def _open_n_channels(
    target: str,
    credentials: grpc.ChannelCredentials | None,
    channel_config: ChannelConfig,
    n: int,
) -> AsyncIterator[list[grpc.aio.Channel]]:
    """Async context yielding a list of n open gRPC channels.

    Channels are opened in parallel for faster setup. All channels are
    closed (gracefully) on context exit.
    """
    kwargs = _client_kwargs(channel_config)
    factories: list[Any] = []
    for _ in range(n):
        if credentials is None:
            factories.append(grpc.aio.insecure_channel(target, **kwargs))
        else:
            factories.append(grpc.aio.secure_channel(target, credentials, **kwargs))
    # Each grpc.aio.insecure_channel returns an async context manager already.
    # Open them sequentially (channel construction is cheap; the costly bit
    # is the first RPC's HTTP/2 negotiation, which happens lazily anyway).
    channels: list[grpc.aio.Channel] = []
    try:
        for f in factories:
            ch = await f.__aenter__()
            channels.append(ch)
        yield channels
    finally:
        for ch in channels:
            with contextlib.suppress(Exception):
                await ch.close(grace=2.0)
