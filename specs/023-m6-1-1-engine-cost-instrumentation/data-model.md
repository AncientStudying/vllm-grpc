# M6.1.1 Phase 1 — Data Model

**Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

All dataclasses live in `tools/benchmark/src/vllm_grpc_bench/m6_1_1_types.py`. Pydantic v2 (project standard) per Research R-6. Literal types are exported for downstream `mypy --strict` consumers.

---

## Literals & Constants

```python
M6_1_1_BASE_SEED: int = 42  # FR-027 default; identical to M6 / M6.1
PERTURBATION_BUDGET_NS: int = 500_000  # FR-012: 500 µs total per RPC across 4 checkpoints

# FR-010 classifier thresholds (round-1 Q1)
DRIFT_NOT_REPRODUCED_THRESHOLD: float = 0.05  # spread(engine_ttft) / mean(engine_ttft)
ATTRIBUTION_THRESHOLD: float = 0.80  # spread(seg_x) / spread(engine_ttft)

# FR-015b embed regression tolerance (round-1 Q5)
EMBED_REGRESSION_TOLERANCE: float = 0.05  # ±5% of M6.1's published engine_forward_ms mean

# FR-015 + FR-022 chat_stream drift-cleared tolerance (round-1 Q5 / SC-003)
CHAT_STREAM_DRIFT_CLEARED_TOLERANCE: float = 0.05  # each cohort within 5% of unweighted cohort-average

CheckpointName = Literal["handler_entry", "pre_engine", "first_chunk", "terminal_emit"]
SegmentName = Literal["seg_ab", "seg_bc", "seg_cd"]
Phase1Classification = Literal[
    "instrumentation_artifact",
    "channel_dependent_batching",
    "drift_not_reproduced",
    "inconclusive",
]
Phase2Path = Literal[
    "phase_2a_verified",          # FR-014 / FR-015 — code change applied; verification sweep passed
    "phase_2b_documented",        # FR-016 — contracts/instrumentation.md updated
    "phase_2_pending",            # transient — Phase 1 complete, Phase 2 not yet run
    "drift_not_reproduced_confirmed",  # FR-018 — two independent n=50 runs both returned drift_not_reproduced
    "split_required",             # FR-017(b) / FR-018 — heterogeneous Phase 2 disallowed; successor sub-milestones needed
]
BaselineSource = Literal["m6_1_1", "m6_1", "documented_in_contracts", "not_applicable"]
M6_1_1ExitCode = Literal[0, 1, 2, 3, 4, 5]
# 0 success
# 1 missing baseline / contracts heading (FR-001, FR-004, FR-016)
# 2 torch pin mismatch (FR-003)
# 3 re-run needed: mixed, inconclusive, drift_not_reproduced single-run (FR-017, FR-018)
# 4 perturbation budget exceeded (FR-012, round-2 Q3)
# 5 milestone split required: still-divergent / still-inconclusive after re-confirmation (FR-017(b), round-2 Q4)
```

---

## Entity: `M6_1_1Cell`

```python
@dataclass(frozen=True)
class M6_1_1Cell:
    """A (path, concurrency) coordinate in the 6-cell M6.1 matrix.
    Alias for M6_1Cell — M6.1.1 reuses M6.1's matrix shape verbatim."""
    path: Literal["embed", "chat_stream"]
    concurrency: Literal[1, 4, 8]
    hidden_size: Literal[4096] = 4096  # fixed per FR-002 (Qwen3-8B fp16)
```

There are exactly 6 instances: 3 embed cells × 3 chat_stream cells. The 3 chat_stream cells are the only cells that get classified (FR-010, FR-031); embed cells are audit-only controls in Phase 1 (FR-011) and pass/fail regression-checked in Phase 2(a) (FR-015b).

---

## Entity: `TimingCheckpoint`

```python
@dataclass(frozen=True)
class TimingCheckpoint:
    """The four per-RPC `perf_counter_ns()` timestamps captured server-side and emitted on the wire (FR-006 / FR-007 / FR-008)."""
    handler_entry_ns: int
    pre_engine_ns: int
    first_chunk_ns: int
    terminal_emit_ns: int
    perturbation_audit_ns: int  # FR-012 — total `perf_counter_ns()` overhead the 4 reads themselves added (server-side measured)
```

Captured on both REST chat_stream and gRPC chat_stream paths for every chat_stream RPC; on every embed RPC as an audit control (FR-011). Emitted on the wire as:
- **REST**: `m6_1_1_timings` sub-object on the terminal SSE event JSON payload (FR-007).
- **gRPC**: 4 trailing-metadata keys prefixed `m6_1_1_t_` (FR-008).

Client-side extraction is best-effort: when the server isn't running with the new checkpoints, extraction returns `None` and the per-RPC event record carries no M6.1.1 fields.

---

## Entity: `PerSegmentDelta`

```python
@dataclass(frozen=True)
class PerSegmentDelta:
    """Three named per-RPC durations derived from the four checkpoints (FR-009)."""
    seg_ab_ms: float  # (pre_engine - handler_entry) × 1e-6
    seg_bc_ms: float  # (first_chunk - pre_engine) × 1e-6
    seg_cd_ms: float  # (terminal_emit - first_chunk) × 1e-6

    @classmethod
    def from_checkpoint(cls, ckpt: TimingCheckpoint) -> "PerSegmentDelta":
        return cls(
            seg_ab_ms=(ckpt.pre_engine_ns - ckpt.handler_entry_ns) * 1e-6,
            seg_bc_ms=(ckpt.first_chunk_ns - ckpt.pre_engine_ns) * 1e-6,
            seg_cd_ms=(ckpt.terminal_emit_ns - ckpt.first_chunk_ns) * 1e-6,
        )
```

Aggregated per cohort per cell into `PerSegmentAggregate` (below).

---

## Entity: `PerSegmentAggregate`

```python
@dataclass(frozen=True)
class PerSegmentAggregate:
    """Mean + 95% CI half-width via bootstrap n_boot=10_000 (FR-009, matches M6.1's confidence-interval methodology)."""
    seg_ab_ms_mean: float
    seg_ab_ms_ci_half_width: float
    seg_bc_ms_mean: float
    seg_bc_ms_ci_half_width: float
    seg_cd_ms_mean: float
    seg_cd_ms_ci_half_width: float
    n_samples: int  # n_successes per cohort per cell (typically 50 in Phase 1, 100 in Phase 2(a))
```

---

## Entity: `MultiPointTimings`

```python
@dataclass(frozen=True)
class MultiPointTimings:
    """Per (cohort × cell) multi-point timing data (FR-009)."""
    cohort: M6_1_1Cohort  # alias for the M6 / M6.1 cohort literal: rest_https_edge | default_grpc | tuned_grpc_multiplexed
    cell: M6_1_1Cell
    engine_ttft_ms_mean: float
    engine_ttft_ms_ci_half_width: float
    per_segment: PerSegmentAggregate
    perturbation_total_us_mean: float  # FR-012 audit; server-side measured overhead in microseconds
```

---

## Entity: `Phase1Classification` (and the magnitude-equivalence classifier)

```python
def classify_cell(
    cell: M6_1_1Cell,
    per_cohort: dict[M6_1_1Cohort, MultiPointTimings],
) -> Phase1Classification:
    """FR-010 magnitude-equivalence classifier (round-1 Q1).
    
    `spread(x) = max(x) - min(x)` over the three cohort means.
    """
    engine_ttft_means = [v.engine_ttft_ms_mean for v in per_cohort.values()]
    spread_ttft = max(engine_ttft_means) - min(engine_ttft_means)
    mean_ttft = sum(engine_ttft_means) / len(engine_ttft_means)
    
    # drift_not_reproduced short-circuits first (the denominator for the segment ratios would be near zero otherwise)
    if spread_ttft / mean_ttft < DRIFT_NOT_REPRODUCED_THRESHOLD:
        return "drift_not_reproduced"
    
    seg_ab_means = [v.per_segment.seg_ab_ms_mean for v in per_cohort.values()]
    seg_bc_means = [v.per_segment.seg_bc_ms_mean for v in per_cohort.values()]
    spread_ab = max(seg_ab_means) - min(seg_ab_means)
    spread_bc = max(seg_bc_means) - min(seg_bc_means)
    
    if spread_ab / spread_ttft >= ATTRIBUTION_THRESHOLD:
        return "instrumentation_artifact"
    if spread_bc / spread_ttft >= ATTRIBUTION_THRESHOLD:
        return "channel_dependent_batching"
    return "inconclusive"
```

`drift_not_reproduced` is the highest-priority short-circuit (segment ratios undefined when the denominator is near zero). `instrumentation_artifact` checked before `channel_dependent_batching` per spec FR-010 ordering. `inconclusive` is the fallback (no segment dominates; or the spread distribution is anomalous like non-monotonic cohort ordering).

The classifier is **deterministic**: given identical per-cohort timings, the output is reproducible by hand from the published markdown table (SC-010).

---

## Entity: `Phase1RunRecord`

```python
@dataclass(frozen=True)
class Phase1RunRecord:
    """One `--m6_1_1-diagnose` invocation's complete data (round-3 Q1).
    
    Each Phase 1 mini-sweep produces ONE record; the M6.1.1 JSON's
    `phase_1_runs` array accumulates these across all runs for this M6.1.1 instance.
    """
    run_id: str  # e.g. "2026-05-17T09:32:00Z-deadbe7"
    run_started_at: str  # ISO8601 UTC
    run_completed_at: str
    wall_clock_s: float
    multi_point_timings: list[MultiPointTimings]  # one per (cohort, cell) — 18 entries for the full 6×3 matrix
    phase_1_classifications: dict[str, Phase1Classification]  # keyed by cell_str (e.g. "chat_stream_c1_h4096"); only chat_stream cells have classifications
    perturbation_audit: PerturbationAudit  # see below
    n_per_cohort: int  # =50 in Phase 1 mini-sweep
```

---

## Entity: `PerturbationAudit`

```python
@dataclass(frozen=True)
class PerturbationAudit:
    """FR-012 perturbation-budget audit, aggregated per (cohort, cell)."""
    per_cohort_per_cell: dict[tuple[str, str], float]  # (cohort, cell_str) → mean perturbation in µs
    budget_us: float = 500.0  # PERTURBATION_BUDGET_NS / 1000
    exceeded: bool  # True iff any (cohort, cell) pair's mean perturbation > budget_us
    exceeded_pairs: list[tuple[str, str]]  # populated when `exceeded == True`
```

---

## Entity: `Phase2Outcome`

```python
# Discriminated union — one of these three concrete shapes per `phase_2_path`.

@dataclass(frozen=True)
class Phase2aVerifiedOutcome:
    """phase_2_path == "phase_2a_verified" (FR-014, FR-015)."""
    drift_cleared_per_cell: dict[str, bool]  # cell_str → cleared (each cohort within 5% of unweighted cohort-average)
    engine_cost_drift_warning_per_cell: dict[str, bool]  # echoes M6.1's flag shape per FR-015
    chat_stream_control_drift_warning: bool  # expected to fire under symmetrisation per round-1 Q2
    chat_stream_control_drift_note: str  # "expected — reflects bracketing change in Phase 2(a) symmetrisation; not infrastructure drift"
    n_per_cohort: int = 100  # full Phase 2(a) sweep

@dataclass(frozen=True)
class Phase2bDocumentedOutcome:
    """phase_2_path == "phase_2b_documented" (FR-016)."""
    contracts_heading_path: str  # e.g. "contracts/instrumentation.md#m611-channel-dependent-batching-effect"
    contracts_heading_text: str  # matched line from contracts/instrumentation.md

@dataclass(frozen=True)
class DriftNotReproducedConfirmedOutcome:
    """phase_2_path == "drift_not_reproduced_confirmed" (FR-018, round-1 Q4)."""
    note: str  # "drift not reproduced in two independent n=50 Phase 1 mini-sweeps; M6.1's engine_cost_drift_warning preserved as-published"
    confirming_run_ids: tuple[str, str]  # IDs of the two phase_1_runs[] entries

@dataclass(frozen=True)
class SplitRequiredOutcome:
    """phase_2_path == "split_required" (FR-017(b), FR-018, round-2 Q4)."""
    per_cell_classifications_after_reconfirmation: dict[str, Phase1Classification]
    proposed_split_shape: str  # operator-supplied; e.g. "M6.1.1a: instrumentation_artifact cells (c=1, c=4); M6.1.1b: channel_dependent_batching cell (c=8)"
    operator_note: str  # ≤2 sentences per FR-017(b)

Phase2Outcome = Phase2aVerifiedOutcome | Phase2bDocumentedOutcome | DriftNotReproducedConfirmedOutcome | SplitRequiredOutcome | None
# None when phase_2_path == "phase_2_pending"
```

---

## Entity: `EmbedRegressionResult`

```python
@dataclass(frozen=True)
class EmbedRegressionResult:
    """FR-015b — Phase 2(a) embed regression check per (embed cell × cohort)."""
    cell: M6_1_1Cell  # path == "embed"
    cohort: M6_1_1Cohort
    m6_1_engine_forward_ms_mean: float  # baseline from m6_1-real-prompt-embeds.json
    m6_1_1_engine_forward_ms_mean: float  # measured in Phase 2(a)
    delta_pct: float  # (m6_1_1 - m6_1) / m6_1
    embed_regression_warning: bool  # |delta_pct| > 0.05
    embed_regression_acknowledged: bool  # operator-set per FR-015b path (ii)
    operator_justification: str | None  # one-sentence reason when acknowledged
```

---

## Entity: `ChatStreamBaselineSentinel` and `EmbedBaselineSentinel`

```python
@dataclass(frozen=True)
class BaselineCellEntry:
    """One (cell × cohort) entry in a populated baseline section."""
    cell: M6_1_1Cell
    cohort: M6_1_1Cohort
    engine_ttft_ms_mean: float | None  # populated for chat_stream, None for embed
    engine_ttft_ms_ci_half_width: float | None
    engine_tpot_ms_mean: float | None  # populated for chat_stream, None for embed
    engine_tpot_ms_ci_half_width: float | None
    engine_forward_ms_mean: float | None  # populated for embed, None for chat_stream
    engine_forward_ms_ci_half_width: float | None
    n_successes: int
    regression_warning: bool | None  # FR-015c — populated for embed only (echoes FR-015b)

@dataclass(frozen=True)
class BaselineSentinel:
    """Sentinel-object shape for `chat_stream_baseline_post_symmetrisation` and 
    `embed_baseline_post_symmetrisation` (round-2 Q1 / Q2). Always present in M6.1.1's JSON 
    even under non-Phase-2(a) outcomes — strict-superset compatibility per FR-022."""
    phase_2_path: Phase2Path  # echo of run_meta.phase_2_path
    baseline_source: BaselineSource  # "m6_1_1" | "m6_1" | "documented_in_contracts" | "not_applicable"
    pointer: str | None  # path to baseline file or contracts doc; None for "not_applicable"
    cells: list[BaselineCellEntry] | None  # 9 entries when baseline_source == "m6_1_1"; None otherwise
```

The same shape is used for both `chat_stream_baseline_post_symmetrisation` and `embed_baseline_post_symmetrisation`. The dispatch table per round-2 Q1 / Q2:

| `phase_2_path`                | `baseline_source`             | `pointer`                                              | `cells`           |
| :--                            | :--                            | :--                                                     | :--                |
| `phase_2a_verified`           | `m6_1_1`                      | `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` (self-reference) | 9 entries        |
| `phase_2b_documented`         | `m6_1` for chat_stream; `m6_1` for embed | `docs/benchmarks/m6_1-real-prompt-embeds.json`     | `None`           |
| `drift_not_reproduced_confirmed` | `m6_1`                      | `docs/benchmarks/m6_1-real-prompt-embeds.json`         | `None`           |
| `split_required`              | `not_applicable`              | `null`                                                 | `None`           |
| `phase_2_pending`             | `not_applicable`              | `null`                                                 | `None`           |

Under Phase 2(b) the `baseline_source` is `"m6_1"` — note that the documented-batching interpretation lives in `contracts/instrumentation.md` separately; the sentinel's `pointer` indicates the *numerical* baseline (still M6.1's), and consumers must additionally consult `contracts/instrumentation.md` for the per-cohort interpretation rule.

---

## Entity: `M6_1_1RunMeta`

```python
@dataclass(frozen=True)
class M6_1_1RunMeta:
    """Run-level metadata; mirrors M6.1's RunMeta shape (FR-021 strict-superset) plus M6.1.1 fields."""
    # M6.1 lineage
    git_sha: str
    hostname: str
    modal_function_id: str | None
    gpu_type: str
    modal_region: str
    model_identifier: str
    hidden_size: int  # 4096
    cold_start_s: float
    max_model_len: int  # 2048
    gpu_memory_utilization: float  # 0.92
    engine_version: str  # vllm==0.20.1
    m6_1_baseline_engine_version: str  # from m6_1-real-prompt-embeds.json:run_meta.engine_version
    torch_version: str  # 2.11.0
    # M6.1.1 additions
    M6_1_1_BASE_SEED: int  # =42 per FR-027
    seq_len: int  # pinned at sweep start; same value M6.1 pinned (reused from m6_1_seq_len)
    phase_1_n: int  # =50 per FR-005
    phase_2_path: Phase2Path
    run_started_at: str  # ISO8601 UTC (most recent run; first run's start is in phase_1_runs[0].run_started_at)
    run_completed_at: str
```

---

## Entity: `M6_1_1Run`

```python
@dataclass(frozen=True)
class M6_1_1Run:
    """Top-level container; one instance = one M6.1.1 instance."""
    schema_version: Literal["m6_1_1.v1"]
    run_id: str  # most-recent run's ID; matches run_meta.run_id
    run_started_at: str  # most-recent run
    run_completed_at: str
    run_meta: M6_1_1RunMeta
    # Phase 1 data
    phase_1_classifications: dict[str, Phase1Classification]  # most recent run's per-cell labels
    phase_1_runs: list[Phase1RunRecord]  # ordered (oldest first); accumulated across all --m6_1_1-diagnose invocations per round-3 Q1
    multi_point_timings: list[MultiPointTimings]  # most recent run only; for older runs see phase_1_runs[]
    # Phase 2 data
    phase_2_outcome: Phase2Outcome  # None when phase_2_path == "phase_2_pending"
    phase_2_choice: Phase2Choice | None  # operator path selection when applicable
    # Always-present sentinel sections per FR-022
    chat_stream_baseline_post_symmetrisation: BaselineSentinel
    embed_baseline_post_symmetrisation: BaselineSentinel
    embed_regression_check: EmbedRegressionCheckResult | None  # present only under phase_2_path == "phase_2a_verified"
    # Pointers
    m6_1_baseline_pointer: str  # path to m6_1-real-prompt-embeds.json
    methodology_supersedence: str  # one-line forward pointer text
```

---

## Entity: `Phase2Choice`

```python
@dataclass(frozen=True)
class Phase2Choice:
    """Operator's discretionary annotation when applicable (FR-017(b), FR-015b path (ii)).
    Records the rationale for non-default outcomes."""
    embed_regression_acknowledged: bool = False  # FR-015b path (ii)
    embed_regression_justification: str | None = None  # one sentence
    split_required_proposed_shape: str | None = None  # FR-017(b) ≤2 sentences
    split_required_operator_note: str | None = None
```

---

## Entity: `EmbedRegressionCheckResult`

```python
@dataclass(frozen=True)
class EmbedRegressionCheckResult:
    """Aggregated FR-015b check result; populated only under Phase 2(a)."""
    per_entry: list[EmbedRegressionResult]  # 9 entries (3 embed cells × 3 cohorts)
    n_warnings: int  # count of entries with embed_regression_warning == True
    all_within_tolerance: bool  # n_warnings == 0
    acknowledged_count: int  # count of entries with embed_regression_acknowledged == True
```

---

## Validation Rules

- **Determinism**: `classify_cell()` is a pure function (no I/O, no randomness). Unit-testable on synthetic inputs (test plan in [`/speckit-tasks`](./tasks.md) will cover all 4 outcome branches + edge cases like all-zero spreads, single-cohort outliers).
- **Schema strict-superset (FR-022)**: a Pydantic `model_validator` on `M6_1_1Run` asserts that every M6.1 top-level field is reachable (engine_cost_baseline section preserved under Phase 2(a); methodology_supersedence echoes M6.1's path).
- **Sentinel object always-present (round-2 Q1)**: both `chat_stream_baseline_post_symmetrisation` and `embed_baseline_post_symmetrisation` are required fields (not `Optional`) so JSON serialisation always includes them.
- **phase_2_path / phase_2_outcome consistency**: a validator asserts `Phase2aVerifiedOutcome` is only constructible when `phase_2_path == "phase_2a_verified"`, etc.
- **phase_1_runs[] append-only**: the constructor for `M6_1_1Run` enforces that `phase_1_runs` is a non-empty list (M6.1.1 cannot publish a report without at least one Phase 1 run).
- **Embed regression tolerance** (FR-015b): an `EmbedRegressionResult.embed_regression_warning` is `True` iff `abs(delta_pct) > 0.05`; the report's executive summary surfaces `n_warnings` from `EmbedRegressionCheckResult` per FR-015b.

---

## State Transitions

```text
                            ┌──────────────────┐
                            │ (no M6.1.1 file) │
                            └────────┬─────────┘
                                     │ --m6_1_1-diagnose (first run)
                                     ▼
                       ┌─────────────────────────────┐
                       │ phase_2_path = phase_2_pending │
                       │ phase_1_runs[] = [run_0]      │
                       └────┬────────────┬────────┬───┘
                            │            │        │
                            │ class:     │        │ class: any other
                            │ uniform    │        │ (mixed / inconclusive / drift_not_reproduced)
                            │ instr_     │        │ → exit code 3
                            │ artifact   │        │
                            │            │        ▼
                            │            │  ┌────────────────────────────────┐
                            │            │  │ operator runs --m6_1_1-diagnose │
                            │            │  │ again → phase_1_runs[] grows   │
                            │            │  └─────────┬──────────────────────┘
                            │            │            │
                            │            │            │  uniform after run 2 → loop back to class branches
                            │            │            │  still divergent → exit 5, phase_2_path = split_required
                            │            │            │  uniform drift_not_reproduced → phase_2_path = drift_not_reproduced_confirmed
                            │            │            ▼
                            ▼            ▼     (transitions per class)
              ┌──────────────────┐  ┌──────────────────────────┐
              │ operator applies │  │ class: uniform channel_  │
              │ symmetrisation   │  │ dependent_batching       │
              │ + runs --m6_1_1  │  └──────────┬───────────────┘
              │ → n=100 sweep   │             │
              │ + embed reg chk  │             │ operator updates contracts/instrumentation.md
              │ + fresh baselines│             │ + runs --m6_1_1
              └────────┬─────────┘             │ → validates contracts heading
                       │                       │ → no Modal sweep
                       │ Phase 2(a)            ▼
                       ▼                ┌─────────────────────────┐
            ┌──────────────────────┐    │ phase_2_path =          │
            │ phase_2_path =       │    │ phase_2b_documented     │
            │ phase_2a_verified    │    └─────────────────────────┘
            └──────────────────────┘
```

Terminal states: `phase_2a_verified`, `phase_2b_documented`, `drift_not_reproduced_confirmed`, `split_required`. `phase_2_pending` is transient (single-run Phase 1, awaiting Phase 2). Three round-trip transitions on multiple re-runs of `--m6_1_1-diagnose` per FR-017 / FR-018.
