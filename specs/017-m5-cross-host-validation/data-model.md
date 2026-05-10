# M5 Data Model

This document enumerates the new and modified data structures the M5 harness needs. All types live under `tools/benchmark/src/vllm_grpc_bench/m3_types.py` (extended in place — keeps the import surface stable for M3, M4, and M5 callers). Where M4 already has a type, M5 extends rather than replaces.

## Verdict literals

```python
# m3_types.py — extended
Verdict = Literal[
    "recommend",         # candidate's 95% CI strictly clears the comparison baseline's 95% CI
    "no_winner",         # CIs overlap and remained overlapping after the borderline-expand step
    "not_measurable",    # cohort failed to produce usable samples (e.g., RPC errors)
    "noise_bounded",     # M3-only literal; preserved for M3 report compatibility but never emitted from M4/M5
    "client_bound",      # M4: cohort's dominant per-RPC cost is client-side overhead (M4 R-5)
    "server_bound",      # NEW (M5): cohort's dominant per-RPC cost is remote-server overhead (R-4)
]
```

`noise_bounded` is preserved so M3's reanalyze path keeps compiling; the M5 sweep emits a runtime check that any attempt to construct a `Recommendation(verdict="noise_bounded")` from the M5 sweep raises `ValueError` (parallel to M4 FR-007 guard). `client_bound` is inherited from M4 unchanged; M5 still emits it when the cohort's classifier (M4 R-5) trips.

## New: `EndpointProvider` Protocol

```python
# m3_types.py
from contextlib import AbstractAsyncContextManager
from typing import Protocol, TypeAlias

import grpc

EndpointTuple: TypeAlias = tuple[
    str,                                          # target (host:port)
    grpc.ChannelCredentials | None,               # None → insecure_channel; non-None → secure_channel
    tuple[tuple[str, str], ...] | None,           # call metadata to attach per RPC; None for unauthenticated
]


class EndpointProvider(Protocol):
    """An async context manager factory yielding an EndpointTuple.

    Implementations:
      * `serve_in_process_adapter` — wraps `m3_sweep.serve_in_process(...)`; yields (addr, None, None).
        Used by M4 (default) so M4 reproductions remain bit-identical.
      * `modal_endpoint.provide_endpoint` — deploys the Modal app, captures tunnel URL + bearer token,
        yields (modal_tunnel_target, ssl_credentials, (("authorization", f"Bearer {token}"),)).
        Used by M5.
    """

    def __call__(
        self,
        engine: MockEngine,
        channel_config: ChannelConfig,
    ) -> AbstractAsyncContextManager[EndpointTuple]: ...
```

The `serve_in_process_adapter` is defined in `m3_sweep.py` (next to the existing `serve_in_process`) and yields `(addr, None, None)`. Existing M3 / M4 call sites that call `serve_in_process(engine, cfg)` directly remain valid — only `m4_sweep.py` is widened to accept an `endpoint_provider` argument with `serve_in_process_adapter` as the default.

## New: `RTTRecord`

```python
# m3_types.py
@dataclass(frozen=True)
class RTTRecord:
    """Per-cohort active-probe RTT measurement (FR-004 / R-3).

    Captured by `rtt_probe.measure_rtt(...)` immediately before the cohort's
    measurement window opens. `samples_ms` is the raw per-probe wall-clock list
    so the M5 JSON consumer can re-derive any percentile.
    """
    n: int                          # number of probe iterations (default 32 per R-3)
    median_ms: float                # median wall-clock latency in milliseconds
    p95_ms: float                   # 95th-percentile wall-clock latency in milliseconds
    samples_ms: tuple[float, ...]   # raw per-probe samples; persisted to JSON
```

`RTTRecord` is attached to every M5 cohort entry. For M3/M4 cohorts (no cross-host topology), `RTTRecord` is absent from the cohort entry — the M5 JSON's strict-superset rule (FR-014) requires the field to be present on M5 cohorts but does not retroactively add it to M3/M4 entries.

## New: `Citation` (FR-017)

```python
# m3_types.py
@dataclass(frozen=True)
class Citation:
    """One ground-truth citation entry attached to a verdict-changed
    time-metric supersession (per FR-017 / M2 ground-truth workflow).

    Populated by `m5_supersede.build_supersedes_m4_table` when an M5
    recommendation supersedes an M4 recommendation on the time metric.
    Source-of-truth lookups use `cross-repo.json` for cross-repo paths
    and the targeted single-repo graphs (`vllm` / `grpcio`) for
    repo-specific evidence per CLAUDE.md navigation rules.
    """
    repo: Literal["vllm-project/vllm", "grpc/grpc"]
    file_path: str          # repo-relative path
    identifier: str | None  # function/class name, or None for whole-file citation
    justification: str      # one-line explanation of why this source backs the verdict change
```

## New: `ExpectedClass` (spec Edge Cases)

```python
# m3_types.py
ExpectedClass = Literal[
    "verdict_confirmed",        # M4 and M5 verdicts match on both metrics; no supersession row strictly required (table still includes for traceability of loopback-caveat resolution)
    "loopback_resolution",      # M4 had loopback_caveat=True AND verdict changed (the headline M5 case)
    "transport_resolution",     # M4 had no loopback_caveat AND axis is keepalive/http2_framing AND verdict changed (a real-RTT effect M4 missed for reasons other than the loopback caveat)
    "unexpected_supersession",  # verdict changed AND axis is max_message_size/compression — transport-RTT shouldn't dominate, so this signals either a real transport-layer effect M4 didn't capture, or a measurement-noise artifact that the reader should investigate (spec Edge Cases)
]
```

## New: `SupersedesM4Entry`

```python
# m3_types.py
@dataclass(frozen=True)
class SupersedesM4Entry:
    """One row in the M5 'Supersedes M4' table (FR-015).

    Cross-references an M4 cell that M5 supersedes. Emitted for:
      (a) every M4 cell flagged with the loopback caveat (per M4 FR-010),
      (b) any other M4 cell whose M5 verdict differs from M4's verdict
          on either the bytes metric or the time metric.
    """
    m4_axis: str                    # e.g., "keepalive"
    m4_hidden_size: int             # e.g., 4096
    m4_path: Literal["chat_stream", "embed"]
    m4_verdict_time: Verdict
    m4_verdict_bytes: Verdict
    m4_loopback_caveat: bool
    m5_verdict_time: Verdict
    m5_verdict_bytes: Verdict
    m5_supporting_ci_lower: float   # CI lower bound on the verdict-driver metric
    m5_supporting_ci_upper: float   # CI upper bound on the verdict-driver metric
    rationale: str                  # one-line human-readable supersession rationale
    verdict_changed: bool           # True iff (m4_verdict_time != m5_verdict_time) or (m4_verdict_bytes != m5_verdict_bytes)
    expected_class: ExpectedClass   # NEW: classification per spec Edge Cases (verdict_confirmed / loopback_resolution / transport_resolution / unexpected_supersession)
    citations: tuple[Citation, ...] = ()  # NEW (FR-017): populated for verdict-changed time-metric supersessions; empty tuple otherwise
```

`verdict_changed` is computed at construction time, not stored separately on either side; the reader can group / sort the supersession table by this flag (SC-004 requires visual distinction between verdict-changed and verdict-confirmed rows).

`expected_class` is computed by the same `m5_supersede.build_supersedes_m4_table` pass using the four-value classifier: `verdict_confirmed` when verdicts match; `loopback_resolution` when M4 had `loopback_caveat == True` AND verdict changed; `transport_resolution` when axis ∈ {`keepalive`, `http2_framing`} AND M4 had no loopback caveat AND verdict changed; `unexpected_supersession` when axis ∈ {`max_message_size`, `compression`} AND verdict changed. Readers MUST treat `unexpected_supersession` rows with elevated scrutiny per spec Edge Cases.

`citations` is populated only for time-metric verdict-changed supersessions (M4 said one thing on the time metric, M5 says another). For bytes-only changes or loopback-resolution rows whose time verdict is unchanged, the tuple is empty.

## New: `M5CrossHostBaseline`

```python
# m3_types.py
@dataclass(frozen=True)
class M5CrossHostBaseline:
    """Per-path cross-host shared-baseline cohort metadata (FR-008).

    Parallels M4's shared M1_BASELINE cohort but measured against the
    Modal-hosted gRPC server. The cohort itself lives in `Run.cohorts[]`;
    this record carries the metadata that distinguishes M5 baseline cohorts
    from M4 baseline cohorts when both appear in the same JSON.
    """
    path: Literal["chat_stream", "embed"]
    cohort_id: str                          # points into Run.cohorts[]
    modal_app_name: str
    modal_region: str
    measured_rtt: RTTRecord                 # the RTT probe captured during this cohort
    n: int                                  # >= 100 per FR-008
```

## New: top-level run metadata

```python
# m3_types.py
@dataclass(frozen=True)
class M5RunMetadata:
    """Top-level M5 run metadata, attached to the M5 JSON report root."""
    m5_methodology_version: int             # 1 for this release
    m5_modal_app_name: str
    m5_modal_region: str
    m5_runtime_wallclock_seconds: float
    m5_rtt_summary_ms: RTTSummary           # min/median/p95/max across all non-discarded cohorts
    rtt_validity_threshold_ms: float        # the FR-004 refuse-verdict threshold (default 1.0)
    rtt_exercise_threshold_ms: float        # the FR-004 low_rtt_caveat threshold (default 20.0)
    warmup_n: int                           # warm-up cohort iteration count (default 32 per R-5)
    server_bound_overhead_threshold_ms: float  # the R-4 max(2 × rtt, 50ms) cap; recorded as the floor
    server_bound_cohort_count: int          # diagnostic; how many cohorts the classifier excluded


@dataclass(frozen=True)
class RTTSummary:
    """Run-level RTT distribution aggregated across all non-discarded cohorts."""
    min_ms: float
    median_ms: float
    p95_ms: float
    max_ms: float
```

## Cohort-level field additions

The existing `CohortResult` (defined in `m3_types.py`) gains the following optional fields, all defaulting to `None` so M3/M4 cohorts remain valid:

```python
# m3_types.py — CohortResult extended (additive only, FR-014)
@dataclass(frozen=True)
class CohortResult:
    # ...existing M3/M4 fields preserved unchanged...
    rtt_record: RTTRecord | None = None              # set on every M5 cohort; None on M3/M4 cohorts
    server_overhead_estimate_ms: float | None = None # R-4 computed value; None on M3/M4 cohorts
    server_bound: bool = False                       # R-4 classifier output
    low_rtt_caveat: bool = False                     # set when rtt_record.median_ms < rtt_exercise_threshold_ms
    discarded: bool = False                          # set on warm-up cohorts (R-5)
```

## Recommendation-level field additions

```python
# m3_types.py — Recommendation extended
@dataclass(frozen=True)
class Recommendation:
    # ...existing M3/M4 fields preserved unchanged...
    supersedes_m4_cell: SupersedesM4Entry | None = None   # populated for M5 recommendations; None for M3/M4
```

This shape lets the supersession table be rebuilt from the per-verdict entries (no separate top-level supersession array needed beyond the FR-015 summary table that the report generator emits for human readers).

## Cohort lifecycle (state transitions)

A cohort progresses through these states during an M5 run:

1. **Probed** — `rtt_probe.measure_rtt(...)` completes and produces an `RTTRecord`. If `RTTRecord.median_ms < rtt_validity_threshold_ms`, the cohort is marked `not_measurable` with reason `"rtt_below_validity_threshold"` and the run continues with the next cohort (no verdict emitted).
2. **Measured** — the cohort's iterations execute; raw timings collected. If the cohort is a warm-up cohort, `discarded=True` is set here.
3. **Classified** — the `server_bound` classifier (R-4) runs on the cohort's median wall-clock + the `RTTRecord`'s median RTT + the per-path `client_overhead_floor_ms` constant from `m4-time-axis-tuning.json`. If the classifier flags the cohort, `server_bound=True` is set and the recommendation builder will not consider this cohort for `recommend` tallies.
4. **Annotated** — `low_rtt_caveat` is set if `RTTRecord.median_ms < rtt_exercise_threshold_ms`.
5. **Compared** — paired with its baseline cohort (either the M5 cross-host shared-baseline for channel cells, or the M5 frozen-channel baseline for schema cells); CIs computed; verdict literal selected per the FR-009 / FR-012 95% CI strict-clearing rule.
6. **Superseded-from-M4** — for cells that map to an M4 cell (every channel cell and every schema candidate at canonical width), construct a `SupersedesM4Entry` by joining against `m4-time-axis-tuning.json`. Discarded warm-up cohorts skip this step (no M4 cell exists for warm-up).

The lifecycle is deterministic and side-effect-free per cohort; the M5 sweep can be re-run from raw timings (under `bench-results/m5-full/`) without re-contacting Modal, supporting reanalysis if the classifier or the threshold values are tuned in a future revision.
