# M6.1.3 — Phase 1 Attribution Closure

> **Note**: M6.2's published artifact ([m6_2-token-budget.md](m6_2-token-budget.md)) extends this milestone's attribution verdicts to a realistic-response-length axis (`max_tokens ∈ {10, 50, 256, 512, 1024, 2048}`). See that artifact for per-cohort latency budgets at production response lengths and the protocol-crossover threshold per cell.

- run_id: `2026-05-19T00:20:22Z-f15efa12`
- sweep_mode: `full`
- modal_region: `eu-west-1`
- model: `Qwen/Qwen3-8B`
- base_seed: `42`
- m6_1_3_diagnose_repeat: `5`
- m6_1_3_diagnose_n: `50`
- m6_1_3_symmetric_prompts: `False`
- run_started_at: `2026-05-19T00:20:22Z`
- run_completed_at: `2026-05-19T01:18:03Z`

## Method / Background

Updates the c=4 / c=8 verdicts from [M6.1.1](m6_1_1-engine-cost-instrumentation.md); see that artifact's leading note for the bidirectional pointer.

## Cohort set

- `default_grpc`
- `rest_https_edge`
- `rest_plain_tcp`
- `tuned_grpc_multiplexed`

## Network paths

| cohort | cloud_provider | region | endpoint_ip | probe_status |
|--------|----------------|--------|-------------|--------------|
| `rest_https_edge` | unknown | — | `130.61.32.116` | ok |
| `rest_plain_tcp` | AWS | eu-west-1 | `63.32.89.206` | ok |
| `default_grpc` | AWS | eu-west-1 | `34.244.87.33` | ok |
| `tuned_grpc_multiplexed` | AWS | eu-west-1 | `34.244.87.33` | ok |

## Per-cell timing table

| cell | cohort | n_succ/n_att | engine_ttft_ms | seg_ab_ms | seg_queue_ms | seg_prefill_ms | seg_ingress_ms | seg_egress_ms |
|------|--------|--------------|----------------|-----------|--------------|-----------------|-----------------|----------------|
| `embed_c1` | `default_grpc` | 50/50 | — | 0.64 | 0.01 | 40.17 | — | — |
| `embed_c1` | `rest_https_edge` | 50/50 | — | 1.01 | 0.01 | 38.91 | — | — |
| `embed_c1` | `rest_plain_tcp` | 50/50 | — | 0.99 | 0.01 | 38.88 | — | — |
| `embed_c4` | `default_grpc` | 50/50 | — | 0.57 | 0.01 | 72.07 | — | — |
| `embed_c4` | `tuned_grpc_multiplexed` | 50/50 | — | 0.57 | 0.01 | 67.05 | — | — |
| `embed_c4` | `rest_https_edge` | 50/50 | — | 0.94 | 0.01 | 68.42 | — | — |
| `embed_c4` | `rest_plain_tcp` | 50/50 | — | 0.91 | 0.01 | 66.65 | — | — |
| `embed_c8` | `default_grpc` | 50/50 | — | 0.52 | 0.01 | 72.91 | — | — |
| `embed_c8` | `tuned_grpc_multiplexed` | 50/50 | — | 0.52 | 0.01 | 73.36 | — | — |
| `embed_c8` | `rest_https_edge` | 50/50 | — | 0.90 | 0.01 | 70.64 | — | — |
| `embed_c8` | `rest_plain_tcp` | 50/50 | — | 0.88 | 0.01 | 69.75 | — | — |
| `chat_stream_c1` | `default_grpc` | 50/50 | 46.60 | 0.26 | 0.01 | 44.69 | 0.05 | 0.92 |
| `chat_stream_c1` | `rest_https_edge` | 50/50 | 44.78 | 0.05 | 0.01 | 39.44 | 0.05 | 4.39 |
| `chat_stream_c1` | `rest_plain_tcp` | 50/50 | 44.73 | 0.05 | 0.01 | 39.37 | 0.05 | 4.41 |
| `chat_stream_c4` | `default_grpc` | 50/50 | 86.38 | 0.21 | 0.01 | 70.06 | 0.04 | 1.00 |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 50/50 | 83.47 | 0.21 | 0.01 | 67.54 | 0.04 | 0.95 |
| `chat_stream_c4` | `rest_https_edge` | 50/50 | 95.85 | 0.04 | 0.01 | 70.98 | 0.04 | 4.89 |
| `chat_stream_c4` | `rest_plain_tcp` | 49/50 | 90.15 | 0.05 | 0.01 | 70.12 | 0.04 | 5.06 |
| `chat_stream_c8` | `default_grpc` | 50/50 | 88.61 | 0.20 | 0.01 | 71.99 | 0.03 | 1.28 |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 50/50 | 91.86 | 0.19 | 0.01 | 71.86 | 0.03 | 1.18 |
| `chat_stream_c8` | `rest_https_edge` | 50/50 | 103.97 | 0.04 | 0.01 | 75.58 | 0.03 | 5.40 |
| `chat_stream_c8` | `rest_plain_tcp` | 50/50 | 91.35 | 0.04 | 0.01 | 72.63 | 0.03 | 5.29 |

## Classifier verdicts

Identifier legend: channel_batching = seg_ab_ms; queue_batching = seg_queue_ms; engine_compute = seg_prefill_ms; frontend_arrival = seg_arrival_ms (dormant in M6.1.3 per FR-008a); proxy_ingress = seg_ingress_ms; proxy_egress = seg_egress_ms.

#### chat_stream_c1 → `inconclusive`

No single segment carries the dominant share of the per-cohort spread; attribution is unattributed.

#### chat_stream_c4 → `inconclusive`

No single segment carries the dominant share of the per-cohort spread; attribution is unattributed.

#### chat_stream_c8 → `inconclusive`

No single segment carries the dominant share of the per-cohort spread; attribution is unattributed.

#### embed_c1 → `inconclusive`

No single segment carries the dominant share of the per-cohort spread; attribution is unattributed.

#### embed_c4 → `inconclusive`

No single segment carries the dominant share of the per-cohort spread; attribution is unattributed.

#### embed_c8 → `inconclusive`

No single segment carries the dominant share of the per-cohort spread; attribution is unattributed.

## Per-Cohort Prompt-Content Audit

### chat_stream_c1 (pooled n=250 per cohort)

| Cohort | mean_tokenized_prompt_length | stddev | n_rpcs | unique_hash_count |
|--------|------------------------------:|-------:|-------:|-------------------:|
| `default_grpc` | 36.88 | 1.37 | 250 | 250 |
| `rest_https_edge` | 28.88 | 1.37 | 250 | 250 |
| `rest_plain_tcp` | 28.88 | 1.37 | 250 | 250 |

**H1 verdict** (per FR-016 + round-1 Q5):

> H1 confirmed: per-cohort token-count means diverge by >2σ

### chat_stream_c4 (pooled n=250 per cohort)

| Cohort | mean_tokenized_prompt_length | stddev | n_rpcs | unique_hash_count |
|--------|------------------------------:|-------:|-------:|-------------------:|
| `default_grpc` | 36.88 | 1.37 | 250 | 250 |
| `rest_https_edge` | 28.88 | 1.37 | 250 | 250 |
| `rest_plain_tcp` | 28.88 | 1.37 | 249 | 249 |
| `tuned_grpc_multiplexed` | 36.88 | 1.37 | 250 | 250 |

**H1 verdict** (per FR-016 + round-1 Q5):

> H1 confirmed: per-cohort token-count means diverge by >2σ

### chat_stream_c8 (pooled n=250 per cohort)

| Cohort | mean_tokenized_prompt_length | stddev | n_rpcs | unique_hash_count |
|--------|------------------------------:|-------:|-------:|-------------------:|
| `default_grpc` | 36.88 | 1.37 | 250 | 250 |
| `rest_https_edge` | 28.88 | 1.37 | 250 | 250 |
| `rest_plain_tcp` | 28.88 | 1.38 | 249 | 249 |
| `tuned_grpc_multiplexed` | 36.88 | 1.37 | 250 | 250 |

**H1 verdict** (per FR-016 + round-1 Q5):

> H1 confirmed: per-cohort token-count means diverge by >2σ

### embed_c1 (pooled n=250 per cohort)

| Cohort | mean_tokenized_prompt_length | stddev | n_rpcs | unique_hash_count |
|--------|------------------------------:|-------:|-------:|-------------------:|
| `default_grpc` | 19.00 | 0.00 | 250 | 1 |
| `rest_https_edge` | 19.00 | 0.00 | 250 | 1 |
| `rest_plain_tcp` | 19.00 | 0.00 | 250 | 1 |

**H1 verdict** (per FR-016 + round-1 Q5):

> H1 rejected: per-cohort distributions statistically identical

### embed_c4 (pooled n=250 per cohort)

| Cohort | mean_tokenized_prompt_length | stddev | n_rpcs | unique_hash_count |
|--------|------------------------------:|-------:|-------:|-------------------:|
| `default_grpc` | 19.00 | 0.00 | 250 | 1 |
| `rest_https_edge` | 19.00 | 0.00 | 250 | 1 |
| `rest_plain_tcp` | 19.00 | 0.00 | 250 | 1 |
| `tuned_grpc_multiplexed` | 19.00 | 0.00 | 250 | 1 |

**H1 verdict** (per FR-016 + round-1 Q5):

> H1 rejected: per-cohort distributions statistically identical

### embed_c8 (pooled n=250 per cohort)

| Cohort | mean_tokenized_prompt_length | stddev | n_rpcs | unique_hash_count |
|--------|------------------------------:|-------:|-------:|-------------------:|
| `default_grpc` | 19.00 | 0.00 | 250 | 1 |
| `rest_https_edge` | 19.00 | 0.00 | 250 | 1 |
| `rest_plain_tcp` | 19.00 | 0.00 | 250 | 1 |
| `tuned_grpc_multiplexed` | 19.00 | 0.00 | 250 | 1 |

**H1 verdict** (per FR-016 + round-1 Q5):

> H1 rejected: per-cohort distributions statistically identical

**Recommendation** (per FR-017 / FR-018):

> H1 confirmed at chat_stream_c1: per-cohort token-count means diverge by >2σ. Symmetric prompts SHOULD become the M6.x convention going forward (per FR-017). M6.2 / M7 / M8 spec authors MUST cite this recommendation as a precondition (per SC-012) and either accept it (turning their milestone's `-symmetric-prompts` flag on by default) or document an explicit divergence with reasoning.

## Between-Run Variance

| Cell × Cohort | mean_of_means (ms) | stddev_of_means (ms) | n_runs |
|---|---:|---:|---:|
| `chat_stream_c1` / `default_grpc` | 46.76 | 0.16 | 5 |
| `chat_stream_c1` / `rest_https_edge` | 43.28 | 0.97 | 5 |
| `chat_stream_c1` / `rest_plain_tcp` | 43.68 | 1.49 | 5 |
| `chat_stream_c4` / `default_grpc` | 85.89 | 3.20 | 5 |
| `chat_stream_c4` / `rest_https_edge` | 92.98 | 2.38 | 5 |
| `chat_stream_c4` / `rest_plain_tcp` | 90.29 | 2.50 | 5 |
| `chat_stream_c4` / `tuned_grpc_multiplexed` | 85.52 | 1.28 | 5 |
| `chat_stream_c8` / `default_grpc` | 87.55 | 2.47 | 5 |
| `chat_stream_c8` / `rest_https_edge` | 99.44 | 4.51 | 5 |
| `chat_stream_c8` / `rest_plain_tcp` | 94.15 | 4.21 | 5 |
| `chat_stream_c8` / `tuned_grpc_multiplexed` | 89.97 | 1.60 | 5 |

**Phase B trigger verdict**: Phase B not required.

