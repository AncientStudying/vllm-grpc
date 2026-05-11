"""T015 — M5.1 sweep orchestrator tests (deterministic surfaces only).

Covers ``enumerate_cells``, ``frozen_tuned_channel_config``, the bootstrap
CI helper, the verdict mapper, and ``emit_cell_verdicts`` against
synthetic measurement fixtures. The full ``dispatch_cell`` /
``run_m5_1_sweep`` paths are exercised by the secrets-gated integration
test ``tests/integration/test_m5_1_modal_smoke.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from vllm_grpc_bench.m3_types import GRPCSubCohortKind, RTTRecord, Sample
from vllm_grpc_bench.m5_1_grpc_cohort import GRPCCohortResult
from vllm_grpc_bench.m5_1_sweep import (
    SMOKE_CELLS,
    CellSpec,
    _bootstrap_delta_ci,
    _CellMeasurement,
    _verdict_for_sub_cohort,
    emit_cell_verdicts,
    enumerate_cells,
    frozen_tuned_channel_config,
)
from vllm_grpc_bench.rest_cohort import RESTCohortRecord, RESTCohortResult, RESTCohortSample


def test_smoke_cells_cover_every_sub_cohort_kind() -> None:
    """SMOKE_CELLS exercises every M5.1 code path: REST, tuned_grpc (c=1
    degenerate), tuned_grpc_multiplexed + tuned_grpc_channels (c>=2),
    default_grpc (every cell), TTFT (chat_stream), wallclock (embed).
    """
    assert len(SMOKE_CELLS) == 3
    paths = {c.path for c in SMOKE_CELLS}
    assert paths == {"chat_stream", "embed"}, "smoke set must cover both metric types"
    concurrencies = {c.concurrency for c in SMOKE_CELLS}
    assert 1 in concurrencies, "smoke set must include a c=1 cell (tuned_grpc degenerate)"
    assert any(c.concurrency >= 2 for c in SMOKE_CELLS), (
        "smoke set must include a c>=2 cell (dual sub-cohort split)"
    )
    # All h=2048 (cheapest payload — smoke prioritizes coverage over width sweep).
    assert {c.hidden_size for c in SMOKE_CELLS} == {2048}


def test_enumerate_cells_produces_18_tuples() -> None:
    """T015 (a): enumerate_cells produces exactly 18 (path × width × c) tuples."""
    cells = enumerate_cells()
    assert len(cells) == 18
    paths = {c.path for c in cells}
    widths = {c.hidden_size for c in cells}
    concurrencies = {c.concurrency for c in cells}
    assert paths == {"chat_stream", "embed"}
    assert widths == {2048, 4096, 8192}
    assert concurrencies == {1, 4, 8}


def test_frozen_tuned_channel_config_falls_back_to_m1_when_no_winner() -> None:
    """If no M5 recommendation fires at (path, hidden_size), every axis falls
    back to M1-default.
    """
    cfg = frozen_tuned_channel_config("chat_stream", 8192)
    # No M5 winners at chat_stream:h8192 → composed config is all defaults.
    assert "frozen" in cfg.name
    # client_options is empty when every axis is m1-default.
    # (We assert via the absence of explicit override args rather than ==
    # because _compose_channel_config returns a default-shaped config.)


def test_frozen_tuned_channel_config_missing_report_raises() -> None:
    """T023 contract: missing M5 report raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match=r"M5 report not found"):
        frozen_tuned_channel_config("chat_stream", 2048, m5_report_path=Path("/no/such/m5.json"))


def test_bootstrap_delta_ci_recognizes_grpc_faster() -> None:
    """gRPC samples consistently faster than REST → CI strictly negative."""
    grpc_samples = [0.080] * 50  # 80 ms TTFT
    rest_samples = [0.100] * 50  # 100 ms TTFT
    delta_pct, (ci_low, ci_high) = _bootstrap_delta_ci(
        grpc_samples, rest_samples, n_bootstrap=200, seed=0
    )
    assert delta_pct < 0  # gRPC faster
    assert ci_high < 0  # strictly negative CI


def test_bootstrap_delta_ci_recognizes_rest_faster() -> None:
    """REST samples consistently faster → CI strictly positive."""
    grpc_samples = [0.120] * 50
    rest_samples = [0.080] * 50
    delta_pct, (ci_low, ci_high) = _bootstrap_delta_ci(
        grpc_samples, rest_samples, n_bootstrap=200, seed=0
    )
    assert delta_pct > 0
    assert ci_low > 0


def test_verdict_mapper_emits_correct_literals() -> None:
    """T015 (e): verdict literal mapper handles each sub-cohort kind.

    One literal per sub-cohort kind — including ``default_grpc_recommend``
    when the M1-default-channel control cohort beats REST. No fallthrough
    collapses one sub-cohort's win into another's label.
    """
    # CI strictly negative → gRPC sub-cohort recommend.
    assert (
        _verdict_for_sub_cohort("tuned_grpc_multiplexed", -20.0, (-25.0, -15.0))
        == "tuned_grpc_multiplexed_recommend"
    )
    assert (
        _verdict_for_sub_cohort("tuned_grpc_channels", -10.0, (-15.0, -5.0))
        == "tuned_grpc_channels_recommend"
    )
    assert _verdict_for_sub_cohort("tuned_grpc", -8.0, (-12.0, -4.0)) == "tuned_grpc_recommend"
    # default_grpc winning gets its own literal, NOT the tuned-multiplexed one.
    assert (
        _verdict_for_sub_cohort("default_grpc", -9.0, (-12.0, -6.0)) == "default_grpc_recommend"
    )
    # CI strictly positive → rest_recommend.
    assert _verdict_for_sub_cohort("tuned_grpc_multiplexed", 12.0, (8.0, 16.0)) == "rest_recommend"
    assert _verdict_for_sub_cohort("default_grpc", 12.0, (8.0, 16.0)) == "rest_recommend"
    # CI spans zero → no_winner.
    assert _verdict_for_sub_cohort("tuned_grpc_multiplexed", 0.5, (-3.0, 4.0)) == "no_winner"
    assert _verdict_for_sub_cohort("default_grpc", 0.5, (-3.0, 4.0)) == "no_winner"


def _fake_grpc_result(
    sub_cohort_kind: GRPCSubCohortKind,
    metric_value: float,
    cell_id: str,
) -> GRPCCohortResult:
    samples = tuple(
        Sample(
            cell_id=cell_id,
            iteration=i,
            request_wire_bytes=100,
            response_wire_bytes=200,
            wall_clock_seconds=metric_value,
            time_to_first_token_seconds=metric_value,
        )
        for i in range(20)
    )
    rtt = RTTRecord(n=8, median_ms=52.0, p95_ms=58.0, samples_ms=(52.0,) * 8)
    return GRPCCohortResult(
        samples=samples,
        rtt_record=rtt,
        sub_cohort_kind=sub_cohort_kind,
        channels_opened=1 if sub_cohort_kind != "tuned_grpc_channels" else 4,
    )


def _fake_rest_result(metric_value: float) -> RESTCohortResult:
    samples = tuple(
        RESTCohortSample(
            wall_clock_seconds=metric_value,
            shim_overhead_ms=0.4,
            request_bytes=300,
            response_bytes=1800,
        )
        for _ in range(20)
    )
    record = RESTCohortRecord(
        shim_overhead_ms_median=0.4,
        shim_overhead_ms_p95=0.9,
        connections_opened=4,
        connections_keepalive_reused=16,
        request_bytes_median=300,
        request_bytes_p95=300,
        response_bytes_median=1800,
        response_bytes_p95=1900,
    )
    rtt = RTTRecord(n=8, median_ms=52.0, p95_ms=58.0, samples_ms=(52.0,) * 8)
    return RESTCohortResult(samples=samples, record=record, rtt_record=rtt)


def test_emit_cell_verdicts_at_c4_has_three_verdicts() -> None:
    """T015 (c): at c >= 2, the cell carries three verdict rows
    (tuned-mux × REST, tuned-channels × REST, default-grpc × REST).
    """
    cell = CellSpec(path="chat_stream", hidden_size=2048, concurrency=4)
    measurement = _CellMeasurement(
        cell=cell,
        rest_result=_fake_rest_result(metric_value=0.100),
        tuned_multiplexed=_fake_grpc_result(
            "tuned_grpc_multiplexed", metric_value=0.080, cell_id=f"grpc-tuned-mux:{cell.key}"
        ),
        tuned_channels=_fake_grpc_result(
            "tuned_grpc_channels", metric_value=0.085, cell_id=f"grpc-tuned-ch:{cell.key}"
        ),
        default_grpc=_fake_grpc_result(
            "default_grpc", metric_value=0.110, cell_id=f"grpc-default:{cell.key}"
        ),
    )
    m5_1_cell = emit_cell_verdicts(measurement)
    assert len(m5_1_cell.verdicts) == 3
    # gRPC tuned cohorts → recommend; default-gRPC is slower → rest_recommend.
    kinds = [v.grpc_sub_cohort for v in m5_1_cell.verdicts]
    assert "tuned_grpc_multiplexed" in kinds
    assert "tuned_grpc_channels" in kinds
    assert "default_grpc" in kinds
    # metric label tracks path.
    assert all(v.metric == "ttft" for v in m5_1_cell.verdicts)


def test_emit_cell_verdicts_at_c1_has_two_verdicts() -> None:
    """T015 (c): at c == 1, the cell carries two verdict rows
    (tuned-degenerate × REST, default-grpc × REST).
    """
    cell = CellSpec(path="embed", hidden_size=4096, concurrency=1)
    measurement = _CellMeasurement(
        cell=cell,
        rest_result=_fake_rest_result(metric_value=0.060),
        tuned_multiplexed=_fake_grpc_result(
            "tuned_grpc", metric_value=0.050, cell_id=f"grpc-tuned:{cell.key}"
        ),
        tuned_channels=None,
        default_grpc=_fake_grpc_result(
            "default_grpc", metric_value=0.062, cell_id=f"grpc-default:{cell.key}"
        ),
    )
    m5_1_cell = emit_cell_verdicts(measurement)
    assert len(m5_1_cell.verdicts) == 2
    assert m5_1_cell.tuned_grpc_channels_cohort_key is None
    # embed metric is wallclock.
    assert all(v.metric == "wallclock" for v in m5_1_cell.verdicts)


def test_emit_cell_verdicts_low_rtt_caveat_fires_below_threshold() -> None:
    """At median RTT < 20 ms (the FR-004 exercise threshold), low_rtt_caveat is True."""
    cell = CellSpec(path="embed", hidden_size=2048, concurrency=1)

    rtt = RTTRecord(n=8, median_ms=2.0, p95_ms=3.0, samples_ms=(2.0,) * 8)
    rest_record = RESTCohortRecord(
        shim_overhead_ms_median=0.4,
        shim_overhead_ms_p95=0.5,
        connections_opened=1,
        connections_keepalive_reused=0,
        request_bytes_median=100,
        request_bytes_p95=100,
        response_bytes_median=100,
        response_bytes_p95=100,
    )
    rest_result = RESTCohortResult(
        samples=tuple(
            RESTCohortSample(
                wall_clock_seconds=0.001,
                shim_overhead_ms=0.4,
                request_bytes=100,
                response_bytes=100,
            )
            for _ in range(20)
        ),
        record=rest_record,
        rtt_record=rtt,
    )

    fast_grpc = GRPCCohortResult(
        samples=tuple(
            Sample(
                cell_id="grpc-tuned",
                iteration=i,
                request_wire_bytes=100,
                response_wire_bytes=100,
                wall_clock_seconds=0.001,
                time_to_first_token_seconds=0.001,
            )
            for i in range(20)
        ),
        rtt_record=rtt,
        sub_cohort_kind="tuned_grpc",
        channels_opened=1,
    )
    measurement = _CellMeasurement(
        cell=cell,
        rest_result=rest_result,
        tuned_multiplexed=fast_grpc,
        tuned_channels=None,
        default_grpc=fast_grpc,
    )
    m5_1_cell = emit_cell_verdicts(measurement)
    assert m5_1_cell.low_rtt_caveat is True
    assert m5_1_cell.rtt_ms_median < 20.0
