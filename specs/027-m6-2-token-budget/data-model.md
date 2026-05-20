# Data Model: M6.2 — Token-Budget Characterization

**Branch**: `027-m6-2-token-budget` | **Phase 1 output** | **Plan**: [plan.md](./plan.md)

## Overview

M6.2 adds **seven top-level additive artifact keys** + **seven additive per-row fields** + **ten additive `run_meta` fields** on top of the M6.1.3 schema. `schema_version` stays at `"m6_1_1.v1"` per FR-011. Pre-M6.2 readers ignore unknown keys cleanly.

Round-5 extends the prior data model with:
- `prompt_source` + `measurement_regime` + `prompt_corpus_idx` fields on `M6_2MeasurementPoint`.
- `sub_probe_n_rpcs` + `sub_probe_prompt_source` on `M6_2KVPressureObservation`.
- `chat_corpus_sha256` + `chat_corpus_path` + `embed_corpus_sha256` + `embed_corpus_path` on `M6_2RunMeta`.

All entity definitions live in `tools/benchmark/src/vllm_grpc_bench/m6_2_types.py`. Each type uses the M6.1.3 `@dataclass(slots=True, kw_only=True)` convention with `mypy --strict` compliance.

## Entities

### MeasurementPoint (extends M6.1.3 per-cell row type)

**Purpose**: a single `(cell, cohort, max_tokens)` tuple. One row per triple in the latency budget table; 144 rows in publish, 72 in validate.

**Fields** (additive over the M6.1.3 per-cell row; round-5 fields marked):

| Field | Type | Required | Source | Notes |
|---|---|---|---|---|
| `cell_id` | `str` | Yes | inherited | One of the 6 cells. |
| `cohort` | `str` | Yes | inherited | One of 4 cohorts. |
| `max_tokens` | `int` | Yes | NEW (M6.2 round-4) | `{10, 50, 256, 512, 1024, 2048}` (publish) or `{10, 50, 2048}` (validate). |
| `n_rpcs` | `int` | Yes | inherited | `n=20` (validate) or round-3-pinned (publish). |
| `wall_p50_ms` | `float \| None` | conditional | inherited | `None` if `failed_<reason>`. |
| `wall_p95_ms` | `float \| None` | conditional | inherited | |
| `wall_p99_ms` | `float \| None` | conditional | inherited | |
| `wall_p50_ms_ci_half_width` | `float \| None` | conditional | inherited | `1.96 × stderr`. |
| `tpot_ms` | `float \| None` | conditional (chat_stream only) | inherited | |
| `seg_ab_ms` / `seg_queue_ms` / `seg_prefill_ms` / `seg_ingress_ms` / `seg_egress_ms` | `float \| None` | conditional | M6.1.3 5-segment decomposition | |
| `failed_reason` | `str \| None` | conditional | FR-029 | E.g. `"oom"`, `"grpc_timeout"`. |
| `block_start_utc` | `str` (ISO-8601) | Yes | FR-032 | |
| `block_end_utc` | `str` (ISO-8601) | Yes | FR-032 | |
| `retry_attempted` | `bool` | Yes | FR-033 | `true` if in-window retry fired. |
| `clock_anomaly` | `bool` | inherited | FR-006 inherited via classifier | SC-011 0.5% RPC budget. |
| **`prompt_source`** | `Literal["synthetic_seed_derived", "corpus_sharegpt", "synthetic_random_tensor", "corpus_sharegpt_embed"]` | Yes | **NEW (round-5 FR-034/FR-035)** | Null-anchor rows carry the synthetic value (cell-type-dependent); interior-cap rows carry the corpus value (cell-type-dependent). Sub-probe rows are NOT in this table (they go to KVPressureObservation only). |
| **`measurement_regime`** | `Literal["natural_eos"]` | Yes | **NEW (round-5 FR-036)** | Always `"natural_eos"` for budget-table rows (the sub-probe's `"forced_cap_ignore_eos_true"` regime is exclusive to KVPressureObservation and never appears in MeasurementPoint). The field is kept on MeasurementPoint as a forward-compatible marker so a future milestone could extend the regime vocabulary additively. |
| **`prompt_corpus_idx`** | `int \| None` | Yes | **NEW (round-5)** | For corpus-regime rows: the `iter_idx` passed to `symmetric_prompts.assign_symmetric_prompt(iter_idx, cohort, corpus)` (so post-hoc analysis can re-derive which corpus entry drove each RPC's prompt selection). `None` for synthetic-regime rows. |

**Validation rules**:
- If `failed_reason is not None`, all latency fields are `None`. Conversely if `failed_reason is None`, required latency fields are populated.
- `block_start_utc < block_end_utc`.
- `max_tokens` in the active axis subset.
- `prompt_source` value MUST be consistent with `(cell_id starts with embed/chat_stream)` and `max_tokens ∈ {10, 50}` (synthetic regime) vs `max_tokens > 50` (corpus regime). Validation rule: cell-type-dependent regime mapping per round-5 R-9 table.
- `prompt_corpus_idx is None` iff `prompt_source ∈ {"synthetic_seed_derived", "synthetic_random_tensor"}`; `prompt_corpus_idx is not None` iff `prompt_source ∈ {"corpus_sharegpt", "corpus_sharegpt_embed"}`.

**Relationships**:
- 144 MeasurementPoints (publish) form the latency budget table.
- 48 anchor MeasurementPoints (at `max_tokens ∈ {10, 50}`) split per FR-012 into 22 cross-checkable NullAnchor pairs (chat at max_tokens=50 + embed at max_tokens=10, minus M6.1.3's 2 cohort omissions) and 26 new-baseline NullAnchor entries (chat at max_tokens=10 + embed at max_tokens=50 + the 2 omitted cohort pairs at the cross-checkable cap).
- The 8 KVPressureObservation records are derived from 16 sub-probe blocks that produce their own `M6_2MeasurementPoint`-shaped rows internally but DO NOT join the budget table per FR-036 additive contract.

### NullAnchor

**Purpose**: a MeasurementPoint at `max_tokens ∈ {10, 50}` paired with the M6.1.3 published measurement; drift verdict per FR-012 / FR-013.

**Fields**: (unchanged from prior data model)

| Field | Type | Required | Notes |
|---|---|---|---|
| `cell_id` | `str` | Yes | |
| `cohort` | `str` | Yes | |
| `max_tokens` | `int` | Yes | `{10, 50}`. |
| `m6_2_wall_p50_ms` | `float \| None` | conditional | `None` if M6.2 anchor block failed. |
| `m6_1_3_wall_p50_ms` | `float` | Yes | M6.1.3 baseline. |
| `m6_1_3_ci_half_width` | `float` | Yes | |
| `drift_verdict` | `Literal["PASS", "WARN", "FAIL"]` | Yes | `PASS`: inside M6.1.3 CI; `WARN`: outside CI but within 2×; `FAIL`: outside 2× CI half-width. |
| `drift_fraction` | `float \| None` | conditional | `(m6_2_p50 - m6_1_3_p50) / m6_1_3_ci_half`. |

**Note (round-5)**: Null-anchor MeasurementPoints carry `prompt_source = "synthetic_seed_derived"` (chat) or `"synthetic_random_tensor"` (embed) — preserves the M6.1.3-baseline byte-comparability. The NullAnchor entity itself doesn't carry `prompt_source` because the regime is implied by `max_tokens ∈ {10, 50}` ↔ null-anchor regime.

### CrossoverThreshold

**Purpose**: per-cell crossover threshold from the symmetric mean-in-CI rule.

**Fields**: (unchanged from prior data model)

| Field | Type | Required | Notes |
|---|---|---|---|
| `cell_id` | `str` | Yes | |
| `m6_1_3_winner_cohort` | `str \| None` | conditional | |
| `m6_1_3_second_cohort` | `str \| None` | conditional | |
| `crossover_max_tokens` | `int \| None` | conditional | Full vocabulary in publish; coarse 4-value in validate. |
| `crossover_evidence` | `str` | Yes | Human-readable explanation. |
| `m6_1_3_base_verdict` | `str` | Yes | |

**Note (round-5)**: The crossover compute consumes the **budget-table rows** (interior-cap natural-EOS regime), NOT the sub-probe rows. The crossover threshold answers "at what `max_tokens` do cohorts converge under production-realistic load" — natural-EOS behavior. The sub-probe is irrelevant to crossover detection.

### KVPressureObservation

**Purpose**: characterizes the `c=8 × max_tokens=2048` regime per cohort × cell-type. Per FR-036 (round-5), this entity is populated from the **KV-pressure sub-probe**, NOT the main-sweep budget-table rows.

**Fields** (extended in round-5):

| Field | Type | Required | Source | Notes |
|---|---|---|---|---|
| `cohort` | `str` | Yes | per-cohort iteration | |
| `cell_type` | `Literal["chat_stream", "embed"]` | Yes | per-cell-type iteration | |
| `wall_clock_ratio_c8_2048_over_1024` | `float \| None` | Yes (computed) | derived from sub-probe rows | `wall_p50_ms(c=8, max_tokens=2048) / wall_p50_ms(c=8, max_tokens=1024)` per cohort × cell-type, from sub-probe measurements (NOT budget-table). REQUIRED per FR-017a. `None` if either sub-probe block failed. |
| `wall_clock_inference_label` | `Literal["kv_pressure_inferred_chat_stream", "kv_pressure_inferred_embed", "kv_pressure_not_observable"]` | Yes | derived | `R > 2.2` → `kv_pressure_inferred_<cell_type>`; else `kv_pressure_not_observable`. Threshold 2.2 pinned per spec round-3 Q3. |
| `kv_cache_used_fraction_peak` | `float \| None` | best-effort | per-RPC trailing metadata | `None` if vLLM doesn't expose `engine_kv_cache_used_fraction`. |
| `scheduling_stall_signals` | `str \| None` | best-effort | engine logs | |
| `oom_observed` | `bool` | Yes | derived | `True` if any sub-probe RPC at (cohort, c=8, 2048) hit OOM. |
| **`sub_probe_n_rpcs`** | `int` | Yes | **NEW (round-5 FR-036)** | Pinned at `20`. |
| **`sub_probe_prompt_source`** | `Literal["corpus_sharegpt", "corpus_sharegpt_embed"]` | Yes | **NEW (round-5 FR-034/FR-035)** | `corpus_sharegpt` for chat sub-probe; `corpus_sharegpt_embed` for embed sub-probe. |
| **`sub_probe_measurement_regime`** | `Literal["forced_cap_ignore_eos_true"]` | Yes | **NEW (round-5 FR-036)** | Always `"forced_cap_ignore_eos_true"` — the sub-probe sets `ignore_eos=True` so generation runs to the cap on every RPC. Distinguishes sub-probe measurements from the budget-table c=8 × {1024, 2048} rows which use `"natural_eos"`. |

**Validation rules**:
- If either sub-probe block (at 1024 or 2048) failed, `wall_clock_ratio_c8_2048_over_1024 = None` and `wall_clock_inference_label = "kv_pressure_not_observable"` with a narrative footnote.
- `oom_observed = True` iff any sub-probe RPC at `(cohort, {chat_stream_c8 or embed_c8}, 2048)` returned an OOM error.

**Relationships**:
- 8 KVPressureObservation records per artifact (4 cohorts × 2 cell-types).
- Derived from 16 sub-probe blocks (4 cohorts × 2 cell-types × 2 caps) at `n=20`.
- The sub-probe blocks emit per-block measurements internally but **do NOT** populate `M6_2MeasurementPoint` rows in the latency budget table — the budget table's c=8 × {1024, 2048} rows are populated by the main-sweep interior-cap regime per FR-036 additive contract.

### NetworkPathSnapshot

**Purpose**: inherited from M6.1.2 unchanged. Per-cohort topology metadata at each probe firing.

**Fields**: (unchanged) `cohort`, `endpoint_ip`, `hops`, `cloud_provider`, `region`, `snapshot_timestamp`.

**Relationships**: M6.2 captures a **trajectory** of snapshots per cohort (8-10 in publish at 4h cadence + start + end; 2 in validate at start + end).

### AnchorLatencyTrajectory

**Purpose**: per-cohort sequence of intra-sweep re-anchor snapshots per FR-031.

**Fields**: (unchanged from prior data model)

| Field | Type | Required | Notes |
|---|---|---|---|
| `cohort` | `str` | Yes | |
| `snapshots` | `list[AnchorLatencySnapshot]` | Yes | 8-10 in publish; 2 in validate. |
| `max_minus_min_wall_p50_ms` | `float` | Yes | derived spread. |
| `latency_drift_warning` | `bool` | Yes | `spread > m6_1_3_baseline_ci_half_width`. |

**AnchorLatencySnapshot sub-entity** fields: `wall_p50_ms`, `wall_p95_ms`, `wall_p99_ms`, `snapshot_timestamp`, `sweep_hour_mark`.

**Note (round-5)**: The anchor block uses the **synthetic prompt regime** (chat_stream c=1 × max_tokens=10 via `m6_rpc_driver._build_chat_prompt(seed)`) — NOT the corpus regime — to preserve byte-comparability with the M6.1.3 baseline anchor CIs. This is intentional; switching to corpus would make the trajectory measure prompt-source drift instead of network/temporal drift.

### M6_2SweepArtifact (top-level)

**Purpose**: complete artifact persisted to `docs/benchmarks/m6_2-token-budget.json` (or `-validate.json`). Extends M6.1.3's `M6_1_3SweepArtifact` with additive top-level fields.

**Fields** (additions only):

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | `Literal["m6_1_1.v1"]` | Yes | Unchanged. |
| `run_meta` | `M6_2RunMeta` | Yes | See `run_meta` schema below. |
| `network_paths` | `dict[cohort, list[NetworkPathSnapshot]]` | Yes | Trajectory per cohort. |
| `per_cell` | `dict[cell_id, dict[cohort, dict[max_tokens, M6_2MeasurementPoint]]]` | Yes | Latency budget table. |
| `null_anchor_validation` | `list[NullAnchor]` | Yes | 48 records. |
| `max_tokens_axis` | `list[int]` | Yes | The axis literal. |
| `protocol_crossover` | `list[CrossoverThreshold]` | Yes | 6 records (one per cell). |
| `kv_pressure_observation` | `list[KVPressureObservation]` | Yes | 8 records (4 cohorts × 2 cell-types). Populated from the sub-probe per round-5 FR-036. |
| `anchor_latency_trajectory` | `dict[cohort, AnchorLatencyTrajectory]` | Yes | 4 records. |
| `failure_summary` | `dict[str, int]` | Yes | Per-reason tally; always present. |
| `integrity_warnings` | `list[str]` | Yes | Canonical channel labels fired (empty if none). |

**M6_2RunMeta schema** (extends M6_1_3RunMeta; round-5 fields marked):

| Field | Type | Required | Notes |
|---|---|---|---|
| `dispatch_mode` | `Literal["concurrent"]` | Yes | FR-007. |
| `symmetric_prompts_enabled` | `bool` | Yes | Always `true` in M6.2 (FR-008). |
| `schema_version` | `Literal["m6_1_1.v1"]` | Yes | |
| `m6_1_3_baseline_artifact_path` | `str` | Yes | Default `"docs/benchmarks/m6_1_3-attribution-closure.json"`. |
| `sweep_mode` | `Literal["m6_2_publish", "m6_2_validate"]` | Yes | |
| `iteration_order` | `Literal["cohort_innermost_block"]` | Yes | FR-030. |
| `iteration_discipline_verified` | `bool` | Yes | FR-032. |
| `n_per_point` | `int` | Yes | Round-3-pinned (publish) or `20` (validate). |
| `validate_axis_subset` | `list[int] \| None` | Yes | `[10, 50, 2048]` in validate; `None` in publish. |
| `wall_clock_start_utc` | `str` (ISO-8601) | Yes | |
| `wall_clock_end_utc` | `str` (ISO-8601) | Yes | |
| `total_sweep_hours` | `float` | Yes | |
| `modal_spend_usd_estimate` | `float \| None` | Yes | Best-effort. |
| **`chat_corpus_sha256`** | `str` | Yes | **NEW (round-5 FR-034)** | The SHA-256 of `tools/benchmark/corpus/chat_sharegpt_1000.json` (read from `chat_sharegpt_1000.provenance.json:corpus_sha256` at sweep start). |
| **`chat_corpus_path`** | `str` | Yes | **NEW (round-5 FR-034)** | Default `"tools/benchmark/corpus/chat_sharegpt_1000.json"`. |
| **`embed_corpus_sha256`** | `str` | Yes | **NEW (round-5 FR-035)** | The SHA-256 of the new embed corpus (read from `completions_embeds_qwen3_8b/manifest.json:corpus_sha256` at sweep start). |
| **`embed_corpus_path`** | `str` | Yes | **NEW (round-5 FR-035)** | Default `"tools/benchmark/corpus/completions_embeds_qwen3_8b/"`. |
| **`sub_probe_ran`** | `bool` | Yes | **NEW (round-5 FR-036)** | `True` in both publish and validate modes (sub-probe is unconditional per SC-019). |

## Strict-superset compatibility

Every M6.1.3-vintage reader can parse the M6.2 artifact without modification. Top-level new keys + per-row new fields + run_meta new fields are added; M6.1.3-vintage readers ignore unknown keys per JSON-decode default. `schema_version` is unchanged. Test `test_m6_2_artifact_schema.py::test_strict_superset_compat_with_m6_1_3` enforces this.

## Type module organization

```python
# tools/benchmark/src/vllm_grpc_bench/m6_2_types.py

from typing import Literal
from dataclasses import dataclass
from .m6_1_3_types import (
    M6_1_3SweepArtifact,
    M6_1_3RunMeta,
    M6_1_3MeasurementPoint,
    ...
)

M6_2_MAX_TOKENS_AXIS: tuple[int, ...] = (10, 50, 256, 512, 1024, 2048)
M6_2_VALIDATE_MAX_TOKENS_AXIS: tuple[int, ...] = (10, 50, 2048)
M6_2_NULL_ANCHOR_MAX_TOKENS: tuple[int, ...] = (10, 50)
M6_2_INTERIOR_CAP_MAX_TOKENS: tuple[int, ...] = (256, 512, 1024, 2048)
M6_2_SUB_PROBE_MAX_TOKENS: tuple[int, ...] = (1024, 2048)
M6_2_SUB_PROBE_N: int = 20
M6_2_KV_PRESSURE_THRESHOLD: float = 2.2
M6_2_NULL_ANCHOR_DRIFT_FRACTION_THRESHOLD: int = 3
M6_2_LATENCY_DRIFT_COHORT_COUNT_THRESHOLD: int = 2
M6_2_FAILURE_SUMMARY_CELL_COUNT_THRESHOLD: int = 3

M6_2SweepMode = Literal["publish", "validate"]
M6_2PromptSource = Literal[
    "synthetic_seed_derived",
    "corpus_sharegpt",
    "synthetic_random_tensor",
    "corpus_sharegpt_embed",
]
M6_2MeasurementRegime = Literal["natural_eos", "forced_cap_ignore_eos_true"]
M6_2WallClockInferenceLabel = Literal[
    "kv_pressure_inferred_chat_stream",
    "kv_pressure_inferred_embed",
    "kv_pressure_not_observable",
]
M6_2DriftVerdict = Literal["PASS", "WARN", "FAIL"]

@dataclass(slots=True, kw_only=True)
class M6_2MeasurementPoint(M6_1_3MeasurementPoint):
    max_tokens: int
    block_start_utc: str
    block_end_utc: str
    retry_attempted: bool
    prompt_source: M6_2PromptSource
    measurement_regime: M6_2MeasurementRegime  # always "natural_eos" in budget table
    prompt_corpus_idx: int | None

@dataclass(slots=True, kw_only=True)
class M6_2KVPressureObservation:
    cohort: str
    cell_type: Literal["chat_stream", "embed"]
    wall_clock_ratio_c8_2048_over_1024: float | None
    wall_clock_inference_label: M6_2WallClockInferenceLabel
    kv_cache_used_fraction_peak: float | None
    scheduling_stall_signals: str | None
    oom_observed: bool
    sub_probe_n_rpcs: int  # always 20
    sub_probe_prompt_source: Literal["corpus_sharegpt", "corpus_sharegpt_embed"]
    sub_probe_measurement_regime: Literal["forced_cap_ignore_eos_true"]

@dataclass(slots=True, kw_only=True)
class M6_2RunMeta(M6_1_3RunMeta):
    iteration_order: Literal["cohort_innermost_block"]
    iteration_discipline_verified: bool
    n_per_point: int
    validate_axis_subset: list[int] | None
    wall_clock_start_utc: str
    wall_clock_end_utc: str
    total_sweep_hours: float
    modal_spend_usd_estimate: float | None
    chat_corpus_sha256: str
    chat_corpus_path: str
    embed_corpus_sha256: str
    embed_corpus_path: str
    sub_probe_ran: bool

@dataclass(slots=True, kw_only=True)
class M6_2SweepArtifact(M6_1_3SweepArtifact):
    null_anchor_validation: list[M6_2NullAnchor]
    max_tokens_axis: list[int]
    protocol_crossover: list[M6_2CrossoverThreshold]
    kv_pressure_observation: list[M6_2KVPressureObservation]
    anchor_latency_trajectory: dict[str, M6_2AnchorLatencyTrajectory]
    failure_summary: dict[str, int]
    integrity_warnings: list[str]
    run_meta: M6_2RunMeta  # type: ignore[assignment]
```

## Validation invariants

Cross-entity invariants the implementation MUST preserve (tested in `test_m6_2_artifact_schema.py` + round-5 additions in `test_m6_2_prompt_source.py` + `test_m6_2_sub_probe.py`):

1. **144-row table completeness (SC-003)**: `len(all_measurement_points) == 144` in both modes — publish renders 144 measurements (or `failed_<reason>` markers); validate renders 72 measurements + 72 `not_validated` placeholders per FR-016.
2. **48-cell anchor pool with cross-checkable / new-baseline split (FR-012 / FR-014)**: `len([m for m in measurement_points if m.max_tokens in {10, 50}]) == 48`; of these, exactly 22 carry `null_anchor.cross_checkable == True` (chat at max_tokens=50 + embed at max_tokens=10 minus M6.1.3's 2 cohort omissions) and 26 carry `null_anchor.new_baseline_marker == True`.
3. **Cohort-innermost discipline (FR-030 / FR-032)**: every `(cell, max_tokens)` tuple's 4 cohort blocks form a contiguous time window.
4. **In-window retry policy (FR-033)**: any row with `retry_attempted=True` has timestamps within its tuple's window.
5. **Strict-superset compat (FR-011 / SC-007)**: M6.1.3-vintage reader parses without exception.
6. **Failure-summary present always (SC-014)**: `failure_summary` key present, `{}` if no failures.
7. **Trajectory snapshot count (SC-015)**: ≥ 8 publish, ≥ 2 validate.
8. **Integrity-warning channel discipline**: `integrity_warnings` ⊆ `{"null_anchor_drift", "failure_summary_threshold", "cohort_csp_mismatch", "intra_sweep_latency_drift", "iteration_discipline_broken"}`.
9. **Round-5: Three-regime prompt-source discipline (SC-018)**: every MeasurementPoint's `prompt_source` is consistent with `(cell_type, max_tokens)` per the R-9 regime table. `prompt_corpus_idx is None` iff `prompt_source` is synthetic; `prompt_corpus_idx is not None` iff `prompt_source` is corpus.
10. **Round-5: Corpus SHA validation (SC-018)**: `run_meta.chat_corpus_sha256` matches `chat_sharegpt_1000.provenance.json:corpus_sha256` on-disk; `run_meta.embed_corpus_sha256` matches `completions_embeds_qwen3_8b/manifest.json:corpus_sha256` on-disk. Mismatch raises `CorpusDriftError` at sweep start.
11. **Round-5: Sub-probe contract (SC-019)**: exactly 8 `KVPressureObservation` records per artifact; each carries `sub_probe_n_rpcs=20`, `sub_probe_measurement_regime="forced_cap_ignore_eos_true"`, `sub_probe_prompt_source` matching the cell-type. `run_meta.sub_probe_ran = True` in both publish and validate modes.
12. **Round-5: KV-pressure inference source (FR-017a amended)**: `wall_clock_ratio_c8_2048_over_1024` MUST be computed from sub-probe `wall_p50_ms` values (NOT from budget-table c=8 rows). Test enforcement: synthesize a budget-table where c=8 rows have very different p50s from the sub-probe rows; assert the ratio equals the sub-probe ratio, not the budget-table ratio.
