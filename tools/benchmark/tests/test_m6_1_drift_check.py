"""Tests for ``m6_1_drift_check`` — FR-029 chat_stream control-drift check."""

from __future__ import annotations

from vllm_grpc_bench.m6_1_drift_check import check_chat_stream_control_drift
from vllm_grpc_bench.m6_1_types import (
    EngineCostAggregate,
    M6_1Cell,
    M6_1CellRecord,
    M6_1PerCohortAggregate,
)


def _agg(cohort: str, mean: float, half_width: float = 1.0) -> M6_1PerCohortAggregate:
    return M6_1PerCohortAggregate(
        cohort=cohort,  # type: ignore[arg-type]
        n_attempted=100,
        n_successes=100,
        failure_count=0,
        classifier_metric_mean_ms=mean,
        classifier_metric_ci_half_width_ms=half_width,
        total_wall_clock_mean_ms=mean,
        total_wall_clock_ci_half_width_ms=half_width,
        engine_cost_mean=EngineCostAggregate(engine_ttft_mean_ms=5.0),
    )


def _chat_stream_cell_record(
    concurrency: int, rest_mean: float, default_mean: float, grpc_mean: float
) -> M6_1CellRecord:
    return M6_1CellRecord(
        cell=M6_1Cell(path="chat_stream", hidden_size=4096, concurrency=concurrency),
        per_cohort={
            "rest_https_edge": _agg("rest_https_edge", rest_mean),
            "default_grpc": _agg("default_grpc", default_mean),
            "tuned_grpc_multiplexed": _agg("tuned_grpc_multiplexed", grpc_mean),
        },
        classification="verdict_survives",
        classification_reason="synthetic",
        classifier_metric="ttft_ms",
        cohort_pair=("rest_https_edge", "tuned_grpc_multiplexed"),
        m6_winner_delta_ms=50.0,
        m6_winner_direction="grpc_wins",
        engine_cost_mean_ms=5.0,
        engine_cost_drift_warning=False,
        per_cohort_engine_cost_mean_ms=None,
        chat_stream_control_drift_warning=False,
    )


def _embed_cell_record(concurrency: int) -> M6_1CellRecord:
    return M6_1CellRecord(
        cell=M6_1Cell(path="embed", hidden_size=4096, concurrency=concurrency),
        per_cohort={
            "rest_https_edge": _agg("rest_https_edge", 200.0),
            "default_grpc": _agg("default_grpc", 150.0),
            "tuned_grpc_multiplexed": _agg("tuned_grpc_multiplexed", 100.0),
        },
        classification="verdict_survives",
        classification_reason="synthetic",
        classifier_metric="wall_clock_ms",
        cohort_pair=("rest_https_edge", "tuned_grpc_multiplexed"),
        m6_winner_delta_ms=80.0,
        m6_winner_direction="grpc_wins",
        engine_cost_mean_ms=5.0,
        engine_cost_drift_warning=False,
        per_cohort_engine_cost_mean_ms=None,
        chat_stream_control_drift_warning=False,
    )


def _make_baseline_row(
    path: str, concurrency: int, rest: float, default: float, grpc: float, ci: float = 1.0
) -> dict[str, object]:
    return {
        "cell": {"path": path, "hidden_size": 4096, "concurrency": concurrency},
        "per_cohort_classifier_metric": {
            "rest_https_edge": {
                "mean_ms": rest,
                "ci_lower_ms": rest - ci,
                "ci_upper_ms": rest + ci,
                "n_successes": 100,
            },
            "default_grpc": {
                "mean_ms": default,
                "ci_lower_ms": default - ci,
                "ci_upper_ms": default + ci,
                "n_successes": 100,
            },
            "tuned_grpc_multiplexed": {
                "mean_ms": grpc,
                "ci_lower_ms": grpc - ci,
                "ci_upper_ms": grpc + ci,
                "n_successes": 100,
            },
        },
    }


def test_all_overlapping_cis_yields_no_drift() -> None:
    m6_1_cells = [_chat_stream_cell_record(1, rest_mean=200.0, default_mean=150.0, grpc_mean=100.0)]
    baseline = [_make_baseline_row("chat_stream", 1, rest=200.0, default=150.0, grpc=100.0)]
    flags = check_chat_stream_control_drift(m6_1_cells, baseline)
    assert flags == {("chat_stream", 1): False}


def test_one_cohort_non_overlap_yields_drift() -> None:
    # M6.1 rest=300 (CI 299..301); M6 rest=200 (CI 199..201). Non-overlap.
    m6_1_cells = [_chat_stream_cell_record(1, rest_mean=300.0, default_mean=150.0, grpc_mean=100.0)]
    baseline = [_make_baseline_row("chat_stream", 1, rest=200.0, default=150.0, grpc=100.0)]
    flags = check_chat_stream_control_drift(m6_1_cells, baseline)
    assert flags == {("chat_stream", 1): True}


def test_embed_cells_always_false() -> None:
    m6_1_cells = [_embed_cell_record(1)]
    # Even with no baseline match, embed cells get False.
    baseline: list[dict[str, object]] = []
    flags = check_chat_stream_control_drift(m6_1_cells, baseline)
    assert flags == {("embed", 1): False}


def test_mix_of_chat_stream_cells() -> None:
    m6_1_cells = [
        _chat_stream_cell_record(1, rest_mean=200.0, default_mean=150.0, grpc_mean=100.0),
        _chat_stream_cell_record(4, rest_mean=300.0, default_mean=150.0, grpc_mean=100.0),
        _chat_stream_cell_record(8, rest_mean=200.0, default_mean=150.0, grpc_mean=100.0),
    ]
    baseline = [
        _make_baseline_row("chat_stream", 1, rest=200.0, default=150.0, grpc=100.0),
        _make_baseline_row("chat_stream", 4, rest=200.0, default=150.0, grpc=100.0),
        _make_baseline_row("chat_stream", 8, rest=200.0, default=150.0, grpc=100.0),
    ]
    flags = check_chat_stream_control_drift(m6_1_cells, baseline)
    assert flags == {
        ("chat_stream", 1): False,
        ("chat_stream", 4): True,
        ("chat_stream", 8): False,
    }
