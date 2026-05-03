---

description: "Task list for Phase 6 — Completions API with Prompt Embeddings"
---

# Tasks: Phase 6 — Completions API with Prompt Embeddings

**Input**: Design documents from `specs/010-phase-6/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Organization**: Tasks grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no blocking dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)
- All tasks include exact file paths

---

## Phase 1: Setup — Proto-First Gate

**Purpose**: Establish the proto contract before any implementation references generated stubs.
**Constitution gate**: `completions.proto` MUST be committed and `make proto` run before Phase 3+.

- [X] T001 Create `proto/vllm_grpc/v1/completions.proto` exactly as specified in `specs/010-phase-6/contracts/completions-proto.md` (CompletionsService with Complete + CompleteStream RPCs; CompletionRequest with `oneof input`; CompletionResponse; CompletionStreamChunk)
- [X] T002 Run `make proto` and verify clean compile — zero diff in `packages/gen/src/` stubs; commit generated `completions_pb2.py` and `completions_pb2_grpc.py`
- [X] T003 [P] Create `docs/decisions/0004-completions-design.md` ADR covering proto schema choices (`oneof input`, `bytes` for prompt_embeds), tensor encoding convention (`torch.save()`/`torch.load()`), and embedding corpus design (4-bucket, 20-sample approach)

---

## Phase 2: Foundational — Integration Test Infrastructure

**Purpose**: Add fake servicer stubs so integration tests in Phase 3 and Phase 4 can run without a real vLLM engine.

**⚠️ CRITICAL**: Depends on Phase 1 (generated stubs must exist). Blocks US1 and US2 integration tests.

- [X] T004 Add `FakeCompletionsServicer` class to `tests/integration/fake_frontend.py` with stub `Complete()` RPC that returns a canned `CompletionResponse` (text "test output", finish_reason "stop", prompt_tokens 5, completion_tokens 3); wire it into the existing `grpc.aio.server()` fixture

**Checkpoint**: Proto stubs compiled + fake servicer registered → US1 and US2 integration tests can run

---

## Phase 3: User Story 1 — Non-Streaming Completions via Proxy (Priority: P1) 🎯 MVP

**Goal**: `POST /v1/completions` returns a complete OpenAI-compatible response for both text-prompt and prompt-embedding inputs.

**Independent Test**: Start proxy + FakeCompletionsServicer. `POST /v1/completions` with `{"prompt": "hello", "max_tokens": 5, "model": "test"}` → 200 response with `choices[0].text` populated. Then repeat with a base64-encoded zero tensor — same response shape, no crash.

### Implementation for User Story 1

- [X] T005 [P] [US1] Create `packages/frontend/src/vllm_grpc_frontend/completions_translate.py` with `decode_embeds(raw_bytes: bytes) -> torch.Tensor` (torch.load from BytesIO, validates dtype/shape, raises `grpc.StatusCode.INVALID_ARGUMENT` on bad input) and `proto_to_sampling_params(req: CompletionRequest) -> SamplingParams`
- [X] T006 [P] [US1] Create `packages/frontend/src/vllm_grpc_frontend/completions.py` with `CompletionsServicer` class implementing `Complete()` RPC: dispatch on `req.WhichOneof("input")`, call `decode_embeds()` or pass text prompt, call `engine.generate()`, return `CompletionResponse`; return `INVALID_ARGUMENT` if neither/both branches set
- [X] T007 [P] [US1] Create `packages/proxy/src/vllm_grpc_proxy/completions_translate.py` with `OpenAICompletionRequest` Pydantic model (fields: model, max_tokens=16, temperature, top_p, seed, stream=False, prompt, prompt_embeds; validator: exactly one of prompt/prompt_embeds required) and `build_completion_response(proto_resp: CompletionResponse, model: str) -> dict[str, Any]` for the non-streaming JSON body
- [X] T008 [P] [US1] Add `GrpcCompletionsClient` class to `packages/proxy/src/vllm_grpc_proxy/grpc_client.py` with `complete(req: CompletionRequest) -> CompletionResponse` method using the `CompletionsServiceStub`
- [X] T009 [US1] Register `CompletionsServicer` in `packages/frontend/src/vllm_grpc_frontend/main.py`: import `completions_pb2_grpc` and `CompletionsServicer`, call `completions_pb2_grpc.add_CompletionsServiceServicer_to_server(CompletionsServicer(engine), server)` (depends on T006)
- [X] T010 [US1] Create `packages/proxy/src/vllm_grpc_proxy/completions_router.py` with `POST /v1/completions` route: parse `OpenAICompletionRequest`, translate to proto, call `GrpcCompletionsClient.complete()`, return non-streaming JSON response (depends on T007, T008)
- [X] T011 [US1] Include `completions_router` in `packages/proxy/src/vllm_grpc_proxy/main.py`: `from vllm_grpc_proxy.completions_router import router as completions_router` and `app.include_router(completions_router)` (depends on T010)

### Tests for User Story 1

- [X] T012 [P] [US1] Create `packages/frontend/tests/test_completions_translate.py`: test `decode_embeds()` with a valid float32 tensor, wrong dtype (int64 → error), corrupted bytes (→ error); test `proto_to_sampling_params()` maps temperature/top_p/seed correctly and handles absent optional fields
- [X] T013 [P] [US1] Create `packages/frontend/tests/test_completions_servicer.py`: test `Complete()` with text prompt (mock engine yields one output), test with prompt_embeds bytes (mock decode + engine), test neither-input → INVALID_ARGUMENT status, test both-inputs → INVALID_ARGUMENT status
- [X] T014 [P] [US1] Create `packages/proxy/tests/test_completions_translate.py`: test `OpenAICompletionRequest` validation rejects both/neither input, accepts text-only and embeds-only; test `build_completion_response()` produces correct OpenAI-compatible shape with `object: "text_completion"` and `choices[0].text`
- [X] T015 [P] [US1] Create `packages/proxy/tests/test_completions_endpoint.py`: test non-streaming `POST /v1/completions` with mock `GrpcCompletionsClient` returning canned response for text prompt and for embeds; test HTTP 422 on missing both inputs; test HTTP 422 on both inputs present
- [X] T016 [US1] Create `tests/integration/test_completions_bridge.py` with non-streaming bridge tests using `ASGITransport` + `FakeCompletionsServicer`: text-prompt round-trip returns `choices[0].text`, prompt-embeds round-trip returns same shape, dual-input request returns 422 (depends on T009, T011)

**Checkpoint**: `POST /v1/completions` (non-streaming, text + embeds) fully functional and tested

---

## Phase 4: User Story 2 — Streaming Completions via Proxy (Priority: P2)

**Goal**: `POST /v1/completions` with `"stream": true` delivers incremental SSE token deltas for both input forms, terminating with `data: [DONE]`; client disconnect cancels backend within 2 s.

**Independent Test**: `curl -N .../v1/completions` with `"stream": true` and a text prompt. SSE events arrive incrementally; final event has non-null `finish_reason`; `data: [DONE]` follows. Concatenated `text` fields equal the non-streaming result for same seed.

### Implementation for User Story 2

- [X] T017 [US2] Add `CompleteStream()` server-streaming RPC to `packages/frontend/src/vllm_grpc_frontend/completions.py`: async-for over `engine.generate()`, yield `CompletionStreamChunk` per token, check `context.is_active()` before each yield and cancel within 2 s on disconnect (FR-009); final chunk sets `finish_reason`, `delta_text=""` (extends T006)
- [X] T018 [P] [US2] Add SSE helpers to `packages/proxy/src/vllm_grpc_proxy/completions_translate.py`: `format_completion_chunk(chunk: CompletionStreamChunk, completion_id: str, model: str, created: int) -> str` (non-final event), `format_completion_final(chunk: CompletionStreamChunk, ...) -> str` (final event with finish_reason), `format_done() -> str` returning `"data: [DONE]\n\n"`; all per `specs/010-phase-6/contracts/completions-sse-format.md`
- [X] T019 [P] [US2] Add `stream_complete(req: CompletionRequest) -> AsyncIterator[CompletionStreamChunk]` to `GrpcCompletionsClient` in `packages/proxy/src/vllm_grpc_proxy/grpc_client.py` using `CompletionsServiceStub.CompleteStream()`; cancel underlying call in `finally` block
- [X] T020 [US2] Add streaming path to `packages/proxy/src/vllm_grpc_proxy/completions_router.py`: when `request.stream is True`, return `StreamingResponse` (media_type `text/event-stream`) that iterates `GrpcCompletionsClient.stream_complete()`, formats each chunk via SSE helpers, and emits `data: [DONE]`; set `Cache-Control: no-cache`, `X-Accel-Buffering: no` headers (depends on T018, T019)
- [X] T021 [US2] Extend `FakeCompletionsServicer` in `tests/integration/fake_frontend.py` with `CompleteStream()` handler that yields 3 canned `CompletionStreamChunk` messages (delta_text "a", "b", "c") then a final chunk with finish_reason "stop"; respect `context.is_active()` check (depends on T017)

### Tests for User Story 2

- [X] T022 [P] [US2] Extend `packages/frontend/tests/test_completions_servicer.py` with `CompleteStream` test cases: mock engine yields 3 tokens → 4 chunks yielded (3 delta + 1 final); client cancels mid-stream → generation task cancelled within 2 s
- [X] T023 [P] [US2] Extend `packages/proxy/tests/test_completions_endpoint.py` with streaming test cases: `stream=True` returns `text/event-stream` response; SSE events parse to correct structure; `data: [DONE]` is final line; client disconnect triggers gRPC call cancellation (FR-009)
- [X] T024 [US2] Extend `tests/integration/test_completions_bridge.py` with streaming bridge tests: streaming text-prompt delivers 3 delta events + final chunk + `[DONE]`; concatenated `text` fields equal the non-streaming result; client aborts mid-stream → no deadlock (depends on T021)

**Checkpoint**: Streaming `POST /v1/completions` (text + embeds, disconnect cancellation) fully functional

---

## Phase 5: User Story 3 — Direct gRPC via Client Library (Priority: P3)

**Goal**: `VllmGrpcClient.completions.complete()` and `complete_stream()` let Python callers bypass the proxy, sending embeddings as raw binary bytes with no base64 encoding.

**Independent Test**: Instantiate `VllmGrpcClient("localhost:50051")`, call `client.completions.complete(model=..., max_tokens=5, prompt="hello")` against the running FakeCompletionsServicer. Returns typed `CompletionResult`. No proxy process needed.

### Implementation for User Story 3

- [X] T025 [P] [US3] Create `packages/client/src/vllm_grpc_client/completions.py` with frozen `CompletionResult` and `CompletionStreamChunk` dataclasses (per `specs/010-phase-6/contracts/client-completions-api.md`) and `CompletionsClient` class with `complete()` (validates exactly one input, serialises tensor via `torch.save()` into proto `bytes`, returns `CompletionResult`) and `complete_stream()` (async generator, cancels gRPC call in `finally`, yields `CompletionStreamChunk`, raises `grpc.aio.AioRpcError` directly); defer torch import to call time
- [X] T026 [US3] Add `completions` property to `VllmGrpcClient` in `packages/client/src/vllm_grpc_client/client.py`: `@property def completions(self) -> CompletionsClient: return CompletionsClient(self._channel)` (depends on T025)
- [X] T027 [P] [US3] Add `CompletionResult` and `CompletionStreamChunk` to exports in `packages/client/src/vllm_grpc_client/__init__.py`: `from vllm_grpc_client.completions import CompletionResult, CompletionStreamChunk` and extend `__all__`
- [X] T028 [US3] Create `packages/client/tests/test_completions_client.py`: test `complete()` with text prompt (mock channel returns canned `CompletionResponse`), test `complete_stream()` yields `CompletionStreamChunk` objects, test prompt_embeds serialised as raw bytes (not base64), test `ValueError` raised when both or neither inputs provided, test `grpc.aio.AioRpcError` propagates unmodified (depends on T025)

**Checkpoint**: `client.completions.complete()` and `complete_stream()` working against FakeCompletionsServicer, no proxy required

---

## Phase 6: User Story 4 — Wire-Size Efficiency Benchmark (Priority: P4)

**Goal**: `make bench-modal` produces `docs/benchmarks/phase-6-completions-comparison.md` with wire-size bytes for text-prompt vs prompt-embedding inputs across all three paths (REST-native, gRPC-proxy, gRPC-direct), demonstrating the ~33% base64 overhead eliminated by proto `bytes`.

**Independent Test**: Run `gen_embed_corpus.py` locally (CPU-only, Qwen3-0.6B tokenizer + embed_tokens). Verify 20 `.pt` files in `tools/benchmark/corpus/completions_embeds/` plus `manifest.json` and `prompts.txt`. Then run `make check` in tools/benchmark — all benchmark tests pass.

### Implementation for User Story 4

- [X] T029 [US4] Create `scripts/python/gen_embed_corpus.py`: load Qwen3-0.6B tokenizer and `model.embed_tokens` (CPU); extract 20 source prompts from `tools/benchmark/corpus/chat_nonstreaming.json` spanning 4 seq-len buckets (short 8–16, medium 32–48, long 96–128, full 192–256; 5 per bucket; concatenate adjacent entries for long/full buckets); run `model.embed_tokens()` for each; save `torch.save(tensor, f"corpus/completions_embeds/{i:02d}.pt")`; write `manifest.json` and `prompts.txt` per `specs/010-phase-6/data-model.md` Embedding Corpus Manifest schema
- [X] T030 [US4] Run `uv run python scripts/python/gen_embed_corpus.py` and commit generated `tools/benchmark/corpus/completions_embeds/` directory (20 `.pt` files, `manifest.json`, `prompts.txt`) — verify tensor shapes match manifest and at least one bucket per seq-len range (depends on T029)
- [X] T031 [P] [US4] Create `tools/benchmark/corpus/completions_text.json` with 20 text-prompt entries (one per manifest entry in `completions_embeds/manifest.json`): each entry has `prompt`, `model`, `max_tokens`, `seed` fields; prompts match `source_prompt` values in the manifest for direct wire-size comparability
- [X] T032 [US4] Add `request_type: Literal["chat", "completion-text", "completion-embeds"]` field to `RequestResult` and `RunSummary` dataclasses in `tools/benchmark/src/vllm_grpc_bench/metrics.py`; update any factory methods or from-dict helpers to include the field
- [X] T033 [P] [US4] Extend `tools/benchmark/tests/test_metrics.py` with test cases for the new `request_type` field: round-trip serialisation preserves all three literal values; `RunSummary` constructed with `request_type="completion-embeds"` serialises correctly
- [X] T034 [US4] Add `load_completions_corpus(corpus_type: Literal["text", "embeds"]) -> list[...]` to `tools/benchmark/src/vllm_grpc_bench/corpus.py`: for `"text"` load `corpus/completions_text.json`; for `"embeds"` load each `.pt` file listed in `corpus/completions_embeds/manifest.json` and return `(tensor_bytes, max_tokens, seed)` tuples; handle missing corpus files with a clear error (depends on T030, T031)
- [X] T035 [P] [US4] Extend `tools/benchmark/tests/test_corpus.py` with tests for `load_completions_corpus()`: `"text"` loads list of prompt entries, `"embeds"` loads list with raw bytes; missing file raises descriptive error
- [X] T036 [US4] Add completions runners to `tools/benchmark/src/vllm_grpc_bench/runner.py`: `run_completions_proxy_text()`, `run_completions_proxy_embeds()`, and `run_completions_grpc_direct()` — each measures TTFT, request bytes, and response bytes; set `request_type` on each `RequestResult`; measure raw bytes for gRPC paths and base64-inflated bytes for REST path (depends on T032, T034)
- [X] T037 [P] [US4] Extend `tools/benchmark/tests/test_runner.py` with test cases for `run_completions_proxy_text()` and `run_completions_grpc_direct()` using `fake_server` fixture: `RequestResult.request_type` set correctly; `request_bytes_mean` is non-zero
- [X] T038 [US4] Add wire-size comparison section to markdown report in `tools/benchmark/src/vllm_grpc_bench/reporter.py`: table with columns `path`, `input_type`, `req_bytes_mean`, `resp_bytes_mean`, `base64_overhead_pct`; compute overhead % as `(rest_bytes / grpc_bytes - 1) * 100`; present for each seq-len bucket (depends on T032, T036)
- [X] T039 [P] [US4] Extend `tools/benchmark/tests/test_reporter.py` with test for wire-size section: given `RunSummary` list with mixed `request_type` values, rendered markdown contains a `| path |` table with `base64_overhead_pct` column
- [X] T040 [US4] Add completions benchmark targets (text + embeds, proxy + grpc-direct = 3 paths total) to `scripts/python/bench_modal.py`; use `load_completions_corpus()` for corpus loading; write results to `docs/benchmarks/phase-6-completions-comparison.md` (depends on T034, T036)
- [X] T041 [US4] Update `.github/workflows/benchmark.yml` "Modal baseline summary" step: replace `cp` with the R-005 shell block that conditionally concatenates `phase-4.2-three-way-comparison.md`, `phase-5-streaming-comparison.md`, and `phase-6-completions-comparison.md` under section headers; update PR comment section heading to "Modal GPU Baselines — All Phases"

**Checkpoint**: `make bench-modal` produces wire-size report; CI comment aggregates all phases

---

## Final Phase: Polish & Cross-Cutting Concerns

**Purpose**: Verify that all modified packages pass the full `make check` gate.

- [X] T042 Run `make check` (mypy --strict, ruff, pytest) across `packages/frontend`, `packages/proxy`, `packages/client`, and `tools/benchmark`; resolve all type errors and lint violations to satisfy FR-011 (zero mypy suppressions across all new and modified files)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 (T002 — proto stubs must exist)
- **Phase 3 (US1)**: Depends on Phase 2 — BLOCKED until fake servicer wired and proto stubs compiled
- **Phase 4 (US2)**: Depends on Phase 3 completion (extends completions.py and completions_router.py)
- **Phase 5 (US3)**: Depends on Phase 1 (proto stubs) — independent of Phase 3/4
- **Phase 6 (US4)**: Depends on Phase 1; benchmark runners depend on Phase 3/4 for the paths they exercise
- **Final Phase**: Depends on all phases complete

### User Story Dependencies

- **US1 (P1)**: After Phase 2 — no dependency on US2/US3/US4
- **US2 (P2)**: After US1 (extends the same completions.py and router files)
- **US3 (P3)**: After Phase 1 — independent of US1/US2 (different package; client only needs proto stubs)
- **US4 (P4)**: After Phase 1; `bench_modal.py` depends on US1/US2/US3 all being functional (exercising all three paths)

### Within Each User Story

- Frontend translate → servicer → register in main.py
- Proxy translate → grpc_client → router → include in main.py
- Unit tests can be written in parallel with their implementation target (different files)
- Integration tests require the full stack (servicer registered + router included)

### Parallel Opportunities

- **T003** (ADR) can run in parallel with T001/T002
- **T005, T006, T007, T008** (US1 core modules) — all different files across two packages, fully parallel
- **T012, T013, T014, T015** (US1 unit tests) — parallel with each other and with T009/T010/T011
- **T018, T019** (US2 SSE helpers + stream client) — parallel with each other
- **T022, T023** (US2 unit test extensions) — parallel with T017/T020
- **T025, T027** (US3 CompletionsClient + `__init__` exports) — parallel
- **T031** (text corpus) — parallel with T030 (embeds generation)
- **T033, T035, T037, T039** (benchmark test extensions) — parallel with their corresponding source tasks

---

## Parallel Example: User Story 1

```bash
# All four core implementation modules can be written simultaneously:
Task: "completions_translate.py (frontend)" — T005
Task: "completions.py Complete() RPC (frontend)" — T006
Task: "completions_translate.py (proxy)" — T007
Task: "GrpcCompletionsClient.complete() (proxy)" — T008

# Then in parallel with T009/T010/T011:
Task: "test_completions_translate.py (frontend)" — T012
Task: "test_completions_servicer.py Complete (frontend)" — T013
Task: "test_completions_translate.py (proxy)" — T014
Task: "test_completions_endpoint.py non-streaming (proxy)" — T015
```

## Parallel Example: User Story 4

```bash
# Corpus generation + text corpus can run together:
Task: "Run gen_embed_corpus.py → commit .pt files" — T030
Task: "Create completions_text.json" — T031

# Benchmark source + its test can run together (different files):
Task: "Add request_type to metrics.py" — T032
Task: "Extend test_metrics.py" — T033
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Proto + stubs (T001–T003)
2. Complete Phase 2: Fake servicer (T004)
3. Complete Phase 3: Non-streaming proxy (T005–T016)
4. **STOP and VALIDATE**: `POST /v1/completions` text + embeds → JSON response with `choices[0].text`
5. Continue to US2 if streaming is needed

### Incremental Delivery

1. Phase 1 + 2 → Proto gate satisfied, test infrastructure ready
2. Phase 3 (US1) → Non-streaming completions via proxy — **first deployable increment**
3. Phase 4 (US2) → Add streaming — deploy/demo TTFT improvement
4. Phase 5 (US3) → Add client library — direct gRPC path available
5. Phase 6 (US4) → Add benchmark — wire-size efficiency claim quantified
6. Final Phase → `make check` green, PR-ready

### US3 Fast-Track Option

US3 (client library) has no dependency on US2 (streaming proxy). A second developer can work on T025–T028 immediately after Phase 1 completes, in parallel with US1 and US2 proxy work.

---

## Notes

- Proto-First gate is non-negotiable (Constitution I): no implementation file may import from `vllm_grpc.v1.completions_pb2*` until T002 (`make proto`) is complete and committed
- `torch` import in client is deferred to call time (per client-completions-api.md invariant) — text-only callers pay no torch startup cost
- Wire-size measurement uses identical tensor bytes across all three paths (REST gets base64 of same bytes); report must be honest even if gRPC advantage is smaller than expected (Constitution V)
- Streaming cancellation (FR-009): 2-second budget tested explicitly in T022 and T023
- `mypy --strict` zero suppressions enforced by T042 before any PR merge (FR-011)
