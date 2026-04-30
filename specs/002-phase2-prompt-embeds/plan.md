# Implementation Plan: Phase 2 — Prompt-Embeds Environment Investigation

**Branch**: `002-phase2-prompt-embeds` | **Date**: 2026-04-29 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `specs/002-phase2-prompt-embeds/spec.md`

## Summary

Determine which compute environment (M2 vllm-metal, M2 CPU-only, or cloud GPU) can serve Qwen3-0.6B with V0 `prompt_embeds` enabled via vLLM's native OpenAI server. Produce an ADR, a reproducible setup script, and a throwaway verification script. No bridge or proxy code is written.

From research: `prompt_embeds` is a V0-path-only feature; the V0 engine is forced via `VLLM_USE_V1_ENGINE=0`. M2 MPS (vllm-metal) is the highest-priority candidate. CPU-only is the M2 fallback. Modal cloud GPU is the final fallback. All exact flag names must be confirmed from the installed vLLM version before scripting.

## Technical Context

**Language/Version**: Python 3.12 (workspace already configured)  
**Primary Dependencies**: `vllm` (current version — confirmed at investigation time), `numpy` (prompt_embeds tensor construction), `httpx` (verification script HTTP calls), `modal` (cloud candidate only)  
**Storage**: N/A — results written to `docs/decisions/` as an ADR  
**Testing**: No pytest — verification is a standalone script producing pass/fail + timing output  
**Target Platform**: M2 Pro MacBook Pro, macOS (primary); CUDA cloud GPU (fallback candidate)  
**Project Type**: Investigation scripts + documentation  
**Performance Goals**: Measure wall-clock time for a 50-token Qwen3-0.6B completion per candidate environment  
**Constraints**: 2–3 day time box; V0 engine only; no new bridge code; no vLLM source modifications  
**Scale/Scope**: 3 candidate environments × 1 experiment each; 1 ADR; 2 scripts

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Proto-First | ✅ PASS | No new `.proto` files or RPCs defined in this phase |
| II. Library Dependency, Not Fork | ✅ PASS | `vllm` installed as an ordinary library dependency; no patches or vendoring |
| III. Phase Discipline | ✅ PASS | Deliverables match `docs/PLAN.md §Phase 2` exactly; no Phase 3+ features introduced |
| IV. CI is the Merge Gate | ✅ PASS | Scripts must pass `ruff` + `mypy --strict` before commit; `make check` in exit criteria |
| V. Honest Measurement | ✅ PASS | Throughput numbers for all viable candidates committed to ADR; negative results reported |

**Post-design re-check**: All principles continue to pass — no new packages, no new RPCs, no bypass of CI.

## Project Structure

### Documentation (this feature)

```text
specs/002-phase2-prompt-embeds/
├── plan.md              # This file
├── research.md          # Phase 0 output (complete)
├── quickstart.md        # Phase 1 output (complete)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
scripts/
├── python/
│   ├── verify_prompt_embeds.py        # Throwaway verification script (direct vLLM, no bridge)
│   └── verify_prompt_embeds_modal.py  # Modal cloud variant (created only if cloud path needed)
└── setup/
    └── phase2-env.sh                  # Setup script for the chosen environment

docs/
└── decisions/
    └── 0001-prompt-embeds-environment.md   # ADR: environment decision + throughput data
```

**Structure Decision**: Scripts-only phase. Existing `scripts/python/` and `scripts/setup/` directories receive new files. No new packages added to the uv workspace. ADR written to `docs/decisions/` per the constitution workflow requirement.

Note: `scripts/setup/` does not exist yet — it will be created alongside `phase2-env.sh`.
