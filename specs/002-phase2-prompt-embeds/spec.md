# Feature Specification: Phase 2 — Prompt-Embeds Environment Investigation

**Feature Branch**: `002-phase2-prompt-embeds`  
**Created**: 2026-04-29  
**Updated**: 2026-04-30 — scope expanded to vLLM 0.20.0 + vllm-metal 0.2.0; clean local install via uv dependency group  
**Status**: In Progress  
**Input**: User description: "Phase 2"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Determine Viable Prompt-Embeds Environment (Priority: P1)

A developer needs to know, before writing any chat-completions code, which compute environment can actually serve Qwen3-0.6B with `prompt_embeds` enabled via vLLM's native OpenAI server. The investigation uses vLLM 0.20.0 (the current ecosystem release) and vllm-metal 0.2.0 (the Apple Silicon plugin), ensuring architectural decisions reflect the current state of the vLLM ecosystem rather than a point-in-time snapshot. This prevents a late-phase surprise where the chosen environment turns out not to work.

**Why this priority**: Phase 6 (Completions API with Prompt Embeds) cannot be planned without this decision. Every other phase can proceed in parallel, but Phase 6 is blocked until the environment is confirmed.

**Independent Test**: Run the throwaway verification script against the chosen environment; it calls vLLM's native `/v1/completions` endpoint with `prompt_embeds` in the request and receives a valid completion — no bridge involved.

**Acceptance Scenarios**:

1. **Given** a fresh dev machine, **When** the setup script is run, **Then** the target environment is reproduced and ready in under 15 minutes with no manual steps beyond what the script documents.
2. **Given** the chosen environment is running, **When** the verification script sends a `/v1/completions` request carrying a `prompt_embeds` tensor for Qwen3-0.6B with a 50-token completion, **Then** the server returns a valid completion response.
3. **Given** the investigation report is complete, **When** a developer reads it, **Then** they can identify the chosen environment, the throughput number measured, and the rationale for rejecting the alternatives without needing to repeat any experiments.

---

### User Story 2 - Document the Environment Decision (Priority: P2)

A developer writes an Architecture Decision Record capturing the environment choice, the data gathered during investigation, and the rationale for accepting or rejecting each candidate. This record becomes the durable reference for Phase 6 planning.

**Why this priority**: The investigation produces ephemeral experiment results; the ADR makes the decision permanent and traceable. Without it, the rationale is lost when the conversation context is cleared.

**Independent Test**: The ADR file exists at `docs/decisions/0001-prompt-embeds-environment.md`, contains throughput numbers for each environment tested, names the chosen option, and provides clear rationale for rejecting the others.

**Acceptance Scenarios**:

1. **Given** experiments are complete, **When** the ADR is written, **Then** it covers all three candidate environments tested under vLLM 0.20.0: M2 vllm-metal 0.2.0, M2 CPU-only, and cloud GPU.
2. **Given** the ADR is written, **When** a developer reads it, **Then** they can reproduce the decision-making process from the data alone.

---

### User Story 3 - Establish a Reproducible Setup Script (Priority: P3)

A developer needs a single script that, run on a fresh machine matching the dev hardware profile, installs and configures the chosen vLLM environment so that the verification script works without additional manual steps.

**Why this priority**: The investigation is useful only if its environment is reproducible. A working but undocumented environment has the same value as no environment once the session ends.

**Independent Test**: Delete the environment, run the setup script from scratch on the same machine, then immediately run the verification script — it succeeds without any additional manual steps.

**Acceptance Scenarios**:

1. **Given** the chosen environment is not installed, **When** the setup script runs on the documented hardware, **Then** the environment is ready.
2. **Given** the setup script has run, **When** the verification script is executed, **Then** it succeeds on the first attempt with no manual intervention.

---

### Edge Cases

- What happens if vllm-metal 0.2.0's `MetalWorker` receives a `prompt_embeds` request but its model runner has no implementation — does it crash, silently ignore, or delegate?
- What if vllm-metal 0.2.0 and vLLM 0.20.0 have a compatibility issue that prevents the server from starting at all?
- What if cloud-GPU instance provisioning is temporarily unavailable or takes longer than the time box?
- What if the Qwen3-0.6B model download fails mid-setup (network interruption)?
- What if the verification script returns a response but the output is clearly incoherent (e.g., empty completion or error masked as 200)?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The investigation MUST evaluate three candidate environments using vLLM 0.20.0 as the target version: (a) M2 vllm-metal 0.2.0 (Apple Silicon GPU via MLX), (b) M2 CPU-only vLLM 0.20.0, and (c) a small CUDA cloud instance (Modal, RunPod, or Lambda L4).
- **FR-002**: Each environment evaluation MUST empirically confirm whether `prompt_embeds` are accepted end-to-end by vLLM's native OpenAI server — source code inspection alone is not sufficient evidence.
- **FR-003**: For any environment that accepts `prompt_embeds`, the evaluation MUST record the time-to-first-token and total wall-clock time for a 50-token completion of Qwen3-0.6B.
- **FR-004**: The investigation MUST produce a single environment decision — M2 vllm-metal, M2 CPU-only, or cloud GPU — with documented rationale.
- **FR-005**: The investigation MUST produce a setup script that reproduces the chosen environment on a fresh machine matching the dev hardware profile (M2 Pro MacBook Pro, 32 GB, macOS).
- **FR-006**: The investigation MUST produce a throwaway verification script that calls vLLM's native OpenAI `/v1/completions` endpoint with a `prompt_embeds` payload and validates the response — no bridge, no proxy.
- **FR-007**: All findings and the final decision MUST be written into an ADR at `docs/decisions/0001-prompt-embeds-environment.md`.
- **FR-008**: The investigation MUST be completed within the 2–3 day time box; if cloud-GPU evaluation cannot be completed within the box, a cost/friction estimate is sufficient.

### Key Entities

- **Candidate Environment**: One of three compute options (M2 vllm-metal, M2 CPU-only, cloud GPU) evaluated for its ability to serve prompt-embeds requests.
- **Verification Script**: A standalone script that calls vLLM's native OpenAI server with a `prompt_embeds` payload and confirms a valid response.
- **Setup Script**: A standalone script that installs and configures the chosen environment on the target hardware.
- **Architecture Decision Record (ADR)**: A durable document recording the environment chosen, data gathered, and rationale for each accept/reject decision.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The chosen environment serves Qwen3-0.6B with `prompt_embeds` end-to-end via vLLM's native OpenAI server, producing a valid 50-token completion — confirmed by the verification script passing.
- **SC-002**: The setup script reproduces the chosen environment from a clean state in under 15 minutes on the documented hardware, with no steps beyond what the script documents.
- **SC-003**: The ADR contains at least one measured throughput number (wall-clock time per completion) for the chosen environment.
- **SC-004**: All three candidate environments are evaluated or explicitly ruled out with a documented reason before the time box expires.
- **SC-005**: The investigation is completed within 3 calendar days of the branch being opened.

## Assumptions

- The development machine is an M2 Pro MacBook Pro, 32 GB unified memory, running macOS — this is the primary hardware target.
- `uv` and Python 3.12 are pre-installed on the dev machine (Phase 1 deliverable).
- **vllm-metal 0.2.0** is the Apple Silicon GPU plugin, installed as a GitHub release wheel. **vLLM 0.20.0** is the version paired with it by the official `install.sh`. Both are declared in `pyproject.toml` under `[dependency-groups] investigation` and installed via `uv sync --group investigation` — matching the project's uv-first pattern for vllm.
- **vLLM 0.20.0** is the target version for all candidates. The `--enable-prompt-embeds` flag exists in this version. The wire format is base64-encoded `torch.save()` output sent as the top-level `prompt_embeds` JSON field. Candidate B (CPU) runs with `VLLM_PLUGINS=""` to suppress the metal plugin in the shared environment.
- The Qwen3-0.6B model weights are downloaded from Hugging Face; no authentication token is required for this model.
- Cloud GPU evaluation (Modal/RunPod/Lambda L4) requires a paid account; cost is estimated but full provisioning may be deferred if the M2 path works.
- The throwaway verification script does not need to be production-quality — its sole purpose is to confirm end-to-end prompt-embeds functionality.
- No bridge or proxy code is written in this phase; all calls go directly to vLLM's native OpenAI server.
