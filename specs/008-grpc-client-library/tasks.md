# Tasks: Direct gRPC Client Library (Phase 4.2)

**Input**: Design documents from `specs/008-grpc-client-library/`  
**Branch**: `008-direct-grpc-client`

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to
- No test tasks — spec does not request TDD; constitution unit-test requirement is scoped to translation logic and covered by existing test patterns

---

## Phase 1: Setup (Package Scaffold)

**Purpose**: Register the new package in the workspace and lay down the file skeleton before any logic is written.

- [X] T001 Add `"packages/client"` to `[tool.uv.workspace] members` list in `pyproject.toml`
- [X] T002 Create `packages/client/pyproject.toml` with name `vllm-grpc-client`, `requires-python = ">=3.12"`, dependencies `grpcio>=1.65` and `vllm-grpc-gen` (workspace source), hatchling build backend, wheel target `packages = ["src/vllm_grpc_client"]`
- [X] T003 [P] Create empty `packages/client/src/vllm_grpc_client/__init__.py`
- [X] T004 [P] Create empty `packages/client/src/vllm_grpc_client/py.typed`
- [X] T005 Add `"vllm-grpc-client"` to `[project] dependencies` and `[tool.uv.sources] vllm-grpc-client = { workspace = true }` in `tools/benchmark/pyproject.toml`

**Checkpoint**: `uv sync` succeeds; `packages/client` appears in the workspace.

---

## Phase 2: User Story 1 — Python gRPC Client Library (Priority: P1) 🎯 MVP

**Goal**: `VllmGrpcClient` async context manager with `chat.complete()` — usable from Python in under 10 lines with no proxy process.

**Independent Test**: Instantiate `VllmGrpcClient("host:port")`, call `chat.complete()` with `seed=42` against a running frontend, verify a typed `ChatCompleteResult` is returned. Run twice; both responses must have identical `content`.

- [X] T006 [US1] Implement `ChatCompleteResult` dataclass (fields: `content`, `role`, `finish_reason`, `prompt_tokens`, `completion_tokens`) and `ChatClient` class with `complete()` method that maps `messages: list[dict[str, str]]` → `repeated ChatMessage`, calls `ChatService.Complete` unary RPC, and returns `ChatCompleteResult` in `packages/client/src/vllm_grpc_client/chat.py`
- [X] T007 [US1] Implement `VllmGrpcClient` with `addr: str`, `timeout: float = 30.0`, `__aenter__` opening `grpc.aio.insecure_channel(addr)`, `__aexit__` calling `await channel.close()`, and `.chat` property returning a `ChatClient` bound to the shared channel in `packages/client/src/vllm_grpc_client/client.py`
- [X] T008 [US1] Export `VllmGrpcClient` from `packages/client/src/vllm_grpc_client/__init__.py` (single public symbol)
- [X] T009 [US1] Verify `mypy --strict packages/client` passes with zero errors and `ruff check packages/client` passes with zero violations

**Checkpoint**: `from vllm_grpc_client import VllmGrpcClient` works; `mypy --strict` passes; quickstart Scenario 1 can be executed against a running frontend.

---

## Phase 3: User Story 2 — Three-Way Benchmark (Priority: P2)

**Goal**: Single `make bench-modal` run produces REST / gRPC-proxy / gRPC-direct comparison report in `docs/benchmarks/`.

**Independent Test**: Run `make bench-modal`. Verify all three targets complete with zero errors and `docs/benchmarks/phase-4.2-three-way-comparison.md` exists with all metrics populated.

- [X] T010 [US2] Add `ThreeWayRow` dataclass (`metric`, `concurrency`, `value_a`, `value_b`, `value_c`, `delta_pct_b`, `delta_pct_c` — all matching contracts/three-way-bench.md) and `ThreeWayReport` dataclass (`label_a`, `label_b`, `label_c`, `rows`, `meta_a`, `meta_b`, `meta_c`) to `tools/benchmark/src/vllm_grpc_bench/metrics.py`
- [X] T011 [US2] Implement `compare_three_way(run_a, run_b, run_c, label_a, label_b, label_c) -> ThreeWayReport` covering metrics `latency_p50_ms`, `latency_p95_ms`, `latency_p99_ms`, `throughput_rps`, `request_bytes_mean`, `response_bytes_mean` with `delta_pct_b/c = (val - val_a) / val_a * 100` (None if either is None or val_a == 0) in `tools/benchmark/src/vllm_grpc_bench/compare.py`
- [X] T012 [US2] Implement `write_three_way_md(report: ThreeWayReport, path: Path) -> None` writing a markdown table with columns `metric | concurrency | {label_a} | {label_b} | Δ vs {label_a} | {label_c} | Δ vs {label_a}` in `tools/benchmark/src/vllm_grpc_bench/reporter.py`
- [X] T013 [US2] Add `compare-three-way` subcommand with required `--result-a/b/c PATH` and optional `--label-a/b/c LABEL` (defaults: `rest`, `grpc-proxy`, `grpc-direct`) and `--output PATH` following the same validation pattern as `compare-cross` in `tools/benchmark/src/vllm_grpc_bench/__main__.py`
- [X] T014 [US2] Add `run_grpc_target(addr: str, samples: list[RequestSample], concurrency: int, timeout: float) -> list[RequestResult]` using `VllmGrpcClient` (one channel, shared across semaphore-bounded `asyncio.gather`), setting `target="grpc-direct"`, measuring `request_bytes = len(ChatCompleteRequest(...).SerializeToString())` and `response_bytes = len(response_proto.SerializeToString())`; extend `Target` literal to `Literal["proxy", "native", "grpc-direct"]` in `tools/benchmark/src/vllm_grpc_bench/runner.py`
- [X] T015 [US2] Extend the gRPC phase in `scripts/python/bench_modal.py`: after the proxy harness run completes, keep `serve_grpc_for_bench` alive, tear down the local proxy subprocess, then call `run_grpc_target(grpc_addr, ...)` and write raw results to `_GRPC_DIRECT_RESULTS` (a new `pathlib.Path` constant pointing to the results dir)
- [X] T016 [US2] Extend the comparison phase in `scripts/python/bench_modal.py`: load all three result JSONs, call `compare_three_way()`, call `write_three_way_md()`, and write all five output files to `docs/benchmarks/` only after all three targets succeed — if any target produced errors or the harness raised, skip all output writes and exit non-zero (FR-008)

**Checkpoint**: `python -m vllm_grpc_bench compare-three-way --help` works; `mypy --strict tools/benchmark` passes.

---

## Phase 4: User Story 3 — py.typed for Generated Stubs (Priority: P3)

**Goal**: All consumers of `vllm_grpc` can import generated types without `# type: ignore[import-untyped]`.

**Independent Test**: Remove all `# type: ignore[import-untyped]` lines. Run `mypy --strict packages/proxy packages/frontend packages/client`. Verify zero errors referencing missing type information from `vllm_grpc`.

- [X] T017 [US3] Create empty file `packages/gen/src/vllm_grpc/py.typed` (PEP 561 marker)
- [X] T018 [P] [US3] Remove `# type: ignore[import-untyped]` from `vllm_grpc.v1` imports in `packages/proxy/src/vllm_grpc_proxy/chat_translate.py`, `packages/proxy/src/vllm_grpc_proxy/grpc_client.py`, `packages/proxy/tests/test_chat_translate.py`, and `packages/proxy/tests/test_chat_endpoint.py`
- [X] T019 [P] [US3] Remove `# type: ignore[import-untyped]` from `vllm_grpc.v1` imports in `packages/frontend/src/vllm_grpc_frontend/chat.py`, `packages/frontend/src/vllm_grpc_frontend/health.py`, `packages/frontend/src/vllm_grpc_frontend/chat_translate.py`, `packages/frontend/src/vllm_grpc_frontend/main.py`, `packages/frontend/tests/test_chat_servicer.py`, `packages/frontend/tests/test_chat_translate.py`, and `packages/frontend/tests/test_health_ping.py` — leave `# type: ignore[misc]` and `# type: ignore[type-arg]` in `chat.py` and `health.py` intact (grpcio servicer gaps, out of scope)
- [X] T020 [US3] Verify `mypy --strict packages/proxy packages/frontend packages/client` shows zero errors referencing missing type information from `vllm_grpc`

**Checkpoint**: No `import-untyped` suppressions remain for `vllm_grpc` imports across all three packages; `misc`/`type-arg` suppressions in frontend remain untouched.

---

## Phase 5: Polish & Validation

**Purpose**: End-to-end validation — benchmark run + CI gate verification.

- [X] T021 Run `make bench-modal` (requires Modal credentials and pre-staged model weights) to generate Phase 4.2 baseline results; commit the five output files (`phase-4.2-grpc-direct-baseline.json`, `phase-4.2-grpc-direct-baseline.md`, `phase-4.2-three-way-comparison.md`, `phase-4.2-rest-baseline.json`, `phase-4.2-grpc-proxy-baseline.json`) to `docs/benchmarks/`
- [X] T022 Verify `make lint` and `make typecheck` pass across all packages (`packages/gen`, `packages/proxy`, `packages/frontend`, `packages/client`, `tools/benchmark`)
- [X] T023 Verify `make test` passes for `packages/proxy`, `packages/frontend`, and `tools/benchmark`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **US1 (Phase 2)**: Requires Phase 1 complete (workspace registration + scaffold)
- **US2 (Phase 3)**: Requires US1 complete (T006–T009); `run_grpc_target` imports `VllmGrpcClient`
- **US3 (Phase 4)**: Independent of US1 and US2 after Phase 1; T017 can start as soon as Phase 1 is done; T018/T019 can run in parallel with US1 work if desired
- **Polish (Phase 5)**: Requires US1, US2, US3 all complete

### Within Each Phase

- T003 and T004 (Phase 1) are parallel — different files
- T006 before T007 — `ChatCompleteResult` must exist before `ChatClient` can return it (same file, sequential)
- T007 before T008 — client.py imports from chat.py
- T010 before T011 — `ThreeWayReport` must exist before `compare_three_way()` can return it
- T011 before T012 — `ThreeWayReport` must exist before `write_three_way_md()` can accept it
- T010–T013 can be done before T014–T016 since they only extend the benchmark tool; T014 (runner.py) and T015–T016 (bench_modal.py) can be sequenced after the data model work
- T018 and T019 (Phase 4) are parallel — different packages
- T018/T019 depend on T017 — py.typed must exist first

---

## Parallel Execution Examples

```bash
# Phase 1 parallel tasks:
Task: "Create packages/client/src/vllm_grpc_client/__init__.py"
Task: "Create packages/client/src/vllm_grpc_client/py.typed"

# Phase 4 parallel tasks (different packages):
Task: "Remove import-untyped from packages/proxy/"
Task: "Remove import-untyped from packages/frontend/"
```

---

## Implementation Strategy

### MVP (US1 Only — 9 tasks)

1. Phase 1: Setup (T001–T005)
2. Phase 2: US1 Client Library (T006–T009)
3. **STOP and VALIDATE**: Instantiate client against a running frontend; verify typed response

### Incremental Delivery

1. Setup → US1 → **validate** client library standalone
2. US1 → US2 → **validate** three-way benchmark report
3. US2 → US3 → **validate** zero mypy suppressions
4. Polish → **commit** baseline files and CI gate

---

## Notes

- T018 and T019 touch different packages — safe to run in parallel
- Frontend `# type: ignore[misc]` and `# type: ignore[type-arg]` in `chat.py`/`health.py` are grpcio servicer inheritance gaps — do NOT remove them
- T021 (`make bench-modal`) requires Modal credentials; run last
- Wire bytes in `run_grpc_target` must be protobuf serialized sizes — not HTTP content-length
- The gRPC serve function in bench_modal.py must stay alive between T015 and T016 (proxy run → direct run) to avoid a second cold start
