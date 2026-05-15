# Phase 1 Data Model: M6 — Real-Engine Mini-Validation

**Branch**: `020-m6-real-engine-mini-validation` | **Date**: 2026-05-14
**Plan**: [plan.md](./plan.md)

This document fixes the concrete in-memory and on-disk shapes for the entities defined in [`spec.md` § Key Entities](./spec.md). Field types use Python's typing notation; the harness implementation will materialise these as `@dataclass(frozen=True)` (or Pydantic models where the JSON serialisation matters) following the existing M5.2 convention.

---

## Cell-level entities

### `M6Cell`

Identifies one of the 6 cells in M6's narrow-slice matrix.

```python
@dataclass(frozen=True)
class M6Cell:
    path: Literal["embed", "chat_stream"]   # FR-001
    hidden_size: Literal[4096]              # FR-001 — fixed by Qwen3-7B
    concurrency: Literal[1, 4, 8]           # FR-001
```

**Identity**: The 3-tuple `(path, hidden_size, concurrency)` uniquely identifies a cell. Cell ordering in the sweep follows iteration order: `embed × c=1, embed × c=4, embed × c=8, chat_stream × c=1, chat_stream × c=4, chat_stream × c=8`.

**Validation rules**:
- `hidden_size` MUST be 4096 — M6 is fixed at h=4096 per FR-001 (h≠4096 deferred to M8).
- `concurrency` MUST be one of {1, 4, 8} — the 3 concurrency points in M5.2's matrix that M6 inherits.

### `M6CohortKind`

Identifies which of the 3 cohorts a measurement comes from.

```python
M6CohortKind = Literal["rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"]
```

**Validation rules**:
- M6 MUST NOT exercise `rest_plain_tcp` or `tuned_grpc_channels` (FR-002 — see Out of Scope).
- Per R-6, the M5.2 lookup function maps `tuned_grpc_multiplexed` to M5.2's `tuned_grpc` at c=1 and to `tuned_grpc_multiplexed` at c≥2. M6's own published cohort name remains `tuned_grpc_multiplexed` for all 6 cells.

### `VerdictClassification`

Terminal classification of an M6 cell.

```python
VerdictClassification = Literal[
    "verdict_survives",          # FR-014
    "verdict_changed",           # FR-014
    "verdict_buried_by_engine",  # FR-014
    "no_winner_at_n100",         # FR-014
    "cell_incomplete",           # FR-023 — 5th terminal classification
]
```

**State transitions**: A cell is assigned **exactly one** terminal classification (SC-002). Transitions are not permitted (FR-014: "operator post-hoc re-classification is not permitted"). Computed deterministically by the classifier per Research R-7.

---

## Per-RPC measurement entities

### `M6RPCMeasurement`

A single measurement RPC's recorded data (excluded for warmup RPCs per FR-021).

```python
@dataclass(frozen=True)
class M6RPCMeasurement:
    rpc_index: int                          # FR-025 — global RPC index across the sweep (warmup excluded)
    cell: M6Cell
    cohort: M6CohortKind
    seed: int                               # FR-025 — M6_BASE_SEED + rpc_index
    success: bool                           # FR-023 — false if all 3 retry attempts failed
    failure_reason: Optional[str]           # populated when success=False
    wall_clock_ms: Optional[float]          # FR-007 — total per-RPC wall-clock (None on failure)
    ttft_ms: Optional[float]                # FR-007 — chat_stream only; None for embed and on failure
    engine_cost: Optional["EngineCostSpan"] # FR-008 — None on failure (no server-side timing emitted)
    retry_count: int                        # 0..3; how many retry attempts were used
```

**Validation rules**:
- `success=True` ⇒ `wall_clock_ms is not None` AND `engine_cost is not None`.
- `success=True` AND `cell.path == "chat_stream"` ⇒ `ttft_ms is not None`.
- `success=True` AND `cell.path == "embed"` ⇒ `ttft_ms is None`.
- `retry_count` ≤ 3 (FR-023).

### `EngineCostSpan`

Server-instrumented per-RPC engine cost (FR-008). The shape is path-discriminated.

```python
@dataclass(frozen=True)
class EngineCostSpan:
    # Exactly one of the following sets is populated based on cell.path:
    engine_forward_ms: Optional[float]   # embed only — FR-008
    engine_ttft_ms: Optional[float]      # chat_stream only — FR-008
    engine_tpot_ms: Optional[float]      # chat_stream only — FR-008
```

**Validation rules**:
- `engine_forward_ms is not None` XOR (`engine_ttft_ms is not None` AND `engine_tpot_ms is not None`).
- Source: gRPC trailing metadata (R-2) for gRPC cohorts; JSON `engine_cost` payload field (R-4) for the REST cohort. Both routes deserialise into the same `EngineCostSpan` type.

---

## Aggregate entities

### `M6PerCohortAggregate`

Per-cohort aggregate statistics for one cell.

```python
@dataclass(frozen=True)
class M6PerCohortAggregate:
    cohort: M6CohortKind
    n_attempted: int                          # always 100 — FR-004
    n_successes: int                          # FR-023 — actual sample size
    failure_count: int                        # FR-023 — n_attempted - n_successes
    classifier_metric_mean_ms: float          # mean of (wall_clock_ms for embed | ttft_ms for chat_stream) — FR-014 comparison metric per path
    classifier_metric_ci_half_width_ms: float # 95% CI half-width — FR-009
    total_wall_clock_mean_ms: float           # always published per FR-007 even when not the classifier metric
    total_wall_clock_ci_half_width_ms: float
    engine_cost_mean: "EngineCostAggregate"   # cohort-level mean engine_cost
```

**Validation rules**:
- `n_attempted == 100` (FR-004).
- `n_successes ≤ n_attempted`; `failure_count == n_attempted - n_successes`.
- If `n_successes < 80`, the parent cell's classification will be `cell_incomplete` (FR-023) and the classifier_metric values are still reported but flagged in the JSON.

### `EngineCostAggregate`

Cohort-level mean engine cost (path-discriminated parallel to `EngineCostSpan`).

```python
@dataclass(frozen=True)
class EngineCostAggregate:
    engine_forward_mean_ms: Optional[float]
    engine_forward_ci_half_width_ms: Optional[float]
    engine_ttft_mean_ms: Optional[float]
    engine_ttft_ci_half_width_ms: Optional[float]
    engine_tpot_mean_ms: Optional[float]
    engine_tpot_ci_half_width_ms: Optional[float]
```

### `M6CellRecord`

The full per-cell record published in the JSON companion.

```python
@dataclass(frozen=True)
class M6CellRecord:
    cell: M6Cell
    per_cohort: Dict[M6CohortKind, M6PerCohortAggregate]   # always 3 entries per FR-002
    classification: VerdictClassification                  # FR-014 / FR-023 — exactly one
    classification_reason: str                             # human-readable, e.g. "M6 cohort CIs non-overlapping; sign matches M5.2 winner"

    # FR-014 sub-clauses:
    classifier_metric: Literal["wall_clock_ms", "ttft_ms"]  # comparison metric per path
    cohort_pair: Tuple[M6CohortKind, M6CohortKind]          # the (rest, grpc) pair from the M5.2 lookup
    m5_2_winner_delta_ms: Optional[float]                   # |delta_median_ms| from M5.2; None if M5.2 verdict was no_winner
    m5_2_winner_direction: Optional[Literal["rest_wins", "grpc_wins"]]
    engine_cost_mean_ms: float                              # per-cell cohort-averaged engine_cost (the metric used in the 5× rule)
    engine_cost_drift_warning: bool                         # FR-014 sub-clause — true if any cohort pair disagrees by >10%
    per_cohort_engine_cost_mean_ms: Dict[M6CohortKind, float]  # surfaced for operator review when drift_warning=True
```

**Validation rules**:
- `len(per_cohort) == 3` (FR-002 — exactly the 3 M6 cohorts).
- `classification == "cell_incomplete"` ⇔ `min(p.n_successes for p in per_cohort.values()) < 80` (FR-023).
- `classifier_metric == "wall_clock_ms"` ⇔ `cell.path == "embed"` (FR-014 comparison metric per path).
- `classifier_metric == "ttft_ms"` ⇔ `cell.path == "chat_stream"`.
- If `classification ∈ {verdict_buried_by_engine, no_winner_at_n100}`, then M6 cohort_pair CIs MUST overlap.
- If `classification == "verdict_buried_by_engine"`, then `engine_cost_mean_ms ≥ 5 × m5_2_winner_delta_ms` MUST hold (FR-014 5× rule).
- If `classification ∈ {verdict_survives, verdict_changed}`, then `m5_2_winner_delta_ms is not None` (a no-winner M5.2 baseline cannot produce a survives/changed verdict).
- If `engine_cost_drift_warning == True`, the `per_cohort_engine_cost_mean_ms` mapping MUST be populated for operator review (FR-014 sub-clause).

---

## Sweep-level entities

### `M6RunMeta`

Run metadata embedded in the JSON companion (FR-018).

```python
@dataclass(frozen=True)
class M6RunMeta:
    git_sha: str                                    # FR-018
    hostname: str                                   # FR-018
    modal_function_id: str                          # FR-018
    gpu_type: Literal["A10G"]                       # FR-018 — A10G fixed by FR-003
    modal_region: str                               # FR-018 — "eu-west-1" default
    model_identifier: str                           # FR-018 — "Qwen/Qwen3-7B" expected
    engine_version: str                             # FR-018 — vLLM version string
    cold_start_s: float                             # FR-018 / FR-019 — single scalar per sweep (FR-024)
    m5_2_winner_deltas: Dict[str, float]            # FR-018 / FR-014 — per-cell snapshot
                                                    # key format: "{path}_c{c}_h{hidden_size}",
                                                    # value: |delta_median_ms| at sweep launch
    m6_base_seed: int                               # FR-018 / FR-025 — default 42
```

**Validation rules**:
- `len(m5_2_winner_deltas) == 6` (one entry per M6 cell).
- `gpu_type == "A10G"` (FR-003).
- `cold_start_s ≥ 0`.

### `M6SmokeResult`

Result of the smoke gate (FR-011).

```python
@dataclass(frozen=True)
class M6SmokeOutcome:
    cell: M6Cell                          # one of the 2 smoke cells (embed × c=1, chat_stream × c=1)
    cohort: M6CohortKind                  # one of the 3 cohorts
    status: Literal["ok", "failed"]
    reason: str                           # short string, max ~60 chars; human-readable

@dataclass(frozen=True)
class M6SmokeResult:
    outcomes: List[M6SmokeOutcome]        # always 6 entries (2 cells × 3 cohorts)
    overall_status: Literal["ok", "failed"]  # ok ⇔ all outcomes ok
    wall_clock_s: float                   # SC-004 — should be ≤ 300
```

**Validation rules**:
- `len(outcomes) == 6` (2 cells × 3 cohorts × n=10 collapsed to per-(cell × cohort) outcomes).
- `overall_status == "ok"` ⇔ all `outcomes[i].status == "ok"`.
- The 2 smoke cells MUST be `(embed, h=4096, c=1)` and `(chat_stream, h=4096, c=1)` (FR-011).

### `M6Run`

Top-level published JSON shape.

```python
@dataclass(frozen=True)
class M6Run:
    run_id: str                                                    # ISO-8601 timestamp + git_sha suffix
    run_started_at: str                                            # ISO-8601
    run_completed_at: str                                          # ISO-8601
    meta: M6RunMeta                                                # FR-018
    smoke_result: Optional[M6SmokeResult]                          # populated if smoke ran in same invocation
    cells: List[M6CellRecord]                                      # always 6 entries per FR-001
    rtt_distribution: Dict[M6CohortKind, "RTTRecord"]              # FR-010 — per-cohort RTT probe result
    supersedes_m5_2: List["SupersedesM5_2Row"]                     # FR-014 — verdict table rows

    # M5.2-strict-superset compatibility (FR-016) — these fields preserve M5.2's
    # JSON shape so existing M5.2-aware consumers (m5_2_supersede.py, etc.)
    # continue to work unmodified against the M6 file:
    cohorts: List[Dict]                                            # M5.2-shape per-cohort summaries
    protocol_comparison_verdicts: List[Dict]                       # M5.2-shape verdict rows (M6's classifier output)
    schema_candidate_recommendations: List[Dict]                   # empty in M6 (deferred axis)
    channel_axis_recommendations: List[Dict]                       # empty in M6 (deferred axis)
```

**Validation rules**:
- `len(cells) == 6` (FR-001).
- `len(rtt_distribution) == 3` (FR-010 — per-cohort RTT probe).
- `len(supersedes_m5_2) == 6` (one verdict row per cell).
- The strict-superset fields (`cohorts`, `protocol_comparison_verdicts`, etc.) MUST be present and structurally valid against M5.2's JSON schema (FR-016) so M5.2-aware downstream consumers don't break.

### `SupersedesM5_2Row`

One row of the "Supersedes M5.2 under real engine" verdict table (FR-014).

```python
@dataclass(frozen=True)
class SupersedesM5_2Row:
    cell: M6Cell
    classification: VerdictClassification
    m6_classifier_metric_mean_per_cohort: Dict[M6CohortKind, float]  # per-cohort mean of the classifier metric
    m6_classifier_metric_ci_per_cohort: Dict[M6CohortKind, Tuple[float, float]]  # per-cohort (lower, upper) CI
    m5_2_winner_cohort: Optional[M6CohortKind]                       # which cohort M5.2 picked, or None if M5.2 verdict was no_winner
    m5_2_winner_delta_ms: Optional[float]                            # |delta_median_ms| from M5.2
    engine_cost_mean_ms: float                                       # per-cell cohort-averaged
    engine_cost_drift_warning: bool                                  # FR-014 sub-clause
    notes: str                                                       # human-readable, e.g. "M5.2 picked tuned_grpc; M6 CIs non-overlapping in same direction"
```

---

## Per-cohort progress / events sidecar

### `M6PerRequestEvent`

Per-RPC event written to the JSONL events sidecar (extends M5.2's `PerRequestEventRecord` per the events-sidecar contract — see [`contracts/output.md`](./contracts/output.md)).

```python
@dataclass(frozen=True)
class M6PerRequestEvent:
    # Inherits all M5.2 PerRequestEventRecord fields (cohort, path, hidden_size,
    # concurrency, network_path, request_uuid, rpc_elapsed_ms, etc.):
    cohort: M6CohortKind
    cell_path: Literal["embed", "chat_stream"]
    cell_hidden_size: Literal[4096]
    cell_concurrency: Literal[1, 4, 8]
    network_path: Literal["https_edge", "plain_tcp"]
    request_uuid: str
    rpc_elapsed_ms: float
    rpc_phase: Literal["warmup", "measurement"]   # NEW for M6 to distinguish phases per FR-021
    rpc_index: Optional[int]                       # NEW — set for measurement RPCs only (FR-025)
    seed: Optional[int]                            # NEW — set for measurement RPCs (FR-025)

    # NEW M6 engine_cost fields:
    engine_forward_ms: Optional[float]
    engine_ttft_ms: Optional[float]
    engine_tpot_ms: Optional[float]
    success: bool
    failure_reason: Optional[str]
    retry_count: int
```

**Validation rules**:
- `rpc_phase == "warmup"` ⇒ `rpc_index is None` AND `seed is None` (warmup excluded from indexed seed sequence per FR-025).
- `rpc_phase == "measurement"` ⇒ `rpc_index is not None` AND `seed is not None`.
- `cell_path == "embed"` ⇒ engine_ttft_ms is None AND engine_tpot_ms is None.
- `cell_path == "chat_stream"` ⇒ engine_forward_ms is None.

---

## Lifecycle: how entities flow through the sweep

```text
1. Sweep launch:
   - M5.2 baseline JSON loaded + validated → M6RunMeta.m5_2_winner_deltas populated.
   - Modal app deployed with M6_USE_REAL_ENGINE=true.
   - M6RunMeta.cold_start_s recorded after engine readiness probe.

2. Smoke gate (optional, operator-driven):
   - For each (smoke cell × cohort): n=10 RPCs (with retries per FR-023) → M6SmokeOutcome.
   - Aggregated into M6SmokeResult.
   - Exit non-zero if overall_status=="failed".

3. Full sweep:
   - For each cell in cell-iteration order:
     a. Per-cohort warmup phase (round-robin per c-batch; warmup successes accumulate).
     b. Measurement phase (round-robin per c-batch; per-RPC seeds via FR-025).
     c. Per-RPC measurements stream into events sidecar AND accumulate into per-cohort aggregates.
     d. Cell-level aggregation produces M6CellRecord with per-cohort aggregates + classification.
     e. Progress line emitted on stderr per (cell × cohort) pair (FR-026).

4. Reporting:
   - 6 M6CellRecord values + M6RunMeta + M6SmokeResult + RTT probe → M6Run.
   - M6Run serialised to JSON companion (FR-013, FR-016 strict superset).
   - SupersedesM5_2Row table rendered into markdown report (FR-014).
   - Final completion banner emitted on stderr (FR-026).
```
