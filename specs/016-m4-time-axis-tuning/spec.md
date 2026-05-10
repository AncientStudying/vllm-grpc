# Feature Specification: M4 — Time-Axis Channel & Schema Tuning

**Feature Branch**: `016-m4-time-axis-tuning`
**Created**: 2026-05-10
**Status**: Draft
**Input**: User description: "M4 — Time-Axis Channel & Schema Tuning from PLAN.md"

## Clarifications

### Session 2026-05-10

- Q: How does the M4 JSON report relate to M3's existing `m3-channel-tuning-time.json` schema? → A: Strict superset — additive only (new fields permitted; no renames or removals). M3 readers continue to work unchanged on M4 files.
- Q: How is the "frozen-channel baseline" for US3 (schema candidates) constructed? → A: Per-path frozen baseline — one cohort per path (chat_stream, embed), each combining its path's per-axis winners from US2 at the canonical width; each schema candidate pairs with the cohort matching its path.
- Q: What sample size do candidate cohorts use (channel sweep and schema candidates)? → A: Default n ≥ 100 (matching the baseline and M3 convention), with a borderline-expand rule: any candidate cohort whose 95% CI touches the comparison baseline's 95% CI is re-measured at n ≥ 250 before the verdict is finalized. The borderline-expand step is recorded in the run output.

## User Scenarios & Testing *(mandatory)*

M4 is the milestone that re-frames M3's measurements around wall-clock time as a first-class success metric (TTFT for streaming, total per-RPC wall-clock for embed) and runs the protobuf message-shape candidates that were deferred from M3. The audience is the project's maintainers and reviewers — researchers comparing channel-level and schema-level tuning options before committing them to the production proto and channel configuration.

M3 produced defensible bytes-axis verdicts but left the chat_stream wall-clock cells marked `noise_bounded` because (a) the mock engine's deterministic per-token pacing dominates total streaming wall-clock and (b) per-axis fresh M1_BASELINE cohorts drifted ~10–15% across batches on macOS, exceeding the size of any expected channel-tuning win. M4 fixes both upstream causes, then re-runs the four-axis channel sweep and the deferred schema candidates under the corrected methodology so every cell M3 left `noise_bounded` carries a real time verdict.

### User Story 1 — Redesigned Harness Produces Defensible Time Verdicts (Priority: P1)

A maintainer needs to evaluate channel-level or schema-level tuning candidates on wall-clock time without the two noise sources that defeated M3: mock-engine pacing dilution and cross-batch baseline drift. The harness must offer a no-pacing mode for the mock engine, a shared-baseline mode for the orchestrator, and TTFT as a first-class verdict metric for streaming cells.

**Why this priority**: Phase B is the *prerequisite* axis named in `docs/PLAN.md` — without it, nothing else in M4 produces a defensible verdict. This is the single bottleneck that gates the entire milestone, and shipping just this user story already delivers value: any future milestone (M5 corpus expansion, M6 model expansion) inherits the same redesigned harness and avoids re-doing the methodology work.

**Independent Test**: A reviewer runs a small end-to-end sweep against the redesigned harness with `no-pacing` and `shared-baseline` enabled and confirms (a) chat_stream total wall-clock for the M1_BASELINE cohort is materially lower than under M3's paced mode (mock pacing no longer dominates), (b) only one M1_BASELINE cohort is measured for the entire run rather than one per axis, (c) the chat_stream verdict in the recommendation builder's output is computed on TTFT and labeled as such, and (d) re-running the same sweep twice on the same host produces baseline cohorts whose 95% CIs overlap (cross-batch drift no longer exceeds expected effect sizes).

**Acceptance Scenarios**:

1. **Given** the mock engine running in its M3 default paced mode, **When** the same engine is invoked with no-pacing enabled, **Then** the chat_stream cohort's measured total wall-clock per RPC drops from being pacing-dominated (correlated with `tokens_per_second × token_count`) to being transport-and-serialization-dominated (correlated with payload size and channel configuration), and the report labels the no-pacing mode used.
2. **Given** a four-axis channel sweep configuration, **When** the orchestrator runs in shared-baseline mode, **Then** exactly one M1_BASELINE cohort (n ≥ 100 samples per measured path) is recorded for the entire run and is referenced as the comparison baseline for every axis × width × path cell, rather than each axis re-measuring its own baseline.
3. **Given** chat_stream cohorts produced under the redesigned harness, **When** the recommendation builder emits verdicts, **Then** each chat_stream cell carries a TTFT-based primary verdict (with the underlying `time_to_first_token_seconds` per-sample distribution), total streaming wall-clock as a secondary diagnostic, and the report explicitly names which metric drove the verdict.
4. **Given** two consecutive end-to-end shared-baseline runs on the same host, **When** their baseline cohorts are compared, **Then** the per-cohort 95% CI bounds overlap on the time metric, demonstrating cross-batch drift is small enough to support time-axis verdicts (no `noise_bounded` outcome attributable to baseline drift).

---

### User Story 2 — Definitive Channel Sweep Closes M3's Noise-Bounded Cells (Priority: P2)

A maintainer needs the channel-level question — "which `max_message_size`, keepalive, compression, and HTTP/2 framing settings reduce wall-clock time for an LLM-style payload?" — answered with a real verdict at hidden_size 2048 / 4096 / 8192 for both the embed and chat_stream paths. Every cell that M3's report left `noise_bounded` on the time metric must carry a definitive verdict in M4's report.

**Why this priority**: This is the headline payoff of the milestone — it is what M3's published report explicitly names as the M4 deliverable. It is meaningful only after US1 ships (US1 is the methodology; US2 is the result), but it is independently testable in the sense that a reader of `docs/benchmarks/m4-time-axis-tuning.md` can confirm M4 verdicts exist for every cell M3 left noise-bounded without inspecting the harness internals.

**Independent Test**: A reviewer reads `docs/benchmarks/m4-time-axis-tuning.md` (a new sibling to M3's bytes report) and confirms (a) every chat_stream and embed cell that M3 marked `noise_bounded` carries a definitive M4 verdict (`recommend` or `no_winner`), (b) every `recommend` verdict cites a 95% CI that strictly clears the shared-baseline's 95% CI under the same minimization or maximization rule M3 used for bytes, (c) the M4 report names which specific M3 cells it supersedes and why, and (d) cells where loopback transport masks the effect carry an honest `no_winner` plus an explicit note about whether cross-host re-measurement is warranted.

**Acceptance Scenarios**:

1. **Given** M3's published time report listing `N` cells as `noise_bounded` (chat_stream total wall-clock under all four axes at all three widths), **When** the M4 report is published, **Then** all `N` cells carry a non-`noise_bounded` verdict and the M4 report contains a "Supersedes M3" table mapping M3 cell → M4 verdict → one-line rationale.
2. **Given** the shared-baseline cohort and a candidate cohort for a given axis × width × path cell, **When** the recommendation builder evaluates the time-metric verdict, **Then** `recommend` is emitted only when the candidate's 95% CI strictly clears the shared-baseline's 95% CI for the metric direction (lower for minimizing metrics like time, higher for maximizing metrics), and `no_winner` otherwise.
3. **Given** a channel axis whose effect is plausibly masked by loopback transport (typically keepalive or HTTP/2 framing on a local socket), **When** the M4 verdict for that axis is `no_winner` because the deltas are within shared-baseline noise, **Then** the report records an explicit "loopback caveat" note for that axis, names whether a cross-host re-measurement was attempted in this milestone, and lists what cohort sizes / host topology would be needed to upgrade the verdict in a future milestone.
4. **Given** the channel sweep results at hidden_size 2048, 4096, and 8192, **When** a reader looks for a single recommendation per axis, **Then** the report names a recommended setting per axis (or an honest `no_winner`) at each width and shows the supporting CI-bounded delta on the time metric, with the bytes-axis verdict cross-linked to M3 for traceability.

---

### User Story 3 — Schema Candidates Measured Against the New Baseline (Priority: P3)

A maintainer needs the protobuf message-shape candidates that were deferred from M3 — packed scalars on chat completion's token-id field, `oneof` flattening on the input union, and alternative streaming chunk granularity — measured under the redesigned harness against the new frozen-channel baseline so that recommendations about the wire schema are made on the same evidence basis as the channel-level recommendations.

**Why this priority**: Schema candidates were deferred from M3 specifically because their effects most plausibly manifest as TTFT or wall-clock wins, and TTFT becomes a defensible verdict metric only under US1's harness changes. They are P3 (not P2) because the channel-level verdicts in US2 are the milestone's headline contribution and deliver value standalone — schema candidates are the second pass that uses the same redesigned infrastructure.

**Independent Test**: A reviewer reads the schema-candidates section of `docs/benchmarks/m4-time-axis-tuning.md` and confirms (a) each named candidate (packed scalars, oneof flattening, chunk granularity) has a verdict at hidden_size 4096 against the frozen-channel baseline from US2, (b) each verdict reports both bytes and time deltas with 95% CIs, (c) candidates where the 4096 result is `recommend` or borderline (CI bounds touch the baseline CI) are also measured at 2048 and 8192, and (d) candidates that produce no measurable signal on either metric are explicitly named as negative results so future readers do not speculatively re-run them.

**Acceptance Scenarios**:

1. **Given** the frozen-channel baseline derived from US2's recommendations and the redesigned harness from US1, **When** the schema-candidate sweep runs at hidden_size 4096, **Then** each of (packed scalars, oneof flattening, chunk granularity) produces a cohort with bytes and time measurements, and a verdict for each metric independently.
2. **Given** a schema candidate whose 4096 verdict on either metric is `recommend` or whose CIs are within one CI-width of the baseline (borderline), **When** the report is finalized, **Then** that candidate is also measured at hidden_size 2048 and 8192 to verify the effect generalizes across canonical widths.
3. **Given** a schema candidate that produces overlapping CIs on both bytes and time at the canonical width, **When** the report is finalized, **Then** that candidate is recorded as a negative result with the supporting CI-bounded numbers and is named in a "Negative results — do not re-run speculatively" appendix.
4. **Given** any schema candidate flagged `recommend`, **When** the maintainer reviews the recommendation, **Then** the supporting numbers cite the frozen-channel baseline cohort (not M3's bytes-only baseline) and the rationale explicitly states which metric (bytes, time, or both) drove the recommendation.

---

### Edge Cases

- **Mock pacing replaced by something else as the bottleneck**: After enabling no-pacing, chat_stream wall-clock might be dominated by the orchestrator's own per-sample overhead or by Python-level event-loop scheduling rather than transport+serialization. The report MUST distinguish "transport-bound" from "client-bound" cohorts and refuse to issue a transport-axis verdict on a cohort whose dominant cost is client-side.
- **Shared-baseline drift detected mid-run**: If the harness detects unusual variance in the shared-baseline cohort itself (e.g., a load spike during the baseline measurement window), it must fail loudly rather than silently use a poisoned baseline; the operator should re-run.
- **Schema candidate breaks wire compatibility**: Candidate proto shapes are evaluated in isolation. The production proto remains on M3's shape; only a candidate that is recommended AND is acceptable to maintainers may be adopted, and adoption is a separate change tracked outside this spec.
- **Loopback masks the effect**: When an axis (typically keepalive or HTTP/2 framing) shows no measurable wall-clock delta on a single-host loopback transport, the report MUST distinguish "no effect" from "effect masked by loopback" using the available evidence (e.g., the axis is theoretically dependent on round-trip latency that loopback collapses to ~0). It MUST NOT report a false `no_winner` as a final answer in cases where the underlying mechanism cannot manifest on the test topology.
- **Negative result on a previously-promising candidate**: If a schema candidate that bytes-axis intuition suggested would win (e.g., packed scalars on token-id) measures as no measurable change, the negative result must be published with full numbers, not silently dropped (Constitution V).
- **CI rule produces a tie**: If a candidate's 95% CI touches but does not strictly clear the baseline's 95% CI, the verdict is `no_winner` with the supporting numbers (the same rule M3 used) — this milestone introduces no new "borderline" verdict literal.

## Requirements *(mandatory)*

### Functional Requirements

#### Harness redesign (Phase B prerequisite)

- **FR-001**: The mock engine MUST support a no-pacing mode that emits tokens with zero artificial inter-token delay so that chat_stream total per-RPC wall-clock is dominated by transport and serialization rather than mock pacing. The default paced mode MUST remain available so prior reproducibility is not broken.
- **FR-002**: The orchestrator MUST support a shared-baseline mode that measures one M1_BASELINE cohort (n ≥ 100 samples per measured path) at the start of a run and reuses it as the time-metric and bytes-metric reference for every axis × width × path cell in the same run. The cohort metadata (cohort id, sample count, timestamp, channel and serializer config) MUST be recorded in the run output so the published report can cite it once. **Candidate cohorts** (channel-axis cells per FR-006 and schema candidates per FR-013) MUST default to n ≥ 100 samples and MUST be re-measured at n ≥ 250 ("borderline-expand") whenever the initial 95% CI touches the comparison baseline's 95% CI; the per-cell decision to expand and the resulting cohort size MUST be recorded in the run output so the report shows which cells were expanded and which were not. **Per-path frozen-channel baseline cohorts** (per FR-011) are themselves baselines, not candidates: they are sized at n ≥ 100 and are NOT subject to the borderline-expand rule (they have no comparison baseline to overlap against — they are the comparison baseline for US3).
- **FR-003**: The recommendation builder MUST treat TTFT (per-sample time-to-first-token) as a first-class output for chat_stream cells. Total streaming wall-clock MUST be reported as a secondary diagnostic. The published verdict MUST name which metric drove it.
- **FR-004**: The harness MUST refuse to issue a transport-axis time verdict for a cohort whose dominant per-RPC cost is client-side (e.g., orchestrator overhead exceeds the measured transport delta). Such cohorts MUST be recorded with a `client_bound` notation and excluded from `recommend` tallies.
- **FR-005**: The harness MUST measure within-cohort coefficient of variation (stddev/mean on the verdict metric — wall-clock for embed cohorts, TTFT for chat_stream cohorts per FR-003) for every cohort and record it on the per-cohort entry of the published report. The harness MUST NOT abort the run when CV exceeds any threshold; the run MUST always proceed to completion and write its report so that all measurement data is preserved for post-hoc analysis. A configurable warn threshold (`--baseline-cv-warn`, default `0.05`, calibrated against M3's observed cross-batch drift) governs only whether (a) a warning is emitted at the end of the run naming the offending baseline cohorts and (b) the per-cohort entry carries a `noisy_baseline: true` flag. Verdict adjudication — including the decision to discount or re-run a verdict whose baseline was noisy — remains with the report's reader.

#### Definitive time-axis channel sweep

- **FR-006**: A four-axis channel sweep covering `max_message_size`, keepalive, compression, and HTTP/2 framing MUST be re-run under the redesigned harness (no-pacing + shared-baseline + TTFT-first-class) at hidden_size 2048, 4096, and 8192 for both the embed and chat_stream paths.
- **FR-007**: The published M4 report MUST emit a definitive time-metric verdict (`recommend` or `no_winner`) for every cell that M3's published time report marked `noise_bounded`. The `noise_bounded` verdict literal MUST NOT appear in the M4 report.
- **FR-008**: Each `recommend` verdict MUST be supported by a candidate cohort whose 95% CI strictly clears the shared-baseline's 95% CI under the same direction-of-improvement rule M3 used for bytes (lower bound > upper bound for maximizing metrics; upper bound < lower bound for minimizing metrics).
- **FR-009**: The M4 report MUST include a "Supersedes M3" table that maps each M3 cell M4 supersedes to the M4 verdict, the M4 supporting numbers, and a one-line rationale (e.g., "no-pacing exposed a 4.2% TTFT reduction under compression at hidden_size 4096"). M3's bytes report MUST remain in place as the bytes baseline for traceability.
- **FR-010**: For axes whose effect is plausibly loopback-masked (typically keepalive and HTTP/2 framing), the report MUST attach a "loopback caveat" note to the verdict and explicitly state whether a cross-host re-measurement is warranted to upgrade the verdict in a later milestone.

#### Schema-level (protobuf) candidates

- **FR-011**: The schema-candidate sweep MUST be evaluated against a **per-path frozen-channel baseline**: for each measured path (chat_stream, embed), the harness MUST construct one cohort whose channel configuration combines that path's per-axis winners from FR-006/FR-007 at the canonical width (hidden_size 4096), measure it at n ≥ 100, and use it as the comparison reference for every schema candidate that targets that path. Each schema candidate MUST pair with the cohort matching its path (e.g., packed scalars on chat completion's token-id field → chat_stream baseline; oneof flattening on the input union → both paths if applicable). Where a path's per-axis winners are all `no_winner` (i.e., M3-default channel config), the per-path frozen baseline is the M3-default channel config measured under the redesigned harness — it MUST still be measured as its own cohort rather than reused from the shared M1_BASELINE cohort, so the comparison is against a single coherent measured configuration. The frozen baselines MUST NOT be M3's bytes-only baseline.
- **FR-012**: At minimum, the schema sweep MUST measure: (a) packed scalars on the chat completion's token-id field, (b) `oneof` flattening on the input union, and (c) alternative streaming chunk granularity per `specs/015-m3-protobuf-grpc-tuning/research.md` R-9.
- **FR-013**: Each schema candidate MUST be evaluated on BOTH the bytes metric and the time metric using the same 95% CI rule as FR-008. Candidates MUST be measured at hidden_size 4096 (canonical mid-width) at minimum; candidates whose 4096 verdict is `recommend` or borderline (CIs within one CI-width of the baseline) MUST also be measured at hidden_size 2048 and 8192 to verify the effect generalizes.
- **FR-014**: Candidates whose 95% CIs overlap the baseline's CI on both metrics MUST be recorded as negative results with supporting numbers and named in a "Negative results — do not re-run speculatively" appendix (Constitution V).

#### Reporting and supersession

- **FR-015**: The M4 report MUST be published at `docs/benchmarks/m4-time-axis-tuning.{md,json}` as a sibling to M3's bytes report. The JSON file's schema MUST be a **strict superset of M3's `m3-channel-tuning-time.json` schema** — only additive changes are allowed (new fields permitted; no renames, no removals, no semantic redefinition of existing fields), so any tooling that reads M3's time-report continues to work without modification on M4's file. The report MUST follow the M2 ground-truth workflow's citation conventions, citing the cloned vLLM and grpcio sources behind any time-affecting recommendation.
- **FR-016**: A reader of the M4 report MUST be able to determine, without reading the harness source, (a) which channel-level setting per axis is recommended at hidden_size 2048 / 4096 / 8192 for each path on the time metric, (b) whether each named schema candidate is recommended at the canonical width, and (c) which M3 cells M4 supersedes.

### Key Entities

- **Shared M1_BASELINE cohort**: A single per-run measurement of the unmodified M1 channel and proto configuration, sized for stable CIs (n ≥ 100), recorded once and referenced by every axis × width × path cell in the run. Replaces M3's per-axis fresh baselines.
- **No-pacing mock cohort**: A cohort produced by the mock engine running with artificial inter-token delay disabled; the resulting chat_stream wall-clock is interpretable as transport + serialization (plus client-side overhead, which FR-004 guards against).
- **TTFT verdict**: A `recommend` / `no_winner` decision computed on per-sample `time_to_first_token_seconds` for chat_stream cohorts, supported by the same 95% CI clearing rule used for bytes verdicts in M3.
- **Frozen-channel baseline**: The recommended channel configuration emerging from US2; serves as the reference configuration against which schema-level candidates are compared in US3.
- **Supersession entry**: A single row in the M4 report that names an M3 cell, the M3 verdict (typically `noise_bounded` on time), the M4 verdict, the M4 supporting numbers, and a one-line rationale.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every cell that M3's published time report marked `noise_bounded` (the chat_stream total wall-clock cells under every axis at every canonical width) carries a non-`noise_bounded` time verdict in M4's published report. The `noise_bounded` verdict literal does not appear in the M4 report at all.
- **SC-002**: A reader can answer "which channel-level setting reduces chat_stream time at hidden_size 2048 / 4096 / 8192?" — at all three widths, the report names a recommended setting (or an honest `no_winner` with the loopback caveat from FR-010) per axis on the time metric and shows the supporting 95% CI-bounded delta.
- **SC-003**: A reader can answer "do any of the named protobuf schema refinements measurably reduce wire bytes or wall-clock time at hidden_size 4096?" — the report names a winning candidate, an `no_winner` verdict with CIs, or a documented negative result for each schema candidate listed in FR-012.
- **SC-004**: No verdict in the M4 report cites cross-batch baseline drift as the reason for an `no_winner` decision. The shared-baseline cohort's reproducibility is demonstrated within the report itself by reporting each cohort's within-cohort CV (per FR-005) alongside its CIs, so a reader can judge baseline noise without leaving the report.
- **SC-005**: The M4 report can be reproduced from a single end-to-end harness run on a single commodity host (i.e., one shared-baseline cohort, one channel sweep, one schema sweep) — cross-host coordination is not required for primary verdicts. (Cross-host re-measurement may be cited as a future milestone for axes flagged with the loopback caveat per FR-010.)
- **SC-006**: A new contributor onboarding via the M4 report can identify, in under five minutes of reading, the methodology changes from M3 to M4 and which M3 conclusions are superseded.

## Assumptions

- **M3 closed before M4 begins.** M3's Phase A re-analysis (US3) shipped on 2026-05-10 and M3 closed; M4 is the next active milestone. The M3 published report stays in place and is not edited by M4 — supersession is recorded in the M4 report instead.
- **Real-model validation is out of scope.** Benchmarks continue to run against the configurable mock model from M3 at canonical hidden_size 2048 / 4096 / 8192. Real-model validation lives in M6.
- **Corpus diversity is out of scope.** Prompt corpus follows M3's harness defaults. Corpus expansion is M5's responsibility.
- **Cross-host transport mode is optional within M4.** It is added only if loopback masking is observed for a specific axis AND the size of the masked effect, judged against the cost of standing up cross-host infrastructure, justifies the work. Otherwise, axes flagged loopback-masked carry a `no_winner` plus the FR-010 caveat and are deferred to a future milestone.
- **Schema-candidate breadth follows a 4096-first cascade.** Each candidate is measured at hidden_size 4096 first; widths 2048 and 8192 are added only when the 4096 result is `recommend` or borderline. This bounds the schema sweep's runtime while preserving the ability to claim cross-width generalization for any winning candidate.
- **Existing M3 data is re-used where it remains valid.** Bytes-axis verdicts from M3 are referenced in M4's report by citation, not re-measured. Only the time-axis cells M3 left `noise_bounded` and the deferred schema candidates require new measurement.
- **Adoption is a separate change.** A `recommend` verdict in M4's report does not automatically modify the production `proto/`, channel-options module, or client defaults. Adoption is performed in a follow-up change with its own review, and only for candidates the maintainers accept.
- **Ground-truth citations follow the M2 workflow.** Recommendations cite cloned vLLM (`~/.graphify/repos/vllm-project/vllm/`) and grpcio (`~/.graphify/repos/grpc/grpc/`) source via `cross-repo.json` for cross-repo paths and the targeted single-repo graphs for repo-specific evidence, per the project CLAUDE.md navigation rules.
- **Constitution V (negative-results-published) applies.** Schema candidates that measure as no-effect are recorded with full supporting numbers in a named appendix so the negative result is reusable rather than re-discovered.
