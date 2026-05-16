# M6 — Real-Engine Mini-Validation

**Status**: delivered 2026-05-15T23:58:33Z
**Branch**: 020-m6-real-engine-mini-validation
**JSON companion**: [m6-real-engine-mini-validation.json](./m6-real-engine-mini-validation.json)

## Executive Summary

M6 runs a 6-cell × 3-cohort × n=100 sweep against a real Qwen/Qwen3-8B inference engine on Modal's A10G GPU instance in region `eu-west-1`, closing the 'MockEngine caveat' that M5.1 and M5.2 both deferred.

**Inference engine**: vLLM unknown
**Model**: Qwen/Qwen3-8B
**Hidden size**: 4096 (fixed by model architecture)
**GPU**: A10G (24 GB VRAM)
**Modal region**: eu-west-1
**M6_BASE_SEED**: 42
**M5.2 baseline source**: `docs/benchmarks/m5_2-transport-vs-tuning.json` (snapshot in JSON RunMeta — FR-018)
**Bytes axis**: NOT re-measured by M6; M1's findings (~89% chat / ~25% embed reductions) remain authoritative — encoding is structural, not engine-dependent (FR-020).

**Verdict tally**: verdict_buried_by_engine=1 / verdict_changed=4 / verdict_survives=1

## Supersedes M5.2 Under Real Engine

| # | Cell | Classification | M5.2 winner | M6 cohort means (classifier metric) | engine_cost mean | Notes |
|---|------|----------------|-------------|--------------------------------------|------------------|-------|
| 1 | embed × c=1 | verdict_survives | gRPC Δ=50.96 ms | rest=519.73 / default=489.02 / tuned=495.69 | engine_forward=352.22 ms | M6 cohort-pair CIs non-overlapping; direction matches M5.2 (grpc_wins) |
| 2 | embed × c=4 | verdict_changed | REST Δ=74.38 ms | rest=517.73 / default=490.81 / tuned=491.33 | engine_forward=350.88 ms | M6 cohort-pair CIs non-overlapping; direction flipped from M5.2 (rest_wins) to M6 (grpc_wins) |
| 3 | embed × c=8 | verdict_changed | REST Δ=98.70 ms | rest=563.61 / default=492.05 / tuned=482.88 | engine_forward=352.80 ms | M6 cohort-pair CIs non-overlapping; direction flipped from M5.2 (rest_wins) to M6 (grpc_wins) |
| 4 | chat_stream × c=1 | verdict_buried_by_engine | gRPC Δ=0.96 ms | rest=109.90 / default=111.90 / tuned=106.13 | engine_ttft=46.58 ms | ⚠ engine drift; per-cohort engine_cost: rest_https_edge=46.14, default_grpc=50.16, tuned_grpc_multiplexed=43.42; M6 cohort-pair CIs overlap AND engine_cost_mean (46.58 ms) >= 5× M5.2 winner delta (0.96 ms) |
| 5 | chat_stream × c=4 | verdict_changed | REST Δ=17.58 ms | rest=141.01 / default=111.00 / tuned=107.63 | engine_ttft=45.62 ms | ⚠ engine drift; per-cohort engine_cost: rest_https_edge=45.10, default_grpc=48.72, tuned_grpc_multiplexed=43.05; M6 cohort-pair CIs non-overlapping; direction flipped from M5.2 (rest_wins) to M6 (grpc_wins) |
| 6 | chat_stream × c=8 | verdict_changed | REST Δ=21.10 ms | rest=133.47 / default=113.83 / tuned=107.64 | engine_ttft=48.22 ms | ⚠ engine drift; per-cohort engine_cost: rest_https_edge=48.47, default_grpc=51.26, tuned_grpc_multiplexed=44.94; M6 cohort-pair CIs non-overlapping; direction flipped from M5.2 (rest_wins) to M6 (grpc_wins) |

## Engine Cost Per RPC

| Cell | engine_forward_ms (embed) | engine_ttft_ms (chat_stream) | engine_tpot_ms (chat_stream) | drift_warning |
|------|---------------------------|------------------------------|------------------------------|---------------|
| embed × c=1 | 355.56 ± 4.58 | n/a | n/a | False |
| embed × c=4 | 352.52 ± 0.13 | n/a | n/a | False |
| embed × c=8 | 356.98 ± 2.31 | n/a | n/a | False |
| chat_stream × c=1 | n/a | 46.14 ± 2.08 | 34.51 ± 0.06 | True |
| chat_stream × c=4 | n/a | 45.10 ± 1.42 | 34.52 ± 0.04 | True |
| chat_stream × c=8 | n/a | 48.47 ± 2.50 | 34.66 ± 0.08 | True |

## Per-Cohort Detail

### embed × c=1

| Cohort | n_successes | failure_count | classifier_metric mean ± CI (ms) | engine_cost mean (ms) |
|--------|-------------|---------------|----|----|
| rest_https_edge | 100 | 0 | 519.73 ± 10.64 | 355.56 |
| default_grpc | 100 | 0 | 489.02 ± 6.29 | 350.62 |
| tuned_grpc_multiplexed | 100 | 0 | 495.69 ± 7.09 | 350.47 |

### embed × c=4

| Cohort | n_successes | failure_count | classifier_metric mean ± CI (ms) | engine_cost mean (ms) |
|--------|-------------|---------------|----|----|
| rest_https_edge | 100 | 0 | 517.73 ± 11.98 | 352.52 |
| default_grpc | 100 | 0 | 490.81 ± 7.05 | 350.06 |
| tuned_grpc_multiplexed | 100 | 0 | 491.33 ± 6.13 | 350.07 |

### embed × c=8

| Cohort | n_successes | failure_count | classifier_metric mean ± CI (ms) | engine_cost mean (ms) |
|--------|-------------|---------------|----|----|
| rest_https_edge | 100 | 0 | 563.61 ± 25.23 | 356.98 |
| default_grpc | 100 | 0 | 492.05 ± 7.94 | 350.75 |
| tuned_grpc_multiplexed | 100 | 0 | 482.88 ± 4.95 | 350.67 |

### chat_stream × c=1

| Cohort | n_successes | failure_count | classifier_metric mean ± CI (ms) | engine_cost mean (ms) |
|--------|-------------|---------------|----|----|
| rest_https_edge | 100 | 0 | 109.90 ± 4.21 | 46.14 |
| default_grpc | 100 | 0 | 111.90 ± 2.08 | 50.16 |
| tuned_grpc_multiplexed | 100 | 0 | 106.13 ± 2.39 | 43.42 |

### chat_stream × c=4

| Cohort | n_successes | failure_count | classifier_metric mean ± CI (ms) | engine_cost mean (ms) |
|--------|-------------|---------------|----|----|
| rest_https_edge | 100 | 0 | 141.01 ± 12.76 | 45.10 |
| default_grpc | 100 | 0 | 111.00 ± 2.02 | 48.72 |
| tuned_grpc_multiplexed | 100 | 0 | 107.63 ± 2.93 | 43.05 |

### chat_stream × c=8

| Cohort | n_successes | failure_count | classifier_metric mean ± CI (ms) | engine_cost mean (ms) |
|--------|-------------|---------------|----|----|
| rest_https_edge | 100 | 0 | 133.47 ± 11.70 | 48.47 |
| default_grpc | 100 | 0 | 113.83 ± 2.72 | 51.26 |
| tuned_grpc_multiplexed | 100 | 0 | 107.64 ± 1.84 | 44.94 |

## Methodology Notes

- n=100 measurement RPCs per (cell × cohort), preceded by 10 warmup RPCs per (cell × cohort) discarded from metrics (FR-021).
- 3 cohorts measured in round-robin per c-batch order to control for Modal/network/engine drift (FR-022).
- Per-RPC sampling seeds: SamplingParams.seed = M6_BASE_SEED + rpc_index, where rpc_index is the global measurement RPC counter (warmup excluded). M6_BASE_SEED=42; recorded in RunMeta (FR-025).
- Per-RPC failures retried up to 3 attempts; cells with any cohort < 80 successes are classified `cell_incomplete` (FR-023).
- Verdict classifier: deterministic; comparison metric is client-observed TTFT for chat_stream, total wall-clock for embed (FR-014). Engine cost (cohort-averaged) ≥ 5× |M5.2 winner delta| classifies a no-overlap cell as `verdict_buried_by_engine`. Per-cohort engine_cost disagreement > 10% sets the `engine_cost_drift_warning` flag (verdict still computed; per-cohort values surfaced).
- Engine instance: ONE AsyncLLM(Qwen/Qwen3-8B, dtype=fp16, enable_prompt_embeds=True, max_model_len=2048, gpu_memory_utilization=0.92) loaded once at sweep start; serves all 6 cells (FR-024). Cold-start excluded from per-RPC latency, recorded as scalar `cold_start_s=251.46` in RunMeta (FR-019).
- `max_model_len=2048` is a runtime cap (the model's natural context window is 40 960 tokens) chosen to fit Qwen3-8B's KV cache within the A10G's 24 GB VRAM after the ~16 GB fp16 weights. The M6 workload's worst-case RPC length is ≤100 tokens (chat_stream prompt + max_tokens=50), so the cap is 20× the actual sequence demand and does NOT affect measured engine cost — it only bounds KV-cache allocation. Distinct from `hidden_size=4096` (FR-001), which is the model's per-token feature dimension and is fixed by Qwen3-8B's architecture. See `research.md` R-11.

## Operator Reproducibility

To reproduce this run bit-exactly: same git_sha (`4770a2406daa01f86e9bcf050e59472288790264`), same engine version (`unknown`), same Modal region (`eu-west-1`), same `M6_BASE_SEED=42`. The classifier is deterministic given the same M5.2 baseline JSON (snapshot in RunMeta).
