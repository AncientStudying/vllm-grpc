"""US1 / FR-005 / R-11 — baseline-CV failure path.

When a shared-baseline cohort's coefficient of variation on the time metric
exceeds ``baseline_cv_max``, the harness aborts with exit 3 (raised as
``BaselineCVError``) and emits no verdicts.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.m3_types import BenchmarkCell, RunCohort, Sample


def _baseline_cohort(values: list[float]) -> RunCohort:
    cell = BenchmarkCell(
        path="embed",
        hidden_size=4096,
        channel_config=M1_BASELINE,
        corpus_subset="m1_embed",
        iterations=len(values),
    )
    samples = tuple(
        Sample(
            cell_id=cell.cell_id,
            iteration=i,
            request_wire_bytes=100,
            response_wire_bytes=100,
            wall_clock_seconds=v,
        )
        for i, v in enumerate(values)
    )
    mean = sum(values) / len(values)
    return RunCohort(
        cell=cell,
        samples=samples,
        n_successful=len(values),
        bytes_mean=200.0,
        bytes_ci_low=199.0,
        bytes_ci_high=201.0,
        time_mean=mean,
        time_ci_low=mean * 0.99,
        time_ci_high=mean * 1.01,
        measurable=True,
        is_baseline=True,
        baseline_role="m1_shared",
    )


class TestBaselineCV:
    def test_cv_within_threshold_passes(self) -> None:
        from vllm_grpc_bench.m4_sweep import check_baseline_cv

        # Stddev / mean ≈ 1% on this cohort — comfortably under the 5% default.
        values = [0.010, 0.0099, 0.0101, 0.0102, 0.0098, 0.0100] * 17  # 102 values
        cohort = _baseline_cohort(values)
        check_baseline_cv(cohort, max_cv=0.05)  # no raise

    def test_cv_exceeds_threshold_raises(self) -> None:
        from vllm_grpc_bench.m4_sweep import BaselineCVError, check_baseline_cv

        # Wide variance: cv > 0.05.
        values = [0.005, 0.015, 0.005, 0.015, 0.005, 0.015] * 17
        cohort = _baseline_cohort(values)
        with pytest.raises(BaselineCVError, match="exceeds"):
            check_baseline_cv(cohort, max_cv=0.05)
