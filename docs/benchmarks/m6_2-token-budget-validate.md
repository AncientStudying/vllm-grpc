# M6.2 — Token-Budget Characterization

- run_id: `2026-05-23T18:20:16Z-1e871011`
- sweep_mode: `validate`
- modal_region: `eu-west-1`
- model: `Qwen/Qwen3-8B`
- base_seed: `42`
- iteration_order: `cohort_innermost_block`
- iteration_discipline_verified: `True`
- n_per_point: `20`
- validate_axis_subset: `[10, 50, 2048]`
- wall_clock_start_utc: `2026-05-23T18:20:16Z`
- wall_clock_end_utc: `2026-05-23T19:25:16Z`
- total_sweep_hours: `1.083`
- chat_corpus_sha256: `4442302df439fdc1967e9fb48a88910cee5d0f712592e733d47bdbbc1e0374f1`
- embed_corpus_sha256: `19a3b43bc34017615d175ea914b362f9d26a39bd2742b27af7e42f2b97df38a0`
- sub_probe_ran: `True`
- run_started_at: `2026-05-23T18:20:16Z`
- run_completed_at: `2026-05-23T19:25:16Z`

> **WARNING (null_anchor_drift)**: ≥ 2 of the 22 cross-checkable null-anchor cells drifted against the M6.1.3 baseline (FR-014 / SC-004). Operator decides publish vs rerun.
>
> **WARNING (intra_sweep_latency_drift)**: ≥ 2 of 4 cohorts' anchor-latency trajectories drifted beyond M6.1.3's CI half-width (FR-031 / SC-016). Cross-block comparison may be confounded.

## Production latency budget

Validate-mode axis subset is `{10, 50, 2048}`; interior caps (`{256, 512, 1024}`) carry `not_validated` placeholders. Use the publish-mode artifact for the full 6-point budget.

| cell | cohort | max_tokens | n | wall_p50_ms | wall_p95_ms | wall_p99_ms | prompt_source | regime | corpus_idx | status |
|------|--------|-----------:|---:|------------:|------------:|------------:|---------------|--------|-----------:|--------|
| `embed_c1` | `default_grpc` | 10 | 20 | 1682.22 | 1966.11 | 1972.93 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `default_grpc` | 50 | 20 | 3010.81 | 3206.33 | 3253.61 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `default_grpc` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `default_grpc` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `default_grpc` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `default_grpc` | 2048 | 20 | 93141.98 | 106905.61 | 109150.98 | `corpus_sharegpt_embed` | `natural_eos` | 6 | ok |
| `embed_c1` | `rest_https_edge` | 10 | 20 | 2100.58 | 2791.06 | 2795.73 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `rest_https_edge` | 50 | 20 | 5088.11 | 7189.50 | 7207.57 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `rest_https_edge` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `rest_https_edge` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `rest_https_edge` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `rest_https_edge` | 2048 | 20 | 149272.55 | 221865.46 | 222405.62 | `corpus_sharegpt_embed` | `natural_eos` | 7 | ok |
| `embed_c1` | `rest_plain_tcp` | 10 | 20 | 2015.40 | 2777.94 | 2786.27 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `rest_plain_tcp` | 50 | 20 | 5183.55 | 7443.65 | 7455.22 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `rest_plain_tcp` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `rest_plain_tcp` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `rest_plain_tcp` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `rest_plain_tcp` | 2048 | 20 | 162847.96 | 240827.25 | 240827.40 | `corpus_sharegpt_embed` | `natural_eos` | 8 | ok |
| `embed_c4` | `default_grpc` | 10 | 20 | 1127.97 | 1407.00 | 1444.16 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `default_grpc` | 50 | 20 | 2588.22 | 2804.76 | 2855.11 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `default_grpc` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `default_grpc` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `default_grpc` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `default_grpc` | 2048 | 20 | 92413.03 | 99488.87 | 102693.97 | `corpus_sharegpt_embed` | `natural_eos` | 17 | ok |
| `embed_c4` | `rest_https_edge` | 10 | 20 | 1660.28 | 2195.04 | 2216.26 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `rest_https_edge` | 50 | 20 | 4628.59 | 6632.15 | 6655.29 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `rest_https_edge` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `rest_https_edge` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `rest_https_edge` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `rest_https_edge` | 2048 | 20 | 135912.02 | 237695.61 | 238869.73 | `corpus_sharegpt_embed` | `natural_eos` | 19 | ok |
| `embed_c4` | `rest_plain_tcp` | 10 | 20 | 1926.37 | 2582.93 | 2604.11 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `rest_plain_tcp` | 50 | 20 | 4786.43 | 6907.26 | 6933.76 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `rest_plain_tcp` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `rest_plain_tcp` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `rest_plain_tcp` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `rest_plain_tcp` | 2048 | 20 | 162564.86 | 240644.87 | 240663.74 | `corpus_sharegpt_embed` | `natural_eos` | 20 | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 10 | 20 | 1508.07 | 1570.19 | 1583.41 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 50 | 20 | 2966.87 | 3173.46 | 3201.49 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `tuned_grpc_multiplexed` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `tuned_grpc_multiplexed` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `tuned_grpc_multiplexed` | 2048 | 20 | 92828.35 | 105679.67 | 107910.95 | `corpus_sharegpt_embed` | `natural_eos` | 18 | ok |
| `embed_c8` | `default_grpc` | 10 | 20 | 1190.32 | 1439.18 | 1490.43 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `default_grpc` | 50 | 20 | 2551.70 | 2740.03 | 2791.24 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `default_grpc` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `default_grpc` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `default_grpc` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `default_grpc` | 2048 | 20 | 90734.27 | 95629.96 | 98559.47 | `corpus_sharegpt_embed` | `natural_eos` | 29 | ok |
| `embed_c8` | `rest_https_edge` | 10 | 20 | 1701.51 | 2221.29 | 2269.57 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `rest_https_edge` | 50 | 20 | 4685.50 | 6686.44 | 6704.06 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `rest_https_edge` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `rest_https_edge` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `rest_https_edge` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `rest_https_edge` | 2048 | 20 | 161078.03 | 238370.19 | 238426.58 | `corpus_sharegpt_embed` | `natural_eos` | 31 | ok |
| `embed_c8` | `rest_plain_tcp` | 10 | 20 | 1805.17 | 2449.15 | 2475.67 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `rest_plain_tcp` | 50 | 20 | 4796.06 | 6913.21 | 6933.83 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `rest_plain_tcp` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `rest_plain_tcp` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `rest_plain_tcp` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `rest_plain_tcp` | 2048 | 20 | 157758.06 | 233364.50 | 233394.03 | `corpus_sharegpt_embed` | `natural_eos` | 32 | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 10 | 20 | 1123.15 | 1440.72 | 1451.56 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 50 | 20 | 2619.35 | 2782.38 | 2797.58 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `tuned_grpc_multiplexed` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `tuned_grpc_multiplexed` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `tuned_grpc_multiplexed` | 2048 | 20 | 93741.22 | 110078.65 | 112219.25 | `corpus_sharegpt_embed` | `natural_eos` | 30 | ok |
| `chat_stream_c1` | `default_grpc` | 10 | 20 | 567.64 | 617.32 | 617.37 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `default_grpc` | 50 | 20 | 2109.83 | 2142.04 | 2149.59 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `default_grpc` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 2048 | 20 | 61650.05 | 80587.48 | 83081.75 | `corpus_sharegpt` | `natural_eos` | 39 | ok |
| `chat_stream_c1` | `rest_https_edge` | 10 | 20 | 1192.16 | 1674.99 | 1675.13 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `rest_https_edge` | 50 | 20 | 4095.24 | 6043.73 | 6044.43 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `rest_https_edge` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 2048 | 20 | 162256.80 | 240123.43 | 240123.87 | `corpus_sharegpt` | `natural_eos` | 40 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 10 | 20 | 1231.75 | 1785.54 | 1808.42 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 50 | 20 | 4243.84 | 6285.20 | 6296.37 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 2048 | 20 | 161749.77 | 239310.33 | 239331.73 | `corpus_sharegpt` | `natural_eos` | 41 | ok |
| `chat_stream_c4` | `default_grpc` | 10 | 20 | 582.25 | 596.72 | 596.78 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `default_grpc` | 50 | 20 | 2157.95 | 2176.70 | 2176.93 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `default_grpc` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 2048 | 20 | 74802.81 | 87026.94 | 87157.23 | `corpus_sharegpt` | `natural_eos` | 50 | ok |
| `chat_stream_c4` | `rest_https_edge` | 10 | 20 | 1149.66 | 1633.98 | 1634.83 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `rest_https_edge` | 50 | 20 | 4078.86 | 6027.43 | 6027.58 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `rest_https_edge` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 2048 | 20 | 160514.91 | 237729.17 | 237729.26 | `corpus_sharegpt` | `natural_eos` | 52 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 10 | 20 | 1252.04 | 1776.14 | 1782.31 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 50 | 20 | 4194.07 | 6189.92 | 6195.32 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 2048 | 20 | 161620.41 | 239304.64 | 239304.74 | `corpus_sharegpt` | `natural_eos` | 53 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 10 | 20 | 573.26 | 574.71 | 586.16 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 50 | 20 | 2143.50 | 2143.61 | 2143.89 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 2048 | 20 | 41414.93 | 51634.19 | 53971.56 | `corpus_sharegpt` | `natural_eos` | 51 | ok |
| `chat_stream_c8` | `default_grpc` | 10 | 20 | 605.04 | 607.82 | 607.91 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `default_grpc` | 50 | 20 | 2158.04 | 2172.89 | 2172.93 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `default_grpc` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 2048 | 20 | 10950.08 | 17621.87 | 19006.23 | `corpus_sharegpt` | `natural_eos` | 62 | ok |
| `chat_stream_c8` | `rest_https_edge` | 10 | 20 | 1142.59 | 1627.51 | 1628.80 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `rest_https_edge` | 50 | 20 | 4107.73 | 6058.38 | 6062.05 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `rest_https_edge` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 2048 | 20 | 158570.75 | 234692.12 | 234693.07 | `corpus_sharegpt` | `natural_eos` | 64 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 10 | 20 | 1314.20 | 1842.37 | 1868.19 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 50 | 20 | 4195.60 | 6219.58 | 6235.44 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 2048 | 20 | 161897.95 | 239534.12 | 239539.76 | `corpus_sharegpt` | `natural_eos` | 65 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 10 | 20 | 578.12 | 597.64 | 597.71 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 50 | 20 | 2149.53 | 2150.85 | 2163.80 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 2048 | 20 | 84146.32 | 94592.27 | 96753.73 | `corpus_sharegpt` | `natural_eos` | 63 | ok |

## TPOT curves

Interior caps not measured in validate mode (`not_validated`). Curves at `{10, 50, 2048}` only.

| cell | cohort | max_tokens | tpot_ms | status |
|------|--------|-----------:|--------:|--------|
| `chat_stream_c1` | `default_grpc` | 10 | 38.89 | ok |
| `chat_stream_c1` | `default_grpc` | 50 | 39.26 | ok |
| `chat_stream_c1` | `default_grpc` | 256 | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 512 | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 1024 | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 2048 | 42.79 | ok |
| `chat_stream_c1` | `rest_https_edge` | 10 | — | ok |
| `chat_stream_c1` | `rest_https_edge` | 50 | — | ok |
| `chat_stream_c1` | `rest_https_edge` | 256 | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 512 | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 1024 | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 2048 | — | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 10 | — | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 50 | — | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 256 | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 512 | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 1024 | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 2048 | — | ok |
| `chat_stream_c4` | `default_grpc` | 10 | 38.63 | ok |
| `chat_stream_c4` | `default_grpc` | 50 | 39.30 | ok |
| `chat_stream_c4` | `default_grpc` | 256 | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 512 | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 1024 | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 2048 | 43.63 | ok |
| `chat_stream_c4` | `rest_https_edge` | 10 | — | ok |
| `chat_stream_c4` | `rest_https_edge` | 50 | — | ok |
| `chat_stream_c4` | `rest_https_edge` | 256 | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 512 | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 1024 | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 2048 | — | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 10 | — | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 50 | — | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 256 | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 512 | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 1024 | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 2048 | — | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 10 | 38.84 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 50 | 39.30 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 256 | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 512 | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 1024 | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 2048 | 41.73 | ok |
| `chat_stream_c8` | `default_grpc` | 10 | 38.79 | ok |
| `chat_stream_c8` | `default_grpc` | 50 | 39.28 | ok |
| `chat_stream_c8` | `default_grpc` | 256 | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 512 | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 1024 | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 2048 | 39.29 | ok |
| `chat_stream_c8` | `rest_https_edge` | 10 | — | ok |
| `chat_stream_c8` | `rest_https_edge` | 50 | — | ok |
| `chat_stream_c8` | `rest_https_edge` | 256 | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 512 | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 1024 | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 2048 | — | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 10 | — | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 50 | — | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 256 | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 512 | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 1024 | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 2048 | — | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 10 | 38.56 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 50 | 39.29 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 256 | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 512 | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 1024 | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 2048 | 46.20 | ok |

## Engine-cost decomposition curves

Interior caps not measured in validate mode (`not_validated`). Decomposition only available at `{10, 50, 2048}`.

| cell | cohort | max_tokens | seg_ab_ms | seg_queue_ms | seg_prefill_ms | seg_ingress_ms | seg_egress_ms | status |
|------|--------|-----------:|----------:|-------------:|---------------:|---------------:|--------------:|--------|
| `embed_c1` | `default_grpc` | 10 | 1.16 | 0.01 | 99.07 | — | — | ok |
| `embed_c1` | `default_grpc` | 50 | 0.70 | 0.01 | 75.63 | — | — | ok |
| `embed_c1` | `default_grpc` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `default_grpc` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `default_grpc` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `default_grpc` | 2048 | 0.96 | 0.01 | 73.29 | — | — | ok |
| `embed_c1` | `rest_https_edge` | 10 | — | — | — | — | — | ok |
| `embed_c1` | `rest_https_edge` | 50 | — | — | — | — | — | ok |
| `embed_c1` | `rest_https_edge` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `rest_https_edge` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `rest_https_edge` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `rest_https_edge` | 2048 | — | — | — | — | — | ok |
| `embed_c1` | `rest_plain_tcp` | 10 | — | — | — | — | — | ok |
| `embed_c1` | `rest_plain_tcp` | 50 | — | — | — | — | — | ok |
| `embed_c1` | `rest_plain_tcp` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `rest_plain_tcp` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `rest_plain_tcp` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `rest_plain_tcp` | 2048 | — | — | — | — | — | ok |
| `embed_c4` | `default_grpc` | 10 | 0.67 | 0.01 | 78.33 | — | — | ok |
| `embed_c4` | `default_grpc` | 50 | 0.72 | 0.01 | 77.07 | — | — | ok |
| `embed_c4` | `default_grpc` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `default_grpc` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `default_grpc` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `default_grpc` | 2048 | 1.62 | 0.01 | 80.78 | — | — | ok |
| `embed_c4` | `rest_https_edge` | 10 | — | — | — | — | — | ok |
| `embed_c4` | `rest_https_edge` | 50 | — | — | — | — | — | ok |
| `embed_c4` | `rest_https_edge` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `rest_https_edge` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `rest_https_edge` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `rest_https_edge` | 2048 | — | — | — | — | — | ok |
| `embed_c4` | `rest_plain_tcp` | 10 | — | — | — | — | — | ok |
| `embed_c4` | `rest_plain_tcp` | 50 | — | — | — | — | — | ok |
| `embed_c4` | `rest_plain_tcp` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `rest_plain_tcp` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `rest_plain_tcp` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `rest_plain_tcp` | 2048 | — | — | — | — | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 10 | 0.64 | 0.01 | 72.85 | — | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 50 | 0.59 | 0.01 | 76.25 | — | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `tuned_grpc_multiplexed` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `tuned_grpc_multiplexed` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `tuned_grpc_multiplexed` | 2048 | 0.62 | 0.01 | 82.46 | — | — | ok |
| `embed_c8` | `default_grpc` | 10 | 0.67 | 0.01 | 77.87 | — | — | ok |
| `embed_c8` | `default_grpc` | 50 | 0.62 | 0.01 | 76.67 | — | — | ok |
| `embed_c8` | `default_grpc` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `default_grpc` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `default_grpc` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `default_grpc` | 2048 | 0.39 | 0.03 | 70.78 | — | — | ok |
| `embed_c8` | `rest_https_edge` | 10 | — | — | — | — | — | ok |
| `embed_c8` | `rest_https_edge` | 50 | — | — | — | — | — | ok |
| `embed_c8` | `rest_https_edge` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `rest_https_edge` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `rest_https_edge` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `rest_https_edge` | 2048 | — | — | — | — | — | ok |
| `embed_c8` | `rest_plain_tcp` | 10 | — | — | — | — | — | ok |
| `embed_c8` | `rest_plain_tcp` | 50 | — | — | — | — | — | ok |
| `embed_c8` | `rest_plain_tcp` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `rest_plain_tcp` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `rest_plain_tcp` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `rest_plain_tcp` | 2048 | — | — | — | — | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 10 | 0.63 | 0.01 | 74.15 | — | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 50 | 0.64 | 0.01 | 76.47 | — | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `tuned_grpc_multiplexed` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `tuned_grpc_multiplexed` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `tuned_grpc_multiplexed` | 2048 | 0.67 | 0.01 | 78.42 | — | — | ok |
| `chat_stream_c1` | `default_grpc` | 10 | 0.19 | 0.02 | 79.25 | 0.02 | 2.32 | ok |
| `chat_stream_c1` | `default_grpc` | 50 | 0.16 | 0.03 | 77.86 | 0.02 | 2.26 | ok |
| `chat_stream_c1` | `default_grpc` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 2048 | 0.20 | 0.03 | 83.28 | 0.02 | 2.39 | ok |
| `chat_stream_c1` | `rest_https_edge` | 10 | — | — | — | — | — | ok |
| `chat_stream_c1` | `rest_https_edge` | 50 | — | — | — | — | — | ok |
| `chat_stream_c1` | `rest_https_edge` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 2048 | — | — | — | — | — | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 10 | — | — | — | — | — | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 50 | — | — | — | — | — | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 2048 | — | — | — | — | — | ok |
| `chat_stream_c4` | `default_grpc` | 10 | 0.17 | 0.03 | 83.57 | 0.02 | 2.83 | ok |
| `chat_stream_c4` | `default_grpc` | 50 | 0.19 | 0.02 | 82.09 | 0.02 | 2.33 | ok |
| `chat_stream_c4` | `default_grpc` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 2048 | 0.18 | 0.02 | 98.68 | 0.02 | 2.46 | ok |
| `chat_stream_c4` | `rest_https_edge` | 10 | — | — | — | — | — | ok |
| `chat_stream_c4` | `rest_https_edge` | 50 | — | — | — | — | — | ok |
| `chat_stream_c4` | `rest_https_edge` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 2048 | — | — | — | — | — | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 10 | — | — | — | — | — | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 50 | — | — | — | — | — | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 2048 | — | — | — | — | — | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 10 | 0.17 | 0.03 | 78.94 | 0.02 | 2.41 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 50 | 0.18 | 0.03 | 77.44 | 0.03 | 2.40 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 2048 | 0.18 | 0.03 | 82.24 | 0.02 | 2.45 | ok |
| `chat_stream_c8` | `default_grpc` | 10 | 0.18 | 0.04 | 77.79 | 0.02 | 2.70 | ok |
| `chat_stream_c8` | `default_grpc` | 50 | 0.18 | 0.02 | 84.06 | 0.02 | 2.41 | ok |
| `chat_stream_c8` | `default_grpc` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 2048 | 0.17 | 0.03 | 88.51 | 0.02 | 2.41 | ok |
| `chat_stream_c8` | `rest_https_edge` | 10 | — | — | — | — | — | ok |
| `chat_stream_c8` | `rest_https_edge` | 50 | — | — | — | — | — | ok |
| `chat_stream_c8` | `rest_https_edge` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 2048 | — | — | — | — | — | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 10 | — | — | — | — | — | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 50 | — | — | — | — | — | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 2048 | — | — | — | — | — | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 10 | 0.17 | 0.03 | 83.27 | 0.02 | 2.39 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 50 | 0.17 | 0.03 | 81.75 | 0.02 | 3.07 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 2048 | 0.20 | 0.03 | 87.94 | 0.03 | 2.98 | ok |

## Protocol crossover threshold

> **Note**: Validate-mode crossover analysis is restricted to the 3-point axis subset `{10, 50, 2048}`; interior-cap crossover thresholds are unobservable in validate mode. Use the publish-mode artifact for fine-grained crossover threshold attribution.

| cell | m6_1_3_base_verdict | crossover_max_tokens | evidence |
|------|---------------------|---------------------:|----------|
| `chat_stream_c1` | `inconclusive` | — | base verdict was already inconclusive at the M6.1.3 baseline |
| `chat_stream_c4` | `inconclusive` | — | base verdict was already inconclusive at the M6.1.3 baseline |
| `chat_stream_c8` | `inconclusive` | — | base verdict was already inconclusive at the M6.1.3 baseline |
| `embed_c1` | `inconclusive` | — | base verdict was already inconclusive at the M6.1.3 baseline |
| `embed_c4` | `inconclusive` | — | base verdict was already inconclusive at the M6.1.3 baseline |
| `embed_c8` | `inconclusive` | — | base verdict was already inconclusive at the M6.1.3 baseline |

## KV-cache pressure

Measurements below are from the forced-cap sub-probe regime (`ignore_eos=True`) — distinct from the budget-table c=8 rows which use natural EOS under cap.

| cohort | cell_type | wall_clock_ratio_2048/1024 | inference | kv_cache_used_fraction_peak | oom | n |
|--------|-----------|--------------------------:|-----------|----------------------------:|----:|--:|
| `rest_https_edge` | `chat_stream` | 1.806 | `kv_pressure_not_observable` | — | False | 20 |
| `rest_plain_tcp` | `chat_stream` | 2.026 | `kv_pressure_not_observable` | — | False | 20 |
| `default_grpc` | `chat_stream` | 2.060 | `kv_pressure_not_observable` | — | False | 20 |
| `tuned_grpc_multiplexed` | `chat_stream` | 1.911 | `kv_pressure_not_observable` | — | False | 20 |
| `rest_https_edge` | `embed` | 2.046 | `kv_pressure_not_observable` | — | False | 20 |
| `rest_plain_tcp` | `embed` | 2.173 | `kv_pressure_not_observable` | — | False | 20 |
| `default_grpc` | `embed` | 2.142 | `kv_pressure_not_observable` | — | False | 20 |
| `tuned_grpc_multiplexed` | `embed` | 2.126 | `kv_pressure_not_observable` | — | False | 20 |

## Null anchor validation

Cross-checkable cells: 11 (≥ 2 drifted → fires FR-014 `null_anchor_drift` header; currently 11 drifted). New-baseline cells: 37 (excluded from the count by construction).

### Cross-checkable cells (drift verdict against M6.1.3 baseline)

| cell | cohort | max_tokens | m6_2_p50 | m6_1_3_p50 | drift_fraction | verdict |
|------|--------|-----------:|---------:|-----------:|---------------:|---------|
| `chat_stream_c1` | `default_grpc` | 50 | 2109.83 | 1957.91 | 1103.598 | `FAIL` |
| `chat_stream_c1` | `rest_https_edge` | 50 | 4095.24 | 1839.34 | 2666.990 | `FAIL` |
| `chat_stream_c1` | `rest_plain_tcp` | 50 | 4243.84 | 2258.18 | 1518.052 | `FAIL` |
| `chat_stream_c4` | `default_grpc` | 50 | 2157.95 | 2093.98 | 22.788 | `FAIL` |
| `chat_stream_c4` | `rest_https_edge` | 50 | 4078.86 | 2036.51 | 978.493 | `FAIL` |
| `chat_stream_c4` | `rest_plain_tcp` | 50 | 4194.07 | 2870.10 | 603.321 | `FAIL` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 50 | 2143.50 | 2094.09 | 44.097 | `FAIL` |
| `chat_stream_c8` | `default_grpc` | 50 | 2158.04 | 2133.63 | 11.280 | `FAIL` |
| `chat_stream_c8` | `rest_https_edge` | 50 | 4107.73 | 2078.25 | 512.898 | `FAIL` |
| `chat_stream_c8` | `rest_plain_tcp` | 50 | 4195.60 | 2157.84 | 551.779 | `FAIL` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 50 | 2149.53 | 2130.20 | 13.768 | `FAIL` |

### New-baseline cells (no M6.1.3 reference; recorded for posterity)

| cell | cohort | max_tokens | m6_2_p50 | marker |
|------|--------|-----------:|---------:|--------|
| `chat_stream_c1` | `default_grpc` | 10 | 567.64 | `new_baseline_marker` |
| `chat_stream_c1` | `rest_https_edge` | 10 | 1192.16 | `new_baseline_marker` |
| `chat_stream_c1` | `rest_plain_tcp` | 10 | 1231.75 | `new_baseline_marker` |
| `chat_stream_c1` | `tuned_grpc_multiplexed` | 10 | — | `new_baseline_marker` |
| `chat_stream_c1` | `tuned_grpc_multiplexed` | 50 | — | `new_baseline_marker` |
| `chat_stream_c4` | `default_grpc` | 10 | 582.25 | `new_baseline_marker` |
| `chat_stream_c4` | `rest_https_edge` | 10 | 1149.66 | `new_baseline_marker` |
| `chat_stream_c4` | `rest_plain_tcp` | 10 | 1252.04 | `new_baseline_marker` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 10 | 573.26 | `new_baseline_marker` |
| `chat_stream_c8` | `default_grpc` | 10 | 605.04 | `new_baseline_marker` |
| `chat_stream_c8` | `rest_https_edge` | 10 | 1142.59 | `new_baseline_marker` |
| `chat_stream_c8` | `rest_plain_tcp` | 10 | 1314.20 | `new_baseline_marker` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 10 | 578.12 | `new_baseline_marker` |
| `embed_c1` | `default_grpc` | 10 | 1682.22 | `new_baseline_marker` |
| `embed_c1` | `default_grpc` | 50 | 3010.81 | `new_baseline_marker` |
| `embed_c1` | `rest_https_edge` | 10 | 2100.58 | `new_baseline_marker` |
| `embed_c1` | `rest_https_edge` | 50 | 5088.11 | `new_baseline_marker` |
| `embed_c1` | `rest_plain_tcp` | 10 | 2015.40 | `new_baseline_marker` |
| `embed_c1` | `rest_plain_tcp` | 50 | 5183.55 | `new_baseline_marker` |
| `embed_c1` | `tuned_grpc_multiplexed` | 10 | — | `new_baseline_marker` |
| `embed_c1` | `tuned_grpc_multiplexed` | 50 | — | `new_baseline_marker` |
| `embed_c4` | `default_grpc` | 10 | 1127.97 | `new_baseline_marker` |
| `embed_c4` | `default_grpc` | 50 | 2588.22 | `new_baseline_marker` |
| `embed_c4` | `rest_https_edge` | 10 | 1660.28 | `new_baseline_marker` |
| `embed_c4` | `rest_https_edge` | 50 | 4628.59 | `new_baseline_marker` |
| `embed_c4` | `rest_plain_tcp` | 10 | 1926.37 | `new_baseline_marker` |
| `embed_c4` | `rest_plain_tcp` | 50 | 4786.43 | `new_baseline_marker` |
| `embed_c4` | `tuned_grpc_multiplexed` | 10 | 1508.07 | `new_baseline_marker` |
| `embed_c4` | `tuned_grpc_multiplexed` | 50 | 2966.87 | `new_baseline_marker` |
| `embed_c8` | `default_grpc` | 10 | 1190.32 | `new_baseline_marker` |
| `embed_c8` | `default_grpc` | 50 | 2551.70 | `new_baseline_marker` |
| `embed_c8` | `rest_https_edge` | 10 | 1701.51 | `new_baseline_marker` |
| `embed_c8` | `rest_https_edge` | 50 | 4685.50 | `new_baseline_marker` |
| `embed_c8` | `rest_plain_tcp` | 10 | 1805.17 | `new_baseline_marker` |
| `embed_c8` | `rest_plain_tcp` | 50 | 4796.06 | `new_baseline_marker` |
| `embed_c8` | `tuned_grpc_multiplexed` | 10 | 1123.15 | `new_baseline_marker` |
| `embed_c8` | `tuned_grpc_multiplexed` | 50 | 2619.35 | `new_baseline_marker` |

## Anchor latency trajectory

### `default_grpc`

- max_minus_min_wall_p50_ms: `99.005`; latency_drift_warning: `True`

| sweep_hour_mark | snapshot_timestamp | wall_p50_ms | wall_p95_ms | wall_p99_ms |
|----------------:|--------------------|------------:|------------:|------------:|
| 0.00 | `2026-05-23T18:20:41Z` | 699.61 | 707.13 | 732.28 |
| 0.01 | `2026-05-23T18:20:54Z` | 600.60 | 611.26 | 611.37 |
| 0.02 | `2026-05-23T18:21:17Z` | 604.68 | 606.74 | 610.65 |
| 1.08 | `2026-05-23T19:25:20Z` | 688.79 | 690.08 | 690.46 |

### `rest_https_edge`

- max_minus_min_wall_p50_ms: `416.796`; latency_drift_warning: `True`

| sweep_hour_mark | snapshot_timestamp | wall_p50_ms | wall_p95_ms | wall_p99_ms |
|----------------:|--------------------|------------:|------------:|------------:|
| 0.00 | `2026-05-23T18:20:39Z` | 1489.05 | 1985.93 | 1986.40 |
| 0.01 | `2026-05-23T18:20:52Z` | 1072.26 | 1548.23 | 1570.95 |
| 0.02 | `2026-05-23T18:21:15Z` | 1153.70 | 1644.54 | 1648.55 |
| 1.08 | `2026-05-23T19:25:18Z` | 1161.68 | 1645.99 | 1669.13 |

### `rest_plain_tcp`

- max_minus_min_wall_p50_ms: `82.101`; latency_drift_warning: `True`

| sweep_hour_mark | snapshot_timestamp | wall_p50_ms | wall_p95_ms | wall_p99_ms |
|----------------:|--------------------|------------:|------------:|------------:|
| 0.00 | `2026-05-23T18:20:41Z` | 1177.06 | 1724.92 | 1774.78 |
| 0.01 | `2026-05-23T18:20:54Z` | 1259.16 | 1803.58 | 1807.93 |
| 0.02 | `2026-05-23T18:21:17Z` | 1230.49 | 1773.66 | 1779.66 |
| 1.08 | `2026-05-23T19:25:20Z` | 1254.26 | 1781.88 | 1803.40 |

### `tuned_grpc_multiplexed`

- max_minus_min_wall_p50_ms: `15.274`; latency_drift_warning: `True`

| sweep_hour_mark | snapshot_timestamp | wall_p50_ms | wall_p95_ms | wall_p99_ms |
|----------------:|--------------------|------------:|------------:|------------:|
| 0.00 | `2026-05-23T18:20:42Z` | 568.65 | 605.55 | 605.67 |
| 0.01 | `2026-05-23T18:20:55Z` | 569.79 | 611.85 | 611.91 |
| 0.02 | `2026-05-23T18:21:18Z` | 580.44 | 620.15 | 620.29 |
| 1.08 | `2026-05-23T19:25:21Z` | 565.17 | 567.37 | 593.01 |

## Failure summary

_No measurement-cell failures._

## Network paths

| cohort | snapshot # | cloud_provider | region | endpoint_ip | status |
|--------|-----------:|----------------|--------|-------------|--------|
| `default_grpc` | 0 | AWS | us-west-1 | `54.183.130.86` | ok |
| `default_grpc` | 1 | AWS | us-west-1 | `54.183.130.86` | ok |
| `rest_https_edge` | 0 | unknown | — | `129.146.27.141` | ok |
| `rest_https_edge` | 1 | unknown | — | `129.146.27.141` | ok |
| `rest_plain_tcp` | 0 | AWS | us-west-1 | `54.193.31.244` | ok |
| `rest_plain_tcp` | 1 | AWS | us-west-1 | `54.193.31.244` | ok |
| `tuned_grpc_multiplexed` | 0 | AWS | us-west-1 | `54.183.130.86` | ok |
| `tuned_grpc_multiplexed` | 1 | AWS | us-west-1 | `54.183.130.86` | ok |

## Method / Background

This milestone builds on M6.1.3's published per-cohort attribution at `max_tokens=10/50`; see [m6_1_3-attribution-closure.md](m6_1_3-attribution-closure.md) for the baseline CIs and cohort omissions. The null-anchor validation section below pairs each cross-checkable M6.2 anchor measurement against that baseline (FR-012 / FR-013).

