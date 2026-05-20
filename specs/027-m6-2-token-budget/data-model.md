# Data Model: M6.2 — Token-Budget Characterization

**Branch**: `027-m6-2-token-budget` | **Phase 1 output** | **Plan**: [plan.md](./plan.md)

## Overview

M6.2 adds **four top-level additive artifact keys** + **four additive per-row fields** + **two additive `run_meta` fields** on top of the M6.1.3 schema. `schema_version` stays at `"m6_1_1.v1"` per FR-011. Pre-M6.2 readers ignore unknown keys cleanly per the strict-superset convention.

All entity definitions live in `tools/benchmark/src/vllm_grpc_bench/m6_2_types.py`. Each type follows the M6.1.3 `@dataclass(slots=True, kw_only=True)` convention with `mypy --strict` compliance.

## Entities

### MeasurementPoint (extends M6.1.3 per-cell row type)

**Purpose**: a single `(cell, cohort, max_tokens)` tuple — the atomic measurement unit. One row per triple in the latency budget table; 144 rows in publish mode (6 cells × 4 cohorts × 6 caps), 72 rows in validate mode (6 cells × 4 cohorts × 3 caps).

**Fields** (additive over the M6.1.3 per-cell row):

| Field | Type | Required | Source | Notes |
|---|---|---|---|---|
| `cell_id` | `str` | Yes | inherited | One of `embed_c1`/`embed_c4`/`embed_c8`/`chat_stream_c1`/`chat_stream_c4`/`chat_stream_c8`. |
| `cohort` | `str` | Yes | inherited | One of `rest_plain_tcp`/`rest_https_edge`/`default_grpc`/`tuned_grpc_multiplexed`. |
| `max_tokens` | `int` | Yes | **NEW (M6.2)** | One of `{10, 50, 256, 512, 1024, 2048}` in publish; `{10, 50, 2048}` in validate. Additive per FR-001. |
| `n_rpcs` | `int` | Yes | inherited | Per-(cell, cohort, max_tokens) sample size. `n=20` in validate; round-3-pinned value in publish (FR-004). |
| `wall_p50_ms` | `float \| None` | conditional | inherited | `None` if `failed_<reason>`; populated otherwise. |
| `wall_p95_ms` | `float \| None` | conditional | inherited | Same conditionality. |
| `wall_p99_ms` | `float \| None` | conditional | inherited | Same conditionality. |
| `wall_p50_ms_ci_half_width` | `float \| None` | conditional | inherited | `1.96 × stderr` (95% normal approximation). Consumed by `m6_2_crossover.py` for the symmetric mean-in-CI rule. |
| `tpot_ms` | `float \| None` | conditional (chat_stream only) | inherited | Per FR-016 TPOT curves section. |
| `seg_ab_ms` / `seg_queue_ms` / `seg_prefill_ms` / `seg_ingress_ms` / `seg_egress_ms` | `float \| None` | conditional | inherited from M6.1.3 5-segment decomposition | Per FR-010, computed and persisted per measurement point. Sum converges to `engine_ttft_ms` ± 1 ms per the M6.1.3 SC-002 canonical invariant. |
| `failed_reason` | `str \| None` | conditional | populated on block failure per FR-029 | `None` if block succeeded; non-`None` (e.g., `"oom"`, `"grpc_timeout"`, `"modal_preemption"`, `"modal_preemption_resume_drift"`) if both first attempt and in-window retry failed. |
| `block_start_utc` | `str` (ISO-8601) | Yes | **NEW (M6.2)** | Per FR-032. Captured at the start of the per-block RPC dispatch loop. |
| `block_end_utc` | `str` (ISO-8601) | Yes | **NEW (M6.2)** | Per FR-032. Captured after the loop completes (including in-window retry). |
| `retry_attempted` | `bool` | Yes | **NEW (M6.2)** | Per FR-033. `false` if first attempt succeeded; `true` if the in-window retry fired (regardless of whether retry succeeded or failed). |
| `clock_anomaly` | `bool` | inherited from M6.1.3 | Negative-segment assertion firing rate; per FR-006 inherited via the classifier import. SC-011 / 0.5% RPC budget. |

**Validation rules**:
- If `failed_reason is not None`, then `wall_p50_ms / wall_p95_ms / wall_p99_ms / wall_p50_ms_ci_half_width / tpot_ms / seg_*_ms` MUST all be `None`. Conversely, if `failed_reason is None`, all required latency fields MUST be non-`None`.
- `block_start_utc < block_end_utc` (ISO-8601 lexicographic comparison is sufficient because all timestamps share the `Z` UTC suffix).
- `max_tokens ∈ M6_2_MAX_TOKENS_AXIS` (publish) or `M6_2_VALIDATE_MAX_TOKENS_AXIS` (validate) — enforced at row construction.

**Relationships**:
- Many MeasurementPoints (144 in publish) collectively form the latency budget table.
- Two MeasurementPoints (one at `max_tokens=10`, one at `max_tokens=50`) per (cell, cohort) form the **NullAnchor pair** (one per cell-cohort, so 24 anchor pairs = 48 anchor cells).
- One MeasurementPoint per (cell, cohort) at `max_tokens=2048` forms the input to the **CrossoverThreshold** compute alongside the rest of the axis.
- Two MeasurementPoints (one at `max_tokens=1024`, one at `max_tokens=2048`) per cohort × cell-type ∈ {chat_stream, embed} at `c=8` form the input to the **KVPressureObservation** compute.

### NullAnchor

**Purpose**: a MeasurementPoint at `max_tokens ∈ {10, 50}` paired with the corresponding M6.1.3 published measurement. Carries the drift verdict per FR-012 / FR-013.

**Fields**:

| Field | Type | Required | Source | Notes |
|---|---|---|---|---|
| `cell_id` | `str` | Yes | inherited from the MeasurementPoint | |
| `cohort` | `str` | Yes | inherited | |
| `max_tokens` | `int` | Yes | inherited; must be `10` or `50` | |
| `m6_2_wall_p50_ms` | `float \| None` | conditional | from the M6.2 MeasurementPoint | `None` if M6.2 block failed. |
| `m6_1_3_wall_p50_ms` | `float` | Yes | loaded from M6.1.3 baseline JSON | Per FR-013, default path `docs/benchmarks/m6_1_3-attribution-closure.json`. |
| `m6_1_3_ci_half_width` | `float` | Yes | loaded from M6.1.3 baseline JSON | |
| `drift_verdict` | `Literal["PASS", "WARN", "FAIL"]` | Yes | derived | `PASS`: M6.2 measurement inside M6.1.3 CI; `WARN`: outside CI but within 2× CI half-width; `FAIL`: outside 2× CI half-width. (`WARN` and `FAIL` both trigger the per-cell `control_drift_warning` line per FR-012; the per-cell drift-verdict distinction is rendered in the "Null anchor validation" subsection for operator visibility.) |
| `drift_fraction` | `float \| None` | conditional | derived | `(m6_2_wall_p50_ms - m6_1_3_wall_p50_ms) / m6_1_3_ci_half_width`; positive = M6.2 is slower. `None` if M6.2 block failed. |

**Validation rules**:
- `max_tokens ∈ {10, 50}` (anchor caps only).
- If `m6_2_wall_p50_ms is None`, then `drift_verdict = "FAIL"` (block failure counts as drift) and `drift_fraction is None`.

**Relationships**:
- 48 NullAnchor records per artifact (6 cells × 4 cohorts × 2 anchor caps). Aggregated into the FR-014 sweep-level integrity header trigger: ≥ 3 records with `drift_verdict ∈ {WARN, FAIL}` → fires.

### CrossoverThreshold

**Purpose**: per-cell record capturing the smallest `max_tokens` at which the M6.1.3-winning and second-place cohorts' wall-clock CIs satisfy the symmetric mean-in-CI rule. Consumed by the "Protocol crossover threshold" markdown section (FR-016).

**Fields**:

| Field | Type | Required | Source | Notes |
|---|---|---|---|---|
| `cell_id` | `str` | Yes | per-cell iteration | |
| `m6_1_3_winner_cohort` | `str \| None` | conditional | from M6.1.3 baseline | `None` if M6.1.3 base verdict was inconclusive. |
| `m6_1_3_second_cohort` | `str \| None` | conditional | from M6.1.3 baseline | Same conditionality. |
| `crossover_max_tokens` | `int \| None` | conditional | derived by `m6_2_crossover.compute_per_cell_crossover(...)` | Per spec round-1 Q3. `None` if base verdict inconclusive OR if symmetric mean-in-CI rule never fires across the axis (verdict survives to 2048). |
| `crossover_evidence` | `str` | Yes | derived | Human-readable explanation. One of: `"base verdict was already inconclusive at the M6.1.3 baseline"` (when `m6_1_3_base_verdict ∈ {inconclusive, multi_factor_*, inconclusive_high_variance}`); `"M6.1.3 verdict not robust to M6.2 resampling"` (when the rule fires at `max_tokens=10`); `"winner_p50={X}ms ± {Y}ms overlaps second_p50={Z}ms ± {W}ms at max_tokens={K}"` (when the rule fires at `max_tokens > 10`); `"verdict survives across the axis"` (when the rule never fires). |
| `m6_1_3_base_verdict` | `str` | Yes | loaded from M6.1.3 baseline JSON | The original M6.1.3 verdict label for this cell. |

**Validation rules**:
- If `m6_1_3_winner_cohort is None` ⟺ `crossover_max_tokens is None` AND `crossover_evidence = "base verdict was already inconclusive at the M6.1.3 baseline"`.
- In publish mode, `crossover_max_tokens ∈ {10, 50, 256, 512, 1024, 2048, None}`. In validate mode, `crossover_max_tokens ∈ {10, 50, 2048, None}` (coarse 4-value vocabulary per FR-016).

**Relationships**:
- 6 CrossoverThreshold records per artifact (one per cell). Rendered as the "Protocol crossover threshold" markdown table.

### KVPressureObservation

**Purpose**: characterizes the `c=8 × max_tokens=2048` regime per cohort × cell-type ∈ {chat_stream, embed}. Computed unconditionally from existing latency budget measurements; engine field captured best-effort.

**Fields**:

| Field | Type | Required | Source | Notes |
|---|---|---|---|---|
| `cohort` | `str` | Yes | per-cohort iteration | |
| `cell_type` | `Literal["chat_stream", "embed"]` | Yes | per-cell-type iteration | |
| `wall_clock_ratio_c8_2048_over_1024` | `float` | Yes | derived | `R = wall_p50_ms(c=8, max_tokens=2048) / wall_p50_ms(c=8, max_tokens=1024)`. REQUIRED per FR-017a. |
| `wall_clock_inference_label` | `Literal["kv_pressure_inferred_chat_stream", "kv_pressure_inferred_embed", "kv_pressure_not_observable"]` | Yes | derived | `R > 2.2` → `kv_pressure_inferred_<cell_type>`; else `kv_pressure_not_observable`. Threshold pinned at 2.2 per spec round-3 Q3. |
| `kv_cache_used_fraction_peak` | `float \| None` | best-effort | from per-RPC trailing metadata | `None` if vLLM does not expose `engine_kv_cache_used_fraction` (the regime is still characterizable via `wall_clock_ratio_c8_2048_over_1024` per FR-017a). |
| `scheduling_stall_signals` | `str \| None` | best-effort | free-form text | Notes from vLLM engine logs captured during the sweep (queue depth, preemption events). Operator-readable narrative; not machine-parsed. |
| `oom_observed` | `bool` | Yes | derived | `True` if any (cohort, c=8, max_tokens=2048) block was marked `failed_oom`. |

**Validation rules**:
- If `failed_reason == "oom"` was observed on the `(cohort, chat_stream_c8, 2048)` or `(cohort, embed_c8, 2048)` MeasurementPoint, then `oom_observed = True` for the corresponding cohort × cell-type pair.
- If `wall_p50_ms` at `(cohort, c=8, max_tokens=1024)` OR `(cohort, c=8, max_tokens=2048)` is `None` (block failed), then `wall_clock_ratio_c8_2048_over_1024 = None` and `wall_clock_inference_label = "kv_pressure_not_observable"` (with a footnote in the narrative explaining the missing input).

**Relationships**:
- 8 KVPressureObservation records per artifact (4 cohorts × 2 cell-types). Rendered as the "KV-cache pressure" markdown subsection.

### NetworkPathSnapshot

**Purpose**: inherited from M6.1.2. Carries per-cohort topology metadata at each probe firing.

**Fields** (inherited from M6.1.2 unchanged):

| Field | Type | Required | Notes |
|---|---|---|---|
| `cohort` | `str` | Yes | |
| `endpoint_ip` | `str` | Yes | |
| `hops` | `list[str]` | Yes | Ordered traceroute hops. |
| `cloud_provider` | `str` | Yes | E.g., `"aws"`, `"gcp"`, `"modal"`. |
| `region` | `str` | Yes | E.g., `"eu-west-1"`. |
| `snapshot_timestamp` | `str` (ISO-8601) | Yes | When the probe fired. |

**Relationships**:
- **NEW (M6.2)**: M6.2 captures a **trajectory** of NetworkPathSnapshots per cohort (8-10 in publish mode at the 4h cadence + start + end; 2 in validate mode at start + end), rather than a single snapshot. Consecutive snapshots are compared to fire the `cohort_csp_mismatch_warning` per FR-009 / SC-010.

### AnchorLatencyTrajectory

**Purpose**: NEW (M6.2). Per-cohort sequence of intra-sweep re-anchor snapshots per FR-031.

**Fields**:

| Field | Type | Required | Source | Notes |
|---|---|---|---|---|
| `cohort` | `str` | Yes | per-cohort iteration | |
| `snapshots` | `list[AnchorLatencySnapshot]` | Yes | populated by `m6_2_anchor_trajectory.compute_anchor_block(...)` invocations | 8-10 snapshots in publish mode (start + end + every 4h); 2 in validate mode (start + end). |
| `max_minus_min_wall_p50_ms` | `float` | Yes | derived | `max(snapshot.wall_p50_ms for snapshot in snapshots) - min(...)`. |
| `latency_drift_warning` | `bool` | Yes | derived | `True` if `max_minus_min_wall_p50_ms > m6_1_3_baseline_ci_half_width_at_chat_stream_c1_max_tokens_10` (loaded from M6.1.3 baseline JSON). |

**AnchorLatencySnapshot sub-entity**:

| Field | Type | Required | Notes |
|---|---|---|---|
| `wall_p50_ms` | `float` | Yes | Per-snapshot p50 at chat_stream c=1 × max_tokens=10, n=20. |
| `wall_p95_ms` | `float` | Yes | |
| `wall_p99_ms` | `float` | Yes | |
| `snapshot_timestamp` | `str` (ISO-8601) | Yes | When the anchor block ran. |
| `sweep_hour_mark` | `int` | Yes | `0` for start, `4`/`8`/...`/40` for in-flight marks, `final` for end. Allows operators to map snapshots to wall-clock position. |

**Validation rules**:
- `len(snapshots) >= 8` in publish mode; `len(snapshots) >= 2` in validate mode.
- `snapshots` are ordered by `snapshot_timestamp` ascending.

**Relationships**:
- 4 AnchorLatencyTrajectory records per artifact (one per cohort).
- The FR-031 / SC-016 sweep-level integrity header fires when ≥ 2 of 4 trajectories have `latency_drift_warning = True`.

### M6_2SweepArtifact (top-level)

**Purpose**: the complete artifact persisted to `docs/benchmarks/m6_2-token-budget.json` (or `-validate.json`). Extends M6.1.3's `M6_1_3SweepArtifact` with additive top-level fields.

**Fields** (showing additions only; inherited M6.1.x fields carry forward unchanged):

| Field | Type | Required | Source | Notes |
|---|---|---|---|---|
| `schema_version` | `Literal["m6_1_1.v1"]` | Yes | inherited | Unchanged per FR-011. |
| `run_meta` | `dict` | Yes | inherited + extended | See `run_meta` schema below. |
| `network_paths` | `dict[cohort, list[NetworkPathSnapshot]]` | Yes | inherited + extended | M6.2 stores a trajectory per cohort, not a single snapshot. |
| `per_cell` | `dict[cell_id, dict]` | Yes | inherited + extended | Each cell's per-cohort × per-max_tokens MeasurementPoint rows. Per FR-016. |
| `null_anchor_validation` | `list[NullAnchor]` | Yes | **NEW (M6.2)** | 48 records per FR-012. |
| `max_tokens_axis` | `list[int]` | Yes | **NEW (M6.2)** | The axis literal: `[10, 50, 256, 512, 1024, 2048]` in publish; `[10, 50, 2048]` in validate. Per FR-001. |
| `protocol_crossover` | `list[CrossoverThreshold]` | Yes | **NEW (M6.2)** | 6 records (one per cell) per FR-016. |
| `kv_pressure_observation` | `list[KVPressureObservation]` | Yes | **NEW (M6.2)** | 8 records (4 cohorts × 2 cell-types) per FR-017. |
| `anchor_latency_trajectory` | `dict[cohort, AnchorLatencyTrajectory]` | Yes | **NEW (M6.2)** | 4 records (one per cohort) per FR-031. |
| `failure_summary` | `dict[str, int]` | Yes | **NEW (M6.2)** | Per FR-029. Keys are failure reasons; values are tallies. Always present even when zero failures (then `{}`). |
| `integrity_warnings` | `list[str]` | Yes | **NEW (M6.2)** | Per-channel sweep-level integrity warning lines fired (the four publish-blocking-eligible + the soft iteration-discipline diagnostic). Empty list if no headers fired. |

**run_meta schema** (showing additions):

| Field | Type | Required | Source | Notes |
|---|---|---|---|---|
| `dispatch_mode` | `Literal["concurrent"]` | Yes | inherited | Per FR-007. |
| `symmetric_prompts_enabled` | `bool` | Yes | inherited from M6.1.3 | Always `true` in M6.2 per FR-008. |
| `schema_version` | `Literal["m6_1_1.v1"]` | Yes | inherited | |
| `m6_1_3_baseline_artifact_path` | `str` | Yes | from CLI | Default `"docs/benchmarks/m6_1_3-attribution-closure.json"`. |
| `sweep_mode` | `Literal["m6_2_publish", "m6_2_validate"]` | Yes | inherited | |
| `iteration_order` | `Literal["cohort_innermost_block"]` | Yes | **NEW (M6.2)** | Per FR-030. Fixed literal; documents the discipline. |
| `iteration_discipline_verified` | `bool` | Yes | **NEW (M6.2)** | Per FR-032. Post-hoc machine check that every `(cell, max_tokens)` tuple's 4 cohort blocks ran contiguously. |
| `n_per_point` | `int` | Yes | from CLI | Round-3-pinned value in publish; `20` in validate. |
| `validate_axis_subset` | `list[int] \| None` | Yes | derived | `[10, 50, 2048]` in validate; `None` in publish. |
| `wall_clock_start_utc` | `str` (ISO-8601) | Yes | derived | When the sweep started. |
| `wall_clock_end_utc` | `str` (ISO-8601) | Yes | derived | When the sweep ended. |
| `total_sweep_hours` | `float` | Yes | derived | `(end - start)` in hours. |
| `modal_spend_usd_estimate` | `float \| None` | Yes | derived | Best-effort estimate from cell count × n × Modal cost rate. |

## Strict-superset compatibility

Every M6.1.3-vintage reader can parse the M6.2 artifact without modification:

- Top-level new keys (`null_anchor_validation`, `max_tokens_axis`, `protocol_crossover`, `kv_pressure_observation`, `anchor_latency_trajectory`, `failure_summary`, `integrity_warnings`) are added; M6.1.3-vintage readers ignore unknown keys per JSON-decode default behavior.
- Per-row new fields on MeasurementPoint (`max_tokens`, `block_start_utc`, `block_end_utc`, `retry_attempted`) are added; M6.1.3-vintage readers ignore them.
- `run_meta` new fields (`iteration_order`, `iteration_discipline_verified`, `n_per_point`, `validate_axis_subset`, `wall_clock_start_utc`, `wall_clock_end_utc`, `total_sweep_hours`, `modal_spend_usd_estimate`) are added; M6.1.3-vintage readers ignore them.
- `schema_version` is unchanged at `"m6_1_1.v1"` — M6.1.3-aware readers do not gate on a version bump.
- Test `test_m6_2_artifact_schema.py::test_strict_superset_compat_with_m6_1_3` synthesizes an M6.2 artifact JSON and parses it with M6.1.3's `M6_1_3SweepArtifact` deserializer; expects no exception and unknown-key warnings only.

## Type module organization

```python
# tools/benchmark/src/vllm_grpc_bench/m6_2_types.py

from typing import Literal
from dataclasses import dataclass, field
# Re-import M6.1.3 types for inheritance:
from .m6_1_3_types import (
    M6_1_3SweepArtifact,
    M6_1_3RunMeta,
    M6_1_3MeasurementPoint,
    ...
)

M6_2_MAX_TOKENS_AXIS: tuple[int, ...] = (10, 50, 256, 512, 1024, 2048)
M6_2_VALIDATE_MAX_TOKENS_AXIS: tuple[int, ...] = (10, 50, 2048)
M6_2_KV_PRESSURE_THRESHOLD: float = 2.2  # FR-017a + spec round-3 Q3
M6_2_NULL_ANCHOR_DRIFT_FRACTION_THRESHOLD: int = 3  # FR-014: ≥ 3 of 48 anchor cells
M6_2_LATENCY_DRIFT_COHORT_COUNT_THRESHOLD: int = 2  # SC-016: ≥ 2 of 4 cohorts
M6_2_FAILURE_SUMMARY_CELL_COUNT_THRESHOLD: int = 3  # FR-029: ≥ 3 cells

M6_2SweepMode = Literal["publish", "validate"]
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

@dataclass(slots=True, kw_only=True)
class M6_2NullAnchor: ...

@dataclass(slots=True, kw_only=True)
class M6_2CrossoverThreshold: ...

@dataclass(slots=True, kw_only=True)
class M6_2KVPressureObservation: ...

@dataclass(slots=True, kw_only=True)
class M6_2AnchorLatencySnapshot: ...

@dataclass(slots=True, kw_only=True)
class M6_2AnchorLatencyTrajectory: ...

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

@dataclass(slots=True, kw_only=True)
class M6_2SweepArtifact(M6_1_3SweepArtifact):
    null_anchor_validation: list[M6_2NullAnchor]
    max_tokens_axis: list[int]
    protocol_crossover: list[M6_2CrossoverThreshold]
    kv_pressure_observation: list[M6_2KVPressureObservation]
    anchor_latency_trajectory: dict[str, M6_2AnchorLatencyTrajectory]
    failure_summary: dict[str, int]
    integrity_warnings: list[str]
    run_meta: M6_2RunMeta  # type: ignore[assignment]  # narrow inherited Union
```

The exact import structure (whether `M6_1_3MeasurementPoint` extends a base class that M6_2 also extends, or whether M6_2 redeclares the per-row schema) is `/speckit-tasks` territory; the dataclass shape above is the spec-level definition.

## Validation invariants

Cross-entity invariants the implementation MUST preserve (test in `test_m6_2_artifact_schema.py`):

1. **144-row table completeness (SC-003)**: `len(all_measurement_points) == 144` in publish, `72` in validate. Every `(cell, cohort, max_tokens)` triple has exactly one row.
2. **48-cell anchor pool (FR-014)**: `len([m for m in measurement_points if m.max_tokens in {10, 50}]) == 48` (across all 4 cohorts × 6 cells × 2 anchor caps). Same count in publish and validate.
3. **Cohort-innermost discipline (FR-030 / FR-032)**: post-hoc check that every `(cell, max_tokens)` tuple's 4 cohort blocks' `block_start_utc` form a contiguous sequence without any other tuple's blocks interleaving.
4. **In-window retry policy (FR-033)**: any `MeasurementPoint` with `retry_attempted = True` has `block_start_utc` and `block_end_utc` within the same `(cell, max_tokens)` tuple's time window (no retry crosses tuple boundaries).
5. **Strict-superset compat (FR-011 / SC-007)**: M6.1.3-vintage readers parse the M6.2 artifact without exception.
6. **Failure-summary present always (SC-014)**: `failure_summary` key present in every artifact (publish + validate), `{}` if no failures.
7. **Trajectory snapshot count (SC-015)**: each cohort's `anchor_latency_trajectory.snapshots` has length ≥ 8 in publish, ≥ 2 in validate.
8. **Integrity-warning channel discipline**: `integrity_warnings` list contains only the canonical channel labels (`null_anchor_drift`, `failure_summary_threshold`, `cohort_csp_mismatch`, `intra_sweep_latency_drift`, `iteration_discipline_broken`); no other strings.
