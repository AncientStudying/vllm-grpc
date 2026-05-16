"""M6.1.1 — FR-010 magnitude-equivalence classifier (round-1 Q1).

The classifier takes per-cohort multi-point timings for one cell and returns
one of four labels:

* ``drift_not_reproduced`` — short-circuits when the chat_stream cell's
  ``engine_ttft_ms`` per-cohort spread is below 5% of the mean (the
  segment-spread ratios would be undefined / unstable otherwise).
* ``instrumentation_artifact`` — the pre-engine bracket (``seg_ab``) carries
  ≥80% of the ``engine_ttft_ms`` spread; the per-cohort difference is
  measurement-window asymmetry, not real engine cost.
* ``channel_dependent_batching`` — the engine-internal first-token segment
  (``seg_bc``) carries ≥80% of the spread; the engine itself sees different
  first-token latencies per cohort.
* ``inconclusive`` — neither attribution threshold met (spread distributed
  across segments, or concentrated in ``seg_cd`` post-engine emit pipeline).

Pure function; no I/O, no randomness. Reproducible by hand from the
published multi-point timing table (SC-010).
"""

from __future__ import annotations

from vllm_grpc_bench.m6_1_1_types import (
    ATTRIBUTION_THRESHOLD,
    DRIFT_NOT_REPRODUCED_THRESHOLD,
    M6_1_1Cell,
    M6_1_1Cohort,
    MultiPointTimings,
    Phase1Classification,
)


def classify_cell(
    cell: M6_1_1Cell,
    per_cohort: dict[M6_1_1Cohort, MultiPointTimings],
) -> Phase1Classification:
    """Deterministic FR-010 magnitude-equivalence classifier (round-1 Q1).

    The formula:
        spread(x) = max(x) - min(x) over the three cohort means.

    Decision order (matters because later checks depend on a non-zero
    denominator):

        1. If spread(engine_ttft) / mean(engine_ttft) < 0.05 →
           ``drift_not_reproduced``.
        2. Else if spread(seg_ab) / spread(engine_ttft) ≥ 0.80 →
           ``instrumentation_artifact``.
        3. Else if spread(seg_bc) / spread(engine_ttft) ≥ 0.80 →
           ``channel_dependent_batching``.
        4. Else → ``inconclusive``.
    """
    del cell  # cell identity is auxiliary; the classification is data-driven
    engine_ttft_means = [v.engine_ttft_ms_mean for v in per_cohort.values()]
    spread_ttft = max(engine_ttft_means) - min(engine_ttft_means)
    mean_ttft = sum(engine_ttft_means) / len(engine_ttft_means)

    if spread_ttft / mean_ttft < DRIFT_NOT_REPRODUCED_THRESHOLD:
        return "drift_not_reproduced"

    seg_ab_means = [v.per_segment.seg_ab_ms_mean for v in per_cohort.values()]
    seg_bc_means = [v.per_segment.seg_bc_ms_mean for v in per_cohort.values()]
    spread_ab = max(seg_ab_means) - min(seg_ab_means)
    spread_bc = max(seg_bc_means) - min(seg_bc_means)

    if spread_ab / spread_ttft >= ATTRIBUTION_THRESHOLD:
        return "instrumentation_artifact"
    if spread_bc / spread_ttft >= ATTRIBUTION_THRESHOLD:
        return "channel_dependent_batching"
    return "inconclusive"


__all__ = ["classify_cell"]
