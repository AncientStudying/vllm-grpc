---
description: "Task list for M6.1.3 — Phase 1 Attribution Closure: Proxy-Edge Probes + Drift Root-Cause + Variance Characterization"
---

# Tasks: M6.1.3 — Phase 1 Attribution Closure

**Input**: Design documents from `/specs/026-m6-1-3-attribution-closure/`
**Prerequisites**: plan.md (with "Implementation Methodology: Copy-Then-Refactor Pattern" section), spec.md (45 FRs + 13 SCs + 18 Q/A across 4 clarify rounds), research.md (R-1 through R-11), data-model.md, contracts/{cli,wire-vocabulary,classifier,artifact-schema}.md, quickstart.md

**Tests**: Test tasks are required, not optional. The 7-bucket classifier + compound-label tie-breaking + dormancy + legacy-fallback rules (FR-008, FR-008a, round-1 Q4, round-4 Q1) carry significant pure-function logic that's only safely correct under unit-test coverage. The pooled-audit aggregation (FR-016 + round-1 Q5) + per-run appendix-conditional rendering (FR-016a + round-2 Q5) have non-obvious edge cases that need explicit assertions. The negative-value clock-anomaly assertion (FR-006 + SC-013 dual-gate per round-3 Q5) is a CI-verifiable safety net against silent vLLM clock-source drift. The default-inheritance regression test (FR-036 carry-over from M6.1.2's FR-027 + round-3 Q2) prevents silent drift on `--m6_1_3-modal-region` / `-base-seed` / `-model`. Two integration tests (`test_m6_1_3_validate_cli.py` + `test_m6_1_3_publish_multirun_cli.py`) exercise the full CLI → orchestrator → reporter path against a stub driver, catching wiring regressions without Modal compute.

**Implementation methodology** (per [`plan.md`](./plan.md) "Implementation Methodology: Copy-Then-Refactor Pattern" + R-11 + the user's round-of-plan methodology critique): every new M6.1.3 module that has a prior-milestone analog starts as a `cp` of that analog (M6.1.2 preferred; M6.1.1 when M6.1.2 didn't fork the module), is renamed appropriately, and is then refactored to inject the new feature. NEVER re-implement from scratch — prior-milestone fixes carry forward automatically when the implementation starts from the prior milestone's already-fixed state. The per-task `cp` command is the load-bearing first action.

**Organization**: Tasks are grouped by user story per the spec's P1/P2/P3 priority:

- **US1 (P1)**: Proxy-edge probes — close M6.1.1's two `inconclusive` chat_stream c=4 / c=8 verdicts with attributed `proxy_*_dominated` labels. The most novel code surface (4 new wire keys, 7-bucket classifier extension, 2 new derived segments).
- **US2 (P2)**: Per-cohort prompt-content audit — identify root-cause of c=1 reproducible `engine_compute_variation`. Pooled-distribution H1/H2/rejection verdict; spec-decision recommendation conditional on the verdict; optional symmetric-prompts Phase B via shared helper module.
- **US3 (P3)**: Multi-run sweep + between-run variance characterization — wire variance into classifier as `inconclusive_high_variance` outer override; multi-run orchestrator with preemption-aware URL refresh; Phase B trigger verdict line.

Cross-cutting glue (CLI wiring, validate entry function, three-path output routing) lands in Phase 2 Foundational so all stories build on the same CLI surface. Modal compute is operator-driven in Phase 6 Polish.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1 / US2 / US3); omitted for Setup / Foundational / Polish
- **[OPERATOR]**: Operator-driven task (requires manual invocation; Modal compute or PR action)
- Exact file paths in every description

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm branch state + external dependencies + M6.1.1/M6.1.2 baselines exist + Modal credentials are available.

- [X] T001 Verify branch `026-m6-1-3-attribution-closure` is checked out and clean (`git status` returns clean tree; `git rev-parse --abbrev-ref HEAD` returns `026-m6-1-3-attribution-closure`)
- [X] T002 Run `uv sync --frozen` to inherit M6.1.1 + M6.1.2's pinned `vllm` + `torch` + `grpcio` + `httpx` + `modal` versions; confirm `uv.lock` is unchanged after the sync (no inadvertent dependency bumps)
- [X] T003 Verify `tcptraceroute` (Michael Toren's binary, inherited from M6.1.2 per FR-032) is installed and on PATH (`tcptraceroute --version` returns a version string; on macOS Homebrew confirm the setuid fixup per M6.1.2's quickstart Phase 0 is applied so unprivileged probes work)
- [X] T004 Verify M6.1.1's published JSON exists at `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` (the `--m6_1_3-m6-1-1-baseline` default per [`contracts/cli.md`](./contracts/cli.md)); confirm it parses (`jq -e '.dispatch_mode' docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` returns `"concurrent"`)
- [X] T005 Verify M6.1.2's published JSON exists at `docs/benchmarks/m6_1_2-methodology-discipline.json` (inheritance precondition per spec Assumptions); confirm it parses + carries the `network_paths` + `cohort_set` top-level keys M6.1.3 inherits per FR-032 (`jq -e '.network_paths' docs/benchmarks/m6_1_2-methodology-discipline.json` returns a non-null object)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Land the cross-story prerequisites — M6.1.3 types module, frontend wire-key emission (all 4 keys at all 3 handler sites), extractor + REST shim extensions, shared symmetric-prompts helper relocation, M6.1.3 sweep / reporter / classifier / validate module skeletons (copied verbatim from M6.1.2 / M6.1.1 per the copy-then-refactor methodology, but NOT yet refactored to add story-specific logic), CLI argparse wiring. Every subsequent task in US1 / US2 / US3 imports from / extends these modules.

**Critical reminder**: All `cp` + rename steps in this phase MUST come BEFORE the corresponding extend / refactor steps. Do NOT skip the `cp` and write from scratch.

### Module relocation: shared symmetric-prompts helper (FR-019 + round-2 Q4 + R-6)

- [X] T006 [P] `cp tools/benchmark/src/vllm_grpc_bench/m5_2_symmetry.py tools/benchmark/src/vllm_grpc_bench/symmetric_prompts.py` (verbatim relocation per R-6); edit `symmetric_prompts.py` module-level docstring only to update it to "M5.2-era cohort-prompt symmetry helper, relocated as a cross-milestone shared module per M6.1.3 FR-019" — do NOT change any function signatures or behavior; module passes `uv run mypy --strict tools/benchmark/src/vllm_grpc_bench/symmetric_prompts.py`
- [X] T007 Convert `tools/benchmark/src/vllm_grpc_bench/m5_2_symmetry.py` to a one-line re-export shim per R-6: replace the file contents with a module-level docstring explaining the relocation + `from .symmetric_prompts import *  # noqa: F401, F403`. Preserves M5.2's `--m5_2` historical re-runnability per FR-037 (M5.2's `m5_2_sweep.py` imports continue working unchanged through the shim)
- [X] T008 Run `uv run pytest tools/benchmark/tests/test_m5_2*.py` to confirm M5.2's historical tests still pass against the relocated helper + re-export shim. If any test fails, the relocation or shim is broken — fix BEFORE proceeding to any other task in this phase

### Types module: copy + extend

- [X] T009 [P] `cp tools/benchmark/src/vllm_grpc_bench/m6_1_2_types.py tools/benchmark/src/vllm_grpc_bench/m6_1_3_types.py`; rename `M6_1_2_*` identifiers to `M6_1_3_*` where the type is M6.1.3-specific (NOT `M6_1_2_COHORTS` — that import is preserved per FR-032). Add per [`data-model.md`](./data-model.md) "Python Dataclasses (in `m6_1_3_types.py`)" section: `M6_1_3SweepMode` literal, `M6_1_3BaseLabel` + `M6_1_3OuterLabel` + `M6_1_3AbbreviatedIdentifier` + `M6_1_3CompoundLabel` + `M6_1_3PrimaryLabel` literals, `M6_1_3TimingCheckpointExtension` dataclass, `M6_1_3PerSegmentDeltaExtension` dataclass, `M6_1_3PerSegmentAggregateExtension` dataclass, `M6_1_3BetweenRunVarianceCell` + `M6_1_3BetweenRunVariance` types, `M6_1_3AuditVerdictLine` literal, `M6_1_3PerCohortAuditDistribution` + `M6_1_3PerCellAuditAggregate` + `M6_1_3PerRunAuditVerdict` dataclasses, `M6_1_3PhaseBTriggerVerdict` dataclass, `M6_1_3SweepArtifact` dataclass (extends `M6_1_2SweepArtifact` with `between_run_variance: M6_1_3BetweenRunVariance | None`). All dataclasses use `@dataclass(frozen=True)`. Module passes `uv run mypy --strict tools/benchmark/src/vllm_grpc_bench/m6_1_3_types.py`

### Frontend servicer wire-key emission (additive in-place edits, NOT copy-then-refactor)

- [X] T010 [P] Edit `packages/frontend/src/vllm_grpc_frontend/chat.py:CompleteStream` per [`contracts/wire-vocabulary.md`](./contracts/wire-vocabulary.md) "gRPC cohorts" section: at the existing `pre_engine_ns` capture site add `m6_1_1_t_pre_engine_wall_ns = time.time_ns()`; at the existing `first_chunk_ns` capture site add `m6_1_1_t_first_chunk_mono_ns = time.monotonic_ns()`; after `messages_to_prompt` / `apply_chat_template` resolves `token_ids` add `tokenized_prompt_length = len(token_ids)` and `tokenized_prompt_hash = hashlib.blake2b(b"".join(t.to_bytes(4, 'little') for t in token_ids), digest_size=8).hexdigest()`; append all 4 keys to the existing `context.set_trailing_metadata([...])` call (keys: `m6_1_1_t_pre_engine_wall_ns`, `m6_1_1_t_first_chunk_mono_ns`, `m6_1_3_tokenized_prompt_length`, `m6_1_3_tokenized_prompt_hash`; all values stringified per gRPC trailing-metadata semantics). No behavioral change to existing handler logic per FR-021 / FR-033
- [X] T011 [P] Edit `packages/frontend/src/vllm_grpc_frontend/completions.py:CompleteStream` with the same 4-key emission as T010 (mirror the chat.py pattern)
- [X] T012 [P] Edit `packages/frontend/src/vllm_grpc_frontend/completions.py:Complete` (unary) per FR-014 + FR-003: emit ONLY the 2 audit keys (`m6_1_3_tokenized_prompt_length` + `m6_1_3_tokenized_prompt_hash`); do NOT emit the proxy-edge keys (streaming-only per FR-003 — unary has no first-chunk-vs-engine-emit delta to bisect). Captures: `tokenized_prompt_length` + `tokenized_prompt_hash` computed the same way as T010/T011

### Client-side extractor + REST shim extensions (additive in-place edits, NOT copy-then-refactor)

- [X] T013 [P] Edit `tools/benchmark/src/vllm_grpc_bench/m6_1_1_timing.py` per [`contracts/wire-vocabulary.md`](./contracts/wire-vocabulary.md) "Extractor mapping" section: in `extract_timing_checkpoint(...)` (or the equivalent existing function), add 4 new `_opt_int` / `_opt_str` reads — `pre_engine_wall_ns=_opt_int(trailing_metadata, "m6_1_1_t_pre_engine_wall_ns")`, `first_chunk_mono_ns=_opt_int(trailing_metadata, "m6_1_1_t_first_chunk_mono_ns")`, `tokenized_prompt_length=_opt_int(trailing_metadata, "m6_1_3_tokenized_prompt_length")`, `tokenized_prompt_hash=_opt_str(trailing_metadata, "m6_1_3_tokenized_prompt_hash")`. Extend `TimingCheckpoint` dataclass with the 4 new optional fields per `M6_1_3TimingCheckpointExtension` (T009). Add the `has_proxy_edge_probes` computed property returning `True` iff both `pre_engine_wall_ns` and `first_chunk_mono_ns` are non-None. Pre-M6.1.3 manifests parse cleanly with the 4 new fields as `None`
- [X] T014 [P] Edit `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` to read the 4 new wire keys from the REST SSE / JSON terminal-event object (mirror the gRPC trailing-metadata read in T013). Populate the same 4 `TimingCheckpoint` optional fields per the data-model's `M6_1_3TimingCheckpointExtension`

### Validate-entry module: copy + refactor for output-path inference

- [X] T015 `cp tools/benchmark/src/vllm_grpc_bench/m6_1_2_validate.py tools/benchmark/src/vllm_grpc_bench/m6_1_3_validate.py`; rename `run_m6_1_2` → `run_m6_1_3`; keep the single-entry-function-for-both-modes pattern from round-2 Q2 (one function handling both `--m6_1_3` and `--m6_1_3-validate` via a keyword-only `sweep_mode: Literal["full", "validate"]` parameter); modify the output-path inference logic per R-7 + [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) "The three-path publishing scheme" — `--m6_1_3-validate` → `docs/benchmarks/m6_1_3-attribution-closure-validate.{md,json}`; `--m6_1_3` (default modifiers) → `docs/benchmarks/m6_1_3-attribution-closure.{md,json}`; `--m6_1_3 --m6_1_3-diagnose-repeat=1 --m6_1_3-diagnose-n=200` → `docs/benchmarks/m6_1_3-attribution-closure-phase-b.{md,json}`; `--m6_1_3-report-out` / `--m6_1_3-report-json-out` explicit overrides take precedence. Record `sweep_mode` in `run_meta.sweep_mode` artifact metadata. NOTE: this task creates the module skeleton with path inference + dispatch only — the orchestrator call (`run_m6_1_3_sweep(...)`) will be wired in by T021 (US1 skeleton)

### CLI argparse extension (additive in-place edit, NOT copy-then-refactor)

- [X] T016 Edit `tools/benchmark/src/vllm_grpc_bench/__main__.py` per [`contracts/cli.md`](./contracts/cli.md): locate the existing M6.1.2 argparse block (`--m6_1_2` + `--m6_1_2-validate` + sub-flags) and add the parallel M6.1.3 block alongside. Add 2 top-level mode flags (`--m6_1_3`, `--m6_1_3-validate`); add 3 modifier flags (`--m6_1_3-diagnose-repeat=int default=5-or-1-by-mode`, `--m6_1_3-diagnose-n=int default=50`, `--m6_1_3-symmetric-prompts=store_true`); add 11 `--m6_1_3-*` namespaced sub-flags per `contracts/cli.md` table with defaults verbatim from M6.1.2 for the 3 inheritable parameters (`--m6_1_3-modal-region="eu-west-1"`, `--m6_1_3-base-seed=42`, `--m6_1_3-model="Qwen/Qwen3-8B"`). Mutual-exclusion list per FR-034 (rejects against all M5.x / M6 / M6.1 / M6.1.1 / M6.1.2 mode flags + `--m6_1_3` vs `--m6_1_3-validate` self-exclusion). Wire both top-level flags to `run_m6_1_3(args, sweep_mode=...)` from `m6_1_3_validate.py` (T015)

### Foundational tests (verify the CLI surface is correct before story implementation)

- [X] T017 Create `tools/benchmark/tests/test_m6_1_3_cli.py` with the spec-level guard tests per [`contracts/cli.md`](./contracts/cli.md) "Default-inheritance regression test" + FR-036 + round-3 Q2 carry-over from M6.1.2 FR-027: `test_m6_1_3_inheritable_defaults_match_m6_1_2()` asserts `args.m6_1_3_modal_region == "eu-west-1"`, `args.m6_1_3_base_seed == 42`, `args.m6_1_3_model == "Qwen/Qwen3-8B"` (fails loudly if any drifts); `test_m6_1_3_modifier_defaults_per_mode()` asserts `repeat=5 + n=50` under `--m6_1_3` and `repeat=1 + n=50` under `--m6_1_3-validate`; `test_m6_1_3_output_path_inference_per_mode()` asserts the three-path scheme per R-7 (validate sibling vs canonical vs Phase B sibling vs operator override); `test_m6_1_3_mutual_exclusion()` parametrizes a full pairwise sweep against all 14 prior mode flags listed in FR-034 + asserts argparse error in each pairing. Run `uv run pytest tools/benchmark/tests/test_m6_1_3_cli.py -v`; assert all tests pass

**Checkpoint**: `m6_1_3_types.py` + `symmetric_prompts.py` + frontend wire-key emission + extractor + REST shim + `m6_1_3_validate.py` skeleton + `__main__.py` CLI surface are all in place. CLI passes its surface tests. US1 / US2 / US3 phases may now begin in parallel where their files don't overlap.

---

## Phase 3: User Story 1 — Proxy-Edge Probes (Priority: P1) 🎯 MVP

**Goal**: Implement the 7-bucket classifier extension + compound-label tie-breaking + dormancy enforcement + 2 new derived segments (`seg_ingress_ms`, `seg_egress_ms`) + FR-006 negative-value clock-anomaly assertion. M6.1.1's two `inconclusive` chat_stream cells at c=4 (~17 ms unattributed) and c=8 (~5 ms unattributed) re-classify to one of the 7 base labels (or a `multi_factor_*` compound) once the proxy-edge probes' bisection lands. This is the structural change that closes M6.1.1's open Phase 2 verdicts per the spec's Story 1 priority rationale.

**Independent Test** (per [`spec.md`](./spec.md) Story 1 Independent Test + SC-002 + SC-003 + SC-008 + round-4 Q1): Run `--m6_1_3-validate` against the stub driver via `test_m6_1_3_validate_cli.py` and confirm the resulting validate-sibling artifact JSON: (a) contains non-null `seg_ingress_ms` + `seg_egress_ms` per chat_stream cell × cohort; (b) the canonical 5-segment sum `seg_ab_ms + seg_queue_ms + seg_prefill_ms + seg_ingress_ms + seg_egress_ms` converges to `engine_ttft_ms` within ±1 ms; (c) the classifier emits one of the 7 base labels or a `multi_factor_*` compound (NOT `inconclusive_high_variance` — that requires multi-run, deferred to US3); (d) an M6.1.1-vintage reader parses the artifact ignoring the new fields per FR-010 strict-superset. Re-classification of M6.1.1's `inconclusive` c=4 / c=8 cells using the new probes' data is the headline outcome (verified in T046/T049 Modal sweeps).

### Tests for User Story 1

- [X] T018 [P] [US1] Create `tools/benchmark/tests/test_m6_1_3_proxy_edge_probes.py` with wire-format round-trip tests per [`contracts/wire-vocabulary.md`](./contracts/wire-vocabulary.md): `test_wire_round_trip_streaming()` synthesizes a `TimingCheckpoint` with all 6 timestamps set (existing `pre_engine_ns`, `first_chunk_ns`, `engine_arrival_ns`, `engine_first_token_ns` + new `pre_engine_wall_ns`, `first_chunk_mono_ns`); passes through the per-RPC aggregator (which T021 will land); asserts `seg_ingress_ms = (engine_arrival_ns - pre_engine_wall_ns) * 1e-6` and `seg_egress_ms = (first_chunk_mono_ns - engine_first_token_ns) * 1e-6` per FR-005. `test_negative_value_assertion_fires()` synthesizes a `TimingCheckpoint` where `engine_arrival_ns < pre_engine_wall_ns` (clock-anomaly); asserts FR-006 negative-value assertion fires, the row is marked `is_clock_anomaly=True`, raw `_ns` values are logged to stderr, aggregation skips the row. `test_negative_value_cell_level_downgrade()` synthesizes a cell where > configurable-fraction of RPCs fire the assertion; asserts the cell receives `clock_anomaly` per-cell warning AND the classifier downgrades the verdict to `inconclusive`. `test_embed_cell_no_proxy_edge_emission()` synthesizes a unary RPC's `TimingCheckpoint` (no `pre_engine_wall_ns` / `first_chunk_mono_ns`); asserts `seg_ingress_ms` and `seg_egress_ms` are `None` and the negative-value assertion is NOT fired (FR-003 + AS 1.7). `test_strict_superset_m6_1_1_reader_compat()` synthesizes an M6.1.3 artifact JSON with all 4 new wire-key-derived fields populated; parses with `m6_1_1_reporter.parse_json` (or the M6.1.1 reader's equivalent); asserts no parse error + `schema_version == "m6_1_1.v1"` (no bump per FR-010 + round-3 Q1)
- [X] T019 [P] [US1] Create `tools/benchmark/tests/test_m6_1_3_classifier.py` with the 7-bucket + compound + dormancy + legacy-fallback tests per [`contracts/classifier.md`](./contracts/classifier.md) "Validation tests" section (omit the outer-override test — that lands in US3 T034). `test_7_bucket_decision_tree_base_labels()` parametrizes over each of the 7 base labels with a clean cell where exactly one segment dominates; asserts the correct label fires. `test_compound_label_alphabetical_ordering()` feeds a near-tie (`seg_egress` 45%, `seg_prefill` 43% — within 5pp); asserts `multi_factor_engine_compute_proxy_egress` per FR-008a + R-8. `test_dominance_margin_enforcement()` feeds a clear winner (10pp gap); asserts the single label fires (not compound). `test_inconclusive_collision_collapse()` feeds a near-tie where one candidate is `inconclusive`; asserts collapse to the non-inconclusive single label per FR-008a tail clause. `test_legacy_fallback_no_proxy_edge_segments()` feeds a `PerSegmentAggregate` missing `seg_ingress_ms` / `seg_egress_ms`; asserts the inherited 5-bucket M6.1.1 logic fires unchanged. `test_frontend_arrival_jitter_dormant_in_7_bucket_tree()` feeds a cell with `seg_arrival_ms` as the only candidate; asserts the label is NEVER `frontend_arrival_jitter` in the 7-bucket native tree (round-4 Q1 dormancy)

### Implementation for User Story 1

- [X] T020 [US1] `cp tools/benchmark/src/vllm_grpc_bench/m6_1_1_classifier.py tools/benchmark/src/vllm_grpc_bench/m6_1_3_classifier.py`; rename top-level entry function (`classify_m6_1_1` → `classify_m6_1_3`) — KEEP the inherited 5-bucket helper functions unchanged (the M6.1.1-preserved-unchanged guarantee per FR-008). Extend per [`contracts/classifier.md`](./contracts/classifier.md): add 7-bucket extension (`proxy_ingress_dominated` + `proxy_egress_dominated` checks against `seg_ingress_ms` / `seg_egress_ms`); add FR-008a highest-share-wins / compound-label tie-breaking with 5pp dominance margin via `make_compound_label(top_id, runner_up_id)` helper using `sorted([top_id, runner_up_id])` per R-8; add FR-008a `frontend_arrival_jitter` dormancy enforcement (round-4 Q1 — must NOT fire as primary; must NOT appear inside `multi_factor_*`); add legacy fallback (when `seg_ingress_ms` / `seg_egress_ms` are absent on rehydrated pre-M6.1.3 manifest, dispatch to the inherited 5-bucket logic). Add a `between_run_variance: M6_1_3BetweenRunVarianceCell | None = None` keyword parameter to `classify_m6_1_3` — for US1 this parameter is unused (outer override is US3 territory); document the stub with a TODO referencing US3 T035. Module passes `uv run mypy --strict tools/benchmark/src/vllm_grpc_bench/m6_1_3_classifier.py`
- [X] T021 [US1] `cp tools/benchmark/src/vllm_grpc_bench/m6_1_2_sweep.py tools/benchmark/src/vllm_grpc_bench/m6_1_3_sweep.py`; rename `M6_1_2*` references to `M6_1_3*` for M6.1.3-specific types; KEEP the topology-probe call (probe-once-per-sweep per FR-030 — inherited from M6.1.2 verbatim) and the `cohorts_at_concurrency()` import from `m6_1_2_sweep.py` (4-cohort iteration + tuned-pair-collapse-at-c=1 rule preserved per FR-032 — do NOT duplicate this function). For US1: add the per-RPC `compute_proxy_edge_segments(...)` helper in the aggregator path (computes `seg_ingress_ms` + `seg_egress_ms` from raw `_ns` checkpoints + vLLM `RequestStateStats` timestamps; fires FR-006 negative-value assertion + logs offending RPC's raw values + sets `is_clock_anomaly=True` on the row); extend the per-cell `aggregate_multi_point_timings` to add `seg_ingress_ms` + `seg_egress_ms` columns to `PerSegmentAggregate` per FR-007 (statistical recipe identical to inherited segments); wire the aggregator output to `m6_1_3_classifier.classify_m6_1_3(...)` with `between_run_variance=None` (US3 will pass non-None). Modify orchestrator return type to `M6_1_3SweepArtifact`. Do NOT add the multi-run loop yet (US3 T036) — US1 sweep runs once. Module passes `uv run mypy --strict tools/benchmark/src/vllm_grpc_bench/m6_1_3_sweep.py`
- [X] T022 [US1] `cp tools/benchmark/src/vllm_grpc_bench/m6_1_2_reporter.py tools/benchmark/src/vllm_grpc_bench/m6_1_3_reporter.py`; rename `m6_1_2*` references to `m6_1_3*`; KEEP the M6.1.2-inherited rendering of `cohort_set` / `cohort_omissions` / `network_paths` blocks. For US1, add per [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) "Per-cell row shape" + [`contracts/classifier.md`](./contracts/classifier.md) "The reporter narrative": (a) `seg_ingress` + `seg_egress` per-cell timing-table columns (formatted matching inherited segment columns); (b) classification narratives for the 2 new `proxy_*_dominated` base labels per FR-009; (c) compound-label narrative using abbreviated identifiers + per-segment shares per FR-009 + round-2 Q2 (concrete shape: `"multi-factor: proxy_egress carries 45% of spread, engine_compute carries 43% (within the 5pp dominance margin); attribution is not single-source"`); (d) one-line identifier legend at start of classifier-narratives subsection per FR-009a (concrete shape per `contracts/classifier.md`). Wire the three-path output routing per R-7 (delegates to `m6_1_3_validate.py` for path inference). Do NOT add audit section / variance section yet (US2 T030 + US3 T037). Module passes `uv run mypy --strict tools/benchmark/src/vllm_grpc_bench/m6_1_3_reporter.py`
- [X] T023 [US1] Extend `tools/benchmark/tests/test_m6_1_3_artifact_schema.py` (or create if absent) with the canonical 5-segment sum invariant test per SC-002 + round-4 Q1: `test_canonical_5_segment_sum()` synthesizes a per-cell row with all 5 named segments populated (`seg_ab_ms`, `seg_queue_ms`, `seg_prefill_ms`, `seg_ingress_ms`, `seg_egress_ms`); asserts the sum converges to `engine_ttft_ms` within ±1 ms. `test_frontend_arrival_jitter_seg_arrival_dormant()` asserts the artifact never contains a non-null `seg_arrival_ms` populated by the M6.1.3 pipeline (per FR-008a row 4 dormancy + round-4 Q1). Run `uv run pytest tools/benchmark/tests/test_m6_1_3_artifact_schema.py -v -k "5_segment or dormant"`; assert pass
- [X] T024 [US1] Run US1 unit tests: `uv run pytest tools/benchmark/tests/test_m6_1_3_proxy_edge_probes.py tools/benchmark/tests/test_m6_1_3_classifier.py -v` — assert all tests from T018 + T019 pass. If any fail, fix the implementation in T020/T021; re-run
- [X] T025 [US1] Create `tools/benchmark/tests/test_m6_1_3_validate_cli.py` by copy-then-refactor: `cp tools/benchmark/tests/test_m6_1_2_smoke_validate_cli.py tools/benchmark/tests/test_m6_1_3_validate_cli.py`; rename M6.1.2 fixtures + assertions to M6.1.3; switch mode flag from `--m6_1_2-validate` to `--m6_1_3-validate`; add US1-specific assertions — the validate-sibling artifact JSON contains non-null `seg_ingress_ms` + `seg_egress_ms` per chat_stream cell × cohort, the canonical 5-segment sum check, the classifier output is one of the 7 base labels (no `inconclusive_high_variance` yet — US3 territory). Keep the stub-driver pattern + `--m6_1_3-skip-deploy` invocation shape. Run `uv run pytest tools/benchmark/tests/test_m6_1_3_validate_cli.py -v`; assert pass

**Checkpoint**: M6.1.1's two `inconclusive` cells now re-classify under the M6.1.3 7-bucket tree using the proxy-edge probes' bisection. US1's MVP is complete — the validate sweep (T046 in Polish) will produce a published artifact with attributed labels for the c=4 / c=8 cells. The classifier's outer override (`inconclusive_high_variance`) is still stubbed; US3 will wire it.

---

## Phase 4: User Story 2 — Per-Cohort Audit (Priority: P2)

**Goal**: Implement pooled-distribution per-cohort prompt-content audit per FR-016 + round-1 Q5. The audit's H1 verdict at `chat_stream c=1` drives the FR-017 / FR-018 spec-decision recommendation (symmetric prompts as M6.x convention vs Phase C engine-config follow-up). Optional Phase B operator-invoked via `--m6_1_3-symmetric-prompts` flag using the shared `symmetric_prompts.py` helper relocated in Foundational (T006/T007).

**Independent Test** (per [`spec.md`](./spec.md) Story 2 Independent Test + SC-004 + SC-005): Run `--m6_1_3-validate` (T046 in Polish) and confirm the validate-sibling artifact contains per-RPC `tokenized_prompt_length` + `tokenized_prompt_hash` for every successful RPC on every cohort × cell (audit emits on BOTH streaming and unary per FR-014); the audit reporter section renders with the H1 verdict line; the markdown carries the corresponding spec-decision recommendation conditional on the verdict.

### Tests for User Story 2

- [X] T026 [P] [US2] Create `tools/benchmark/tests/test_m6_1_3_audit.py` per [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) "Per-Cohort Prompt-Content Audit reporter section" + FR-016 + round-1 Q5: `test_pooled_h1_confirmed()` synthesizes 5 per-run audit datasets at `chat_stream c=1` with per-cohort token-count means at e.g. `{rest_https_edge: 48.2, default_grpc: 53.7, tuned_grpc_multiplexed: 47.9}` (>2σ divergence from pooled stddev ~1.2); asserts pooled verdict is `"H1 confirmed: per-cohort token-count means diverge by >2σ"`. `test_pooled_h2_candidate()` synthesizes datasets with identical token-count means but divergent hash distributions; asserts verdict is `"H2 candidate: token-counts identical but hash distributions differ"`. `test_pooled_h1_rejected()` synthesizes datasets with identical means AND identical hash distributions; asserts verdict is `"H1 rejected: per-cohort distributions statistically identical"`. `test_per_run_appendix_omitted_when_all_match()` synthesizes 5-run dataset where all per-run verdicts == pooled verdict; asserts `should_render_audit_appendix(pooled, per_run)` returns False. `test_per_run_appendix_rendered_when_any_disagrees()` synthesizes 5-run dataset where 2 per-run verdicts differ from pooled; asserts the function returns True. `test_pooled_n_counts()` asserts `n_rpcs == 5 × 50 == 250` per cohort on publish sweep; `n_rpcs == 50` on validate sweep. **`test_sidecar_row_matches_extractor_output()` per FR-015 + round-1 Q1 (closes `/speckit-analyze` C1)**: synthesize a stub `TimingCheckpoint` with `tokenized_prompt_length=47` + `tokenized_prompt_hash="a1b2c3d4e5f60718"`; run the sweep against a stub driver that returns this checkpoint; parse the emitted sidecar JSONL row for that `(cohort, cell, iter_idx)`; assert the sidecar row's `tokenized_prompt_length` + `tokenized_prompt_hash` values are byte-identical to the extractor-populated `TimingCheckpoint` fields — pins the wire-only canonical-source rule (sidecar is orchestrator-derived from extractor output, NOT a parallel frontend-servicer emission path). Failure mode this guards: a future refactor accidentally re-introduces a parallel sidecar-emission path in the frontend servicer, causing wire / sidecar drift
- [X] T027 [P] [US2] Create `tools/benchmark/tests/test_m6_1_3_symmetric_prompts.py` per FR-019 + round-2 Q4 + R-6: `test_shared_helper_roundtrip()` imports `assign_symmetric_prompt` from `symmetric_prompts.py`; invokes against canned inputs; asserts outputs match the pre-relocation M5.2 behavior (same prompt for same iteration index across cohorts). `test_m5_2_back_compat_via_shim()` imports via the legacy path (`from vllm_grpc_bench.m5_2_symmetry import assign_symmetric_prompt` or whatever the re-export shim re-exports); asserts the legacy import resolves to the shared helper without behavior change. `test_symmetric_mode_invariant()` simulates a sweep where `--m6_1_3-symmetric-prompts` is set; asserts per-cohort token-count + token-hash distributions are byte-identical across cohorts for the same iteration index per FR-020

### Implementation for User Story 2

- [X] T028 [US2] Create `tools/benchmark/src/vllm_grpc_bench/m6_1_3_audit.py` from scratch (NET-NEW per the plan's table — no copy source; algorithmic spec lives in `contracts/artifact-schema.md` audit section + `data-model.md` audit dataclasses): implement `compute_pooled_verdict(phase_1_runs)` per FR-016 (pool per-RPC audit data across `phase_1_runs[]`; produce `M6_1_3PerCellAuditAggregate` per cell with `M6_1_3PerCohortAuditDistribution` per cohort); implement H1 / H2 / rejection criterion per FR-016 (2σ divergence on token-count means → H1 confirmed; identical means AND identical hash distributions → H1 rejected; identical means with divergent hash distributions → H2 candidate); implement `compute_per_run_verdicts(phase_1_runs)` producing `M6_1_3PerRunAuditVerdict` per run × cell; implement `should_render_audit_appendix(pooled, per_run)` per FR-016a + round-2 Q5 (byte-non-identical disagreement detection); implement `extract_h1_recommendation(pooled)` returning the FR-017 (symmetric-prompts) recommendation when chat_stream c=1 verdict is "H1 confirmed" or the FR-018 (Phase C follow-up) recommendation otherwise. Module passes `uv run mypy --strict tools/benchmark/src/vllm_grpc_bench/m6_1_3_audit.py`
- [X] T029 [US2] Edit `tools/benchmark/src/vllm_grpc_bench/m6_1_3_sweep.py` (the skeleton from T021) to wire the `--m6_1_3-symmetric-prompts` flag per FR-019: when the flag is set, the sweep's cohort-prompt assignment uses `symmetric_prompts.assign_symmetric_prompt(iter_idx, cohort, corpus)` (the shared helper relocated in T006); when unset, the existing per-cohort defaulting (inherited from M6.1.2's sweep pattern) applies. Add post-loop call `pooled_audit_verdicts = m6_1_3_audit.compute_pooled_verdict(phase_1_runs)` + `per_run_audit_verdicts = m6_1_3_audit.compute_per_run_verdicts(phase_1_runs)`. Both feed the reporter via T030
- [X] T030 [US2] Extend `tools/benchmark/src/vllm_grpc_bench/m6_1_3_reporter.py` (already extended in T022 for US1) with the audit reporter sections per [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) "The Per-Cohort Prompt-Content Audit reporter section": (a) per-cell pooled-distribution audit table per FR-016 (columns: `mean_tokenized_prompt_length`, `stddev`, `n_rpcs`, `unique_hash_count`); (b) one-line H1 verdict line drawn from the pooled distribution; (c) spec-decision recommendation block per FR-017 (when "H1 confirmed" — symmetric-prompts becomes M6.x convention) or FR-018 (when "H1 rejected" — Phase C follow-up) or H2-candidate note (when "H2 candidate"); (d) conditional per-run audit appendix per FR-016a + round-2 Q5 (renders when any per-run verdict differs from pooled; omits when all match)
- [X] T031 [US2] Run US2 unit tests: `uv run pytest tools/benchmark/tests/test_m6_1_3_audit.py tools/benchmark/tests/test_m6_1_3_symmetric_prompts.py -v` — assert all tests from T026 + T027 pass

**Checkpoint**: The audit reporter section renders in any M6.1.3 artifact (validate-sibling at single-run pooled-n=50; canonical publish at multi-run pooled-n=250); the H1 verdict at chat_stream c=1 drives the FR-017 / FR-018 spec recommendation. The optional `--m6_1_3-symmetric-prompts` flag wires the shared helper for operator-invoked Phase B. US2's MVP is complete.

---

## Phase 5: User Story 3 — Multi-Run Variance (Priority: P3)

**Goal**: Implement the multi-run sweep orchestration + between-run variance compute + `inconclusive_high_variance` outer override + Phase B trigger verdict. The unified high-variance threshold (between-run stddev ÷ within-run CI half-width per round-2 Q3) drives both FR-026 (outer override) and FR-043 (Phase B publication requirement) — one `/speckit-plan` knob, not two. Phase B requirement derives mechanically from cells carrying `inconclusive_high_variance`.

**Independent Test** (per [`spec.md`](./spec.md) Story 3 Independent Test + SC-006 + FR-044): Run `--m6_1_3 --m6_1_3-diagnose-repeat=3 --m6_1_3-skip-deploy` against the stub driver via `test_m6_1_3_publish_multirun_cli.py` and confirm: (a) `phase_1_runs[]` accumulates 3 entries; (b) the "Between-Run Variance" section renders with per-cell per-cohort `(mean_of_means_ms, stddev_of_means_ms, n_runs)`; (c) the classifier upgrades any cell where between-run stddev > unified threshold × within-run CI half-width to `inconclusive_high_variance`; (d) the Phase B trigger verdict line renders (`"Phase B required: <cells>"` or `"Phase B not required"`).

### Tests for User Story 3

- [X] T032 [P] [US3] Create `tools/benchmark/tests/test_m6_1_3_variance.py` per [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) variance section + [`contracts/classifier.md`](./contracts/classifier.md) outer-override section: `test_compute_between_run_variance_shape()` feeds 5 per-run `phase_1_runs[]` entries with per-cohort means; asserts output dict is keyed by `(cell, cohort)` with `M6_1_3BetweenRunVarianceCell(mean_of_means_ms, stddev_of_means_ms, n_runs)` values. `test_cohort_unhealthy_drop_per_run()` feeds 5-run data where one cohort has `n_rpcs=0` in 1 of the 5 runs; asserts that cohort × cell has `n_runs=4` in the variance output. `test_cohort_unhealthy_null_at_3_plus_failures()` feeds 5-run data where one cohort has `n_rpcs=0` in 3 of the 5 runs; asserts variance compute emits `null` for that cell × cohort AND the classifier emits a `cohort_unhealthy` warning per FR-027. `test_phase_b_trigger_fires_on_high_variance()` feeds a multi-run dataset where one chat_stream cell's between-run stddev exceeds the unified threshold × within-run CI half-width; asserts that cell carries `inconclusive_high_variance` AND `compute_phase_b_trigger_cells(...)` returns that cell name. `test_phase_b_trigger_absent_on_clean_data()` feeds clean data (low between-run stddev); asserts `compute_phase_b_trigger_cells(...)` returns `[]`. `test_variance_section_suppressed_below_3_runs()` feeds 2-run data; asserts the variance compute returns valid output BUT the reporter `should_render_variance_section(...)` returns False per FR-025
- [X] T033 [P] [US3] Extend `tools/benchmark/tests/test_m6_1_3_classifier.py` (already created in T019) with the outer-override tests per [`contracts/classifier.md`](./contracts/classifier.md): `test_outer_override_inconclusive_high_variance()` feeds an aggregate with a single dominant segment (`seg_prefill_ms` 60% spread) + a `M6_1_3BetweenRunVarianceCell` where `stddev_of_means_ms = 8.0` and within-run `ci_halfwidth_ms = 4.0` and threshold = 1.0 (so 8 > 1 × 4 fires); asserts the result is `"inconclusive_high_variance (engine_compute_variation)"` (outer label + inner parenthetical per FR-026). `test_outer_override_compound_inner()` feeds a near-tie inner cell + high variance; asserts result is `"inconclusive_high_variance (multi_factor_engine_compute_proxy_egress)"`. `test_outer_override_absent_on_normal_variance()` feeds the same inner cell but with low between-run stddev (well under threshold); asserts outer override does NOT fire; result is the inner label alone

### Implementation for User Story 3

- [X] T034 [US3] Create `tools/benchmark/src/vllm_grpc_bench/m6_1_3_variance.py` from scratch (NET-NEW per the plan's table — no copy source; algorithmic spec in `contracts/artifact-schema.md` + `contracts/classifier.md`): implement `compute_between_run_variance(phase_1_runs)` per FR-024 producing per cell × cohort `M6_1_3BetweenRunVarianceCell(mean_of_means_ms, stddev_of_means_ms, n_runs)` (excludes runs where cohort had 0 successful RPCs per FR-027); implement `should_fire_inconclusive_high_variance(cell_variance, cell_ci_halfwidth_ms, threshold)` per FR-026 + round-2 Q3 (between-run stddev > threshold × within-run CI half-width); implement `compute_phase_b_trigger(classifications, variance_section_suppressed)` per FR-043 + FR-044 + round-2 Q3 returning `M6_1_3PhaseBTriggerVerdict` (`required`, `trigger_cells` alphabetically sorted, `variance_section_suppressed` flag); implement `should_render_variance_section(phase_1_runs)` per FR-025 (True iff `len(phase_1_runs) >= 3`). Module passes `uv run mypy --strict tools/benchmark/src/vllm_grpc_bench/m6_1_3_variance.py`
- [X] T035 [US3] Edit `tools/benchmark/src/vllm_grpc_bench/m6_1_3_classifier.py` (already extended in T020) to wire `between_run_variance` into the outer-override logic per FR-026: in `classify_m6_1_3(per_segment_aggregate, between_run_variance, ...)`, when `between_run_variance is not None` AND `m6_1_3_variance.should_fire_inconclusive_high_variance(...)` returns True, emit `"inconclusive_high_variance (<inner_label>)"` per [`contracts/classifier.md`](./contracts/classifier.md) outer-override semantics — outer label is the headline, inner label (whatever the 7-bucket tree + compound logic produced) is the parenthetical. Replaces US1's stub (T020). Module still passes `uv run mypy --strict`
- [X] T036 [US3] Extend `tools/benchmark/src/vllm_grpc_bench/m6_1_3_sweep.py` (already extended in T021 + T029) with the multi-run loop per FR-022 + preemption-aware URL refresh per FR-028 + R-5: implement `_run_phase1_with_preemption_retry(config, handshake, run_idx, network_paths_for_run)` wrapping `_run_phase1_once(...)` in try/except detecting Modal tunnel preemption (connection errors against `*.modal.run` / `*.modal.host` URLs); on preemption, call `refresh_modal_urls(handshake, exc)` (porting M5.2's pattern from `m5_2_sweep.py`) and continue the loop; track preemption count per multi-run sequence; abort remaining runs after > 2 preemptions per FR-028 round-3 Q3 pinned threshold (emit "multi-run incomplete" warning via `_stderr_ts()` prefix). Add post-loop calls: `between_run_variance = m6_1_3_variance.compute_between_run_variance(phase_1_runs) if len(phase_1_runs) >= 3 else None` (FR-025 suppression); `phase_b_trigger = m6_1_3_variance.compute_phase_b_trigger(classifications, variance_section_suppressed=(between_run_variance is None))` (FR-044). Pass `between_run_variance` into each `m6_1_3_classifier.classify_m6_1_3(...)` call per cell (US3 now uses the non-None argument that US1's T020 stubbed). Wire `between_run_variance` + `phase_b_trigger` into the `M6_1_3SweepArtifact` returned by the orchestrator
- [X] T037 [US3] Extend `tools/benchmark/src/vllm_grpc_bench/m6_1_3_reporter.py` (already extended in T022 + T030) with the variance reporter sections per [`contracts/artifact-schema.md`](./contracts/artifact-schema.md): (a) "Between-Run Variance" markdown section conditional on `len(phase_1_runs) >= 3` per FR-025 (per-cell per-cohort table with `mean_of_means_ms`, `stddev_of_means_ms`, `n_runs` columns); (b) Phase B trigger verdict line at end of the variance section per FR-044 (`"Phase B required: <comma-separated cells>"` or `"Phase B not required"`); (c) FR-044 override fallback when `variance_section_suppressed` is True (`"Phase B trigger verdict unavailable (requires --m6_1_3-diagnose-repeat >= 3 for between-run variance compute)"` rendered at end of per-cell timing table instead); (d) "Phase B: n=200 Power Test" comparison section when invoked for the Phase B mode (output path inferred per R-7), with per-cell CI half-width comparison at n=200 vs n=50 + the V2/V3/V4-dominant call-outs per FR-045; (e) reciprocal cross-reference to M6.1.1's published markdown in the "Method / Background" section per FR-041 (concrete text: `"Updates the c=4 / c=8 verdicts from [M6.1.1](m6_1_1-engine-cost-instrumentation.md); see that artifact's leading note for the bidirectional pointer."`)
- [X] T038 [US3] Run US3 unit tests: `uv run pytest tools/benchmark/tests/test_m6_1_3_variance.py tools/benchmark/tests/test_m6_1_3_classifier.py -v -k "variance or outer_override"` — assert all tests from T032 + T033 pass
- [X] T039 [US3] Create `tools/benchmark/tests/test_m6_1_3_publish_multirun_cli.py` (NET-NEW — no copy source; the multi-run scenario is M6.1.3-specific per the plan's table). Implements `test_publish_multirun_3_runs()` exercising `--m6_1_3 --m6_1_3-diagnose-repeat=3 --m6_1_3-skip-deploy` against the stub driver (uses `repeat=3` instead of `repeat=5` to keep the test fast); asserts `phase_1_runs[]` accumulates 3 entries, the "Between-Run Variance" markdown section renders, the Phase B trigger verdict line renders (either form is acceptable depending on the stub data), the per-run audit appendix renders only when per-run verdicts disagree with the pooled verdict (FR-016a). Add `test_phase_b_verdict_override_fallback()` exercising `--m6_1_3 --m6_1_3-diagnose-repeat=2 --m6_1_3-skip-deploy` (operator override below 3); asserts the variance section is suppressed AND the FR-044 override fallback message renders at end of per-cell timing table. Run `uv run pytest tools/benchmark/tests/test_m6_1_3_publish_multirun_cli.py -v`; assert pass

**Checkpoint**: M6.1.3's three-store integration is complete. The validate sweep (T046 in Polish) produces wiring-check artifact at the validate-sibling path; the publish sweep (T048 in Polish) produces the canonical milestone artifact with multi-run variance + Phase B trigger verdict; the conditional Phase B sweep (T051 in Polish, if triggered) produces the Phase B sibling artifact.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation updates (`contracts/instrumentation.md` extension + M6.1.1 forward-pointing annotation), local lint chain verification, operator-driven Modal sweeps (validate → publish → conditional Phase B), pre-PR verification, PR open.

### Documentation updates

- [X] T040 [P] Extend `contracts/instrumentation.md` per FR-011 + SC-010 + round-3 Q1: add sections documenting (a) 4 new wire keys (2 `m6_1_1_*` proxy-edge + 2 `m6_1_3_*` audit) per [`contracts/wire-vocabulary.md`](./contracts/wire-vocabulary.md); (b) 2 new derived segments (`seg_ingress_ms`, `seg_egress_ms`); (c) 7-bucket classifier + canonical 6-row mapping table per [`contracts/classifier.md`](./contracts/classifier.md); (d) compound-label vocabulary + 5pp dominance margin; (e) `inconclusive_high_variance` outer override + unified high-variance threshold (round-2 Q3); (f) `between_run_variance` top-level block; (g) `frontend_arrival_jitter` dormancy note (round-4 Q1); (h) additive-strict-superset versioning convention (round-3 Q1). Cross-reference the per-section M6.1.3 contracts. SC-007: a reader unfamiliar with M6.x can determine cell label, c=1 root-cause, c=4 variance fraction, and audit recommendation in under 5 min from the updated `contracts/instrumentation.md` + `docs/benchmarks/m6_1_3-attribution-closure.md`
- [X] T041 [P] Add the M6.1.1 forward-pointing annotation per FR-031 + round-3 Q2 minimal-touch mechanism: insert this EXACT line at the top of `docs/benchmarks/m6_1_1-engine-cost-instrumentation.md` (above the existing H1 title, with one blank line separating from the H1): `> **Note**: This milestone's c=4 / c=8 verdicts were updated by [M6.1.3](m6_1_3-attribution-closure.md). See that artifact for attributed labels and Phase B variance characterization.` NO other body mutation per round-3 Q2; M6.1.1's JSON is UNTOUCHED. Verify with `grep -q "updated by \[M6.1.3\]" docs/benchmarks/m6_1_1-engine-cost-instrumentation.md`

### Local quality gates

- [X] T042 Run the local lint chain (Constitution Principle IV; per [`feedback_local_lint_chain`](../../.claude/projects/-Users-bsansom-projects-vllm-grpc/memory/feedback_local_lint_chain.md) memory): `uv run ruff check tools/benchmark/ packages/frontend/`; `uv run ruff format --check tools/benchmark/ packages/frontend/`; `uv run mypy --strict tools/benchmark/src/vllm_grpc_bench/m6_1_3_*.py tools/benchmark/src/vllm_grpc_bench/symmetric_prompts.py tools/benchmark/src/vllm_grpc_bench/m5_2_symmetry.py packages/frontend/src/vllm_grpc_frontend/chat.py packages/frontend/src/vllm_grpc_frontend/completions.py`; `uv run pytest tools/benchmark/tests/test_m6_1_3_*.py tools/benchmark/tests/test_m5_2*.py`. All four MUST pass before any push. The `--no-verify` prohibition per Constitution Principle IV applies
- [X] T043 Run the full pytest suite as a regression gate: `uv run pytest tools/benchmark/tests/` — confirm no M6 / M6.1 / M6.1.1 / M6.1.2 test regresses due to the M6.1.3 modifications (frontend wire-key emission, extractor extension, REST shim extension, M5.2 → shared helper relocation). FR-037's freeze on historical re-runnability is verified by the existing M6.1.1 / M6.1.2 test suite passing unchanged

### Operator-driven Modal sweeps

- [X] T044 [OPERATOR] Confirm Modal credentials available: `echo "${MODAL_BENCH_TOKEN:-<unset>}"` returns a non-empty token; confirm M6.1.1 + M6.1.2 baseline JSONs present at the expected `docs/benchmarks/` paths
- [X] T045 [OPERATOR] Run the M6.1.3 validate sweep per FR-039 + SC-001 + SC-013 dual-gate: `uv run python -m vllm_grpc_bench --m6_1_3-validate --m6_1_3-modal-region=eu-west-1 --m6_1_3-base-seed=42 --m6_1_3-model="Qwen/Qwen3-8B"`. Expected: ~15 min wall-clock; ~$0.29 Modal cost; produces `docs/benchmarks/m6_1_3-attribution-closure-validate.{md,json}`. Verify the validate-sibling artifact contains the new wire-key-derived fields per [`quickstart.md`](./quickstart.md) Phase 2 "Inspect the validate-sibling artifact"
- [X] T046 [OPERATOR] Verify SC-013 dual-gate on the validate artifact: `jq '.multi_point_timings | to_entries | map({cell: .key, worst_cohort_clock_anomaly_fraction: (.value | to_entries | map(.value.audit.clock_anomaly_fraction) | max)})' docs/benchmarks/m6_1_3-attribution-closure-validate.json` — assert `worst_cohort_clock_anomaly_fraction < 0.005` (0.5%) per SC-013 + round-3 Q5. If exceeded, the M6.1.3 PR is held until the cause is diagnosed per quickstart Troubleshooting "Negative-value assertion fires above 0.5% RPC budget"; do NOT proceed to the ~75 min publish run
- [X] T047 [OPERATOR] Run the M6.1.3 publish sweep per FR-039 + SC-001 + SC-006: `uv run python -m vllm_grpc_bench --m6_1_3 --m6_1_3-modal-region=eu-west-1 --m6_1_3-base-seed=42 --m6_1_3-model="Qwen/Qwen3-8B"`. Expected: ~75 min wall-clock (5 runs × ~15 min); ~$1.45 Modal cost; produces `docs/benchmarks/m6_1_3-attribution-closure.{md,json}`. Per FR-028: orchestrator tolerates up to 2 Modal preemptions; aborts on 3rd. Verify the canonical artifact contains `phase_1_runs[]` with 5 entries + the populated `between_run_variance` block per quickstart Phase 3 inspect commands
- [X] T048 [OPERATOR] Verify SC-013 dual-gate on the canonical publish artifact (per round-3 Q5): same `jq` check as T046 but on `docs/benchmarks/m6_1_3-attribution-closure.json`; assert `worst_cohort_clock_anomaly_fraction < 0.005` per SC-013. If exceeded, hold the M6.1.3 PR
- [X] T049 [OPERATOR] Inspect the Phase B trigger verdict line per FR-044: `grep -A 5 "Phase B trigger verdict\|Phase B required\|Phase B not required" docs/benchmarks/m6_1_3-attribution-closure.md` — record the verdict for the PR description
- [~] T050 [OPERATOR] (CONDITIONAL on T049 verdict) If "Phase B required" — run the Phase B sweep per FR-043 + FR-045: `uv run python -m vllm_grpc_bench --m6_1_3 --m6_1_3-diagnose-repeat=1 --m6_1_3-diagnose-n=200 --m6_1_3-modal-region=eu-west-1 --m6_1_3-base-seed=42 --m6_1_3-model="Qwen/Qwen3-8B"`. Expected: ~60 min wall-clock; ~$1.16 Modal cost; produces `docs/benchmarks/m6_1_3-attribution-closure-phase-b.{md,json}` per FR-045 + R-7 path inference. Verify the Phase B sibling cross-references the Phase A artifact + reports per-cell CI half-widths at n=200 vs n=50 per quickstart Phase 4 inspect commands. If "Phase B not required" — skip this task entirely

### Pre-PR verification + open

- [ ] T051 Pre-PR artifact + documentation + cost verification: `jq -e '.schema_version' docs/benchmarks/m6_1_3-attribution-closure.json` returns `"m6_1_1.v1"` (no bump per FR-010); `jq -e '.schema_version' docs/benchmarks/m6_1_3-attribution-closure-validate.json` returns `"m6_1_1.v1"`; if Phase B ran, `jq -e '.schema_version' docs/benchmarks/m6_1_3-attribution-closure-phase-b.json` returns `"m6_1_1.v1"`; `grep -q "updated by \[M6.1.3\]" docs/benchmarks/m6_1_1-engine-cost-instrumentation.md` returns 0 (annotation landed per T041); `grep -q "between_run_variance\|inconclusive_high_variance\|proxy_ingress_dominated" contracts/instrumentation.md` returns 0 (contract updated per T040); final lint chain re-run per T042. **Cost-tracking gate per SC-009 + round-5 (closes `/speckit-analyze` C4)**: record actual Modal spend for each sweep from the Modal billing dashboard or `modal app list --json` output — `validate_cost`, `publish_cost`, `phase_b_cost` (0 if Phase B did not fire per T049 verdict); compute `total_cost = validate_cost + publish_cost + phase_b_cost`; assert `total_cost <= 6.05` (USD) per FR-042 + SC-009 hard cap; record the per-sweep breakdown + total for inclusion in the T052 PR description. If the cap is exceeded, the M6.1.3 PR is held until the overrun is diagnosed (likely cause: extended preemption-recovery cycles per FR-028, or per-sweep wall-clock above the SC-001 ~75 min / Phase B ~60 min estimates)
- [ ] T052 [OPERATOR] Open the M6.1.3 PR (separate gate per [`feedback_pr_creation_deferred`](../../.claude/projects/-Users-bsansom-projects-vllm-grpc/memory/feedback_pr_creation_deferred.md) memory — confirm with user before `gh pr create`). PR description references: spec (`specs/026-m6-1-3-attribution-closure/spec.md`, 20 Q/A across 5 rounds), plan (`specs/026-m6-1-3-attribution-closure/plan.md` with copy-then-refactor methodology section), published artifacts (canonical + validate + conditional Phase B), PLAN.md M6.1.3 section (`docs/PLAN.md` §259-307), M6.1.1 + M6.1.2 baselines consumed, Phase B trigger verdict outcome from T049, **per-sweep Modal cost breakdown + total from T051 (validate + publish + optional Phase B; asserted ≤ $6.05 per SC-009 / FR-042 cap)**

---

## Dependencies & Story Completion Order

### Phase-level dependencies

```text
Phase 1 (Setup, T001-T005)
    └── must complete before Phase 2

Phase 2 (Foundational, T006-T017)
    └── must complete before Phase 3/4/5 (US1 / US2 / US3)

Phase 3 (US1, T018-T025) ─┐
Phase 4 (US2, T026-T031) ─┼── may run in parallel after Phase 2 checkpoint
Phase 5 (US3, T032-T039) ─┘    (US3 depends on US1 T020 classifier skeleton)

Phase 6 (Polish, T040-T052)
    └── T040-T043 may run after any user story
    └── T044-T052 require ALL user stories complete (operator-driven Modal sweeps)
```

### Inter-story dependencies (minimal)

- **US3 → US1**: US3's classifier outer-override task (T035) modifies the `m6_1_3_classifier.py` module that US1 created in T020. US3 must wait for US1's T020 to complete before starting T035 — but US3's other tasks (T032, T033, T034, T036, T037, T038, T039) can begin in parallel with US1's tasks.
- **US2 → US1**: US2's reporter audit-section task (T030) modifies the `m6_1_3_reporter.py` module that US1 created in T022. US2 must wait for US1's T022 to complete before starting T030 — but US2's other tasks (T026, T027, T028, T029, T031) can begin in parallel with US1's tasks.

### Per-story parallel execution opportunities

**Phase 2 Foundational — many [P] opportunities**:
```text
After T005 (Setup complete):
  Parallel batch 1: T006 [P] + T009 [P] + T010 [P] + T011 [P] + T012 [P] + T013 [P] + T014 [P]
                    (symmetric_prompts relocation + 3 frontend servicer edits + extractor extension + REST shim extension — all different files)
  Sequential after batch 1:
    T007 (depends on T006); T008 (depends on T007); T015 (depends on T009); T016 (depends on T015); T017 (depends on T016)
```

**Phase 3 US1**:
```text
Parallel: T018 [P] + T019 [P] (test files, different from production files)
Sequential: T020 → T021 (sweep depends on classifier signature) → T022 (reporter depends on types) — these touch related production modules
Parallel after T020/T021/T022: T023 [P] (artifact-schema test)
Sequential: T024 (run unit tests) → T025 (integration test)
```

**Phase 4 US2**:
```text
Parallel: T026 [P] + T027 [P] (test files)
Sequential: T028 (audit module net-new) → T029 (sweep extension) → T030 (reporter extension; depends on US1 T022 reporter skeleton)
Sequential: T031 (run unit tests)
```

**Phase 5 US3**:
```text
Parallel: T032 [P] + T033 [P] (test files)
Sequential: T034 (variance module net-new) → T035 (classifier wiring; depends on US1 T020 classifier skeleton) → T036 (sweep multi-run extension)
Sequential: T037 (reporter variance section; depends on US1 T022 reporter skeleton) → T038 (run unit tests) → T039 (integration test)
```

**Phase 6 Polish**:
```text
Parallel: T040 [P] + T041 [P] (contracts/instrumentation.md + M6.1.1 annotation — different files)
Sequential: T042 (lint chain) → T043 (full pytest regression gate)
Sequential operator gates: T044 → T045 → T046 → T047 → T048 → T049 → T050 (conditional)
Sequential PR gates: T051 → T052
```

---

## Implementation Strategy

### MVP delivery (US1 = P1)

The Phase 3 US1 deliverable is the M6.1.3 MVP: 7-bucket classifier + proxy-edge probes + 2 new derived segments + FR-006 negative-value assertion + validate-sibling artifact. Once T018-T025 complete, the validate sweep (T045) produces a working artifact with attributed labels for M6.1.1's previously-`inconclusive` c=4 / c=8 chat_stream cells. The audit (US2) and multi-run variance (US3) are valuable but the headline "close M6.1.1's inconclusive verdicts" outcome lands with US1 alone.

### Incremental delivery cadence

1. **Foundational complete** (after T017): CLI surface present, no story-specific behavior. Can be merged as a stand-alone scaffold PR if desired (no functional change to existing milestones).
2. **US1 MVP complete** (after T025): proxy-edge bisection works; M6.1.1's inconclusive cells re-classify. Validate-sibling integration test passes.
3. **US2 complete** (after T031): pooled audit + symmetric-prompts helper available. Audit reporter section renders in any sweep.
4. **US3 complete** (after T039): multi-run variance + Phase B trigger wires the outer override + the Phase B publication requirement.
5. **Polish complete** (after T052): Modal sweeps run; artifacts published; PR opened.

### Copy-then-refactor reminder (cross-cutting)

Per the plan's "Implementation Methodology" section + R-11 + the user's methodology critique: every task labeled "copy-then-refactor" (T009, T015, T020, T021, T022, T025) MUST start with the `cp` step before the refactor. Skipping the `cp` and writing from scratch loses prior-milestone fixes and produces the kind of regressions that motivated this methodology in the first place. Code review for these tasks should explicitly verify the diff against the copy source shows only the refactor delta — not a full reimplementation.

For the NET-NEW modules (T028 audit, T034 variance, T039 publish-multirun integration test): there's no copy source, so the algorithmic spec in `contracts/artifact-schema.md` + `contracts/classifier.md` + `data-model.md` is load-bearing. The implementer should reference these contracts repeatedly during implementation rather than deriving the algorithm from first principles.

---

## Cross-references

- Plan: [`plan.md`](./plan.md)
- Spec: [`spec.md`](./spec.md) — 45 FRs + 13 SCs + 18 Clarifications across 4 rounds
- Research: [`research.md`](./research.md) — R-1 through R-11
- Data model: [`data-model.md`](./data-model.md)
- CLI contract: [`contracts/cli.md`](./contracts/cli.md)
- Wire-vocabulary contract: [`contracts/wire-vocabulary.md`](./contracts/wire-vocabulary.md)
- Classifier contract: [`contracts/classifier.md`](./contracts/classifier.md)
- Artifact-schema contract: [`contracts/artifact-schema.md`](./contracts/artifact-schema.md)
- Quickstart: [`quickstart.md`](./quickstart.md)
- PLAN.md M6.1.3 section: `docs/PLAN.md` §259-307
- M6.1.2 tasks precedent: `specs/025-m6-1-2-methodology-discipline/tasks.md`
- M6.1.1 tasks precedent: `specs/023-m6-1-1-engine-cost-instrumentation/tasks.md`
