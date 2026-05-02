# Feature Specification: Direct gRPC Client Library (Phase 4.2)

**Feature Branch**: `008-direct-grpc-client`  
**Created**: 2026-05-02  
**Status**: Draft  
**Input**: User description: "phase 4.2"

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Call the gRPC Frontend Directly from Python (Priority: P1)

A Python developer wants to send chat completion requests to the vLLM gRPC frontend without going through the REST proxy or constructing raw protobuf messages by hand. They import a client library, open a connection, and call a single method to get a typed response.

**Why this priority**: This is the core deliverable of Phase 4.2. Everything else depends on the client library existing. It also produces the first benchmark comparison that isolates protocol overhead from proxy overhead, validating the project's wire-efficiency thesis.

**Independent Test**: Instantiate the client pointed at a running gRPC frontend (local or Modal), call `chat.complete()` with a fixed seed, and verify a deterministic response is returned. No proxy process is involved. Delivers standalone value as a Python-native interface to the frontend.

**Acceptance Scenarios**:

1. **Given** a running gRPC frontend and valid connection address, **When** a developer opens a client context and calls `chat.complete(messages, model, max_tokens)`, **Then** a response containing the assistant message content and token counts is returned within the configured timeout.
2. **Given** a valid client context, **When** the same request is sent twice with identical seed, **Then** both responses contain identical content (deterministic completion).
3. **Given** a client with an unreachable address, **When** `chat.complete()` is called, **Then** a clear error is raised identifying the connection failure; no hang beyond the configured timeout.
4. **Given** a client context, **When** the `async with` block exits (normally or via exception), **Then** the underlying connection is closed cleanly with no resource leaks.

---

### User Story 2 — Run a Three-Way Benchmark: REST vs gRPC-via-Proxy vs gRPC-Direct (Priority: P2)

A developer wants to run a single benchmark command that exercises all three access paths — native REST, gRPC through the proxy, and gRPC direct — against the same model on the same GPU hardware, producing a side-by-side latency and throughput comparison report.

**Why this priority**: This is the first measurement that separates proxy overhead from protocol overhead. It is the primary evidence for or against the project's wire-efficiency thesis. Without it, Phase 4.1's results leave the key question unanswered.

**Independent Test**: Run the three-way benchmark command. Verify that the output report contains latency and throughput numbers for all three targets at each concurrency level, with zero errors on any target. The report must be honest — no metric selectively omitted.

**Acceptance Scenarios**:

1. **Given** valid Modal credentials and pre-staged model weights, **When** the three-way benchmark command is run, **Then** all three targets (REST, gRPC-via-proxy, gRPC-direct) complete with zero errors and results are written to `docs/benchmarks/`.
2. **Given** a completed three-way run, **When** the comparison report is opened, **Then** it shows P50/P95/P99 latency and throughput at each concurrency level for all three paths, with delta columns between them.
3. **Given** committed three-way baseline files, **When** a PR is opened touching proxy or frontend code, **Then** the CI benchmark comment includes the three-way summary section alongside the existing stub regression results.

---

### User Story 3 — Import Generated Stubs Without Type Suppressions (Priority: P3)

A developer adding a new consumer of the generated protobuf stubs (proxy, client, test code) wants full type-checker coverage without having to add `# type: ignore` comments to suppress missing-type errors from the generated package.

**Why this priority**: Unblocks clean typing for `packages/client` and removes an ongoing friction for all future stub consumers. Lower priority because the proxy and frontend already work with suppressions, and the client can be built first with suppressions if needed.

**Independent Test**: Remove all `# type: ignore[import-untyped]` comments from proxy, frontend, and client imports of generated stubs. Run the type checker on all three packages. Verify zero errors attributable to the generated package.

**Acceptance Scenarios**:

1. **Given** the `py.typed` marker added to the generated stubs package, **When** the type checker is run on `packages/proxy`, `packages/frontend`, and `packages/client`, **Then** no errors reference missing type information from the generated stubs.
2. **Given** the updated stubs package, **When** a developer adds a new import of a generated message type, **Then** their editor and type checker resolve the type without any suppression comment.

---

### Edge Cases

- What happens when the gRPC frontend is not yet healthy when the client connects? The client must surface a clear error, not silently hang.
- What happens if the three-way benchmark command is run without Modal credentials? It must fail fast with a clear error before spawning any GPU resources.
- What happens if one of the three benchmark targets fails mid-run? Results from completed targets must be preserved internally; partial output files must not be written to `docs/benchmarks/`.
- What happens when `py.typed` is added but generated stub code itself lacks complete annotations? Remaining annotation gaps in generated code are acceptable; only the missing-type-information suppressions must be eliminated.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The client library MUST provide a context manager that opens and holds a persistent connection for its lifetime, closing it cleanly on exit.
- **FR-002**: The client library MUST expose a `chat.complete()` method that accepts human-readable arguments (message list, model name, optional sampling parameters) and returns a typed response object; callers MUST NOT need to construct protobuf messages directly.
- **FR-003**: The client library MUST report connection errors and timeouts as clear exceptions within the configured timeout; it MUST NOT hang indefinitely.
- **FR-004**: The generated stubs package MUST be marked as typed so that all consumers can import it without type-checker suppressions for missing type information.
- **FR-005**: The benchmark harness MUST support a gRPC-direct target that uses the client library to drive requests at the same concurrency levels as the existing REST and gRPC-via-proxy targets.
- **FR-006**: The three-way benchmark command MUST run all three targets sequentially against the same GPU-deployed model using the same corpus and concurrency settings, and MUST write a comparison report covering P50/P95/P99 latency, throughput, and wire bytes for all three paths.
- **FR-007**: The three-way comparison report MUST include all metrics for all three targets; no metric may be selectively omitted.
- **FR-008**: If any target in the three-way benchmark fails, the command MUST NOT write partial output files to `docs/benchmarks/`; it MUST report the failure clearly and exit non-zero.

### Key Entities

- **VllmGrpcClient**: Top-level client. Holds a persistent connection to a named address. Accessed via `async with`. Exposes sub-clients (`.chat`) for each service area.
- **ChatClient**: Sub-client exposed as `.chat`. Exposes `complete()`. Maps human-readable arguments to protobuf and back.
- **ChatCompleteResponse**: Typed response returned by `chat.complete()`. Exposes assistant message, finish reason, and token counts without requiring callers to access protobuf fields directly.
- **ThreeWayBenchmarkRun**: Logical grouping of three `BenchmarkRun` results (REST, gRPC-via-proxy, gRPC-direct) from a single execution.
- **ThreeWayReport**: Comparison document derived from a `ThreeWayBenchmarkRun`, showing all three paths side-by-side at each concurrency level.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer can send a chat completion request to a running gRPC frontend using the client library in under 10 lines of Python with no proxy process running.
- **SC-002**: The three-way benchmark command completes both Modal deployments and all three harness runs in under 45 minutes total wall-clock time.
- **SC-003**: The three-way comparison report quantifies gRPC-direct latency relative to both REST and gRPC-via-proxy at each concurrency level, providing the empirical answer to whether proxy overhead or protocol overhead dominates.
- **SC-004**: The type checker passes on `packages/client` with zero suppressions for generated stub imports.
- **SC-005**: The three-way report is committed to `docs/benchmarks/` with zero errors on any of the three targets.

## Assumptions

- The gRPC frontend is already deployed and functional on Modal A10G; no frontend code changes are required in this phase.
- Existing generated stubs are structurally correct; only the `py.typed` marker is missing.
- The benchmark corpus and concurrency settings from Phase 4.1 are reused unchanged for the gRPC-direct target, ensuring comparability with committed baselines.
- Non-streaming (unary) `ChatService.Complete` is the only RPC needed; streaming is deferred to Phase 5.
- The three-way benchmark requires Modal credentials and pre-staged model weights, consistent with the Phase 4.1 manual gate precedent.
- TLS is out of scope; the client connects via plaintext gRPC, matching existing proxy-to-frontend patterns.
