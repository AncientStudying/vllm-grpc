# Spike #5 — `engine_compute_variation` root-cause (M6.1.3 scoping note)

**Branch**: `spike/m6-1-roadmap-additions`
**Date**: 2026-05-17
**Status**: ✅ Read-only investigation complete. Implementation deferred to **M6.1.3**.

## Recap of the finding

M6.1.1's Phase 1 re-run classified `chat_stream c=1 h=4096` as
`engine_compute_variation`: `seg_prefill` (post-schedule engine compute,
from vLLM's `RequestStateStats.first_token_ts − scheduled_ts`) carries
99.8% of the per-cohort `engine_ttft_ms` spread.

Per-cohort numbers from the published artifact
(`docs/benchmarks/m6_1_1-engine-cost-instrumentation.md`, Run 2):

| Cohort | `engine_ttft_ms` | `seg_prefill_ms` | `seg_queue_ms` | `seg_ab_ms` |
|---|---:|---:|---:|---:|
| rest_https_edge | 42.14 ± 1.34 | 39.48 ± 0.10 | 0.01 | 0.05 |
| default_grpc | **46.58 ± 0.10** ← outlier | **44.67 ± 0.07** | 0.01 | 0.26 |
| tuned_grpc_multiplexed | 40.81 ± 0.18 | 38.91 ± 0.16 | 0.01 | 0.26 |
| **spread (max − min)** | **5.77 ms** | **5.76 ms (99.8%)** | ~0 | 0.21 |

The data has structure beyond "random per-cohort variation":

- `default_grpc` is **the** outlier (~+5–6 ms over the other two).
- `rest_https_edge` and `tuned_grpc_multiplexed` are within ~1.3 ms of
  each other — well within the c=1 CI half-widths.
- The clustering is **not** REST-vs-gRPC (rest pairs with tuned, not
  with default).
- The clustering is **not** Azure-vs-AWS (rest = Azure, default + tuned
  = AWS; default and tuned diverge by 5.77 ms despite same CSP route).
- `seg_queue ≈ 0` rules out scheduler-side variation (single in-flight
  request at c=1).

So we have a c=1 finding where a single gRPC cohort spends ~5 ms more in
post-schedule engine compute than its sibling cohorts, with no obvious
network / batching explanation. **What's in `seg_prefill` that varies
per-cohort?**

## Hypothesis space (six candidates)

| # | Hypothesis | Predicts | Cheapest test |
|---|---|---|---|
| H1 | **Prompt content drift** — cohorts cycle through different prompts (different token counts or attention shapes) → different prefill compute | spread tracks per-cohort mean token count | Token-count audit (log per-RPC) |
| H2 | **Prompt encoding drift** — same text prompt, but `messages_to_prompt` / `apply_chat_template` produces different token streams per cohort | spread tracks tokenized-prompt hash divergence | Hash audit + compare per cohort |
| H3 | **KV-cache prefix reuse drift** — vLLM's prefix-cache hits favor cohorts whose prompts overlap with prior requests | spread shrinks when prefix-caching is disabled | Toggle `--enable-prefix-caching=False` |
| H4 | **Cohort-order / warmup bias** — deterministic cohort iteration leaves the second/third cohort with a warmer engine (Python JIT, allocator pools, etc.) | slowness moves with the position, not the cohort identity | Reverse cohort iteration order |
| H5 | **Channel-config side effect** — the tuned channel's options change how requests arrive at the engine (e.g., different max-message-size triggers a different code path) | spread persists across all experiments above | Process-of-elimination (least likely; engine compute shouldn't see channel config) |
| H6 | **HTTPS-Edge cold-path bias on rest** — Azure entry path adds variable arrival jitter that affects KV-cache placement timing | rest cohort is the outlier | Already disproven — default_grpc is the outlier, not rest |

H6 is eliminated by the existing data. H1 / H2 / H3 / H4 are the live
candidates. H5 is the residual.

## Important context: prompt-symmetry was NOT preserved past M5.2

A grep across `m6_sweep.py`, `m6_1_sweep.py`, `m6_1_1_sweep.py` shows
zero references to `symmetry` / `chat_corpus` / `prompt_for_*` /
similar. The M5.2 spec (`019-m5-2-transport-tuning/`) explicitly
introduced prompt-symmetry enforcement via `m5_2_symmetry.py` so REST
and gRPC cohorts saw the same logical request for the same iteration
index (corpus-based, deterministic).

That code is still in-tree but is NOT wired into M6 / M6.1 / M6.1.1.
**Each M-milestone sweep has been using whatever per-cohort prompt
defaulting the synthetic-prompt helper produces, which may or may not
be symmetric depending on how cohort iteration interacts with the
random/seeded prompt generator.**

This is the single most-likely explanation for `default_grpc` being the
outlier: if cohorts cycle through deterministically-seeded prompts in a
different order, each cohort sees a different prompt distribution. H1
becomes the leading candidate.

## Experiment design (proposed for M6.1.3)

**Phase A — cheap audit, ~0 incremental Modal cost.** Add per-RPC
instrumentation that captures:

- Tokenized prompt length (number of tokens fed into prefill)
- Tokenized prompt hash (BLAKE2b-8 of the token id list, hex-encoded)
- Cohort, cell, iteration index

Emit alongside the existing `m6_1_1_t_*` trailing-metadata keys (or to
the sidecar JSONL). Re-aggregate the existing Run 2 artifact: if
per-cohort token-count means differ, **H1 is confirmed** — root cause
is prompt distribution, not engine cost.

If per-cohort token-count means are identical but per-cohort
prompt-hash distributions differ → **H2 confirmed** (encoding drift).

**Phase B — controlled symmetric-prompt sweep, ~$0.30 Modal cost.**
Re-wire the M6.1.1 sweep to use the M5.2 `m5_2_symmetry`-style cohort
prompt assignment (same prompt for the same iteration index across
cohorts). Re-run Phase 1.

- If `seg_prefill` spread shrinks from 5.76 ms to within CI noise →
  **H1 was correct**; the fix is to make symmetric prompts the
  permanent M6.x convention.
- If spread persists → H3 or H4 are live. Proceed to Phase C.

**Phase C — engine-config probes, ~$0.60 Modal cost (2 sweeps).** Only
runs if Phase B doesn't resolve. Two variants:

- C1: symmetric prompts + prefix-caching disabled. If spread shrinks
  further → **H3 confirmed**; document the engine-config dependency.
- C2: symmetric prompts + reversed cohort iteration order. If the
  outlier moves with the position rather than staying on
  `default_grpc` → **H4 confirmed**; the fix is per-cohort warmup
  isolation.

**Phase D (out of scope for M6.1.3)**: if all of A/B/C come back null,
the residual is H5 (channel-config side effect) — a much deeper
investigation that probably needs vLLM-side instrumentation.

## Total Modal cost estimate

| Phase | Sweeps | Cost |
|---|---:|---:|
| A (audit-only re-aggregation) | 0 fresh | $0 |
| B (symmetric prompts) | 1 | ~$0.30 |
| C1 (prefix-caching off) | 1 | ~$0.30 |
| C2 (reversed cohort order) | 1 | ~$0.30 |
| **Max if all phases run** | **3** | **~$1** |

Likely actual cost is just Phase A + B (~$0.30), since H1 is the
most-supported hypothesis. The full matrix is bounded at ~$1.

## Edit-size estimate

**Phase A (audit instrumentation)**:

| File | Edit | Lines |
|---|---|---|
| `packages/frontend/src/vllm_grpc_frontend/chat.py` | 2 new keys (token_count, token_hash) in trailing metadata after `messages_to_prompt` | ~6 |
| `packages/frontend/src/vllm_grpc_frontend/completions.py` | Same for both `Complete` and `CompleteStream` | ~12 |
| `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` | Same for REST shim | ~6 |
| `tools/benchmark/src/vllm_grpc_bench/m6_1_1_timing.py` | Extract the 2 new fields | ~6 |
| `tools/benchmark/src/vllm_grpc_bench/m6_1_1_sweep.py` | Sidecar emission of (cohort, cell, iter_idx, token_count, token_hash) | ~15 |
| Tests | Round-trip + a "per-cohort token-count divergence detector" | ~30 |

**Total Phase A**: ~75 lines.

**Phase B (symmetric-prompt wiring)**:

| File | Edit | Lines |
|---|---|---|
| `tools/benchmark/src/vllm_grpc_bench/m6_1_1_sweep.py` | Add optional symmetric-prompt mode using M5.2's helper | ~20 |
| `tools/benchmark/src/vllm_grpc_bench/m6_1_sweep.py` | Same hook (M6.2 / M7 / M8 inherit) | ~20 |
| CLI flag in `__main__.py` | `--m6_1_1-symmetric-prompts` toggle | ~6 |
| Tests | Symmetric mode produces identical token streams per cell-iter across cohorts | ~25 |

**Total Phase B**: ~70 lines.

Phases C1 / C2 are smaller (~30 lines each, mostly CLI flags + sweep
config plumbing).

**Combined Phase A + B**: ~145 lines. Comparable to item #4's edit
estimate; both fit cleanly into a single M6.1.3 milestone.

## What this won't tell us — flag for M6.1.3 design

- The c=1 finding is on **one cell** only. The c=4 / c=8 `inconclusive`
  verdicts have a DIFFERENT failure mode (proxy-edge gap, item #4) — the
  root-cause investigation for c=1 doesn't bear on those cells.
- The audit (Phase A) is non-destructive but the symmetric-prompts
  change (Phase B) **alters the M6.1 baseline cohort comparison**. The
  decision to make symmetric prompts the convention going forward is a
  spec change, not just an experiment — needs to be reflected in M6.2 /
  M7 / M8 spec assumptions.
- vLLM's prefix-cache state is non-deterministic across deploys (cache
  warmups from prior requests, eviction order, etc.). If H3 is the
  driver, repeated runs at the same config might show different spreads
  — which connects to item #6 (run-to-run variance characterization).

## Recommended M6.1.3 scope

- **Bundle**: items #4 (proxy-edge probes), #5 (this — A + B at
  minimum), #6 (variance characterization).
- **Sequence**: ship probes (#4) + audit instrumentation (#5 Phase A)
  in one code change. Re-run Phase 1 ONCE — that single sweep produces
  data for both #4 (proxy-edge attribution) and #5-A (per-cohort
  token-count audit). Then decide on #5-B based on what the audit
  shows.
- **Cost**: ~$0.30–$1.00 Modal depending on how many follow-up sweeps
  H1's confirmation level dictates.
- **Deliverables**: per-cell attributed Phase 1 verdicts on chat_stream
  c=1 / c=4 / c=8; spec note declaring whether symmetric prompts become
  the M6.x convention; updated `classifier_notes` reflecting the new
  decision tree.

## Disposition

- Item #5 marked done at the spike level. No code change on this branch.
- M6.1.3 spec/plan can cite this note for the experiment design
  (4-phase A→B→(C1|C2)→D, H1 as leading hypothesis, ~$1 max Modal
  budget) and the leading-hypothesis recommendation (re-wire prompt
  symmetry from M5.2 as the cheapest single intervention).
