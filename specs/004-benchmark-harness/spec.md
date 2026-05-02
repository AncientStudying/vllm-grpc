# Feature Specification: Metrics and Benchmark Harness

**Feature Branch**: `004-benchmark-harness`
**Created**: 2026-05-01
**Status**: Implemented
**Input**: User description: "Phase 4 — Metrics and Test Harness (docs/PLAN.md)"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run Head-to-Head Benchmark (Priority: P1)

A developer wants to compare the performance of the proxy-bridge path against the native server path to understand whether the bridge is faster, slower, or neutral on each measured metric.

**Why this priority**: This is the core deliverable of Phase 4 — generating honest, reproducible performance numbers. Every subsequent phase depends on having this measurement infrastructure in place.

**Independent Test**: Can be fully tested by invoking a single benchmark command and verifying that a report is produced comparing both paths on all defined metrics, completing in under five minutes.

**Acceptance Scenarios**:

1. **Given** both the proxy-bridge and the native server are running, **When** the developer invokes the benchmark command, **Then** a head-to-head report is produced covering latency (P50, P95, P99), wire bytes per request and per response, throughput, and processing overhead per request for both paths.
2. **Given** the developer runs the benchmark, **When** the run completes, **Then** the total elapsed time is under five minutes on the development machine.
3. **Given** the benchmark completes, **When** the developer reads the report, **Then** the report clearly and unambiguously indicates which path is faster, slower, or neutral on each metric.
4. **Given** one of the two target endpoints is unavailable at benchmark start, **When** the developer runs the benchmark, **Then** the harness reports an actionable error rather than producing a partial or misleading report.

---

### User Story 2 - Capture and Commit Phase 3 Baseline (Priority: P2)

A developer needs to record and commit the benchmark numbers from Phase 3's non-streaming chat completion path, establishing a reference point for all future phases.

**Why this priority**: The committed baseline is what makes future regression detection meaningful. Without it, automated comparisons have nothing to compare against.

**Independent Test**: Can be tested by verifying that a baseline report exists at the documented location in the repository and contains Phase 3 non-streaming measurements across all metric categories.

**Acceptance Scenarios**:

1. **Given** the benchmark harness is operational, **When** the developer runs it against the Phase 3 non-streaming bridge, **Then** the results can be saved in a format that is committed to the repository as the canonical Phase 3 baseline.
2. **Given** the Phase 3 baseline is committed, **When** a future developer reads it, **Then** they can understand the measured performance of the Phase 3 bridge without running the benchmark themselves.

---

### User Story 3 - Automated Regression Detection on Pull Requests (Priority: P3)

When a pull request modifies the proxy or frontend, an automated check runs the benchmark and posts a comparison comment showing any performance changes relative to the committed baseline.

**Why this priority**: This is the quality gate that ensures performance regressions are visible before merging. It converts the measurement infrastructure into an ongoing safeguard for future phases.

**Independent Test**: Can be tested by opening a sample pull request that touches proxy or frontend code and verifying that an automated benchmark comparison comment is posted.

**Acceptance Scenarios**:

1. **Given** a pull request is opened that modifies proxy or frontend code, **When** automated checks run, **Then** a benchmark comparison comment is posted on the PR showing results against the committed baseline.
2. **Given** a PR introduces a measurable regression (any metric degrades more than 10% vs. baseline), **When** the automated check runs, **Then** the regression is clearly flagged in the comment.
3. **Given** a PR has no performance regressions, **When** the automated check runs, **Then** the comment confirms no regressions were detected.
4. **Given** no committed baseline exists yet, **When** the automated check runs, **Then** the check posts a notification rather than failing silently.

---

### User Story 4 - Extend the Harness with a New Metric (Priority: P4)

A developer working on a future phase wants to add a new measurement (such as time-to-first-token for streaming completions) to the harness without disrupting existing metrics.

**Why this priority**: The harness must be extensible to support Phase 5 streaming metrics. Lower priority than the core measurement capability, but essential for the harness's long-term value.

**Independent Test**: Can be tested by following the written extension guide to add a custom metric and verifying it appears in the next benchmark report without affecting existing metrics.

**Acceptance Scenarios**:

1. **Given** the extension documentation, **When** a developer follows it to add a new metric, **Then** the new metric appears in subsequent benchmark reports without modifying existing metrics or breaking existing report output.

---

### Edge Cases

- What happens when one of the two target endpoints is unavailable at benchmark start?
- How does the report handle a run where some requests produce errors rather than valid completions?
- What happens when a request exceeds a maximum expected response time?
- How does the automated PR check behave when no committed baseline exists?
- When the committed baseline was produced on different hardware: the `hostname` field in `RunMeta` makes the discrepancy visible in the report; no metric normalization is performed; regression thresholds apply regardless of hardware. Comparing runs across different machines is a known limitation and the user's responsibility to avoid.

## Clarifications

### Session 2026-05-01

- Q: Should FR-006 require both CSV and JSON, or leave the format choice open? → A: Both CSV and JSON are always produced in every run; FR-006 updated accordingly.
- Q: What is the accepted policy when baseline and new run are on different hardware? → A: Known limitation — `hostname` is recorded in `RunMeta` so the discrepancy is visible, but no normalization is performed and regression thresholds apply regardless; users are responsible for comparing same-hardware runs.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST replay a fixed, reproducible corpus of requests against two configurable target endpoints and collect measurements from both in a single run.
- **FR-002**: The system MUST measure and report wire bytes transferred per request and per response for each target endpoint.
- **FR-003**: The system MUST measure and report end-to-end latency at the P50, P95, and P99 percentiles for each endpoint.
- **FR-004**: The system MUST measure and report throughput (completions per second) at a configurable concurrency level for each endpoint.
- **FR-005**: The system MUST measure and report processing overhead attributable to the proxy translation layer per request, separately from model inference time.
- **FR-006**: The system MUST emit both a CSV report and a JSON report containing all measurements for both endpoints. Both formats are always produced in a single run; CSV enables spreadsheet import and JSON enables programmatic comparison.
- **FR-007**: The system MUST emit a human-readable markdown summary alongside the machine-readable report, explicitly indicating which path is faster, slower, or neutral on each metric.
- **FR-008**: A full benchmark run MUST complete within five minutes on the project's development machine.
- **FR-009**: The system MUST support committing a named baseline snapshot from a completed benchmark run to the repository.
- **FR-010**: Automated pull request checks MUST run the benchmark when changes are made to the proxy or frontend, and MUST post a comment comparing results to the committed baseline.
- **FR-011**: The automated check MUST flag a regression when any measured metric degrades more than 10% relative to the committed baseline.
- **FR-012**: The automated check MUST handle the absence of a committed baseline gracefully, posting a notification rather than failing silently.
- **FR-013**: The harness MUST be documented such that a developer can add a new metric by following written instructions, without modifying the core reporting logic.

### Key Entities

- **Benchmark Run**: A complete execution of the harness against both target endpoints, producing a full set of measurements across all defined metrics.
- **Request Corpus**: A fixed, reproducible set of chat completion requests used for all benchmark runs; inputs are deterministic (fixed random seed).
- **Measurement**: A recorded value for a specific metric (latency percentile, wire bytes, throughput, or processing overhead) for a specific endpoint within a run.
- **Report**: The output of a benchmark run — a machine-readable file and a markdown summary — containing all measurements for both endpoints side-by-side.
- **Baseline**: A committed reference report representing the measured performance of a specific named phase (e.g., Phase 3 non-streaming), used as the comparison target for regression detection.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A single benchmark command produces a complete head-to-head comparison report in under 5 minutes on the development machine.
- **SC-002**: The report covers all five metric categories: latency (P50/P95/P99), wire bytes per request and per response, throughput, and processing overhead per request.
- **SC-003**: The Phase 3 non-streaming baseline is committed to the repository and is readable by a developer without running the benchmark.
- **SC-004**: 100% of pull requests touching proxy or frontend code receive an automated benchmark comparison comment before merge.
- **SC-005**: Regressions of 10% or more on any measured metric are automatically flagged on the PR.
- **SC-006**: A developer who has not previously worked on the harness can follow the extension guide and add a new metric in under 30 minutes.

## Assumptions

- The Phase 3 non-streaming chat completion bridge is fully operational before Phase 4 work begins.
- The request corpus uses a fixed random seed to ensure reproducibility across runs.
- The benchmark covers only the non-streaming chat completion path from Phase 3; streaming support is out of scope for this phase.
- Concurrency levels in the benchmark are representative of developer testing (e.g., 1, 4, and 8 concurrent requests), not production-scale load.
- The automated PR check uses recorded fixtures or a stub model rather than a live model, to keep automated checks fast and cost-free.
- "Processing overhead per request" covers translation and forwarding time at the proxy only — model inference time is explicitly excluded.
- The native server endpoint used for head-to-head comparison runs the same model on the same hardware to ensure a fair comparison.
- Report output format (CSV or JSON for machine-readable, markdown for human-readable) is fixed for this phase; format extensibility is out of scope.
