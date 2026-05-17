"""M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation: shared types.

Data shapes follow ``specs/023-m6-1-1-engine-cost-instrumentation/data-model.md``.

M6.1.1 reuses M6.1's cell + cohort entity shapes verbatim (six 6 cells × 3
cohorts) and adds the four-checkpoint timing instrumentation plus the
sentinel-object schema (round-2 Q1 / Q2) for downstream M6.2 dispatch.

Note on dataclass framework: M6.1's ``m6_1_types.py`` uses stdlib
``@dataclass(frozen=True)`` rather than Pydantic v2 dataclasses. M6.1.1
follows the same project convention for consistency; validators live in
``__post_init__`` blocks. The "Pydantic v2" reference in
``research.md`` R-6 is documentation drift relative to actual M6.1 code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from vllm_grpc_bench.m6_1_types import (
    M6_1Cell,
    M6_1CohortKind,
)
from vllm_grpc_bench.m6_types import (
    EngineCostAggregate,
    EngineCostSpan,
)

# --- M6.1.1 aliases (preserve M6.1 / M6 shapes verbatim) --------------------

# ``M6_1_1Cell`` is an alias for :class:`M6_1Cell` (itself an alias for
# :class:`M6Cell`). The ``concurrency`` field carries the M6.0a semantics
# (FR-006): actual in-flight parallelism (peak concurrent RPCs per cohort
# within a c-batch). See :class:`M6Cell` for the full docstring.
M6_1_1Cell = M6_1Cell
M6_1_1Cohort = M6_1CohortKind

# --- Module-level constants -------------------------------------------------

M6_1_1_BASE_SEED: int = 42  # FR-027 default; identical to M6 / M6.1
PERTURBATION_BUDGET_NS: int = 500_000  # FR-012: 500 µs per RPC across 4 checkpoints

# FR-010 classifier thresholds (round-1 Q1)
DRIFT_NOT_REPRODUCED_THRESHOLD: float = 0.05  # spread / mean shortcut
ATTRIBUTION_THRESHOLD: float = 0.80  # spread(seg_x) / spread(engine_ttft)

# FR-015b embed regression tolerance (round-1 Q5)
EMBED_REGRESSION_TOLERANCE: float = 0.05

# FR-015 + FR-022 chat_stream drift-cleared tolerance (SC-003)
CHAT_STREAM_DRIFT_CLEARED_TOLERANCE: float = 0.05

# --- Literal types ----------------------------------------------------------

CheckpointName = Literal["handler_entry", "pre_engine", "first_chunk", "terminal_emit"]
SegmentName = Literal["seg_ab", "seg_bc", "seg_cd"]
Phase1Classification = Literal[
    "instrumentation_artifact",
    "channel_dependent_batching",
    "drift_not_reproduced",
    "inconclusive",
]
Phase2Path = Literal[
    "phase_2a_verified",
    "phase_2b_documented",
    "phase_2_pending",
    "drift_not_reproduced_confirmed",
    "split_required",
]
BaselineSource = Literal[
    "m6_1_1",
    "m6_1",
    "documented_in_contracts",
    "not_applicable",
]
# 0 success
# 1 missing baseline / contracts heading (FR-001, FR-004, FR-016)
# 2 torch pin mismatch (FR-003)
# 3 re-run needed: mixed / inconclusive / drift_not_reproduced single-run (FR-017, FR-018)
# 4 perturbation budget exceeded (FR-012, round-2 Q3)
# 5 milestone split required: still-divergent after re-confirmation (FR-017(b), round-2 Q4)
M6_1_1ExitCode = Literal[0, 1, 2, 3, 4, 5]

# --- Per-RPC checkpoint + segment entities ----------------------------------


@dataclass(frozen=True)
class TimingCheckpoint:
    """Four per-RPC ``perf_counter_ns()`` timestamps captured server-side and
    emitted on the wire (FR-006 / FR-007 / FR-008).

    ``perturbation_audit_ns`` is the server-measured total cost the 4 reads
    themselves added to the request lifecycle (FR-012 hard gate input).
    """

    handler_entry_ns: int
    pre_engine_ns: int
    first_chunk_ns: int
    terminal_emit_ns: int
    perturbation_audit_ns: int


@dataclass(frozen=True)
class PerSegmentDelta:
    """Three named per-RPC durations derived from the four checkpoints (FR-009)."""

    seg_ab_ms: float
    seg_bc_ms: float
    seg_cd_ms: float

    @classmethod
    def from_checkpoint(cls, ckpt: TimingCheckpoint) -> PerSegmentDelta:
        return cls(
            seg_ab_ms=(ckpt.pre_engine_ns - ckpt.handler_entry_ns) * 1e-6,
            seg_bc_ms=(ckpt.first_chunk_ns - ckpt.pre_engine_ns) * 1e-6,
            seg_cd_ms=(ckpt.terminal_emit_ns - ckpt.first_chunk_ns) * 1e-6,
        )


@dataclass(frozen=True)
class PerSegmentAggregate:
    """Mean + 95% CI half-width via bootstrap n_boot=10_000 (FR-009)."""

    seg_ab_ms_mean: float
    seg_ab_ms_ci_half_width: float
    seg_bc_ms_mean: float
    seg_bc_ms_ci_half_width: float
    seg_cd_ms_mean: float
    seg_cd_ms_ci_half_width: float
    n_samples: int


@dataclass(frozen=True)
class MultiPointTimings:
    """Per (cohort × cell) aggregated multi-point timing data (FR-009)."""

    cohort: M6_1_1Cohort
    cell: M6_1_1Cell
    engine_ttft_ms_mean: float
    engine_ttft_ms_ci_half_width: float
    per_segment: PerSegmentAggregate
    perturbation_total_us_mean: float


# --- Phase 1 audit + classification entities --------------------------------


@dataclass(frozen=True)
class PerturbationAudit:
    """FR-012 perturbation-budget audit aggregated per (cohort, cell).

    Validation: ``exceeded`` is True iff any pair's mean perturbation in
    ``per_cohort_per_cell`` exceeds ``budget_us``. ``exceeded_pairs`` is the
    list of offending ``(cohort, cell_str)`` tuples.
    """

    per_cohort_per_cell: dict[tuple[str, str], float]
    exceeded: bool
    exceeded_pairs: list[tuple[str, str]] = field(default_factory=list)
    budget_us: float = 500.0  # PERTURBATION_BUDGET_NS / 1000


@dataclass(frozen=True)
class Phase1RunRecord:
    """One ``--m6_1_1-diagnose`` invocation's complete data (round-3 Q1).

    Each Phase 1 mini-sweep produces ONE record; the M6.1.1 JSON's
    ``phase_1_runs`` array accumulates these across all runs for this M6.1.1
    instance.
    """

    run_id: str
    run_started_at: str
    run_completed_at: str
    wall_clock_s: float
    multi_point_timings: list[MultiPointTimings]
    phase_1_classifications: dict[str, Phase1Classification]
    perturbation_audit: PerturbationAudit
    n_per_cohort: int


# --- Phase 2 outcome shapes (discriminated union by phase_2_path) -----------


@dataclass(frozen=True)
class Phase2aVerifiedOutcome:
    """``phase_2_path == "phase_2a_verified"`` (FR-014, FR-015)."""

    drift_cleared_per_cell: dict[str, bool]
    engine_cost_drift_warning_per_cell: dict[str, bool]
    chat_stream_control_drift_warning: bool
    chat_stream_control_drift_note: str
    n_per_cohort: int = 100


@dataclass(frozen=True)
class Phase2bDocumentedOutcome:
    """``phase_2_path == "phase_2b_documented"`` (FR-016)."""

    contracts_heading_path: str
    contracts_heading_text: str


@dataclass(frozen=True)
class DriftNotReproducedConfirmedOutcome:
    """``phase_2_path == "drift_not_reproduced_confirmed"`` (FR-018, round-1 Q4)."""

    note: str
    confirming_run_ids: tuple[str, str]


@dataclass(frozen=True)
class SplitRequiredOutcome:
    """``phase_2_path == "split_required"`` (FR-017(b), FR-018, round-2 Q4)."""

    per_cell_classifications_after_reconfirmation: dict[str, Phase1Classification]
    proposed_split_shape: str
    operator_note: str


Phase2Outcome = (
    Phase2aVerifiedOutcome
    | Phase2bDocumentedOutcome
    | DriftNotReproducedConfirmedOutcome
    | SplitRequiredOutcome
    | None
)


# --- Embed regression check (FR-015b) ---------------------------------------


@dataclass(frozen=True)
class EmbedRegressionResult:
    """FR-015b per (embed cell × cohort) regression check."""

    cell: M6_1_1Cell
    cohort: M6_1_1Cohort
    m6_1_engine_forward_ms_mean: float
    m6_1_1_engine_forward_ms_mean: float
    delta_pct: float
    embed_regression_warning: bool
    embed_regression_acknowledged: bool = False
    operator_justification: str | None = None


@dataclass(frozen=True)
class EmbedRegressionCheckResult:
    """Aggregated FR-015b check result; populated only under Phase 2(a)."""

    per_entry: list[EmbedRegressionResult]
    n_warnings: int
    all_within_tolerance: bool
    acknowledged_count: int


# --- Sentinel baseline shapes (round-2 Q1 / Q2) -----------------------------


@dataclass(frozen=True)
class BaselineCellEntry:
    """One (cell × cohort) entry in a populated baseline section.

    Fields are conditionally populated by ``cell.path``: chat_stream cells
    carry ``engine_ttft_ms_*`` and ``engine_tpot_ms_*``; embed cells carry
    ``engine_forward_ms_*`` and (FR-015c) ``regression_warning``. The other
    branch's fields are ``None``.
    """

    cell: M6_1_1Cell
    cohort: M6_1_1Cohort
    engine_ttft_ms_mean: float | None
    engine_ttft_ms_ci_half_width: float | None
    engine_tpot_ms_mean: float | None
    engine_tpot_ms_ci_half_width: float | None
    engine_forward_ms_mean: float | None
    engine_forward_ms_ci_half_width: float | None
    n_successes: int
    regression_warning: bool | None


@dataclass(frozen=True)
class BaselineSentinel:
    """Sentinel-object shape for chat_stream_baseline_post_symmetrisation and
    embed_baseline_post_symmetrisation (round-2 Q1 / Q2).

    Always present in M6.1.1's JSON even under non-Phase-2(a) outcomes —
    strict-superset compatibility per FR-022. Consumers dispatch on
    ``baseline_source`` alone, never on ``phase_2_path``.
    """

    phase_2_path: Phase2Path
    baseline_source: BaselineSource
    pointer: str | None
    cells: list[BaselineCellEntry] | None


# --- Operator-discretionary annotations -------------------------------------


@dataclass(frozen=True)
class Phase2Choice:
    """Operator's discretionary annotation when applicable (FR-017(b), FR-015b path (ii))."""

    embed_regression_acknowledged: bool = False
    embed_regression_justification: str | None = None
    split_required_proposed_shape: str | None = None
    split_required_operator_note: str | None = None


# --- Run-level metadata + top-level container -------------------------------


@dataclass(frozen=True)
class M6_1_1RunMeta:
    """Run-level metadata; mirrors M6.1's RunMeta shape (FR-021 strict-superset)
    plus M6.1.1 fields."""

    # M6.1 lineage
    git_sha: str
    hostname: str
    modal_function_id: str | None
    gpu_type: str
    modal_region: str
    model_identifier: str
    hidden_size: int
    cold_start_s: float
    max_model_len: int
    gpu_memory_utilization: float
    engine_version: str
    m6_1_baseline_engine_version: str
    torch_version: str
    # M6.1.1 additions
    M6_1_1_BASE_SEED: int
    seq_len: int
    phase_1_n: int
    phase_2_path: Phase2Path
    run_started_at: str
    run_completed_at: str


@dataclass(frozen=True)
class M6_1_1Run:
    """Top-level published JSON shape — strict superset of M6.1's schema.

    Validation: ``phase_1_runs`` is non-empty (M6.1.1 cannot publish a report
    without at least one Phase 1 run); ``phase_2_outcome``'s concrete type
    matches ``run_meta.phase_2_path``.
    """

    schema_version: Literal["m6_1_1.v1"]
    run_id: str
    run_started_at: str
    run_completed_at: str
    run_meta: M6_1_1RunMeta
    # Phase 1 data
    phase_1_classifications: dict[str, Phase1Classification]
    phase_1_runs: list[Phase1RunRecord]
    multi_point_timings: list[MultiPointTimings]
    # Phase 2 data
    phase_2_outcome: Phase2Outcome
    phase_2_choice: Phase2Choice | None
    # Always-present sentinel sections per FR-022
    chat_stream_baseline_post_symmetrisation: BaselineSentinel
    embed_baseline_post_symmetrisation: BaselineSentinel
    embed_regression_check: EmbedRegressionCheckResult | None
    # Pointers
    m6_1_baseline_pointer: str
    methodology_supersedence: str

    def __post_init__(self) -> None:
        if not self.phase_1_runs:
            raise ValueError(
                "M6_1_1Run.phase_1_runs must be non-empty: M6.1.1 cannot publish "
                "a report without at least one Phase 1 run."
            )
        path = self.run_meta.phase_2_path
        outcome = self.phase_2_outcome
        match (path, outcome):
            case ("phase_2_pending", None):
                pass
            case ("phase_2a_verified", Phase2aVerifiedOutcome()):
                pass
            case ("phase_2b_documented", Phase2bDocumentedOutcome()):
                pass
            case ("drift_not_reproduced_confirmed", DriftNotReproducedConfirmedOutcome()):
                pass
            case ("split_required", SplitRequiredOutcome()):
                pass
            case _:
                raise ValueError(
                    f"phase_2_outcome type {type(outcome).__name__} "
                    f"inconsistent with run_meta.phase_2_path={path!r}"
                )


__all__ = [
    "ATTRIBUTION_THRESHOLD",
    "BaselineCellEntry",
    "BaselineSentinel",
    "BaselineSource",
    "CHAT_STREAM_DRIFT_CLEARED_TOLERANCE",
    "CheckpointName",
    "DRIFT_NOT_REPRODUCED_THRESHOLD",
    "DriftNotReproducedConfirmedOutcome",
    "EMBED_REGRESSION_TOLERANCE",
    "EmbedRegressionCheckResult",
    "EmbedRegressionResult",
    "EngineCostAggregate",
    "EngineCostSpan",
    "M6_1_1Cell",
    "M6_1_1Cohort",
    "M6_1_1ExitCode",
    "M6_1_1Run",
    "M6_1_1RunMeta",
    "M6_1_1_BASE_SEED",
    "MultiPointTimings",
    "PERTURBATION_BUDGET_NS",
    "PerSegmentAggregate",
    "PerSegmentDelta",
    "PerturbationAudit",
    "Phase1Classification",
    "Phase1RunRecord",
    "Phase2Choice",
    "Phase2Outcome",
    "Phase2Path",
    "Phase2aVerifiedOutcome",
    "Phase2bDocumentedOutcome",
    "SegmentName",
    "SplitRequiredOutcome",
    "TimingCheckpoint",
]
