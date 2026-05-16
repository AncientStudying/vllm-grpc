"""Tests for the M6.1 engine-path differential (T029 — US2)."""

from __future__ import annotations

import math

from vllm_grpc_bench.m6_1_supersede import compute_engine_path_differential
from vllm_grpc_bench.m6_1_types import (
    EngineCostAggregate,
    M6_1Cell,
    M6_1CellRecord,
    M6_1PerCohortAggregate,
)


def _agg(cohort: str, mean: float, half: float, n: int = 100) -> M6_1PerCohortAggregate:
    return M6_1PerCohortAggregate(
        cohort=cohort,  # type: ignore[arg-type]
        n_attempted=100,
        n_successes=n,
        failure_count=100 - n,
        classifier_metric_mean_ms=mean,
        classifier_metric_ci_half_width_ms=half,
        total_wall_clock_mean_ms=mean,
        total_wall_clock_ci_half_width_ms=half,
        engine_cost_mean=EngineCostAggregate(
            engine_forward_mean_ms=5.0, engine_forward_ci_half_width_ms=0.1
        ),
    )


def _cell_record(n_succ_default: int = 100) -> M6_1CellRecord:
    pc = {
        "rest_https_edge": _agg("rest_https_edge", 220.0, 1.0),
        "default_grpc": _agg("default_grpc", 165.0, 1.0, n=n_succ_default),
        "tuned_grpc_multiplexed": _agg("tuned_grpc_multiplexed", 110.0, 1.0),
    }
    return M6_1CellRecord(
        cell=M6_1Cell(path="embed", hidden_size=4096, concurrency=1),
        per_cohort=pc,
        classification="verdict_survives",
        classification_reason="synthetic",
        classifier_metric="wall_clock_ms",
        cohort_pair=("rest_https_edge", "tuned_grpc_multiplexed"),
        m6_winner_delta_ms=80.0,
        m6_winner_direction="grpc_wins",
        engine_cost_mean_ms=20.0,
        engine_cost_drift_warning=False,
        per_cohort_engine_cost_mean_ms=None,
        chat_stream_control_drift_warning=False,
    )


def _m6_baseline_row(rest: float, default: float, grpc: float, ci: float = 2.0) -> dict:
    return {
        "cell": {"path": "embed", "hidden_size": 4096, "concurrency": 1},
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
        "engine_cost_mean_ms": 10.0,
    }


def test_delta_sign_correct() -> None:
    cell = _cell_record()
    m6_row = _m6_baseline_row(rest=210.0, default=155.0, grpc=100.0)
    result = compute_engine_path_differential(cell, m6_row)
    # M6.1 rest=220, M6 rest=210 → delta=+10
    assert result["per_cohort_classifier_metric_delta_ms"]["rest_https_edge"] == 10.0
    assert result["per_cohort_classifier_metric_delta_ms"]["default_grpc"] == 10.0
    assert result["per_cohort_classifier_metric_delta_ms"]["tuned_grpc_multiplexed"] == 10.0


def test_combined_ci_half_width_formula() -> None:
    """CI half-width of difference = sqrt(M6.1^2 + M6^2)."""
    cell = _cell_record()
    # M6.1 CI half = 1.0; M6 CI = (rest-2, rest+2) → half = 2.0 → combined = sqrt(5)
    m6_row = _m6_baseline_row(rest=210.0, default=155.0, grpc=100.0)
    result = compute_engine_path_differential(cell, m6_row)
    expected = math.sqrt(1.0 * 1.0 + 2.0 * 2.0)
    assert (
        result["per_cohort_classifier_metric_delta_ci_half_width_ms"]["rest_https_edge"] == expected
    )


def test_cell_incomplete_still_populates_row_with_actual_n_successes() -> None:
    cell = _cell_record(n_succ_default=60)
    m6_row = _m6_baseline_row(rest=210.0, default=155.0, grpc=100.0)
    result = compute_engine_path_differential(cell, m6_row)
    n_succ = result["per_cohort_n_successes"]
    assert n_succ["rest_https_edge"] == 100
    assert n_succ["default_grpc"] == 60
    assert n_succ["tuned_grpc_multiplexed"] == 100


def test_engine_cost_delta_uses_cell_means() -> None:
    cell = _cell_record()
    # M6 engine_cost_mean = 10; M6.1 = 20 → delta = +10.
    m6_row = _m6_baseline_row(rest=210.0, default=155.0, grpc=100.0)
    result = compute_engine_path_differential(cell, m6_row)
    assert result["engine_cost_mean_delta_ms"] == 10.0
