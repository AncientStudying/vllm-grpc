# M6.2 — Token-Budget Characterization

- run_id: `2026-05-25T11:00:54Z-1e4c7c58`
- sweep_mode: `publish`
- modal_region: `eu-west-1`
- model: `Qwen/Qwen3-8B`
- base_seed: `42`
- iteration_order: `cohort_innermost_block`
- iteration_discipline_verified: `True`
- n_per_point: `40`
- validate_axis_subset: `None`
- wall_clock_start_utc: `2026-05-25T11:00:54Z`
- wall_clock_end_utc: `2026-05-26T00:42:37Z`
- total_sweep_hours: `13.695`
- chat_corpus_sha256: `4442302df439fdc1967e9fb48a88910cee5d0f712592e733d47bdbbc1e0374f1`
- embed_corpus_sha256: `19a3b43bc34017615d175ea914b362f9d26a39bd2742b27af7e42f2b97df38a0`
- sub_probe_ran: `True`
- preemption_events: `0`
- run_started_at: `2026-05-25T11:00:54Z`
- run_completed_at: `2026-05-26T00:42:37Z`

> **WARNING (null_anchor_drift)**: ≥ 2 of the 22 cross-checkable null-anchor cells drifted against the M6.1.3 baseline (FR-014 / SC-004). Operator decides publish vs rerun.
>
> **WARNING (trajectory_insufficient_snapshots)**: At least one cohort has fewer than 2 post-warmup anchor snapshots (C1 round-8 amendment, FR-031). The intra-sweep drift verdict for that cohort was suppressed. Soft diagnostic — informational only, validate-mode start+end trajectories naturally hit this fallback.

## Production latency budget

| cell | cohort | max_tokens | n | wall_p50_ms | wall_p95_ms | wall_p99_ms | prompt_source | regime | corpus_idx | status |
|------|--------|-----------:|---:|------------:|------------:|------------:|---------------|--------|-----------:|--------|
| `embed_c1` | `default_grpc` | 10 | 40 | 610.04 | 994.63 | 1063.94 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `default_grpc` | 50 | 40 | 1900.83 | 1989.65 | 1998.49 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `default_grpc` | 256 | 40 | 8908.16 | 9008.63 | 9012.10 | `corpus_sharegpt_embed` | `natural_eos` | 6 | ok |
| `embed_c1` | `default_grpc` | 512 | 40 | 17509.40 | 17609.27 | 17612.37 | `corpus_sharegpt_embed` | `natural_eos` | 9 | ok |
| `embed_c1` | `default_grpc` | 1024 | 40 | 35211.48 | 35415.78 | 35684.39 | `corpus_sharegpt_embed` | `natural_eos` | 12 | ok |
| `embed_c1` | `default_grpc` | 2048 | 40 | 70040.89 | 70645.02 | 70786.79 | `corpus_sharegpt_embed` | `natural_eos` | 15 | ok |
| `embed_c1` | `rest_https_edge` | 10 | 40 | 908.11 | 2997.13 | 4344.41 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `rest_https_edge` | 50 | 40 | 1889.10 | 1995.14 | 2544.25 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `rest_https_edge` | 256 | 40 | 9608.65 | 10741.32 | 18400.93 | `corpus_sharegpt_embed` | `natural_eos` | 7 | ok |
| `embed_c1` | `rest_https_edge` | 512 | 40 | 17508.19 | 17610.51 | 17983.32 | `corpus_sharegpt_embed` | `natural_eos` | 10 | ok |
| `embed_c1` | `rest_https_edge` | 1024 | 40 | 35556.07 | 36472.98 | 36525.90 | `corpus_sharegpt_embed` | `natural_eos` | 13 | ok |
| `embed_c1` | `rest_https_edge` | 2048 | 40 | 69650.42 | 70451.67 | 70532.07 | `corpus_sharegpt_embed` | `natural_eos` | 16 | ok |
| `embed_c1` | `rest_plain_tcp` | 10 | 40 | 709.47 | 783.62 | 1190.54 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `rest_plain_tcp` | 50 | 40 | 2132.00 | 2163.24 | 2595.19 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c1` | `rest_plain_tcp` | 256 | 40 | 9044.57 | 9154.88 | 9430.10 | `corpus_sharegpt_embed` | `natural_eos` | 8 | ok |
| `embed_c1` | `rest_plain_tcp` | 512 | 40 | 17744.51 | 17848.36 | 18170.81 | `corpus_sharegpt_embed` | `natural_eos` | 11 | ok |
| `embed_c1` | `rest_plain_tcp` | 1024 | 40 | 35121.93 | 39073.62 | 39102.09 | `corpus_sharegpt_embed` | `natural_eos` | 14 | ok |
| `embed_c1` | `rest_plain_tcp` | 2048 | 40 | 66200.30 | 68574.61 | 69673.59 | `corpus_sharegpt_embed` | `natural_eos` | 17 | ok |
| `embed_c4` | `default_grpc` | 10 | 40 | 1584.69 | 4968.24 | 5781.93 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `default_grpc` | 50 | 40 | 2160.80 | 2700.93 | 2800.17 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `default_grpc` | 256 | 40 | 9814.41 | 10645.16 | 10856.68 | `corpus_sharegpt_embed` | `natural_eos` | 26 | ok |
| `embed_c4` | `default_grpc` | 512 | 40 | 19384.67 | 19882.55 | 19971.56 | `corpus_sharegpt_embed` | `natural_eos` | 30 | ok |
| `embed_c4` | `default_grpc` | 1024 | 40 | 38948.16 | 42774.57 | 43812.43 | `corpus_sharegpt_embed` | `natural_eos` | 34 | ok |
| `embed_c4` | `default_grpc` | 2048 | 40 | 78207.01 | 80405.48 | 80944.70 | `corpus_sharegpt_embed` | `natural_eos` | 38 | ok |
| `embed_c4` | `rest_https_edge` | 10 | 40 | 623.31 | 1558.42 | 1566.59 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `rest_https_edge` | 50 | 40 | 2160.24 | 2948.70 | 2971.88 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `rest_https_edge` | 256 | 40 | 10803.94 | 12247.92 | 13325.63 | `corpus_sharegpt_embed` | `natural_eos` | 28 | ok |
| `embed_c4` | `rest_https_edge` | 512 | 40 | 20599.27 | 41911.19 | 51950.54 | `corpus_sharegpt_embed` | `natural_eos` | 32 | ok |
| `embed_c4` | `rest_https_edge` | 1024 | 40 | 38904.90 | 40007.09 | 40062.05 | `corpus_sharegpt_embed` | `natural_eos` | 36 | ok |
| `embed_c4` | `rest_https_edge` | 2048 | 40 | 78064.92 | 78758.62 | 78999.74 | `corpus_sharegpt_embed` | `natural_eos` | 40 | ok |
| `embed_c4` | `rest_plain_tcp` | 10 | 40 | 891.85 | 1652.64 | 1673.08 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `rest_plain_tcp` | 50 | 40 | 2271.50 | 2991.85 | 3002.72 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `rest_plain_tcp` | 256 | 40 | 9813.95 | 10071.90 | 10107.79 | `corpus_sharegpt_embed` | `natural_eos` | 29 | ok |
| `embed_c4` | `rest_plain_tcp` | 512 | 40 | 19798.14 | 25993.41 | 29453.94 | `corpus_sharegpt_embed` | `natural_eos` | 33 | ok |
| `embed_c4` | `rest_plain_tcp` | 1024 | 40 | 40414.59 | 55891.26 | 63192.47 | `corpus_sharegpt_embed` | `natural_eos` | 37 | ok |
| `embed_c4` | `rest_plain_tcp` | 2048 | 40 | 77906.14 | 78863.34 | 79686.18 | `corpus_sharegpt_embed` | `natural_eos` | 41 | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 10 | 40 | 743.42 | 1717.23 | 1762.04 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 50 | 40 | 2176.96 | 2670.31 | 2765.02 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 256 | 40 | 10141.40 | 11679.43 | 11798.81 | `corpus_sharegpt_embed` | `natural_eos` | 27 | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 512 | 40 | 19508.18 | 23124.75 | 23436.77 | `corpus_sharegpt_embed` | `natural_eos` | 31 | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 1024 | 40 | 38692.71 | 38910.93 | 39118.87 | `corpus_sharegpt_embed` | `natural_eos` | 35 | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 2048 | 40 | 77443.57 | 78803.22 | 79030.40 | `corpus_sharegpt_embed` | `natural_eos` | 39 | ok |
| `embed_c8` | `default_grpc` | 10 | 40 | 920.86 | 4869.42 | 5396.86 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `default_grpc` | 50 | 40 | 2164.42 | 2439.28 | 2467.75 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `default_grpc` | 256 | 40 | 9935.57 | 10850.95 | 10862.41 | `corpus_sharegpt_embed` | `natural_eos` | 50 | ok |
| `embed_c8` | `default_grpc` | 512 | 40 | 20439.77 | 24129.44 | 24396.76 | `corpus_sharegpt_embed` | `natural_eos` | 54 | ok |
| `embed_c8` | `default_grpc` | 1024 | 40 | 39743.02 | 40577.80 | 40686.51 | `corpus_sharegpt_embed` | `natural_eos` | 58 | ok |
| `embed_c8` | `default_grpc` | 2048 | 40 | 80754.15 | 80902.74 | 80926.42 | `corpus_sharegpt_embed` | `natural_eos` | 62 | ok |
| `embed_c8` | `rest_https_edge` | 10 | 40 | 700.56 | 1654.68 | 2190.58 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `rest_https_edge` | 50 | 40 | 2309.95 | 3031.27 | 3061.29 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `rest_https_edge` | 256 | 40 | 10176.42 | 11101.15 | 11125.95 | `corpus_sharegpt_embed` | `natural_eos` | 52 | ok |
| `embed_c8` | `rest_https_edge` | 512 | 40 | 19989.91 | 21012.81 | 21131.62 | `corpus_sharegpt_embed` | `natural_eos` | 56 | ok |
| `embed_c8` | `rest_https_edge` | 1024 | 40 | 40866.04 | 43508.83 | 44820.04 | `corpus_sharegpt_embed` | `natural_eos` | 60 | ok |
| `embed_c8` | `rest_https_edge` | 2048 | 40 | 79439.70 | 81730.75 | 82188.31 | `corpus_sharegpt_embed` | `natural_eos` | 64 | ok |
| `embed_c8` | `rest_plain_tcp` | 10 | 40 | 850.35 | 1639.48 | 1689.43 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `rest_plain_tcp` | 50 | 40 | 2404.14 | 3080.43 | 3166.44 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `rest_plain_tcp` | 256 | 40 | 10237.63 | 10870.82 | 10920.73 | `corpus_sharegpt_embed` | `natural_eos` | 53 | ok |
| `embed_c8` | `rest_plain_tcp` | 512 | 40 | 19833.85 | 20377.98 | 20454.49 | `corpus_sharegpt_embed` | `natural_eos` | 57 | ok |
| `embed_c8` | `rest_plain_tcp` | 1024 | 40 | 39752.91 | 40200.50 | 40219.29 | `corpus_sharegpt_embed` | `natural_eos` | 61 | ok |
| `embed_c8` | `rest_plain_tcp` | 2048 | 40 | 81126.28 | 81599.48 | 81696.39 | `corpus_sharegpt_embed` | `natural_eos` | 65 | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 10 | 40 | 966.13 | 1888.07 | 2020.46 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 50 | 40 | 2156.98 | 2576.79 | 2664.79 | `synthetic_random_tensor` | `natural_eos` | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 256 | 40 | 10392.22 | 10884.56 | 10996.15 | `corpus_sharegpt_embed` | `natural_eos` | 51 | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 512 | 40 | 19793.25 | 20726.09 | 20812.36 | `corpus_sharegpt_embed` | `natural_eos` | 55 | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 1024 | 40 | 40869.35 | 89677.33 | 111042.96 | `corpus_sharegpt_embed` | `natural_eos` | 59 | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 2048 | 40 | 75551.01 | 110199.93 | 111386.68 | `corpus_sharegpt_embed` | `natural_eos` | 63 | ok |
| `chat_stream_c1` | `default_grpc` | 10 | 40 | 611.94 | 622.07 | 625.09 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `default_grpc` | 50 | 40 | 1973.06 | 1982.56 | 1986.00 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `default_grpc` | 256 | 40 | 8862.08 | 8955.14 | 8969.49 | `corpus_sharegpt` | `natural_eos` | 72 | ok |
| `chat_stream_c1` | `default_grpc` | 512 | 40 | 17557.34 | 17673.74 | 17737.81 | `corpus_sharegpt` | `natural_eos` | 75 | ok |
| `chat_stream_c1` | `default_grpc` | 1024 | 40 | 34908.22 | 35026.30 | 35074.65 | `corpus_sharegpt` | `natural_eos` | 78 | ok |
| `chat_stream_c1` | `default_grpc` | 2048 | 40 | 22048.92 | 28566.19 | 29167.80 | `corpus_sharegpt` | `natural_eos` | 81 | ok |
| `chat_stream_c1` | `rest_https_edge` | 10 | 40 | 488.53 | 492.52 | 704.70 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `rest_https_edge` | 50 | 40 | 1837.19 | 1860.89 | 2067.58 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `rest_https_edge` | 256 | 40 | 8819.53 | 8846.46 | 9035.87 | `corpus_sharegpt` | `natural_eos` | 73 | ok |
| `chat_stream_c1` | `rest_https_edge` | 512 | 40 | 17481.30 | 17530.91 | 17743.31 | `corpus_sharegpt` | `natural_eos` | 76 | ok |
| `chat_stream_c1` | `rest_https_edge` | 1024 | 40 | 34869.51 | 34989.34 | 35202.71 | `corpus_sharegpt` | `natural_eos` | 79 | ok |
| `chat_stream_c1` | `rest_https_edge` | 2048 | 40 | 68749.99 | 68911.81 | 69084.07 | `corpus_sharegpt` | `natural_eos` | 82 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 10 | 40 | 614.57 | 622.27 | 773.61 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 50 | 40 | 1977.14 | 2004.70 | 2154.86 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 256 | 40 | 8877.06 | 8986.50 | 9081.08 | `corpus_sharegpt` | `natural_eos` | 74 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 512 | 40 | 17545.68 | 17673.33 | 17802.98 | `corpus_sharegpt` | `natural_eos` | 77 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 1024 | 40 | 34998.75 | 35129.00 | 35258.58 | `corpus_sharegpt` | `natural_eos` | 80 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 2048 | 40 | 69555.06 | 69764.01 | 69850.84 | `corpus_sharegpt` | `natural_eos` | 83 | ok |
| `chat_stream_c4` | `default_grpc` | 10 | 40 | 692.91 | 977.81 | 1014.13 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `default_grpc` | 50 | 40 | 2073.15 | 2145.46 | 2183.53 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `default_grpc` | 256 | 40 | 9700.73 | 9778.55 | 9793.77 | `corpus_sharegpt` | `natural_eos` | 92 | ok |
| `chat_stream_c4` | `default_grpc` | 512 | 40 | 19373.99 | 19437.07 | 19442.29 | `corpus_sharegpt` | `natural_eos` | 96 | ok |
| `chat_stream_c4` | `default_grpc` | 1024 | 40 | 33279.06 | 38621.06 | 38630.92 | `corpus_sharegpt` | `natural_eos` | 100 | ok |
| `chat_stream_c4` | `default_grpc` | 2048 | 40 | 77519.11 | 77624.23 | 77676.84 | `corpus_sharegpt` | `natural_eos` | 104 | ok |
| `chat_stream_c4` | `rest_https_edge` | 10 | 40 | 575.00 | 903.68 | 906.95 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `rest_https_edge` | 50 | 40 | 2042.88 | 2325.44 | 2345.23 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `rest_https_edge` | 256 | 40 | 9624.68 | 9988.17 | 9991.33 | `corpus_sharegpt` | `natural_eos` | 94 | ok |
| `chat_stream_c4` | `rest_https_edge` | 512 | 40 | 19242.30 | 19624.86 | 19626.62 | `corpus_sharegpt` | `natural_eos` | 98 | ok |
| `chat_stream_c4` | `rest_https_edge` | 1024 | 40 | 38527.84 | 38852.12 | 38852.86 | `corpus_sharegpt` | `natural_eos` | 102 | ok |
| `chat_stream_c4` | `rest_https_edge` | 2048 | 40 | 77880.99 | 78173.73 | 78173.78 | `corpus_sharegpt` | `natural_eos` | 106 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 10 | 40 | 676.48 | 904.09 | 937.55 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 50 | 40 | 2169.82 | 2325.09 | 2396.25 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 256 | 40 | 9716.47 | 9942.44 | 9963.25 | `corpus_sharegpt` | `natural_eos` | 95 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 512 | 40 | 19286.72 | 19596.98 | 19615.37 | `corpus_sharegpt` | `natural_eos` | 99 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 1024 | 40 | 38570.22 | 38733.03 | 38820.96 | `corpus_sharegpt` | `natural_eos` | 103 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 2048 | 40 | 78124.78 | 78301.99 | 78302.32 | `corpus_sharegpt` | `natural_eos` | 107 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 10 | 40 | 630.09 | 966.22 | 1076.47 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 50 | 40 | 2074.11 | 2150.30 | 2208.26 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 256 | 40 | 9687.63 | 9795.53 | 9800.19 | `corpus_sharegpt` | `natural_eos` | 93 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 512 | 40 | 19265.05 | 19442.94 | 19446.48 | `corpus_sharegpt` | `natural_eos` | 97 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 1024 | 40 | 38596.58 | 38667.77 | 38677.62 | `corpus_sharegpt` | `natural_eos` | 101 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 2048 | 40 | 10657.60 | 15630.11 | 18810.17 | `corpus_sharegpt` | `natural_eos` | 105 | ok |
| `chat_stream_c8` | `default_grpc` | 10 | 40 | 627.54 | 697.27 | 737.18 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `default_grpc` | 50 | 40 | 2125.50 | 2208.47 | 2220.22 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `default_grpc` | 256 | 40 | 9855.09 | 9906.66 | 9923.38 | `corpus_sharegpt` | `natural_eos` | 116 | ok |
| `chat_stream_c8` | `default_grpc` | 512 | 40 | 19594.24 | 19663.72 | 19696.95 | `corpus_sharegpt` | `natural_eos` | 120 | ok |
| `chat_stream_c8` | `default_grpc` | 1024 | 40 | 39402.33 | 39664.85 | 39681.33 | `corpus_sharegpt` | `natural_eos` | 124 | ok |
| `chat_stream_c8` | `default_grpc` | 2048 | 40 | 5102.74 | 8933.27 | 9451.89 | `corpus_sharegpt` | `natural_eos` | 128 | ok |
| `chat_stream_c8` | `rest_https_edge` | 10 | 40 | 583.12 | 949.90 | 950.18 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `rest_https_edge` | 50 | 40 | 2079.21 | 2400.47 | 2401.68 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `rest_https_edge` | 256 | 40 | 9803.20 | 10186.81 | 10188.13 | `corpus_sharegpt` | `natural_eos` | 118 | ok |
| `chat_stream_c8` | `rest_https_edge` | 512 | 40 | 19592.86 | 20084.96 | 20087.77 | `corpus_sharegpt` | `natural_eos` | 122 | ok |
| `chat_stream_c8` | `rest_https_edge` | 1024 | 40 | 39530.28 | 39878.92 | 39879.58 | `corpus_sharegpt` | `natural_eos` | 126 | ok |
| `chat_stream_c8` | `rest_https_edge` | 2048 | 40 | 80278.32 | 80744.49 | 80746.05 | `corpus_sharegpt` | `natural_eos` | 130 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 10 | 40 | 693.79 | 945.25 | 947.48 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 50 | 40 | 2200.50 | 2433.06 | 2447.13 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 256 | 40 | 9900.38 | 10183.77 | 10217.98 | `corpus_sharegpt` | `natural_eos` | 119 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 512 | 40 | 19619.63 | 19869.90 | 19888.36 | `corpus_sharegpt` | `natural_eos` | 123 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 1024 | 40 | 39696.49 | 40037.89 | 40087.36 | `corpus_sharegpt` | `natural_eos` | 127 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 2048 | 40 | 81240.23 | 81515.10 | 81555.52 | `corpus_sharegpt` | `natural_eos` | 131 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 10 | 40 | 600.09 | 708.36 | 724.71 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 50 | 40 | 2129.53 | 2224.24 | 2241.04 | `synthetic_seed_derived` | `natural_eos` | — | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 256 | 40 | 9866.21 | 9946.19 | 9983.16 | `corpus_sharegpt` | `natural_eos` | 117 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 512 | 40 | 19734.54 | 19808.57 | 19840.70 | `corpus_sharegpt` | `natural_eos` | 121 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 1024 | 40 | 39714.64 | 39784.66 | 39804.25 | `corpus_sharegpt` | `natural_eos` | 125 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 2048 | 40 | 80151.70 | 80247.15 | 80250.58 | `corpus_sharegpt` | `natural_eos` | 129 | ok |

## Prompt-driven early-EOS audit

The cells below terminated via natural EOS at fewer than `50%` of the `max_tokens` cap (threshold `EARLY_EOS_RATIO_THRESHOLD = 0.5`, minimum cap `EARLY_EOS_AUDIT_MIN_MAX_TOKENS = 256`). Each cell draws a single corpus prompt per block (see `m6_2_sweep.py:546` + `assign_symmetric_prompt`); adjacent cohort blocks for the same `(cell, max_tokens)` draw *different* prompts, so per-cohort `wall_p50_ms` at high `max_tokens` in `natural_eos` regime confounds protocol cost with prompt-content distribution. The flagged rows are not protocol pathologies — they are cells whose corpus prompt elicited a short response and stopped early.

For a clean cohort-axis protocol comparison at large `max_tokens` use either the §"TPOT curves" table (protocol-invariant per-token decode cost) or the §"KV-cache pressure" sub-probe (forced-cap via `ignore_eos=True`, prompt-content held constant).

| cell | cohort | max_tokens | corpus_idx | wall_p50_ms | tpot_ms | implied_output_tokens | implied/cap |
|------|--------|-----------:|-----------:|------------:|--------:|---------------------:|------------:|
| `chat_stream_c1` | `default_grpc` | 2048 | 81 | 22048.92 | 33.81 | 651 | 0.32 |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 2048 | 105 | 10657.60 | 36.99 | 286 | 0.14 |
| `chat_stream_c8` | `default_grpc` | 2048 | 128 | 5102.74 | 37.43 | 134 | 0.07 |

## TPOT curves

| cell | cohort | max_tokens | tpot_ms | status |
|------|--------|-----------:|--------:|--------|
| `chat_stream_c1` | `default_grpc` | 10 | 33.51 | ok |
| `chat_stream_c1` | `default_grpc` | 50 | 33.74 | ok |
| `chat_stream_c1` | `default_grpc` | 256 | 33.78 | ok |
| `chat_stream_c1` | `default_grpc` | 512 | 33.88 | ok |
| `chat_stream_c1` | `default_grpc` | 1024 | 33.87 | ok |
| `chat_stream_c1` | `default_grpc` | 2048 | 33.81 | ok |
| `chat_stream_c1` | `rest_https_edge` | 10 | 33.39 | ok |
| `chat_stream_c1` | `rest_https_edge` | 50 | 33.77 | ok |
| `chat_stream_c1` | `rest_https_edge` | 256 | 33.85 | ok |
| `chat_stream_c1` | `rest_https_edge` | 512 | 33.84 | ok |
| `chat_stream_c1` | `rest_https_edge` | 1024 | 33.90 | ok |
| `chat_stream_c1` | `rest_https_edge` | 2048 | 34.05 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 10 | 33.47 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 50 | 33.74 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 256 | 33.83 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 512 | 33.83 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 1024 | 33.95 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 2048 | 34.03 | ok |
| `chat_stream_c4` | `default_grpc` | 10 | 36.54 | ok |
| `chat_stream_c4` | `default_grpc` | 50 | 36.72 | ok |
| `chat_stream_c4` | `default_grpc` | 256 | 36.85 | ok |
| `chat_stream_c4` | `default_grpc` | 512 | 37.29 | ok |
| `chat_stream_c4` | `default_grpc` | 1024 | 37.24 | ok |
| `chat_stream_c4` | `default_grpc` | 2048 | 38.07 | ok |
| `chat_stream_c4` | `rest_https_edge` | 10 | 36.59 | ok |
| `chat_stream_c4` | `rest_https_edge` | 50 | 36.68 | ok |
| `chat_stream_c4` | `rest_https_edge` | 256 | 36.78 | ok |
| `chat_stream_c4` | `rest_https_edge` | 512 | 37.19 | ok |
| `chat_stream_c4` | `rest_https_edge` | 1024 | 37.41 | ok |
| `chat_stream_c4` | `rest_https_edge` | 2048 | 38.06 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 10 | 36.25 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 50 | 36.75 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 256 | 36.84 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 512 | 37.12 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 1024 | 37.31 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 2048 | 37.98 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 10 | 36.49 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 50 | 36.74 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 256 | 36.88 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 512 | 37.13 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 1024 | 37.41 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 2048 | 36.99 | ok |
| `chat_stream_c8` | `default_grpc` | 10 | 37.18 | ok |
| `chat_stream_c8` | `default_grpc` | 50 | 37.30 | ok |
| `chat_stream_c8` | `default_grpc` | 256 | 37.50 | ok |
| `chat_stream_c8` | `default_grpc` | 512 | 37.78 | ok |
| `chat_stream_c8` | `default_grpc` | 1024 | 38.29 | ok |
| `chat_stream_c8` | `default_grpc` | 2048 | 37.43 | ok |
| `chat_stream_c8` | `rest_https_edge` | 10 | 37.30 | ok |
| `chat_stream_c8` | `rest_https_edge` | 50 | 37.24 | ok |
| `chat_stream_c8` | `rest_https_edge` | 256 | 37.47 | ok |
| `chat_stream_c8` | `rest_https_edge` | 512 | 37.87 | ok |
| `chat_stream_c8` | `rest_https_edge` | 1024 | 38.36 | ok |
| `chat_stream_c8` | `rest_https_edge` | 2048 | 39.58 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 10 | 37.15 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 50 | 37.37 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 256 | 37.57 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 512 | 37.75 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 1024 | 38.47 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 2048 | 39.55 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 10 | 37.16 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 50 | 37.36 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 256 | 37.48 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 512 | 38.01 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 1024 | 38.52 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 2048 | 39.63 | ok |

## Engine-cost decomposition curves

| cell | cohort | max_tokens | seg_ab_ms | seg_queue_ms | seg_prefill_ms | seg_ingress_ms | seg_egress_ms | status |
|------|--------|-----------:|----------:|-------------:|---------------:|---------------:|--------------:|--------|
| `embed_c1` | `default_grpc` | 10 | 0.74 | 0.01 | 40.36 | — | — | ok |
| `embed_c1` | `default_grpc` | 50 | 0.64 | 0.01 | 38.96 | — | — | ok |
| `embed_c1` | `default_grpc` | 256 | 0.72 | 0.01 | 35.53 | — | — | ok |
| `embed_c1` | `default_grpc` | 512 | 0.58 | 0.01 | 38.93 | — | — | ok |
| `embed_c1` | `default_grpc` | 1024 | 0.71 | 0.02 | 40.08 | — | — | ok |
| `embed_c1` | `default_grpc` | 2048 | 0.63 | 0.01 | 39.41 | — | — | ok |
| `embed_c1` | `rest_https_edge` | 10 | 1.03 | 0.01 | 39.07 | — | — | ok |
| `embed_c1` | `rest_https_edge` | 50 | 1.00 | 0.01 | 38.94 | — | — | ok |
| `embed_c1` | `rest_https_edge` | 256 | 6.11 | 0.03 | 40.09 | — | — | ok |
| `embed_c1` | `rest_https_edge` | 512 | 0.78 | 0.01 | 39.27 | — | — | ok |
| `embed_c1` | `rest_https_edge` | 1024 | 4.16 | 0.01 | 40.05 | — | — | ok |
| `embed_c1` | `rest_https_edge` | 2048 | 0.86 | 0.01 | 39.60 | — | — | ok |
| `embed_c1` | `rest_plain_tcp` | 10 | 0.97 | 0.01 | 38.93 | — | — | ok |
| `embed_c1` | `rest_plain_tcp` | 50 | 0.99 | 0.01 | 38.97 | — | — | ok |
| `embed_c1` | `rest_plain_tcp` | 256 | 0.71 | 0.01 | 39.52 | — | — | ok |
| `embed_c1` | `rest_plain_tcp` | 512 | 1.10 | 0.01 | 39.30 | — | — | ok |
| `embed_c1` | `rest_plain_tcp` | 1024 | 0.83 | 0.01 | 39.58 | — | — | ok |
| `embed_c1` | `rest_plain_tcp` | 2048 | 3.81 | 0.01 | 39.90 | — | — | ok |
| `embed_c4` | `default_grpc` | 10 | 0.60 | 0.01 | 56.98 | — | — | ok |
| `embed_c4` | `default_grpc` | 50 | 0.57 | 0.01 | 71.76 | — | — | ok |
| `embed_c4` | `default_grpc` | 256 | 0.58 | 0.01 | 69.96 | — | — | ok |
| `embed_c4` | `default_grpc` | 512 | 0.57 | 0.01 | 77.18 | — | — | ok |
| `embed_c4` | `default_grpc` | 1024 | 0.69 | 0.01 | 74.13 | — | — | ok |
| `embed_c4` | `default_grpc` | 2048 | 0.60 | 0.01 | 72.80 | — | — | ok |
| `embed_c4` | `rest_https_edge` | 10 | 0.99 | 0.01 | 68.73 | — | — | ok |
| `embed_c4` | `rest_https_edge` | 50 | 0.97 | 0.01 | 70.10 | — | — | ok |
| `embed_c4` | `rest_https_edge` | 256 | 0.67 | 0.01 | 72.68 | — | — | ok |
| `embed_c4` | `rest_https_edge` | 512 | 2.90 | 0.01 | 73.18 | — | — | ok |
| `embed_c4` | `rest_https_edge` | 1024 | 1.67 | 0.01 | 75.31 | — | — | ok |
| `embed_c4` | `rest_https_edge` | 2048 | 0.79 | 0.01 | 76.79 | — | — | ok |
| `embed_c4` | `rest_plain_tcp` | 10 | 0.98 | 0.01 | 62.38 | — | — | ok |
| `embed_c4` | `rest_plain_tcp` | 50 | 0.95 | 0.01 | 67.50 | — | — | ok |
| `embed_c4` | `rest_plain_tcp` | 256 | 0.52 | 0.01 | 66.81 | — | — | ok |
| `embed_c4` | `rest_plain_tcp` | 512 | 1.11 | 0.01 | 72.21 | — | — | ok |
| `embed_c4` | `rest_plain_tcp` | 1024 | 4.32 | 0.01 | 75.20 | — | — | ok |
| `embed_c4` | `rest_plain_tcp` | 2048 | 0.91 | 0.01 | 70.07 | — | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 10 | 0.58 | 0.01 | 70.12 | — | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 50 | 0.57 | 0.01 | 72.02 | — | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 256 | 0.65 | 0.01 | 72.53 | — | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 512 | 0.62 | 0.01 | 74.53 | — | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 1024 | 0.58 | 0.01 | 75.07 | — | — | ok |
| `embed_c4` | `tuned_grpc_multiplexed` | 2048 | 0.65 | 0.01 | 73.87 | — | — | ok |
| `embed_c8` | `default_grpc` | 10 | 0.60 | 0.01 | 69.01 | — | — | ok |
| `embed_c8` | `default_grpc` | 50 | 0.56 | 0.01 | 73.78 | — | — | ok |
| `embed_c8` | `default_grpc` | 256 | 0.61 | 0.01 | 73.84 | — | — | ok |
| `embed_c8` | `default_grpc` | 512 | 1.26 | 0.01 | 77.03 | — | — | ok |
| `embed_c8` | `default_grpc` | 1024 | 0.59 | 0.01 | 74.87 | — | — | ok |
| `embed_c8` | `default_grpc` | 2048 | 0.58 | 0.01 | 74.69 | — | — | ok |
| `embed_c8` | `rest_https_edge` | 10 | 0.95 | 0.01 | 72.07 | — | — | ok |
| `embed_c8` | `rest_https_edge` | 50 | 1.06 | 0.01 | 72.17 | — | — | ok |
| `embed_c8` | `rest_https_edge` | 256 | 1.26 | 0.01 | 75.49 | — | — | ok |
| `embed_c8` | `rest_https_edge` | 512 | 1.54 | 0.01 | 74.81 | — | — | ok |
| `embed_c8` | `rest_https_edge` | 1024 | 2.11 | 0.01 | 75.65 | — | — | ok |
| `embed_c8` | `rest_https_edge` | 2048 | 1.94 | 0.01 | 79.92 | — | — | ok |
| `embed_c8` | `rest_plain_tcp` | 10 | 0.95 | 0.01 | 72.09 | — | — | ok |
| `embed_c8` | `rest_plain_tcp` | 50 | 0.91 | 0.01 | 72.39 | — | — | ok |
| `embed_c8` | `rest_plain_tcp` | 256 | 0.97 | 0.01 | 72.62 | — | — | ok |
| `embed_c8` | `rest_plain_tcp` | 512 | 0.75 | 0.01 | 71.29 | — | — | ok |
| `embed_c8` | `rest_plain_tcp` | 1024 | 0.62 | 0.01 | 76.02 | — | — | ok |
| `embed_c8` | `rest_plain_tcp` | 2048 | 0.84 | 0.01 | 79.97 | — | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 10 | 0.62 | 0.01 | 73.68 | — | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 50 | 0.56 | 0.01 | 73.98 | — | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 256 | 0.62 | 0.01 | 74.48 | — | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 512 | 0.65 | 0.01 | 75.08 | — | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 1024 | 1.16 | 0.01 | 70.79 | — | — | ok |
| `embed_c8` | `tuned_grpc_multiplexed` | 2048 | 1.00 | 0.01 | 80.85 | — | — | ok |
| `chat_stream_c1` | `default_grpc` | 10 | 0.27 | 0.01 | 39.66 | 0.05 | 1.09 | ok |
| `chat_stream_c1` | `default_grpc` | 50 | 0.27 | 0.01 | 39.43 | 0.05 | 1.04 | ok |
| `chat_stream_c1` | `default_grpc` | 256 | 0.27 | 0.01 | 39.48 | 0.05 | 1.05 | ok |
| `chat_stream_c1` | `default_grpc` | 512 | 0.28 | 0.01 | 39.79 | 0.05 | 1.13 | ok |
| `chat_stream_c1` | `default_grpc` | 1024 | 0.27 | 0.01 | 35.85 | 0.05 | 1.01 | ok |
| `chat_stream_c1` | `default_grpc` | 2048 | 0.27 | 0.01 | 39.53 | 0.05 | 0.96 | ok |
| `chat_stream_c1` | `rest_https_edge` | 10 | 0.05 | 0.01 | 39.73 | 0.05 | 2.05 | ok |
| `chat_stream_c1` | `rest_https_edge` | 50 | 0.06 | 0.01 | 39.70 | 0.05 | 1.28 | ok |
| `chat_stream_c1` | `rest_https_edge` | 256 | 0.05 | 0.01 | 39.75 | 0.05 | 1.46 | ok |
| `chat_stream_c1` | `rest_https_edge` | 512 | 0.07 | 0.01 | 39.55 | 0.05 | 1.45 | ok |
| `chat_stream_c1` | `rest_https_edge` | 1024 | 0.05 | 0.01 | 39.68 | 0.05 | 1.27 | ok |
| `chat_stream_c1` | `rest_https_edge` | 2048 | 0.05 | 0.01 | 35.75 | 0.05 | 1.17 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 10 | 0.06 | 0.01 | 39.69 | 0.05 | 1.19 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 50 | 0.05 | 0.01 | 39.64 | 0.05 | 1.16 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 256 | 0.05 | 0.01 | 39.70 | 0.05 | 1.19 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 512 | 0.06 | 0.01 | 39.59 | 0.05 | 1.21 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 1024 | 0.06 | 0.01 | 40.50 | 0.05 | 1.42 | ok |
| `chat_stream_c1` | `rest_plain_tcp` | 2048 | 0.05 | 0.01 | 39.64 | 0.05 | 1.17 | ok |
| `chat_stream_c4` | `default_grpc` | 10 | 0.23 | 0.01 | 69.67 | 0.04 | 1.32 | ok |
| `chat_stream_c4` | `default_grpc` | 50 | 0.21 | 0.01 | 65.26 | 0.04 | 1.02 | ok |
| `chat_stream_c4` | `default_grpc` | 256 | 0.21 | 0.01 | 66.79 | 0.04 | 0.98 | ok |
| `chat_stream_c4` | `default_grpc` | 512 | 0.23 | 0.01 | 70.22 | 0.04 | 1.19 | ok |
| `chat_stream_c4` | `default_grpc` | 1024 | 0.24 | 0.01 | 74.72 | 0.04 | 1.09 | ok |
| `chat_stream_c4` | `default_grpc` | 2048 | 0.23 | 0.01 | 74.13 | 0.04 | 1.18 | ok |
| `chat_stream_c4` | `rest_https_edge` | 10 | 0.04 | 0.01 | 68.89 | 0.03 | 1.49 | ok |
| `chat_stream_c4` | `rest_https_edge` | 50 | 0.04 | 0.01 | 73.22 | 0.03 | 1.22 | ok |
| `chat_stream_c4` | `rest_https_edge` | 256 | 0.05 | 0.01 | 69.76 | 0.03 | 3.09 | ok |
| `chat_stream_c4` | `rest_https_edge` | 512 | 0.07 | 0.01 | 70.51 | 0.04 | 2.11 | ok |
| `chat_stream_c4` | `rest_https_edge` | 1024 | 0.05 | 0.01 | 74.63 | 0.03 | 1.43 | ok |
| `chat_stream_c4` | `rest_https_edge` | 2048 | 0.04 | 0.01 | 63.32 | 0.03 | 1.41 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 10 | 0.04 | 0.01 | 67.88 | 0.04 | 1.75 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 50 | 0.04 | 0.01 | 70.67 | 0.04 | 1.30 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 256 | 0.04 | 0.01 | 70.25 | 0.04 | 1.15 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 512 | 0.05 | 0.01 | 69.00 | 0.04 | 1.64 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 1024 | 0.05 | 0.00 | 75.33 | 0.04 | 1.33 | ok |
| `chat_stream_c4` | `rest_plain_tcp` | 2048 | 0.05 | 0.01 | 85.35 | 0.05 | 1.66 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 10 | 0.22 | 0.01 | 66.53 | 0.04 | 1.13 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 50 | 0.21 | 0.01 | 66.02 | 0.03 | 1.00 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 256 | 0.22 | 0.01 | 67.88 | 0.04 | 1.05 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 512 | 0.22 | 0.01 | 66.06 | 0.04 | 1.09 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 1024 | 0.22 | 0.01 | 72.60 | 0.04 | 1.03 | ok |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 2048 | 0.25 | 0.01 | 74.35 | 0.04 | 1.56 | ok |
| `chat_stream_c8` | `default_grpc` | 10 | 0.70 | 0.01 | 73.61 | 0.03 | 1.31 | ok |
| `chat_stream_c8` | `default_grpc` | 50 | 0.20 | 0.01 | 72.33 | 0.03 | 1.35 | ok |
| `chat_stream_c8` | `default_grpc` | 256 | 0.19 | 0.01 | 72.18 | 0.03 | 1.29 | ok |
| `chat_stream_c8` | `default_grpc` | 512 | 0.19 | 0.01 | 70.20 | 0.03 | 1.29 | ok |
| `chat_stream_c8` | `default_grpc` | 1024 | 0.26 | 0.01 | 76.44 | 0.04 | 1.54 | ok |
| `chat_stream_c8` | `default_grpc` | 2048 | 0.23 | 0.01 | 75.37 | 0.04 | 1.51 | ok |
| `chat_stream_c8` | `rest_https_edge` | 10 | 0.04 | 0.01 | 72.95 | 0.03 | 2.02 | ok |
| `chat_stream_c8` | `rest_https_edge` | 50 | 0.04 | 0.01 | 74.26 | 0.03 | 1.71 | ok |
| `chat_stream_c8` | `rest_https_edge` | 256 | 0.04 | 0.01 | 71.14 | 0.03 | 1.63 | ok |
| `chat_stream_c8` | `rest_https_edge` | 512 | 0.04 | 0.01 | 70.51 | 0.03 | 1.78 | ok |
| `chat_stream_c8` | `rest_https_edge` | 1024 | 0.05 | 0.01 | 73.68 | 0.04 | 1.88 | ok |
| `chat_stream_c8` | `rest_https_edge` | 2048 | 0.05 | 0.01 | 82.15 | 0.04 | 2.34 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 10 | 0.04 | 0.01 | 74.06 | 0.03 | 1.80 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 50 | 0.04 | 0.01 | 75.16 | 0.03 | 1.57 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 256 | 0.04 | 0.01 | 73.00 | 0.04 | 1.78 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 512 | 0.04 | 0.01 | 74.61 | 0.03 | 1.68 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 1024 | 0.04 | 0.01 | 76.72 | 0.04 | 1.70 | ok |
| `chat_stream_c8` | `rest_plain_tcp` | 2048 | 0.05 | 0.01 | 76.20 | 0.04 | 1.84 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 10 | 0.18 | 0.01 | 71.81 | 0.03 | 1.31 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 50 | 0.19 | 0.01 | 88.41 | 0.03 | 1.30 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 256 | 0.20 | 0.01 | 71.22 | 0.03 | 1.64 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 512 | 0.19 | 0.01 | 74.40 | 0.03 | 1.50 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 1024 | 0.20 | 0.01 | 74.10 | 0.03 | 1.53 | ok |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 2048 | 0.20 | 0.01 | 76.48 | 0.03 | 1.39 | ok |

## Protocol crossover threshold

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
| `rest_https_edge` | `chat_stream` | 1.807 | `kv_pressure_not_observable` | — | False | 20 |
| `rest_plain_tcp` | `chat_stream` | 2.015 | `kv_pressure_not_observable` | — | False | 20 |
| `default_grpc` | `chat_stream` | 1.997 | `kv_pressure_not_observable` | — | False | 20 |
| `tuned_grpc_multiplexed` | `chat_stream` | 1.822 | `kv_pressure_not_observable` | — | False | 20 |
| `rest_https_edge` | `embed` | 2.041 | `kv_pressure_not_observable` | — | False | 20 |
| `rest_plain_tcp` | `embed` | 1.984 | `kv_pressure_not_observable` | — | False | 20 |
| `default_grpc` | `embed` | 2.050 | `kv_pressure_not_observable` | — | False | 20 |
| `tuned_grpc_multiplexed` | `embed` | 1.992 | `kv_pressure_not_observable` | — | False | 20 |

## Null anchor validation

Cross-checkable cells: 11 (≥ 2 drifted → fires FR-014 `null_anchor_drift` header; currently 2 drifted). New-baseline cells: 37 (excluded from the count by construction).

### Cross-checkable cells (drift verdict against M6.1.3 baseline)

| cell | cohort | max_tokens | m6_2_p50 | m6_1_3_p50 | drift_fraction | verdict |
|------|--------|-----------:|---------:|-----------:|---------------:|---------|
| `chat_stream_c1` | `default_grpc` | 50 | 1973.06 | 1957.91 | 0.310 | `PASS` |
| `chat_stream_c1` | `rest_https_edge` | 50 | 1837.19 | 1839.34 | -0.047 | `PASS` |
| `chat_stream_c1` | `rest_plain_tcp` | 50 | 1977.14 | 2258.18 | -4.978 | `FAIL` |
| `chat_stream_c4` | `default_grpc` | 50 | 2073.15 | 2093.98 | -0.398 | `PASS` |
| `chat_stream_c4` | `rest_https_edge` | 50 | 2042.88 | 2036.51 | 0.125 | `PASS` |
| `chat_stream_c4` | `rest_plain_tcp` | 50 | 2169.82 | 2870.10 | -9.760 | `FAIL` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 50 | 2074.11 | 2094.09 | -0.382 | `PASS` |
| `chat_stream_c8` | `default_grpc` | 50 | 2125.50 | 2133.63 | -0.152 | `PASS` |
| `chat_stream_c8` | `rest_https_edge` | 50 | 2079.21 | 2078.25 | 0.018 | `PASS` |
| `chat_stream_c8` | `rest_plain_tcp` | 50 | 2200.50 | 2157.84 | 0.791 | `PASS` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 50 | 2129.53 | 2130.20 | -0.013 | `PASS` |

### New-baseline cells (no M6.1.3 reference; recorded for posterity)

| cell | cohort | max_tokens | m6_2_p50 | marker |
|------|--------|-----------:|---------:|--------|
| `chat_stream_c1` | `default_grpc` | 10 | 611.94 | `new_baseline_marker` |
| `chat_stream_c1` | `rest_https_edge` | 10 | 488.53 | `new_baseline_marker` |
| `chat_stream_c1` | `rest_plain_tcp` | 10 | 614.57 | `new_baseline_marker` |
| `chat_stream_c1` | `tuned_grpc_multiplexed` | 10 | — | `new_baseline_marker` |
| `chat_stream_c1` | `tuned_grpc_multiplexed` | 50 | — | `new_baseline_marker` |
| `chat_stream_c4` | `default_grpc` | 10 | 692.91 | `new_baseline_marker` |
| `chat_stream_c4` | `rest_https_edge` | 10 | 575.00 | `new_baseline_marker` |
| `chat_stream_c4` | `rest_plain_tcp` | 10 | 676.48 | `new_baseline_marker` |
| `chat_stream_c4` | `tuned_grpc_multiplexed` | 10 | 630.09 | `new_baseline_marker` |
| `chat_stream_c8` | `default_grpc` | 10 | 627.54 | `new_baseline_marker` |
| `chat_stream_c8` | `rest_https_edge` | 10 | 583.12 | `new_baseline_marker` |
| `chat_stream_c8` | `rest_plain_tcp` | 10 | 693.79 | `new_baseline_marker` |
| `chat_stream_c8` | `tuned_grpc_multiplexed` | 10 | 600.09 | `new_baseline_marker` |
| `embed_c1` | `default_grpc` | 10 | 610.04 | `new_baseline_marker` |
| `embed_c1` | `default_grpc` | 50 | 1900.83 | `new_baseline_marker` |
| `embed_c1` | `rest_https_edge` | 10 | 908.11 | `new_baseline_marker` |
| `embed_c1` | `rest_https_edge` | 50 | 1889.10 | `new_baseline_marker` |
| `embed_c1` | `rest_plain_tcp` | 10 | 709.47 | `new_baseline_marker` |
| `embed_c1` | `rest_plain_tcp` | 50 | 2132.00 | `new_baseline_marker` |
| `embed_c1` | `tuned_grpc_multiplexed` | 10 | — | `new_baseline_marker` |
| `embed_c1` | `tuned_grpc_multiplexed` | 50 | — | `new_baseline_marker` |
| `embed_c4` | `default_grpc` | 10 | 1584.69 | `new_baseline_marker` |
| `embed_c4` | `default_grpc` | 50 | 2160.80 | `new_baseline_marker` |
| `embed_c4` | `rest_https_edge` | 10 | 623.31 | `new_baseline_marker` |
| `embed_c4` | `rest_https_edge` | 50 | 2160.24 | `new_baseline_marker` |
| `embed_c4` | `rest_plain_tcp` | 10 | 891.85 | `new_baseline_marker` |
| `embed_c4` | `rest_plain_tcp` | 50 | 2271.50 | `new_baseline_marker` |
| `embed_c4` | `tuned_grpc_multiplexed` | 10 | 743.42 | `new_baseline_marker` |
| `embed_c4` | `tuned_grpc_multiplexed` | 50 | 2176.96 | `new_baseline_marker` |
| `embed_c8` | `default_grpc` | 10 | 920.86 | `new_baseline_marker` |
| `embed_c8` | `default_grpc` | 50 | 2164.42 | `new_baseline_marker` |
| `embed_c8` | `rest_https_edge` | 10 | 700.56 | `new_baseline_marker` |
| `embed_c8` | `rest_https_edge` | 50 | 2309.95 | `new_baseline_marker` |
| `embed_c8` | `rest_plain_tcp` | 10 | 850.35 | `new_baseline_marker` |
| `embed_c8` | `rest_plain_tcp` | 50 | 2404.14 | `new_baseline_marker` |
| `embed_c8` | `tuned_grpc_multiplexed` | 10 | 966.13 | `new_baseline_marker` |
| `embed_c8` | `tuned_grpc_multiplexed` | 50 | 2156.98 | `new_baseline_marker` |

## Anchor latency trajectory

### `default_grpc`

- max_minus_min_wall_p50_ms: `0.000`; latency_drift_warning: `False`

| sweep_hour_mark | snapshot_timestamp | wall_p50_ms | wall_p95_ms | wall_p99_ms |
|----------------:|--------------------|------------:|------------:|------------:|
| 0.00 | `2026-05-25T11:05:25Z` | 613.37 | 630.96 | 649.39 |
| 8.01 | `2026-05-25T19:05:40Z` | 614.13 | 647.41 | 648.93 |

### `rest_https_edge`

- max_minus_min_wall_p50_ms: `0.000`; latency_drift_warning: `False`

| sweep_hour_mark | snapshot_timestamp | wall_p50_ms | wall_p95_ms | wall_p99_ms |
|----------------:|--------------------|------------:|------------:|------------:|
| 0.00 | `2026-05-25T11:05:00Z` | 483.08 | 520.89 | 1004.84 |
| 8.01 | `2026-05-25T19:05:15Z` | 488.40 | 511.97 | 773.04 |

### `rest_plain_tcp`

- max_minus_min_wall_p50_ms: `0.000`; latency_drift_warning: `False`

| sweep_hour_mark | snapshot_timestamp | wall_p50_ms | wall_p95_ms | wall_p99_ms |
|----------------:|--------------------|------------:|------------:|------------:|
| 0.00 | `2026-05-25T11:05:13Z` | 614.07 | 639.39 | 808.23 |
| 8.01 | `2026-05-25T19:05:27Z` | 614.09 | 632.56 | 820.25 |

### `tuned_grpc_multiplexed`

- max_minus_min_wall_p50_ms: `0.000`; latency_drift_warning: `False`

| sweep_hour_mark | snapshot_timestamp | wall_p50_ms | wall_p95_ms | wall_p99_ms |
|----------------:|--------------------|------------:|------------:|------------:|
| 0.00 | `2026-05-25T11:05:37Z` | 610.73 | 614.77 | 616.22 |
| 8.01 | `2026-05-25T19:05:52Z` | 611.53 | 617.77 | 622.37 |

## Failure summary

_No measurement-cell failures._

## Sweep wall-clock timeline

| cell | max_tokens | cohort | block_start_utc | duration_min | retry |
|------|-----------:|--------|-----------------|-------------:|-------|
| `chat_stream_c1` | 10 | `default_grpc` | `2026-05-25T18:08:29Z` | 0.42 | False |
| `chat_stream_c1` | 10 | `rest_https_edge` | `2026-05-25T18:08:54Z` | 0.33 | False |
| `chat_stream_c1` | 10 | `rest_plain_tcp` | `2026-05-25T18:09:14Z` | 0.40 | False |
| `chat_stream_c1` | 50 | `default_grpc` | `2026-05-25T18:09:38Z` | 1.32 | False |
| `chat_stream_c1` | 50 | `rest_https_edge` | `2026-05-25T18:10:57Z` | 1.23 | False |
| `chat_stream_c1` | 50 | `rest_plain_tcp` | `2026-05-25T18:12:11Z` | 1.33 | False |
| `chat_stream_c1` | 256 | `default_grpc` | `2026-05-25T18:13:31Z` | 5.92 | False |
| `chat_stream_c1` | 256 | `rest_https_edge` | `2026-05-25T18:19:26Z` | 5.88 | False |
| `chat_stream_c1` | 256 | `rest_plain_tcp` | `2026-05-25T18:25:19Z` | 5.93 | False |
| `chat_stream_c1` | 512 | `default_grpc` | `2026-05-25T18:31:15Z` | 10.47 | False |
| `chat_stream_c1` | 512 | `rest_https_edge` | `2026-05-25T18:41:43Z` | 11.65 | False |
| `chat_stream_c1` | 512 | `rest_plain_tcp` | `2026-05-25T18:53:22Z` | 11.72 | False |
| `chat_stream_c1` | 1024 | `default_grpc` | `2026-05-25T19:05:52Z` | 23.28 | False |
| `chat_stream_c1` | 1024 | `rest_https_edge` | `2026-05-25T19:29:09Z` | 22.85 | False |
| `chat_stream_c1` | 1024 | `rest_plain_tcp` | `2026-05-25T19:52:00Z` | 23.33 | False |
| `chat_stream_c1` | 2048 | `default_grpc` | `2026-05-25T20:15:20Z` | 14.72 | False |
| `chat_stream_c1` | 2048 | `rest_https_edge` | `2026-05-25T20:30:03Z` | 45.70 | False |
| `chat_stream_c1` | 2048 | `rest_plain_tcp` | `2026-05-25T21:15:45Z` | 41.40 | False |
| `chat_stream_c4` | 10 | `default_grpc` | `2026-05-25T21:57:09Z` | 0.13 | False |
| `chat_stream_c4` | 10 | `tuned_grpc_multiplexed` | `2026-05-25T21:57:17Z` | 0.12 | False |
| `chat_stream_c4` | 10 | `rest_https_edge` | `2026-05-25T21:57:24Z` | 0.10 | False |
| `chat_stream_c4` | 10 | `rest_plain_tcp` | `2026-05-25T21:57:30Z` | 0.12 | False |
| `chat_stream_c4` | 50 | `default_grpc` | `2026-05-25T21:57:37Z` | 0.35 | False |
| `chat_stream_c4` | 50 | `tuned_grpc_multiplexed` | `2026-05-25T21:57:58Z` | 0.35 | False |
| `chat_stream_c4` | 50 | `rest_https_edge` | `2026-05-25T21:58:19Z` | 0.33 | False |
| `chat_stream_c4` | 50 | `rest_plain_tcp` | `2026-05-25T21:58:39Z` | 0.37 | False |
| `chat_stream_c4` | 256 | `default_grpc` | `2026-05-25T21:59:01Z` | 1.62 | False |
| `chat_stream_c4` | 256 | `tuned_grpc_multiplexed` | `2026-05-25T22:00:38Z` | 1.63 | False |
| `chat_stream_c4` | 256 | `rest_https_edge` | `2026-05-25T22:02:16Z` | 1.60 | False |
| `chat_stream_c4` | 256 | `rest_plain_tcp` | `2026-05-25T22:03:52Z` | 1.63 | False |
| `chat_stream_c4` | 512 | `default_grpc` | `2026-05-25T22:05:30Z` | 3.23 | False |
| `chat_stream_c4` | 512 | `tuned_grpc_multiplexed` | `2026-05-25T22:08:44Z` | 3.22 | False |
| `chat_stream_c4` | 512 | `rest_https_edge` | `2026-05-25T22:11:57Z` | 3.22 | False |
| `chat_stream_c4` | 512 | `rest_plain_tcp` | `2026-05-25T22:15:10Z` | 3.22 | False |
| `chat_stream_c4` | 1024 | `default_grpc` | `2026-05-25T22:18:23Z` | 5.62 | False |
| `chat_stream_c4` | 1024 | `tuned_grpc_multiplexed` | `2026-05-25T22:24:00Z` | 6.43 | False |
| `chat_stream_c4` | 1024 | `rest_https_edge` | `2026-05-25T22:30:26Z` | 6.42 | False |
| `chat_stream_c4` | 1024 | `rest_plain_tcp` | `2026-05-25T22:36:51Z` | 5.30 | False |
| `chat_stream_c4` | 2048 | `default_grpc` | `2026-05-25T22:42:09Z` | 12.92 | False |
| `chat_stream_c4` | 2048 | `tuned_grpc_multiplexed` | `2026-05-25T22:55:04Z` | 1.88 | False |
| `chat_stream_c4` | 2048 | `rest_https_edge` | `2026-05-25T22:56:57Z` | 5.78 | False |
| `chat_stream_c4` | 2048 | `rest_plain_tcp` | `2026-05-25T23:45:21Z` | 12.63 | False |
| `chat_stream_c8` | 10 | `default_grpc` | `2026-05-25T23:57:59Z` | 0.07 | False |
| `chat_stream_c8` | 10 | `tuned_grpc_multiplexed` | `2026-05-25T23:58:03Z` | 0.05 | False |
| `chat_stream_c8` | 10 | `rest_https_edge` | `2026-05-25T23:58:06Z` | 0.07 | False |
| `chat_stream_c8` | 10 | `rest_plain_tcp` | `2026-05-25T23:58:10Z` | 0.05 | False |
| `chat_stream_c8` | 50 | `default_grpc` | `2026-05-25T23:58:13Z` | 0.18 | False |
| `chat_stream_c8` | 50 | `tuned_grpc_multiplexed` | `2026-05-25T23:58:24Z` | 0.18 | False |
| `chat_stream_c8` | 50 | `rest_https_edge` | `2026-05-25T23:58:35Z` | 0.18 | False |
| `chat_stream_c8` | 50 | `rest_plain_tcp` | `2026-05-25T23:58:46Z` | 0.18 | False |
| `chat_stream_c8` | 256 | `default_grpc` | `2026-05-25T23:58:57Z` | 0.83 | False |
| `chat_stream_c8` | 256 | `tuned_grpc_multiplexed` | `2026-05-25T23:59:47Z` | 0.82 | False |
| `chat_stream_c8` | 256 | `rest_https_edge` | `2026-05-26T00:00:36Z` | 0.83 | False |
| `chat_stream_c8` | 256 | `rest_plain_tcp` | `2026-05-26T00:01:26Z` | 0.83 | False |
| `chat_stream_c8` | 512 | `default_grpc` | `2026-05-26T00:02:16Z` | 1.63 | False |
| `chat_stream_c8` | 512 | `tuned_grpc_multiplexed` | `2026-05-26T00:03:54Z` | 1.65 | False |
| `chat_stream_c8` | 512 | `rest_https_edge` | `2026-05-26T00:05:33Z` | 1.63 | False |
| `chat_stream_c8` | 512 | `rest_plain_tcp` | `2026-05-26T00:07:11Z` | 1.65 | False |
| `chat_stream_c8` | 1024 | `default_grpc` | `2026-05-26T00:08:50Z` | 3.18 | False |
| `chat_stream_c8` | 1024 | `tuned_grpc_multiplexed` | `2026-05-26T00:12:01Z` | 3.32 | False |
| `chat_stream_c8` | 1024 | `rest_https_edge` | `2026-05-26T00:15:20Z` | 3.30 | False |
| `chat_stream_c8` | 1024 | `rest_plain_tcp` | `2026-05-26T00:18:38Z` | 3.32 | False |
| `chat_stream_c8` | 2048 | `default_grpc` | `2026-05-26T00:21:57Z` | 0.52 | False |
| `chat_stream_c8` | 2048 | `tuned_grpc_multiplexed` | `2026-05-26T00:22:28Z` | 6.68 | False |
| `chat_stream_c8` | 2048 | `rest_https_edge` | `2026-05-26T00:29:09Z` | 6.68 | False |
| `chat_stream_c8` | 2048 | `rest_plain_tcp` | `2026-05-26T00:35:50Z` | 6.78 | False |
| `embed_c1` | 10 | `default_grpc` | `2026-05-25T11:05:37Z` | 0.45 | False |
| `embed_c1` | 10 | `rest_https_edge` | `2026-05-25T11:06:04Z` | 0.87 | False |
| `embed_c1` | 10 | `rest_plain_tcp` | `2026-05-25T11:06:56Z` | 0.50 | False |
| `embed_c1` | 50 | `default_grpc` | `2026-05-25T11:07:26Z` | 1.27 | False |
| `embed_c1` | 50 | `rest_https_edge` | `2026-05-25T11:08:42Z` | 1.27 | False |
| `embed_c1` | 50 | `rest_plain_tcp` | `2026-05-25T11:09:58Z` | 1.40 | False |
| `embed_c1` | 256 | `default_grpc` | `2026-05-25T11:11:22Z` | 5.95 | False |
| `embed_c1` | 256 | `rest_https_edge` | `2026-05-25T11:17:19Z` | 6.85 | False |
| `embed_c1` | 256 | `rest_plain_tcp` | `2026-05-25T11:24:10Z` | 6.05 | False |
| `embed_c1` | 512 | `default_grpc` | `2026-05-25T11:30:13Z` | 11.67 | False |
| `embed_c1` | 512 | `rest_https_edge` | `2026-05-25T11:41:53Z` | 11.68 | False |
| `embed_c1` | 512 | `rest_plain_tcp` | `2026-05-25T11:53:34Z` | 11.85 | False |
| `embed_c1` | 1024 | `default_grpc` | `2026-05-25T12:05:25Z` | 23.37 | False |
| `embed_c1` | 1024 | `rest_https_edge` | `2026-05-25T12:28:47Z` | 23.67 | False |
| `embed_c1` | 1024 | `rest_plain_tcp` | `2026-05-25T12:52:27Z` | 23.78 | False |
| `embed_c1` | 2048 | `default_grpc` | `2026-05-25T13:16:14Z` | 44.60 | False |
| `embed_c1` | 2048 | `rest_https_edge` | `2026-05-25T14:00:50Z` | 45.82 | False |
| `embed_c1` | 2048 | `rest_plain_tcp` | `2026-05-25T14:46:39Z` | 43.30 | False |
| `embed_c4` | 10 | `default_grpc` | `2026-05-25T15:29:57Z` | 0.33 | False |
| `embed_c4` | 10 | `tuned_grpc_multiplexed` | `2026-05-25T15:30:17Z` | 0.13 | False |
| `embed_c4` | 10 | `rest_https_edge` | `2026-05-25T15:30:25Z` | 0.15 | False |
| `embed_c4` | 10 | `rest_plain_tcp` | `2026-05-25T15:30:34Z` | 0.17 | False |
| `embed_c4` | 50 | `default_grpc` | `2026-05-25T15:30:44Z` | 0.38 | False |
| `embed_c4` | 50 | `tuned_grpc_multiplexed` | `2026-05-25T15:31:07Z` | 0.38 | False |
| `embed_c4` | 50 | `rest_https_edge` | `2026-05-25T15:31:30Z` | 0.38 | False |
| `embed_c4` | 50 | `rest_plain_tcp` | `2026-05-25T15:31:53Z` | 0.42 | False |
| `embed_c4` | 256 | `default_grpc` | `2026-05-25T15:32:18Z` | 1.67 | False |
| `embed_c4` | 256 | `tuned_grpc_multiplexed` | `2026-05-25T15:33:58Z` | 1.78 | False |
| `embed_c4` | 256 | `rest_https_edge` | `2026-05-25T15:35:45Z` | 1.87 | False |
| `embed_c4` | 256 | `rest_plain_tcp` | `2026-05-25T15:37:37Z` | 1.63 | False |
| `embed_c4` | 512 | `default_grpc` | `2026-05-25T15:39:15Z` | 3.25 | False |
| `embed_c4` | 512 | `tuned_grpc_multiplexed` | `2026-05-25T15:42:30Z` | 3.37 | False |
| `embed_c4` | 512 | `rest_https_edge` | `2026-05-25T15:45:52Z` | 4.38 | False |
| `embed_c4` | 512 | `rest_plain_tcp` | `2026-05-25T15:50:15Z` | 3.57 | False |
| `embed_c4` | 1024 | `default_grpc` | `2026-05-25T15:53:49Z` | 6.62 | False |
| `embed_c4` | 1024 | `tuned_grpc_multiplexed` | `2026-05-25T16:00:26Z` | 6.40 | False |
| `embed_c4` | 1024 | `rest_https_edge` | `2026-05-25T16:06:50Z` | 6.55 | False |
| `embed_c4` | 1024 | `rest_plain_tcp` | `2026-05-25T16:13:23Z` | 7.25 | False |
| `embed_c4` | 2048 | `default_grpc` | `2026-05-25T16:20:38Z` | 13.12 | False |
| `embed_c4` | 2048 | `tuned_grpc_multiplexed` | `2026-05-25T16:33:45Z` | 12.93 | False |
| `embed_c4` | 2048 | `rest_https_edge` | `2026-05-25T16:46:41Z` | 13.07 | False |
| `embed_c4` | 2048 | `rest_plain_tcp` | `2026-05-25T16:59:45Z` | 13.10 | False |
| `embed_c8` | 10 | `default_grpc` | `2026-05-25T17:12:51Z` | 0.15 | False |
| `embed_c8` | 10 | `tuned_grpc_multiplexed` | `2026-05-25T17:13:00Z` | 0.10 | False |
| `embed_c8` | 10 | `rest_https_edge` | `2026-05-25T17:13:06Z` | 0.08 | False |
| `embed_c8` | 10 | `rest_plain_tcp` | `2026-05-25T17:13:11Z` | 0.08 | False |
| `embed_c8` | 50 | `default_grpc` | `2026-05-25T17:13:16Z` | 0.20 | False |
| `embed_c8` | 50 | `tuned_grpc_multiplexed` | `2026-05-25T17:13:28Z` | 0.18 | False |
| `embed_c8` | 50 | `rest_https_edge` | `2026-05-25T17:13:39Z` | 0.22 | False |
| `embed_c8` | 50 | `rest_plain_tcp` | `2026-05-25T17:13:52Z` | 0.23 | False |
| `embed_c8` | 256 | `default_grpc` | `2026-05-25T17:14:06Z` | 0.85 | False |
| `embed_c8` | 256 | `tuned_grpc_multiplexed` | `2026-05-25T17:14:57Z` | 0.87 | False |
| `embed_c8` | 256 | `rest_https_edge` | `2026-05-25T17:15:49Z` | 0.88 | False |
| `embed_c8` | 256 | `rest_plain_tcp` | `2026-05-25T17:16:42Z` | 0.87 | False |
| `embed_c8` | 512 | `default_grpc` | `2026-05-25T17:17:34Z` | 1.78 | False |
| `embed_c8` | 512 | `tuned_grpc_multiplexed` | `2026-05-25T17:19:21Z` | 1.67 | False |
| `embed_c8` | 512 | `rest_https_edge` | `2026-05-25T17:21:01Z` | 1.70 | False |
| `embed_c8` | 512 | `rest_plain_tcp` | `2026-05-25T17:22:43Z` | 1.67 | False |
| `embed_c8` | 1024 | `default_grpc` | `2026-05-25T17:24:23Z` | 3.32 | False |
| `embed_c8` | 1024 | `tuned_grpc_multiplexed` | `2026-05-25T17:27:42Z` | 6.87 | False |
| `embed_c8` | 1024 | `rest_https_edge` | `2026-05-25T17:34:34Z` | 3.52 | False |
| `embed_c8` | 1024 | `rest_plain_tcp` | `2026-05-25T17:38:05Z` | 3.33 | False |
| `embed_c8` | 2048 | `default_grpc` | `2026-05-25T17:41:25Z` | 6.72 | False |
| `embed_c8` | 2048 | `tuned_grpc_multiplexed` | `2026-05-25T17:48:08Z` | 6.92 | False |
| `embed_c8` | 2048 | `rest_https_edge` | `2026-05-25T17:55:03Z` | 6.68 | False |
| `embed_c8` | 2048 | `rest_plain_tcp` | `2026-05-25T18:01:44Z` | 6.75 | False |

## Network paths

| cohort | snapshot # | cloud_provider | region | endpoint_ip | status |
|--------|-----------:|----------------|--------|-------------|--------|
| `default_grpc` | 0 | AWS | eu-west-1 | `34.244.87.33` | ok |
| `default_grpc` | 1 | AWS | eu-west-1 | `34.244.87.33` | ok |
| `rest_https_edge` | 0 | unknown | — | `130.162.251.249` | ok |
| `rest_https_edge` | 1 | unknown | — | `130.162.251.249` | ok |
| `rest_plain_tcp` | 0 | AWS | eu-west-1 | `34.244.87.33` | ok |
| `rest_plain_tcp` | 1 | AWS | eu-west-1 | `34.244.87.33` | ok |
| `tuned_grpc_multiplexed` | 0 | AWS | eu-west-1 | `34.244.87.33` | ok |
| `tuned_grpc_multiplexed` | 1 | AWS | eu-west-1 | `34.244.87.33` | ok |

## Method / Background

This milestone builds on M6.1.3's published per-cohort attribution at `max_tokens=10/50`; see [m6_1_3-attribution-closure.md](m6_1_3-attribution-closure.md) for the baseline CIs and cohort omissions. The null-anchor validation section below pairs each cross-checkable M6.2 anchor measurement against that baseline (FR-012 / FR-013).

