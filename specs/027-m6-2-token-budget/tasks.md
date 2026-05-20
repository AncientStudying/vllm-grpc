---
description: "Implementation tasks for M6.2 Token-Budget Characterization"
---

# Tasks: M6.2 — Token-Budget Characterization (Production Latency Budgets Across `max_tokens` Axis)

**Input**: Design documents from `/specs/027-m6-2-token-budget/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli.md, contracts/artifact-schema.md, contracts/iteration-order.md, contracts/wire-vocabulary.md, contracts/prompt-source.md, quickstart.md

**Tests**: Required per Constitution Principle IV + plan.md Testing section. Test tasks are interleaved with implementation per phase.

**Organization**: Tasks are grouped by user story (US1: latency budget table, US2: protocol-crossover threshold, US3: KV-pressure observation) per spec.md's three user stories. Foundational phase carries the bulk of M6.2's shared infrastructure (the spec round-4 / round-5 controls + helpers used by all stories).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1 / US2 / US3); omitted for Setup / Foundational / Polish
- Exact file paths included

## Path conventions

- Harness modules: `tools/benchmark/src/vllm_grpc_bench/`
- Harness tests: `tools/benchmark/tests/`
- Offline scripts: `scripts/python/`
- Corpora: `tools/benchmark/corpus/`
- Benchmark artifacts: `docs/benchmarks/`
- Spec / plan docs: `specs/027-m6-2-token-budget/`
- Project-wide instrumentation contract: `contracts/instrumentation.md`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify the operator environment is ready and resolve the one pre-implementation question (`ignore_eos` proto schema).

- [ ] T001 Verify branch + prerequisites: confirm working tree clean on `027-m6-2-token-budget`, `docs/benchmarks/m6_1_3-attribution-closure.json` exists, `MODAL_BENCH_TOKEN` is set, and `uv sync --frozen --all-groups` completes cleanly. Reference: `specs/027-m6-2-token-budget/quickstart.md` Stage 0b.
- [ ] T002 [P] Investigate `ignore_eos` field in `proto/vllm_grpc/v1/chat.proto` (message `ChatCompleteRequest`) and `proto/vllm_grpc/v1/completions.proto` (message `CompletionRequest`). Determine whether the field already exists. Document findings in `specs/027-m6-2-token-budget/research.md` as a R-12 addendum or in the appropriate proto-investigation issue.
- [ ] T003 If `ignore_eos` does NOT exist in the proto schemas (per T002): add `bool ignore_eos = N;` field to `ChatCompleteRequest` in `proto/vllm_grpc/v1/chat.proto` and to `CompletionRequest` in `proto/vllm_grpc/v1/completions.proto` (with field numbers chosen to avoid collision with existing fields). Run `make proto` (or equivalent stub-regen task) and verify the stub-compile CI gate passes. If the field DOES already exist (per T002), skip this task and document the existing field number in `contracts/prompt-source.md`. **Note (post-analysis 2026-05-20)**: inspection of the proto files confirmed `ignore_eos` is NOT present; this task WILL fire. The plan's Constitution I narrative + `contracts/wire-vocabulary.md` were updated to reflect the additive wire field.
- [ ] T003a Wire `ignore_eos` translation through the frontend after T003's proto edit. Modify `packages/frontend/src/vllm_grpc_frontend/chat.py` to read `request.ignore_eos` from the gRPC `ChatCompleteRequest` and pass it into `SamplingParams(ignore_eos=...)`. Same for `packages/frontend/src/vllm_grpc_frontend/completions.py` reading `CompletionRequest.ignore_eos`. Add unit tests in `packages/frontend/tests/test_ignore_eos_translation.py` (directory confirmed to exist) for round-trip translation (request with `ignore_eos=True` → SamplingParams carries through; default `False` round-trips). ~10-20 LOC across both files + ~30-50 LOC tests. Depends on T003. SKIP if T002 found `ignore_eos` already present.
- [ ] T004 [P] Verify local lint chain works against the current tree: `ruff check .` + `ruff format --check .` + `mypy --strict .` + `pytest tools/benchmark/tests/` all pass on the current commit. Reference: `feedback_local_lint_chain` memory.

**Checkpoint**: Setup complete. Foundational phase can begin.

---

## Phase 2: Foundational (Blocking Prerequisites for ALL User Stories)

**Purpose**: Embed corpus generation, RPC builder parameterization, corpus loader extensions, M6.2 type definitions, prompt-source resolution, sweep orchestrator skeleton (with FR-030/031/032/033 round-4 controls), validate entry, CLI wiring, and the foundational test suite. All stories depend on these.

**⚠️ CRITICAL**: No user-story work can begin until this phase is complete.

### 2a — Embed corpus generation (FR-035 Phase 1 prerequisite)

- [ ] T005 Write `scripts/python/gen_embed_corpus_qwen3_8b.py` (adapt from existing `scripts/python/gen_embed_corpus.py`): load `tools/benchmark/corpus/chat_sharegpt_1000.json`, feed each prompt through Qwen3-8B's embedding layer, save 1000 `.pt` files at variable `seq_len × 4096` (fp16), build `manifest.json` with per-entry SHA + `source_prompt_id` + `seq_len` + `bucket` + top-level `corpus_sha256` + `source_chat_corpus_sha256` + `model` + `hidden_size` + `generated_at_utc`. ~150-200 LOC. Reference: `specs/027-m6-2-token-budget/research.md` R-11.
- [ ] T006 Run `python scripts/python/gen_embed_corpus_qwen3_8b.py --source-corpus=tools/benchmark/corpus/chat_sharegpt_1000.json --output-dir=tools/benchmark/corpus/completions_embeds_qwen3_8b/ --model=Qwen/Qwen3-8B --hidden-size=4096 --dtype=float16` on Modal A10G (or local GPU with ~16 GB VRAM). Verify 1000 `.pt` files + `manifest.json` are produced; commit to repo.

### 2b — RPC builder parameterization (round-5 plumbing)

- [ ] T007 [P] Modify `tools/benchmark/src/vllm_grpc_bench/m6_rpc_driver.py`: parameterize `_build_chat_grpc_request(seed, *, max_tokens, ignore_eos=False, prompt=None)` and `_build_chat_rest_payload(seed, *, max_tokens, ignore_eos=False, prompt=None)`. Default `prompt=None` falls back to existing `_build_chat_prompt(seed)`. Existing M6.x call sites pass `max_tokens=M6_CHAT_MAX_TOKENS` and `ignore_eos=False` for backward compatibility. ~25-40 LOC. Reference: `specs/027-m6-2-token-budget/contracts/prompt-source.md` "ignore_eos plumbing".
- [ ] T008 [P] Modify `tools/benchmark/src/vllm_grpc_bench/m6_1_rpc_driver.py`: parameterize `_build_embed_grpc_request(seq_len, hidden_size, rpc_index, base_seed, *, max_tokens, ignore_eos=False, prompt_embeds_override=None, seed=None)` and `_build_embed_rest_payload_m6_1(seq_len, hidden_size, rpc_index, base_seed, *, max_tokens, ignore_eos=False, prompt_embeds_override=None, seed=None)`. Existing M6.x call sites pass `max_tokens=10` and `ignore_eos=False` for backward compatibility. ~25-40 LOC. Reference: `specs/027-m6-2-token-budget/contracts/prompt-source.md`.

### 2c — Corpus loader extensions

- [ ] T009 Modify `tools/benchmark/src/vllm_grpc_bench/corpus.py`: add `load_completions_embeds_qwen3_8b(corpus_dir: Path | None = None) -> list[CompletionEmbedSample]` (loads the new `completions_embeds_qwen3_8b/` 1000-entry corpus at `hidden_size=4096`); add `verify_corpus_sha(corpus_path: Path, expected_sha: str) -> None` helper (raises `CorpusDriftError` on mismatch); define `CorpusDriftError` exception. Add `DEFAULT_EMBED_CORPUS_QWEN3_8B_DIR` module constant. ~30-40 LOC. Reference: `specs/027-m6-2-token-budget/contracts/prompt-source.md` "corpus paths".

### 2d — M6.2 type definitions

- [ ] T010 Create `tools/benchmark/src/vllm_grpc_bench/m6_2_types.py` by copying `m6_1_3_types.py` and refactoring per `specs/027-m6-2-token-budget/data-model.md`. Add `M6_2_MAX_TOKENS_AXIS`, `M6_2_VALIDATE_MAX_TOKENS_AXIS`, `M6_2_NULL_ANCHOR_MAX_TOKENS`, `M6_2_INTERIOR_CAP_MAX_TOKENS`, `M6_2_SUB_PROBE_MAX_TOKENS`, `M6_2_SUB_PROBE_N=20`, `M6_2_KV_PRESSURE_THRESHOLD=2.2`, `M6_2_NULL_ANCHOR_DRIFT_COUNT_THRESHOLD=2`, `M6_2_LATENCY_DRIFT_COHORT_COUNT_THRESHOLD=2`, `M6_2_FAILURE_SUMMARY_CELL_COUNT_THRESHOLD=3`. Define `M6_2SweepMode`, `M6_2PromptSource`, `M6_2MeasurementRegime`, `M6_2WallClockInferenceLabel`, `M6_2DriftVerdict` Literals. Define dataclasses: `M6_2MeasurementPoint` (extends `M6_1_3MeasurementPoint` with `max_tokens`, `block_start_utc`, `block_end_utc`, `retry_attempted`, `prompt_source`, `measurement_regime`, `prompt_corpus_idx`), `M6_2NullAnchor`, `M6_2CrossoverThreshold`, `M6_2KVPressureObservation` (with `sub_probe_n_rpcs`, `sub_probe_prompt_source`, `sub_probe_measurement_regime`), `M6_2AnchorLatencySnapshot`, `M6_2AnchorLatencyTrajectory`, `M6_2RunMeta` (with `iteration_order`, `iteration_discipline_verified`, `n_per_point`, `validate_axis_subset`, `wall_clock_start_utc`, `wall_clock_end_utc`, `total_sweep_hours`, `modal_spend_usd_estimate`, `chat_corpus_sha256`, `chat_corpus_path`, `embed_corpus_sha256`, `embed_corpus_path`, `sub_probe_ran`), `M6_2SweepArtifact`.

### 2e — Prompt-source resolution module (round-5)

- [ ] T011 Create `tools/benchmark/src/vllm_grpc_bench/m6_2_prompt_source.py`. Implement `load_chat_corpus() -> list[RequestSample]` (loads `chat_sharegpt_1000.json` + verifies SHA against `chat_sharegpt_1000.provenance.json`), `load_embed_corpus() -> list[CompletionEmbedSample]` (loads `completions_embeds_qwen3_8b/` + verifies SHA against `manifest.json`; raises `FileNotFoundError` if directory missing — FR-035 Phase 1 prerequisite enforcement), `resolve_block_inputs(cell, max_tokens, iter_idx, cohort, base_seed, chat_corpus, embed_corpus, *, ignore_eos_override=None)` per the regime table in `contracts/prompt-source.md`. Calls `symmetric_prompts.assign_symmetric_prompt(iter_idx, cohort, corpus)` for corpus regimes. Returns dict with keys `prompt_text` OR `embed_tensor_bytes`, `prompt_source`, `prompt_corpus_idx`, `ignore_eos`, `max_tokens`. ~200-250 LOC.

### 2f — Anchor trajectory (FR-031)

- [ ] T012 Create `tools/benchmark/src/vllm_grpc_bench/m6_2_anchor_trajectory.py`. Implement `compute_anchor_block(cohorts, rpc_driver, base_seed, sweep_hour_mark, *, cell_id="chat_stream_c1", max_tokens=10, n=20) -> dict[str, M6_2AnchorLatencySnapshot]` (uses SYNTHETIC prompt regime via direct call to `m6_rpc_driver._build_chat_prompt(seed)` — NOT the corpus regime — to preserve M6.1.3 baseline byte-comparability per R-3 of research.md), `compute_anchor_latency_trajectory(snapshots_by_cohort, m6_1_3_baseline_ci_half_width) -> dict[str, M6_2AnchorLatencyTrajectory]`, `compute_intra_sweep_drift_header_fired(trajectories) -> bool` (≥ 2 of 4 cohorts drifted per SC-016). ~150-200 LOC.

### 2g — Sweep orchestrator skeleton

- [ ] T013 Create `tools/benchmark/src/vllm_grpc_bench/m6_2_sweep.py` by copying `m6_1_3_sweep.py` and refactoring per `specs/027-m6-2-token-budget/contracts/iteration-order.md`. Implement the cohort-innermost outer loop `for cell in M6_1_CELLS: for max_tokens in axis: for cohort in cohorts_at_concurrency(cell): for rpc in range(n): ...` (FR-030); per-block UTC timestamp capture (FR-032); in-window retry-once dispatch wrapper (FR-033); FR-031 4h-mark re-anchor invocation via `m6_2_anchor_trajectory.compute_anchor_block(...)`; FR-009 `network_paths` topology probe co-firing at 4h marks; iteration_discipline_verified post-hoc machine check at sweep end; FR-004 round-3 deferral gate (refuse `--m6_2` if `args.m6_2_n is None`); SC-018 corpus-SHA validation gate (call `load_chat_corpus()` + `load_embed_corpus()` at sweep start; `CorpusDriftError` aborts). Calls `m6_2_prompt_source.resolve_block_inputs(...)` per block to get regime-correct kwargs. Inherits M6.0a concurrent dispatch + M6.1.x classifier instrumentation + M6.1.2 4-cohort iteration + M6.1.3 5-segment decomposition verbatim from imported modules. Removes M6.1.3's multi-run / variance / Phase B logic. ~400-600 LOC.

### 2h — Validate / publish CLI entry function

- [ ] T014 Create `tools/benchmark/src/vllm_grpc_bench/m6_2_validate.py` by copying `m6_1_3_validate.py` and refactoring. Implement `run_m6_2(args, *, sweep_mode: Literal["publish", "validate"])`. Output-path inference per FR-015 (canonical vs validate sibling). Record `sweep_mode`, `iteration_order="cohort_innermost_block"`, `chat_corpus_sha256`, `chat_corpus_path`, `embed_corpus_sha256`, `embed_corpus_path` in `run_meta` at sweep start. FR-004 round-3 deferral gate enforcement. SC-018 corpus-SHA validation before sweep start (chains to `m6_2_prompt_source.load_chat_corpus()` + `load_embed_corpus()`). ~100-150 LOC.

### 2i — CLI wiring

- [ ] T015 Modify `tools/benchmark/src/vllm_grpc_bench/__main__.py`: add `--m6_2` and `--m6_2-validate` top-level mode flags + the namespaced sub-flags from `contracts/cli.md` (`--m6_2-modal-region`, `--m6_2-modal-token-env`, `--m6_2-modal-endpoint`, `--m6_2-skip-deploy`, `--m6_2-base-seed`, `--m6_2-model`, `--m6_2-m6-1-3-baseline`, `--m6_2-report-out`, `--m6_2-report-json-out`, `--m6_2-events-sidecar-out`, `--m6_2-allow-engine-mismatch`, `--m6_2-n`). Mutual exclusion against 17 prior mode flags (M3 through M6.1.3). Default-inheritance: `--m6_2-modal-region="eu-west-1"`, `--m6_2-base-seed=42`, `--m6_2-model="Qwen/Qwen3-8B"` verbatim from M6.1.3. `--m6_2-asymmetric-prompts` MUST NOT be added per FR-008. Both `--m6_2` and `--m6_2-validate` dispatch to `m6_2_validate.run_m6_2(args, sweep_mode=...)`. ~80-120 LOC.

### 2j — Foundational tests

- [ ] T016 [P] Create `tools/benchmark/tests/test_m6_2_prompt_source.py`: unit tests for `resolve_block_inputs` three-regime dispatch (chat null-anchor → synthetic; chat interior-cap → corpus; chat sub-probe → corpus + ignore_eos=True; embed null-anchor → random tensor; embed interior-cap → corpus; embed sub-probe → corpus + ignore_eos=True); `assign_symmetric_prompt` cohort-invariance at fixed `iter_idx`; `load_chat_corpus()` raises `CorpusDriftError` on SHA mismatch; `load_embed_corpus()` raises `FileNotFoundError` on missing directory; `run_meta.chat_corpus_sha256` matches provenance.
- [ ] T017 [P] Create `tools/benchmark/tests/test_m6_2_iteration_order.py`: unit tests for FR-030 cohort-innermost discipline (canonical iteration produces `iteration_discipline_verified=true`); discipline-broken detection (interleaved tuples → `false`); per-block UTC timestamp recording on every MeasurementPoint row; wall-clock-timeline subsection rendering (publish mode unconditional; validate mode conditional on ≥ 8h).
- [ ] T018 [P] Create `tools/benchmark/tests/test_m6_2_anchor_trajectory.py`: unit tests for FR-031 4h cadence (40h sweep → 10 snapshots; 2.5h validate → 2 snapshots); per-cohort `latency_drift_warning` firing when spread > M6.1.3 CI half-width; SC-016 sweep-level integrity header at ≥ 2-of-4 drifted; cell-of-headroom rule at 1-of-4 does NOT fire header.
- [ ] T019 [P] Create `tools/benchmark/tests/test_m6_2_retry_policy.py`: unit tests for FR-033 in-window retry once (first attempt transient error → retry succeeds; row marked `retry_attempted=true`); both attempts fail → row marked `failed_<reason>`, `retry_attempted=true`; end-of-sweep retry FORBIDDEN (failed block stays `failed_<reason>` after orchestrator advances past tuple); retry stays in time-window (assert `block_start_utc`/`block_end_utc` within the same tuple's window).
- [ ] T020 [P] Create `tools/benchmark/tests/test_m6_2_null_anchor.py`: unit tests for FR-012 / FR-013 cross-milestone comparison on the **22 cross-checkable cells** (M6.2 anchor inside M6.1.3 CI → `PASS`; outside CI but within 2× → `WARN`; outside 2× → `FAIL`); FR-012 **new-baseline behavior on the 26 non-cross-checkable cells** (each carries `new_baseline_marker = true` and `drift_verdict = null`); FR-014 sweep-level integrity header at ≥ 2 of 22 cross-checkable cells drifted (assert: new-baseline cells do NOT count toward the threshold); per-cohort sub-warnings NOT separately wired (spec round-1 Q4).
- [ ] T021 [P] Create `tools/benchmark/tests/test_m6_2_cli.py`: unit tests for argparse — all `--m6_2-*` flags present with documented defaults; mutual exclusion against 17 prior mode flags; default-inheritance regression (`--m6_2-modal-region`/`--m6_2-base-seed`/`--m6_2-model` match M6.1.3); round-3 deferral gate (`--m6_2` without `--m6_2-n` → SystemExit); `--m6_2-validate --m6_2-n=X` with X != 20 → SystemExit; `--m6_2-asymmetric-prompts` flag NOT in parser (argparse error if passed).

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel.

---

## Phase 3: User Story 1 — Per-cohort latency budget table across the `max_tokens` axis (Priority: P1) 🎯 MVP

**Goal**: Publish a per-cohort × per-cell × per-`max_tokens` `wall_p50_ms` / `wall_p95_ms` / `wall_p99_ms` table for the M6.2 measurement matrix (144 rows in publish; 72 measured + 72 `not_validated` placeholders in validate). Null-anchor validation against M6.1.3's published CIs fires per-cell `control_drift_warning` lines on the 22 cross-checkable cells + per-cell `new_baseline_marker` lines on the 26 non-cross-checkable cells + the FR-014 sweep-level integrity header when ≥ 2 of 22 cross-checkable anchor cells drift.

**Independent Test**: Run `python -m vllm_grpc_bench --m6_2-validate --m6_2-skip-deploy` against the stub RPC driver; assert the validate-sibling artifact JSON contains exactly 72 `M6_2MeasurementPoint` rows under `per_cell` (3-point axis × 4 cohorts × 6 cells), the markdown contains a "Production latency budget" section with one table per cell-cohort combination, the `run_meta` block carries the correct `iteration_order`, `chat_corpus_sha256`, `embed_corpus_sha256`, `sub_probe_ran=true`, and `schema_version="m6_1_1.v1"`.

### Implementation for User Story 1

- [ ] T022 [US1] Create `tools/benchmark/src/vllm_grpc_bench/m6_2_reporter.py` by copying `m6_1_3_reporter.py` and refactoring. Implement entry `write_m6_2_report(artifact, *, sweep_mode)`, JSON serialization (`render_json(artifact)`), Markdown skeleton (`render_markdown(artifact, *, sweep_mode)`), two-path output routing per FR-015. The skeleton produces the empty four-primary-section + six-auxiliary-subsection structure; per-section content is populated in subsequent US1/US2/US3 tasks. ~200-300 LOC base + ~600-800 LOC across the section-rendering tasks below.
- [ ] T023 [US1] Implement the "Production latency budget" primary section rendering in `m6_2_reporter.py`. Per-cell × per-cohort × per-`max_tokens` `wall_p50_ms` / `wall_p95_ms` / `wall_p99_ms` table with `prompt_source` + `measurement_regime` + `prompt_corpus_idx` columns per row. Validate-mode marks interior-cap rows (`max_tokens ∈ {256, 512, 1024}`) as `not_validated`. Reference: `specs/027-m6-2-token-budget/contracts/artifact-schema.md` section 1.
- [ ] T024 [US1] Implement the "TPOT curves" primary section rendering in `m6_2_reporter.py`. Chat_stream-only TPOT vs `max_tokens` per (chat_stream_c1 / c4 / c8, cohort) pair. Validate-mode marks interior-cap rows `not_validated`. Reference: `contracts/artifact-schema.md` section 2.
- [ ] T025 [US1] Implement the "Engine-cost decomposition curves" primary section rendering in `m6_2_reporter.py`. Per (cell, cohort) pair, segment-share evolution (`seg_ab_ms`, `seg_queue_ms`, `seg_prefill_ms`, `seg_ingress_ms`, `seg_egress_ms`) as a function of `max_tokens`. Inherited from M6.1.3 5-segment decomposition. Validate-mode marks interior-cap rows `not_validated`. Reference: `contracts/artifact-schema.md` section 3.
- [ ] T026 [US1] Implement the "Null anchor validation" auxiliary subsection rendering in `m6_2_reporter.py`. Per-cross-checkable-(cell, cohort) `drift_verdict ∈ {PASS, WARN, FAIL}` against M6.1.3's published CIs; per-cell `control_drift_warning` lines for drifting cross-checkable cells; per-new-baseline-(cell, cohort) `new_baseline_marker` line. FR-014 sweep-level null-anchor integrity warning header firing when ≥ 2 of the 22 cross-checkable anchor cells carry `drift_verdict ∈ {WARN, FAIL}` (new-baseline cells excluded from the count). Reference: `contracts/artifact-schema.md` section 6.
- [ ] T027 [US1] Implement the "Failure summary" auxiliary subsection rendering in `m6_2_reporter.py`. Per-reason tally of `failed_<reason>` markers; always present even when zero failures (reads "no measurement-cell failures"). FR-029 sweep-level failure-summary integrity warning header firing per the two-condition rule (≥ 3 cells failed OR any (cell, max_tokens) with all 4 cohorts failed → `systemic_failure_<reason>` tag). Reference: `contracts/artifact-schema.md` section 8.
- [ ] T028 [US1] Implement the "Sweep wall-clock timeline" auxiliary subsection rendering in `m6_2_reporter.py`. One row per `(cell, max_tokens)` tuple with each cohort's `block_start_utc` + duration in minutes. Renders in publish mode unconditionally; in validate mode only if total sweep wall-clock ≥ 8h. Soft `iteration_discipline_broken` diagnostic header fires when `iteration_discipline_verified=false`. Reference: `contracts/artifact-schema.md` section 9.
- [ ] T029 [US1] Implement the FR-009 / SC-010 cohort-CSP-mismatch warning rendering in `m6_2_reporter.py`. Inspect `network_paths` per-cohort trajectories; for any consecutive snapshot pair revealing a CSP / region change, emit the sweep-level integrity warning header.
- [ ] T030 [US1] Implement the SC-016 intra-sweep latency-drift integrity warning header rendering in `m6_2_reporter.py` (consumes `M6_2AnchorLatencyTrajectory.latency_drift_warning` per cohort; fires at ≥ 2-of-4 cohorts). Also render the per-cohort "Anchor latency trajectory" auxiliary subsection (with the trajectory snapshots, derived spread, and per-cohort `latency_drift_warning` line).

### Tests for User Story 1

- [ ] T031 [P] [US1] Create `tools/benchmark/tests/test_m6_2_artifact_schema.py`: 144-row latency budget table completeness in both modes (publish: 144 measurements/failures; validate: 72 measurements + 72 `not_validated` placeholders) per SC-003; strict-superset compat with M6.1.3-vintage readers (FR-011 / SC-007); validate-mode `not_validated` rendering for interior caps; per-row `prompt_source` + `measurement_regime` + `prompt_corpus_idx` field discipline; `run_meta` schema (all M6.2 round-4 + round-5 additive fields present); `failure_summary` always present (SC-014); `integrity_warnings` ⊆ canonical channel labels; **SC-011 clock-anomaly gate**: assert the reporter computes the fraction of negative-segment / impossible-ordering wire-format assertions across the full sweep and emits a `clock_anomaly_warning` artifact-header line iff the fraction ≥ 0.5%; unit-test with stub data exercising both sides of the 0.5% threshold.
- [ ] T032 [P] [US1] Create `tools/benchmark/tests/test_m6_2_validate_cli.py`: integration test exercising `--m6_2-validate --m6_2-skip-deploy` against a stub RPC driver; assert validate-sibling artifact JSON contains 72 measured rows + 72 `not_validated` placeholder rows; assert all four sweep-level integrity warning headers + the soft diagnostic render conditionally based on the stub's injected drift / failure conditions; assert `run_meta.sub_probe_ran=true` (US3's sub-probe co-fires; foundational concern but exercised here).

### M6.1.3 forward-pointing annotation (FR-019)

- [ ] T033 [US1] Add the single leading `> **Note**:` line at the top of `docs/benchmarks/m6_1_3-attribution-closure.md` per FR-019. Line content per `contracts/artifact-schema.md` "Forward-pointing annotation". M6.1.3's JSON is untouched. M6.2's reporter emits the reciprocal "Method / Background" pointer per the existing reporter implementation (no separate task — done in T022).

**Checkpoint**: User Story 1 should be fully functional and testable independently — running `--m6_2-validate --m6_2-skip-deploy` against the stub driver produces a complete validate artifact with the budget table, null-anchor verdicts, failure summary, wall-clock timeline, and the FR-019 forward-pointing annotation in M6.1.3's markdown.

---

## Phase 4: User Story 2 — Per-cell `max_tokens` crossover threshold (Priority: P2)

**Goal**: Publish a per-cell `crossover_max_tokens` derived from the symmetric mean-in-CI rule (spec round-1 Q3). Operators read this table to answer "at what `max_tokens` does the M6.1.3-published protocol verdict collapse to no winner?". US2 derives from US1's budget table data; no independent measurement loop.

**Independent Test**: Synthesize per-cell × per-cohort × per-`max_tokens` `wall_p50_ms` + CI rows; pass to `m6_2_crossover.compute_per_cell_crossover(...)` with canned M6.1.3 base verdicts; assert the function identifies the correct crossover point per the symmetric mean-in-CI rule for cells with meaningful base verdicts AND `crossover_max_tokens=None` for cells with inconclusive base verdicts (US2 #2). Run `--m6_2-validate --m6_2-skip-deploy`; assert the validate artifact's "Protocol crossover threshold" markdown section carries the axis-restricted disclaimer callout and uses the coarse 4-value vocabulary `{10, 50, 2048, survives_to_2048, null}`.

### Implementation for User Story 2

- [ ] T034 [US2] Create `tools/benchmark/src/vllm_grpc_bench/m6_2_crossover.py`. Implement `compute_per_cell_crossover(per_cell_axis_rows, m6_1_3_base_verdicts, *, sweep_mode) -> list[M6_2CrossoverThreshold]` per spec round-1 Q3 (symmetric mean-in-CI rule). Iterate axis ascending; check `(winner_p50 ∈ [second_p50 ± second_ci_half]) OR (second_p50 ∈ [winner_p50 ± winner_ci_half])` at each axis point. Handle US2 #2 (inconclusive base verdict → `crossover_max_tokens=None`) and US2 #3 (CIs overlap at `max_tokens=10` → evidence `"M6.1.3 verdict not robust to M6.2 resampling"`). Validate mode uses the coarse 4-value vocabulary. Reference: `specs/027-m6-2-token-budget/contracts/artifact-schema.md` "Symmetric mean-in-CI crossover rule". ~150-200 LOC. (Same file also gets `compute_kv_pressure_inference` in US3 phase.)
- [ ] T035 [US2] Implement the "Protocol crossover threshold" primary section rendering in `m6_2_reporter.py`. Consumes `M6_2CrossoverThreshold` records; renders per-cell row with `(cell_id, m6_1_3_base_verdict, crossover_max_tokens, crossover_evidence)`. Validate-mode prepends the axis-restricted disclaimer callout per FR-016. Reference: `contracts/artifact-schema.md` section 4.

### Tests for User Story 2

- [ ] T036 [P] [US2] Create `tools/benchmark/tests/test_m6_2_crossover.py`: unit tests for the symmetric mean-in-CI rule (winner mean ∈ second CI but not vice versa → predicate fires; either-direction satisfies; never fires across axis → `crossover_max_tokens=None` with "verdict survives across the axis" evidence); US2 #2 (inconclusive base verdict → `None` + "base verdict was already inconclusive at the M6.1.3 baseline" evidence); US2 #3 (rule fires at `max_tokens=10` → "M6.1.3 verdict not robust to M6.2 resampling" evidence); validate-mode coarse 4-value vocabulary.

**Checkpoint**: User Stories 1 AND 2 should both work independently. Validate artifact now contains the "Protocol crossover threshold" section in addition to US1's sections.

---

## Phase 5: User Story 3 — KV-cache pressure characterization at `c=8 × max_tokens=2048` (Priority: P3)

**Goal**: Characterize the `c=8 × max_tokens=2048` regime per cohort × cell-type via the FR-017a wall-clock-ratio inference. Per round-5 FR-036, the measurement comes from a dedicated KV-pressure **sub-probe** (`c=8 × {1024, 2048} × 4 cohorts × 2 cell-types × n=20`, `ignore_eos=True`) that runs after the main 144-point sweep completes (publish) or alongside the validate sweep (validate). The sub-probe is **additive** to the budget table — its results populate the `KVPressureObservation` entity only, NOT the budget-table c=8 rows.

**Independent Test**: Run `--m6_2-validate --m6_2-skip-deploy`; assert the validate artifact's `kv_pressure_observation` block contains 8 records (4 cohorts × 2 cell-types) each with `sub_probe_n_rpcs=20`, `sub_probe_measurement_regime="forced_cap_ignore_eos_true"`, `sub_probe_prompt_source` matching cell-type, and a computed `wall_clock_ratio_c8_2048_over_1024` (or `None` if either sub-probe block failed). Assert the markdown's "KV-cache pressure" subsection cites the wall-clock-ratio + threshold-2.2 comparison + best-effort engine field + OOM-observed flag, labeled as "forced-cap regime" to distinguish from budget-table c=8 rows. Assert `run_meta.sub_probe_ran=true`.

### Implementation for User Story 3

- [ ] T037 [US3] Create `tools/benchmark/src/vllm_grpc_bench/m6_2_sub_probe.py`. Implement `run_kv_pressure_sub_probe(rpc_driver, cohorts, chat_corpus, embed_corpus, base_seed, n=20, sweep_orchestrator_clock) -> list[SubProbeBlockResult]`. Iterate `for cell_type in ("chat_stream", "embed"): for max_tokens in (1024, 2048): for cohort in M6_1_2_COHORTS:` — cohort-innermost per FR-030 within each `(cell_type, max_tokens)` tuple (4 cohorts contiguous). Each block calls `m6_2_prompt_source.resolve_block_inputs(cell=f"{cell_type}_c8", max_tokens, iter_idx, cohort, base_seed, chat_corpus, embed_corpus, ignore_eos_override=True)` to get corpus-regime input + `ignore_eos=True`. RPC builder called with the new `max_tokens` + `ignore_eos` + `prompt`-or-`prompt_embeds_override` kwargs per T007 / T008. Per-block UTC timestamps per FR-032; in-window retry-once per FR-033. ~250-300 LOC. Reference: `specs/027-m6-2-token-budget/research.md` R-10.
- [ ] T038 [US3] Add `compute_kv_pressure_inference(per_cohort_sub_probe_rows) -> list[M6_2KVPressureObservation]` to `tools/benchmark/src/vllm_grpc_bench/m6_2_crossover.py` (extends the file T034 created). Consumes sub-probe block results (NOT main-sweep budget-table c=8 rows) per round-5 FR-017a amendment. Computes `R = wall_p50_ms(2048) / wall_p50_ms(1024)` per cohort × cell-type; `R > 2.2` → `kv_pressure_inferred_<cell_type>`; else `kv_pressure_not_observable`. Best-effort `kv_cache_used_fraction_peak` extraction from per-RPC trailing metadata; `oom_observed` from `failed_reason == "oom"`. Populates `sub_probe_n_rpcs=20`, `sub_probe_prompt_source` (cell-type-dependent), `sub_probe_measurement_regime="forced_cap_ignore_eos_true"`. ~100-150 LOC. Reference: `contracts/artifact-schema.md` "Wall-clock-ratio KV-pressure inference".
- [ ] T039 [US3] Wire the sub-probe into `m6_2_sweep.py` (T013): after the main 144-point sweep iteration completes (publish mode) OR alongside (validate mode), invoke `m6_2_sub_probe.run_kv_pressure_sub_probe(...)` then pipe results into `m6_2_crossover.compute_kv_pressure_inference(...)`. Populate the artifact's `kv_pressure_observation` field with the resulting 8 records. Set `run_meta.sub_probe_ran=true`. The sub-probe runs in BOTH publish and validate modes per SC-019.
- [ ] T040 [US3] Implement the "KV-cache pressure" auxiliary subsection rendering in `m6_2_reporter.py`. Per cohort × cell-type narrative paragraph citing: peak KV-budget consumption (`kv_cache_used_fraction_peak` if available else `null` with a documented reason), wall-clock-ratio inference label + ratio value + threshold-2.2 comparison, OOM-observed flag, and a comparison to the c=8 × 1024 point. Explicit "forced-cap regime (ignore_eos=True)" labeling distinguishes from budget-table c=8 rows which are "natural EOS under cap=N". Reference: `contracts/artifact-schema.md` section 5.

### Tests for User Story 3

- [ ] T041 [P] [US3] Create `tools/benchmark/tests/test_m6_2_kv_pressure.py`: unit tests for `compute_kv_pressure_inference` consuming sub-probe rows (NOT budget-table c=8 rows — synthesize divergent budget-table vs sub-probe values, assert ratio uses sub-probe); R > 2.2 → label `kv_pressure_inferred_<cell_type>`; R ≤ 2.2 → `kv_pressure_not_observable`; OOM at (cohort, c=8, 2048) → `oom_observed=true` AND label `kv_pressure_not_observable` with footnote; engine field present → propagates; engine field absent → inference still fires.
- [ ] T042 [P] [US3] Create `tools/benchmark/tests/test_m6_2_sub_probe.py`: unit tests for `run_kv_pressure_sub_probe` — 16 sub-probe blocks total (4 cohorts × 2 cell-types × 2 caps); each block at `n=20`; each block has `ignore_eos=True` in its sampling params; sub-probe results emit to `KVPressureObservation` only (NOT to the latency budget table — assert budget-table c=8 rows remain populated by the interior-cap regime); FR-030 cohort-innermost discipline within each `(cell_type, max_tokens)` tuple; FR-033 in-window retry-once applies; sub-probe runs in both publish and validate modes per SC-019.
- [ ] T043 [P] [US3] Extend `tools/benchmark/tests/test_m6_2_validate_cli.py` (created in T032) with US3-specific assertions: `kv_pressure_observation` contains 8 records; each carries `sub_probe_n_rpcs=20`, `sub_probe_measurement_regime="forced_cap_ignore_eos_true"`, `sub_probe_prompt_source` matching cell-type; "KV-cache pressure" markdown subsection cites the wall-clock-ratio inference + threshold-2.2 comparison + best-effort engine field; `run_meta.sub_probe_ran=true`.

**Checkpoint**: All three user stories now independently functional. The validate artifact carries: budget table (US1) + crossover table (US2) + KV-pressure subsection (US3) + all four sweep-level integrity warning channels + the soft iteration-discipline diagnostic + the FR-019 forward-pointing annotation in M6.1.3's markdown.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final integration test, contracts documentation update, README hygiene, manual validate sweep execution against Modal.

- [ ] T044 [P] Create `tools/benchmark/tests/test_m6_2_publish_cli.py`: integration test exercising `--m6_2 --m6_2-n=50 --m6_2-skip-deploy` against the stub RPC driver (use `n=50` for test speed even though spec round-3 has not yet pinned the publish n). Asserts: full 6-point axis × 4-cohort × 6-cell table = 144 rows + 0 `not_validated` placeholders; full 6-point crossover vocabulary; `iteration_discipline_verified=true`; "Sweep wall-clock timeline" subsection renders; all 4 publish-blocking-eligible integrity warning channels render conditionally; sub-probe contract (16 blocks × n=20 × ignore_eos=True per T042); `run_meta.sub_probe_ran=true`.
- [ ] T045 Update `contracts/instrumentation.md` (the project-wide instrumentation contract) with M6.2's schema additions: the four additive top-level keys (`null_anchor_validation`, `max_tokens_axis`, `protocol_crossover`, `kv_pressure_observation`, `anchor_latency_trajectory`, `failure_summary`, `integrity_warnings`); the seven additive per-row fields (`max_tokens`, `block_start_utc`, `block_end_utc`, `retry_attempted`, `prompt_source`, `measurement_regime`, `prompt_corpus_idx`); the ten additive `run_meta` fields; the four publish-blocking-eligible sweep-level integrity-header rules + the soft `iteration_discipline_verified` diagnostic; the symmetric mean-in-CI crossover rule; the wall-clock-ratio inference rule; the three-regime prompt source contract (FR-034 / FR-035); the KV-pressure sub-probe contract (FR-036); the corpus SHA validation rule (SC-018); validate-mode rendering rules; FR-027 project-wide convention propagation.
- [ ] T046 [P] Run the full local lint chain on the M6.2 implementation: `ruff check .` + `ruff format --check .` + `mypy --strict .` + `pytest tools/benchmark/tests/test_m6_2_*.py` — all four must pass before pushing. Reference: `feedback_local_lint_chain` memory.
- [ ] T047 Manual validate sweep execution: `python -m vllm_grpc_bench --m6_2-validate --m6_2-modal-region=eu-west-1` against Modal A10G. Expected ~2.3-2.5 h wall-clock, ~$4 Modal spend (FR-022 / SC-002). Inspect the resulting `docs/benchmarks/m6_2-token-budget-validate.{md,json}` per quickstart.md Stage 4 checklist; confirm zero entries in `integrity_warnings`.
- [ ] T048 After T047 produces clean validate output: invoke `/speckit-clarify` (round 6 — the future clarify cycle gated on validate-sweep variance data per FR-004) to pin the publish-mode `n` (and the wall-clock + Modal-spend caps per FR-021 / FR-023). Document the pinned values via a spec amendment + plan/contracts/CLAUDE.md updates if needed.
- [ ] T049 After T048 closes: manual publish sweep execution: `python -m vllm_grpc_bench --m6_2 --m6_2-n=<ROUND_3_PINNED_N> --m6_2-modal-region=eu-west-1` against Modal A10G. Expected 20-48 h wall-clock, $20-$40 Modal spend (depending on pinned n). Inspect the resulting `docs/benchmarks/m6_2-token-budget.{md,json}` per quickstart.md Stage 4 checklist.
- [ ] T050 Commit + push + open PR per quickstart.md Stage 7. PR title: "M6.2 — token-budget characterization across max_tokens axis". PR body summarizes the three user stories' deliverables, links the published artifact pair, references the round-1-through-round-5 clarify history, and includes the CI gate status.

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (Setup)**: T001-T004 run first. T002 → T003 is the only intra-phase sequential dependency.
- **Phase 2 (Foundational)**: Depends on Phase 1 completion. Within Phase 2: T005 → T006 (embed corpus generation script must exist before running it); T007/T008/T009 are [P] across files; T010 → T011/T012/T013 (types module first); T011 + T012 + T013 + T014 + T015 build the orchestrator stack roughly in this order; T016-T021 [P] foundational tests can be written against the implemented foundational modules.
- **Phase 3 (US1)**: Depends on Phase 2 completion. T022 reporter skeleton first, then T023-T030 [Story-internal sequential — same `m6_2_reporter.py` file] section-rendering tasks. T031/T032 [P] tests parallel with implementation. T033 [P] forward-pointing annotation can run any time after Phase 1.
- **Phase 4 (US2)**: Depends on Phase 2 completion. Independent of US1 implementation (different reporter sections + different module). T034 creates `m6_2_crossover.py`; T035 adds the markdown section to the reporter (depends on T022 reporter skeleton). T036 [P] tests parallel.
- **Phase 5 (US3)**: Depends on Phase 2 completion. T037 creates `m6_2_sub_probe.py`; T038 extends `m6_2_crossover.py` (depends on T034's file existing); T039 wires sub-probe into `m6_2_sweep.py` (depends on T013); T040 adds the markdown section (depends on T022 reporter skeleton). T041/T042 [P] tests parallel.
- **Phase 6 (Polish)**: Depends on Phases 3+4+5 being complete. T044/T046 [P] CI hygiene; T045 documentation; T047/T048/T049 sequential (validate → clarify round 6 → publish).

### User story dependencies

- **US1 (P1)**: Pure dependency on Phase 2 (foundational). MVP — the latency budget table is the headline deliverable.
- **US2 (P2)**: Derives from US1's per-cell × per-cohort × per-`max_tokens` rows but is implementation-independent (different module file, different reporter section). Can be developed in parallel with US1 once Phase 2 is done.
- **US3 (P3)**: Independent measurement regime (sub-probe) + independent module (`m6_2_sub_probe.py`) + independent reporter section. Can be developed in parallel with US1 and US2 once Phase 2 is done; only intersects with US1 at the shared `m6_2_sweep.py` wiring (T039).

### Within each user story

- Reporter skeleton (T022) before section-rendering tasks for US1.
- `m6_2_crossover.py` creation (T034) before extending it (T038, in US3 phase).
- Tests can be written in parallel with implementation per the project's standard practice (no strict TDD requirement per the spec; tests are required to pass before push).

### Parallel opportunities

**Phase 1 (Setup)**:
```bash
# T002 + T004 can run in parallel:
Task T002: Investigate proto schemas for ignore_eos
Task T004: Verify local lint chain
```

**Phase 2 (Foundational)** — once T005/T006 (corpus) + T010 (types) land:
```bash
# T007 + T008 + T009 can run in parallel (different files):
Task T007: Parameterize chat RPC builders in m6_rpc_driver.py
Task T008: Parameterize embed RPC builders in m6_1_rpc_driver.py
Task T009: Extend corpus.py with embed loader

# T011 + T012 can run in parallel (different files):
Task T011: Create m6_2_prompt_source.py
Task T012: Create m6_2_anchor_trajectory.py

# T016-T021 foundational tests can all run in parallel (different files):
Task T016: test_m6_2_prompt_source.py
Task T017: test_m6_2_iteration_order.py
Task T018: test_m6_2_anchor_trajectory.py
Task T019: test_m6_2_retry_policy.py
Task T020: test_m6_2_null_anchor.py
Task T021: test_m6_2_cli.py
```

**Phase 3 / Phase 4 / Phase 5** — once Phase 2 lands, the three stories can be developed by separate developers in parallel:
```bash
# Developer A: US1
Tasks T022 → T023-T030 (reporter section rendering, same file, sequential) + T031/T032/T033 [P]

# Developer B: US2
Tasks T034 + T035 + T036 [P]

# Developer C: US3
Tasks T037 + T038 + T039 + T040 + T041/T042/T043 [P]
```

**Phase 6 (Polish)**:
```bash
# T044 + T046 can run in parallel:
Task T044: Publish CLI integration test
Task T046: Local lint chain re-run
```

---

## Implementation strategy

### MVP first (User Story 1 only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (~21 tasks; this is the heaviest phase by far).
3. Complete Phase 3: User Story 1 (~12 tasks).
4. **STOP and VALIDATE**: Run `--m6_2-validate --m6_2-skip-deploy`; inspect the validate artifact. The MVP delivers the per-cohort latency budget table + null-anchor validation + failure summary + wall-clock timeline + M6.1.3 forward annotation — answering "what does production latency look like at the 3-point axis subset?" for the validate run.

### Incremental delivery

1. Setup + Foundational → foundation ready.
2. US1 → validate-against-stub-driver passes → MVP demoable.
3. US2 → crossover threshold renders → both stories independent.
4. US3 → KV-pressure observation populates → all three stories complete.
5. Polish → manual validate sweep against Modal → `/speckit-clarify` round 6 → manual publish sweep → PR.

### Parallel team strategy

With three developers and Phase 2 complete:
- Developer A: US1 (~12 tasks; reporter section work)
- Developer B: US2 (~3 tasks; pure-function crossover + reporter section)
- Developer C: US3 (~7 tasks; sub-probe module + crossover extension + reporter section + sweep wiring)

The three stories complete and integrate independently. Polish phase brings them together.

---

## Validation criteria

For each generated task, this tasks.md ensures:

- **Checkbox + Task ID + (optional [P] + optional [Story]) + Description with file path** format compliance: T001-T050 all conform.
- **Test coverage**: each user story has both unit tests (per-module pure-function tests) and integration coverage (via T032 / T043 / T044) per Constitution IV.
- **File paths**: every implementation task names the exact file it touches (`tools/benchmark/src/vllm_grpc_bench/m6_2_*.py`, `tools/benchmark/tests/test_m6_2_*.py`, etc.); no ambiguity.
- **Story labels**: US1 / US2 / US3 labels applied to user-story-phase tasks only; Setup / Foundational / Polish tasks omit story labels per the protocol.
- **Parallel markers**: [P] applied only to tasks operating on different files with no dependencies on incomplete tasks.
- **Independent testability**: each user story's Independent Test description is concrete and runnable (e.g., "Run `--m6_2-validate --m6_2-skip-deploy`; assert X, Y, Z").
- **Round-5 amendments covered**: T005-T011 + T037-T043 carry the three-regime prompt source + KV-pressure sub-probe + corpus generation + corpus SHA validation deltas introduced in clarify round 5.
- **Round-3 deferral preserved**: T015 wires the `--m6_2-n` gate; T048 explicitly tasks the future clarify round 6 that fires after validate-sweep variance data lands.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks.
- [Story] label maps task to specific user story for traceability.
- Each user story is independently completable and testable post-Phase 2.
- Tests must pass before push per Constitution IV + `feedback_local_lint_chain` memory.
- Commit after each task or logical group (typically after each phase checkpoint).
- Phase 6 T047 / T048 / T049 are sequential and gated on Modal compute + a future `/speckit-clarify` cycle — DO NOT attempt to run them before validate completes and round 6 closes.
- The `--m6_2` publish sweep is BLOCKED until T048 pins `--m6_2-n` (FR-004 round-3 deferral).
- Sub-probe runs unconditionally in both `--m6_2` and `--m6_2-validate` per SC-019; no operator-facing flag controls it.
- Embed corpus generation (T005/T006) is a one-time Phase 1 prerequisite per FR-035; subsequent sweeps reuse the committed corpus.
