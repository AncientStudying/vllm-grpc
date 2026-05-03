# Implementation Plan: Enable Prompt Embeddings in gRPC Frontend (Phase 6.1)

**Branch**: `011-enable-prompt-embeds` | **Date**: 2026-05-03 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/011-phase-6.1/spec.md`

## Summary

The Phase 6 `completion-embeds` benchmark paths fail because the gRPC frontend initializes vLLM's engine without `enable_prompt_embeds=True`. Without that flag the v1 engine's renderer raises a hard error on any `prompt_embeds` input. All Phase 6 proto encoding, proxy translation, tensor decoding, and engine-call code is correct; only the engine initialization is wrong. Adding `enable_prompt_embeds=True` to `AsyncEngineArgs` in `main.py` unblocks both the proxy and gRPC-direct prompt-embedding paths.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: vllm ≥ 0.19.0 (AsyncEngineArgs, AsyncLLMEngine); grpcio ≥ 1.65
**Storage**: N/A
**Testing**: pytest + pytest-asyncio (`asyncio_mode=auto`); mypy --strict; ruff
**Target Platform**: Modal A10G (GPU) for runtime; local macOS arm64 for unit tests
**Project Type**: uv workspace — 4 packages (`gen`, `proxy`, `frontend`, `client`) + 1 tool (`benchmark`); no new packages this phase
**Performance Goals**: `completion-embeds` paths produce real latency/throughput numbers; gRPC-direct request bytes ~33% smaller than REST (base64) path for same tensor
**Constraints**: mypy --strict zero errors; `make check` green; no new modules, no proto changes
**Scale/Scope**: 1 file modified (`main.py`); 1 doc updated; 1 benchmark re-run

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Proto-First ✅ Compliant

No proto changes. The existing `completions.proto` `oneof input { string prompt; bytes prompt_embeds }` schema is correct and unchanged.

### II. Library Dependency, Not Fork ✅ Compliant

`enable_prompt_embeds=True` is a public `AsyncEngineArgs` parameter in vLLM's published API (`vllm/engine/arg_utils.py`). No vLLM source is copied or patched.

### III. Phase Discipline ✅ Compliant

This change is explicitly listed as a Phase 6.1 deliverable in `docs/PLAN.md`. No phase N+1 abstractions introduced.

### IV. CI is the Merge Gate ✅ Required

`make check` (ruff + mypy --strict + pytest) must pass before merge. Unit tests mock the engine and exercise the servicer logic; they pass regardless of GPU. Modal benchmark re-run is required to verify the fix end-to-end.

### V. Honest Measurement ✅ Required

Both `grpc-direct | completion-embeds` and `proxy | completion-embeds` benchmark rows must be committed with real numbers after the Modal re-run, regardless of the observed latency vs the text-prompt baseline.

## Project Structure

### Documentation (this feature)

```text
specs/011-phase-6.1/
├── plan.md              # This file
├── research.md          # Phase 0 — root cause investigation findings
├── data-model.md        # Phase 1 — no new entities (N/A this phase)
├── quickstart.md        # Phase 1 — updated usage notes
└── tasks.md             # Phase 2 output (/speckit-tasks command — NOT created here)
```

### Source Code (repository root)

```text
packages/frontend/src/vllm_grpc_frontend/
└── main.py              ← MODIFY: add enable_prompt_embeds=True to AsyncEngineArgs
```

No other source files change. No proto files change. No test files change.

**Structure Decision**: Single uv workspace unchanged. No new packages, modules, or RPCs. The change is a one-line addition to the engine initialization call.

---

## Phase 0 Research — Complete

### Decision Log

| # | Topic | Decision | Rationale |
|---|-------|----------|-----------|
| 1 | Why does the engine reject `prompt_embeds` input? | Missing `enable_prompt_embeds=True` in `AsyncEngineArgs` | `vllm/renderers/embed_utils.py` checks `model_config.enable_prompt_embeds` and raises if `False` |
| 2 | Is `AsyncLLMEngine` the v0 or v1 engine? | v1 engine (`AsyncLLM`) — `AsyncLLMEngine = AsyncLLM` in `vllm/engine/async_llm_engine.py` | Confirmed by reading installed vLLM 0.19.0 source |
| 3 | Is `enable_prompt_embeds` a valid `AsyncEngineArgs` parameter in 0.19/0.20? | Yes — `enable_prompt_embeds: bool = False` confirmed in `AsyncEngineArgs.__init__` signature | Verified by `inspect.signature` on the installed package |
| 4 | Does enabling the flag affect text-prompt or token-ID requests? | No — flag is additive; the renderer checks it only on `prompt_embeds` input paths | No regressions expected |
| 5 | Is the `{"prompt_embeds": tensor}` dict format correct for the v1 engine? | Yes — `vllm/inputs/preprocess.py` dispatches to `_process_embeds()` when `"prompt_embeds" in prompt` | Existing servicer code needs no changes |

See `docs/notes/vllm-embedding-input-limitation.md` for the full investigation trail.

---

## Phase 1 Design — Complete

### Data Model

No new entities. `CompletionRequest`, `CompletionResponse`, `CompletionStreamChunk`, and `OpenAICompletionRequest` are unchanged from Phase 6.

### Contracts

No new contracts. The `completions.proto` schema and the `client-completions-api.md` contract are unchanged. The only observable behavior change is that requests that previously returned `INTERNAL` error now return a valid completion.

### Implementation Detail

`packages/frontend/src/vllm_grpc_frontend/main.py` line 19:

```python
# Before
engine = AsyncLLMEngine.from_engine_args(AsyncEngineArgs(model=model_name))

# After
engine = AsyncLLMEngine.from_engine_args(
    AsyncEngineArgs(model=model_name, enable_prompt_embeds=True)
)
```

### Quickstart Notes

No changes to the end-user quickstart. The gRPC frontend startup command is unchanged. The `enable_prompt_embeds=True` flag is opaque to callers — the frontend simply begins accepting prompt-embedding requests that previously failed.

To verify after deployment:

```bash
# Smoke test via vLLM's native REST (already-existing script)
modal run scripts/python/verify_prompt_embeds_modal.py

# End-to-end via benchmark (confirms both gRPC-direct and proxy paths)
make bench-modal
```

## Post-Design Constitution Re-Check

All five principles remain satisfied:

- **Proto-First**: No proto changes; schema unchanged.
- **Library Dependency**: `enable_prompt_embeds=True` is a public API parameter.
- **Phase Discipline**: Change is scoped to Phase 6.1 deliverables only.
- **CI Gate**: `make check` covers lint, type-check, and unit tests. Modal bench confirms end-to-end.
- **Honest Measurement**: Both completion-embeds rows must appear in the committed benchmark output with real numbers.
