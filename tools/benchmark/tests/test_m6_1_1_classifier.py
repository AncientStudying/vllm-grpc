"""M6.1.1 classifier — FR-010 magnitude-equivalence test coverage.

The classifier was upgraded in M6.1.2 to a 5-bucket scheme using
engine-internal segments (``seg_queue``, ``seg_prefill``) derived from
vLLM's :class:`RequestStateStats`. The original four-checkpoint scheme had
``seg_bc ≡ engine_ttft`` by construction, making the attribution rule
degenerate. The new classifier uses ``seg_queue`` (queue wait, from
``scheduled_ts - queued_ts``) and ``seg_prefill`` (post-schedule engine
compute, from ``first_token_ts - scheduled_ts``).

Coverage:

* All 5 labels reachable from hand-constructed inputs.
* Legacy data (no engine-internal segments) falls back to a 3-bucket
  scheme that returns ``inconclusive`` when seg_ab doesn't dominate.
* Threshold boundary behaviour at the 0.80 attribution ratio.
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
    seg_queue_ms_mean: float | None = 0.0,
    seg_prefill_ms_mean: float | None = 0.0,
) -> MultiPointTimings:
    """Build a synthetic :class:`MultiPointTimings` for one cohort.

    ``seg_queue_ms_mean`` / ``seg_prefill_ms_mean`` default to 0.0 (engine
    segments present, no variation across cohorts) so tests that don't care
    about the M6.1.2 engine-internal attribution don't have to specify them.
    Pass ``None`` explicitly to simulate legacy data without the M6.1.2
    upgrade.
    """
    seg_queue_ci = None if seg_queue_ms_mean is None else 0.1
    seg_prefill_ci = None if seg_prefill_ms_mean is None else 0.1
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
            seg_queue_ms_mean=seg_queue_ms_mean,
            seg_queue_ms_ci_half_width=seg_queue_ci,
            seg_prefill_ms_mean=seg_prefill_ms_mean,
            seg_prefill_ms_ci_half_width=seg_prefill_ci,
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
    """spread(seg_ab) ≥ 0.80 × spread(engine_ttft) → instrumentation_artifact.

    spread_ttft = 47.5 - 41.5 = 6.0
    spread_ab = 5.5 - 0.5 = 5.0; 5.0 / 6.0 = 0.833 ≥ 0.80 ✓
    """
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
            seg_queue_ms_mean=20.0,  # variation in engine segments but seg_ab dominates
            seg_prefill_ms_mean=20.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=39.0,
            seg_cd_ms_mean=2.0,
        ),
    }
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == "instrumentation_artifact"


def test_channel_dependent_batching_when_seg_queue_carries_spread() -> None:
    """spread(seg_queue) ≥ 0.80 × spread(engine_ttft) → channel_dependent_batching.

    M6.1.2 semantics: seg_queue = scheduled_ts - queued_ts (scheduler queue wait).
    spread_ttft = 47.5 - 41.5 = 6.0
    spread_queue = 6.0 - 0.5 = 5.5; 5.5 / 6.0 = 0.917 ≥ 0.80 ✓
    """
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=41.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=2.0,
            seg_prefill_ms_mean=39.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=45.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=6.0,
            seg_prefill_ms_mean=39.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=39.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=0.5,
            seg_prefill_ms_mean=39.0,
        ),
    }
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == "channel_dependent_batching"


def test_engine_compute_variation_when_seg_prefill_carries_spread() -> None:
    """spread(seg_prefill) ≥ 0.80 × spread(engine_ttft) → engine_compute_variation.

    M6.1.2 new bucket. Queue wait is uniform; post-schedule engine compute
    varies per cohort (likely KV-cache or prompt-length artifact).
    spread_ttft = 47.5 - 41.5 = 6.0
    spread_prefill = 44.0 - 38.0 = 6.0; 6.0 / 6.0 = 1.0 ≥ 0.80 ✓
    """
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=41.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=2.0,
            seg_prefill_ms_mean=40.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=45.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=2.0,
            seg_prefill_ms_mean=44.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=39.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=2.0,
            seg_prefill_ms_mean=38.0,
        ),
    }
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == "engine_compute_variation"


def test_inconclusive_when_spread_split_between_engine_segments() -> None:
    """seg_queue and seg_prefill each carry ~50% of engine_ttft spread → inconclusive."""
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=41.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=1.0,
            seg_prefill_ms_mean=40.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=45.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=4.0,
            seg_prefill_ms_mean=43.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=39.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=1.0,
            seg_prefill_ms_mean=38.0,
        ),
    }
    # spread_ttft = 6.0; spread_queue = 3.0; spread_prefill = 5.0
    # 3/6 = 0.50 < 0.80; 5/6 = 0.833 ≥ 0.80 → engine_compute_variation actually
    # Adjust so neither dominates:
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=41.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=1.0,
            seg_prefill_ms_mean=40.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=45.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=4.0,
            seg_prefill_ms_mean=42.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=39.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=1.0,
            seg_prefill_ms_mean=39.0,
        ),
    }
    # spread_ttft = 6.0; spread_queue = 3.0 → 0.5; spread_prefill = 3.0 → 0.5
    # neither hits 0.80 → inconclusive
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == "inconclusive"


def test_inconclusive_when_spread_carried_by_seg_cd() -> None:
    """spread carried entirely by seg_cd (post-engine emit) is unphysical:
    engine_ttft is measured at first_chunk, so seg_cd (first_chunk → terminal_emit)
    cannot affect engine_ttft spread. Test the synthetic case anyway — classifier
    correctly returns inconclusive when no tracked segment dominates."""
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=1.5,
            seg_bc_ms_mean=40.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=2.0,
            seg_prefill_ms_mean=38.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=1.5,
            seg_bc_ms_mean=40.0,
            seg_cd_ms_mean=6.0,
            seg_queue_ms_mean=2.0,
            seg_prefill_ms_mean=38.0,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.5,
            seg_ab_ms_mean=1.5,
            seg_bc_ms_mean=40.0,
            seg_cd_ms_mean=0.0,
            seg_queue_ms_mean=2.0,
            seg_prefill_ms_mean=38.0,
        ),
    }
    # spread_ttft = 6.0; spread_ab = 0; spread_queue = 0; spread_prefill = 0.
    # No tracked segment meets the 0.80 threshold → inconclusive.
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == "inconclusive"


def test_inconclusive_when_legacy_data_missing_engine_segments() -> None:
    """Legacy data (pre-M6.1.2 instrumentation) has no seg_queue / seg_prefill.

    When seg_ab doesn't dominate (the typical case for real data), the
    classifier falls back to ``inconclusive`` rather than the degenerate
    ``channel_dependent_batching`` via seg_bc. Raw numbers in the report
    are the authoritative read.
    """
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=41.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=None,  # legacy: M6.1.2 segments absent
            seg_prefill_ms_mean=None,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=45.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=None,
            seg_prefill_ms_mean=None,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=39.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=None,
            seg_prefill_ms_mean=None,
        ),
    }
    # spread_ttft = 6.0; spread_ab = 0 < 0.80; no engine segments → inconclusive
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == "inconclusive"


def test_legacy_data_still_detects_instrumentation_artifact() -> None:
    """Legacy data with seg_ab dominance still classifies correctly."""
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=43.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=41.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=None,
            seg_prefill_ms_mean=None,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=47.5,
            seg_ab_ms_mean=5.5,
            seg_bc_ms_mean=40.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=None,
            seg_prefill_ms_mean=None,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=41.5,
            seg_ab_ms_mean=0.5,
            seg_bc_ms_mean=39.0,
            seg_cd_ms_mean=2.0,
            seg_queue_ms_mean=None,
            seg_prefill_ms_mean=None,
        ),
    }
    # spread_ab = 5.0; spread_ttft = 6.0; 5/6 ≥ 0.80 → instrumentation_artifact
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == "instrumentation_artifact"


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


@pytest.mark.parametrize(
    "ratios,expected",
    [
        # (seg_ab_ratio, seg_queue_ratio, seg_prefill_ratio)
        ((0.85, 0.10, 0.05), "instrumentation_artifact"),
        ((0.80, 0.10, 0.10), "instrumentation_artifact"),  # seg_ab exactly at threshold
        ((0.10, 0.85, 0.05), "channel_dependent_batching"),
        ((0.10, 0.80, 0.10), "channel_dependent_batching"),  # seg_queue exactly at threshold
        ((0.10, 0.10, 0.85), "engine_compute_variation"),
        ((0.10, 0.10, 0.80), "engine_compute_variation"),  # seg_prefill exactly at threshold
        ((0.30, 0.30, 0.30), "inconclusive"),
    ],
)
def test_classifier_threshold_boundary(ratios: tuple[float, float, float], expected: str) -> None:
    """Classifier behaves correctly at the 0.80 attribution threshold boundary
    across all three positive-attribution segments (seg_ab, seg_queue,
    seg_prefill).
    """
    seg_ab_ratio, seg_queue_ratio, seg_prefill_ratio = ratios
    spread_ttft = 10.0
    seg_ab_high = seg_ab_ratio * spread_ttft
    seg_queue_high = seg_queue_ratio * spread_ttft
    seg_prefill_high = seg_prefill_ratio * spread_ttft
    per_cohort = {
        _COHORTS[0]: _mpt(
            _COHORTS[0],
            engine_ttft_ms_mean=40.0,
            seg_ab_ms_mean=0.0,
            seg_bc_ms_mean=0.0,
            seg_cd_ms_mean=0.0,
            seg_queue_ms_mean=0.0,
            seg_prefill_ms_mean=0.0,
        ),
        _COHORTS[1]: _mpt(
            _COHORTS[1],
            engine_ttft_ms_mean=50.0,
            seg_ab_ms_mean=seg_ab_high,
            seg_bc_ms_mean=0.0,
            seg_cd_ms_mean=0.0,
            seg_queue_ms_mean=seg_queue_high,
            seg_prefill_ms_mean=seg_prefill_high,
        ),
        _COHORTS[2]: _mpt(
            _COHORTS[2],
            engine_ttft_ms_mean=45.0,
            seg_ab_ms_mean=seg_ab_high / 2,
            seg_bc_ms_mean=0.0,
            seg_cd_ms_mean=0.0,
            seg_queue_ms_mean=seg_queue_high / 2,
            seg_prefill_ms_mean=seg_prefill_high / 2,
        ),
    }
    assert classify_cell(_CHAT_STREAM_C1, per_cohort) == expected
