# M6.1.1 — Audit Data, Sequential-Dispatch Baseline (2026-05-16)

> **⚠️ AUDIT DATA — NOT THE M6.1.1 PUBLISHED VERDICT.**
>
> This file captures the **second live Phase 1 run** of M6.1.1 (sweep completed 2026-05-16 23:57 UTC, 26.7 min on Modal A10G eu-west-1, commit `501ea28`). It is committed as audit-trail data so the post-fix definitive run (after M6.0a + classifier-degeneracy resolution) has a "before" comparison point.
>
> **Three open methodology issues affect this run's interpretation** (filed on PR #27):
>
> 1. **M6.0a — Concurrent Dispatch Restoration** ([PLAN.md](../PLAN.md#m60a--concurrent-dispatch-restoration-planned-blocks-m611-closure)). The M6 / M6.1 / M6.1.1 harness inherited M5.x's cell × cohort matrix but dropped `asyncio.gather`-based concurrent dispatch — the bench sends RPCs sequentially regardless of cell `concurrency`. Under sequential dispatch, vLLM's continuous batching never sees overlapping requests from different cohorts, so the `channel_dependent_batching` mechanism cannot manifest mechanistically.
>
> 2. **JSON tuple-key serialization bug** (fixed in `14a9a0c`). `PerturbationAudit.per_cohort_per_cell: dict[tuple[str, str], float]` crashed `json.dumps`; the markdown was written but the JSON companion never landed. This audit file is the *only* artifact from this run. Future runs (post-fix) produce both.
>
> 3. **FR-010 classifier degeneracy for chat_stream cells** ([PR #27 comment](https://github.com/AncientStudying/vllm-grpc/pull/27#issuecomment-4468600646)). `seg_bc_ms ≡ engine_ttft_ms` by construction (both measure `first_chunk_ns − pre_engine_ns`). The classifier's `spread(seg_bc) / spread(engine_ttft) ≥ 0.80` therefore *always fires* `channel_dependent_batching` on chat_stream cells with any non-trivial spread. The uniform `channel_dependent_batching × 3` classification below is **mechanically inevitable** under the current checkpoint placement — it does not constitute affirmative evidence of channel-dependent batching.
>
> **What this data IS useful for**:
> - Sequential-dispatch baseline: comparison target for the post-M6.0a concurrent-dispatch re-run.
> - Per-cohort `engine_ttft_ms` spread evidence: c=1 = 19.5%, c=4 = 6.0%, c=8 = 8.4% — reproduces M6.1's published 14-17% drift on the c=1 cell, marginal on c=4, moderate on c=8.
> - Embed cell cohort uniformity: <1.3% spread across all 3 embed cells — confirms the drift is chat_stream-specific.
> - Per-segment table forensic data: even though the classifier output is mechanical, the raw seg_ab / seg_bc / seg_cd numbers are real and can be re-interpreted under corrected mechanisms.
>
> **What this data is NOT**: the M6.1.1 published verdict. Do not treat the `channel_dependent_batching` classification below as actionable for Phase 2(b).

---

# M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation

**Run**: `2026-05-16T23:30:54Z-501ea28` | **Phase 2 path**: `phase_2_pending` ⏳
**Phase 1 classifications** (chat_stream cells): c1_h4096=channel_dependent_batching, c4_h4096=channel_dependent_batching, c8_h4096=channel_dependent_batching
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

### Run 1 — `2026-05-16T23:30:54Z-501ea28` (n=50)

| cell | cohort | engine_ttft_ms (±CI) | seg_ab_ms (±CI) | seg_bc_ms (±CI) | seg_cd_ms (±CI) | perturbation µs | n |
|------|--------|----------------------|------------------|------------------|------------------|------------------|---|
| embed c=1 | rest_https_edge | 358.58 ± 0.30 | 1.20 ± 0.02 | 47.16 ± 0.20 | 311.42 ± 0.22 | 0.81 | 50 |
| embed c=1 | default_grpc | 356.35 ± 0.36 | 0.88 ± 0.03 | 44.59 ± 0.20 | 311.77 ± 0.26 | 0.72 | 50 |
| embed c=1 | tuned_grpc_multiplexed | 357.94 ± 1.13 | 0.85 ± 0.02 | 45.67 ± 1.28 | 312.27 ± 0.70 | 0.72 | 50 |
| embed c=4 | rest_https_edge | 357.82 ± 1.53 | 1.27 ± 0.07 | 45.46 ± 1.44 | 312.36 ± 1.06 | 0.81 | 50 |
| embed c=4 | default_grpc | 356.08 ± 0.29 | 0.86 ± 0.02 | 44.49 ± 0.15 | 311.60 ± 0.25 | 0.74 | 50 |
| embed c=4 | tuned_grpc_multiplexed | 356.69 ± 0.45 | 0.87 ± 0.02 | 44.75 ± 0.29 | 311.94 ± 0.30 | 0.74 | 50 |
| embed c=8 | rest_https_edge | 361.23 ± 1.58 | 1.42 ± 0.20 | 46.58 ± 0.96 | 314.65 ± 0.88 | 0.77 | 50 |
| embed c=8 | default_grpc | 365.71 ± 1.86 | 1.15 ± 0.17 | 49.01 ± 1.52 | 316.70 ± 1.19 | 0.63 | 50 |
| embed c=8 | tuned_grpc_multiplexed | 364.69 ± 1.18 | 1.09 ± 0.12 | 48.96 ± 1.03 | 315.74 ± 1.17 | 0.63 | 50 |
| chat_stream c=1 | rest_https_edge | 53.34 ± 2.02 | 0.15 ± 0.05 | 53.34 ± 2.02 | 1735.81 ± 3.63 | 0.77 | 50 |
| chat_stream c=1 | default_grpc | 57.28 ± 1.26 | 0.64 ± 0.14 | 57.28 ± 1.26 | 1739.99 ± 2.54 | 0.61 | 50 |
| chat_stream c=1 | tuned_grpc_multiplexed | 47.05 ± 0.85 | 0.49 ± 0.09 | 47.05 ± 0.85 | 1725.87 ± 3.14 | 0.61 | 50 |
| chat_stream c=4 | rest_https_edge | 47.87 ± 1.45 | 0.10 ± 0.03 | 47.87 ± 1.45 | 1714.78 ± 2.02 | 0.73 | 50 |
| chat_stream c=4 | default_grpc | 45.10 ± 0.40 | 0.38 ± 0.02 | 45.10 ± 0.40 | 1716.33 ± 1.74 | 0.57 | 50 |
| chat_stream c=4 | tuned_grpc_multiplexed | 46.10 ± 0.54 | 0.39 ± 0.03 | 46.10 ± 0.54 | 1719.07 ± 1.37 | 0.56 | 50 |
| chat_stream c=8 | rest_https_edge | 57.50 ± 2.05 | 0.32 ± 0.15 | 57.50 ± 2.05 | 1746.86 ± 3.18 | 0.70 | 50 |
| chat_stream c=8 | default_grpc | 53.71 ± 1.71 | 0.74 ± 0.23 | 53.72 ± 1.71 | 1751.13 ± 2.67 | 0.63 | 50 |
| chat_stream c=8 | tuned_grpc_multiplexed | 52.92 ± 1.28 | 0.73 ± 0.16 | 52.92 ± 1.28 | 1749.83 ± 2.76 | 0.63 | 50 |

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
