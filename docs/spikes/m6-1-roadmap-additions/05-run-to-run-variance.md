# Spike #6 — Run-to-run variance characterization (M6.1.3 scoping note)

**Branch**: `spike/m6-1-roadmap-additions`
**Date**: 2026-05-17
**Status**: ✅ Read-only investigation complete. Implementation deferred to **M6.1.3**.

## Recap of the concern

M6.1.1's published artifact carries two back-to-back Phase 1 runs at
the same config (n=50, base_seed=42, A10G `eu-west-1`, same model
identifier, M6.0a-corrected concurrent dispatch). Both runs were done
within ~9 hours of each other (Run 1 at 01:54 UTC, Run 2 at 10:48
UTC); the second was a re-run after the M6.1.1 expansion classifier
upgrade. By construction they should produce nearly-identical
per-cohort `engine_ttft_ms` means.

They didn't. Computed directly from the artifact's `phase_1_runs[]`:

### chat_stream c=1 (well-behaved)

| Cohort | Run 1 ttft | Run 2 ttft | Δ |
|---|---:|---:|---:|
| rest_https_edge | 42.27 | 42.14 | −0.13 |
| default_grpc | 47.14 | 46.58 | −0.56 |
| tuned_grpc_multiplexed | 41.22 | 40.81 | −0.41 |

- within-run spread: Run 1 = 5.92 ms, Run 2 = 5.77 ms
- between-run |Δ|: max **0.56 ms**, mean 0.37 ms
- **noise ÷ signal ≈ 6–10%** ✓ reproducible

### chat_stream c=4 (the problem cell)

| Cohort | Run 1 ttft | Run 2 ttft | Δ |
|---|---:|---:|---:|
| rest_https_edge | 87.01 | **101.57** | **+14.56** |
| default_grpc | 84.31 | 75.05 | **−9.26** |
| tuned_grpc_multiplexed | 74.01 | 81.78 | **+7.77** |

- within-run spread: Run 1 = 13.00 ms, Run 2 = 26.52 ms
- between-run |Δ|: max **14.56 ms**, mean 10.53 ms
- **noise ÷ signal ≈ 50–100%** ✗ NOT reproducible

### chat_stream c=8 (intermediate)

| Cohort | Run 1 ttft | Run 2 ttft | Δ |
|---|---:|---:|---:|
| rest_https_edge | 102.21 | 97.65 | −4.56 |
| default_grpc | 90.90 | 90.01 | −0.89 |
| tuned_grpc_multiplexed | 86.93 | 84.32 | −2.61 |

- within-run spread: Run 1 = 15.28 ms, Run 2 = 13.33 ms
- between-run |Δ|: max **4.56 ms**, mean 2.69 ms
- **noise ÷ signal ≈ 20–30%** ⚠ marginal

## What this means for the M6.1.1 verdicts

- **c=1's `engine_compute_variation` is reproducible** — between-run
  noise is well under the CI half-widths (typically ±0.1 to ±1.3 ms).
  Item #5's root-cause investigation can proceed against a stable
  baseline.
- **c=4's `inconclusive` is not just "we don't know where the gap is"
  (item #4) — it's also "the gap moves between runs"**. Adding
  proxy-edge probes alone won't fix this; even with full attribution,
  the attributed bucket might be different next run.
- **c=8 sits between** — probably attributable, but with wider
  uncertainty than the artifact's CI half-widths suggest (the CIs
  reflect sample-noise only, not run-to-run variance).

**The CI half-widths in the artifact UNDERSTATE the true uncertainty**
for c=4 and arguably c=8. They're bootstrap CIs over the n=50 sample,
which captures intra-run noise but not the additional run-state /
deploy-state noise that compounds on top.

## The variance has structure: it scales with concurrency

Between-run noise grows from 0.37 ms (c=1) → 2.69 ms (c=8) → 10.53 ms
(c=4) average. **c=4 has the worst signal-to-noise ratio** —
non-monotonic, which is suspicious. Two plausible explanations:

- The 4-way concurrent batch interacts with the engine's batching
  scheduler in a way that's particularly sensitive to whatever
  per-run state varies (KV-cache footprint, scheduler microstate,
  allocator state, etc.). c=1 is too sparse to hit the sensitivity;
  c=8 saturates past it.
- Or it's coincidence — two runs aren't enough data to distinguish.
  We're computing |Δ| over n=2 runs, which has its own n=2 noise.

Either way, n=2 is insufficient to characterize variance. We need ≥ 5
runs at each cell to compute meaningful between-run variance, ideally
with each run's deploy isolated.

## Hypothesis space — four sources of variance

| # | Source | What it is | How n=50 → n=200 affects it | How separate deploys affect it |
|---|---|---|---|---|
| V1 | **Sample noise** | random / seeded variation across the n RPCs in a single sweep | shrinks as 1/√n | unchanged |
| V2 | **Run-state noise** | KV-cache state, container warmth, Python allocator state, vLLM scheduler microstate changing between back-to-back runs (no redeploy) | unchanged with n | shrinks per-run isolation |
| V3 | **Deploy-state noise** | cold-start variations, different worker pods, infrastructure jitter (changes when teardown + redeploy) | unchanged with n | this IS the deploy-state noise — magnitude reveals it |
| V4 | **Network-path noise** | hop-by-hop latency variation along the routes characterized in spike #1 | unchanged with n | could change if Modal routes to different worker on redeploy |

The artifact's bootstrap CI captures **V1 only**. V2 + V3 + V4 are all
missing from the published uncertainty estimate — that's why the
between-run |Δ| outstrips the CI half-widths.

## Experiment design (proposed for M6.1.3)

Each experiment isolates a different variance source by choosing what
to hold constant. Modal-cost calculation assumes ~15 min per n=50
Phase 1 run at A10G eu-west-1 = ~$0.29 (per memory + M6.1.1
empirics).

### Phase A — between-run characterization at n=50 (no redeploy, fixed seed)

- Configuration: same deploy, same model, same base_seed, same n=50,
  fire `--m6_1_1-diagnose` **5 times back-to-back**.
- Output: per-cohort per-cell between-run variance estimate at n=5;
  add to artifact under a new `between_run_variance` block.
- **Isolates**: V2 (run-state) on top of V1 (sample noise).
- **Modal cost**: 5 × ~$0.29 = **~$1.45**.

### Phase B — n=200 power test (single run)

- Configuration: same deploy, same seed, n=200 (4× M6.1.1 baseline),
  one run.
- Output: confirm CI half-widths shrink by ~2× (sqrt(4)). Determine
  whether the c=4 problem is solvable by sample size alone.
- **Isolates**: V1 reduction.
- **Modal cost**: ~60 min × $0.0193/min ≈ **~$1.16**.

### Phase C — multi-deploy variance (5 runs across separate deploys)

- Configuration: same model, same seed, n=50, but **teardown +
  redeploy** between each of the 5 runs (or use 5 separate Modal
  app-handles concurrently).
- Output: V3 + V4 magnitude, independently of V2.
- **Isolates**: V3 (deploy-state) + V4 (network-path).
- **Modal cost**: 5 × (~$0.29 + ~$0.05 deploy overhead) ≈ **~$1.70**.

### Phase D — multi-seed variance (3-5 runs, varied base_seed)

- Configuration: same deploy, n=50, base_seed = {42, 142, 242, 342,
  442}.
- Output: V1-like component that's seed-dependent vs uniform across
  seeds. Distinguishes "seeded prompt variation" (which item #5 also
  cares about) from intrinsic random noise.
- **Isolates**: seed-induced subset of V1.
- **Modal cost**: 5 × ~$0.29 = **~$1.45**.

## Total Modal cost matrix

| Combination | Cost | What you learn |
|---|---:|---|
| Phase A only | ~$1.45 | Is c=4 reproducible at all under fixed everything? |
| Phase A + B | ~$2.60 | + Does sample size fix c=4? |
| Phase A + B + C | ~$4.30 | + Is the noise primarily within-deploy or across-deploy? |
| Full A + B + C + D | ~$5.75 | + Plus seed-sensitivity attribution |

Recommended M6.1.3 bundle: **A + B**. Together they tell us
(i) is the c=4 signal reproducible at all (Phase A), and (ii) does
4×-ing the sample size fix the c=4 problem (Phase B). C and D become
follow-ups if A + B don't resolve.

## Edit-size estimate

The orchestrator already supports `phase_1_runs[]` accumulation
(round-3 Q1 — exactly the rehydration path we fixed earlier on this
session). Multi-run is supported by design — the existing code just
needs a "run K times in sequence" wrapper.

| File | Edit | Lines |
|---|---|---|
| `tools/benchmark/src/vllm_grpc_bench/__main__.py` | New `--m6_1_1-diagnose-repeat=N` CLI flag; new `--m6_1_1-diagnose-n=200` flag for Phase B | ~12 |
| `tools/benchmark/src/vllm_grpc_bench/m6_1_1_diagnose.py` | Loop `run_m6_1_1_diagnose` body N times when repeat > 1; each iteration appends to `phase_1_runs[]` (already supported by the rehydrator fix); thread the `n_per_cohort` override through | ~25 |
| `tools/benchmark/src/vllm_grpc_bench/m6_1_1_sweep.py` | Honor the n override in `M6_1_1ProgressReporter` startup banner + `n_per_cohort` field | ~6 |
| `tools/benchmark/src/vllm_grpc_bench/m6_1_1_types.py` | New optional `between_run_variance: dict[str, dict[str, float]] \| None` field on `M6_1_1Run` | ~10 |
| `tools/benchmark/src/vllm_grpc_bench/m6_1_1_sweep.py` (variance compute) | New `compute_between_run_variance(phase_1_runs)` that produces per-cohort per-cell `(mean_of_means, stddev_of_means, n_runs)` | ~30 |
| `tools/benchmark/src/vllm_grpc_bench/m6_1_1_reporter.py` | New section "Between-Run Variance" rendered when `phase_1_runs[] >= 3`; markdown table mirroring the Phase 1 timing tables | ~30 |
| `tools/benchmark/src/vllm_grpc_bench/m6_1_1_classifier.py` | Augment 5-bucket (or 7-bucket post-item-#4) with an `inconclusive_high_variance` label when between-run |Δ| > X% of within-run spread | ~20 |
| Tests | Multi-run accumulator behavior, variance compute, reporter section | ~50 |

**Total Phase A + B implementation**: ~180 lines. Comparable to
items #4 and #5 individually.

**Phase C (multi-deploy)** adds Modal-deploy plumbing (~30 lines) to
tear down + redeploy between runs. **Phase D (multi-seed)** is just
a CLI flag (~10 lines). Both small.

## What this won't tell us — flag for M6.1.3 design

- Variance characterization gives us **measured** uncertainty bounds,
  but it doesn't FIX the c=4 problem if the noise is intrinsic to the
  measurement setup. If A + B show n=200 + 5-run averaging still leaves
  c=4 unreproducible, we have to either accept the wider uncertainty
  (publish CIs that span the inconclusive verdict) or redesign the
  c=4 sweep (different concurrency target, different cell definition,
  etc.).
- Phase A's "no redeploy" assumes Modal doesn't preempt the function
  mid-sequence. The M5.2 sweep had a preemption-aware URL refresh
  precisely because of this. M6.1.3 should reuse that pattern (it's
  already in `m5_2_sweep.py`; just needs porting to the diagnose
  loop).
- The 2-run dataset we already have is enough to **flag** the problem
  (between-run |Δ| outstrips CI half-widths) but **not enough to
  characterize** it (we can't compute variance from n=2 runs in a
  meaningful way).
- The `between_run_variance` finding has implications for items #4 and
  #5: if the proxy-edge gap (item #4) varies between runs, item #4's
  attribution will too. If the engine_compute_variation finding (item
  #5) varies between runs, item #5's hypothesis testing needs multi-run
  controls.

## Recommended M6.1.3 scope

Builds on the bundle from items #4 + #5:

- **Implement**: Phase A (5-run characterization) + Phase B (n=200
  power test). Modal: ~$2.60. Edit: ~180 lines.
- **Sequence with items #4 + #5**: After the proxy-edge probes (#4)
  and audit instrumentation (#5-A) ship, run Phase A — each of the 5
  runs uses the new instrumentation. This gives us:
  - 5 datapoints of proxy-edge attribution per cell (#4)
  - 5 datapoints of per-cohort token-count distribution (#5-A)
  - 5 datapoints of `engine_ttft_ms` per cell × cohort (#6)
  - All from the same multi-run config. Maximally informative per
    Modal dollar.
- **Then**: Run Phase B (n=200) once at the highest-uncertainty cell
  to confirm sample-size scaling works as expected.
- **Total M6.1.3 Modal cost** (items #4 + #5-A + #6-A + #6-B):
  - Items #4 + #5-A baseline: ~$0.30 (one sweep, just instrumented
    differently)
  - Item #6 Phase A: ~$1.45 (5 runs)
  - Item #6 Phase B: ~$1.16 (one n=200 run)
  - **Total: ~$2.90**, well under any reasonable budget.

## Disposition

- Item #6 marked done at the spike level. No code change on this
  branch.
- M6.1.3 spec/plan can cite this note for:
  - The variance decomposition framework (V1–V4 hypothesis space)
  - The 4-phase experiment design (A → B → optional C → optional D)
  - The Modal-cost budget (~$2.60 for A + B; ~$5.75 for full matrix)
  - The "bundle multi-run with items #4 + #5" sequencing rationale
- The artifact-level conclusion: **the M6.1.1 published CIs are honest
  about sample noise but understate true cohort-comparison uncertainty
  at c=4 and (weakly) c=8.** That's a finding the M6.1.3 spec should
  pull into its motivation section.
