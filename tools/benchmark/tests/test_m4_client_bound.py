"""US1 / FR-004 / R-5 — client_bound cohort detection.

A candidate cohort whose mean delta vs. its baseline is *smaller* than the
baseline's within-cohort std-dev is tagged ``client_bound`` and excluded
from ``recommend`` tallies.
"""

from __future__ import annotations

from vllm_grpc_bench.channel_config import COMPRESSION_GZIP, M1_BASELINE
from vllm_grpc_bench.m3_types import BenchmarkCell, RunCohort, Sample


def _cohort(
    *,
    config_name: str,
    wall_clock_values: list[float],
) -> RunCohort:
    cfg = M1_BASELINE if config_name == "m1-baseline" else COMPRESSION_GZIP
    cell = BenchmarkCell(
        path="embed",
        hidden_size=4096,
        channel_config=cfg,
        corpus_subset="m1_embed",
        iterations=len(wall_clock_values),
    )
    samples = tuple(
        Sample(
            cell_id=cell.cell_id,
            iteration=i,
            request_wire_bytes=100,
            response_wire_bytes=100,
            wall_clock_seconds=v,
        )
        for i, v in enumerate(wall_clock_values)
    )
    mean = sum(wall_clock_values) / len(wall_clock_values)
    return RunCohort(
        cell=cell,
        samples=samples,
        n_successful=len(wall_clock_values),
        bytes_mean=200.0,
        bytes_ci_low=199.0,
        bytes_ci_high=201.0,
        time_mean=mean,
        time_ci_low=mean * 0.99,
        time_ci_high=mean * 1.01,
        measurable=True,
    )


class TestClientBoundDetection:
    def test_below_jitter_floor_tagged(self) -> None:
        from vllm_grpc_bench.m4_sweep import is_client_bound

        # Baseline with stddev ~ 0.001 around 0.01.  Candidate's mean is
        # 0.0095 — only 0.0005 lower than baseline mean (below the 0.001
        # baseline jitter), so the cohort is client_bound.
        baseline_values = [0.009, 0.010, 0.011] * 34  # 102 values
        candidate_values = [0.0094, 0.0095, 0.0096] * 34
        baseline = _cohort(config_name="m1-baseline", wall_clock_values=baseline_values)
        candidate = _cohort(config_name="compression-gzip", wall_clock_values=candidate_values)
        assert is_client_bound(baseline, candidate) is True

    def test_above_jitter_floor_not_tagged(self) -> None:
        from vllm_grpc_bench.m4_sweep import is_client_bound

        baseline_values = [0.009, 0.010, 0.011] * 34
        # Candidate mean 0.005 — half the baseline mean, well above jitter.
        candidate_values = [0.0049, 0.005, 0.0051] * 34
        baseline = _cohort(config_name="m1-baseline", wall_clock_values=baseline_values)
        candidate = _cohort(config_name="compression-gzip", wall_clock_values=candidate_values)
        assert is_client_bound(baseline, candidate) is False
