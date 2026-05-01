# Tasks: Phase 3 — Minimal Non-Streaming Chat Completion Bridge

**Input**: Design documents from `specs/003-chat-bridge/`
**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ contracts/ ✅ quickstart.md ✅

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no unresolved dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Wire in the new proto, integration test directory, and `openai` dev dependency before
any implementation code is written.

- [ ] T001 Update `Makefile` proto target to compile `proto/vllm_grpc/v1/chat.proto` alongside `health.proto`; add `tests/integration` to the `test` target's pytest invocation
- [ ] T002 [P] Add `"openai>=1.0"` to `[dependency-groups] dev` in `pyproject.toml`; run `uv sync --all-packages` to confirm it resolves without conflicts
- [ ] T003 [P] Create `tests/integration/__init__.py` (empty) and `tests/integration/conftest.py` (empty pytest conftest placeholder) at the workspace root

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The proto schema and the `FakeChatServicer` test fixture are prerequisites for every
user story. No story implementation can begin until these are in place.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T004 Write `proto/vllm_grpc/v1/chat.proto` — define `ChatMessage` (role, content), `ChatCompleteRequest` (messages, model, max_tokens, optional temperature/top_p/seed), `ChatCompleteResponse` (message, finish_reason, prompt_tokens, completion_tokens), and `ChatService.Complete` unary RPC; see `contracts/chat-proto.md` for the exact definition
- [ ] T005 Run `make proto`; confirm `packages/gen/src/vllm_grpc/v1/chat_pb2.py` and `chat_pb2_grpc.py` are generated; add `"vllm_grpc.v1.chat_pb2"` and `"vllm_grpc.v1.chat_pb2_grpc"` to the `ignore_errors = true` override block in `pyproject.toml`'s `[tool.mypy.overrides]` section; confirm `.gitignore` excludes the generated chat stubs
- [ ] T006 Implement `tests/integration/fake_frontend.py` — a `FakeChatServicer` class that implements `ChatService.Complete` (using the generated `chat_pb2_grpc` base class) and returns a hardcoded `ChatCompleteResponse` (message.role="assistant", message.content="4.", finish_reason="stop", prompt_tokens=10, completion_tokens=3) without importing vllm; also implement an async context-manager helper `fake_frontend_server(port)` that starts and stops a `grpc.aio.server` with the servicer attached

**Checkpoint**: Proto stubs compile; `FakeChatServicer` exists and is importable. User story work can begin.

---

## Phase 3: User Story 1 — End-to-End Non-Streaming Chat Completion (Priority: P1) 🎯 MVP

**Goal**: A `POST /v1/chat/completions` request flows through proxy → gRPC → servicer → proto → proxy → OpenAI JSON. This is the core architectural proof.

**Independent Test**: `pytest tests/integration/test_chat_bridge.py -v` passes using `FakeChatServicer` (no GPU needed).

### Implementation for User Story 1

- [ ] T007 [P] [US1] Implement `packages/proxy/src/vllm_grpc_proxy/chat_translate.py` — define `OpenAIChatMessage` and `OpenAIChatRequest` Pydantic models (fields from `contracts/rest-api.md`); implement `openai_request_to_proto(req: OpenAIChatRequest) -> chat_pb2.ChatCompleteRequest` and `proto_response_to_openai_dict(resp: chat_pb2.ChatCompleteResponse, model: str) -> dict[str, Any]` (constructs the full OpenAI JSON dict per `contracts/rest-api.md` including uuid4 id, timestamp, choices, usage)
- [ ] T008 [P] [US1] Implement `packages/frontend/src/vllm_grpc_frontend/chat_translate.py` — implement `proto_to_sampling_params(req: chat_pb2.ChatCompleteRequest) -> SamplingParams` (maps max_tokens, temperature/top_p/seed with correct defaults per `research.md` R2); implement `messages_to_prompt(messages: list[chat_pb2.ChatMessage], tokenizer: PreTrainedTokenizer) -> str` (calls `tokenizer.apply_chat_template` per `research.md` R3); implement `request_output_to_proto(output: RequestOutput) -> chat_pb2.ChatCompleteResponse` (extracts text, finish_reason, token counts per `data-model.md` Layer 3)
- [ ] T009 [P] [US1] Write `packages/proxy/tests/test_chat_translate.py` — unit tests for `openai_request_to_proto()` (all fields present, optional fields absent, empty messages list rejected) and `proto_response_to_openai_dict()` (finish_reason=stop, finish_reason=length, usage counts correct)
- [ ] T010 [P] [US1] Write `packages/frontend/tests/test_chat_translate.py` — unit tests for `proto_to_sampling_params()` (seed present vs absent, temperature/top_p defaults) and `request_output_to_proto()` (finish_reason=stop with token counts, finish_reason=length)
- [ ] T011 [US1] Extend `packages/proxy/src/vllm_grpc_proxy/grpc_client.py` — add `GrpcChatClient` class (mirrors `GrpcHealthClient` pattern): `__init__(addr)`, `async def complete(req: chat_pb2.ChatCompleteRequest) -> chat_pb2.ChatCompleteResponse` (opens channel, calls `ChatServiceStub.Complete` with 30-second deadline); depends on T004 stubs compiled
- [ ] T012 [US1] Implement `packages/proxy/src/vllm_grpc_proxy/chat_router.py` — FastAPI `APIRouter`; `POST /v1/chat/completions` endpoint that: (1) parses body into `OpenAIChatRequest`, (2) returns HTTP 501 JSON if `stream=True` (per `contracts/rest-api.md` error format), (3) calls `openai_request_to_proto()`, (4) calls `GrpcChatClient.complete()`, (5) returns `JSONResponse(proto_response_to_openai_dict(...))`; maps `grpc.aio.AioRpcError` to HTTP 502/504/422 per error table; depends on T007, T011
- [ ] T013 [US1] Update `packages/proxy/src/vllm_grpc_proxy/main.py` — instantiate `GrpcChatClient` at module level; include `chat_router.router` in the FastAPI app; depends on T012
- [ ] T014 [US1] Implement `packages/frontend/src/vllm_grpc_frontend/chat.py` — `ChatServicer` class implementing `chat_pb2_grpc.ChatServiceServicer`; `__init__(engine: AsyncLLM, tokenizer: PreTrainedTokenizer)`; `async def Complete(request, context)` calls `messages_to_prompt()`, `proto_to_sampling_params()`, the async generator loop per `research.md` R2, then `request_output_to_proto()`; depends on T008
- [ ] T015 [US1] Update `packages/frontend/src/vllm_grpc_frontend/main.py` — instantiate `AsyncLLM` and tokenizer at startup using `MODEL_NAME` env var (default `Qwen/Qwen3-0.6B`); register `ChatServicer` via `chat_pb2_grpc.add_ChatServiceServicerToServer()`; depends on T014
- [ ] T016 [P] [US1] Write `packages/proxy/tests/test_chat_endpoint.py` — tests for `POST /v1/chat/completions` using `httpx.AsyncClient(app=app, base_url="http://test")`; mock `GrpcChatClient.complete()` to return a canned proto response; assert: (1) happy path returns HTTP 200 with valid OpenAI JSON, (2) `stream=True` returns HTTP 501 with `error.message`, (3) gRPC `UNAVAILABLE` returns HTTP 502; depends on T012
- [ ] T017 [P] [US1] Write `packages/frontend/tests/test_chat_servicer.py` — test `ChatServicer.Complete()` with a stub `AsyncLLM` that yields a pre-built `RequestOutput`; assert `ChatCompleteResponse` fields match expected values; test with seed present and seed absent; depends on T014
- [ ] T018 [US1] Write `tests/integration/test_chat_bridge.py` — pytest asyncio test that: (1) uses `fake_frontend_server()` fixture to start `FakeChatServicer` on ephemeral port, (2) points `GrpcChatClient` at that port and starts FastAPI via `httpx.AsyncClient(app=app)`, (3) sends `POST /v1/chat/completions` with seed=42, (4) asserts response is HTTP 200 with `choices[0].message.content == "4."` and `usage.total_tokens > 0`; depends on T006, T013
- [ ] T019 [US1] Run `make check` (lint + typecheck + test); fix all ruff format/lint errors and mypy --strict errors; confirm `test_chat_bridge.py` passes

**Checkpoint**: `make check` passes. Full proxy → gRPC → FakeChatServicer → OpenAI JSON pipeline works. US1 is complete and independently testable.

---

## Phase 4: User Story 2 — OpenAI SDK Compatibility (Priority: P2)

**Goal**: The `openai` Python SDK can call the proxy via `base_url` without errors.

**Independent Test**: `uv run python scripts/python/chat-nonstreaming.py` runs against a live proxy and prints a completion without raising `openai.APIError`.

### Implementation for User Story 2

- [ ] T020 [US2] Implement `scripts/python/chat-nonstreaming.py` — uses `openai.OpenAI(base_url="http://localhost:8000/v1", api_key="none")` to call `client.chat.completions.create(model="Qwen/Qwen3-0.6B", messages=[...], max_tokens=64, seed=42)`; prints `response.choices[0].message.content`; prints `response.usage`; handles `openai.APIError` with a clear diagnostic message and non-zero exit; depends on T013 being runnable

**Checkpoint**: US2 complete — existing openai SDK client code works against the proxy unchanged.

---

## Phase 5: User Story 3 — Streaming Rejection (Priority: P3)

**Goal**: `stream: true` returns HTTP 501 with a human-readable error — never crashes, never hangs.

**Independent Test**: `curl -X POST http://localhost:8000/v1/chat/completions -d '{"stream":true,...}'` returns HTTP 501 with `{"error":{"message":"...","type":"not_implemented_error"}}`.

### Implementation for User Story 3

- [ ] T021 [US3] Verify `packages/proxy/tests/test_chat_endpoint.py` includes a dedicated test for `stream=True` → HTTP 501 with JSON body containing `error.message` and `error.type == "not_implemented_error"`; add or strengthen the test case if the assertion in T016 is not explicit enough; run `make test` to confirm it passes

**Checkpoint**: US3 complete — the 501 error path is explicitly tested and documented.

---

## Phase 6: User Story 4 — Fast Local Demo (Priority: P3)

**Goal**: Proxy + frontend start from scratch and serve a first chat completion in under 2 minutes on the M2.

**Independent Test**: `bash scripts/curl/chat-nonstreaming.sh` exits 0 and prints a non-empty completion against a live proxy; `make test` completes cleanly from a fresh checkout.

### Implementation for User Story 4

- [ ] T022 [US4] Implement `scripts/curl/chat-nonstreaming.sh` — curl `POST http://localhost:8000/v1/chat/completions` with `Content-Type: application/json`, body with `model`, `messages`, `max_tokens=64`, `seed=42`; pipe response through `python -m json.tool` for readable output; include a usage comment at the top explaining `PROXY_PORT` override; make the script executable (`chmod +x`)
- [ ] T023 [US4] Validate quickstart.md Option B end-to-end: run `make bootstrap && make test` from a clean state (`uv sync --all-packages && make proto` then `make check`); confirm the full sequence completes without manual intervention; note any discrepancy with quickstart.md and update that file if needed

**Checkpoint**: US4 complete — `scripts/curl/chat-nonstreaming.sh` and `scripts/python/chat-nonstreaming.py` both work against a live proxy; `make test` is self-healing from scratch.

---

## Final Phase: Polish & Cross-Cutting Concerns

- [ ] T024 [P] Update `README.md` — add Phase 3 to the project status section; add `make run-proxy` and `make run-frontend` invocation examples; note the `scripts/curl/chat-nonstreaming.sh` and `scripts/python/chat-nonstreaming.py` entry points
- [ ] T025 [P] Verify `.gitignore` explicitly excludes `packages/gen/src/vllm_grpc/v1/chat_pb2.py` and `packages/gen/src/vllm_grpc/v1/chat_pb2_grpc.py`; add patterns if missing
- [ ] T026 Run `make check` from a completely clean state (`git clean -fdx` + `make bootstrap` + `make check`); confirm lint, typecheck, unit tests, and integration tests all pass; this is the final CI gate validation before opening the PR

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001, T002, T003 can all start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion — **BLOCKS all user stories**
  - T004 → T005 → T006 must run in order
- **US1 (Phase 3)**: Depends on Foundational completion; T007–T010 can start together after T005; T011 depends on T004/T005; T012 depends on T007 + T011; T014 depends on T008; T016 depends on T012; T017 depends on T014; T018 depends on T006 + T013
- **US2 (Phase 4)**: Depends on T013 (proxy runnable); can start after T019
- **US3 (Phase 5)**: Depends on T016 — just a verification/strengthening step
- **US4 (Phase 6)**: Depends on T013 (proxy) and T015 (frontend) being runnable
- **Polish**: Depends on all user stories complete

### User Story Dependencies

- **US1 (P1)**: Depends only on Foundational. No dependency on US2/US3/US4.
- **US2 (P2)**: Depends on US1 (proxy must be runnable). Otherwise independent.
- **US3 (P3)**: Depends on US1 (chat router must exist). Just a test verification step.
- **US4 (P3)**: Depends on US1 (both servers must be runnable). Otherwise independent.

### Within User Story 1 (Phase 3)

```
T007 (proxy translate) ──┐
T008 (frontend translate)─┤──→ T011 (grpc client) ──→ T012 (chat router) ──→ T013 (proxy main)
T009 (proxy tests) ──────┤                                                         │
T010 (frontend tests) ───┘                                                         │
                                                                                   ↓
T008 (frontend translate) ──→ T014 (ChatServicer) ──→ T015 (frontend main) ──→ T018 (integration test)
T016 (endpoint tests) ← depends on T012                                           ↑
T017 (servicer tests) ← depends on T014            T006 (FakeChatServicer) ───────┘
```

---

## Parallel Opportunities

### Phase 1 (all parallel)

```
T001 (Makefile)
T002 (pyproject openai dep)     ← all three can run simultaneously
T003 (integration dir)
```

### Phase 3 — First batch (all parallel after Foundational)

```
T007 (proxy/chat_translate.py)
T008 (frontend/chat_translate.py)
T009 (proxy/test_chat_translate.py)     ← all four can run simultaneously
T010 (frontend/test_chat_translate.py)
```

### Phase 3 — Second batch (parallel after translations)

```
T011 (grpc_client.py GrpcChatClient)    ← parallel; T011 only needs proto stubs (T005)
T014 (frontend/chat.py ChatServicer)    ← parallel; depends only on T008
```

### Phase 3 — Test batch (parallel after implementations)

```
T016 (proxy/test_chat_endpoint.py)      ← parallel; depends on T012
T017 (frontend/test_chat_servicer.py)   ← parallel; depends on T014
```

---

## Implementation Strategy

### MVP First (User Story 1 Only — Phases 1–3)

1. Complete Phase 1: Setup (T001–T003)
2. Complete Phase 2: Foundational (T004–T006) — **BLOCKS everything**
3. Complete Phase 3: US1 (T007–T019)
4. **STOP and VALIDATE**: `make check` passes; `test_chat_bridge.py` passes
5. Demo: start `FakeChatServicer` + proxy; `curl` the endpoint

### Incremental Delivery

1. Phases 1–2 → proto + FakeChatServicer ready
2. Phase 3 → full non-streaming bridge works in CI
3. Phase 4 → Python openai SDK example works live
4. Phase 5 → streaming rejection explicitly tested
5. Phase 6 → curl script + quickstart validated; demo ready
6. Final phase → README + CI gate clean

---

## Notes

- Proto-first: T004 (write the proto) must precede all implementation. The proto is the single source of truth.
- TDD: write tests (T009, T010, T016, T017) alongside their corresponding implementations. Tests should fail before the implementation file exists.
- `mypy --strict`: the `chat_translate.py` modules in both packages must be fully typed. Use `from __future__ import annotations` and explicit return types throughout.
- The `FakeChatServicer` (T006) must NOT import `vllm` — this is the key to keeping CI fast and GPU-free.
- Commit after each phase checkpoint.
