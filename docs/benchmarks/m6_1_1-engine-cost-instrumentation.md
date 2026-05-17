# M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation

**Run**: `2026-05-17T10:48:36Z-c4645c3` | **Phase 2 path**: `phase_2_pending` ⏳
**Phase 1 classifications** (chat_stream cells): c1_h4096=engine_compute_variation, c4_h4096=inconclusive, c8_h4096=inconclusive
**Phase 1 runs recorded**: 2

## Methodology

- **Model**: `Qwen/Qwen3-8B`, hidden_size=4096
- **Engine**: vllm==0.20.1 (M6.1 baseline recorded: 0.20.1)
- **Dispatch mode**: concurrent (peak in-flight = c, per M6.0a)
- **Hardware**: A10G on Modal `eu-west-1`
- **Torch pin**: 2.11.0 (FR-003)
- **Phase 1 sample size**: n=50 per cohort per cell
- **Base seed**: 42 (matches M6 / M6.1)
- **Seq len pinned at sweep start**: 512
- **Perturbation budget**: 500 µs per RPC (FR-012 hard gate, exit code 4)
- **Classifier**: 5-bucket FR-010 classifier (M6.1.1-expansion). Engine-internal `seg_queue` and `seg_prefill` derived from vLLM `RequestStateStats` (`queued_ts → scheduled_ts → first_token_ts`). Run 1 (`2026-05-17T01:54:46Z-f3ad158`) was classified by the pre-expansion 4-checkpoint scheme — retired in-branch in commit `541ca8e` because the degenerate `seg_bc ≡ engine_ttft` identity made `channel_dependent_batching` mechanically inevitable for any non-trivial chat_stream spread. Run 2 (`2026-05-17T10:48:36Z-c4645c3`) used the upgraded 5-bucket scheme: `drift_not_reproduced` (spread/mean < 5%) → `instrumentation_artifact` (seg_ab ≥ 80%) → `channel_dependent_batching` (seg_queue ≥ 80%) → `engine_compute_variation` (seg_prefill ≥ 80%) → `inconclusive`. Legacy data without engine-internal segments falls back to a 3-bucket scheme returning `inconclusive` rather than the retired rule.

## Multi-Point Timing Table

### Run 1 — `2026-05-17T01:54:46Z-f3ad158` (n=50)

| cell | cohort | engine_ttft_ms (±CI) | seg_ab_ms (±CI) | seg_queue_ms (±CI) | seg_prefill_ms (±CI) | seg_bc_ms (±CI) | seg_cd_ms (±CI) | perturbation µs | n |
|------|--------|----------------------|------------------|----------------------|----------------------|------------------|------------------|------------------|---|
| embed c=1 | rest_https_edge | 341.84 ± 0.14 | 1.04 ± 0.02 | n/a | n/a | 42.75 ± 0.08 | 299.09 ± 0.12 | 0.63 | 50 |
| embed c=1 | default_grpc | 342.13 ± 0.25 | 0.68 ± 0.01 | n/a | n/a | 42.04 ± 0.39 | 300.09 ± 0.41 | 0.70 | 50 |
| embed c=1 | tuned_grpc_multiplexed | 341.59 ± 0.21 | 0.68 ± 0.01 | n/a | n/a | 41.60 ± 0.13 | 299.99 ± 0.16 | 0.72 | 50 |
| embed c=4 | rest_https_edge | 411.45 ± 5.39 | 1.03 ± 0.04 | n/a | n/a | 84.55 ± 4.84 | 326.90 ± 1.39 | 0.66 | 50 |
| embed c=4 | default_grpc | 385.38 ± 9.79 | 0.69 ± 0.05 | n/a | n/a | 68.91 ± 6.91 | 316.47 ± 3.74 | 0.72 | 50 |
| embed c=4 | tuned_grpc_multiplexed | 399.85 ± 8.18 | 0.65 ± 0.02 | n/a | n/a | 79.71 ± 6.24 | 320.13 ± 3.01 | 0.69 | 50 |
| embed c=8 | rest_https_edge | 419.83 ± 6.04 | 0.95 ± 0.02 | n/a | n/a | 89.47 ± 5.21 | 330.36 ± 1.88 | 0.66 | 50 |
| embed c=8 | default_grpc | 405.74 ± 9.42 | 0.61 ± 0.04 | n/a | n/a | 80.79 ± 6.97 | 324.95 ± 3.30 | 0.67 | 50 |
| embed c=8 | tuned_grpc_multiplexed | 403.82 ± 8.18 | 0.55 ± 0.02 | n/a | n/a | 81.76 ± 5.98 | 322.06 ± 3.62 | 0.65 | 50 |
| chat_stream c=1 | rest_https_edge | 42.27 ± 1.38 | 0.05 ± 0.00 | n/a | n/a | 42.27 ± 1.38 | 1645.75 ± 1.77 | 0.61 | 50 |
| chat_stream c=1 | default_grpc | 47.14 ± 0.13 | 0.28 ± 0.00 | n/a | n/a | 47.14 ± 0.13 | 1655.13 ± 1.01 | 0.69 | 50 |
| chat_stream c=1 | tuned_grpc_multiplexed | 41.22 ± 0.20 | 0.28 ± 0.00 | n/a | n/a | 41.22 ± 0.20 | 1655.73 ± 0.99 | 0.60 | 50 |
| chat_stream c=4 | rest_https_edge | 87.01 ± 3.72 | 0.04 ± 0.00 | n/a | n/a | 87.01 ± 3.72 | 1800.40 ± 1.60 | 0.57 | 50 |
| chat_stream c=4 | default_grpc | 84.31 ± 5.71 | 0.22 ± 0.01 | n/a | n/a | 84.31 ± 5.71 | 1802.03 ± 2.39 | 0.59 | 50 |
| chat_stream c=4 | tuned_grpc_multiplexed | 74.01 ± 4.99 | 0.20 ± 0.01 | n/a | n/a | 74.01 ± 4.99 | 1802.71 ± 2.56 | 0.56 | 50 |
| chat_stream c=8 | rest_https_edge | 102.21 ± 3.80 | 0.04 ± 0.01 | n/a | n/a | 102.21 ± 3.80 | 1821.14 ± 2.32 | 0.56 | 50 |
| chat_stream c=8 | default_grpc | 90.90 ± 5.10 | 0.19 ± 0.01 | n/a | n/a | 90.90 ± 5.10 | 1821.31 ± 1.81 | 0.56 | 50 |
| chat_stream c=8 | tuned_grpc_multiplexed | 86.93 ± 4.33 | 0.19 ± 0.01 | n/a | n/a | 86.93 ± 4.33 | 1821.43 ± 2.13 | 0.55 | 50 |

### Run 2 — `2026-05-17T10:48:36Z-c4645c3` (n=50)

| cell | cohort | engine_ttft_ms (±CI) | seg_ab_ms (±CI) | seg_queue_ms (±CI) | seg_prefill_ms (±CI) | seg_bc_ms (±CI) | seg_cd_ms (±CI) | perturbation µs | n |
|------|--------|----------------------|------------------|----------------------|----------------------|------------------|------------------|------------------|---|
| embed c=1 | rest_https_edge | 340.86 ± 0.14 | 1.02 ± 0.02 | 0.01 ± 0.00 | 40.13 ± 0.07 | 42.15 ± 0.09 | 298.71 ± 0.11 | 0.71 | 50 |
| embed c=1 | default_grpc | 339.89 ± 0.18 | 0.66 ± 0.01 | 0.02 ± 0.00 | 38.70 ± 0.04 | 40.82 ± 0.08 | 299.07 ± 0.15 | 0.63 | 50 |
| embed c=1 | tuned_grpc_multiplexed | 339.72 ± 0.16 | 0.67 ± 0.00 | 0.02 ± 0.00 | 38.66 ± 0.04 | 40.72 ± 0.06 | 299.00 ± 0.12 | 0.62 | 50 |
| embed c=4 | rest_https_edge | 399.46 ± 7.89 | 0.97 ± 0.02 | 0.01 ± 0.00 | 63.73 ± 4.01 | 78.79 ± 6.10 | 320.67 ± 2.84 | 0.69 | 50 |
| embed c=4 | default_grpc | 416.90 ± 3.87 | 0.62 ± 0.02 | 0.01 ± 0.00 | 72.03 ± 1.47 | 89.30 ± 3.29 | 327.60 ± 1.51 | 0.62 | 50 |
| embed c=4 | tuned_grpc_multiplexed | 416.75 ± 5.17 | 0.63 ± 0.02 | 0.01 ± 0.00 | 70.11 ± 2.71 | 89.53 ± 4.76 | 327.22 ± 1.29 | 0.63 | 50 |
| embed c=8 | rest_https_edge | 426.25 ± 3.77 | 0.90 ± 0.02 | 0.01 ± 0.00 | 73.43 ± 1.60 | 94.74 ± 3.55 | 331.51 ± 1.17 | 0.66 | 50 |
| embed c=8 | default_grpc | 425.58 ± 3.42 | 0.55 ± 0.02 | 0.00 ± 0.00 | 73.49 ± 1.55 | 93.75 ± 3.32 | 331.83 ± 0.99 | 0.59 | 50 |
| embed c=8 | tuned_grpc_multiplexed | 426.10 ± 3.88 | 0.53 ± 0.02 | 0.00 ± 0.00 | 73.52 ± 1.68 | 94.11 ± 3.30 | 331.99 ± 1.18 | 0.61 | 50 |
| chat_stream c=1 | rest_https_edge | 42.14 ± 1.34 | 0.05 ± 0.00 | 0.01 ± 0.00 | 39.48 ± 0.10 | 42.14 ± 1.34 | 1649.57 ± 1.54 | 0.62 | 50 |
| chat_stream c=1 | default_grpc | 46.58 ± 0.10 | 0.26 ± 0.00 | 0.01 ± 0.00 | 44.67 ± 0.07 | 46.58 ± 0.10 | 1656.54 ± 0.99 | 0.59 | 50 |
| chat_stream c=1 | tuned_grpc_multiplexed | 40.81 ± 0.18 | 0.26 ± 0.00 | 0.01 ± 0.00 | 38.91 ± 0.16 | 40.82 ± 0.18 | 1658.76 ± 0.76 | 0.57 | 50 |
| chat_stream c=4 | rest_https_edge | 101.57 ± 4.70 | 0.05 ± 0.01 | 0.01 ± 0.00 | 74.05 ± 1.38 | 101.57 ± 4.70 | 1802.16 ± 1.65 | 0.60 | 50 |
| chat_stream c=4 | default_grpc | 75.05 ± 5.65 | 0.22 ± 0.01 | 0.01 ± 0.00 | 64.65 ± 3.72 | 75.05 ± 5.65 | 1810.15 ± 2.22 | 0.56 | 50 |
| chat_stream c=4 | tuned_grpc_multiplexed | 81.78 ± 4.97 | 0.21 ± 0.01 | 0.01 ± 0.00 | 67.71 ± 3.22 | 81.78 ± 4.97 | 1800.27 ± 2.64 | 0.56 | 50 |
| chat_stream c=8 | rest_https_edge | 97.65 ± 3.46 | 0.04 ± 0.01 | 0.01 ± 0.00 | 77.60 ± 1.54 | 97.66 ± 3.46 | 1827.34 ± 2.24 | 0.56 | 50 |
| chat_stream c=8 | default_grpc | 90.01 ± 5.36 | 0.20 ± 0.01 | 0.01 ± 0.00 | 70.32 ± 3.12 | 90.01 ± 5.36 | 1824.43 ± 2.21 | 0.55 | 50 |
| chat_stream c=8 | tuned_grpc_multiplexed | 84.32 ± 5.33 | 0.18 ± 0.01 | 0.01 ± 0.00 | 69.33 ± 2.88 | 84.32 ± 5.33 | 1828.98 ± 2.60 | 0.55 | 50 |

## Root-Cause Attribution

### chat_stream_c1_h4096: `engine_compute_variation`

The post-schedule engine-compute segment (`seg_prefill` = `first_token_ts - scheduled_ts`, from vLLM's RequestStateStats) carries ≥80% of the `engine_ttft_ms` per-cohort spread. The scheduler picked up requests promptly, but post-schedule compute took per-cohort variable time — likely a KV-cache-state or prompt-length artifact (not the canonical batching effect).

### chat_stream_c4_h4096: `inconclusive`

Neither `seg_ab` nor the engine-internal segments (`seg_queue`, `seg_prefill`) individually carry ≥80% of the `engine_ttft_ms` spread, OR the M6.1.2 engine-internal segments are absent (legacy data). Raw per-segment numbers in the table above are the authoritative read; manual interpretation required.

### chat_stream_c8_h4096: `inconclusive`

Neither `seg_ab` nor the engine-internal segments (`seg_queue`, `seg_prefill`) individually carry ≥80% of the `engine_ttft_ms` spread, OR the M6.1.2 engine-internal segments are absent (legacy data). Raw per-segment numbers in the table above are the authoritative read; manual interpretation required.

## Phase 2 Outcome

Phase 2 not yet run. Under `instrumentation_artifact` apply symmetrisation and run `--m6_1_1`; under `channel_dependent_batching` update `contracts/instrumentation.md` and run `--m6_1_1`.

## Methodology Supersedence

_N/A — this artifact does not supersede an earlier published verdict._
