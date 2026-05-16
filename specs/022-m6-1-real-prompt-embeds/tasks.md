---
description: "Task list for M6.1 — Real-Prompt-Embeds Engine Path"
---

# Tasks: M6.1 — Real-Prompt-Embeds Engine Path

**Input**: Design documents from `/specs/022-m6-1-real-prompt-embeds/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cli.md`, `contracts/instrumentation.md`, `contracts/output.md`, `quickstart.md`

**Tests**: INCLUDED — the plan's Constitution Check (Principle IV) and `contracts/output.md` (strict-superset validation) and `research.md` R-8 (deterministic classifier unit-testable on synthetic inputs) explicitly mandate pytest coverage for the verdict classifier, the torch-pin validation gate, the seq_len pinning, the new REST `input_kind`, the gRPC `torch.save` payload, the chat_stream control-drift check, and the strict-superset JSON compatibility. M6's per-milestone test convention (`tools/benchmark/tests/test_m6_*`) is preserved as `test_m6_1_*`.

**Organization**: Tasks are grouped by user story (US1 = "Supersedes M6" headline verdict table, US2 = Engine path differential section, US3 = smoke gate) so each story can be implemented and tested independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps task to a user story (US1, US2, US3); Setup / Foundational / Polish phases have no story label
- Include exact file paths in descriptions

## Path Conventions

- Harness: `tools/benchmark/src/vllm_grpc_bench/` (new modules: `m6_1_*.py`)
- Harness tests: `tools/benchmark/tests/test_m6_1_*.py`
- gRPC frontend: `packages/frontend/src/vllm_grpc_frontend/` — **UNCHANGED for M6.1** (the existing `_resolve_prompt_embeds_input` dispatch routes `torch.save` bytes to `decode_embeds` via the ZIP-magic prefix — see [`research.md` R-1](./research.md#r-1-frontend-dispatch-already-routes-torchsave-bytes-to-real-prompt-embeds))
- REST shim: `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` (extended with new `input_kind`)
- Bench client pyproject: `tools/benchmark/pyproject.toml` (extended with `torch==2.11.0` pin)
- Modal app: `scripts/python/modal_bench_rest_grpc_server.py` — **UNCHANGED for M6.1** (engine config reused from M6 per FR-007)
- Published artifacts: `docs/benchmarks/m6_1-real-prompt-embeds.{md,json}`
- M6 baseline (read-only input): `docs/benchmarks/m6-real-engine-mini-validation.json`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify preconditions are in place; pin client `torch` to the version vLLM 0.20.1 pulls transitively (FR-006).

- [X] T001 Verify M6 baseline file present and valid by reading `docs/benchmarks/m6-real-engine-mini-validation.json` and confirming `supersedes_m5_2_under_real_engine[]` contains rows for all 6 M6.1 cells (path ∈ {embed, chat_stream}, hidden_size=4096, concurrency ∈ {1, 4, 8}) AND `m6_meta` is present (carries `m5_2_winner_deltas`, `engine_version`, `cold_start_s`). If any cell entry is missing, abort M6.1 implementation and republish M6 first. (FR-008 / FR-009 hard precondition; [R-4](./research.md#r-4-m6-published-json-schema-for-m6_winner_deltas-lookup))
- [X] T002 [P] Confirm `vllm==0.20.1` and `torch==2.11.0` are the resolved versions in `uv.lock` and that vLLM's transitive `torch` requirement still pins to 2.11.0 (`awk '/^name = "torch"/,/^$/' uv.lock` should show `version = "2.11.0"`; `awk '/^name = "vllm"/,/^$/' uv.lock` should show `version = "0.20.1"`). No version bump required for M6.1; if the lockfile diverges, halt and reconcile. ([R-2](./research.md#r-2-torch-client-side-version-pin-policy))
- [X] T003 Add `torch==2.11.0` to the `[project.dependencies]` list in `tools/benchmark/pyproject.toml` (the bench client package) so the harness can import torch on the operator's client machine. Include a code comment explaining the pin policy (matches vLLM's transitive requirement per FR-006; future bumps must stay in sync with the project's pinned `vllm` version). Run `uv sync` after the edit and verify `python -c "import torch; print(torch.__version__)"` reports `2.11.0`.

**Checkpoint**: Setup complete. Foundational phase can begin.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared M6.1 plumbing — types, torch-pin validation, per-RPC seed mapping, seq_len pinning, M6 baseline loader, chat_stream control-drift check, CLI flag wiring. All 3 user stories depend on this phase.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. The torch-pin gate, the M6 baseline loader, the seed mapping, and the seq_len pin are shared across smoke + full sweep + verdict classification + differential computation.

### Data-model types (shared across all stories)

- [X] T004 [P] Define `M6_1Cell` (alias for `M6Cell`), `M6_1CohortKind` (alias for `M6CohortKind`), `M6_1RPCMeasurement`, `M6_1PerCohortAggregate`, `M6_1CellRecord` (with new `chat_stream_control_drift_warning` field), `EnginePathDifferentialRow`, `M6_1RunMeta` (with `M6_1_BASE_SEED`, `seq_len`, `engine_version`, `m6_baseline_engine_version`, `torch_version`, `m6_winner_deltas`, plus reused M6 fields), `M6_1SmokeOutcome`, `M6_1SmokeResult`, `SupersedesM6Row`, `M6_1Run`, `M6_1PerRequestEvent`, and `PromptEmbedsTensorPayload` as `@dataclass(frozen=True)` in `tools/benchmark/src/vllm_grpc_bench/m6_1_types.py` (NEW) per data-model.md shapes and validation rules. Re-export `VerdictClassification`, `EngineCostSpan`, and `EngineCostAggregate` from `m6_types.py` unchanged.

### Client-side torch pin validation (FR-006, R-2)

- [X] T005 [P] Implement `validate_torch_version()` in `tools/benchmark/src/vllm_grpc_bench/m6_1_torch_pin.py` (NEW) per `contracts/instrumentation.md` §3. The module MUST define `_EXPECTED_TORCH_VERSION: Final[str] = "2.11.0"`. The function MUST raise `SystemExit(2)` with a clear actionable stderr message naming both detected and expected versions if mismatched (or if `import torch` fails). Returns the detected version string on success.
- [X] T006 [P] Add pytest unit tests for `m6_1_torch_pin` in `tools/benchmark/tests/test_m6_1_torch_pin.py` (NEW): assert the constant matches the pin in `tools/benchmark/pyproject.toml` (cross-validates T003 / FR-006); use monkeypatch to simulate `torch.__version__ = "2.11.0"` (passes) and `"2.12.0"` (raises `SystemExit(2)`); use monkeypatch to simulate `ImportError` on `import torch` (raises `SystemExit(2)` with `pip install torch==2.11.0` message).

### Per-RPC seed + torch.Generator mapping (FR-019, FR-028, R-3)

- [X] T007 [P] Implement `compute_rpc_seed(rpc_index, base_seed=42) -> int` and `build_torch_generator_for_rpc(rpc_index, base_seed=42, device="cpu") -> torch.Generator` in `tools/benchmark/src/vllm_grpc_bench/m6_1_seed.py` (NEW). The seed function MUST return `base_seed + rpc_index` (matches M6's `m6_seed.py` convention; FR-019). The generator function MUST call `torch.Generator(device).manual_seed(base_seed + rpc_index)` so the tensor-values draw is bit-reproducible (FR-028). Both functions MUST be pure and cohort-independent.
- [X] T008 [P] Add pytest unit tests for `m6_1_seed` in `tools/benchmark/tests/test_m6_1_seed.py` (NEW): assert `compute_rpc_seed(0, 42) == 42`; assert two `torch.Generator` instances built with the same `rpc_index` produce identical `torch.randn(shape, dtype=torch.float16, generator=...)` outputs across calls (bit-reproducibility); assert different `rpc_index` produces different output.

### Seq_len pinning (FR-028, R-3)

- [X] T009 [P] Implement `pin_seq_len_at_sweep_start(model_identifier="Qwen/Qwen3-8B") -> int` in `tools/benchmark/src/vllm_grpc_bench/m6_1_seq_len.py` (NEW). The function MUST tokenise the canonical M6 text-digest format `"embeds:" + "0" * 16` against the loaded model's tokenizer (via `transformers.AutoTokenizer.from_pretrained(model_identifier)` with `add_special_tokens=False`) and return the resulting integer token count. Caches the tokenizer load (don't re-fetch from HuggingFace per call). Expected return value at the time of writing for Qwen/Qwen3-8B: ~5-8 (concrete value recorded in `M6_1RunMeta.seq_len`).
- [X] T010 [P] Add pytest unit test for `m6_1_seq_len` in `tools/benchmark/tests/test_m6_1_seq_len.py` (NEW): assert that the function returns a positive integer ≥ 1; use a stub/monkeypatched tokenizer that returns a known token list and assert the function returns its length. Skip the test in CI if `transformers` model download is not available; the real-tokenizer call is exercised at sweep start.

### M6 baseline file precondition (FR-008, FR-009, FR-013, R-4)

- [X] T011 Implement `load_and_validate_m6_baseline(path) -> tuple[dict[str, Optional[float]], dict[str, Optional[str]], str]` in `tools/benchmark/src/vllm_grpc_bench/m6_1_supersede.py` (NEW; signature plus the loader — the classifier proper comes in US1 T022). The function MUST: (a) open the file, (b) parse JSON, (c) assert `supersedes_m5_2_under_real_engine[]` contains rows for all 6 M6.1 cells, (d) for each cell, extract the M6 winner delta + direction per [R-4](./research.md#r-4-m6-published-json-schema-for-m6_winner_deltas-lookup) — returning `None` for cells whose M6 classification is `no_winner_at_n100`, `cell_incomplete`, OR `verdict_buried_by_engine` (FR-010 sub-clause), (e) extract `m6_meta.engine_version` (or `"unknown"` if absent), (f) return `(m6_winner_deltas, m6_winner_directions, m6_baseline_engine_version)`. Raise a typed `M6BaselineMissingCellError(cell)` if any cell row is missing.
- [X] T012 [P] Add pytest tests for the baseline precondition in `tools/benchmark/tests/test_m6_1_supersede.py` (NEW): construct synthetic M6 JSON missing one cell row, assert `M6BaselineMissingCellError` raised naming that cell; construct synthetic JSON with cell verdicts of each type (`verdict_survives`, `verdict_changed`, `verdict_buried_by_engine`, `no_winner_at_n100`, `cell_incomplete`) and assert the loader returns the correct `Optional[float]` per cell (None for the last three per FR-010 sub-clause); assert `m6_baseline_engine_version` is read correctly when present, defaults to `"unknown"` when absent.

### chat_stream control-drift check (FR-029, R-6)

- [X] T013 [P] Implement `check_chat_stream_control_drift(m6_1_cells, m6_baseline_cells) -> dict[tuple[str, int], bool]` in `tools/benchmark/src/vllm_grpc_bench/m6_1_drift_check.py` (NEW) per [research.md R-6](./research.md#r-6-chat_stream-control-drift-check-algorithm). For each chat_stream cell, the function MUST compare each cohort's M6.1 95% CI against M6's published 95% CI for the same (cell, cohort) and return `True` for that cell if at least one cohort's CIs do not overlap. Operates only on chat_stream cells; embed cells trivially return `False`.
- [X] T014 [P] Add pytest unit tests for `m6_1_drift_check` in `tools/benchmark/tests/test_m6_1_drift_check.py` (NEW): synthetic inputs with all-overlapping CIs assert all flags `False`; one-cohort non-overlap asserts that cell's flag `True` (other cells `False`); embed cells skipped (always `False` regardless of inputs).

### CLI flag wiring (FR-025, contracts/cli.md)

- [X] T015 Add `--m6_1` / `--m6_1-smoke` (mutually exclusive top-level flags) and the namespaced flags listed in `contracts/cli.md` (`--m6_1-modal-region`, `--m6_1-modal-token-env`, `--m6_1-modal-endpoint`, `--m6_1-skip-deploy`, `--m6_1-base-seed`, `--m6_1-model`, `--m6_1-events-sidecar-out`, `--m6_1-report-out`, `--m6_1-report-json-out`, `--m6_1-rtt-validity-ms`, `--m6_1-rtt-exercise-ms`, `--m6_1-shim-overhead-warn-pct`, `--m6_1-run-id`, `--m6_1-m6-baseline`) to `tools/benchmark/src/vllm_grpc_bench/__main__.py`, mirroring the existing `--m6` flag namespace. Wire both `--m6_1` and `--m6_1-smoke` to argparse mutual-exclusion against all earlier mode flags (`--m5_1`, `--m5_1-smoke`, `--m5_2`, `--m5_2-smoke`, `--m6`, `--m6-smoke`). Dispatch `--m6_1` to a new `run_m6_1_sweep(...)` entry point and `--m6_1-smoke` to `run_m6_1_smoke(...)` (implementations land in US1 T024 and US3 T033 respectively).
- [X] T016 [P] Add pytest test for the M6.1 CLI surface in `tools/benchmark/tests/test_m6_1_cli.py` (NEW): assert all M6.1 flags parse with documented defaults; assert `--m6_1` + `--m6_1-smoke` rejection; assert `--m6_1` + `--m6` rejection; assert `--m6_1` + `--m5_2` rejection; assert exit code mapping matches `contracts/cli.md` §"Exit codes" (specifically: code 1 from baseline-precondition failure, code 2 from torch-pin failure at startup, code 0 on success).

**Checkpoint**: Foundational ready. User story implementation can now begin.

---

## Phase 3: User Story 1 - "Supersedes M6 under enable_prompt_embeds" verdict table (Priority: P1) 🎯 MVP

**Goal**: Run the M6.1 sweep against Modal A10G eu-west-1 and produce a markdown + JSON report pair whose executive section contains a 6-row verdict table classifying each cell into one of the 5 canonical categories (`verdict_survives` / `verdict_changed` / `verdict_buried_by_engine` / `no_winner_at_n100` / `cell_incomplete`) against M6's published baseline.

**Independent Test**: Drive the M6.1 sweep against Modal eu-west-1 with the M6 baseline JSON present. Verify (1) the markdown report's executive section contains the verdict table with all 6 cells classified into exactly one canonical category, (2) the JSON companion is a strict superset of M6's schema, (3) cells whose M6 verdict was `verdict_buried_by_engine` / `no_winner_at_n100` / `cell_incomplete` classify as `no_winner_at_n100` in M6.1 regardless of CI overlap (FR-010 sub-clause), (4) the `chat_stream_control_drift_warning` flag surfaces on chat_stream cells with non-overlapping CIs.

### gRPC embed driver — torch.save bytes encoding (FR-002, FR-028, R-1)

- [X] T017 [P] [US1] Implement `_build_embed_grpc_request(seq_len, hidden_size, rpc_index, base_seed) -> completions_pb2.CompletionRequest` in `tools/benchmark/src/vllm_grpc_bench/m6_1_rpc_driver.py` (NEW) per `contracts/instrumentation.md` §1. Build a `[seq_len, hidden_size=4096] torch.float16` tensor via `m6_1_seed.build_torch_generator_for_rpc(rpc_index, base_seed)` + `torch.randn(...)`, then `torch.save` it into a `BytesIO` buffer and ship `buf.getvalue()` in `CompletionRequest.prompt_embeds`. Also re-export the chat_stream request builder `_build_chat_grpc_request(seed)` from `m6_rpc_driver` unchanged (FR-005 — chat_stream wire format identical to M6).
- [X] T018 [P] [US1] Add pytest test for the gRPC embed driver in `tools/benchmark/tests/test_m6_1_rpc_driver.py` (NEW): assert `_build_embed_grpc_request` produces a `CompletionRequest` whose `prompt_embeds` field starts with the ZIP magic `b"PK\x03\x04"`; round-trip the bytes through `vllm_grpc_frontend.completions_translate.decode_embeds` and assert the recovered tensor has the expected `shape == (seq_len, 4096)` and `dtype == torch.float16`; assert two builds with the same `rpc_index` produce bit-identical bytes (FR-028 / SC-006).

### REST shim — new input_kind="prompt_embedding_torch_b64" (FR-003, FR-004, R-1)

- [X] T019 [US1] Modify `tools/benchmark/src/vllm_grpc_bench/rest_shim.py`'s `/v1/embeddings` handler per `contracts/instrumentation.md` §2: (a) accept `input_kind ∈ {"prompt_embedding_b64", "prompt_embedding_torch_b64", "text"}` (extend the existing validation); (b) when `input_kind == "prompt_embedding_torch_b64"`, base64-decode `input`, call `vllm_grpc_frontend.completions_translate.decode_embeds(raw_bytes)` to obtain a `torch.Tensor`, and pass `{"prompt_embeds": tensor}` to `engine.generate(...)` (driving `enable_prompt_embeds=True`); (c) preserve the existing `prompt_embedding_b64` (raw float32 → text-digest hash) and `text` paths UNCHANGED per FR-004; (d) emit the existing `engine_cost.engine_forward_ms` JSON top-level field unchanged on the new path too. Return HTTP 422 with a clear error if `decode_embeds` raises (treats as cell_incomplete via FR-017 retry pathway).
- [X] T020 [US1] Modify `tools/benchmark/src/vllm_grpc_bench/rest_cohort.py`'s embed payload builder to emit `input_kind="prompt_embedding_torch_b64"` and base64-encoded `torch.save` bytes when invoked under the `--m6_1` dispatch path. The existing M6 dispatch path (called from `m6_rpc_driver`) keeps `input_kind="prompt_embedding_b64"` UNCHANGED per FR-004. Depends on T017 (uses the same tensor-build helper from `m6_1_rpc_driver`).
- [X] T021 [P] [US1] Add pytest test for the REST shim's new `input_kind` path in `tools/benchmark/tests/test_m6_1_rest_shim.py` (NEW): POST a `prompt_embedding_torch_b64` payload (built via `m6_1_rpc_driver`'s helpers), assert HTTP 200 and that the engine was called with `{"prompt_embeds": <Tensor>}` (use a fake engine that records its `generate(...)` call); assert `engine_cost.engine_forward_ms` is present in the response JSON; assert the existing `prompt_embedding_b64` path still routes to the text-digest hash (FR-004 regression guard); assert `prompt_embedding_torch_b64` with malformed base64 returns HTTP 400 and with malformed torch.save bytes returns HTTP 422.

### Verdict classifier (FR-010, R-4, R-8)

- [X] T022 [US1] Implement the full M6.1 verdict classifier in `tools/benchmark/src/vllm_grpc_bench/m6_1_supersede.py` (extends T011's loader) per [research.md R-8](./research.md#r-8-verdict-classifier-algorithm-m61). Pure function `classify_cell(cell_record, m6_winner_delta, m6_winner_direction, engine_cost_drift_warning) -> tuple[VerdictClassification, str]`. Algorithm: (1) if any cohort `n_successes < 80` → `cell_incomplete`; (2) compute classifier_metric per cohort (wall_clock_ms for embed, ttft_ms for chat_stream); (3) compute engine_cost_mean per cell as the **simple unweighted average of the three per-cohort means** (FR-022 — `(rest + default + tuned) / 3`); (4) compute the (rest_https_edge, tuned_grpc_multiplexed) cohort-pair CI overlap; (5) apply FR-010 discrimination rule with the FR-010 sub-clause that cells whose M6 verdict was `no_winner_at_n100`, `cell_incomplete`, OR `verdict_buried_by_engine` (i.e. `m6_winner_delta is None`) classify as `no_winner_at_n100` regardless of M6.1 CI overlap; (6) return the verdict and a human-readable reason string for the markdown report's `Notes` column.
- [X] T023 [US1] Add pytest tests for the verdict classifier in `tools/benchmark/tests/test_m6_1_supersede.py` (extends T012). Cover all 5 categories on synthetic inputs: (a) `verdict_survives` — M6.1 CIs non-overlapping in same direction as M6 winner; (b) `verdict_changed` — non-overlapping in opposite direction; (c) `verdict_buried_by_engine` — CIs overlap AND engine_cost_mean ≥ 5 × M6 winner delta; (d) `no_winner_at_n100` — CIs overlap AND engine_cost_mean < 5 × M6 winner delta; (e) `cell_incomplete` — any cohort `n_successes < 80`; (f) FR-010 sub-clause regression — M6 baseline was `verdict_buried_by_engine` on a cell, M6.1 CI is non-overlapping in the same direction, classifier MUST return `no_winner_at_n100` (NOT `verdict_survives`); (g) repeat (f) for `no_winner_at_n100` and `cell_incomplete` M6 verdicts; (h) FR-022 engine_cost_mean unweighted-average computation: cohort means (10, 20, 30) → cell mean exactly 20.0.

### Sweep orchestrator (FR-001, FR-015, FR-016, FR-017)

- [X] T024 [US1] Implement `run_m6_1_sweep(args)` in `tools/benchmark/src/vllm_grpc_bench/m6_1_sweep.py` (NEW). The orchestrator MUST: (a) call `m6_1_torch_pin.validate_torch_version()` first (FR-006 pre-RPC gate); (b) call `m6_1_supersede.load_and_validate_m6_baseline(args.m6_baseline)` (FR-009 precondition); (c) deploy the Modal app reusing M6's `M6_USE_REAL_ENGINE=true` + `M6_MODEL=Qwen/Qwen3-8B` env-var convention (FR-007 — engine config UNCHANGED from M6); (d) call `m6_1_seq_len.pin_seq_len_at_sweep_start(args.model)` after engine readiness (FR-028); (e) for each of the 6 cells: run warmup phase (10 RPCs/cohort via reused round-robin per c-batch sequencer from `m6_sweep`) then measurement phase (100 RPCs/cohort with retries up to 3 per FR-017); (f) per-RPC seeds via `m6_1_seed.compute_rpc_seed(global_rpc_index, args.base_seed)` (FR-019 — warmup excluded from index sequence); (g) emit progress line on stderr per (cell × cohort) pair per FR-023; (h) after sweep completion, call `m6_1_drift_check.check_chat_stream_control_drift(...)` to populate the chat_stream cell flags (FR-029); (i) compute per-cell verdicts via `m6_1_supersede.classify_cell(...)`; (j) hand off to `m6_1_reporter` (T026) to write the markdown + JSON outputs.
- [X] T025 [US1] Add pytest test for the sweep orchestrator wiring in `tools/benchmark/tests/test_m6_1_sweep.py` (NEW). Use a fake RPC driver that returns deterministic per-RPC results (no Modal connection); assert: (a) torch-pin gate runs FIRST and raises `SystemExit(2)` if `_EXPECTED_TORCH_VERSION` is monkey-patched to a mismatched value; (b) baseline-precondition gate runs SECOND and raises `M6BaselineMissingCellError` on synthetic 5-cell baseline JSON; (c) the FR-029 drift check runs AFTER sweep completion (not during); (d) warmup RPCs are excluded from the `rpc_index` counter (FR-019 — assert measurement RPC i's seed is `args.base_seed + i` regardless of warmup count); (e) `cell_incomplete` cells still produce a populated `M6_1CellRecord` (no silent skip).

### Reporter — markdown + JSON for US1 (FR-020, FR-021, FR-027, FR-030)

- [X] T026 [US1] Implement `write_m6_1_report(run: M6_1Run, md_path, json_path)` in `tools/benchmark/src/vllm_grpc_bench/m6_1_reporter.py` (NEW) per `contracts/output.md` §1 and §2. The markdown writer MUST: (a) emit the Executive Summary section naming model + region + GPU + pinned `torch_version` + pinned `seq_len` + engine_version + M6 baseline source (FR-020 / FR-027); (b) emit the "Supersedes M6 Under enable_prompt_embeds" verdict table with the 6 cell rows including the `Drift flags` column for `⚠ engine drift` (FR-022) and `⚠ chat_stream drift` (FR-029) markers; (c) emit the Engine Cost Per RPC table (M7 hand-off — reused from M6); (d) emit the Per-Cohort Detail tables; (e) emit the Smoke Result section if smoke ran in the same invocation; (f) emit the Methodology Notes section including the FR-030 engine_version comparison line (informational, non-blocking; flag if values differ or either is `"unknown"`); (g) emit the Operator Reproducibility section. The JSON writer MUST produce a strict superset of M6's schema per `contracts/output.md` §2 — populate `supersedes_m6_under_enable_prompt_embeds[]` (FR-020 / US1), `run_meta` with all M6.1-specific fields (FR-027), the back-reference `m6_meta` passthrough (FR-021), and all preserved M6-shape strict-superset fields (`cohorts`, `protocol_comparison_verdicts`, `engine_cost_baseline`, etc.).
- [X] T027 [US1] Add pytest tests for the markdown + JSON reporter in `tools/benchmark/tests/test_m6_1_reporter.py` (NEW): construct a synthetic 6-cell `M6_1Run` (mixing `verdict_survives`, `verdict_changed`, `verdict_buried_by_engine`, `no_winner_at_n100`, `cell_incomplete`, and one cell with `chat_stream_control_drift_warning=True`); assert the markdown contains the verdict table with all 6 cells, the correct `⚠` flags, and the methodology-section FR-030 engine_version comparison line; assert the JSON has top-level `supersedes_m6_under_enable_prompt_embeds[]` with 6 entries, `run_meta.seq_len` set, `run_meta.torch_version == "2.11.0"`, and `m6_meta` back-reference present.

**Checkpoint**: At this point, User Story 1 (the headline verdict table) should be fully functional. The operator can run `python -m vllm_grpc_bench --m6_1 --m6_1-modal-region=eu-west-1` and read the markdown report's "Supersedes M6" section. US2 (engine path differential) and US3 (smoke gate) are still missing.

---

## Phase 4: User Story 2 - Engine path differential section (Priority: P2)

**Goal**: Publish per-cell M6.1 − M6 numeric deltas (classifier metric per cohort + engine_cost_mean per cell) as a named "Engine path differential" section in both the markdown report and the JSON companion, with 95% CI half-widths. Every cell populates a row, even `cell_incomplete` cells (annotated with actual `n_successes`).

**Independent Test**: Read any cell's row in the published "Engine path differential" section and confirm the M6.1 − M6 deltas are present with units (ms) and 95% CI half-widths for both the per-cohort classifier metric (3 entries per cell) and the per-cell `engine_cost_mean` delta. For a `cell_incomplete` cell, confirm the row is still populated with the achieved `n_successes` per cohort per SC-007.

### Differential computation (FR-020, SC-007)

- [X] T028 [P] [US2] Implement `compute_engine_path_differential(m6_1_cell, m6_baseline_cell) -> EnginePathDifferentialRow` in `tools/benchmark/src/vllm_grpc_bench/m6_1_supersede.py` (extends T022's classifier module). For each cell, compute: (a) per-cohort `classifier_metric_delta_ms = m6_1_mean − m6_mean`; (b) per-cohort combined 95% CI half-width = `sqrt(m6_1_ci_half_width^2 + m6_ci_half_width^2)` (standard CI of difference for independent samples); (c) per-cell `engine_cost_mean_delta_ms` and combined CI half-width; (d) populate `per_cohort_n_successes` from the M6.1 cell record so cell_incomplete cells surface their actual `n_successes` (SC-007).
- [X] T029 [P] [US2] Add pytest tests for the differential computation in `tools/benchmark/tests/test_m6_1_supersede_differential.py` (NEW) (or extend `test_m6_1_supersede.py`): assert the delta sign is correct (M6.1 mean=20, M6 mean=10 → delta=+10); assert the combined CI half-width formula (M6.1 CI half-width=1.0, M6 CI half-width=2.0 → combined=√5≈2.236); assert that a `cell_incomplete` cell (one cohort `n_successes=60`) still produces a populated row with `per_cohort_n_successes` reflecting 60 for that cohort.

### Reporter — Engine path differential section (FR-020 / US2)

- [X] T030 [US2] Extend `tools/benchmark/src/vllm_grpc_bench/m6_1_reporter.py` (from T026) to emit the "Engine path differential (M6.1 − M6)" markdown section per `contracts/output.md` §1 — a 6-row table with the 3 per-cohort classifier-metric deltas (with CI half-widths), the per-cell engine_cost_mean delta (with CI half-width), and the per-cohort `n_successes` column (SC-007). Add the corresponding `engine_path_differential[]` top-level field to the JSON companion per `contracts/output.md` §2 — 6 entries, each with the full `EnginePathDifferentialRow` shape from data-model.md.
- [X] T031 [US2] Add pytest tests for the differential section in `tools/benchmark/tests/test_m6_1_reporter_differential.py` (NEW) (or extend `test_m6_1_reporter.py`): synthetic `M6_1Run` with 6 differential rows; assert markdown contains the section title, 6 cell rows, and the n_successes column for a `cell_incomplete` cell; assert JSON `engine_path_differential[]` has 6 entries with all required fields per data-model.md validation rules.

### Strict-superset JSON compatibility (FR-021, SC-005)

- [X] T032 [US2] Add a strict-superset compatibility test in `tools/benchmark/tests/test_m6_1_strict_superset.py` (NEW): construct a representative M6.1 JSON output via the reporter, then run it through the M6-aware loader code path (i.e., the parsing functions in `m6_supersede.py` that consume M6's published JSON shape) and assert no schema errors, no missing required fields, and that the new `engine_path_differential[]` and `run_meta.m6_winner_deltas` fields can be opt-in read by an M6-aware reader that knows about them. This is the SC-005 acceptance test.

**Checkpoint**: At this point, both User Stories 1 AND 2 should work. The operator gets the headline verdict table AND the engine-path differential decision aid in the same report.

---

## Phase 5: User Story 3 - Smoke gate (Priority: P3)

**Goal**: A fast (~5 min) operator-triggered smoke gate that catches `torch` import / version failures, M6 baseline JSON failures, REST shim wiring failures, and gRPC torch.save round-trip failures before the operator commits to a ~80-min full sweep. The smoke gate exercises 2 cells × 3 cohorts × n=10 (60 RPCs total) covering both an embed cell and a chat_stream cell.

**Independent Test**: Run `python -m vllm_grpc_bench --m6_1-smoke --m6_1-modal-region=eu-west-1` from a freshly-checked-out workspace with M6 baseline JSON present. Confirm: (1) exits within 5 minutes, (2) exit code `0` if all 6 (cell × cohort) pairs pass, (3) exit code `1` if any pair fails (with per-pair stderr summary), (4) exit code `2` if M6 baseline JSON pre-check fails OR torch version mismatch is detected before any RPC, (5) the smoke summary stderr includes the one-line note that the FR-029 chat_stream control-drift check is full-sweep-only.

### Smoke gate orchestrator (FR-012, FR-013)

- [X] T033 [P] [US3] Implement `run_m6_1_smoke(args)` in `tools/benchmark/src/vllm_grpc_bench/m6_1_smoke.py` (NEW). The function MUST: (a) call `m6_1_torch_pin.validate_torch_version()` first; (b) call `m6_1_supersede.load_and_validate_m6_baseline(args.m6_baseline)`; (c) deploy the Modal app reusing M6's engine config (FR-007); (d) exercise the 2 smoke cells `(embed × c=1)` and `(chat_stream × c=1)` × 3 cohorts × n=10 (60 RPCs total — FR-012); (e) emit one stderr summary line per (cell × cohort) pair (6 lines); (f) emit the one-line stderr note that the FR-029 chat_stream control-drift check is full-sweep-only and will run after the n=100 sweep completes (FR-012 mandate); (g) MUST NOT call `m6_1_drift_check.check_chat_stream_control_drift(...)` (smoke-only deferral per FR-012); (h) exit `0` if all 6 pairs pass, `1` if any RPC pair fails, `2` if pre-checks fail.
- [X] T034 [P] [US3] Add pytest tests for the smoke gate in `tools/benchmark/tests/test_m6_1_smoke.py` (NEW). Use a fake RPC driver: (a) all 6 pairs succeed → exit code `0`, 6 stderr summary lines, drift-check-deferral note printed; (b) one (cell × cohort) pair fails → exit code `1`; (c) torch version mismatched → exit code `2` BEFORE any deployment/RPC; (d) M6 baseline JSON missing → exit code `2` BEFORE any deployment/RPC; (e) explicit assertion that `m6_1_drift_check.check_chat_stream_control_drift` is NOT called during smoke (FR-012 mandate).

**Checkpoint**: All three user stories now independently functional. MVP (US1) ships first; US2 enriches the report with the differential section; US3 protects operator quality-of-life with the pre-flight smoke gate.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Local CI gate, documentation tie-ins, end-to-end validation.

- [X] T035 Run the local lint chain end-to-end before opening a PR per the project's `feedback_local_lint_chain` memory: `ruff check .` then `ruff format --check .` then `mypy --strict packages tools` then `pytest`. All four MUST pass with zero errors. If `mypy --strict` flags `torch.*` modules as untyped, ensure the existing `[[tool.mypy.overrides]]` block in `pyproject.toml` covering `torch.*` is preserved (it already exists per current pyproject.toml).
- [X] T036 [P] Run the quickstart smoke command end-to-end against Modal A10G eu-west-1 (`python -m vllm_grpc_bench --m6_1-smoke --m6_1-modal-region=eu-west-1`) and verify the actual stderr output matches the layout documented in `quickstart.md` Step 1. This is a manual operator validation step; if Modal credentials are not available, document the deferral in the PR description.
- [X] T037 [P] After the published M6.1 sweep lands, update `docs/PLAN.md`'s M6.1 section to link to the published `docs/benchmarks/m6_1-real-prompt-embeds.{md,json}` artifacts and mark the milestone status as "delivered". Update `ANALYSIS.md`'s M6 section to add an "M6.1 followup" footnote summarising the headline verdict counts (e.g. "3/6 cells verdict_survives, 2/6 verdict_changed, 1/6 cell_incomplete") and pointing readers at the published "Engine path differential" section as the methodology disclosure.
- [X] T038 [P] Update the REST contract documentation surface so both `input_kind` values are named and described per FR-004 (operator-facing REST documentation). Concretely: add (or extend) a module-level docstring on `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` (or the `_EmbedRequest` Pydantic model + the embed handler) that documents (a) `input_kind="prompt_embedding_b64"` — raw float32 bytes hashed to a text digest server-side; engine work is text-prompt unary completion; preserved for M5.x / M6 reproductions; (b) `input_kind="prompt_embedding_torch_b64"` — base64-encoded `torch.save(tensor)` bytes; `decode_embeds` deserialises and the engine consumes via `enable_prompt_embeds=True`; used by M6.1+ sweeps; (c) cross-reference to `docs/benchmarks/m6_1-real-prompt-embeds.md`'s "Engine path differential" section as the operator's decision aid for choosing between paths. Add a one-line note in `tools/benchmark/README.md` if it exists, pointing at the shim docstring as the canonical REST contract reference.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 + T002 can run in parallel; T003 depends on T002 (must confirm the lock-file pin first before adding the matching client-side dependency).
- **Foundational (Phase 2)**: Depends on Setup completion. Within Phase 2, T004 (types) blocks all other foundational tasks. T005/T006, T007/T008, T009/T010, T011/T012, T013/T014, T015/T016 can each run as a tightly-coupled pair (impl then test) once T004 is done.
- **User Stories (Phase 3+)**: All depend on Foundational completion.
  - US1 (P1, MVP) can start as soon as Foundational is done.
  - US2 (P2) depends on US1 because the differential section is rendered alongside the verdict table (single reporter, T026 → T030).
  - US3 (P3) is independent of US1 and US2 (the smoke gate only needs the Foundational primitives) and can run in parallel with US1/US2 after Foundational completes.
- **Polish (Phase 6)**: Depends on all three user stories being complete.

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational. No dependencies on other stories.
- **User Story 2 (P2)**: Depends on US1's reporter (T026) being in place — the differential section extends the same markdown + JSON writer. Cannot start before T026 lands.
- **User Story 3 (P3)**: Independent of US1 and US2. Smoke gate reuses Foundational primitives (torch pin, baseline loader, seed mapping) directly; it doesn't need the full sweep orchestrator or the reporter.

### Within Each User Story

- Tests are written alongside implementation (NOT TDD-first); each impl task pairs with a test task that asserts the contract documented in `contracts/`. Verify tests pass before moving on.
- Implementation order within US1: T017/T018 (gRPC driver) + T019/T020/T021 (REST shim & cohort) can run in parallel → T022/T023 (classifier) → T024/T025 (sweep orchestrator) → T026/T027 (reporter).

### Parallel Opportunities

- **Setup**: T001 + T002 parallel; T003 sequential after T002.
- **Foundational**: After T004, the 6 foundational impl/test pairs (T005-T006, T007-T008, T009-T010, T011-T012, T013-T014, T015-T016) can largely proceed in parallel (different files); T015 (CLI wiring) has a soft dependency on T011 (baseline loader) because the CLI references it.
- **US1**: T017+T018 (gRPC driver) parallel with T019+T020+T021 (REST shim+cohort); both feed into T022 (classifier); T024 (sweep orchestrator) composes everything; T026 (reporter) is final.
- **US2**: T028+T029 (differential compute) parallel with each other; both block T030 (reporter extension); T032 (strict-superset test) parallel with T031.
- **US3**: T033+T034 (smoke + tests) parallel pair, completely independent of US1/US2 after Foundational.
- **Polish**: T036 + T037 + T038 parallel; T035 (lint chain) is the final blocker before PR.

---

## Parallel Example: User Story 1

```bash
# After Foundational completes, the US1 implementation can fan out:

# gRPC + REST surfaces in parallel:
Task: "Implement gRPC torch.save embed driver in m6_1_rpc_driver.py" (T017)
Task: "Add prompt_embedding_torch_b64 path to rest_shim.py" (T019)
Task: "Add pytest test for gRPC embed driver round-trip" (T018)

# Then classifier and tests:
Task: "Implement full M6.1 verdict classifier in m6_1_supersede.py" (T022)
Task: "Add pytest test covering all 5 verdict categories + FR-010 sub-clause" (T023)

# Then sweep orchestrator:
Task: "Implement run_m6_1_sweep in m6_1_sweep.py" (T024)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (verify M6 baseline, pin torch).
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories).
3. Complete Phase 3: User Story 1.
4. **STOP and VALIDATE**: Run `--m6_1-smoke` against Modal (smoke gate primitives are mostly in Foundational); if green, run a single small `--m6_1` sweep and read the verdict table.
5. Ship the MVP: M6.1 publishes "Supersedes M6" as the headline; differential and dedicated smoke gate added in next increments.

### Incremental Delivery

1. Foundation ready → Run smoke against M6 baseline + torch pin pre-checks pass.
2. Add US1 → Publish first M6.1 report with verdict table only → Deploy/Demo (MVP).
3. Add US2 → Extend report with engine-path differential section → Re-publish.
4. Add US3 → Standalone smoke gate (independent of US1's full-sweep harness) → Operator workflow improvement.
5. Polish → Lint chain + PLAN.md + ANALYSIS.md updates → PR ready.

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together (Foundational has the highest fan-out).
2. Once Foundational is done:
   - Developer A: US1 (T017-T027) — owns gRPC driver, REST shim, classifier, sweep, reporter.
   - Developer B: US3 (T033-T034) — owns smoke gate in parallel with US1.
   - Developer A then picks up US2 (T028-T032) once US1's reporter lands.
3. Polish work (T035-T037) at the end, on whichever developer is available.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks.
- [Story] label maps task to specific user story for traceability.
- Each user story should be independently completable and testable.
- M6.1 is an **additive** milestone — no M6 modules are modified except as explicitly listed in plan.md's "Project Structure" §; M6 reproductions MUST continue to work bit-exactly after this milestone lands (FR-004 / regression protection).
- The frontend is UNCHANGED for M6.1; if any task surfaces a need to edit `packages/frontend/src/vllm_grpc_frontend/completions.py`, escalate — the prefix-aware dispatch at line 49 is the load-bearing invariant that lets M6.1 ship without proto changes (Constitution Principle I).
- Commit after each logical group (e.g., after T010 the foundational types + tests + torch pin + seed + seq_len are all in place; commit as a single logical change).
- Stop at any checkpoint to validate story independence — US1 alone, US1+US2, and US3 alone all need to be functional.
- Avoid: vague tasks, same-file conflicts inside a phase (especially T026 → T030 → T031 all touching `m6_1_reporter.py`), cross-story dependencies that break independence.
