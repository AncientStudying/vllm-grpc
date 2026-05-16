# Implementation Plan: M6.1 — Real-Prompt-Embeds Engine Path

**Branch**: `022-m6-1-real-prompt-embeds` | **Date**: 2026-05-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/022-m6-1-real-prompt-embeds/spec.md`

## Summary

Change **exactly one variable** in M6's published 6-cell × 3-cohort matrix: the
embed cohort engine code path. Under M6, both the gRPC and REST embed cohorts
ship opaque float32 bytes that the frontend hashes to a short text digest
before the engine call — engine work is text-prompt unary completion on both
transports. M6.1 routes both transports through vLLM's
`enable_prompt_embeds=True` engine path with real prompt-embedding tensors so
the published "Engine path differential" section quantifies the engine code
path cost on identical hardware, model, engine, classifier, and matrix shape
as M6. M6.1's headline deliverable is a "Supersedes M6 under
enable_prompt_embeds" per-cell verdict table (same 5-category set as M6 — see
[spec.md FR-010](./spec.md)) and the named "Engine path differential" section
(US2 — see [spec.md FR-020](./spec.md)).

**Technical approach.** Reuse the entire M6 harness wholesale — the cell
× cohort × concurrency orchestration, the round-robin per c-batch sequencer,
the per-RPC deterministic seed mapping, the smoke gate, the engine-cost
instrumentation contract (gRPC trailing metadata + REST JSON), the verdict
classifier algorithm (just retargeted to M6 baseline winner deltas instead of
M5.2), and the reporter. Add 6 parallel `m6_1_*` modules (mirroring M6's
naming convention) and modify 3 shared surfaces:
1. The gRPC embed driver now emits `torch.save(tensor)` bytes (instead of raw
   float32 bytes) so the frontend's existing prefix-aware
   `_resolve_prompt_embeds_input` routes the request through `decode_embeds`
   → `{"prompt_embeds": tensor}` → `enable_prompt_embeds=True`. No frontend
   change required (the dispatch is already prefix-driven by the
   `PK\x03\x04` ZIP magic — see Assumption ¶1 in spec.md).
2. The REST shim recognises a new `input_kind="prompt_embedding_torch_b64"`
   that base64-decodes the payload, runs it through the same `decode_embeds`
   path, and ships `{"prompt_embeds": tensor}` directly to
   `engine.generate(...)`. The existing `input_kind="prompt_embedding_b64"`
   (M5.x / M6 raw float32 + text-digest hash) is preserved verbatim per
   FR-004 (both `input_kind` values coexist indefinitely — no deprecation,
   no migration mandate).
3. The bench client (`tools/benchmark/pyproject.toml`) gains a `torch`
   dependency pinned to `==2.11.0` (the version the project's pinned
   `vllm==0.20.1` requires transitively); the embed driver validates
   `torch.__version__` at driver-start before the first measurement RPC and
   exits with a clear error if the operator's environment is mismatched
   (FR-006).

The classifier is the same 5-category function as M6, retargeted: it reads
**M6 winner deltas** from `docs/benchmarks/m6-real-engine-mini-validation.json`
instead of M5.2's. Cells where M6 itself had no usable winner delta
(`no_winner_at_n100`, `cell_incomplete`, OR `verdict_buried_by_engine`)
classify as `no_winner_at_n100` regardless of M6.1 CI overlap (FR-010).

The published JSON is a strict superset of M6's schema (FR-021): existing
M6-aware consumers read M6.1's JSON unmodified, except to opt-in read the
additive `engine_path_differential` section and `run_meta.m6_winner_deltas`.

## Technical Context

**Language/Version**: Python 3.12 (project standard; matches M5.x / M6 harness, frontend, proxy, and Modal app)
**Primary Dependencies**: `vllm==0.20.1` (real engine — `AsyncLLM(Qwen/Qwen3-8B, dtype=fp16, enable_prompt_embeds=True, max_model_len=2048, gpu_memory_utilization=0.92)` — UNCHANGED from M6), `torch==2.11.0` (NEW client-side requirement for the M6.1 embed driver's `torch.save(tensor)` call; pinned to vllm's transitive requirement per FR-006), `grpcio` + `grpcio-tools` (gRPC transport — UNCHANGED from M6), `FastAPI` + `uvicorn` (REST shim — extended with new `input_kind` per FR-003), `modal` (deployment — UNCHANGED from M6), the existing `vllm_grpc_bench` harness package (extended with `m6_1_*` modules), the existing `vllm_grpc_frontend` package (UNCHANGED — the prefix-aware dispatch in `_resolve_prompt_embeds_input` already routes `torch.save` bytes to `decode_embeds`).
**Storage**: Outputs written to `docs/benchmarks/m6_1-real-prompt-embeds.{md,json}` (FR-026). Inputs read from `docs/benchmarks/m6-real-engine-mini-validation.json` (M6 baseline — FR-008/FR-009 hard precondition). Per-RPC events JSONL sidecar at a path the operator passes via `--m6_1-events-sidecar-out` (mirrors M5.2 / M6 sidecar convention).
**Testing**: `pytest` + `pytest-asyncio` (project convention). Unit tests for the M6.1 verdict classifier on synthetic inputs (deterministic — FR-010); unit test for the torch-pin validation gate at driver-start (FR-006); unit test for the REST shim's new `input_kind="prompt_embedding_torch_b64"` path (FR-003); integration test for the gRPC embed driver's `torch.save(tensor)` round-trip through `decode_embeds`; harness-level test that the M6 baseline JSON pre-check rejects missing / malformed / cell-incomplete inputs (FR-009/FR-013); harness-level test that the FR-029 chat_stream control-drift check fires only on full sweep and not at smoke (FR-012); golden-file test that the JSON is a strict superset of M6's schema (FR-021).
**Target Platform**: Modal A10G GPU instance in `eu-west-1` (default per FR-025 and reused from M6). Driven from operator workstation (M2 Pro MBP per M6 convention); operator pre-configures `modal token new`. Client-side now requires `torch==2.11.0` (FR-006 — quickstart names this prerequisite explicitly).
**Project Type**: Sibling library + benchmark harness — Python monorepo with `proxy/`, `frontend/`, `client/`, `proto/`, `tools/benchmark/`, `scripts/`, `docs/benchmarks/`. M6.1 is a benchmark-research milestone (additive to M6), not a library / CLI / web-service in the conventional product sense.
**Performance Goals**:
- SC-001: Full sweep ≤ 90 min wall-clock on Modal A10G (matches M6's budget; the operative change removes the server-side text-digest hashing step and runs the prompt-embeds forward instead — comparable engine work at h=4096).
- SC-002: Smoke gate ≤ 5 min wall-clock.
- Per-cohort 95% CI half-widths must be narrow enough that the classifier resolves the majority of cells into a non-`no_winner_at_n100` bucket on a representative run (no separate SC; implicit from sweep structure).

**Constraints**:
- A10G GPU memory: Qwen3-8B fp16 ≈ 16 GB + KV-cache headroom for c=8 chat_stream within 24 GB total. The real prompt-embeds engine path uses extra activation memory not present under M6's text-digest path; if any (cell × cohort) surfaces OOM, the affected RPCs are retried per FR-017 and the cell classifies `cell_incomplete` rather than the harness aborting. The engine config (`max_model_len=2048`, `gpu_memory_utilization=0.92`) is reused unchanged from M6 (the same headroom budget is preserved).
- FR-021: JSON companion is a strict superset of M6's schema; existing M6-aware consumers MUST continue to work unmodified against M6.1's JSON.
- FR-014: One engine instance for the entire sweep; no reload per cell or per path. Engine loads in the Modal app's startup hook before the gRPC + REST servers begin accepting traffic (reused from M6).
- FR-010: Verdict classifier is deterministic given M6.1 numeric inputs and the M6 published winner deltas — no operator post-hoc re-classification permitted.
- FR-006: Bench client `torch` version pinned to `2.11.0`; driver-start validates `torch.__version__` before the first RPC and exits non-zero if mismatched.
- FR-028: Prompt-embeds tensor shape is `[seq_len, hidden_size=4096]` and dtype `fp16`. `seq_len` is fixed across all RPCs / cells / cohorts, pinned at sweep start to the M6 text-digest tokenised length (`embed_<hex>` against Qwen3-8B's tokenizer — see Research R-3); per-RPC tensor *values* drawn deterministically from `torch.Generator(seed=M6_1_BASE_SEED + rpc_index)`.

**Scale/Scope**:
- 6 cells × 3 cohorts × 100 measurement RPCs = 1,800 measurement RPCs per full sweep (matches M6).
- + 6 cells × 3 cohorts × 10 warmup RPCs = 180 warmup RPCs.
- + 2 smoke cells × 3 cohorts × 10 RPCs = 60 smoke RPCs.
- Total ≈ 2,040 RPCs per "smoke + full sweep" sequence on Modal A10G (matches M6).
- Per-RPC payload: at h=4096 and `seq_len ≈ 8` (the pinned M6 text-digest tokenised length under Qwen3-8B's tokenizer — see Research R-3), `torch.save` bytes of a `[8, 4096] fp16` tensor ≈ 64 KiB (8 × 4096 × 2 bytes + torch pickle metadata). Under base64 wrapping for REST that's ≈ 88 KiB on-wire — well under the gRPC `MAX_MSG_16MIB` channel cap.
- Generation length: chat_stream `max_tokens=50` per RPC (FR-005 / M6 convention — UNCHANGED); embed `max_tokens=10` (M6 convention — UNCHANGED).
- Engine cost: under `enable_prompt_embeds=True`, the embed path runs the prompt-embeds forward (a few tens of ms at h=4096, seq_len ≈ 8) instead of the text-tokenise + forward path (~tens of ms also). The M6.1 − M6 differential is the deliverable; absolute magnitudes are reported per-cell.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against the 5 principles in `.specify/memory/constitution.md` (v1.0.0):

| Principle | Status | Notes |
|---|---|---|
| **I. Proto-First** | **PASS** | M6.1 makes no `.proto` edits. The existing `proto/vllm_grpc/v1/completions.proto` already carries the `prompt_embeds` field as `bytes`; M6.1 changes only the encoding shipped in that field (raw float32 → `torch.save`-pickled bytes). The frontend's existing `_resolve_prompt_embeds_input` dispatch in `packages/frontend/src/vllm_grpc_frontend/completions.py:49` already distinguishes the two encodings by ZIP magic prefix and routes accordingly — no schema or stub regeneration is required. REST is not proto-tracked; the new `input_kind="prompt_embedding_torch_b64"` is a string discriminator in the FastAPI shim, not a wire-format change. |
| **II. Library Dependency, Not Fork** | **PASS** | M6.1 uses `vllm==0.20.1` as an ordinary dependency. No vLLM source code is copied or modified. The real prompt-embeds engine path is vLLM's `AsyncEngineArgs.enable_prompt_embeds=True` flag — already exercised by M6's frontend launch and reused unchanged. `torch==2.11.0` is added as a client-side requirement to the bench client package; it's pinned to the version vLLM itself pulls transitively (Research R-2) so client-serialized `torch.save` bytes are wire-compatible with server-side `torch.load`/`decode_embeds`. |
| **III. Phase Discipline** | **PASS** | M6.1 is a canonical milestone in `docs/PLAN.md` (Draft v8 or later) listed as a follow-on to M6. The plan's scope matches PLAN.md M6.1 § exactly: same 6-cell × 3-cohort × n=100 matrix, same Qwen3-8B model, same A10G hardware, same engine config — **exactly one variable change** (embed cohort engine code path). Out-of-scope items (corpus diversity → M7; additional models → M8; h≠4096 → M8; M3/M4 channel-tuning re-validation → deferred per spec Out-of-Scope §) are explicit. No M7/M8 capability leaks in. The new REST `input_kind="prompt_embedding_torch_b64"` is added because M6.1 needs it to drive the engine path under measurement; the existing `prompt_embedding_b64` is preserved unchanged per FR-004 so M5.x / M6 reproducibility holds. |
| **IV. CI is the Merge Gate** | **PASS** | All M6.1 code changes (new harness modules under `tools/benchmark/`, modified REST shim under `tools/benchmark/src/vllm_grpc_bench/rest_shim.py`, modified bench client pyproject under `tools/benchmark/pyproject.toml`) MUST pass `ruff check`, `ruff format --check`, `mypy --strict`, and `pytest` per the project's local-lint-chain feedback memory before push. New unit tests for the M6.1 verdict classifier, the torch-pin validation gate, and the REST shim's new `input_kind` path are mandatory. The torch-pin gate (FR-006) MUST exit non-zero with a clear error before any RPC if the operator's `torch.__version__` mismatches — turning a silent `decode_embeds` failure into an actionable startup error. |
| **V. Honest Measurement** | **PASS** | M6.1 IS a benchmark milestone. Outputs land in `docs/benchmarks/`. SC-003 mandates terminal classification of all 6 cells (no selective omission); SC-007 mandates that even `cell_incomplete` cells populate the "Engine path differential" section's row. FR-029 mandates an automated chat_stream control-drift check (CI-overlap against M6's published chat_stream CIs) so the operator sees whether infrastructure noise contaminated the embed-cell verdicts; the resulting `chat_stream_control_drift_warning` flag is diagnostic, not blocking — verdicts are still published per FR-029. FR-022's `engine_cost_drift_warning` rule (>10% cross-cohort engine_cost disagreement) is preserved from M6 unchanged. FR-030 surfaces the M6 baseline's recorded `engine_version` vs M6.1's pinned `engine_version` as a methodology note — non-blocking so M6.1 can run against the existing legacy M6 baseline (which recorded `engine_version=unknown` because M6's version-reader helper landed post-sweep); the report flags the comparison as informational if the values differ or either is `unknown`. |

**Result: 5/5 PASS. No violations. Complexity Tracking is empty.**

Re-check after Phase 1 design: see "Post-Design Constitution Check" at the end of this document.

## Project Structure

### Documentation (this feature)

```text
specs/022-m6-1-real-prompt-embeds/
├── plan.md                     # This file (/speckit-plan output)
├── research.md                 # Phase 0 — research items + decisions (/speckit-plan output)
├── data-model.md               # Phase 1 — entity shapes (/speckit-plan output)
├── quickstart.md               # Phase 1 — operator playbook (/speckit-plan output)
├── contracts/
│   ├── cli.md                  # M6.1 CLI surface (smoke + full sweep) (/speckit-plan output)
│   ├── instrumentation.md      # Prompt-embeds wire format (gRPC torch.save bytes + REST prompt_embedding_torch_b64) (/speckit-plan output)
│   └── output.md               # Published artifact shapes (verdict table + engine path differential + JSON strict-superset of M6) (/speckit-plan output)
├── spec.md                     # Feature spec (existing, with 2 rounds of clarifications — 10 Q/A bullets)
└── tasks.md                    # /speckit-tasks output (NOT created by /speckit-plan)
```

### Source Code (repository root — extending existing layout)

M6.1 is an additive extension of the M6 harness, not a refactor. The M6 modules
remain unchanged in their existing semantics; M6.1 adds 6 parallel `m6_1_*`
modules and modifies 3 shared surfaces (bench-client pyproject, REST shim,
embed driver build helpers — the gRPC embed payload encoding moves from
`numpy.tobytes()` to `torch.save(io.BytesIO(...))`).

```text
tools/benchmark/src/vllm_grpc_bench/
├── m6_1_types.py               # NEW — M6.1 dataclasses + constants (M6_1Cell alias for M6Cell, M6_1RunMeta, EnginePathDifferential, M6_1Run; M6_1_BASE_SEED default; canonical prompt-embeds tensor shape + dtype constants)
├── m6_1_sweep.py               # NEW — M6.1 sweep orchestrator (parallel to m6_sweep.py; reuses the per-cell warmup + round-robin per c-batch sequencer from m6_sweep but builds embed-cohort requests via m6_1_rpc_driver)
├── m6_1_rpc_driver.py          # NEW — M6.1 embed driver: builds torch tensors with shape [seq_len, 4096] fp16 via torch.Generator(seed=M6_1_BASE_SEED+rpc_index), ships torch.save bytes (gRPC) or base64-wrapped torch.save bytes (REST); validates torch.__version__ at driver-start (FR-006); reuses chat_stream request builders from m6_rpc_driver unchanged
├── m6_1_supersede.py           # NEW — M6.1 verdict classifier (parallel to m6_supersede.py): reads M6 winner deltas from docs/benchmarks/m6-real-engine-mini-validation.json, same 5-category algorithm, plus the FR-010 sub-clause that cells whose M6 verdict was no_winner_at_n100 / cell_incomplete / verdict_buried_by_engine classify as no_winner_at_n100 regardless of M6.1 CI overlap
├── m6_1_smoke.py               # NEW — M6.1 smoke gate (2 cells × 3 cohorts × n=10 — parallel pattern to m6_smoke.py); skips FR-029 chat_stream control-drift check (FR-012)
├── m6_1_seed.py                # NEW — per-RPC deterministic seed mapping + per-RPC torch.Generator (FR-019/FR-028); M6_1_BASE_SEED default 42
├── m6_1_reporter.py            # NEW — M6.1 markdown + JSON writers (verdict table "Supersedes M6 under enable_prompt_embeds", "Engine path differential" section, M6-strict-superset JSON shape, chat_stream_control_drift_warning surfacing, engine_version note per FR-030)
├── m6_1_seq_len.py             # NEW — pin seq_len at sweep start: tokenise the M6 text-digest format embed_<hex> against the loaded model's Qwen3-8B tokenizer; record the resulting integer in RunMeta (FR-028)
├── m6_1_drift_check.py         # NEW — chat_stream control-drift CI-overlap check against M6's published per-cell/per-cohort CIs (FR-029); runs only on full sweep, not smoke (FR-012)
├── m6_1_torch_pin.py           # NEW — read the expected torch version pin from the bench-client package's metadata (or a constant matching FR-006); validate torch.__version__ at driver-start; raise an actionable error if mismatched
├── __main__.py                 # MODIFY — add --m6_1 + --m6_1-smoke + --m6_1-modal-region + --m6_1-base-seed + --m6_1-report-out + --m6_1-report-json-out + --m6_1-m6-baseline + --m6_1-events-sidecar-out flags following the m6 pattern; mutual-exclusion with --m6, --m6-smoke, --m5_2, etc.
├── rest_shim.py                # MODIFY — recognise input_kind="prompt_embedding_torch_b64" alongside the existing prompt_embedding_b64; base64-decode then call decode_embeds; pass {"prompt_embeds": tensor} to engine.generate directly (driving enable_prompt_embeds=True). Existing prompt_embedding_b64 + text paths UNCHANGED per FR-004. engine_cost JSON emission contract from M6 reused unchanged.
├── rest_cohort.py              # MODIFY — embed cohort's REST payload builder now emits input_kind="prompt_embedding_torch_b64" with base64-encoded torch.save bytes (under the --m6_1 dispatch path only; the existing m6 path keeps input_kind="prompt_embedding_b64" for FR-004 compatibility)
├── m6_rpc_driver.py            # UNCHANGED for m6 dispatch path. M6.1 uses m6_1_rpc_driver instead.
├── m6_engine_cost.py           # UNCHANGED — gRPC trailing metadata + REST JSON engine_cost parsers reused verbatim (FR-018)
├── m6_sweep.py                 # UNCHANGED — sequencer reused via composition by m6_1_sweep
├── m6_supersede.py             # UNCHANGED — M6 classifier reused as the algorithmic template; m6_1_supersede is a parallel module retargeted at M6 baselines + the FR-010 sub-clause for verdict_buried_by_engine cells
├── m6_types.py                 # UNCHANGED — m6_1_types re-exports the canonical M6Cell / M6CohortKind / VerdictClassification literals + EngineCostSpan
├── m5_2_events.py              # UNCHANGED — per-RPC event record shape reused (engine_cost trio already present per M6)
└── modal_endpoint.py           # UNCHANGED — Modal endpoint discovery shared with M5.x / M6 / M6.1

tools/benchmark/
└── pyproject.toml              # MODIFY — add torch==2.11.0 to dependencies (matches the version vllm==0.20.1 pulls transitively; FR-006). Document the pin policy in a code comment so future bumps stay aligned with the project's vllm pin.

packages/frontend/src/vllm_grpc_frontend/
├── completions.py              # UNCHANGED — _resolve_prompt_embeds_input already dispatches torch.save bytes (ZIP magic PK\x03\x04) to decode_embeds and falls back to text-digest hash on non-matching bytes. M6.1's gRPC embed cohort relies on this existing dispatch.
└── main.py                     # UNCHANGED — AsyncEngineArgs(enable_prompt_embeds=True) already set per M6

scripts/python/
└── modal_bench_rest_grpc_server.py  # UNCHANGED — the same Modal app definition that M6 uses, since the engine config (Qwen3-8B fp16, enable_prompt_embeds=True, max_model_len=2048, gpu_memory_utilization=0.92) is reused unchanged per FR-007. M6.1 doesn't need its own --m6_1-* env var because the engine launch is identical to M6's; the harness's --m6_1 dispatch is purely a client-side concern.

docs/benchmarks/
├── m6-real-engine-mini-validation.json   # READ-ONLY input (classifier baseline + engine_version baseline — FR-008/FR-009/FR-030 hard precondition)
├── m6_1-real-prompt-embeds.md            # NEW — published markdown report (FR-026)
└── m6_1-real-prompt-embeds.json          # NEW — published JSON companion (strict superset of M6 schema — FR-021)

CLAUDE.md                       # MODIFY — update SPECKIT plan reference between markers (Phase 1 step 3)
```

**Structure Decision**: M6.1 is an additive extension of the M6 harness, not a refactor. The M6 modules remain unchanged in their existing semantics; M6.1 adds 10 parallel modules (`m6_1_types`, `m6_1_sweep`, `m6_1_rpc_driver`, `m6_1_supersede`, `m6_1_smoke`, `m6_1_seed`, `m6_1_reporter`, `m6_1_seq_len`, `m6_1_drift_check`, `m6_1_torch_pin`) and modifies 4 shared surfaces (`__main__`, `rest_shim`, `rest_cohort`, `tools/benchmark/pyproject.toml`). The gRPC frontend is **unchanged** — the existing prefix-aware dispatch in `_resolve_prompt_embeds_input` already routes M6.1's `torch.save` bytes to `decode_embeds` and falls back to the M5.x / M6 text-digest hash for raw float32 bytes. This preserves M6's published verdict pipeline as the inheritance baseline and isolates M6.1's real-engine-path concerns in clearly named modules.

## Complexity Tracking

> Empty — Constitution Check passed 5/5 with no violations.

Per the project's `feedback_thorough_clarify_cycles` memory, the spec underwent
2 rounds of clarification (10 Q/A bullets total) before this plan was written.
The plan inherits those decisions verbatim; no new architectural complexity is
introduced beyond what the spec already mandates. The single new dependency
(`torch==2.11.0` on the bench client) is pinned to the version vLLM itself
pulls transitively, so the client-side `torch.save` bytes are guaranteed to
deserialise on the server-side `torch.load` path (FR-006).

---

## Phase 0: Outline & Research

See [`research.md`](./research.md) for the 9 research items and decisions.

**Output**: `research.md` with all NEEDS CLARIFICATION resolved (none in
Technical Context — the 2-round spec clarification process settled them at
spec time).

## Phase 1: Design & Contracts

See [`data-model.md`](./data-model.md), [`contracts/cli.md`](./contracts/cli.md), [`contracts/instrumentation.md`](./contracts/instrumentation.md), [`contracts/output.md`](./contracts/output.md), [`quickstart.md`](./quickstart.md).

Agent context update: the SPECKIT plan reference in `/Users/bsansom/projects/vllm-grpc/CLAUDE.md` between the `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers is updated as part of Phase 1 step 3 to point at this plan's path.

**Output**: `data-model.md`, `contracts/*.md`, `quickstart.md`, updated `CLAUDE.md`.

## Post-Design Constitution Check

Re-evaluated against the 5 principles after Phase 1 design artifacts were drafted:

| Principle | Status | Post-design notes |
|---|---|---|
| I. Proto-First | **PASS** | Confirmed by `contracts/instrumentation.md` — no `.proto` edits in M6.1. The `prompt_embeds` field is already `bytes` in `proto/vllm_grpc/v1/completions.proto`; M6.1 changes only the byte encoding shipped in it. The frontend's existing prefix-aware dispatch routes the new encoding without any schema change. |
| II. Library Dependency, Not Fork | **PASS** | Confirmed by `data-model.md` — M6.1 uses vLLM's `enable_prompt_embeds=True` engine path as an ordinary library feature. The new client-side `torch==2.11.0` pin (Research R-2) is the version vLLM itself pulls transitively, so there's no version-fork risk. No vLLM source modification. |
| III. Phase Discipline | **PASS** | Confirmed by `contracts/cli.md` — the `--m6_1` flag namespace is parallel to `--m6` / `--m5_2`; no M7/M8 functionality (corpus diversity, additional models, h≠4096) leaks into M6.1 CLI. The two REST `input_kind` values (`prompt_embedding_b64` from M5.x/M6 and `prompt_embedding_torch_b64` from M6.1) coexist indefinitely per FR-004 — no deprecation, no migration mandate. |
| IV. CI is the Merge Gate | **PASS** | `quickstart.md` operator playbook includes the local-lint-chain step before any push (`ruff check`, `ruff format --check`, `mypy --strict`, `pytest`) per the project memory. The new `m6_1_torch_pin` module is unit-tested for both the success and failure paths so the FR-006 validation gate is regression-protected. |
| V. Honest Measurement | **PASS** | `contracts/output.md` mandates that `cell_incomplete` cells appear in both the verdict table AND the "Engine path differential" section (SC-007 — no silent omission), the `engine_cost_drift_warning` and `chat_stream_control_drift_warning` flags are surfaced per-cell (no silent averaging), and `m6_winner_deltas` are snapshotted into RunMeta (FR-008 — no post-hoc re-classification). The engine_version comparison note (FR-030) is published as informational metadata so operators can judge differential trust. The verdict_buried_by_engine → no_winner_at_n100 sub-clause (FR-010) prevents M6.1 from smuggling a verdict claim into cells M6 itself refused to verdict on. |

**Result: 5/5 PASS post-design. No new complexity introduced.**
