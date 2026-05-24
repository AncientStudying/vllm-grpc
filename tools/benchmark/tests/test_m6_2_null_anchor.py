"""T020 — FR-012 / FR-013 null-anchor verdict + FR-014 sweep-level header.

Threshold model: pooled-CI-with-floor (B2, 2026-05-23). See
:mod:`vllm_grpc_bench.m6_2_null_anchor` for the formula. Tests use small
``floor_ms`` overrides where they need to exercise pure band semantics
without the 10 ms operational floor masking the boundary.
"""

from __future__ import annotations

from vllm_grpc_bench.m6_2_null_anchor import (
    DRIFT_THRESHOLD_FLOOR_FRACTION,
    DRIFT_THRESHOLD_FLOOR_MS,
    DRIFT_THRESHOLD_WARN_MULTIPLIER,
    compute_drift_verdict,
    compute_null_anchor_drift_header_fired,
    make_new_baseline_anchor,
    make_null_anchor,
    pooled_ci_half_width,
)


class TestB4RelativeCoFloor:
    """Round-8 amendment (T060): pooled-CI threshold now includes a
    ``floor_fraction × baseline_p50_ms`` relative co-floor on top of B2's
    10 ms absolute floor. Default is 2.5 % per
    :data:`DRIFT_THRESHOLD_FLOOR_FRACTION`.
    """

    def test_constant_pinned_at_2_5_percent(self) -> None:
        """B4 floor calibration is load-bearing; a silent drift would shift
        the WARN/FAIL boundary across the cell budget table."""
        assert DRIFT_THRESHOLD_FLOOR_FRACTION == 0.025

    def test_relative_floor_dominates_on_slow_baseline(self) -> None:
        # baseline p50 = 80_000 ms (chat_stream c=8 max_tokens=2048 regime);
        # 2.5% of that = 2000 ms — way above the 10 ms absolute floor.
        # Pooled threshold = 2000 ms; delta = 1500 ms → PASS (was WARN
        # under pre-B4 B2-only with pooled = max(0.2, 10) = 10 ms).
        pooled = pooled_ci_half_width(0.2, baseline_p50_ms=80_000.0)
        assert pooled == 2000.0
        assert compute_drift_verdict(81_500.0, 80_000.0, 0.2) == "PASS"

    def test_absolute_floor_dominates_on_fast_baseline(self) -> None:
        # baseline p50 = 200 ms (chat_stream anchor regime);
        # 2.5% of that = 5 ms — below the 10 ms absolute floor.
        # Pooled threshold = 10 ms (B2 wins).
        pooled = pooled_ci_half_width(0.2, baseline_p50_ms=200.0)
        assert pooled == 10.0

    def test_baseline_ci_dominates_when_largest(self) -> None:
        # baseline p50 = 1000 ms (2.5% = 25 ms); baseline CI = 80 ms wins.
        pooled = pooled_ci_half_width(80.0, baseline_p50_ms=1000.0)
        assert pooled == 80.0

    def test_m6_2_ci_dominates_when_largest(self) -> None:
        # baseline p50 = 1000 ms (2.5% = 25 ms); M6.2 block CI = 90 ms wins.
        pooled = pooled_ci_half_width(0.5, 90.0, baseline_p50_ms=1000.0)
        assert pooled == 90.0

    def test_b4_default_is_no_op_when_baseline_p50_omitted(self) -> None:
        """Pre-B4 callers (``baseline_p50_ms`` defaulted to 0) still get the
        pre-B4 B2-only behavior — backward-compatible default."""
        with_b4_default = pooled_ci_half_width(5.0)
        without_p50 = pooled_ci_half_width(5.0, baseline_p50_ms=0.0)
        assert with_b4_default == without_p50 == DRIFT_THRESHOLD_FLOOR_MS

    def test_compute_drift_verdict_threads_baseline_p50(self) -> None:
        """Verdict on slow-baseline cells uses B4's relative floor."""
        # baseline 80_000 ms, M6.2 80_500 ms → delta=500, pooled=2000 → PASS
        # (pre-B4 this would be FAIL: delta=500 > 3 × 10 ms = 30 ms FAIL band).
        assert compute_drift_verdict(80_500.0, 80_000.0, 0.2) == "PASS"
        # delta=3000, pooled=2000 → WARN (in 1× to 3× band: > 2000 and ≤ 6000).
        assert compute_drift_verdict(83_000.0, 80_000.0, 0.2) == "WARN"
        # delta=10_000 → FAIL (> 3 × 2000).
        assert compute_drift_verdict(90_000.0, 80_000.0, 0.2) == "FAIL"

    def test_floor_fraction_override(self) -> None:
        """Callers MAY tighten the relative co-floor (e.g., diagnostics)."""
        pooled = pooled_ci_half_width(0.2, baseline_p50_ms=1000.0, floor_fraction=0.05)
        assert pooled == 50.0  # 5% × 1000

    def test_negative_baseline_p50_coerced_to_zero(self) -> None:
        """Defensive: a malformed baseline (negative p50) reduces to B2."""
        pooled = pooled_ci_half_width(0.2, baseline_p50_ms=-1000.0)
        assert pooled == DRIFT_THRESHOLD_FLOOR_MS


class TestDriftVerdict:
    def test_inside_pooled_passes(self) -> None:
        # delta=2.5 ≤ pooled=5 → PASS (floor disabled so the CI dominates).
        assert compute_drift_verdict(102.5, 100.0, 5.0, floor_ms=0.0) == "PASS"
        assert compute_drift_verdict(95.0, 100.0, 5.0, floor_ms=0.0) == "PASS"

    def test_outside_pooled_in_warn_band(self) -> None:
        # pooled=20, warn band = (20, 60]; delta=25 → WARN.
        assert compute_drift_verdict(125.0, 100.0, 20.0, floor_ms=0.0) == "WARN"
        # Other side of zero.
        assert compute_drift_verdict(75.0, 100.0, 20.0, floor_ms=0.0) == "WARN"

    def test_outside_warn_multiplier_fails(self) -> None:
        # pooled=20, fail band > 60; delta=70 → FAIL.
        assert compute_drift_verdict(170.0, 100.0, 20.0, floor_ms=0.0) == "FAIL"
        assert compute_drift_verdict(30.0, 100.0, 20.0, floor_ms=0.0) == "FAIL"

    def test_floor_applies_when_baseline_ci_subms(self) -> None:
        """Sub-ms baseline CI (M6.1.3 chat_stream_c1 default_grpc is 0.14 ms)
        must NOT make small operationally-insignificant deltas FAIL."""
        # baseline_ci=0.2, delta=8 → pooled=max(0.2, 0, 10)=10, 8 ≤ 10 → PASS.
        assert compute_drift_verdict(108.0, 100.0, 0.2) == "PASS"
        # delta=15 > 10 but ≤ 30 → WARN.
        assert compute_drift_verdict(115.0, 100.0, 0.2) == "WARN"
        # delta=50 > 30 → FAIL.
        assert compute_drift_verdict(150.0, 100.0, 0.2) == "FAIL"

    def test_pooled_uses_m6_2_ci_when_larger(self) -> None:
        """If the M6.2 per-block CI is larger than M6.1.3's, the gate must
        widen — sweeps with naturally noisier blocks shouldn't trip on noise."""
        # baseline=2, m6_2=50, delta=40 → pooled=50, 40 ≤ 50 → PASS.
        assert (
            compute_drift_verdict(
                140.0, 100.0, m6_1_3_ci_half_width=2.0, m6_2_ci_half_width=50.0
            )
            == "PASS"
        )

    def test_pooled_uses_baseline_ci_when_larger(self) -> None:
        # baseline=100, m6_2=2, delta=80 → pooled=100, 80 ≤ 100 → PASS.
        assert (
            compute_drift_verdict(
                180.0, 100.0, m6_1_3_ci_half_width=100.0, m6_2_ci_half_width=2.0
            )
            == "PASS"
        )

    def test_negative_ci_inputs_coerced_to_zero_before_max(self) -> None:
        """Defense-in-depth: malformed negative CIs should not under-cut the
        floor (the max-with-floor still applies)."""
        assert (
            compute_drift_verdict(
                108.0, 100.0, m6_1_3_ci_half_width=-5.0, m6_2_ci_half_width=-5.0
            )
            == "PASS"
        )

    def test_module_constants_unchanged(self) -> None:
        """Lock the floor + multiplier so accidental edits to the constants
        get caught by CI rather than silently shifting verdict thresholds."""
        assert DRIFT_THRESHOLD_FLOOR_MS == 10.0
        assert DRIFT_THRESHOLD_WARN_MULTIPLIER == 3.0


class TestPooledCIHelper:
    def test_returns_floor_when_all_inputs_below(self) -> None:
        assert pooled_ci_half_width(0.5, 0.5) == DRIFT_THRESHOLD_FLOOR_MS

    def test_returns_baseline_when_dominant(self) -> None:
        assert pooled_ci_half_width(50.0, 2.0) == 50.0

    def test_returns_m6_2_when_dominant(self) -> None:
        assert pooled_ci_half_width(2.0, 50.0) == 50.0

    def test_custom_floor_honored(self) -> None:
        assert pooled_ci_half_width(2.0, 3.0, floor_ms=20.0) == 20.0


class TestCrossCheckableAnchor:
    def test_pass_anchor(self) -> None:
        # delta=2, pooled=max(5,0,10)=10, 2 ≤ 10 → PASS.
        anchor = make_null_anchor(
            cell_id="chat_stream_c1",
            cohort="default_grpc",
            max_tokens=50,
            m6_2_wall_p50_ms=102.0,
            m6_1_3_wall_p50_ms=100.0,
            m6_1_3_ci_half_width=5.0,
        )
        assert anchor.drift_verdict == "PASS"
        assert anchor.new_baseline_marker is False
        assert anchor.drift_fraction is not None
        # drift_fraction = delta / pooled = 2/10 = 0.2
        assert anchor.drift_fraction == 0.2

    def test_failed_block_fails_verdict(self) -> None:
        anchor = make_null_anchor(
            cell_id="chat_stream_c1",
            cohort="default_grpc",
            max_tokens=50,
            m6_2_wall_p50_ms=None,
            m6_1_3_wall_p50_ms=100.0,
            m6_1_3_ci_half_width=5.0,
        )
        assert anchor.drift_verdict == "FAIL"
        assert anchor.drift_fraction is None

    def test_m6_2_ci_widens_threshold(self) -> None:
        # delta=40, baseline_ci=2, m6_2_ci=50 → pooled=50, 40 ≤ 50 → PASS.
        anchor = make_null_anchor(
            cell_id="chat_stream_c1",
            cohort="default_grpc",
            max_tokens=50,
            m6_2_wall_p50_ms=140.0,
            m6_1_3_wall_p50_ms=100.0,
            m6_1_3_ci_half_width=2.0,
            m6_2_ci_half_width=50.0,
        )
        assert anchor.drift_verdict == "PASS"
        # drift_fraction reported against the pooled width too: 40/50 = 0.8.
        assert anchor.drift_fraction == 0.8


class TestNewBaselineAnchor:
    def test_new_baseline_carries_marker_no_verdict(self) -> None:
        anchor = make_new_baseline_anchor(
            cell_id="chat_stream_c1",
            cohort="default_grpc",
            max_tokens=10,
            m6_2_wall_p50_ms=120.0,
        )
        assert anchor.new_baseline_marker is True
        assert anchor.drift_verdict is None
        assert anchor.m6_1_3_wall_p50_ms is None
        assert anchor.m6_1_3_ci_half_width is None


class TestSweepLevelHeader:
    def test_fires_at_2_drifted_cross_checkable(self) -> None:
        """With the 10 ms floor, deltas must clear ~10 ms to enter WARN. Use
        deltas in {0, 15, 30, 45, ...} so i=1..7 all carry WARN/FAIL → ≥2."""
        anchors = [
            make_null_anchor(
                cell_id=f"chat_stream_c{i}",
                cohort="default_grpc",
                max_tokens=50,
                m6_2_wall_p50_ms=100.0 + i * 15.0,
                m6_1_3_wall_p50_ms=100.0,
                m6_1_3_ci_half_width=2.0,
            )
            for i in range(8)
        ]
        # pooled=10; i=0 PASS; i=1 delta=15 → WARN; i>=4 delta>=60 wraps to FAIL.
        assert compute_null_anchor_drift_header_fired(anchors) is True

    def test_does_not_fire_at_1_drifted(self) -> None:
        anchors = [
            make_null_anchor(
                cell_id="chat_stream_c1",
                cohort="default_grpc",
                max_tokens=50,
                m6_2_wall_p50_ms=120.0,  # delta=20, pooled=10, WARN
                m6_1_3_wall_p50_ms=100.0,
                m6_1_3_ci_half_width=5.0,
            ),
            make_null_anchor(
                cell_id="chat_stream_c4",
                cohort="default_grpc",
                max_tokens=50,
                m6_2_wall_p50_ms=105.0,  # delta=5, pooled=10, PASS
                m6_1_3_wall_p50_ms=100.0,
                m6_1_3_ci_half_width=5.0,
            ),
        ]
        assert compute_null_anchor_drift_header_fired(anchors) is False

    def test_new_baseline_excluded_from_count(self) -> None:
        # 1 cross-checkable that fails + 2 new-baseline anchors — header
        # should NOT fire because new-baseline don't count toward threshold.
        anchors = [
            make_null_anchor(
                cell_id="chat_stream_c1",
                cohort="default_grpc",
                max_tokens=50,
                m6_2_wall_p50_ms=200.0,  # delta=100, pooled=10, FAIL
                m6_1_3_wall_p50_ms=100.0,
                m6_1_3_ci_half_width=5.0,
            ),
            make_new_baseline_anchor(
                cell_id="embed_c1",
                cohort="default_grpc",
                max_tokens=50,
                m6_2_wall_p50_ms=130.0,
            ),
            make_new_baseline_anchor(
                cell_id="embed_c4",
                cohort="default_grpc",
                max_tokens=50,
                m6_2_wall_p50_ms=130.0,
            ),
        ]
        assert compute_null_anchor_drift_header_fired(anchors) is False

    def test_fires_at_2_cross_checkable_drifted_even_with_new_baselines(self) -> None:
        anchors = [
            make_null_anchor(
                cell_id="chat_stream_c1",
                cohort="default_grpc",
                max_tokens=50,
                m6_2_wall_p50_ms=200.0,
                m6_1_3_wall_p50_ms=100.0,
                m6_1_3_ci_half_width=5.0,
            ),
            make_null_anchor(
                cell_id="chat_stream_c4",
                cohort="default_grpc",
                max_tokens=50,
                m6_2_wall_p50_ms=200.0,
                m6_1_3_wall_p50_ms=100.0,
                m6_1_3_ci_half_width=5.0,
            ),
            make_new_baseline_anchor(
                cell_id="embed_c1",
                cohort="default_grpc",
                max_tokens=50,
                m6_2_wall_p50_ms=200.0,
            ),
        ]
        assert compute_null_anchor_drift_header_fired(anchors) is True
