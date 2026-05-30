# M6.1.2 — Methodology Discipline

- run_id: `2026-05-17T20:09:46Z-b0b9d72e`
- sweep_mode: `validate`
- modal_region: `eu-west-1`
- model: `Qwen/Qwen3-8B`
- base_seed: `42`
- run_started_at: `2026-05-17T20:09:46Z`
- run_completed_at: `2026-05-17T20:20:14Z`

## Cohort set

- `default_grpc`
- `rest_https_edge`
- `rest_plain_tcp`
- `tuned_grpc_multiplexed`

## Network paths

Per-sweep topology evidence captured via `tcptraceroute`. See [`contracts/network-paths.md`](../../specs/025-m6-1-2-methodology-discipline/contracts/network-paths.md) for the wire shape.

| cohort | cloud_provider | region | endpoint_ip | probe_status |
|--------|----------------|--------|-------------|--------------|
| `rest_https_edge` | AWS | us-east-1 | `98.92.241.71` | ok |
| `rest_plain_tcp` | AWS | us-east-1 | `100.26.248.115` | ok |
| `default_grpc` | AWS | us-east-1 | `13.220.63.3` | ok |
| `tuned_grpc_multiplexed` | AWS | us-east-1 | `13.220.63.3` | ok |

## Per-cell measurements

| path | concurrency | cohort | n_succ/n_att | wall_clock_ms_mean | engine_ttft_ms_mean |
|------|-------------|--------|--------------|--------------------|---------------------|
| embed | 1 | `default_grpc` | 50/50 | 465.33 | — |
| embed | 1 | `rest_https_edge` | 50/50 | 490.75 | — |
| embed | 1 | `rest_plain_tcp` | 50/50 | 541.54 | — |
| embed | 4 | `default_grpc` | 50/50 | 574.39 | — |
| embed | 4 | `tuned_grpc_multiplexed` | 50/50 | 562.92 | — |
| embed | 4 | `rest_https_edge` | 50/50 | 603.63 | — |
| embed | 4 | `rest_plain_tcp` | 50/50 | 668.56 | — |
| embed | 8 | `default_grpc` | 50/50 | 712.30 | — |
| embed | 8 | `tuned_grpc_multiplexed` | 50/50 | 1068.18 | — |
| embed | 8 | `rest_https_edge` | 50/50 | 741.60 | — |
| embed | 8 | `rest_plain_tcp` | 50/50 | 765.88 | — |
| chat_stream | 1 | `default_grpc` | 50/50 | 1809.52 | 47.80 |
| chat_stream | 1 | `rest_https_edge` | 50/50 | 1780.95 | 43.22 |
| chat_stream | 1 | `rest_plain_tcp` | 50/50 | 1804.40 | 43.28 |
| chat_stream | 4 | `default_grpc` | 50/50 | 1937.78 | 89.31 |
| chat_stream | 4 | `tuned_grpc_multiplexed` | 50/50 | 1946.60 | 88.33 |
| chat_stream | 4 | `rest_https_edge` | 50/50 | 1922.97 | 87.46 |
| chat_stream | 4 | `rest_plain_tcp` | 50/50 | 1940.82 | 90.24 |
| chat_stream | 8 | `default_grpc` | 50/50 | 1969.49 | 97.68 |
| chat_stream | 8 | `tuned_grpc_multiplexed` | 50/50 | 1955.58 | 91.43 |
| chat_stream | 8 | `rest_https_edge` | 50/50 | 1951.74 | 96.82 |
| chat_stream | 8 | `rest_plain_tcp` | 50/50 | 1972.19 | 98.20 |

