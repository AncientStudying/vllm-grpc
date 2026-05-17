"""M6 — Real-Engine Mini-Validation: shared types and cell-iteration constants.

Data shapes follow `specs/020-m6-real-engine-mini-validation/data-model.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from vllm_grpc_bench.m3_types import RTTRecord

# --- Cell-iteration constants (T003) -----------------------------------------

M6Path = Literal["embed", "chat_stream"]
M6Concurrency = Literal[1, 4, 8]
M6CohortKind = Literal["rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"]
VerdictClassification = Literal[
    "verdict_survives",
    "verdict_changed",
    "verdict_buried_by_engine",
    "no_winner_at_n100",
    "cell_incomplete",
]
ClassifierMetric = Literal["wall_clock_ms", "ttft_ms"]
M5_2WinnerDirection = Literal["rest_wins", "grpc_wins"]
RpcPhase = Literal["warmup", "measurement"]

M6_PATHS: tuple[M6Path, ...] = ("embed", "chat_stream")
M6_HIDDEN_SIZE: Literal[4096] = 4096
M6_CONCURRENCIES: tuple[M6Concurrency, ...] = (1, 4, 8)

# Cell iteration order per data-model.md `M6Cell.Identity`:
#   embed × c=1, embed × c=4, embed × c=8, chat_stream × c=1, ...
M6_CELLS: tuple[tuple[M6Path, Literal[4096], M6Concurrency], ...] = (
    ("embed", 4096, 1),
    ("embed", 4096, 4),
    ("embed", 4096, 8),
    ("chat_stream", 4096, 1),
    ("chat_stream", 4096, 4),
    ("chat_stream", 4096, 8),
)

# Three cohorts measured per cell (FR-002). `rest_plain_tcp` and
# `tuned_grpc_channels` are out of scope for M6.
M6_COHORTS: tuple[M6CohortKind, ...] = (
    "rest_https_edge",
    "default_grpc",
    "tuned_grpc_multiplexed",
)

# Smoke gate exercises 2 cells × 3 cohorts × n=10 (FR-011).
M6_SMOKE_CELLS: tuple[tuple[M6Path, Literal[4096], Literal[1]], ...] = (
    ("embed", 4096, 1),
    ("chat_stream", 4096, 1),
)

# Constants used by classifier + sweep (per spec FRs).
M6_MEASUREMENT_N: int = 100  # FR-004
M6_WARMUP_N: int = 10  # FR-021
M6_CELL_COMPLETE_FLOOR: int = 80  # FR-023 (cell_incomplete threshold)
M6_RPC_RETRY_MAX: int = 3  # FR-023 per-RPC retry cap
M6_SMOKE_N: int = 10  # FR-011
M6_CHAT_MAX_TOKENS: int = 50  # FR-005
M6_BURIED_BY_ENGINE_FACTOR: float = 5.0  # FR-014 5× rule
M6_DRIFT_WARNING_PCT: float = 0.10  # FR-014 sub-clause (>10%)


# --- Per-cell identity -------------------------------------------------------


@dataclass(frozen=True)
class M6Cell:
    """One (path, hidden_size, concurrency) cell of the M6 sweep matrix.

    ``concurrency`` is the actual in-flight parallelism: the peak number
    of concurrent RPCs dispatched per cohort within a c-batch under
    M6.0a's restored concurrent dispatch (FR-006). Cohort iteration stays
    sequential; within a cohort, ``concurrency`` RPCs run concurrently
    via ``asyncio.gather`` in :mod:`vllm_grpc_bench.m6_sweep`. This shape
    is re-exported as :data:`M6_1Cell` and :data:`M6_1_1Cell`.
    """

    path: M6Path
    hidden_size: Literal[4096]
    concurrency: M6Concurrency


# --- Per-RPC measurement entities -------------------------------------------


@dataclass(frozen=True)
class EngineCostSpan:
    """Server-instrumented per-RPC engine cost (FR-008). Path-discriminated.

    Validation: ``engine_forward_ms is not None`` XOR
    (``engine_ttft_ms is not None`` AND ``engine_tpot_ms is not None``).
    """

    engine_forward_ms: float | None = None
    engine_ttft_ms: float | None = None
    engine_tpot_ms: float | None = None


@dataclass(frozen=True)
class M6RPCMeasurement:
    rpc_index: int
    cell: M6Cell
    cohort: M6CohortKind
    seed: int
    success: bool
    failure_reason: str | None
    wall_clock_ms: float | None
    ttft_ms: float | None
    engine_cost: EngineCostSpan | None
    retry_count: int


# --- Aggregate entities ------------------------------------------------------


@dataclass(frozen=True)
class EngineCostAggregate:
    """Cohort-level mean engine cost (path-discriminated)."""

    engine_forward_mean_ms: float | None = None
    engine_forward_ci_half_width_ms: float | None = None
    engine_ttft_mean_ms: float | None = None
    engine_ttft_ci_half_width_ms: float | None = None
    engine_tpot_mean_ms: float | None = None
    engine_tpot_ci_half_width_ms: float | None = None


@dataclass(frozen=True)
class M6PerCohortAggregate:
    cohort: M6CohortKind
    n_attempted: int
    n_successes: int
    failure_count: int
    classifier_metric_mean_ms: float
    classifier_metric_ci_half_width_ms: float
    total_wall_clock_mean_ms: float
    total_wall_clock_ci_half_width_ms: float
    engine_cost_mean: EngineCostAggregate


@dataclass(frozen=True)
class M6CellRecord:
    cell: M6Cell
    per_cohort: dict[M6CohortKind, M6PerCohortAggregate]
    classification: VerdictClassification
    classification_reason: str
    classifier_metric: ClassifierMetric
    cohort_pair: tuple[M6CohortKind, M6CohortKind]
    m5_2_winner_delta_ms: float | None
    m5_2_winner_direction: M5_2WinnerDirection | None
    engine_cost_mean_ms: float
    engine_cost_drift_warning: bool
    per_cohort_engine_cost_mean_ms: dict[M6CohortKind, float] | None


# --- Sweep-level entities ----------------------------------------------------


@dataclass(frozen=True)
class M6RunMeta:
    git_sha: str
    hostname: str
    modal_function_id: str
    gpu_type: Literal["A10G"]
    modal_region: str
    model_identifier: str
    engine_version: str
    cold_start_s: float
    m5_2_winner_deltas: dict[str, float | None]
    m6_base_seed: int


@dataclass(frozen=True)
class M6SmokeOutcome:
    cell: M6Cell
    cohort: M6CohortKind
    status: Literal["ok", "failed"]
    reason: str


@dataclass(frozen=True)
class M6SmokeResult:
    outcomes: list[M6SmokeOutcome]
    overall_status: Literal["ok", "failed"]
    wall_clock_s: float


@dataclass(frozen=True)
class SupersedesM5_2Row:
    cell: M6Cell
    classification: VerdictClassification
    m6_classifier_metric_mean_per_cohort: dict[M6CohortKind, float]
    m6_classifier_metric_ci_per_cohort: dict[M6CohortKind, tuple[float, float]]
    m5_2_winner_cohort: M6CohortKind | None
    m5_2_winner_delta_ms: float | None
    m5_2_winner_direction: M5_2WinnerDirection | None
    engine_cost_mean_ms: float
    engine_cost_drift_warning: bool
    # T050 / FR-014 sub-clause: per-cohort engine_cost means MUST be
    # surfaced for operator review when drift fires; MUST be None
    # otherwise per data-model.md M6CellRecord validation rule.
    per_cohort_engine_cost_mean_ms: dict[M6CohortKind, float] | None
    notes: str


@dataclass(frozen=True)
class M6Run:
    run_id: str
    run_started_at: str
    run_completed_at: str
    meta: M6RunMeta
    smoke_result: M6SmokeResult | None
    cells: list[M6CellRecord]
    rtt_distribution: dict[M6CohortKind, RTTRecord]
    supersedes_m5_2: list[SupersedesM5_2Row]


# --- Per-RPC events sidecar extension (M6PerRequestEvent) -------------------


@dataclass(frozen=True)
class M6PerRequestEvent:
    """Extends M5.2's ``PerRequestEventRecord`` with M6-only fields.

    Validation rules per data-model.md:
    - ``rpc_phase == "warmup"`` ⇒ ``rpc_index is None`` AND ``seed is None``.
    - ``rpc_phase == "measurement"`` ⇒ both set.
    - ``cell_path == "embed"`` ⇒ engine_ttft_ms / engine_tpot_ms None.
    - ``cell_path == "chat_stream"`` ⇒ engine_forward_ms None.
    """

    cohort: M6CohortKind
    cell_path: M6Path
    cell_hidden_size: Literal[4096]
    cell_concurrency: M6Concurrency
    network_path: Literal["https_edge", "plain_tcp"]
    request_uuid: str
    rpc_elapsed_ms: float
    rpc_phase: RpcPhase
    rpc_index: int | None
    seed: int | None
    engine_forward_ms: float | None
    engine_ttft_ms: float | None
    engine_tpot_ms: float | None
    success: bool
    failure_reason: str | None
    retry_count: int


# --- Helpers ----------------------------------------------------------------


def cell_key(cell: M6Cell) -> str:
    """Key format used in ``M6RunMeta.m5_2_winner_deltas`` and JSON output."""
    return f"{cell.path}_c{cell.concurrency}_h{cell.hidden_size}"


def make_cells() -> list[M6Cell]:
    """Return the canonical list of 6 M6 cells in iteration order."""
    return [M6Cell(path=p, hidden_size=h, concurrency=c) for (p, h, c) in M6_CELLS]


def make_smoke_cells() -> list[M6Cell]:
    """Return the 2 smoke cells (FR-011)."""
    return [M6Cell(path=p, hidden_size=h, concurrency=c) for (p, h, c) in M6_SMOKE_CELLS]


# Keep ``field`` imported for downstream modules that build M6CellRecord
# instances with dict default factories; suppress unused-import lint.
__all__ = [
    "ClassifierMetric",
    "EngineCostAggregate",
    "EngineCostSpan",
    "M5_2WinnerDirection",
    "M6_BURIED_BY_ENGINE_FACTOR",
    "M6_CELLS",
    "M6_CELL_COMPLETE_FLOOR",
    "M6_CHAT_MAX_TOKENS",
    "M6_COHORTS",
    "M6_CONCURRENCIES",
    "M6_DRIFT_WARNING_PCT",
    "M6_HIDDEN_SIZE",
    "M6_MEASUREMENT_N",
    "M6_PATHS",
    "M6_RPC_RETRY_MAX",
    "M6_SMOKE_CELLS",
    "M6_SMOKE_N",
    "M6_WARMUP_N",
    "M6Cell",
    "M6CellRecord",
    "M6CohortKind",
    "M6Concurrency",
    "M6Path",
    "M6PerCohortAggregate",
    "M6PerRequestEvent",
    "M6RPCMeasurement",
    "M6Run",
    "M6RunMeta",
    "M6SmokeOutcome",
    "M6SmokeResult",
    "RpcPhase",
    "SupersedesM5_2Row",
    "VerdictClassification",
    "cell_key",
    "field",
    "make_cells",
    "make_smoke_cells",
]
