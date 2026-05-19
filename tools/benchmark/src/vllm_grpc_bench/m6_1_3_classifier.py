"""M6.1.3 — Phase 1 Attribution Closure: 7-bucket classifier extension.

Extends M6.1.1's 5-bucket decision tree to 7 buckets per FR-008. Adds the
compound-label vocabulary per FR-008a + R-8 (alphabetical tie-breaking
with a 5pp dominance margin), the ``frontend_arrival_jitter`` dormancy
guard per round-4 Q1 (the label stays in the legacy fallback for backward
compatibility but never fires as the primary attribution in the 7-bucket
native tree), the legacy fallback for pre-M6.1.3 manifest rehydration per
FR-010, and the ``inconclusive_high_variance`` outer-override scaffold
(wired by US3 T035 — for US1 the parameter is accepted but unused).

The decision logic operates on a per-cell ``per_cohort`` dict whose values
are :class:`vllm_grpc_bench.m6_1_1_types.MultiPointTimings` extended with
the M6.1.3-additive ``seg_ingress_ms_*`` / ``seg_egress_ms_*`` fields on
:class:`PerSegmentAggregate` (added in this milestone). The classifier is
a pure function — no I/O, no randomness; reproducible by hand from the
published multi-point timing table (SC-010).

Per FR-008's "M6.1.1-preserved-unchanged" guarantee:
:func:`vllm_grpc_bench.m6_1_1_classifier.classify_cell` is untouched. The
M6.1.3 classifier is a parallel module per FR-037 (the
parallel-module pattern; historical re-runnability stays frozen).

Per ``specs/026-m6-1-3-attribution-closure/contracts/classifier.md``:

* 7 base labels (round-4 Q1: ``frontend_arrival_jitter`` is dormant in
  native 7-bucket; remains in legacy fallback).
* Compound label form ``multi_factor_<sorted_top>_<sorted_runner_up>``
  using abbreviated identifiers from the canonical 6-row mapping.
* ``inconclusive`` collapse: if a near-tie candidate would otherwise be
  ``inconclusive``, the cell emits the non-inconclusive single label.
* Outer override ``inconclusive_high_variance (<inner>)`` wired by US3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vllm_grpc_bench.m6_1_3_types import (
    DEFAULT_THRESHOLDS,
    M6_1_2CohortKind,
    M6_1_3BetweenRunVarianceCell,
    M6_1_3ClassifierThresholds,
)

if TYPE_CHECKING:
    from vllm_grpc_bench.m6_1_1_types import M6_1_1Cell, MultiPointTimings


# --- Canonical vocabulary mapping (FR-008a + contracts/classifier.md) -------

# The 5 active driving identifiers (frontend_arrival is dormant per round-4
# Q1 — never participates in the 7-bucket native tree or compound labels).
# Ordered by emission preference for deterministic candidate enumeration;
# the actual decision rule is share-based, so order doesn't change output.
_ACTIVE_CANDIDATES: tuple[tuple[str, str, str, str], ...] = (
    # (segment_field_attr, abbreviated_id, base_label, threshold_attr)
    ("seg_ab_ms_mean", "channel_batching", "channel_dependent_batching", "channel_share_min"),
    ("seg_queue_ms_mean", "queue_batching", "queue_dependent_batching", "queue_share_min"),
    ("seg_prefill_ms_mean", "engine_compute", "engine_compute_variation", "prefill_share_min"),
    ("seg_ingress_ms_mean", "proxy_ingress", "proxy_ingress_dominated", "ingress_share_min"),
    ("seg_egress_ms_mean", "proxy_egress", "proxy_egress_dominated", "egress_share_min"),
)

# Proxy-edge segments — when absent across ALL cohorts, the classifier
# applies the legacy fallback (no proxy_*_dominated / no multi_factor_*
# compound labels involving proxy_* identifiers).
_PROXY_EDGE_FIELDS: frozenset[str] = frozenset({"seg_ingress_ms_mean", "seg_egress_ms_mean"})


# --- Helpers ----------------------------------------------------------------


def make_compound_label(top_id: str, runner_up_id: str) -> str:
    """Produce the canonical ``multi_factor_<a>_<b>`` label with alphabetical
    ordering per FR-008a + R-8.

    The two abbreviated identifiers are sorted alphabetically so a near-tie
    produces a deterministic label regardless of which segment scored
    fractionally higher.
    """
    sorted_pair = sorted([top_id, runner_up_id])
    return f"multi_factor_{sorted_pair[0]}_{sorted_pair[1]}"


def _segment_means(
    per_cohort: dict[M6_1_2CohortKind, MultiPointTimings],
    field_attr: str,
) -> list[float] | None:
    """Collect per-cohort means for a single segment.

    Returns ``None`` when ANY cohort lacks the segment value (the segment
    is treated as absent for the cell, so the segment's candidate label
    is excluded from the share computation). Returns the list otherwise.
    """
    out: list[float] = []
    for v in per_cohort.values():
        mean = getattr(v.per_segment, field_attr, None)
        if mean is None:
            return None
        out.append(float(mean))
    return out


def _spread(values: list[float]) -> float:
    return max(values) - min(values)


def _has_proxy_edge_segments(
    per_cohort: dict[M6_1_2CohortKind, MultiPointTimings],
) -> bool:
    """True iff at least one proxy-edge segment is populated across all
    cohorts (FR-008 legacy fallback signal).

    The legacy fallback per FR-008 + FR-010 fires when proxy-edge segments
    are absent across all cohorts (pre-M6.1.3 manifest rehydration). In
    that case the classifier emits labels from the inherited 5-bucket set
    only (channel_dependent_batching / queue_dependent_batching /
    engine_compute_variation / frontend_arrival_jitter / inconclusive),
    excluding proxy_*_dominated candidates AND compound labels that would
    have included a proxy_* identifier.
    """
    for field_attr in _PROXY_EDGE_FIELDS:
        if _segment_means(per_cohort, field_attr) is not None:
            return True
    return False


def _cell_clock_anomaly_warning(
    per_cohort: dict[M6_1_2CohortKind, MultiPointTimings],
    thresholds: M6_1_3ClassifierThresholds,
) -> bool:
    """Cell-level clock-anomaly downgrade gate per FR-006 + SC-013.

    Returns True if any cohort in this cell has
    ``clock_anomaly_fraction > thresholds.clock_anomaly_max_fraction`` OR
    if ``per_segment.clock_anomaly_warning`` is already True for any cohort
    (set by the aggregator when the gate was hit at aggregation time).
    """
    for v in per_cohort.values():
        seg = v.per_segment
        if getattr(seg, "clock_anomaly_warning", False):
            return True
        fraction = getattr(seg, "clock_anomaly_fraction", 0.0)
        if fraction > thresholds.clock_anomaly_max_fraction:
            return True
    return False


# --- Main entry function -----------------------------------------------------


def classify_m6_1_3(
    cell: M6_1_1Cell | None,
    per_cohort: dict[M6_1_2CohortKind, MultiPointTimings],
    *,
    between_run_variance: M6_1_3BetweenRunVarianceCell | None = None,
    ci_halfwidth_ms: float | None = None,
    thresholds: M6_1_3ClassifierThresholds | None = None,
) -> str:
    """Deterministic 7-bucket classifier per FR-008 + FR-008a + R-8.

    Decision flow (matters because later steps depend on earlier guards):

    1. **Drift-not-reproduced short-circuit** — if the cross-cohort
       ``engine_ttft_ms`` spread is below the drift-not-reproduced
       threshold (default 5% per ``DRIFT_NOT_REPRODUCED_THRESHOLD``), there
       is no meaningful drift to attribute → return ``inconclusive``. This
       matches M6.1.1's first guard per ``contracts/classifier.md``.
    2. **Clock-anomaly cell-level downgrade** (FR-006 + SC-013) — if any
       cohort's ``clock_anomaly_warning`` is True OR
       ``clock_anomaly_fraction`` exceeds the configured threshold → return
       ``inconclusive`` regardless of segment-share signal.
    3. **Candidate enumeration** — for each of the 5 active driving
       identifiers (the 6th canonical identifier ``frontend_arrival`` is
       dormant per round-4 Q1), compute the per-cohort spread and the
       fraction of total ``engine_ttft_ms`` spread it represents (its
       "share"). Candidates whose share clears their per-rule gate enter
       the tie-breaker.
    4. **Legacy fallback** (FR-008 + FR-010) — if proxy-edge segments are
       absent across all cohorts, exclude ``proxy_ingress`` /
       ``proxy_egress`` candidates from the enumeration. The remaining
       candidate set is the inherited 5-bucket set; ``frontend_arrival``
       is allowed in fallback per the dormancy note's "legacy
       compatibility" carve-out.
    5. **Tie-breaking** (FR-008a) — sort candidates by share descending.
       Zero candidates → ``inconclusive``. One candidate → emit single
       base label. Two or more candidates: if top - runner_up ≥ 5pp
       margin → emit top base label; otherwise emit
       ``multi_factor_<a>_<b>`` with alphabetical ordering.
    6. **Outer override** (FR-026 + round-2 Q3, wired by US3 T035) — if
       ``between_run_variance`` and ``ci_halfwidth_ms`` are provided AND
       the unified threshold check fires, wrap the inner label as
       ``inconclusive_high_variance (<inner>)``. For US1 the parameter is
       accepted but the override is NOT yet wired; see the TODO below.
    """
    del cell  # cell identity is auxiliary; classification is data-driven
    thresholds = thresholds or DEFAULT_THRESHOLDS

    if not per_cohort:
        return "inconclusive"

    # Step 1: drift-not-reproduced short-circuit (folded into inconclusive
    # for M6.1.3 since drift_not_reproduced isn't in the M6.1.3 label set).
    engine_ttft_means = [v.engine_ttft_ms_mean for v in per_cohort.values()]
    mean_ttft = sum(engine_ttft_means) / len(engine_ttft_means)
    spread_ttft = _spread(engine_ttft_means)
    if mean_ttft <= 0 or spread_ttft / mean_ttft < thresholds.drift_not_reproduced_threshold:
        return "inconclusive"

    # Step 2: clock-anomaly cell-level downgrade (FR-006 + SC-013).
    if _cell_clock_anomaly_warning(per_cohort, thresholds):
        return "inconclusive"

    # Step 3 + 4: candidate enumeration with legacy fallback.
    legacy_fallback = not _has_proxy_edge_segments(per_cohort)
    candidates: list[tuple[float, str, str]] = []  # (share, abbreviated_id, base_label)
    for field_attr, abbrev_id, base_label, threshold_attr in _ACTIVE_CANDIDATES:
        if legacy_fallback and field_attr in _PROXY_EDGE_FIELDS:
            # Pre-M6.1.3 manifest rehydration: skip proxy_* candidates.
            continue
        means = _segment_means(per_cohort, field_attr)
        if means is None:
            continue  # Segment absent on at least one cohort; not a candidate.
        spread = _spread(means)
        share = spread / spread_ttft if spread_ttft > 0 else 0.0
        gate = float(getattr(thresholds, threshold_attr))
        if share >= gate:
            candidates.append((share, abbrev_id, base_label))

    # Step 5: tie-breaking.
    if not candidates:
        inner_label: str = "inconclusive"
    elif len(candidates) == 1:
        inner_label = candidates[0][2]
    else:
        # Sort by share descending (lexicographic tiebreaker on share-tied
        # candidates is stable; the alphabetical ordering of the compound
        # label below handles the FR-008a determinism requirement).
        candidates.sort(key=lambda c: c[0], reverse=True)
        top_share, top_id, top_label = candidates[0]
        runner_share, runner_id, _runner_label = candidates[1]
        gap = top_share - runner_share
        if gap >= thresholds.compound_margin:
            inner_label = top_label
        else:
            inner_label = make_compound_label(top_id, runner_id)

    # Step 6: outer override (FR-026 + FR-043 + round-2 Q3 unified threshold).
    # When the multi-run variance signal exceeds threshold × within-run
    # CI half-width, the cell's headline verdict becomes
    # ``"inconclusive_high_variance (<inner>)"``. The inner label is
    # preserved as a parenthetical so the reader sees both signals.
    if between_run_variance is not None and ci_halfwidth_ms is not None and ci_halfwidth_ms > 0:
        # Local import: ``m6_1_3_variance`` imports M6_1_3BetweenRunVarianceCell
        # from m6_1_3_types, not from this classifier module, so there's no
        # circular dependency at module load time.
        from vllm_grpc_bench.m6_1_3_variance import should_fire_inconclusive_high_variance

        if should_fire_inconclusive_high_variance(
            between_run_variance,
            cell_ci_halfwidth_ms=ci_halfwidth_ms,
            threshold=thresholds.high_variance_ratio_threshold,
        ):
            return f"inconclusive_high_variance ({inner_label})"

    return inner_label


__all__ = [
    "classify_m6_1_3",
    "make_compound_label",
]
