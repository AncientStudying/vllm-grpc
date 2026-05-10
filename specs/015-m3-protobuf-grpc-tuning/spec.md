# Feature Specification: M3 — Protobuf & gRPC Tuning

**Feature Branch**: `015-m3-protobuf-grpc-tuning`
**Created**: 2026-05-09
**Status**: Draft
**Input**: User description: "M3 — Protobuf & gRPC Tuning. Focus on gRPC tuning first (channel options, max_message_size, keepalive, compression, HTTP/2 framing, streaming flow control between FastAPI proxy and the gRPC servicer wrapping AsyncLLM). Protobuf message-shape tuning is in scope but secondary — sequence after gRPC wins are measured."

**Note**: The original input also bundled a small repository-hygiene task — stop tracking `graphify-out/GRAPH_REPORT.md` and `graphify-out/graph.html`, and add them to `.gitignore`. On investigation that work had already landed in M2 (PR #16, task T034): `git ls-files graphify-out/` is empty on `main` and `/graphify-out/` is in `.gitignore`. The friction surfaced for the user only because they encountered it on a `main` checkout that pre-dated the M2 merge; pulling M2 permanently resolves it. No carry-over work into M3.

## Clarifications

### Session 2026-05-09

- Q: What threshold defines a "win" for an M3 channel- or schema-level recommendation (the noise floor referenced by SC-003)? → A: A measured improvement must exceed the upper bound of the 95% confidence interval of the M1-baseline measurement at the same workload; this requires repeated runs per cell to estimate the baseline CI.
- Q: When does P1 close so that P2 (schema-level proto tuning) may begin? → A: All four channel axes (`max_message_size`, keepalive, compression, HTTP/2 framing) must each have a recorded outcome — a positive recommendation, an explicit "no winner found", or an explicit "not measurable on this harness" — before P2 starts. Partial closure does not unblock P2.
- Q: What prompt corpus drives the chat-completion streaming workload? → A: The M1 prompt corpus drives the bulk of streaming runs (preserving M1↔M3 comparability per FR-003), and the harness adds at least one explicit long-stream synthetic prompt — long enough to exercise keepalive and HTTP/2 framing behaviour the M1 corpus may not reach — so the keepalive-regression Edge Case is observable.

### Session 2026-05-10

- Q: Are wire-byte savings and wall-clock time savings equally important M3 outcomes, or is one primary? → A: Wall-clock time savings is the primary milestone goal. Wire-byte reduction is a contributor (fewer bytes to write/read off the wire usually means less wall-clock time) but the project's central thesis is end-to-end execution time efficiency. Bytes-only verdicts are valid but incomplete; time-metric verdicts are required for milestone closure.
- Q: How is wall-clock time measured per path? → A: For the embed path, total per-RPC wall-clock is the primary time metric. For chat_stream, time-to-first-token (TTFT, per-sample `time_to_first_token_seconds`) is primary because total wall-clock is dominated by the mock engine's deterministic token-emission pacing rather than transport (see `research.md` R-11). Mean inter-token latency is reported as a secondary diagnostic.
- Q: Is the bytes-only US1 closure (PR #17) sufficient, or does it need a time-axis re-analysis? → A: Insufficient as-is. A code-only re-analysis on the data already collected (Phase A / US3) extends the published P1 report to cover time deltas where the existing harness produced defensible signal (compression both paths; embed total wall-clock across all axes; TTFT for chat_stream). For axes where the existing harness cannot produce a defensible time verdict (specifically, chat_stream total wall-clock under any axis, where mock pacing dominates), a harness redesign is required before re-sweeping; that work is **scoped to M4** in `docs/PLAN.md` and is out of scope for this feature.
- Q: What happens to the originally-scoped US2 (schema-level proto tuning) given the time-metric elevation? → A: Deferred to M4. US2 candidates (`packed`, `oneof` flattening) are most likely to manifest as TTFT wins, and TTFT becomes a defensible verdict metric only under the M4 harness changes. T028–T034 below remain as drafted but are tagged "deferred to M4"; they will be re-spec'd as part of feature 016 (M4) and not executed on this branch.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Channel-level (gRPC) tuning measurements (Priority: P1)

A maintainer or external evaluator wants to know how gRPC channel-level settings affect wire size and decode time for an LLM-style payload, so they can decide which settings to ship in the project's reference configuration and so they can publish defensible numbers to back the protocol-overhead thesis.

The work uses a mock vLLM stand-in that exposes a configurable embedding width (canonical sizes: 2048, 4096, 8192) and emits dummy-weighted embeddings of that shape. The mock removes GPU cost from the loop while preserving the wire-size characteristics that channel-level tuning is sensitive to. Measurements cover both the embed path (where payload is wholly determined by embedding width) and the chat-completion streaming path (where channel framing and liveness settings have the largest effect).

**Why this priority**: This is the milestone's central empirical question. Channel settings are repo-internal configuration with low blast radius and produce numbers that directly extend the M1 benchmark report. Schema-level proto changes (P2) depend on having a known-good channel baseline to measure against, so this must be done first.

**Independent Test**: A reviewer can run the M3 benchmark harness against the mock model at each of the three canonical embedding widths, with the project's M1 channel configuration as the baseline and at least one tuned configuration as the comparator, and read out per-setting deltas in wire bytes and decode time. The output is a markdown report under `docs/benchmarks/` analogous to the existing M1 summary.

**Acceptance Scenarios**:

1. **Given** the mock model is running at embedding width 2048, **When** the benchmark harness runs both the M1-baseline channel configuration and at least one tuned configuration over the embed path, **Then** the report records wire bytes and decode time for each, with deltas expressed as both absolute and percent change vs. baseline.
2. **Given** the mock is running at embedding width 8192, **When** the benchmark runs the embed path with the M1-baseline `max_message_size`, **Then** the report documents whether the default becomes binding (request rejected or truncated) and at what width the threshold first appears.
3. **Given** the mock is running and a streaming chat-completion workload is configured, **When** the benchmark runs with and without keepalive tuning and with and without channel compression, **Then** the report records per-token decode-time variance and total wall-clock for each combination.
4. **Given** any tuning recommendation is being added to the M3 report, **When** the recommendation cites a specific channel setting, **Then** the rationale references the corresponding behaviour in cloned grpcio source (per the M2 ground-truth workflow) rather than guessing from documentation alone.

---

### User Story 2 — Schema-level (protobuf) message-shape tuning (Priority: P2) — DEFERRED to M4

**Status (2026-05-10)**: This story is deferred to milestone M4 per the 2026-05-10 clarifications session. The text below remains as originally drafted for traceability; the work itself moves to feature 016 (M4) when that spec is opened.

After P1 has produced a documented best channel configuration, a maintainer wants to know whether refinements to the proto message shape — packed scalars, streaming chunk granularity, and the layout of the input `oneof` union — can move wire size or decode time below the channel-tuned baseline.

**Why this priority**: This is the second axis of the milestone but is gated on P1 being measured. Without a fixed channel baseline, schema-level wins cannot be cleanly attributed. Schema changes also have higher blast radius than channel-config changes (regenerated stubs, downstream client compatibility) and warrant being sequenced after the channel work proves out.

**Independent Test**: With the channel configuration frozen at the P1-recommended values, a reviewer can run the same benchmark harness against a candidate proto revision and read out wire-size and decode-time deltas vs. the P1 baseline.

**Acceptance Scenarios**:

1. **Given** the P1-recommended channel configuration is in effect and the mock model is running at embedding width 4096, **When** a candidate proto revision (packed scalars or alternative streaming chunk granularity) is benchmarked against the P1 baseline, **Then** the report records wire-byte and decode-time deltas attributable solely to the schema change.
2. **Given** any proto message-shape recommendation, **When** the recommendation is added to the M3 report, **Then** the rationale references vLLM and/or grpcio source via the M2 ground-truth workflow, and any compatibility implications for existing clients are documented.

---

### User Story 3 — Wall-clock time re-analysis on the existing P1 sweep data (Priority: P1.5 — Phase A)

After PR #17 closed US1 with bytes-only verdicts, a maintainer wants to extend the published P1 channel-tuning report to cover wall-clock time deltas using the data already collected — without re-running the sweep — so M3 ships with both bytes and time analyses where the existing harness produces defensible signal, and explicitly flags where it doesn't.

**Why this priority**: Per the 2026-05-10 clarifications, wall-clock time is the primary milestone goal, not bytes. The existing sweep JSON (`bench-results/m3-full/m3-channel-tuning.json`) carries every per-cohort time field and per-sample `time_to_first_token_seconds` already — a code-only re-analysis can produce a defensible time-axis report for compression (both paths), embed (all axes), and chat_stream TTFT, alongside an honest "noise-bounded by mock-pacing dilution" verdict for chat_stream total wall-clock. This closes the bytes-only gap that PR #17 left open while the M4 harness redesign is still being scoped.

**Independent Test**: A reviewer reads `docs/benchmarks/m3-channel-tuning-time.md` (a new companion to the bytes report) and confirms (a) every axis × width × path cell has a time-metric verdict (`recommend` / `no_winner` / `not_measurable` / `noise_bounded`), (b) every chat_stream verdict is computed on TTFT and labeled as such, (c) every `recommend` carries CI-bounded supporting numbers and a citation, and (d) the "Limitations" section explicitly cites which axes the existing harness cannot produce a defensible total-wall-clock verdict for and why.

**Acceptance Scenarios**:

1. **Given** the P1 sweep JSON exists at `bench-results/m3-full/m3-channel-tuning.json`, **When** the bench harness gains a `metric="time"` and `metric="ttft"` mode and is invoked with `--reanalyze` against that JSON, **Then** the harness writes `m3-channel-tuning-time.json` with per-axis time verdicts using immediate-predecessor M1_BASELINE pairing (so the per-axis baseline drift documented in research.md R-12 does not contaminate the verdict).
2. **Given** the chat_stream cohorts in the sweep JSON, **When** the time-axis recommendation builder runs on chat_stream cells, **Then** the verdict is computed on `time_to_first_token_seconds` per-sample (not on total `wall_clock_seconds`), and the report explicitly labels the metric as TTFT.
3. **Given** any axis × width × path cell whose existing-harness time signal is dominated by mock pacing or by cross-batch baseline drift in excess of the candidate's expected effect size, **When** the verdict is emitted, **Then** the verdict is `noise_bounded` (a new verdict literal alongside `recommend` / `no_winner` / `not_measurable`) with a brief notes field naming the dominating source, and the cell does not enter the "recommend" tally.
4. **Given** the Phase A re-analysis report is published, **When** an M4 spec is opened, **Then** the M3 report's Limitations section names the specific cells M4 must re-measure under the harness redesign and points to the R-11..R-14 research entries as the design inputs.

---

### Edge Cases

- **Embedding width above the canonical set**: If a contributor or reviewer runs the harness at an embedding width outside {2048, 4096, 8192}, the harness should accept the value but the report should clearly mark such results as off-canonical and not used as a primary recommendation.
- **`max_message_size` becomes binding mid-run**: At larger embedding widths the default channel limit may reject the request entirely. The harness must distinguish "request rejected at the boundary" from "request succeeded with degraded throughput" so the report does not silently treat a failed call as a fast call.
- **Compression that lengthens the payload**: For some message shapes, channel compression may produce a *larger* on-wire payload than uncompressed. The report must surface negative wins rather than only the positive ones.
- **Keepalive tuning regressions**: Aggressive keepalive can cause the upstream servicer to drop long-streaming connections. The benchmark must include long-running streaming completions, not only short ones, so this regression is observable.
- **Schema change that breaks existing M1 clients**: Any proto change that would force regeneration on the existing benchmark client must be flagged in the report; "breaks M1 client" is a valid reason to defer or reject a candidate even if it wins on bytes.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The project MUST provide a mock vLLM stand-in that exposes a configurable embedding width and emits embeddings of the matching shape with dummy weights, so M3 measurements can be taken without GPU cost.
- **FR-002**: The mock MUST support the canonical embedding widths 2048, 4096, and 8192, and MUST also accept other widths for exploratory runs (results from non-canonical widths are reported but not used as primary recommendations).
- **FR-003**: The benchmark harness MUST exercise the FastAPI-proxy → gRPC-servicer → mock-model path that mirrors the M1 production topology, so M3 channel-tuning results are directly comparable to M1 numbers.
- **FR-004**: The harness MUST measure both the embed path (request and response wire bytes) and the chat-completion streaming path (per-token decode time, total wall-clock, streaming framing behaviour).
- **FR-005**: For each gRPC channel-level setting under test (`max_message_size`, keepalive, compression, HTTP/2 framing), the report MUST document the configurations compared, the per-setting **wire-byte deltas AND wall-clock time deltas** (TTFT for chat_stream per FR-014, total per-RPC wall-clock for embed) vs. **the M1-baseline channel configuration measured on the same M3 hardware** (not the absolute M1 timings published from Modal A10G — see `research.md` R-8 for the rationale), with each delta expressed as **both an absolute and a percent change** vs. baseline, and the recommended setting with its rationale. Where the existing harness cannot produce a defensible time-metric verdict for a cell (per `research.md` R-11 / R-12), the report MUST mark that cell `noise_bounded` and name the dominating noise source.
- **FR-006**: The report MUST identify the embedding width at which the default `max_message_size` first becomes binding for the embed path.
- **FR-007**: Channel-tuning recommendations MUST cite the corresponding behaviour in cloned grpcio source per the M2 ground-truth workflow, not documentation summaries alone.
- **FR-008**: Schema-level (protobuf) tuning MUST NOT begin until **all four** P1 channel axes — `max_message_size`, keepalive, compression, and HTTP/2 framing — have each been measured and have a recorded outcome in the M3 report. A recorded outcome is one of: a positive recommendation with supporting delta, an explicit "no winner found" with supporting numbers, or an explicit "not measurable on this harness" with rationale. Partial axis closure does not unblock P2. The frozen four-axis P1 channel configuration becomes the fixed baseline against which P2 schema-level deltas are reported.
- **FR-009**: For each schema-level proto change under test, the report MUST document the wire-byte and decode-time deltas vs. the P1 baseline, the rationale (with vLLM/grpcio citations per the M2 workflow), and any compatibility implications for existing clients.
- **FR-010**: Findings, deltas, and recommendations MUST be published in a new section of `docs/benchmarks/` (or an analogous report file) in the same format as the existing M1 summary, so external readers can compare M1 vs. M3 numbers at a glance.
- **FR-011**: The chat-completion streaming workload MUST be driven by the M1 prompt corpus (to preserve M1↔M3 comparability per FR-003), augmented with at least one explicit long-stream synthetic prompt long enough to exercise keepalive and HTTP/2 framing behaviour the M1 corpus may not surface (so the keepalive-regression Edge Case is observable).
- **FR-012**: The mock engine MUST eventually support a no-pacing mode (e.g. `tokens_per_second=0` or a `--no-pacing` flag) so total streaming wall-clock can be dominated by transport+serialization rather than artificial token-emission delay. **Implementation deferred to M4.** Time-metric verdicts on chat_stream total wall-clock REQUIRE this mode to be defensible; verdicts produced under the default paced mode (the only mode available in M3) MUST be labeled "TTFT-only" in the report, with chat_stream total wall-clock cells marked `noise_bounded` per FR-005.
- **FR-013**: The harness MUST eventually support a shared-baseline mode that measures one M1_BASELINE cohort (n≥100) up front and reuses it as the reference for all axis evaluations on the time metric. **Implementation deferred to M4.** Per-axis fresh baselines exhibit cross-batch wall-clock drift on the order of 10–15% under typical macOS scheduling (observed in M3, see `research.md` R-12), which exceeds the size of any expected channel-tuning time win and therefore poisons SC-003 evaluation on time. Phase A (US3) works around this by pairing each candidate with its immediate-predecessor M1_BASELINE in cohort run-order rather than the global "first baseline" the M3 builder selected for bytes.
- **FR-014**: For the chat_stream path, the recommendation builder MUST evaluate the time metric on TTFT (per-sample `time_to_first_token_seconds`) as the primary signal. Total wall-clock is reported as a secondary diagnostic. Mean inter-token latency is reported but is not used as a primary verdict metric because it is bounded by the mock's pacing. Phase A (US3): re-derive TTFT statistics from existing per-sample data. M4 (Phase B): promote TTFT to first-class output of the recommendation builder.

### Key Entities

- **Mock model configuration**: The set of parameters that define a mock run — primarily embedding width (canonical or off-canonical) and any seeded weights needed for reproducibility.
- **Channel configuration**: The named tuple of gRPC channel-level settings under test in P1 — at minimum `max_message_size`, keepalive parameters, compression, and HTTP/2 framing options. Two specific configurations are first-class: the M1-baseline configuration (the comparator) and the M3-recommended configuration (the P1 outcome that becomes the P2 baseline).
- **Proto revision**: A candidate change to the project's `.proto` definitions evaluated under P2. Each candidate has an identity, a description of the schema change (e.g. "packed scalars on token-id field"), and measured deltas against the P1 baseline.
- **Benchmark run**: A single execution of the harness at one mock width with one channel configuration and one proto revision, producing wire-byte and decode-time measurements.
- **M3 report**: The published markdown artefact under `docs/benchmarks/` recording the channel configurations compared, the schema candidates compared, all measurements, and the resulting recommendations with ground-truth citations.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A reader of the M3 report can answer "which gRPC channel settings should I use to minimise wire bytes for an LLM-style embed payload at hidden_size 2048, 4096, and 8192?" without rerunning the benchmark — at all three canonical widths, the report names a recommended setting per axis (`max_message_size`, keepalive, compression, HTTP/2 framing) and shows the supporting delta vs. the M1 baseline.
- **SC-002**: A reader can identify the embedding width at which the default `max_message_size` first becomes binding for the embed path, expressed as a specific width value, with the failure mode described.
- **SC-003**: For each channel-level axis, the M3 report records a verdict on **both** the bytes metric **and** the time metric (TTFT for chat_stream per FR-014, total per-RPC wall-clock for embed). A `recommend` verdict on either metric requires the candidate's 95% CI to clear the same-cohort baseline's 95% CI (lower bound of candidate strictly greater than upper bound of baseline for maximizing metrics, candidate upper strictly less than baseline lower for the minimizing metrics this milestone uses). If neither metric clears the bar for a given axis × width × path cell, `no_winner` is recorded for both with the supporting per-cohort numbers and CIs. Cells whose existing-harness time signal is dominated by mock pacing or by cross-batch baseline drift larger than the candidate's expected effect size are recorded as `noise_bounded` (FR-005) — these cells re-measure under M4.
- **SC-004**: After P1 closes, at least one schema-level proto candidate is benchmarked against the P1 channel baseline and its wire-byte and decode-time deltas are recorded in the report — even if the candidate is ultimately rejected, the negative result is documented. **Status (2026-05-10)**: deferred to M4 alongside US2.
- **SC-005**: Every channel-level and schema-level recommendation in the M3 report is paired with a citation pointing into cloned grpcio or vLLM source via the M2 ground-truth workflow.
- **SC-006**: A reader of the M3 report can answer "which gRPC channel settings reduce wall-clock time for an LLM-style payload at hidden_size 2048, 4096, and 8192?" without rerunning the benchmark — at all three canonical widths, the report names a recommended setting (or honest `no_winner` / `noise_bounded`) per axis on the time metric and shows the supporting CI-bounded delta. For chat_stream the time metric is TTFT (per FR-014); for embed it is total per-RPC wall-clock. SC-006 closure for the cells M3's existing harness can defensibly verdict (compression both paths; embed total wall-clock; TTFT for chat_stream) lands in this milestone via Phase A / US3; SC-006 closure for the cells the existing harness cannot verdict (chat_stream total wall-clock under any axis) lands in M4.

## Assumptions

- **Benchmarks run locally on CPU** against the mock model (no Modal A10G round-trip), per the milestone framing that "GPU cost is removed from the loop." If a result requires cross-validation against a real model, that work falls under M5, not M3.
- **The mock model's wire characteristics are sufficient to drive channel-tuning conclusions.** Per upstream guidance recorded in the README, embed payload size is determined by `hidden_size` and not by total parameter count, so a dummy-weighted mock at canonical widths produces representative wire payloads. M5 will revalidate against real models.
- **The M1 baseline channel configuration is the correct starting point** for P1 comparisons. The M1 benchmark numbers in `docs/benchmarks/summary.md` are treated as authoritative for "before" measurements.
- **Cloned vLLM and grpcio (per M2 workflow) are available** at the versions pinned in `uv.lock`, and `cross-repo.json` is current. If the lockfile bumps mid-milestone, `/ground-truth-refresh` is run before further citations are added.
- **Streaming chat-completion paths exercise channel-framing and keepalive behaviour** that the embed path alone would not surface; both paths are therefore in scope under P1 even though the mock's primary output is embeddings.
- **No external API or client integration is required** for M3. All changes are internal to the repository's benchmark harness, mock model, proto definitions, and documentation.
