# ADR 0001: Prompt-Embeds Compute Environment

**Date**: 2026-04-29  
**Branch**: `002-phase2-prompt-embeds`  
**Status**: Accepted

---

## Context

Phase 6 of this project requires serving Qwen3-0.6B with V0 `prompt_embeds` via vLLM's native
OpenAI server. Before writing any bridge code, this ADR documents which compute environment
can actually do that, along with measured throughput.

Three candidates were evaluated:

- **Candidate A**: M2 Pro MBP — vLLM with MPS (Metal Performance Shaders) backend
- **Candidate B**: M2 Pro MBP — vLLM CPU-only backend
- **Candidate C**: Cloud GPU — CUDA instance (Modal/RunPod/Lambda L4)

---

## vLLM Version

<!-- Filled in by T003 (0.11.0 source) + T017 (0.20.0 empirical) -->

**Target version for this investigation**: vLLM 0.20.0 + vllm-metal 0.2.0 (installed via `pyproject.toml [dependency-groups] investigation`)

| Field | Value |
|-------|-------|
| vLLM version (macOS) | 0.11.0 — latest macOS-compatible PyPI wheel; vllm 0.20.0 has `nvidia-cudnn-frontend` as a CUDA-Linux-only dep with no macOS wheels |
| vLLM version (cloud) | 0.20.0 — used for Candidate C (Linux/CUDA environment) |
| vllm-metal version | 0.2.0 (GitHub release wheel `v0.2.0-20260430-132616`); officially paired with vllm 0.20.0 by install.sh |
| Engine | V1 only — V0 was removed in 0.11.0; setting `VLLM_USE_V1=0` raises `AssertionError` |
| Prompt-embeds flag | `--enable-prompt-embeds` (default: False); confirmed in both 0.11.0 and 0.20.0 |
| Platform backends | base vLLM: cpu, cuda, rocm, tpu, xpu; vllm-metal 0.2.0 adds: Metal (`MetalPlatform`, MLX-based `MetalWorker`) |
| prompt_embeds wire format | Base64-encoded `torch.save()` output (float32/bfloat16/float16 tensor, shape [seq_len, hidden_size]), sent as top-level `prompt_embeds` JSON field (not inside `extra_body`) |
| prompt_embeds backend support (source) | GPU/CUDA (`gpu_model_runner.py`) ✅, TPU (`tpu_model_runner.py`) ✅, CPU (`cpu_model_runner.py`) ❌, Metal (`vllm_metal/v1/model_runner.py`) ❌ — empirical verification in T018/T019 |
| Install command | `uv sync --group investigation && uv run --group investigation --with vllm ...` |

---

## Candidate A: M2 Metal (vllm-metal 0.2.0)

| Field | Value |
|-------|-------|
| Status | ❌ NOT VIABLE (on macOS via uv) |
| Server started | No — crashed at startup |
| prompt_embeds accepted | N/A |
| Wall-clock time (50-token completion) | N/A |
| Start command tried | `uv run --group investigation --with vllm vllm serve Qwen/Qwen3-0.6B --enable-prompt-embeds --max-model-len 256 --port 9002` |
| vllm version in uv env | 0.11.0 (latest macOS-compatible PyPI wheel) |
| Startup error | `ModuleNotFoundError: No module named 'vllm.utils.torch_utils'` — vllm-metal 0.2.0 requires this module which was added after 0.11.0 |
| Root cause chain | vllm 0.20.0 (which has `vllm.utils.torch_utils`) cannot be installed on macOS via PyPI because its transitive dep `nvidia-cudnn-frontend==1.18.0` has no macOS wheels. The official `install.sh` works around this by building vllm 0.20.0 from source — but this cannot be replicated via `uv sync --group investigation`. |
| Source-level finding | vllm-metal's `v1/model_runner.py` has no `prompt_embeds` implementation regardless of version, so even if startup succeeded, prompt_embeds requests would fail at the model runner level. |
| Possible path (not pursued) | Use `~/.venv-vllm-metal` (install.sh build) — but this is outside the project's dependency management and cannot be made reproducible via uv. |

---

## Candidate B: M2 CPU-only (vllm 0.11.0)

<!-- Filled in by T008 + T019 -->

| Field | Value |
|-------|-------|
| Status | ❌ NOT VIABLE |
| Server started | No — crashed at startup |
| prompt_embeds accepted | N/A |
| Wall-clock time (50-token completion) | N/A |
| Start command tried | `VLLM_PLUGINS="" uv run --group investigation --with vllm vllm serve Qwen/Qwen3-0.6B --enable-prompt-embeds --max-model-len 256 --port 9003` |
| vllm version | 0.11.0 (latest macOS-compatible PyPI wheel) |
| Startup error | `AttributeError: Qwen2Tokenizer has no attribute all_special_tokens_extended` — transformers 5.7.0 is incompatible with vllm 0.11.0's tokenizer wrapper for Qwen3 |
| Fundamental blocker | Even if startup succeeded: `vllm/v1/worker/cpu_model_runner.py` has no `prompt_embeds` implementation in either 0.11.0 or 0.20.0 (confirmed by source inspection) |
| macOS vllm 0.20.0 constraint | vllm 0.20.0 cannot be installed on macOS via PyPI (CUDA-only `nvidia-cudnn-frontend` dep); no macOS wheel available; install.sh builds from source. CPU-only path with 0.20.0 untestable via uv on macOS without the source-build. |

---

## Candidate C: Cloud GPU

| Field | Value |
|-------|-------|
| Status | ✅ VIABLE — chosen environment |
| Provider | Modal (serverless GPU cloud) |
| GPU type | NVIDIA A10G (24 GB VRAM) |
| vLLM version | 0.20.0 (Linux/CUDA; installed into Modal container via pip) |
| prompt_embeds accepted | Yes |
| Wall-clock time (50-token completion) | **1.54s** |
| Tokens generated | 50 |
| Estimated cost per run | ~$0.10–$0.16 (7–12 min at ~$0.013/min A10G rate) |
| Run command | `uv run --with modal modal run scripts/python/verify_prompt_embeds_modal.py` |
| Container definition | `modal.Image.debian_slim(python_version="3.12").pip_install("vllm==0.20.0", "httpx", "torch")` |
| Server flags | `--enable-prompt-embeds --max-model-len 512 --port 8000` |
| Execution model | Ephemeral — Modal provisions an A10G, runs the experiment, tears down; nothing persists |
| Auth required | `modal token new` (one-time browser login; token stored in `~/.modal.toml`) |

---

## Decision

**Chosen environment**: Modal A10G — vLLM 0.20.0 on Linux/CUDA via Modal serverless cloud

**Throughput**: 1.54s wall-clock for a 50-token Qwen3-0.6B completion

---

## Rationale

`prompt_embeds` is implemented only in `gpu_model_runner.py` (CUDA) and `tpu_model_runner.py`
in vLLM's V1 engine. Both macOS candidates (Metal and CPU) lack the implementation entirely,
and both also failed to start due to independent compatibility blockers. Cloud GPU is not a
fallback choice — it is the only path that could ever work given current vLLM architecture.

Modal was selected over RunPod/Lambda because:
- Python-native API: the entire container definition and server invocation are code, not YAML
- Ephemeral by default: no idle cost, no persistent cluster to manage
- Free-tier credits cover the full investigation
- `modal run` (one command) handles provisioning, execution, and teardown

The 1.54s wall-clock for 50 tokens (Qwen3-0.6B, seq_len=8, A10G) establishes a baseline for
Phase 6 bridge latency budgeting.

---

## Rejected Alternatives

### Candidate A rejected: M2 Metal (vllm-metal 0.2.0 + vllm 0.11.0)

Two independent blockers, either of which is fatal:

1. **API incompatibility**: vllm-metal 0.2.0 requires `vllm.utils.torch_utils` (introduced after
   0.11.0). vllm 0.20.0 — which has the module — cannot be installed on macOS via PyPI because
   its transitive dep `nvidia-cudnn-frontend==1.18.0` has no macOS wheels. The official
   `install.sh` builds vllm 0.20.0 from source, but this is outside the project's uv-managed
   dependency model and cannot be made reproducible.

2. **Missing implementation**: vllm-metal's `v1/model_runner.py` (`MetalWorker`) has no
   `prompt_embeds` code path. Even if startup succeeded, any `prompt_embeds` request would fail
   at the model runner level.

### Candidate B rejected: M2 CPU-only (vllm 0.11.0)

Two independent blockers, either of which is fatal:

1. **Tokenizer incompatibility**: `transformers==5.7.0` is incompatible with vllm 0.11.0's
   tokenizer wrapper for Qwen3 — `AttributeError: Qwen2Tokenizer has no attribute
   all_special_tokens_extended`. The server crashes before accepting any requests.

2. **Missing implementation**: `vllm/v1/worker/cpu_model_runner.py` has no `prompt_embeds`
   implementation in either 0.11.0 or 0.20.0 (confirmed by source inspection). This is a
   fundamental architectural gap, not a version-specific bug.
