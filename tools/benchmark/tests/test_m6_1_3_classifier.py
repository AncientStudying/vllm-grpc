"""M6.1.3 — 7-bucket classifier unit tests (T019).

Exercises ``classify_m6_1_3`` against the contract scenarios in
``specs/026-m6-1-3-attribution-closure/contracts/classifier.md``:

* 7-bucket decision tree (one test per base label).
* Compound-label alphabetical ordering (FR-008a + R-8).
* Dominance margin enforcement (5pp gap → single label).
* ``inconclusive`` collision collapse (FR-008a tail clause).
* Legacy fallback when proxy-edge segments are absent (FR-008 + FR-010).
* ``frontend_arrival_jitter`` dormancy in the 7-bucket native tree
  (round-4 Q1).

The outer-override ``inconclusive_high_variance`` test lands in US3 T033
(``test_m6_1_3_variance.py`` + the US3 extension to this file).
"""

from __future__ import annotations

from typing import cast

import pytest
from vllm_grpc_bench.m6_1_1_types import MultiPointTimings, PerSegmentAggregate
from vllm_grpc_bench.m6_1_2_types import M6_1_2CohortKind
from vllm_grpc_bench.m6_1_3_classifier import classify_m6_1_3, make_compound_label
from vllm_grpc_bench.m6_1_3_types import DEFAULT_THRESHOLDS
from vllm_grpc_bench.m6_1_types import M6_1Cell

# --- Test fixture builders --------------------------------------------------

# A baseline TTFT pair with non-trivial spread so the
# drift-not-reproduced short-circuit doesn't fire on every fixture.
_BASELINE_TTFT_MEANS: tuple[float, float] = (40.0, 60.0)
_BASELINE_TTFT_SPREAD: float = _BASELINE_TTFT_MEANS[1] - _BASELINE_TTFT_MEANS[0]  # 20.0


def _two_cohort_means(spread: float, base: float = 1.0) -> tuple[float, float]:
    """Build a 2-tuple of cohort means with the target spread."""
    return (base, base + spread)


def _build_per_cohort(
    *,
    ttft_means: tuple[float, float] = _BASELINE_TTFT_MEANS,
    seg_ab_means: tuple[float, float] | None = None,
    seg_queue_means: tuple[float, float] | None = None,
    seg_prefill_means: tuple[float, float] | None = None,
    seg_ingress_means: tuple[float, float] | None = None,
    seg_egress_means: tuple[float, float] | None = None,
    clock_anomaly_fraction: float = 0.0,
    clock_anomaly_warning: bool = False,
    include_proxy_edge: bool = True,
) -> dict[M6_1_2CohortKind, MultiPointTimings]:
    """Build a per_cohort dict the classifier consumes.

    Each segment is opt-in: pass ``seg_X_means`` to set the per-cohort
    means for segment X. Unspecified segments default to a small (non-
    dominant) spread so they don't accidentally clear the per-rule gate.

    ``include_proxy_edge=False`` simulates a pre-M6.1.3 manifest (proxy-edge
    segments absent across all cohorts) so the legacy-fallback branch
    fires.
    """
    cohorts: tuple[M6_1_2CohortKind, M6_1_2CohortKind] = (
        "rest_https_edge",
        "default_grpc",
    )
    out: dict[M6_1_2CohortKind, MultiPointTimings] = {}
    for idx, cohort in enumerate(cohorts):
        seg_ab = (seg_ab_means or (0.1, 0.11))[idx]
        seg_queue = (seg_queue_means or (0.1, 0.11))[idx]
        seg_prefill = (seg_prefill_means or (10.0, 10.1))[idx]
        if include_proxy_edge:
            seg_ingress: float | None = (seg_ingress_means or (1.0, 1.05))[idx]
            seg_egress: float | None = (seg_egress_means or (1.0, 1.05))[idx]
        else:
            seg_ingress = None
            seg_egress = None
        per_seg = PerSegmentAggregate(
            seg_ab_ms_mean=seg_ab,
            seg_ab_ms_ci_half_width=0.01,
            seg_bc_ms_mean=0.0,
            seg_bc_ms_ci_half_width=0.0,
            seg_cd_ms_mean=0.0,
            seg_cd_ms_ci_half_width=0.0,
            n_samples=50,
            seg_queue_ms_mean=seg_queue,
            seg_queue_ms_ci_half_width=0.01,
            seg_prefill_ms_mean=seg_prefill,
            seg_prefill_ms_ci_half_width=0.01,
            seg_ingress_ms_mean=seg_ingress,
            seg_ingress_ms_ci_half_width=0.01 if seg_ingress is not None else None,
            seg_egress_ms_mean=seg_egress,
            seg_egress_ms_ci_half_width=0.01 if seg_egress is not None else None,
            clock_anomaly_fraction=clock_anomaly_fraction,
            clock_anomaly_warning=clock_anomaly_warning,
        )
        out[cohort] = MultiPointTimings(
            cohort=cohort,  # type: ignore[arg-type]
            cell=M6_1Cell(path="chat_stream", hidden_size=4096, concurrency=4),
            engine_ttft_ms_mean=ttft_means[idx],
            engine_ttft_ms_ci_half_width=0.1,
            per_segment=per_seg,
            perturbation_total_us_mean=0.0,
        )
    return out


def _share_to_spread(share: float) -> float:
    """Convert a desired share to the corresponding segment spread.

    The baseline ttft spread is 20.0, so a 0.6 share = 12.0 spread.
    """
    return share * _BASELINE_TTFT_SPREAD


# --- 7-bucket decision tree -------------------------------------------------


@pytest.mark.parametrize(
    "segment_field,expected_label",
    [
        ("seg_ab_means", "channel_dependent_batching"),
        ("seg_queue_means", "queue_dependent_batching"),
        ("seg_prefill_means", "engine_compute_variation"),
        ("seg_ingress_means", "proxy_ingress_dominated"),
        ("seg_egress_means", "proxy_egress_dominated"),
    ],
)
def test_7_bucket_decision_tree_base_labels(segment_field: str, expected_label: str) -> None:
    """FR-008: each of the 5 active base labels fires when its driving
    segment carries the dominant share. ``frontend_arrival_jitter`` is
    intentionally absent — it's dormant per round-4 Q1 and tested separately.
    """
    # The target segment carries 60% share; all others stay at non-dominant
    # small spreads (default 0.01 spread in _build_per_cohort).
    target_spread = _share_to_spread(0.6)
    kwargs = {segment_field: _two_cohort_means(target_spread)}
    per_cohort = _build_per_cohort(**kwargs)  # type: ignore[arg-type]
    result = classify_m6_1_3(None, per_cohort, thresholds=DEFAULT_THRESHOLDS)
    assert result == expected_label, (
        f"expected {expected_label} for dominant {segment_field}; got {result}"
    )


def test_inconclusive_fires_when_no_segment_clears_threshold() -> None:
    """No segment clears the per-rule gate (~40% share); classifier emits
    ``inconclusive`` regardless of the cell's TTFT spread."""
    # All segments at tiny spreads — none clears 40%.
    per_cohort = _build_per_cohort(
        seg_ab_means=(0.1, 0.11),
        seg_queue_means=(0.1, 0.11),
        seg_prefill_means=(10.0, 10.1),
        seg_ingress_means=(1.0, 1.01),
        seg_egress_means=(1.0, 1.01),
    )
    result = classify_m6_1_3(None, per_cohort, thresholds=DEFAULT_THRESHOLDS)
    assert result == "inconclusive"


# --- Compound-label tie-breaking (FR-008a + R-8) ----------------------------


def test_compound_label_alphabetical_ordering() -> None:
    """FR-008a + R-8: compound label uses ``sorted(top, runner_up)``.

    Near-tie: ``seg_egress`` at 45% spread (share=0.45) and
    ``seg_prefill`` at 43% spread (share=0.43). Gap = 2pp < 5pp margin →
    compound. Alphabetical: ``engine_compute`` < ``proxy_egress``, so the
    canonical label is ``multi_factor_engine_compute_proxy_egress``.
    """
    per_cohort = _build_per_cohort(
        seg_egress_means=_two_cohort_means(_share_to_spread(0.45)),
        seg_prefill_means=_two_cohort_means(_share_to_spread(0.43), base=10.0),
    )
    result = classify_m6_1_3(None, per_cohort, thresholds=DEFAULT_THRESHOLDS)
    assert result == "multi_factor_engine_compute_proxy_egress"


def test_dominance_margin_enforcement() -> None:
    """FR-008a: a 10pp gap (clear winner) → single label, not compound.

    ``seg_egress`` at 55% spread (share=0.55) and ``seg_prefill`` at 40%
    spread (share=0.40). Gap = 15pp ≥ 5pp margin → single
    ``proxy_egress_dominated``.
    """
    per_cohort = _build_per_cohort(
        seg_egress_means=_two_cohort_means(_share_to_spread(0.55)),
        seg_prefill_means=_two_cohort_means(_share_to_spread(0.40), base=10.0),
    )
    result = classify_m6_1_3(None, per_cohort, thresholds=DEFAULT_THRESHOLDS)
    assert result == "proxy_egress_dominated"


def test_inconclusive_collision_collapse() -> None:
    """FR-008a tail clause: when only ONE segment clears its per-rule
    gate, the classifier emits the corresponding single base label (no
    compound formed with ``inconclusive``).

    Setup: ``seg_egress`` at 42% share (clears the 40% gate) while every
    other segment stays well under 40%. The would-be "runner-up" is the
    null inconclusive candidate — it doesn't enter the compound.
    """
    per_cohort = _build_per_cohort(
        seg_egress_means=_two_cohort_means(_share_to_spread(0.42)),
    )
    result = classify_m6_1_3(None, per_cohort, thresholds=DEFAULT_THRESHOLDS)
    assert result == "proxy_egress_dominated"  # NOT a compound with inconclusive


def test_make_compound_label_alphabetical() -> None:
    """Unit test on the helper directly — alphabetical pair, regardless of
    input order."""
    assert (
        make_compound_label("proxy_egress", "engine_compute")
        == "multi_factor_engine_compute_proxy_egress"
    )
    assert (
        make_compound_label("engine_compute", "proxy_egress")
        == "multi_factor_engine_compute_proxy_egress"
    )
    assert (
        make_compound_label("channel_batching", "queue_batching")
        == "multi_factor_channel_batching_queue_batching"
    )


# --- Legacy fallback (FR-008 + FR-010) --------------------------------------


def test_legacy_fallback_no_proxy_edge_segments() -> None:
    """FR-008 + FR-010: pre-M6.1.3 manifest rehydration → 5-bucket
    fallback (no proxy_*_dominated, no multi_factor_* with proxy_*
    identifiers).

    Setup: proxy-edge segments are absent across all cohorts AND
    ``seg_prefill`` carries the dominant share — should fire
    ``engine_compute_variation`` from the 5-bucket inherited set.
    """
    per_cohort = _build_per_cohort(
        include_proxy_edge=False,
        seg_prefill_means=_two_cohort_means(_share_to_spread(0.6), base=10.0),
    )
    result = classify_m6_1_3(None, per_cohort, thresholds=DEFAULT_THRESHOLDS)
    assert result in {
        "channel_dependent_batching",
        "queue_dependent_batching",
        "engine_compute_variation",
        "frontend_arrival_jitter",
        "inconclusive",
    }
    # Specifically — the dominant prefill share should resolve to
    # engine_compute_variation.
    assert result == "engine_compute_variation"


def test_legacy_fallback_excludes_proxy_compounds() -> None:
    """The legacy fallback MUST NOT emit a compound label that includes
    ``proxy_ingress`` or ``proxy_egress`` identifiers (they're absent on
    pre-M6.1.3 manifests)."""
    per_cohort = _build_per_cohort(
        include_proxy_edge=False,
        # Near-tie among M6.1.1 / M6.1.2 segments — would produce a
        # compound of M6.1.1+M6.1.2 identifiers, NOT a proxy_* compound.
        seg_prefill_means=_two_cohort_means(_share_to_spread(0.45), base=10.0),
        seg_queue_means=_two_cohort_means(_share_to_spread(0.43)),
    )
    result = classify_m6_1_3(None, per_cohort, thresholds=DEFAULT_THRESHOLDS)
    assert "proxy_ingress" not in result
    assert "proxy_egress" not in result
    # And it IS a compound between the M6.1.2 segments (alphabetical):
    assert result == "multi_factor_engine_compute_queue_batching"


# --- frontend_arrival_jitter dormancy (round-4 Q1) -------------------------


def test_frontend_arrival_jitter_dormant_in_7_bucket_tree() -> None:
    """FR-008a revised row 4 + round-4 Q1: ``frontend_arrival_jitter`` MUST
    NOT fire as primary attribution in the 7-bucket tree.

    The current implementation doesn't expose a ``seg_arrival_ms`` field
    on PerSegmentAggregate at all, so the candidate isn't enumerated.
    This test asserts the contract holds: even when constructing a cell
    where one might naïvely expect ``frontend_arrival`` to dominate,
    the label NEVER appears in the result string.
    """
    # Drive a clear ``proxy_egress_dominated`` result via the egress
    # segment carrying 60% share; assert frontend_arrival never appears.
    per_cohort = _build_per_cohort(
        seg_egress_means=_two_cohort_means(_share_to_spread(0.6)),
    )
    result = classify_m6_1_3(None, per_cohort, thresholds=DEFAULT_THRESHOLDS)
    assert result != "frontend_arrival_jitter"
    assert "frontend_arrival" not in result


def test_frontend_arrival_jitter_never_in_compound() -> None:
    """Dormancy extends to compound labels: ``frontend_arrival`` MUST NOT
    appear inside any ``multi_factor_*`` token (round-4 Q1)."""
    # Even if we somehow set up a near-tie scenario, frontend_arrival
    # isn't in the active candidate list. Verify across a sweep of
    # near-tie cell shapes.
    near_tie_pairs: list[tuple[str, str]] = [
        ("seg_egress_means", "seg_prefill_means"),
        ("seg_ingress_means", "seg_queue_means"),
        ("seg_ab_means", "seg_egress_means"),
        ("seg_prefill_means", "seg_queue_means"),
    ]
    for a, b in near_tie_pairs:
        kwargs = {
            a: _two_cohort_means(_share_to_spread(0.45)),
            b: _two_cohort_means(_share_to_spread(0.43), base=10.0),
        }
        per_cohort = _build_per_cohort(**cast(dict[str, tuple[float, float]], kwargs))
        result = classify_m6_1_3(None, per_cohort, thresholds=DEFAULT_THRESHOLDS)
        assert "frontend_arrival" not in result, (
            f"frontend_arrival appeared in compound result {result} for ({a}, {b})"
        )


# --- Clock-anomaly cell-level downgrade (FR-006 + SC-013) ------------------


def test_clock_anomaly_warning_downgrades_to_inconclusive() -> None:
    """FR-006 + SC-013: when ``clock_anomaly_warning`` is set on any
    cohort, the classifier returns ``inconclusive`` regardless of
    segment-share signal."""
    per_cohort = _build_per_cohort(
        seg_prefill_means=_two_cohort_means(_share_to_spread(0.6), base=10.0),
        clock_anomaly_warning=True,
    )
    result = classify_m6_1_3(None, per_cohort, thresholds=DEFAULT_THRESHOLDS)
    assert result == "inconclusive"


def test_clock_anomaly_fraction_above_threshold_downgrades() -> None:
    """Even without ``clock_anomaly_warning`` set, a
    ``clock_anomaly_fraction`` above the threshold (default 0.5%) fires
    the cell-level downgrade per SC-013."""
    per_cohort = _build_per_cohort(
        seg_prefill_means=_two_cohort_means(_share_to_spread(0.6), base=10.0),
        clock_anomaly_fraction=0.01,  # 1% > 0.5% threshold
    )
    result = classify_m6_1_3(None, per_cohort, thresholds=DEFAULT_THRESHOLDS)
    assert result == "inconclusive"


# --- Drift-not-reproduced short-circuit ------------------------------------


def test_drift_not_reproduced_returns_inconclusive() -> None:
    """The drift-not-reproduced short-circuit (inherited from M6.1.1 via
    M6.1.2) folds into ``inconclusive`` in M6.1.3's vocabulary (the
    M6.1.1 ``drift_not_reproduced`` label is NOT in the M6.1.3 set)."""
    # TTFT means almost identical → spread / mean < 5% threshold.
    per_cohort = _build_per_cohort(
        ttft_means=(50.0, 50.5),  # 1% spread; below 5% drift threshold
        seg_prefill_means=(10.0, 30.0),  # dominant share but no drift signal
    )
    result = classify_m6_1_3(None, per_cohort, thresholds=DEFAULT_THRESHOLDS)
    assert result == "inconclusive"
