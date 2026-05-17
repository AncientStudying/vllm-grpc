"""M6.1 — Real-Prompt-Embeds Engine Path: shared types and cell-iteration constants.

Data shapes follow ``specs/022-m6-1-real-prompt-embeds/data-model.md``.

M6.1 reuses M6's cell + RPC + cohort entity shapes verbatim and adds three
M6.1-specific extensions:

* ``M6_1CellRecord`` adds ``chat_stream_control_drift_warning`` (FR-029).
* ``M6_1RunMeta`` adds ``seq_len``, ``M6_1_BASE_SEED``, ``torch_version``,
  ``m6_baseline_engine_version``, and ``m6_winner_deltas`` (FR-006/008/027/028/030).
* ``M6_1Run`` adds ``supersedes_m6_under_enable_prompt_embeds`` (US1 / FR-020),
  ``engine_path_differential`` (US2 / FR-020), and an ``m6_meta`` back-reference
  passthrough (FR-021 strict-superset compatibility).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from vllm_grpc_bench.m3_types import RTTRecord
from vllm_grpc_bench.m6_types import (
    M6_CHAT_MAX_TOKENS,
    M6_HIDDEN_SIZE,
    M6_MEASUREMENT_N,
    M6_RPC_RETRY_MAX,
    M6_SMOKE_N,
    M6_WARMUP_N,
    ClassifierMetric,
    EngineCostAggregate,
    EngineCostSpan,
    M6Cell,
    M6CohortKind,
    M6Concurrency,
    M6Path,
    M6PerCohortAggregate,
    M6PerRequestEvent,
    M6RPCMeasurement,
    RpcPhase,
    VerdictClassification,
    cell_key,
)

# --- M6.1 aliases (preserve M6 shapes verbatim) ------------------------------

# ``M6_1Cell`` is an alias for :class:`M6Cell`. The ``concurrency`` field
# carries the M6.0a semantics (FR-006): actual in-flight parallelism (peak
# concurrent RPCs per cohort within a c-batch). See :class:`M6Cell` for the
# full docstring.
M6_1Cell = M6Cell
M6_1CohortKind = M6CohortKind
M6_1Path = M6Path
M6_1Concurrency = M6Concurrency
M6_1RPCMeasurement = M6RPCMeasurement
M6_1PerCohortAggregate = M6PerCohortAggregate
M6_1PerRequestEvent = M6PerRequestEvent

# --- Cell-iteration constants (data-model.md `M6_1Cell.Identity`) ------------

M6_1_PATHS: tuple[M6_1Path, ...] = ("embed", "chat_stream")
M6_1_HIDDEN_SIZE: Literal[4096] = M6_HIDDEN_SIZE
M6_1_CONCURRENCIES: tuple[M6_1Concurrency, ...] = (1, 4, 8)

M6_1_CELLS: tuple[tuple[M6_1Path, Literal[4096], M6_1Concurrency], ...] = (
    ("embed", 4096, 1),
    ("embed", 4096, 4),
    ("embed", 4096, 8),
    ("chat_stream", 4096, 1),
    ("chat_stream", 4096, 4),
    ("chat_stream", 4096, 8),
)

M6_1_COHORTS: tuple[M6_1CohortKind, ...] = (
    "rest_https_edge",
    "default_grpc",
    "tuned_grpc_multiplexed",
)

M6_1_SMOKE_CELLS: tuple[tuple[M6_1Path, Literal[4096], Literal[1]], ...] = (
    ("embed", 4096, 1),
    ("chat_stream", 4096, 1),
)

M6_1_MEASUREMENT_N: int = M6_MEASUREMENT_N
M6_1_WARMUP_N: int = M6_WARMUP_N
M6_1_SMOKE_N: int = M6_SMOKE_N
M6_1_RPC_RETRY_MAX: int = M6_RPC_RETRY_MAX
M6_1_CHAT_MAX_TOKENS: int = M6_CHAT_MAX_TOKENS
M6_1_CELL_COMPLETE_FLOOR: int = 80
M6_1_BURIED_BY_ENGINE_FACTOR: float = 5.0
M6_1_DRIFT_WARNING_PCT: float = 0.10
DEFAULT_M6_1_BASE_SEED: int = 42

# Canonical prompt-embeds tensor shape + dtype constants (FR-028).
M6_1_PROMPT_EMBED_DTYPE: Literal["float16"] = "float16"
M6_1_PROMPT_EMBED_HIDDEN_SIZE: Literal[4096] = M6_HIDDEN_SIZE

# Pinned client-side torch version (FR-006 / R-2).
M6_1_EXPECTED_TORCH_VERSION: str = "2.11.0"


# --- M6.1 cell-level entities -----------------------------------------------


@dataclass(frozen=True)
class M6_1CellRecord:
    """Full per-cell record published in the JSON companion.

    Extends ``M6CellRecord`` with one new field
    (``chat_stream_control_drift_warning``) and retargets the winner-delta
    references at the M6 baseline.
    """

    cell: M6_1Cell
    per_cohort: dict[M6_1CohortKind, M6_1PerCohortAggregate]
    classification: VerdictClassification
    classification_reason: str
    classifier_metric: ClassifierMetric
    cohort_pair: tuple[M6_1CohortKind, M6_1CohortKind]
    m6_winner_delta_ms: float | None
    m6_winner_direction: Literal["rest_wins", "grpc_wins"] | None
    engine_cost_mean_ms: float
    engine_cost_drift_warning: bool
    per_cohort_engine_cost_mean_ms: dict[M6_1CohortKind, float] | None
    chat_stream_control_drift_warning: bool


# --- Engine path differential -----------------------------------------------


@dataclass(frozen=True)
class EnginePathDifferentialRow:
    """One row of the "Engine path differential" section (US2 / FR-020).

    Populated for every cell, including ``cell_incomplete`` cells (SC-007).
    """

    cell: M6_1Cell
    per_cohort_classifier_metric_delta_ms: dict[M6_1CohortKind, float]
    per_cohort_classifier_metric_delta_ci_half_width_ms: dict[M6_1CohortKind, float]
    engine_cost_mean_delta_ms: float
    engine_cost_mean_delta_ci_half_width_ms: float
    per_cohort_n_successes: dict[M6_1CohortKind, int]


# --- Sweep-level entities ---------------------------------------------------


@dataclass(frozen=True)
class M6_1RunMeta:
    """Run metadata embedded in the JSON companion (FR-027)."""

    git_sha: str
    hostname: str
    modal_function_id: str
    gpu_type: Literal["A10G"]
    modal_region: str
    model_identifier: str
    hidden_size: Literal[4096]
    M6_1_BASE_SEED: int
    seq_len: int
    engine_version: str
    m6_baseline_engine_version: str
    torch_version: str
    m6_winner_deltas: dict[str, float | None]
    cold_start_s: float
    max_model_len: int
    gpu_memory_utilization: float
    run_started_at: str
    run_completed_at: str


@dataclass(frozen=True)
class M6_1SmokeOutcome:
    cell: M6_1Cell
    cohort: M6_1CohortKind
    status: Literal["ok", "failed"]
    reason: str


@dataclass(frozen=True)
class M6_1SmokeResult:
    outcomes: list[M6_1SmokeOutcome]
    overall_status: Literal["ok", "failed"]
    wall_clock_s: float


@dataclass(frozen=True)
class SupersedesM6Row:
    """One row of the "Supersedes M6 under enable_prompt_embeds" table (US1)."""

    cell: M6_1Cell
    classification: VerdictClassification
    m6_1_classifier_metric_mean_per_cohort: dict[M6_1CohortKind, float]
    m6_1_classifier_metric_ci_per_cohort: dict[M6_1CohortKind, tuple[float, float]]
    m6_winner_cohort: M6_1CohortKind | None
    m6_winner_delta_ms: float | None
    m6_winner_direction: Literal["rest_wins", "grpc_wins"] | None
    engine_cost_mean_ms: float
    engine_cost_drift_warning: bool
    chat_stream_control_drift_warning: bool
    notes: str


@dataclass(frozen=True)
class M6_1Run:
    """Top-level published JSON shape — strict superset of M6's ``M6Run``."""

    run_id: str
    run_started_at: str
    run_completed_at: str
    run_meta: M6_1RunMeta
    smoke_result: M6_1SmokeResult | None
    cells: list[M6_1CellRecord]
    rtt_distribution: dict[M6_1CohortKind, RTTRecord]
    supersedes_m6_under_enable_prompt_embeds: list[SupersedesM6Row]
    engine_path_differential: list[EnginePathDifferentialRow]
    # M6-strict-superset back-reference (FR-021): passthrough copy of M6
    # baseline JSON's ``m6_meta`` block for consumers that index by the old key.
    m6_meta: dict[str, Any]


# --- Prompt-embeds tensor payload (logical view per FR-028) -----------------


@dataclass(frozen=True)
class PromptEmbedsTensorPayload:
    shape: tuple[int, int]
    dtype: Literal["float16"]
    grpc_bytes: bytes
    rest_input_b64: str


# --- Helpers -----------------------------------------------------------------


def make_cells() -> list[M6_1Cell]:
    """Return the canonical list of 6 M6.1 cells in iteration order."""
    return [M6_1Cell(path=p, hidden_size=h, concurrency=c) for (p, h, c) in M6_1_CELLS]


def make_smoke_cells() -> list[M6_1Cell]:
    """Return the 2 smoke cells (FR-012)."""
    return [M6_1Cell(path=p, hidden_size=h, concurrency=c) for (p, h, c) in M6_1_SMOKE_CELLS]


__all__ = [
    "DEFAULT_M6_1_BASE_SEED",
    "EnginePathDifferentialRow",
    "EngineCostAggregate",
    "EngineCostSpan",
    "M6_1Cell",
    "M6_1CellRecord",
    "M6_1CohortKind",
    "M6_1Concurrency",
    "M6_1Path",
    "M6_1PerCohortAggregate",
    "M6_1PerRequestEvent",
    "M6_1RPCMeasurement",
    "M6_1Run",
    "M6_1RunMeta",
    "M6_1SmokeOutcome",
    "M6_1SmokeResult",
    "M6_1_BURIED_BY_ENGINE_FACTOR",
    "M6_1_CELLS",
    "M6_1_CELL_COMPLETE_FLOOR",
    "M6_1_CHAT_MAX_TOKENS",
    "M6_1_COHORTS",
    "M6_1_CONCURRENCIES",
    "M6_1_DRIFT_WARNING_PCT",
    "M6_1_EXPECTED_TORCH_VERSION",
    "M6_1_HIDDEN_SIZE",
    "M6_1_MEASUREMENT_N",
    "M6_1_PATHS",
    "M6_1_PROMPT_EMBED_DTYPE",
    "M6_1_PROMPT_EMBED_HIDDEN_SIZE",
    "M6_1_RPC_RETRY_MAX",
    "M6_1_SMOKE_CELLS",
    "M6_1_SMOKE_N",
    "M6_1_WARMUP_N",
    "PromptEmbedsTensorPayload",
    "RTTRecord",
    "RpcPhase",
    "SupersedesM6Row",
    "VerdictClassification",
    "cell_key",
    "make_cells",
    "make_smoke_cells",
]
