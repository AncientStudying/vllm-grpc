"""In-process data model for the M3 + M4 sweeps (``data-model.md``).

These are **not** wire types — for wire types see ``proto/vllm_grpc/v1/*.proto``.

M4 extends this module in place rather than introducing a sibling: the new
``Verdict`` literal ``"client_bound"``, ``BaselineRole``, ``ExpansionRecord``,
``FrozenChannelBaseline``, ``SchemaCandidate*``, and ``SupersessionEntry``
types are additive, and the existing M3 dataclasses (``BenchmarkCell``,
``Sample``, ``RunCohort``, ``Recommendation``, ``ProtoRevision``) are kept
unchanged so M3's reanalyze path keeps compiling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from vllm_grpc_bench.channel_config import Axis, ChannelConfig

Path_ = Literal["embed", "chat_stream"]
CorpusSubset = Literal["m1_chat", "m1_embed", "m3_long_stream"]
# ``noise_bounded`` is M3-only — preserved here for compatibility with the
# already-published ``m3-channel-tuning-time.json`` reanalyze path.  M4's
# recommendation builder forbids constructing a ``Recommendation`` with this
# verdict (FR-007); the runtime check lives in ``m4_sweep.validate_run``.
Verdict = Literal[
    "recommend",
    "no_winner",
    "not_measurable",
    "noise_bounded",
    "client_bound",
]
ErrorKind = Literal["rpc_aborted", "max_msg_exceeded", "timeout", "other"]
WinningMetric = Literal["bytes", "time", "ttft"]
AppliesPath = Literal["embed", "chat_stream", "both"]
BaselineRole = Literal["m1_shared", "frozen_channel"]
PacingMode = Literal["paced", "no_pacing"]

CANONICAL_WIDTHS: frozenset[int] = frozenset({2048, 4096, 8192})


@dataclass(frozen=True)
class BenchmarkCell:
    path: Path_
    hidden_size: int
    channel_config: ChannelConfig
    corpus_subset: CorpusSubset
    iterations: int = 30

    def __post_init__(self) -> None:
        if self.hidden_size <= 0:
            raise ValueError("BenchmarkCell.hidden_size must be > 0")
        if self.iterations < 1:
            raise ValueError("BenchmarkCell.iterations must be >= 1")
        if self.path == "embed" and self.corpus_subset != "m1_embed":
            raise ValueError(
                f"path/corpus_subset mismatch: path=embed requires "
                f"corpus_subset=m1_embed, got {self.corpus_subset}"
            )
        if self.path == "chat_stream" and self.corpus_subset not in (
            "m1_chat",
            "m3_long_stream",
        ):
            raise ValueError(
                f"path/corpus_subset mismatch: path=chat_stream requires "
                f"corpus_subset in (m1_chat, m3_long_stream), got {self.corpus_subset}"
            )

    @property
    def cell_id(self) -> str:
        return f"{self.path}|h{self.hidden_size}|{self.channel_config.name}|{self.corpus_subset}"

    @property
    def off_canonical(self) -> bool:
        return self.hidden_size not in CANONICAL_WIDTHS


@dataclass(frozen=True)
class Sample:
    cell_id: str
    iteration: int
    request_wire_bytes: int
    response_wire_bytes: int
    wall_clock_seconds: float
    tokens_emitted: int | None = None
    time_to_first_token_seconds: float | None = None
    mean_inter_token_seconds: float | None = None
    inter_token_seconds_stddev: float | None = None
    off_canonical: bool = False
    error: str | None = None
    error_kind: ErrorKind | None = None


@dataclass(frozen=True)
class RunCohort:
    cell: BenchmarkCell
    samples: tuple[Sample, ...]
    n_successful: int
    bytes_mean: float
    bytes_ci_low: float
    bytes_ci_high: float
    time_mean: float
    time_ci_low: float
    time_ci_high: float
    measurable: bool = True
    # M4 additions — defaults preserve M3 JSON shape and M3 builder paths.
    is_baseline: bool = False
    baseline_role: BaselineRole | None = None
    expansion_record: ExpansionRecord | None = None
    client_bound: bool = False
    # Cohort-level TTFT summary (mean, ci_low, ci_high). None for embed
    # cohorts; populated for chat_stream cohorts when the M4 sweep aggregates
    # per-sample TTFTs (FR-003 promotion). M3 cohorts leave this unset.
    time_to_first_token_seconds: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class Recommendation:
    axis: Axis
    applies_to_path: AppliesPath
    applies_to_widths: frozenset[int]
    verdict: Verdict
    baseline_ci_upper: float
    citation: str
    winning_config: ChannelConfig | None = None
    winning_delta_pct: float | None = None
    winning_metric: WinningMetric | None = None
    candidate_ci_lower: float | None = None
    notes: str = ""
    corpus_subset: CorpusSubset | None = None

    def __post_init__(self) -> None:
        if not self.applies_to_widths:
            raise ValueError("Recommendation.applies_to_widths must be non-empty")
        if not self.citation:
            raise ValueError("Recommendation.citation must be non-empty")
        if self.verdict == "recommend":
            missing = [
                f
                for f, v in (
                    ("winning_config", self.winning_config),
                    ("winning_delta_pct", self.winning_delta_pct),
                    ("winning_metric", self.winning_metric),
                    ("candidate_ci_lower", self.candidate_ci_lower),
                )
                if v is None
            ]
            if missing:
                raise ValueError(f"Recommendation(verdict=recommend) missing fields: {missing}")
            assert self.candidate_ci_lower is not None
            if self.candidate_ci_lower <= self.baseline_ci_upper:
                raise ValueError(
                    "Recommendation(verdict=recommend) requires "
                    "candidate_ci_lower > baseline_ci_upper (SC-003)"
                )
        if self.verdict == "noise_bounded" and not self.notes:
            raise ValueError(
                "Recommendation(verdict=noise_bounded) requires a populated "
                "notes field naming the dominating noise source (FR-005)"
            )


@dataclass(frozen=True)
class ProtoRevision:
    name: str
    description: str
    target_files: tuple[str, ...]
    frozen_channel_config: ChannelConfig
    client_compat_break: bool = False

    def __post_init__(self) -> None:
        import re

        if not re.match(r"^[a-z0-9][a-z0-9-]+[a-z0-9]$", self.name):
            raise ValueError(f"ProtoRevision.name {self.name!r} must be kebab-case")
        if not self.description:
            raise ValueError("ProtoRevision.description must be non-empty")
        if not self.target_files:
            raise ValueError("ProtoRevision.target_files must be non-empty")


# ---------------------------------------------------------------------------
# M4 additions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpansionRecord:
    """Documents the FR-002 / R-4 borderline-expand decision for one cohort.

    A cohort that did *not* trigger the borderline rule still records
    ``ExpansionRecord(initial_n=100, initial_ci_overlapped=False,
    expanded=False, final_n=100, expansion_reason=None)`` so the JSON shape
    is uniform across cohorts.
    """

    initial_n: int
    initial_ci_overlapped: bool
    expanded: bool
    final_n: int
    expansion_reason: str | None = None

    def __post_init__(self) -> None:
        if self.initial_n < 1:
            raise ValueError("ExpansionRecord.initial_n must be >= 1")
        if self.final_n < self.initial_n:
            raise ValueError(
                "ExpansionRecord.final_n must be >= initial_n "
                f"(got {self.final_n} < {self.initial_n})"
            )
        if self.expanded and self.final_n == self.initial_n:
            raise ValueError("ExpansionRecord.expanded=True requires final_n > initial_n")
        if not self.expanded and self.final_n != self.initial_n:
            raise ValueError("ExpansionRecord.expanded=False requires final_n == initial_n")


@dataclass(frozen=True)
class FrozenChannelBaseline:
    """Per-path frozen-channel baseline (R-3). One per path."""

    path: Path_
    cohort_id: str
    channel_config_name: str
    per_axis_winners: dict[str, str]
    measured_at_hidden_size: int


@dataclass(frozen=True)
class SchemaCandidatePerWidth:
    """Per-width verdict for a single schema candidate."""

    hidden_size: int
    frozen_baseline_cohort_id: str
    candidate_cohort_id: str
    bytes_verdict: Verdict
    time_verdict: Verdict
    primary_metric: Literal["bytes", "time"]
    delta_bytes_pct: float | None
    delta_time_pct: float | None
    ci_overlap_initial: bool
    expanded: bool


@dataclass(frozen=True)
class SchemaCandidateResult:
    """Aggregated schema-candidate verdict spanning one or more widths."""

    candidate_name: str
    proto_file: str
    measured_widths: list[int]
    per_width: list[SchemaCandidatePerWidth]
    is_negative_result: bool
    notes: str | None = None


@dataclass(frozen=True)
class SupersessionEntry:
    """One row in the M4 'Supersedes M3' table (FR-009)."""

    m3_cell_id: str
    m3_verdict: str
    m4_cell_id: str
    m4_verdict: Verdict
    rationale: str

    def __post_init__(self) -> None:
        if not self.m3_cell_id:
            raise ValueError("SupersessionEntry.m3_cell_id must be non-empty")
        if not self.m4_cell_id:
            raise ValueError("SupersessionEntry.m4_cell_id must be non-empty")
        if not self.rationale:
            raise ValueError("SupersessionEntry.rationale must be non-empty")
        if self.m4_verdict == "noise_bounded":
            raise ValueError("SupersessionEntry.m4_verdict must never be 'noise_bounded' (FR-007)")


@dataclass(frozen=True)
class M4SweepConfig:
    """Top-level configuration for the M4 sweep (consumed by ``m4_sweep``)."""

    pacing_mode: PacingMode = "no_pacing"
    shared_baseline: bool = True
    baseline_n: int = 100
    candidate_n: int = 100
    expand_n: int = 250
    baseline_cv_max: float = 0.05
    widths: tuple[int, ...] = (2048, 4096, 8192)
    paths: tuple[Path_, ...] = ("embed", "chat_stream")
    axes: tuple[str, ...] = (
        "max_message_size",
        "keepalive",
        "compression",
        "http2_framing",
    )
    loopback_caveat_axes: frozenset[str] = frozenset({"keepalive", "http2_framing"})
    schema_candidates: tuple[str, ...] = (
        "packed_token_ids",
        "oneof_flattened_input",
        "chunk_granularity",
    )
    schema_canonical_width: int = 4096
    skip_schema: bool = False
    seed: int = 0

    def __post_init__(self) -> None:
        if self.baseline_n < 100:
            raise ValueError("M4SweepConfig.baseline_n must be >= 100 (FR-002)")
        if self.candidate_n < 100:
            raise ValueError("M4SweepConfig.candidate_n must be >= 100 (FR-002)")
        if self.expand_n <= self.candidate_n:
            raise ValueError(
                "M4SweepConfig.expand_n must be > candidate_n "
                f"(got {self.expand_n} <= {self.candidate_n})"
            )
        if self.baseline_cv_max <= 0:
            raise ValueError("M4SweepConfig.baseline_cv_max must be > 0")
        if not self.widths:
            raise ValueError("M4SweepConfig.widths must be non-empty")
        if not self.paths:
            raise ValueError("M4SweepConfig.paths must be non-empty")
        if not self.axes:
            raise ValueError("M4SweepConfig.axes must be non-empty")
        if self.schema_canonical_width not in self.widths:
            raise ValueError(
                "M4SweepConfig.schema_canonical_width must be in widths "
                f"(got {self.schema_canonical_width} not in {self.widths})"
            )


@dataclass(frozen=True)
class Run:
    """Top-level M4 run record. Strict superset of M3's run JSON (R-7)."""

    mode: str
    axes: list[str]
    widths: list[int]
    paths: list[str]
    iterations_per_cell: int
    seed: int
    cohorts: list[RunCohort]
    p2_revision: str | None = None
    frozen_channel: dict[str, Any] | None = None
    pacing_mode: PacingMode | None = None
    shared_baseline_cohort_ids: dict[str, str] | None = None
    frozen_channel_baselines: dict[str, FrozenChannelBaseline] | None = None
    supersedes: list[SupersessionEntry] = field(default_factory=list)
    candidate_sizing_policy: dict[str, Any] | None = None
    loopback_caveat_axes: list[str] | None = None
    schema_candidate_results: list[SchemaCandidateResult] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
