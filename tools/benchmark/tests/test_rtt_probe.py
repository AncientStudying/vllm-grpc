"""T012 / T013 — rtt_probe.measure_rtt correctness and validity gating.

Tests use a tiny in-process gRPC server that registers a ``Health`` servicer
whose ``Ping`` method sleeps a configurable amount of time so the probe sees
deterministic per-call wall-clock. The probe is exercised end-to-end through
``grpc.aio.insecure_channel`` so the stub-construction path and the
metadata-forwarding kwarg are covered.
"""

from __future__ import annotations

import asyncio
import statistics

import grpc
import pytest
from vllm_grpc.v1 import health_pb2, health_pb2_grpc
from vllm_grpc_bench.rtt_probe import (
    is_below_exercise_threshold,
    is_below_validity_threshold,
    measure_rtt,
)


class _PingServicer(health_pb2_grpc.HealthServicer):  # type: ignore[misc]
    """Deterministic Ping: sleep ``delay_ms`` per call, record metadata seen."""

    def __init__(self, delay_ms: float) -> None:
        self._delay_s = delay_ms / 1000.0
        self.observed_metadata: list[tuple[tuple[str, str], ...]] = []

    async def Ping(  # noqa: N802
        self,
        request: health_pb2.HealthRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> health_pb2.HealthResponse:
        # Capture invocation metadata so the test can verify forwarding.
        md = tuple((k, v) for k, v in (context.invocation_metadata() or ()) if isinstance(v, str))
        self.observed_metadata.append(md)
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)
        return health_pb2.HealthResponse(message="ok")


async def _serve(delay_ms: float) -> tuple[grpc.aio.Server, str, _PingServicer]:  # type: ignore[type-arg]
    servicer = _PingServicer(delay_ms=delay_ms)
    server = grpc.aio.server()
    health_pb2_grpc.add_HealthServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    return server, f"127.0.0.1:{port}", servicer


@pytest.mark.asyncio
async def test_measure_rtt_returns_correctly_shaped_record() -> None:
    """Probe count, median, p95, and raw samples all populated."""
    server, addr, _servicer = await _serve(delay_ms=5.0)
    try:
        async with grpc.aio.insecure_channel(addr) as channel:
            record = await measure_rtt(channel, n=8)
        assert record.n == 8
        assert len(record.samples_ms) == 8
        # All samples should be at least the server's deterministic floor.
        assert all(s >= 4.0 for s in record.samples_ms), record.samples_ms
        # Median should sit somewhere above the 5ms sleep (allow generous slack
        # for scheduler jitter on a busy CI host).
        assert 4.0 <= record.median_ms <= 50.0, record.median_ms
        # p95 must be >= median by construction.
        assert record.p95_ms >= record.median_ms
        # Spot-check the percentile math against statistics.median.
        assert record.median_ms == pytest.approx(statistics.median(record.samples_ms))
    finally:
        await server.stop(grace=0.5)


@pytest.mark.asyncio
async def test_measure_rtt_forwards_metadata() -> None:
    """Bearer-token metadata is attached to every probe RPC."""
    server, addr, servicer = await _serve(delay_ms=1.0)
    try:
        async with grpc.aio.insecure_channel(addr) as channel:
            md = (("authorization", "Bearer test-token-123"),)
            await measure_rtt(channel, n=3, metadata=md)
        # Every observed RPC saw the auth header (insertion order preserved).
        for observed in servicer.observed_metadata:
            assert ("authorization", "Bearer test-token-123") in observed
    finally:
        await server.stop(grace=0.5)


@pytest.mark.asyncio
async def test_measure_rtt_rejects_zero_n() -> None:
    """n < 1 is a programmer error — fail fast at the call site."""
    async with grpc.aio.insecure_channel("127.0.0.1:1") as channel:
        with pytest.raises(ValueError, match=r"n must be >= 1"):
            await measure_rtt(channel, n=0)


class TestValidityGating:
    """FR-004: callers gate verdict emission based on the measured median."""

    def _record(self, median_ms: float) -> object:
        from vllm_grpc_bench.m3_types import RTTRecord

        # samples is the median repeated; the probe's percentile math is
        # exercised elsewhere — here we only care about the gating helpers.
        return RTTRecord(
            n=4,
            median_ms=median_ms,
            p95_ms=median_ms,
            samples_ms=(median_ms,) * 4,
        )

    def test_below_validity_threshold_true_when_under_one_ms(self) -> None:
        rec = self._record(median_ms=0.4)
        assert is_below_validity_threshold(rec, threshold_ms=1.0) is True  # type: ignore[arg-type]

    def test_below_validity_threshold_false_at_one_ms(self) -> None:
        rec = self._record(median_ms=1.0)
        # Boundary is strict less-than per FR-004 wording.
        assert is_below_validity_threshold(rec, threshold_ms=1.0) is False  # type: ignore[arg-type]

    def test_below_exercise_threshold_true_at_ten_ms_default_twenty(self) -> None:
        rec = self._record(median_ms=10.0)
        assert is_below_exercise_threshold(rec, threshold_ms=20.0) is True  # type: ignore[arg-type]

    def test_below_exercise_threshold_false_at_eighty_ms(self) -> None:
        rec = self._record(median_ms=80.0)
        assert is_below_exercise_threshold(rec, threshold_ms=20.0) is False  # type: ignore[arg-type]
