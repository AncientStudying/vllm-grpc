# Phase 0 Research: M6.2 — Token-Budget Characterization

**Branch**: `027-m6-2-token-budget` | **Date**: 2026-05-19 | **Plan**: [plan.md](./plan.md)

## Overview

Phase 0 captures the implementation-level research that complements the spec-level decisions made during the 4-round `/speckit-clarify` cycle (22 Q/A bullets total). The Technical Context in [`plan.md`](./plan.md) has no `NEEDS CLARIFICATION` markers — every architecturally-significant choice was resolved during clarify. Phase 0 here documents the code-surface investigation needed to write the data model and contracts cleanly.

The single open deferral (publish-mode `n` per FR-004) is methodology-bounded: the publish-mode orchestrator MUST refuse `--m6_2` invocation if `--m6_2-n` is unset; a future clarify round 3 pins the value after validate-sweep variance data lands. No implementation-side research is needed for the deferral — the gate enforcement is the contract.

## Research Items

### R-1 — M6.1.3 module file set + naming convention inheritance

**Decision**: M6.2 mirrors M6.1.3's parallel-module pattern (which mirrors M6.1.2's, which mirrors M6.1.1's). Files: `m6_2_types.py`, `m6_2_sweep.py`, `m6_2_reporter.py`, `m6_2_validate.py`, `m6_2_crossover.py`, `m6_2_anchor_trajectory.py`. Each `m6_2_*` follows the `m6_2_<role>.py` pattern. Six new modules total; no shared cross-milestone helper introduced by M6.2 (the M6.1.3 `symmetric_prompts.py` is imported, not extended).

**Rationale**: M6.1.1 established the "one module per concern" convention; M6.1.2 inherited it with 5 modules; M6.1.3 inherited with 8 (more concerns: 7-bucket classifier extension, pooled audit aggregation, between-run variance compute, plus the shared helper); M6.2 inherits with 6 (the 4 standard `_types` / `_sweep` / `_reporter` / `_validate` modules plus the 2 net-new `_crossover` and `_anchor_trajectory` pure-function modules for the new M6.2 analyses). The split is intentional — crossover and anchor-trajectory modules each carry significant pure-function logic that's easier to unit-test in isolation than as part of a larger orchestrator. The parallel-module pattern (vs in-place modification of `m6_1_3_*` files) is mandated by the M6.1.3 FR-037 freeze rule (prior-milestone historical re-runnability stays frozen).

**Alternatives considered**:
- Modify `m6_1_3_sweep.py` in-place to add the `max_tokens` axis — REJECTED because in-place modification breaks the M6.1.3 FR-037 freeze on `--m6_1_3` historical output. The parallel `m6_2_*` family preserves M6.1.3 re-runnability.
- Bundle crossover + anchor-trajectory into `m6_2_sweep.py` — REJECTED; the two concerns have separable test surfaces (crossover doesn't depend on anchor trajectory; both are pure functions consumed by the reporter). Module-per-concern matches the M6.1.x pattern.
- Add new `m6_2_*` modules for KV-pressure computation separately — REJECTED; the KV-pressure inference is logically the same family as crossover (both are derived analyses on top of the same per-(cell, cohort, max_tokens) measurements). Combining them in `m6_2_crossover.py` reduces module count without losing test isolation.

### R-2 — Sweep iteration order: cohort-innermost block iteration (FR-030)

**Decision**: The orchestrator iterates as:
```python
for cell in M6_1_CELLS:                               # outer
    for max_tokens in M6_2_MAX_TOKENS_AXIS:           # middle
        for cohort in cohorts_at_concurrency(cell):   # innermost (per FR-030)
            for rpc in range(n):                       # per-cohort dispatch (concurrent per FR-007)
                ...
```
where `M6_2_MAX_TOKENS_AXIS = (10, 50, 256, 512, 1024, 2048)` in publish mode and `(10, 50, 2048)` in validate mode. The outer-loop `(cell × max_tokens)` order is `(M6_1_CELLS × M6_2_MAX_TOKENS_AXIS)` — cells iterate first, then max_tokens within each cell. This pairs each `(cell, max_tokens)` tuple with its 4 contiguous cohort blocks per FR-030.

**Rationale**: Cohort-innermost is the FR-030 spec-level decision (round-4 Q1). The choice of `(cell × max_tokens)` outer order vs `(max_tokens × cell)` outer order is implementation-deferred per FR-030 but MUST keep each `(cell, max_tokens)` tuple's 4 cohort blocks contiguous. Cells-first means the per-cell rendering in the reporter naturally aligns with the iteration order; max_tokens-first would interleave cells which complicates the reporter's per-cell aggregation. Cells-first is the natural choice.

The `iteration_discipline_verified` machine check (FR-032) inspects the per-block UTC timestamps post-hoc: for every `(cell, max_tokens)` tuple, the 4 cohort blocks' timestamps must be contiguous (no other tuple's blocks fall between them). The check is purely diagnostic — it never blocks publication, only emits a soft warning header.

**Alternatives considered**:
- Max_tokens-outermost, cells-middle, cohort-innermost — REJECTED; would interleave cells, complicating per-cell aggregation in the reporter and making the per-cell trajectory in the wall-clock timeline subsection less readable.
- Randomized `(cell, max_tokens)` outer order — REJECTED; the cohort-innermost discipline already controls between-cohort time-of-day bias; adding randomization to the outer order would distribute within-cell axis-trend variance across the wall clock without methodological benefit, and would make the wall-clock timeline subsection harder to interpret.
- Cohort-outermost — REJECTED at spec round-4 Q1; this option was explicitly named as "the bad baseline" and is FORBIDDEN per FR-030.

### R-3 — Intra-sweep anchor re-measurement implementation (FR-031)

**Decision**: The `m6_2_anchor_trajectory.compute_anchor_block(...)` function is invoked by `m6_2_sweep.py` at sweep start, sweep end, and every 4-hour wall-clock mark in between (in publish mode). The function runs a minimal `chat_stream × c=1 × max_tokens=10` measurement per cohort, `n=20` RPCs, executed cohort-innermost (per FR-030's same-tuple-discipline-applies-to-the-anchor-block). The 4-hour mark is determined by polling `time.monotonic()` against the sweep's start timestamp; the sweep yields an anchor-block invocation when `(now - sweep_start) / 3600 >= next_anchor_mark` where `next_anchor_mark` advances by 4 each fire. Validate-mode (sweep wall-clock < 8h) skips in-flight marks and only fires the start + end anchors.

**Rationale**: The 4h cadence aligns with FR-009's `network_paths` cadence so the operator gets a unified "sweep health check" tick: at each 4h mark, both the topology probe (FR-009) AND the anchor re-anchor (FR-031) co-fire. Implementation-wise this is one synchronization barrier per 4h mark — the sweep orchestrator finishes the current `(cell, max_tokens, cohort)` RPC, runs the network_paths probe, runs the anchor re-anchor across all 4 cohorts, then resumes the main iteration.

The chat_stream × c=1 × max_tokens=10 cell choice optimizes for: (a) cheap (low max_tokens → ~35 ms per RPC), (b) network-latency-sensitive (c=1 → no concurrent dispatch masking; the wall-clock includes the full network round-trip), (c) symmetric across cohorts (chat_stream is the canonical Story 2 cell-type). At n=20, the anchor block per cohort takes ~0.7s wall-clock; cohort-innermost iteration across 4 cohorts is ~3s; plus channel setup overhead per cohort is ~5-10s; total ~30-50s per 4h-mark anchor-block firing. Over a 40h publish sweep with 9 in-flight marks + start + end (~11 firings), cumulative overhead is ~5-10 min — well under the FR-031's "≤ ~25 min cumulative" budget.

The `latency_drift_warning` per-cohort threshold (M6.1.3-published CI half-width at `chat_stream c=1 × max_tokens=10`) is read from M6.1.3's published JSON via the `--m6_2-m6-1-3-baseline` path (FR-013, default `docs/benchmarks/m6_1_3-attribution-closure.json`). The exact field path inside the M6.1.3 JSON is `per_cell["chat_stream_c1"]["per_cohort"][cohort_name]["max_tokens=10"]["wall_p50_ms_ci_half_width"]` (or equivalent in the M6.1.3 schema; the data-model.md captures the exact path).

**Alternatives considered**:
- Run the anchor block at every 2h mark — REJECTED; doubles the cumulative overhead without proportional drift-detection benefit (the 4h cadence catches ≥ 4h-period drift; 2h-period drift is rare and already partially mitigated by FR-030's cohort-innermost interleaving within each `(cell, max_tokens)` block).
- Run a larger anchor block (e.g., n=50) — REJECTED; the n=20 anchor is already sensitive enough (M6.1.3's CI half-width at chat_stream c=1 × max_tokens=10 is well-bounded; spread > CI half-width is detectable with n=20).
- Anchor at multiple cells (e.g., chat_stream × c=1 × {10, 50} or both embed and chat_stream) — REJECTED; the 4h cadence already adds ~5-10 min cumulative overhead; doubling the cell coverage doubles the overhead without meaningfully improving detection (the chat_stream c=1 anchor is the highest-network-sensitivity cell; if it doesn't drift, the others aren't expected to either).

### R-4 — Per-block UTC timestamp capture (FR-032)

**Decision**: The sweep orchestrator captures `block_start_utc = datetime.now(UTC).isoformat()` immediately before entering the per-block RPC dispatch loop and `block_end_utc = datetime.now(UTC).isoformat()` immediately after the loop completes (including any in-window retry per FR-033). The timestamps are stored on the per-(cell, cohort, max_tokens) row of the latency budget table. The orchestrator ALSO accumulates the full iteration sequence as an ordered list of `(cell, max_tokens, cohort, block_start_utc, block_end_utc)` tuples; this list is consumed by the `iteration_discipline_verified` post-hoc check (FR-032) and by the "Sweep wall-clock timeline" reporter subsection.

**Rationale**: The decision is one-of-a-kind per block, not per-RPC — per-RPC timestamps are higher granularity than needed for the time-of-day attribution purpose. The post-hoc machine check is straightforward: group the iteration sequence by `(cell, max_tokens)` tuple and verify each group's 4 cohort blocks are contiguous (no other tuple's blocks fall between them, modulo the anchor re-anchor blocks and the network_paths probe — which are accounted for as known interruptions).

The ISO-8601 string format is chosen over Unix timestamp seconds because (a) human-readable in the JSON artifact, (b) timezone-explicit (UTC suffix), (c) sortable lexicographically without numeric conversion, (d) parseable by every artifact consumer.

**Alternatives considered**:
- Capture timestamps inside the per-RPC inner loop — REJECTED; per-RPC granularity is higher than needed and would inflate the artifact JSON size by 144 × n × 2 timestamps (~144 × 100 × 2 × 30 bytes ≈ 1 MB of timestamp metadata in publish mode).
- Use Unix timestamp seconds — REJECTED; ISO-8601 is more readable + sortable + timezone-explicit; the storage cost difference is negligible.
- Capture wall-clock duration only (no start/end timestamps) — REJECTED; the FR-030 discipline check requires knowing when each block started AND ended to verify contiguity across cohorts at the same `(cell, max_tokens)` tuple. Duration alone doesn't say WHEN.

### R-5 — In-window retry policy implementation (FR-033)

**Decision**: The per-block dispatch loop is wrapped in a try/except that catches the transient-error set `(grpc.RpcError [UNAVAILABLE / DEADLINE_EXCEEDED], asyncio.TimeoutError, httpx.RequestError, single-RPC-OOM-from-engine)`. On first-attempt failure, the loop retries ONCE — re-executing the entire per-cohort block at the current `(cell, max_tokens)` tuple within the same `(cell, max_tokens)` time window (i.e., before the orchestrator advances to the next tuple). On retry success, the row is marked `retry_attempted = true` and `wall_p50_ms` reflects the retry's measurements. On retry failure, the row is marked `failed_<reason>` per FR-029 with `retry_attempted = true` (both attempts failed), and the orchestrator advances to the next cohort within the same tuple.

End-of-sweep retries are FORBIDDEN: there is no second pass over failed blocks at the end of the sweep. The orchestrator's main iteration is the only retry opportunity — after the `(cell, max_tokens)` tuple closes, failed blocks are permanently `failed_<reason>`.

**Rationale**: The FR-033 contract is "in-window retry once, no after-the-fact retries". The transient-error set is conservatively scoped to known-transient conditions (network-level errors and dispatch timeouts and single-RPC OOM); other error types (e.g., gRPC INVALID_ARGUMENT, AUTHENTICATION_FAILED) are NOT retried — they indicate a structural failure that retry wouldn't fix.

The single-RPC OOM case (where the engine returns an OOM-like error for one RPC but doesn't crash the engine — rare, but possible at `c=8 × max_tokens=2048`) is included in the retry set because the engine has shown ability to recover from transient memory pressure at the next RPC. If the retry also fails, the row is `failed_oom` and the FR-029 failure-summary tally fires.

**Alternatives considered**:
- Retry twice (or N > 1 times) — REJECTED; spec FR-033 pins retry count at exactly 1. Multiple retries would extend the in-window dispatch time and risk slipping into the next 4h-mark cadence boundary.
- End-of-sweep retry pass for failed blocks — REJECTED at spec round-4 Q5 (Option C); the retry would run in a different time-of-day window than its 3 sibling cohorts at the same tuple, violating FR-030 cohort-innermost discipline. The failure-summary tally per FR-029 is the operator's signal to rerun the entire sweep if data completeness is critical.
- No retries at all (first failure is final) — REJECTED at spec round-4 Q5 (Option B); transient gRPC errors are common enough during multi-day Modal sweeps that no-retry would inflate the failed-cell count unnecessarily.

### R-6 — Symmetric mean-in-CI crossover rule implementation (spec round-1 Q3)

**Decision**: The `m6_2_crossover.compute_per_cell_crossover(...)` function implements the symmetric mean-in-CI rule (spec round-1 Q3) as follows. For each measurement cell:

1. Read the M6.1.3 base verdict from the loaded `m6_1_3_base_verdicts` dict. If the verdict is `inconclusive_high_variance` or any `multi_factor_*` compound label, return `M6_2CrossoverThreshold(crossover_max_tokens=None, crossover_evidence="base verdict was already inconclusive at the M6.1.3 baseline", m6_1_3_base_verdict=base_verdict)`.
2. Identify the M6.1.3-winning cohort (the cohort with the lowest `wall_p50_ms` at M6.1.3's measurement; equivalently, the cohort the M6.1.3 verdict identified as "wins"). Identify the second-place cohort (the one with the lowest `wall_p50_ms` AFTER the winner).
3. Iterate the M6.2 axis points in ascending order `(10, 50, 256, 512, 1024, 2048)`. For each axis point:
   - Compute `winner_p50 ± winner_ci_half = [winner_p50 - 1.96 × winner_stderr, winner_p50 + 1.96 × winner_stderr]`.
   - Compute `second_p50 ± second_ci_half`.
   - Evaluate the symmetric mean-in-CI predicate: `(winner_p50 ∈ [second_p50 ± second_ci_half]) OR (second_p50 ∈ [winner_p50 ± winner_ci_half])`.
4. Return the smallest `max_tokens` axis point at which the predicate fires. If the predicate fires at `max_tokens=10` (i.e., the cohort pair already overlaps at the M6.1.3 baseline), return `crossover_max_tokens=10` with `crossover_evidence="M6.1.3 verdict not robust to M6.2 resampling"` per US2 #3.
5. If the predicate never fires across the entire axis, return `crossover_max_tokens=None` (which renders in markdown as `survives_to_2048` per US2 acceptance #4 phrasing — interpreted by the reporter, not by the compute function).

For validate-mode, the function operates on the 3-point axis subset `{10, 50, 2048}` and returns a coarse 4-value vocabulary (`10`, `50`, `2048`, `survives_to_2048`, or `None`) per FR-016.

**Rationale**: The rule is geometric (no stats library), symmetric (either direction satisfies), and unambiguous (no "which percentage of overlap?" interpretation). The CI half-width definition (`1.96 × stderr`, 95% normal approximation) matches M6.1.x's published CIs.

**Alternatives considered**:
- CI-overlap ≥ 50% (linear-fraction-of-shorter-CI) — REJECTED at spec round-1 Q3; introduces a "which 50%?" ambiguity (50% of the shorter CI? 50% of the union? 50% of one cohort's CI?) that the symmetric mean-in-CI rule sidesteps.
- Welch's t-test p > 0.05 — REJECTED at spec round-1 Q3; requires a stats library dependency and the p-value threshold has its own arbitrary cutoff debate.
- Asymmetric mean-in-CI (only winner's mean must fall in second-place's CI) — REJECTED at spec round-1 Q3; the symmetric rule is more conservative and matches operator intuition ("the means are inside each other's error bars").

### R-7 — Wall-clock-ratio KV-pressure inference (FR-017a)

**Decision**: The `m6_2_crossover.compute_kv_pressure_inference(...)` function computes, for each cohort × cell-type ∈ {chat_stream, embed}:

```
R = wall_p50_ms(c=8, max_tokens=2048) / wall_p50_ms(c=8, max_tokens=1024)
```

The 2.2 threshold is a spec-level literal (FR-017a + spec round-3 Q3). If `R > 2.2`, the regime is classified as `kv_pressure_inferred_<cell_type>` (e.g., `kv_pressure_inferred_chat_stream`). Otherwise, classified as `kv_pressure_not_observable`. The `M6_2KVPressureObservation` entity carries both the computed `R` (field `wall_clock_ratio_c8_2048_over_1024`) and the label (field `wall_clock_inference_label`).

The engine-side `kv_cache_used_fraction_peak` field is best-effort: extracted from per-RPC trailing metadata if present, `None` otherwise. The reporter's narrative cites both signals; a discrepancy (e.g., engine field shows high pressure but R ≤ 2.2) is surfaced as a one-line note in the narrative.

**Rationale**: Engine generation cost at high `max_tokens` should scale ~linearly with the cap; R ≈ 2.0 is the expected baseline (max_tokens=2048 generates twice the tokens as max_tokens=1024). The 2.2 threshold gives a 10% margin above linear — KV-cache pressure manifests as super-linear scaling because the per-token engine cost grows with the KV-cache occupancy (eviction, recomputation, scheduler pressure). The 10% margin is tight enough to detect onset of pressure without false-firing on benign per-token cost variance.

The wall-clock-ratio inference is REQUIRED (vs the engine field which is best-effort) because the inference is computed unconditionally from existing latency budget measurements — no new instrumentation, no engine-side dependency.

**Alternatives considered**:
- Inter-token-latency dispersion proxy (TPOT stddev / mean) — REJECTED at spec round-3 Q3; would require per-RPC TPOT capture (currently aggregated only at the cell level); adds complexity without proportional inference improvement.
- Engine-log scraping — REJECTED at spec round-3 Q3; brittle (log format changes break the parser); the engine field via gRPC trailing metadata is the structured channel if vLLM exposes it.
- Best-effort narrative only (no machine-checkable label) — REJECTED at spec round-3 Q3; the regime needs a categorical signal for M8's KV-budget sizing decision; narrative-only would force M8 spec authors to re-derive the inference manually.

### R-8 — Modal preemption recovery + sweep resume at the 20-48h budget

**Decision**: M6.2 inherits the M6.1.3 FR-028 preemption-recurrence threshold (pinned at 2). At the 20-48h M6.2 wall-clock budget, mid-sweep Modal preemption is meaningfully more likely than for any prior M6.x sweep. The orchestrator's auto-resume / partial-artifact-merge handler MUST tolerate one transient preemption per cohort without sweep abort; a second preemption (within the same multi-cohort sequence) aborts.

**Resume mechanism**: on preemption recovery, the orchestrator re-establishes the Modal tunnel + deploy handshake (inherited from M5.2's preemption-aware URL refresh), then resumes the main iteration at the `(cell, max_tokens, cohort)` block where the preemption occurred. The preemption interrupts mid-block; resume re-runs the entire interrupted block (n RPCs) within the SAME `(cell, max_tokens)` tuple's time window — which means the cohort-innermost discipline (FR-030) is preserved if the resume happens promptly. If the resume happens > some threshold (e.g., > 30 minutes after the original block started, indicating the resume drifted into a different time-of-day window), the interrupted block's siblings may already be complete; in that case, the orchestrator marks the interrupted block as `failed_modal_preemption_resume_drift` per FR-029 and the FR-030 cohort comparison for that tuple loses one cohort. This edge case is rare but spec-acknowledged.

Per-block UTC timestamps (FR-032) capture the actual resume time, making the time-of-day drift visible in the artifact; `iteration_discipline_verified` may fire false (indicating the discipline was broken at the resumed tuple) and the operator can inspect the wall-clock timeline subsection to see exactly which block drifted.

**Rationale**: M6.1.3's preemption-recurrence threshold (2) was pinned against the ~75-minute M6.1.3 sweep. M6.2's longer wall-clock makes the same threshold less conservative (in absolute preemption probability), but the methodological logic is identical: one transient recovery acceptable, second failure aborts. Tightening the threshold would risk false-aborts; relaxing it would mask repeated infrastructure issues.

**Alternatives considered**:
- Tighten preemption-recurrence threshold to 1 (no transient recovery) — REJECTED; would risk false-aborts at the 20-48h budget where transient preemptions are more likely.
- Relax the threshold to 3 or more — REJECTED; would mask repeated infrastructure issues that should abort the sweep.
- Add a `resume_drift_threshold` knob (e.g., abort the cohort if resume happens > 30 min later) — REJECTED as out-of-scope for M6.2; the spec-level decision is "FR-030 discipline is preserved if the resume is prompt; if not, mark the block as failed and continue". A drift-threshold knob would be a future-milestone refinement if observed drift is significant.

## Phase 0 closure

All 8 research items are resolved. No NEEDS CLARIFICATION markers remain. The Technical Context in [`plan.md`](./plan.md) is complete.

Proceed to Phase 1: write [`data-model.md`](./data-model.md), [`contracts/cli.md`](./contracts/cli.md), [`contracts/artifact-schema.md`](./contracts/artifact-schema.md), [`contracts/iteration-order.md`](./contracts/iteration-order.md), [`contracts/wire-vocabulary.md`](./contracts/wire-vocabulary.md), [`quickstart.md`](./quickstart.md), and update `CLAUDE.md`.
