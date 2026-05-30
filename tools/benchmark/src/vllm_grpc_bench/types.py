"""Harness-wide types (v0.0.1 generic home).

Single milestone-agnostic home for the types/enums/aliases the live harness
shares. ``CohortKind`` is the 4-member forward cohort universe (clarify Q1 +
session-3 decision); the dropped ``tuned_grpc_channels`` / ``tuned_grpc``
members live only in the M5.2 tag's history.

The definitions here were hoisted in-place from the legacy ``m3_types`` /
``m6_types`` / ``m6_1_types`` / ``m6_1_2_types`` / ``m6_sweep`` modules at
Phase 4 (T020); this module no longer imports from any milestone-prefixed
source. The T028a symbol-rename pass de-prefixed the network-probe dataclasses
to ``TopologyPath`` / ``TopologyPathHop`` / ``TopologyPathError`` (the
``Topology`` prefix resolves the clash with the ``NetworkPath`` transport
literal).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import grpc

from vllm_grpc_bench.channel_config import ChannelConfig
from vllm_grpc_bench.engine_cost import EngineCostSpan

# --- Path / concurrency / corpus literals -----------------------------------

Path = Literal["embed", "chat_stream"]
"""The sweep path universe (formerly ``CellPath`` / ``CellPath``)."""

Path_ = Path
"""Structural alias kept for the M3-era REST records (formerly ``m3_types.Path_``)."""

Concurrency = Literal[1, 4, 8]
CorpusSubset = Literal["m1_chat", "m1_embed", "m3_long_stream"]
ErrorKind = Literal["rpc_aborted", "max_msg_exceeded", "timeout", "other"]
BaselineRole = Literal["m1_shared", "frozen_channel"]
BenchProtocol = Literal["rest", "grpc"]
GRPCSubCohortKind = Literal[
    "tuned_grpc_multiplexed",
    "tuned_grpc_channels",
    "tuned_grpc",
    "default_grpc",
]

CANONICAL_WIDTHS: frozenset[int] = frozenset({2048, 4096, 8192})

# --- Cohort universe (4-member forward set) ---------------------------------

CohortKind = Literal[
    "rest_https_edge",
    "rest_plain_tcp",
    "default_grpc",
    "tuned_grpc_multiplexed",
]
"""The closed 4-element cohort universe (FR R3 / clarify Q1)."""

COHORTS: tuple[CohortKind, ...] = (
    "rest_https_edge",
    "rest_plain_tcp",
    "default_grpc",
    "tuned_grpc_multiplexed",
)

CloudProvider = Literal[
    "AWS",
    "Microsoft Azure",
    "GCP",
    "unknown",
]
"""Closed enum for the cohort-level ``network_paths.<cohort>.cloud_provider``."""

CohortOmissions = dict[CohortKind, str]
"""Map of design-intentional cohort omissions; cohort name → one-line reason."""


def cohorts_at_concurrency(c: int) -> tuple[CohortKind, ...]:
    """Return the cohort tuple to iterate for a cell with the given concurrency.

    * At ``c == 1``: ``("default_grpc", "rest_https_edge", "rest_plain_tcp")``
      — ``default_grpc`` and ``tuned_grpc_multiplexed`` collapse to a single
      gRPC cohort whose ``cohort_kind`` is ``"default_grpc"`` (FR-011).
    * At ``c >= 2``: all 4 cohorts, gRPC cohorts first (keepalive belt-and-
      suspenders against an idle Modal plain-TCP tunnel).
    """
    if c == 1:
        return ("default_grpc", "rest_https_edge", "rest_plain_tcp")
    return ("default_grpc", "tuned_grpc_multiplexed", "rest_https_edge", "rest_plain_tcp")


# --- Network path entities (FR-003 wire shape) -------------------------------


@dataclass(frozen=True)
class TopologyPathHop:
    """One hop in a per-cohort ``tcptraceroute`` path.

    ``ip`` and ``rtt_ms_or_null`` are None when the hop was an asterisk
    (filtered). ``cloud_provider`` is best-effort.
    """

    hop_number: int
    ip: str | None
    rtt_ms_or_null: float | None
    cloud_provider: str | None


@dataclass(frozen=True)
class TopologyPath:
    """Per-cohort successful topology-probe result (FR-003 wire shape)."""

    endpoint_ip: str
    hops: list[TopologyPathHop]
    cloud_provider: CloudProvider
    region: str | None
    probe_method: Literal["tcptraceroute"]
    probed_at_utc: str


@dataclass(frozen=True)
class TopologyPathError:
    """Per-cohort failed topology-probe result (FR-005 wire shape).

    Discriminator from ``TopologyPath``: presence of the ``error`` field.
    """

    error: Literal[
        "tcptraceroute_unavailable",
        "probe_timeout",
        "subprocess_error",
        "parse_error",
    ]
    probe_method: Literal["tcptraceroute"]
    probed_at_utc: str
    detail: str | None = None


# --- Per-cell identity (formerly M6Cell) ------------------------------------


@dataclass(frozen=True)
class Cell:
    """One (path, hidden_size, concurrency) cell of the sweep matrix.

    ``concurrency`` is the actual in-flight parallelism: peak concurrent RPCs
    per cohort within a c-batch.
    """

    path: Path
    hidden_size: Literal[4096]
    concurrency: Concurrency


CELLS: tuple[tuple[Path, Literal[4096], Concurrency], ...] = (
    ("embed", 4096, 1),
    ("embed", 4096, 4),
    ("embed", 4096, 8),
    ("chat_stream", 4096, 1),
    ("chat_stream", 4096, 4),
    ("chat_stream", 4096, 8),
)


# --- RPC measurement result (formerly m6_sweep.RPCResult) --------------------


@dataclass(frozen=True)
class RPCResult:
    """One RPC's measurement, as returned by an ``RPCDriver``.

    ``wall_clock_ms`` is the total per-RPC wall-clock (always set on success).
    ``ttft_ms`` is set ONLY for chat_stream cells (None for embed).
    ``engine_cost`` is the server-instrumented per-RPC cost; None on
    instrumentation gap. ``m6_1_1_timing_payload`` is the four-checkpoint
    timing data parsed from the wire format, stored as a plain dict so this
    module stays free of a timing-types import cycle; callers re-hydrate to
    ``TimingCheckpoint`` via ``TimingCheckpoint(**payload)``.
    """

    success: bool
    wall_clock_ms: float | None
    ttft_ms: float | None
    engine_cost: EngineCostSpan | None
    failure_reason: str | None
    m6_1_1_timing_payload: dict[str, int | str | None] | None = None


# --- Active-probe RTT record -------------------------------------------------


@dataclass(frozen=True)
class RTTRecord:
    """Per-cohort active-probe RTT measurement (FR-004 / R-3).

    Captured by ``rtt_probe.measure_rtt(...)`` immediately before the cohort's
    measurement window opens. ``samples_ms`` is the raw per-probe wall-clock
    list so the JSON consumer can re-derive any percentile.
    """

    n: int
    median_ms: float
    p95_ms: float
    samples_ms: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.n < 1:
            raise ValueError(f"RTTRecord.n must be >= 1 (got {self.n})")
        if any(s < 0 for s in self.samples_ms):
            raise ValueError("RTTRecord.samples_ms entries must be non-negative")


# --- Endpoint tuple ----------------------------------------------------------

# (host:port, channel_credentials, call_metadata). credentials=None → insecure
# channel; metadata=None → no per-RPC auth headers attached.
type EndpointTuple = tuple[
    str,
    grpc.ChannelCredentials | None,
    tuple[tuple[str, str], ...] | None,
]


# --- M3-era REST/benchmark cohort records -----------------------------------

NetworkPath = Literal["https_edge", "plain_tcp"]


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
    engine_cost_payload: dict[str, float] | None = None
    m6_1_1_timing_payload: dict[str, int | str | None] | None = None


@dataclass(frozen=True)
class ExpansionRecord:
    """Documents the FR-002 / R-4 borderline-expand decision for one cohort."""

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
class RESTCohortRecord:
    """Per-(path × hidden_size × concurrency) REST cohort measurement."""

    shim_overhead_ms_median: float
    shim_overhead_ms_p95: float
    connections_opened: int
    connections_keepalive_reused: int
    request_bytes_median: int
    request_bytes_p95: int
    response_bytes_median: int
    response_bytes_p95: int


@dataclass(frozen=True)
class RestHttpsEdgeCohortRecord:
    """Per-(path x hidden_size x concurrency) REST cohort measurement over
    Modal's HTTPS edge (TLS-terminated, anycast-routed). Built by
    ``rest_cohort.run_rest_cohort(network_path="https_edge", ...)``.
    """

    shim_overhead_ms_median: float
    shim_overhead_ms_p95: float
    connections_opened: int
    connections_keepalive_reused: int
    request_bytes_median: int
    request_bytes_p95: int
    response_bytes_median: int
    response_bytes_p95: int

    network_path: Literal["https_edge"] = "https_edge"
    https_edge_endpoint: str = ""
    tls_handshake_ms_first_request: float | None = None
    measured_rtt_ms_median: float = 0.0
    measured_rtt_ms_p95: float = 0.0
    client_external_geolocation_country: str | None = None
    client_external_geolocation_region: str | None = None


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
    is_baseline: bool = False
    baseline_role: BaselineRole | None = None
    expansion_record: ExpansionRecord | None = None
    client_bound: bool = False
    time_to_first_token_seconds: tuple[float, float, float] | None = None
    time_cv: float | None = None
    ttft_cv: float | None = None
    noisy_baseline: bool = False
    rtt_record: RTTRecord | None = None
    server_overhead_estimate_ms: float | None = None
    server_bound: bool = False
    low_rtt_caveat: bool = False
    discarded: bool = False
    protocol: BenchProtocol | None = None
    grpc_channel_model: GRPCSubCohortKind | None = None
    connection_count: int | None = None
    shim_overhead_ms: float | None = None
    comparison_cell_key: str | None = None
    rest_cohort_record: RESTCohortRecord | None = None


__all__ = [
    "CELLS",
    "COHORTS",
    "Cell",
    "CloudProvider",
    "CohortKind",
    "CohortOmissions",
    "EndpointTuple",
    "TopologyPath",
    "TopologyPathError",
    "TopologyPathHop",
    "NetworkPath",
    "Path",
    "Path_",
    "RESTCohortRecord",
    "RPCResult",
    "RTTRecord",
    "RestHttpsEdgeCohortRecord",
    "RunCohort",
    "cohorts_at_concurrency",
]
