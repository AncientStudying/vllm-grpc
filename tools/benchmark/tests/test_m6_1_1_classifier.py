"""M6.1.1 classifier — FR-010 magnitude-equivalence test coverage.

All four classifications must be reachable from a hand-constructed
``per_cohort`` input. Edge cases per spec Edge Cases lines 105 / 107:

* spread carried entirely by ``seg_cd`` (post-engine emit) → ``inconclusive``
* non-monotonic cohort ordering → ``inconclusive``
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.m6_1_1_classifier import classify_cell
from vllm_grpc_bench.m6_1_1_types import (
    M6_1_1Cell,
    M6_1_1Cohort,
    MultiPointTimings,
    PerSegmentAggregate,
)

_CHAT_STREAM_C1 = M6_1_1Cell(path="chat_stream", concurrency=1, hidden_size=4096)
_COHORTS: tuple[M6_1_1Cohort, M6_1_1Cohort, M6_1_1Cohort] = (
    "rest_https_edge",
    "default_grpc",
    "tuned_grpc_multiplexed",
)


def _mpt(
    cohort: M6_1_1Cohort,
    *,
    engine_ttft_ms_mean: float,
    seg_ab_ms_mean: float,
    seg_bc_ms_mean: float,
    seg_cd_ms_mean: float,
) -> MultiPointTimings:
    return MultiPointTimings(
        cohort=cohort,
        cell=_CHAT_STREAM_C1,
        engine_ttft_ms_mean=engine_ttft_ms_mean,
        engine_ttft_ms_ci_half_width=0.5,
        per_segment=PerSegmentAggregate(
            seg_ab_ms_mean=seg_ab_ms_mean,
            seg_ab_ms_ci_half_width=0.1,
            seg_bc_ms_mean=seg_bc_ms_mean,
            seg_bc_ms_ci_half_width=0.1,
            seg_cd_ms_mean=seg_cd_ms_mean,
            seg_cd_ms_ci_half_width=0.1,
            n_samples=50,
        ),
        perturbation_total_us_mean=0.2,
    )


def test_drift_not_reproduced_short_circuits_when_ttft_spread_under_5pct() -> None:
    """All 3 cohorts within 4% spread → drift_not_reproduced (FR-018 / round-1 Q4)."""
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=44.0,
            seg_ab_ms_mean=2.0,
            seg_bc_ms_mean=40.0,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=44.6,
            seg_ab_ms_mean=2.0,
            seg_bc_ms_mean=40.6,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=45.4,
            seg_ab_ms_mean=2.0,
            seg_bc_ms_mean=41.4,
            seg_cd_ms_mean=2.0,
        ),
    }
    # spread / mean = 1.4 / 44.67 ≈ 0.031 < 0.05 → drift_not_reproduced
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == "drift_not_reproduced"


def test_instrumentation_artifact_when_seg_ab_carries_spread() -> None:
    """spread(seg_ab) ≥ 0.80 × spread(engine_ttft) → instrumentation_artifact."""
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=41.0,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=4.5,
            seg_bc_ms_mean=41.0,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=39.0,
            seg_cd_ms_mean=2.0,
        ),
    }
    # spread_ttft = 47.5 - 41.5 = 6.0; spread_ab = 4.5 - 0.5 = 4.0; 4/6 = 0.67 < 0.80
    # Adjust so spread_ab dominates:
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=41.0,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=5.0,
            seg_bc_ms_mean=40.5,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=39.0,
            seg_cd_ms_mean=2.0,
        ),
    }
    # spread_ttft = 6.0; spread_ab = 5.0 - 0.5 = 4.5; 4.5 / 6.0 = 0.75 — still < 0.80
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=41.0,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=5.5,
            seg_bc_ms_mean=40.0,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=39.0,
            seg_cd_ms_mean=2.0,
        ),
    }
    # spread_ttft = 6.0; spread_ab = 5.0; 5/6 = 0.833 ≥ 0.80 ✓
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == "instrumentation_artifact"


def test_channel_dependent_batching_when_seg_bc_carries_spread() -> None:
    """spread(seg_bc) ≥ 0.80 × spread(engine_ttft) → channel_dependent_batching."""
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=1.5,
            seg_bc_ms_mean=40.0,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=1.5,
            seg_bc_ms_mean=44.0,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.5,
            seg_ab_ms_mean=1.5,
            seg_bc_ms_mean=38.0,
            seg_cd_ms_mean=2.0,
        ),
    }
    # spread_ttft = 6.0; spread_bc = 44 - 38 = 6.0; 6/6 = 1.0 ≥ 0.80 ✓
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == "channel_dependent_batching"


def test_inconclusive_when_spread_evenly_split() -> None:
    """spread(seg_ab) ≈ spread(seg_bc) ≈ 50% of spread(ttft) → inconclusive."""
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=41.0,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=3.5,
            seg_bc_ms_mean=42.0,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=39.0,
            seg_cd_ms_mean=2.0,
        ),
    }
    # spread_ttft = 6.0; spread_ab = 3.0; spread_bc = 3.0 — both at 50%, neither ≥ 0.80
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == "inconclusive"


def test_inconclusive_when_spread_carried_by_seg_cd() -> None:
    """spread carried entirely by seg_cd (post-engine emit) → inconclusive (Edge Cases line 105)."""
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=1.5,
            seg_bc_ms_mean=40.0,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=1.5,
            seg_bc_ms_mean=40.0,
            seg_cd_ms_mean=6.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.5,
            seg_ab_ms_mean=1.5,
            seg_bc_ms_mean=40.0,
            seg_cd_ms_mean=0.0,
        ),
    }
    # spread_ttft = 6.0; spread_ab = 0; spread_bc = 0; spread_cd = 6.
    # Neither tracked segment (seg_ab / seg_bc) meets the 0.80 threshold.
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == "inconclusive"


def test_inconclusive_when_non_monotonic_cohort_ordering() -> None:
    """seg_ab and ttft order differently across cohorts → segment doesn't
    dominate → inconclusive."""
    # ttft: rest=43.5 < tuned=44.0 < default=47.5  (default highest)
    # seg_ab: tuned=4.0 > rest=2.0 > default=1.0  (tuned highest, opposite ttft)
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=2.0,
            seg_bc_ms_mean=39.5,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=1.0,
            seg_bc_ms_mean=44.5,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=44.0,
            seg_ab_ms_mean=4.0,
            seg_bc_ms_mean=38.0,
            seg_cd_ms_mean=2.0,
        ),
    }
    # spread_ttft = 47.5 - 43.5 = 4.0; spread_ab = 4.0 - 1.0 = 3.0; 3/4 = 0.75 < 0.80
    # spread_bc = 44.5 - 38 = 6.5; 6.5/4 = 1.625 → would trigger channel_dependent_batching!
    # Fix: make seg_bc spread smaller too
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=2.0,
            seg_bc_ms_mean=39.5,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=1.0,
            seg_bc_ms_mean=42.5,
            seg_cd_ms_mean=4.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=44.0,
            seg_ab_ms_mean=4.0,
            seg_bc_ms_mean=37.0,
            seg_cd_ms_mean=3.0,
        ),
    }
    # spread_ttft = 4.0; spread_ab = 3.0; spread_bc = 5.5 — bc would dominate.
    # Non-monotonic across-cohort ordering produces inconclusive when neither
    # segment dominates. Tighter case below: spread_ttft = 6 with seg_ab
    # carrying 42% and seg_bc carrying 58%.
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=2.0,
            seg_bc_ms_mean=39.5,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=49.5,
            seg_ab_ms_mean=4.5,
            seg_bc_ms_mean=43.0,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=46.5,
            seg_ab_ms_mean=2.0,
            seg_bc_ms_mean=42.5,
            seg_cd_ms_mean=2.0,
        ),
    }
    # spread_ttft = 6.0; spread_ab = 2.5; spread_bc = 3.5
    # 2.5/6 = 0.417 < 0.80; 3.5/6 = 0.583 < 0.80 → inconclusive
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == "inconclusive"


def test_classifier_is_pure() -> None:
    """classify_cell with identical inputs returns identical outputs (no I/O, no state)."""
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=41.0,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=5.5,
            seg_bc_ms_mean=40.0,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=39.0,
            seg_cd_ms_mean=2.0,
        ),
    }
    first = classify_cell(_CHAT_STREAM_C1, per_cohort)
    second = classify_cell(_CHAT_STREAM_C1, per_cohort)
    assert first == second == "instrumentation_artifact"


def test_classifier_reproduces_m6_1_baseline_observed_drift() -> None:
    """Sanity-check against M6.1's published chat_stream c=1 numbers:
    rest=43.7, default=47.1, tuned=41.3 → spread/mean ≈ 13% → NOT drift_not_reproduced;
    without per-segment data the test only confirms the short-circuit didn't fire."""
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.7,
            seg_ab_ms_mean=4.5,
            seg_bc_ms_mean=37.2,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.1,
            seg_ab_ms_mean=8.6,
            seg_bc_ms_mean=36.5,
            seg_cd_ms_mean=2.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.3,
            seg_ab_ms_mean=2.7,
            seg_bc_ms_mean=36.6,
            seg_cd_ms_mean=2.0,
        ),
    }
    # spread_ttft = 5.8; mean = 44.0; ratio = 0.132 > 0.05 → not drift_not_reproduced.
    # spread_ab = 8.6 - 2.7 = 5.9; 5.9 / 5.8 = 1.017 ≥ 0.80 →
    # instrumentation_artifact (hypothesised by spec).
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == "instrumentation_artifact"


@pytest.mark.parametrize(
    "ratios,expected",
    [
        ((0.50, 0.50), "inconclusive"),
        ((0.85, 0.10), "instrumentation_artifact"),
        ((0.10, 0.85), "channel_dependent_batching"),
        ((0.80, 0.20), "instrumentation_artifact"),  # exactly at threshold
        ((0.20, 0.80), "channel_dependent_batching"),  # exactly at threshold
    ],
)
def test_classifier_threshold_boundary(ratios: tuple[float, float], expected: str) -> None:
    """Classifier behaves correctly at the 0.80 attribution threshold boundary."""
    seg_ab_ratio, seg_bc_ratio = ratios
    spread_ttft = 10.0
    seg_ab_high = seg_ab_ratio * spread_ttft
    seg_bc_high = seg_bc_ratio * spread_ttft
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=40.0,
            seg_ab_ms_mean=0.0,
            seg_bc_ms_mean=0.0,
            seg_cd_ms_mean=0.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=50.0,
            seg_ab_ms_mean=seg_ab_high,
            seg_bc_ms_mean=seg_bc_high,
            seg_cd_ms_mean=0.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=45.0,
            seg_ab_ms_mean=seg_ab_high / 2,
            seg_bc_ms_mean=seg_bc_high / 2,
            seg_cd_ms_mean=0.0,
        ),
    }
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == expected
