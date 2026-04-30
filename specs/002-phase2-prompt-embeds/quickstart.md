# Quickstart: Phase 2 — Prompt-Embeds Environment Investigation

**Branch**: `002-phase2-prompt-embeds`  
**Time box**: 2–3 days  
**Prerequisite**: Phase 1 deliverables are on `main` and CI is green.

---

## Overview

This phase produces three things:

1. Empirical measurements of `prompt_embeds` support across three candidate environments
2. An Architecture Decision Record (ADR) documenting the chosen environment
3. A setup script + verification script for the chosen environment

No bridge or proxy code is written. All commands go directly to vLLM's native OpenAI server.

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

Before running any experiment, inspect the installed vLLM to confirm flag names.

```bash
# Install a minimal vLLM in an isolated environment for inspection
uv run --with vllm python -c "import vllm; print(vllm.__version__)"

# Check available flags
uv run --with vllm vllm serve --help | grep -i "prompt.embed\|v1.engine\|v0\|enable"
```

Record:
- vLLM version
- The exact flag or environment variable that enables V0 engine (likely `VLLM_USE_V1_ENGINE=0`)
- The exact flag that enables prompt_embeds (likely `--enable-prompt-embeds`)

If neither flag exists, check the vLLM changelog for the installed version and update the setup/verification scripts accordingly.

---

## Step 2 — Candidate A: M2 vllm-metal (MPS backend)

```bash
# Install vLLM (MPS backend is included on macOS arm64)
pip install vllm   # or: uv add vllm to a scratch venv

# Start the server in V0 mode, targeting MPS, with prompt_embeds enabled
VLLM_USE_V1_ENGINE=0 vllm serve Qwen/Qwen3-0.6B \
    --enable-prompt-embeds \
    --device mps \
    --max-model-len 512 \
    --port 9000
```

Then run the verification script (Step 4). Record:
- Whether the server started without errors
- Wall-clock time for a 50-token completion (from verification script output)
- Any errors or warnings in server logs

---

## Step 3 — Candidate B: M2 CPU-only vLLM

```bash
# Start the server in V0 mode, CPU only, with prompt_embeds enabled
VLLM_USE_V1_ENGINE=0 VLLM_CPU_ONLY=1 vllm serve Qwen/Qwen3-0.6B \
    --enable-prompt-embeds \
    --device cpu \
    --max-model-len 256 \
    --port 9001
```

Then run the verification script (Step 4). Record:
- Whether the server started without errors
- Wall-clock time for a 50-token completion
- Any errors or warnings

---

## Step 4 — Run the Verification Script

Once either candidate server is running, run:

```bash
# Generate and send a minimal prompt_embeds request
uv run scripts/python/verify_prompt_embeds.py \
    --base-url http://localhost:9000 \
    --model Qwen/Qwen3-0.6B \
    --seq-len 8 \
    --max-tokens 50
```

Expected output:
```
[OK] Server responded in X.XXs
[OK] Response contains 50 tokens
[OK] prompt_embeds accepted — environment is viable
```

If the script fails with a 400 or 422 error, check the error message for the exact field name mismatch.

---

## Step 5 — Candidate C: Cloud GPU (Modal)

If both M2 candidates fail or produce unacceptably slow results:

```bash
# Install Modal CLI
pip install modal

# Authenticate (one-time)
modal setup

# Deploy and run the verification script on a Modal A10G
uv run scripts/python/verify_prompt_embeds_modal.py
```

Record:
- Whether `prompt_embeds` is accepted on CUDA
- Wall-clock time for a 50-token completion on A10G
- Estimated cost per run (Modal dashboard)

---

## Step 6 — Write the ADR

Once all viable candidates are evaluated (or explicitly ruled out), write the decision:

```bash
# Create the ADR file (fill in the template with measured results)
cp docs/decisions/adr-template.md docs/decisions/0001-prompt-embeds-environment.md
# Edit with your findings — see template for required sections
```

The ADR must contain:
- Version of vLLM tested
- Results for each candidate (pass/fail + throughput number)
- The chosen environment and rationale
- The rejected environments and reason for rejection

---

## Step 7 — Finalize Scripts

Move the working scripts from throwaway state to committed state:

```bash
# Lint and type-check before committing
make check

# Commit the setup script + verification script + ADR
git add scripts/ docs/decisions/0001-prompt-embeds-environment.md
git commit -m "Phase 2: prompt-embeds environment investigation complete"
```

---

## Exit Criteria Checklist

Before marking Phase 2 complete:

- [ ] Chosen environment serves Qwen3-0.6B with `prompt_embeds` end-to-end (verification script passes)
- [ ] Throughput number (wall-clock time, 50-token completion) recorded in ADR
- [ ] All three candidates evaluated or ruled out with documented rationale
- [ ] Setup script runs from scratch on M2 Pro (or cloud equivalent documented)
- [ ] `make check` passes on all committed scripts
- [ ] ADR written and committed to `docs/decisions/0001-prompt-embeds-environment.md`
- [ ] Branch merged to `main` with CI green
