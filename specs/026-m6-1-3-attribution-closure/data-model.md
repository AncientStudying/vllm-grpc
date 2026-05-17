# Phase 1 Data Model: M6.1.3 — Phase 1 Attribution Closure

**Branch**: `026-m6-1-3-attribution-closure` | **Date**: 2026-05-17 | **Plan**: [plan.md](./plan.md)

## Overview

M6.1.3 adds (a) 4 new wire keys (2 proxy-edge `m6_1_1_*` + 2 audit `m6_1_3_*`), (b) 2 new per-RPC derived segments (`seg_ingress_ms`, `seg_egress_ms`), (c) 1 new top-level artifact field (`between_run_variance`), (d) a 7-bucket classifier extension plus compound-label vocabulary, and (e) the new outer-override label `inconclusive_high_variance`. Every addition is a **strict-superset** schema evolution per FR-010 round-3 Q1 — pre-M6.1.3 readers ignore the unknown keys without parse error and `schema_version` stays at `"m6_1_1.v1"`.

Module-level dataclasses live across 8 new files under `tools/benchmark/src/vllm_grpc_bench/` (plus the cross-milestone `symmetric_prompts.py`). The wire format is documented separately in [`contracts/wire-vocabulary.md`](./contracts/wire-vocabulary.md); the classifier vocabulary in [`contracts/classifier.md`](./contracts/classifier.md); the artifact schema (validate / canonical / Phase B publishing scheme) in [`contracts/artifact-schema.md`](./contracts/artifact-schema.md); the CLI surface in [`contracts/cli.md`](./contracts/cli.md).

## Python Dataclasses (in `m6_1_3_types.py`)

### `M6_1_3SweepMode`

```python
M6_1_3SweepMode = Literal["full", "validate"]
```

**Relationship**: recorded in `M6_1_3SweepArtifact.run_meta.sweep_mode`. `"full"` for `--m6_1_3` (multi-run publish or single-run Phase B with `--m6_1_3-diagnose-repeat=1 --m6_1_3-diagnose-n=200`); `"validate"` for `--m6_1_3-validate`. Mirrors M6.1.2's `sweep_mode` literal pattern.

### `M6_1_3ClassifierLabel` (the 7-bucket extension + outer override + compound space)

```python
M6_1_3BaseLabel = Literal[
    # Inherited 5 from M6.1.1 (FR-008's "preserved unchanged" set)
    "channel_dependent_batching",
    "queue_dependent_batching",
    "engine_compute_variation",
    "frontend_arrival_jitter",       # Dormant per round-4 Q1; never fires as primary attribution
    "inconclusive",
    # NEW 2 from M6.1.3 (FR-008)
    "proxy_ingress_dominated",
    "proxy_egress_dominated",
]

M6_1_3OuterLabel = Literal["inconclusive_high_variance"]

# Compound labels: multi_factor_<top>_<runner_up> where top/runner_up are
# drawn from the 6 abbreviated identifiers per FR-008a (frontend_arrival
# is dormant; never appears in compounds per round-4 Q1 — so the practical
# compound space is 5×5=25 - 5 self-pairs - asymmetric pairs that violate
# alphabetical ordering, leaving 10 valid compound labels).
M6_1_3AbbreviatedIdentifier = Literal[
    "channel_batching",   # → seg_ab_ms
    "queue_batching",     # → seg_queue_ms
    "engine_compute",     # → seg_prefill_ms
    "proxy_ingress",      # → seg_ingress_ms
    "proxy_egress",       # → seg_egress_ms
    # NOTE: frontend_arrival is intentionally omitted (dormant per round-4 Q1)
]

# The 10 valid compound labels (alphabetical pairs from the 5 active identifiers):
M6_1_3CompoundLabel = Literal[
    "multi_factor_channel_batching_engine_compute",
    "multi_factor_channel_batching_proxy_egress",
    "multi_factor_channel_batching_proxy_ingress",
    "multi_factor_channel_batching_queue_batching",
    "multi_factor_engine_compute_proxy_egress",
    "multi_factor_engine_compute_proxy_ingress",
    "multi_factor_engine_compute_queue_batching",
    "multi_factor_proxy_egress_proxy_ingress",
    "multi_factor_proxy_egress_queue_batching",
    "multi_factor_proxy_ingress_queue_batching",
]

# The full per-cell label space:
M6_1_3PrimaryLabel = M6_1_3BaseLabel | M6_1_3CompoundLabel
# When `inconclusive_high_variance` outer override fires, the primary label
# is rendered as a parenthetical alongside the outer label.
```

**Vocabulary mapping** (canonical per FR-008a + round-2 Q2; documented in `contracts/instrumentation.md` per FR-011):

| Classifier base label | Abbreviated identifier | Driving segment field |
|---|---|---|
| `channel_dependent_batching` | `channel_batching` | `seg_ab_ms` |
| `queue_dependent_batching` | `queue_batching` | `seg_queue_ms` |
| `engine_compute_variation` | `engine_compute` | `seg_prefill_ms` |
| `frontend_arrival_jitter` | `frontend_arrival` | `seg_arrival_ms` (dormant in M6.1.3 per round-4 Q1) |
| `proxy_ingress_dominated` | `proxy_ingress` | `seg_ingress_ms` |
| `proxy_egress_dominated` | `proxy_egress` | `seg_egress_ms` |

### `M6_1_3TimingCheckpointExtension`

```python
@dataclass
class M6_1_3TimingCheckpointExtension:
    """Net new fields populated by m6_1_1_timing.py's extractor when M6.1.3
    wire keys are present. Optional — absent on pre-M6.1.3 manifests; absent
    on unary RPC rows for the proxy-edge fields (FR-003 streaming-only)."""

    # Proxy-edge probes (FR-001 + FR-002; streaming-only per FR-003)
    pre_engine_wall_ns: int | None = None       # from m6_1_1_t_pre_engine_wall_ns
    first_chunk_mono_ns: int | None = None      # from m6_1_1_t_first_chunk_mono_ns

    # Prompt-content audit (FR-012 + FR-013; both streaming and unary per FR-014)
    tokenized_prompt_length: int | None = None  # from m6_1_3_tokenized_prompt_length
    tokenized_prompt_hash: str | None = None    # from m6_1_3_tokenized_prompt_hash
```

**Relationship**: extends M6.1.1's `TimingCheckpoint` dataclass (in `m6_1_1_timing.py`) with 4 optional fields. The existing M6.1.1 fields are unchanged. The new derived segments `seg_ingress_ms` / `seg_egress_ms` are computed by the aggregator (`m6_1_3_classifier.py` or the aggregation path) from `pre_engine_wall_ns` / `first_chunk_mono_ns` plus the existing M6.1.1 `engine_arrival_ns` / `engine_first_token_ns`.

### `M6_1_3PerSegmentDeltaExtension`

```python
@dataclass
class M6_1_3PerSegmentDeltaExtension:
    """Net new optional fields on PerSegmentDelta when the proxy-edge probes
    are present. Computed per RPC from the proxy-edge anchors + vLLM's
    RequestStateStats timestamps."""

    seg_ingress_ms: float | None = None
    seg_egress_ms: float | None = None
    is_clock_anomaly: bool = False  # Set True when FR-006 negative-value assertion fires
```

**Validation** (FR-006):
- `seg_ingress_ms ≥ 0` and `seg_egress_ms ≥ 0` on every per-RPC row. If either is negative, `is_clock_anomaly` is set to True and the offending raw `_ns` values are logged. The row is excluded from per-cell aggregation.
- If more than the configurable fraction of RPCs in a cell are clock anomalies (default `/speckit-plan` deliverable), the cell receives a `clock_anomaly` per-cell warning AND the classifier downgrades the cell's verdict to `inconclusive`.

### `M6_1_3PerSegmentAggregateExtension`

```python
@dataclass
class M6_1_3PerSegmentAggregateExtension:
    """Net new fields on PerSegmentAggregate. Per-cohort means / stddevs /
    CI half-widths for the new segments, using the SAME statistical recipe
    as the inherited segments (FR-007 — no new aggregation primitive)."""

    seg_ingress_ms: PerSegmentStat | None = None  # mean, stddev, CI half-width
    seg_egress_ms: PerSegmentStat | None = None
    clock_anomaly_fraction: float = 0.0  # Fraction of per-RPC rows where is_clock_anomaly was True
    clock_anomaly_warning: bool = False  # True when clock_anomaly_fraction exceeds the configurable threshold
```

**SegmentName Literal extension** (FR-005):
```python
SegmentName = Literal[
    # Inherited M6.1.1 segment names
    "seg_ab", "seg_queue", "seg_prefill", "seg_arrival",
    # NEW M6.1.3 (FR-005)
    "seg_ingress", "seg_egress",
]
```

### `M6_1_3BetweenRunVariance`

```python
@dataclass
class M6_1_3BetweenRunVarianceCell:
    """Per cell × cohort between-run variance estimate from
    compute_between_run_variance per FR-024."""

    mean_of_means_ms: float | None       # Mean across runs of per-run per-cohort engine_ttft_ms means
    stddev_of_means_ms: float | None     # Standard deviation across runs of those per-run means
    n_runs: int                          # Count of runs that contributed (excludes failed-cohort runs)

# Top-level artifact field shape:
M6_1_3BetweenRunVariance = dict[
    str,                                 # Cell ID (e.g., "chat_stream_c4")
    dict[
        M6_1_2CohortKind,                # Cohort name (inherited literal from m6_1_2_types.py)
        M6_1_3BetweenRunVarianceCell,
    ],
]
```

**Reporter rendering**: a "Between-Run Variance" markdown section renders only when `len(phase_1_runs) >= 3` per FR-025. For shorter accumulators (single-run validate, or operator override `--m6_1_3-diagnose-repeat=2`), the section is omitted entirely.

**Cohort-unhealthy handling** (FR-027): if a cohort produces no successful RPCs in one of the runs, the variance compute drops that run's contribution for the cohort × cell only; `n_runs` is decremented accordingly. If a cohort fails in 3+ of the 5 runs for the same cell, the compute emits `null` for `mean_of_means_ms` / `stddev_of_means_ms` and the classifier emits a `cohort_unhealthy` warning.

### `M6_1_3PerRunAuditVerdict` + `M6_1_3PerCellAuditAggregate`

```python
M6_1_3AuditVerdictLine = Literal[
    "H1 confirmed: per-cohort token-count means diverge by >2σ",
    "H1 rejected: per-cohort distributions statistically identical",
    "H2 candidate: token-counts identical but hash distributions differ",
]

@dataclass
class M6_1_3PerCohortAuditDistribution:
    """Per-cohort distribution of audit fields for a single cell, pooled
    across all runs in phase_1_runs[]."""

    mean_tokenized_prompt_length: float
    stddev_tokenized_prompt_length: float
    n_rpcs: int                              # Pooled n: N_runs × n_per_run per cohort
    unique_hash_count: int                   # Distinct tokenized_prompt_hash values seen
    hash_distribution: dict[str, int]        # hash → count (for H2 candidate detection)

@dataclass
class M6_1_3PerCellAuditAggregate:
    """Per-cell pooled-distribution audit aggregate per FR-016 + round-1 Q5."""

    cell_id: str
    per_cohort: dict[M6_1_2CohortKind, M6_1_3PerCohortAuditDistribution]
    pooled_verdict: M6_1_3AuditVerdictLine

@dataclass
class M6_1_3PerRunAuditVerdict:
    """Per-run, per-cell audit verdict for the FR-016a conditional appendix
    (round-2 Q5). Computed from a single run's per-RPC sidecar rows."""

    run_idx: int                             # 0-indexed position in phase_1_runs[]
    cell_id: str
    verdict: M6_1_3AuditVerdictLine
```

**Pooled-distribution semantics** (FR-016 + round-1 Q5):
- The per-cohort distribution is computed by concatenating all per-RPC audit rows across all runs in `phase_1_runs[]`. For the canonical publish sweep (`--m6_1_3` at `repeat=5`, `n=50`), `n_rpcs == 5 × 50 == 250` per cohort. For the validate sweep (`--m6_1_3-validate` at `repeat=1`, `n=50`), `n_rpcs == 50` per cohort.
- The pooled verdict is computed once from the pooled distribution; it is the single load-bearing output (drives FR-017 / FR-018 spec recommendations).
- Per-run verdicts are computed separately for the conditional appendix per FR-016a + round-2 Q5: the appendix MUST render whenever any per-run verdict differs from the pooled verdict for any cell ("differs" = byte-non-identical label string per cell).

### `M6_1_3PhaseBTriggerVerdict`

```python
@dataclass
class M6_1_3PhaseBTriggerVerdict:
    """The verdict line emitted by the Phase A publish-run reporter at the
    end of the 'Between-Run Variance' section per FR-044 + round-2 Q3."""

    required: bool                           # True when at least one cell carries inconclusive_high_variance
    trigger_cells: list[str]                 # Cell IDs where the unified high-variance threshold fired
    variance_section_suppressed: bool        # True when len(phase_1_runs) < 3 (FR-025 suppression)
```

**Rendering** (FR-044):
- When `variance_section_suppressed == False` AND `required == True`:
  `"Phase B required: chat_stream_c4, chat_stream_c8"` (alphabetically sorted cell IDs).
- When `variance_section_suppressed == False` AND `required == False`:
  `"Phase B not required"`.
- When `variance_section_suppressed == True` (operator override `--m6_1_3-diagnose-repeat < 3`):
  `"Phase B trigger verdict unavailable (requires --m6_1_3-diagnose-repeat >= 3 for between-run variance compute)"` — rendered at the end of the per-cell timing table instead of the suppressed variance section.

### `M6_1_3SweepArtifact` (top-level entity)

```python
@dataclass
class M6_1_3SweepArtifact:
    # === M6.1.1 + M6.1.2-inherited top-level keys (preserved verbatim) ===
    schema_version: Literal["m6_1_1.v1"]            # NO BUMP per FR-010 round-3 Q1
    dispatch_mode: Literal["concurrent"]             # From M6.0a; M6.1.3 inherits
    run_id: str
    run_started_at: str
    run_completed_at: str
    run_meta: dict                                   # Extends M6.1.2's run_meta with sweep_mode literal
    phase_1_classifications: dict
    phase_1_runs: list[dict]                         # 5 entries on the publish sweep at repeat=5
    multi_point_timings: dict
    phase_2_outcome: dict | None
    phase_2_choice: str | None
    chat_stream_baseline_post_symmetrisation: dict
    embed_baseline_post_symmetrisation: dict
    embed_regression_check: dict | None
    m6_1_baseline_pointer: str
    methodology_supersedence: dict
    classifier_notes: list[str]
    network_paths: dict                              # M6.1.2-inherited per FR-032
    cohort_set: list[str]                            # M6.1.2-inherited per FR-032
    cohort_omissions: dict[str, str] | None          # M6.1.2-inherited per FR-032 (None / absent OK)

    # === M6.1.3 NEW top-level fields (strict-superset addition per FR-010) ===
    between_run_variance: M6_1_3BetweenRunVariance | None  # None for single-run sweeps
```

**Strict-superset evolution** (FR-010 + round-3 Q1): an M6.1.1-vintage or M6.1.2-vintage reader parses this artifact, ignoring the `between_run_variance` top-level key + the new per-cell segment columns + the new audit fields. The integration test `test_m6_1_3_artifact_schema.py` exercises this for all three M6.1.3 artifacts (validate / canonical / Phase B).

## Module Surface Map

The 8 new files under `tools/benchmark/src/vllm_grpc_bench/`, with their entity roles:

| File | Entity / Function | Notes |
|------|-------------------|-------|
| `m6_1_3_types.py` | `M6_1_3SweepMode`, `M6_1_3BaseLabel`, `M6_1_3OuterLabel`, `M6_1_3AbbreviatedIdentifier`, `M6_1_3CompoundLabel`, `M6_1_3PrimaryLabel`, `M6_1_3TimingCheckpointExtension`, `M6_1_3PerSegmentDeltaExtension`, `M6_1_3PerSegmentAggregateExtension`, `M6_1_3BetweenRunVariance`, `M6_1_3BetweenRunVarianceCell`, `M6_1_3AuditVerdictLine`, `M6_1_3PerCohortAuditDistribution`, `M6_1_3PerCellAuditAggregate`, `M6_1_3PerRunAuditVerdict`, `M6_1_3PhaseBTriggerVerdict`, `M6_1_3SweepArtifact` | All shared dataclasses + literals live here. Mirrors `m6_1_2_types.py`'s role. |
| `m6_1_3_sweep.py` | `run_m6_1_3_sweep(...)`, `_stderr_ts()`, `_measure_cell_m6_1_3(...)`, `_run_phase1_with_preemption_retry(...)` | Sweep orchestrator. Inherits M6.0a-corrected concurrent dispatch + M6.1.2 4-cohort iteration + M6.1.2 network_paths probe. NEW: multi-run loop per FR-022 with preemption-aware URL refresh per FR-028 (pinned threshold > 2). Calls `m6_1_3_audit.compute_pooled_verdict(...)` and `m6_1_3_variance.compute_between_run_variance(...)` after all runs complete. |
| `m6_1_3_classifier.py` | `classify_m6_1_3(per_segment_aggregate, between_run_variance)`, `pick_dominant_label(...)`, `pick_compound_label(...)`, `apply_outer_override(...)` | Extends M6.1.1's 5-bucket tree to 7 buckets (FR-008) with FR-008a tie-breaking rules. Legacy fallback to M6.1.1's 5-bucket classifier when `seg_ingress_ms` / `seg_egress_ms` are absent on a rehydrated manifest. Enforces `frontend_arrival_jitter` dormancy per round-4 Q1. |
| `m6_1_3_audit.py` | `compute_pooled_verdict(phase_1_runs)`, `compute_per_run_verdicts(phase_1_runs)`, `should_render_audit_appendix(pooled, per_run)`, `extract_h1_recommendation(pooled)` | Pooled audit aggregation per FR-016 + round-1 Q5. Per-run verdict + appendix-conditional rendering per FR-016a + round-2 Q5. H1 / H2 / rejection criterion logic. FR-017 / FR-018 spec-decision recommendation extraction. |
| `m6_1_3_variance.py` | `compute_between_run_variance(phase_1_runs)`, `compute_phase_b_trigger(variance, cell_ci_halfwidths, threshold)`, `should_render_variance_section(phase_1_runs)` | Between-run variance compute per FR-024. Unified high-variance threshold check per FR-026 + FR-043 + round-2 Q3. Phase B trigger verdict generation per FR-044. FR-027 cohort-unhealthy handling. |
| `m6_1_3_reporter.py` | `render_json(...)`, `render_markdown(...)`, `write_m6_1_3_report(...)`, `_render_audit_section(...)`, `_render_variance_section(...)`, `_render_compound_label_narrative(...)`, `_render_identifier_legend(...)` | Mirrors `m6_1_2_reporter.py`. Adds: seg_ingress + seg_egress per-cell columns; classification narratives for the 2 new proxy_*_dominated labels; compound-label narrative with abbreviated identifiers + per-segment shares (round-2 Q2); one-line identifier legend at start of classifier section (FR-009a + round-2 Q2); per-cell pooled-distribution audit section + H1 verdict line (FR-016); conditional per-run audit appendix (FR-016a + round-2 Q5); spec-decision recommendation block (FR-017 / FR-018); between-run variance section (FR-025); Phase B trigger verdict line with FR-044 override fallback. Three-path output routing per FR-038 + round-2 Q1. |
| `m6_1_3_validate.py` | `run_m6_1_3(args, *, sweep_mode: M6_1_3SweepMode)` | Single CLI entry function for both `--m6_1_3` and `--m6_1_3-validate` per round-2 Q2 (matches M6.1.2 pattern). Mode-inferred output path per FR-038 + R-7. Records `sweep_mode` in `run_meta.sweep_mode` artifact metadata. |
| `symmetric_prompts.py` | `assign_symmetric_prompt(iter_idx, cohort, corpus)`, `validate_symmetric_invariant(per_cohort_distributions)` | Cross-milestone shared helper per FR-019 + round-2 Q4. Imported by `m6_1_3_sweep.py` when `--m6_1_3-symmetric-prompts` is set AND by `m5_2_sweep.py` (back-compat). Per R-6: M5.2 back-compat via re-export shim at `m5_2_symmetry.py` (zero-cost; `from .symmetric_prompts import *  # noqa: F401, F403`). |

## Modified Files (existing)

| File | Change | Notes |
|------|--------|-------|
| `packages/frontend/src/vllm_grpc_frontend/chat.py:CompleteStream` | Add 4 wire keys to trailing metadata | 2 proxy-edge (`m6_1_1_t_pre_engine_wall_ns`, `m6_1_1_t_first_chunk_mono_ns`) + 2 audit (`m6_1_3_tokenized_prompt_length`, `m6_1_3_tokenized_prompt_hash`). Capture sites: alongside existing `pre_engine_ns` and `first_chunk_ns` captures (proxy-edge), and post-`messages_to_prompt` / `apply_chat_template` resolution (audit). ~25-40 LOC. |
| `packages/frontend/src/vllm_grpc_frontend/completions.py:CompleteStream` | Same 4-key emission as chat.py | ~25-40 LOC. |
| `packages/frontend/src/vllm_grpc_frontend/completions.py:Complete` | Add 2 audit keys only (FR-014 both-RPC-kinds) | Unary RPC; no proxy-edge keys per FR-003. ~15-20 LOC. |
| `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` | REST SSE / JSON terminal-event handler reads 4 new keys | Mirrors the gRPC trailing-metadata read in the timing.py extractor. ~15-25 LOC. |
| `tools/benchmark/src/vllm_grpc_bench/m6_1_1_timing.py` | Extractor populates new TimingCheckpoint optional fields | Uses existing `_opt_int` / `_opt_str` patterns. ~10-20 LOC. |
| `tools/benchmark/src/vllm_grpc_bench/__main__.py` | Add `--m6_1_3` + `--m6_1_3-validate` + 3 modifier flags + 11 namespaced sub-flags | Mirrors M6.1.2's argparse pattern. Mutual-exclusion list per FR-034. Verbatim-inheritance defaults per FR-036. ~120-180 LOC. |
| `tools/benchmark/src/vllm_grpc_bench/m5_2_symmetry.py` | Convert to re-export shim per R-6 | One-line `from .symmetric_prompts import *  # noqa: F401, F403`. Existing in-tree symmetry logic moved verbatim to `symmetric_prompts.py`. |
| `docs/benchmarks/m6_1_1-engine-cost-instrumentation.md` | Single leading note line per FR-031 + round-3 Q2 | Exact text: `> **Note**: This milestone's c=4 / c=8 verdicts were updated by [M6.1.3](m6_1_3-attribution-closure.md). See that artifact for attributed labels and Phase B variance characterization.` Placement above the existing H1 title. No other body mutation. |
| `contracts/instrumentation.md` | Extend with M6.1.3 wire vocabulary + classifier extension + new labels + versioning convention | Per FR-011 + SC-010 + round-3 Q1. Sections added: (a) 4 new wire keys (2 `m6_1_1_*` proxy-edge + 2 `m6_1_3_*` audit), (b) 2 new derived segments, (c) 7-bucket classifier + canonical mapping table, (d) compound-label vocabulary + 5pp dominance margin, (e) inconclusive_high_variance outer override, (f) between_run_variance top-level block, (g) frontend_arrival_jitter dormancy note, (h) additive-strict-superset versioning convention. |
| `CLAUDE.md` | Update SPECKIT plan reference between markers | Phase 1 step 3 of `/speckit-plan`. Path: `specs/026-m6-1-3-attribution-closure/plan.md`. |

## Sweep Orchestration Semantics (detailed)

The sweep orchestrator in `m6_1_3_sweep.py` runs the multi-run loop as follows:

```python
async def run_m6_1_3_sweep(config: M6_1_3Config) -> M6_1_3SweepArtifact:
    # Step 1: Modal deploy + handshake (reuses M6.1.1's + M6.1.2's pattern)
    handshake = await deploy_and_handshake(config)

    # Step 2: Topology probe — ONCE at first run start per FR-030 (M6.1.2 inheritance)
    # Parallel across cohorts, 30s per-cohort timeout
    network_paths = await run_topology_probe(
        handshake_dict=handshake,
        cohorts=M6_1_2_COHORTS,                  # Inherited 4-cohort set per FR-032
        per_cohort_timeout_seconds=30,
    )

    # Step 3: Multi-run loop per FR-022
    phase_1_runs = []
    preemption_count = 0
    for run_idx in range(config.repeat):         # config.repeat from --m6_1_3-diagnose-repeat (default 5 under --m6_1_3, 1 under --m6_1_3-validate)
        try:
            run_result = await _run_phase1_once(
                config=config,
                handshake=handshake,
                run_idx=run_idx,
                network_paths_for_run=network_paths,  # Same network_paths for every run per FR-030
            )
            phase_1_runs.append(run_result)
        except ModalTunnelPreemption as exc:
            # FR-028 preemption-aware refresh
            preemption_count += 1
            if preemption_count > 2:             # FR-028 pinned-at-2 threshold per round-3 Q3
                # Abort remaining runs; reporter will emit "multi-run incomplete" warning
                break
            handshake = await refresh_modal_urls(handshake, exc)
            phase_1_runs.append(_partial_result_with_preemption_note(run_idx, exc))

    # Step 4: Cross-run computations
    pooled_audit_verdicts = m6_1_3_audit.compute_pooled_verdict(phase_1_runs)
    per_run_audit_verdicts = m6_1_3_audit.compute_per_run_verdicts(phase_1_runs)
    between_run_variance = (
        m6_1_3_variance.compute_between_run_variance(phase_1_runs)
        if len(phase_1_runs) >= 3 else None        # FR-025 suppression
    )
    phase_b_trigger = m6_1_3_variance.compute_phase_b_trigger(
        between_run_variance=between_run_variance,
        cell_ci_halfwidths=_extract_ci_halfwidths(phase_1_runs),
        threshold=config.high_variance_threshold,  # FR-026 unified threshold (default /speckit-plan deliverable)
    )

    # Step 5: Classifier — per cell, with the 7-bucket extension + outer override
    classifications = {}
    for cell in M6_1_CELLS:                       # Reused from m6_1_types.py:72-82
        per_segment_agg = _aggregate_across_runs(phase_1_runs, cell)
        cell_variance = between_run_variance.get(cell.id) if between_run_variance else None
        classifications[cell.id] = m6_1_3_classifier.classify_m6_1_3(
            per_segment_agg, cell_variance, config.classifier_thresholds,
        )

    # Step 6: Reporter writes the artifact
    artifact = build_artifact(
        phase_1_runs=phase_1_runs,
        network_paths=network_paths,
        cohort_set=sorted(M6_1_2_COHORTS),
        cohort_omissions=None,                     # M6.1.3 default: no intentional omissions
        between_run_variance=between_run_variance,
        classifications=classifications,
        pooled_audit_verdicts=pooled_audit_verdicts,
        per_run_audit_verdicts=per_run_audit_verdicts,
        phase_b_trigger=phase_b_trigger,
        sweep_mode=config.sweep_mode,              # Recorded in run_meta.sweep_mode
    )
    return artifact
```

## Cross-references

- Spec: [`spec.md`](./spec.md) — FR-001 through FR-045 + 13 SCs + 18 Clarifications.
- Plan: [`plan.md`](./plan.md) — Technical Context + Constitution Check + Project Structure.
- Phase 0 research: [`research.md`](./research.md) — R-1 through R-10 inform every dataclass shape above.
- CLI contract: [`contracts/cli.md`](./contracts/cli.md) — flag names, defaults, mutual exclusion, output-path inference.
- Wire-vocabulary contract: [`contracts/wire-vocabulary.md`](./contracts/wire-vocabulary.md) — 4 new wire keys + extractor mapping + additive-strict-superset versioning convention.
- Classifier contract: [`contracts/classifier.md`](./contracts/classifier.md) — 7-bucket decision tree, FR-008a tie-breaking, compound-label vocabulary, `inconclusive_high_variance` outer override, dormancy note.
- Artifact-schema contract: [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) — `between_run_variance` block, three-path publishing scheme, per-run audit appendix conditional rendering, Phase B trigger verdict line, M6.1.1 forward-pointing annotation contract.
- M6.1.2 reference: `tools/benchmark/src/vllm_grpc_bench/m6_1_2_types.py` (M6_1_2_COHORTS reused), `m6_1_2_sweep.py` (cohorts_at_concurrency reused), `m6_1_2_reporter.py` (M6.1.3's reporter mirrors this).
- M6.1.1 reference: `tools/benchmark/src/vllm_grpc_bench/m6_1_types.py:72-82` (M6_1_CELLS reused), `m6_1_1_classifier.py` (M6.1.3's classifier extends the 5-bucket tree), `m6_1_1_timing.py` (extractor extended).
- vLLM source: `vllm/v1/engine/__init__.py:149-153` (monotonic-clock source); `vllm/v1/metrics/stats.py:202-217` (RequestStateStats field clock sources).
