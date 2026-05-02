# Tasks: Modal gRPC Frontend Deployment

**Input**: Design documents from `specs/005-modal-grpc-frontend/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: Not requested. Smoke-test scripts are their own integration tests; `ruff` + `mypy --strict` are the CI gates.

**Organization**: Tasks grouped by user story for independent implementation and validation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no unresolved dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)
- Exact file paths in all descriptions

---

## Phase 1: Setup

**Purpose**: Add `modal` to the dev dependency group so all new scripts can be linted and type-checked locally.

- [ ] T001 Add `modal>=0.73` to `[dependency-groups.dev]` in `pyproject.toml`; run `uv sync --all-packages` to update the lockfile

**Checkpoint**: `python -c "import modal"` succeeds in the uv venv.

---

## Phase 2: Foundational — Weight Volume

**Purpose**: Pre-stage `Qwen/Qwen3-0.6B` in a persistent Modal Volume. **Must complete before any smoke-test script can run** (both US1 and US3 depend on the volume).

⚠️ **CRITICAL**: T004 is a manual, GPU-free operation that must complete before Phase 3 or Phase 5 can be validated.

- [ ] T002 Implement `scripts/python/modal_download_weights.py`: define `_MODEL_VOLUME = modal.Volume.from_name("vllm-grpc-model-weights", create_if_missing=True)`, a CPU-only Modal function that calls `huggingface_hub.snapshot_download(repo_id="Qwen/Qwen3-0.6B", local_dir="/mnt/weights")` with idempotency guard (`if Path("/mnt/weights/config.json").exists(): return`), calls `_MODEL_VOLUME.commit()`, and a `@app.local_entrypoint()` that prints elapsed time and exit status
- [ ] T003 [P] Add `download-weights` Makefile target in `Makefile`: `uv run --with modal modal run scripts/python/modal_download_weights.py`
- [ ] T004 Run `make download-weights` manually; confirm exit 0 and that `vllm-grpc-model-weights` volume appears in the Modal dashboard

**Checkpoint**: Modal Volume `vllm-grpc-model-weights` exists and contains `config.json`.

---

## Phase 3: User Story 1 — Deploy gRPC Frontend to Modal (Priority: P1) 🎯 MVP

**Goal**: `modal run scripts/python/modal_frontend_smoke.py` deploys the gRPC frontend + proxy on A10G, runs a full proxy→gRPC→vLLM smoke test, and tears down. Exit 0 = PASSED.

**Independent Test**: `make smoke-grpc-frontend` exits 0 with a non-empty `completion_text` and `cold_start_s` / `request_latency_s` printed to stdout.

- [ ] T005 [US1] Define Modal app, constants, and image in `scripts/python/modal_frontend_smoke.py`: `_MODEL_VOLUME`, `_VLLM_VERSION = "0.20.0"`, `_MODEL_PATH = "/mnt/weights"`, `_GRPC_PORT = 50051`, `_PROXY_PORT = 8000`; image chain: `debian_slim(python_version="3.12")` → `pip_install("vllm==0.20.0", "grpcio>=1.65", "grpcio-tools>=1.65", "fastapi>=0.115", "uvicorn[standard]>=0.30", "httpx>=0.27")` → `copy_local_dir("proto", "/build/proto")` → `copy_local_dir("packages/gen", "/build/packages/gen")` → `copy_local_dir("packages/frontend", "/build/packages/frontend")` → `copy_local_dir("packages/proxy", "/build/packages/proxy")` → `run_commands(...)` (run `grpcio_tools.protoc` for `health.proto` and `chat.proto`, then `pip install /build/packages/gen /build/packages/frontend /build/packages/proxy`)
- [ ] T006 [US1] Implement gRPC frontend startup in `smoke_test()` in `scripts/python/modal_frontend_smoke.py`: `subprocess.Popen(["python", "-m", "vllm_grpc_frontend.main"], env={**os.environ, "MODEL_NAME": _MODEL_PATH, "FRONTEND_HOST": "0.0.0.0", "FRONTEND_PORT": str(_GRPC_PORT)}, ...)`; record `t_start = time.monotonic()`; poll `grpc.aio.insecure_channel(f"localhost:{_GRPC_PORT}")` → `HealthStub.Ping()` with 5 s retry loop up to 120 polls (10 min timeout); on success record `cold_start_s = time.monotonic() - t_start`; on timeout kill process and return `SmokeTestResult(ok=False, error="gRPC server did not become healthy within 600s")`
- [ ] T007 [US1] Implement proxy startup in `smoke_test()` in `scripts/python/modal_frontend_smoke.py`: after gRPC server is healthy, `subprocess.Popen(["uvicorn", "vllm_grpc_proxy.main:app", "--host", "0.0.0.0", "--port", str(_PROXY_PORT)], env={**os.environ, "FRONTEND_ADDR": f"localhost:{_GRPC_PORT}"})`; poll `http://localhost:{_PROXY_PORT}/healthz` with `httpx.get()` up to 30 s; on timeout kill both processes and return failure result
- [ ] T008 [US1] Implement smoke-test request and cleanup in `smoke_test()` in `scripts/python/modal_frontend_smoke.py`: `t_req = time.monotonic()`; `httpx.post(f"http://localhost:{_PROXY_PORT}/v1/chat/completions", json={"model": _MODEL_PATH, "messages": [...], "max_tokens": 20, "seed": 42}, timeout=60.0)`; assert `response.status_code == 200` and `choices[0].message.content` non-empty; record `request_latency_s`; kill proxy and frontend subprocesses; return `SmokeTestResult` dict matching the schema in `specs/005-modal-grpc-frontend/contracts/smoke-test-result.md`
- [ ] T009 [US1] Implement `@app.local_entrypoint()` in `scripts/python/modal_frontend_smoke.py`: call `smoke_test.remote()`; print `cold_start_s`, `request_latency_s`, `completion_text`; `sys.exit(0)` if `result["ok"]`, else print `result["error"]` to stderr and `sys.exit(1)`
- [ ] T010 [P] [US1] Add `smoke-grpc-frontend` Makefile target in `Makefile`: `uv run --with modal modal run scripts/python/modal_frontend_smoke.py`
- [ ] T011 [US1] Run `make smoke-grpc-frontend` manually; confirm exit 0; note `cold_start_s` and `request_latency_s` values for use in T016 (ADR)

**Checkpoint**: US1 complete — `make smoke-grpc-frontend` exits 0. gRPC frontend on A10G confirmed working end-to-end.

---

## Phase 4: User Story 2 — Smoke Test Reference Script (Priority: P2)

**Goal**: A manual curl script exists that documents the full local-proxy → cloud-gRPC path for developers who want to run it without the automated lifecycle script.

**Independent Test**: `bash scripts/curl/chat-nonstreaming-modal.sh` (with `PROXY_PORT` set and a running proxy pointed at a Modal gRPC tunnel) produces a valid OpenAI-format JSON response.

- [ ] T012 [P] [US2] Create `scripts/curl/chat-nonstreaming-modal.sh`: identical request body to `scripts/curl/chat-nonstreaming.sh` (same model, same seed=42 prompt); add a header comment block documenting that `PROXY_PORT` must point at a locally-running proxy with `FRONTEND_ADDR` set to a Modal gRPC tunnel address; reference `docs/decisions/0002-modal-deployment.md` for how to obtain a tunnel address

**Checkpoint**: US2 complete — curl script exists with clear usage instructions.

---

## Phase 5: User Story 3 — REST Comparison Target (Priority: P2)

**Goal**: `make smoke-rest` deploys vLLM's native OpenAI REST server on A10G, sends the same prompt with the same seed, and tears down. `completion_text` must match the US1 result (SC-003).

**Independent Test**: `make smoke-rest` exits 0 with a non-empty `completion_text`; manually compare with the US1 output to confirm token-level equivalence.

- [ ] T013 [US3] Implement `scripts/python/modal_vllm_rest.py` following the `verify_prompt_embeds_modal.py` pattern: define `_MODEL_VOLUME`, image = `debian_slim(python_version="3.12").pip_install("vllm==0.20.0", "httpx")`; `smoke_test()` function starts `python -m vllm.entrypoints.openai.api_server --model /mnt/weights --port 8000` as subprocess, polls `GET /health` with httpx until 200, records `cold_start_s`, sends `POST /v1/chat/completions` with `{"model": "/mnt/weights", "messages": [...same prompt as T008...], "max_tokens": 20, "seed": 42}`, records `request_latency_s` and `completion_text`, kills server, returns `SmokeTestResult` dict matching `specs/005-modal-grpc-frontend/contracts/smoke-test-result.md`; `@app.local_entrypoint()` prints result and exits 0/1
- [ ] T014 [P] [US3] Add `smoke-rest` Makefile target in `Makefile`: `uv run --with modal modal run scripts/python/modal_vllm_rest.py`
- [ ] T015 [US3] Run `make smoke-rest` manually; confirm exit 0; compare `completion_text` with T011 result to verify token-level equivalence (SC-003); note `cold_start_s` for ADR (T016)

**Checkpoint**: US3 complete — `make smoke-rest` exits 0. REST baseline on A10G confirmed. SC-003 equivalence verified.

---

## Phase 6: User Story 4 — Fresh Machine Reproducibility + Type Safety (Priority: P3)

**Goal**: A new developer can follow the ADR to reproduce both deployments from scratch. All new Python files pass `ruff` and `mypy --strict`.

**Independent Test**: Following `docs/decisions/0002-modal-deployment.md` prerequisites section on a machine with only Modal auth produces passing smoke tests.

- [ ] T016 [US4] Write `docs/decisions/0002-modal-deployment.md`: sections — Context (why Modal, why pre-staged weights), Container Build Approach (how `grpcio_tools.protoc` + `copy_local_dir` + `pip install` assembles the image), Required Environment Variables (`MODEL_NAME`, `FRONTEND_HOST`, `FRONTEND_PORT`, `FRONTEND_ADDR`), Cold-Start Behavior (observed `cold_start_s` from T011 and T015, both ≤ 5 min, ±10 s reproducibility), Teardown Behavior (automatic on function return; no manual cleanup needed), Prerequisites (Modal token, `make download-weights` one-time step), Manual External Tunnel (advanced: instructions for running a local proxy against a Modal gRPC tunnel using `modal.forward` for developers who need to validate the external path)
- [ ] T017 [P] [US4] Run `uv run ruff check scripts/python/modal_download_weights.py scripts/python/modal_frontend_smoke.py scripts/python/modal_vllm_rest.py` and `uv run mypy --strict scripts/python/modal_download_weights.py scripts/python/modal_frontend_smoke.py scripts/python/modal_vllm_rest.py`; fix all errors

**Checkpoint**: US4 complete — ADR written with real timing numbers; all new files are ruff-clean and mypy --strict clean.

---

## Phase 7: Polish

**Purpose**: End-to-end validation that the quickstart works as documented and that README is current.

- [ ] T018 Run the full `specs/005-modal-grpc-frontend/quickstart.md` sequence in order (Steps 1–4) on a clean terminal session; confirm all steps complete without manual intervention beyond what the quickstart documents; fix any discrepancies between quickstart and actual behavior

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 (modal importable); T004 blocks Phases 3 and 5
- **US1 (Phase 3)**: Depends on Phase 2 complete (T004 done)
- **US2 (Phase 4)**: Independent of US1 (curl script only); can start after Phase 1
- **US3 (Phase 5)**: Depends on Phase 2 complete (T004 done); independent of US1
- **US4 (Phase 6)**: T016 (ADR) depends on T011 + T015 timing data; T017 (lint/type) depends on all scripts implemented (T002, T005–T009, T013)
- **Polish (Phase 7)**: Depends on all phases complete

### User Story Dependencies

- **US1 (P1)**: Requires Phase 2 (volume must exist). No dependency on US2/US3/US4.
- **US2 (P2)**: Requires only Phase 1. Fully independent (just a curl script).
- **US3 (P2)**: Requires Phase 2. Independent of US1.
- **US4 (P3)**: Requires T011 + T015 timing numbers (observed from live runs) and all scripts implemented.

### Within Phase 3 (US1)

- T005 before T006 (image must be defined before implementing the function body)
- T006 before T007 (gRPC server start before proxy start)
- T007 before T008 (proxy must be running before sending request)
- T008 before T009 (return value must be defined before entrypoint uses it)
- T010 [P] can be done alongside T005–T009 (different file)

---

## Parallel Execution Examples

```bash
# Phase 2: T002 and T003 in parallel (different files)
Task: "Implement scripts/python/modal_download_weights.py"
Task: "Add download-weights Makefile target"

# Phase 3 + Phase 4: T010 and T012 in parallel with T005
Task: "Add smoke-grpc-frontend Makefile target"    # T010 [P]
Task: "Create scripts/curl/chat-nonstreaming-modal.sh"  # T012 [P]
# (both are independent of the modal_frontend_smoke.py implementation work)

# Phase 5: T013 and T014 in parallel
Task: "Implement scripts/python/modal_vllm_rest.py"
Task: "Add smoke-rest Makefile target"

# Phase 6: T016 and T017 in parallel once T011 + T015 done
Task: "Write docs/decisions/0002-modal-deployment.md"
Task: "ruff + mypy --strict on all new scripts"
```

---

## Implementation Strategy

### MVP (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (weight volume — **run T004 before continuing**)
3. Complete Phase 3: US1 (modal_frontend_smoke.py)
4. **STOP and VALIDATE**: `make smoke-grpc-frontend` exits 0
5. Record timing numbers — these are the first real GPU benchmarks for the project

### Incremental Delivery

1. Phase 1 + Phase 2 → Weight volume ready (foundation)
2. Phase 3 → gRPC frontend smoke test passing (MVP — first live Modal gRPC deployment)
3. Phase 4 → Curl reference script for manual external-path testing
4. Phase 5 → REST comparison baseline established; SC-003 equivalence verified
5. Phase 6 → ADR documented with real numbers; type safety confirmed
6. Phase 7 → Quickstart validated end-to-end

---

## Notes

- T004, T011, and T015 are **manual execution tasks** — they require running Modal commands on the developer's machine and cannot be automated in CI.
- `cold_start_s` from T011 and T015 are real observed values that must be entered into T016 (ADR). Do not write the ADR until both live runs have completed.
- Both smoke-test scripts use identical request parameters (`seed=42`, `max_tokens=20`, same prompt) so SC-003 comparison is valid.
- No pytest tests are added in this phase; the scripts themselves are the integration tests.
- `mypy --strict` on Modal scripts may require `# type: ignore` annotations for Modal's dynamic API; document any suppressions in the code.
