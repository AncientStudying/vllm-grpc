"""M6.1.3 — Phase 1 Attribution Closure: shared types, literals, and dataclasses.

Data shapes follow ``specs/026-m6-1-3-attribution-closure/data-model.md``.

M6.1.3 inherits the M6.1.2 cohort universe + network-paths + cohort-set +
cohort-omissions vocabulary verbatim (per FR-032; see ``m6_1_2_types.py``)
and adds the proxy-edge / audit / variance / classifier-extension dataclasses
that the seven new M6.1.3 modules consume.

The wire format is documented in ``specs/026-m6-1-3-attribution-closure/
contracts/wire-vocabulary.md``; the classifier vocabulary in
``contracts/classifier.md``; the artifact schema in
``contracts/artifact-schema.md``.

Per FR-010 + round-3 Q1: every addition is a strict-superset evolution of
the M6.1.1 schema. ``schema_version`` stays at ``"m6_1_1.v1"``; pre-M6.1.3
readers ignore the new fields without parse error.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Re-export the M6.1.2 cohort universe + network-paths primitives so callers
# can `from vllm_grpc_bench.m6_1_3_types import M6_1_2CohortKind` without
# threading the import through m6_1_2_types directly. The M6.1.2 names stay
# unchanged per FR-032 (M6.1.3 inherits, not supersedes).
from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2_COHORTS,
    M6_1_2CloudProvider,
    M6_1_2CohortKind,
    M6_1_2CohortOmissions,
    M6_1_2NetworkPath,
    M6_1_2NetworkPathError,
    M6_1_2NetworkPathHop,
)

# --- Sweep-mode metadata (round-2 Q2 single-entry-function pattern) ---------

M6_1_3SweepMode = Literal["full", "validate"]
"""Recorded in ``run_meta.sweep_mode`` so downstream readers can distinguish
PR-merge publishable artifacts from harness-wiring confidence-builder runs.
``"full"`` for ``--m6_1_3`` (multi-run publish or single-run Phase B);
``"validate"`` for ``--m6_1_3-validate``."""


# --- Classifier vocabulary (FR-008 + FR-008a + round-4 Q1) ------------------

M6_1_3BaseLabel = Literal[
    # Inherited 5 from M6.1.1 (FR-008's "preserved unchanged" set)
    "channel_dependent_batching",
    "queue_dependent_batching",
    "engine_compute_variation",
    "frontend_arrival_jitter",  # Dormant per round-4 Q1; never fires as primary.
    "inconclusive",
    # NEW 2 from M6.1.3 (FR-008)
    "proxy_ingress_dominated",
    "proxy_egress_dominated",
]
"""The 7 base classifier labels in M6.1.3. The first 5 are inherited from
M6.1.1's classifier; ``frontend_arrival_jitter`` is dormant per round-4 Q1
(never the primary attribution and never participates in compound labels).
The 2 new labels are produced by the proxy-edge probes' bisection."""


M6_1_3OuterLabel = Literal["inconclusive_high_variance"]
"""Outer-override label emitted when between-run stddev exceeds the unified
high-variance threshold (FR-026 + round-2 Q3). The inner 7-bucket / compound
label is rendered as a parenthetical alongside the outer label."""


M6_1_3AbbreviatedIdentifier = Literal[
    "channel_batching",  # → seg_ab_ms
    "queue_batching",  # → seg_queue_ms
    "engine_compute",  # → seg_prefill_ms
    "proxy_ingress",  # → seg_ingress_ms
    "proxy_egress",  # → seg_egress_ms
    # frontend_arrival is intentionally omitted (dormant per round-4 Q1).
]
"""The 5 abbreviated identifiers used in compound-label suffixes. The
6th canonical identifier (``frontend_arrival``) is dormant per round-4 Q1
and never participates in compound labels."""


M6_1_3CompoundLabel = Literal[
    "multi_factor_channel_batching_engine_compute",
    "multi_factor_channel_batching_proxy_egress",
    "multi_factor_channel_batching_proxy_ingress",
    "multi_factor_channel_batching_queue_batching",
    "multi_factor_engine_compute_proxy_egress",
    "multi_factor_engine_compute_proxy_ingress",
    "multi_factor_engine_compute_queue_batching",
    "multi_factor_proxy_egress_proxy_ingress",
    "multi_factor_proxy_egress_queue_batching",
    "multi_factor_proxy_ingress_queue_batching",
]
"""The 10 valid alphabetically-ordered compound labels per FR-008a + R-8.
Compound naming: ``multi_factor_<sorted_id_a>_<sorted_id_b>`` where both
ids come from :data:`M6_1_3AbbreviatedIdentifier`. ``frontend_arrival`` is
dormant per round-4 Q1 and never appears."""


M6_1_3PrimaryLabel = M6_1_3BaseLabel | M6_1_3CompoundLabel
"""The full per-cell classifier label space (excluding the outer override).
When ``inconclusive_high_variance`` outer override fires, the primary label
is rendered as a parenthetical alongside the outer label."""


# Extended SegmentName literal (FR-005). The M6.1.1 set is preserved per
# FR-008's "M6.1.1-preserved-unchanged" guarantee; the 2 new entries are
# added for proxy-edge probe attribution.
M6_1_3SegmentName = Literal[
    # Inherited M6.1.1 segment names
    "seg_ab",
    "seg_queue",
    "seg_prefill",
    "seg_arrival",
    # NEW M6.1.3 (FR-005)
    "seg_ingress",
    "seg_egress",
]


# --- Per-segment summary (mean / stddev / CI half-width) --------------------


@dataclass(frozen=True)
class PerSegmentStat:
    """Per-segment statistical summary computed by the aggregator.

    Used by :class:`M6_1_3PerSegmentAggregateExtension` for the two new
    derived segments (``seg_ingress_ms`` / ``seg_egress_ms``). The shape
    mirrors M6.1.1's inherited segments' per-aggregate fields but is
    bundled into a dataclass for readability + future extension.

    The aggregator uses the SAME statistical recipe as M6.1.1's inherited
    segments per FR-007 (no new aggregation primitive — mean + 95% CI via
    bootstrap n_boot=10_000).
    """

    mean_ms: float
    stddev_ms: float
    ci_halfwidth_ms: float
    n_samples: int


# --- Proxy-edge probe extensions (FR-001 / FR-002 / FR-003 / FR-005) --------


@dataclass(frozen=True)
class M6_1_3TimingCheckpointExtension:
    """Net new fields populated by ``m6_1_1_timing.py``'s extractor when the
    M6.1.3 wire keys are present on the response.

    All fields are optional — absent on pre-M6.1.3 manifests; absent on
    unary RPC rows for the proxy-edge fields (FR-003 streaming-only).
    """

    # Proxy-edge probes (FR-001 + FR-002; streaming-only per FR-003)
    pre_engine_wall_ns: int | None = None  # from m6_1_1_t_pre_engine_wall_ns
    first_chunk_mono_ns: int | None = None  # from m6_1_1_t_first_chunk_mono_ns

    # Prompt-content audit (FR-012 + FR-013; both streaming and unary per FR-014)
    tokenized_prompt_length: int | None = None  # from m6_1_3_tokenized_prompt_length
    tokenized_prompt_hash: str | None = None  # from m6_1_3_tokenized_prompt_hash


@dataclass(frozen=True)
class M6_1_3PerSegmentDeltaExtension:
    """Net new optional fields on PerSegmentDelta when the proxy-edge probes
    are present. Computed per RPC from the proxy-edge anchors + vLLM's
    RequestStateStats timestamps.

    Per FR-006: if either segment is negative, the row is marked a clock
    anomaly (``is_clock_anomaly=True``), the raw ``_ns`` values are logged,
    and the row is excluded from per-cell aggregation.
    """

    seg_ingress_ms: float | None = None
    seg_egress_ms: float | None = None
    is_clock_anomaly: bool = False


@dataclass(frozen=True)
class M6_1_3PerSegmentAggregateExtension:
    """Net new fields on PerSegmentAggregate. Per-cohort means / stddevs /
    CI half-widths for the new segments, using the SAME statistical recipe
    as the inherited segments (FR-007 — no new aggregation primitive).
    """

    seg_ingress_ms: PerSegmentStat | None = None
    seg_egress_ms: PerSegmentStat | None = None
    # Fraction of per-RPC rows where is_clock_anomaly was True.
    clock_anomaly_fraction: float = 0.0
    # True when clock_anomaly_fraction exceeds the configurable threshold
    # (configured via /speckit-plan; default tracked in m6_1_3_classifier).
    clock_anomaly_warning: bool = False


# --- Between-run variance (FR-024 / FR-025 / FR-027) ------------------------


@dataclass(frozen=True)
class M6_1_3BetweenRunVarianceCell:
    """Per cell × cohort between-run variance estimate from
    :func:`m6_1_3_variance.compute_between_run_variance` per FR-024.

    ``mean_of_means_ms`` and ``stddev_of_means_ms`` are ``None`` when fewer
    than 3 runs contributed for this cell × cohort (e.g., after FR-027
    cohort-unhealthy drop reduced ``n_runs`` below the minimum for a
    meaningful variance estimate). ``n_runs`` is decremented when a cohort
    produced 0 successful RPCs in any of the multi-run sweep's runs.
    """

    mean_of_means_ms: float | None
    stddev_of_means_ms: float | None
    n_runs: int


# Top-level artifact field shape (FR-024). Keyed by cell id (e.g.
# ``"chat_stream_c4"``) → cohort → variance cell.
M6_1_3BetweenRunVariance = dict[
    str,
    dict[M6_1_2CohortKind, M6_1_3BetweenRunVarianceCell],
]


# --- Per-cohort prompt-content audit (FR-012 / FR-013 / FR-014 / FR-016) ----

M6_1_3AuditVerdictLine = Literal[
    "H1 confirmed: per-cohort token-count means diverge by >2σ",
    "H1 rejected: per-cohort distributions statistically identical",
    "H2 candidate: token-counts identical but hash distributions differ",
]
"""The one-line audit verdict that drives FR-017 / FR-018 spec recommendations.

Computed from the pooled per-cohort token-count + hash distributions across
all runs in the sweep. The H1 / H2 / rejection criteria are documented in
``contracts/artifact-schema.md`` "Per-Cohort Prompt-Content Audit section"."""


@dataclass(frozen=True)
class M6_1_3PerCohortAuditDistribution:
    """Per-cohort distribution of audit fields for a single cell, pooled
    across all runs in ``phase_1_runs[]`` (FR-016 + round-1 Q5).

    ``unique_hash_count`` + ``hash_distribution`` distinguish H1 (different
    token-id sequences across cohorts → diverging hash distributions) from
    H2 (same token-id sequences with different text-level prompts that
    happen to tokenize identically → identical hash distributions).
    """

    mean_tokenized_prompt_length: float
    stddev_tokenized_prompt_length: float
    n_rpcs: int  # Pooled n: N_runs × n_per_run per cohort
    unique_hash_count: int
    hash_distribution: dict[str, int]  # hash → count


@dataclass(frozen=True)
class M6_1_3PerCellAuditAggregate:
    """Per-cell pooled-distribution audit aggregate per FR-016 + round-1 Q5."""

    cell_id: str
    per_cohort: dict[M6_1_2CohortKind, M6_1_3PerCohortAuditDistribution]
    pooled_verdict: M6_1_3AuditVerdictLine


@dataclass(frozen=True)
class M6_1_3PerRunAuditVerdict:
    """Per-run, per-cell audit verdict for the FR-016a conditional appendix
    (round-2 Q5). The appendix renders only when any per-run verdict differs
    from the pooled verdict for any cell."""

    run_idx: int  # 0-indexed position in phase_1_runs[]
    cell_id: str
    verdict: M6_1_3AuditVerdictLine


# --- Phase B trigger verdict (FR-043 / FR-044 + round-2 Q3) -----------------


@dataclass(frozen=True)
class M6_1_3PhaseBTriggerVerdict:
    """The verdict line emitted by the Phase A publish-run reporter at the
    end of the 'Between-Run Variance' section per FR-044 + round-2 Q3.

    When ``variance_section_suppressed`` is True (operator override with
    ``--m6_1_3-diagnose-repeat < 3``), the reporter renders an FR-044
    override-fallback message at the end of the per-cell timing table
    instead, and ``required`` + ``trigger_cells`` are unavailable.
    """

    required: bool
    trigger_cells: list[str]  # Alphabetically sorted cell IDs
    variance_section_suppressed: bool


# --- Top-level artifact entity (strict-superset of M6.1.2 + M6.1.1) ---------


@dataclass(frozen=True)
class M6_1_3SweepArtifact:
    """Top-level M6.1.3 artifact. Strict-superset of the M6.1.2 / M6.1.1
    artifact shapes per FR-010 + round-3 Q1.

    Pre-M6.1.3 readers parse this artifact, ignoring the
    ``between_run_variance`` top-level field. ``schema_version`` stays at
    ``"m6_1_1.v1"`` (the prefix is naming, not versioning, per FR-010
    round-3 Q1).
    """

    schema_version: Literal["m6_1_1.v1"]
    dispatch_mode: Literal["concurrent"]
    run_id: str
    run_started_at: str
    run_completed_at: str
    run_meta: dict[str, object]
    phase_1_classifications: dict[str, object]
    phase_1_runs: list[dict[str, object]]
    multi_point_timings: dict[str, object]
    phase_2_outcome: dict[str, object] | None
    phase_2_choice: str | None
    chat_stream_baseline_post_symmetrisation: dict[str, object]
    embed_baseline_post_symmetrisation: dict[str, object]
    embed_regression_check: dict[str, object] | None
    m6_1_baseline_pointer: str
    methodology_supersedence: dict[str, object]
    classifier_notes: list[str]
    network_paths: dict[str, object]
    cohort_set: list[str]
    cohort_omissions: dict[str, str] | None
    # M6.1.3 NEW top-level field per FR-010 strict-superset (FR-024 + FR-025).
    between_run_variance: M6_1_3BetweenRunVariance | None


__all__ = [
    # Re-exports from m6_1_2_types (per FR-032 inheritance)
    "M6_1_2_COHORTS",
    "M6_1_2CloudProvider",
    "M6_1_2CohortKind",
    "M6_1_2CohortOmissions",
    "M6_1_2NetworkPath",
    "M6_1_2NetworkPathError",
    "M6_1_2NetworkPathHop",
    # M6.1.3 sweep mode metadata
    "M6_1_3SweepMode",
    # M6.1.3 classifier vocabulary
    "M6_1_3AbbreviatedIdentifier",
    "M6_1_3AuditVerdictLine",
    "M6_1_3BaseLabel",
    "M6_1_3CompoundLabel",
    "M6_1_3OuterLabel",
    "M6_1_3PrimaryLabel",
    "M6_1_3SegmentName",
    # M6.1.3 audit + variance + Phase B dataclasses
    "M6_1_3BetweenRunVariance",
    "M6_1_3BetweenRunVarianceCell",
    "M6_1_3PerCellAuditAggregate",
    "M6_1_3PerCohortAuditDistribution",
    "M6_1_3PerRunAuditVerdict",
    "M6_1_3PerSegmentAggregateExtension",
    "M6_1_3PerSegmentDeltaExtension",
    "M6_1_3PhaseBTriggerVerdict",
    "M6_1_3SweepArtifact",
    "M6_1_3TimingCheckpointExtension",
    "PerSegmentStat",
]
