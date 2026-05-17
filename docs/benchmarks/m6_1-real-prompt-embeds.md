# M6.1 — Real-Prompt-Embeds Engine Path

**Status**: delivered 2026-05-16
**Branch**: 022-m6-1-real-prompt-embeds
**JSON companion**: [m6_1-real-prompt-embeds.json](./m6_1-real-prompt-embeds.json)

## Executive Summary

**Inference engine**: vLLM 0.20.1 (M6 baseline: vLLM unknown — see methodology note below)
**Model**: Qwen/Qwen3-8B
**Hidden size**: 4096 (fixed by model architecture)
**GPU**: A10G (24 GB VRAM)
**Modal region**: eu-west-1
**M6_1_BASE_SEED**: 42
**Pinned client torch**: 2.11.0 (validated at driver-start — FR-006)
**Prompt-embeds seq_len**: 19 (tokenised against Qwen3-8B's tokenizer from M6's `embed_<hex>` digest format — FR-028 / R-3)
**M6 baseline source**: docs/benchmarks/m6-real-engine-mini-validation.json (m6_winner_deltas snapshotted in JSON RunMeta — FR-008)
**Bytes axis**: NOT re-measured by M6.1; M1's findings remain authoritative — encoding is structural, not engine-dependent (FR-024).

## Supersedes M6 Under enable_prompt_embeds

| # | Cell | Classification | M6 winner | M6.1 cohort means (classifier metric) | engine_cost mean | Drift flags | Notes |
|---|------|----------------|-----------|----------------------------------------|------------------|-------------|-------|
| 1 | embed × c=1 | verdict_buried_by_engine | tuned_grpc_multiplexed Δ=24.04ms | rest_https_edge=593.29ms / default_grpc=651.05ms / tuned_grpc_multiplexed=562.94ms | 338.11ms | — | M6.1 CIs overlap AND engine_cost_mean (338.11ms) ≥ 5× M6 winner delta (24.04ms). |
| 2 | embed × c=4 | verdict_buried_by_engine | tuned_grpc_multiplexed Δ=26.40ms | rest_https_edge=617.59ms / default_grpc=599.99ms / tuned_grpc_multiplexed=583.25ms | 337.96ms | — | M6.1 CIs overlap AND engine_cost_mean (337.96ms) ≥ 5× M6 winner delta (26.40ms). |
| 3 | embed × c=8 | verdict_survives | tuned_grpc_multiplexed Δ=80.73ms | rest_https_edge=681.37ms / default_grpc=572.17ms / tuned_grpc_multiplexed=565.45ms | 341.03ms | — | M6.1 CIs non-overlapping in same direction as M6 winner (grpc_wins); |Δ|=115.92ms. |
| 4 | chat_stream × c=1 | no_winner_at_n100 | (M6: no usable delta) | rest_https_edge=182.79ms / default_grpc=213.50ms / tuned_grpc_multiplexed=204.44ms | 44.05ms | ⚠ engine drift, ⚠ chat_stream drift | M6 baseline had no usable winner delta for this cell (M6 verdict was no_winner_at_n100 / cell_incomplete / verdict_buried_by_engine) — FR-010 sub-clause. |
| 5 | chat_stream × c=4 | no_winner_at_n100 | tuned_grpc_multiplexed Δ=33.39ms | rest_https_edge=260.42ms / default_grpc=238.06ms / tuned_grpc_multiplexed=229.90ms | 44.13ms | ⚠ engine drift, ⚠ chat_stream drift | M6.1 CIs overlap AND engine_cost_mean (44.13ms) < 5× M6 winner delta (33.39ms). |
| 6 | chat_stream × c=8 | no_winner_at_n100 | tuned_grpc_multiplexed Δ=25.84ms | rest_https_edge=228.45ms / default_grpc=229.55ms / tuned_grpc_multiplexed=216.53ms | 44.70ms | ⚠ engine drift, ⚠ chat_stream drift | M6.1 CIs overlap AND engine_cost_mean (44.70ms) < 5× M6 winner delta (25.84ms). |

## Engine Path Differential (M6.1 − M6)

For each cell, the per-cohort classifier-metric delta (M6.1 mean − M6 mean) and the per-cell engine_cost_mean delta. Units are ms; 95% CI half-widths are combined via the standard sqrt-of-sum-of-squared-CIs formula (FR-020).

| Cell | rest_https_edge Δ (ms ± CI) | default_grpc Δ (ms ± CI) | tuned_grpc_multiplexed Δ (ms ± CI) | engine_cost_mean Δ (ms ± CI) | n_successes (per cohort) |
|------|-----------------------------|---------------------------|--------------------------------------|------------------------------|---------------------------|
| embed × c=1 | +73.57 ± 31.42 | +162.03 ± 56.28 | +67.25 ± 12.85 | -14.10 ± 33.52 | 100 / 100 / 100 |
| embed × c=4 | +99.87 ± 40.53 | +109.17 ± 29.11 | +91.92 ± 18.19 | -12.92 ± 29.28 | 100 / 100 / 100 |
| embed × c=8 | +117.76 ± 57.92 | +80.12 ± 10.40 | +82.57 ± 8.71 | -11.77 ± 25.68 | 100 / 100 / 100 |
| chat_stream × c=1 | +72.89 ± 4.24 | +101.60 ± 3.90 | +98.31 ± 2.64 | -2.53 ± 3.60 | 100 / 100 / 100 |
| chat_stream × c=4 | +119.40 ± 29.28 | +127.07 ± 8.23 | +122.27 ± 8.90 | -1.50 ± 15.47 | 100 / 100 / 100 |
| chat_stream × c=8 | +94.97 ± 24.32 | +115.72 ± 11.09 | +108.89 ± 6.64 | -3.52 ± 14.01 | 100 / 100 / 100 |

## Engine Cost Per RPC

| Cell | engine_forward_ms (embed) | engine_ttft_ms (chat_stream) | engine_tpot_ms (chat_stream) | drift_warning |
|------|---------------------------|------------------------------|------------------------------|---------------|
| embed × c=1 | 338.11 | n/a | n/a | False |
| embed × c=4 | 337.96 | n/a | n/a | False |
| embed × c=8 | 341.03 | n/a | n/a | False |
| chat_stream × c=1 | n/a | 44.05 | 33.67 | True |
| chat_stream × c=4 | n/a | 44.13 | 33.71 | True |
| chat_stream × c=8 | n/a | 44.70 | 33.73 | True |

## Per-Cohort Detail

### embed × c=1

| Cohort | n_successes | failure_count | wall_clock mean ± CI (ms) | classifier_metric mean ± CI (ms) | engine_forward / TTFT mean ± CI (ms) |
|--------|-------------|---------------|---------------------------|-----------------------------------|--------------------------------------|
| rest_https_edge | 100 | 0 | 593.29 ± 29.56 | 593.29 ± 29.56 | 339.12 ± 5.93 |
| default_grpc | 100 | 0 | 651.05 ± 55.93 | 651.05 ± 55.93 | 337.61 ± 5.93 |
| tuned_grpc_multiplexed | 100 | 0 | 562.94 ± 10.72 | 562.94 ± 10.72 | 337.61 ± 5.94 |

### embed × c=4

| Cohort | n_successes | failure_count | wall_clock mean ± CI (ms) | classifier_metric mean ± CI (ms) | engine_forward / TTFT mean ± CI (ms) |
|--------|-------------|---------------|---------------------------|-----------------------------------|--------------------------------------|
| rest_https_edge | 100 | 0 | 617.59 ± 38.72 | 617.59 ± 38.72 | 339.02 ± 5.28 |
| default_grpc | 100 | 0 | 599.99 ± 28.24 | 599.99 ± 28.24 | 337.39 ± 5.28 |
| tuned_grpc_multiplexed | 100 | 0 | 583.25 ± 17.12 | 583.25 ± 17.12 | 337.48 ± 5.28 |

### embed × c=8

| Cohort | n_successes | failure_count | wall_clock mean ± CI (ms) | classifier_metric mean ± CI (ms) | engine_forward / TTFT mean ± CI (ms) |
|--------|-------------|---------------|---------------------------|-----------------------------------|--------------------------------------|
| rest_https_edge | 100 | 0 | 681.37 ± 52.14 | 681.37 ± 52.14 | 342.10 ± 0.24 |
| default_grpc | 100 | 0 | 572.17 ± 6.71 | 572.17 ± 6.71 | 340.60 ± 0.21 |
| tuned_grpc_multiplexed | 100 | 0 | 565.45 ± 7.17 | 565.45 ± 7.17 | 340.40 ± 0.16 |

### chat_stream × c=1

| Cohort | n_successes | failure_count | wall_clock mean ± CI (ms) | classifier_metric mean ± CI (ms) | engine_forward / TTFT mean ± CI (ms) |
|--------|-------------|---------------|---------------------------|-----------------------------------|--------------------------------------|
| rest_https_edge | 100 | 0 | 1834.72 ± 1.07 | 182.79 ± 0.50 | 43.73 ± 1.71 |
| default_grpc | 100 | 0 | 1898.25 ± 9.25 | 213.50 ± 3.30 | 47.10 ± 0.16 |
| tuned_grpc_multiplexed | 100 | 0 | 1913.79 ± 11.65 | 204.44 ± 1.14 | 41.31 ± 0.11 |

### chat_stream × c=4

| Cohort | n_successes | failure_count | wall_clock mean ± CI (ms) | classifier_metric mean ± CI (ms) | engine_forward / TTFT mean ± CI (ms) |
|--------|-------------|---------------|---------------------------|-----------------------------------|--------------------------------------|
| rest_https_edge | 100 | 0 | 1913.07 ± 26.29 | 260.42 ± 26.35 | 43.29 ± 1.12 |
| default_grpc | 100 | 0 | 1921.78 ± 10.06 | 238.06 ± 7.98 | 47.53 ± 0.25 |
| tuned_grpc_multiplexed | 100 | 0 | 1936.78 ± 11.15 | 229.90 ± 8.40 | 41.56 ± 0.13 |

### chat_stream × c=8

| Cohort | n_successes | failure_count | wall_clock mean ± CI (ms) | classifier_metric mean ± CI (ms) | engine_forward / TTFT mean ± CI (ms) |
|--------|-------------|---------------|---------------------------|-----------------------------------|--------------------------------------|
| rest_https_edge | 100 | 0 | 1880.28 ± 21.36 | 228.45 ± 21.32 | 43.60 ± 1.13 |
| default_grpc | 100 | 0 | 1922.24 ± 12.49 | 229.55 ± 10.75 | 48.66 ± 2.40 |
| tuned_grpc_multiplexed | 100 | 0 | 1923.79 ± 11.42 | 216.53 ± 6.38 | 41.84 ± 0.19 |

## Methodology Notes

- n=100 measurement RPCs per (cell × cohort), preceded by 10 warmup RPCs per (cell × cohort) discarded from metrics (FR-015).
- 3 cohorts measured in round-robin per c-batch order to control for Modal/network/engine drift (FR-016).
- Per-RPC sampling seeds: `SamplingParams.seed = M6_1_BASE_SEED + rpc_index`, where rpc_index is the global measurement RPC counter (warmup excluded). `M6_1_BASE_SEED=42`; recorded in RunMeta (FR-019).
- Per-RPC tensor values: `torch.Generator(device='cpu').manual_seed(M6_1_BASE_SEED + rpc_index)` then `torch.randn([seq_len, 4096], dtype=torch.float16, generator=...)`. Only the values vary per RPC; tensor shape is fixed (FR-028).
- Per-RPC failures retried up to 3 attempts; cells with any cohort < 80 successes are classified `cell_incomplete` (FR-017).
- Verdict classifier: deterministic; comparison metric is client-observed TTFT for chat_stream, total wall-clock for embed (FR-011). Cells whose M6 verdict was `no_winner_at_n100`, `cell_incomplete`, OR `verdict_buried_by_engine` classify as `no_winner_at_n100` regardless of M6.1 CI overlap (FR-010 sub-clause). engine_cost (cohort-averaged simple unweighted mean per FR-022) ≥ 5× |M6 winner delta| classifies a no-overlap cell as `verdict_buried_by_engine`. Per-cohort engine_cost disagreement > 10% sets the `engine_cost_drift_warning` flag (verdict still computed; per-cohort values surfaced).
- chat_stream control-drift check (FR-029): each chat_stream cell × cohort's M6.1 95% CI on TTFT is compared against M6's published 95% CI; non-overlap on at least one cohort sets the `chat_stream_control_drift_warning` flag on that cell. Diagnostic only — verdicts still computed.
- Engine instance: ONE `AsyncLLM(Qwen/Qwen3-8B, dtype=fp16, enable_prompt_embeds=True, max_model_len=2048, gpu_memory_utilization=0.92)` loaded once at sweep start (FR-014). Cold-start excluded from per-RPC latency, recorded as scalar `cold_start_s=153.93` in RunMeta. Engine config UNCHANGED from M6 per FR-007.
- Engine version comparison (FR-030): M6.1's pinned vLLM version is **0.20.1** (read from `pyproject.toml`); the M6 baseline JSON's recorded vLLM version is **unknown**.
  NOTE: the comparison is informational; the 'Engine path differential' read is cleanest when both versions match. The legacy M6 baseline records `engine_version=unknown` because M6's version-reader helper landed post-sweep — future M6 republishes feed cleanly through the same plumbing.
- Client torch version: **2.11.0** (matches vllm==0.20.1's transitive pin per FR-006). The driver validates `torch.__version__` at driver-start and exits with a clear actionable error if mismatched.

## Methodology Supersedence (M6.0a — Dispatch-Correction)

> **Per-cohort drift sub-finding — dispatch-sensitive (M6.0a, 2026-05-17).** The per-cohort `engine_ttft_ms` spread on the chat_stream cells above (most visible on `chat_stream × c=1` where `engine_cost_drift_warning` and `chat_stream_control_drift_warning` are both set) was measured under a benchmark harness that silently dispatched RPCs sequentially regardless of `cell.concurrency`. M6.0a's correction restored true `asyncio.gather`-based concurrent in-flight dispatch and re-ran M6.1.1's Phase 1 diagnostic against the same Modal A10G `eu-west-1` configuration. The corrected run **disproves the "sequential-dispatch state-drift artifact" hypothesis** for the per-cohort drift sub-finding — under real concurrency the spread at c=4 and c=8 grows from 6.0%/8.4% to ~16%, confirming the effect is engine-side under continuous batching. The M6.1 verdict-supersedes table above and the engine-path differential remain **dispatch-robust** (they read aggregate per-cell timings, not per-cohort spread). See [`m6_0a-dispatch-correction.md`](./m6_0a-dispatch-correction.md) for the bug, the fix, the regression test, the before/after spread table, and the per-finding dispatch-sensitivity classification.

## Operator Reproducibility

To reproduce this run bit-exactly: same git_sha (`df35a065ece68f99eb2c10225ccd98a634623748`), same vLLM engine version (`0.20.1`), same client torch version (`2.11.0`), same Modal region (`eu-west-1`), same `M6_1_BASE_SEED` (`42`), and the same M6 baseline JSON (snapshotted in `run_meta.m6_winner_deltas`). The classifier is deterministic given these inputs (SC-006).
