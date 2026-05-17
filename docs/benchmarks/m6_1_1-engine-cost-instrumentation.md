# M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation

**Run**: `2026-05-17T01:54:46Z-f3ad158` | **Phase 2 path**: `phase_2_pending` ⏳
**Phase 1 classifications** (chat_stream cells): c1_h4096=channel_dependent_batching, c4_h4096=channel_dependent_batching, c8_h4096=channel_dependent_batching
**Phase 1 runs recorded**: 1

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

## Multi-Point Timing Table

### Run 1 — `2026-05-17T01:54:46Z-f3ad158` (n=50)

| cell | cohort | engine_ttft_ms (±CI) | seg_ab_ms (±CI) | seg_bc_ms (±CI) | seg_cd_ms (±CI) | perturbation µs | n |
|------|--------|----------------------|------------------|------------------|------------------|------------------|---|
| embed c=1 | rest_https_edge | 341.84 ± 0.14 | 1.04 ± 0.02 | 42.75 ± 0.08 | 299.09 ± 0.12 | 0.63 | 50 |
| embed c=1 | default_grpc | 342.13 ± 0.25 | 0.68 ± 0.01 | 42.04 ± 0.39 | 300.09 ± 0.41 | 0.70 | 50 |
| embed c=1 | tuned_grpc_multiplexed | 341.59 ± 0.21 | 0.68 ± 0.01 | 41.60 ± 0.13 | 299.99 ± 0.16 | 0.72 | 50 |
| embed c=4 | rest_https_edge | 411.45 ± 5.39 | 1.03 ± 0.04 | 84.55 ± 4.84 | 326.90 ± 1.39 | 0.66 | 50 |
| embed c=4 | default_grpc | 385.38 ± 9.79 | 0.69 ± 0.05 | 68.91 ± 6.91 | 316.47 ± 3.74 | 0.72 | 50 |
| embed c=4 | tuned_grpc_multiplexed | 399.85 ± 8.18 | 0.65 ± 0.02 | 79.71 ± 6.24 | 320.13 ± 3.01 | 0.69 | 50 |
| embed c=8 | rest_https_edge | 419.83 ± 6.04 | 0.95 ± 0.02 | 89.47 ± 5.21 | 330.36 ± 1.88 | 0.66 | 50 |
| embed c=8 | default_grpc | 405.74 ± 9.42 | 0.61 ± 0.04 | 80.79 ± 6.97 | 324.95 ± 3.30 | 0.67 | 50 |
| embed c=8 | tuned_grpc_multiplexed | 403.82 ± 8.18 | 0.55 ± 0.02 | 81.76 ± 5.98 | 322.06 ± 3.62 | 0.65 | 50 |
| chat_stream c=1 | rest_https_edge | 42.27 ± 1.38 | 0.05 ± 0.00 | 42.27 ± 1.38 | 1645.75 ± 1.77 | 0.61 | 50 |
| chat_stream c=1 | default_grpc | 47.14 ± 0.13 | 0.28 ± 0.00 | 47.14 ± 0.13 | 1655.13 ± 1.01 | 0.69 | 50 |
| chat_stream c=1 | tuned_grpc_multiplexed | 41.22 ± 0.20 | 0.28 ± 0.00 | 41.22 ± 0.20 | 1655.73 ± 0.99 | 0.60 | 50 |
| chat_stream c=4 | rest_https_edge | 87.01 ± 3.72 | 0.04 ± 0.00 | 87.01 ± 3.72 | 1800.40 ± 1.60 | 0.57 | 50 |
| chat_stream c=4 | default_grpc | 84.31 ± 5.71 | 0.22 ± 0.01 | 84.31 ± 5.71 | 1802.03 ± 2.39 | 0.59 | 50 |
| chat_stream c=4 | tuned_grpc_multiplexed | 74.01 ± 4.99 | 0.20 ± 0.01 | 74.01 ± 4.99 | 1802.71 ± 2.56 | 0.56 | 50 |
| chat_stream c=8 | rest_https_edge | 102.21 ± 3.80 | 0.04 ± 0.01 | 102.21 ± 3.80 | 1821.14 ± 2.32 | 0.56 | 50 |
| chat_stream c=8 | default_grpc | 90.90 ± 5.10 | 0.19 ± 0.01 | 90.90 ± 5.10 | 1821.31 ± 1.81 | 0.56 | 50 |
| chat_stream c=8 | tuned_grpc_multiplexed | 86.93 ± 4.33 | 0.19 ± 0.01 | 86.93 ± 4.33 | 1821.43 ± 2.13 | 0.55 | 50 |

## Root-Cause Attribution

### chat_stream_c1_h4096: `channel_dependent_batching`

The engine-internal first-token segment (`seg_bc`) carries ≥80% of the spread. The engine itself sees different first-token latencies per cohort — this is a real engine behaviour under continuous batching. Phase 2(b) documents the interpretation rule.

### chat_stream_c4_h4096: `channel_dependent_batching`

The engine-internal first-token segment (`seg_bc`) carries ≥80% of the spread. The engine itself sees different first-token latencies per cohort — this is a real engine behaviour under continuous batching. Phase 2(b) documents the interpretation rule.

### chat_stream_c8_h4096: `channel_dependent_batching`

The engine-internal first-token segment (`seg_bc`) carries ≥80% of the spread. The engine itself sees different first-token latencies per cohort — this is a real engine behaviour under continuous batching. Phase 2(b) documents the interpretation rule.

## Phase 2 Outcome

Phase 2 not yet run. Under `instrumentation_artifact` apply symmetrisation and run `--m6_1_1`; under `channel_dependent_batching` update `contracts/instrumentation.md` and run `--m6_1_1`.

## Methodology Supersedence

(no supersedence annotation written for this run state)
