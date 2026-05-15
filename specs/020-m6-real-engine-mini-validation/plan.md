# Implementation Plan: M6 — Real-Engine Mini-Validation

**Branch**: `020-m6-real-engine-mini-validation` | **Date**: 2026-05-14 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/020-m6-real-engine-mini-validation/spec.md`

## Summary

Replace MockEngine with real Qwen3-7B inference on Modal A10G for a focused 6-cell × 3-cohort slice of M5.2's matrix at h=4096, in order to close the "real-engine validation" caveat that M5.1 and M5.2 both deferred. Output: a per-cell "Supersedes M5.2 under real engine" verdict table classifying each cell as `verdict_survives` / `verdict_buried_by_engine` / `verdict_changed` / `no_winner_at_n100` / `cell_incomplete`, plus a published engine-cost-per-RPC baseline that M7's prompt-length-scaling work inherits as a real cost floor.

**Technical approach.** Reuse the existing M5.2 harness (`tools/benchmark/src/vllm_grpc_bench/`) wholesale — cell × cohort × concurrency orchestration, RTT probe, events sidecar, symmetry audit, JSON+markdown reporter. Add a `--m6` CLI branch that narrows the matrix (6 cells × 3 cohorts × n=100), wires the round-robin per c-batch sequencing convention (FR-022), pins per-RPC sampling seeds (FR-025), and feeds verdicts into a new M6 classifier that reads M5.2 winner deltas from the published JSON (FR-014). Add greenfield server-side timing wrapping in the gRPC frontend so the engine's per-RPC forward-pass / TTFT / TPOT cost is published via gRPC trailing metadata (FR-008); mirror that contract in the REST shim via JSON-payload fields. Swap MockEngine for `AsyncLLM` loaded with Qwen3-7B in the existing Modal app (`scripts/python/modal_bench_rest_grpc_server.py`) behind a flag, with model loading once at sweep start (FR-024) and `enable_prompt_embeds=True` inherited from Phase 6.1.

## Technical Context

**Language/Version**: Python 3.12 (project standard; matches M5.x harness, frontend, proxy, and Modal app)
**Primary Dependencies**: `vllm` (real engine — Qwen3-7B fp16, ~14 GB GPU; AsyncLLM as in Phase 6.1), `grpcio` + `grpcio-tools` (HTTP/2 transport for gRPC cohorts), `FastAPI` + `uvicorn` (REST shim for `rest_https_edge` cohort), `modal` (deployment + HTTPS edge + plain-TCP tunnel), the existing `vllm_grpc_bench` harness package (M5.2 codebase under `tools/benchmark/`), and `vllm_grpc_frontend` / `vllm_grpc_proxy` packages (under `packages/`).
**Storage**: Outputs written to `docs/benchmarks/m6-real-engine-mini-validation.{md,json}`; per-RPC events JSONL sidecar at a path the operator passes via flag (mirroring M5.2's `--m5_2-events-sidecar-out`). Inputs read from `docs/benchmarks/m5_2-transport-vs-tuning.json` (classifier baseline — FR-014 hard precondition).
**Testing**: `pytest` + `pytest-asyncio` (project convention). Unit tests for the M6 verdict classifier on synthetic inputs (deterministic — FR-014); integration tests for the engine-cost instrumentation contract (gRPC trailing metadata + REST JSON parity); harness-level test for the round-robin per c-batch sequencer (FR-022) and the per-RPC seed mapping (FR-025).
**Target Platform**: Modal A10G GPU instance in `eu-west-1` (default per FR-006 and Assumption "Region"). Driven from operator workstation (M2 Pro MBP per Phase 1 / Assumption "Driver"); operator pre-configures `modal token new`.
**Project Type**: Sibling library + benchmark harness — Python monorepo with `proxy/`, `frontend/`, `client/`, `proto/`, `tools/benchmark/`, `scripts/`, `docs/benchmarks/`. M6 is a benchmark-research milestone, not a library / CLI / web-service in the conventional product sense.
**Performance Goals**:
- SC-001: Full sweep ≤ 90 min wall-clock on Modal A10G (PLAN.md budget 75–90 min).
- SC-004: Smoke gate ≤ 5 min wall-clock.
- Per-cohort 95% CI half-widths must be narrow enough that the classifier's CI-overlap test resolves the majority of cells into a non-`no_winner_at_n100` bucket on a representative run (no separate SC; implicit from sweep structure).

**Constraints**:
- A10G GPU memory: Qwen3-7B fp16 ≈ 14 GB + KV-cache headroom for c=8 chat_stream within 24 GB total. Quantisation pinning to fp16 is mandatory (Edge case "GPU memory exceeds A10G's 24 GB").
- FR-016: JSON companion is a strict superset of M5.2's schema; existing M5.2-aware consumers (the `m5_2_supersede` classifier itself, downstream M5.1 supersession code paths) MUST continue to work unmodified against M6's JSON.
- FR-024: One engine instance for the entire sweep; no reload per cell or per path. Engine loads in the Modal app's startup hook before the gRPC + REST servers begin accepting traffic.
- FR-014: Verdict classifier is deterministic given M6 numeric inputs and the M5.2 published winner deltas — no operator post-hoc re-classification permitted.

**Scale/Scope**:
- 6 cells × 3 cohorts × 100 measurement RPCs = 1,800 measurement RPCs per full sweep.
- + 6 cells × 3 cohorts × 10 warmup RPCs (FR-021) = 180 warmup RPCs.
- + 2 smoke cells × 3 cohorts × 10 RPCs (FR-011) = 60 smoke RPCs.
- Total ≈ 2,040 RPCs per "smoke + full sweep" sequence on Modal A10G.
- Generation length: chat_stream max_tokens=50 per RPC (FR-005); embed unary, no generation.
- Engine cost: forward-pass for embed (~tens of ms at h=4096) + TTFT/TPOT for chat_stream (~hundreds of ms TTFT, ~30–50 ms TPOT × 50 tokens ≈ 1.5–2.5 s total wall-clock per chat_stream RPC).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against the 5 principles in `.specify/memory/constitution.md` (v1.0.0):

| Principle | Status | Notes |
|---|---|---|
| **I. Proto-First** | **PASS** | Engine cost is published via gRPC **trailing metadata** (per FR-008 "via gRPC response or trailing metadata" — trailing metadata picked to avoid proto-message changes; settled in Research item R-2). REST shim adds JSON-payload fields (REST is not proto-tracked; FastAPI shim). No `.proto` edits in M6. The existing `proto/vllm_grpc/v1/` schema is unchanged. |
| **II. Library Dependency, Not Fork** | **PASS** | M6 uses `vllm` as an ordinary dependency. No vLLM source code is copied or modified. Real engine launch reuses Phase 6.1's `enable_prompt_embeds=True` AsyncEngineArgs flag. AsyncLLM's lack of native per-request timing surface (Research R-3) is handled by adapter code in our gRPC frontend, not by patching vLLM. |
| **III. Phase Discipline** | **PASS** | M6 is a canonical milestone in `docs/PLAN.md` (Draft v7) with explicitly listed deliverables. The plan's scope matches PLAN.md M6 § exactly: 6-cell narrow slice, 3-cohort surface, single-model real-engine validation. Out-of-scope items (corpus diversity → M7; additional models → M8; h≠4096 → M8; M3/M4 channel-tuning real-engine validation → out of scope) are explicit in spec.md "Out of Scope" §. No M7/M8 capability leaks in. |
| **IV. CI is the Merge Gate** | **PASS** | All M6 code changes (harness modules under `tools/benchmark/`, frontend instrumentation under `packages/frontend/`, REST shim updates under `tools/benchmark/src/vllm_grpc_bench/rest_shim.py`, Modal app under `scripts/python/`) MUST pass `ruff check`, `ruff format --check`, `mypy --strict`, and `pytest` per the project's local-lint-chain feedback memory. New unit tests for the verdict classifier are mandatory (Research R-7). |
| **V. Honest Measurement** | **PASS** | M6 IS a benchmark milestone. Outputs land in `docs/benchmarks/`. SC-002 mandates terminal classification of all 6 cells (no selective omission). FR-014 mandates a verdict table for every cell including `cell_incomplete` cells. FR-020 explicitly preserves M1's bytes-axis findings without re-measurement (encoding is structural, not engine-dependent). The `engine_cost_drift_warning` flag (FR-014 sub-clause) surfaces cohort disagreement honestly rather than silently averaging it away. The classifier is deterministic — operator post-hoc re-classification is forbidden. |

**Result: 5/5 PASS. No violations. Complexity Tracking is empty.**

Re-check after Phase 1 design: see "Post-Design Constitution Check" at the end of this document.

## Project Structure

### Documentation (this feature)

```text
specs/020-m6-real-engine-mini-validation/
├── plan.md                     # This file (/speckit-plan output)
├── research.md                 # Phase 0 — research items + decisions (/speckit-plan output)
├── data-model.md               # Phase 1 — entity shapes (/speckit-plan output)
├── quickstart.md               # Phase 1 — operator playbook (/speckit-plan output)
├── contracts/
│   ├── cli.md                  # M6 CLI surface (smoke + full sweep) (/speckit-plan output)
│   ├── instrumentation.md      # Engine-cost wire format (gRPC trailing meta + REST JSON) (/speckit-plan output)
│   └── output.md               # Published artifact shapes (markdown verdict table + JSON delta from M5.2) (/speckit-plan output)
├── checklists/
│   └── requirements.md         # Spec quality checklist (existing, from /speckit-specify)
├── spec.md                     # Feature spec (existing, with 5 rounds of clarifications)
└── tasks.md                    # /speckit-tasks output (NOT created by /speckit-plan)
```

### Source Code (repository root — extending existing layout)

The M6 work integrates into the existing project layout; no new top-level packages or directories are introduced. New files are added inside existing modules following M5.2's conventions.

```text
tools/benchmark/src/vllm_grpc_bench/
├── m6_sweep.py                 # NEW — M6 sweep orchestrator (parallel to m5_2_sweep.py)
├── m6_supersede.py             # NEW — verdict classifier (parallel to m5_2_supersede.py)
├── m6_engine_cost.py           # NEW — engine_cost extraction (gRPC trailing meta parser + REST JSON field reader)
├── m6_smoke.py                 # NEW — smoke gate (2-cell × 3-cohort × n=10) (parallel pattern to existing smoke flows)
├── m6_seed.py                  # NEW — per-RPC deterministic seed mapping (FR-025)
├── __main__.py                 # MODIFY — add --m6 + --m6-smoke + --m6-modal-region + --m6-base-seed flags following m5_2 pattern
├── m5_2_sweep.py               # UNCHANGED (M6 reuses cell-iteration helpers from m5_1_sweep, exported by m5_2)
├── rest_cohort.py              # MODIFY — read engine_cost JSON fields from REST response payload
├── m5_1_grpc_cohort.py         # MODIFY — read engine_cost from gRPC trailing metadata
├── modal_endpoint.py           # UNCHANGED (Modal endpoint discovery shared with M5.x)
├── rtt_probe.py                # UNCHANGED (RTT probe shared with M5.x)
├── m5_2_events.py              # MODIFY — extend per-request event record with engine_cost fields
└── rest_shim.py                # MODIFY — emit engine_cost JSON fields in unary + streaming responses

packages/frontend/src/vllm_grpc_frontend/
├── chat.py                     # MODIFY — wrap engine.generate() with TTFT/TPOT timing; emit gRPC trailing metadata
├── completions.py              # MODIFY — wrap engine.generate() (embed path) with forward-pass timing; emit gRPC trailing metadata
└── main.py                     # UNCHANGED (Phase 6.1 already added enable_prompt_embeds=True)

scripts/python/
└── modal_bench_rest_grpc_server.py  # MODIFY — add --use-real-engine flag (or env var); when set, instantiate AsyncLLM(Qwen3-7B) instead of MockEngine; load engine once at startup (FR-024)

docs/benchmarks/
├── m5_2-transport-vs-tuning.json      # READ-ONLY input (classifier baseline — FR-014 hard precondition)
├── m6-real-engine-mini-validation.md  # NEW — published markdown report
└── m6-real-engine-mini-validation.json # NEW — published JSON companion (strict superset of M5.2 schema — FR-016)

CLAUDE.md                       # MODIFY — update SPECKIT plan reference between markers (Phase 1 step 3)
```

**Structure Decision**: M6 is an additive extension of the M5.2 harness, not a refactor. The M5.2 modules remain unchanged in their existing semantics; M6 adds 5 parallel modules (`m6_sweep`, `m6_supersede`, `m6_engine_cost`, `m6_smoke`, `m6_seed`) and modifies 7 shared modules (`__main__`, `rest_cohort`, `m5_1_grpc_cohort`, `m5_2_events`, `rest_shim`, gRPC frontend `chat.py` + `completions.py`, Modal app `modal_bench_rest_grpc_server.py`). This preserves M5.2's published verdict pipeline as the inheritance baseline and isolates M6's real-engine concerns in clearly named modules.

## Complexity Tracking

> Empty — Constitution Check passed 5/5 with no violations.

Per the project's `feedback_thorough_clarify_cycles` memory, the spec underwent 5 rounds of clarification (14 Q/A bullets) before this plan was written. The plan inherits those decisions verbatim; no new architectural complexity is introduced beyond what the spec already mandates.

---

## Phase 0: Outline & Research

See [`research.md`](./research.md) for the 8 research items and decisions.

**Output**: `research.md` with all NEEDS CLARIFICATION resolved (none in Technical Context — the 5-round clarification process settled them at spec time).

## Phase 1: Design & Contracts

See [`data-model.md`](./data-model.md), [`contracts/cli.md`](./contracts/cli.md), [`contracts/instrumentation.md`](./contracts/instrumentation.md), [`contracts/output.md`](./contracts/output.md), [`quickstart.md`](./quickstart.md).

Agent context update: the SPECKIT plan reference in `/Users/bsansom/projects/vllm-grpc/CLAUDE.md` between the `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers is updated as part of Phase 1 step 3 to point at this plan's path.

**Output**: `data-model.md`, `contracts/*.md`, `quickstart.md`, updated `CLAUDE.md`.

## Post-Design Constitution Check

Re-evaluated against the 5 principles after Phase 1 design artifacts were drafted:

| Principle | Status | Post-design notes |
|---|---|---|
| I. Proto-First | **PASS** | Confirmed by `contracts/instrumentation.md` — engine_cost on gRPC side uses trailing metadata only; no `.proto` edits in M6. The existing `chat.proto` / `completions.proto` schemas are unchanged. |
| II. Library Dependency, Not Fork | **PASS** | Confirmed by `data-model.md` — the engine instrumentation entity wraps `AsyncLLM.generate()` with our own timer; no vLLM source modification. |
| III. Phase Discipline | **PASS** | Confirmed by `contracts/cli.md` — the `--m6` flag namespace is parallel to `--m5_1` / `--m5_2`; no M7/M8 functionality (corpus diversity, additional models, h≠4096) leaks into M6 CLI. |
| IV. CI is the Merge Gate | **PASS** | `quickstart.md` operator playbook includes the local-lint-chain step before any push (`ruff check`, `ruff format --check`, `mypy --strict`, `pytest`) per the project memory. |
| V. Honest Measurement | **PASS** | `contracts/output.md` mandates that `cell_incomplete` cells appear in the verdict table (no silent omission), the `engine_cost_drift_warning` flag is surfaced per-cell (no silent averaging), and `m5_2_winner_deltas` are snapshotted into RunMeta (no post-hoc re-classification). |

**Result: 5/5 PASS post-design. No new complexity introduced.**
