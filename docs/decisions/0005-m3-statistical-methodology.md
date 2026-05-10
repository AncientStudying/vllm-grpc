# ADR 0005 — M3 Statistical Methodology: 95% CI Win Bar, Predecessor Pairing, `noise_bounded` Verdict

**Date**: 2026-05-10
**Status**: Accepted
**Branch**: `015c-m3-phase-a-time-reanalysis` (initially recorded; rule applies retroactively to PR #17 and forward to M4)
**Related**: [`015-m3-protobuf-grpc-tuning/spec.md`](../../specs/015-m3-protobuf-grpc-tuning/spec.md) (SC-003, SC-006, FR-005); [`015-m3-protobuf-grpc-tuning/research.md`](../../specs/015-m3-protobuf-grpc-tuning/research.md) (R-1, R-11, R-12, R-14)

---

## Context

M3 produces channel-tuning recommendations from a CPU-only mock-engine sweep. Three statistical-methodology questions arose during the milestone — one in Phase 0 / R-1 (the "win" threshold), two during Phase A / US3 (baseline pairing for the time metric, and a new verdict literal for cells the harness cannot defensibly resolve). All three are non-obvious enough that future readers (and M4) need them recorded as project-level decisions, not buried in spec-internal research notes.

The decisions below apply uniformly across the bytes metric (PR #17), the time metric (Phase A / US3, this branch), and any future time-axis sweeps in M4.

---

## Decision 1: 95% CI win bar (SC-003)

### Choice

A candidate channel configuration earns a `recommend` verdict against an M1_BASELINE comparator only when the candidate's 95% confidence interval is strictly separated from the baseline's 95% confidence interval — i.e., the candidate's upper CI bound is below the baseline's lower CI bound for our minimizing metrics (bytes, time, TTFT — smaller is better).

Operationally, with n=30 iterations per cell and the t-distribution at α=0.025 (two-sided), the critical value is ≈2.045 (`scipy.stats.t.ppf(0.975, 29)`); this is hard-coded in `tools/benchmark/src/vllm_grpc_bench/ci.py` so the bench package stays scipy-free. CI half-width = `t_critical * stddev / sqrt(n)`. The "candidate's CI clears the baseline's CI" check is implemented by `ci.is_winner(baseline_ci_high, candidate_ci_low)` against the appropriately-signed inputs.

### Why

- 30 samples is the smallest sample size at which the t-distribution converges close to the normal — long-standing convention in performance engineering, and the math is stable.
- For typical M1 measurement noise (~5–10% relative, observed in `docs/benchmarks/phase-4.2-three-way-comparison.md`), n=30 puts the 95% CI half-width at roughly 2–4% of the mean. This is well below the wins we expect to see on channel tuning (single-digit to mid-double-digit percent), but it is a strict bar: a candidate must clear it.
- Comparing means alone would let a noisy candidate accidentally claim a win. The CI-separation rule is an explicit pre-registered hypothesis test — pass or fail, no after-the-fact massaging.

### Alternatives rejected

- *n=10*: t-critical jumps to 2.262, CI half-widths blow up. Insufficient rigor.
- *Bootstrap resampling*: more robust to non-normal distributions but adds complexity and only marginal benefit on a benchmark where each iteration is a clean repeated measurement.
- *Bayesian / sequential testing*: overkill for the M3 budget; introduces priors that would need their own justification.

### Consequences

- The bench harness must run ≥30 iterations per cell. CI eligibility for the harness is gated on this (smoke runs explicitly skip the CI math).
- A "honest negative result" — `no_winner` with full CI numbers — is a first-class outcome. Both the M3 bytes report (PR #17) and the time report (this branch) record `no_winner` cells with the same evidentiary detail as `recommend` cells.

---

## Decision 2: Immediate-predecessor M1_BASELINE pairing for time-axis verdicts

### Choice

For the time metric (`metric="time"` for embed cells, `metric="ttft"` for chat_stream cells), `m3_sweep.build_recommendations` pairs each candidate cohort with its **immediate-predecessor M1_BASELINE in cohort run-order at the same `(path, hidden_size, corpus_subset)`** — not the global "first M1_BASELINE in the group" the bytes path uses.

The bytes path (PR #17) pairs against the first matching baseline because the bytes metric exhibits ~0.01% cross-batch drift on this harness — pairing choice doesn't matter for bytes verdicts. The time path uses immediate-predecessor pairing because the time metric exhibits substantially larger cross-batch drift.

### Why

In PR #17's run, the same M1_BASELINE cell (chat_stream/h=2048/m1_chat) measured at four different points across the four axis batches showed mean wall-clock of 184.4 / 182.4 / 204.9 / 207.9 ms — a **13% spread** driven by ambient system load between axis batches. The bytes metric for the same baseline cohorts varied by <0.01%. A time-axis SC-003 evaluation against a non-paired baseline could spuriously claim a win or miss a real one solely because of when the baseline happened to be measured relative to the candidate.

Immediate-predecessor pairing kills the drift contamination by pairing each candidate with the baseline measured immediately before it in the same axis batch — the system-load conditions are most similar between consecutive measurements.

### Alternatives rejected

- *First-baseline-in-group* (the bytes path): broken for time, as documented above.
- *Mean of all same-cell baselines*: dilutes the signal — fast and slow baselines average out, but the candidate is still measured against a single arbitrary point in the drift band.
- *Shared-baseline mode (FR-013)*: the *correct* long-term answer — measure one large M1_BASELINE cohort (n≥100) up front and reuse it. Implementation deferred to M4 because it requires harness changes; immediate-predecessor pairing is the Phase A workaround that lets us verdict the existing data without re-running.

### Consequences

- The time-axis path needs to know cohort run-order. The current implementation walks the input cohorts list in the order it was given — which is the order `run_sweep` appended them. Any future re-ordering of cohorts before `build_recommendations` would need to preserve run-order or carry an explicit ordering field.
- Multi-baseline noise stability is a separate check (Decision 3) — predecessor pairing alone is not enough; we also verify the verdict survives against alternative baselines.

---

## Decision 3: `noise_bounded` verdict literal (FR-005)

### Choice

Add a fourth verdict literal to `Recommendation.verdict` — `"noise_bounded"`, alongside the existing `"recommend"`, `"no_winner"`, `"not_measurable"`. A cell receives `noise_bounded` when:

1. The predecessor pairing claims a win (candidate CI strictly below predecessor baseline CI), AND
2. The win does not survive against at least one *alternative* same-cell M1_BASELINE.

Per the dataclass invariant in `m3_types.py`, every `noise_bounded` recommendation must carry a populated `notes` field naming the dominating noise source (typically the cross-baseline relative spread and the count of alternative baselines that disagreed).

### Why

`recommend` would falsely claim stability the harness cannot produce. `no_winner` would falsely report the bar wasn't met when the predecessor pairing did meet it. `not_measurable` is reserved for "the harness produced no usable data" (e.g., baseline cohort failed to run) — different meaning. The honest verdict for a cell where the conclusion *depends on which baseline you happen to pair with* is a fourth literal that says exactly that.

In Phase A's re-analysis of PR #17's data, two cells fell to `noise_bounded`:

- `keepalive` × embed × h=2048 (wall-clock): predecessor claimed `keepalive-aggressive` as winner; the win did not survive against 1 alternative same-cell baseline; cross-baseline spread = 13.5%.
- `http2_framing` × chat_stream × h=4096 (TTFT): predecessor claimed `http2-bdp-probe` as winner; did not survive against 3 alternative same-cell baselines; cross-baseline spread = 35.2%.

Both cells re-measure under M4's shared-baseline harness (FR-013) — neither becomes a recommendation in the M3 report.

### Alternatives rejected

- *Force-pick `recommend` or `no_winner` based on majority of baseline outcomes*: hides the methodology fragility from the reader. Constitution V (Honest Measurement) prefers explicit "we couldn't tell" over plausible-looking false certainty.
- *Use predecessor verdict only, ignore alternative baselines*: reproduces the cross-batch drift problem the bytes-path-on-time-data would have. Caller cannot tell whether the predecessor was a typical sample or an outlier.
- *Run more iterations to shrink CIs and force resolution*: more iterations can't reduce the *cross-batch* drift, only within-batch noise. The drift is inherent to the per-axis-batch baseline measurement pattern; only shared-baseline mode (FR-013, M4) actually resolves it.

### Consequences

- The `Recommendation` dataclass invariant is now: `verdict ∈ {"recommend", "no_winner", "not_measurable", "noise_bounded"}`; `noise_bounded` requires non-empty `notes`. Both M3 reports (bytes and time) emit cells with this verdict where appropriate.
- Reports MUST list every `noise_bounded` cell in a Limitations section as an explicit M4 input — these are not ambiguous "maybes" left for the reader to interpret, they are flagged work items.
- The `p1_frozen_config_time` rule (the time-axis analog of `p1_frozen_config`) defaults the entire axis to `M1_BASELINE` if any cell on that axis is `noise_bounded` — we cannot freeze a configuration we couldn't defensibly verdict, even if a sibling cell on the same axis produced a clean `recommend`.

---

## Cross-cutting consequence: SC-003 vs SC-006 symmetry

SC-003 (originally bytes-only) and SC-006 (time, added 2026-05-10) use the same statistical bar, the same per-cell n=30 default, and the same CI-separation win rule. The only metric-specific difference is the pairing rule: bytes path uses first-baseline-in-group (Decision 2 above), time path uses immediate-predecessor pairing. M4's shared-baseline mode (FR-013) collapses this difference by giving both metrics one canonical baseline.

This ADR is the canonical reference for both SC-003 and SC-006 evaluation; future milestones MUST reference it (or supersede it explicitly) when extending the verdict surface.

---

## References

- [`tools/benchmark/src/vllm_grpc_bench/ci.py`](../../tools/benchmark/src/vllm_grpc_bench/ci.py) — CI estimator, t-critical table, `is_winner()` helper.
- [`tools/benchmark/src/vllm_grpc_bench/m3_sweep.py`](../../tools/benchmark/src/vllm_grpc_bench/m3_sweep.py) — `build_recommendations` dispatcher; `_build_recommendations_bytes` (first-baseline pairing); `_build_recommendations_time_axis` (immediate-predecessor pairing + `noise_bounded` detection).
- [`tools/benchmark/src/vllm_grpc_bench/m3_types.py`](../../tools/benchmark/src/vllm_grpc_bench/m3_types.py) — `Recommendation` dataclass with the four-verdict invariant.
- [`docs/benchmarks/m3-channel-tuning.md`](../benchmarks/m3-channel-tuning.md) — bytes-axis verdicts using Decisions 1 and "first-baseline" pairing.
- [`docs/benchmarks/m3-channel-tuning-time.md`](../benchmarks/m3-channel-tuning-time.md) — time-axis verdicts using Decisions 1, 2, and 3.
- [`specs/015-m3-protobuf-grpc-tuning/research.md`](../../specs/015-m3-protobuf-grpc-tuning/research.md) — R-1 (CI rule), R-11 (mock pacing dilution), R-12 (cross-batch drift evidence), R-14 (Phase A vs. M4 scope).
