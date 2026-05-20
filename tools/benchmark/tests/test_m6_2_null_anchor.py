"""T020 — FR-012 / FR-013 null-anchor verdict + FR-014 sweep-level header."""

from __future__ import annotations

from vllm_grpc_bench.m6_2_null_anchor import (
    compute_drift_verdict,
    compute_null_anchor_drift_header_fired,
    make_new_baseline_anchor,
    make_null_anchor,
)


class TestDriftVerdict:
    def test_inside_ci_passes(self) -> None:
        assert compute_drift_verdict(100.0, 100.0, 5.0) == "PASS"
        assert compute_drift_verdict(102.5, 100.0, 5.0) == "PASS"
        assert compute_drift_verdict(95.0, 100.0, 5.0) == "PASS"

    def test_outside_ci_but_within_2x_warns(self) -> None:
        assert compute_drift_verdict(108.0, 100.0, 5.0) == "WARN"
        assert compute_drift_verdict(110.0, 100.0, 5.0) == "WARN"
        assert compute_drift_verdict(92.0, 100.0, 5.0) == "WARN"

    def test_outside_2x_fails(self) -> None:
        assert compute_drift_verdict(115.0, 100.0, 5.0) == "FAIL"
        assert compute_drift_verdict(80.0, 100.0, 5.0) == "FAIL"


class TestCrossCheckableAnchor:
    def test_pass_anchor(self) -> None:
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
    def test_fires_at_2_of_22_drifted(self) -> None:
        anchors = [
            make_null_anchor(
                cell_id=f"chat_stream_c{i}",
                cohort="default_grpc",
                max_tokens=50,
                m6_2_wall_p50_ms=100.0 + i,  # alternate inside/outside
                m6_1_3_wall_p50_ms=100.0,
                m6_1_3_ci_half_width=2.0,
            )
            for i in range(8)
        ]
        # i=3 is +3 → WARN; i=4 → WARN; i=5+ → WARN/FAIL
        assert compute_null_anchor_drift_header_fired(anchors) is True

    def test_does_not_fire_at_1_drifted(self) -> None:
        anchors = [
            make_null_anchor(
                cell_id="chat_stream_c1",
                cohort="default_grpc",
                max_tokens=50,
                m6_2_wall_p50_ms=110.0,  # WARN (delta=10, ci_half=5 → 1<x<=2)
                m6_1_3_wall_p50_ms=100.0,
                m6_1_3_ci_half_width=5.0,
            ),
            make_null_anchor(
                cell_id="chat_stream_c4",
                cohort="default_grpc",
                max_tokens=50,
                m6_2_wall_p50_ms=101.0,
                m6_1_3_wall_p50_ms=100.0,
                m6_1_3_ci_half_width=5.0,
            ),
        ]
        assert compute_null_anchor_drift_header_fired(anchors) is False

    def test_new_baseline_excluded_from_count(self) -> None:
        # 1 cross-checkable that fails + 4 new-baseline anchors — header
        # should NOT fire because new-baseline don't count toward threshold.
        anchors = [
            make_null_anchor(
                cell_id="chat_stream_c1",
                cohort="default_grpc",
                max_tokens=50,
                m6_2_wall_p50_ms=130.0,  # FAIL
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
                m6_2_wall_p50_ms=130.0,
                m6_1_3_wall_p50_ms=100.0,
                m6_1_3_ci_half_width=5.0,
            ),
            make_null_anchor(
                cell_id="chat_stream_c4",
                cohort="default_grpc",
                max_tokens=50,
                m6_2_wall_p50_ms=130.0,
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
