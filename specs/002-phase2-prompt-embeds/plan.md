# Implementation Plan: Phase 2 — Prompt-Embeds Environment Investigation

**Branch**: `002-phase2-prompt-embeds` | **Date**: 2026-04-30 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/002-phase2-prompt-embeds/spec.md`

## Summary

Determine which compute environment (M2 vllm-metal 0.2.0, M2 CPU-only, or cloud GPU) can
serve Qwen3-0.6B with `prompt_embeds` via vLLM's native OpenAI server, using **vLLM 0.20.0**
and **vllm-metal 0.2.0** as the target versions. Both packages are installed cleanly in the
repo via a `uv` dependency group — matching the project's existing pattern for vllm — rather
than relying on any global venv. Produce an ADR, a reproducible setup script, and a throwaway
verification script. No bridge or proxy code is written.

Key findings from live investigation (research.md R6):

- `prompt_embeds` is **V1-native** in vLLM 0.11.0+; V0 was removed. No engine override env
  var needed.
- `--enable-prompt-embeds` flag confirmed in vLLM 0.20.0 (`vllm serve --help=enable-prompt-embeds`).
- Wire format: base64-encoded `torch.save()` output sent as the top-level `prompt_embeds` JSON
  field (not inside `extra_body`).
- Only `gpu_model_runner.py` (CUDA) and `tpu_model_runner.py` implement prompt_embeds in
  vLLM's V1 engine. `cpu_model_runner.py` and vllm-metal's `MetalWorker` do not — per source
  inspection — but empirical evidence is required per FR-002.
- vllm-metal 0.2.0 installs from a GitHub release wheel (not PyPI). vLLM 0.20.0 is on PyPI.
  The official `install.sh` pairs these two versions.

## Technical Context

**Language/Version**: Python 3.12 (workspace already configured)
**Primary Dependencies**:
  - `vllm` macOS-compatible version (currently resolves to 0.11.0 — vllm 0.20.0 has `nvidia-cudnn-frontend` as a CUDA-Linux-only dep with no macOS wheels; the install.sh works around this by building from source, but that cannot be replicated cleanly via uv)
  - `vllm-metal==0.2.0` (GitHub wheel, in `investigation` dependency group)
  - `httpx` (verification script HTTP calls)
  - `torch` (prompt_embeds tensor construction, included transitively by vllm)
  - `modal==1.4.2` (cloud candidate only — cloud environment is Linux/CUDA and CAN use vllm 0.20.0)
**Storage**: N/A — results written to `docs/decisions/` as an ADR
**Testing**: No pytest — verification is a standalone script producing pass/fail + timing output
**Target Platform**: M2 Pro MacBook Pro, macOS (primary); CUDA cloud GPU (fallback candidate)
**Project Type**: Investigation scripts + documentation
**Performance Goals**: Measure wall-clock time for a 50-token Qwen3-0.6B completion per candidate
**Constraints**: 2–3 day time box; V1 engine only (V0 removed in 0.11.0+); no new bridge code; no vLLM source modifications
**Scale/Scope**: 3 candidate environments × 1 experiment each; 1 ADR; 2 scripts

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Proto-First | ✅ PASS | No new `.proto` files or RPCs defined in this phase |
| II. Library Dependency, Not Fork | ✅ PASS | `vllm==0.20.0` and `vllm-metal==0.2.0` used as ordinary published packages; no source patching or vendoring |
| III. Phase Discipline | ✅ PASS | Deliverables match `docs/PLAN.md §Phase 2` exactly; no Phase 3+ features introduced |
| IV. CI is the Merge Gate | ✅ PASS | Scripts pass `ruff` + `mypy --strict`; `make check` in exit criteria |
| V. Honest Measurement | ✅ PASS | Empirical evidence required for all candidates; negative results and source-inspection-only findings clearly labelled; throughput numbers committed to ADR |

**Post-design re-check**: All principles pass. Clean local install of vllm-metal via uv dependency group (Principle II) supersedes the earlier approach of using the pre-installed global venv.

## Project Structure

### Documentation (this feature)

```text
specs/002-phase2-prompt-embeds/
├── plan.md              # This file
├── research.md          # Phase 0 output (complete; R6 added 2026-04-30)
├── quickstart.md        # Phase 1 output (complete)
└── tasks.md             # Phase 2 output (T001–T019; T017–T019 added 2026-04-30)
```

### Source Code (repository root)

```text
pyproject.toml                          # investigation dependency group added here

scripts/
├── python/
│   ├── verify_prompt_embeds.py         # Verification script (vLLM 0.20.0 compatible)
│   └── verify_prompt_embeds_modal.py   # Modal cloud variant (awaiting auth)
└── setup/
    └── phase2-env.sh                   # Setup script for the chosen environment (T012)

docs/
└── decisions/
    └── 0001-prompt-embeds-environment.md   # ADR: environment decision + throughput data
```

**Structure Decision**: Scripts-only phase. No new workspace packages. vllm-metal and vllm are
declared in `pyproject.toml` under `[dependency-groups] investigation`, managed by uv, and
installed on demand with `uv sync --group investigation` — matching the project's uv-first
workflow. ADR lives in `docs/decisions/` per constitution workflow requirement.

## Phase 0: Research

**Status**: Complete — `research.md` exists with R1–R6.

Key resolutions:

| Question | Resolution |
|----------|------------|
| Flag name for prompt_embeds | `--enable-prompt-embeds` (confirmed vLLM 0.20.0) |
| V0/V1 engine | V0 removed; V1 is mandatory; `prompt_embeds` is V1-native |
| Wire format | base64(`torch.save(tensor)`) as top-level JSON field `prompt_embeds` |
| vllm-metal source | GitHub release wheel: `vllm_metal-0.2.0-cp312-cp312-macosx_11_0_arm64.whl` |
| Paired vLLM version | 0.20.0 (per current `install.sh`; 0.19.0 is stale) |
| M2 MPS support (source) | `MetalWorker` has no prompt_embeds impl; empirical test required |
| CPU support (source) | `cpu_model_runner.py` has no prompt_embeds impl; empirical test required |

## Phase 1: Design & Contracts

**Status**: Complete — `quickstart.md` exists. No external interface contracts (scripts-only phase).

### Dependency Group (pyproject.toml)

vllm-metal 0.2.0 is declared in `pyproject.toml`; vllm is added at runtime via `--with vllm`
because vllm 0.20.0 cannot install on macOS (CUDA-only `nvidia-cudnn-frontend` dep). The
install.sh builds vllm from source to avoid this — our uv approach uses `--with vllm` which
resolves to the latest macOS-compatible wheel (currently 0.11.0).

```toml
[dependency-groups]
investigation = [
    # vllm added via --with vllm at runtime (see commands below)
    "vllm-metal @ https://github.com/vllm-project/vllm-metal/releases/download/v0.2.0-20260430-132616/vllm_metal-0.2.0-cp312-cp312-macosx_11_0_arm64.whl",
]
```

Install: `uv sync --group investigation`

Verified: `uv run --group investigation --with vllm python -c "..."` activates `MetalPlatform` correctly with vllm 0.11.0.

### Wire Format (confirmed from vLLM 0.20.0 source — unchanged from 0.11.0)

```python
tensor = torch.zeros(seq_len, 1024, dtype=torch.float32)  # [seq_len, hidden_dim]
buf = io.BytesIO()
torch.save(tensor, buf)
embed_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

payload = {
    "model": "Qwen/Qwen3-0.6B",
    "prompt_embeds": embed_b64,   # top-level field, NOT inside extra_body
    "max_tokens": 50,
}
```

### Candidate Experiment Matrix

| Candidate | Command prefix | vllm version | Plugin | Port | Task |
|-----------|---------------|--------------|--------|------|------|
| A — M2 Metal | `uv run --group investigation --with vllm` | 0.11.0 (macOS compat) | vllm-metal 0.2.0 active | 9002 | T018 |
| B — M2 CPU | `VLLM_PLUGINS="" uv run --group investigation --with vllm` | 0.11.0 (macOS compat) | metal disabled | 9003 | T019 |
| C — Modal A10G | `uv run --with modal --with vllm==0.20.0` | 0.20.0 (Linux/CUDA) | N/A | 8000 (container) | T009 |

Server start command pattern:

```bash
# Candidate A (Metal platform auto-detected via vllm-metal plugin)
uv run --group investigation --with vllm vllm serve Qwen/Qwen3-0.6B \
  --enable-prompt-embeds --max-model-len 256 --port 9002

# Candidate B (metal plugin explicitly suppressed)
VLLM_PLUGINS="" uv run --group investigation --with vllm vllm serve Qwen/Qwen3-0.6B \
  --enable-prompt-embeds --max-model-len 256 --port 9003
```
