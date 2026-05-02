# Feature Specification: Phase 3.2 — Local Proxy → Modal gRPC Tunnel

**Feature Branch**: `006-modal-grpc-tunnel`
**Created**: 2026-05-02
**Status**: Draft
**Input**: User description: "phase 3.2"

## Clarifications

### Session 2026-05-02

- **Context**: Phase 3.1 ran both proxy and gRPC frontend as subprocesses inside the same Modal container. No request bytes traversed an external network.
- **Decision for Phase 3.2**: The proxy runs on the developer's local workstation; the gRPC frontend runs on a cloud GPU. A TCP tunnel exposes the cloud gRPC port to the local proxy. This is the only topology that exercises the wire-efficiency thesis. Modal is the only cloud GPU environment currently available.
- **Primary unknown**: Whether the cloud TCP tunnel mechanism correctly forwards persistent HTTP/2 connections with gRPC keep-alive frames. This must be confirmed empirically. If it does not work, failure behavior must be documented and an alternative approach identified before the phase is considered complete.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Bring Up gRPC Frontend with External Tunnel (Priority: P1)

A developer wants to run the gRPC frontend on a cloud GPU and expose its port to their local machine via a TCP tunnel, so they can point a locally-running proxy at it. They run a single command, wait for the frontend to become ready, and receive a tunnel address they can export as an environment variable.

**Why this priority**: This is the gate for everything else in the phase. Without an externally-reachable gRPC frontend, the local-proxy → cloud-gRPC topology cannot be tested. It is also the direct precondition for Phase 4.1 real-network benchmarks.

**Independent Test**: Run the serve command; observe that a `FRONTEND_ADDR=<host>:<port>` line is printed to the terminal within the documented cold-start window. Set that env var, start the proxy locally, and confirm `GET /healthz` returns 200.

**Acceptance Scenarios**:

1. **Given** the developer has authenticated with the cloud provider and pre-staged model weights, **When** they run the serve command, **Then** the cloud container starts, loads the model, and prints a stable tunnel address to the local terminal within the documented cold-start window.
2. **Given** the tunnel address has been printed, **When** the developer exports it as `FRONTEND_ADDR` and starts the proxy locally, **Then** `GET /healthz` on the local proxy returns 200, confirming the proxy has successfully reached the cloud gRPC frontend.
3. **Given** the serve command is running, **When** the developer presses Ctrl+C in the terminal, **Then** the cloud container tears down automatically with no manual cleanup required.

---

### User Story 2 — Send a Request Over the Real Network Path (Priority: P1)

A developer has the local proxy running and pointed at the cloud gRPC frontend. They want to confirm that a full request travels from their local machine over the network as protobuf, is processed by vLLM on the cloud GPU, and returns a valid response. This is the first real exercise of the wire-efficiency path.

**Why this priority**: Equally critical to US1 — without a completed round-trip, the phase exit criteria are not met. Phase 4.1 benchmarks and all future wire-efficiency claims depend on this path working.

**Independent Test**: With the proxy running locally and `FRONTEND_ADDR` pointing at the cloud tunnel, run the existing smoke-test curl script. Observe a valid OpenAI-format chat completion response with a non-empty `content` field.

**Acceptance Scenarios**:

1. **Given** the local proxy is running with `FRONTEND_ADDR` set to the cloud tunnel address, **When** the smoke-test curl script is run with `seed=42` and `max_tokens=20`, **Then** a valid chat completion response is returned with non-empty `choices[0].message.content`.
2. **Given** the same parameters are used twice, **When** the curl script is run a second time, **Then** both responses contain the same generated text (deterministic seed).
3. **Given** the cloud container is not running, **When** the proxy receives a request, **Then** it returns a clear error indicating the upstream is unreachable, not a silent failure or hang.

---

### User Story 3 — Reproduce from a Fresh Machine (Priority: P2)

A developer on a new machine wants to reproduce the local-proxy → cloud-gRPC path from scratch. They follow documented steps and complete the full sequence without tribal knowledge.

**Why this priority**: Reproducibility is a first-class requirement per Constitution V (Honest Measurement). A deployment that only works on one machine is not a valid baseline for Phase 4.1.

**Independent Test**: Follow the ADR prerequisites on a machine with only project repo access and cloud provider credentials. The serve command succeeds and the curl smoke test returns a valid response.

**Acceptance Scenarios**:

1. **Given** a machine with only the project repo and cloud credentials, **When** the documented setup sequence is followed, **Then** the serve command succeeds and the smoke-test curl script returns a valid completion.
2. **Given** the ADR documents the tunnel topology and any observed connection behavior, **When** a developer reads it, **Then** they can predict whether the tunnel will remain stable for a single-request smoke test before running it.

---

### Edge Cases

- What happens if the TCP tunnel drops mid-request — does the proxy return a clear error or hang?
- What happens if `modal.forward` does not correctly pass persistent HTTP/2 connections with gRPC keep-alive frames?
- What happens if the developer's local machine is behind a corporate firewall that blocks the tunnel's port?
- What happens if the cloud function times out (default 600 s) while the developer is actively testing — is there a warning before the tunnel closes?
- What happens if the serve command is run a second time before the previous cloud container finishes tearing down — are two containers allocated simultaneously?

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A standalone serve script MUST exist that starts the gRPC frontend on a cloud GPU and exposes its gRPC port as an externally-reachable TCP address, staying alive until manually interrupted or until a documented timeout.
- **FR-002**: The tunnel address MUST be printed to the developer's local terminal automatically after the frontend becomes healthy — no manual log-scraping or container SSH required.
- **FR-003**: The proxy MUST be configurable to connect to the tunnel address by setting a single environment variable (`FRONTEND_ADDR`), with no proxy code changes required.
- **FR-004**: The tunnel MUST remain stable for the duration of at least one complete request/response cycle (request sent, response received, connection closed cleanly).
- **FR-005**: A single command MUST encapsulate the full serve lifecycle: container provisioning, model loading, tunnel setup, address printing, and blocking until interrupted.
- **FR-006**: If the cloud TCP tunnel mechanism fails to pass persistent connections reliably, the failure mode MUST be documented in the ADR and an alternative approach identified before the phase is considered complete.
- **FR-007**: Graceful shutdown on Ctrl+C MUST tear down the cloud container automatically; no manual cloud console cleanup should be required.
- **FR-008**: `docs/decisions/0002-modal-deployment.md` MUST be updated to document the validated local-proxy → cloud-gRPC topology, the tunnel address-communication mechanism, observed connection behavior (including HTTP/2 keep-alive handling), and any instability encountered.
- **FR-009**: All new Python source files MUST pass `ruff` (lint + format) and `mypy --strict` type checking.

### Key Entities

- **Serve Script**: A cloud-executable script that manages the gRPC frontend container lifecycle and exposes the gRPC port via a tunnel. Accepts the same model path and port configuration as the existing local deployment.
- **TCP Tunnel**: A network path from the developer's local machine to the gRPC port inside the cloud container. Must support persistent HTTP/2 connections. Lives for the duration of the serve script invocation.
- **Tunnel Address**: The `host:port` string printed by the serve script's local entrypoint. Valid for the lifetime of the serve script. Used as the value of `FRONTEND_ADDR` for the local proxy.
- **Local Proxy**: The existing `vllm_grpc_proxy` package, started locally on the developer's machine with `FRONTEND_ADDR` set to the tunnel address. No code changes.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The serve command prints a usable tunnel address to the developer's terminal within the documented cold-start window (≤ 5 minutes after weights are pre-staged).
- **SC-002**: A request sent to the locally-running proxy with `FRONTEND_ADDR` pointing at the cloud tunnel returns a valid, deterministic chat completion (`seed=42`, `max_tokens=20`, non-empty content).
- **SC-003**: The tunnel remains stable for at least one complete request/response cycle with no connection errors.
- **SC-004**: Switching the proxy from the local gRPC frontend to the cloud gRPC frontend requires changing only the `FRONTEND_ADDR` environment variable — no other configuration or code change.
- **SC-005**: The full sequence (serve command start → tunnel address printed → local proxy started → request sent → response received) completes in under 15 minutes end-to-end.
- **SC-006**: The updated ADR documents observed tunnel behavior (stability, HTTP/2 keep-alive handling, any drops) so a future developer can make an informed decision about whether the tunnel is suitable for multi-request benchmarks.

---

## Assumptions

- Model weights are pre-staged in the persistent cloud volume from Phase 3.1 (`make download-weights` already run). Phase 3.2 does not re-download weights.
- The cloud provider's TCP tunnel mechanism is capable of forwarding HTTP/2 frames; this assumption is the primary unknown and must be empirically validated.
- The existing proxy code (`vllm_grpc_proxy`) requires no changes to connect to a remote gRPC address — only `FRONTEND_ADDR` needs to change. This was verified in Phase 3.1.
- The existing smoke-test curl script (`scripts/curl/chat-nonstreaming-modal.sh`) is reused for the manual validation step; no new curl scripts are needed.
- The cloud container function timeout (≥ 600 s) is sufficient for cold-start plus manual testing. Timeout value is documented in the ADR.
- TLS is not required for the cloud gRPC connection in this phase; the proxy uses an insecure channel, consistent with the local development and Phase 3.1 configurations.
- Phase 3.2 does not include benchmark orchestration (that is Phase 4.1). A single deterministic smoke-test request is the validation gate.
- If the TCP tunnel mechanism proves fundamentally incompatible with persistent gRPC connections, the phase is not abandoned — the incompatibility is documented, an alternative is identified, and that alternative is scoped as follow-on work.
