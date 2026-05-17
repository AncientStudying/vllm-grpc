# M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation

**Run**: `r` | **Phase 2 path**: `phase_2_pending` ⏳
**Phase 1 classifications** (chat_stream cells): c1_h4096=instrumentation_artifact, c2_h4096=channel_dependent_batching, c3_h4096=inconclusive
**Phase 1 runs recorded**: 1

## Methodology

- **Model**: `Qwen/Qwen3-8B`, hidden_size=4096
- **Engine**: vllm==0.20.1 (M6.1 baseline recorded: 0.20.1)
- **Hardware**: A10G on Modal `eu-west-1`
- **Torch pin**: 2.11.0 (FR-003)
- **Phase 1 sample size**: n=50 per cohort per cell
- **Base seed**: 42 (matches M6 / M6.1)
- **Seq len pinned at sweep start**: 512
- **Perturbation budget**: 500 µs per RPC (FR-012 hard gate, exit code 4)

## Multi-Point Timing Table

### Run 1 — `r` (n=50)

| cell | cohort | engine_ttft_ms (±CI) | seg_ab_ms (±CI) | seg_bc_ms (±CI) | seg_cd_ms (±CI) | perturbation µs | n |
|------|--------|----------------------|------------------|------------------|------------------|------------------|---|

## Root-Cause Attribution

### chat_stream_c1_h4096: `instrumentation_artifact`

The pre-engine bracket (`seg_ab`) carries ≥80% of the `engine_ttft_ms` per-cohort spread. The per-cohort difference is measurement-window asymmetry between transport paths, not engine cost. Phase 2(a) symmetrisation will eliminate the asymmetry.

### chat_stream_c2_h4096: `channel_dependent_batching`

The engine-internal first-token segment (`seg_bc`) carries ≥80% of the spread. The engine itself sees different first-token latencies per cohort — this is a real engine behaviour under continuous batching. Phase 2(b) documents the interpretation rule.

### chat_stream_c3_h4096: `inconclusive`

Neither `seg_ab` nor `seg_bc` carries ≥80% of the `engine_ttft_ms` spread; the distribution is mixed. A second Phase 1 run is required to disambiguate.

## Phase 2 Outcome

Phase 2 not yet run. Under `instrumentation_artifact` apply symmetrisation and run `--m6_1_1`; under `channel_dependent_batching` update `contracts/instrumentation.md` and run `--m6_1_1`.

## Methodology Supersedence

(no supersedence annotation written for this run state)
