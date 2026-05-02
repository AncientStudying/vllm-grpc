# Feature Specification: Modal gRPC Frontend Deployment

**Feature Branch**: `005-modal-grpc-frontend`
**Created**: 2026-05-01
**Status**: Draft
**Input**: User description: "implement Phase 3.1"

## Clarifications

### Session 2026-05-01

- Q: When should cloud deployments tear down relative to the smoke test? → A: The smoke-test script manages the full lifecycle (start → test → teardown) as a single self-contained command. No persistent deployment is left running after the script exits.
- Q: Should model weights be pre-staged in persistent cloud storage to make cold-start reproducible, or downloaded fresh on each run? → A: Pre-stage weights in a persistent cloud storage volume during a one-time setup step. Cold start = container provision + server init only (~60–90 s, reproducible). Avoids variable HuggingFace download time on every run.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Deploy gRPC Frontend to Modal (Priority: P1)

A developer wants to bring up the gRPC frontend on a cloud GPU so that the proxy bridge can be exercised against a real model instead of local stubs. They run a single command, wait for the container to start, and have a live gRPC endpoint the proxy can target.

**Why this priority**: This is the gate for everything else in the phase. Without a deployable gRPC frontend, neither the smoke test nor the REST comparison deployment are achievable. It is also the direct precondition for Phase 4.1 real benchmarks.

**Independent Test**: Can be tested by running the deploy command, sending a `ChatService.Complete` request from the proxy with a fixed seed and a short prompt, and confirming a non-empty completion is returned.

**Acceptance Scenarios**:

1. **Given** the developer has authenticated with the cloud GPU provider, **When** they run the gRPC frontend deploy command, **Then** the container starts, loads the model, and the gRPC server accepts incoming connections within a documented cold-start window.
2. **Given** the gRPC frontend is running on a cloud GPU, **When** the proxy sends a `ChatService.Complete` request with `seed=42` and `max_tokens=20`, **Then** the frontend returns a deterministic completion.
3. **Given** the gRPC frontend deploy script is run a second time on a fresh machine with no local model cache, **When** the deploy command completes, **Then** the endpoint is reachable and the same deterministic completion is produced.

---

### User Story 2 — Run End-to-End Smoke Test via the Proxy (Priority: P2)

A developer wants to confirm the full path — local proxy translating REST → gRPC → cloud GPU vLLM → gRPC response → REST response — works before any benchmarks are run. They run a single curl command and see a valid chat completion response.

**Why this priority**: Validates the proxy's `FRONTEND_ADDR` wiring works with a remote endpoint, not just localhost. Catches networking, serialization, or cold-start issues before the benchmark harness tries to use the deployment.

**Independent Test**: Can be fully tested by setting `FRONTEND_ADDR` to the Modal gRPC endpoint, starting the proxy locally, and running `scripts/curl/chat-nonstreaming-modal.sh`. Delivers a working end-to-end demonstration on real hardware.

**Acceptance Scenarios**:

1. **Given** the proxy is started with `FRONTEND_ADDR` pointing at the cloud gRPC endpoint, **When** the smoke-test curl script runs, **Then** it prints a valid OpenAI-format chat completion with no errors.
2. **Given** the smoke-test curl script uses a fixed seed, **When** it is run twice against the same deployed endpoint, **Then** both responses contain identical content.
3. **Given** the gRPC frontend has not been deployed, **When** the smoke-test curl script runs, **Then** the proxy returns a clear error indicating the upstream is unreachable, not a silent failure.

---

### User Story 3 — Deploy REST Comparison Target to Modal (Priority: P2)

A developer wants a vLLM native OpenAI REST server running on the same cloud GPU tier so that Phase 4.1 can run identical request corpora against both endpoints on equal hardware. They deploy the REST target with a single command and confirm it returns completions.

**Why this priority**: Without a REST baseline on the same hardware as the gRPC frontend, the head-to-head comparison in Phase 4.1 is meaningless. Shares the same priority as the smoke test because both are required before Phase 4.1 can start.

**Independent Test**: Can be tested independently by running the REST deploy command and sending a direct `POST /v1/chat/completions` request to the cloud-hosted OpenAI endpoint. No proxy required.

**Acceptance Scenarios**:

1. **Given** the developer runs the REST server deploy command, **When** the container starts, **Then** `GET /health` (or equivalent) returns 200 OK and `POST /v1/chat/completions` with a fixed seed returns a valid completion.
2. **Given** both the gRPC frontend and the REST server have been deployed, **When** both are sent the same prompt with `seed=42`, **Then** their responses contain the same generated text (token-level equivalence, same model, same sampling params).

---

### User Story 4 — Reproduce Deployment from a Fresh Machine (Priority: P3)

A developer on a new machine (or CI environment) wants to reproduce the full deployment without any tribal knowledge. They follow documented steps, run the bootstrap sequence, and have both cloud endpoints running.

**Why this priority**: Reproducibility is a first-class requirement per Constitution V (Honest Measurement). A deployment that only works on one developer's machine is not a valid baseline.

**Independent Test**: Can be tested by following the ADR setup steps on a machine that has only the project repo and cloud provider credentials installed. Both deploy commands succeed without additional manual steps.

**Acceptance Scenarios**:

1. **Given** a machine with only project repo access and cloud provider authentication, **When** the documented setup sequence is followed, **Then** both deploy commands succeed and both endpoints serve completions.
2. **Given** the ADR documents cold-start latency, **When** a developer reads it, **Then** they can predict whether a given deployment will be ready within the budget before starting a benchmark run.

---

### Edge Cases

- What happens when the cloud container times out during model load (model download stalls)?
- What happens if the lifecycle-managed smoke-test script is interrupted (e.g., Ctrl+C) before teardown completes — does the cloud container need to be cleaned up manually?
- What happens if `FRONTEND_ADDR` is set to a cloud gRPC endpoint but TLS is expected (insecure channel vs TLS channel mismatch)?
- What happens when both deploy commands are run simultaneously and they compete for the same GPU pool allocation?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A deployable app definition MUST exist for the gRPC frontend that packages the `vllm-grpc-frontend` workspace package together with vLLM on a Linux/CUDA container, targeting an A10G GPU. The container MUST load model weights from a pre-staged persistent cloud storage volume rather than downloading them at runtime.
- **FR-002**: A deployable app definition MUST exist for vLLM's native OpenAI REST server on the same GPU tier (A10G), serving the same model (`Qwen/Qwen3-0.6B`), as the REST comparison target for Phase 4.1. It MUST use the same pre-staged weights volume as FR-001.
- **FR-009**: A one-time weight pre-staging script MUST exist that downloads `Qwen/Qwen3-0.6B` into a persistent cloud storage volume. This script MUST be idempotent (safe to re-run if weights are already present) and MUST be documented as a prerequisite in the ADR.
- **FR-003**: The gRPC frontend deployment MUST accept `FRONTEND_HOST`, `FRONTEND_PORT`, and `MODEL_NAME` environment variables, consistent with the local development configuration.
- **FR-004**: The proxy MUST route gRPC calls to whatever address `FRONTEND_ADDR` specifies, with the cloud gRPC tunnel URL as a valid value, requiring no code changes — only an environment variable update.
- **FR-005**: A smoke-test script MUST manage the full deployment lifecycle end-to-end: start the cloud gRPC frontend, wait for it to be healthy, send a test request through the full proxy → cloud gRPC frontend → vLLM path, verify the response, then tear the deployment down. The entire sequence MUST complete from a single invocation — no manual teardown step required.
- **FR-006**: Cold-start latency for both cloud deployments MUST be observed, recorded, and documented so it can be excluded from benchmark per-request timing in Phase 4.1.
- **FR-007**: An ADR (`docs/decisions/0002-modal-deployment.md`) MUST document: container build approach, required environment variables, cold-start behavior and observed timing, teardown behavior (automatic on script exit), and prerequisites for a new developer to reproduce the deployment.
- **FR-008**: Both smoke-test scripts MUST be runnable with a single command that encapsulates start, test, and teardown. No manual container-build, teardown, or cleanup steps are required from the developer.

### Key Entities

- **gRPC Frontend Deployment**: A cloud-hosted instance of the `vllm-grpc-frontend` service, backed by a GPU, accessible at a stable network address for the duration of the lifecycle-managed smoke-test script. The deployment is started and torn down automatically by the script; it does not persist beyond the script's execution.
- **REST Comparison Target**: A cloud-hosted instance of vLLM's native OpenAI server, backed by the same GPU tier, used exclusively as the REST baseline for head-to-head comparison.
- **Cold-Start Window**: The elapsed time from smoke-test script invocation to first successful request, composed of container provisioning time and server startup time. Model download is excluded because weights are pre-staged in a persistent volume. Documented per deployment; excluded from per-request latency metrics.
- **Weight Volume**: A persistent cloud storage volume holding the pre-downloaded `Qwen/Qwen3-0.6B` model weights. Created once via the pre-staging script and shared by both the gRPC frontend and REST comparison target containers.
- **Smoke Test**: A single end-to-end request through the full proxy → cloud gRPC frontend path that confirms functional correctness before benchmarks are run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Both the gRPC frontend and the REST server can be deployed and serve completions from a fresh machine with only cloud provider authentication as a prerequisite.
- **SC-002**: The smoke-test script produces a valid, deterministic completion (`seed=42`, non-empty content) when the proxy is pointed at the cloud gRPC endpoint.
- **SC-003**: The gRPC frontend and the REST server, given identical prompts and `seed=42`, return token-level equivalent completions, confirming the bridge does not alter generation.
- **SC-004**: Cold-start timing for both deployments (provisioning + server init, excluding model download) is documented in the ADR to within ±10 seconds, observed on at least two separate runs after weights have been pre-staged.
- **SC-005**: Switching the proxy from the local gRPC frontend to the cloud gRPC frontend requires changing only `FRONTEND_ADDR` — no proxy code or configuration file changes.
- **SC-006**: The lifecycle-managed smoke-test script (start → test → teardown) completes end-to-end in under 15 minutes (including cold-start) on a developer machine.

## Assumptions

- The existing Phase 3 `vllm-grpc-frontend` package is environment-agnostic: it requires no macOS-specific code and runs on Linux/CUDA without modification.
- The cloud provider's Python-native API handles container image build, provisioning, and teardown; no external Docker registry or Kubernetes cluster is needed.
- A one-time weight pre-staging step is a documented prerequisite. The persistent weight volume must exist before either smoke-test script is run; the pre-staging script handles this and is idempotent.
- The cloud gRPC tunnel URL is stable for the lifetime of a single deploy invocation (i.e., it does not rotate mid-run); this is required for the benchmark harness to hold the connection across multiple requests.
- `vllm==0.20.0` is the correct version for the GPU container, consistent with ADR 0001 (Linux/CUDA, A10G).
- The proxy's existing `FRONTEND_ADDR` env var (defaulting to `localhost:50051`) is sufficient to redirect gRPC calls to the cloud endpoint; no new env var is required.
- Benchmark orchestration (running both endpoints sequentially and comparing results) is out of scope for this phase; that is Phase 4.1.
- TLS is not required for the cloud gRPC connection in this phase; the tunnel URL uses an insecure channel, consistent with the local development setup.
- Modal is the cloud provider, consistent with ADR 0001 and the existing `scripts/python/verify_prompt_embeds_modal.py` pattern.
