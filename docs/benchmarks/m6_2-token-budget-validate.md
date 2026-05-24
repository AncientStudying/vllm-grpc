# M6.2 — Token-Budget Characterization

- run_id: `2026-05-24T16:17:01Z-e2336315`
- sweep_mode: `validate`
- modal_region: `eu-west-1`
- model: `Qwen/Qwen3-8B`
- base_seed: `42`
- iteration_order: `cohort_innermost_block`
- iteration_discipline_verified: `True`
- n_per_point: `20`
- validate_axis_subset: `[10, 50, 2048]`
- wall_clock_start_utc: `2026-05-24T16:17:01Z`
- wall_clock_end_utc: `2026-05-24T19:54:54Z`
- total_sweep_hours: `3.631`
- chat_corpus_sha256: `4442302df439fdc1967e9fb48a88910cee5d0f712592e733d47bdbbc1e0374f1`
- embed_corpus_sha256: `19a3b43bc34017615d175ea914b362f9d26a39bd2742b27af7e42f2b97df38a0`
- sub_probe_ran: `True`
- preemption_events: `0`
- run_started_at: `2026-05-24T16:17:01Z`
- run_completed_at: `2026-05-24T19:54:54Z`

> **WARNING (null_anchor_drift)**: ≥ 2 of the 22 cross-checkable null-anchor cells drifted against the M6.1.3 baseline (FR-014 / SC-004). Operator decides publish vs rerun.
>
> **WARNING (trajectory_insufficient_snapshots)**: At least one cohort has fewer than 2 post-warmup anchor snapshots (C1 round-8 amendment, FR-031). The intra-sweep drift verdict for that cohort was suppressed. Soft diagnostic — informational only, validate-mode start+end trajectories naturally hit this fallback.

## Production latency budget

Validate-mode axis subset is `{10, 50, 2048}`; interior caps (`{256, 512, 1024}`) carry `not_validated` placeholders. Use the publish-mode artifact for the full 6-point budget.

| cell | cohort | max_tokens | n | wall_p50_ms | wall_p95_ms | wall_p99_ms | prompt_source | regime | corpus_idx | status |
|------|--------|-----------:|---:|------------:|------------:|------------:|---------------|--------|-----------:|--------|
| `embed_c1` | `default_grpc` | 10 | 20 | 576.36 | 874.53 | 878.36 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `default_grpc` | 50 | 20 | 1933.81 | 1943.46 | 1952.52 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `default_grpc` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `default_grpc` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `default_grpc` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `default_grpc` | 2048 | 20 | 70615.65 | 70800.97 | 70879.16 | `corpus_sharegpt_embed` | `natural_eos` | 6 | ok |
| `embed_c1` | `rest_https_edge` | 10 | 20 | 499.42 | 570.68 | 708.20 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `rest_https_edge` | 50 | 20 | 1939.73 | 2093.36 | 2105.59 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `rest_https_edge` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `rest_https_edge` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `rest_https_edge` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `rest_https_edge` | 2048 | 20 | 64833.37 | 65225.21 | 65404.68 | `corpus_sharegpt_embed` | `natural_eos` | 7 | ok |
| `embed_c1` | `rest_plain_tcp` | 10 | 20 | 530.47 | 622.31 | 719.81 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `rest_plain_tcp` | 50 | 20 | 1996.26 | 2361.88 | 2592.19 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `rest_plain_tcp` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `rest_plain_tcp` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `rest_plain_tcp` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c1` | `rest_plain_tcp` | 2048 | 20 | 72525.79 | 72728.68 | 72735.96 | `corpus_sharegpt_embed` | `natural_eos` | 8 | ok |
| `embed_c4` | `default_grpc` | 10 | 20 | 573.59 | 1115.42 | 1147.26 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `default_grpc` | 50 | 20 | 2058.67 | 2115.76 | 2144.56 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `default_grpc` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `default_grpc` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `default_grpc` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `default_grpc` | 2048 | 20 | 74348.80 | 78213.64 | 78298.48 | `corpus_sharegpt_embed` | `natural_eos` | 17 | ok |
| `embed_c4` | `rest_https_edge` | 10 | 20 | 628.07 | 893.49 | 1030.04 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `rest_https_edge` | 50 | 20 | 2026.99 | 2276.73 | 2283.54 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `rest_https_edge` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `rest_https_edge` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `rest_https_edge` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `rest_https_edge` | 2048 | 20 | 78037.16 | 78291.40 | 78308.19 | `corpus_sharegpt_embed` | `natural_eos` | 19 | ok |
| `embed_c4` | `rest_plain_tcp` | 10 | 20 | 595.97 | 938.85 | 982.56 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `rest_plain_tcp` | 50 | 20 | 2112.10 | 2315.81 | 2328.66 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `rest_plain_tcp` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `rest_plain_tcp` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `rest_plain_tcp` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `rest_plain_tcp` | 2048 | 20 | 78032.75 | 78307.96 | 78308.46 | `corpus_sharegpt_embed` | `natural_eos` | 20 | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 10 | 20 | 549.23 | 988.53 | 1020.74 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 50 | 20 | 2119.41 | 2353.92 | 2419.05 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `tuned_grpc_multiplexed` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `tuned_grpc_multiplexed` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c4` | `tuned_grpc_multiplexed` | 2048 | 20 | 77864.87 | 78480.07 | 78511.86 | `corpus_sharegpt_embed` | `natural_eos` | 18 | ok |
| `embed_c8` | `default_grpc` | 10 | 20 | 1111.59 | 1670.16 | 1704.94 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `default_grpc` | 50 | 20 | 2244.73 | 2919.73 | 3193.65 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `default_grpc` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `default_grpc` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `default_grpc` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `default_grpc` | 2048 | 20 | 80981.84 | 81137.62 | 81232.15 | `corpus_sharegpt_embed` | `natural_eos` | 29 | ok |
| `embed_c8` | `rest_https_edge` | 10 | 20 | 723.02 | 1038.24 | 1041.04 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `rest_https_edge` | 50 | 20 | 2213.16 | 2775.43 | 2980.01 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `rest_https_edge` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `rest_https_edge` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `rest_https_edge` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `rest_https_edge` | 2048 | 20 | 80528.00 | 81249.07 | 81329.14 | `corpus_sharegpt_embed` | `natural_eos` | 31 | ok |
| `embed_c8` | `rest_plain_tcp` | 10 | 20 | 933.50 | 1093.20 | 1608.52 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `rest_plain_tcp` | 50 | 20 | 2292.00 | 2532.00 | 2593.07 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `rest_plain_tcp` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `rest_plain_tcp` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `rest_plain_tcp` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `rest_plain_tcp` | 2048 | 20 | 78549.70 | 81072.82 | 81337.88 | `corpus_sharegpt_embed` | `natural_eos` | 32 | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 10 | 20 | 772.21 | 1753.82 | 1784.12 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 50 | 20 | 2158.28 | 2410.59 | 2468.04 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 256 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `tuned_grpc_multiplexed` | 512 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `tuned_grpc_multiplexed` | 1024 | 0 | — | — | — | `corpus_sharegpt_embed` | `natural_eos` | — | `not_validated` |
| `embed_c8` | `tuned_grpc_multiplexed` | 2048 | 20 | 81281.55 | 81817.98 | 81911.90 | `corpus_sharegpt_embed` | `natural_eos` | 30 | ok |
| `chat_stream_c1` | `default_grpc` | 10 | 20 | 452.70 | 481.67 | 616.88 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `default_grpc` | 50 | 20 | 1870.01 | 1905.67 | 1907.51 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `default_grpc` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 2048 | 20 | 48690.13 | 71187.63 | 71396.04 | `corpus_sharegpt` | `natural_eos` | 39 | ok |
| `chat_stream_c1` | `rest_https_edge` | 10 | 20 | 425.16 | 447.43 | 555.03 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `rest_https_edge` | 50 | 20 | 1837.55 | 1890.99 | 1913.08 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `rest_https_edge` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 2048 | 20 | 72290.98 | 72529.93 | 72674.72 | `corpus_sharegpt` | `natural_eos` | 40 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 10 | 20 | 476.47 | 543.99 | 630.88 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 50 | 20 | 1859.11 | 1917.98 | 1947.35 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 2048 | 20 | 72230.36 | 72520.55 | 72546.42 | `corpus_sharegpt` | `natural_eos` | 41 | ok |
| `chat_stream_c4` | `default_grpc` | 10 | 20 | 528.99 | 572.40 | 577.53 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `default_grpc` | 50 | 20 | 2009.23 | 2074.08 | 2074.33 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `default_grpc` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 2048 | 20 | 62530.86 | 74364.68 | 76699.78 | `corpus_sharegpt` | `natural_eos` | 50 | ok |
| `chat_stream_c4` | `rest_https_edge` | 10 | 20 | 512.55 | 649.98 | 650.45 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `rest_https_edge` | 50 | 20 | 1956.34 | 2045.69 | 2045.72 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `rest_https_edge` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 2048 | 20 | 77054.43 | 77399.21 | 77399.88 | `corpus_sharegpt` | `natural_eos` | 52 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 10 | 20 | 529.78 | 676.14 | 676.38 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 50 | 20 | 2016.84 | 2076.17 | 2091.80 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 2048 | 20 | 77746.74 | 77984.16 | 78000.80 | `corpus_sharegpt` | `natural_eos` | 53 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 10 | 20 | 534.36 | 599.01 | 599.29 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 50 | 20 | 1992.49 | 2039.32 | 2039.60 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 2048 | 20 | 37912.63 | 43864.92 | 50468.75 | `corpus_sharegpt` | `natural_eos` | 51 | ok |
| `chat_stream_c8` | `default_grpc` | 10 | 20 | 546.71 | 592.32 | 609.80 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `default_grpc` | 50 | 20 | 2002.34 | 2014.21 | 2028.01 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `default_grpc` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 2048 | 20 | 10167.86 | 17013.94 | 17068.42 | `corpus_sharegpt` | `natural_eos` | 62 | ok |
| `chat_stream_c8` | `rest_https_edge` | 10 | 20 | 559.78 | 704.22 | 707.14 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `rest_https_edge` | 50 | 20 | 2036.69 | 2163.14 | 2164.05 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `rest_https_edge` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 2048 | 20 | 79290.09 | 79349.88 | 79350.41 | `corpus_sharegpt` | `natural_eos` | 64 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 10 | 20 | 563.52 | 671.88 | 673.29 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 50 | 20 | 2050.13 | 2146.77 | 2159.72 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 2048 | 20 | 80703.44 | 80965.13 | 80965.70 | `corpus_sharegpt` | `natural_eos` | 65 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 10 | 20 | 536.23 | 566.91 | 566.99 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 50 | 20 | 2019.46 | 2050.51 | 2050.72 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 256 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 512 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 1024 | 0 | — | — | — | `corpus_sharegpt` | `natural_eos` | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 2048 | 20 | 73804.57 | 74109.58 | 74109.85 | `corpus_sharegpt` | `natural_eos` | 63 | ok |

## Prompt-driven early-EOS audit

The cells below terminated via natural EOS at fewer than `50%` of the `max_tokens` cap (threshold `EARLY_EOS_RATIO_THRESHOLD = 0.5`, minimum cap `EARLY_EOS_AUDIT_MIN_MAX_TOKENS = 256`). Each cell draws a single corpus prompt per block (see `m6_2_sweep.py:546` + `assign_symmetric_prompt`); adjacent cohort blocks for the same `(cell, max_tokens)` draw *different* prompts, so per-cohort `wall_p50_ms` at high `max_tokens` in `natural_eos` regime confounds protocol cost with prompt-content distribution. The flagged rows are not protocol pathologies — they are cells whose corpus prompt elicited a short response and stopped early.

For a clean cohort-axis protocol comparison at large `max_tokens` use either the §"TPOT curves" table (protocol-invariant per-token decode cost) or the §"KV-cache pressure" sub-probe (forced-cap via `ignore_eos=True`, prompt-content held constant).

| cell | cohort | max_tokens | corpus_idx | wall_p50_ms | tpot_ms | implied_output_tokens | implied/cap |
|------|--------|-----------:|-----------:|------------:|--------:|---------------------:|------------:|
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 2048 | 51 | 37912.63 | 37.46 | 1010 | 0.49 |
| `chat_stream_c8` | `default_grpc` | 2048 | 62 | 10167.86 | 37.77 | 267 | 0.13 |

## TPOT curves

Interior caps not measured in validate mode (`not_validated`). Curves at `{10, 50, 2048}` only.

| cell | cohort | max_tokens | tpot_ms | status |
|------|--------|-----------:|--------:|--------|
| `chat_stream_c1` | `default_grpc` | 10 | 34.66 | ok |
| `chat_stream_c1` | `default_grpc` | 50 | 35.28 | ok |
| `chat_stream_c1` | `default_grpc` | 256 | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 512 | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 1024 | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 2048 | 35.39 | ok |
| `chat_stream_c1` | `rest_https_edge` | 10 | 34.68 | ok |
| `chat_stream_c1` | `rest_https_edge` | 50 | 35.19 | ok |
| `chat_stream_c1` | `rest_https_edge` | 256 | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 512 | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 1024 | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 2048 | 35.46 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 10 | 34.92 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 50 | 35.19 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 256 | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 512 | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 1024 | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 2048 | 35.49 | ok |
| `chat_stream_c4` | `default_grpc` | 10 | 36.75 | ok |
| `chat_stream_c4` | `default_grpc` | 50 | 37.03 | ok |
| `chat_stream_c4` | `default_grpc` | 256 | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 512 | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 1024 | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 2048 | 37.99 | ok |
| `chat_stream_c4` | `rest_https_edge` | 10 | 37.31 | ok |
| `chat_stream_c4` | `rest_https_edge` | 50 | 36.76 | ok |
| `chat_stream_c4` | `rest_https_edge` | 256 | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 512 | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 1024 | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 2048 | 38.13 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 10 | 36.72 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 50 | 36.94 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 256 | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 512 | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 1024 | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 2048 | 38.23 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 10 | 37.66 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 50 | 36.94 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 256 | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 512 | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 1024 | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 2048 | 37.46 | ok |
| `chat_stream_c8` | `default_grpc` | 10 | 36.80 | ok |
| `chat_stream_c8` | `default_grpc` | 50 | 37.20 | ok |
| `chat_stream_c8` | `default_grpc` | 256 | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 512 | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 1024 | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 2048 | 37.77 | ok |
| `chat_stream_c8` | `rest_https_edge` | 10 | 37.08 | ok |
| `chat_stream_c8` | `rest_https_edge` | 50 | 37.73 | ok |
| `chat_stream_c8` | `rest_https_edge` | 256 | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 512 | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 1024 | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 2048 | 39.47 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 10 | 37.17 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 50 | 37.29 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 256 | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 512 | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 1024 | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 2048 | 39.27 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 10 | 37.23 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 50 | 37.22 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 256 | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 512 | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 1024 | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 2048 | 39.50 | ok |

## Engine-cost decomposition curves

Interior caps not measured in validate mode (`not_validated`). Decomposition only available at `{10, 50, 2048}`.

| cell | cohort | max_tokens | seg_ab_ms | seg_queue_ms | seg_prefill_ms | seg_ingress_ms | seg_egress_ms | status |
|------|--------|-----------:|----------:|-------------:|---------------:|---------------:|--------------:|--------|
| `embed_c1` | `default_grpc` | 10 | 1.33 | 0.02 | 43.49 | — | — | ok |
| `embed_c1` | `default_grpc` | 50 | 0.71 | 0.02 | 40.95 | — | — | ok |
| `embed_c1` | `default_grpc` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `default_grpc` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `default_grpc` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `default_grpc` | 2048 | 0.80 | 0.02 | 39.03 | — | — | ok |
| `embed_c1` | `rest_https_edge` | 10 | 1.07 | 0.01 | 39.94 | — | — | ok |
| `embed_c1` | `rest_https_edge` | 50 | 1.13 | 0.02 | 41.17 | — | — | ok |
| `embed_c1` | `rest_https_edge` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `rest_https_edge` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `rest_https_edge` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `rest_https_edge` | 2048 | 6.65 | 0.01 | 42.88 | — | — | ok |
| `embed_c1` | `rest_plain_tcp` | 10 | 1.07 | 0.01 | 39.94 | — | — | ok |
| `embed_c1` | `rest_plain_tcp` | 50 | 1.28 | 0.02 | 41.30 | — | — | ok |
| `embed_c1` | `rest_plain_tcp` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `rest_plain_tcp` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `rest_plain_tcp` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c1` | `rest_plain_tcp` | 2048 | 0.96 | 0.02 | 41.42 | — | — | ok |
| `embed_c4` | `default_grpc` | 10 | 0.97 | 0.01 | 76.92 | — | — | ok |
| `embed_c4` | `default_grpc` | 50 | 0.95 | 0.01 | 69.81 | — | — | ok |
| `embed_c4` | `default_grpc` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `default_grpc` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `default_grpc` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `default_grpc` | 2048 | 1.67 | 0.01 | 79.07 | — | — | ok |
| `embed_c4` | `rest_https_edge` | 10 | 1.51 | 0.01 | 71.42 | — | — | ok |
| `embed_c4` | `rest_https_edge` | 50 | 1.28 | 0.01 | 72.52 | — | — | ok |
| `embed_c4` | `rest_https_edge` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `rest_https_edge` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `rest_https_edge` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `rest_https_edge` | 2048 | 2.44 | 0.01 | 78.53 | — | — | ok |
| `embed_c4` | `rest_plain_tcp` | 10 | 1.60 | 0.01 | 67.18 | — | — | ok |
| `embed_c4` | `rest_plain_tcp` | 50 | 1.88 | 0.01 | 68.44 | — | — | ok |
| `embed_c4` | `rest_plain_tcp` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `rest_plain_tcp` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `rest_plain_tcp` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `rest_plain_tcp` | 2048 | 2.08 | 0.01 | 72.69 | — | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 10 | 1.20 | 0.01 | 71.28 | — | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 50 | 0.76 | 0.01 | 69.11 | — | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `tuned_grpc_multiplexed` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `tuned_grpc_multiplexed` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c4` | `tuned_grpc_multiplexed` | 2048 | 1.40 | 0.01 | 102.67 | — | — | ok |
| `embed_c8` | `default_grpc` | 10 | 1.02 | 0.01 | 76.34 | — | — | ok |
| `embed_c8` | `default_grpc` | 50 | 1.03 | 0.01 | 74.37 | — | — | ok |
| `embed_c8` | `default_grpc` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `default_grpc` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `default_grpc` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `default_grpc` | 2048 | 0.88 | 0.01 | 68.79 | — | — | ok |
| `embed_c8` | `rest_https_edge` | 10 | 1.66 | 0.02 | 72.54 | — | — | ok |
| `embed_c8` | `rest_https_edge` | 50 | 1.38 | 0.01 | 75.67 | — | — | ok |
| `embed_c8` | `rest_https_edge` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `rest_https_edge` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `rest_https_edge` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `rest_https_edge` | 2048 | 1.60 | 0.01 | 81.55 | — | — | ok |
| `embed_c8` | `rest_plain_tcp` | 10 | 1.36 | 0.01 | 72.07 | — | — | ok |
| `embed_c8` | `rest_plain_tcp` | 50 | 1.69 | 0.01 | 72.45 | — | — | ok |
| `embed_c8` | `rest_plain_tcp` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `rest_plain_tcp` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `rest_plain_tcp` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `rest_plain_tcp` | 2048 | 4.44 | 0.01 | 81.45 | — | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 10 | 0.99 | 0.01 | 73.29 | — | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 50 | 0.73 | 0.01 | 73.94 | — | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 256 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `tuned_grpc_multiplexed` | 512 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `tuned_grpc_multiplexed` | 1024 | — | — | — | — | — | `not_validated` |
| `embed_c8` | `tuned_grpc_multiplexed` | 2048 | 1.07 | 0.01 | 82.19 | — | — | ok |
| `chat_stream_c1` | `default_grpc` | 10 | 0.32 | 0.02 | 42.52 | 0.06 | 6.24 | ok |
| `chat_stream_c1` | `default_grpc` | 50 | 0.42 | 0.02 | 43.03 | 0.06 | 6.10 | ok |
| `chat_stream_c1` | `default_grpc` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `default_grpc` | 2048 | 0.44 | 0.02 | 44.46 | 0.12 | 4.62 | ok |
| `chat_stream_c1` | `rest_https_edge` | 10 | 0.43 | 0.02 | 46.37 | 0.06 | 8.82 | ok |
| `chat_stream_c1` | `rest_https_edge` | 50 | 0.17 | 0.02 | 44.01 | 0.07 | 8.02 | ok |
| `chat_stream_c1` | `rest_https_edge` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `rest_https_edge` | 2048 | 0.36 | 0.02 | 44.30 | 0.07 | 4.46 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 10 | 0.26 | 0.02 | 44.91 | 0.06 | 6.84 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 50 | 0.52 | 0.02 | 43.75 | 0.06 | 5.52 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c1` | `rest_plain_tcp` | 2048 | 0.28 | 0.02 | 39.21 | 0.06 | 5.90 | ok |
| `chat_stream_c4` | `default_grpc` | 10 | 0.33 | 0.01 | 69.59 | 0.05 | 3.50 | ok |
| `chat_stream_c4` | `default_grpc` | 50 | 0.68 | 0.01 | 67.52 | 0.06 | 8.05 | ok |
| `chat_stream_c4` | `default_grpc` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `default_grpc` | 2048 | 0.62 | 0.01 | 78.98 | 0.07 | 6.45 | ok |
| `chat_stream_c4` | `rest_https_edge` | 10 | 0.14 | 0.01 | 76.18 | 0.04 | 5.08 | ok |
| `chat_stream_c4` | `rest_https_edge` | 50 | 0.08 | 0.01 | 73.67 | 0.05 | 3.26 | ok |
| `chat_stream_c4` | `rest_https_edge` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `rest_https_edge` | 2048 | 0.20 | 0.01 | 81.32 | 0.06 | 5.89 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 10 | 0.15 | 0.01 | 71.56 | 0.06 | 4.81 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 50 | 0.69 | 0.01 | 72.87 | 0.07 | 8.31 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `rest_plain_tcp` | 2048 | 0.18 | 0.01 | 69.40 | 0.06 | 6.07 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 10 | 0.62 | 0.01 | 71.39 | 0.07 | 5.70 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 50 | 0.37 | 0.01 | 69.25 | 0.06 | 5.88 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 2048 | 0.36 | 0.01 | 76.75 | 0.06 | 4.63 | ok |
| `chat_stream_c8` | `default_grpc` | 10 | 0.44 | 0.02 | 75.57 | 0.07 | 10.64 | ok |
| `chat_stream_c8` | `default_grpc` | 50 | 0.51 | 0.02 | 70.04 | 0.05 | 6.92 | ok |
| `chat_stream_c8` | `default_grpc` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `default_grpc` | 2048 | 0.37 | 0.01 | 74.44 | 0.06 | 6.68 | ok |
| `chat_stream_c8` | `rest_https_edge` | 10 | 0.34 | 0.01 | 78.46 | 0.06 | 9.02 | ok |
| `chat_stream_c8` | `rest_https_edge` | 50 | 0.47 | 0.02 | 82.73 | 0.05 | 9.63 | ok |
| `chat_stream_c8` | `rest_https_edge` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `rest_https_edge` | 2048 | 0.10 | 0.02 | 77.28 | 0.05 | 10.88 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 10 | 0.41 | 0.02 | 76.15 | 0.05 | 7.54 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 50 | 0.16 | 0.01 | 83.43 | 0.05 | 8.54 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `rest_plain_tcp` | 2048 | 0.19 | 0.02 | 76.44 | 0.06 | 10.58 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 10 | 0.39 | 0.02 | 77.07 | 0.04 | 6.09 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 50 | 0.60 | 0.02 | 71.42 | 0.05 | 9.07 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 256 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 512 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 1024 | — | — | — | — | — | `not_validated` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 2048 | 0.27 | 0.02 | 80.59 | 0.05 | 5.15 | ok |

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
| `rest_https_edge` | `chat_stream` | 1.803 | `kv_pressure_not_observable` | — | False | 20 |
| `rest_plain_tcp` | `chat_stream` | 2.015 | `kv_pressure_not_observable` | — | False | 20 |
| `default_grpc` | `chat_stream` | 2.001 | `kv_pressure_not_observable` | — | False | 20 |
| `tuned_grpc_multiplexed` | `chat_stream` | 1.831 | `kv_pressure_not_observable` | — | False | 20 |
| `rest_https_edge` | `embed` | 2.049 | `kv_pressure_not_observable` | — | False | 20 |
| `rest_plain_tcp` | `embed` | 1.945 | `kv_pressure_not_observable` | — | False | 20 |
| `default_grpc` | `embed` | 2.045 | `kv_pressure_not_observable` | — | False | 20 |
| `tuned_grpc_multiplexed` | `embed` | 2.025 | `kv_pressure_not_observable` | — | False | 20 |

## Null anchor validation

Cross-checkable cells: 11 (≥ 2 drifted → fires FR-014 `null_anchor_drift` header; currently 9 drifted). New-baseline cells: 37 (excluded from the count by construction).

### Cross-checkable cells (drift verdict against M6.1.3 baseline)

| cell | cohort | max_tokens | m6_2_p50 | m6_1_3_p50 | drift_fraction | verdict |
|------|--------|-----------:|---------:|-----------:|---------------:|---------|
| `chat_stream_c1` | `default_grpc` | 50 | 1870.01 | 1957.91 | -1.796 | `WARN` |
| `chat_stream_c1` | `rest_https_edge` | 50 | 1837.55 | 1839.34 | -0.039 | `PASS` |
| `chat_stream_c1` | `rest_plain_tcp` | 50 | 1859.11 | 2258.18 | -7.069 | `FAIL` |
| `chat_stream_c4` | `default_grpc` | 50 | 2009.23 | 2093.98 | -1.619 | `WARN` |
| `chat_stream_c4` | `rest_https_edge` | 50 | 1956.34 | 2036.51 | -1.575 | `WARN` |
| `chat_stream_c4` | `rest_plain_tcp` | 50 | 2016.84 | 2870.10 | -11.892 | `FAIL` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 50 | 1992.49 | 2094.09 | -1.941 | `WARN` |
| `chat_stream_c8` | `default_grpc` | 50 | 2002.34 | 2133.63 | -2.461 | `WARN` |
| `chat_stream_c8` | `rest_https_edge` | 50 | 2036.69 | 2078.25 | -0.800 | `PASS` |
| `chat_stream_c8` | `rest_plain_tcp` | 50 | 2050.13 | 2157.84 | -1.997 | `WARN` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 50 | 2019.46 | 2130.20 | -2.079 | `WARN` |

### New-baseline cells (no M6.1.3 reference; recorded for posterity)

| cell | cohort | max_tokens | m6_2_p50 | marker |
|------|--------|-----------:|---------:|--------|
| `chat_stream_c1` | `default_grpc` | 10 | 452.70 | `new_baseline_marker` |
| `chat_stream_c1` | `rest_https_edge` | 10 | 425.16 | `new_baseline_marker` |
| `chat_stream_c1` | `rest_plain_tcp` | 10 | 476.47 | `new_baseline_marker` |
| `chat_stream_c1` | `tuned_grpc_multiplexed` | 10 | — | `new_baseline_marker` |
| `chat_stream_c1` | `tuned_grpc_multiplexed` | 50 | — | `new_baseline_marker` |
| `chat_stream_c4` | `default_grpc` | 10 | 528.99 | `new_baseline_marker` |
| `chat_stream_c4` | `rest_https_edge` | 10 | 512.55 | `new_baseline_marker` |
| `chat_stream_c4` | `rest_plain_tcp` | 10 | 529.78 | `new_baseline_marker` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 10 | 534.36 | `new_baseline_marker` |
| `chat_stream_c8` | `default_grpc` | 10 | 546.71 | `new_baseline_marker` |
| `chat_stream_c8` | `rest_https_edge` | 10 | 559.78 | `new_baseline_marker` |
| `chat_stream_c8` | `rest_plain_tcp` | 10 | 563.52 | `new_baseline_marker` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 10 | 536.23 | `new_baseline_marker` |
| `embed_c1` | `default_grpc` | 10 | 576.36 | `new_baseline_marker` |
| `embed_c1` | `default_grpc` | 50 | 1933.81 | `new_baseline_marker` |
| `embed_c1` | `rest_https_edge` | 10 | 499.42 | `new_baseline_marker` |
| `embed_c1` | `rest_https_edge` | 50 | 1939.73 | `new_baseline_marker` |
| `embed_c1` | `rest_plain_tcp` | 10 | 530.47 | `new_baseline_marker` |
| `embed_c1` | `rest_plain_tcp` | 50 | 1996.26 | `new_baseline_marker` |
| `embed_c1` | `tuned_grpc_multiplexed` | 10 | — | `new_baseline_marker` |
| `embed_c1` | `tuned_grpc_multiplexed` | 50 | — | `new_baseline_marker` |
| `embed_c4` | `default_grpc` | 10 | 573.59 | `new_baseline_marker` |
| `embed_c4` | `default_grpc` | 50 | 2058.67 | `new_baseline_marker` |
| `embed_c4` | `rest_https_edge` | 10 | 628.07 | `new_baseline_marker` |
| `embed_c4` | `rest_https_edge` | 50 | 2026.99 | `new_baseline_marker` |
| `embed_c4` | `rest_plain_tcp` | 10 | 595.97 | `new_baseline_marker` |
| `embed_c4` | `rest_plain_tcp` | 50 | 2112.10 | `new_baseline_marker` |
| `embed_c4` | `tuned_grpc_multiplexed` | 10 | 549.23 | `new_baseline_marker` |
| `embed_c4` | `tuned_grpc_multiplexed` | 50 | 2119.41 | `new_baseline_marker` |
| `embed_c8` | `default_grpc` | 10 | 1111.59 | `new_baseline_marker` |
| `embed_c8` | `default_grpc` | 50 | 2244.73 | `new_baseline_marker` |
| `embed_c8` | `rest_https_edge` | 10 | 723.02 | `new_baseline_marker` |
| `embed_c8` | `rest_https_edge` | 50 | 2213.16 | `new_baseline_marker` |
| `embed_c8` | `rest_plain_tcp` | 10 | 933.50 | `new_baseline_marker` |
| `embed_c8` | `rest_plain_tcp` | 50 | 2292.00 | `new_baseline_marker` |
| `embed_c8` | `tuned_grpc_multiplexed` | 10 | 772.21 | `new_baseline_marker` |
| `embed_c8` | `tuned_grpc_multiplexed` | 50 | 2158.28 | `new_baseline_marker` |

## Anchor latency trajectory

### `default_grpc`

- max_minus_min_wall_p50_ms: `0.000`; latency_drift_warning: `False`

| sweep_hour_mark | snapshot_timestamp | wall_p50_ms | wall_p95_ms | wall_p99_ms |
|----------------:|--------------------|------------:|------------:|------------:|
| 0.00 | `2026-05-24T16:17:52Z` | 457.41 | 463.29 | 463.54 |
| 3.63 | `2026-05-24T19:55:22Z` | 467.61 | 482.37 | 487.33 |

### `rest_https_edge`

- max_minus_min_wall_p50_ms: `0.000`; latency_drift_warning: `False`

| sweep_hour_mark | snapshot_timestamp | wall_p50_ms | wall_p95_ms | wall_p99_ms |
|----------------:|--------------------|------------:|------------:|------------:|
| 0.00 | `2026-05-24T16:17:33Z` | 408.47 | 450.93 | 913.45 |
| 3.63 | `2026-05-24T19:55:03Z` | 423.64 | 449.89 | 556.07 |

### `rest_plain_tcp`

- max_minus_min_wall_p50_ms: `0.000`; latency_drift_warning: `False`

| sweep_hour_mark | snapshot_timestamp | wall_p50_ms | wall_p95_ms | wall_p99_ms |
|----------------:|--------------------|------------:|------------:|------------:|
| 0.00 | `2026-05-24T16:17:43Z` | 461.43 | 493.84 | 518.14 |
| 3.63 | `2026-05-24T19:55:12Z` | 472.19 | 493.14 | 579.65 |

### `tuned_grpc_multiplexed`

- max_minus_min_wall_p50_ms: `0.000`; latency_drift_warning: `False`

| sweep_hour_mark | snapshot_timestamp | wall_p50_ms | wall_p95_ms | wall_p99_ms |
|----------------:|--------------------|------------:|------------:|------------:|
| 0.00 | `2026-05-24T16:18:01Z` | 450.54 | 465.34 | 473.35 |
| 3.63 | `2026-05-24T19:55:31Z` | 445.42 | 464.92 | 467.98 |

## Failure summary

_No measurement-cell failures._

## Network paths

| cohort | snapshot # | cloud_provider | region | endpoint_ip | status |
|--------|-----------:|----------------|--------|-------------|--------|
| `default_grpc` | 0 | AWS | us-east-1 | `3.237.255.73` | ok |
| `default_grpc` | 1 | AWS | us-east-1 | `3.237.255.73` | ok |
| `rest_https_edge` | 0 | AWS | us-east-2 | `52.14.204.126` | ok |
| `rest_https_edge` | 1 | AWS | us-east-2 | `52.14.204.126` | ok |
| `rest_plain_tcp` | 0 | AWS | us-east-1 | `44.214.1.122` | ok |
| `rest_plain_tcp` | 1 | AWS | us-east-1 | `44.214.1.122` | ok |
| `tuned_grpc_multiplexed` | 0 | AWS | us-east-1 | `3.237.255.73` | ok |
| `tuned_grpc_multiplexed` | 1 | AWS | us-east-1 | `3.237.255.73` | ok |

## Method / Background

This milestone builds on M6.1.3's published per-cohort attribution at `max_tokens=10/50`; see [m6_1_3-attribution-closure.md](m6_1_3-attribution-closure.md) for the baseline CIs and cohort omissions. The null-anchor validation section below pairs each cross-checkable M6.2 anchor measurement against that baseline (FR-012 / FR-013).

