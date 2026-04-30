# Research: Phase 1 — Scaffolding

**Phase**: 0 — Outline & Research
**Date**: 2026-04-28
**Branch**: `001-phase1-scaffolding`

---

## Decision 1: Python Version

**Decision**: Python 3.12

**Rationale**: vLLM officially supports Python 3.9–3.12. 3.12 is the latest stable release,
has the best performance characteristics (improved GIL handling, faster startup), and is
what `uv` will default to on a current macOS installation. It is also the version most likely
to be current when Phase 3 and later phases begin using `AsyncLLM`.

**Alternatives considered**:
- 3.11: Older but equally supported. No advantage over 3.12 for this project.
- 3.13: Not yet officially supported by vLLM as of 2026-04-28.

---

## Decision 2: Generated Stub Placement

**Decision**: `packages/gen/` — a dedicated `uv` workspace package named `vllm-grpc-gen`

**Rationale**: A shared workspace package is the cleanest pattern for generated code in a
`uv` monorepo. Both `proxy` and `frontend` declare `vllm-grpc-gen = {workspace = true}` in
their `pyproject.toml`, making the dependency explicit and typed. The generated files live
under `packages/gen/src/` (not committed) and are produced by `make proto` into the correct
output path. This is analogous to how AIBrix and other `vllm-project` sibling repos handle
shared generated artifacts.

**Proto output path**: `python -m grpc_tools.protoc -I proto --python_out=packages/gen/src
--grpc_python_out=packages/gen/src proto/vllm_grpc/v1/health.proto` produces:
- `packages/gen/src/vllm_grpc/v1/health_pb2.py`
- `packages/gen/src/vllm_grpc/v1/health_pb2_grpc.py`

Both proxy and frontend import as: `from vllm_grpc.v1 import health_pb2, health_pb2_grpc`

**Alternatives considered**:
- Generate into each package's own `src/`: duplicated stubs, harder to evolve the schema.
- Top-level `gen/` on `PYTHONPATH`: not proper packaging; doesn't integrate with `uv` workspace
  dependency resolution.
- Use `betterproto`: better Python ergonomics but adds a non-trivial dependency and generates
  dataclass-based stubs that are less familiar to gRPC practitioners. Revisit in a later phase
  if generated-code ergonomics become a pain point.

---

## Decision 3: Task Runner

**Decision**: `make` (GNU Make)

**Rationale**: `make` is installed by default on macOS (via Xcode command line tools) and on
all GitHub Actions Ubuntu runners. It requires zero additional setup, which satisfies the
"single bootstrap command" exit criterion. Required targets: `proto`, `lint`, `typecheck`,
`test`, `check` (runs all three), `run-proxy`, `run-frontend`.

**Alternatives considered**:
- `just`: Cleaner syntax and better error messages, but requires an explicit install step
  (`brew install just` or `cargo install just`), adding friction to the bootstrap path.
  Defer to a later phase if `make` becomes awkward.

---

## Decision 4: mypy + grpcio Type Stubs

**Decision**: Add `grpc-stubs` as a dev dependency in all packages that import grpcio

**Rationale**: `grpcio` ships no inline type annotations. `grpc-stubs` is the community-
maintained stub package (`pip install grpc-stubs`) that satisfies `mypy --strict` for
grpcio imports. Without it, every grpcio import produces an `error: Skipping analyzing
"grpc"` error under strict mode. `grpc-stubs` is a well-maintained package pinned to
grpcio version ranges.

**Alternatives considered**:
- `# type: ignore` on grpcio imports: violates the `mypy --strict` constitution principle.
- Inline stubs (`py.typed` marker in a local stub file): high maintenance burden.

---

## Decision 5: vLLM Dependency in Phase 1

**Decision**: Do not add `vllm` as a dependency of `packages/frontend` in Phase 1

**Rationale**: Phase 1's frontend implements only `Health.Ping` — it does not import
`vllm` at all. Adding the dependency now would require CI to install a multi-GB package
with CUDA dependencies for a health-ping test. vLLM will be added as a proper dependency
in Phase 3 when `AsyncLLM` is first referenced. This follows the Phase Discipline principle.

**Alternatives considered**:
- Add vllm as optional extra now: premature; adds complexity without benefit.

---

## Decision 6: HealthResponse Message Shape

**Decision**: `HealthResponse` contains a single `string message` field

**Rationale**: An empty response is sufficient to prove the RPC works, but a `message`
field (value: `"pong"`) makes the response visible in `grpc_cli` and `curl` output without
any extra tooling. It costs one field in the proto schema and zero implementation complexity.

**Alternatives considered**:
- Fully empty message: works but produces no visible output to confirm the call succeeded.
- Richer status enum: over-engineered for a health check; defer to a real health protocol
  (gRPC Health Checking Protocol v1) in a later phase if needed.

---

## Decision 7: REST /healthz Response Format

**Decision**: `{"status": "ok"}` with HTTP 200; `{"status": "error", "detail": "<msg>"}` with
HTTP 503 when the gRPC frontend is unreachable

**Rationale**: Standard convention for health endpoints. The two-state response keeps the
frontend unavailability case observable without adding complexity.

---

## Decision 8: CI Strategy

**Decision**: Two workflow files — `ci.yml` (lint + typecheck + test) and `proto.yml`
(proto compile check); both trigger on `push` and `pull_request` to `main`

**ci.yml** jobs:
1. `lint` — `uv run ruff check .` + `uv run ruff format --check .`
2. `typecheck` — `uv run mypy --strict packages/proxy/src packages/frontend/src`
3. `test` — `uv run pytest packages/proxy/tests packages/frontend/tests`

**proto.yml** job:
1. Install `grpcio-tools`, run `make proto`, assert `git diff --exit-code packages/gen/src`
   (stubs must match what `make proto` produces from committed `.proto` sources)

**uv in CI**: Use the official `astral-sh/setup-uv` action. `uv sync --frozen` installs
the workspace in CI without touching any global Python installation.

**Alternatives considered**:
- Single workflow: separation keeps the proto check independent and faster to re-run
  when only `.proto` files change.
- `pip install` in CI: slower than `uv`; doesn't use the lockfile.
