"""In-process data model for the M3 sweep (``data-model.md``).

These are **not** wire types — for wire types see ``proto/vllm_grpc/v1/*.proto``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vllm_grpc_bench.channel_config import Axis, ChannelConfig

Path_ = Literal["embed", "chat_stream"]
CorpusSubset = Literal["m1_chat", "m1_embed", "m3_long_stream"]
Verdict = Literal["recommend", "no_winner", "not_measurable"]
ErrorKind = Literal["rpc_aborted", "max_msg_exceeded", "timeout", "other"]
WinningMetric = Literal["bytes", "time"]
AppliesPath = Literal["embed", "chat_stream", "both"]

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
