"""M6.2 — Token-Budget Characterization: shared types, literals, and dataclasses.

Data shapes follow ``specs/027-m6-2-token-budget/data-model.md``.

M6.2 inherits the M6.1.3 cohort universe + network-paths + 5-segment
decomposition vocabulary verbatim (per FR-028) and adds the
``max_tokens``-axis fields, three-regime prompt-source vocabulary, null-anchor
+ crossover-threshold + KV-pressure + anchor-trajectory dataclasses that the
new M6.2 modules consume.

Per FR-011 + round-3 Q1: every addition is a strict-superset evolution of the
M6.1.1 schema. ``schema_version`` stays at ``"m6_1_1.v1"``; pre-M6.2 readers
ignore the new fields without parse error.

Round-5 round (clarify) extends the data model with:
- ``prompt_source`` + ``measurement_regime`` + ``prompt_corpus_idx`` on
  ``M6_2MeasurementPoint``.
- ``sub_probe_n_rpcs`` + ``sub_probe_prompt_source`` +
  ``sub_probe_measurement_regime`` on ``M6_2KVPressureObservation``.
- ``chat_corpus_sha256`` + ``chat_corpus_path`` + ``embed_corpus_sha256`` +
  ``embed_corpus_path`` + ``sub_probe_ran`` on ``M6_2RunMeta``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Re-export M6.1.3 inheritance primitives for downstream call sites that want
# `from m6_2_types import M6_1_2CohortKind` without threading the import.
from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2_COHORTS,
    M6_1_2CloudProvider,
    M6_1_2CohortKind,
    M6_1_2CohortOmissions,
    M6_1_2NetworkPath,
    M6_1_2NetworkPathError,
    M6_1_2NetworkPathHop,
)

# --- M6.2 axis constants (FR-001 / FR-016) ----------------------------------

M6_2_MAX_TOKENS_AXIS: tuple[int, ...] = (10, 50, 256, 512, 1024, 2048)
"""The full 6-point publish-mode axis."""

M6_2_VALIDATE_MAX_TOKENS_AXIS: tuple[int, ...] = (10, 50, 2048)
"""The 3-point validate-mode axis subset (round-1 Q2)."""

M6_2_NULL_ANCHOR_MAX_TOKENS: tuple[int, ...] = (10, 50)
"""Caps where null-anchor cross-milestone comparison fires (FR-012 / FR-013)."""

M6_2_INTERIOR_CAP_MAX_TOKENS: tuple[int, ...] = (256, 512, 1024, 2048)
"""Caps where the corpus-regime (production-realistic) measurement applies."""

M6_2_SUB_PROBE_MAX_TOKENS: tuple[int, ...] = (1024, 2048)
"""Caps the KV-pressure sub-probe runs at (FR-036 / R-10)."""

M6_2_SUB_PROBE_N: int = 20
"""Per-block sample size for the KV-pressure sub-probe (FR-036)."""


M6_2_PUBLISH_N: int = 40
"""Per-(cell × cohort × max_tokens) sample size for the publish sweep,
pinned in clarify round 3 (2026-05-24) against the 2026-05-24 validate
sweep's measured CI half-widths.

Round-3 closure rationale: the validate sweep at n=20 produced median
CI half-widths of 1.95% at max_tokens=50 and 3.94% at max_tokens=2048;
n=40 tightens both by 1/sqrt(2) ≈ 29% (to ~1.4% and ~2.8% median), well
under the FR-014 / SC-004 pooled-CI WARN bar, while keeping the publish
sweep at ~13 h wall-clock and ~$20 Modal spend at the bottom of the
spec's provisional ``$20–$40`` envelope.

The CLI gate (:func:`m6_2_sweep.gate_publish_mode_n`) still REQUIRES an
explicit ``--m6_2-n`` flag — this constant documents the canonical pinned
value but does NOT supply a default, so an operator cannot launch the
publish sweep at an unintended n by omission."""

M6_2_KV_PRESSURE_THRESHOLD: float = 2.2
"""Wall-clock ratio threshold above which KV-pressure is inferred (FR-017a)."""

M6_2_NULL_ANCHOR_DRIFT_COUNT_THRESHOLD: int = 2
"""Cross-checkable cells that must carry WARN/FAIL before FR-014 sweep-level
``null_anchor_drift`` integrity header fires. The 22 cross-checkable cells
are the chat_stream cells × cohort pairs at ``max_tokens=50`` plus the embed
cells × cohort pairs at ``max_tokens=10`` (minus M6.1.3's 2 cohort omissions)."""

M6_2_LATENCY_DRIFT_COHORT_COUNT_THRESHOLD: int = 2
"""Cohorts that must fire ``latency_drift_warning`` before SC-016 sweep-level
``intra_sweep_latency_drift`` integrity header fires."""

M6_2_FAILURE_SUMMARY_CELL_COUNT_THRESHOLD: int = 3
"""Failed cells (across the table) that trigger FR-029 sweep-level
``failure_summary_threshold`` integrity header. The companion rule —
``systemic_failure_<reason>`` — fires when any (cell, max_tokens) sees
all 4 cohorts fail with the same reason (handled inline by the reporter)."""


# --- Sweep-mode metadata (FR-015 + R-7 two-path routing) --------------------

M6_2SweepMode = Literal["publish", "validate"]
"""Recorded in ``run_meta.sweep_mode`` so downstream readers can distinguish
the canonical publish artifact from the wiring-confidence validate sibling.
``"publish"`` for ``--m6_2``; ``"validate"`` for ``--m6_2-validate``."""


# --- Three-regime prompt-source vocabulary (round-5 FR-034 / FR-035) -------

M6_2PromptSource = Literal[
    "synthetic_seed_derived",
    "corpus_sharegpt",
    "synthetic_random_tensor",
    "corpus_sharegpt_embed",
]
"""Cell-type-dependent label that records which prompt-construction regime
produced the inputs for a given block. Synthetic regimes apply to null-anchor
caps ``{10, 50}``; corpus regimes apply to interior caps + sub-probe."""


M6_2MeasurementRegime = Literal["natural_eos", "forced_cap_ignore_eos_true"]
"""Generation-termination regime. Budget-table rows are always
``"natural_eos"``; KV-pressure sub-probe rows are always
``"forced_cap_ignore_eos_true"``."""


M6_2WallClockInferenceLabel = Literal[
    "kv_pressure_inferred_chat_stream",
    "kv_pressure_inferred_embed",
    "kv_pressure_not_observable",
]
"""Per cell-type × cohort KV-pressure inference label, derived from the
wall-clock-ratio rule with threshold ``M6_2_KV_PRESSURE_THRESHOLD``."""


M6_2DriftVerdict = Literal["PASS", "WARN", "FAIL"]
"""Null-anchor cross-milestone verdict (FR-012 / FR-013).

``PASS``: M6.2 anchor measurement inside M6.1.3 CI half-width.
``WARN``: outside M6.1.3 CI but within 2× CI half-width.
``FAIL``: outside 2× CI half-width."""


# --- M6.2 dataclasses -------------------------------------------------------


@dataclass(slots=True, kw_only=True)
class M6_2MeasurementPoint:
    """A single ``(cell, cohort, max_tokens)`` block measurement.

    144 rows in publish mode (6 cells × 4 cohorts × 6 caps); 72 measured + 72
    ``not_validated`` placeholders in validate mode (6 cells × 4 cohorts × 3
    caps). Failed blocks set ``failed_reason`` and leave latency fields
    ``None``.

    Round-5 fields (``prompt_source``, ``measurement_regime``,
    ``prompt_corpus_idx``) record the three-regime prompt-source contract per
    FR-034 / FR-035; ``measurement_regime`` is always ``"natural_eos"`` on
    budget-table rows (sub-probe rows live in ``M6_2KVPressureObservation``).
    """

    cell_id: str
    cohort: M6_1_2CohortKind
    max_tokens: int
    n_rpcs: int
    wall_p50_ms: float | None
    wall_p95_ms: float | None
    wall_p99_ms: float | None
    wall_p50_ms_ci_half_width: float | None
    tpot_ms: float | None
    seg_ab_ms: float | None
    seg_queue_ms: float | None
    seg_prefill_ms: float | None
    seg_ingress_ms: float | None
    seg_egress_ms: float | None
    failed_reason: str | None
    block_start_utc: str
    block_end_utc: str
    retry_attempted: bool
    clock_anomaly: bool
    prompt_source: M6_2PromptSource
    measurement_regime: M6_2MeasurementRegime
    prompt_corpus_idx: int | None


@dataclass(slots=True, kw_only=True)
class M6_2NullAnchor:
    """Null-anchor verdict for one ``(cell, cohort)`` pair at
    ``max_tokens ∈ {10, 50}``.

    Cross-checkable cells (22 of 48) pair the M6.2 measurement against
    M6.1.3's published CI; new-baseline cells (26 of 48) carry
    ``new_baseline_marker=True`` and ``drift_verdict=None`` (FR-012). Only
    cross-checkable cells count toward the FR-014 sweep-level integrity
    header.
    """

    cell_id: str
    cohort: M6_1_2CohortKind
    max_tokens: int
    m6_2_wall_p50_ms: float | None
    m6_1_3_wall_p50_ms: float | None  # None on new-baseline cells
    m6_1_3_ci_half_width: float | None  # None on new-baseline cells
    drift_verdict: M6_2DriftVerdict | None  # None on new-baseline cells
    drift_fraction: float | None
    new_baseline_marker: bool


@dataclass(slots=True, kw_only=True)
class M6_2CrossoverThreshold:
    """Per-cell crossover threshold from the symmetric mean-in-CI rule
    (spec round-1 Q3). ``crossover_max_tokens`` uses the coarse 4-value
    vocabulary ``{10, 50, 2048, survives_to_2048}`` in validate mode and the
    full 6-point axis in publish mode."""

    cell_id: str
    m6_1_3_winner_cohort: M6_1_2CohortKind | None
    m6_1_3_second_cohort: M6_1_2CohortKind | None
    crossover_max_tokens: int | None
    crossover_evidence: str
    m6_1_3_base_verdict: str


@dataclass(slots=True, kw_only=True)
class M6_2KVPressureObservation:
    """Per ``(cohort, cell_type)`` KV-pressure observation derived from the
    sub-probe (NOT the main-sweep budget-table c=8 rows) per round-5 FR-036.

    8 records per artifact (4 cohorts × 2 cell-types); derived from 16
    sub-probe blocks (4 cohorts × 2 cell-types × 2 caps in
    ``M6_2_SUB_PROBE_MAX_TOKENS``).
    """

    cohort: M6_1_2CohortKind
    cell_type: Literal["chat_stream", "embed"]
    wall_clock_ratio_c8_2048_over_1024: float | None
    wall_clock_inference_label: M6_2WallClockInferenceLabel
    kv_cache_used_fraction_peak: float | None
    scheduling_stall_signals: str | None
    oom_observed: bool
    sub_probe_n_rpcs: int  # always M6_2_SUB_PROBE_N (20)
    sub_probe_prompt_source: Literal["corpus_sharegpt", "corpus_sharegpt_embed"]
    sub_probe_measurement_regime: Literal["forced_cap_ignore_eos_true"]


@dataclass(slots=True, kw_only=True)
class M6_2AnchorLatencySnapshot:
    """One snapshot in the intra-sweep anchor-latency trajectory (FR-031).

    The anchor block uses the SYNTHETIC chat_stream c=1 × max_tokens=10
    regime — preserves M6.1.3-baseline byte-comparability per R-3 (switching
    to corpus would make the trajectory measure prompt-source drift instead
    of network/temporal drift)."""

    wall_p50_ms: float
    wall_p95_ms: float
    wall_p99_ms: float
    snapshot_timestamp: str  # ISO-8601 UTC
    sweep_hour_mark: float


@dataclass(slots=True, kw_only=True)
class M6_2AnchorLatencyTrajectory:
    """Per-cohort sequence of intra-sweep anchor snapshots (FR-031).

    Publish: ≥ 8 snapshots at 4h cadence + start + end (~40h sweep gives 10).
    Validate: 2 snapshots (start + end; ~2.3h sweep ≪ 4h cadence)."""

    cohort: M6_1_2CohortKind
    snapshots: list[M6_2AnchorLatencySnapshot]
    max_minus_min_wall_p50_ms: float
    latency_drift_warning: bool
    insufficient_post_warmup_snapshots: bool = False
    """C1 round-8 amendment (2026-05-23): set ``True`` when the cohort has
    fewer than 2 snapshots after the ``WARMUP_SUPPRESSION_HOURS`` cold-start
    drop. The trajectory's spread and ``latency_drift_warning`` are
    suppressed in this case (set to 0.0 / False). The soft
    ``trajectory_insufficient_snapshots`` integrity diagnostic fires when
    any cohort carries this flag — purely informational, NOT
    publish-blocking, distinct from SC-016 ``intra_sweep_latency_drift``.
    Validate-mode 2-snapshot start+end trajectories hit this fallback by
    construction once the start snapshot is warmup-dropped."""


@dataclass(slots=True, kw_only=True)
class M6_2RunMeta:
    """Per-sweep run metadata for the M6.2 artifact. Extends M6.1.3's RunMeta
    schema-wise with M6.2's round-4 controls (iteration discipline, wall-clock
    bounds, Modal spend) and round-5 controls (corpus SHAs, sub-probe flag).
    """

    git_sha: str
    modal_region: str
    base_seed: int
    model_identifier: str
    dispatch_mode: Literal["concurrent"]  # always "concurrent" per FR-007
    symmetric_prompts_enabled: bool  # always True per FR-008
    schema_version: Literal["m6_1_1.v1"]  # unchanged per FR-011
    sweep_mode: M6_2SweepMode
    m6_1_3_baseline_artifact_path: str  # default docs/benchmarks/m6_1_3-attribution-closure.json
    iteration_order: Literal["cohort_innermost_block"]  # FR-030
    iteration_discipline_verified: bool  # FR-032 post-hoc machine check
    n_per_point: int  # round-3-pinned (publish) or 20 (validate)
    validate_axis_subset: list[int] | None  # [10, 50, 2048] in validate; None in publish
    wall_clock_start_utc: str
    wall_clock_end_utc: str
    total_sweep_hours: float
    modal_spend_usd_estimate: float | None
    # Round-5 corpus-SHA pinning (SC-018).
    chat_corpus_sha256: str
    chat_corpus_path: str
    embed_corpus_sha256: str
    embed_corpus_path: str
    sub_probe_ran: bool  # True in both publish + validate per SC-019
    # T074c / T074e — Modal preemption recovery telemetry. Total count of
    # successful (DETECTED → RECOVERED) preemption-recovery cycles across
    # the block dispatcher AND the anchor dispatcher for this sweep.
    # ``0`` is the happy-path value (no Modal preemption mid-sweep);
    # non-zero values indicate the run survived ``preemption_events`` Modal
    # worker restarts via T074's recovery loop. Capped at
    # ``M6_2_PREEMPTION_RECURRENCE_THRESHOLD`` per dispatcher (the next
    # recovery aborts the sweep cleanly via ``PreemptionBudgetExhausted``).
    # Backward-compatible default ``0`` preserves the M6.1.3 strict-superset
    # contract — pre-T074 readers ignore the new key cleanly.
    preemption_events: int = 0


@dataclass(slots=True, kw_only=True)
class M6_2SweepArtifact:
    """The top-level M6.2 artifact payload persisted to
    ``docs/benchmarks/m6_2-token-budget.json`` (or ``-validate.json``).

    Strict-superset over M6.1.3 per FR-011 (the seven NEW top-level keys are
    additive; pre-M6.2 readers ignore them without parse error).
    ``schema_version`` stays at ``"m6_1_1.v1"``.
    """

    schema_version: Literal["m6_1_1.v1"]
    dispatch_mode: Literal["concurrent"]
    run_id: str
    run_started_at: str
    run_completed_at: str
    run_meta: M6_2RunMeta
    # Per-cell × per-cohort × per-max_tokens latency budget table.
    per_cell: dict[str, dict[M6_1_2CohortKind, dict[int, M6_2MeasurementPoint]]]
    # M6.1.3 inheritance — topology probe trajectory.
    network_paths: dict[
        M6_1_2CohortKind,
        list[M6_1_2NetworkPath | M6_1_2NetworkPathError],
    ]
    cohort_set: list[M6_1_2CohortKind]
    cohort_omissions: M6_1_2CohortOmissions | None
    # M6.2 additive top-level keys.
    null_anchor_validation: list[M6_2NullAnchor]
    max_tokens_axis: list[int]
    protocol_crossover: list[M6_2CrossoverThreshold]
    kv_pressure_observation: list[M6_2KVPressureObservation]
    anchor_latency_trajectory: dict[M6_1_2CohortKind, M6_2AnchorLatencyTrajectory]
    failure_summary: dict[str, int] = field(default_factory=dict)
    integrity_warnings: list[str] = field(default_factory=list)


__all__ = [
    # Re-exports from m6_1_2_types
    "M6_1_2_COHORTS",
    "M6_1_2CloudProvider",
    "M6_1_2CohortKind",
    "M6_1_2CohortOmissions",
    "M6_1_2NetworkPath",
    "M6_1_2NetworkPathError",
    "M6_1_2NetworkPathHop",
    # Axis constants
    "M6_2_MAX_TOKENS_AXIS",
    "M6_2_VALIDATE_MAX_TOKENS_AXIS",
    "M6_2_NULL_ANCHOR_MAX_TOKENS",
    "M6_2_INTERIOR_CAP_MAX_TOKENS",
    "M6_2_SUB_PROBE_MAX_TOKENS",
    "M6_2_SUB_PROBE_N",
    "M6_2_PUBLISH_N",
    "M6_2_KV_PRESSURE_THRESHOLD",
    "M6_2_NULL_ANCHOR_DRIFT_COUNT_THRESHOLD",
    "M6_2_LATENCY_DRIFT_COHORT_COUNT_THRESHOLD",
    "M6_2_FAILURE_SUMMARY_CELL_COUNT_THRESHOLD",
    # Literals
    "M6_2SweepMode",
    "M6_2PromptSource",
    "M6_2MeasurementRegime",
    "M6_2WallClockInferenceLabel",
    "M6_2DriftVerdict",
    # Dataclasses
    "M6_2AnchorLatencySnapshot",
    "M6_2AnchorLatencyTrajectory",
    "M6_2CrossoverThreshold",
    "M6_2KVPressureObservation",
    "M6_2MeasurementPoint",
    "M6_2NullAnchor",
    "M6_2RunMeta",
    "M6_2SweepArtifact",
]
