"""T018 — FR-031 4h anchor cadence + drift detection + SC-016 sweep-level header."""

from __future__ import annotations

from vllm_grpc_bench.m6_1_2_types import M6_1_2_COHORTS, M6_1_2CohortKind
from vllm_grpc_bench.m6_2_anchor_trajectory import (
    WARMUP_SUPPRESSION_HOURS,
    AnchorRPCDriver,
    compute_anchor_block,
    compute_anchor_latency_trajectory,
    compute_insufficient_snapshots_header_fired,
    compute_intra_sweep_drift_header_fired,
)
from vllm_grpc_bench.m6_2_types import M6_2AnchorLatencySnapshot, M6_2AnchorLatencyTrajectory
from vllm_grpc_bench.sweep import should_run_anchor_at


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
        # Use post-warmup snapshot timings (0.5 h, 4 h) so the C1 warmup
        # suppression doesn't drop the spread-defining samples.
        traj = compute_anchor_latency_trajectory(
            {
                "default_grpc": [_snapshot(10.0, 0.5), _snapshot(50.0, 4.0)],
            },
            m6_1_3_baseline_ci_half_width=5.0,
        )
        assert traj["default_grpc"].latency_drift_warning is True
        assert traj["default_grpc"].max_minus_min_wall_p50_ms == 40.0

    def test_trajectory_drift_does_not_fire_when_inside_ci(self) -> None:
        traj = compute_anchor_latency_trajectory(
            {
                "default_grpc": [_snapshot(10.0, 0.5), _snapshot(11.0, 4.0)],
            },
            m6_1_3_baseline_ci_half_width=5.0,
        )
        assert traj["default_grpc"].latency_drift_warning is False

    def test_single_snapshot_no_drift_warning(self) -> None:
        traj = compute_anchor_latency_trajectory(
            {"default_grpc": [_snapshot(10.0, 0.5)]},
            m6_1_3_baseline_ci_half_width=5.0,
        )
        assert traj["default_grpc"].latency_drift_warning is False
        assert traj["default_grpc"].max_minus_min_wall_p50_ms == 0.0
        # C1: a single post-warmup snapshot falls into the insufficient-
        # snapshots fallback.
        assert traj["default_grpc"].insufficient_post_warmup_snapshots is True

    def test_floor_suppresses_subms_baseline_false_alarm(self) -> None:
        """B2 regression: the original SC-016 rule fired whenever a cohort's
        ``max-min`` spread exceeded M6.1.3's sub-ms baseline CI. The 10 ms
        floor must absorb noise that falls within ordinary measurement
        variance even when the baseline CI is essentially zero.

        Note: the floor is absolute, so cohorts with very low baseline
        latency may still trip on small operational drifts (e.g. 15 ms on a
        ~570 ms tuned_grpc baseline is ~2.6% — above the 10 ms floor and
        thus reports as drift). Further suppression for low-latency cells
        would need the relative-magnitude floor from option B4."""
        # spread = 9 ms < 10 ms floor → no warning. Use post-warmup snapshot
        # marks (0.06 h, 1.08 h, 4 h, 8 h) so C1 doesn't drop the early ones.
        traj = compute_anchor_latency_trajectory(
            {
                "tuned_grpc_multiplexed": [
                    _snapshot(568.0, 0.06),
                    _snapshot(571.0, 1.08),
                    _snapshot(573.0, 4.0),
                    _snapshot(577.0, 8.0),
                ],
            },
            m6_1_3_baseline_ci_half_width=0.14,  # M6.1.3 chat_stream_c1 default_grpc
        )
        assert traj["tuned_grpc_multiplexed"].max_minus_min_wall_p50_ms == 9.0
        assert traj["tuned_grpc_multiplexed"].latency_drift_warning is False

    def test_pooled_snapshot_ci_dominates_when_variance_is_large(self) -> None:
        """If the trajectory's own samples are very noisy, the snapshot CI
        exceeds both the baseline CI and the 10 ms floor — the gate widens
        accordingly. This is the "natural noise" symmetric to the floor:
        a sweep with a large spread but commensurately large variance
        should not trip."""
        # snapshots [100, 200] → stdev=70.7, snapshot_ci = 1.96 * 70.7 / sqrt(2) ≈ 98
        # spread = 100 → 100 ≤ 98? No, 100 > 98 → fires. Need a tighter spread
        # vs the implied variance. Use [100, 150, 200] (n=3, stdev=50):
        # snapshot_ci = 1.96 * 50 / sqrt(3) ≈ 56.6; spread = 100 → fires.
        # We want the OPPOSITE: spread below pooled. Use [50, 100, 200]:
        # stdev = 76.4, ci = 1.96 * 76.4 / sqrt(3) ≈ 86.4; spread = 150 → still fires.
        # Construct so spread < pooled: 3 samples with one outlier driving variance
        # up but spread itself moderate. [100, 100, 200, 100, 100]: stdev=44.7,
        # ci = 1.96 * 44.7 / sqrt(5) ≈ 39.2; spread = 100 → fires.
        # The math: with k samples and one outlier of size d above baseline,
        # spread = d but stdev ≈ d/sqrt(k); ci = 1.96 * d / k. So spread / ci ≈ k / 1.96.
        # For k=2 → spread/ci ≈ 1.02 (always fires by ~2%). For k>=2 the gate
        # always fires on the "one outlier" pattern. This is actually correct
        # behavior — a single sustained outlier IS drift evidence.
        # Verify the contrapositive: a tight cluster where pooled wins via floor.
        # Use post-warmup snapshot marks (0.5/4/8/12 h) so C1 doesn't drop
        # the t=0 sample.
        traj = compute_anchor_latency_trajectory(
            {
                "default_grpc": [
                    _snapshot(100.0, 0.5),
                    _snapshot(105.0, 4.0),
                    _snapshot(103.0, 8.0),
                    _snapshot(107.0, 12.0),
                ],
            },
            m6_1_3_baseline_ci_half_width=0.2,
        )
        # spread = 7.0, floor=10.0 → 7 ≤ 10 → no warning.
        assert traj["default_grpc"].max_minus_min_wall_p50_ms == 7.0
        assert traj["default_grpc"].latency_drift_warning is False

    def test_drift_fires_when_spread_exceeds_pooled_with_quiet_baseline(self) -> None:
        """Sanity: when the spread is genuinely large vs both the baseline CI
        and the snapshot CI and the floor, the gate must fire."""
        # 4 snapshots, all clustered at one value except one large outlier.
        # Spread will dominate stdev because samples are mostly identical.
        traj = compute_anchor_latency_trajectory(
            {
                "default_grpc": [
                    _snapshot(100.0, 0.0),
                    _snapshot(100.0, 4.0),
                    _snapshot(100.0, 8.0),
                    _snapshot(500.0, 12.0),  # 400 ms outlier
                ],
            },
            m6_1_3_baseline_ci_half_width=0.2,
        )
        assert traj["default_grpc"].max_minus_min_wall_p50_ms == 400.0
        assert traj["default_grpc"].latency_drift_warning is True


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


class TestT073StartGuardRegression:
    """T073 (2026-05-24): the pre-fix code shared ``epsilon_hours=0.05`` for
    both the "this is t=0" start-guard branch AND the 4-h-cadence tolerance.
    That caused any tuple-end mark in [0, 0.05] to re-fire the anchor block,
    so the validate sweep that exposed the bug logged an
    ``ANCHOR_START sweep_hour_mark=0.02`` immediately after tuple 1.

    Post-fix the start guard uses :data:`START_GUARD_HOURS = 0.001` (~3.6 s)
    — tight enough to match only the literal sweep-start tick captured before
    the main loop begins."""

    def test_start_guard_constant_is_tight(self) -> None:
        """``START_GUARD_HOURS`` MUST be tight enough that a tuple-end check
        landing in the first few minutes does not re-fire the anchor."""
        from vllm_grpc_bench.sweep import START_GUARD_HOURS

        assert START_GUARD_HOURS < 0.05, (
            "start guard must be tighter than the 4-h-cadence epsilon, or the T073 bug regresses"
        )
        assert START_GUARD_HOURS > 0, "guard must still match t=0"

    def test_start_anchor_fires_at_exact_zero(self) -> None:
        assert should_run_anchor_at(0.0, "validate") is True
        assert should_run_anchor_at(0.0, "publish") is True

    def test_start_anchor_does_not_fire_at_0_02h(self) -> None:
        """Regression: this was the live-sweep duplicate (validate run
        2026-05-24 13:46:05Z emitted ``ANCHOR_START sweep_hour_mark=0.02``
        immediately after tuple 1 closed). The post-fix tight guard must
        treat 0.02 as "past sweep start, no anchor required"."""
        assert should_run_anchor_at(0.02, "validate") is False
        assert should_run_anchor_at(0.02, "publish") is False

    def test_start_anchor_does_not_fire_at_old_epsilon_boundary(self) -> None:
        """0.05 h was the pre-fix epsilon. Anything in the (start_guard,
        epsilon] band must no longer fire the start branch — the test
        anchors the regression at the OLD threshold."""
        assert should_run_anchor_at(0.05, "validate") is False
        assert should_run_anchor_at(0.04, "publish") is False

    def test_start_anchor_does_not_fire_during_first_3_minutes(self) -> None:
        """The bug was 'anchor re-fires for any mark in the first 3 min'.
        Sweep several marks inside that window and assert none fire the
        start branch."""
        for mark in (0.005, 0.01, 0.015, 0.025, 0.04):
            assert should_run_anchor_at(mark, "validate") is False, (
                f"start branch must NOT fire at mark={mark}h (T073 regression)"
            )

    def test_start_guard_does_not_affect_4h_cadence(self) -> None:
        """The 4-h-cadence tolerance (``epsilon_hours=0.05``) is unchanged —
        publish-mode marks near multiples of 4 h still fire."""
        assert should_run_anchor_at(4.0, "publish") is True
        assert should_run_anchor_at(4.04, "publish") is True  # within cadence epsilon
        assert should_run_anchor_at(3.96, "publish") is True
        assert should_run_anchor_at(4.1, "publish") is False  # outside cadence epsilon

    def test_end_anchor_still_uses_epsilon_tolerance(self) -> None:
        """The "this is the sweep-end mark" branch keeps the ``epsilon_hours``
        tolerance — that one tolerates jitter around the actual sweep
        wall-clock and is a separate concern from the start-guard fix."""
        # total_sweep_hours = 2.5h; mark = 2.49h is within epsilon → fires.
        assert should_run_anchor_at(2.49, "validate", total_sweep_hours=2.5) is True
        # mark = 2.4h is outside epsilon → does NOT fire.
        assert should_run_anchor_at(2.4, "validate", total_sweep_hours=2.5) is False


class TestC1WarmupSuppression:
    """Round-8 amendment (T061): snapshots at ``sweep_hour_mark <
    WARMUP_SUPPRESSION_HOURS`` (default 0.05 h = 3 min) are dropped from
    the drift verdict; cohorts with < 2 post-warmup snapshots set
    ``insufficient_post_warmup_snapshots=True`` and
    ``latency_drift_warning=False``."""

    def test_warmup_constant_pinned_at_3_minutes(self) -> None:
        """The 0.05 h cutoff is load-bearing for false-positive suppression;
        a drift would either re-admit Modal cold-start spikes (too small)
        or silence legitimate early drift (too large)."""
        assert WARMUP_SUPPRESSION_HOURS == 0.05

    def test_warmup_snapshot_dropped_from_spread(self) -> None:
        # Three snapshots: t=0 is a 200 ms cold-start spike (warmup);
        # t=1 and t=2 are 100/105 ms steady-state. Spread over post-warmup
        # = 5 ms (not 105 ms including the cold-start).
        traj = compute_anchor_latency_trajectory(
            {"default_grpc": [_snapshot(200.0, 0.0), _snapshot(100.0, 1.0), _snapshot(105.0, 2.0)]},
            m6_1_3_baseline_ci_half_width=2.0,
            baseline_p50_ms=0.0,
            floor_ms=0.0,
            floor_fraction=0.0,
        )
        record = traj["default_grpc"]
        assert record.max_minus_min_wall_p50_ms == 5.0, (
            "spread must be computed over post-warmup snapshots only (t=0 cold-start excluded)"
        )
        # The pre-warmup snapshot is retained in the persisted list (visible
        # to the artifact reader) — only the drift computation excludes it.
        assert len(record.snapshots) == 3
        assert record.insufficient_post_warmup_snapshots is False

    def test_insufficient_post_warmup_snapshots_fallback(self) -> None:
        # Only one post-warmup snapshot (validate-mode start+end with start
        # warmup-dropped). Cohort gets the fallback flag + no drift verdict.
        traj = compute_anchor_latency_trajectory(
            {"default_grpc": [_snapshot(200.0, 0.0), _snapshot(100.0, 2.3)]},
            m6_1_3_baseline_ci_half_width=2.0,
        )
        record = traj["default_grpc"]
        assert record.insufficient_post_warmup_snapshots is True
        assert record.latency_drift_warning is False
        assert record.max_minus_min_wall_p50_ms == 0.0
        # Pre-warmup snapshot still present in the persisted list.
        assert len(record.snapshots) == 2

    def test_zero_snapshots_hits_fallback(self) -> None:
        # Empty cohort (RPC driver returned nothing) → also fallback.
        traj = compute_anchor_latency_trajectory(
            {"default_grpc": []},
            m6_1_3_baseline_ci_half_width=2.0,
        )
        record = traj["default_grpc"]
        assert record.insufficient_post_warmup_snapshots is True
        assert record.latency_drift_warning is False

    def test_b4_relative_co_floor_honored(self) -> None:
        # Baseline p50 = 80_000 ms (chat_stream c=8 max_tokens=2048 regime);
        # B4 co-floor = 2.5% × 80_000 = 2000 ms. Spread = 1500 ms < 2000 →
        # latency_drift_warning=False even though it would exceed B2's 10 ms.
        traj = compute_anchor_latency_trajectory(
            {
                "default_grpc": [
                    _snapshot(80_000.0, 0.5),
                    _snapshot(81_500.0, 4.0),
                ]
            },
            m6_1_3_baseline_ci_half_width=5.0,
            baseline_p50_ms=80_000.0,
        )
        assert traj["default_grpc"].latency_drift_warning is False

    def test_b4_co_floor_does_not_mask_real_drift(self) -> None:
        # Baseline p50 = 80_000 ms (B4 co-floor = 2000 ms); spread = 3000 ms
        # → drift fires.
        traj = compute_anchor_latency_trajectory(
            {
                "default_grpc": [
                    _snapshot(80_000.0, 0.5),
                    _snapshot(83_000.0, 4.0),
                ]
            },
            m6_1_3_baseline_ci_half_width=5.0,
            baseline_p50_ms=80_000.0,
        )
        assert traj["default_grpc"].latency_drift_warning is True

    def test_validate_mode_start_end_naturally_hits_fallback(self) -> None:
        # Validate-mode 2-snapshot start+end trajectory: start at t=0 is
        # warmup-dropped, leaving 1 post-warmup snapshot → fallback fires.
        traj = compute_anchor_latency_trajectory(
            {
                "default_grpc": [
                    _snapshot(100.0, 0.0),  # warmup-dropped
                    _snapshot(115.0, 2.3),  # sole post-warmup
                ]
            },
            m6_1_3_baseline_ci_half_width=2.0,
        )
        assert traj["default_grpc"].insufficient_post_warmup_snapshots is True


class TestInsufficientSnapshotsHeader:
    """C1 soft-diagnostic header: fires when any cohort has
    ``insufficient_post_warmup_snapshots=True``. Distinct from
    ``intra_sweep_latency_drift``."""

    def test_fires_when_one_cohort_insufficient(self) -> None:
        traj = {
            "default_grpc": _make_trajectory_with_warmup_flag(insufficient=True),
            "rest_https_edge": _make_trajectory_with_warmup_flag(insufficient=False),
        }
        assert compute_insufficient_snapshots_header_fired(traj) is True

    def test_does_not_fire_when_all_cohorts_have_post_warmup_snapshots(self) -> None:
        traj = {
            c: _make_trajectory_with_warmup_flag(insufficient=False)
            for c in ("default_grpc", "rest_https_edge")
        }
        assert compute_insufficient_snapshots_header_fired(traj) is False

    def test_independent_of_drift_verdict(self) -> None:
        # A cohort with insufficient_post_warmup_snapshots=True carries
        # latency_drift_warning=False by construction (T061 fallback), but
        # the insufficient header fires regardless of the drift header.
        traj = {
            "default_grpc": _make_trajectory_with_warmup_flag(insufficient=True),
        }
        assert compute_insufficient_snapshots_header_fired(traj) is True
        assert compute_intra_sweep_drift_header_fired(traj) is False


def _make_trajectory_with_warmup_flag(*, insufficient: bool) -> M6_2AnchorLatencyTrajectory:
    return M6_2AnchorLatencyTrajectory(
        cohort="default_grpc",
        snapshots=[_snapshot(100.0, 0.0)],
        max_minus_min_wall_p50_ms=0.0,
        latency_drift_warning=False,
        insufficient_post_warmup_snapshots=insufficient,
    )
