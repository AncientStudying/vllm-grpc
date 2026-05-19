"""M6.1.3 — proxy-edge probe wire-format + aggregation unit tests (T018).

Exercises the per-RPC derivation + per-cell aggregation paths landed in
``m6_1_3_sweep.py``:

* :func:`compute_proxy_edge_segments` — per-RPC derivation from a timing
  payload dict (the shape ``m6_1_1_timing.timing_checkpoint_to_payload``
  produces). Covers the streaming round-trip + the FR-006 negative-value
  clock-anomaly assertion + the embed-cell (no-proxy-edge) case.
* :func:`_aggregate_per_segment` — per-cell-cohort PerSegmentAggregate
  build, including the cell-level clock-anomaly-warning gate per SC-013.
* Strict-superset compat — an M6.1.3 artifact's per-cell rows carry the
  new fields with values an M6.1.1-vintage reader can ignore cleanly
  (FR-010 + round-3 Q1).

The wire-extractor tests for ``extract_grpc_timings`` /
``extract_rest_timings`` live in ``test_m6_1_1_timing.py`` (existing) +
``test_m6_1_rest_shim.py`` (existing); this file focuses on the
M6.1.3-derived segments + classifier handoff.
"""

from __future__ import annotations

from typing import Any

import pytest
from vllm_grpc_bench.m6_1_3_sweep import (
    _aggregate_per_segment,
    compute_proxy_edge_segments,
)
from vllm_grpc_bench.m6_1_3_types import DEFAULT_THRESHOLDS
from vllm_grpc_bench.m6_sweep import RPCResult

# --- Test fixture builders --------------------------------------------------


def _build_timing_payload(
    *,
    # M6.1.1 perf_counter fields (handler-internal monotonic).
    handler_entry_ns: int = 0,
    pre_engine_ns: int = 200_000,  # 0.2ms seg_ab
    first_chunk_ns: int = 50_000_000,  # 50ms TTFT
    terminal_emit_ns: int = 51_000_000,  # 1ms seg_cd
    perturbation_audit_ns: int = 1000,
    # M6.1.2 engine-internal fields. Engine_arrival_ns uses wall-clock
    # (time.time_ns); engine_queued/scheduled/first_token/last_token use
    # monotonic (time.monotonic_ns). For the test fixtures we pick
    # plausible non-zero values; the exact epoch doesn't matter for the
    # derivation (just the deltas).
    engine_arrival_ns: int = 1_747_512_345_678_901_234,  # wall (~now)
    engine_queued_ns: int = 100_000_000_000,
    engine_scheduled_ns: int = 100_000_100_000,  # +0.1ms scheduled
    engine_first_token_ns: int = 100_040_100_000,  # +40ms prefill
    engine_last_token_ns: int = 100_050_100_000,
    # M6.1.3 proxy-edge fields.
    pre_engine_wall_ns: int | None = 1_747_512_345_676_401_234,  # 2.5ms before arrival
    first_chunk_mono_ns: int | None = 100_047_300_000,  # 7.2ms after first_token
    tokenized_prompt_length: int | None = 47,
    tokenized_prompt_hash: str | None = "a1b2c3d4e5f60718",
) -> dict[str, Any]:
    """Build a timing payload dict matching the shape produced by
    :func:`m6_1_1_timing.timing_checkpoint_to_payload`.
    """
    return {
        "handler_entry_ns": handler_entry_ns,
        "pre_engine_ns": pre_engine_ns,
        "first_chunk_ns": first_chunk_ns,
        "terminal_emit_ns": terminal_emit_ns,
        "perturbation_audit_ns": perturbation_audit_ns,
        "engine_arrival_ns": engine_arrival_ns,
        "engine_queued_ns": engine_queued_ns,
        "engine_scheduled_ns": engine_scheduled_ns,
        "engine_first_token_ns": engine_first_token_ns,
        "engine_last_token_ns": engine_last_token_ns,
        "pre_engine_wall_ns": pre_engine_wall_ns,
        "first_chunk_mono_ns": first_chunk_mono_ns,
        "tokenized_prompt_length": tokenized_prompt_length,
        "tokenized_prompt_hash": tokenized_prompt_hash,
    }


def _build_rpc_results(
    *,
    n_successful: int = 50,
    timing_payload_overrides: dict[str, Any] | None = None,
) -> list[RPCResult]:
    """Build a list of successful RPCResults each carrying a timing payload."""
    overrides = timing_payload_overrides or {}
    payload = _build_timing_payload(**overrides)
    return [
        RPCResult(
            success=True,
            wall_clock_ms=51.0,
            ttft_ms=50.0,
            engine_cost=None,
            failure_reason=None,
            m6_1_1_timing_payload=payload,
        )
        for _ in range(n_successful)
    ]


# --- compute_proxy_edge_segments — per-RPC derivation ----------------------


def test_compute_proxy_edge_segments_streaming_round_trip() -> None:
    """FR-005: ``seg_ingress_ms = engine_arrival_ns - pre_engine_wall_ns``
    + ``seg_egress_ms = first_chunk_mono_ns - engine_first_token_ns``.

    Uses the default fixture's values:
    * seg_ingress = (1_747_512_345_678_901_234 - 1_747_512_345_676_401_234) ns
      = 2_500_000 ns = 2.5 ms
    * seg_egress  = (100_047_300_000 - 100_040_100_000) ns = 7_200_000 ns = 7.2 ms
    """
    payload = _build_timing_payload()
    row = compute_proxy_edge_segments(payload)
    assert row.seg_ingress_ms is not None
    assert row.seg_egress_ms is not None
    assert row.seg_ingress_ms == pytest.approx(2.5, abs=1e-6)
    assert row.seg_egress_ms == pytest.approx(7.2, abs=1e-6)
    assert row.is_clock_anomaly is False


def test_compute_proxy_edge_segments_negative_ingress_fires_assertion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FR-006: when ``engine_arrival_ns < pre_engine_wall_ns`` (clock
    drift between wall-clock sources), the assertion fires — the row is
    marked ``is_clock_anomaly=True``, ``seg_ingress_ms`` becomes ``None``,
    and the raw ``_ns`` values are logged to stderr.
    """
    # Set pre_engine_wall AFTER engine_arrival → negative delta.
    payload = _build_timing_payload(
        pre_engine_wall_ns=1_747_512_345_679_999_999,  # > engine_arrival_ns
    )
    row = compute_proxy_edge_segments(payload)
    assert row.is_clock_anomaly is True
    assert row.seg_ingress_ms is None
    # seg_egress should remain valid (anomaly was on the ingress span only).
    assert row.seg_egress_ms is not None
    # Stderr log carries the raw _ns values.
    captured = capsys.readouterr()
    assert "clock-anomaly" in captured.err
    assert "seg_ingress_ms" in captured.err
    assert "engine_arrival_ns=" in captured.err
    assert "pre_engine_wall_ns=" in captured.err


def test_compute_proxy_edge_segments_negative_egress_fires_assertion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Symmetric to the ingress test: a negative ``seg_egress_ms`` (i.e.,
    ``first_chunk_mono_ns < engine_first_token_ns``) fires the FR-006
    assertion."""
    payload = _build_timing_payload(
        first_chunk_mono_ns=100_039_999_999,  # < engine_first_token_ns
    )
    row = compute_proxy_edge_segments(payload)
    assert row.is_clock_anomaly is True
    assert row.seg_egress_ms is None
    assert row.seg_ingress_ms is not None  # ingress unaffected
    captured = capsys.readouterr()
    assert "clock-anomaly" in captured.err
    assert "seg_egress_ms" in captured.err


def test_compute_proxy_edge_segments_embed_cell_no_proxy_edge_emission() -> None:
    """FR-003 + AS 1.7: a unary RPC (embed cell) emits the audit fields
    but NOT the proxy-edge wire keys. The extractor populates
    ``pre_engine_wall_ns`` and ``first_chunk_mono_ns`` as ``None``;
    ``compute_proxy_edge_segments`` returns ``seg_ingress_ms`` /
    ``seg_egress_ms`` as ``None`` AND does NOT fire the clock-anomaly
    assertion."""
    payload = _build_timing_payload(
        pre_engine_wall_ns=None,
        first_chunk_mono_ns=None,
    )
    row = compute_proxy_edge_segments(payload)
    assert row.seg_ingress_ms is None
    assert row.seg_egress_ms is None
    assert row.is_clock_anomaly is False  # NOT a clock anomaly — just absent


def test_compute_proxy_edge_segments_handles_none_payload() -> None:
    """The aggregator can pass ``None`` when an RPC didn't populate the
    timing payload (pre-M6.1.1 vintage, or RPC failed before emission)."""
    row = compute_proxy_edge_segments(None)
    assert row.seg_ingress_ms is None
    assert row.seg_egress_ms is None
    assert row.is_clock_anomaly is False


# --- _aggregate_per_segment — per-cell PerSegmentAggregate build ----------


def test_aggregate_per_segment_populates_proxy_edge_means() -> None:
    """Aggregator produces ``seg_ingress_ms_mean`` + ``seg_egress_ms_mean``
    on the PerSegmentAggregate when the per-RPC timing payloads carry the
    new wire keys."""
    results = _build_rpc_results(n_successful=50)
    agg = _aggregate_per_segment(results, thresholds=DEFAULT_THRESHOLDS)
    assert agg is not None
    assert agg.n_samples == 50
    # Per-RPC seg_ingress = 2.5 ms — every sample has the same value, so
    # the mean equals the per-RPC value.
    assert agg.seg_ingress_ms_mean == pytest.approx(2.5, abs=1e-6)
    assert agg.seg_egress_ms_mean == pytest.approx(7.2, abs=1e-6)
    # Inherited M6.1.1 + M6.1.2 segments also populated.
    assert agg.seg_ab_ms_mean == pytest.approx(0.2, abs=1e-3)
    assert agg.seg_queue_ms_mean == pytest.approx(0.1, abs=1e-3)
    assert agg.seg_prefill_ms_mean == pytest.approx(40.0, abs=1e-3)
    # No clock anomaly in this cell.
    assert agg.clock_anomaly_fraction == 0.0
    assert agg.clock_anomaly_warning is False


def test_aggregate_per_segment_returns_none_on_no_timing_payload() -> None:
    """When no successful RPC populated the timing payload, the aggregator
    returns ``None`` (the cell × cohort can't be characterized)."""
    results = [
        RPCResult(
            success=True,
            wall_clock_ms=51.0,
            ttft_ms=50.0,
            engine_cost=None,
            failure_reason=None,
            m6_1_1_timing_payload=None,
        ),
        RPCResult(
            success=False,
            wall_clock_ms=None,
            ttft_ms=None,
            engine_cost=None,
            failure_reason="grpc error",
            m6_1_1_timing_payload=None,
        ),
    ]
    agg = _aggregate_per_segment(results, thresholds=DEFAULT_THRESHOLDS)
    assert agg is None


def test_aggregate_per_segment_cell_level_clock_anomaly_warning() -> None:
    """When > configurable fraction of RPCs fire the FR-006 clock-anomaly
    assertion, the cell receives ``clock_anomaly_warning=True``.

    Default threshold is 0.5% per SC-013. We force 10% of RPCs to have a
    negative ingress span (clock drift) → ``clock_anomaly_fraction = 0.1``
    > 0.005 → warning fires.
    """
    # 45 healthy + 5 anomalous = 50 total; 10% anomaly fraction.
    healthy_payload = _build_timing_payload()
    anomalous_payload = _build_timing_payload(
        pre_engine_wall_ns=1_747_512_345_679_999_999,  # > engine_arrival_ns
    )
    healthy_results = [
        RPCResult(
            success=True,
            wall_clock_ms=51.0,
            ttft_ms=50.0,
            engine_cost=None,
            failure_reason=None,
            m6_1_1_timing_payload=healthy_payload,
        )
        for _ in range(45)
    ]
    anomalous_results = [
        RPCResult(
            success=True,
            wall_clock_ms=51.0,
            ttft_ms=50.0,
            engine_cost=None,
            failure_reason=None,
            m6_1_1_timing_payload=anomalous_payload,
        )
        for _ in range(5)
    ]
    agg = _aggregate_per_segment(healthy_results + anomalous_results, thresholds=DEFAULT_THRESHOLDS)
    assert agg is not None
    assert agg.clock_anomaly_fraction == pytest.approx(5 / 50)
    assert agg.clock_anomaly_warning is True


def test_aggregate_per_segment_clock_anomaly_excludes_from_mean() -> None:
    """Per FR-006: anomalous rows are EXCLUDED from the seg_ingress /
    seg_egress means but the underlying perf_counter / engine segments
    are still computed from all rows (the anomaly is wall↔monotonic
    conversion-specific to proxy-edge derivation).

    Setup: half the rows have inflated seg_ingress (e.g., 100 ms anomaly
    would be detected as positive, not negative — but we use the negative
    case to trip the assertion). The mean of seg_ingress should reflect
    only the healthy rows.
    """
    healthy_payload = _build_timing_payload()  # 2.5 ms ingress
    anomalous_payload = _build_timing_payload(
        pre_engine_wall_ns=1_747_512_345_679_999_999,  # negative delta
    )
    results = [
        RPCResult(
            success=True,
            wall_clock_ms=51.0,
            ttft_ms=50.0,
            engine_cost=None,
            failure_reason=None,
            m6_1_1_timing_payload=healthy_payload,
        )
        for _ in range(40)
    ] + [
        RPCResult(
            success=True,
            wall_clock_ms=51.0,
            ttft_ms=50.0,
            engine_cost=None,
            failure_reason=None,
            m6_1_1_timing_payload=anomalous_payload,
        )
        for _ in range(10)
    ]
    agg = _aggregate_per_segment(results, thresholds=DEFAULT_THRESHOLDS)
    assert agg is not None
    # Ingress mean reflects only the 40 healthy rows (all = 2.5ms).
    assert agg.seg_ingress_ms_mean == pytest.approx(2.5, abs=1e-6)
    # Egress mean — anomalous rows had pre_engine_wall set badly but
    # first_chunk_mono / engine_first_token were healthy → their egress
    # span was unaffected. The is_clock_anomaly flag still excluded the
    # whole row from BOTH ingress and egress aggregation though, so:
    assert agg.seg_egress_ms_mean == pytest.approx(7.2, abs=1e-6)


# --- Strict-superset compat (FR-010 + round-3 Q1) --------------------------


def test_pre_m6_1_3_payload_aggregates_without_proxy_edge_means() -> None:
    """Pre-M6.1.3 manifest rehydration: timing payloads WITHOUT the M6.1.3
    fields aggregate cleanly with ``seg_ingress_ms_mean`` /
    ``seg_egress_ms_mean`` left as ``None``."""
    pre_m6_1_3_payload = _build_timing_payload(
        pre_engine_wall_ns=None,
        first_chunk_mono_ns=None,
        tokenized_prompt_length=None,
        tokenized_prompt_hash=None,
    )
    results = [
        RPCResult(
            success=True,
            wall_clock_ms=51.0,
            ttft_ms=50.0,
            engine_cost=None,
            failure_reason=None,
            m6_1_1_timing_payload=pre_m6_1_3_payload,
        )
        for _ in range(20)
    ]
    agg = _aggregate_per_segment(results, thresholds=DEFAULT_THRESHOLDS)
    assert agg is not None
    # M6.1.1 + M6.1.2 segments populated as expected.
    assert agg.seg_ab_ms_mean == pytest.approx(0.2, abs=1e-3)
    assert agg.seg_prefill_ms_mean == pytest.approx(40.0, abs=1e-3)
    # M6.1.3 segments absent (None) — the classifier will trigger the
    # legacy-fallback branch on this cell.
    assert agg.seg_ingress_ms_mean is None
    assert agg.seg_egress_ms_mean is None
    # No clock anomaly: absent wire fields ≠ anomalous values.
    assert agg.clock_anomaly_fraction == 0.0
    assert agg.clock_anomaly_warning is False
