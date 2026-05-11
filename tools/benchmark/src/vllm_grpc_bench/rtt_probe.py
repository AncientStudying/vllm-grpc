"""Per-cohort active-probe RTT measurement (FR-004 / research.md R-3).

The probe runs ``n`` consecutive unary ``Health.Ping`` RPCs against the same
gRPC channel immediately before each cohort's measurement window opens. The
returned ``RTTRecord`` carries the raw per-probe samples so the M5 JSON
consumer can re-derive any percentile downstream. Reusing the existing
``health.proto`` Ping RPC avoids a proto edit (Constitution I) and keeps the
TCP path warm for the cohort that follows.

The harness gates verdict emission on the median: cohorts whose median RTT
falls below the FR-004 same-host-fallback threshold (default 1.0 ms) are
marked ``not_measurable`` by the caller with reason
``"rtt_below_validity_threshold"``. ``measure_rtt`` itself never raises on
low RTT — it returns the record and lets the caller adjudicate against the
configured threshold (so an operator running against a near-local Modal
region still gets a recorded distribution, just with a caveat or refusal at
the sweep layer).
"""

from __future__ import annotations

import statistics
import time

import grpc
from vllm_grpc.v1 import health_pb2, health_pb2_grpc

from vllm_grpc_bench.m3_types import RTTRecord

_DEFAULT_PROBE_N: int = 32


async def measure_rtt(
    channel: grpc.aio.Channel,
    n: int = _DEFAULT_PROBE_N,
    metadata: tuple[tuple[str, str], ...] | None = None,
    *,
    timeout: float = 5.0,
) -> RTTRecord:
    """Run ``n`` unary ``Health.Ping`` calls; return median/p95 + raw samples.

    ``metadata`` is forwarded to every probe RPC so cross-host probes carry
    the same bearer-token header as the cohort RPCs that follow. ``timeout``
    is per-call (not aggregate); a probe that hangs longer than ``timeout``
    seconds raises through to the caller (the M5 sweep treats this as a
    handshake failure and exits with code 3).
    """
    if n < 1:
        raise ValueError(f"measure_rtt: n must be >= 1 (got {n})")
    stub = health_pb2_grpc.HealthStub(channel)
    samples_seconds: list[float] = []
    request = health_pb2.HealthRequest()
    for _ in range(n):
        start = time.perf_counter()
        await stub.Ping(request, timeout=timeout, metadata=metadata)
        samples_seconds.append(time.perf_counter() - start)
    samples_ms = tuple(s * 1000.0 for s in samples_seconds)
    return RTTRecord(
        n=n,
        median_ms=statistics.median(samples_ms),
        p95_ms=_percentile(samples_ms, 95.0),
        samples_ms=samples_ms,
    )


def _percentile(samples: tuple[float, ...], pct: float) -> float:
    """Linear-interpolation percentile across ``samples``.

    Matches numpy's default ``linear`` method so percentile math is
    reproducible across the harness's M3/M4/M5 paths (m4 uses numpy directly;
    this helper avoids a numpy import in the probe path to keep cold-start
    cost down).
    """
    if not samples:
        raise ValueError("_percentile: samples must be non-empty")
    if len(samples) == 1:
        return samples[0]
    ordered = sorted(samples)
    if pct <= 0:
        return ordered[0]
    if pct >= 100:
        return ordered[-1]
    rank = (pct / 100.0) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    frac = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * frac


def is_below_validity_threshold(record: RTTRecord, threshold_ms: float) -> bool:
    """FR-004 same-host-fallback gate: median RTT below ``threshold_ms``.

    Callers that get ``True`` are expected to mark the cohort
    ``not_measurable`` with reason ``"rtt_below_validity_threshold"``. The
    M5 sweep refuses to emit a verdict on such cohorts because the connection
    has unexpectedly resolved to a same-host route — the M5 measurement
    premise (real wire) is violated.
    """
    return record.median_ms < threshold_ms


def is_below_exercise_threshold(record: RTTRecord, threshold_ms: float) -> bool:
    """FR-004 low-RTT-caveat annotator gate: median RTT below ``threshold_ms``.

    Cohorts above the validity threshold but below this exercise threshold
    get ``low_rtt_caveat=True`` — the verdict is still emitted but the
    report flags it because the RTT-bounded axes (``keepalive``,
    ``http2_framing``) cannot be defensibly exercised at this distance.
    """
    return record.median_ms < threshold_ms
