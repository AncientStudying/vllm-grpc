---
description: "Task list for Phase 1 — Scaffolding"
---

# Tasks: Phase 1 — Scaffolding

**Input**: Design documents from `specs/001-phase1-scaffolding/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: User story this task belongs to (US1–US4)
- Every task includes an exact file path

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Workspace root files that all packages depend on.

- [ ] T001 Create root `pyproject.toml` declaring uv workspace with members `packages/gen`, `packages/proxy`, `packages/frontend` at `pyproject.toml`
- [ ] T002 [P] Create `.python-version` containing `3.12` at `.python-version`
- [ ] T003 [P] Update `.gitignore` to exclude `packages/gen/src/vllm_grpc/v1/*.py` (generated stubs only; keep `__init__.py` files) and standard Python ignores at `.gitignore`
- [ ] T004 [P] Create root `Makefile` skeleton with empty targets: `proto`, `bootstrap`, `lint`, `typecheck`, `test`, `check`, `run-proxy`, `run-frontend` (targets will be filled in later phases) at `Makefile`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Protobuf schema and generated-stubs package. All user stories import from `vllm-grpc-gen` — nothing can run until stubs exist.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T005 Create `proto/vllm_grpc/v1/health.proto` with `Health` service, `Ping` unary RPC, empty `HealthRequest`, and `HealthResponse { string message = 1; }` per `contracts/health-grpc.md` at `proto/vllm_grpc/v1/health.proto`
- [ ] T006 Create `packages/gen/pyproject.toml` declaring `name = "vllm-grpc-gen"`, `version = "0.1.0"`, `src` layout, no external runtime deps at `packages/gen/pyproject.toml`
- [ ] T007 [P] Create static namespace-package init files `packages/gen/src/vllm_grpc/__init__.py` and `packages/gen/src/vllm_grpc/v1/__init__.py` (empty files; committed to repo; stubs alongside them are gitignored) at `packages/gen/src/`
- [ ] T008 Implement `make proto` target in `Makefile`: runs `uv run python -m grpc_tools.protoc -I proto --python_out=packages/gen/src --grpc_python_out=packages/gen/src proto/vllm_grpc/v1/health.proto` at `Makefile`
- [ ] T009 Run `make proto` and verify `packages/gen/src/vllm_grpc/v1/health_pb2.py` and `health_pb2_grpc.py` are generated cleanly (manual validation checkpoint)

**Checkpoint**: Foundation ready — stub files exist, gen package importable. User story work can begin.

---

## Phase 3: User Story 1 — Developer Bootstrap (Priority: P1) 🎯 MVP

**Goal**: A new contributor clones the repo, runs `make bootstrap`, starts proxy and frontend, and sees `{"status":"ok"}` from `GET /healthz`.

**Independent Test**: `make bootstrap && make run-frontend` (background) `&& make run-proxy` (background) `&& curl -s http://localhost:8000/healthz` returns `{"status":"ok"}`.

### Package Setup for User Story 1

- [ ] T010 Create `packages/frontend/pyproject.toml` with `name = "vllm-grpc-frontend"`, `grpcio` and `vllm-grpc-gen = {workspace = true}` deps, src layout, and `vllm_grpc_frontend.main:main` entry point at `packages/frontend/pyproject.toml`
- [ ] T011 [P] Create `packages/proxy/pyproject.toml` with `name = "vllm-grpc-proxy"`, `fastapi`, `uvicorn[standard]`, `grpcio`, and `vllm-grpc-gen = {workspace = true}` deps, src layout, and `vllm_grpc_proxy.main:main` entry point at `packages/proxy/pyproject.toml`

### Tests for User Story 1

- [ ] T012 [P] [US1] Write unit tests for `HealthServicer` (call servicer method directly, assert `response.message == "pong"`) at `packages/frontend/tests/test_health_ping.py`
- [ ] T013 [P] [US1] Write unit tests for `GET /healthz` (mock `GrpcHealthClient.ping`; test 200 path and 503 path when gRPC raises) using `httpx.AsyncClient` at `packages/proxy/tests/test_healthz.py`
- [ ] T014 [P] [US1] Create `packages/frontend/tests/conftest.py` and `packages/proxy/tests/conftest.py` with shared pytest-asyncio fixtures at `packages/*/tests/conftest.py`

### Implementation for User Story 1

- [ ] T015 [P] [US1] Implement `HealthServicer.Ping` returning `HealthResponse(message="pong")` in `packages/frontend/src/vllm_grpc_frontend/health.py`
- [ ] T016 [US1] Implement `asyncio` gRPC server in `packages/frontend/src/vllm_grpc_frontend/main.py`: reads `FRONTEND_HOST` / `FRONTEND_PORT` env vars, registers `HealthServicer`, starts `grpc.aio` server at `packages/frontend/src/vllm_grpc_frontend/main.py`
- [ ] T017 [P] [US1] Implement `GrpcHealthClient` in `packages/proxy/src/vllm_grpc_proxy/grpc_client.py`: opens insecure channel to `FRONTEND_ADDR`, calls `Health.Ping` with 2 s deadline, returns `HealthResponse` or raises at `packages/proxy/src/vllm_grpc_proxy/grpc_client.py`
- [ ] T018 [US1] Implement `GET /healthz` FastAPI route in `packages/proxy/src/vllm_grpc_proxy/main.py`: calls `GrpcHealthClient.ping()`, returns `{"status":"ok"}` (200) or `{"status":"error","detail":"..."}` (503) per `contracts/rest-healthz.md` at `packages/proxy/src/vllm_grpc_proxy/main.py`
- [ ] T019 [US1] Complete `Makefile` with `bootstrap` (`uv sync --frozen && make proto`), `run-frontend` (`uv run python -m vllm_grpc_frontend.main`), and `run-proxy` (`uv run uvicorn vllm_grpc_proxy.main:app`) targets at `Makefile`
- [ ] T020 [US1] Create `scripts/curl/healthz.sh` that runs `curl -s http://localhost:${PROXY_PORT:-8000}/healthz` at `scripts/curl/healthz.sh`
- [ ] T021 [US1] Write `README.md` developer onboarding section: prerequisites, `make bootstrap`, start frontend, start proxy, curl `/healthz`, expected output at `README.md`

**Checkpoint**: `make bootstrap && make run-frontend & make run-proxy & curl localhost:8000/healthz` returns `{"status":"ok"}`. User Story 1 independently complete.

---

## Phase 4: User Story 2 — CI Green on Main (Priority: P2)

**Goal**: All three CI jobs (lint, typecheck, test + proto check) pass on every push to `main`.

**Independent Test**: Push any commit to `main`; all GitHub Actions jobs show green in the Actions tab.

### Tests for User Story 2

- [ ] T022 [P] [US2] Verify `make lint` passes locally (must show zero ruff errors and zero format violations) across `packages/`
- [ ] T023 [P] [US2] Verify `make typecheck` passes locally (`mypy --strict` on `packages/proxy/src` and `packages/frontend/src`) with zero errors

### Implementation for User Story 2

- [ ] T024 [P] [US2] Add `[tool.ruff]` (line-length, target-version, select rules) and `[tool.mypy]` (strict = true, per-package overrides) sections to root `pyproject.toml` at `pyproject.toml`
- [ ] T025 [P] [US2] Add `grpc-stubs` as a dev dependency to `packages/proxy/pyproject.toml` and `packages/frontend/pyproject.toml` (required for `mypy --strict` on grpcio imports) at `packages/*/pyproject.toml`
- [ ] T026 [US2] Create `.github/workflows/ci.yml` with three jobs — `lint` (`ruff check` + `ruff format --check`), `typecheck` (`mypy --strict`), `test` (`pytest`) — all using `astral-sh/setup-uv` and `uv sync --frozen` at `.github/workflows/ci.yml`
- [ ] T027 [US2] Create `.github/workflows/proto.yml` with one job that runs `make proto` then `git diff --exit-code packages/gen/src` to verify committed stubs match proto sources at `.github/workflows/proto.yml`
- [ ] T028 [US2] Complete `Makefile` `lint`, `typecheck`, `test`, and `check` targets at `Makefile`

**Checkpoint**: All CI jobs green on `main`. User Story 2 independently complete.

---

## Phase 5: User Story 3 — Spec-Kit Artifact Generation (Priority: P3)

**Goal**: Confirm spec-kit is wired up and producing useful artifacts in this repository.

**Independent Test**: The three output files `specs/001-phase1-scaffolding/spec.md`, `plan.md`, and `tasks.md` all exist and are non-empty (they do — validated by reaching this task).

### Implementation for User Story 3

- [ ] T029 [US3] Add spec-kit usage section to `README.md` — how to run `/specify`, `/plan`, `/tasks`; where artifacts are written; link to `specs/` directory at `README.md`
- [ ] T030 [US3] Verify `.specify/feature.json` points to `specs/001-phase1-scaffolding` and spec-kit config in `.specify/init-options.json` is correct at `.specify/feature.json`

**Checkpoint**: `specs/001-phase1-scaffolding/` contains spec.md, plan.md, and tasks.md. User Story 3 independently complete (artifacts produced by this planning run).

---

## Phase 6: User Story 4 — Knowledge Graph Indexing (Priority: P4)

**Goal**: `graphify` runs against the repository and produces an HTML knowledge graph with nodes for proxy, frontend, and proto components.

**Independent Test**: Run graphify; open the output HTML; confirm at least three labeled nodes exist.

### Implementation for User Story 4

- [ ] T031 [P] [US4] Create `graphify.json` configuration at repo root: point at `packages/`, `proto/`, `scripts/`; set output to `docs/graphs/` at `graphify.json`
- [ ] T032 [US4] Run graphify and confirm HTML output is written to `docs/graphs/` with visible component nodes (manual validation checkpoint)
- [ ] T033 [US4] Add graphify usage instructions to `README.md`: how to install, how to run, where output goes at `README.md`

**Checkpoint**: `docs/graphs/` contains a rendered HTML graph. User Story 4 independently complete.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and cleanup before merging to `main`.

- [ ] T034 Run `make check` end-to-end (lint + typecheck + test) and confirm zero errors across all packages
- [ ] T035 [P] Follow `specs/001-phase1-scaffolding/quickstart.md` step by step on a clean shell (no pre-running services) and confirm every step works as documented
- [ ] T036 [P] Ensure all source packages have `py.typed` marker files (`packages/proxy/src/vllm_grpc_proxy/py.typed`, `packages/frontend/src/vllm_grpc_frontend/py.typed`) for mypy compatibility at `packages/*/src/*/py.typed`
- [ ] T037 [P] Add `packages/gen/src/vllm_grpc/v1/` pattern to `.gitignore` and confirm `git status` shows generated stub files as ignored after `make proto` at `.gitignore`
- [ ] T038 Merge `001-phase1-scaffolding` to `main` and confirm all CI jobs green

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — start after T009 checkpoint
- **US2 (Phase 4)**: Depends on US1 (CI tests the code from US1)
- **US3 (Phase 5)**: Independent of US1/US2 — can start in parallel with Phase 3 (already complete)
- **US4 (Phase 6)**: Independent — can start after Phase 2
- **Polish (Phase 7)**: Depends on all user stories

### Within Each Phase

- Tasks marked [P] within a phase can run in parallel
- Frontend tasks (T015–T016) and proxy tasks (T017–T018) can run in parallel once T010/T011 complete
- T012 and T013 (test files) can be written in parallel before T015–T018 (implementation)

### Parallel Opportunities

```bash
# Phase 1 — all [P] tasks run together
T002 (.python-version) || T003 (.gitignore) || T004 (Makefile skeleton)

# Phase 2 — T007 can run alongside T005+T006
T005 (health.proto) → T008 (make proto target) → T009 (verify)
T006 (gen pyproject.toml) → T009
T007 (init files) → T009

# Phase 3 package setup — parallel
T010 (frontend pyproject.toml) || T011 (proxy pyproject.toml)

# Phase 3 tests + implementation — parallel pairs
T012 (frontend tests) || T013 (proxy tests) || T014 (conftest)
T015 (HealthServicer) || T017 (GrpcHealthClient)
T016 (frontend main) → T018 (proxy main)  # proxy main uses grpc_client → do after T017

# Phase 4 CI — parallel setup
T024 (ruff/mypy config) || T025 (grpc-stubs)
T026 (ci.yml) || T027 (proto.yml)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T004)
2. Complete Phase 2: Foundational (T005–T009) — **CRITICAL gate**
3. Complete Phase 3: US1 (T010–T021)
4. **STOP and VALIDATE**: `make bootstrap && curl localhost:8000/healthz` → `{"status":"ok"}`
5. Proceed to CI if demo works

### Incremental Delivery

1. Setup + Foundational → proto compiles ✓
2. US1 → end-to-end ping works ✓ (MVP)
3. US2 → CI green on main ✓
4. US3 → spec-kit confirmed ✓ (already done via this run)
5. US4 → graphify graph produced ✓
6. Polish → merge to main ✓

---

## Notes

- [P] = different files, no cross-task dependencies within phase
- T009 and T032 are validation checkpoints, not code tasks — mark complete after manual verification
- Generated stubs (`health_pb2.py`, `health_pb2_grpc.py`) are never committed; only `__init__.py` files in `packages/gen/src/` are committed
- All `uv run` invocations in Makefile targets assume the workspace is synced (`make bootstrap` ran first)
- CI uses `uv sync --frozen` to ensure reproducible installs from the lockfile
