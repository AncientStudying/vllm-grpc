# Phase 1 Data Model: M6.1 — Real-Prompt-Embeds Engine Path

**Branch**: `022-m6-1-real-prompt-embeds` | **Date**: 2026-05-16
**Plan**: [plan.md](./plan.md)

This document fixes the concrete in-memory and on-disk shapes for the
entities defined in [`spec.md` § Key Entities](./spec.md). Field types use
Python's typing notation; the harness implementation materialises these as
`@dataclass(frozen=True)` (or Pydantic models where the JSON serialisation
matters) following the existing M6 convention.

M6.1 reuses M6's per-RPC and per-cohort entity shapes verbatim. The
M6.1-specific additions are at the cell-record level (a new
`chat_stream_control_drift_warning` flag), at the run-meta level (the
`m6_winner_deltas` snapshot, the pinned `seq_len`, the dual engine_version
fields, the M6.1 base seed) and at the top-level run shape (the
`engine_path_differential` section).

---

## Cell-level entities (mostly reused from M6)

### `M6_1Cell`

Identifies one of the 6 cells in M6.1's matrix. **Identical shape to
`M6Cell`**; the alias exists so M6.1 modules type their cells unambiguously.

```python
M6_1Cell = M6Cell  # re-export from vllm_grpc_bench.m6_types
# i.e.
# @dataclass(frozen=True)
# class M6Cell:
#     path: Literal["embed", "chat_stream"]   # FR-001
#     hidden_size: Literal[4096]              # FR-001 — fixed by Qwen3-8B
#     concurrency: Literal[1, 4, 8]           # FR-001
```

**Identity**: The 3-tuple `(path, hidden_size, concurrency)` uniquely
identifies a cell. Cell ordering in the sweep follows iteration order:
`embed × c=1, embed × c=4, embed × c=8, chat_stream × c=1, chat_stream × c=4,
chat_stream × c=8`.

**Validation rules**:
- `hidden_size` MUST be 4096 — M6.1 is fixed at h=4096 per FR-001 (matches M6).
- `concurrency` MUST be one of {1, 4, 8}.

### `M6_1CohortKind`

Identifies which of the 3 cohorts a measurement comes from. **Identical
shape to `M6CohortKind`** — cohort names match M6 verbatim so per-cell
verdict tables across M5.2 / M6 / M6.1 align row-for-row.

```python
M6_1CohortKind = Literal["rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"]
```

### `VerdictClassification`

Terminal classification of an M6.1 cell. **Identical shape to M6's**
`VerdictClassification`.

```python
VerdictClassification = Literal[
    "verdict_survives",
    "verdict_changed",
    "verdict_buried_by_engine",
    "no_winner_at_n100",
    "cell_incomplete",
]
```

**State transitions**: A cell is assigned **exactly one** terminal
classification (SC-003). Transitions are not permitted (FR-010: "operator
post-hoc re-classification is not permitted"). Computed deterministically by
the classifier per [Research R-8](./research.md#r-8-verdict-classifier-algorithm-m61).

---

## Per-RPC measurement entities (reused from M6)

### `M6_1RPCMeasurement`

A single measurement RPC's recorded data (excluded for warmup RPCs per
FR-015). **Identical shape to M6's `M6RPCMeasurement`.**

```python
@dataclass(frozen=True)
class M6_1RPCMeasurement:
    rpc_index: int                          # FR-019 — global RPC index (warmup excluded)
    cell: M6_1Cell
    cohort: M6_1CohortKind
    seed: int                               # FR-019 — M6_1_BASE_SEED + rpc_index
    success: bool                           # FR-017 — false if all 3 retry attempts failed
    failure_reason: Optional[str]           # populated when success=False
    wall_clock_ms: Optional[float]          # FR-011 — total per-RPC wall-clock (None on failure)
    ttft_ms: Optional[float]                # FR-011 — chat_stream only; None for embed and on failure
    engine_cost: Optional[EngineCostSpan]   # FR-018 — None on failure
    retry_count: int                        # 0..3
```

### `EngineCostSpan`

Server-instrumented per-RPC engine cost (FR-018). **Identical shape to
M6's `EngineCostSpan`** — gRPC trailing metadata + REST JSON wire format
reused unchanged.

```python
@dataclass(frozen=True)
class EngineCostSpan:
    engine_forward_ms: Optional[float]   # embed only
    engine_ttft_ms: Optional[float]      # chat_stream only
    engine_tpot_ms: Optional[float]      # chat_stream only
```

---

## Aggregate entities

### `M6_1PerCohortAggregate`

Per-cohort aggregate statistics for one cell. **Identical shape to M6's
`M6PerCohortAggregate`.**

```python
@dataclass(frozen=True)
class M6_1PerCohortAggregate:
    cohort: M6_1CohortKind
    n_attempted: int                          # always 100 — FR-001
    n_successes: int                          # FR-017 — actual sample size
    failure_count: int
    classifier_metric_mean_ms: float          # FR-011 per path
    classifier_metric_ci_half_width_ms: float
    total_wall_clock_mean_ms: float
    total_wall_clock_ci_half_width_ms: float
    engine_cost_mean: EngineCostAggregate
```

**Validation rules**:
- `n_attempted == 100` (FR-001).
- `n_successes ≤ n_attempted`.
- If `n_successes < 80`, the parent cell's classification will be
  `cell_incomplete` (FR-017).

### `M6_1CellRecord`

The full per-cell record published in the JSON companion. **Extends M6's
`M6CellRecord` with one new field** (`chat_stream_control_drift_warning`)
and **retargets the winner-delta references** at M6 instead of M5.2.

```python
@dataclass(frozen=True)
class M6_1CellRecord:
    cell: M6_1Cell
    per_cohort: Dict[M6_1CohortKind, M6_1PerCohortAggregate]  # always 3 entries
    classification: VerdictClassification                      # FR-010 / FR-017
    classification_reason: str                                 # human-readable

    classifier_metric: Literal["wall_clock_ms", "ttft_ms"]
    cohort_pair: Tuple[M6_1CohortKind, M6_1CohortKind]         # the (rest, grpc) pair from the M6 baseline lookup
    m6_winner_delta_ms: Optional[float]                        # |delta_median_ms| extracted from M6 baseline; None per FR-010 sub-clause
    m6_winner_direction: Optional[Literal["rest_wins", "grpc_wins"]]
    engine_cost_mean_ms: float                                 # FR-022 — simple unweighted average of 3 per-cohort means
    engine_cost_drift_warning: bool                            # FR-022 — true if any cohort pair disagrees by >10%
    per_cohort_engine_cost_mean_ms: Dict[M6_1CohortKind, float]  # populated when drift_warning=True

    # NEW in M6.1:
    chat_stream_control_drift_warning: bool                    # FR-029 — only set on chat_stream cells; False on embed cells
```

**Validation rules**:
- `len(per_cohort) == 3` (FR-002 — exactly the 3 cohorts).
- `classification == "cell_incomplete"` ⇔
  `min(p.n_successes for p in per_cohort.values()) < 80` (FR-017).
- `classifier_metric == "wall_clock_ms"` ⇔ `cell.path == "embed"` (FR-011).
- `classifier_metric == "ttft_ms"` ⇔ `cell.path == "chat_stream"`.
- If `classification == "verdict_buried_by_engine"`, then
  `engine_cost_mean_ms ≥ 5 × m6_winner_delta_ms` MUST hold (FR-010 5× rule).
- If `classification ∈ {verdict_survives, verdict_changed}`, then
  `m6_winner_delta_ms is not None` (FR-010 sub-clause — cells where M6 had
  no usable winner delta classify as `no_winner_at_n100` regardless of CI
  overlap; this includes M6 cells whose verdict was
  `verdict_buried_by_engine`, `no_winner_at_n100`, or `cell_incomplete`).
- `chat_stream_control_drift_warning == True` is only possible for
  `cell.path == "chat_stream"` (FR-029 — embed cells have no published M6
  same-cohort baseline to drift-check against in the same way; their drift
  surface is the embed-cell verdict differential itself).

---

## Engine path differential entities

### `EnginePathDifferentialRow`

One row of the "Engine path differential" section (US2 / FR-020). Each
cell produces one row.

```python
@dataclass(frozen=True)
class EnginePathDifferentialRow:
    cell: M6_1Cell

    # Per-cohort classifier-metric deltas (FR-020):
    per_cohort_classifier_metric_delta_ms: Dict[M6_1CohortKind, float]
    per_cohort_classifier_metric_delta_ci_half_width_ms: Dict[M6_1CohortKind, float]

    # Per-cell engine_cost delta (FR-020):
    engine_cost_mean_delta_ms: float
    engine_cost_mean_delta_ci_half_width_ms: float

    # n_successes contributing to the differential (SC-007):
    per_cohort_n_successes: Dict[M6_1CohortKind, int]
```

**Validation rules**:
- `len(per_cohort_classifier_metric_delta_ms) == 3` (FR-020 — per cohort).
- For each cohort, both the delta and the CI half-width MUST be present
  (SC-007 — even cell_incomplete cells populate the differential row with
  whatever sample size was achieved).
- Delta computation: `M6.1 mean − M6 mean` (FR-020). Combined 95% CI
  half-width uses the standard formula for the CI of a difference between
  two independent sample means (square root of sum of squared CI
  half-widths, treating each sample's CI as a normal approximation).

---

## Sweep-level entities

### `M6_1RunMeta`

Run metadata embedded in the JSON companion (FR-027). **Extends M6's
`M6RunMeta` with**:
1. `m6_winner_deltas` (replacing M6's `m5_2_winner_deltas`).
2. `seq_len` (the pinned prompt-embeds sequence length per FR-028).
3. `M6_1_BASE_SEED` (replacing M6's `m6_base_seed`).
4. `m6_baseline_engine_version` (M6's recorded engine_version — FR-030).
5. `engine_version` (M6.1's own pinned engine_version — FR-027 / FR-030).
6. `torch_version` (the pinned torch version validated at driver-start — FR-006).

```python
@dataclass(frozen=True)
class M6_1RunMeta:
    git_sha: str                                    # FR-027
    hostname: str
    modal_function_id: str
    gpu_type: Literal["A10G"]                       # FR-027
    modal_region: str                               # FR-027 — "eu-west-1" default
    model_identifier: str                           # FR-027 — "Qwen/Qwen3-8B" expected
    hidden_size: Literal[4096]                      # FR-027

    # NEW / RENAMED in M6.1:
    M6_1_BASE_SEED: int                             # FR-019 / FR-027 — default 42
    seq_len: int                                    # FR-027 / FR-028 — pinned at sweep start; recorded for reproducibility
    engine_version: str                             # FR-027 / FR-030 — M6.1's own pinned vllm version, read from pyproject.toml
    m6_baseline_engine_version: str                 # FR-030 — value from M6 baseline JSON (may be "unknown" for legacy baseline)
    torch_version: str                              # FR-006 — the pinned torch.__version__ validated at driver-start
    m6_winner_deltas: Dict[str, Optional[float]]    # FR-008 — per-cell M6 winner delta snapshot
                                                    # key format: "{path}_c{c}_h{hidden_size}",
                                                    # value: |delta_median_ms| at sweep launch, or None per FR-010 sub-clause

    # REUSED from M6:
    cold_start_s: float                             # FR-014 / FR-027 — single scalar per sweep
    max_model_len: int                              # FR-027 — engine config, expected 2048
    gpu_memory_utilization: float                   # FR-027 — engine config, expected 0.92
    run_started_at: str                             # FR-027 — ISO-8601
    run_completed_at: str                           # FR-027 — ISO-8601
```

**Validation rules**:
- `len(m6_winner_deltas) == 6` (one entry per M6.1 cell).
- `gpu_type == "A10G"`.
- `cold_start_s ≥ 0`.
- `seq_len ≥ 1` (FR-028 — pinned at sweep start by tokenising the M6 text-digest
  format under Qwen3-8B's tokenizer; concrete value recorded for reproducibility).
- `engine_version` is a non-empty string (read from `pyproject.toml`; expected
  format e.g. `"0.20.1"`).
- `m6_baseline_engine_version` is a non-empty string (may be `"unknown"` for
  the legacy M6 baseline — FR-030 is non-blocking on mismatch).
- `torch_version` matches the pinned version checked by `m6_1_torch_pin`
  (FR-006 — driver-start validation gate).

### `M6_1SmokeResult`

Result of the smoke gate (FR-012). **Identical shape to M6's
`M6SmokeResult`** with the smoke matrix unchanged (2 cells × 3 cohorts ×
n=10 = 60 RPCs collapsed to 6 per-(cell × cohort) outcomes).

```python
@dataclass(frozen=True)
class M6_1SmokeOutcome:
    cell: M6_1Cell
    cohort: M6_1CohortKind
    status: Literal["ok", "failed"]
    reason: str

@dataclass(frozen=True)
class M6_1SmokeResult:
    outcomes: List[M6_1SmokeOutcome]    # always 6 entries (2 cells × 3 cohorts)
    overall_status: Literal["ok", "failed"]
    wall_clock_s: float                 # SC-002 — should be ≤ 300
```

**Validation rules**:
- `len(outcomes) == 6` (FR-012).
- `overall_status == "ok"` ⇔ all `outcomes[i].status == "ok"`.
- The 2 smoke cells MUST be `(embed, h=4096, c=1)` and
  `(chat_stream, h=4096, c=1)` (FR-012).
- The smoke gate MUST NOT execute the FR-029 chat_stream control-drift check
  (FR-012 — n=10 CIs too wide for meaningful overlap test).

### `SupersedesM6Row`

One row of the "Supersedes M6 under enable_prompt_embeds" verdict table
(FR-020 / US1).

```python
@dataclass(frozen=True)
class SupersedesM6Row:
    cell: M6_1Cell
    classification: VerdictClassification
    m6_1_classifier_metric_mean_per_cohort: Dict[M6_1CohortKind, float]
    m6_1_classifier_metric_ci_per_cohort: Dict[M6_1CohortKind, Tuple[float, float]]
    m6_winner_cohort: Optional[M6_1CohortKind]    # which cohort M6 picked, or None per FR-010 sub-clause
    m6_winner_delta_ms: Optional[float]
    engine_cost_mean_ms: float
    engine_cost_drift_warning: bool
    chat_stream_control_drift_warning: bool       # NEW in M6.1 — only true for chat_stream cells per FR-029
    notes: str                                    # human-readable
```

### `M6_1Run`

Top-level published JSON shape. **Strict superset of M6's `M6Run`** (FR-021).

```python
@dataclass(frozen=True)
class M6_1Run:
    run_id: str                                                # ISO-8601 timestamp + git_sha suffix
    run_started_at: str
    run_completed_at: str
    run_meta: M6_1RunMeta                                      # FR-027 (renamed from m6_meta for M6.1 — see strict-superset note below)
    smoke_result: Optional[M6_1SmokeResult]
    cells: List[M6_1CellRecord]                                # always 6 entries
    rtt_distribution: Dict[M6_1CohortKind, RTTRecord]          # reused from M6
    supersedes_m6_under_enable_prompt_embeds: List[SupersedesM6Row]   # FR-020 / US1

    # NEW in M6.1 (additive section per FR-021):
    engine_path_differential: List[EnginePathDifferentialRow]  # FR-020 / US2

    # M6-strict-superset compatibility (FR-021) — these fields preserve M6's
    # JSON shape so existing M6-aware consumers continue to work unmodified:
    schema_version: str                                        # bumped to "m6_1.v1"
    cohorts: List[Dict]                                        # M6-shape per-cohort summaries
    protocol_comparison_verdicts: List[Dict]                   # M6-shape verdict rows (populated from M6.1 classifier output)
    supersedes_m5_2_under_real_engine: List[Dict]              # passthrough of M6's section (snapshot in m6_winner_deltas)
    engine_cost_baseline: List[Dict]                           # M6-shape engine-cost-per-RPC table
    schema_candidate_recommendations: List[Dict]               # empty in M6.1 (deferred axis)
    channel_axis_recommendations: List[Dict]                   # empty in M6.1 (deferred axis)
    transport_only_verdicts: List[Dict]                        # empty in M6.1
    shared_baseline_cohorts: List[Dict]                        # empty in M6.1
    supersedes_m1_time: Optional[Dict]                         # null in M6.1
    supersedes_m3: Optional[Dict]                              # null in M6.1
    supersedes_m4: Optional[Dict]                              # null in M6.1
    supersedes_m5_1: Optional[Dict]                            # null in M6.1
    symmetry: Optional[Dict]                                   # M6-shape symmetry audit
    payload_parity_audit: Optional[Dict]                       # null in M6.1
```

**Strict-superset note on `run_meta` vs `m6_meta`**: M6 published its
RunMeta under the JSON key `m6_meta`. M6.1's RunMeta is published under both
`run_meta` (the new canonical key for the milestone family going forward)
AND `m6_meta` (a back-reference passthrough copy that contains the M6
baseline's recorded values, for M6-aware consumers that index by the old
key). The duplication is a one-line cost and preserves the strict-superset
guarantee (FR-021) without forcing downstream consumers to retag.

**Validation rules**:
- `len(cells) == 6` (FR-001).
- `len(rtt_distribution) == 3`.
- `len(supersedes_m6_under_enable_prompt_embeds) == 6` (US1 — one per cell).
- `len(engine_path_differential) == 6` (US2 — one per cell, even
  cell_incomplete cells populate per SC-007).
- The strict-superset fields MUST be present and structurally valid against
  M6's JSON schema so M6-aware downstream consumers don't break (FR-021).
  A golden-file unit test validates this.

---

## Prompt-embeds tensor payload entity

### `PromptEmbedsTensorPayload`

Logical view of the tensor shipped on the wire (FR-028). Materialised
per-RPC by the M6.1 embed driver.

```python
@dataclass(frozen=True)
class PromptEmbedsTensorPayload:
    shape: Tuple[int, int]    # always (seq_len, hidden_size=4096); seq_len pinned per FR-028
    dtype: Literal["float16"]  # FR-028 — matches engine's loaded weights dtype

    # Wire representations (one of these is what travels on the network):
    grpc_bytes: bytes          # torch.save(tensor) raw bytes — shipped in CompletionRequest.prompt_embeds
    rest_input_b64: str        # base64-encoded torch.save(tensor) bytes — shipped in REST input field
```

**Validation rules**:
- `shape[1] == 4096` (FR-028 — hidden_size pinned to Qwen3-8B architecture).
- `shape[0] == M6_1RunMeta.seq_len` (FR-028 — fixed across all RPCs).
- `dtype == "float16"` (FR-028 — matches the engine's loaded weights).
- `grpc_bytes[:4] == b"PK\x03\x04"` (the torch.save ZIP magic — Research R-1).
- Tensor values per RPC: drawn deterministically from
  `torch.Generator(device='cpu').manual_seed(M6_1_BASE_SEED + rpc_index)`
  via `torch.randn(shape, dtype=torch.float16, generator=...)` (FR-028 / R-3).
  Only the *values* vary per RPC; shape and dtype are fixed.

---

## Per-cohort progress / events sidecar

### `M6_1PerRequestEvent`

Per-RPC event written to the JSONL events sidecar. **Identical shape to M6's
`M6PerRequestEvent`** with the same path-discrimination invariants on the
engine_cost trio.

```python
@dataclass(frozen=True)
class M6_1PerRequestEvent:
    cohort: M6_1CohortKind
    cell_path: Literal["embed", "chat_stream"]
    cell_hidden_size: Literal[4096]
    cell_concurrency: Literal[1, 4, 8]
    network_path: Literal["https_edge", "plain_tcp"]
    request_uuid: str
    rpc_elapsed_ms: float
    rpc_phase: Literal["warmup", "measurement"]
    rpc_index: Optional[int]                       # set for measurement RPCs only
    seed: Optional[int]                            # set for measurement RPCs only (M6_1_BASE_SEED + rpc_index)
    engine_forward_ms: Optional[float]
    engine_ttft_ms: Optional[float]
    engine_tpot_ms: Optional[float]
    success: bool
    failure_reason: Optional[str]
    retry_count: int
```

**Validation rules**:
- `rpc_phase == "warmup"` ⇒ `rpc_index is None` AND `seed is None`.
- `rpc_phase == "measurement"` ⇒ `rpc_index is not None` AND `seed is not None`.
- `cell_path == "embed"` ⇒ `engine_ttft_ms is None` AND `engine_tpot_ms is None`.
- `cell_path == "chat_stream"` ⇒ `engine_forward_ms is None`.

---

## Lifecycle: how entities flow through the sweep

```text
1. Sweep launch:
   - M6 baseline JSON loaded + validated (FR-008/FR-009) → M6_1RunMeta.m6_winner_deltas populated.
   - M6 baseline's engine_version read → M6_1RunMeta.m6_baseline_engine_version.
   - torch.__version__ validated against pinned 2.11.0 (FR-006); abort on mismatch.
   - Modal app deployed reusing M6's startup hook (engine config UNCHANGED per FR-007).
   - seq_len pinned at sweep start by tokenising the M6 text-digest format
     under the loaded model's tokenizer → M6_1RunMeta.seq_len (FR-028 / R-3).
   - M6_1RunMeta.cold_start_s recorded after engine readiness probe.

2. Smoke gate (optional, operator-driven):
   - For each (smoke cell × cohort): n=10 RPCs (with retries per FR-017) → M6_1SmokeOutcome.
   - Aggregated into M6_1SmokeResult.
   - Smoke MUST NOT run the FR-029 chat_stream control-drift check (FR-012);
     smoke summary prints a one-line stderr note that the drift check is
     full-sweep-only.
   - Exit non-zero if overall_status=="failed".

3. Full sweep:
   - For each cell in cell-iteration order:
     a. Per-cohort warmup phase (round-robin per c-batch; reused from M6 R-9).
     b. Measurement phase (round-robin per c-batch; per-RPC seeds via FR-019).
        Embed cohorts emit torch.save(tensor) bytes per FR-002/FR-003.
     c. Per-RPC measurements stream into events sidecar AND accumulate into
        M6_1PerCohortAggregate values.
     d. Cell-level aggregation produces M6_1CellRecord with
        classification (FR-010 algorithm — see [R-8](./research.md#r-8-verdict-classifier-algorithm-m61)).
     e. Progress line emitted on stderr per (cell × cohort) pair (FR-023).

4. Post-sweep:
   - For each chat_stream cell, check CI-overlap against M6's published
     chat_stream CIs (FR-029) — set
     M6_1CellRecord.chat_stream_control_drift_warning per [R-6](./research.md#r-6-chat_stream-control-drift-check-algorithm).
   - For each cell, compute EnginePathDifferentialRow (FR-020 / SC-007 — even
     cell_incomplete cells populate this).

5. Reporting:
   - 6 M6_1CellRecord values + M6_1RunMeta + M6_1SmokeResult + RTT probe +
     EnginePathDifferentialRow values → M6_1Run.
   - M6_1Run serialised to JSON companion (FR-021 strict superset of M6).
   - SupersedesM6Row table rendered into markdown report (FR-020).
   - Engine path differential section rendered (FR-020 / US2).
   - Engine_version comparison note rendered in methodology section (FR-030).
   - Final completion banner emitted on stderr (FR-023).
```
