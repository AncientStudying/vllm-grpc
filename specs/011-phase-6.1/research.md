# Phase 0 Research: Enable Prompt Embeddings in gRPC Frontend

**Feature**: Phase 6.1 — `enable_prompt_embeds=True` engine flag
**Date**: 2026-05-03

## Investigation Summary

The Phase 6 `completion-embeds` paths fail because vLLM's v1 engine renderer guards all `prompt_embeds` input paths behind a `model_config.enable_prompt_embeds` flag. The flag defaults to `False` and was never set in the gRPC frontend's engine initialization.

## Key Findings

### Finding 1: `AsyncLLMEngine` is the v1 engine

**Decision**: `AsyncLLMEngine` in vLLM 0.19/0.20 is a direct alias for `AsyncLLM` (the v1 engine).

**Evidence**: `vllm/engine/async_llm_engine.py`:
```python
from vllm.v1.engine.async_llm import AsyncLLM
AsyncLLMEngine = AsyncLLM
```

**Rationale**: The original `vllm-embedding-input-limitation.md` note assumed `AsyncLLMEngine` was the v0 engine and that prompt embeddings were not part of its public interface. This was incorrect.

**Alternatives considered**: N/A — this is a factual finding, not a design choice.

---

### Finding 2: `enable_prompt_embeds` is a public `AsyncEngineArgs` parameter

**Decision**: Add `enable_prompt_embeds=True` to `AsyncEngineArgs` in `main.py`.

**Evidence**: Confirmed by `inspect.signature(AsyncEngineArgs.__init__)` on the locally installed vLLM 0.19.0:
```
enable_prompt_embeds: bool = False
```
Also confirmed in `vllm/engine/arg_utils.py` line 385 and in the `--enable-prompt-embeds` CLI flag for the OpenAI server.

**Rationale**: The flag is the correct public API. It is not experimental or internal.

**Alternatives considered**:
- Switching to `AsyncLLM` directly: unnecessary — `AsyncLLMEngine` already is `AsyncLLM`.
- Routing through vLLM's OpenAI REST server: would add HTTP round-trip latency to every gRPC request; defeats the purpose.

---

### Finding 3: The v1 engine's prompt-embeds code path is gated by the flag

**Decision**: No changes needed in `completions.py` or `completions_translate.py`.

**Evidence**: `vllm/renderers/embed_utils.py`:
```python
if not model_config.enable_prompt_embeds:
    raise ...  # hard error
```
`vllm/inputs/preprocess.py`:
```python
if "prompt_embeds" in prompt:
    return self._process_embeds(prompt)
```
The `_process_embeds` path is reached only after the renderer guard passes. The `{"prompt_embeds": tensor}` dict format used in the current servicer is already correct.

**Rationale**: The existing Phase 6 servicer code is correct end-to-end once the engine flag is set.

---

### Finding 4: The flag is additive — no regressions expected

**Decision**: Enable the flag unconditionally for all frontend instances.

**Evidence**: `vllm/v1/worker/gpu_model_runner.py` — `enable_prompt_embeds` is checked only on `prompt_embeds`-carrying requests. Text-prompt and token-ID-prompt paths are unaffected.

**Rationale**: No reason to make this conditional. All frontend deployments benefit from having the capability available.

## Conclusion

The fix is a one-line change. All other Phase 6 infrastructure is correct. No new research tasks remain.
