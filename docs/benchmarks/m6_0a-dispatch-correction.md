# M6.0a — Dispatch-Correction Note

**Status**: Delivered 2026-05-17. Sequel to the 2026-05-16 sequential-dispatch audit baseline.

> **TL;DR.** The M6 / M6.1 / M6.1.1 benchmark harness inherited M5.x's cell × cohort × concurrency matrix but silently dropped `asyncio.gather`-based concurrent in-flight dispatch in favour of a sequential `await` loop. Under sequential dispatch, peak in-flight RPCs equalled 1 regardless of cell `concurrency` — so the engine never saw overlapping requests from different cohorts and the M6.1.1 FR-010 classifier could not mechanistically distinguish real channel-dependent batching from chronological state drift. M6.0a restores concurrent dispatch in five harness entry points, adds a path-agnostic regression test, and re-runs M6.1.1 Phase 1 against Modal A10G `eu-west-1` to produce the corrected baseline. The dispatch fix is harness-only; no engine, transport, or wire-format changes.

## 1. What broke

The M6.1.1 audit baseline ([`m6_1_1-audit-2026-05-16-seq-dispatch.md`](./m6_1_1-audit-2026-05-16-seq-dispatch.md), committed at `b63947a`) was the first sweep that surfaced the dispatch bug. The audit run completed cleanly (30.4 min, 50/50 successes across all 18 cell × cohort pairs), but its per-cohort `engine_ttft_ms` spreads couldn't be interpreted with confidence because:

1. **Sequential dispatch**: each measurement loop iterated `for cohort: for idx: await driver(...)`. Peak in-flight = 1 even at `cell.concurrency = 4` or `8`. The `concurrency` field had become a metadata tag, not actual parallelism.
2. **Engine never overlapped requests**: vLLM's continuous batching can only batch what's in-flight together. Under sequential dispatch the engine processed one request at a time, so any cross-cohort difference in `engine_ttft_ms` had to come from chronological state drift (warm-vs-warmer cache, scheduler internal counters), not from channel-dependent batching effects.
3. **FR-010 classifier was running on uninterpretable data**: M6.1.1's classifier reads per-cohort `engine_ttft_ms` spread and attempts to attribute it to either pre-engine (transport) or in-engine (batching) causes. With no real concurrency, the attribution didn't tell us anything we could act on.

## 2. The fix

PR-1 (commit `f3ad158`) restored the canonical M5.1 dispatch pattern at five entry points across three modules:

| Module | Entry point | Pattern |
|---|---|---|
| `m6_sweep.py` | `_run_warmup` | per-(cohort × c-batch) `asyncio.gather` of `_warmup_one()` |
| `m6_sweep.py` | `_run_measurement` | per-(cohort × c-batch) `asyncio.gather` over `batch_indices` |
| `m6_1_sweep.py` | `_run_warmup_m6_1` | same pattern as `_run_warmup` |
| `m6_1_sweep.py` | `_run_measurement_m6_1` | same pattern as `_run_measurement` |
| `m6_1_1_sweep.py` | `_measure_cell` | per-cohort `asyncio.Semaphore(c)`-bounded `asyncio.gather` over `range(n_measurement)` (steady c-in-flight stream) |

Across cohorts within a cell, dispatch remains sequential — matches M5.1's canonical "in series" cohort orchestration (`m5_1_sweep.py:246`). Per-cohort, up to `cell.concurrency` RPCs run concurrently. Seed mapping is unchanged: `compute_rpc_seed(idx, base_seed)` (M6 / M6.1) and `base_seed + i` (M6.1.1) are pure functions of `(idx, base_seed)`, so the SET of `(cohort, seed)` pairs emitted is bit-identical to the pre-fix harness.

A new top-level `dispatch_mode: "concurrent"` key is injected into M6.1.1's JSON manifest by `m6_1_1_reporter.render_json` — strict-superset addition per FR-007 (no `schema_version` bump). Absent `dispatch_mode` retroactively means `"sequential"` so the audit-baseline manifest (which doesn't carry the key) parses unchanged.

## 3. The regression test

[`tools/benchmark/tests/test_m6_concurrent_dispatch.py`](../../tools/benchmark/tests/test_m6_concurrent_dispatch.py) provides 18 parametrised assertions: 9 peak-in-flight tests (`c ∈ {1, 4, 8}` × 3 entry points), 3 warmup-symmetry tests (`c=4` × 3 entry points), 6 seed-determinism tests (`c ∈ {1, 4}` × 3 entry points). A path-agnostic `_ConcurrencyProbe` fake driver wraps the project's `RPCDriver` callable signature `(cohort, cell, seed) → RPCResult`, records peak simultaneous entries via an `asyncio.sleep(0)`-yielding counter, and asserts `probe.peak == cell.concurrency`. Against the pre-fix harness the test detects the bug (9 of 18 parametrisations fail — the c=4/c=8 peak cases and all warmup cases; c=1 peak and seed-set tests are dispatch-mode-invariant by design and pass under both). Against the corrected harness all 18 pass.

## 4. Before vs after — chat_stream per-cohort `engine_ttft_ms` spread

| Cell | Audit baseline (sequential dispatch, 2026-05-16) | M6.0a-corrected (concurrent dispatch, 2026-05-17) | Direction |
|---|---|---|---|
| chat_stream c=1 | **19.5%** spread (raw means not published in audit) | **13.6%** spread (range 41.22 – 47.14 ms, mean 43.55 ms) | reduced |
| chat_stream c=4 | **6.0%** spread | **15.9%** spread (range 74.01 – 87.01 ms, mean 81.78 ms) | **2.65× increase** |
| chat_stream c=8 | **8.4%** spread | **16.4%** spread (range 86.93 – 102.21 ms, mean 93.34 ms) | **1.95× increase** |

The **direction** is the headline finding. Under sequential dispatch the spread at c=4 and c=8 was artificially compressed — with no real concurrency, the per-cohort first-token times converged toward baseline RTT variation. Under TRUE concurrency the spread at c=4 and c=8 *grows* to ~16%, well above the M6.1.1 5% drift_not_reproduced threshold. This **cleanly disproves the "sequential-dispatch artifact" hypothesis** that the original M6.1 per-cohort drift was a chronological state-drift artifact. Something real is happening when the engine sees overlapping requests from different cohorts; the magnitude depends on how the cohort's channel configuration interacts with the engine's continuous batching.

The c=1 reduction (19.5% → 13.6%) is consistent with the corrected harness having one fewer source of state drift — at c=1 there's no concurrency to harness either way, so the spread reflects baseline cohort RTT differences and any residual scheduler-state delta from the (now slightly different) overall sweep timing. Both numbers are well above the 5% threshold.

### What this comparison does NOT tell you

The M6.1.1 FR-010 classifier produces `channel_dependent_batching × 3` for the corrected run (identical to the audit baseline classification). **This classification is mechanically inevitable for any non-trivial chat_stream spread** under the current four-checkpoint instrumentation — `seg_bc_ms` is identical to `engine_ttft_ms` by construction (both measure `first_chunk_ns − pre_engine_ns`), so the classifier's `spread(seg_bc) / spread(engine_ttft) ≥ 0.80` attribution rule always fires. The audit baseline header documents this as an open issue ([PR #27 comment 4468600646](https://github.com/AncientStudying/vllm-grpc/pull/27#issuecomment-4468600646)); it remains unresolved after M6.0a because it is out of M6.0a's scope (M6.0a is a dispatch correction, not a classifier redesign).

**Net interpretation**: the dispatch correction removes ambiguity about whether real concurrency is happening (it is) and disproves the "sequential artifact" hypothesis (it is not), but does not by itself close out M6.1.1's Phase 2 verdict. The FR-010 classifier degeneracy needs a separate resolution (most likely a checkpoint placement change so `seg_bc` measures something the classifier can actually attribute against — see [M6.1.1 PR #27](https://github.com/AncientStudying/vllm-grpc/pull/27)).

## 5. Implication for M6.x findings — dispatch-sensitive vs dispatch-robust

| Finding | Dispatch sensitivity | Notes |
|---|---|---|
| **M6 main verdicts** (engine cost dominates; transport delta < 5× engine cost on every cell) | **Dispatch-robust** | M6's verdicts compare per-cell aggregate timings between cohorts. Both audit-baseline-equivalent (sequential) and corrected (concurrent) runs preserve the rank order and the order-of-magnitude relationship between engine cost and transport delta. No re-run needed. M6's `m6_meta.dispatch_mode` is absent (pre-M6.0a manifest) → reads as `"sequential"` per FR-007. |
| **M6.1 engine-path differential** (chat_stream and embed engine paths behave equivalently when prompt-embeds replaces text prompts on the chat_stream path) | **Dispatch-robust** | M6.1's main verdict is the *equivalence* of engine paths, not the per-cohort spread. The equivalence holds under both dispatch modes — the engine sees the same call sequence. The c=1 per-cohort drift sub-finding (14-17% drift in M6.1's published narrative) is **dispatch-sensitive** and is annotated with a forward cross-link to this note (see [M6.1 narrative](./m6_1-real-prompt-embeds.md)). |
| **M6.1.1 Phase 1 FR-010 classification** (uniform `channel_dependent_batching × 3` on chat_stream cells) | **Dispatch-sensitive but classifier-degenerate** | Both runs produce the same classification *label*. Under sequential dispatch, the label was unreliable (no real concurrency to classify). Under concurrent dispatch, the label is mechanically inevitable (seg_bc ≡ engine_ttft by construction). Neither run constitutes affirmative evidence of channel-dependent batching as a Phase 2(b) verdict. Phase 2 remains pending until the classifier degeneracy is resolved separately. |

A reader can determine in ≤ 5 min from this table which M6.x findings need re-interpretation (only one sub-finding: M6.1's c=1 per-cohort drift) and which stand as-published. M6 and M6.1's main verdicts are dispatch-robust; M6.1.1's Phase 1 classification is dispatch-sensitive only insofar as it is degenerate under both modes.

## 6. Cross-links

- **Sequential-dispatch audit baseline**: [`m6_1_1-audit-2026-05-16-seq-dispatch.md`](./m6_1_1-audit-2026-05-16-seq-dispatch.md) (committed at `b63947a`)
- **Corrected-dispatch run**: [`m6_1_1-engine-cost-instrumentation.md`](./m6_1_1-engine-cost-instrumentation.md) + [`m6_1_1-engine-cost-instrumentation.json`](./m6_1_1-engine-cost-instrumentation.json) (run completed 2026-05-17 02:10 UTC, 15.6 min, $0.29 Modal A10G eu-west-1)
- **M6.1.1 PR (held open during M6.0a)**: [PR #27](https://github.com/AncientStudying/vllm-grpc/pull/27)
- **PLAN.md M6.0a section**: [`docs/PLAN.md#m60a--concurrent-dispatch-restoration-planned-blocks-m611-closure`](../PLAN.md#m60a--concurrent-dispatch-restoration-planned-blocks-m611-closure)
- **M6.0a spec / plan / tasks**: [`specs/024-m6-0a-concurrent-dispatch/`](../../specs/024-m6-0a-concurrent-dispatch/)
