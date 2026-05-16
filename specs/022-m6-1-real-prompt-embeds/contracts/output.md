# Contract: M6.1 Published Output Artifacts

**Plan**: [../plan.md](../plan.md)
**Spec FRs**: FR-020 (markdown + engine path differential), FR-021 (JSON strict superset of M6), FR-022 (engine_cost_drift_warning), FR-026 (output paths), FR-027 (RunMeta), FR-029 (chat_stream_control_drift_warning), FR-030 (engine_version comparison note), SC-005 (M6-aware consumer compatibility), SC-007 (every cell populates differential row)
**Research**: [R-4](../research.md#r-4-m6-published-json-schema-for-m6_winner_deltas-lookup), [R-5](../research.md#r-5-m6-engine_version-baseline-value-handling), [R-6](../research.md#r-6-chat_stream-control-drift-check-algorithm), [R-8](../research.md#r-8-verdict-classifier-algorithm-m61)

Two artifacts are written per successful sweep — a markdown report
(operator-facing) and a JSON companion (machine-readable, M6-superset).
Both land under `docs/benchmarks/`.

---

## 1. Markdown report

### Path

`docs/benchmarks/m6_1-real-prompt-embeds.md` (overridable via
`--m6_1-report-out` per [`cli.md`](./cli.md)).

### Required sections (in order)

```markdown
# M6.1 — Real-Prompt-Embeds Engine Path

**Status**: delivered <YYYY-MM-DD>
**Branch**: 022-m6-1-real-prompt-embeds
**JSON companion**: [m6_1-real-prompt-embeds.json](./m6_1-real-prompt-embeds.json)

## Executive Summary

<2–3 paragraphs naming the topology — same shape as M6's executive summary>

**Inference engine**: vLLM <version> (M6 baseline: vLLM <baseline_version> — see methodology note below)
**Model**: Qwen/Qwen3-8B
**Hidden size**: 4096 (fixed by model architecture)
**GPU**: A10G (24 GB VRAM)
**Modal region**: <eu-west-1>
**M6_1_BASE_SEED**: 42
**Pinned client torch**: 2.11.0 (validated at driver-start — FR-006)
**Prompt-embeds seq_len**: <pinned value> (tokenised against Qwen3-8B's tokenizer from M6's `embed_<hex>` digest format — FR-028 / R-3)
**M6 baseline source**: docs/benchmarks/m6-real-engine-mini-validation.json (m6_winner_deltas snapshotted in JSON RunMeta — FR-008)
**Bytes axis**: NOT re-measured by M6.1; M1's findings remain authoritative — encoding is structural, not engine-dependent (FR-024).

## Supersedes M6 Under enable_prompt_embeds

| # | Cell | Classification | M6 winner | M6.1 cohort means (classifier metric) | engine_cost mean | Drift flags | Notes |
|---|------|----------------|-----------|----------------------------------------|------------------|-------------|-------|
| 1 | embed × c=1 | verdict_survives | tuned_grpc_multiplexed Δ=...ms | rest=...ms / default_grpc=...ms / tuned_grpc_multiplexed=...ms | engine_forward=...ms | — | M6 picked tuned_grpc_multiplexed; M6.1 CIs non-overlapping in same direction |
| 2 | embed × c=4 | no_winner_at_n100 | (M6: no_winner_at_n100 → no usable delta) | ... | ... | — | M6 had no usable winner delta; M6.1 classifies no_winner regardless of CI overlap (FR-010 sub-clause) |
| 3 | embed × c=8 | verdict_changed | rest_https_edge Δ=...ms | ... | ... | — | CIs non-overlapping; opposite direction ⚠ |
| 4 | chat_stream × c=1 | verdict_buried_by_engine | tuned_grpc_multiplexed Δ=...ms | ... (TTFT) | engine_ttft=...ms (5.3× M6 winner) | — | CIs overlap; engine dominates |
| 5 | chat_stream × c=4 | cell_incomplete | (n/a) | (cohort n_successes < 80) | ... | — | retry budget exhausted on tuned_grpc_multiplexed |
| 6 | chat_stream × c=8 | verdict_survives | rest_https_edge Δ=...ms | ... (TTFT) | ... | ⚠ chat_stream drift, ⚠ engine drift | M6.1 CI does not overlap M6's published chat_stream CI for at least one cohort (FR-029) — embed-cell verdicts on this run weighted cautiously |

## Engine Path Differential (M6.1 − M6)

For each cell, the per-cohort classifier-metric delta (M6.1 mean − M6 mean) and the per-cell engine_cost_mean delta. Units are ms; 95% CI half-widths are combined via the standard sqrt-of-sum-of-squared-CIs formula (FR-020).

| Cell | rest_https_edge Δ (ms ± CI) | default_grpc Δ (ms ± CI) | tuned_grpc_multiplexed Δ (ms ± CI) | engine_cost_mean Δ (ms ± CI) | n_successes (per cohort) |
|------|-----------------------------|---------------------------|--------------------------------------|------------------------------|---------------------------|
| embed × c=1 | +12.3 ± 1.8 | +11.7 ± 1.6 | +11.2 ± 1.5 | +11.7 ± 1.0 | 100 / 100 / 100 |
| embed × c=4 | +14.5 ± 2.1 | +14.0 ± 2.0 | +13.6 ± 1.9 | +14.0 ± 1.2 | 100 / 100 / 100 |
| embed × c=8 | +15.8 ± 2.3 | +15.2 ± 2.2 | +14.7 ± 2.1 | +15.2 ± 1.3 | 100 / 100 / 100 |
| chat_stream × c=1 | +0.3 ± 5.4 | +0.1 ± 5.2 | +0.0 ± 5.1 | +0.1 ± 3.0 | 100 / 100 / 100 |
| chat_stream × c=4 | +0.5 ± 6.0 | (n/a — cohort cell_incomplete) | +0.2 ± 5.8 | +0.4 ± 3.4 | 100 / 65 / 100 |
| chat_stream × c=8 | +0.7 ± 7.2 | +0.4 ± 6.9 | +0.3 ± 6.7 | +0.5 ± 4.0 | 100 / 100 / 100 |

(Per SC-007: every cell populates a row, including `cell_incomplete` cells — annotated with the actual `n_successes` per cohort. embed cells show non-trivial positive deltas because the real prompt-embeds engine path is doing more work than M6's text-digest path; chat_stream cells should show ~zero delta because their engine path is unchanged from M6 per FR-005.)

## Engine Cost Per RPC

| Cell | engine_forward_ms (embed) | engine_ttft_ms (chat_stream) | engine_tpot_ms (chat_stream) | drift_warning |
|------|---------------------------|------------------------------|------------------------------|---------------|
| embed × c=1 | <mean ± CI> | n/a | n/a | <bool> |
| ... | ... | ... | ... | ... |
| chat_stream × c=8 | n/a | <mean ± CI> | <mean ± CI> | ... |

(M6.1 publishes the same Engine Cost Per RPC table M6 did, so the M7 hand-off semantics carry forward.)

## Per-Cohort Detail

### embed × c=1

| Cohort | n_successes | failure_count | wall_clock mean ± CI (ms) | engine_forward mean ± CI (ms) | RTT median (ms) |
|--------|-------------|---------------|---------------------------|-------------------------------|-----------------|
| rest_https_edge | 100 | 0 | ... | ... | ... |
| default_grpc | 100 | 0 | ... | ... | ... |
| tuned_grpc_multiplexed | 100 | 0 | ... | ... | ... |

(Repeat for the other 5 cells. Per-cohort detail tables surface n_successes and CI half-widths so the operator can read variance without parsing the JSON.)

## Smoke Result

(If smoke ran in the same invocation. Per FR-012 — 6 outcomes for 2 cells × 3 cohorts. The smoke result section MUST include the one-line note that the chat_stream control-drift check is full-sweep-only — FR-012.)

## Methodology Notes

- n=100 measurement RPCs per (cell × cohort), preceded by 10 warmup RPCs per (cell × cohort) discarded from metrics (FR-015).
- 3 cohorts measured in round-robin per c-batch order to control for Modal/network/engine drift (FR-016).
- Per-RPC sampling seeds: `SamplingParams.seed = M6_1_BASE_SEED + rpc_index`, where rpc_index is the global measurement RPC counter (warmup excluded). `M6_1_BASE_SEED=42`; recorded in RunMeta (FR-019).
- Per-RPC tensor values: `torch.Generator(device='cpu').manual_seed(M6_1_BASE_SEED + rpc_index)` then `torch.randn([seq_len, 4096], dtype=torch.float16, generator=...)`. Only the values vary per RPC; tensor shape is fixed (FR-028).
- Per-RPC failures retried up to 3 attempts; cells with any cohort < 80 successes are classified `cell_incomplete` (FR-017).
- Verdict classifier: deterministic; comparison metric is client-observed TTFT for chat_stream, total wall-clock for embed (FR-011). Cells whose M6 verdict was `no_winner_at_n100`, `cell_incomplete`, OR `verdict_buried_by_engine` classify as `no_winner_at_n100` regardless of M6.1 CI overlap (FR-010 sub-clause). engine_cost (cohort-averaged simple unweighted mean per FR-022) ≥ 5× |M6 winner delta| classifies a no-overlap cell as `verdict_buried_by_engine`. Per-cohort engine_cost disagreement > 10% sets the `engine_cost_drift_warning` flag (verdict still computed; per-cohort values surfaced).
- chat_stream control-drift check (FR-029): each chat_stream cell × cohort's M6.1 95% CI on TTFT is compared against M6's published 95% CI; non-overlap on at least one cohort sets the `chat_stream_control_drift_warning` flag on that cell. Diagnostic only — verdicts still computed. The flag's presence on any chat_stream cell signals that infrastructure or engine drift may have contaminated the same-sweep embed-cell verdicts.
- Engine instance: ONE `AsyncLLM(Qwen/Qwen3-8B, dtype=fp16, enable_prompt_embeds=True, max_model_len=2048, gpu_memory_utilization=0.92)` loaded once at sweep start; serves all 6 cells (FR-014). Cold-start excluded from per-RPC latency, recorded as scalar `cold_start_s` in RunMeta. Engine config UNCHANGED from M6 per FR-007.
- Engine version comparison (FR-030): M6.1's pinned vLLM version is **<engine_version>** (read from `pyproject.toml`); the M6 baseline JSON's recorded vLLM version is **<m6_baseline_engine_version>**. <If they differ or either is `unknown`:> NOTE: the comparison is informational; the "Engine path differential" read is cleanest when both versions match. The legacy M6 baseline records `engine_version=unknown` because M6's version-reader helper landed post-sweep — future M6 republishes feed cleanly through the same plumbing.
- Client torch version: **2.11.0** (matches vllm==0.20.1's transitive pin per FR-006). The driver validates `torch.__version__` at driver-start and exits with a clear actionable error if mismatched.

## Operator Reproducibility

To reproduce this run bit-exactly: same git_sha, same vLLM engine version, same client torch version, same Modal region, same `M6_1_BASE_SEED`, and the same M6 baseline JSON (snapshotted in `run_meta.m6_winner_deltas`). The classifier is deterministic given these inputs (SC-006).
```

### FR-020 executive section requirements

The Executive Summary section MUST name the inference engine, model
identifier, hidden_size, Modal region, GPU type, **plus** the pinned
client `torch` version and the pinned `seq_len` value within the first
screenful of content. The header block above discharges this requirement.

### Cell-row markers

| Marker | Meaning | When applied |
|---|---|---|
| (none) | Standard verdict | All clean cases |
| `⚠ engine drift` | `engine_cost_drift_warning == True` (FR-022) | Surfaced in Drift flags column with footnote naming per-cohort engine_cost means |
| `⚠ chat_stream drift` | `chat_stream_control_drift_warning == True` (FR-029) | Surfaced in Drift flags column only for chat_stream cells; embed cells inherit the warning's implications via the methodology note |
| `cell_incomplete` | Any cohort had < 80 successes (FR-017) | Surfaced as the Classification value (NOT folded into a verdict bucket) |

### Verdict-direction conventions

- `verdict_survives` — M6.1 CIs non-overlapping in same direction as M6 published winner.
- `verdict_changed` — M6.1 CIs non-overlapping in opposite direction. **Always include a `⚠` footnote** noting the direction flip.
- `verdict_buried_by_engine` — M6.1 CIs overlap AND engine_cost ≥ 5× M6 winner delta.
- `no_winner_at_n100` — M6.1 CIs overlap AND engine_cost < 5× M6 winner delta, OR M6 itself had no usable winner delta (M6 verdict was `no_winner_at_n100`, `cell_incomplete`, OR `verdict_buried_by_engine` — FR-010 sub-clause).
- `cell_incomplete` — Any cohort < 80 successes (FR-017).

---

## 2. JSON companion

### Path

`docs/benchmarks/m6_1-real-prompt-embeds.json` (overridable via
`--m6_1-report-json-out` per [`cli.md`](./cli.md)).

### Top-level shape

The JSON companion is a strict superset of M6's published JSON schema
(FR-021). Existing M6-aware consumers MUST continue to work unmodified
against M6.1's JSON.

```json
{
  // ===== M6-strict-superset fields (FR-021 — preserved structurally) =====
  "schema_version": "m6_1.v1",
  "run_id": "2026-05-16T12:00:00Z-<git_sha>",
  "run_started_at": "2026-05-16T12:00:00Z",
  "run_completed_at": "2026-05-16T13:25:00Z",
  "harness_version_sha": "<git_sha>",
  "modal_region": "eu-west-1",
  "modal_instance_class": "A10G",
  "modal_metadata": { "function_id": "fn-...", "...": "..." },
  "client_external_geolocation": { "country": "US", "city": "..." },
  "rtt_distribution": { /* per-cohort RTT probe results */ },
  "https_edge_endpoint": "https://...",
  "events_sidecar_path": "docs/benchmarks/m6_1-events-2026-05-16.jsonl.gz",
  "cohorts": [ /* per-cohort summaries in M6 shape */ ],
  "protocol_comparison_verdicts": [ /* per-cell verdict rows in M6 shape — populated from M6.1 classifier output */ ],
  "transport_only_verdicts": [],
  "channel_axis_recommendations": [],
  "schema_candidate_recommendations": [],
  "shared_baseline_cohorts": [],
  "smoke_run_outcome": { /* M6_1SmokeResult shape (parallel to M6's M6SmokeResult) */ },
  "supersedes_m1_time": null,
  "supersedes_m3": null,
  "supersedes_m4": null,
  "supersedes_m5_1": null,
  "supersedes_m5_2_under_real_engine": [
    /* M6's verdict table passthrough — M6.1 publishes M6's section here so M6-aware
       readers that index by this key still find the M5.2-derived verdicts (one level back).
       Snapshot at sweep launch; not re-computed. */
  ],
  "engine_cost_baseline": [
    /* M6-shape engine-cost table — M6.1 publishes its own per-cell engine_forward / TTFT / TPOT means here */
  ],
  "symmetry": { /* M6-shape symmetry audit */ },
  "payload_parity_audit": null,

  // ===== M6.1-specific additions (strict superset per FR-021) =====
  "supersedes_m6_under_enable_prompt_embeds": [
    {
      "cell": { "path": "embed", "hidden_size": 4096, "concurrency": 1 },
      "classification": "verdict_survives",
      "classifier_metric": "wall_clock_ms",
      "cohort_pair": ["rest_https_edge", "tuned_grpc_multiplexed"],
      "m6_winner_delta_ms": 51.0,
      "m6_winner_direction": "grpc_wins",
      "engine_cost_mean_ms": 24.0,
      "engine_cost_drift_warning": false,
      "chat_stream_control_drift_warning": false,
      "per_cohort_engine_cost_mean_ms": null,
      "per_cohort_classifier_metric": {
        "rest_https_edge": { "mean_ms": 246.8, "ci_lower_ms": 242.1, "ci_upper_ms": 251.5, "n_successes": 100 },
        "default_grpc":    { "mean_ms": 209.4, "ci_lower_ms": 205.6, "ci_upper_ms": 213.2, "n_successes": 100 },
        "tuned_grpc_multiplexed": { "mean_ms": 194.6, "ci_lower_ms": 190.6, "ci_upper_ms": 198.6, "n_successes": 100 }
      },
      "notes": "M6 picked tuned_grpc_multiplexed; M6.1 CIs non-overlapping in same direction"
    }
    // ... 5 more entries — one per cell
  ],
  "engine_path_differential": [
    {
      "cell": { "path": "embed", "hidden_size": 4096, "concurrency": 1 },
      "per_cohort_classifier_metric_delta_ms": {
        "rest_https_edge": 12.3,
        "default_grpc": 11.3,
        "tuned_grpc_multiplexed": 11.2
      },
      "per_cohort_classifier_metric_delta_ci_half_width_ms": {
        "rest_https_edge": 1.8,
        "default_grpc": 1.6,
        "tuned_grpc_multiplexed": 1.5
      },
      "engine_cost_mean_delta_ms": 11.7,
      "engine_cost_mean_delta_ci_half_width_ms": 1.0,
      "per_cohort_n_successes": {
        "rest_https_edge": 100,
        "default_grpc": 100,
        "tuned_grpc_multiplexed": 100
      }
    }
    // ... 5 more entries — one per cell, populated even for cell_incomplete cells per SC-007
  ],
  "run_meta": {
    "git_sha": "<git_sha>",
    "hostname": "ben-mbp.local",
    "modal_function_id": "fn-...",
    "gpu_type": "A10G",
    "modal_region": "eu-west-1",
    "model_identifier": "Qwen/Qwen3-8B",
    "hidden_size": 4096,
    "M6_1_BASE_SEED": 42,
    "seq_len": 8,
    "engine_version": "0.20.1",
    "m6_baseline_engine_version": "unknown",
    "torch_version": "2.11.0",
    "m6_winner_deltas": {
      "embed_c1_h4096": 51.0,
      "embed_c4_h4096": null,
      "embed_c8_h4096": 8.7,
      "chat_stream_c1_h4096": 1.14,
      "chat_stream_c4_h4096": null,
      "chat_stream_c8_h4096": null
    },
    "cold_start_s": 28.4,
    "max_model_len": 2048,
    "gpu_memory_utilization": 0.92,
    "run_started_at": "2026-05-16T12:00:00Z",
    "run_completed_at": "2026-05-16T13:25:00Z"
  },
  "m6_meta": {
    /* Back-reference passthrough copy of M6's m6_meta block — same shape M6 published,
       carries the M6 baseline's recorded engine_version + m5_2_winner_deltas, so
       M6-aware consumers indexing by `m6_meta` (instead of `run_meta`) still
       resolve to the upstream baseline. Populated by the harness from the M6
       baseline JSON's m6_meta block at sweep launch. */
  }
}
```

### Field-by-field provenance (M6.1-specific)

| JSON path | Source | Spec FR |
|---|---|---|
| `schema_version` | constant `"m6_1.v1"` | (M6 superset) |
| `supersedes_m6_under_enable_prompt_embeds[]` | NEW — M6.1 verdict table rows | FR-020 / US1 |
| `engine_path_differential[]` | NEW — M6.1 − M6 differential | FR-020 / US2 / SC-007 |
| `run_meta.m6_winner_deltas` | snapshot from `docs/benchmarks/m6-real-engine-mini-validation.json` at sweep launch (see [R-4](../research.md#r-4-m6-published-json-schema-for-m6_winner_deltas-lookup)) | FR-008 / FR-027 |
| `run_meta.seq_len` | pinned at sweep start by tokenising the M6 text-digest format under the loaded model's tokenizer | FR-027 / FR-028 / R-3 |
| `run_meta.engine_version` | M6.1's pinned `vllm` version, read from `pyproject.toml` | FR-027 / FR-030 |
| `run_meta.m6_baseline_engine_version` | from M6 baseline JSON's `m6_meta.engine_version` field | FR-030 |
| `run_meta.torch_version` | from `torch.__version__` after FR-006 validation passes | FR-006 / FR-027 |
| `run_meta.M6_1_BASE_SEED` | from `--m6_1-base-seed` flag (default 42) | FR-019 / FR-027 |
| `m6_meta` (back-reference) | passthrough copy from M6 baseline JSON's `m6_meta` block | FR-021 |
| `supersedes_m6_under_enable_prompt_embeds[].chat_stream_control_drift_warning` | set per chat_stream cell from FR-029 CI-overlap check; always `false` on embed cells | FR-029 / R-6 |

### Strict-superset compatibility test

A unit test MUST verify that `m6_1-real-prompt-embeds.json` validates
against M6's published JSON schema (FR-021 / SC-005). The harness ships
M6's schema expectations via `m6_supersede.py`'s loader; the M6.1 test
re-runs that loader against a representative M6.1 sample JSON to confirm
no field shape drift.

### M5.2-aware consumer compatibility (downstream of M6)

The strict-superset chain is M5.2 → M6 → M6.1. Because M6.1's JSON is a
strict superset of M6's, and M6's JSON was a strict superset of M5.2's,
M5.2-aware consumers also continue to work against M6.1's JSON without
modification. The `cohorts[]`, `protocol_comparison_verdicts[]`, etc.
fields preserved structurally per FR-021.

---

## 3. Per-RPC events JSONL sidecar

### Path

Per `--m6_1-events-sidecar-out` (default under `docs/benchmarks/` —
auto-generated as `m6_1-events-<timestamp>.jsonl.gz`). Gzipped JSONL stream.

### Record shape

See [`data-model.md`](../data-model.md) `M6_1PerRequestEvent`. The shape is
identical to M6's `M6PerRequestEvent` — the engine_cost fields, retry
counts, rpc_phase, rpc_index, and seed are reused unchanged. The only
addition is that on embed cells, the `engine_forward_ms` value now
reflects the cost of the real prompt-embeds forward (vs M6's text-prompt
forward).

The events sidecar is the per-RPC reproducibility ledger: any anomalous
cell verdict can be cross-referenced to per-RPC engine_cost values, retry
counts, and seeds for forensic analysis without re-running the sweep.
