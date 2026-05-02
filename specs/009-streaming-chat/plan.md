# Implementation Plan: Streaming Chat Completions (Phase 5)

**Branch**: `009-streaming-chat` | **Date**: 2026-05-02 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/009-streaming-chat/spec.md`

## Summary

Add server-streaming gRPC to the frontend (`CompleteStream` RPC), SSE streaming to the proxy (`StreamingResponse` over `text/event-stream`), an `async for`-iterable `complete_stream()` to `VllmGrpcClient`, and TTFT/TPOT timing fields to the benchmark harness — completing the wire-overhead measurement thesis with streaming metrics across all three target paths.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: grpcio ≥ 1.65, grpcio-tools, FastAPI, httpx ≥ 0.27, vllm (via Modal A10G), pytest-asyncio ≥ 0.23, mypy ≥ 1.10, ruff ≥ 0.4, openai ≥ 1.0  
**Storage**: N/A  
**Testing**: pytest + pytest-asyncio (`asyncio_mode=auto`), mypy --strict, ruff  
**Target Platform**: Linux server (Modal A10G GPU for benchmark runs); local macOS arm64 for unit/integration tests  
**Project Type**: uv workspace — 4 packages (`gen`, `proxy`, `frontend`, `client`) + 1 tool (`benchmark`); no new packages this phase  
**Performance Goals**: TTFT via gRPC-direct ≤ TTFT via proxy path; all TTFT strictly less than total response latency  
**Constraints**: mypy --strict zero errors across all packages; client-disconnect → server cancellation within 2s (SC-003); insecure gRPC only (TLS out of scope)  
**Scale/Scope**: 3 packages modified (frontend, proxy, client), 1 tool modified (benchmark), 1 new ADR (`docs/decisions/0003-streaming-design.md`)

## Constitution Check

### I. Proto-First — GATE ✅
- `ChatStreamChunk` and `CompleteStream` RPC MUST be committed to `proto/vllm_grpc/v1/chat.proto` and `make proto` run **before** any implementation code references generated stubs.
- The proto contract is documented in `contracts/chat-proto.md` and is the authoritative source.
- CI proto-stub compile check must pass (no diff after `make proto`).

### II. Library Dependency, Not Fork ✅ Compliant
- vLLM's `AsyncLLM.generate()` already yields tokens incrementally as an async generator. No vLLM source is patched, copied, or vendored.

### III. Phase Discipline ✅ Enforced
- **In scope**: streaming chat completions, TTFT/TPOT metrics, streaming ADR.
- **Out of scope this phase**: `/v1/completions` streaming, TLS, prompt-embeds streaming, per-request streaming toggle in the client library config.
- No phase N+1 abstractions.

### IV. CI is the Merge Gate ✅ Required
- `make check` (lint + typecheck + test) must pass before PR merge.
- No `--no-verify`.

### V. Honest Measurement ✅ Required
- TTFT/TPOT reported for all three paths even if neutral or negative vs. the thesis.
- Committed to `docs/benchmarks/phase-5-streaming-comparison.md` with full methodology (hardware, concurrency, corpus, vLLM version).

## Project Structure

### Documentation (this feature)

```text
specs/009-streaming-chat/
├── plan.md              # This file
├── research.md          # Phase 0 — design decisions and rationale
├── data-model.md        # Phase 1 — entities and field definitions
├── quickstart.md        # Phase 1 — usage and testing guide
├── contracts/
│   ├── chat-proto.md          # Updated proto (authoritative design-time spec)
│   ├── sse-format.md          # OpenAI SSE delta wire format
│   └── client-streaming-api.md  # VllmGrpcClient.chat.complete_stream() contract
└── tasks.md             # Phase 2 output (/speckit-tasks command — NOT created here)
```

### Source Code (repository root)

```text
proto/vllm_grpc/v1/
└── chat.proto                   ← add ChatStreamChunk message + CompleteStream RPC

packages/gen/src/                ← generated stubs only (not committed)

packages/frontend/src/vllm_grpc_frontend/
├── chat.py                      ← add CompleteStream async-generator servicer method
└── chat_translate.py            ← add output_to_stream_chunk(output, index) helper

packages/frontend/tests/
└── test_chat_servicer.py        ← add streaming servicer tests (mock engine)

packages/proxy/src/vllm_grpc_proxy/
├── chat_router.py               ← implement streaming route with StreamingResponse
├── chat_translate.py            ← add proto_chunk_to_sse_event() + SSE encoding helpers
└── grpc_client.py               ← add stream_complete() returning AsyncIterator[ChatStreamChunk]

packages/proxy/tests/
├── test_chat_endpoint.py        ← add streaming integration tests (mock gRPC client)
└── test_chat_translate.py       ← add SSE encoding unit tests

packages/client/src/vllm_grpc_client/
├── chat.py                      ← add StreamChunk dataclass + complete_stream() async generator
└── __init__.py                  ← export StreamChunk

tools/benchmark/src/vllm_grpc_bench/
├── metrics.py                   ← add ttft_ms, tpot_ms, token_count to RequestResult/RunSummary
├── runner.py                    ← add streaming senders for proxy/native (httpx) + grpc-direct
├── reporter.py                  ← add TTFT/TPOT columns to markdown + CSV report
└── fake_server.py               ← add streaming SSE response mode for bench-ci

docs/decisions/
└── 0003-streaming-design.md     ← ADR: chunk granularity, error encoding, back-pressure, cancellation

docs/benchmarks/
└── phase-5-streaming-comparison.md  ← generated after real Modal bench run (not in tasks)

scripts/python/
└── bench_modal.py               ← update to invoke streaming benchmark targets
```

**Structure Decision**: Single uv workspace unchanged from Phase 4.2. No new packages. Streaming extends the existing four-package workspace. No complexity violations.

## Complexity Tracking

No constitution violations. No new packages added. No speculative abstractions. Complexity Tracking table not required.

---

## Phase 0 Research — Complete

See [`research.md`](research.md) for full decision log. Key resolutions:

| # | Topic | Resolution |
|---|-------|-----------|
| 1 | Chunk granularity | One proto message per token; `finish_reason` sentinel for final chunk |
| 2 | Role in streaming | Injected by proxy on first SSE chunk; absent from proto |
| 3 | Error encoding | gRPC status code → proxy emits SSE error event; client raises `AioRpcError` |
| 4 | Cancellation | `asyncio.CancelledError` chain: client disconnect → proxy → gRPC cancel → frontend → engine |
| 5 | Back-pressure | Native async generator `yield`; no explicit buffering |
| 6 | TTFT/TPOT measurement | `httpx` streaming for HTTP targets; `complete_stream()` timestamps for gRPC-direct |
| 7 | Client streaming API | `async def complete_stream(...) -> AsyncIterator[StreamChunk]` |
| 8 | CI fake server | `fake_server.py` extended with streaming SSE response mode |
| 9 | gRPC servicer pattern | `async def CompleteStream(...)` as async generator with `context.is_active()` guard |

## Phase 1 Design — Complete

Artifacts generated:

- [`data-model.md`](data-model.md) — `ChatStreamChunk`, `StreamChunk`, extended `RequestResult`/`RunSummary`
- [`contracts/chat-proto.md`](contracts/chat-proto.md) — updated proto schema (authoritative)
- [`contracts/sse-format.md`](contracts/sse-format.md) — OpenAI SSE delta wire format
- [`contracts/client-streaming-api.md`](contracts/client-streaming-api.md) — `VllmGrpcClient` streaming API
- [`quickstart.md`](quickstart.md) — curl, openai-SDK, direct-gRPC, and benchmark usage

## Post-Design Constitution Re-Check

All five principles remain satisfied after Phase 1 design:

- **Proto-First**: The proto contract (`contracts/chat-proto.md`) is defined before any implementation tasks begin.
- **Library Dependency**: Design uses `engine.generate()` as a library call throughout.
- **Phase Discipline**: No out-of-scope items surfaced in design artifacts.
- **CI Gate**: mypy --strict and pytest coverage requirements incorporated into all new module designs.
- **Honest Measurement**: TTFT/TPOT measurement approach is bias-free (same methodology for all three targets).
