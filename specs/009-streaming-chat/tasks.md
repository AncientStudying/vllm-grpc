# Tasks: Streaming Chat Completions (Phase 5)

**Input**: Design documents from `specs/009-streaming-chat/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Organization**: Tasks grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- All paths are relative to repository root

---

## Phase 1: Setup (Proto Schema)

**Purpose**: Extend the protobuf schema. Required before any package code references new types.

**⚠️ CRITICAL**: Nothing else can begin until the stubs are regenerated.

- [x] T001 Add `ChatStreamChunk` message and `CompleteStream` server-streaming RPC to `proto/vllm_grpc/v1/chat.proto` per `contracts/chat-proto.md`
- [x] T002 Regenerate stubs via `make proto` — confirm `chat_pb2.ChatStreamChunk` and `chat_pb2_grpc.ChatServiceStub.CompleteStream` are accessible

**Checkpoint**: `make proto` runs cleanly; new types importable from `vllm_grpc.v1`.

---

## Phase 2: Foundational (Frontend Servicer + ADR)

**Purpose**: Frontend streaming implementation and architectural decision record. MUST complete before US1, US2, or US3 can proceed.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T003 [P] Write ADR `docs/decisions/0003-streaming-design.md` covering: chunk granularity (one proto message per token), error encoding (gRPC status → SSE error event), back-pressure model (native async generator yield), cancellation semantics (asyncio chain: client → proxy → gRPC → engine) (FR-012)
- [x] T004 [P] Add `output_to_stream_chunk(output: Any, token_index: int) -> chat_pb2.ChatStreamChunk` helper to `packages/frontend/src/vllm_grpc_frontend/chat_translate.py` — extract `outputs[0].text` delta, map `finish_reason`, populate `token_index`
- [x] T005 Add `CompleteStream` async-generator servicer method to `packages/frontend/src/vllm_grpc_frontend/chat.py` — iterate `engine.generate()`, call `output_to_stream_chunk()` per token, check `context.is_active()` before each yield, handle `asyncio.CancelledError` cleanly; return type `AsyncIterator[chat_pb2.ChatStreamChunk]`
- [x] T006 Add unit tests for `output_to_stream_chunk()` (in `packages/frontend/tests/test_chat_translate.py`) and `CompleteStream` servicer (in `packages/frontend/tests/test_chat_servicer.py`) — mock engine yielding N outputs, verify chunk sequence, verify final chunk has `finish_reason != ""` and `delta_content == ""`, verify `context.is_active() == False` causes early return

**Checkpoint**: `CompleteStream` servicer passes unit tests; `make typecheck` shows no new errors in frontend package.

---

## Phase 3: User Story 1 — Streaming via Proxy (Priority: P1) 🎯 MVP

**Goal**: `POST /v1/chat/completions` with `"stream": true` returns OpenAI-compatible SSE deltas via the proxy, terminating with `data: [DONE]`.

**Independent Test**: `curl -N http://localhost:8000/v1/chat/completions -d '{"stream":true,"model":"Qwen/Qwen3-0.6B","messages":[{"role":"user","content":"hi"}],"max_tokens":5,"seed":42}'` — SSE deltas arrive incrementally; concatenated content equals non-streaming response for same seed.

- [x] T007 [P] [US1] Add `stream_complete(req: chat_pb2.ChatCompleteRequest) -> AsyncIterator[chat_pb2.ChatStreamChunk]` to `GrpcChatClient` in `packages/proxy/src/vllm_grpc_proxy/grpc_client.py` — call `stub.CompleteStream(req, timeout=...)` and return the `grpc.aio.UnaryStreamCall` as an async iterator; store the call reference for cancellation
- [x] T008 [P] [US1] Add SSE encoding helpers to `packages/proxy/src/vllm_grpc_proxy/chat_translate.py`: `proto_chunk_to_sse_event(chunk, completion_id, created, model) -> str` (formats a single `data: {...}\n\n` line per SSE delta contract), `format_sse_done() -> str` (returns `data: [DONE]\n\n`), `format_sse_error(message) -> str` (formats error event per `contracts/sse-format.md`)
- [x] T009 [US1] Add unit tests for SSE encoding helpers in `packages/proxy/tests/test_chat_translate.py` — verify first-chunk role delta, mid-chunk content delta, final-chunk empty delta + finish_reason, `[DONE]` format, error event format
- [x] T010 [US1] Implement streaming route in `packages/proxy/src/vllm_grpc_proxy/chat_router.py` — replace 501 stub with `StreamingResponse(media_type="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})`; async generator yields: role-delta SSE event, then one content-delta event per `ChatStreamChunk`, then finish-reason event, then `[DONE]`; poll `request.is_disconnected()` between chunks and cancel gRPC call + return on disconnect; catch `grpc.aio.AioRpcError` and emit SSE error event
- [x] T011 [US1] Add `CompleteStream` to `FakeChatServicer` in `tests/integration/fake_frontend.py` — yield 3 `ChatStreamChunk` messages (`delta_content="Hello"`, `delta_content=" world"`, `delta_content=""` with `finish_reason="stop"`)
- [x] T012 [US1] Add streaming endpoint unit tests to `packages/proxy/tests/test_chat_endpoint.py` — mock `GrpcChatClient.stream_complete()` yielding fake chunks; verify: `Content-Type: text/event-stream`, SSE role-delta on first event, content-delta per chunk, finish-reason on penultimate, `[DONE]` on last; verify gRPC error yields SSE error event (no `[DONE]`)
- [x] T013 [US1] Add end-to-end streaming integration test to `tests/integration/test_chat_bridge.py` — use `ASGITransport` with httpx streaming (`client.stream()`), iterate `response.aiter_lines()`, verify event sequence and that concatenated content equals `"Hello world"`, verify stream ends with `[DONE]`

**Checkpoint**: `curl -N` streaming works locally; `make test` passes for proxy and integration test packages.

---

## Phase 4: User Story 2 — Direct gRPC Streaming (Priority: P2)

**Goal**: `VllmGrpcClient.chat.complete_stream()` yields typed `StreamChunk` objects via async generator, usable with `async for` without touching protobuf types.

**Independent Test**: `async for chunk in client.chat.complete_stream(messages, model="Qwen/Qwen3-0.6B", max_tokens=5, seed=42)` — chunks arrive incrementally; concatenated `delta_content` equals `complete()` result for same seed.

- [x] T014 [P] [US2] Add `StreamChunk` dataclass to `packages/client/src/vllm_grpc_client/chat.py` — fields: `delta_content: str`, `finish_reason: str | None` (`None` when proto value is `""`), `token_index: int`; use `@dataclass(frozen=True)` for immutability; fully typed for mypy --strict
- [x] T015 [US2] Add `complete_stream()` async generator method to `ChatClient` in `packages/client/src/vllm_grpc_client/chat.py` — call `stub.CompleteStream(req, timeout=timeout)`, iterate with `async for`, convert each `chat_pb2.ChatStreamChunk` to `StreamChunk` (mapping `""` finish_reason → `None`), yield; on `grpc.aio.AioRpcError` re-raise; generator's `finally` block calls `call.cancel()` to cancel if abandoned mid-iteration; return type `AsyncIterator[StreamChunk]` (from `collections.abc`)
- [x] T016 [US2] Export `StreamChunk` from `packages/client/src/vllm_grpc_client/__init__.py` — add to `__all__`
- [x] T017 [US2] Add integration tests for `complete_stream()` in `tests/integration/test_grpc_client.py` (new file) — spin up `fake_frontend_server` (which now has `CompleteStream` from T011); verify `StreamChunk` sequence matches `FakeChatServicer` output; verify `finish_reason` is `None` on non-final and `"stop"` on final; verify `AioRpcError` propagates on server error; verify generator cancellation stops iteration

**Checkpoint**: `test_grpc_client.py` passes; `StreamChunk` importable from `vllm_grpc_client`; `make typecheck` zero errors for client package.

---

## Phase 5: User Story 3 — TTFT and TPOT Benchmark (Priority: P3)

**Goal**: `make bench-modal` measures TTFT and TPOT for proxy, native, and gRPC-direct streaming paths; writes `docs/benchmarks/phase-5-streaming-comparison.md` with P50/P95/P99 for all three targets.

**Independent Test**: `make bench-modal` completes without error; `docs/benchmarks/phase-5-streaming-comparison.md` contains TTFT and TPOT columns for REST-native, gRPC-proxy, gRPC-direct at each concurrency level (SC-005).

- [x] T018 [US3] Extend `RequestResult` with `ttft_ms: float | None`, `tpot_ms: float | None`, `token_count: int | None`; extend `RunSummary` with `ttft_p50_ms`, `ttft_p95_ms`, `ttft_p99_ms`, `tpot_p50_ms`, `tpot_p95_ms`, `tpot_p99_ms` (all `float | None`); update `compute_summaries()` to aggregate new fields using `_percentile()` — all in `tools/benchmark/src/vllm_grpc_bench/metrics.py`
- [x] T019 [P] [US3] Add `run_target_streaming()` to `tools/benchmark/src/vllm_grpc_bench/runner.py` — mirrors `run_target()` but uses `client.stream("POST", ...)` with `response.aiter_lines()`; records `t_first` on first `data:` line (not `[DONE]`), records `t_each` for each subsequent `data:` line; computes and returns `ttft_ms`, `tpot_ms`, `token_count` in each `RequestResult`
- [x] T020 [P] [US3] Add `run_grpc_target_streaming()` to `tools/benchmark/src/vllm_grpc_bench/runner.py` — mirrors `run_grpc_target()` but calls `grpc_client.chat.complete_stream()`; records `t_first` on first yielded `StreamChunk`, `t_each` for subsequent chunks; computes `ttft_ms`, `tpot_ms`, `token_count`
- [x] T021 [P] [US3] Extend `fake_server.py` in `tools/benchmark/src/vllm_grpc_bench/fake_server.py` — detect `"stream": true` in request body; when streaming, respond with `Content-Type: text/event-stream`, emit 3 synthetic SSE chunks with `asyncio.sleep(0.001)` between each, then `data: [DONE]`
- [x] T022 [US3] Add TTFT and TPOT columns to `write_summary_md()` and `write_csv()` in `tools/benchmark/src/vllm_grpc_bench/reporter.py` — add TTFT P50/P95/P99 and TPOT P50/P95/P99 columns alongside existing latency columns; `None` values render as `—` in markdown
- [x] T023 [US3] Update `tools/benchmark/src/vllm_grpc_bench/__main__.py` — add `--streaming` flag to the main benchmark run; when set, call `run_target_streaming()` for proxy and native, `run_grpc_target_streaming()` for gRPC-direct; write streaming results and summaries to output dir
- [x] T024 [US3] Update `scripts/python/bench_modal.py` — add streaming benchmark phase: invoke proxy streaming, native streaming, and gRPC-direct streaming; collect results; call reporter to write `docs/benchmarks/phase-5-streaming-comparison.md`; ensure three-way streaming comparison is structured like the existing `phase-4.2-*` non-streaming report

**Checkpoint**: `make bench-modal` writes `docs/benchmarks/phase-5-streaming-comparison.md` with TTFT/TPOT columns for all three targets; `make bench-ci` exercises streaming paths via `fake_server.py`.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: CI gate, test additions for the benchmark tool, and final verification.

- [x] T025 [P] Add tests for TTFT/TPOT computation and streaming senders to `tools/benchmark/tests/test_metrics.py` and `tools/benchmark/tests/test_runner.py` — verify `compute_summaries()` populates new TTFT/TPOT fields; verify streaming sender records correct `ttft_ms` when fake chunks arrive with measured delay
- [x] T026 [P] Update `Makefile` `test` target to include `packages/client/tests` if a client-only test directory is created (only needed if T017 creates `packages/client/tests/` instead of `tests/integration/`)
- [x] T027 Run `make check` (lint + typecheck + test) — zero ruff errors, zero mypy errors across all packages (SC-006), all tests pass including streaming variants (SC-007); fix any type annotation gaps discovered by mypy --strict

**Checkpoint**: `make check` exits 0. Phase 5 complete — all seven success criteria (SC-001 through SC-007) met.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Requires Phase 1 complete — BLOCKS all user stories
- **Phase 3 (US1, P1)**: Requires Phase 2 complete
- **Phase 4 (US2, P2)**: Requires Phase 2 complete — independent of Phase 3; can run in parallel with Phase 3
- **Phase 5 (US3, P3)**: Requires Phase 3 AND Phase 4 complete (benchmarks both streaming paths)
- **Phase 6 (Polish)**: Requires Phase 5 complete

### User Story Dependencies

- **US1 (P1)**: Can start after Phase 2 — depends only on frontend servicer (T005)
- **US2 (P2)**: Can start after Phase 2 — independent of US1; only shares `FakeChatServicer.CompleteStream` (T011, writeable alongside US1)
- **US3 (P3)**: Depends on US1 complete (proxy streaming path) and US2 complete (gRPC-direct streaming)

### Within Each Phase

- T003 and T004 (both Phase 2): parallel — different concerns, different files
- T007 and T008 (both Phase 3): parallel — different files (`grpc_client.py` vs `chat_translate.py`)
- T019 and T020 (both Phase 5): parallel — both in `runner.py` but no shared state; can be sequential commits in same PR
- T021 (Phase 5): parallel with T019/T020 once T018 is done

---

## Parallel Examples

### Phase 2 (Foundational)

```
Parallel start:
  Task T003: Write docs/decisions/0003-streaming-design.md
  Task T004: Add output_to_stream_chunk() to frontend/chat_translate.py

Sequential after T004:
  Task T005: Add CompleteStream servicer to frontend/chat.py
  Task T006: Add frontend streaming tests
```

### Phase 3 (US1) — after Phase 2 complete

```
Parallel start:
  Task T007: Add stream_complete() to proxy/grpc_client.py
  Task T008: Add SSE helpers to proxy/chat_translate.py

Sequential after T008:
  Task T009: Add SSE encoding unit tests

Sequential after T007+T008:
  Task T010: Implement streaming route in proxy/chat_router.py

Parallel:
  Task T011: Add CompleteStream to FakeChatServicer

Sequential after T010+T011:
  Task T012: Add proxy streaming endpoint tests
  Task T013: Add integration test
```

### Phase 3 + Phase 4 (US1 and US2) — in parallel after Phase 2

```
Developer A: T007 → T008 → T009 → T010 → T011 → T012 → T013 (US1)
Developer B: T014 → T015 → T016 → T017 (US2)
```

---

## Implementation Strategy

### MVP (US1 Only — Phases 1–3)

1. Complete Phase 1: Proto update + stubs
2. Complete Phase 2: Frontend servicer + ADR
3. Complete Phase 3: Proxy streaming (US1)
4. **STOP and VALIDATE**: `curl -N` streaming works; SSE deltas appear before generation completes; concatenated output matches non-streaming response for same seed
5. Demo-ready: proxy path delivers streaming chat completions

### Incremental Delivery

1. Phases 1–2 → Foundation ready (all stories unblocked)
2. Phase 3 → US1 complete → proxy streaming demo
3. Phase 4 → US2 complete → direct-gRPC streaming usable in Python
4. Phase 5 → US3 complete → TTFT/TPOT benchmark results committed
5. Phase 6 → CI gate passes → branch ready for PR

---

## Notes

- [P] tasks = different files or independent concerns; no dependency on incomplete tasks
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable
- Non-streaming tests MUST continue to pass after each phase (SC-007)
- Proto update (T001–T002) is the global gate — nothing else can proceed until stubs are regenerated
- `make proto` must be rerun after any `.proto` change; CI checks that stubs are up to date
- Client test file `tests/integration/test_grpc_client.py` uses the `fake_frontend_server` fixture already in `tests/integration/fake_frontend.py` (extended by T011)
