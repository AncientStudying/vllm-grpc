"""T024 — M5.2 per-cell verdict-family tests.

Covers ``emit_cell_verdicts`` from ``m5_2_sweep``:
- Protocol-comparison verdict literal computation when gRPC clears REST CI.
- ``rest_https_edge_recommend`` when REST CI clears gRPC.
- ``no_winner`` when CIs overlap.
- Transport-only verdict literal computation between rest_https_edge and
  rest_plain_tcp.
- Every protocol-comparison row's network-path labels are correct
  (``plain_tcp`` for gRPC, ``https_edge`` for REST).
"""

from __future__ import annotations

from vllm_grpc_bench.m3_types import RTTRecord, Sample
from vllm_grpc_bench.m5_1_grpc_cohort import GRPCCohortResult
from vllm_grpc_bench.m5_2_sweep import (
    CellSpec,
    M5_2CellMeasurement,
    emit_cell_verdicts,
)
from vllm_grpc_bench.rest_cohort import (
    RESTCohortRecord,
    RESTCohortResult,
    RESTCohortSample,
)


def _rest_result_with_wallclock(values_seconds: list[float]) -> RESTCohortResult:
    samples = tuple(
        RESTCohortSample(
            wall_clock_seconds=v,
            shim_overhead_ms=0.3,
            request_bytes=500,
            response_bytes=2000,
        )
        for v in values_seconds
    )
    return RESTCohortResult(
        samples=samples,
        record=RESTCohortRecord(
            shim_overhead_ms_median=0.3,
            shim_overhead_ms_p95=0.4,
            connections_opened=1,
            connections_keepalive_reused=len(values_seconds) - 1,
            request_bytes_median=500,
            request_bytes_p95=500,
            response_bytes_median=2000,
            response_bytes_p95=2000,
        ),
        rtt_record=RTTRecord(n=4, median_ms=50.0, p95_ms=55.0, samples_ms=(48.0, 50.0, 52.0, 55.0)),
    )


def _grpc_result_with_metric(
    kind: str, *, ttft_seconds: list[float], path: str = "embed"
) -> GRPCCohortResult:
    """For ``path='embed'``, the metric is ``wall_clock_seconds``. For
    ``path='chat_stream'``, the metric is ``time_to_first_token_seconds``.
    """
    samples = tuple(
        Sample(
            cell_id="test",
            iteration=i,
            request_wire_bytes=256,
            response_wire_bytes=1500,
            wall_clock_seconds=v if path == "embed" else 0.5,
            time_to_first_token_seconds=v if path == "chat_stream" else None,
        )
        for i, v in enumerate(ttft_seconds)
    )
    return GRPCCohortResult(
        samples=samples,
        rtt_record=RTTRecord(n=4, median_ms=48.0, p95_ms=53.0, samples_ms=(46.0, 48.0, 50.0, 53.0)),
        sub_cohort_kind=kind,  # type: ignore[arg-type]
        channels_opened=1,
    )


def _measurement(
    *,
    rest_edge_values: list[float],
    rest_tcp_values: list[float],
    grpc_default_values: list[float],
    grpc_tuned_mux_values: list[float] | None = None,
    grpc_tuned_ch_values: list[float] | None = None,
    grpc_tuned_values: list[float] | None = None,
    path: str = "embed",
    concurrency: int = 4,
) -> M5_2CellMeasurement:
    return M5_2CellMeasurement(
        cell=CellSpec(path=path, hidden_size=2048, concurrency=concurrency),
        rest_https_edge=_rest_result_with_wallclock(rest_edge_values),
        rest_plain_tcp=_rest_result_with_wallclock(rest_tcp_values),
        default_grpc=_grpc_result_with_metric(
            "default_grpc", ttft_seconds=grpc_default_values, path=path
        ),
        tuned_multiplexed=(
            _grpc_result_with_metric(
                "tuned_grpc_multiplexed", ttft_seconds=grpc_tuned_mux_values, path=path
            )
            if grpc_tuned_mux_values is not None
            else None
        ),
        tuned_channels=(
            _grpc_result_with_metric(
                "tuned_grpc_channels", ttft_seconds=grpc_tuned_ch_values, path=path
            )
            if grpc_tuned_ch_values is not None
            else None
        ),
        tuned_grpc=(
            _grpc_result_with_metric("tuned_grpc", ttft_seconds=grpc_tuned_values, path=path)
            if grpc_tuned_values is not None
            else None
        ),
    )


def test_grpc_clearly_faster_yields_grpc_recommend() -> None:
    """A gRPC cohort that is consistently ~30% faster than REST should
    yield ``default_grpc_recommend`` (CI strictly < 0)."""
    measurement = _measurement(
        rest_edge_values=[0.100, 0.101, 0.102, 0.099, 0.103] * 4,
        rest_tcp_values=[0.099, 0.100, 0.101, 0.098, 0.102] * 4,
        grpc_default_values=[0.070, 0.071, 0.072, 0.069, 0.070] * 4,
        grpc_tuned_mux_values=[0.071, 0.072, 0.073, 0.070, 0.071] * 4,
        grpc_tuned_ch_values=[0.072, 0.073, 0.074, 0.071, 0.072] * 4,
    )
    rows, _ = emit_cell_verdicts(measurement)
    default = [r for r in rows if r.grpc_cohort == "default_grpc"][0]
    assert default.verdict == "default_grpc_recommend"
    assert default.delta_median_ms < 0  # gRPC faster than REST.


def test_rest_clearly_faster_yields_rest_https_edge_recommend() -> None:
    """When the REST cohort is faster than every gRPC cohort, each
    protocol-comparison row's verdict literal is
    ``rest_https_edge_recommend``."""
    measurement = _measurement(
        rest_edge_values=[0.050, 0.051, 0.052, 0.049, 0.050] * 4,
        rest_tcp_values=[0.060, 0.061, 0.062, 0.059, 0.060] * 4,
        grpc_default_values=[0.090, 0.091, 0.092, 0.089, 0.090] * 4,
        grpc_tuned_mux_values=[0.091, 0.092, 0.093, 0.090, 0.091] * 4,
        grpc_tuned_ch_values=[0.092, 0.093, 0.094, 0.091, 0.092] * 4,
    )
    rows, _ = emit_cell_verdicts(measurement)
    for row in rows:
        assert row.verdict == "rest_https_edge_recommend"


def test_overlapping_ci_yields_no_winner() -> None:
    """When CIs overlap zero, every row is no_winner."""
    measurement = _measurement(
        rest_edge_values=[0.10, 0.05, 0.20, 0.08, 0.15] * 4,
        rest_tcp_values=[0.10, 0.05, 0.20, 0.08, 0.15] * 4,
        grpc_default_values=[0.10, 0.05, 0.20, 0.08, 0.15] * 4,
        grpc_tuned_mux_values=[0.10, 0.05, 0.20, 0.08, 0.15] * 4,
        grpc_tuned_ch_values=[0.10, 0.05, 0.20, 0.08, 0.15] * 4,
    )
    rows, _ = emit_cell_verdicts(measurement)
    assert {r.verdict for r in rows} == {"no_winner"}


def test_transport_only_verdict_rest_https_edge_recommend() -> None:
    """rest_https_edge is faster than rest_plain_tcp → verdict is
    ``rest_https_edge_recommend`` on the transport-only row."""
    measurement = _measurement(
        rest_edge_values=[0.040, 0.041, 0.042, 0.039, 0.040] * 4,
        rest_tcp_values=[0.060, 0.061, 0.062, 0.059, 0.060] * 4,
        grpc_default_values=[0.050, 0.051, 0.052, 0.049, 0.050] * 4,
        grpc_tuned_mux_values=[0.050, 0.051, 0.052, 0.049, 0.050] * 4,
        grpc_tuned_ch_values=[0.050, 0.051, 0.052, 0.049, 0.050] * 4,
    )
    _, transport = emit_cell_verdicts(measurement)
    assert transport.verdict == "rest_https_edge_recommend"


def test_transport_only_verdict_rest_plain_tcp_recommend() -> None:
    """When the HTTPS edge has a measurable transport cost, plain-TCP
    wins."""
    measurement = _measurement(
        rest_edge_values=[0.060, 0.061, 0.062, 0.059, 0.060] * 4,
        rest_tcp_values=[0.040, 0.041, 0.042, 0.039, 0.040] * 4,
        grpc_default_values=[0.050, 0.051, 0.052, 0.049, 0.050] * 4,
        grpc_tuned_mux_values=[0.050, 0.051, 0.052, 0.049, 0.050] * 4,
        grpc_tuned_ch_values=[0.050, 0.051, 0.052, 0.049, 0.050] * 4,
    )
    _, transport = emit_cell_verdicts(measurement)
    assert transport.verdict == "rest_plain_tcp_recommend"


def test_every_protocol_row_carries_correct_network_path_pair() -> None:
    """FR-009: protocol-comparison rows always have gRPC on plain_tcp and
    REST on https_edge. The dataclass defaults pin the pair; we verify
    the values surface unchanged through emit_cell_verdicts."""
    measurement = _measurement(
        rest_edge_values=[0.05, 0.06, 0.05] * 4,
        rest_tcp_values=[0.05, 0.06, 0.05] * 4,
        grpc_default_values=[0.05, 0.06, 0.05] * 4,
        grpc_tuned_mux_values=[0.05, 0.06, 0.05] * 4,
        grpc_tuned_ch_values=[0.05, 0.06, 0.05] * 4,
    )
    rows, _ = emit_cell_verdicts(measurement)
    for row in rows:
        assert row.grpc_cohort_network_path == "plain_tcp"
        assert row.rest_cohort_network_path == "https_edge"
        assert row.rest_cohort == "rest_https_edge"


def test_c1_cell_emits_only_two_protocol_rows() -> None:
    """At c=1 the tuned-pair collapses to a single tuned_grpc cohort, so
    the protocol-family has two rows (tuned_grpc + default_grpc)."""
    measurement = _measurement(
        rest_edge_values=[0.05, 0.06, 0.05] * 4,
        rest_tcp_values=[0.05, 0.06, 0.05] * 4,
        grpc_default_values=[0.05, 0.06, 0.05] * 4,
        grpc_tuned_values=[0.05, 0.06, 0.05] * 4,
        concurrency=1,
    )
    rows, _ = emit_cell_verdicts(measurement)
    cohorts = {r.grpc_cohort for r in rows}
    assert cohorts == {"tuned_grpc", "default_grpc"}


def test_low_rtt_caveat_set_when_below_threshold() -> None:
    """When the cell's aggregate RTT median falls below the exercise
    threshold, every row carries ``low_rtt_caveat=True``."""
    measurement = _measurement(
        rest_edge_values=[0.05] * 4,
        rest_tcp_values=[0.05] * 4,
        grpc_default_values=[0.05] * 4,
        grpc_tuned_mux_values=[0.05] * 4,
        grpc_tuned_ch_values=[0.05] * 4,
    )
    # The default RTT in the fakes is ~50 ms, so threshold > 50 ms forces the caveat.
    rows, t_row = emit_cell_verdicts(measurement, rtt_exercise_threshold_ms=200.0)
    assert all(r.low_rtt_caveat for r in rows)
    assert t_row.low_rtt_caveat
