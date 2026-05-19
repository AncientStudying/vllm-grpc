# M6.1.3 — Phase 1 Attribution Closure

- run_id: `2026-05-18T23:46:18Z-95618ad0`
- sweep_mode: `validate`
- modal_region: `eu-west-1`
- model: `Qwen/Qwen3-8B`
- base_seed: `42`
- m6_1_3_diagnose_repeat: `1`
- m6_1_3_diagnose_n: `50`
- m6_1_3_symmetric_prompts: `False`
- run_started_at: `2026-05-18T23:46:18Z`
- run_completed_at: `2026-05-19T00:00:08Z`

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
| `rest_https_edge` | unknown | — | `92.5.96.133` | ok |
| `rest_plain_tcp` | AWS | eu-west-1 | `63.32.89.206` | ok |
| `default_grpc` | AWS | eu-west-1 | `34.244.87.33` | ok |
| `tuned_grpc_multiplexed` | AWS | eu-west-1 | `34.244.87.33` | ok |

## Per-cell timing table

| cell | cohort | n_succ/n_att | engine_ttft_ms | seg_ab_ms | seg_queue_ms | seg_prefill_ms | seg_ingress_ms | seg_egress_ms |
|------|--------|--------------|----------------|-----------|--------------|-----------------|-----------------|----------------|
| `embed_c1` | `default_grpc` | 50/50 | — | 0.73 | 0.02 | 41.01 | — | — |
| `embed_c1` | `rest_https_edge` | 50/50 | — | 1.11 | 0.02 | 39.55 | — | — |
| `embed_c1` | `rest_plain_tcp` | 50/50 | — | 1.06 | 0.02 | 39.38 | — | — |
| `embed_c4` | `default_grpc` | 50/50 | — | 0.68 | 0.01 | 59.98 | — | — |
| `embed_c4` | `tuned_grpc_multiplexed` | 50/50 | — | 0.68 | 0.01 | 47.34 | — | — |
| `embed_c4` | `rest_https_edge` | 50/50 | — | 1.04 | 0.01 | 64.76 | — | — |
| `embed_c4` | `rest_plain_tcp` | 50/50 | — | 1.03 | 0.01 | 62.15 | — | — |
| `embed_c8` | `default_grpc` | 50/50 | — | 0.67 | 0.01 | 71.41 | — | — |
| `embed_c8` | `tuned_grpc_multiplexed` | 50/50 | — | 0.69 | 0.01 | 52.98 | — | — |
| `embed_c8` | `rest_https_edge` | 47/50 | — | 1.03 | 0.01 | 73.34 | — | — |
| `embed_c8` | `rest_plain_tcp` | 50/50 | — | 1.03 | 0.01 | 71.81 | — | — |
| `chat_stream_c1` | `default_grpc` | 50/50 | 48.06 | 0.31 | 0.02 | 45.64 | 0.06 | 1.20 |
| `chat_stream_c1` | `rest_https_edge` | 50/50 | 43.68 | 0.06 | 0.02 | 40.53 | 0.06 | 2.07 |
| `chat_stream_c1` | `rest_plain_tcp` | 50/50 | 43.39 | 0.06 | 0.02 | 40.26 | 0.06 | 2.05 |
| `chat_stream_c4` | `default_grpc` | 50/50 | 87.90 | 0.27 | 0.01 | 71.09 | 0.05 | 1.49 |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 50/50 | 90.10 | 0.27 | 0.01 | 71.64 | 0.05 | 1.71 |
| `chat_stream_c4` | `rest_https_edge` | 50/50 | 90.30 | 0.05 | 0.01 | 72.76 | 0.04 | 2.52 |
| `chat_stream_c4` | `rest_plain_tcp` | 50/50 | 91.03 | 0.05 | 0.01 | 71.55 | 0.05 | 2.46 |
| `chat_stream_c8` | `default_grpc` | 50/50 | 88.99 | 0.23 | 0.01 | 71.27 | 0.04 | 2.00 |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 50/50 | 90.43 | 0.24 | 0.01 | 72.41 | 0.04 | 1.86 |
| `chat_stream_c8` | `rest_https_edge` | 50/50 | 88.32 | 0.04 | 0.02 | 72.96 | 0.03 | 3.40 |
| `chat_stream_c8` | `rest_plain_tcp` | 50/50 | 100.24 | 0.05 | 0.01 | 76.30 | 0.05 | 3.39 |

**Phase B trigger verdict** (per FR-044): Phase B trigger verdict unavailable (requires --m6_1_3-diagnose-repeat >= 3 for between-run variance compute).

## Classifier verdicts

Identifier legend: channel_batching = seg_ab_ms; queue_batching = seg_queue_ms; engine_compute = seg_prefill_ms; frontend_arrival = seg_arrival_ms (dormant in M6.1.3 per FR-008a); proxy_ingress = seg_ingress_ms; proxy_egress = seg_egress_ms.

#### chat_stream_c1 → `engine_compute_variation`

The budget lives in the post-schedule engine prefill compute segment.

#### chat_stream_c4 → `inconclusive`

No single segment carries the dominant share of the per-cohort spread; attribution is unattributed.

#### chat_stream_c8 → `engine_compute_variation`

The budget lives in the post-schedule engine prefill compute segment.

#### embed_c1 → `inconclusive`

No single segment carries the dominant share of the per-cohort spread; attribution is unattributed.

#### embed_c4 → `inconclusive`

No single segment carries the dominant share of the per-cohort spread; attribution is unattributed.

#### embed_c8 → `inconclusive`

No single segment carries the dominant share of the per-cohort spread; attribution is unattributed.

## Per-Cohort Prompt-Content Audit

### chat_stream_c1 (pooled n=50 per cohort)

| Cohort | mean_tokenized_prompt_length | stddev | n_rpcs | unique_hash_count |
|--------|------------------------------:|-------:|-------:|-------------------:|
| `default_grpc` | 36.06 | 1.22 | 50 | 50 |
| `rest_https_edge` | 28.06 | 1.22 | 50 | 50 |
| `rest_plain_tcp` | 28.06 | 1.22 | 50 | 50 |

**H1 verdict** (per FR-016 + round-1 Q5):

> H1 confirmed: per-cohort token-count means diverge by >2σ

### chat_stream_c4 (pooled n=50 per cohort)

| Cohort | mean_tokenized_prompt_length | stddev | n_rpcs | unique_hash_count |
|--------|------------------------------:|-------:|-------:|-------------------:|
| `default_grpc` | 36.06 | 1.22 | 50 | 50 |
| `rest_https_edge` | 28.06 | 1.22 | 50 | 50 |
| `rest_plain_tcp` | 28.06 | 1.22 | 50 | 50 |
| `tuned_grpc_multiplexed` | 36.06 | 1.22 | 50 | 50 |

**H1 verdict** (per FR-016 + round-1 Q5):

> H1 confirmed: per-cohort token-count means diverge by >2σ

### chat_stream_c8 (pooled n=50 per cohort)

| Cohort | mean_tokenized_prompt_length | stddev | n_rpcs | unique_hash_count |
|--------|------------------------------:|-------:|-------:|-------------------:|
| `default_grpc` | 36.06 | 1.22 | 50 | 50 |
| `rest_https_edge` | 28.06 | 1.22 | 50 | 50 |
| `rest_plain_tcp` | 28.06 | 1.22 | 50 | 50 |
| `tuned_grpc_multiplexed` | 36.06 | 1.22 | 50 | 50 |

**H1 verdict** (per FR-016 + round-1 Q5):

> H1 confirmed: per-cohort token-count means diverge by >2σ

### embed_c1 (pooled n=50 per cohort)

| Cohort | mean_tokenized_prompt_length | stddev | n_rpcs | unique_hash_count |
|--------|------------------------------:|-------:|-------:|-------------------:|
| `default_grpc` | 19.00 | 0.00 | 50 | 1 |
| `rest_https_edge` | 19.00 | 0.00 | 50 | 1 |
| `rest_plain_tcp` | 19.00 | 0.00 | 50 | 1 |

**H1 verdict** (per FR-016 + round-1 Q5):

> H1 rejected: per-cohort distributions statistically identical

### embed_c4 (pooled n=50 per cohort)

| Cohort | mean_tokenized_prompt_length | stddev | n_rpcs | unique_hash_count |
|--------|------------------------------:|-------:|-------:|-------------------:|
| `default_grpc` | 19.00 | 0.00 | 50 | 1 |
| `rest_https_edge` | 19.00 | 0.00 | 50 | 1 |
| `rest_plain_tcp` | 19.00 | 0.00 | 50 | 1 |
| `tuned_grpc_multiplexed` | 19.00 | 0.00 | 50 | 1 |

**H1 verdict** (per FR-016 + round-1 Q5):

> H1 rejected: per-cohort distributions statistically identical

### embed_c8 (pooled n=50 per cohort)

| Cohort | mean_tokenized_prompt_length | stddev | n_rpcs | unique_hash_count |
|--------|------------------------------:|-------:|-------:|-------------------:|
| `default_grpc` | 19.00 | 0.00 | 50 | 1 |
| `rest_https_edge` | 19.00 | 0.00 | 47 | 1 |
| `rest_plain_tcp` | 19.00 | 0.00 | 50 | 1 |
| `tuned_grpc_multiplexed` | 19.00 | 0.00 | 50 | 1 |

**H1 verdict** (per FR-016 + round-1 Q5):

> H1 rejected: per-cohort distributions statistically identical

**Recommendation** (per FR-017 / FR-018):

> H1 confirmed at chat_stream_c1: per-cohort token-count means diverge by >2σ. Symmetric prompts SHOULD become the M6.x convention going forward (per FR-017). M6.2 / M7 / M8 spec authors MUST cite this recommendation as a precondition (per SC-012) and either accept it (turning their milestone's `-symmetric-prompts` flag on by default) or document an explicit divergence with reasoning.

