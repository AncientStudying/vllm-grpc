# Research: Phase 2 — Prompt-Embeds Environment Investigation

**Branch**: `002-phase2-prompt-embeds`  
**Date**: 2026-04-29  
**Purpose**: Resolve open questions before the investigation can be scripted and executed.

---

## R1: vLLM V0 vs V1 Engine and the `prompt_embeds` Path

### Decision
The V0 engine must be explicitly requested when launching `vllm serve` on any recent vLLM release. The `prompt_embeds` feature is a V0-path capability; it has not been ported to V1.

### Rationale
vLLM's V1 engine became the default in the 0.7.x series (released early 2025). V1 introduces a new execution pipeline with different input handling — the `prompt_embeds` tensor input path exists only in the V0 `LLMInputs` / `EngineCore` code paths. The upstream PLAN.md explicitly targets "V0 vLLM path for prompt-embeds", confirming this is a known constraint.

To force V0, set the environment variable `VLLM_USE_V1_ENGINE=0` before starting the server (supported since vLLM 0.7.x; the exact flag name must be confirmed against the installed version via `vllm serve --help` and release notes).

### How to pass prompt_embeds over the API
The vLLM native OpenAI completions endpoint (`POST /v1/completions`) accepts `prompt_embeds` via the `extra_body` field:

```json
{
  "model": "Qwen/Qwen3-0.6B",
  "prompt": "",
  "extra_body": {
    "prompt_embeds": "<base64-encoded float32 numpy array, shape [seq_len, hidden_dim]>"
  }
}
```

The server must be started with a flag to accept embedded inputs (exact flag name requires verification from `vllm serve --help` on the installed version; likely `--enable-prompt-embeds` or equivalent).

### Alternatives Considered
- **Using V1 engine**: Not viable — `prompt_embeds` is not supported in V1 as of 2026-04.
- **Patching vLLM to add V1 support**: Prohibited by Constitution Principle II (library dependency, not fork).
- **Using a custom Python API instead of the REST server**: Would bypass the proxy-bridge architecture being validated in Phase 6; rejected.

---

## R2: vllm-metal — Apple Silicon GPU (MPS) Backend

### Decision
`vllm-metal` refers to vLLM's Metal Performance Shaders (MPS) backend for Apple Silicon. It is available as part of the standard `vllm` package when installed on macOS/arm64 — no separate plugin package is required. The MPS backend is activated automatically when no CUDA device is present and MPS is available.

### Rationale
vLLM added MPS (Metal) backend support targeting Apple M-series hardware. On an M2 Pro with 32 GB unified memory, the GPU (MPS) device can accelerate inference for models that fit in GPU-accessible memory. However, MPS support in vLLM has historically lagged behind CUDA, and not all features are supported on every MPS version.

Key unknowns requiring empirical verification:
1. **V0 engine on MPS**: Whether `VLLM_USE_V1_ENGINE=0` is compatible with the MPS backend.
2. **`--enable-prompt-embeds` on MPS**: Whether the V0 prompt_embeds code path runs without error when the device is MPS.
3. **Installation stability**: Whether `pip install vllm` on macOS arm64 includes a functional MPS backend in the vLLM version available in 2026-Q2.

Fallback: if MPS backend + V0 + prompt_embeds does not work, fall through to CPU-only evaluation.

### Alternatives Considered
- **CoreML backend**: Not available in vLLM; Apple's MLX framework is separate from vLLM.
- **Running in a Linux VM via Docker**: Would invalidate the "runs on the M2" premise; Docker on Apple Silicon uses qemu/Rosetta, which doesn't expose MPS to guest.

---

## R3: CPU-Only vLLM on M2 with Qwen3-0.6B

### Decision
CPU-only vLLM on the M2 is a viable fallback for functional verification but is expected to be too slow for any throughput-sensitive use in Phase 6.

### Rationale
vLLM's CPU backend is available when neither CUDA nor MPS is detected (or when `VLLM_CPU_ONLY=1` is set). Qwen3-0.6B at fp16 requires approximately 1.2 GB of RAM for weights; a 50-token completion on CPU with a small model on M2 Pro is expected to take 10–60 seconds depending on quantization and thread count. This is acceptable for functional validation but would make any Phase 6 benchmark numbers unrepresentative of production use.

Key measurements to collect during investigation:
- Wall-clock time for a 50-token completion with `prompt_embeds` on CPU
- Whether the V0 + `prompt_embeds` path works on CPU without modification

### Alternatives Considered
- **int4 quantization on CPU**: Would improve speed but adds a dependency on `bitsandbytes` or `llm-compressor`; not worth introducing for a throwaway validation step.
- **MLX on M2**: MLX (Apple's ML framework) can serve Qwen3-0.6B efficiently on M2, but MLX is not vLLM — it would not exercise the V0 prompt_embeds code path.

---

## R4: Cloud GPU Options for Phase 6

### Decision
Modal is the preferred cloud GPU option if neither M2 path works. It offers the lowest friction for single-script invocation with no persistent instance management. RunPod is the lowest-cost option for longer sessions.

### Rationale

| Provider | GPU | Price (approx 2026-Q2) | Friction | Billing |
|----------|-----|------------------------|----------|---------|
| Modal    | A10G / T4 / L4 | $0.002–0.0059/sec | Low — Python SDK, no instance management | Per-second |
| RunPod   | L4  | ~$0.44/hr  | Medium — web UI for provisioning | Per-hour |
| Lambda Labs | A10 | ~$0.60/hr | Medium — SSH, self-managed | Per-hour |

Modal is preferred because:
1. Invocation is a single Python script with no persistent instance to manage or accidentally leave running.
2. L4 and A10G both have sufficient VRAM (24 GB) to run Qwen3-0.6B at fp16.
3. CUDA support is complete — no MPS compatibility questions.

Cloud GPU evaluation can be done within the time box as a cost-and-friction estimate even if a full end-to-end run is deferred. The key question is: does `vllm serve` with `--enable-prompt-embeds` start and accept requests on a CUDA L4 with `VLLM_USE_V1_ENGINE=0`?

### Alternatives Considered
- **Google Colab**: Free tier lacks persistent VRAM guarantee; paid tier (Colab Pro+) is comparable to Modal but less scriptable.
- **AWS EC2 g4dn.xlarge (T4)**: 16 GB VRAM — marginal for Qwen3-0.6B at fp16 but workable at int8. Friction is higher due to instance provisioning.

---

## R5: Qwen3-0.6B Model Details

### Decision
Use `Qwen/Qwen3-0.6B` from HuggingFace, downloaded via `huggingface_hub`. No authentication token is required for this model.

### Rationale
- Parameters: ~600M; fp16 weight size ~1.2 GB.
- Hidden dimension: 1024 (required for constructing `prompt_embeds` tensors of correct shape).
- Vocabulary: 151,936 tokens (Qwen3 tokenizer).
- No gating or license barrier on HuggingFace as of 2026-04.
- Confirmed as the target model in `docs/PLAN.md §3 (Technology Choices)`.

### Prompt-Embeds Tensor Shape
For the verification script, a syntactically valid `prompt_embeds` input is a float32 numpy array of shape `[seq_len, 1024]`. A minimal test can use `seq_len=8` (arbitrary token embeddings). The model's output will be incoherent for random embeddings but the server response shape will be correct, which is sufficient for functional verification.

### Alternatives Considered
- **Qwen3-1.7B or larger**: Unnecessary for functional verification; larger memory footprint would fail on CPU.
- **Qwen2.5-0.5B**: Would also work but Qwen3-0.6B is the documented target model for this project.

---

---

## R6: Empirical Findings — vLLM 0.11.0 and 0.19.0 Investigation (2026-04-30)

**Status**: Supersedes assumptions in R1 and R2. Based on source inspection of installed packages and live server experiments.

### R1 Correction: prompt_embeds is V1-native, not V0-only

R1 stated that `prompt_embeds` is a V0-only path and that `VLLM_USE_V1_ENGINE=0` is required. This is wrong as of vLLM 0.11.0:

- V0 engine was **removed** in vLLM 0.11.0; setting `VLLM_USE_V1=0` raises `AssertionError`
- `prompt_embeds` was **ported to V1** and is now a first-class feature in both 0.11.0 and 0.19.0
- The `--enable-prompt-embeds` flag exists in both versions (confirmed via `vllm serve --help=enable-prompt-embeds`)
- Wire format is unchanged: base64-encoded `torch.save()` output, sent as a top-level `prompt_embeds` JSON field (not inside `extra_body`)

### R2 Correction: vllm-metal is a separate plugin, not part of the standard vLLM package

R2 stated that vllm-metal is "part of the standard `vllm` package when installed on macOS/arm64". This is wrong:

- `vllm-metal` 0.2.0 is a separate plugin package, installed at `~/.venv-vllm-metal` alongside vLLM 0.19.0
- `uv run --with vllm` installs base vLLM without the plugin — the metal plugin is absent in that environment
- vllm-metal registers a `MetalWorker` class that replaces the default GPU worker when the Metal platform is detected

### Prompt-embeds backend support matrix (confirmed by source inspection)

| vLLM model runner | Implements `prompt_embeds` |
|-------------------|---------------------------|
| `v1/worker/gpu_model_runner.py` (CUDA) | ✅ Yes |
| `v1/worker/tpu_model_runner.py` | ✅ Yes |
| `v1/worker/cpu_model_runner.py` | ❌ No (0.11.0 and 0.19.0) |
| `vllm_metal/v1/model_runner.py` (Metal/MLX) | ❌ No (0.2.0) |

### Open questions requiring empirical validation (updated)

| # | Question | Status |
|---|----------|--------|
| Q1 | What error does vllm-metal's MetalWorker produce when `prompt_embeds` is sent? | Open — empirical test needed |
| Q2 | Does vllm-metal 0.2.0 start cleanly with vLLM 0.19.0 on M2 Pro? | Open — empirical test needed |
| Q3 | What is the exact HTTP error/traceback when CPU receives `prompt_embeds` in 0.19.0? | Open — transformers compat blocked 0.11.0 test |
| Q4 | Does Modal A10G + vLLM 0.19.0 + `--enable-prompt-embeds` succeed end-to-end? | Open — requires Modal auth |

---

## Summary of Open Questions Requiring Empirical Validation

The following cannot be resolved without running experiments on the actual hardware and vLLM version:

| # | Question | Blocking | Where Answered |
|---|----------|----------|----------------|
| Q1 | Does V0 + MPS + `prompt_embeds` work on M2 Pro? | Phase 6 if M2-metal is chosen | Investigation experiment |
| Q2 | What is the wall-clock time for a 50-token completion on M2 MPS? | Throughput number for ADR | Investigation experiment |
| Q3 | What is the wall-clock time for a 50-token completion on M2 CPU? | Throughput number for ADR | Investigation experiment |
| Q4 | What is the exact flag name for enabling prompt_embeds in the installed vLLM version? | Setup script + verification script | `vllm serve --help` |
| Q5 | Does `VLLM_USE_V1_ENGINE=0` force V0 in the installed vLLM version, or is a different mechanism needed? | All experiments | vLLM release notes / `--help` |
| Q6 | Does Modal/RunPod CUDA + V0 + `prompt_embeds` work without additional patches? | Phase 6 if cloud chosen | Brief cloud experiment or docs review |
