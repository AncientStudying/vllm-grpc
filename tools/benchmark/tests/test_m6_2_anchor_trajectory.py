"""T018 — FR-031 4h anchor cadence + drift detection + SC-016 sweep-level header."""

from __future__ import annotations

from vllm_grpc_bench.m6_1_2_types import M6_1_2_COHORTS, M6_1_2CohortKind
from vllm_grpc_bench.m6_2_anchor_trajectory import (
    AnchorRPCDriver,
    compute_anchor_block,
    compute_anchor_latency_trajectory,
    compute_intra_sweep_drift_header_fired,
)
from vllm_grpc_bench.m6_2_sweep import should_run_anchor_at
from vllm_grpc_bench.m6_2_types import M6_2AnchorLatencySnapshot, M6_2AnchorLatencyTrajectory


def _stub_rpc_driver(
    values_by_cohort: dict[M6_1_2CohortKind, list[float]],
) -> AnchorRPCDriver:
    async def driver(
        *,
        cohort: M6_1_2CohortKind,
        n: int,
        base_seed: int,
        seed_offset: int,
    ) -> list[float]:
        del n, base_seed, seed_offset
        return list(values_by_cohort.get(cohort, []))

    return driver


def _snapshot(p50: float, hour: float) -> M6_2AnchorLatencySnapshot:
    return M6_2AnchorLatencySnapshot(
        wall_p50_ms=p50,
        wall_p95_ms=p50 * 1.1,
        wall_p99_ms=p50 * 1.2,
        snapshot_timestamp=f"2026-05-20T0{int(hour) % 24}:00:00Z",
        sweep_hour_mark=hour,
    )


class TestAnchorBlock:
    async def test_per_cohort_snapshot_built_from_rpc_driver(self) -> None:
        values: dict[M6_1_2CohortKind, list[float]] = {
            c: [10.0, 12.0, 14.0, 16.0, 18.0] for c in M6_1_2_COHORTS
        }
        snapshots = await compute_anchor_block(
            cohorts=list(M6_1_2_COHORTS),
            rpc_driver=_stub_rpc_driver(values),
            base_seed=42,
            sweep_hour_mark=0.0,
        )
        assert set(snapshots.keys()) == set(M6_1_2_COHORTS)
        for cohort in M6_1_2_COHORTS:
            assert snapshots[cohort].wall_p50_ms > 0
            assert snapshots[cohort].sweep_hour_mark == 0.0

    async def test_empty_cohort_skipped(self) -> None:
        values: dict[M6_1_2CohortKind, list[float]] = {c: [] for c in M6_1_2_COHORTS}
        values["default_grpc"] = [10.0, 20.0]
        snapshots = await compute_anchor_block(
            cohorts=list(M6_1_2_COHORTS),
            rpc_driver=_stub_rpc_driver(values),
            base_seed=42,
            sweep_hour_mark=4.0,
        )
        assert "default_grpc" in snapshots
        # Cohorts that produced 0 samples don't get a snapshot.
        for cohort in M6_1_2_COHORTS:
            if cohort != "default_grpc":
                assert cohort not in snapshots


class TestTrajectoryAndDrift:
    def test_trajectory_drift_fires_above_baseline_ci(self) -> None:
        # Spread 50.0 - 10.0 = 40.0; baseline CI half-width 5.0 → fires.
        traj = compute_anchor_latency_trajectory(
            {
                "default_grpc": [_snapshot(10.0, 0.0), _snapshot(50.0, 4.0)],
            },
            m6_1_3_baseline_ci_half_width=5.0,
        )
        assert traj["default_grpc"].latency_drift_warning is True
        assert traj["default_grpc"].max_minus_min_wall_p50_ms == 40.0

    def test_trajectory_drift_does_not_fire_when_inside_ci(self) -> None:
        traj = compute_anchor_latency_trajectory(
            {
                "default_grpc": [_snapshot(10.0, 0.0), _snapshot(11.0, 4.0)],
            },
            m6_1_3_baseline_ci_half_width=5.0,
        )
        assert traj["default_grpc"].latency_drift_warning is False

    def test_single_snapshot_no_drift_warning(self) -> None:
        traj = compute_anchor_latency_trajectory(
            {"default_grpc": [_snapshot(10.0, 0.0)]},
            m6_1_3_baseline_ci_half_width=5.0,
        )
        assert traj["default_grpc"].latency_drift_warning is False
        assert traj["default_grpc"].max_minus_min_wall_p50_ms == 0.0


class TestSC016SweepLevelHeader:
    def test_header_fires_at_2_of_4_drifted(self) -> None:
        traj: dict[M6_1_2CohortKind, M6_2AnchorLatencyTrajectory] = {
            "default_grpc": _make_trajectory("default_grpc", drift=True),
            "tuned_grpc_multiplexed": _make_trajectory("tuned_grpc_multiplexed", drift=True),
            "rest_https_edge": _make_trajectory("rest_https_edge", drift=False),
            "rest_plain_tcp": _make_trajectory("rest_plain_tcp", drift=False),
        }
        assert compute_intra_sweep_drift_header_fired(traj) is True

    def test_header_does_not_fire_at_1_of_4_drifted(self) -> None:
        traj: dict[M6_1_2CohortKind, M6_2AnchorLatencyTrajectory] = {
            "default_grpc": _make_trajectory("default_grpc", drift=True),
            "tuned_grpc_multiplexed": _make_trajectory("tuned_grpc_multiplexed", drift=False),
            "rest_https_edge": _make_trajectory("rest_https_edge", drift=False),
            "rest_plain_tcp": _make_trajectory("rest_plain_tcp", drift=False),
        }
        assert compute_intra_sweep_drift_header_fired(traj) is False


def _make_trajectory(cohort: str, *, drift: bool) -> M6_2AnchorLatencyTrajectory:
    from vllm_grpc_bench.m6_2_types import M6_2AnchorLatencyTrajectory

    return M6_2AnchorLatencyTrajectory(
        cohort=cohort,  # type: ignore[arg-type]
        snapshots=[_snapshot(10.0, 0.0), _snapshot(50.0, 4.0)],
        max_minus_min_wall_p50_ms=40.0,
        latency_drift_warning=drift,
    )


class TestCadenceRule:
    def test_sweep_start_always_fires(self) -> None:
        assert should_run_anchor_at(0.0, "publish") is True
        assert should_run_anchor_at(0.0, "validate") is True

    def test_publish_fires_at_4h_marks(self) -> None:
        assert should_run_anchor_at(4.0, "publish") is True
        assert should_run_anchor_at(8.0, "publish") is True
        assert should_run_anchor_at(12.0, "publish") is True

    def test_publish_does_not_fire_at_non_4h_marks(self) -> None:
        assert should_run_anchor_at(1.0, "publish") is False
        assert should_run_anchor_at(3.0, "publish") is False
        assert should_run_anchor_at(5.0, "publish") is False

    def test_validate_2_3h_sweep_skips_4h_marks(self) -> None:
        # validate mode + total < 8h → only start/end fire.
        assert should_run_anchor_at(2.0, "validate", total_sweep_hours=2.5) is False
        assert should_run_anchor_at(2.5, "validate", total_sweep_hours=2.5) is True
        assert should_run_anchor_at(0.0, "validate", total_sweep_hours=2.5) is True

    def test_validate_long_sweep_uses_publish_cadence(self) -> None:
        # validate mode + total >= 8h → 4h cadence resumes.
        assert should_run_anchor_at(4.0, "validate", total_sweep_hours=10.0) is True
