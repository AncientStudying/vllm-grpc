# M6.1.1 Output Contract

**Plan**: [../plan.md](../plan.md) | **Spec**: [../spec.md](../spec.md) | **Data model**: [../data-model.md](../data-model.md) | **CLI**: [cli.md](./cli.md) | **Instrumentation**: [instrumentation.md](./instrumentation.md)

Defines the shape of M6.1.1's published artifacts: markdown report, JSON companion, supersedence annotations on M6.1's published files, sidecar events.

---

## Output paths

| Path | Author | When written | Format |
| :-- | :-- | :-- | :-- |
| `docs/benchmarks/m6_1_1-engine-cost-instrumentation.md` | M6.1.1 reporter | Each `--m6_1_1-diagnose` and `--m6_1_1` invocation (overwrite) | Markdown |
| `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` | M6.1.1 reporter | Same (overwrite with `phase_1_runs[]` preserved per round-3 Q1) | JSON (schema_version `m6_1_1.v1`) |
| `docs/benchmarks/m6_1_1-events.jsonl` | M6.1.1 reporter | Each `--m6_1_1-diagnose` / `--m6_1_1` run (append) | JSONL (per-RPC events) |
| `docs/benchmarks/m6_1-real-prompt-embeds.json` | M6.1.1 supersedence | First successful M6.1.1 close (additive write) | JSON — adds top-level `methodology_supersedence` key |
| `docs/benchmarks/m6_1-real-prompt-embeds.md` | M6.1.1 supersedence | First successful M6.1.1 close (additive write) | Markdown — adds one-line forward pointer in chat_stream verdict section |
| `contracts/instrumentation.md` (project-level) | Operator (Phase 2(b) only) | Manual edit before `--m6_1_1` validates | Markdown — adds `## M6.1.1: ...` heading |

---

## Markdown report shape (FR-019 / FR-020)

6 sections in fixed order. Renders identically across all `phase_2_path` outcomes (the section content adapts but the section structure is invariant).

### Section 1: Executive Summary

Top-of-file. Conveys the milestone status in ≤ 8 lines.

**Under Phase 2(a) verified:**
```markdown
# M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation

**Run**: `2026-MM-DDTHH:MM:SSZ-<git-sha-short>` | **Phase 2 path**: `phase_2a_verified` ✅
**Phase 1 classifications** (chat_stream cells, c=1 / c=4 / c=8): `instrumentation_artifact` × 3 (uniform)
**Phase 2(a) outcome**: drift cleared on all 3 chat_stream cells; each cohort within 5% of unweighted cohort-average.
**Embed regression check**: 0 warnings of 9 (cell × cohort) entries; all within ±5% of M6.1's published means.
**Fresh baselines published**: `chat_stream_baseline_post_symmetrisation` (9 entries), `embed_baseline_post_symmetrisation` (9 entries).
**M6.1 supersedence annotations**: written to `m6_1-real-prompt-embeds.{md,json}` in this PR.
```

**Under Phase 2(b) documented:**
```markdown
# M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation

**Run**: `...` | **Phase 2 path**: `phase_2b_documented` 📝
**Phase 1 classifications**: `channel_dependent_batching` × 3 (uniform)
**Phase 2(b) outcome**: doc-only; `contracts/instrumentation.md` § "M6.1.1: Channel-Dependent Batching Effect" added.
**M6.1 baseline status**: numbers preserved as published; per-cohort `engine_ttft_ms` interpretation rule landed in contracts.
```

**Under drift_not_reproduced_confirmed:**
```markdown
# M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation

**Run**: `...` | **Phase 2 path**: `drift_not_reproduced_confirmed` ⚠
**Phase 1 (run 1) classifications**: `drift_not_reproduced` × 3
**Phase 1 (run 2) classifications**: `drift_not_reproduced` × 3 (confirming)
**Phase 2 outcome**: NONE — M6.1's `engine_cost_drift_warning` preserved as published; `methodology_supersedence` annotation records non-reproduction.
```

**Under split_required (round-2 Q4):**
```markdown
# M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation

**Run**: `...` | **Phase 2 path**: `split_required` 🪓
**Phase 1 (run 1) classifications**: <c1>, <c2>, <c3>  
**Phase 1 (run 2) classifications**: <c1>, <c2>, <c3> (still divergent)
**Phase 2 outcome**: NONE — heterogeneous Phase 2 disallowed; open successor sub-milestones (proposal: <operator-supplied split>).
**M6.2 status**: BLOCKED (SC-008 anchor → `baseline_source = "not_applicable"`) until ≥1 successor sub-milestone publishes.
```

### Section 2: Methodology

Engine version, hardware, torch pin, baseline file path, perturbation budget audit, M6.1 baseline `engine_version` vs M6.1.1 deployed version comparison. Format mirrors M6.1's methodology section.

### Section 3: Multi-Point Timing Table

The data the operator needs to reproduce the classifier by hand. One sub-section per Phase 1 run (typically just one; up to two under FR-017 / FR-018 fallback paths). Each sub-section contains a markdown table with one row per (cohort × cell) = 18 rows for the 6×3 matrix.

Columns: `cell`, `cohort`, `engine_ttft_ms (95% CI)`, `seg_ab_ms (95% CI)`, `seg_bc_ms (95% CI)`, `seg_cd_ms (95% CI)`, `perturbation_audit µs`, `n_successes`.

Worked example row:
```text
| chat_stream c=8 | tuned_grpc_multiplexed | 41.5 ± 0.8 | 2.1 ± 0.3 | 38.8 ± 0.7 | 0.6 ± 0.05 | 0.24 | 50 |
```

### Section 4: Root-Cause Attribution

One sub-section per chat_stream cell. For each:
- The cell's classification (with the magnitude-equivalence formula applied — operator can verify by hand).
- The segment carrying the spread (`seg_ab`, `seg_bc`, or "neither dominates").
- 2–4 sentences of narrative interpreting the segment-level evidence.

### Section 5: Phase 2 Outcome

The section's content branches by `phase_2_path`:
- **Phase 2(a)**: drift-cleared status per cell + new per-cohort `engine_ttft_ms` means + embed regression check summary + fresh baseline tables (`chat_stream_baseline_post_symmetrisation` rendered as a 9-row table; `embed_baseline_post_symmetrisation` likewise).
- **Phase 2(b)**: link to the `contracts/instrumentation.md` § that was added, the matched heading line, a paragraph summarising the documented interpretation rule.
- **drift_not_reproduced_confirmed**: brief explanatory paragraph; M6.1 flag preservation note.
- **split_required**: per-cell divergent classifications across both Phase 1 runs + operator-supplied proposal for the successor sub-milestone split.
- **phase_2_pending** (intermediate): "Phase 2 not yet run — under `instrumentation_artifact` apply symmetrisation and run `--m6_1_1`; under `channel_dependent_batching` update `contracts/instrumentation.md` and run `--m6_1_1`".

### Section 6: Methodology Supersedence

One paragraph + links:
- Forward pointer text written into `m6_1-real-prompt-embeds.md` (one line, copied verbatim here for audit).
- JSON annotation written into `m6_1-real-prompt-embeds.json` (the `methodology_supersedence` key's value, copied here).
- (If `embed_regression_acknowledged == True`) the per-row supersedence notes added to M6.1's `supersedes_m6_under_enable_prompt_embeds` rows.

---

## JSON companion shape (FR-021)

The top-level schema for `m6_1_1-engine-cost-instrumentation.json` (Pydantic-serialised; round-trips through `M6_1_1Run` per data-model.md). All keys are present under every `phase_2_path`; non-applicable fields use the sentinel-object shape (round-2 Q1).

```json
{
  "schema_version": "m6_1_1.v1",
  "run_id": "2026-MM-DDTHH:MM:SSZ-<sha7>",
  "run_started_at": "2026-MM-DDTHH:MM:SSZ",
  "run_completed_at": "2026-MM-DDTHH:MM:SSZ",
  "run_meta": {
    "git_sha": "...",
    "hostname": "...",
    "modal_function_id": "...",
    "gpu_type": "A10G",
    "modal_region": "eu-west-1",
    "model_identifier": "Qwen/Qwen3-8B",
    "hidden_size": 4096,
    "cold_start_s": 28.4,
    "max_model_len": 2048,
    "gpu_memory_utilization": 0.92,
    "engine_version": "0.20.1",
    "m6_1_baseline_engine_version": "0.20.1",
    "torch_version": "2.11.0",
    "M6_1_1_BASE_SEED": 42,
    "seq_len": 8,
    "phase_1_n": 50,
    "phase_2_path": "phase_2a_verified",
    "run_started_at": "...",
    "run_completed_at": "..."
  },
  "phase_1_classifications": {
    "chat_stream_c1_h4096": "instrumentation_artifact",
    "chat_stream_c4_h4096": "instrumentation_artifact",
    "chat_stream_c8_h4096": "instrumentation_artifact"
  },
  "phase_1_runs": [
    {
      "run_id": "...",
      "run_started_at": "...",
      "run_completed_at": "...",
      "wall_clock_s": 1782.4,
      "multi_point_timings": [/* 18 entries */],
      "phase_1_classifications": {/* 3 entries */},
      "perturbation_audit": {/* see data-model.md */},
      "n_per_cohort": 50
    }
  ],
  "multi_point_timings": [/* 18 entries — most recent run only; see phase_1_runs[-1] for older */],
  "phase_2_outcome": {/* discriminated union — see data-model.md */},
  "phase_2_choice": null,
  "chat_stream_baseline_post_symmetrisation": {
    "phase_2_path": "phase_2a_verified",
    "baseline_source": "m6_1_1",
    "pointer": "docs/benchmarks/m6_1_1-engine-cost-instrumentation.json",
    "cells": [/* 9 entries — (3 chat_stream cells × 3 cohorts) */]
  },
  "embed_baseline_post_symmetrisation": {
    "phase_2_path": "phase_2a_verified",
    "baseline_source": "m6_1_1",
    "pointer": "docs/benchmarks/m6_1_1-engine-cost-instrumentation.json",
    "cells": [/* 9 entries — (3 embed cells × 3 cohorts) */]
  },
  "embed_regression_check": {
    "per_entry": [/* 9 entries */],
    "n_warnings": 0,
    "all_within_tolerance": true,
    "acknowledged_count": 0
  },
  "m6_1_baseline_pointer": "docs/benchmarks/m6_1-real-prompt-embeds.json",
  "methodology_supersedence": "M6.1.1 closed 2026-MM-DD; see docs/benchmarks/m6_1_1-engine-cost-instrumentation.md for diagnosis and resolution of the engine_cost_drift_warning."
}
```

Under non-Phase-2(a) outcomes, the baseline sentinels change shape but the keys remain:

```json
"chat_stream_baseline_post_symmetrisation": {
  "phase_2_path": "phase_2b_documented",
  "baseline_source": "m6_1",
  "pointer": "docs/benchmarks/m6_1-real-prompt-embeds.json",
  "cells": null
}
```

```json
"chat_stream_baseline_post_symmetrisation": {
  "phase_2_path": "split_required",
  "baseline_source": "not_applicable",
  "pointer": null,
  "cells": null
}
```

`embed_regression_check` is `null` under non-Phase-2(a) outcomes (no verification sweep was run).

---

## Strict-superset rules (FR-022)

Validated by a unit test that:
1. Loads M6.1's published JSON schema (`docs/benchmarks/m6_1-real-prompt-embeds.json` shape).
2. Loads M6.1.1's published JSON.
3. Asserts every top-level key in M6.1's schema is present in M6.1.1's (except where M6.1.1 explicitly supersedes — `methodology_supersedence` is additive, not replacing).
4. Asserts M6.1.1's NEW top-level keys (`multi_point_timings`, `phase_1_runs`, `chat_stream_baseline_post_symmetrisation`, `embed_baseline_post_symmetrisation`, `embed_regression_check`, etc.) DO NOT collide with any M6.1 key.

---

## Supersedence annotations on M6.1's published files (FR-023 / FR-024)

### JSON annotation (FR-023)

Adds a single top-level key to `m6_1-real-prompt-embeds.json`:

```json
{
  // ... all existing M6.1 fields preserved exactly ...
  "methodology_supersedence": {
    "pointer": "docs/benchmarks/m6_1_1-engine-cost-instrumentation.md",
    "schema_version": "m6_1_1.v1",
    "phase_2_path": "phase_2a_verified",
    "summary": "Engine_cost_drift_warning on chat_stream cells was attributed to measurement-window asymmetry (instrumentation_artifact); Phase 2(a) symmetrisation cleared the drift. Fresh chat_stream + embed baselines published in M6.1.1."
  }
}
```

Under `phase_2_path = "phase_2b_documented"`, the `summary` instead names the documented finding: "Engine_cost_drift_warning on chat_stream cells was attributed to channel-dependent batching (channel_dependent_batching); documented in `contracts/instrumentation.md` § 'M6.1.1: Channel-Dependent Batching Effect'." Etc.

### Markdown annotation (FR-024)

A one-line forward pointer added in M6.1's chat_stream verdict section (e.g., immediately under the "## Supersedes M6 under enable_prompt_embeds" or "## chat_stream verdict" heading):

```markdown
> **Methodology supersedence (2026-MM-DD)**: see `docs/benchmarks/m6_1_1-engine-cost-instrumentation.md` for the diagnosis and resolution of the `engine_cost_drift_warning` reported on these chat_stream cells.
```

### Per-row supersedence notes (FR-015c — only under embed_regression_acknowledged)

When `phase_2_choice.embed_regression_acknowledged == True`, each affected (embed cell × cohort) row of M6.1's `supersedes_m6_under_enable_prompt_embeds` table gets an inline note appended:

```markdown
| embed c=1 | ... | rest_https_edge | ... | ⚠ embed_regression_acknowledged: post-symmetrisation mean shifted -7% (see m6_1_1-engine-cost-instrumentation.json#embed_baseline_post_symmetrisation) |
```

---

## Sidecar events (`m6_1_1-events.jsonl`)

One JSONL line per RPC. Each line carries the per-RPC event record:

```json
{
  "run_id": "...",
  "cell_str": "chat_stream_c4_h4096",
  "cohort": "tuned_grpc_multiplexed",
  "rpc_index": 23,
  "seed": 65,
  "wall_clock_ms": 89.4,
  "engine_ttft_ms": 41.2,
  "engine_tpot_ms": 12.5,
  "engine_forward_ms": null,
  "m6_1_1_timings": {
    "handler_entry_ns": 1716480000000000000,
    "pre_engine_ns": 1716480000003200000,
    "first_chunk_ns": 1716480000046700000,
    "terminal_emit_ns": 1716480000089200000,
    "perturbation_audit_ns": 240
  },
  "per_segment": {"seg_ab_ms": 3.2, "seg_bc_ms": 43.5, "seg_cd_ms": 42.5},
  "n_attempt": 1,
  "rpc_status": "ok"
}
```

The sidecar is append-only across both `--m6_1_1-diagnose` and `--m6_1_1` invocations. Each invocation prepends a separator line of the form `{"_run_separator": true, "run_id": "..."}` so consumers can split by run.

---

## Invariants

- **All top-level JSON keys present under every `phase_2_path`**: strict-superset compatibility per FR-022. Validated by a golden-file test for each `phase_2_path` value.
- **Markdown 6-section order is fixed**: Executive Summary → Methodology → Multi-Point Timing Table → Root-Cause Attribution → Phase 2 Outcome → Methodology Supersedence (FR-020).
- **Sentinel object shape is identical between chat_stream and embed baselines**: same `{phase_2_path, baseline_source, pointer, cells?}` quad. M6.2 consumers can use one parser for both.
- **`phase_1_runs[]` is append-only**: round-3 Q1.
- **M6.1's published files are PRESERVED EXACTLY** except for the additive `methodology_supersedence` key + one-line pointer. Validated by diffing M6.1's pre-M6.1.1-PR snapshot against the post-merge state in CI.
