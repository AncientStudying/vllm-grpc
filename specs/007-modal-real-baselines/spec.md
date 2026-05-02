# Feature Specification: Phase 4.1 — Real Comparative Baselines (Modal)

**Feature Branch**: `007-modal-real-baselines`
**Created**: 2026-05-02
**Status**: Draft
**Input**: User description: "phase 4.1"

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Run End-to-End GPU Benchmarks with One Command (Priority: P1)

A developer working on the wire-overhead thesis wants to collect real, GPU-backed latency and wire-size numbers for both the REST and gRPC paths. Today, the committed baseline files contain stub data from test runs. This story delivers the ability to replace those stubs with real measurements from a single command that orchestrates both deployments sequentially.

**Why this priority**: Without real numbers, the project's core thesis cannot be evaluated. This is the sole deliverable that turns prototype infrastructure into evidence.

**Independent Test**: Run the benchmark command and verify it produces two populated result files plus a comparison report, all without any manual steps between the two deployments.

**Acceptance Scenarios**:

1. **Given** valid cloud credentials and the benchmark harness available, **When** the developer runs the benchmark command, **Then** the REST deployment runs, collects results, shuts down, the gRPC deployment runs, collects results, shuts down, and a comparison report is written to the benchmarks directory — all without manual intervention.

2. **Given** a completed benchmark run, **When** the developer inspects the comparison report, **Then** P50, P95, and P99 latency, wire bytes per request and response, and throughput at each concurrency level are present for both REST and gRPC, with no metric selectively omitted.

3. **Given** a completed benchmark run, **When** cold-start provisioning is slow, **Then** provisioning time is recorded in run metadata but is excluded from per-request latency numbers in the report.

---

### User Story 2 — Compare Two Existing Result Files Offline (Priority: P2)

A developer has previously saved two result files (one REST, one gRPC) and wants to re-generate the comparison report without re-running both deployments. This supports iterating on the report format or re-comparing results after a code change without incurring GPU cost.

**Why this priority**: Offline comparison avoids expensive re-runs when only the report format changes or when a developer wants to inspect archived results.

**Independent Test**: Run the compare command with two existing result files and confirm a valid comparison report is produced in under 30 seconds with no network calls.

**Acceptance Scenarios**:

1. **Given** two existing result files on disk, **When** the developer invokes the compare command with those file paths, **Then** a comparison report is generated from the local files without contacting any remote service.

2. **Given** a mismatched pair of result files (different corpus or schema), **When** the developer invokes the compare command, **Then** an informative error is displayed and no partial report is written.

---

### User Story 3 — Detect Benchmark Regressions in CI (Priority: P3)

A developer merging a change to the proxy or frontend wants automated confirmation that the change has not regressed the measured performance metrics. The CI system compares the new run's results against the committed baseline and posts a summary comment on the pull request.

**Why this priority**: Regression detection closes the feedback loop so future phases cannot silently degrade the numbers gathered here.

**Independent Test**: Open a sample pull request touching a proxy or frontend file and verify CI posts a benchmark comment showing a before/after comparison.

**Acceptance Scenarios**:

1. **Given** a pull request that touches proxy or frontend source files, **When** CI runs the benchmark job, **Then** a comment is posted on the PR showing whether each metric improved, regressed, or is unchanged relative to the committed baseline.

2. **Given** a pull request where a metric regresses beyond an acceptable threshold, **When** CI posts the comment, **Then** the comment clearly identifies which metrics regressed and by how much, so the author can decide whether the regression is intentional.

---

### Edge Cases

- What happens when a cloud deployment fails to become healthy before the timeout? — The orchestration run should abort cleanly, report which deployment failed, and not write partial result files.
- What happens when one result file is corrupted or missing? — The compare step should fail with a clear error rather than producing a misleading partial report.
- What happens when the benchmark corpus produces zero successful responses? — The result file must record the failure and the report must surface it rather than computing metrics over empty data.
- What if both deployments use different model versions or GPU types? — Run metadata must include enough information (model ID, GPU type) for the discrepancy to be detected on inspection.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST run both the REST and gRPC benchmarks sequentially from a single command, managing all deployment lifecycle steps automatically.
- **FR-002**: The system MUST measure and record cold-start (provisioning) time separately from per-request latency, and MUST exclude cold-start from reported P50/P95/P99 figures.
- **FR-003**: Each result file MUST embed traceability metadata: the source code revision, the machine that produced the run, the deployment identifier, and the GPU type.
- **FR-004**: The comparison report MUST present P50, P95, and P99 latency; wire bytes per request and per response; and throughput at each concurrency level for both REST and gRPC — with no metric selectively omitted.
- **FR-005**: The system MUST support an offline compare path: given two existing result files, produce a comparison report without contacting any remote service.
- **FR-006**: Committed baseline result files MUST be used by CI to detect metric regressions on pull requests that touch proxy or frontend source files.
- **FR-007**: The CI job MUST post a benchmark summary comment on any qualifying pull request, showing per-metric before/after comparison against the baseline.
- **FR-008**: On deployment health-check timeout or any partial failure, the orchestration run MUST exit with a non-zero status and a clear error message; partial result files MUST NOT be written.

### Key Entities

- **RunResult**: A single benchmark run's outcome — includes per-request latency samples, wire-byte measurements, throughput figures, and run metadata (revision, machine, deployment ID, GPU type, cold-start duration).
- **RunMeta**: The traceability record attached to each RunResult — uniquely identifies when, where, and on what hardware a run was produced.
- **ComparisonReport**: The human-readable document produced by diffing a REST RunResult and a gRPC RunResult — contains head-to-head tables and an honest summary narrative.
- **BaselineFile**: A committed RunResult that CI uses as the reference point for regression detection.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The benchmark command completes both deployments and writes a comparison report without any manual steps, in a single unattended run.
- **SC-002**: The comparison report contains valid, non-zero P50/P95/P99 latency figures and wire-byte measurements for both REST and gRPC paths.
- **SC-003**: Cold-start duration is recorded in every run's metadata and is never included in the per-request latency percentiles.
- **SC-004**: The offline compare command produces a comparison report from two local files in under 30 seconds.
- **SC-005**: CI posts a benchmark regression comment on 100% of qualifying pull requests within the normal CI run time.
- **SC-006**: Baseline result files are committed and the CI regression check passes against them on the first green run.

## Assumptions

- Phase 3.2 (local proxy → cloud gRPC tunnel) is merged and its deployment is reproducible from the developer's machine.
- Phase 3.1 (REST comparison deployment) is available and deployable.
- Phase 4 (benchmark harness with corpus, compare module, and CI job skeleton) is merged and functional.
- The benchmark corpus used for REST and gRPC runs is identical, ensuring the comparison is apples-to-apples.
- Only one GPU-backed deployment can be live at a time due to the ephemeral nature of cloud functions; sequential runs are the required approach.
- The developer has valid cloud credentials configured locally before running the benchmark command.
- The CI environment does not have access to cloud GPU credentials; CI regression detection uses locally committed baseline files, not live re-runs.
- Baseline JSON files are committed from the developer's machine after the first successful run and are treated as the reference point for all subsequent CI regression checks.
