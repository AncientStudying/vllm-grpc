# Contract: M6.1.3 Classifier Extension

**Branch**: `026-m6-1-3-attribution-closure` | **Phase 1 output** | **Plan**: [../plan.md](../plan.md)

## Purpose

M6.1.3 extends M6.1.1's 5-bucket classifier decision tree to **7 buckets** (FR-008) and adds:
- A **compound-label vocabulary** for near-tie cells with FR-008a's highest-share-wins-with-5pp-margin rule.
- An **outer-override label** `inconclusive_high_variance` (FR-026) driven by the unified high-variance threshold (FR-026 + FR-043 + round-2 Q3).
- A **dormancy note** for `frontend_arrival_jitter` (round-4 Q1): the label stays in the inherited 5-bucket fallback for legacy compatibility but never fires as a primary attribution in the 7-bucket tree and never appears inside a compound label.

The classifier lives in `m6_1_3_classifier.py` (new module per R-1). M6.1.1's `m6_1_1_classifier.py` is UNCHANGED per FR-037 — historical `--m6_1_1-diagnose` invocations stay frozen.

## The 7 base labels

| Label | Driving segment | Description |
|---|---|---|
| `channel_dependent_batching` | `seg_ab_ms` | Inherited from M6.1.1. The per-cohort spread lives in the auxiliary batching segment — typically channel-config dependent. |
| `queue_dependent_batching` | `seg_queue_ms` | Inherited from M6.1.1. Spread lives in the engine-side queue wait segment. |
| `engine_compute_variation` | `seg_prefill_ms` | Inherited from M6.1.1. Spread lives in the post-schedule engine prefill compute segment. |
| `frontend_arrival_jitter` | `seg_arrival_ms` (DORMANT in M6.1.3 per round-4 Q1) | Inherited from M6.1.1 but **dormant**: never fires as primary attribution in M6.1.3's 7-bucket tree; remains in the 5-bucket fallback for legacy-manifest rehydration. |
| `inconclusive` | n/a | Inherited from M6.1.1. Fired when no segment carries sufficient dominance share OR when `clock_anomaly_fraction` exceeds the configurable cell-level threshold per FR-006. |
| `proxy_ingress_dominated` | `seg_ingress_ms` | **NEW (FR-008)**. The unattributed budget lived in the proxy → engine handoff (`pre_engine_wall_ns` → `arrival_time`). |
| `proxy_egress_dominated` | `seg_egress_ms` | **NEW (FR-008)**. The unattributed budget lived in the engine → proxy yield (`first_token_ts` → `first_chunk_mono_ns`). |

## Canonical mapping table (load-bearing vocabulary)

Per FR-008a + round-2 Q2, this 6-row table is the canonical vocabulary for compound labels. Documented in `contracts/instrumentation.md` per FR-011; inherited unchanged by M6.2 / M7 / M8.

| Classifier base label | Abbreviated identifier (used in `multi_factor_*`) | Driving segment field |
|---|---|---|
| `channel_dependent_batching` | `channel_batching` | `seg_ab_ms` |
| `queue_dependent_batching` | `queue_batching` | `seg_queue_ms` |
| `engine_compute_variation` | `engine_compute` | `seg_prefill_ms` |
| `frontend_arrival_jitter` | `frontend_arrival` | `seg_arrival_ms` (dormant in M6.1.3 per round-4 Q1) |
| `proxy_ingress_dominated` | `proxy_ingress` | `seg_ingress_ms` |
| `proxy_egress_dominated` | `proxy_egress` | `seg_egress_ms` |

The `inconclusive` label and `inconclusive_high_variance` outer label are NOT compound-mappable — they MUST NOT appear inside a `multi_factor_*` token.

## The compound-label tie-breaking rule (FR-008a + round-1 Q4)

When **two or more** attribution labels clear their per-rule dominance thresholds for the same cell, the classifier applies **highest-share-wins precedence with a 5-percentage-point dominance margin**:

1. Compute each label's driving-segment share as a fraction of total `engine_ttft_ms` spread.
2. If the top-share label exceeds the runner-up by ≥ 5 percentage points → emit the top label as a single primary label.
3. Otherwise (within 5pp) → emit a compound label `multi_factor_<top>_<runner_up>` where `<top>` and `<runner_up>` are the abbreviated identifiers from the canonical mapping, **sorted alphabetically** per FR-008a + R-8.

**Per-rule dominance thresholds**: each base label has a minimum-share gate (e.g., `~40%` of total `engine_ttft_ms` spread per FR-008's spike-suggested starting point for `proxy_*_dominated`). The exact thresholds for each of the 6 active driving-segment identifiers are `/speckit-plan` deliverables (4 of the 5 remaining configurable knobs). The compound-label rule fires only when **two or more** labels clear their gates simultaneously — if only one label clears, it wins outright regardless of the share.

**`inconclusive` collision rule** (FR-008a tail clause): if one of the top two candidates is `inconclusive`, the cell collapses to the other candidate's single label (no compound formed; the `inconclusive` label is not compound-mappable per the dormancy note above).

### Alphabetical ordering implementation

Per R-8, the compound label uses `sorted([top_id, runner_up_id])` to produce a canonical form:

```python
def make_compound_label(top_id: str, runner_up_id: str) -> str:
    """Produce the canonical multi_factor_<a>_<b> label with alphabetical
    ordering per FR-008a + R-8."""
    sorted_pair = sorted([top_id, runner_up_id])
    return f"multi_factor_{sorted_pair[0]}_{sorted_pair[1]}"
```

**Example near-ties**:
- Top: `proxy_egress` at 45% spread; runner-up: `engine_compute` at 43% spread (gap 2pp < 5pp margin) → compound `multi_factor_engine_compute_proxy_egress`.
- Top: `engine_compute` at 50% spread; runner-up: `proxy_egress` at 40% spread (gap 10pp ≥ 5pp margin) → single `engine_compute_variation` (the inherited base label, NOT the abbreviated identifier).
- Top: `seg_egress` at 45% but `inconclusive` is the runner-up at 43% (e.g., the cell would otherwise be `inconclusive` due to insufficient dominance everywhere) → `proxy_egress_dominated` single label (the `inconclusive` runner-up is collapsed per the tail clause).

## The `inconclusive_high_variance` outer-override label (FR-026 + round-2 Q3)

The outer-override label fires when the multi-run variance signal dominates attribution. Per the unified high-variance threshold (round-2 Q3):

```python
def should_fire_inconclusive_high_variance(
    cell_variance: M6_1_3BetweenRunVarianceCell,
    cell_ci_halfwidth_ms: float,
    threshold: float,
) -> bool:
    """FR-026 + FR-043 + round-2 Q3 unified threshold."""
    if cell_variance.stddev_of_means_ms is None:
        return False
    return cell_variance.stddev_of_means_ms > threshold * cell_ci_halfwidth_ms
```

When `inconclusive_high_variance` fires, it **overrides** the inner attribution label as the cell's headline verdict. The inner label (whatever the 7-bucket tree + compound-label logic produces) remains present in the per-cell row as a parenthetical so the published markdown carries both signals.

**Example outer-override**:
- Inner result: `engine_compute_variation` (cell at single-run interpretation).
- Cell variance: `stddev_of_means_ms` = 8.0; CI half-width = 4.0; unified threshold = 1.0 (so `8 > 1 × 4 = 4` fires).
- Final cell verdict: outer `inconclusive_high_variance`; inner `engine_compute_variation` as parenthetical.
- Reporter renders: `"inconclusive_high_variance (engine_compute_variation)"`.

## The Phase B trigger derivation (FR-043 + FR-044 + round-2 Q3)

Per round-2 Q3 unification, the Phase B publication requirement is **derived mechanically from the cell-label list**:

```python
def compute_phase_b_trigger(
    classifications: dict[str, M6_1_3PrimaryLabel],
    variance_section_suppressed: bool,
) -> M6_1_3PhaseBTriggerVerdict:
    """FR-043 + FR-044 + round-2 Q3."""
    if variance_section_suppressed:
        return M6_1_3PhaseBTriggerVerdict(
            required=False,
            trigger_cells=[],
            variance_section_suppressed=True,
        )
    trigger_cells = sorted([
        cell_id for cell_id, label in classifications.items()
        if label == "inconclusive_high_variance"
    ])
    return M6_1_3PhaseBTriggerVerdict(
        required=bool(trigger_cells),
        trigger_cells=trigger_cells,
        variance_section_suppressed=False,
    )
```

## The legacy fallback (FR-008 + FR-010)

When the proxy-edge segments (`seg_ingress_ms`, `seg_egress_ms`) are absent — i.e., when a pre-M6.1.3 manifest is rehydrated by the M6.1.3 reader — the classifier MUST emit labels from the **inherited 5-bucket** set only (no `proxy_*_dominated` labels; no `multi_factor_*` compound labels; no `inconclusive_high_variance` outer override since no `between_run_variance` block is present either). This preserves M6.1.1's historical behavior when the M6.1.3 reader is pointed at an M6.1.1 baseline (e.g., when computing diffs via `--m6_1_3-m6-1-1-baseline`).

## The reporter narrative (FR-009 + FR-009a + round-2 Q2)

The reporter renders three classifier-related artifacts in the published markdown:

### 1. Identifier legend (FR-009a + round-2 Q2)

A single-line legend at the start of the classifier-narratives subsection mapping each abbreviated identifier to its driving segment field:

```
Identifier legend: channel_batching = seg_ab_ms; queue_batching = seg_queue_ms; engine_compute = seg_prefill_ms; frontend_arrival = seg_arrival_ms (dormant in M6.1.3 per FR-008a); proxy_ingress = seg_ingress_ms; proxy_egress = seg_egress_ms.
```

Rendered once per published markdown — readers don't need to re-look-up the mapping at each cell.

### 2. Per-cell base-label narratives

For each cell with a base label, the reporter renders a one-line narrative:

| Label | Narrative |
|---|---|
| `channel_dependent_batching` | "The budget lives in the auxiliary batching segment (channel-config dependent)." |
| `queue_dependent_batching` | "The budget lives in the engine-side queue wait segment." |
| `engine_compute_variation` | "The budget lives in the post-schedule engine prefill compute segment." |
| `proxy_ingress_dominated` | "The budget lives in the proxy → engine handoff (frontend's `pre_engine` to vLLM's `arrival_time`)." |
| `proxy_egress_dominated` | "The budget lives in the engine → proxy yield (vLLM's `first_token_ts` to frontend's `first_chunk`)." |
| `inconclusive` | "No single segment carries the dominant share of the per-cohort spread; attribution is unattributed." |

### 3. Compound-label narratives (FR-009 + round-2 Q2)

For each cell with a compound label, the reporter renders a multi-line narrative using **abbreviated identifiers** (per round-2 Q2) and citing the contributing shares:

```
multi_factor_engine_compute_proxy_egress
  multi-factor: proxy_egress carries 45% of spread, engine_compute carries 43%
  (within the 5pp dominance margin); attribution is not single-source.
```

The narrative cites the specific shares so the reader can judge the near-tie.

### 4. Outer-override narratives

When `inconclusive_high_variance` fires alongside an inner label:

```
inconclusive_high_variance (proxy_egress_dominated)
  Between-run variance dominates attribution: stddev_of_means_ms = 8.0 ms vs
  within-run CI half-width = 4.0 ms (ratio = 2.0; exceeds unified threshold).
  Inner attribution (proxy_egress_dominated) remains present in the per-cell
  row as a parenthetical. Run Phase B (`--m6_1_3 --m6_1_3-diagnose-repeat=1
  --m6_1_3-diagnose-n=200`) to verify whether sample-size scaling closes the gap.
```

## Validation tests

The unit test `tools/benchmark/tests/test_m6_1_3_classifier.py` exercises the rules:

```python
def test_7_bucket_decision_tree_base_labels() -> None:
    """FR-008: each of the 7 base labels fires correctly for a clean cell
    where exactly one segment dominates."""
    for label, segment_field in CANONICAL_MAPPING.items():
        agg = make_aggregate_with_single_dominant_segment(segment_field, share=0.6)
        result = classify_m6_1_3(agg, variance=None, thresholds=DEFAULT_THRESHOLDS)
        assert result == label or result == segment_field.label_form()


def test_compound_label_alphabetical_ordering() -> None:
    """FR-008a + R-8: compound label uses sorted(top, runner_up)."""
    agg = make_aggregate_with_two_near_tie_segments(
        ("seg_egress_ms", 0.45),     # share 45%
        ("seg_prefill_ms", 0.43),    # share 43%; within 5pp margin
    )
    result = classify_m6_1_3(agg, variance=None, thresholds=DEFAULT_THRESHOLDS)
    # Alphabetical: engine_compute < proxy_egress
    assert result == "multi_factor_engine_compute_proxy_egress"


def test_dominance_margin_enforcement() -> None:
    """FR-008a: 10pp gap (clear winner) → single label, not compound."""
    agg = make_aggregate_with_two_segments(
        ("seg_egress_ms", 0.50),     # share 50%
        ("seg_prefill_ms", 0.40),    # share 40%; 10pp gap
    )
    result = classify_m6_1_3(agg, variance=None, thresholds=DEFAULT_THRESHOLDS)
    assert result == "proxy_egress_dominated"


def test_inconclusive_collision_collapse() -> None:
    """FR-008a tail clause: if one near-tie candidate is inconclusive, collapse
    to the other candidate's single label."""
    agg = make_aggregate_with_one_segment_clearing_and_otherwise_inconclusive(
        ("seg_egress_ms", 0.42),     # share 42%; clears the ~40% threshold
    )
    result = classify_m6_1_3(agg, variance=None, thresholds=DEFAULT_THRESHOLDS)
    assert result == "proxy_egress_dominated"  # NOT a compound with inconclusive


def test_outer_override_inconclusive_high_variance() -> None:
    """FR-026 + round-2 Q3 unified threshold: variance dominates → outer
    label overrides inner."""
    agg = make_aggregate_with_single_dominant_segment("seg_prefill_ms", share=0.6)
    variance = M6_1_3BetweenRunVarianceCell(
        mean_of_means_ms=42.0, stddev_of_means_ms=8.0, n_runs=5,
    )
    result = classify_m6_1_3(agg, variance=variance, thresholds=DEFAULT_THRESHOLDS,
                             ci_halfwidth_ms=4.0)
    # Outer label fires; inner label rendered as parenthetical
    assert result == "inconclusive_high_variance (engine_compute_variation)"


def test_legacy_fallback_no_proxy_edge_segments() -> None:
    """FR-008 + FR-010: pre-M6.1.3 manifest rehydration → 5-bucket fallback."""
    agg = make_aggregate_without_proxy_edge_segments()
    result = classify_m6_1_3(agg, variance=None, thresholds=DEFAULT_THRESHOLDS)
    # No proxy_*_dominated; no multi_factor_*; no inconclusive_high_variance
    assert result in {
        "channel_dependent_batching",
        "queue_dependent_batching",
        "engine_compute_variation",
        "frontend_arrival_jitter",  # Dormant in M6.1.3 native, but allowed in legacy fallback
        "inconclusive",
    }


def test_frontend_arrival_jitter_dormant_in_7_bucket_tree() -> None:
    """FR-008a revised row 4 + round-4 Q1: frontend_arrival_jitter MUST NOT
    fire as primary attribution in the 7-bucket tree."""
    agg = make_aggregate_with_single_dominant_segment("seg_arrival_ms", share=0.6)
    result = classify_m6_1_3(agg, variance=None, thresholds=DEFAULT_THRESHOLDS)
    assert result != "frontend_arrival_jitter"
    assert "frontend_arrival" not in result  # Also not in any compound


def test_phase_b_trigger_derivation() -> None:
    """FR-043 + FR-044 + round-2 Q3: trigger cells == cells with inconclusive_high_variance."""
    classifications = {
        "chat_stream_c1": "engine_compute_variation",
        "chat_stream_c4": "inconclusive_high_variance (proxy_egress_dominated)",
        "chat_stream_c8": "inconclusive_high_variance (proxy_egress_dominated)",
        "embed_c1": "channel_dependent_batching",
    }
    trigger = compute_phase_b_trigger(classifications, variance_section_suppressed=False)
    assert trigger.required is True
    assert trigger.trigger_cells == ["chat_stream_c4", "chat_stream_c8"]  # Alphabetically sorted
```

## Cross-references

- Plan: [`../plan.md`](../plan.md) — Technical Context.
- Data model: [`../data-model.md`](../data-model.md) — `M6_1_3BaseLabel`, `M6_1_3CompoundLabel`, `M6_1_3AbbreviatedIdentifier`, `M6_1_3OuterLabel`, `M6_1_3PrimaryLabel`.
- Wire-vocabulary: [`./wire-vocabulary.md`](./wire-vocabulary.md) — sources for the new segments.
- Artifact-schema: [`./artifact-schema.md`](./artifact-schema.md) — `between_run_variance` block + Phase B trigger verdict line.
- Spec: [`../spec.md`](../spec.md) — FR-008, FR-008a, FR-009, FR-009a, FR-026, FR-043, FR-044 + round-1 Q4 + round-2 Q2 + round-2 Q3 + round-4 Q1.
- M6.1.1 classifier reference: `tools/benchmark/src/vllm_grpc_bench/m6_1_1_classifier.py` (the 5-bucket tree this extends).
