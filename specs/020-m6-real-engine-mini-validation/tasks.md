---
description: "Task list for M6 — Real-Engine Mini-Validation"
---

# Tasks: M6 — Real-Engine Mini-Validation

**Input**: Design documents from `/specs/020-m6-real-engine-mini-validation/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cli.md`, `contracts/instrumentation.md`, `contracts/output.md`, `quickstart.md`

**Tests**: INCLUDED — the plan's Constitution Check (Principle IV) and `contracts/output.md` (strict-superset validation) and `research.md` R-7 (deterministic classifier unit-testable on synthetic inputs) explicitly mandate pytest coverage for the classifier, the round-robin sequencer, the seed mapping, and the engine-cost wire-format contract. M5.x's per-milestone test convention (`tools/benchmark/tests/test_m5_2_*`) is preserved as `test_m6_*`.

**Organization**: Tasks are grouped by user story (US1 = headline verdict table, US2 = engine-cost baseline hand-off to M7, US3 = smoke gate) so each story can be implemented and tested independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps task to a user story (US1, US2, US3); Setup / Foundational / Polish phases have no story label
- Include exact file paths in descriptions

## Path Conventions

- Harness: `tools/benchmark/src/vllm_grpc_bench/` (new modules: `m6_*.py`)
- Harness tests: `tools/benchmark/tests/test_m6_*.py`
- gRPC frontend: `packages/frontend/src/vllm_grpc_frontend/`
- Frontend tests: `packages/frontend/tests/`
- Modal app: `scripts/python/modal_bench_rest_grpc_server.py`
- Published artifacts: `docs/benchmarks/m6-real-engine-mini-validation.{md,json}`
- M5.2 baseline (read-only input): `docs/benchmarks/m5_2-transport-vs-tuning.json`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify the existing M5.2 harness is the right launch point; no new top-level packages or dependencies.

- [X] T001 Verify M5.2 baseline file present and valid by reading `docs/benchmarks/m5_2-transport-vs-tuning.json` and confirming `protocol_comparison_verdicts[]` contains rows for all 6 M6 cells (path ∈ {embed, chat_stream}, hidden_size=4096, concurrency ∈ {1, 4, 8}). If any cell entry is missing, abort M6 implementation and fix M5.2 first. (FR-014 baseline precondition; R-5)
- [X] T002 [P] Confirm `vllm`, `grpcio`, `grpcio-tools`, `FastAPI`, `uvicorn`, `modal`, `pytest`, `pytest-asyncio` are pinned in `pyproject.toml` / `uv.lock` at versions matching plan.md Technical Context; no version bump required for M6.
- [X] T003 [P] Add the M6 cell-iteration helper constants to `tools/benchmark/src/vllm_grpc_bench/m6_types.py` (NEW FILE): `M6_CELLS` tuple of 6 `(path, hidden_size=4096, concurrency)` triples in iteration order per data-model.md `M6Cell.Identity`; `M6_COHORTS` tuple `("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed")`; `M6_SMOKE_CELLS` tuple of 2 (`embed × c=1`, `chat_stream × c=1`).

**Checkpoint**: Setup complete. Foundational phase can begin.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared real-engine plumbing — engine-cost emission on both transports, parser, Modal app real-engine launch, sweep-loop infrastructure, CLI flag wiring. All 3 user stories depend on this phase.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. The real engine, the engine_cost wire formats, and the cohort readers are shared across smoke + full sweep + verdict classification.

### Data-model types (shared across all stories)

- [X] T004 [P] Define `M6Cell`, `M6CohortKind`, `VerdictClassification`, `M6RPCMeasurement`, `EngineCostSpan`, `M6PerCohortAggregate`, `EngineCostAggregate`, `M6CellRecord`, `M6RunMeta`, `M6SmokeOutcome`, `M6SmokeResult`, `M6Run`, `SupersedesM5_2Row`, `M6PerRequestEvent` as `@dataclass(frozen=True)` in `tools/benchmark/src/vllm_grpc_bench/m6_types.py` per data-model.md shapes and validation rules.

### Server-side engine instrumentation (FR-008, R-1, R-2)

- [X] T005 [P] Add per-RPC engine-cost timing wrapper around `AsyncLLM.generate()` for embed path in `packages/frontend/src/vllm_grpc_frontend/completions.py`: time `perf_counter()` start before generate call and end after drain; emit `engine-forward-ms` via `context.set_trailing_metadata((("engine-forward-ms", f"{ms:.3f}"),))` per contracts/instrumentation.md §1. Preserve existing response shape and proto (no `.proto` edits — Constitution Principle I).
- [X] T006 [P] Add per-RPC engine-cost timing wrapper around `AsyncLLM.generate()` for chat_stream path in `packages/frontend/src/vllm_grpc_frontend/chat.py`: capture `first_token_at` on first non-empty output chunk, `last_token_at` and `token_count` continuously; on stream completion compute `engine_ttft_ms` and `engine_tpot_ms` and emit both keys via `context.set_trailing_metadata(...)` per contracts/instrumentation.md §1.
- [X] T007 [US1] [US2] Add pytest unit test for embed timing wrapper trailing-metadata emission in `packages/frontend/tests/test_chat_servicer.py` (extend existing file) / new `packages/frontend/tests/test_engine_cost_metadata.py` — invoke servicer against a fake engine, assert `engine-forward-ms` is present in trailing metadata and parses as float; for chat_stream assert both `engine-ttft-ms` and `engine-tpot-ms` are present on stream completion.

### REST shim engine_cost (FR-008, R-4)

- [X] T008 Emit `engine_cost: {engine_forward_ms: ...}` at top level of `/v1/embeddings` JSON response payload in `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` (unary path) per contracts/instrumentation.md §2. Read the float value from the gRPC trailing-metadata `engine-forward-ms` returned by the upstream gRPC frontend.
- [X] T009 Emit `engine_cost: {engine_ttft_ms: ..., engine_tpot_ms: ...}` on the terminal SSE event of `/v1/chat/completions?stream=true` in `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` (streaming path) per contracts/instrumentation.md §2. The engine_cost field is added to the event with `finish_reason` set, immediately before `data: [DONE]`. Read floats from upstream gRPC trailing metadata.
- [X] T010 [P] Add pytest test for REST shim engine_cost emission in `tools/benchmark/tests/test_m6_rest_shim_engine_cost.py` (NEW): assert `/v1/embeddings` response has top-level `engine_cost.engine_forward_ms`; assert final SSE event from `/v1/chat/completions?stream=true` carries `engine_cost.engine_ttft_ms` and `engine_cost.engine_tpot_ms`.

### Engine-cost harness-side parser (R-2, R-4)

- [X] T011 [P] Implement `parse_grpc_trailing_metadata(metadata, path) -> Optional[EngineCostSpan]` and `parse_rest_response(response_json, path) -> Optional[EngineCostSpan]` in `tools/benchmark/src/vllm_grpc_bench/m6_engine_cost.py` (NEW) per contracts/instrumentation.md §3. Return None on missing keys or unparseable values (callers treat as instrumentation gap).
- [X] T012 [P] Implement `compute_drift_warning(per_cohort_engine_cost_mean_ms) -> bool` (pairwise >10% disagreement test) in `tools/benchmark/src/vllm_grpc_bench/m6_engine_cost.py` per contracts/instrumentation.md §4. Skip pairs where `min(a, b) <= 0`.
- [X] T013 [P] Add pytest unit tests for both parsers and the drift function in `tools/benchmark/tests/test_m6_engine_cost.py` (NEW): cover happy paths for embed + chat_stream on both transports, missing-key handling, and drift-warning thresholds (10.0% exact, 10.1% triggers, degenerate zero values skipped).

### Cohort readers (consume engine_cost; FR-008, R-2, R-4)

- [X] T014 Modify `tools/benchmark/src/vllm_grpc_bench/m5_1_grpc_cohort.py` to read `call.trailing_metadata()` after `await response_with_call()` and pass the metadata to `m6_engine_cost.parse_grpc_trailing_metadata()`. Surface the resulting `EngineCostSpan` on each per-RPC measurement record. Preserve existing M5.x semantics when `engine_cost` is absent (M5.x callers still work).
- [X] T015 Modify `tools/benchmark/src/vllm_grpc_bench/rest_cohort.py` to parse the top-level `engine_cost` JSON field on unary responses and the terminal SSE event's payload on streaming responses, via `m6_engine_cost.parse_rest_response()`. Surface the resulting `EngineCostSpan` on each per-RPC measurement record; preserve M5.x semantics when absent.

### Events sidecar extension (data-model.md `M6PerRequestEvent`)

- [X] T016 Modify `tools/benchmark/src/vllm_grpc_bench/m5_2_events.py` to add the M6-specific event fields (`rpc_phase`, `rpc_index`, `seed`, `engine_forward_ms`, `engine_ttft_ms`, `engine_tpot_ms`, `success`, `failure_reason`, `retry_count`) to the per-request event record. Existing M5.2-shape readers MUST keep working (additive only; FR-016 strict superset).
- [X] T017 [P] Add pytest test for the extended event record in `tools/benchmark/tests/test_m6_events_sidecar.py` (NEW): assert warmup records have `rpc_index is None` and `seed is None` (FR-021/FR-025 validation rule); assert measurement records have both set; assert engine_cost trio is path-discriminated (embed sets `engine_forward_ms` only; chat_stream sets `engine_ttft_ms` + `engine_tpot_ms`).

### Per-RPC sampling-seed mapping (FR-025, R-7 step input)

- [X] T018 [P] Implement `compute_rpc_seed(rpc_index, m6_base_seed=42) -> int` and `build_global_rpc_index_iterator()` in `tools/benchmark/src/vllm_grpc_bench/m6_seed.py` (NEW). The seed function MUST return `m6_base_seed + rpc_index`. The iterator MUST count measurement RPCs across the whole sweep (warmup excluded) and MUST produce the same `rpc_index → seed` for the i-th RPC across all 3 cohorts within a cell (FR-025).
- [X] T019 [P] Add pytest test for the seed mapping in `tools/benchmark/tests/test_m6_seed.py` (NEW): assert `compute_rpc_seed(0, 42) == 42`; assert warmup RPCs do not advance the rpc_index counter; assert seed is cohort-independent (same i-th measurement RPC produces same seed across all 3 cohorts within a cell).

### Modal app real-engine launch (FR-003, FR-024, R-10)

- [X] T020 Modify `scripts/python/modal_bench_rest_grpc_server.py` to honour `M6_USE_REAL_ENGINE` and `M6_MODEL` env vars: when `M6_USE_REAL_ENGINE=true`, instantiate `AsyncLLM.from_engine_args(AsyncEngineArgs(model=M6_MODEL, dtype="float16", enable_prompt_embeds=True))`; otherwise keep the existing MockEngine path. Engine loads ONCE at startup, before gRPC and REST servers begin accepting traffic (FR-024).
- [X] T021 Add a `_smoke_check_engine(engine)` step in `scripts/python/modal_bench_rest_grpc_server.py` that runs a single throwaway forward pass after `AsyncLLM` instantiation; on failure surface a clear OOM/load error (NOT a silent worker-pod kill) per Edge case "GPU memory exceeds A10G's 24 GB" and R-3 / R-10.

### M5.2 baseline file precondition (FR-014, R-5)

- [X] T022 [P] Implement `load_and_validate_m5_2_baseline(path)` in `tools/benchmark/src/vllm_grpc_bench/m6_supersede.py` (NEW; signature only — full classifier comes in US1) that: (a) opens the file, (b) parses JSON, (c) asserts `protocol_comparison_verdicts[]` contains rows for all 6 M6 cells via the R-6 cohort-name mapping, (d) raises a typed exception `M5_2BaselineMissingCellError(cell)` naming the failing cell. Used by both smoke and full sweep launches (FR-014 sub-clause "M5.2 baseline file precondition").
- [X] T023 [P] Add pytest test for the baseline precondition in `tools/benchmark/tests/test_m6_supersede.py` (NEW): construct synthetic M5.2 JSON missing one cell row, assert `M5_2BaselineMissingCellError` is raised naming that cell; assert valid 6-cell JSON loads cleanly.

### CLI flag wiring (FR-011, FR-017; contracts/cli.md)

- [X] T024 Add `--m6` / `--m6-smoke` (mutually exclusive top-level flags) and the namespaced flags listed in `contracts/cli.md` (`--m6-modal-region`, `--m6-modal-token-env`, `--m6-modal-endpoint`, `--m6-skip-deploy`, `--m6-base-seed`, `--m6-model`, `--m6-events-sidecar-out`, `--m6-report-out`, `--m6-report-json-out`, `--m6-rtt-validity-ms`, `--m6-rtt-exercise-ms`, `--m6-shim-overhead-warn-pct`, `--m6-run-id`, `--m6-m5-2-baseline`) to `tools/benchmark/src/vllm_grpc_bench/__main__.py`, mirroring the existing `--m5_2` flag namespace. Wire both `--m6` and `--m6-smoke` to argparse mutual-exclusion against all M5.x mode flags.
- [X] T025 [P] Add pytest test for the M6 CLI surface in `tools/benchmark/tests/test_m6_cli.py` (NEW) (parallel to `test_m5_2_cli.py`): assert all M6 flags parse with documented defaults; assert `--m6` + `--m6-smoke` rejection; assert `--m6` + `--m5_2` rejection; assert exit code mapping matches `contracts/cli.md` §"Exit codes".

**Checkpoint**: Foundation ready — engine-cost wire format published on both transports, parser consumes both, cohort readers integrated, Modal app launches real engine, CLI flags plumbed, seed mapping deterministic, M5.2 baseline precondition enforced. User story implementation can now begin.

---

## Phase 3: User Story 1 — Per-cell survival verdict (Priority: P1) 🎯 MVP

**Goal**: Produce the "Supersedes M5.2 under real engine" verdict table — one row per cell, classifying each into exactly one of `verdict_survives` / `verdict_changed` / `verdict_buried_by_engine` / `no_winner_at_n100` / `cell_incomplete`. Drivable from a single `python -m vllm_grpc_bench --m6` invocation; emits both markdown + JSON companion at `docs/benchmarks/m6-real-engine-mini-validation.{md,json}`.

**Independent Test**: Drive the M6 full sweep against Modal `eu-west-1` with Qwen3-7B on A10G. Confirm: (a) run completes within 90 min (SC-001); (b) the produced markdown's executive section contains a 6-row verdict table where each cell receives exactly one of the 5 terminal classifications (SC-002); (c) the JSON companion is consumable by the existing `m5_2_supersede.py` classifier unmodified (FR-016, SC-007). Acceptance scenarios from spec.md US1 1–3.

### Sweep orchestration (FR-021, FR-022, FR-023, FR-024)

- [ ] T026 [US1] Implement the per-cell sweep loop in `tools/benchmark/src/vllm_grpc_bench/m6_sweep.py` (NEW) following R-8 / R-9: for each of the 6 cells iterate (1) warmup phase — 10 RPCs per cohort in round-robin per c-batch (ceil(10/c) rounds) with silent retries until 10 successes per cohort (FR-021/FR-023); (2) measurement phase — 100 RPCs per cohort in round-robin per c-batch (100/c rounds, with c=8 truncation rule per R-9) with per-RPC retry up to 3 attempts (FR-023). Use `m6_seed.compute_rpc_seed()` (T018) for per-RPC `SamplingParams.seed`. For chat_stream RPCs, set `SamplingParams.max_tokens=50` (FR-005) on every RPC (warmup + measurement); embed RPCs are unary and do not carry a `max_tokens` parameter.
- [ ] T027 [US1] Implement per-cell `M6CellRecord` aggregation in `tools/benchmark/src/vllm_grpc_bench/m6_sweep.py`: aggregate per-cohort `M6PerCohortAggregate` (mean + 95% CI half-width per FR-009 using the existing `metrics.ci.compute_ci_half_width` helper); attach `n_successes`, `failure_count`, classifier_metric mean & CI per cohort; mark `cell_incomplete` when any cohort has < 80 successes after retries (FR-023).
- [ ] T028 [US1] Implement progress output (FR-026) in `tools/benchmark/src/vllm_grpc_bench/m6_sweep.py`: emit startup banner to stderr; one progress line per (cell × cohort) pair in form `[i/18] <cell.path> × c=<c> / <cohort> — <succ>/100 succ — <wall_ms> ms — ETA <minutes>m`; emit completion banner naming the report path; reserve stdout for the final report path (so harness composes with shell pipes).
- [ ] T029 [US1] Add pytest test for the round-robin per c-batch sequencer in `tools/benchmark/tests/test_m6_sweep.py` (NEW): mock the cohort executors and assert the call-order at c=1, c=4, c=8 matches R-8 / R-9 (12 rounds at c=8 + the truncation round); assert warmup follows the same rotation per FR-022; assert each cohort accumulates exactly n=100 measurement RPCs at every c (FR-004); assert seeds match `m6_base_seed + rpc_index` and are identical across cohorts for the same rpc_index (FR-025); assert that every chat_stream RPC's `SamplingParams.max_tokens == 50` (FR-005) and embed RPCs carry no `max_tokens` field.
- [ ] T030 [US1] Add pytest test for per-RPC retry + `cell_incomplete` marking in `tools/benchmark/tests/test_m6_sweep.py`: inject synthetic failures into a cohort such that one cohort lands at n_successes=79 after 3 retries; assert the cell is marked `cell_incomplete` (FR-023); inject 81 successes and assert the cell is NOT marked `cell_incomplete`.

### Verdict classifier (FR-014, R-6, R-7)

- [ ] T031 [US1] Implement the deterministic classifier in `tools/benchmark/src/vllm_grpc_bench/m6_supersede.py` per R-7 pseudocode: ordered steps (cell_incomplete check first, then classifier_metric per path, then engine_cost_mean, then drift flag, then M5.2 winner-delta lookup with the R-6 cohort-name mapping, then FR-014 discrimination rule). Pure function `classify_cell(cell, per_cohort_aggregates, m5_2_baseline) -> M6CellRecord`. The CI-overlap test uses 95% CI half-widths from `M6PerCohortAggregate.classifier_metric_ci_half_width_ms`.
- [ ] T032 [US1] Implement the M5.2 cohort-name mapping (R-6) in `tools/benchmark/src/vllm_grpc_bench/m6_supersede.py`: `map_m6_grpc_cohort_to_m5_2_lookup(concurrency) -> "tuned_grpc" if c == 1 else "tuned_grpc_multiplexed"`; consumed by the M5.2 baseline row lookup.
- [ ] T033 [US1] Snapshot the per-cell M5.2 winner deltas the classifier consumed into `M6RunMeta.m5_2_winner_deltas` (FR-018) — keyed `"{path}_c{c}_h{hidden_size}"`, value `|delta_median_ms|` or `None` when M5.2 verdict was `no_winner`. Returned alongside the classifier output for embedding in the JSON companion.
- [ ] T034 [US1] Add pytest unit tests for the classifier in `tools/benchmark/tests/test_m6_supersede.py` covering all 5 FR-014 branches: (a) `verdict_survives` — non-overlapping CIs same direction; (b) `verdict_changed` — non-overlapping CIs opposite direction; (c) `verdict_buried_by_engine` — overlapping CIs AND engine_cost ≥ 5× M5.2 winner delta; (d) `no_winner_at_n100` — overlapping CIs AND not buried; (e) `cell_incomplete` — n_successes < 80; plus the R-6 cohort-name mapping for c=1 vs c≥2; plus the FR-014 "M5.2 verdict was no_winner" sub-case (classifier must produce `no_winner_at_n100` not survives/changed).
- [ ] T035 [US1] [P] Add pytest test for classifier determinism in `tools/benchmark/tests/test_m6_supersede.py`: invoke `classify_cell(...)` twice with identical inputs, assert byte-identical `M6CellRecord` returned (FR-014 "deterministic; operator post-hoc re-classification not permitted").

### RTT probe + cold_start_s + RunMeta (FR-010, FR-018, FR-019)

- [ ] T036 [US1] [P] Wire the existing `rtt_probe.py` (M5.x shared) into the M6 sweep entry-point to produce one `RTTRecord` per cohort before the sweep (FR-010); embed the result in `M6Run.rtt_distribution`.
- [ ] T037 [US1] Capture `cold_start_s` as a single scalar per sweep (FR-019/FR-024) in `tools/benchmark/src/vllm_grpc_bench/m6_sweep.py`: measure wall-clock from Modal function deploy until the engine's first successful forward pass (engine-readiness probe per R-10's `_smoke_check_engine` exit); embed into `M6RunMeta.cold_start_s`.
- [ ] T038 [US1] Populate `M6RunMeta` (FR-018) in `tools/benchmark/src/vllm_grpc_bench/m6_sweep.py` with `git_sha` (from `git rev-parse HEAD` at launch), `hostname`, `modal_function_id`, `gpu_type="A10G"`, `modal_region` (from `--m6-modal-region`), `model_identifier` (from `--m6-model`), `engine_version` (from `vllm.__version__`), `cold_start_s` (T037), `m5_2_winner_deltas` (T033), `m6_base_seed` (from `--m6-base-seed`).

### Markdown reporter — verdict table + executive section (FR-013, FR-014, FR-015, FR-020)

- [ ] T039 [US1] Implement the M6 markdown reporter in `tools/benchmark/src/vllm_grpc_bench/m6_reporter.py` (NEW) generating sections in order per contracts/output.md §1: title block, Executive Summary (FR-015: inference engine + model + hidden_size + GPU + Modal region + M6_BASE_SEED + M5.2 baseline source + bytes-axis preservation note per FR-020), Supersedes M5.2 Under Real Engine verdict table (FR-014; one row per cell with cell-row markers per contracts/output.md §"Cell-row markers"), Per-Cohort Detail tables, Methodology Notes, Operator Reproducibility section. Writes to `docs/benchmarks/m6-real-engine-mini-validation.md` (overridable via `--m6-report-out`).
- [ ] T040 [US1] [P] Add pytest test for the markdown reporter executive section in `tools/benchmark/tests/test_m6_reporter.py` (NEW): assert FR-015 strings (inference engine, model, hidden_size, GPU, Modal region) appear within the first 1500 characters of the report (SC-005 first-screenful test); assert the bytes-axis preservation note (FR-020) is present.
- [ ] T041 [US1] [P] Add pytest test for the verdict-table renderer in `tools/benchmark/tests/test_m6_reporter.py`: feed a synthetic `M6Run` with one cell of each of the 5 terminal classifications; assert the rendered markdown table contains exactly 6 rows, the correct classification per row, the correct cell-row markers (`⚠ engine drift` when `engine_cost_drift_warning=True`, `cell_incomplete` as the Classification value not folded into a verdict bucket per FR-023), and the M5.2 winner-direction footnote on `verdict_changed` rows per contracts/output.md.

### JSON companion writer — strict superset of M5.2 (FR-013, FR-016)

- [ ] T042 [US1] Implement the M6 JSON companion writer in `tools/benchmark/src/vllm_grpc_bench/m6_reporter.py` generating the shape in contracts/output.md §2: M5.2-strict-superset fields (`schema_version="m6.v1"`, `run_id`, `cohorts[]`, `protocol_comparison_verdicts[]` populated from the M6 classifier, `transport_only_verdicts=[]`, etc.) plus M6-specific additions (`supersedes_m5_2_under_real_engine[]`, `engine_cost_baseline[]`, `m6_meta`). Writes to `docs/benchmarks/m6-real-engine-mini-validation.json` (overridable via `--m6-report-json-out`).
- [ ] T043 [US1] Add the M5.2 strict-superset compatibility pytest test in `tools/benchmark/tests/test_m6_reporter.py` per contracts/output.md §"Strict-superset compatibility test": construct a synthetic `M6Run`, serialise via the M6 reporter, then deserialise via `m5_2_supersede.py`'s expected types and assert no shape drift (FR-016/SC-007).

### M6 sweep entry-point + CLI dispatch

- [ ] T044 [US1] Wire `--m6` in `tools/benchmark/src/vllm_grpc_bench/__main__.py` to: (1) call `m6_supersede.load_and_validate_m5_2_baseline(path)` (T022) — abort with exit code 1 on precondition fail; (2) deploy the Modal app with `M6_USE_REAL_ENGINE=true` and `M6_MODEL=<--m6-model>` env vars; (3) run RTT probe (T036); (4) run `m6_sweep.run_sweep(...)` (T026–T028); (5) classify each cell (T031); (6) write markdown + JSON outputs (T039, T042); (7) print final report path to stdout; (8) emit completion banner to stderr (T028). Exit codes per contracts/cli.md §"Exit codes" — 0 / 1 / 2 / 3.

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently. The MVP (verdict table) is achievable by running `python -m vllm_grpc_bench --m6 --m6-modal-region=eu-west-1` against a real Modal deploy.

---

## Phase 4: User Story 2 — Engine-cost baseline hand-off to M7 (Priority: P2)

**Goal**: Publish the per-cell engine-cost-per-RPC metric as a separate, named field (with 95% CI half-widths) — distinct from the cohort comparison columns — so M7's prompt-length-scaling work can interpret deltas against a known real-engine cost floor instead of MockEngine assumptions. Surface the `engine_cost_drift_warning` flag (FR-014 sub-clause) when per-cohort engine_cost values disagree by >10%.

**Independent Test**: Read any cell's row in the published report and confirm the engine-cost-per-RPC metric is present as a named field (with units), distinct from the cohort comparison columns, with a 95% CI half-width attached. For embed cells: `engine_forward_ms`. For chat_stream cells: both `engine_ttft_ms` and `engine_tpot_ms`. (SC-003, SC-006; spec.md US2 acceptance scenarios 1–2.)

### Engine-cost baseline aggregation (FR-008, SC-006)

- [ ] T045 [US2] [P] Implement `aggregate_engine_cost_per_cell(per_rpc_measurements) -> EngineCostAggregate` in `tools/benchmark/src/vllm_grpc_bench/m6_engine_cost.py`: mean + 95% CI half-width per path-discriminated field (`engine_forward_*` for embed; `engine_ttft_*` + `engine_tpot_*` for chat_stream). Reuses the existing `metrics.ci.compute_ci_half_width` helper.
- [ ] T046 [US2] Compute the per-cell cohort-averaged `engine_cost_mean` (FR-014 classifier input) and per-cohort `engine_cost_mean` map in `tools/benchmark/src/vllm_grpc_bench/m6_supersede.py`, alongside `engine_cost_drift_warning` via `compute_drift_warning()` (T012); attach to `M6CellRecord` per data-model.md.

### Markdown — Engine Cost Per RPC table + drift footnotes (FR-014 sub-clause, contracts/output.md §1)

- [ ] T047 [US2] Add the "Engine Cost Per RPC" section to the M6 markdown reporter in `tools/benchmark/src/vllm_grpc_bench/m6_reporter.py` per contracts/output.md §1: 6-row table (one per cell) with columns `engine_forward_ms` (embed) / `engine_ttft_ms` (chat_stream) / `engine_tpot_ms` (chat_stream) / `drift_warning`. Each numeric value rendered as `mean ± CI`.
- [ ] T048 [US2] Render `⚠ engine drift` marker in the Supersedes M5.2 verdict-table row's Notes column AND a footnote under that row surfacing per-cohort engine_cost mean values (FR-014 sub-clause "per-cohort `engine_cost_mean` values MUST be surfaced for operator review") in `tools/benchmark/src/vllm_grpc_bench/m6_reporter.py`.

### JSON — engine_cost_baseline[] section (SC-006, FR-014)

- [ ] T049 [US2] Add the `engine_cost_baseline[]` array to the JSON companion writer in `tools/benchmark/src/vllm_grpc_bench/m6_reporter.py` per contracts/output.md §2: one entry per cell with `engine_forward_mean_ms`, `engine_forward_ci_half_width_ms`, `engine_ttft_mean_ms`, `engine_tpot_mean_ms`, `drift_warning` (None for path-irrelevant fields per data-model.md `EngineCostSpan` validation rules).
- [ ] T050 [US2] [P] Populate `per_cohort_engine_cost_mean_ms` in each `SupersedesM5_2Row` only when `engine_cost_drift_warning == True` (FR-014 sub-clause) in `tools/benchmark/src/vllm_grpc_bench/m6_reporter.py`; assert `None` otherwise per data-model.md `M6CellRecord` validation rule.

### Tests for US2

- [ ] T051 [US2] [P] Add pytest test for engine-cost aggregation in `tools/benchmark/tests/test_m6_engine_cost.py`: feed synthetic per-RPC `EngineCostSpan` values for an embed cell and a chat_stream cell; assert mean and 95% CI half-width match independent reference calculations.
- [ ] T052 [US2] [P] Add pytest test for the "Engine Cost Per RPC" markdown section in `tools/benchmark/tests/test_m6_reporter.py`: construct a synthetic `M6Run` with mixed embed + chat_stream cells; assert all 6 rows render with correct path-discriminated columns (embed rows show `engine_forward_ms`; chat_stream rows show `engine_ttft_ms` and `engine_tpot_ms`; `n/a` in irrelevant cells).
- [ ] T053 [US2] [P] Add pytest test for drift-warning rendering in `tools/benchmark/tests/test_m6_reporter.py`: feed synthetic per-cohort engine_cost means that disagree by 12%; assert the `⚠ engine drift` marker appears in the verdict-table row, the per-cohort values surface in a footnote, and the JSON companion populates `per_cohort_engine_cost_mean_ms` (not None) on that row.

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently. The Engine Cost Per RPC table is the M6 → M7 hand-off (SC-006).

---

## Phase 5: User Story 3 — Smoke gate for cheap wiring-failure detection (Priority: P3)

**Goal**: Run a fast (~5 min wall-clock, SC-004) pre-flight check before committing to the full ~75–90 min sweep. Exercises 2 cells (`embed × c=1` AND `chat_stream × c=1`) × 3 cohorts × n=10 against the real engine so wiring bugs in either unary or streaming code paths surface within minutes. Smoke is operator-triggered, NOT a CI gate.

**Independent Test**: Drive `python -m vllm_grpc_bench --m6-smoke --m6-modal-region=eu-west-1`. Confirm: (a) wall-clock ≤ 5 min (SC-004); (b) stderr emits 6 summary lines `cell=<path>×c=1 cohort=<cohort> status=<ok|failed> reason=<short>` (FR-011); (c) exit code 0 when all 6 pairs pass, 1 if any pair fails (FR-011); (d) full sweep does NOT proceed automatically on smoke failure (FR-012). Acceptance scenarios from spec.md US3 1–3.

### Smoke gate implementation (FR-011, FR-012)

- [ ] T054 [US3] Implement the smoke runner in `tools/benchmark/src/vllm_grpc_bench/m6_smoke.py` (NEW): for each of the 2 smoke cells (`(embed, h=4096, c=1)` and `(chat_stream, h=4096, c=1)`) and each of the 3 cohorts, run 10 RPCs (with FR-023 retries); collect per-(cell × cohort) `M6SmokeOutcome` (status `ok` if all 10 succeeded after retries, `failed` otherwise; reason string max ~60 chars). No persistent diagnostic file (FR-011 — smoke is cheap to re-run; operator terminal is the only consumer).
- [ ] T055 [US3] Implement the smoke-gate stderr summary output in `tools/benchmark/src/vllm_grpc_bench/m6_smoke.py`: print one line per (cell × cohort) pair in form `cell=<path>×c=<c> cohort=<cohort> status=<ok|failed> reason=<short string>` (FR-011). No startup banner; no completion banner; stdout empty.
- [ ] T056 [US3] Wire `--m6-smoke` in `tools/benchmark/src/vllm_grpc_bench/__main__.py` to: (1) call `m6_supersede.load_and_validate_m5_2_baseline(path)` (T022) — abort with exit code 2 on precondition fail per contracts/cli.md §"Exit codes" (smoke); (2) deploy the Modal app with `M6_USE_REAL_ENGINE=true` and `M6_MODEL=<--m6-model>` env vars; (3) run `m6_smoke.run_smoke(...)` (T054); (4) emit per-pair stderr summary (T055); (5) exit 0 if all 6 pairs ok, exit 1 if any failed (FR-011). Smoke MUST NOT trigger full sweep on success (US3 acceptance scenario 3).

### Tests for US3

- [ ] T057 [US3] [P] Add pytest test for smoke matrix coverage in `tools/benchmark/tests/test_m6_smoke.py` (NEW): assert the smoke runner exercises exactly the 2 cells `(embed, h=4096, c=1)` and `(chat_stream, h=4096, c=1)` × 3 cohorts × n=10 (FR-011) — 60 RPCs total; assert SC-004 budget by mocking RPC latencies and verifying total scheduled work falls within budget.
- [ ] T058 [US3] [P] Add pytest test for smoke exit-code + stderr summary in `tools/benchmark/tests/test_m6_smoke.py`: inject one failing (cell × cohort) pair; assert exit code 1; assert 6 stderr lines emitted; assert the failing line names that pair with `status=failed reason=<...>`; assert the 5 passing lines name `status=ok`.
- [ ] T059 [US3] [P] Add pytest test asserting smoke does NOT trigger full sweep in `tools/benchmark/tests/test_m6_smoke.py`: invoke `--m6-smoke` and assert `m6_sweep.run_sweep` was NOT called regardless of smoke outcome (FR-012 / US3 acceptance scenario 3).

**Checkpoint**: All 3 user stories now independently functional. The operator can run smoke + full sweep end-to-end per `quickstart.md`.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, lint pass, documentation review.

- [ ] T060 Run the project local-lint chain (`ruff check .`, `ruff format --check .`, `mypy --strict packages tools`, `pytest`) per `feedback_local_lint_chain` memory; fix any reported issues before push. All four gates MUST pass.
- [ ] T061 [P] Run `graphify update .` to refresh the local project knowledge graph with the new M6 modules (per project CLAUDE.md `## graphify` Rules section).
- [ ] T062 [P] Validate `quickstart.md` Step 1 (smoke) and Step 2 (full sweep) against the implemented harness — confirm stderr output format matches the quickstart's expected output exactly (FR-011 / FR-026). Update quickstart if implementation drifted from spec.
- [ ] T063 [P] Validate that the published `docs/benchmarks/m6-real-engine-mini-validation.json` from a real sweep round-trips through `tools/benchmark/src/vllm_grpc_bench/m5_2_supersede.py` without schema-validation errors (FR-016 / SC-007) — runs the existing M5.2 reader against the M6 file in an integration test under `tools/benchmark/tests/test_m6_reporter.py`.
- [ ] T064 Re-run the full M6 sweep against Modal `eu-west-1` and confirm SC-001 (≤90 min) + SC-002 (every cell receives exactly one terminal classification) + SC-003 (chat_stream cells publish TTFT + wall-clock with 95% CI half-widths) + SC-004 (smoke ≤5 min) on the implemented harness; commit published artifacts to `docs/benchmarks/` per `quickstart.md` Step 4.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all 3 user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational. MVP — the headline deliverable.
- **User Story 2 (Phase 4)**: Depends on Foundational; piggybacks on US1's reporter scaffolding (T039, T042) for adding the engine-cost section. Can begin in parallel with US1 once Foundational is complete, but must integrate with US1's markdown + JSON writers (T047–T050 modify the same files US1 created — sequential within those files).
- **User Story 3 (Phase 5)**: Depends on Foundational. Independent of US1 + US2 — smoke is a separate code path (`m6_smoke.py`) and a separate CLI dispatch (`--m6-smoke`). Can be implemented in parallel with US1 + US2.
- **Polish (Phase 6)**: Depends on US1 + US2 + US3 all being complete.

### Within-Phase Sequencing

- **Phase 2**: T004 (types) MUST precede T005–T025 (everything references the types). After T004, the rest of Phase 2 can largely parallelise — T005/T006 (frontend), T008/T009 (REST shim), T011/T012 (parser), T020/T021 (Modal app), T022 (baseline loader), T024 (CLI flags) all touch different files.
- **Phase 3 (US1)**: T026 → T027 → T028 (sweep loop builds aggregates builds progress) are sequential within `m6_sweep.py`. T031 → T032 → T033 are sequential within `m6_supersede.py`. T039, T042 are sequential within `m6_reporter.py`. T044 is the dispatch and depends on all the above being landed.
- **Phase 4 (US2)**: T045 → T046 (engine_cost aggregate then drift-flag attachment) sequential. T047 → T048 (markdown sections, same file) sequential. T049 → T050 (JSON sections, same file) sequential.
- **Phase 5 (US3)**: T054 → T055 → T056 sequential (smoke runner builds stderr renderer builds CLI dispatch within `m6_smoke.py` + `__main__.py`).

### Parallel Opportunities

**Within Phase 2 (after T004 types are in)**: T005 / T006 / T008 / T009 / T011 / T012 / T018 / T020 / T022 / T024 all touch DIFFERENT files and can be implemented in parallel. The corresponding tests (T007 / T010 / T013 / T017 / T019 / T023 / T025) follow each implementation task and are also independent.

**Across user stories (after Phase 2 is complete)**: US1 (T026–T044), US2 (T045–T053), and US3 (T054–T059) can each be picked up by a different implementer in parallel — they touch separate sweep / classifier / smoke modules. The only friction point is the shared `m6_reporter.py` file (US1 creates it; US2 extends it) — sequence those edits within that file.

**Within US1 tests**: T034 (classifier branches) and T035 (determinism) can run in parallel — both are pure-function tests on synthetic inputs.

---

## Parallel Example: Phase 2 Foundational (after T004 is complete)

```bash
# Different files, independent — can be picked up in parallel:
Task: "T005 [P] Add embed engine-cost timing wrapper in packages/frontend/src/vllm_grpc_frontend/completions.py"
Task: "T006 [P] Add chat_stream engine-cost timing wrapper in packages/frontend/src/vllm_grpc_frontend/chat.py"
Task: "T008 Emit engine_cost JSON on /v1/embeddings in tools/benchmark/src/vllm_grpc_bench/rest_shim.py"
Task: "T011 [P] Implement parsers in tools/benchmark/src/vllm_grpc_bench/m6_engine_cost.py"
Task: "T018 [P] Implement seed mapping in tools/benchmark/src/vllm_grpc_bench/m6_seed.py"
Task: "T020 Modal app real-engine launch in scripts/python/modal_bench_rest_grpc_server.py"
Task: "T022 [P] Implement M5.2 baseline precondition in tools/benchmark/src/vllm_grpc_bench/m6_supersede.py"
Task: "T024 CLI flag plumbing in tools/benchmark/src/vllm_grpc_bench/__main__.py"
```

## Parallel Example: User Story 1 tests

```bash
# All read synthetic inputs and write to different test files — fully parallel:
Task: "T029 [US1] Round-robin sequencer test in tools/benchmark/tests/test_m6_sweep.py"
Task: "T034 [US1] Classifier branch tests in tools/benchmark/tests/test_m6_supersede.py"
Task: "T035 [US1] [P] Classifier determinism test in tools/benchmark/tests/test_m6_supersede.py"
Task: "T040 [US1] [P] Executive-section test in tools/benchmark/tests/test_m6_reporter.py"
Task: "T041 [US1] [P] Verdict-table test in tools/benchmark/tests/test_m6_reporter.py"
Task: "T043 [US1] Strict-superset compat test in tools/benchmark/tests/test_m6_reporter.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T003).
2. Complete Phase 2: Foundational (T004–T025) — engine instrumentation + parser + Modal app + CLI + baseline precondition + seed.
3. Complete Phase 3: User Story 1 (T026–T044) — sweep + classifier + reporter.
4. **STOP and VALIDATE**: Run `python -m vllm_grpc_bench --m6 --m6-modal-region=eu-west-1`; confirm SC-001 (≤90 min) + SC-002 (every cell classified) + SC-007 (M5.2-aware consumer still works). The verdict table is the milestone exit deliverable.
5. Publish `docs/benchmarks/m6-real-engine-mini-validation.{md,json}` (US1 alone is the MVP).

### Incremental Delivery

1. Setup + Foundational → Foundation ready.
2. US1 → MVP verdict table published (M6 milestone exit). Re-run smoke locally without `m6_smoke.py` by doing a manual `--m6 --m6-modal-region=eu-west-1` against a 1-cell budget — operator workaround until US3 lands.
3. US2 → Engine-cost baseline table added; M7 hand-off complete.
4. US3 → Smoke gate added; operator no longer needs the workaround. Iteration loop is now fast.
5. Polish → Lint clean, quickstart validated, sweep re-run against published Modal region.

### Parallel Team Strategy

With multiple implementers:

1. Implementer A: Foundational tasks T004 → T005/T006 → T007 (frontend instrumentation + test).
2. Implementer B: Foundational tasks T008/T009 → T010 (REST shim + test).
3. Implementer C: Foundational tasks T011/T012 → T013, then T018 → T019 (parser + seed).
4. Implementer D: Foundational tasks T014/T015 → T016 → T017 (cohort readers + events).
5. Implementer E: Foundational tasks T020/T021 + T022/T023 + T024/T025 (Modal app + baseline + CLI).
6. Once Foundational is complete:
   - Implementer A: US1 (T026–T044) — the MVP.
   - Implementer B: US2 (T045–T053) — engine-cost baseline.
   - Implementer C: US3 (T054–T059) — smoke gate.
7. Final polish (T060–T064) by whoever lands last.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks.
- [Story] label maps task to US1 / US2 / US3 for traceability — Setup, Foundational, and Polish tasks have no story label.
- Tests are mandated by the plan (Constitution Principle IV + contracts/output.md strict-superset compatibility test + research.md R-7 deterministic classifier) — every load-bearing module ships with a pytest file.
- Verify tests FAIL before implementing the production code they test (TDD discipline per the project local-lint-chain feedback memory).
- Commit after each logical group; per the project `feedback_check_merged_before_repro` memory, also check `git log main..HEAD` to make sure nothing has been double-implemented from a recent merge.
- Stop at any checkpoint to validate the story independently against the spec's acceptance scenarios.
- `cell_incomplete` is a 5th terminal classification per FR-023 — it is NOT a verdict bucket and MUST appear as the Classification value in the verdict table, not folded into one of the 4 verdict buckets (this is checked by T041).
- Engine instance lifecycle is ONE instance for the entire sweep (FR-024) — neither the smoke gate nor the full sweep should reload the engine mid-run.
- M5.2 baseline file is a HARD prerequisite (FR-014 sub-clause) — both smoke and full sweep validate it before any Modal compute is consumed (T022, T023, T044, T056).
