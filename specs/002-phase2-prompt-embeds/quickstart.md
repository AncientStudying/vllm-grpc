# Quickstart: Phase 2 — Prompt-Embeds Environment Investigation

**Branch**: `002-phase2-prompt-embeds`  
**Status**: Complete  
**Chosen environment**: Modal A10G — vLLM 0.20.0 on Linux/CUDA (see ADR 0001)

---

## Overview

This phase produces three things:

1. Empirical measurements of `prompt_embeds` support across three candidate environments
2. An Architecture Decision Record (ADR) documenting the chosen environment
3. A setup script + verification script for the chosen environment

No bridge or proxy code is written. All commands go directly to vLLM's native OpenAI server.

**Key finding**: `prompt_embeds` requires a CUDA GPU. Both macOS candidates (Metal and CPU)
failed — the feature is implemented only in `gpu_model_runner.py` in vLLM's V1 engine.

---

## Prerequisites

```bash
# Verify Phase 1 bootstrap still works
make bootstrap
make check

# Verify Python 3.12 is active
python --version  # should print Python 3.12.x

# Verify uv is installed
uv --version
```

---

## Step 1 — Determine the installed vLLM version and flag names

```bash
# Install a minimal vLLM in an isolated environment for inspection
uv run --with vllm python -c "import vllm; print(vllm.__version__)"

# Check available flags
uv run --with vllm vllm serve --help | grep -i "prompt.embed\|enable"
```

**Findings** (recorded in ADR 0001):
- macOS resolves to vLLM **0.11.0** — the latest PyPI wheel with macOS ARM support
- vLLM 0.20.0 requires `nvidia-cudnn-frontend==1.18.0`, which has no macOS wheels; cannot be installed on macOS via pip/uv
- V0 engine was **removed** in vLLM 0.11.0+; `VLLM_USE_V1_ENGINE=0` raises `AssertionError`; V1 is the only engine
- Prompt-embeds flag: `--enable-prompt-embeds` (default: False)
- Wire format: `base64(torch.save(tensor))` as top-level `prompt_embeds` JSON field (not inside `extra_body`)

---

## Step 2 — Candidate A: M2 Metal (vllm-metal 0.2.0)

```bash
# Install investigation dependency group (includes vllm-metal 0.2.0 wheel)
uv sync --group investigation

# Start the server (vllm-metal auto-activates MetalPlatform via plugin system)
uv run --group investigation --with vllm vllm serve Qwen/Qwen3-0.6B \
    --enable-prompt-embeds \
    --max-model-len 256 \
    --port 9002
```

**Result**: ❌ NOT VIABLE — server crashes at startup:
```
ModuleNotFoundError: No module named 'vllm.utils.torch_utils'
```
vllm-metal 0.2.0 requires APIs from vllm 0.20.0; the macOS-compatible vllm (0.11.0) does not
have them. vllm 0.20.0 cannot be installed on macOS via uv due to CUDA-only
`nvidia-cudnn-frontend` dep. Additionally, vllm-metal's `MetalWorker` has no `prompt_embeds`
implementation — this candidate cannot work regardless of the version constraint.

---

## Step 3 — Candidate B: M2 CPU-only (vllm 0.11.0)

```bash
# Start vLLM with metal plugin suppressed (forces CPU path)
VLLM_PLUGINS="" uv run --group investigation --with vllm vllm serve Qwen/Qwen3-0.6B \
    --enable-prompt-embeds \
    --max-model-len 256 \
    --port 9003
```

**Result**: ❌ NOT VIABLE — server crashes at startup:
```
AttributeError: Qwen2Tokenizer has no attribute all_special_tokens_extended
```
`transformers==5.7.0` is incompatible with vllm 0.11.0's tokenizer wrapper for Qwen3.
Additionally, `cpu_model_runner.py` has no `prompt_embeds` implementation — this candidate
cannot work even if the tokenizer issue were resolved.

---

## Step 4 — Run the Verification Script (local candidates)

If a local candidate server does start, run:

```bash
uv run scripts/python/verify_prompt_embeds.py \
    --base-url http://localhost:9002 \
    --model Qwen/Qwen3-0.6B \
    --seq-len 8 \
    --max-tokens 50
```

Expected output on success:
```
[OK] Server responded in X.XXs
[OK] prompt_embeds accepted — environment is viable
```

Note: Neither Candidate A nor B reached this step — both crashed before accepting requests.

---

## Step 5 — Candidate C: Cloud GPU (Modal A10G) — Chosen Environment

Modal auth is a one-time setup per machine:

```bash
# Authenticate with Modal (opens browser, stores token in ~/.modal.toml)
uv run --with modal modal token new
```

Run the verification experiment:

```bash
uv run --with modal modal run scripts/python/verify_prompt_embeds_modal.py
```

Expected runtime: 7–12 minutes (image build + model download + inference).  
Expected cost: ~$0.10–$0.16 per run (A10G at ~$0.013/min).

**Result**: ✅ VIABLE
```
[OK] Server responded in 1.54s
[OK] Tokens generated: 50
[OK] prompt_embeds accepted — Modal A10G environment is viable
```

Or use the setup script (validates prerequisites then runs the above):

```bash
bash scripts/setup/phase2-env.sh
```

---

## Step 6 — ADR

The ADR is written and committed at `docs/decisions/0001-prompt-embeds-environment.md`.
It contains vLLM version details, all three candidate results with empirical evidence,
the decision (Modal A10G), rationale, and rejected alternatives.

No template file is used — the ADR was created directly from the skeleton in T002.

---

## Step 7 — Finalize Scripts

```bash
# Verify all scripts pass lint, type checks, and tests
make check

# Commit all Phase 2 artifacts
git add docs/decisions/ scripts/ specs/002-phase2-prompt-embeds/ pyproject.toml uv.lock
git commit -m "Phase 2: prompt-embeds environment investigation complete"

# Merge to main
git checkout main && git merge --no-ff 002-phase2-prompt-embeds
```

---

## Exit Criteria Checklist

- [x] Chosen environment serves Qwen3-0.6B with `prompt_embeds` end-to-end (verification script passes)
- [x] Throughput number (wall-clock time, 50-token completion) recorded in ADR — **1.54s**
- [x] All three candidates evaluated with documented rationale
- [x] Setup script (`scripts/setup/phase2-env.sh`) runs end-to-end cleanly
- [x] `make check` passes on all committed scripts
- [x] ADR written and committed to `docs/decisions/0001-prompt-embeds-environment.md`
- [ ] Branch merged to `main` with CI green
