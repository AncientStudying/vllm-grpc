"""Per-block segment aggregator unit tests (closes the foundational gap
between `BlockDispatchResult.per_rpc_metadata` and the M6.2 per-cell row's
`seg_*_ms` / `tpot_ms` / `wall_p50_ms_ci_half_width` fields).

Before this aggregator landed, `sweep._build_measurement_point`
hardcoded all derived fields to `None`, which prevented any cross-cohort
ingress/egress bisection on a real Modal sweep. These tests pin the
aggregator's contract so a regression couldn't ship the same scaffolding
gap silently again.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.sweep import (
    BlockDispatchResult,
    _aggregate_block_metrics,
    _AggregatedRPCMetrics,
    _build_measurement_point,
)


def _payload(
    *,
    handler_entry_ns: int = 1_000_000,
    pre_engine_ns: int = 2_000_000,
    first_chunk_ns: int = 50_000_000,
    terminal_emit_ns: int = 100_000_000,
    engine_queued_ns: int = 3_000_000,
    engine_scheduled_ns: int = 5_000_000,
    engine_first_token_ns: int = 45_000_000,
    pre_engine_wall_ns: int | None = 1_500_000,
    engine_arrival_ns: int = 4_000_000,
    first_chunk_mono_ns: int | None = 50_500_000,
    engine_tpot_ms: float | None = 33.7,
) -> dict[str, str]:
    """Build a per-RPC metadata dict with M6.1.1 + M6.1.2 + M6.1.3 keys.

    Default values produce non-degenerate positive segments:
      seg_ab    = (pre_engine - handler_entry) * 1e-6        = 1.0 ms
      seg_queue = (eng_scheduled - eng_queued) * 1e-6        = 2.0 ms
      seg_pre   = (eng_first_token - eng_scheduled) * 1e-6   = 40.0 ms
      seg_ing   = (eng_arrival - pre_engine_wall) * 1e-6     = 2.5 ms
      seg_egr   = (first_chunk_mono - eng_first_token) * 1e-6 = 5.5 ms
    """
    md: dict[str, str] = {
        "handler_entry_ns": str(handler_entry_ns),
        "pre_engine_ns": str(pre_engine_ns),
        "first_chunk_ns": str(first_chunk_ns),
        "terminal_emit_ns": str(terminal_emit_ns),
        "engine_queued_ns": str(engine_queued_ns),
        "engine_scheduled_ns": str(engine_scheduled_ns),
        "engine_first_token_ns": str(engine_first_token_ns),
        "engine_arrival_ns": str(engine_arrival_ns),
    }
    if pre_engine_wall_ns is not None:
        md["pre_engine_wall_ns"] = str(pre_engine_wall_ns)
    if first_chunk_mono_ns is not None:
        md["first_chunk_mono_ns"] = str(first_chunk_mono_ns)
    if engine_tpot_ms is not None:
        md["engine_tpot_ms"] = str(engine_tpot_ms)
    return md


class TestHappyPath:
    def test_all_segments_populated_when_all_keys_present(self) -> None:
        timings = [100.0, 110.0, 105.0, 95.0, 102.0]
        metadata = [_payload() for _ in range(5)]
        agg = _aggregate_block_metrics(timings, metadata)
        assert agg.seg_ab_ms == pytest.approx(1.0)
        assert agg.seg_queue_ms == pytest.approx(2.0)
        assert agg.seg_prefill_ms == pytest.approx(40.0)
        assert agg.seg_ingress_ms == pytest.approx(2.5)
        assert agg.seg_egress_ms == pytest.approx(5.5)
        assert agg.tpot_ms == pytest.approx(33.7)
        assert agg.wall_p50_ms == pytest.approx(102.0)
        assert agg.wall_p95_ms is not None
        assert agg.wall_p99_ms is not None
        assert agg.wall_p50_ms_ci_half_width > 0.0
        assert agg.clock_anomaly is False
        assert agg.clock_anomaly_fraction == 0.0

    def test_returns_dataclass_shape(self) -> None:
        timings = [50.0, 60.0]
        metadata = [_payload(), _payload()]
        agg = _aggregate_block_metrics(timings, metadata)
        assert isinstance(agg, _AggregatedRPCMetrics)


class TestMissingProxyEdgeKeys:
    def test_pre_engine_wall_absent_leaves_ingress_none(self) -> None:
        """Pre-M6.1.3 wire vintage or unary embed RPC: no pre_engine_wall_ns."""
        timings = [100.0] * 5
        metadata = [_payload(pre_engine_wall_ns=None) for _ in range(5)]
        agg = _aggregate_block_metrics(timings, metadata)
        assert agg.seg_ingress_ms is None
        # Other segments still derive cleanly.
        assert agg.seg_ab_ms == pytest.approx(1.0)
        assert agg.seg_queue_ms == pytest.approx(2.0)
        assert agg.seg_egress_ms == pytest.approx(5.5)

    def test_first_chunk_mono_absent_leaves_egress_none(self) -> None:
        timings = [100.0] * 5
        metadata = [_payload(first_chunk_mono_ns=None) for _ in range(5)]
        agg = _aggregate_block_metrics(timings, metadata)
        assert agg.seg_egress_ms is None
        assert agg.seg_ingress_ms == pytest.approx(2.5)


class TestMissingEngineStats:
    def test_zero_engine_fields_skip_queue_and_prefill(self) -> None:
        """vLLM didn't populate RequestStateStats — engine_*_ns are 0."""
        timings = [100.0] * 5
        metadata = [
            _payload(
                engine_queued_ns=0,
                engine_scheduled_ns=0,
                engine_first_token_ns=0,
            )
            for _ in range(5)
        ]
        agg = _aggregate_block_metrics(timings, metadata)
        assert agg.seg_queue_ms is None
        assert agg.seg_prefill_ms is None
        # M6.1.1 perf_counter segments still derive.
        assert agg.seg_ab_ms == pytest.approx(1.0)


class TestMissingTpot:
    def test_engine_tpot_absent_leaves_tpot_none(self) -> None:
        """Embed (unary) RPCs don't emit `engine_tpot_ms` — only engine_forward_ms."""
        timings = [100.0] * 5
        metadata = [_payload(engine_tpot_ms=None) for _ in range(5)]
        agg = _aggregate_block_metrics(timings, metadata)
        assert agg.tpot_ms is None
        # Segments still derive from the M6.1.1 timing keys.
        assert agg.seg_ab_ms == pytest.approx(1.0)


class TestClockAnomalyExclusion:
    def test_negative_seg_ingress_excluded_and_counted(self, capsys) -> None:
        """FR-006: negative `seg_ingress_ms` (wall↔monotonic mismatch) is
        excluded from the per-segment mean and counted toward `clock_anomaly`."""
        timings = [100.0] * 10
        metadata: list[dict[str, str]] = []
        for i in range(10):
            if i == 0:
                # One anomalous row: arrival before wall anchor.
                metadata.append(
                    _payload(
                        pre_engine_wall_ns=5_000_000,
                        engine_arrival_ns=1_000_000,  # before pre_engine_wall_ns
                    )
                )
            else:
                metadata.append(_payload())
        agg = _aggregate_block_metrics(timings, metadata)
        # 9 healthy ingress samples (each = 2.5 ms); anomalous one excluded.
        assert agg.seg_ingress_ms == pytest.approx(2.5)
        # Anomaly rate 10% — well above the 0.5% gate.
        assert agg.clock_anomaly_fraction == pytest.approx(0.1)
        assert agg.clock_anomaly is True
        captured = capsys.readouterr()
        assert "[clock-anomaly]" in captured.err
        assert "seg_ingress_ms" in captured.err

    def test_negative_seg_egress_excluded_and_counted(self, capsys) -> None:
        timings = [100.0] * 10
        metadata: list[dict[str, str]] = []
        for i in range(10):
            if i == 0:
                metadata.append(
                    _payload(
                        first_chunk_mono_ns=10_000_000,
                        engine_first_token_ns=20_000_000,  # after first_chunk
                    )
                )
            else:
                metadata.append(_payload())
        agg = _aggregate_block_metrics(timings, metadata)
        assert agg.seg_egress_ms == pytest.approx(5.5)
        assert agg.clock_anomaly is True
        captured = capsys.readouterr()
        assert "seg_egress_ms" in captured.err

    def test_one_anomaly_in_200_does_not_fire_gate(self) -> None:
        """0.5% gate: 1/200 = 0.5% (boundary — strictly greater, so doesn't fire)."""
        timings = [100.0] * 200
        metadata: list[dict[str, str]] = []
        metadata.append(
            _payload(
                pre_engine_wall_ns=5_000_000,
                engine_arrival_ns=1_000_000,
            )
        )
        metadata.extend(_payload() for _ in range(199))
        agg = _aggregate_block_metrics(timings, metadata)
        # 1/200 = 0.005; gate is `> 0.005`, so at-threshold does NOT fire.
        assert agg.clock_anomaly_fraction == pytest.approx(0.005)
        assert agg.clock_anomaly is False

    def test_two_anomalies_in_200_fires_gate(self) -> None:
        timings = [100.0] * 200
        metadata: list[dict[str, str]] = []
        for _ in range(2):
            metadata.append(
                _payload(
                    pre_engine_wall_ns=5_000_000,
                    engine_arrival_ns=1_000_000,
                )
            )
        metadata.extend(_payload() for _ in range(198))
        agg = _aggregate_block_metrics(timings, metadata)
        assert agg.clock_anomaly_fraction == pytest.approx(0.01)
        assert agg.clock_anomaly is True


class TestCIHalfWidth:
    def test_ci_zero_when_n_lt_2(self) -> None:
        timings = [100.0]
        metadata = [_payload()]
        agg = _aggregate_block_metrics(timings, metadata)
        assert agg.wall_p50_ms_ci_half_width == 0.0

    def test_ci_nonzero_at_n_ge_2_with_variance(self) -> None:
        timings = [50.0, 100.0, 150.0]
        metadata = [_payload() for _ in range(3)]
        agg = _aggregate_block_metrics(timings, metadata)
        assert agg.wall_p50_ms_ci_half_width > 0.0

    def test_ci_zero_when_all_timings_identical(self) -> None:
        timings = [100.0, 100.0, 100.0]
        metadata = [_payload() for _ in range(3)]
        agg = _aggregate_block_metrics(timings, metadata)
        assert agg.wall_p50_ms_ci_half_width == 0.0


class TestEmptyMetadata:
    def test_empty_per_rpc_metadata_returns_none_segments(self) -> None:
        """REST cohort dispatch with no per_rpc_metadata (pre-M6.1.x server,
        or M6.2 dispatcher that didn't thread payload) — wall stats still
        derive from timings_ms, but all segments + tpot are None."""
        timings = [50.0, 60.0, 70.0]
        metadata: list[dict[str, str]] = []
        agg = _aggregate_block_metrics(timings, metadata)
        assert agg.wall_p50_ms == pytest.approx(60.0)
        assert agg.wall_p50_ms_ci_half_width > 0.0
        assert agg.seg_ab_ms is None
        assert agg.seg_queue_ms is None
        assert agg.seg_prefill_ms is None
        assert agg.seg_ingress_ms is None
        assert agg.seg_egress_ms is None
        assert agg.tpot_ms is None
        assert agg.clock_anomaly is False


class TestBuildMeasurementPointIntegration:
    def test_successful_block_populates_segments(self) -> None:
        """End-to-end: BlockDispatchResult → M6_2MeasurementPoint with
        segments populated. This is what `sweep` does in the main loop."""
        result = BlockDispatchResult(
            timings_ms=[100.0, 110.0, 105.0, 95.0, 102.0],
            failed_reason=None,
            per_rpc_metadata=[_payload() for _ in range(5)],
        )
        point = _build_measurement_point(
            cell_id="chat_stream_c1",
            cohort="default_grpc",
            max_tokens=50,
            n=5,
            result=result,
            block_start_utc="2026-05-23T16:00:00Z",
            block_end_utc="2026-05-23T16:00:05Z",
            retry_attempted=False,
            block_inputs={
                "prompt_text": "M6 chat probe seed=0 digest=0",
                "prompt_source": "synthetic_seed_derived",
                "prompt_corpus_idx": None,
                "ignore_eos": False,
                "max_tokens": 50,
            },  # type: ignore[arg-type]
        )
        # The four bugs that previously stayed None now populate from the
        # aggregator output.
        assert point.seg_ab_ms == pytest.approx(1.0)
        assert point.seg_queue_ms == pytest.approx(2.0)
        assert point.seg_prefill_ms == pytest.approx(40.0)
        assert point.seg_ingress_ms == pytest.approx(2.5)
        assert point.seg_egress_ms == pytest.approx(5.5)
        assert point.tpot_ms == pytest.approx(33.7)
        assert point.wall_p50_ms_ci_half_width > 0.0
        assert point.clock_anomaly is False

    def test_failed_block_leaves_segments_none(self) -> None:
        """Failed block (no timings) — segment fields stay None per the
        existing M6_2MeasurementPoint failed-row convention."""
        result = BlockDispatchResult(
            timings_ms=[],
            failed_reason="grpc_timeout",
            per_rpc_metadata=[],
        )
        point = _build_measurement_point(
            cell_id="chat_stream_c1",
            cohort="default_grpc",
            max_tokens=50,
            n=20,
            result=result,
            block_start_utc="2026-05-23T16:00:00Z",
            block_end_utc="2026-05-23T16:00:05Z",
            retry_attempted=True,
            block_inputs={
                "prompt_text": "M6 chat probe",
                "prompt_source": "synthetic_seed_derived",
                "prompt_corpus_idx": None,
                "ignore_eos": False,
                "max_tokens": 50,
            },  # type: ignore[arg-type]
        )
        assert point.failed_reason == "grpc_timeout"
        assert point.seg_ab_ms is None
        assert point.seg_ingress_ms is None
        assert point.tpot_ms is None
        assert point.wall_p50_ms_ci_half_width is None

    def test_successful_block_with_no_metadata_leaves_segs_none(self) -> None:
        """Successful timings but no per_rpc_metadata (e.g., stub dispatcher
        emits empty metadata) — wall stats populate but seg fields stay None."""
        result = BlockDispatchResult(
            timings_ms=[100.0, 110.0, 105.0],
            failed_reason=None,
            per_rpc_metadata=[],
        )
        point = _build_measurement_point(
            cell_id="chat_stream_c1",
            cohort="default_grpc",
            max_tokens=50,
            n=3,
            result=result,
            block_start_utc="2026-05-23T16:00:00Z",
            block_end_utc="2026-05-23T16:00:05Z",
            retry_attempted=False,
            block_inputs={
                "prompt_text": "M6 chat probe",
                "prompt_source": "synthetic_seed_derived",
                "prompt_corpus_idx": None,
                "ignore_eos": False,
                "max_tokens": 50,
            },  # type: ignore[arg-type]
        )
        # Wall percentiles populate from timings; segments stay None.
        assert point.wall_p50_ms == pytest.approx(105.0)
        assert point.wall_p50_ms_ci_half_width > 0.0
        assert point.seg_ab_ms is None
        assert point.tpot_ms is None


class TestUnparseableValues:
    def test_garbage_value_skipped_not_crashed(self) -> None:
        """Defensive: a corrupt per-RPC payload doesn't crash the aggregator."""
        timings = [100.0, 100.0]
        metadata = [
            {**_payload(), "engine_tpot_ms": "not-a-number"},
            _payload(),
        ]
        agg = _aggregate_block_metrics(timings, metadata)
        # The good row contributes; the bad row's tpot is skipped.
        assert agg.tpot_ms == pytest.approx(33.7)


class TestRESTRegressionScenario:
    """Specifically exercises the scenario this aggregator was built to
    diagnose: REST cohort showing ~35ms higher seg_egress per RPC."""

    def test_synthetic_rest_egress_overhead_visible(self) -> None:
        """gRPC and REST cohorts get the same engine, but REST shows +35ms
        egress per RPC. With segment aggregation in place, the gap is
        directly readable from the per-cell row."""
        # gRPC cohort: tight egress (5.5 ms baseline from default _payload).
        grpc_md = [_payload() for _ in range(20)]
        # REST cohort: +35 ms egress per RPC (modelled as first_chunk_mono_ns
        # delayed by 35 ms from engine_first_token_ns).
        rest_md = [
            _payload(
                engine_first_token_ns=45_000_000,
                first_chunk_mono_ns=45_000_000 + 5_500_000 + 35_000_000,
            )
            for _ in range(20)
        ]
        grpc_agg = _aggregate_block_metrics([100.0] * 20, grpc_md)
        rest_agg = _aggregate_block_metrics([100.0] * 20, rest_md)
        assert grpc_agg.seg_egress_ms == pytest.approx(5.5)
        assert rest_agg.seg_egress_ms == pytest.approx(40.5)
        # The diagnostic signal — REST egress ~35ms higher than gRPC — is now
        # visible in the per-cell row, without needing to fish through raw
        # per-RPC sidecars.
        delta_ms = rest_agg.seg_egress_ms - grpc_agg.seg_egress_ms
        assert delta_ms == pytest.approx(35.0)
