# Feature Specification: Phase 7 — Demo Polish

**Feature Branch**: `012-demo-polish`
**Created**: 2026-05-03
**Status**: Draft
**Input**: Phase 7 section of `docs/PLAN.md`

## User Scenarios & Testing *(mandatory)*

### User Story 1 — New Viewer Runs the Demo Locally (Priority: P1)

A developer who has never seen the project reads the README, follows the onboarding steps, and within ten minutes has the proxy and frontend running locally on their M2 with all three `demo/` scripts producing real completions.

**Why this priority**: This is the primary deliverable of Phase 7. Every other deliverable exists to support this experience.

**Independent Test**: Can be fully tested by cloning the repo, running the bootstrap command, and executing each `demo/` script. Success means all three scripts return valid completions against a locally-deployed frontend with no manual troubleshooting.

**Acceptance Scenarios**:

1. **Given** a clean clone of the repo, **When** the viewer follows the README quickstart, **Then** both the proxy and frontend are running locally in under five minutes.
2. **Given** a running local environment, **When** the viewer runs `demo/curl-rest.sh`, **Then** a valid OpenAI-format chat completion is returned via the proxy REST path.
3. **Given** a running local environment, **When** the viewer runs `demo/openai-sdk.py`, **Then** a valid completion is returned using the `openai` Python SDK via the proxy REST path.
4. **Given** a running local environment, **When** the viewer runs `demo/grpc-direct.py`, **Then** a valid completion is returned using `VllmGrpcClient` directly, with no proxy involved.
5. **Given** a running local environment, **When** the viewer runs `demo/streaming.py`, **Then** tokens stream to the terminal via SSE through the proxy.

---

### User Story 2 — Reviewer Reads the Benchmark Summary (Priority: P2)

A sympathetic but skeptical technical reviewer reads `docs/benchmarks/summary.md` and comes away with a fair, honest picture of measured wire-overhead results across all three access paths (REST / gRPC-via-proxy / gRPC-direct) for both streaming and non-streaming.

**Why this priority**: The wire-overhead thesis is the project's core claim. The summary must present results that are honest and reproducible — no metric selectively omitted.

**Independent Test**: A reviewer unfamiliar with the project reads `docs/benchmarks/summary.md` and can understand what was measured, how, and what the results show — including any cases where gRPC was neutral or slower.

**Acceptance Scenarios**:

1. **Given** the benchmark summary, **When** a reviewer reads it, **Then** headline P50/P95/P99 latency and wire-size numbers for REST, gRPC-via-proxy, and gRPC-direct are all present for non-streaming chat.
2. **Given** the benchmark summary, **When** a reviewer reads it, **Then** TTFT and TPOT numbers for streaming are present for all three paths.
3. **Given** the benchmark summary, **When** a reviewer reads it, **Then** the corpus, concurrency levels, hardware (M2 Pro for local; Modal A10G for GPU), and vLLM version are documented.
4. **Given** the benchmark summary, **When** a reviewer checks a number against `docs/benchmarks/`, **Then** every headline number traces directly to a committed JSON result file.

---

### User Story 3 — Viewer Understands the Project from the README (Priority: P3)

A Python/ML developer who has not heard of the project reads the README and, without running anything, understands what the project does, what the wire-overhead thesis is, and what the measured results showed.

**Why this priority**: The README is the project's public face. It sets context before the demo scripts are run.

**Independent Test**: The README covers: (a) what the project is, (b) the wire-overhead thesis, (c) how to run the demo in under five minutes, (d) a one-paragraph summary of headline benchmark results.

**Acceptance Scenarios**:

1. **Given** the README, **When** a viewer reads it, **Then** they can articulate the wire-overhead thesis without additional context.
2. **Given** the README, **When** a viewer reads it, **Then** they understand the three access paths (REST via proxy, gRPC via proxy, gRPC direct) and why each exists.
3. **Given** the README, **When** a viewer follows the "run locally" section, **Then** all steps succeed on a fresh macOS install with `uv` and `modal` already available.

---

### Edge Cases

- What if the viewer does not have Modal credentials? The local-only demo path (frontend + proxy both on M2) must work without Modal.
- What if a `demo/` script is run without the proxy or frontend running? Each script must fail with a clear error message, not a Python traceback.
- What if the benchmark summary shows gRPC was slower than REST in some cases? Results must be reported honestly — no selective omission.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The README MUST contain a "What is this?" section, a "Wire-overhead thesis" section, a "Run locally in under 5 minutes" quickstart, and a one-paragraph benchmark results summary.
- **FR-002**: A `demo/` directory MUST exist at the repository root with exactly four scripts: `curl-rest.sh`, `openai-sdk.py`, `grpc-direct.py`, and `streaming.py`.
- **FR-003**: Each `demo/` script MUST be annotated with inline comments explaining each step and MUST be runnable end-to-end against a locally-deployed frontend without modification.
- **FR-004**: `demo/grpc-direct.py` MUST use `VllmGrpcClient` and MUST NOT involve the proxy.
- **FR-005**: `demo/streaming.py` MUST produce SSE token output visible in the terminal via the proxy REST path.
- **FR-006**: `docs/benchmarks/summary.md` MUST cover P50/P95/P99 latency and wire bytes for REST, gRPC-via-proxy, and gRPC-direct for non-streaming chat completions.
- **FR-007**: `docs/benchmarks/summary.md` MUST cover TTFT and TPOT for all three paths for streaming chat completions.
- **FR-008**: `docs/benchmarks/summary.md` MUST document corpus, concurrency levels, hardware, and vLLM version; every headline number MUST trace to a committed JSON result file.
- **FR-009**: The README quickstart MUST be reproducible from a clean macOS machine that has `uv` and `modal` already installed.
- **FR-010**: All `demo/` scripts MUST pass `ruff` lint and `mypy` (non-strict is acceptable for demo scripts); `curl-rest.sh` MUST pass `shellcheck`.
- **FR-011**: The `bench_modal.py` benchmark orchestrator MUST write Phase 6 completions results to three committed JSON files in `docs/benchmarks/`: `phase-6-completions-native.json`, `phase-6-completions-proxy.json`, `phase-6-completions-grpc-direct.json`.
- **FR-012**: `docs/benchmarks/phase-6-completions-comparison.md` MUST be reformatted so its latency and throughput section uses the same concurrency-split table layout with explicit Δ vs native columns as `phase-4.2-three-way-comparison.md` and `phase-5-streaming-comparison.md` — one table per concurrency level, separate sub-sections per input type (text-prompt and prompt-embed).
- **FR-013**: `scripts/python/regen_bench_reports.py` MUST support regenerating Phase 5 streaming and Phase 6 completions markdown reports from their committed JSON files, so all phases (3 through 6) can be reproduced without a GPU run.
- **FR-014**: All benchmark comparison documents visible to a new viewer (`phase-4.2-three-way-comparison.md`, `phase-5-streaming-comparison.md`, `phase-6-completions-comparison.md`) MUST use consistent layout: concurrency-grouped tables, explicit Δ columns, matching column ordering.

### Key Entities

- **`demo/` scripts**: Four standalone runnable files — `curl-rest.sh`, `openai-sdk.py`, `grpc-direct.py`, `streaming.py` — each self-contained and annotated.
- **`docs/benchmarks/summary.md`**: A human-readable synthesis of all committed benchmark JSON files, covering all three paths and both streaming/non-streaming.
- **`README.md`**: Updated top-level project documentation covering thesis, architecture, quickstart, and benchmark headline.
- **Phase 6 JSON files**: Three new committed benchmark result files — `phase-6-completions-{native,proxy,grpc-direct}.json` — each a `BenchmarkRun` with all results for that path (both text and embed input types).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new viewer can clone the repo, follow the README, and have all four `demo/` scripts running against a local frontend in under ten minutes.
- **SC-002**: `docs/benchmarks/summary.md` presents headline numbers for all three paths (REST, gRPC-proxy, gRPC-direct) in both streaming and non-streaming modes — zero paths omitted.
- **SC-003**: Every headline number in every benchmark comparison document traces to a committed JSON result file in `docs/benchmarks/`.
- **SC-004**: All four `demo/` scripts run without modification against a locally-deployed frontend.
- **SC-005**: `make check` remains green after all Phase 7 changes.
- **SC-006**: `phase-6-completions-comparison.md` uses the same concurrency-split, delta-explicit table format as the Phase 4.2 and Phase 5 reports — a new viewer can read any comparison document with the same mental model.
- **SC-007**: `make regen-bench-reports` regenerates correct markdown for all phases (3–6) from committed JSON without a GPU run.

## Assumptions

- Phase 6 completions JSON files do not yet exist in `docs/benchmarks/` — they must be generated by re-running `make bench-modal` as part of this phase.
- The M2 Pro local environment (CPU-only vLLM or vllm-metal) is sufficient for the local-only demo path; Modal is the GPU path.
- Demo scripts target `Qwen/Qwen3-0.6B` (the project's standard model) with a fixed seed for deterministic output.
- `uv` and `modal` are prerequisites for the viewer; the README may assume these are installed but MUST link to install instructions.
- No new proto changes, RPC additions, or package additions are in scope for Phase 7.
- The optional screen capture / asciinema recording is out of scope for this phase.
