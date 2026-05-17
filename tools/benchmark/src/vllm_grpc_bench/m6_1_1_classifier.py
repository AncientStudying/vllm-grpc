"""M6.1.1 — FR-010 magnitude-equivalence classifier.

The classifier takes per-cohort multi-point timings for one cell and returns
one of five labels. The decision tree was upgraded in M6.1.2 to fix the
``seg_bc ≡ engine_ttft`` degeneracy of the original four-checkpoint scheme:
``seg_bc`` is now redundant with ``engine_ttft`` by construction (both measure
``first_chunk_ns - pre_engine_ns``), so the original
``spread(seg_bc) / spread(engine_ttft) ≥ 0.80`` rule fired mechanically on any
non-trivial chat_stream spread. The M6.1.2 instrumentation upgrade pulls
``arrival_time``, ``queued_ts``, ``scheduled_ts``, ``first_token_ts``, and
``last_token_ts`` from :class:`vllm.v1.metrics.stats.RequestStateStats` so the
classifier can decompose ``engine_ttft`` into ``seg_queue`` (queue wait) and
``seg_prefill`` (post-schedule engine compute).

Labels:

* ``drift_not_reproduced`` — short-circuits when the chat_stream cell's
  ``engine_ttft_ms`` per-cohort spread is below 5% of the mean (the
  segment-spread ratios would be undefined / unstable otherwise).
* ``instrumentation_artifact`` — the pre-engine bracket (``seg_ab``,
  handler-internal pre-engine work) carries ≥80% of the ``engine_ttft_ms``
  spread; the per-cohort difference is measurement-window asymmetry in the
  servicer, not engine cost.
* ``channel_dependent_batching`` — the engine queue-wait segment
  (``seg_queue``, vLLM's scheduler picking up the request) carries ≥80% of
  the spread. This is the canonical continuous-batching effect: cohorts
  arrive in different timing patterns, so the engine's scheduler dispatches
  them at different times relative to other in-flight requests.
* ``engine_compute_variation`` — the post-schedule engine compute segment
  (``seg_prefill``, ``first_token_ts - scheduled_ts``) carries ≥80% of the
  spread. The scheduler picked up the request promptly but the engine took
  per-cohort variable time to produce the first token — most likely a
  KV-cache-state or prompt-length artifact.
* ``inconclusive`` — variation distributed across multiple sources; raw
  per-segment numbers reported for manual interpretation.

Backward compatibility: when ``per_segment.seg_queue_ms_mean is None`` (no
sample populated the M6.1.2 engine-internal timestamps), the classifier
falls back to a 3-bucket scheme without the ``channel_dependent_batching`` /
``engine_compute_variation`` distinction:

1. ``drift_not_reproduced`` (unchanged)
2. ``instrumentation_artifact`` if ``spread(seg_ab) ≥ 0.80 × spread(ttft)``
3. ``inconclusive`` otherwise (no positive evidence either way; raw numbers
   reported)

This ensures the classifier produces a defensible verdict on legacy
audit-baseline data without resurrecting the degenerate seg_bc rule.

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
    """Deterministic FR-010 magnitude-equivalence classifier (M6.1.2 5-bucket).

    Decision order (matters because later checks depend on a non-zero
    denominator):

        1. If spread(engine_ttft) / mean(engine_ttft) < 0.05 →
           ``drift_not_reproduced``.
        2. Else if spread(seg_ab) / spread(engine_ttft) ≥ 0.80 →
           ``instrumentation_artifact``.
        3. Else if M6.1.2 engine-internal segments present:
           a. If spread(seg_queue) / spread(engine_ttft) ≥ 0.80 →
              ``channel_dependent_batching``.
           b. Else if spread(seg_prefill) / spread(engine_ttft) ≥ 0.80 →
              ``engine_compute_variation``.
           c. Else → ``inconclusive``.
        4. Else (legacy data, no engine-internal segments) → ``inconclusive``.
    """
    del cell  # cell identity is auxiliary; the classification is data-driven
    engine_ttft_means = [v.engine_ttft_ms_mean for v in per_cohort.values()]
    spread_ttft = max(engine_ttft_means) - min(engine_ttft_means)
    mean_ttft = sum(engine_ttft_means) / len(engine_ttft_means)

    if mean_ttft <= 0 or spread_ttft / mean_ttft < DRIFT_NOT_REPRODUCED_THRESHOLD:
        return "drift_not_reproduced"

    seg_ab_means = [v.per_segment.seg_ab_ms_mean for v in per_cohort.values()]
    spread_ab = max(seg_ab_means) - min(seg_ab_means)

    if spread_ab / spread_ttft >= ATTRIBUTION_THRESHOLD:
        return "instrumentation_artifact"

    # M6.1.2 — use engine-internal segments when present.
    seg_queue_means = [v.per_segment.seg_queue_ms_mean for v in per_cohort.values()]
    seg_prefill_means = [v.per_segment.seg_prefill_ms_mean for v in per_cohort.values()]
    if any(m is None for m in seg_queue_means) or any(m is None for m in seg_prefill_means):
        # Legacy data without engine-internal segments; no positive evidence
        # for channel_dependent_batching vs engine_compute_variation.
        return "inconclusive"

    # All cohorts have engine-internal segments; safe to subtract.
    queue_values = [m for m in seg_queue_means if m is not None]
    prefill_values = [m for m in seg_prefill_means if m is not None]
    spread_queue = max(queue_values) - min(queue_values)
    spread_prefill = max(prefill_values) - min(prefill_values)

    if spread_queue / spread_ttft >= ATTRIBUTION_THRESHOLD:
        return "channel_dependent_batching"
    if spread_prefill / spread_ttft >= ATTRIBUTION_THRESHOLD:
        return "engine_compute_variation"
    return "inconclusive"


__all__ = ["classify_cell"]
