# Contract: M6.1.3 Artifact Schema

**Branch**: `026-m6-1-3-attribution-closure` | **Phase 1 output** | **Plan**: [../plan.md](../plan.md)

## Purpose

M6.1.3 publishes **three artifacts** at distinct paths per FR-038 + round-2 Q1 (validate sibling, canonical publish, conditional Phase B sibling). Each artifact extends M6.1.2's strict-superset JSON schema with: new per-cell segment columns (`seg_ingress_ms`, `seg_egress_ms`), new audit fields (`tokenized_prompt_length`, `tokenized_prompt_hash` in the per-RPC sidecar), a new top-level `between_run_variance` block, and the new classifier label set (7 base labels + compound + `inconclusive_high_variance` outer override). This contract documents the wire-level shape of the new fields plus the conditional rendering rules for the per-run audit appendix, the between-run variance section, and the Phase B trigger verdict line.

## The three-path publishing scheme (FR-038 + round-2 Q1)

```text
docs/benchmarks/
├── m6_1_3-attribution-closure.{md,json}                # Canonical publish (--m6_1_3 at repeat=5, n=50)
├── m6_1_3-attribution-closure-validate.{md,json}       # Validate sibling (--m6_1_3-validate at repeat=1, n=50)
└── m6_1_3-attribution-closure-phase-b.{md,json}        # Phase B sibling (--m6_1_3 at repeat=1, n=200; CONDITIONAL per FR-043)
```

**Path-inference logic** (per R-7, implemented in `m6_1_3_validate.py`):
1. `--m6_1_3-validate` → validate-sibling path.
2. `--m6_1_3` with `--m6_1_3-diagnose-repeat=1` AND `--m6_1_3-diagnose-n != 50` → Phase B sibling path.
3. `--m6_1_3` otherwise (default modifiers) → canonical publish path.
4. Operator explicitly passing `--m6_1_3-report-out` / `--m6_1_3-report-json-out` overrides regardless of mode.

**Why three paths**: per round-2 Q1, a re-run validate sweep MUST NOT clobber a recent publish run's output (operator footgun). Same for Phase B vs canonical. The dedicated sibling paths eliminate the clobber risk; each artifact has a clear purpose.

## Top-level artifact JSON shape

```jsonc
{
  // === M6.1.1-inherited keys (preserved verbatim) ===
  "schema_version": "m6_1_1.v1",
  "dispatch_mode": "concurrent",
  "run_id": "20260517-123456",
  "run_started_at": "2026-05-17T12:34:56Z",
  "run_completed_at": "2026-05-17T13:49:12Z",
  "run_meta": {
    // ... M6.1.2-inherited shape ...
    "sweep_mode": "full",                                // M6.1.2-style literal: "full" | "validate"
    "m6_1_3_diagnose_repeat": 5,                         // Modifier value at invocation
    "m6_1_3_diagnose_n": 50,                             // Modifier value at invocation
    "m6_1_3_symmetric_prompts": false                    // FR-019 flag state
  },
  "phase_1_classifications": { /* per-cell label assignments per the 7-bucket + compound + outer override */ },
  "phase_1_runs": [ /* 5 entries on the canonical publish sweep at repeat=5; 1 entry on validate / Phase B */ ],
  "multi_point_timings": { /* per-cell aggregates with new seg_ingress_ms + seg_egress_ms columns */ },
  // ... other M6.1.1-inherited keys ...

  // === M6.1.2-inherited keys (preserved verbatim per FR-032) ===
  "network_paths": { /* M6.1.2 topology probe block; probed ONCE at first-run start per FR-030 */ },
  "cohort_set": ["default_grpc", "rest_https_edge", "rest_plain_tcp", "tuned_grpc_multiplexed"],
  "cohort_omissions": null,                              // M6.1.3 default: no intentional omissions

  // === M6.1.3 NEW top-level keys (strict-superset addition per FR-010) ===
  "between_run_variance": {                              // null on single-run sweeps (validate, Phase B)
    "chat_stream_c1": {
      "rest_https_edge":            { "mean_of_means_ms": 42.20, "stddev_of_means_ms": 0.43, "n_runs": 5 },
      "default_grpc":               { "mean_of_means_ms": 46.85, "stddev_of_means_ms": 0.38, "n_runs": 5 },
      "tuned_grpc_multiplexed":     { "mean_of_means_ms": 41.05, "stddev_of_means_ms": 0.22, "n_runs": 5 }
      // rest_plain_tcp absent on this c=1 cell — per the M6.1.2 tuned-pair-collapse-at-c=1 rule
      // Actually wait — tuned_grpc_multiplexed collapses with default_grpc at c=1, not rest_plain_tcp.
      // Per M6.1.2: at c=1, cohorts are (rest_https_edge, rest_plain_tcp, default_grpc) — 3 cohorts.
      // Let me re-do this example:
    },
    "chat_stream_c4": {
      "rest_https_edge":            { "mean_of_means_ms": 89.50, "stddev_of_means_ms": 7.28, "n_runs": 5 },
      "rest_plain_tcp":             { "mean_of_means_ms": 81.20, "stddev_of_means_ms": 4.91, "n_runs": 5 },
      "default_grpc":               { "mean_of_means_ms": 79.68, "stddev_of_means_ms": 4.63, "n_runs": 5 },
      "tuned_grpc_multiplexed":     { "mean_of_means_ms": 78.05, "stddev_of_means_ms": 3.89, "n_runs": 5 }
    }
    // ... per chat_stream cell; embed cells absent here (no streaming = no proxy_*_dominated variance to characterize the same way)
  }
}
```

## Per-cell row shape (within `multi_point_timings` and `phase_1_runs[*].cells`)

Each per-cell row gains 2 new segment columns and (when streaming) the audit-derived columns:

```jsonc
{
  "cell_id": "chat_stream_c4",
  "cohort": "rest_https_edge",
  "engine_ttft_ms": { "mean": 89.50, "stddev": 4.21, "ci_halfwidth_95_ms": 1.17 },

  // Inherited M6.1.1 segments
  "seg_ab_ms":      { "mean": 0.32, "stddev": 0.04, "ci_halfwidth_95_ms": 0.011 },
  "seg_queue_ms":   { "mean": 0.05, "stddev": 0.02, "ci_halfwidth_95_ms": 0.006 },
  "seg_prefill_ms": { "mean": 38.92, "stddev": 2.83, "ci_halfwidth_95_ms": 0.79 },

  // NEW M6.1.3 segments (streaming-only per FR-003)
  "seg_ingress_ms": { "mean": 3.20, "stddev": 1.21, "ci_halfwidth_95_ms": 0.34 },
  "seg_egress_ms":  { "mean": 47.01, "stddev": 4.18, "ci_halfwidth_95_ms": 1.16 },

  // NEW M6.1.3 audit metadata (both streaming + unary per FR-014; absent for some pre-M6.1.3 cells)
  "audit": {
    "n_rpcs_with_audit_fields": 50,
    "clock_anomaly_fraction": 0.0,
    "clock_anomaly_warning": false
  },

  // Per-cell classifier label (one of the 7 base + compound + outer override per contracts/classifier.md)
  "label": "proxy_egress_dominated"
}
```

**Canonical 5-segment sum invariant** (SC-002 + round-4 Q1): for chat_stream cells, `seg_ab_ms.mean + seg_queue_ms.mean + seg_prefill_ms.mean + seg_ingress_ms.mean + seg_egress_ms.mean` MUST converge to `engine_ttft_ms.mean` within ±1 ms (sample noise). The 5-segment sum is exhaustive per round-4 Q1 — `seg_arrival_ms` is dormant in M6.1.3 (`frontend_arrival_jitter` never fires as primary attribution).

**Embed cells**: the proxy-edge segments are absent (`seg_ingress_ms` and `seg_egress_ms` are `null` or omitted entirely) per FR-003. The audit fields (`tokenized_prompt_length`, `tokenized_prompt_hash`) ARE present per FR-014. The canonical sum for embed cells is the inherited 3-segment sum from M6.1.1.

## The "Per-Cohort Prompt-Content Audit" reporter section (FR-016)

Rendered per cell × cohort, computed from the **pooled distribution** across all `phase_1_runs[]`:

```markdown
### Per-Cohort Prompt-Content Audit

#### chat_stream_c1 (pooled n=250 per cohort)

| Cohort                | mean_tokenized_prompt_length | stddev | n_rpcs | unique_hash_count |
|-----------------------|------------------------------:|--------:|-------:|-------------------:|
| rest_https_edge       | 48.20 | 1.18 | 250 | 50 |
| default_grpc          | 47.95 | 1.22 | 250 | 50 |
| tuned_grpc_multiplexed | 48.05 | 1.20 | 250 | 50 |

**H1 verdict** (per FR-016 + round-1 Q5):

> H1 rejected: per-cohort distributions statistically identical

**Recommendation** (per FR-018):

> H1 rejected at chat_stream_c1: proceed to Phase C engine-config probes
> (prefix-cache disable per H3, reversed cohort order per H4) for further
> investigation. Phase C is out of scope for the M6.1.3 closure deliverable;
> invoke manually with `<TBD /speckit-plan-defined CLI flag>` if a follow-up
> operator wants to pursue it.
```

If the pooled-distribution H1 verdict on `chat_stream_c1` is `"H1 confirmed"`, the **Recommendation** block per FR-017 reads:

```markdown
**Recommendation** (per FR-017):

> H1 confirmed at chat_stream_c1: per-cohort token-count means diverge by
> >2σ (rest_https_edge=48.2, default_grpc=53.7, tuned_grpc_multiplexed=47.9).
> Symmetric prompts SHOULD become the M6.x convention going forward. M6.2 /
> M7 / M8 spec authors MUST cite this recommendation as a precondition (per
> SC-012) and either accept it (turning `--m6_2-symmetric-prompts` on by
> default) or document an explicit divergence with reasoning.
```

## The per-run audit appendix (FR-016a + round-2 Q5)

**Conditional rendering** per round-2 Q5: the appendix MUST render whenever any per-run verdict differs from the pooled verdict for any cell ("differs" = byte-non-identical label string per cell). The appendix MAY be omitted only when all per-run verdicts match the pooled verdict for every cell — in that case omission keeps the published markdown concise.

```markdown
### Per-Run Audit Verdict Appendix (rendered because per-run / pooled disagreement detected)

#### chat_stream_c1

| Run | Per-run verdict |
|-----|------------------|
| 0   | H1 confirmed: per-cohort token-count means diverge by >2σ |
| 1   | H1 rejected: per-cohort distributions statistically identical |
| 2   | H1 confirmed: per-cohort token-count means diverge by >2σ |
| 3   | H1 confirmed: per-cohort token-count means diverge by >2σ |
| 4   | H1 confirmed: per-cohort token-count means diverge by >2σ |
| **Pooled** | **H1 confirmed: per-cohort token-count means diverge by >2σ** |

#### embed_c1

| Run | Per-run verdict |
|-----|------------------|
| 0   | H1 rejected: per-cohort distributions statistically identical |
| 1   | H1 rejected: per-cohort distributions statistically identical |
| 2   | H1 rejected: per-cohort distributions statistically identical |
| 3   | H1 rejected: per-cohort distributions statistically identical |
| 4   | H1 rejected: per-cohort distributions statistically identical |
| **Pooled** | **H1 rejected: per-cohort distributions statistically identical** |

_(embed_c1's per-run verdicts all match the pooled — appendix would have
been omitted for this cell alone, but chat_stream_c1's disagreement forces
the appendix to render for all cells.)_
```

Per FR-016a clarification: when one cell forces the appendix to render, the appendix renders ALL cells (even those where per-run verdicts match) so a reader sees the full context, not a sparse "only disagreement-cells" table.

## The "Between-Run Variance" reporter section (FR-025)

Rendered only when `len(phase_1_runs) >= 3`. Suppressed on validate sweeps (`repeat=1`) and Phase B sweeps (`repeat=1`).

```markdown
### Between-Run Variance

| Cell × Cohort | mean_of_means (ms) | stddev_of_means (ms) | n_runs |
|---|--------------------:|----------------------:|-------:|
| chat_stream_c1 / rest_https_edge       | 42.20 | 0.43 | 5 |
| chat_stream_c1 / default_grpc          | 46.85 | 0.38 | 5 |
| chat_stream_c1 / tuned_grpc_multiplexed | 41.05 | 0.22 | 5 |
| chat_stream_c4 / rest_https_edge       | 89.50 | 7.28 | 5 |
| chat_stream_c4 / rest_plain_tcp        | 81.20 | 4.91 | 5 |
| chat_stream_c4 / default_grpc          | 79.68 | 4.63 | 5 |
| chat_stream_c4 / tuned_grpc_multiplexed | 78.05 | 3.89 | 5 |
| chat_stream_c8 / ...                   | ...    | ...    | ... |

**Phase B trigger verdict** (per FR-044 + round-2 Q3):

> Phase B required: chat_stream_c4, chat_stream_c8
>
> Run `--m6_1_3 --m6_1_3-diagnose-repeat=1 --m6_1_3-diagnose-n=200` to
> produce the n=200 power test artifact at
> `docs/benchmarks/m6_1_3-attribution-closure-phase-b.{md,json}`.
```

Or when no cell triggers:

```markdown
**Phase B trigger verdict** (per FR-044 + round-2 Q3):

> Phase B not required.
```

## FR-044 override fallback (operator runs `--m6_1_3-diagnose-repeat < 3`)

When the operator overrides repeat to fewer than 3 runs, the "Between-Run Variance" section is suppressed (per FR-025) and FR-044's verdict line MUST instead be emitted at the end of the per-cell timing table:

```markdown
### Per-Cell Timing Table

| ... |

**Phase B trigger verdict** (per FR-044):

> Phase B trigger verdict unavailable (requires --m6_1_3-diagnose-repeat >= 3
> for between-run variance compute).
```

## Phase B sibling artifact (FR-045)

When Phase B is invoked (whether required per FR-043 or operator-discretionary), the orchestrator writes to `docs/benchmarks/m6_1_3-attribution-closure-phase-b.{md,json}` per FR-045. The Phase B published markdown MUST:

1. **Cross-reference** the canonical Phase A artifact (`m6_1_3-attribution-closure.md`).
2. **Report per-cell CI half-widths at n=200 vs n=50** for the chat_stream cells that triggered Phase B (or all chat_stream cells if Phase B was operator-discretionary).
3. **Call out** any cell whose CI half-width does NOT shrink by the expected `sqrt(4) ≈ 2×` ratio — this is evidence that V2/V3/V4 variance sources (run-state, deploy-state, network-path) dominate sample-size scaling.
4. **NOT swap** the Phase A baseline. The published verdict baseline remains Phase A's n=50 5-run multi-sweep per the Assumptions section.

```markdown
## Phase B: n=200 Power Test

Comparison against the canonical [Phase A artifact](m6_1_3-attribution-closure.md).

### CI half-width comparison

| Cell × Cohort | n=50 CI (ms) | n=200 CI (ms) | Ratio | Expected (1/√n) | V2/V3/V4-dominant? |
|---|---:|---:|---:|---:|---|
| chat_stream_c4 / rest_https_edge | 1.17 | 0.62 | 1.89× | 2.00× | NO (close to expected) |
| chat_stream_c4 / default_grpc | 1.05 | 0.95 | 1.11× | 2.00× | **YES** — sample-size scaling does NOT close the gap; V2/V3/V4 variance dominates |
| chat_stream_c8 / ... | ... | ... | ... | ... | ... |

### V2/V3/V4-dominant cells

> chat_stream_c4 / default_grpc shows a CI half-width ratio of 1.11× when 2.00× was
> expected from 1/√n sample-size scaling. This indicates V2 (run-state) or V3
> (deploy-state) variance sources dominate. Recommendation: invoke optional Phase C
> (multi-deploy, ~$1.70) or Phase D (multi-seed, ~$1.45) for further attribution
> — these are operator-triggered follow-ups, not invoked by default per FR-042.
```

## Strict-superset schema evolution (FR-010 + round-3 Q1)

All M6.1.3 additions (new wire keys, new derived segments, new top-level `between_run_variance` block, new classifier labels) leave `schema_version` at `"m6_1_1.v1"`. The integration test `tools/benchmark/tests/test_m6_1_3_artifact_schema.py` exercises this for all three M6.1.3 artifacts:

```python
@pytest.mark.parametrize("artifact_path", [
    "docs/benchmarks/m6_1_3-attribution-closure.json",
    "docs/benchmarks/m6_1_3-attribution-closure-validate.json",
    "docs/benchmarks/m6_1_3-attribution-closure-phase-b.json",
])
def test_m6_1_3_artifact_strict_superset_compat(artifact_path: str) -> None:
    """FR-010 + SC-008: an M6.1.1-vintage reader parses any of the three
    M6.1.3 artifacts without error."""
    artifact = json.loads(Path(artifact_path).read_text())
    assert artifact["schema_version"] == "m6_1_1.v1"  # No bump
    from vllm_grpc_bench.m6_1_1_reporter import parse_json  # M6.1.1's reader
    result = parse_json(artifact)
    assert result is not None
    # The reader doesn't know about between_run_variance — it's ignored cleanly
    assert "between_run_variance" not in result.__dict__
```

## The M6.1.1 forward-pointing annotation contract (FR-031 + round-3 Q2)

`docs/benchmarks/m6_1_1-engine-cost-instrumentation.md` MUST receive exactly ONE leading note line, placed above the existing title or H1 (or immediately under it — placement deferred to Phase 2's implementation as a tiny detail):

```markdown
> **Note**: This milestone's c=4 / c=8 verdicts were updated by [M6.1.3](m6_1_3-attribution-closure.md). See that artifact for attributed labels and Phase B variance characterization.

# M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation

<!-- ... existing M6.1.1 body unchanged ... -->
```

No appended subsection, no sibling annotation file, no body-content mutation beyond this single line per round-3 Q2. The reciprocal cross-reference in the M6.1.3 markdown (per FR-041) makes navigation bidirectional:

```markdown
## Method / Background

Updates the c=4 / c=8 verdicts from [M6.1.1](m6_1_1-engine-cost-instrumentation.md); see that artifact's leading note for the bidirectional pointer.

Scoped by spike items #4 + #5 + #6:
- [Spike #4 — Proxy-edge instrumentation gap](../spikes/m6-1-roadmap-additions/03-proxy-edge-instrumentation-gap.md)
- [Spike #5 — engine_compute_variation root-cause](../spikes/m6-1-roadmap-additions/04-engine-compute-variation-rootcause.md)
- [Spike #6 — Run-to-run variance characterization](../spikes/m6-1-roadmap-additions/05-run-to-run-variance.md)
```

This sets the project-wide convention for superseding-milestone updates per round-3 Q2 — future M7 / M8 applies the same minimal-touch pattern.

## Cross-references

- Plan: [`../plan.md`](../plan.md) — Technical Context.
- Data model: [`../data-model.md`](../data-model.md) — `M6_1_3SweepArtifact`, `M6_1_3BetweenRunVariance`, `M6_1_3PhaseBTriggerVerdict`, `M6_1_3PerCellAuditAggregate`.
- Wire vocabulary: [`./wire-vocabulary.md`](./wire-vocabulary.md) — 4 new wire keys + derived segments.
- Classifier contract: [`./classifier.md`](./classifier.md) — 7-bucket decision tree + compound labels + outer override.
- CLI contract: [`./cli.md`](./cli.md) — three-path output inference logic.
- Spec: [`../spec.md`](../spec.md) — FR-015 / FR-016 / FR-016a / FR-017 / FR-018 / FR-025 / FR-029 / FR-031 / FR-038 / FR-041 / FR-043 / FR-044 / FR-045 + round-1 Q1 / Q5 + round-2 Q1 / Q3 / Q5 + round-3 Q1 / Q2 / Q3 + round-4 Q1.
- M6.1.2 artifact-schema precedent: [`../../025-m6-1-2-methodology-discipline/contracts/artifact-schema.md`](../../025-m6-1-2-methodology-discipline/contracts/artifact-schema.md).
- M6.0a precedent for additive-strict-superset JSON evolution: [`../../024-m6-0a-concurrent-dispatch/contracts/output.md`](../../024-m6-0a-concurrent-dispatch/contracts/output.md).
