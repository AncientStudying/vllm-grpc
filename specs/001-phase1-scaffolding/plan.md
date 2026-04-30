# Implementation Plan: Phase 1 — Scaffolding

**Branch**: `001-phase1-scaffolding` | **Date**: 2026-04-28 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/001-phase1-scaffolding/spec.md`

## Summary

Bring the repository from empty to a working monorepo where a new contributor can clone,
run `make bootstrap`, and reach a live end-to-end health-ping (`GET /healthz` → gRPC
`Health.Ping`) in under five minutes. CI must be green on `main` with lint, type-check,
test, and proto-compile jobs. The monorepo uses `uv` workspaces with three packages:
`gen` (generated stubs), `proxy` (FastAPI REST server), `frontend` (asyncio gRPC server).

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: FastAPI 0.115+, uvicorn[standard], grpcio 1.65+, grpcio-tools,
grpc-stubs (dev), pytest, pytest-asyncio, ruff, mypy, uv (workspace manager)
**Storage**: N/A
**Testing**: pytest + pytest-asyncio
**Target Platform**: macOS (M2 Pro, development) / Ubuntu 22.04 (GitHub Actions CI)
**Project Type**: Monorepo — REST proxy (web-service) + gRPC server
**Performance Goals**: Bootstrap < 5 min; proto compile < 30 s; `/healthz` round-trip < 3 s
**Constraints**: Generated stubs MUST NOT be committed; vllm NOT a dependency in Phase 1;
no TLS in Phase 1 (loopback only)
**Scale/Scope**: 2 runnable packages + 1 shared generated package; 1 proto service; 1 RPC

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Proto-First | ✅ PASS | `health.proto` is the first artifact; stubs not committed; `make proto` is the only generation mechanism |
| II. Library Dependency, Not Fork | ✅ PASS | `vllm` not added until Phase 3; no vLLM source touched |
| III. Phase Discipline | ✅ PASS | Scope matches exactly Phase 1 deliverables in PLAN.md; no Phase 3+ RPC stubs |
| IV. CI is the Merge Gate | ✅ PASS | CI workflows are Phase 1 deliverables; two workflow files cover all three job types |
| V. Honest Measurement | N/A | No benchmark work in Phase 1 |

*Post-design re-check*: All passing. No violations. Complexity Tracking table not required.

## Project Structure

### Documentation (this feature)

```text
specs/001-phase1-scaffolding/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── health-grpc.md   # Phase 1 output
│   └── rest-healthz.md  # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
.
├── README.md
├── LICENSE                          # MIT (already present)
├── Makefile                         # targets: bootstrap, proto, lint, typecheck, test, check, run-proxy, run-frontend
├── pyproject.toml                   # uv workspace root; members = ["packages/gen", "packages/proxy", "packages/frontend"]
├── .python-version                  # 3.12
├── .gitignore                       # includes packages/gen/src/vllm_grpc/
├── .github/
│   └── workflows/
│       ├── ci.yml                   # jobs: lint, typecheck, test
│       └── proto.yml                # job: proto-check (make proto + git diff)
├── .specify/                        # spec-kit (already present)
├── docs/
│   ├── PLAN.md                      # already present
│   ├── decisions/                   # ADRs (empty in Phase 1)
│   └── benchmarks/                  # phase results (empty in Phase 1)
├── proto/
│   └── vllm_grpc/
│       └── v1/
│           └── health.proto
├── packages/
│   ├── gen/
│   │   ├── pyproject.toml           # name="vllm-grpc-gen"; src layout
│   │   └── src/
│   │       └── vllm_grpc/           # generated (gitignored)
│   │           └── v1/
│   │               ├── __init__.py
│   │               ├── health_pb2.py
│   │               └── health_pb2_grpc.py
│   ├── proxy/
│   │   ├── pyproject.toml           # deps: fastapi, uvicorn, grpcio, vllm-grpc-gen
│   │   ├── src/
│   │   │   └── vllm_grpc_proxy/
│   │   │       ├── __init__.py
│   │   │       ├── grpc_client.py   # HealthStub wrapper
│   │   │       └── main.py          # FastAPI app + /healthz route
│   │   └── tests/
│   │       ├── conftest.py
│   │       └── test_healthz.py      # unit tests (mock gRPC client)
│   └── frontend/
│       ├── pyproject.toml           # deps: grpcio, vllm-grpc-gen
│       ├── src/
│       │   └── vllm_grpc_frontend/
│       │       ├── __init__.py
│       │       ├── health.py        # HealthServicer implementation
│       │       └── main.py          # gRPC server entry point
│       └── tests/
│           ├── conftest.py
│           └── test_health_ping.py  # unit tests (call servicer directly)
├── scripts/
│   └── curl/
│       └── healthz.sh               # curl -s http://localhost:8000/healthz
└── tools/                           # empty in Phase 1
```

**Structure Decision**: Three-package uv workspace (`gen`, `proxy`, `frontend`). The `gen`
package holds generated stubs and is the only workspace member that is not directly runnable.
This avoids duplicating stubs across packages and keeps the proto-to-Python dependency chain
explicit via `pyproject.toml` declarations.

## Complexity Tracking

> No constitution violations — table not required.
