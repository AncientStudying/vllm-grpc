"""Cartesian-product sweep orchestrator for the M3 channel-tuning benchmark.

The orchestrator builds a list of ``BenchmarkCell``s from
``axis × width × path × candidate-config``, brings up an in-process gRPC
server backed by ``MockEngine`` for each cell, drives ``iterations`` RPCs,
and aggregates results into ``RunCohort`` and ``Recommendation`` objects.

Why M3-specific servicers (not the real ``ChatServicer`` / ``CompletionsServicer``)?
The real servicers depend on ``vllm`` and ``torch`` for ``proto_to_sampling_params``
and ``decode_embeds`` respectively — heavy deps that aren't part of the bench
package's dependency closure (vllm only ships on Linux; vllm-metal is in the
``investigation`` group, not synced by default). The M3 sweep measures
*channel* behaviour, not servicer translation behaviour, so we wire
``MockEngine`` directly to thin servicers in this module. ``T016`` separately
proves the real-servicer drop-in claim under ``packages/frontend/tests/``
where ``vllm`` is mocked via the conftest.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import statistics
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import grpc
import numpy as np
from vllm_grpc.v1 import (
    chat_pb2,
    chat_pb2_grpc,
    completions_pb2,
    completions_pb2_grpc,
)

from vllm_grpc_bench.channel_config import (
    M1_BASELINE,
    Axis,
    ChannelConfig,
    presets_for_axis,
)
from vllm_grpc_bench.ci import estimate, is_winner
from vllm_grpc_bench.m3_types import (
    BenchmarkCell,
    CorpusSubset,
    ErrorKind,
    Path_,
    Recommendation,
    RunCohort,
    Sample,
    WinningMetric,
)
from vllm_grpc_bench.mock_engine import MockEngine, MockEngineConfig

# ---------------------------------------------------------------------------
# Citations (FR-007). Static per axis; resolved via M2 ground-truth workflow.
# ---------------------------------------------------------------------------

CITATIONS: dict[Axis, str] = {
    "max_message_size": (
        "~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py "
        "(channel-args plumbing); "
        "~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults)"
    ),
    "keepalive": (
        "~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/"
        "chttp2_transport.cc (keepalive timer logic)"
    ),
    "compression": (
        "~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py "
        "(compression argument); "
        "~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/"
        "frame_data.cc (frame-level compression handling)"
    ),
    "http2_framing": (
        "~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/"
        "flow_control.cc (chttp2 stream/transport flow-control state); "
        "~/.graphify/repos/grpc/grpc/src/core/lib/transport/"
        "bdp_estimator.cc (BDP probe state machine)"
    ),
    "schema": (
        "~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_runtime_protos.py "
        "(serialization path); protobuf language guide §scalar packed encoding"
    ),
    "baseline": "n/a (baseline reference)",
}


# ---------------------------------------------------------------------------
# M3-specific thin servicers that wrap MockEngine without vllm/torch deps
# ---------------------------------------------------------------------------


class M3ChatServicer(chat_pb2_grpc.ChatServiceServicer):  # type: ignore[misc]
    def __init__(self, engine: MockEngine) -> None:
        self._engine = engine

    async def Complete(  # noqa: N802 — matches generated stub
        self,
        request: chat_pb2.ChatCompleteRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> chat_pb2.ChatCompleteResponse:
        prompt = _request_prompt_text(request)
        params = SimpleNamespace(max_tokens=int(request.max_tokens or 64))
        request_id = str(uuid.uuid4())
        final = None
        async for output in self._engine.generate(prompt, params, request_id=request_id):
            final = output
        assert final is not None
        comp = final.outputs[0]
        return chat_pb2.ChatCompleteResponse(
            message=chat_pb2.ChatMessage(role="assistant", content=comp.text),
            finish_reason=comp.finish_reason or "stop",
            prompt_tokens=len(final.prompt_token_ids),
            completion_tokens=len(comp.token_ids),
        )

    async def CompleteStream(  # noqa: N802
        self,
        request: chat_pb2.ChatCompleteRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> AsyncIterator[chat_pb2.ChatStreamChunk]:
        prompt = _request_prompt_text(request)
        params = SimpleNamespace(max_tokens=int(request.max_tokens or 64))
        request_id = str(uuid.uuid4())
        prev = ""
        idx = 0
        async for output in self._engine.generate(prompt, params, request_id=request_id):
            comp = output.outputs[0]
            delta = comp.text[len(prev) :]
            prev = comp.text
            if delta:
                yield chat_pb2.ChatStreamChunk(
                    delta_content=delta, finish_reason="", token_index=idx
                )
                idx += 1
            if comp.finish_reason:
                yield chat_pb2.ChatStreamChunk(
                    delta_content="",
                    finish_reason=comp.finish_reason or "stop",
                    token_index=idx,
                )
                return


class M3CompletionsServicer(completions_pb2_grpc.CompletionsServiceServicer):  # type: ignore[misc]
    def __init__(self, engine: MockEngine) -> None:
        self._engine = engine

    async def Complete(  # noqa: N802
        self,
        request: completions_pb2.CompletionRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> completions_pb2.CompletionResponse:
        prompt = _completion_prompt(request)
        params = SimpleNamespace(max_tokens=int(request.max_tokens or 10))
        request_id = str(uuid.uuid4())
        final = None
        async for output in self._engine.generate(prompt, params, request_id=request_id):
            final = output
        assert final is not None
        comp = final.outputs[0]
        return completions_pb2.CompletionResponse(
            generated_text=comp.text,
            finish_reason=comp.finish_reason or "stop",
            prompt_tokens=len(final.prompt_token_ids),
            completion_tokens=len(comp.token_ids),
        )


def _request_prompt_text(request: chat_pb2.ChatCompleteRequest) -> str:
    parts = [m.content for m in request.messages if m.content]
    return "\n".join(parts) if parts else "default"


def _completion_prompt(request: completions_pb2.CompletionRequest) -> str:
    which = request.WhichOneof("input")
    if which == "prompt_embeds":
        digest = hashlib.blake2b(request.prompt_embeds, digest_size=8).hexdigest()
        return f"embeds:{digest}"
    return request.prompt or "default"


# ---------------------------------------------------------------------------
# Server bring-up
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def serve_in_process(
    engine: MockEngine,
    cfg: ChannelConfig,
) -> AsyncIterator[str]:
    """Start a gRPC server with M3-specific servicers; yield ``host:port``."""
    server_kwargs: dict[str, Any] = {}
    if cfg.server_options:
        server_kwargs["options"] = list(cfg.server_options)
    if cfg.compression is not grpc.Compression.NoCompression:
        server_kwargs["compression"] = cfg.compression
    server = grpc.aio.server(**server_kwargs)
    chat_pb2_grpc.add_ChatServiceServicer_to_server(M3ChatServicer(engine), server)
    completions_pb2_grpc.add_CompletionsServiceServicer_to_server(
        M3CompletionsServicer(engine), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        yield f"127.0.0.1:{port}"
    finally:
        await server.stop(grace=0.5)


@contextlib.asynccontextmanager
async def serve_in_process_adapter(
    engine: MockEngine,
    channel_config: ChannelConfig,
) -> AsyncIterator[tuple[str, grpc.ChannelCredentials | None, tuple[tuple[str, str], ...] | None]]:
    """``EndpointProvider``-conforming wrapper around :func:`serve_in_process`.

    Yields an ``(addr, credentials, metadata)`` tuple where ``credentials`` and
    ``metadata`` are ``None`` (insecure local channel, no per-RPC auth). The M4
    sweep uses this as its default ``endpoint_provider`` so M4 reproductions
    remain bit-identical: same in-process server bring-up, same host/port shape,
    same lifecycle. M5 swaps in ``modal_endpoint.provide_endpoint`` instead,
    which yields a Modal-tunnel target with TLS credentials and a bearer-token
    metadata pair.
    """
    async with serve_in_process(engine, channel_config) as addr:
        yield (addr, None, None)


def _client_kwargs(cfg: ChannelConfig) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if cfg.client_options:
        kwargs["options"] = list(cfg.client_options)
    if cfg.compression is not grpc.Compression.NoCompression:
        kwargs["compression"] = cfg.compression
    return kwargs


# ---------------------------------------------------------------------------
# Per-cell drivers
# ---------------------------------------------------------------------------


def _classify_error(exc: BaseException) -> ErrorKind:
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    code = getattr(exc, "code", None)
    if callable(code):
        try:
            status = code()
        except Exception:
            status = None
        if status is grpc.StatusCode.RESOURCE_EXHAUSTED:
            return "max_msg_exceeded"
        if status is grpc.StatusCode.DEADLINE_EXCEEDED:
            return "timeout"
        if status is grpc.StatusCode.ABORTED:
            return "rpc_aborted"
    return "other"


def _build_embed_request(
    hidden_size: int, seed: int, seq_len: int = 16
) -> completions_pb2.CompletionRequest:
    rng = np.random.default_rng(seed ^ hidden_size ^ seq_len)
    arr = rng.standard_normal((seq_len, hidden_size), dtype=np.float32)
    return completions_pb2.CompletionRequest(
        model="mock-engine",
        max_tokens=10,
        prompt_embeds=arr.tobytes(),
    )


def _build_chat_request(prompt_text: str, max_tokens: int = 64) -> chat_pb2.ChatCompleteRequest:
    return chat_pb2.ChatCompleteRequest(
        messages=[chat_pb2.ChatMessage(role="user", content=prompt_text)],
        model="mock-engine",
        max_tokens=max_tokens,
    )


async def _drive_embed_cell(
    addr: str,
    cell: BenchmarkCell,
    seed: int,
    *,
    credentials: grpc.ChannelCredentials | None = None,
    metadata: tuple[tuple[str, str], ...] | None = None,
) -> list[Sample]:
    samples: list[Sample] = []
    kwargs = _client_kwargs(cell.channel_config)
    channel_ctx = (
        grpc.aio.insecure_channel(addr, **kwargs)
        if credentials is None
        else grpc.aio.secure_channel(addr, credentials, **kwargs)
    )
    async with channel_ctx as channel:
        stub = completions_pb2_grpc.CompletionsServiceStub(channel)
        for i in range(cell.iterations):
            req = _build_embed_request(cell.hidden_size, seed + i)
            req_bytes = len(req.SerializeToString())
            t0 = time.perf_counter()
            try:
                resp: completions_pb2.CompletionResponse = await stub.Complete(
                    req, timeout=60.0, metadata=metadata
                )
            except Exception as exc:  # noqa: BLE001 — record-and-continue at boundary
                samples.append(
                    Sample(
                        cell_id=cell.cell_id,
                        iteration=i,
                        request_wire_bytes=req_bytes,
                        response_wire_bytes=0,
                        wall_clock_seconds=time.perf_counter() - t0,
                        off_canonical=cell.off_canonical,
                        error=str(exc),
                        error_kind=_classify_error(exc),
                    )
                )
                continue
            wall = time.perf_counter() - t0
            samples.append(
                Sample(
                    cell_id=cell.cell_id,
                    iteration=i,
                    request_wire_bytes=req_bytes,
                    response_wire_bytes=len(resp.SerializeToString()),
                    wall_clock_seconds=wall,
                    off_canonical=cell.off_canonical,
                )
            )
    return samples


async def _drive_chat_stream_cell(
    addr: str,
    cell: BenchmarkCell,
    seed: int,
    long_stream: bool,
    *,
    credentials: grpc.ChannelCredentials | None = None,
    metadata: tuple[tuple[str, str], ...] | None = None,
) -> list[Sample]:
    samples: list[Sample] = []
    kwargs = _client_kwargs(cell.channel_config)
    if long_stream:
        prompt_text = (
            "Generate a long technical explanation of gRPC channel options. "
            "min_tokens=1024 deterministic_seed=m3"
        )
        max_tokens = 1024
    else:
        prompt_text = "Explain gRPC channel options briefly."
        max_tokens = 32
    channel_ctx = (
        grpc.aio.insecure_channel(addr, **kwargs)
        if credentials is None
        else grpc.aio.secure_channel(addr, credentials, **kwargs)
    )
    async with channel_ctx as channel:
        stub = chat_pb2_grpc.ChatServiceStub(channel)
        for i in range(cell.iterations):
            req = _build_chat_request(f"{prompt_text} iter={seed + i}", max_tokens=max_tokens)
            req_bytes = len(req.SerializeToString())
            t0 = time.perf_counter()
            arrival_times: list[float] = []
            response_bytes = 0
            tokens_emitted = 0
            error: str | None = None
            error_kind: ErrorKind | None = None
            try:
                call = stub.CompleteStream(req, timeout=120.0, metadata=metadata)
                async for chunk in call:
                    arrival_times.append(time.perf_counter())
                    response_bytes += len(chunk.SerializeToString())
                    if chunk.delta_content:
                        tokens_emitted += 1
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                error_kind = _classify_error(exc)
            wall = time.perf_counter() - t0
            ttft: float | None = None
            mean_inter: float | None = None
            stddev_inter: float | None = None
            if arrival_times:
                ttft = arrival_times[0] - t0
                if len(arrival_times) >= 2:
                    inter = [
                        arrival_times[k] - arrival_times[k - 1]
                        for k in range(1, len(arrival_times))
                    ]
                    mean_inter = statistics.fmean(inter)
                    stddev_inter = statistics.stdev(inter) if len(inter) >= 2 else 0.0
            samples.append(
                Sample(
                    cell_id=cell.cell_id,
                    iteration=i,
                    request_wire_bytes=req_bytes,
                    response_wire_bytes=response_bytes,
                    wall_clock_seconds=wall,
                    tokens_emitted=tokens_emitted if error is None else None,
                    time_to_first_token_seconds=ttft,
                    mean_inter_token_seconds=mean_inter,
                    inter_token_seconds_stddev=stddev_inter,
                    off_canonical=cell.off_canonical,
                    error=error,
                    error_kind=error_kind,
                )
            )
    return samples


async def run_cell(cell: BenchmarkCell, *, seed: int) -> RunCohort:
    """Execute one cell end-to-end and return its aggregated cohort."""
    # For long-streams we need the mock to produce >= 1024 tokens, so bump
    # max_tokens_per_stream accordingly.
    long_stream = cell.corpus_subset == "m3_long_stream"
    max_tokens_per_stream = 2048 if long_stream else 64
    # Faster pacing for non-long-stream cells so the smoke run finishes quickly.
    tps = 20.0 if long_stream else 200.0
    engine_cfg = MockEngineConfig(
        hidden_size=cell.hidden_size,
        seed=seed,
        tokens_per_second=tps,
        max_tokens_per_stream=max_tokens_per_stream,
    )
    engine = MockEngine(engine_cfg)
    async with serve_in_process(engine, cell.channel_config) as addr:
        if cell.path == "embed":
            samples = await _drive_embed_cell(addr, cell, seed)
        else:
            samples = await _drive_chat_stream_cell(addr, cell, seed, long_stream=long_stream)
    return _aggregate(cell, samples)


def _aggregate(cell: BenchmarkCell, samples: list[Sample]) -> RunCohort:
    successful = [s for s in samples if s.error is None]
    error_budget = max(5, cell.iterations - 10)
    measurable = len(successful) >= max(10, cell.iterations - error_budget)
    if not successful:
        return RunCohort(
            cell=cell,
            samples=tuple(samples),
            n_successful=0,
            bytes_mean=0.0,
            bytes_ci_low=0.0,
            bytes_ci_high=0.0,
            time_mean=0.0,
            time_ci_low=0.0,
            time_ci_high=0.0,
            measurable=False,
        )
    bytes_samples = [float(s.response_wire_bytes + s.request_wire_bytes) for s in successful]
    time_samples = [s.wall_clock_seconds for s in successful]
    time_cv = _coefficient_of_variation(time_samples)
    # ci.estimate() refuses n<10 for SC-003 rigor; pilots and other low-n runs
    # report mean-only with degenerate CIs and measurable=False so the
    # recommendation builder downgrades them to "not_measurable" cleanly.
    if len(successful) < 10:
        bm = sum(bytes_samples) / len(bytes_samples)
        tm = sum(time_samples) / len(time_samples)
        return RunCohort(
            cell=cell,
            samples=tuple(samples),
            n_successful=len(successful),
            bytes_mean=bm,
            bytes_ci_low=bm,
            bytes_ci_high=bm,
            time_mean=tm,
            time_ci_low=tm,
            time_ci_high=tm,
            measurable=False,
            time_cv=time_cv,
        )
    bytes_est = estimate(bytes_samples)
    time_est = estimate(time_samples)
    return RunCohort(
        cell=cell,
        samples=tuple(samples),
        n_successful=len(successful),
        bytes_mean=bytes_est.mean,
        bytes_ci_low=bytes_est.ci_low,
        bytes_ci_high=bytes_est.ci_high,
        time_mean=time_est.mean,
        time_ci_low=time_est.ci_low,
        time_ci_high=time_est.ci_high,
        measurable=measurable,
        time_cv=time_cv,
    )


def _coefficient_of_variation(values: list[float]) -> float | None:
    """Within-cohort CV (stddev/mean). Returns None if undefined.

    FR-005 recording helper. Used by both M3 and M4 cohorts so the per-cohort
    CV field is always populated when there's enough signal to compute it.
    """
    import statistics

    if len(values) < 2:
        return None
    mean = statistics.fmean(values)
    if mean <= 0:
        return None
    return statistics.stdev(values) / mean


# ---------------------------------------------------------------------------
# Sweep planning + Recommendation builder
# ---------------------------------------------------------------------------


def _corpus_for_path(path: Path_, long_stream: bool) -> CorpusSubset:
    if path == "embed":
        return "m1_embed"
    return "m3_long_stream" if long_stream else "m1_chat"


LONG_STREAM_WIDTH: int = 4096
"""Canonical mid-point width at which the long-stream cohort is evaluated.

Long-stream coverage is restricted to one width because keepalive ping
intervals and HTTP/2 BDP-probe behaviour are timing-dominated, not
payload-size-dominated — per-width × per-config long-stream cells would
multiply wall time (~52s/iter at n=30 → 26 min/cell) without adding signal.
The published M3 report records this scope decision in its methodology note.
"""


def plan_cells(
    *,
    axes: tuple[Axis, ...],
    widths: tuple[int, ...],
    paths: tuple[Path_, ...],
    iterations: int,
    include_long_stream: bool = True,
) -> list[BenchmarkCell]:
    """Build the cartesian product of cells for the given dimensions.

    Long-stream chat cohorts are added only on the keepalive and http2_framing
    axes and only at ``LONG_STREAM_WIDTH`` (the canonical mid-point). See the
    constant's docstring for the rationale.
    """
    cells: list[BenchmarkCell] = []
    for axis in axes:
        for cfg in presets_for_axis(axis):
            for w in widths:
                for path in paths:
                    long_streams = (
                        (False, True)
                        if (
                            path == "chat_stream"
                            and include_long_stream
                            and axis in {"keepalive", "http2_framing"}
                            and w == LONG_STREAM_WIDTH
                        )
                        else (False,)
                    )
                    for ls in long_streams:
                        cells.append(
                            BenchmarkCell(
                                path=path,
                                hidden_size=w,
                                channel_config=cfg,
                                corpus_subset=_corpus_for_path(path, ls),
                                iterations=iterations,
                            )
                        )
    return cells


def build_recommendations(
    cohorts: list[RunCohort],
    *,
    axis: Axis,
    metric: str = "bytes",
) -> list[Recommendation]:
    """Compare each candidate cohort against the M1_BASELINE cohort within the axis.

    Dispatches by ``metric``:

    - ``"bytes"`` (PR #17 / SC-003 bytes path): groups by ``(path, hidden_size)``;
      pairs each candidate with the *first* M1_BASELINE in that group. Robust
      because the bytes metric exhibits ~0.01% cross-batch drift on this harness.
    - ``"time"`` / ``"ttft"`` (Phase A / US3 / SC-006): groups by
      ``(path, hidden_size, corpus_subset)`` so the long-stream cohort gets its
      own verdict; pairs each candidate with the **immediate-predecessor**
      M1_BASELINE in cohort run-order (per ``research.md`` R-12). For
      ``metric="ttft"``, only chat_stream cells are emitted (TTFT is undefined
      off the streaming path); per-cohort TTFT mean+CI is computed from
      ``samples[i].time_to_first_token_seconds``. Emits a ``noise_bounded``
      verdict (per ``spec.md`` FR-005) when the predecessor pairing claims a win
      but at least one alternative same-cell M1_BASELINE would NOT — the
      conclusion is unstable across baselines and re-measures under M4.
    """
    if metric not in ("bytes", "time", "ttft"):
        raise ValueError(f"metric must be 'bytes', 'time', or 'ttft', got {metric!r}")
    if metric == "bytes":
        return _build_recommendations_bytes(cohorts, axis=axis)
    return _build_recommendations_time_axis(cohorts, axis=axis, metric=metric)


def _build_recommendations_bytes(cohorts: list[RunCohort], *, axis: Axis) -> list[Recommendation]:
    """SC-003 bytes-axis recommendation builder (PR #17 path, preserved verbatim)."""
    recs: list[Recommendation] = []
    citation = CITATIONS[axis]

    by_path_width: dict[tuple[Path_, int], list[RunCohort]] = {}
    for c in cohorts:
        if c.cell.channel_config.axis not in (axis, "baseline"):
            continue
        key = (c.cell.path, c.cell.hidden_size)
        by_path_width.setdefault(key, []).append(c)

    for (path, width), group in sorted(by_path_width.items()):
        baseline = next(
            (c for c in group if c.cell.channel_config.name == M1_BASELINE.name),
            None,
        )
        if baseline is None or not baseline.measurable:
            recs.append(
                Recommendation(
                    axis=axis,
                    applies_to_path=path,
                    applies_to_widths=frozenset({width}),
                    verdict="not_measurable",
                    baseline_ci_upper=0.0,
                    citation=citation,
                    notes=(
                        "baseline cohort missing or unmeasurable"
                        if baseline is None
                        else f"baseline n_successful={baseline.n_successful}"
                    ),
                )
            )
            continue

        base_mean = baseline.bytes_mean
        base_low = baseline.bytes_ci_low
        base_high = baseline.bytes_ci_high

        candidates = [c for c in group if c.cell.channel_config.name != M1_BASELINE.name]
        if not candidates:
            recs.append(
                Recommendation(
                    axis=axis,
                    applies_to_path=path,
                    applies_to_widths=frozenset({width}),
                    verdict="no_winner",
                    baseline_ci_upper=base_high,
                    citation=citation,
                    notes="no candidates evaluated for this axis/path/width",
                )
            )
            continue

        # SC-003 rule for *minimizing* metrics (bytes, smaller is better):
        # candidate WINS iff candidate_ci_high < baseline_ci_low. We reuse
        # ``ci.is_winner`` (maximizing-metric framing) by negating both inputs.
        # The dataclass invariant ``candidate_ci_lower > baseline_ci_upper`` is
        # satisfied by storing the negated CIs.
        winner: RunCohort | None = None
        for cand in candidates:
            if not cand.measurable:
                continue
            cand_high = cand.bytes_ci_high
            if is_winner(baseline_ci_high=-base_low, candidate_ci_low=-cand_high):
                cand_mean = cand.bytes_mean
                if winner is None:
                    winner = cand
                else:
                    if cand_mean < winner.bytes_mean:
                        winner = cand

        if winner is None:
            recs.append(
                Recommendation(
                    axis=axis,
                    applies_to_path=path,
                    applies_to_widths=frozenset({width}),
                    verdict="no_winner",
                    baseline_ci_upper=base_high,
                    citation=citation,
                    notes=(
                        f"no candidate cleared the SC-003 threshold "
                        f"(baseline_ci_low={base_low:.4g}); "
                        + "; ".join(
                            f"{c.cell.channel_config.name}: mean={c.bytes_mean:.4g}, "
                            f"ci_high={c.bytes_ci_high:.4g}"
                            for c in candidates
                        )
                    ),
                )
            )
            continue

        win_mean = winner.bytes_mean
        win_high = winner.bytes_ci_high
        delta_pct = ((win_mean - base_mean) / base_mean * 100.0) if base_mean else 0.0
        recs.append(
            Recommendation(
                axis=axis,
                applies_to_path=path,
                applies_to_widths=frozenset({width}),
                verdict="recommend",
                winning_config=winner.cell.channel_config,
                winning_delta_pct=delta_pct,
                winning_metric="bytes",
                baseline_ci_upper=-base_low,
                candidate_ci_lower=-win_high,
                citation=citation,
                notes=(
                    f"baseline_mean={base_mean:.4g}, candidate_mean={win_mean:.4g}, "
                    f"baseline_ci=[{base_low:.4g},{base_high:.4g}], "
                    f"candidate_ci_high={win_high:.4g}"
                ),
            )
        )

    return recs


def _ttft_estimate_for_cohort(cohort: RunCohort) -> tuple[float, float, float, int] | None:
    """Delegate to ``vllm_grpc_bench.ttft.ttft_estimate`` (R-10 shared math)."""
    from vllm_grpc_bench.ttft import ttft_estimate

    return ttft_estimate(cohort)


def _metric_estimate(cohort: RunCohort, metric: str) -> tuple[float, float, float] | None:
    """``(mean, ci_low, ci_high)`` for the given metric; None if unavailable."""
    if metric == "time":
        return cohort.time_mean, cohort.time_ci_low, cohort.time_ci_high
    if metric == "ttft":
        ttft = _ttft_estimate_for_cohort(cohort)
        if ttft is None:
            return None
        mean, low, high, _n = ttft
        return mean, low, high
    raise ValueError(f"unknown metric {metric!r}")


def _build_recommendations_time_axis(
    cohorts: list[RunCohort], *, axis: Axis, metric: str
) -> list[Recommendation]:
    """SC-006 time/TTFT recommendation builder (Phase A / US3).

    Differs from the bytes builder in three ways:

    1. **Grouping key** is ``(path, hidden_size, corpus_subset)`` so long-stream
       cohorts get their own verdicts (different workload, different baseline).
    2. **Baseline pairing** is *immediate-predecessor* in cohort run-order
       rather than "first M1_BASELINE in group" — kills the cross-batch drift
       documented in research.md R-12 (~13% spread on this harness).
    3. **noise_bounded verdict** is emitted (per FR-005) when the predecessor
       verdict claims a win but at least one alternative same-cell M1_BASELINE
       would NOT — the conclusion is unstable across baselines.

    For ``metric="ttft"``, embed cells are skipped (TTFT is undefined off the
    streaming path).
    """
    recs: list[Recommendation] = []
    citation = CITATIONS[axis]

    # Walk cohorts in run-order, building:
    #   - predecessor_for[id(candidate_cohort)] -> baseline RunCohort
    #   - all_baselines_at[(path, width, corpus_subset)] -> list[RunCohort]
    predecessor_for: dict[int, RunCohort] = {}
    all_baselines_at: dict[tuple[Path_, int, str], list[RunCohort]] = {}
    last_baseline_at: dict[tuple[Path_, int, str], RunCohort] = {}

    for c in cohorts:
        key = (c.cell.path, c.cell.hidden_size, c.cell.corpus_subset)
        if c.cell.channel_config.name == M1_BASELINE.name:
            last_baseline_at[key] = c
            all_baselines_at.setdefault(key, []).append(c)
        elif c.cell.channel_config.axis == axis:
            if key in last_baseline_at:
                predecessor_for[id(c)] = last_baseline_at[key]

    # Group axis-relevant cohorts (baseline + this-axis candidates) by cell.
    by_cell: dict[tuple[Path_, int, str], list[RunCohort]] = {}
    for c in cohorts:
        if c.cell.channel_config.axis not in (axis, "baseline"):
            continue
        if metric == "ttft" and c.cell.path != "chat_stream":
            continue
        key = (c.cell.path, c.cell.hidden_size, c.cell.corpus_subset)
        by_cell.setdefault(key, []).append(c)

    for (path, width, corpus), group in sorted(by_cell.items()):
        candidates = [c for c in group if c.cell.channel_config.name != M1_BASELINE.name]
        baselines_at_cell = all_baselines_at.get((path, width, corpus), [])
        baseline = next(
            (c for c in group if c.cell.channel_config.name == M1_BASELINE.name),
            None,
        )

        if baseline is None or not baseline.measurable:
            recs.append(
                Recommendation(
                    axis=axis,
                    applies_to_path=path,
                    applies_to_widths=frozenset({width}),
                    verdict="not_measurable",
                    baseline_ci_upper=0.0,
                    citation=citation,
                    notes=(f"baseline cohort missing or unmeasurable for {path}/h{width}/{corpus}"),
                    corpus_subset=corpus,  # type: ignore[arg-type]
                )
            )
            continue

        base_est = _metric_estimate(baseline, metric)
        if base_est is None:
            recs.append(
                Recommendation(
                    axis=axis,
                    applies_to_path=path,
                    applies_to_widths=frozenset({width}),
                    verdict="not_measurable",
                    baseline_ci_upper=0.0,
                    citation=citation,
                    notes=(
                        f"insufficient {metric} data for baseline cohort "
                        f"{baseline.cell.cell_id} (need n>=10 valid samples)"
                    ),
                    corpus_subset=corpus,  # type: ignore[arg-type]
                )
            )
            continue
        base_mean, base_low, base_high = base_est

        if not candidates:
            recs.append(
                Recommendation(
                    axis=axis,
                    applies_to_path=path,
                    applies_to_widths=frozenset({width}),
                    verdict="no_winner",
                    baseline_ci_upper=base_high,
                    citation=citation,
                    notes=f"no candidates evaluated for {path}/h{width}/{corpus}",
                    corpus_subset=corpus,  # type: ignore[arg-type]
                )
            )
            continue

        # Find the best winner using each candidate's *immediate-predecessor*
        # baseline (R-12). This is the candidate-specific pairing; we then
        # check it for noise-bounded instability against the OTHER baselines
        # at the same cell.
        winner: RunCohort | None = None
        winner_predecessor: RunCohort | None = None
        winner_est: tuple[float, float, float] | None = None

        candidate_notes: list[str] = []
        for cand in candidates:
            if not cand.measurable:
                continue
            cand_est = _metric_estimate(cand, metric)
            if cand_est is None:
                candidate_notes.append(
                    f"{cand.cell.channel_config.name}: insufficient {metric} data"
                )
                continue
            cand_mean, cand_low, cand_high = cand_est
            candidate_notes.append(
                f"{cand.cell.channel_config.name}: mean={cand_mean:.4g}, ci_high={cand_high:.4g}"
            )

            pred = predecessor_for.get(id(cand), baseline)
            pred_est = _metric_estimate(pred, metric)
            if pred_est is None:
                continue
            _pred_mean, pred_low, _pred_high = pred_est

            # Minimizing-metric win: cand_ci_high < pred_ci_low.
            # Among multiple winners, keep the one with the smallest mean.
            if is_winner(baseline_ci_high=-pred_low, candidate_ci_low=-cand_high) and (
                winner is None or cand_mean < (winner_est[0] if winner_est else float("inf"))
            ):
                winner = cand
                winner_predecessor = pred
                winner_est = cand_est

        if winner is None:
            recs.append(
                Recommendation(
                    axis=axis,
                    applies_to_path=path,
                    applies_to_widths=frozenset({width}),
                    verdict="no_winner",
                    baseline_ci_upper=base_high,
                    citation=citation,
                    notes=(
                        f"no candidate cleared the SC-006 {metric} threshold "
                        f"against its immediate-predecessor M1_BASELINE for "
                        f"{path}/h{width}/{corpus}: " + "; ".join(candidate_notes)
                    ),
                    corpus_subset=corpus,  # type: ignore[arg-type]
                )
            )
            continue

        # Noise-bounded check: would this win survive against ALL same-cell
        # M1_BASELINE cohorts, not just the predecessor? Per FR-005 / R-12, an
        # apparent win that depends on which baseline we pair with cannot be
        # defensibly emitted — the cross-batch drift exceeds the candidate's
        # signal.
        assert winner is not None and winner_est is not None
        win_mean, _win_low, win_high = winner_est
        unstable_baselines: list[str] = []
        for alt_baseline in baselines_at_cell:
            if alt_baseline is winner_predecessor or not alt_baseline.measurable:
                continue
            alt_est = _metric_estimate(alt_baseline, metric)
            if alt_est is None:
                continue
            _alt_mean, alt_low, _alt_high = alt_est
            if not is_winner(baseline_ci_high=-alt_low, candidate_ci_low=-win_high):
                unstable_baselines.append(
                    f"alt_baseline_mean={_alt_mean:.4g}, ci_low={alt_low:.4g}"
                )

        if unstable_baselines:
            # Compute the cross-baseline drift magnitude to surface in notes.
            baseline_means = [
                _metric_estimate(b, metric)[0]  # type: ignore[index]
                for b in baselines_at_cell
                if _metric_estimate(b, metric) is not None
            ]
            spread = (
                (max(baseline_means) - min(baseline_means)) / min(baseline_means) * 100.0
                if baseline_means and min(baseline_means) > 0
                else 0.0
            )
            recs.append(
                Recommendation(
                    axis=axis,
                    applies_to_path=path,
                    applies_to_widths=frozenset({width}),
                    verdict="noise_bounded",
                    baseline_ci_upper=base_high,
                    citation=citation,
                    notes=(
                        f"cross-batch baseline drift dominates the candidate's signal "
                        f"({metric}; cross-baseline spread {spread:.1f}% across "
                        f"{len(baseline_means)} M1_BASELINE cohorts at "
                        f"{path}/h{width}/{corpus}). Predecessor pairing claimed "
                        f"{winner.cell.channel_config.name} as winner "
                        f"(mean={win_mean:.4g}, ci_high={win_high:.4g}) but the win "
                        f"does not survive {len(unstable_baselines)} alternative "
                        f"same-cell baseline(s). Re-measure under M4's shared-baseline "
                        f"mode (FR-013)."
                    ),
                    corpus_subset=corpus,  # type: ignore[arg-type]
                )
            )
            continue

        # Stable win: emit recommend.
        delta_pct = ((win_mean - base_mean) / base_mean * 100.0) if base_mean else 0.0
        win_metric_label: WinningMetric = "ttft" if metric == "ttft" else "time"
        # The winning_predecessor may differ from the group's first baseline; report
        # its CI in notes for traceability.
        assert winner_predecessor is not None
        pred_est = _metric_estimate(winner_predecessor, metric)
        assert pred_est is not None
        pred_mean, pred_low, pred_high = pred_est
        recs.append(
            Recommendation(
                axis=axis,
                applies_to_path=path,
                applies_to_widths=frozenset({width}),
                verdict="recommend",
                winning_config=winner.cell.channel_config,
                winning_delta_pct=delta_pct,
                winning_metric=win_metric_label,
                # Negated CIs preserve the dataclass invariant
                # ``candidate_ci_lower > baseline_ci_upper`` for our minimizing metric.
                baseline_ci_upper=-pred_low,
                candidate_ci_lower=-win_high,
                citation=citation,
                notes=(
                    f"{metric}: predecessor_baseline_mean={pred_mean:.4g}, "
                    f"candidate_mean={win_mean:.4g}, "
                    f"predecessor_baseline_ci=[{pred_low:.4g},{pred_high:.4g}], "
                    f"candidate_ci_high={win_high:.4g}; "
                    f"win survives {len(baselines_at_cell)} same-cell baseline(s)"
                ),
                corpus_subset=corpus,  # type: ignore[arg-type]
            )
        )

    return recs


# ---------------------------------------------------------------------------
# Top-level orchestrators (called by __main__)
# ---------------------------------------------------------------------------


async def run_sweep(
    *,
    axes: tuple[Axis, ...],
    widths: tuple[int, ...],
    paths: tuple[Path_, ...],
    iterations: int,
    seed: int,
    progress: bool = True,
) -> list[RunCohort]:
    cells = plan_cells(axes=axes, widths=widths, paths=paths, iterations=iterations)
    cohorts: list[RunCohort] = []
    for idx, cell in enumerate(cells):
        if progress:
            print(
                f"[{idx + 1}/{len(cells)}] cell={cell.cell_id} iters={cell.iterations}",
                flush=True,
            )
        cohort = await run_cell(cell, seed=seed + idx * 1000)
        cohorts.append(cohort)
    return cohorts


async def run_smoke(
    *,
    axis: Axis,
    width: int,
    path: Path_,
    seed: int,
    out_path: Path,
) -> int:
    """One iteration per cell on a single (axis, width, path), no CI math."""
    cells = plan_cells(
        axes=(axis,),
        widths=(width,),
        paths=(path,),
        iterations=1,
        include_long_stream=False,
    )
    cohorts: list[RunCohort] = []
    for cell in cells:
        cohort = await run_cell(cell, seed=seed)
        cohorts.append(cohort)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "mode": "smoke",
        "axis": axis,
        "width": width,
        "path": path,
        "seed": seed,
        "cohorts": [_cohort_to_smoke_dict(c) for c in cohorts],
    }
    out_path.write_text(json.dumps(payload, indent=2))
    has_any_success = any(c.n_successful >= 1 for c in cohorts)
    return 0 if has_any_success else 3


def _cohort_to_smoke_dict(c: RunCohort) -> dict[str, Any]:
    return {
        "cell_id": c.cell.cell_id,
        "config_name": c.cell.channel_config.name,
        "n_samples": len(c.samples),
        "n_successful": c.n_successful,
        "bytes_mean": c.bytes_mean,
        "time_mean": c.time_mean,
        "off_canonical": c.cell.off_canonical,
        "errors": [s.error for s in c.samples if s.error is not None],
    }


def cohort_to_dict(c: RunCohort) -> dict[str, Any]:
    """Serialize a RunCohort to the m3-channel-tuning.json schema."""
    return {
        "cell_id": c.cell.cell_id,
        "path": c.cell.path,
        "hidden_size": c.cell.hidden_size,
        "config_name": c.cell.channel_config.name,
        "config_axis": c.cell.channel_config.axis,
        "corpus_subset": c.cell.corpus_subset,
        "iterations": c.cell.iterations,
        "n_successful": c.n_successful,
        "measurable": c.measurable,
        "off_canonical": c.cell.off_canonical,
        "bytes": {
            "mean": c.bytes_mean,
            "ci_low": c.bytes_ci_low,
            "ci_high": c.bytes_ci_high,
        },
        "time_seconds": {
            "mean": c.time_mean,
            "ci_low": c.time_ci_low,
            "ci_high": c.time_ci_high,
        },
        "samples": [_sample_to_dict(s) for s in c.samples],
    }


def _sample_to_dict(s: Sample) -> dict[str, Any]:
    d = asdict(s)
    return d


def cohort_from_dict(d: dict[str, Any]) -> RunCohort:
    """Inverse of ``cohort_to_dict``: reconstruct a ``RunCohort`` from its
    JSON-serialized form. Used by the Phase A ``--reanalyze`` path to re-run
    ``build_recommendations`` against an already-collected sweep JSON without
    re-executing the benchmark.

    Slim cohorts (no ``samples`` field, e.g. the docs/benchmarks/ companion JSON
    that strips per-iteration data) are accepted: ``samples`` becomes an empty
    tuple. TTFT-metric verdicts require non-empty samples and will return
    ``not_measurable`` if asked to verdict a slim cohort.
    """
    from vllm_grpc_bench.channel_config import preset_by_name

    cfg = preset_by_name(d["config_name"])
    cell = BenchmarkCell(
        path=d["path"],
        hidden_size=int(d["hidden_size"]),
        channel_config=cfg,
        corpus_subset=d["corpus_subset"],
        iterations=int(d["iterations"]),
    )
    samples_raw = d.get("samples", []) or []
    samples = tuple(Sample(**s) for s in samples_raw)
    bytes_d = d["bytes"]
    time_d = d["time_seconds"]
    return RunCohort(
        cell=cell,
        samples=samples,
        n_successful=int(d["n_successful"]),
        bytes_mean=float(bytes_d["mean"]),
        bytes_ci_low=float(bytes_d["ci_low"]),
        bytes_ci_high=float(bytes_d["ci_high"]),
        time_mean=float(time_d["mean"]),
        time_ci_low=float(time_d["ci_low"]),
        time_ci_high=float(time_d["ci_high"]),
        measurable=bool(d["measurable"]),
    )


def recommendation_to_dict(r: Recommendation) -> dict[str, Any]:
    return {
        "axis": r.axis,
        "applies_to_path": r.applies_to_path,
        "applies_to_widths": sorted(r.applies_to_widths),
        "corpus_subset": r.corpus_subset,
        "verdict": r.verdict,
        "winning_config": r.winning_config.name if r.winning_config else None,
        "winning_delta_pct": r.winning_delta_pct,
        "winning_metric": r.winning_metric,
        "baseline_ci_upper": r.baseline_ci_upper,
        "candidate_ci_lower": r.candidate_ci_lower,
        "citation": r.citation,
        "notes": r.notes,
    }
