# M4 Research — Time-Axis Channel & Schema Tuning

This document collects the methodology and implementation research that backs the M4 plan. Each item resolves a design choice that the spec's functional requirements imply but do not pin down to a specific mechanism. Citations follow the M2 ground-truth workflow (cloned vLLM at `~/.graphify/repos/vllm-project/vllm/`, cloned grpcio at `~/.graphify/repos/grpc/grpc/src/python/grpcio/`, cross-repo paths via `cross-repo.json`).

## R-1 — No-pacing mode mechanics

**Decision**: Add `pace_tokens: bool = True` to `MockEngineConfig` (defined in `tools/benchmark/src/vllm_grpc_bench/mock_engine.py`). When `True`, retain the existing `await asyncio.sleep(1.0 / tokens_per_second)` between emitted tokens; when `False`, skip the sleep entirely and emit tokens as fast as the asyncio event loop dispatches them. `tokens_per_second` validation is relaxed only when `pace_tokens=False` (it then has no effect, so any positive number or even the existing default is accepted).

**Rationale**: An explicit boolean flag makes the mode self-documenting in serialized run metadata (it appears as `"pacing_mode": "paced"` or `"pacing_mode": "no_pacing"` in the run JSON, supporting FR-007 "report labels the no-pacing mode used"). The alternative — overloading `tokens_per_second=0` as a sentinel — is implicit and would require either weakening the existing `> 0` validation everywhere or adding a separate guard. The explicit flag also keeps M3's default behavior unchanged (the M3 default config is still `pace_tokens=True, tokens_per_second=20.0`), which Constitution III requires: M3 reproducibility cannot be broken by an M4 default change.

**Alternatives considered**:
- `tokens_per_second=0` sentinel: rejected per above (implicit; conflicts with existing `> 0` validation in `mock_engine.py:76–77`).
- A separate "mode" enum (`Paced` / `Unpaced`): rejected as over-engineered for two states.
- Killing pacing entirely (always emit as fast as possible): rejected because M3's bytes report and M3 reproducibility depend on the paced default.

**Citations**:
- Existing pacing mechanism: `tools/benchmark/src/vllm_grpc_bench/mock_engine.py:70` (the `tokens_per_second` field) and line 179 (the `await asyncio.sleep(interval)` in the streaming loop).
- vLLM's streaming pattern (for type-shape parity): `~/.graphify/repos/vllm-project/vllm/vllm/v1/engine/async_llm.py` `AsyncLLM.generate` (no artificial pacing in the real engine — token emission is bounded by GPU compute).

## R-2 — Shared-baseline orchestration

**Decision**: Add `tools/benchmark/src/vllm_grpc_bench/m4_sweep.py` as a sibling to `m3_sweep.py`. The new orchestrator measures M1_BASELINE cohorts once at the start of the run (one per path: `embed`, `chat_stream`), records each cohort's id + metadata + per-sample timings + 95% CI, then iterates the channel-axis matrix passing `baseline_cohort_id` instead of measuring a fresh baseline per axis. Internally, the per-cell evaluation reuses extracted helpers from `m3_sweep.py` (CI estimation, predecessor pairing primitives) so the recommendation logic does not diverge between M3 and M4.

**Rationale**: A sibling module keeps M3's `m3_sweep.py` runnable for bytes-report regeneration (Constitution III, spec FR-009 traceability). Refactoring M3's module in place to make baseline-measurement strategy injectable would risk regressing M3's published numbers. A sibling also makes the M4 entry point cleanly distinguishable in the CLI (`--m4` invokes `m4_sweep.run_m4_sweep`; `--m3` continues to invoke `m3_sweep.run_m3_sweep`) and gives the new shared-baseline code a clear owner.

**Alternatives considered**:
- Refactor `m3_sweep.py` in place with a `baseline_strategy: BaselinePerAxis | BaselineShared` parameter: rejected on Constitution III grounds — risk to M3 reproducibility outweighs DRY benefit, and the two strategies have different downstream report-shape implications.
- Make M4 a `--reanalyze` flavor of `m3_sweep.py`: rejected — M4 needs new measurement, not just re-analysis. M3's `--reanalyze` path is preserved unchanged.

**Citations**:
- M3's per-axis fresh baseline pattern: `tools/benchmark/src/vllm_grpc_bench/m3_sweep.py:374` (where `time_to_first_token_seconds` is harvested) and the surrounding cohort-construction loop.
- M3's per-cell CI estimator (`ci.py`, 72 lines): reusable as-is.

## R-3 — Per-path frozen-channel baseline composition

**Decision**: For each path (`chat_stream`, `embed`), build the frozen-channel baseline by combining that path's per-axis winners from the US2 channel sweep at the canonical width (hidden_size 4096) into a single `ChannelConfig`. Where a path has no `recommend` verdict on a given axis, the frozen baseline keeps that axis at the M3-default value. The combined config is then measured as its own n ≥ 100 cohort and recorded in the run JSON under a new top-level field `frozen_channel_baselines: { chat_stream: <cohort>, embed: <cohort> }`. Schema candidates pair with the cohort matching their path (per spec FR-011).

**Rationale**: Per-path matches how M3 reports per-path verdicts and how the production deployment shape works (chat_stream and embed share a process but are configured per-RPC). Measuring the combined config — rather than algebraically combining per-axis deltas — is the only honest way to attribute a schema-candidate delta against a single coherent measured baseline; channel axes can interact in non-additive ways. Falling back to M3 defaults on no-winner axes is the principled choice: the spec's "winner" language refers to recommended overrides, not mandates, so absence of a winner means "M3 defaults are acceptable for that axis."

**Alternatives considered**:
- One global super-config combining all per-axis winners across both paths: rejected per /speckit-clarify Q2 — chat_stream and embed may have different winners, and a single super-config attributes deltas against a configuration the production system never runs as a unit.
- Per-axis pairing (each schema candidate compared to whichever single-axis winner is most relevant): rejected per /speckit-clarify Q2 — makes "schema candidate beats baseline" claims hard to interpret.
- Algebraically combining per-axis deltas: rejected — channel options can interact (compression+max_message_size, keepalive+http2_framing); only an empirical measurement of the combined config is defensible.

## R-4 — Borderline-expand trigger and mechanic

**Decision**: After computing a candidate cohort's 95% CI, classify the cohort as "borderline" iff the candidate's CI overlaps the comparison baseline's CI (specifically: candidate's CI low ≤ baseline's CI high AND candidate's CI high ≥ baseline's CI low). Borderline cohorts are immediately re-measured at n ≥ 250 (the existing samples are *replaced*, not appended, to avoid mixing run-conditions across n=100 and n=250 batches that may have different system-noise profiles). The expansion decision and the n=100→n=250 transition are recorded as an `ExpansionRecord` per cohort in the run JSON.

**Rationale**: The CI-overlap rule is the formal version of "CI touches" from /speckit-clarify Q3 — it is symmetric (works for minimizing and maximizing metrics), deterministic (no judgment), and matches the verdict rule from FR-008 ("strictly clears" is the negation of "overlaps"). Replacing rather than appending samples addresses cross-batch system-noise variance: appending 150 samples taken five minutes after the first 100 risks mixing two different system-load profiles into one cohort, defeating the purpose of expansion. n ≥ 250 tightens CIs by ~58% relative to n ≥ 100 (CI width ∝ 1/√n), which is sufficient for the typical 3–5% TTFT effect sizes M4 expects to detect.

**Alternatives considered**:
- Append-then-re-test: rejected for cross-batch noise reasons above.
- Larger expansion (n ≥ 500): rejected as runtime-prohibitive — doubles the per-borderline-cell budget vs n=250 for only a 1.4× CI tightening.
- Power-analysis-driven sizing per cohort: rejected per /speckit-clarify Q3 — adds a power-analysis step the harness does not have today; the cascade (n=100 → n=250) targets statistical power exactly where it pays off (borderline cells) without that complexity.

## R-5 — `client_bound` cohort detection (FR-004)

**Decision**: After enabling no-pacing, a cohort is tagged `client_bound` when its measured per-RPC wall-clock contains a substantial component that is provably not transport+serialization. The harness uses the simplest defensible proxy: it measures the M1_BASELINE cohort's per-RPC wall-clock at no-pacing, treats the M1_BASELINE measurement as the lower bound on per-RPC orchestrator overhead, and tags any candidate cohort `client_bound` if `(candidate.wall_clock_mean - baseline.wall_clock_mean)` is smaller than the cohort's within-baseline standard deviation. Such cohorts are emitted in the JSON (Constitution V — no metric omitted) but are excluded from `recommend` tallies.

**Rationale**: The harness has no instrumentation to attribute per-RPC time to transport vs. serialization vs. orchestrator overhead at sub-millisecond resolution. The simpler invariant — "if the candidate's mean delta against the baseline is smaller than the baseline's own jitter, the transport contribution is below the noise floor" — is the strongest claim the existing data supports without adding tracing. This is conservative (it under-classifies cohorts as `client_bound` rather than over-classifying, which would suppress real wins).

**Alternatives considered**:
- Add per-stage time breakdown via grpcio interceptors / Python tracing: rejected — significant new instrumentation surface; matches the spirit of the spec but is over-engineered for M4's empirical-question framing.
- Use a fixed absolute threshold (e.g., 500 µs): rejected — system-dependent; would need re-calibration per host and would fail SC-005 (single-host reproducibility).
- Skip detection entirely and trust the verdict CI rule: rejected per FR-004 — the spec explicitly requires this guard so a transport-axis recommendation cannot ride on client-side noise.

**Citations**:
- grpcio's Python `Channel`/`UnaryUnaryMultiCallable` per-call timing surface: `~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py` (no per-stage breakdown is exposed at the public Python API; instrumentation would have to live in the harness).

## R-6 — Loopback caveat trigger rule (FR-010)

**Decision**: An axis carries the loopback caveat note in the M4 report iff (a) the harness ran with `localhost`/`127.0.0.1` as the server bind address (always true in single-host M4 runs) AND (b) the axis is in the deterministic "physically-loopback-dependent" set: `{keepalive, http2_framing}`. The set is determined by mechanism: keepalive timeouts and HTTP/2 framing parameters affect behavior over RTT-bounded network paths; on loopback the kernel collapses RTT to ~0 and these parameters cannot manifest. `max_message_size` and `compression` are excluded because their effects (header parsing limits, payload-byte reduction) operate independent of network distance.

**Rationale**: A deterministic set is more honest than judgment-based classification — the report can be regenerated and produces the same caveats. Driving the set off the *physical mechanism* (does the parameter affect over-RTT behavior?) is more defensible than driving it off observed deltas (which would conflate "loopback-masked" with "no real effect").

**Alternatives considered**:
- Per-axis judgment by the operator: rejected — judgment doesn't reproduce.
- Cross-host re-measurement to confirm the masking: explicitly listed as **out of scope for M4** (spec Assumptions). The caveat note documents the gap and names the future-milestone trigger to upgrade the verdict.
- Detection by observed delta (e.g., "if the four configurations on this axis are all within 2% of each other, attach the caveat"): rejected — confuses physical cause with observed effect.

**Citations**:
- gRPC keepalive RTT-dependence: see grpcio's keepalive option semantics in `~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/__init__.py` channel-options docstrings; HTTP/2 framing semantics in HTTP/2 RFC 7540 §6 (loopback collapses round-trip-bounded behaviors).

## R-7 — M4 JSON schema delta vs. M3's `m3-channel-tuning-time.json`

**Decision** (per /speckit-clarify Q1): M4's JSON is a **strict superset** of M3's `m3-channel-tuning-time.json` schema. M3's existing top-level fields (`mode`, `axes`, `widths`, `paths`, `iterations_per_cell`, `seed`, `p2_revision`, `frozen_channel`, `cohorts[]`) and existing per-cohort fields (`cell_id`, `path`, `hidden_size`, `config_name`, `config_axis`, `corpus_subset`, `iterations`, `n_successful`, `measurable`, `off_canonical`, `bytes`, `time_seconds`) are preserved with identical semantics. M4 adds:

| New top-level field | Type | Purpose |
|---------------------|------|---------|
| `pacing_mode` | `"paced" \| "no_pacing"` | Records FR-001 mode used. M3 readers ignore. |
| `shared_baseline_cohort_ids` | `{ chat_stream: str, embed: str }` | Pointer into `cohorts[]`. Identifies the shared M1_BASELINE per path. |
| `frozen_channel_baselines` | `{ chat_stream: <cohort_summary>, embed: <cohort_summary> }` | Per-path frozen baselines from R-3. |
| `supersedes` | `[<supersession_entry>]` | M3 cell → M4 verdict mapping (FR-009). |
| `candidate_sizing_policy` | `{ default_n: 100, expand_n: 250, expand_rule: "ci_overlap" }` | Documents FR-002 / R-4 policy. |
| `loopback_caveat_axes` | `[string]` | Subset of `axes` with the loopback caveat (R-6). |

Per-cohort additions:

| New per-cohort field | Type | Purpose |
|----------------------|------|---------|
| `is_baseline` | `bool` | True for shared M1_BASELINE and frozen-channel baseline cohorts. |
| `baseline_role` | `"m1_shared" \| "frozen_channel" \| null` | Distinguishes the two baseline roles. |
| `expansion_record` | `<ExpansionRecord> \| null` | Records borderline-expand decision (R-4). |
| `client_bound` | `bool` | True iff the cohort failed the FR-004 / R-5 detection. |
| `time_to_first_token_seconds` | `{ mean, ci_low, ci_high } \| null` | Promoted to first-class for chat_stream cohorts (FR-003). M3 had per-sample TTFT; M4 publishes the cohort-level summary. |

The M4 `mode` field uses a new value `"m4-time-axis-tuning"` (M3 used `"p1-time-reanalysis"`). M3's `noise_bounded` verdict literal is **never emitted** in M4 reports (FR-007).

**Rationale**: Strict superset means any M3 reader keeps working unchanged on M4 files; new fields are ignored by M3 code and consumed by M4-aware code. This matches the project's "M3 stays in place as the bytes baseline for traceability" ethos.

**Alternatives considered**: see /speckit-clarify Q1 for the option-A (clean break) and option-C (independent versioning) rationale.

## R-8 — Schema candidate sequencing (FR-012 (a)/(b)/(c))

**Decision**: Each schema candidate is measured **independently** against its per-path frozen-channel baseline. Candidates do not stack: candidate (b) is not measured with candidate (a) frozen in. If two or more candidates win independently at hidden_size 4096, a follow-up combined-candidate cohort is measured (still within M4) so the report can claim either (i) the wins are additive or (ii) they interact. If only one candidate wins, no combined cohort is needed.

**Rationale**: Independent measurement gives each candidate a clean attribution to its own per-cohort delta, and matches FR-014's "each candidate ... overlapping CIs ... recorded as negative result" framing (which presupposes per-candidate verdicts). The follow-up combined cohort is the minimum work needed to answer the natural question "do the wins compose?" without spawning a multi-candidate combinatorial sweep.

**Alternatives considered**:
- Cumulative measurement (each candidate measured with prior winners frozen in): rejected — order-dependent (candidate (a) winning then (b) measured-with-(a) is a different question from (b) winning then (a) measured-with-(b)) and harder to attribute.
- Full combinatorial sweep (all 2^3 = 8 combinations of candidates): rejected as runtime-prohibitive and unmotivated by the spec's per-candidate verdict framing.
- Skip the follow-up combined cohort even when multiple win: rejected — leaves a question the report would naturally raise unanswered.

## R-9 — Schema candidate proto isolation

**Decision**: Candidate `.proto` shapes live in a sibling namespace `proto/vllm_grpc/v1/m4-candidates/`. Three files: `packed_token_ids.proto`, `oneof_flattened_input.proto`, `chunk_granularity.proto`. Each defines the *minimal* candidate variation against the production message — typically a single field-level change — and `make proto` regenerates Python stubs into `packages/gen/vllm_grpc_m4_candidates/`. The bench harness imports these stubs only when measuring the corresponding candidate cohort; production proxy/frontend/client code never imports them.

**Rationale**: Constitution I (Proto-First) requires every wire-format change to start with a `.proto` edit and forbids hand-written equivalents. Isolating candidates in a sibling namespace lets the harness measure each variation while keeping production proto immutable until a candidate is explicitly accepted in a follow-up change (per spec Assumptions: "Adoption is a separate change"). M3's P2 plan used the same sibling-namespace pattern at a finer grain.

**Alternatives considered**:
- Edit production proto directly per candidate, run the cohort, revert: rejected — leaves the workspace in an inconsistent state during measurement and makes simultaneous candidate cohorts impossible.
- Hand-write equivalent Python message classes for candidate measurement: explicitly forbidden by Constitution I.

## R-10 — TTFT promotion path (FR-003)

**Decision**: TTFT is promoted from M3's "re-analysis-only" path to a first-class output of `m4_sweep.build_recommendations`. The recommendation builder emits TTFT as the primary chat_stream metric *and* total wall-clock as a secondary diagnostic in the same cohort record. M3's existing `m3_sweep` re-analysis helpers (the ones that compute TTFT from `time_to_first_token_seconds` per-sample) are extracted into a shared module and consumed unchanged by both M3 (re-analyze) and M4 (primary).

**Rationale**: Sharing the math means the TTFT semantics can't drift between milestones — M3's published TTFT numbers and M4's published TTFT numbers come from the same code path. "Primary metric" status only changes the verdict-driver; it does not redefine what TTFT is.

**Alternatives considered**:
- Compute TTFT differently in M4 (e.g., trim outliers): rejected — would break M3 / M4 comparability and Constitution V "honest measurement" framing (no methodology drift across phases without explicit ADR).
- Drop total wall-clock from chat_stream cells entirely: rejected — total wall-clock is still a useful secondary diagnostic, especially for the no-pacing-mode validation step (acceptance scenario US1.1).

## R-11 — Within-cohort CV: record-and-report, not abort (FR-005)

**Decision**: The harness measures within-cohort CV (stddev/mean on the verdict metric — wall-clock for embed, TTFT for chat_stream) for **every** cohort and writes it on the per-cohort entry of the published JSON+markdown report. The harness never aborts the run on CV overflow; the run always proceeds to completion so that all measurement data is preserved for post-hoc analysis. A configurable warn threshold (`--baseline-cv-warn=<float>`, default `0.05`) governs only (a) a closing warning that names baseline cohorts above the threshold and (b) a `noisy_baseline: true` flag on those cohorts' JSON entries. Verdict adjudication — including whether to discount or re-run — is the report reader's job, informed by the per-cohort CV they can see directly.

**Rationale**: An earlier design (T010 / T017 in tasks.md as originally written) made CV overflow a fatal exit-3 abort with no JSON written. Operating on commodity macOS hosts revealed the structural problem: at sub-millisecond per-RPC wall-clock latencies, run-to-run CV fluctuates between ~3% and ~10% on the same machine even with extended warmup, because OS scheduler quanta (~1 ms) and ambient host load (Slack, Chrome, Spotify) contribute jitter on the same order as the measurement itself. Aborting one cohort throws away the whole sweep's measurement work — including cohorts whose CV would have been fine — and forces operators into a frustrating retry loop with no diagnostic data. Recording the CV inline lets a reader see *which* cohorts were noisy, judge whether to trust their verdicts, and re-run only the affected cohorts in a follow-up. The 5% warn threshold is preserved as the calibration target against M3's cross-batch drift; it just no longer kills the run.

**Alternatives considered**:
- Keep abort behavior, loosen threshold: tried in T051 (`--warmup-n=20 --baseline-cv-max=0.10`); failed at CV=10.93%. Tried `--warmup-n=50 --baseline-cv-max=0.10`; failed at CV=10.45%. The host-noise distribution is wide enough that no fixed cap reliably clears it.
- Add a "low-confidence verdict" literal (`recommend_low_confidence`, `no_winner_low_confidence`): rejected — adds a new verdict literal to the schema and forces the trust judgment into the harness rather than the reader. Per-cohort CV gives the same information without schema growth.
- Compute CV but skip recommendations[] entirely for noisy paths: rejected — the user (T051 operator) explicitly preferred verdicts always be computed, with the noise indicator visible alongside.

## R-12 — Interaction with M3's existing `--reanalyze` path

**Decision**: M3's `vllm_grpc_bench --m3 --reanalyze <existing.json>` path is preserved unchanged. M4's new `--m4` path is independent and does **not** consume `m3-channel-tuning.json` or `m3-channel-tuning-time.json` directly (no re-analysis of M3 data — M4 measures fresh under the redesigned harness). M4 *cites* M3's published time report when it builds the Supersedes M3 table (R-7's `supersedes` field), which is a one-time read of M3's JSON to enumerate the cells M4 needs to verdict.

**Rationale**: M3's reanalyze path is the artifact that closed M3's US3 (the Phase A wall-clock re-analysis that landed 2026-05-10). Touching it risks regression on already-published M3 numbers. M4 reads M3's report only as an enumerate-which-cells-to-supersede driver — it does not re-derive any M3 number.

**Alternatives considered**:
- Build M4 as another re-analyze flavor reading M3's raw per-sample data: rejected — M3's data was collected under paced mode and per-axis fresh baselines; no re-analysis can rescue chat_stream total wall-clock from those conditions. M4 *must* re-measure.

## R-13 — Test surface for M4 harness mechanics

**Decision**: The harness mechanics (no-pacing, shared-baseline, TTFT-first-class, borderline-expand, client_bound detection, loopback-caveat tagging, supersession-table generation) are tested with deterministic small-fixture unit tests at PR time under `tools/benchmark/tests/`. The full M4 sweep (the actual ~4-hour cohort runs) is operator-triggered, not part of CI's runtime budget. CI verifies the *plumbing* is correct; the operator drives the actual measurement and commits the resulting `docs/benchmarks/m4-time-axis-tuning.{md,json}`.

**Rationale**: Matches the M3 pattern (M3 P1 sweep was operator-run; M3 harness mechanics were CI-tested). Constitution IV requires the gate to be CI; the gate is "harness produces correct shape under fixtures," not "the four-hour sweep ran on the merge bot."

**Alternatives considered**:
- Run the full sweep in CI: rejected — runtime prohibitive on shared CI runners; flakiness from CI-host noise would mask real signals.
- Sample-only fixture (50 iterations): rejected — would not exercise the borderline-expand path that triggers at n=100.
