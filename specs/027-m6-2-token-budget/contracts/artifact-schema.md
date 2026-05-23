# Contract: M6.2 Artifact Schema

**Branch**: `027-m6-2-token-budget` | **Phase 1 output** | **Plan**: [../plan.md](../plan.md)

## Schema versioning

`schema_version` MUST stay at `"m6_1_1.v1"` per FR-011. M6.2 makes **strict-superset additive** evolution. Round-5 extends the additions:

- New top-level keys (unchanged from round-4): `null_anchor_validation`, `max_tokens_axis`, `protocol_crossover`, `kv_pressure_observation`, `anchor_latency_trajectory`, `failure_summary`, `integrity_warnings`.
- New per-row fields on `M6_2MeasurementPoint`: `max_tokens`, `block_start_utc`, `block_end_utc`, `retry_attempted` (round-4), **`prompt_source`, `measurement_regime`, `prompt_corpus_idx`** (round-5).
- New fields on `M6_2KVPressureObservation` (round-5): `sub_probe_n_rpcs`, `sub_probe_prompt_source`, `sub_probe_measurement_regime`.
- New `run_meta` fields: `iteration_order`, `iteration_discipline_verified`, `n_per_point`, `validate_axis_subset`, `wall_clock_start_utc`, `wall_clock_end_utc`, `total_sweep_hours`, `modal_spend_usd_estimate` (round-4), **`chat_corpus_sha256`, `chat_corpus_path`, `embed_corpus_sha256`, `embed_corpus_path`, `sub_probe_ran`** (round-5).

M6.1.3-vintage readers parse the M6.2 artifact without exception per JSON-decode default. Test enforcement: `test_m6_2_artifact_schema.py::test_strict_superset_compat_with_m6_1_3`.

## JSON top-level structure

```json
{
  "schema_version": "m6_1_1.v1",
  "run_meta": { ... },
  "network_paths": { <cohort>: [<NetworkPathSnapshot>, ...] },
  "per_cell": { <cell_id>: { <cohort>: { <max_tokens>: <MeasurementPoint> } } },
  "null_anchor_validation": [<NullAnchor>, ...],
  "max_tokens_axis": [10, 50, 256, 512, 1024, 2048],
  "protocol_crossover": [<CrossoverThreshold>, ...],
  "kv_pressure_observation": [<KVPressureObservation>, ...],
  "anchor_latency_trajectory": { <cohort>: <AnchorLatencyTrajectory> },
  "failure_summary": { <reason>: <count> },
  "integrity_warnings": [<channel_label>, ...]
}
```

Entity shapes live in [`../data-model.md`](../data-model.md). This contract focuses on **rendering rules** (markdown structure, conditional sections, integrity-header firing) and **derived-field computation** (crossover rule, wall-clock-ratio inference, drift-detection thresholds).

## Markdown rendering structure

### Primary sections (FR-016, in this order)

1. **Production latency budget** — per-cell × per-cohort × per-`max_tokens` p50/p95/p99 table. Per FR-016 / US1. Renders the full 144 rows in publish mode; in validate mode, interior-cap rows (`max_tokens ∈ {256, 512, 1024}`) are marked `not_validated`.

2. **TPOT curves** — chat_stream-only time-per-output-token vs `max_tokens`. Per FR-016. One curve per (chat_stream_c1 / c4 / c8, cohort) pair; x-axis is `max_tokens`, y-axis is `tpot_ms`. In validate mode, interior caps rendered as `not_validated`.

3. **Engine-cost decomposition curves** — segment-share evolution as generation length grows. Per FR-016. For each (cell, cohort) pair, renders the inherited M6.1.3 5-segment breakdown (`seg_ab_ms`, `seg_queue_ms`, `seg_prefill_ms`, `seg_ingress_ms`, `seg_egress_ms`) as a function of `max_tokens`. Operators read this to see how engine cost rebalances with generation length.

4. **Protocol crossover threshold** — per-cell `crossover_max_tokens` from the symmetric mean-in-CI rule (User Story 2). Per FR-016. One row per cell with columns `(cell_id, m6_1_3_base_verdict, crossover_max_tokens, crossover_evidence)`. Validate mode carries the leading axis-restricted disclaimer callout: *"Validate-mode crossover analysis is restricted to the 3-point axis subset `{10, 50, 2048}`; interior-cap crossover thresholds are unobservable in validate mode. Use the publish-mode artifact for fine-grained crossover threshold attribution."* and uses the coarse 4-value vocabulary `{10, 50, 2048, survives_to_2048}` (or `null`).

### Auxiliary subsections (in this order)

5. **KV-cache pressure** — characterizes the `c=8 × max_tokens=2048` regime per FR-017. **Sourced from the FR-036 KV-pressure sub-probe (round-5)**, NOT the main-sweep budget-table c=8 rows. Per cohort × cell-type ∈ {chat_stream, embed}: `kv_cache_used_fraction_peak` (best-effort, `null` if vLLM doesn't expose) AND `wall_clock_ratio_c8_2048_over_1024` (REQUIRED, per FR-017a; computed from sub-probe `wall_p50_ms` at `c=8 × {1024, 2048}` with `ignore_eos=True`) AND `wall_clock_inference_label` ∈ {`kv_pressure_inferred_chat_stream`, `kv_pressure_inferred_embed`, `kv_pressure_not_observable`}. Subsection explicitly labels measurements as "forced-cap regime (ignore_eos=True)" to distinguish from the budget-table c=8 rows which are "natural EOS under cap=N". The subsection narrative cites both regimes when discussing the c=8 × 2048 row of the budget table — operators see the two answers (production-EOS vs forced-cap) side by side.

6. **Null anchor validation** — per FR-018. Per-(cell, cohort) drift verdict at `max_tokens=10/50` against M6.1.3's published CI. Three-column table: cell, cohort, drift status (`PASS` / `WARN` / `FAIL`) + `drift_fraction` numeric.

7. **Anchor latency trajectory** — per FR-031 / SC-015. Per-cohort intra-sweep anchor trajectory rendered as a small line chart or table. 8-10 snapshots/cohort in publish mode; 2 in validate. Each snapshot row: `sweep_hour_mark` / `snapshot_timestamp` / `wall_p50_ms`. Per-cohort `latency_drift_warning` line when `max_minus_min_wall_p50_ms > m6_1_3_baseline_ci_half_width`.

8. **Failure summary** — per FR-029 / SC-014. Per-reason tally of `failed_<reason>` markers across the 144-row table. Always present, even when zero failures (renders "no measurement-cell failures").

9. **Sweep wall-clock timeline** — per FR-032 / SC-017. One row per `(cell, max_tokens)` tuple showing each cohort's block start UTC + duration in minutes — visual verification of FR-030 cohort-innermost discipline. Renders in publish mode unconditionally; in validate mode only if total sweep wall-clock ≥ 8h (otherwise low-signal, JSON timestamps still persist for operator inspection).

10. **Method / Background** — FR-019 reciprocal cross-reference to the M6.1.3 artifact. Single paragraph noting "This milestone builds on M6.1.3's published per-cohort attribution at `max_tokens=10/50`; see [m6_1_3-attribution-closure.md](m6_1_3-attribution-closure.md)."

### Leading sweep-level integrity warning headers

Four publish-blocking-eligible integrity warning channels render as leading callouts at the top of the markdown body (above section 1). Each channel is independent — multiple may fire on the same artifact. Operator decides whether to publish or rerun in all cases (publication is NOT auto-blocked by any channel).

| Channel label | Firing rule | FR | SC |
|---|---|---|---|
| `null_anchor_drift` | ≥ 2 of 22 cross-checkable anchor cells (chat at max_tokens=50 + embed at max_tokens=10 minus M6.1.3's cohort omissions, per FR-012) have `drift_verdict ∈ {WARN, FAIL}` against M6.1.3 published CI. The 26 new-baseline cells (chat at max_tokens=10 + embed at max_tokens=50 + the 2 omitted cohort pairs) emit `new_baseline_marker` lines but are excluded from this count. Per-cell verdict uses the **pooled-CI-with-floor rule** documented below. | FR-014 | SC-004 |
| `failure_summary_threshold` | EITHER (a) ≥ 3 cells across the latency budget table have `failed_<reason>` markers, OR (b) any single `(cell, max_tokens)` point has all 4 cohorts failed (then tagged `systemic_failure_<reason>` in addition to per-cohort `failed_<reason>`) | FR-029 | SC-014 |
| `cohort_csp_mismatch` | Any consecutive-snapshot pair in `network_paths[cohort]` reveals a CSP / region change | FR-009 | SC-010 |
| `intra_sweep_latency_drift` | ≥ 2 of 4 cohorts in `anchor_latency_trajectory` have `latency_drift_warning = true`. Per-cohort `latency_drift_warning` uses the same **pooled-CI-with-floor rule** documented below. | FR-031 | SC-016 |

One soft diagnostic warning (NOT publish-blocking-eligible, informational only):

| Channel label | Firing rule | FR | SC |
|---|---|---|---|
| `iteration_discipline_broken` | `run_meta.iteration_discipline_verified = false` | FR-032 | SC-017 |

Test enforcement: `test_m6_2_artifact_schema.py::test_integrity_warning_channels_canonical` asserts that `integrity_warnings` list contains only the canonical channel labels above (or is empty).

### Pooled-CI-with-floor drift threshold rule (B2 amendment, 2026-05-23)

SC-004 (`null_anchor_drift`) and SC-016 (`intra_sweep_latency_drift`) both
depend on a per-cell drift threshold derived from CI half-widths. The
original rule compared `|delta|` directly against M6.1.3's published
CI half-width alone. M6.1.3's CIs were measured under tighter conditions
(more runs, longer warm-up) than an M6.2 per-block n=20 sweep, so sub-ms
baseline CIs (e.g., `chat_stream_c1` `default_grpc` published a 0.14 ms CI)
made the gate trip at 100σ+ on operationally-insignificant drift.

The **pooled-CI-with-floor** rule (implemented in
`m6_2_null_anchor.pooled_ci_half_width` /
`m6_2_null_anchor.compute_drift_verdict`) is:

```
pooled = max(m6_1_3_ci_half_width, m6_2_ci_half_width, 10 ms)
PASS   if |delta| ≤ pooled
WARN   if pooled < |delta| ≤ 3 × pooled
FAIL   if |delta| > 3 × pooled
```

Where:

- `m6_1_3_ci_half_width` is the baseline CI for the (cell, cohort) pair
  loaded from `docs/benchmarks/m6_1_3-attribution-closure.json`.
- `m6_2_ci_half_width` is the current sweep's per-block CI half-width
  computed by the per-segment aggregator (`_aggregate_block_metrics` in
  `m6_2_sweep.py`) using the same 1.96 × stderr formula as
  `m6_1_3_reporter._ci_half_width_95`. For SC-016, `m6_2_ci_half_width` is
  the trajectory's own CI half-width over the snapshot p50 samples
  (`_snapshot_ci_half_width` in `m6_2_anchor_trajectory.py`).
- The 10 ms floor (`DRIFT_THRESHOLD_FLOOR_MS`) prevents sub-ms baseline CIs
  on either side from flagging operationally-insignificant drift.
- The 3× multiplier (`DRIFT_THRESHOLD_WARN_MULTIPLIER`) separates WARN from
  FAIL — calibrated so FAIL roughly aligns with the operationally "this is
  real drift, not measurement noise" point.

The reported `drift_fraction` numeric is computed against the pooled width
(`delta / pooled`) so the value matches the band placement of the verdict.

Known limitation (not addressed by B2): the floor is absolute, so
low-latency cohorts may still report `WARN` on small operational drifts
(e.g., 15 ms on a ~570 ms `tuned_grpc_multiplexed` baseline is ~2.6%
relative — above the 10 ms floor and thus flagged). Further suppression
for low-latency cells would need a relative-magnitude floor (option B4
from the 2026-05-23 selection round) which is NOT implemented in B2.

## Derived-field computation rules

### Symmetric mean-in-CI crossover rule (FR-016 + spec round-1 Q3)

Implemented in `m6_2_crossover.compute_per_cell_crossover(per_cell_axis_rows, m6_1_3_base_verdicts)`:

```python
def compute_per_cell_crossover(
    per_cell_axis_rows: dict[str, dict[str, dict[int, M6_2MeasurementPoint]]],
    m6_1_3_base_verdicts: dict[str, str],
    *,
    sweep_mode: M6_2SweepMode,
) -> list[M6_2CrossoverThreshold]:
    axis = M6_2_MAX_TOKENS_AXIS if sweep_mode == "publish" else M6_2_VALIDATE_MAX_TOKENS_AXIS
    out: list[M6_2CrossoverThreshold] = []
    for cell_id, base_verdict in m6_1_3_base_verdicts.items():
        if base_verdict in INCONCLUSIVE_VERDICTS:
            out.append(M6_2CrossoverThreshold(
                cell_id=cell_id,
                m6_1_3_winner_cohort=None,
                m6_1_3_second_cohort=None,
                crossover_max_tokens=None,
                crossover_evidence="base verdict was already inconclusive at the M6.1.3 baseline",
                m6_1_3_base_verdict=base_verdict,
            ))
            continue

        winner, second = identify_winner_and_second(base_verdict)
        # Iterate axis in ascending order
        for max_tokens in axis:
            winner_row = per_cell_axis_rows[cell_id][winner][max_tokens]
            second_row = per_cell_axis_rows[cell_id][second][max_tokens]
            if symmetric_mean_in_ci(winner_row, second_row):
                evidence = (
                    f"winner_p50={winner_row.wall_p50_ms}ms "
                    f"± {winner_row.wall_p50_ms_ci_half_width}ms overlaps "
                    f"second_p50={second_row.wall_p50_ms}ms "
                    f"± {second_row.wall_p50_ms_ci_half_width}ms "
                    f"at max_tokens={max_tokens}"
                )
                if max_tokens == axis[0]:
                    # Rule fires at 10 → M6.1.3 verdict not robust to M6.2 resampling per US2 #3
                    evidence = "M6.1.3 verdict not robust to M6.2 resampling"
                out.append(M6_2CrossoverThreshold(
                    cell_id=cell_id,
                    m6_1_3_winner_cohort=winner,
                    m6_1_3_second_cohort=second,
                    crossover_max_tokens=max_tokens,
                    crossover_evidence=evidence,
                    m6_1_3_base_verdict=base_verdict,
                ))
                break
        else:
            # Rule never fired across the axis
            out.append(M6_2CrossoverThreshold(
                cell_id=cell_id,
                m6_1_3_winner_cohort=winner,
                m6_1_3_second_cohort=second,
                crossover_max_tokens=None,
                crossover_evidence="verdict survives across the axis",
                m6_1_3_base_verdict=base_verdict,
            ))
    return out


def symmetric_mean_in_ci(a: M6_2MeasurementPoint, b: M6_2MeasurementPoint) -> bool:
    """EITHER a's mean falls in b's CI OR b's mean falls in a's CI (95% normal approx)."""
    if a.wall_p50_ms is None or b.wall_p50_ms is None:
        return False  # Block failure → no crossover detection possible
    a_low, a_high = a.wall_p50_ms - a.wall_p50_ms_ci_half_width, a.wall_p50_ms + a.wall_p50_ms_ci_half_width
    b_low, b_high = b.wall_p50_ms - b.wall_p50_ms_ci_half_width, b.wall_p50_ms + b.wall_p50_ms_ci_half_width
    return (b_low <= a.wall_p50_ms <= b_high) or (a_low <= b.wall_p50_ms <= a_high)
```

Test cases in `test_m6_2_crossover.py`:
- Symmetric rule fires at one direction only (`winner` mean ∈ `second` CI but `second` mean ∉ `winner` CI; predicate true) → `crossover_max_tokens` populated.
- Symmetric rule fires at both directions (means each in the other's CI) → `crossover_max_tokens` populated.
- Rule never fires across the axis → `crossover_max_tokens = None`, evidence `"verdict survives across the axis"`.
- Rule fires at `max_tokens=10` → evidence `"M6.1.3 verdict not robust to M6.2 resampling"` per US2 #3.
- Base verdict inconclusive → `crossover_max_tokens = None`, evidence `"base verdict was already inconclusive at the M6.1.3 baseline"` per US2 #2.
- Validate-mode axis subset → returns coarse 4-value vocabulary `{10, 50, 2048, None}`.

### Wall-clock-ratio KV-pressure inference (FR-017a + spec round-3 Q3 + round-5 amendment)

**Round-5 amendment**: The inputs to this compute are the **KV-pressure sub-probe rows** (FR-036), NOT the main-sweep budget-table c=8 rows. The sub-probe sets `ignore_eos=True` so the engine generates to the cap on every RPC — that's the measurement the threshold-2.2 calibration assumes.

Implemented in `m6_2_crossover.compute_kv_pressure_inference(per_cohort_sub_probe_rows)`:

```python
M6_2_KV_PRESSURE_THRESHOLD: float = 2.2  # Pinned per spec round-3 Q3
M6_2_SUB_PROBE_N: int = 20  # Pinned per round-5 Q4

def compute_kv_pressure_inference(
    per_cohort_sub_probe_rows: dict[str, dict[str, dict[int, SubProbeBlockResult]]],
    # ^ Keyed by cell_type ("chat_stream" | "embed") → cohort → max_tokens (1024 | 2048).
    #   SubProbeBlockResult is the internal sub-probe block measurement shape
    #   (n=20 RPCs, ignore_eos=True, wall_p50_ms / wall_p95_ms / failed_reason).
) -> list[M6_2KVPressureObservation]:
    out: list[M6_2KVPressureObservation] = []
    for cell_type in ("chat_stream", "embed"):
        for cohort in M6_1_2_COHORTS:
            block_1024 = per_cohort_sub_probe_rows[cell_type][cohort].get(1024)
            block_2048 = per_cohort_sub_probe_rows[cell_type][cohort].get(2048)
            oom = block_2048 is not None and block_2048.failed_reason == "oom"
            if block_1024 is None or block_2048 is None or block_1024.wall_p50_ms is None or block_2048.wall_p50_ms is None:
                ratio = None
                label = "kv_pressure_not_observable"
            else:
                ratio = block_2048.wall_p50_ms / block_1024.wall_p50_ms
                label = (
                    f"kv_pressure_inferred_{cell_type}"
                    if ratio > M6_2_KV_PRESSURE_THRESHOLD
                    else "kv_pressure_not_observable"
                )
            engine_field = peak_kv_fraction_from_trailing_metadata(block_2048) if block_2048 else None
            sub_probe_prompt_source = "corpus_sharegpt" if cell_type == "chat_stream" else "corpus_sharegpt_embed"
            out.append(M6_2KVPressureObservation(
                cohort=cohort,
                cell_type=cell_type,
                wall_clock_ratio_c8_2048_over_1024=ratio,
                wall_clock_inference_label=label,
                kv_cache_used_fraction_peak=engine_field,
                scheduling_stall_signals=None,  # filled by orchestrator from engine logs if any
                oom_observed=oom,
                sub_probe_n_rpcs=M6_2_SUB_PROBE_N,
                sub_probe_prompt_source=sub_probe_prompt_source,
                sub_probe_measurement_regime="forced_cap_ignore_eos_true",
            ))
    return out
```

Test cases in `test_m6_2_kv_pressure.py`:
- `R > 2.2` for chat_stream → label `"kv_pressure_inferred_chat_stream"`.
- `R = 2.0` (exactly linear) → label `"kv_pressure_not_observable"`.
- `R = 2.1` (below threshold) → label `"kv_pressure_not_observable"`.
- Engine field present → propagated to `kv_cache_used_fraction_peak`.
- Engine field absent → `kv_cache_used_fraction_peak = None` AND inference still fires.
- OOM at `(cohort, c=8, max_tokens=2048)` → `oom_observed = True` AND inference is `"kv_pressure_not_observable"` with footnote.

### Null-anchor drift verdict (FR-012 / FR-013)

Implemented in the reporter (per-row derivation, no separate module):

```python
def derive_null_anchor_verdicts(
    m6_2_anchor_rows: list[M6_2MeasurementPoint],
    m6_1_3_baseline: dict,
) -> list[M6_2NullAnchor]:
    out = []
    for row in m6_2_anchor_rows:
        # row.max_tokens ∈ {10, 50}
        m6_1_3_p50 = m6_1_3_baseline["per_cell"][row.cell_id]["per_cohort"][row.cohort][f"max_tokens={row.max_tokens}"]["wall_p50_ms"]
        m6_1_3_ci_half = m6_1_3_baseline["per_cell"][row.cell_id]["per_cohort"][row.cohort][f"max_tokens={row.max_tokens}"]["wall_p50_ms_ci_half_width"]
        if row.wall_p50_ms is None:
            verdict = "FAIL"  # Block failure counts as drift
            fraction = None
        else:
            fraction = (row.wall_p50_ms - m6_1_3_p50) / m6_1_3_ci_half
            if abs(fraction) <= 1.0:
                verdict = "PASS"
            elif abs(fraction) <= 2.0:
                verdict = "WARN"
            else:
                verdict = "FAIL"
        out.append(M6_2NullAnchor(
            cell_id=row.cell_id,
            cohort=row.cohort,
            max_tokens=row.max_tokens,
            m6_2_wall_p50_ms=row.wall_p50_ms,
            m6_1_3_wall_p50_ms=m6_1_3_p50,
            m6_1_3_ci_half_width=m6_1_3_ci_half,
            drift_verdict=verdict,
            drift_fraction=fraction,
        ))
    return out
```

The FR-014 sweep-level integrity header fires when `sum(1 for r in null_anchor_validation if r.drift_verdict in {"WARN", "FAIL"}) >= 3`.

### Intra-sweep latency drift detection (FR-031 / SC-016)

Implemented in `m6_2_anchor_trajectory.compute_anchor_latency_trajectory(...)`:

```python
def compute_anchor_latency_trajectory(
    snapshots_by_cohort: dict[str, list[M6_2AnchorLatencySnapshot]],
    m6_1_3_baseline_ci_half_width_at_chat_stream_c1_max_tokens_10: dict[str, float],
) -> dict[str, M6_2AnchorLatencyTrajectory]:
    out = {}
    for cohort, snapshots in snapshots_by_cohort.items():
        max_p50 = max(s.wall_p50_ms for s in snapshots)
        min_p50 = min(s.wall_p50_ms for s in snapshots)
        spread = max_p50 - min_p50
        ci_half = m6_1_3_baseline_ci_half_width_at_chat_stream_c1_max_tokens_10[cohort]
        out[cohort] = M6_2AnchorLatencyTrajectory(
            cohort=cohort,
            snapshots=snapshots,
            max_minus_min_wall_p50_ms=spread,
            latency_drift_warning=(spread > ci_half),
        )
    return out


def compute_intra_sweep_drift_header_fired(trajectories: dict[str, M6_2AnchorLatencyTrajectory]) -> bool:
    """SC-016: ≥ 2 of 4 cohorts drifted → integrity header fires."""
    return sum(1 for t in trajectories.values() if t.latency_drift_warning) >= 2
```

### Failure summary tally + integrity header (FR-029 / SC-014)

```python
def compute_failure_summary(measurement_points: list[M6_2MeasurementPoint]) -> dict[str, int]:
    failure_summary = collections.Counter()
    for point in measurement_points:
        if point.failed_reason is not None:
            failure_summary[point.failed_reason] += 1
    return dict(failure_summary)


def compute_failure_summary_integrity_header_fired(
    measurement_points: list[M6_2MeasurementPoint],
) -> bool:
    """FR-029: ≥ 3 cells failed OR any (cell, max_tokens) has all 4 cohorts failed."""
    failed = [p for p in measurement_points if p.failed_reason is not None]
    if len(failed) >= 3:
        return True
    # Check for systemic failure: any (cell, max_tokens) tuple with all 4 cohorts failed
    by_tuple = collections.defaultdict(list)
    for point in failed:
        by_tuple[(point.cell_id, point.max_tokens)].append(point.cohort)
    return any(len(cohorts) == 4 for cohorts in by_tuple.values())
```

### Iteration discipline machine check (FR-032 / SC-017)

```python
def compute_iteration_discipline_verified(
    measurement_points: list[M6_2MeasurementPoint],
) -> bool:
    """Every (cell, max_tokens) tuple's 4 cohort blocks ran contiguously without
    any other tuple's cohort blocks interleaving between them."""
    # Sort by block_start_utc
    ordered = sorted(measurement_points, key=lambda p: p.block_start_utc)
    # Group by (cell_id, max_tokens) and check contiguity
    seen_tuples = set()
    current_tuple = None
    current_cohorts_in_tuple = []
    for point in ordered:
        tup = (point.cell_id, point.max_tokens)
        if tup != current_tuple:
            if current_tuple is not None:
                if tup in seen_tuples:
                    # We've seen this tuple before AND it's reappearing — discipline broken
                    return False
                seen_tuples.add(current_tuple)
            current_tuple = tup
            current_cohorts_in_tuple = [point.cohort]
        else:
            current_cohorts_in_tuple.append(point.cohort)
    return True
```

## Validate-mode rendering rules (FR-001 + FR-016 + spec round-1 Q6)

The validate-sibling artifact:
- Reports the same 4 primary sections (Production latency budget / TPOT curves / Engine-cost decomposition curves / Protocol crossover threshold) with sections 1/2/3 marking `max_tokens ∈ {256, 512, 1024}` rows as `not_validated`.
- Section 4 carries the leading axis-restricted disclaimer callout AND uses the coarse 4-value `crossover_max_tokens` vocabulary `{10, 50, 2048, survives_to_2048, null}`.
- Auxiliary subsections all render: KV-cache pressure (the 2048 axis point IS in the validate subset), Null anchor validation (22 cross-checkable cells with PASS/WARN/FAIL + 26 new-baseline cells with `new_baseline_marker` per FR-012), Anchor latency trajectory (start + end snapshots only), Failure summary (always present), Sweep wall-clock timeline (OMITTED if total sweep < 8h; included if ≥ 8h e.g. due to retries).
- Same integrity-header firing rules apply (no validate-mode relaxation).

## Forward-pointing annotation (FR-019)

The M6.1.3 markdown receives exactly ONE leading note line at the top of the body (immediately after the title + frontmatter):

```markdown
> **Note**: M6.2's published artifact ([m6_2-token-budget.md](m6_2-token-budget.md)) extends this milestone's
> attribution verdicts to a realistic-response-length axis (`max_tokens ∈ {10, 50, 256, 512, 1024, 2048}`).
> See that artifact for per-cohort latency budgets at production response lengths and the protocol-crossover
> threshold per cell.
```

M6.1.3's JSON is untouched. M6.2's markdown carries the reciprocal "Method / Background" pointer per section 10 above.

This convention mirrors M6.1.3's own FR-031 round-3 Q2 minimal-touch annotation of M6.1.1's markdown. Same constraint: ONE leading line, no body-content mutation, no appended subsection.
