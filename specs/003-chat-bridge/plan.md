# Implementation Plan: Phase 3 — Minimal Non-Streaming Chat Completion Bridge

**Branch**: `003-chat-bridge` | **Date**: 2026-04-30 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/003-chat-bridge/spec.md`

## Summary

Implement the first end-to-end bridging milestone: a proxy that accepts OpenAI-compatible
non-streaming `POST /v1/chat/completions` requests, translates them to protobuf, forwards them
via gRPC to a frontend server that calls `AsyncLLM.generate()`, and returns an OpenAI-compatible
JSON response. Streaming (`stream: true`) is rejected with HTTP 501. All new wire formats are
defined proto-first in `proto/vllm_grpc/v1/chat.proto` before any implementation code.

## Technical Context

**Language/Version**: Python 3.12 (workspace-wide)
**Primary Dependencies**:
  - `grpcio>=1.65` + `grpcio-tools>=1.65` — gRPC transport and codegen (already in workspace)
  - `protobuf` — generated message classes (transitive via grpcio)
  - `fastapi>=0.115` + `uvicorn[standard]>=0.30` — proxy HTTP server (already in `proxy`)
  - `vllm` — model execution library imported by `frontend` (version resolves to 0.11.0 on macOS via the `investigation` group; for live cloud runs, 0.20.0 on Modal A10G per ADR 0001)
  - `openai` — Python example script client (added to `dev` group)
  - `httpx>=0.27` — async HTTP test client (already in `dev` group)
  - `pytest>=8` + `pytest-asyncio>=0.23` — test framework (already in `dev` group)
  - `ruff>=0.4` — lint + format (already in `dev` group)
  - `mypy>=1.10` — type-checking (already in `dev` group)

**Storage**: None — no persistent state; all I/O is request/response within a single call
**Testing**: pytest + pytest-asyncio; httpx.AsyncClient for proxy HTTP tests; a `FakeChatServicer`
(a gRPC servicer that returns a hardcoded response without importing vllm) for CI integration tests
**Target Platform**: M2 Pro MacBook Pro (macOS) for local development; Modal A10G (Linux/CUDA) for
live model runs. CI runs on GitHub Actions (Linux, no GPU) using the `FakeChatServicer`.
**Project Type**: Two cooperating servers — an HTTP proxy (`vllm_grpc_proxy`) and a gRPC frontend
(`vllm_grpc_frontend`) — both existing packages in the uv workspace
**Performance Goals**: A non-streaming 50-token Qwen3-0.6B completion returns within the
Modal A10G wall-clock time established in Phase 2 (~1.54s). No additional latency budget for proxy
overhead is set in this phase — Phase 4 measures it.
**Constraints**:
  - `mypy --strict` zero errors across `packages/proxy/src` and `packages/frontend/src`
  - `ruff` clean (lint + format)
  - Generated protobuf stubs (`chat_pb2.py`, `chat_pb2_grpc.py`) MUST NOT be committed
  - CI integration test MUST pass without GPU (uses `FakeChatServicer`)
  - No features from Phase 4+ (streaming, metrics, benchmarking) are introduced
**Scale/Scope**: One new RPC (`ChatService.Complete`), one new `.proto` file, extensions to both
existing packages, four new test files, two new example scripts, one integration test

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Proto-First | ✅ PASS | `proto/vllm_grpc/v1/chat.proto` defined before any implementation code; `make proto` generates stubs; stubs not committed |
| II. Library Dependency, Not Fork | ✅ PASS | `vllm` imported as an ordinary library dependency in `vllm-grpc-frontend`; no source patching |
| III. Phase Discipline | ✅ PASS | Deliverables match `docs/PLAN.md §Phase 3` exactly; no streaming (Phase 5), no metrics (Phase 4), no prompt_embeds (Phase 6) |
| IV. CI is the Merge Gate | ✅ PASS | ruff + mypy --strict + pytest all required; integration test uses `FakeChatServicer` to run without GPU |
| V. Honest Measurement | ✅ PASS (N/A) | No benchmarking in this phase; Phase 4 measures the bridge — no thumb on the scale |

**Post-design re-check**: All principles pass. The `FakeChatServicer` CI strategy avoids GPU while
still exercising the full proxy → gRPC → servicer → response path.

## Project Structure

### Documentation (this feature)

```text
specs/003-chat-bridge/
├── plan.md              # This file
├── research.md          # Phase 0 output (complete)
├── data-model.md        # Phase 1 output (complete)
├── quickstart.md        # Phase 1 output (complete)
├── contracts/           # Phase 1 output (complete)
│   ├── chat-proto.md    # ChatService proto design
│   └── rest-api.md      # OpenAI REST contract (request/response JSON schema)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
proto/
└── vllm_grpc/
    └── v1/
        ├── health.proto                     ← existing
        └── chat.proto                       ← NEW (Phase 3; proto-first)

packages/
├── gen/
│   └── src/vllm_grpc/v1/
│       ├── health_pb2{_grpc}.py             ← existing generated stubs (gitignored)
│       ├── chat_pb2.py                      ← NEW generated stub (gitignored)
│       └── chat_pb2_grpc.py                 ← NEW generated stub (gitignored)
│
├── proxy/
│   └── src/vllm_grpc_proxy/
│       ├── main.py                          ← EXTEND: include chat router
│       ├── grpc_client.py                   ← EXTEND: add GrpcChatClient
│       ├── chat_router.py                   ← NEW: POST /v1/chat/completions handler
│       └── chat_translate.py                ← NEW: JSON ↔ proto translation helpers
│
│   tests/
│       ├── test_healthz.py                  ← existing
│       ├── test_chat_endpoint.py            ← NEW: HTTP handler tests (mock gRPC client)
│       └── test_chat_translate.py           ← NEW: translation unit tests
│
└── frontend/
    └── src/vllm_grpc_frontend/
        ├── main.py                          ← EXTEND: register ChatServicer
        ├── health.py                        ← existing
        ├── chat.py                          ← NEW: ChatServicer (calls AsyncLLM)
        └── chat_translate.py                ← NEW: proto → SamplingParams, output → proto

    tests/
        ├── test_health_ping.py              ← existing
        ├── test_chat_servicer.py            ← NEW: ChatServicer tests (stub AsyncLLM)
        └── test_chat_translate.py           ← NEW: translation unit tests

scripts/
├── curl/
│   ├── healthz.sh                           ← existing
│   └── chat-nonstreaming.sh                 ← NEW
└── python/
    ├── verify_prompt_embeds{_modal}.py      ← existing (Phase 2)
    └── chat-nonstreaming.py                 ← NEW

tests/
└── integration/
    └── test_chat_bridge.py                  ← NEW: FakeChatServicer + real proxy

Makefile                                     ← EXTEND: add integration test target; update
                                               proto target to include chat.proto
```

**Structure Decision**: Extends the existing `proxy` / `frontend` / `gen` three-package workspace
established in Phase 1. No new workspace members are added — this phase adds files within the
existing packages only.

## Complexity Tracking

> *No constitution violations — this section is informational only.*

No new workspace packages are introduced. The `FakeChatServicer` used in CI tests is a test-only
file and does not add a runtime dependency on vllm to the test environment. The integration test
(`tests/integration/`) lives at the workspace root rather than inside a package because it spans
both `proxy` and `frontend` packages — this is consistent with the project's existing `scripts/`
pattern of cross-package scripts at the root.
