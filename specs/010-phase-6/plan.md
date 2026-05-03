# Implementation Plan: Completions API with Prompt Embeddings (Phase 6)

**Branch**: `010-phase-6` | **Date**: 2026-05-03 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/010-phase-6/spec.md`

## Summary

Add the `/v1/completions` endpoint to the proxy and a `CompletionsService` gRPC RPC to the frontend, supporting both plain text prompts and pre-computed prompt embedding tensors. Prompt embeddings travel as raw `bytes` in the protobuf wire format, eliminating the ~33% base64 overhead of the REST path and providing the phase's central wire-efficiency measurement. The `VllmGrpcClient` library gains a `completions` property exposing `complete()` and `complete_stream()`. The benchmark harness gains a completions corpus and wire-size comparison columns. The CI benchmark PR comment is updated to aggregate all historical phase summaries (Phase 4.2, Phase 5, Phase 6) rather than showing only the latest.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: grpcio ≥ 1.65, grpcio-tools, FastAPI, httpx ≥ 0.27, vllm 0.20.0 (Modal A10G/CUDA), torch ≥ 2.0 (for tensor encode/decode), pytest-asyncio ≥ 0.23, mypy ≥ 1.10, ruff ≥ 0.4, openai ≥ 1.0
**Storage**: N/A (benchmark JSON/pt corpus files committed to repo)
**Testing**: pytest + pytest-asyncio (`asyncio_mode=auto`), mypy --strict, ruff
**Target Platform**: Linux server (Modal A10G GPU for benchmark runs); local macOS arm64 for unit/integration tests
**Project Type**: uv workspace — 4 packages (`gen`, `proxy`, `frontend`, `client`) + 1 tool (`benchmark`); no new packages this phase
**Performance Goals**: Wire size of prompt-embedding gRPC-direct request < REST path for same input; gRPC-direct TTFT ≤ Phase 5 gRPC-direct baseline at equivalent concurrency
**Constraints**: mypy --strict zero errors across all packages; client disconnect → server cancellation within 2 s (FR-009); insecure gRPC only (TLS out of scope)
**Scale/Scope**: 4 packages modified (`proto`, `proxy`, `frontend`, `client`), 1 tool modified (`benchmark`), 1 workflow modified (`benchmark.yml`), 1 new ADR, 1 new script (`gen_embed_corpus.py`)

## Constitution Check

### I. Proto-First — GATE ✅
- `CompletionRequest`, `CompletionResponse`, `CompletionStreamChunk`, and `CompletionsService` RPCs MUST be committed to `proto/vllm_grpc/v1/completions.proto` and `make proto` run **before** any implementation code references generated stubs.
- The proto contract is documented in `contracts/completions-proto.md` and is the authoritative source.
- CI proto-stub compile check must pass (no diff after `make proto`).

### II. Library Dependency, Not Fork ✅ Compliant
- vLLM's `AsyncLLM.generate()` is called as a library function with the tensor input. No vLLM source is patched, copied, or vendored.
- `torch` is used only as a serialisation/deserialisation tool at the bridge boundary; the frontend does not implement any model logic.

### III. Phase Discipline ✅ Enforced
- **In scope**: `/v1/completions` (text prompt + prompt_embeds), streaming completions, `VllmGrpcClient.completions` API, wire-size benchmark, multi-phase CI comment.
- **Out of scope this phase**: `/v1/completions` batch API, TLS, prompt-embedding caching, streaming completions corpus (non-embedding streaming completions share the existing chat corpus for CI).
- No phase N+1 abstractions.

### IV. CI is the Merge Gate ✅ Required
- `make check` (lint + typecheck + test) must pass before PR merge.
- No `--no-verify`.

### V. Honest Measurement ✅ Required
- Wire-size numbers reported for all three paths even if the gRPC advantage is smaller than expected.
- Committed to `docs/benchmarks/phase-6-completions-comparison.md` with full methodology (hardware, concurrency, corpus, vLLM version, tensor shape/dtype).

## Project Structure

### Documentation (this feature)

```text
specs/010-phase-6/
├── plan.md              # This file
├── research.md          # Phase 0 — design decisions and rationale
├── data-model.md        # Phase 1 — entities and field definitions
├── quickstart.md        # Phase 1 — usage and testing guide
├── contracts/
│   ├── completions-proto.md        # Authoritative proto schema
│   ├── completions-sse-format.md   # OpenAI completions SSE delta wire format
│   └── client-completions-api.md   # VllmGrpcClient.completions contract
└── tasks.md             # Phase 2 output (/speckit-tasks command — NOT created here)
```

### Source Code (repository root)

```text
proto/vllm_grpc/v1/
└── completions.proto                ← NEW: CompletionsService + messages

packages/gen/src/                   ← generated stubs only (not committed)

packages/frontend/src/vllm_grpc_frontend/
├── completions.py                   ← NEW: CompletionsServicer (Complete + CompleteStream)
├── completions_translate.py         ← NEW: proto_to_sampling_params (completions), decode_embeds()
└── main.py                          ← add CompletionsServicer registration

packages/frontend/tests/
├── test_completions_servicer.py     ← NEW: unit tests (mock engine, text + embeds)
└── test_completions_translate.py    ← NEW: unit tests for decode_embeds, translation helpers

packages/proxy/src/vllm_grpc_proxy/
├── completions_router.py            ← NEW: POST /v1/completions (non-stream + stream)
├── completions_translate.py         ← NEW: OpenAICompletionRequest, base64→bytes, SSE helpers
└── main.py                          ← include completions_router

packages/proxy/src/vllm_grpc_proxy/grpc_client.py
                                     ← add GrpcCompletionsClient (complete + stream_complete)

packages/proxy/tests/
├── test_completions_endpoint.py     ← NEW: unit tests (mock gRPC client, text + embeds + stream)
└── test_completions_translate.py    ← NEW: SSE encoding helpers unit tests

packages/client/src/vllm_grpc_client/
├── completions.py                   ← NEW: CompletionsClient + CompletionResult + CompletionStreamChunk
├── client.py                        ← add .completions property
└── __init__.py                      ← export CompletionResult, CompletionStreamChunk

packages/client/tests/
└── test_completions_client.py       ← NEW: unit tests (mock channel, text + embeds + stream)

tests/integration/
├── fake_frontend.py                 ← add FakeCompletionsServicer (text + embeds + stream)
└── test_completions_bridge.py       ← NEW: end-to-end integration tests (ASGITransport)

tools/benchmark/corpus/
├── completions_text.json            ← NEW: text-prompt completions corpus
└── completions_embeds/              ← NEW: pre-computed .pt tensor files + manifest.json

tools/benchmark/src/vllm_grpc_bench/
├── metrics.py                       ← add request_type field to RequestResult/RunSummary
├── runner.py                        ← add completions runners (proxy text, proxy embeds, grpc-direct)
├── reporter.py                      ← add wire-size comparison section to markdown report
└── corpus.py                        ← add load_completions_corpus() for both corpus types

scripts/python/
├── gen_embed_corpus.py              ← NEW: generate .pt files from tokenizer + embed_tokens
└── bench_modal.py                   ← add completions benchmark targets (text + embeds, 3 paths)

docs/benchmarks/
└── phase-6-completions-comparison.md  ← committed after Modal bench run (not in tasks)

docs/decisions/
└── 0004-completions-design.md      ← NEW: ADR covering proto schema choices, tensor encoding,
                                       embedding corpus design

.github/workflows/
└── benchmark.yml                    ← update Modal baseline summary to aggregate all phase files;
                                       update section header to "Modal GPU Baselines — All Phases"
```

**Structure Decision**: Single uv workspace unchanged from Phase 5. No new packages. Completions extends the existing four-package workspace with parallel modules mirroring the chat pattern. No complexity violations.

---

## Phase 0 Research — Complete

See [`research.md`](research.md) for full decision log. Key resolutions:

| # | Topic | Resolution |
|---|-------|-----------|
| 1 | AsyncLLM.generate() API for prompt_embeds | `{"prompt_embeds": tensor}` input dict; exact keyword to verify against vLLM 0.20.0 at implementation time |
| 2 | completions.proto schema | New file; `oneof input { string prompt; bytes prompt_embeds }` enforces mutual exclusivity |
| 3 | Proxy prompt_embeds handling | base64 decode → proto `bytes` field; frontend does `torch.load()` |
| 4 | SSE format for streaming completions | `object: text_completion`, `choices[0].text` (not `delta.content`), no initial role-delta event |
| 5 | CI multi-phase comment aggregation | Shell block concatenates all phase markdown files with section headers |
| 6 | Benchmark embedding corpus | Pre-computed `.pt` files from tokenizer + embed_tokens; same tensors used across all paths |

## Phase 1 Design — Complete

Artifacts generated:

- [`data-model.md`](data-model.md) — `CompletionRequest`, `CompletionResponse`, `CompletionStreamChunk`, `OpenAICompletionRequest`, `CompletionResult` (client)
- [`contracts/completions-proto.md`](contracts/completions-proto.md) — authoritative proto schema
- [`contracts/completions-sse-format.md`](contracts/completions-sse-format.md) — OpenAI completions SSE delta wire format
- [`contracts/client-completions-api.md`](contracts/client-completions-api.md) — `VllmGrpcClient.completions` API contract
- [`quickstart.md`](quickstart.md) — curl, Python proxy, direct gRPC, and benchmark usage

## Post-Design Constitution Re-Check

All five principles remain satisfied after Phase 1 design:

- **Proto-First**: `contracts/completions-proto.md` is committed before any implementation tasks begin. The `oneof input` design is locked.
- **Library Dependency**: Design uses `engine.generate()` with tensor input throughout; no vLLM internals copied.
- **Phase Discipline**: No out-of-scope items surfaced. Batch API, TLS, and embedding caching explicitly excluded.
- **CI Gate**: mypy --strict and pytest requirements incorporated into all new module designs.
- **Honest Measurement**: Wire-size measurement approach is unbiased (same tensor bytes used for all three paths; base64 overhead measured honestly for the REST path).
