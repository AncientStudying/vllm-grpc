# Feature Specification: M3 — Protobuf & gRPC Tuning

**Feature Branch**: `015-m3-protobuf-grpc-tuning`
**Created**: 2026-05-09
**Status**: Draft
**Input**: User description: "M3 — Protobuf & gRPC Tuning. Focus on gRPC tuning first (channel options, max_message_size, keepalive, compression, HTTP/2 framing, streaming flow control between FastAPI proxy and the gRPC servicer wrapping AsyncLLM). Protobuf message-shape tuning is in scope but secondary — sequence after gRPC wins are measured."

**Note**: The original input also bundled a small repository-hygiene task — stop tracking `graphify-out/GRAPH_REPORT.md` and `graphify-out/graph.html`, and add them to `.gitignore`. That task has been split out of M3 and shipped as its own change off `main`, because it is a friction point for all future branch switches and does not need to wait for the M3 benchmark cycle to land.

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

### User Story 2 — Schema-level (protobuf) message-shape tuning (Priority: P2)

After P1 has produced a documented best channel configuration, a maintainer wants to know whether refinements to the proto message shape — packed scalars, streaming chunk granularity, and the layout of the input `oneof` union — can move wire size or decode time below the channel-tuned baseline.

**Why this priority**: This is the second axis of the milestone but is gated on P1 being measured. Without a fixed channel baseline, schema-level wins cannot be cleanly attributed. Schema changes also have higher blast radius than channel-config changes (regenerated stubs, downstream client compatibility) and warrant being sequenced after the channel work proves out.

**Independent Test**: With the channel configuration frozen at the P1-recommended values, a reviewer can run the same benchmark harness against a candidate proto revision and read out wire-size and decode-time deltas vs. the P1 baseline.

**Acceptance Scenarios**:

1. **Given** the P1-recommended channel configuration is in effect and the mock model is running at embedding width 4096, **When** a candidate proto revision (packed scalars or alternative streaming chunk granularity) is benchmarked against the P1 baseline, **Then** the report records wire-byte and decode-time deltas attributable solely to the schema change.
2. **Given** any proto message-shape recommendation, **When** the recommendation is added to the M3 report, **Then** the rationale references vLLM and/or grpcio source via the M2 ground-truth workflow, and any compatibility implications for existing clients are documented.

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
- **FR-005**: For each gRPC channel-level setting under test (`max_message_size`, keepalive, compression, HTTP/2 framing), the report MUST document the configurations compared, the per-setting wire-byte and decode-time deltas vs. the M1 baseline, and the recommended setting with its rationale.
- **FR-006**: The report MUST identify the embedding width at which the default `max_message_size` first becomes binding for the embed path.
- **FR-007**: Channel-tuning recommendations MUST cite the corresponding behaviour in cloned grpcio source per the M2 ground-truth workflow, not documentation summaries alone.
- **FR-008**: Schema-level (protobuf) tuning MUST NOT begin until the P1 channel configuration has been measured and recorded in the M3 report. The recorded P1 configuration becomes the fixed baseline against which schema-level deltas are reported.
- **FR-009**: For each schema-level proto change under test, the report MUST document the wire-byte and decode-time deltas vs. the P1 baseline, the rationale (with vLLM/grpcio citations per the M2 workflow), and any compatibility implications for existing clients.
- **FR-010**: Findings, deltas, and recommendations MUST be published in a new section of `docs/benchmarks/` (or an analogous report file) in the same format as the existing M1 summary, so external readers can compare M1 vs. M3 numbers at a glance.

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
- **SC-003**: For at least one channel-level setting, the M3 report demonstrates a measurable reduction in either wire bytes or decode time relative to the M1 baseline, beyond benchmark noise floor (or, if no setting wins, the report explicitly documents that finding with the supporting numbers).
- **SC-004**: After P1 closes, at least one schema-level proto candidate is benchmarked against the P1 channel baseline and its wire-byte and decode-time deltas are recorded in the report — even if the candidate is ultimately rejected, the negative result is documented.
- **SC-005**: Every channel-level and schema-level recommendation in the M3 report is paired with a citation pointing into cloned grpcio or vLLM source via the M2 ground-truth workflow.

## Assumptions

- **Benchmarks run locally on CPU** against the mock model (no Modal A10G round-trip), per the milestone framing that "GPU cost is removed from the loop." If a result requires cross-validation against a real model, that work falls under M5, not M3.
- **The mock model's wire characteristics are sufficient to drive channel-tuning conclusions.** Per upstream guidance recorded in the README, embed payload size is determined by `hidden_size` and not by total parameter count, so a dummy-weighted mock at canonical widths produces representative wire payloads. M5 will revalidate against real models.
- **The M1 baseline channel configuration is the correct starting point** for P1 comparisons. The M1 benchmark numbers in `docs/benchmarks/summary.md` are treated as authoritative for "before" measurements.
- **Cloned vLLM and grpcio (per M2 workflow) are available** at the versions pinned in `uv.lock`, and `cross-repo.json` is current. If the lockfile bumps mid-milestone, `/ground-truth-refresh` is run before further citations are added.
- **Streaming chat-completion paths exercise channel-framing and keepalive behaviour** that the embed path alone would not surface; both paths are therefore in scope under P1 even though the mock's primary output is embeddings.
- **No external API or client integration is required** for M3. All changes are internal to the repository's benchmark harness, mock model, proto definitions, and documentation.
