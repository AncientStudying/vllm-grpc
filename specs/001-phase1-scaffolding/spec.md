# Feature Specification: Phase 1 — Scaffolding

**Feature Branch**: `001-phase1-scaffolding`  
**Created**: 2026-04-28  
**Status**: Draft  
**Input**: User description: "Phase 1 — Scaffolding"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Developer Bootstrap (Priority: P1)

A new contributor clones the repository, runs a single bootstrap command, and has both the proxy server and gRPC frontend running locally with a working health-ping end-to-end. They should not need to know the internal project layout to get started.

**Why this priority**: This is the foundational exit criterion for the entire phase. Nothing else is verifiable until a contributor can bring the system up from scratch.

**Independent Test**: Clone the repo to a fresh directory, run the bootstrap command, confirm the proxy returns HTTP 200 on `/healthz` and the gRPC frontend responds to `Health.Ping`.

**Acceptance Scenarios**:

1. **Given** a freshly cloned repository with no pre-installed dependencies, **When** the contributor runs the documented bootstrap command, **Then** both the proxy and frontend start successfully with no manual intervention.
2. **Given** both services are running, **When** the proxy receives `GET /healthz`, **Then** it calls `Health.Ping` over gRPC to the frontend and returns HTTP 200 with an OK body.
3. **Given** both services are running, **When** the gRPC frontend receives a `Health.Ping` request directly, **Then** it returns a successful response.

---

### User Story 2 - CI Green on Main (Priority: P2)

A developer pushes to the `main` branch (or opens a PR against it) and GitHub Actions runs lint, type-checking, unit tests, and protobuf stub compilation automatically — all passing.

**Why this priority**: CI is the quality gate for every subsequent phase. It must be established before feature code is written.

**Independent Test**: Push any commit to main; all three CI workflows (lint/type, test, proto) pass green.

**Acceptance Scenarios**:

1. **Given** a commit on `main`, **When** CI runs, **Then** the lint and type-check job passes with zero errors.
2. **Given** a commit on `main`, **When** CI runs, **Then** the unit test job passes.
3. **Given** a commit on `main`, **When** CI runs, **Then** the protobuf stub compilation job runs `make proto` (or equivalent) successfully with no diff in generated files.
4. **Given** a code change that introduces a lint violation, **When** CI runs, **Then** the lint job fails and blocks the PR.

---

### User Story 3 - Spec-Kit Artifact Generation (Priority: P3)

A developer runs `/specify`, `/plan`, and `/tasks` within the project and each command produces useful, non-empty artifacts — confirming that spec-kit is wired up correctly.

**Why this priority**: Spec-kit is the planning backbone for all later phases. Its correct operation must be confirmed during Phase 1 while the repo is still simple.

**Independent Test**: Run each spec-kit command and confirm it produces a populated output file.

**Acceptance Scenarios**:

1. **Given** a feature description, **When** `/specify` is run, **Then** a populated `spec.md` is created in the appropriate feature directory.
2. **Given** a completed `spec.md`, **When** `/plan` is run, **Then** a `plan.md` is created with implementation tasks.
3. **Given** a completed `plan.md`, **When** `/tasks` is run, **Then** a `tasks.md` is created with ordered, actionable steps.

---

### User Story 4 - Knowledge Graph Indexing (Priority: P4)

A developer runs graphify against the repository and receives a rendered knowledge graph HTML file that correctly reflects the project's module structure and dependencies.

**Why this priority**: Graphify is listed as a Phase 1 deliverable and supports navigation for later phases, but it is not a blocking dependency for code development.

**Independent Test**: Run graphify; an HTML graph file is produced and contains nodes representing project components.

**Acceptance Scenarios**:

1. **Given** the scaffolded repository, **When** graphify is run, **Then** an HTML knowledge graph is produced.
2. **Given** the produced graph, **When** it is opened in a browser, **Then** it shows nodes for the main project components (proto, proxy, frontend).

---

### Edge Cases

- What happens when the bootstrap command is run a second time (idempotency)?
- How does the system behave if the gRPC frontend is not running when the proxy receives `/healthz`?
- What happens if `make proto` is run without the grpcio-tools dependency installed?
- How does CI handle a branch where protobuf stubs are committed but out of sync with the `.proto` sources?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The repository MUST be structured as a `uv` workspace monorepo containing two packages: `proxy` and `frontend`, as specified in `docs/PLAN.md §4`.
- **FR-002**: The workspace MUST be bootstrappable with a single command that installs all dependencies and generates protobuf stubs.
- **FR-003**: The `proto/` directory MUST contain a `Health` service with a `Ping` unary RPC, defined in a `.proto` file.
- **FR-004**: Protobuf Python stubs MUST be generated from source via a single task (e.g., `make proto`) and MUST NOT be committed to the repository.
- **FR-005**: The proxy package MUST expose `GET /healthz` and return HTTP 200 when the gRPC frontend is reachable.
- **FR-006**: The frontend package MUST implement the `Health.Ping` gRPC RPC and return a successful response.
- **FR-007**: The proxy MUST call `Health.Ping` on the frontend as part of handling `GET /healthz`, completing the end-to-end ping.
- **FR-008**: GitHub Actions CI MUST run on every push to `main` and on every pull request targeting `main`.
- **FR-009**: CI MUST include three distinct jobs: (a) lint and type-check, (b) unit tests, (c) protobuf stub compilation check.
- **FR-010**: The lint job MUST use `ruff` for linting and formatting, and `mypy --strict` for type-checking.
- **FR-011**: The test job MUST use `pytest` (with `pytest-asyncio` for async tests).
- **FR-012**: The CI proto job MUST verify that running `make proto` produces no uncommitted diff (i.e., generated stubs match source).
- **FR-013**: The repository MUST include a `README.md` with onboarding instructions sufficient for a new contributor to bootstrap and run the ping demo.
- **FR-014**: The `CLAUDE.md` project config MUST reference `docs/PLAN.md` so Claude Code has context when starting a session.
- **FR-015**: A task runner (`make` or `just`) MUST provide at minimum these targets: `proto`, `lint`, `test`, `typecheck`, and a combined `check` target.

### Key Entities

- **Proxy Package** (`packages/proxy/`): A minimal async HTTP server exposing `/healthz`. Depends on the generated gRPC stubs at runtime.
- **Frontend Package** (`packages/frontend/`): A minimal async gRPC server implementing `Health.Ping`. Depends on `vllm` as a library (though not invoked in Phase 1).
- **Proto Schema** (`proto/vllm_grpc/v1/`): The protobuf source of truth. Contains `health.proto` with the `Health.Ping` RPC. Generated stubs are ephemeral (build-time only).
- **Generated Stubs**: Python files produced by `grpcio-tools` from `.proto` sources. Placed in a known location for both packages to import.
- **CI Workflows** (`.github/workflows/`): `ci.yml` (lint, type, test) and `proto.yml` (stub compile check).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new contributor can clone the repository and reach a running ping demo (proxy + frontend, end-to-end `GET /healthz` succeeds) in under five minutes using only the README instructions.
- **SC-002**: All three CI jobs pass green on `main` with zero manual intervention after the initial push.
- **SC-003**: Running the bootstrap command twice in succession produces the same result (idempotent).
- **SC-004**: The protobuf stub compilation task completes in under thirty seconds on the development machine.
- **SC-005**: Each spec-kit command (`/specify`, `/plan`, `/tasks`) produces a non-empty artifact file when invoked against a valid input.
- **SC-006**: The graphify knowledge graph contains at least three distinct component nodes (proxy, frontend, proto) when run against the scaffolded repository.

## Assumptions

- The development machine is an M2 Pro MacBook Pro with macOS and `uv` pre-installed; contributors on other platforms are not the primary audience for this phase.
- `grpcio` and `grpcio-tools` are the chosen protobuf/gRPC libraries (confirmed in `docs/PLAN.md §3`).
- `grpc.aio` (asyncio gRPC) is used for the frontend server (confirmed in `docs/PLAN.md §3`).
- `FastAPI` + `uvicorn` is used for the proxy server (confirmed in `docs/PLAN.md §3`).
- The task runner choice (`make` vs `just`) is deferred to implementation; either is acceptable as long as it provides the required targets.
- The `vllm` package is listed as a dependency for the frontend but is not invoked in Phase 1 (health ping only). Its installation may be skipped in the CI environment to keep CI fast.
- Generated stubs are placed under a `gen/` or `src/generated/` directory within each package (exact path decided during `/plan`).
- The `Health.Ping` RPC uses an empty request and response message for simplicity.
- graphify is configured via its own config file (e.g., `graphify.json`) at the repo root; exact configuration is resolved during implementation.
