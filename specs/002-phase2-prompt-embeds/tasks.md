---
description: "Task list for Phase 2 — Prompt-Embeds Environment Investigation"
---

# Tasks: Phase 2 — Prompt-Embeds Environment Investigation

**Input**: Design documents from `specs/002-phase2-prompt-embeds/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, quickstart.md ✅

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: User story this task belongs to (US1–US3)
- Every task includes an exact file path

---

## Phase 1: Setup

**Purpose**: Create the directory skeleton and scaffolding that all later tasks write into.

- [ ] T001 Create `scripts/setup/` directory and empty placeholder at `scripts/setup/phase2-env.sh` (will be filled in Phase 5) at `scripts/setup/phase2-env.sh`
- [ ] T002 [P] Create `docs/decisions/` directory and ADR skeleton at `docs/decisions/0001-prompt-embeds-environment.md` — include sections: vLLM Version, Candidate A (M2 MPS), Candidate B (M2 CPU), Candidate C (Cloud GPU), Decision, Rationale, Rejected Alternatives at `docs/decisions/0001-prompt-embeds-environment.md`
- [ ] T003 Install vLLM in a scratch environment (`uv run --with vllm python -c "import vllm; print(vllm.__version__)"`); run `uv run --with vllm vllm serve --help | grep -i "prompt.embed\|v1.engine\|v0\|enable"` and record the exact flag names in the ADR's vLLM Version section at `docs/decisions/0001-prompt-embeds-environment.md`

---

## Phase 2: Foundational (Blocking Prerequisite)

**Purpose**: The verification script must exist before any candidate environment can be tested. No experiment can be validated without it.

**⚠️ CRITICAL**: US1–US3 all depend on the verification script from this phase.

- [ ] T004 Implement `scripts/python/verify_prompt_embeds.py`: accepts `--base-url`, `--model`, `--seq-len` (default 8), `--max-tokens` (default 50) CLI arguments; constructs a float32 numpy array of shape `[seq_len, 1024]`; base64-encodes it; sends `POST /v1/completions` with `extra_body: {"prompt_embeds": <b64>}`; prints `[OK] Server responded in X.XXs` and `[OK] prompt_embeds accepted` on success, or a descriptive `[FAIL]` message on any error; exits 0 on success, 1 on failure at `scripts/python/verify_prompt_embeds.py`
- [ ] T005 Add `py.typed` marker, full type annotations, and `__main__` guard to `verify_prompt_embeds.py` so it passes `mypy --strict` with zero errors at `scripts/python/verify_prompt_embeds.py`
- [ ] T006 Run `ruff check scripts/python/verify_prompt_embeds.py` and `ruff format --check scripts/python/verify_prompt_embeds.py`; fix any violations at `scripts/python/verify_prompt_embeds.py`

**Checkpoint**: Verification script exists and passes `make check`. Experiment work can begin.

---

## Phase 3: User Story 1 — Determine Viable Prompt-Embeds Environment (Priority: P1) 🎯 MVP

**Goal**: Empirically confirm which compute environment accepts `prompt_embeds` via vLLM's native OpenAI server and measure the throughput.

**Independent Test**: Run `python scripts/python/verify_prompt_embeds.py --base-url http://localhost:<PORT> --model Qwen/Qwen3-0.6B`; script exits 0 and prints a throughput number.

### Implementation for User Story 1

- [ ] T007 [US1] Run Candidate A (M2 MPS): start vLLM with `VLLM_USE_V1_ENGINE=0 vllm serve Qwen/Qwen3-0.6B --enable-prompt-embeds --device mps --max-model-len 512 --port 9000` (adjust flags per T003 findings); run the verification script; record server startup result, elapsed time, and any errors in the ADR Candidate A section at `docs/decisions/0001-prompt-embeds-environment.md`
- [ ] T008 [US1] Run Candidate B (M2 CPU): start vLLM with `VLLM_USE_V1_ENGINE=0 VLLM_CPU_ONLY=1 vllm serve Qwen/Qwen3-0.6B --enable-prompt-embeds --device cpu --max-model-len 256 --port 9001` (adjust flags per T003 findings); run the verification script; record server startup result, elapsed time, and any errors in the ADR Candidate B section at `docs/decisions/0001-prompt-embeds-environment.md`
- [ ] T009 [US1] Assess Candidate C (cloud GPU): if Candidate A or B succeeded, document the estimated cost and friction of Modal/RunPod/Lambda L4 without running a full experiment; if both A and B failed, write `scripts/python/verify_prompt_embeds_modal.py` deploying `verify_prompt_embeds.py` logic to a Modal A10G and run it; record results in the ADR Candidate C section at `docs/decisions/0001-prompt-embeds-environment.md`
- [ ] T010 [US1] Select the chosen environment: review results from T007–T009; pick the highest-priority viable candidate (MPS > CPU > cloud); enter the Decision and Rationale into the ADR, including the measured throughput number (wall-clock time for 50-token completion) for the chosen environment at `docs/decisions/0001-prompt-embeds-environment.md`

**Checkpoint**: Verification script passes against the chosen environment. User Story 1 complete.

---

## Phase 4: User Story 2 — Document the Environment Decision (Priority: P2)

**Goal**: Produce a complete, durable ADR that a developer can read cold and understand the decision without re-running experiments.

**Independent Test**: Read `docs/decisions/0001-prompt-embeds-environment.md`; it contains: vLLM version, all three candidate results, the chosen environment, the throughput number, and rationale for rejecting the alternatives.

### Implementation for User Story 2

- [ ] T011 [US2] Complete the ADR at `docs/decisions/0001-prompt-embeds-environment.md`: fill all sections with actual data from T007–T010; verify the chosen environment section includes the vLLM version, the start command used, and the exact throughput number; verify the rejected sections state the failure mode or reason for not choosing them at `docs/decisions/0001-prompt-embeds-environment.md`

**Checkpoint**: ADR is complete and self-contained. User Story 2 complete.

---

## Phase 5: User Story 3 — Reproducible Setup Script (Priority: P3)

**Goal**: A developer can delete the environment, run one script, and immediately verify prompt_embeds works — no manual steps.

**Independent Test**: Delete the vLLM installation from the scratch environment; run `bash scripts/setup/phase2-env.sh`; run `python scripts/python/verify_prompt_embeds.py --base-url <URL> --model Qwen/Qwen3-0.6B`; script exits 0.

### Implementation for User Story 3

- [ ] T012 [US3] Implement `scripts/setup/phase2-env.sh` for the chosen environment: the script installs the required vLLM version (and plugin if MPS), downloads or verifies Qwen3-0.6B model weights, and starts the vLLM server with the exact flags confirmed in T007 or T008 (or documents Modal setup steps if cloud was chosen); each step is logged to stdout at `scripts/setup/phase2-env.sh`
- [ ] T013 [US3] Validate the setup script end-to-end: tear down the existing environment (deactivate venv / kill running server); run `bash scripts/setup/phase2-env.sh` from scratch; immediately run the verification script; confirm it exits 0 with no manual intervention; fix any issues in the script at `scripts/setup/phase2-env.sh`

**Checkpoint**: Setup script + verification script chain works from a clean state. User Story 3 complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: CI compliance, quickstart validation, and merge.

- [ ] T014 Run `make check` (ruff + mypy --strict) across all new and modified files in `scripts/`; fix any lint, format, or type errors at `scripts/python/verify_prompt_embeds.py`, `scripts/setup/phase2-env.sh`
- [ ] T015 [P] Follow `specs/002-phase2-prompt-embeds/quickstart.md` step by step on a clean shell; confirm each step produces the documented output; update quickstart.md if any step is inaccurate at `specs/002-phase2-prompt-embeds/quickstart.md`
- [ ] T016 Merge `002-phase2-prompt-embeds` to `main` and confirm all CI jobs green

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — experiments require the verification script
- **US2 (Phase 4)**: Depends on US1 — ADR requires experimental results
- **US3 (Phase 5)**: Depends on US1 — setup script targets the chosen environment
- **Polish (Phase 6)**: Depends on US1, US2, US3

### Within Each Phase

- T001 and T002 [P] run in parallel (different directories)
- T003 depends on nothing but benefits from running after T001/T002 (ADR file must exist)
- T005 and T006 are sequential (T006 checks the result of T005)
- T007 and T008 are sequential (avoid running two vLLM servers simultaneously; record results between runs)
- T009 depends on T007 and T008 results (decision tree: cloud only if both M2 paths fail)
- T010 depends on T007–T009

### Parallel Opportunities

```bash
# Phase 1 — T001 and T002 in parallel
T001 (scripts/setup/ directory) || T002 (docs/decisions/ + ADR skeleton)

# Phase 3 — T007 and T008 must be sequential (shared hardware)
T007 (MPS experiment) → T008 (CPU experiment) → T009 (cloud assessment) → T010 (decision)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T003)
2. Complete Phase 2: Foundational (T004–T006) — **CRITICAL gate**
3. Complete Phase 3: US1 (T007–T010)
4. **STOP and VALIDATE**: Verification script passes against chosen environment
5. Proceed to US2/US3 once the environment is confirmed

### Incremental Delivery

1. Setup + Foundational → verification script exists ✓
2. US1 → environment confirmed + throughput measured ✓ (MVP)
3. US2 → ADR written + decision permanent ✓
4. US3 → environment reproducible from scratch ✓
5. Polish → CI green, merge to main ✓

---

## Notes

- [P] = different files, no cross-task dependencies within phase
- T009 has a conditional path: write Modal script only if M2 experiments both fail
- T003 is an environment-inspection task (runs commands, records observations) — mark complete after recording flag names in the ADR
- T007 and T008 are experiment tasks — mark complete after recording results in the ADR, regardless of pass/fail outcome
- The Qwen3-0.6B hidden dimension is 1024; `verify_prompt_embeds.py` must use this exact value for the tensor shape
- All Python scripts must pass `mypy --strict` before the branch is merged (Constitution Principle IV)
