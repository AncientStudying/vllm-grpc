# M5.1 Data Model

This file documents the additive dataclasses and Literal-type extensions M5.1 adds to `tools/benchmark/src/vllm_grpc_bench/m3_types.py`. Every addition is **additive** — no field is renamed, removed, or semantically redefined relative to M5's `m3_types.py`. M5-aware consumers (existing harness modules, report renderers, JSON readers) continue to work unmodified when M5.1 fields are present but unread.

## Verdict literals

```python
# m3_types.py — extended
ComparisonVerdict = Literal[
    # c >= 2 verdict literals (FR-006, FR-007, FR-013):
    "tuned_grpc_multiplexed_recommend",
    "tuned_grpc_channels_recommend",
    # c == 1 verdict literal (multiplexed/channels degenerate):
    "tuned_grpc_recommend",
    # Both-c REST recommendation:
    "rest_recommend",
    # Standard outcomes:
    "no_winner",
    # FR-005 / Edge Case 3: fires when either protocol's cohort is server_bound
    # at the same cell (cannot emit a meaningful head-to-head verdict):
    "comparison_unavailable",
]

GRPCSubCohortKind = Literal[
    "tuned_grpc_multiplexed",   # 1 channel, c HTTP/2 streams, M5 frozen-tuned-channel config
    "tuned_grpc_channels",      # c independent channels, serial RPCs, M5 frozen-tuned-channel config
    "tuned_grpc",               # c=1 degenerate: collapses the above two
    "default_grpc",             # 1 channel, c HTTP/2 streams, M1-default channel config (FR-007)
]

Protocol = Literal["rest", "grpc"]
```

## New: `RESTCohortRecord`

```python
# m3_types.py
@dataclass(slots=True, frozen=True)
class RESTCohortRecord:
    """Per-(path × hidden_size × concurrency) REST cohort measurement.

    Built by ``rest_cohort.run_rest_cohort()`` and folded into the M5.1
    JSON report. Carries the REST-specific provenance the spec's FR-010
    requires alongside the standard cohort fields (sample size, CI bounds,
    median wall-clock, etc., which live on the wrapping ``CohortResult``).
    """

    # FastAPI shim's intra-process overhead (server-side, handler-entry
    # to mock_engine.{generate,embed} call boundary). Recorded as the
    # cohort's median across all n requests. Surfaced in the report so
    # the reader can attribute REST-side time to plumbing vs transport.
    shim_overhead_ms_median: float
    shim_overhead_ms_p95: float

    # Connection-pool observability (FR-008, FR-010 (b)).
    # The harness configures Limits(max_keepalive_connections=c,
    # max_connections=c, keepalive_expiry=300s) and httpx reports the
    # actually-opened connection count via its transport's connection
    # pool stats. Recorded so a reader can verify the pool behaved as
    # configured.
    connections_opened: int
    connections_keepalive_reused: int

    # JSON serialization byte counts (FR-010 (c)).
    # Per-request and per-response medians and p95 over the cohort.
    request_bytes_median: int
    request_bytes_p95: int
    response_bytes_median: int
    response_bytes_p95: int
```

## New: `ShimOverheadRecord`

```python
# m3_types.py
@dataclass(slots=True, frozen=True)
class ShimOverheadRecord:
    """Run-level aggregate of FastAPI shim intra-process overhead.

    Folded into the M5.1 report's executive section so the reader can
    confirm at a glance that REST's time component is dominated by
    transport, not by shim plumbing. Aggregates across every REST cohort
    in the run.
    """

    shim_overhead_ms_median_across_run: float
    shim_overhead_ms_p95_across_run: float
    shim_overhead_ms_max_across_run: float
    # Set true if the harness ever observed shim overhead > 5% of the
    # cohort's median wall-clock. Triggers a "shim plumbing was a
    # material contributor" warning in the report.
    shim_overhead_material_in_any_cohort: bool
```

## New: `SupersedesM1Entry`

```python
# m3_types.py
@dataclass(slots=True, frozen=True)
class SupersedesM1Entry:
    """One row in the M5.1 'Supersedes M1 (time-axis)' table (FR-020).

    Maps a single M1 published time-axis cell to the M5.1 verdict and
    its supporting numbers. Aggregated per (path × concurrency) because
    M1 did not vary hidden_size (per research.md R-5).
    """

    # M1 cell identity
    m1_path: Literal["chat_completion", "embed_completion"]
    m1_concurrency: int
    m1_verdict_literal: str   # paraphrased M1 verdict (e.g., "REST faster")
    m1_source_report: str     # path-to-report citing this M1 cell

    # M5.1 verdict pattern across widths at this (path, concurrency)
    m5_1_verdict_per_width: dict[int, ComparisonVerdict]   # {2048: ..., 4096: ..., 8192: ...}
    m5_1_supporting_delta_pct: dict[int, float]            # {2048: -23.2, ...}
    m5_1_supporting_ci_pct: dict[int, tuple[float, float]] # {2048: (-25.1, -21.3), ...}

    # Classification: 'verdict_confirmed' if every width matches M1's
    # verdict; 'verdict_changed' if any width contradicts; 'mixed' if
    # widths split between confirm/change.
    classification: Literal["verdict_confirmed", "verdict_changed", "mixed"]

    # Rationale: a single sentence, generated by the supersede builder.
    # The MockEngine continuity caveat is appended automatically when
    # the verdict changes from M1 (Edge Case 2).
    rationale: str

    # comparison_basis: records the methodology divergence so a reader
    # can interpret the row correctly (M1 was real vLLM; M5.1 is
    # MockEngine; the rationale text already says this for changed rows
    # but the field is structured so JSON consumers can filter on it).
    comparison_basis: Literal[
        "m1_real_vllm_vs_m5_1_mock_engine",   # standard M5.1 supersession
    ]
```

## New: `M5_1Cell`

```python
# m3_types.py
@dataclass(slots=True, frozen=True)
class M5_1Cell:
    """One (path × hidden_size × concurrency) cell in the M5.1 matrix.

    Carries the cell's three (at c=1, two) cohort references plus the
    emitted comparison verdict(s). Folded into the M5.1 JSON under
    'm5_1_matrix[*]'.
    """

    path: Literal["chat_stream", "embed"]
    hidden_size: Literal[2048, 4096, 8192]
    concurrency: Literal[1, 4, 8]

    rest_cohort_key: str         # CohortResult.key for the REST cohort
    default_grpc_cohort_key: str # CohortResult.key for the default-gRPC cohort

    # At c >= 2: both keys are non-None (dual sub-cohort).
    # At c == 1: tuned_grpc_channels_cohort_key is None (degenerate).
    tuned_grpc_multiplexed_cohort_key: str
    tuned_grpc_channels_cohort_key: str | None

    # Emitted comparison verdict(s).
    # At c >= 2: list has 2 entries (one per gRPC sub-cohort × REST).
    # At c == 1: list has 1 entry.
    # Plus 1 entry per cell for default-gRPC vs REST (always emitted).
    verdicts: list[CellVerdict]

    # FR-005 / Edge Case 3: set when either protocol is server_bound.
    comparison_unavailable: bool
    comparison_unavailable_reason: str | None

    # RTT range across all cohorts at this cell (FR-004, SC-003).
    rtt_ms_median: float
    rtt_ms_p95: float
    low_rtt_caveat: bool

@dataclass(slots=True, frozen=True)
class CellVerdict:
    """One row of the M5.1 per-cell comparison verdict."""

    grpc_sub_cohort: GRPCSubCohortKind
    verdict: ComparisonVerdict
    delta_pct: float                       # signed, gRPC vs REST on TTFT/wall-clock
    ci_pct: tuple[float, float]            # 95% CI on delta_pct
    metric: Literal["ttft", "wallclock"]   # ttft for chat_stream; wallclock for embed
```

## Cohort-level field additions (additive to M5's `CohortResult`)

```python
# m3_types.py — CohortResult extended (additive only, FR-014)
@dataclass(slots=True, frozen=True)
class CohortResult:  # existing M5 fields preserved verbatim above this block
    # ... existing M5 fields (sample_size, ci_lo, ci_hi, median_ms, etc.) ...

    # M5.1 additive fields:
    protocol: Protocol | None = None
    # GRPCSubCohortKind only set when protocol == "grpc"; None for REST cohorts.
    grpc_channel_model: GRPCSubCohortKind | None = None
    # The actually-opened connection count for this cohort. For REST,
    # measured via httpx transport stats; for gRPC, equal to 1 when
    # multiplexed and equal to c when channels.
    connection_count: int | None = None
    # REST-specific: median shim overhead across the cohort's n requests.
    # Always None for gRPC cohorts.
    shim_overhead_ms: float | None = None
    # Reference back to the M5.1 matrix cell this cohort belongs to.
    # Lets a downstream aggregator group cohorts back to their cell.
    comparison_cell_key: str | None = None
```

## Run-level field additions

```python
# m3_types.py — top-level run metadata extended (additive)
@dataclass(slots=True, frozen=True)
class M5_1RunMetadata:
    """Top-level M5.1 metadata, folded into the JSON root.

    Only present when the harness ran in --m5_1 mode. Absent when the
    same JSON file was produced by an M5 (or earlier) run.
    """

    # Modal handles
    modal_app_handle: str
    modal_region: str
    modal_instance_class: Literal["cpu"]  # constrained per FR-003

    # FastAPI shim version (commit SHA of scripts/python/modal_bench_rest_grpc_server.py)
    rest_shim_version_sha: str
    rest_shim_uvicorn_workers: int   # always 1 per research.md R-8

    # Bearer-token sourcing (no token value leaks into report; only the
    # name of the env var the token came from).
    auth_token_env_var: str

    # Aggregate shim overhead across all REST cohorts.
    shim_overhead: ShimOverheadRecord

    # M1 supersession results
    supersedes_m1_time: list[SupersedesM1Entry]

    # The 18-cell matrix
    m5_1_matrix: list[M5_1Cell]
```

## Cohort lifecycle (state transitions)

A single M5.1 cohort moves through the following states. M5's lifecycle (see M5's `data-model.md`) is unchanged; M5.1 adds the REST-cohort-specific transitions on the left fork.

```text
              ┌────────────────────────────────────────────────────────────┐
              │                       cell scheduling                       │
              │   M5.1 sweep enumerates 18 (path × width × c) cells.        │
              │   For each cell, dispatches REST + dual-gRPC + default-gRPC │
              │   in SERIES (per research.md R-4).                          │
              └────────────────────────────────────────────────────────────┘
                                          │
            ┌─────────────────────────────┼─────────────────────────────┐
            ▼                             ▼                             ▼
   REST cohort runner            tuned-gRPC sub-cohorts         default-gRPC control
   (rest_cohort.py)              (m5_sweep helpers via          (m5_sweep helpers,
                                  m5_1_sweep wrapper)            default channel cfg)
            │                             │                             │
            ▼                             ▼                             ▼
   ┌─────────────────┐          ┌────────────────┐         ┌────────────────────┐
   │ RTT probe       │          │ RTT probe (per │         │ RTT probe (per     │
   │ (HTTP/1.1       │          │  M5 mechanism) │         │  M5 mechanism)     │
   │  /healthz)      │          │                │         │                    │
   └─────────────────┘          └────────────────┘         └────────────────────┘
            │                             │                             │
            ▼                             ▼                             ▼
   ┌─────────────────┐          ┌────────────────┐         ┌────────────────────┐
   │ Warmup (1 per   │          │ Warmup (M5     │         │ Warmup (M5         │
   │  path,          │          │  mechanism)    │         │  mechanism)        │
   │  discarded)     │          │                │         │                    │
   └─────────────────┘          └────────────────┘         └────────────────────┘
            │                             │                             │
            ▼                             ▼                             ▼
   ┌─────────────────┐          ┌────────────────┐         ┌────────────────────┐
   │ Measure n ≥ 100 │          │ Measure n ≥ 100│         │ Measure n ≥ 100    │
   │ via httpx       │          │ via grpc.aio   │         │ via grpc.aio       │
   │ AsyncClient     │          │ (M5 path)      │         │ (M5 path, M1       │
   │ with c keep-    │          │                │         │  default channel)  │
   │ alive conns     │          │                │         │                    │
   └─────────────────┘          └────────────────┘         └────────────────────┘
            │                             │                             │
            ▼                             ▼                             ▼
   ┌─────────────────┐          ┌────────────────┐         ┌────────────────────┐
   │ Borderline      │          │ Borderline     │         │ Borderline         │
   │ expand n ≥ 250  │          │ expand n ≥ 250 │         │ expand n ≥ 250     │
   │ (M5 cascade)    │          │ (M5 cascade)   │         │ (M5 cascade)       │
   └─────────────────┘          └────────────────┘         └────────────────────┘
            │                             │                             │
            ▼                             ▼                             ▼
   ┌─────────────────┐          ┌────────────────┐         ┌────────────────────┐
   │ server_bound    │          │ server_bound   │         │ server_bound       │
   │ classifier      │          │ classifier     │         │ classifier         │
   │ (M5 mechanism)  │          │ (M5 mechanism) │         │ (M5 mechanism)     │
   └─────────────────┘          └────────────────┘         └────────────────────┘
            │                             │                             │
            └─────────────────────────────┼─────────────────────────────┘
                                          ▼
                          ┌──────────────────────────────────┐
                          │ Comparison verdict emitter       │
                          │ (m5_1_sweep.emit_cell_verdicts)  │
                          │                                  │
                          │ If either side server_bound →    │
                          │   verdict = comparison_unavailable│
                          │ Else for each gRPC sub-cohort:   │
                          │   compute (gRPC - REST) delta &  │
                          │   95% CI; emit verdict per rule  │
                          │   FR-013.                        │
                          └──────────────────────────────────┘
                                          │
                                          ▼
                          ┌──────────────────────────────────┐
                          │ M5_1Cell record built;           │
                          │ folded into M5_1RunMetadata      │
                          │ .m5_1_matrix; written to JSON.   │
                          └──────────────────────────────────┘
```
