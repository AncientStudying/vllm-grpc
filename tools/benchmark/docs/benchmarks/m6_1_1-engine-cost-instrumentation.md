# M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation

**Run**: `r` | **Phase 2 path**: `phase_2_pending` ⏳
**Phase 1 classifications** (chat_stream cells): c1_h4096=instrumentation_artifact, c2_h4096=channel_dependent_batching, c3_h4096=inconclusive
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
- **Classifier**: 5-bucket FR-010 classifier (M6.1.1-expansion). Engine-internal `seg_queue` and `seg_prefill` derived from vLLM `RequestStateStats` (`queued_ts → scheduled_ts → first_token_ts`). Decision tree: `drift_not_reproduced` (spread/mean < 5%) → `instrumentation_artifact` (seg_ab ≥ 80%) → `channel_dependent_batching` (seg_queue ≥ 80%) → `engine_compute_variation` (seg_prefill ≥ 80%) → `inconclusive`. Legacy data without engine-internal segments falls back to a 3-bucket scheme returning `inconclusive` rather than resurrecting the retired degenerate `seg_bc` rule.

## Multi-Point Timing Table

### Run 1 — `r` (n=50)

| cell | cohort | engine_ttft_ms (±CI) | seg_ab_ms (±CI) | seg_queue_ms (±CI) | seg_prefill_ms (±CI) | seg_bc_ms (±CI) | seg_cd_ms (±CI) | perturbation µs | n |
|------|--------|----------------------|------------------|----------------------|----------------------|------------------|------------------|------------------|---|

## Root-Cause Attribution

### chat_stream_c1_h4096: `instrumentation_artifact`

The pre-engine bracket (`seg_ab`, handler-internal pre-engine work) carries ≥80% of the `engine_ttft_ms` per-cohort spread. The per-cohort difference is measurement-window asymmetry inside the servicer, not engine cost. Phase 2(a) symmetrisation will eliminate the asymmetry.

### chat_stream_c2_h4096: `channel_dependent_batching`

The engine queue-wait segment (`seg_queue` = `scheduled_ts - queued_ts`, from vLLM's RequestStateStats) carries ≥80% of the `engine_ttft_ms` per-cohort spread. The engine's scheduler dispatches requests from different cohorts at different relative times — the canonical continuous-batching effect. Phase 2(b) documents the interpretation rule.

### chat_stream_c3_h4096: `inconclusive`

Neither `seg_ab` nor the engine-internal segments (`seg_queue`, `seg_prefill`) individually carry ≥80% of the `engine_ttft_ms` spread, OR the M6.1.2 engine-internal segments are absent (legacy data). Raw per-segment numbers in the table above are the authoritative read; manual interpretation required.

## Phase 2 Outcome

Phase 2 not yet run. Under `instrumentation_artifact` apply symmetrisation and run `--m6_1_1`; under `channel_dependent_batching` update `contracts/instrumentation.md` and run `--m6_1_1`.

## Methodology Supersedence

_N/A — this artifact does not supersede an earlier published verdict._
