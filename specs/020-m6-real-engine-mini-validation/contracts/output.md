# Contract: Published Output Artifacts

**Plan**: [../plan.md](../plan.md)
**Spec FRs**: FR-013 (output paths), FR-014 (verdict table), FR-015 (executive section), FR-016 (strict superset of M5.2 schema), FR-018 (RunMeta), FR-020 (bytes-axis preservation note), FR-023 (cell_incomplete in verdict table)
**Research**: [R-5](../research.md#r-5-m52-published-json-schema-for-winner-delta-lookup), [R-7](../research.md#r-7-verdict-classifier-algorithm)

Two artifacts are written per successful sweep — a markdown report (operator-facing) and a JSON companion (machine-readable, M5.2-superset). Both land under `docs/benchmarks/`.

---

## 1. Markdown report

### Path

`docs/benchmarks/m6-real-engine-mini-validation.md` (overridable via `--m6-report-out` per `contracts/cli.md`).

### Required sections (in order)

```markdown
# M6 — Real-Engine Mini-Validation

**Status**: delivered <YYYY-MM-DD>
**Branch**: 020-m6-real-engine-mini-validation
**JSON companion**: [m6-real-engine-mini-validation.json](./m6-real-engine-mini-validation.json)

## Executive Summary

<2–3 paragraphs naming the topology — see FR-015 requirements below>

**Inference engine**: vLLM <version>
**Model**: <Qwen/Qwen3-8B>
**Hidden size**: 4096 (fixed by model architecture)
**GPU**: A10G (24 GB VRAM)
**Modal region**: <eu-west-1>
**M6_BASE_SEED**: 42
**M5.2 baseline source**: docs/benchmarks/m5_2-transport-vs-tuning.json (snapshot in JSON RunMeta — FR-018)
**Bytes axis**: NOT re-measured by M6; M1's findings (~89% chat / ~25% embed reductions) remain authoritative — encoding is structural, not engine-dependent (FR-020).

## Supersedes M5.2 Under Real Engine

| # | Cell | Classification | M5.2 winner | M6 cohort means (classifier metric) | engine_cost mean | Notes |
|---|------|----------------|-------------|--------------------------------------|------------------|-------|
| 1 | embed × c=1 | verdict_survives | tuned_grpc (M5.2 c=1 cohort name) Δ=−51.0 ms | rest=...ms / default_grpc=...ms / tuned_grpc_multiplexed=...ms | engine_forward=...ms | non-overlapping CI; same direction |
| 2 | embed × c=4 | no_winner_at_n100 | (M5.2: no_winner) | ... | ... | CIs overlap; no M5.2 baseline to compare |
| 3 | embed × c=8 | verdict_changed | rest_https_edge Δ=...ms | ... | ... | CIs non-overlapping; opposite direction ⚠ |
| 4 | chat_stream × c=1 | verdict_buried_by_engine | tuned_grpc Δ=...ms | ... (TTFT) | engine_ttft=2400ms (5.2× M5.2 winner) | CIs overlap; engine dominates |
| 5 | chat_stream × c=4 | cell_incomplete | (n/a) | (cohort n_successes < 80) | ... | retry budget exhausted on tuned_grpc_multiplexed |
| 6 | chat_stream × c=8 | verdict_survives | rest_https_edge Δ=...ms | ... (TTFT) | ... ⚠ engine drift | non-overlapping; same direction; engine_cost_drift_warning=true |

## Engine Cost Per RPC

| Cell | engine_forward_ms (embed) | engine_ttft_ms (chat_stream) | engine_tpot_ms (chat_stream) | drift_warning |
|------|---------------------------|------------------------------|------------------------------|---------------|
| embed × c=1 | <mean ± CI> | n/a | n/a | <bool> |
| embed × c=4 | ... | n/a | n/a | ... |
| embed × c=8 | ... | n/a | n/a | ... |
| chat_stream × c=1 | n/a | <mean ± CI> | <mean ± CI> | <bool> |
| chat_stream × c=4 | n/a | ... | ... | ... |
| chat_stream × c=8 | n/a | ... | ... | ... |

(This table is the M7 hand-off — see [`spec.md` SC-006](../spec.md))

## Per-Cohort Detail

### embed × c=1

| Cohort | n_successes | failure_count | wall_clock mean ± CI (ms) | engine_forward mean ± CI (ms) | RTT median (ms) |
|--------|-------------|---------------|---------------------------|-------------------------------|-----------------|
| rest_https_edge | 100 | 0 | ... | ... | ... |
| default_grpc | 100 | 0 | ... | ... | ... |
| tuned_grpc_multiplexed | 99 | 1 | ... | ... | ... |

(Repeat for the other 5 cells.)

## Smoke Result

(If smoke ran in the same invocation. Per FR-011 — 6 outcomes for 2 cells × 3 cohorts.)

## Methodology Notes

- n=100 measurement RPCs per (cell × cohort), preceded by 10 warmup RPCs per (cell × cohort) discarded from metrics (FR-021).
- 3 cohorts measured in round-robin per c-batch order to control for Modal/network/engine drift (FR-022).
- Per-RPC sampling seeds: SamplingParams.seed = M6_BASE_SEED + rpc_index, where rpc_index is the global measurement RPC counter (warmup excluded). M6_BASE_SEED=42; recorded in RunMeta (FR-025).
- Per-RPC failures retried up to 3 attempts; cells with any cohort < 80 successes are classified `cell_incomplete` (FR-023).
- Verdict classifier: deterministic; comparison metric is client-observed TTFT for chat_stream, total wall-clock for embed (FR-014). Engine cost (cohort-averaged) ≥ 5× |M5.2 winner delta| classifies a no-overlap cell as `verdict_buried_by_engine`. Per-cohort engine_cost disagreement > 10% sets the `engine_cost_drift_warning` flag (verdict still computed; per-cohort values surfaced).
- Engine instance: ONE AsyncLLM(Qwen/Qwen3-8B, dtype=fp16, enable_prompt_embeds=True) loaded once at sweep start; serves all 6 cells (FR-024). Cold-start excluded from per-RPC latency, recorded as scalar `cold_start_s` in RunMeta (FR-019).

## Operator Reproducibility

To reproduce this run bit-exactly: same git_sha, same engine version, same Modal region, same `M6_BASE_SEED`. The classifier is deterministic given the same M5.2 baseline JSON (snapshot in RunMeta).
```

### FR-015 executive section requirements

The Executive Summary section MUST name the inference engine, model identifier, hidden_size, Modal region, and GPU type within the first screenful of content (FR-015 / SC-005). The header block above (Inference engine / Model / Hidden size / GPU / Modal region) discharges this requirement.

### Cell-row markers

| Marker | Meaning | When applied |
|---|---|---|
| (none) | Standard verdict | All clean cases |
| `⚠ engine drift` | `engine_cost_drift_warning == True` (FR-014 sub-clause) | Surfaced in Notes column with footnote naming per-cohort engine_cost means |
| `cell_incomplete` | Any cohort had < 80 successes (FR-023) | Surfaced as the Classification value (NOT folded into a verdict bucket) |

### Verdict-direction conventions

- `verdict_survives` — M6 CIs non-overlapping in same direction as M5.2 published winner.
- `verdict_changed` — M6 CIs non-overlapping in opposite direction. **Always include a `⚠` footnote** noting the direction flip.
- `verdict_buried_by_engine` — M6 CIs overlap AND engine_cost ≥ 5× M5.2 winner delta.
- `no_winner_at_n100` — M6 CIs overlap AND engine_cost < 5× M5.2 winner delta (or M5.2 itself was no_winner).
- `cell_incomplete` — Any cohort < 80 successes (FR-023).

---

## 2. JSON companion

### Path

`docs/benchmarks/m6-real-engine-mini-validation.json` (overridable via `--m6-report-json-out` per `contracts/cli.md`).

### Top-level shape

The JSON companion is a strict superset of M5.2's published JSON schema (FR-016). Existing M5.2-aware consumers (the `m5_2_supersede` classifier, downstream M5.1 supersession code) MUST continue to work unmodified against M6's JSON.

```json
{
  // ===== M5.2-strict-superset fields (FR-016 — preserved structurally) =====
  "schema_version": "m6.v1",
  "run_id": "2026-05-14T18:23:14Z-be99919",
  "run_started_at": "2026-05-14T18:23:14Z",
  "run_completed_at": "2026-05-14T19:42:01Z",
  "harness_version_sha": "be99919",
  "modal_region": "eu-west-1",
  "modal_instance_class": "A10G",
  "modal_metadata": { "function_id": "fn-...", "..." : "..." },
  "client_external_geolocation": { "country": "US", "city": "..." },
  "rtt_distribution": { /* per-cohort RTT probe results — FR-010 */ },
  "https_edge_endpoint": "https://...",
  "events_sidecar_path": "docs/benchmarks/m6-events-2026-05-14.jsonl.gz",
  "cohorts": [ /* per-cohort summaries in M5.2 shape */ ],
  "protocol_comparison_verdicts": [ /* per-cell verdict rows in M5.2 shape — populated from M6 classifier */ ],
  "transport_only_verdicts": [],   // empty in M6 (transport-only deltas already characterised by M5.2)
  "channel_axis_recommendations": [],   // empty in M6 (deferred axis)
  "schema_candidate_recommendations": [],   // empty in M6 (deferred axis)
  "shared_baseline_cohorts": [],   // empty in M6 (no shared baseline; M6 measures fresh)
  "smoke_run_outcome": { /* M6SmokeResult shape */ },
  "supersedes_m1_time": null,
  "supersedes_m3": null,
  "supersedes_m4": null,
  "supersedes_m5_1": null,
  "symmetry": { /* M5.2 symmetry audit shape */ },
  "payload_parity_audit": null,

  // ===== M6-specific additions (strict superset) =====
  "supersedes_m5_2_under_real_engine": [
    {
      "cell": { "path": "embed", "hidden_size": 4096, "concurrency": 1 },
      "classification": "verdict_survives",
      "classifier_metric": "wall_clock_ms",
      "cohort_pair": ["rest_https_edge", "tuned_grpc_multiplexed"],
      "m5_2_winner_delta_ms": 51.0,
      "m5_2_winner_direction": "grpc_wins",
      "engine_cost_mean_ms": 12.345,
      "engine_cost_drift_warning": false,
      "per_cohort_engine_cost_mean_ms": null,   // populated only when drift_warning=true
      "per_cohort_classifier_metric": {
        "rest_https_edge": { "mean_ms": 234.5, "ci_lower_ms": 230.0, "ci_upper_ms": 239.0, "n_successes": 100 },
        "default_grpc":    { "mean_ms": 198.1, "ci_lower_ms": 194.5, "ci_upper_ms": 201.7, "n_successes": 100 },
        "tuned_grpc_multiplexed": { "mean_ms": 183.4, "ci_lower_ms": 179.6, "ci_upper_ms": 187.2, "n_successes": 100 }
      },
      "notes": "M5.2 picked tuned_grpc; M6 CIs non-overlapping in same direction"
    }
    // ... 5 more entries
  ],
  "engine_cost_baseline": [
    {
      "cell": { "path": "embed", "hidden_size": 4096, "concurrency": 1 },
      "engine_forward_mean_ms": 12.345,
      "engine_forward_ci_half_width_ms": 0.234,
      "engine_ttft_mean_ms": null,
      "engine_tpot_mean_ms": null,
      "drift_warning": false
    }
    // ... 5 more entries
  ],
  "m6_meta": {
    "model_identifier": "Qwen/Qwen3-8B",
    "engine_version": "vllm 0.20.0",
    "cold_start_s": 28.4,
    "m5_2_winner_deltas": {
      "embed_c1_h4096": 51.0,
      "embed_c4_h4096": 12.3,
      "embed_c8_h4096": 8.7,
      "chat_stream_c1_h4096": 1.14,
      "chat_stream_c4_h4096": 16.0,
      "chat_stream_c8_h4096": null   // M5.2 verdict was no_winner for this cell
    },
    "m6_base_seed": 42,
    "git_sha": "be99919",
    "hostname": "ben-mbp.local",
    "gpu_type": "A10G"
  }
}
```

### Field-by-field provenance

| JSON path | Source | Spec FR |
|---|---|---|
| `schema_version` | constant `"m6.v1"` | (M5.2 superset) |
| `harness_version_sha` | git_sha | FR-018 |
| `cohorts[]` | M5.2-shape per-cohort summaries (M6 reuses the same shape) | FR-016 |
| `protocol_comparison_verdicts[]` | populated with M6 classifier output in M5.2 shape | FR-014 / FR-016 |
| `supersedes_m5_2_under_real_engine[]` | NEW — M6 verdict table rows | FR-014 |
| `engine_cost_baseline[]` | NEW — M7 hand-off | SC-006 |
| `m6_meta.cold_start_s` | scalar | FR-019 / FR-024 |
| `m6_meta.m5_2_winner_deltas` | snapshot from `docs/benchmarks/m5_2-transport-vs-tuning.json` at sweep launch | FR-018 / FR-014 |
| `m6_meta.m6_base_seed` | from `--m6-base-seed` flag (default 42) | FR-018 / FR-025 |

### Strict-superset compatibility test

A unit test MUST verify that `m6_run.json` validates against M5.2's published JSON schema (FR-016). The harness ships an M5.2 schema validator (`m5_2_supersede.py` reads the file using its own type expectations); the M6 test re-runs that validator against an M6 sample JSON to confirm no field shape drift.

---

## 3. Per-RPC events JSONL sidecar

### Path

Per `--m6-events-sidecar-out` (default under `docs/benchmarks/`). Gzipped JSONL stream.

### Record shape

See [`data-model.md`](../data-model.md) `M6PerRequestEvent`. The shape extends M5.2's `PerRequestEventRecord` with three new fields:
- `rpc_phase` — `warmup` or `measurement`
- `rpc_index` — global measurement-RPC counter (None for warmup)
- `seed` — `M6_BASE_SEED + rpc_index` (None for warmup)
- engine_cost trio — `engine_forward_ms`, `engine_ttft_ms`, `engine_tpot_ms`

The events sidecar is the per-RPC reproducibility ledger: any anomalous cell verdict can be cross-referenced to per-RPC engine_cost values, retry counts, and seeds for forensic analysis without re-running the sweep.
