---
description: "Task list for M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation"
---

# Tasks: M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation

**Input**: Design documents from `/specs/023-m6-1-1-engine-cost-instrumentation/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cli.md`, `contracts/instrumentation.md`, `contracts/output.md`, `quickstart.md`

**Tests**: INCLUDED — the plan's Constitution Check (Principle IV) and `contracts/output.md` (strict-superset validation) and `research.md` R-6 (Pydantic + golden-file approach) explicitly mandate pytest coverage for the FR-010 classifier, the FR-012 perturbation-budget gate, the FR-015b embed regression check, the FR-016 contracts heading validator, the FR-017 / FR-018 re-run + split_required gates, the sentinel-object schema (round-2 Q1 / Q2), and the `phase_1_runs[]` append-on-re-read pattern (round-3 Q1). M6.1's per-milestone test convention (`tools/benchmark/tests/test_m6_1_*`) is preserved as `test_m6_1_1_*`.

**Organization**: Tasks are grouped by user story (US1 = Phase 1 diagnostic mini-sweep, US2 = Phase 2 fix-or-document with fresh baselines, US3 = methodology supersedence annotations on M6.1's published files) so each story can be implemented and tested independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps task to a user story (US1, US2, US3); Setup / Foundational / Polish phases have no story label
- Include exact file paths in descriptions

## Path Conventions

- Harness: `tools/benchmark/src/vllm_grpc_bench/` (new modules: `m6_1_1_*.py`)
- Harness tests: `tools/benchmark/tests/test_m6_1_1_*.py`
- gRPC frontend: `packages/frontend/src/vllm_grpc_frontend/` — **possibly modified** under Phase 2(a) symmetrisation (specific edit identified by Phase 1's data, not pre-committed)
- REST shim: `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` (extended to extract `m6_1_1_timings` sub-object)
- Bench client pyproject: `tools/benchmark/pyproject.toml` — **UNCHANGED** (`torch==2.11.0` already present from M6.1)
- Modal server entrypoint: `scripts/python/modal_bench_rest_grpc_server.py` — **MODIFIED** (4 checkpoints × 2 transports per FR-007 / FR-008)
- Published artifacts: `docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}`
- Sidecar: `docs/benchmarks/m6_1_1-events.jsonl`
- M6.1 baseline (read-only input + additive annotation): `docs/benchmarks/m6_1-real-prompt-embeds.{md,json}`
- Project contracts (Phase 2(b) only): `contracts/instrumentation.md` at repo root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify preconditions — M6.1 baseline JSON present and valid; `torch==2.11.0` still pinned; M6.1's harness modules importable.

- [ ] T001 Verify M6.1 baseline file present and valid by reading `docs/benchmarks/m6_1-real-prompt-embeds.json` and confirming `schema_version == "m6_1.v1"`, `run_meta.engine_version` present (record for FR-004 comparison), and the chat_stream cells have published per-cohort `engine_ttft_ms` means + CIs (M6.1.1's FR-010 classifier inputs and FR-015b regression-check baselines depend on these). If the baseline file is missing or malformed, abort M6.1.1 implementation and republish M6.1 first. ([FR-001](./spec.md) hard precondition; [R-4](./research.md) baseline loader)
- [ ] T002 [P] Confirm `vllm==0.20.1` and `torch==2.11.0` are still the resolved versions in `uv.lock` (`awk '/^name = "torch"/,/^$/' uv.lock` shows `version = "2.11.0"`; `awk '/^name = "vllm"/,/^$/' uv.lock` shows `version = "0.20.1"`). No version bump required for M6.1.1; if the lockfile diverges from M6.1's pins, halt and reconcile. ([R-2](./research.md))
- [ ] T003 [P] Confirm M6.1's harness modules (`m6_1_torch_pin`, `m6_1_seed`, `m6_1_seq_len`, `m6_1_drift_check`, `m6_engine_cost`) are importable from `tools/benchmark/src/vllm_grpc_bench/` and that their public APIs match M6.1's published shapes. M6.1.1 reuses these unchanged per [plan.md Project Structure](./plan.md). Run `python -c "from vllm_grpc_bench import m6_1_torch_pin, m6_1_seed, m6_1_seq_len, m6_1_drift_check, m6_engine_cost; print('ok')"`.

**Checkpoint**: Setup complete. Foundational phase can begin.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared M6.1.1 plumbing — types, perturbation-budget gate, magnitude-equivalence classifier, contracts heading validator, supersedence annotation writers, CLI flag wiring. All 3 user stories depend on this phase.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. The classifier, the exit codes, the sentinel-object schema, and the CLI dispatch are shared across Phase 1 mini-sweep + Phase 2 (a/b/c/d) outcomes + supersedence annotation flow.

### Data-model types (shared across all stories)

- [ ] T004 [P] Define `M6_1_1Cell` (alias for `M6_1Cell`), `M6_1_1Cohort` (alias for `M6_1Cohort`), `CheckpointName` / `SegmentName` / `Phase1Classification` / `Phase2Path` / `BaselineSource` / `M6_1_1ExitCode` literals, `TimingCheckpoint`, `PerSegmentDelta`, `PerSegmentAggregate`, `MultiPointTimings`, `Phase1RunRecord`, `PerturbationAudit`, `EmbedRegressionResult`, `EmbedRegressionCheckResult`, `BaselineCellEntry`, `BaselineSentinel`, `Phase2aVerifiedOutcome` / `Phase2bDocumentedOutcome` / `DriftNotReproducedConfirmedOutcome` / `SplitRequiredOutcome` discriminated union, `Phase2Choice`, `M6_1_1RunMeta`, `M6_1_1Run` as Pydantic v2 dataclasses in `tools/benchmark/src/vllm_grpc_bench/m6_1_1_types.py` (NEW) per [data-model.md](./data-model.md) shapes and validation rules. Re-export `EngineCostSpan` and `EngineCostAggregate` from `m6_types.py` unchanged. Define module-level constants: `M6_1_1_BASE_SEED = 42`, `PERTURBATION_BUDGET_NS = 500_000`, `DRIFT_NOT_REPRODUCED_THRESHOLD = 0.05`, `ATTRIBUTION_THRESHOLD = 0.80`, `EMBED_REGRESSION_TOLERANCE = 0.05`, `CHAT_STREAM_DRIFT_CLEARED_TOLERANCE = 0.05`.
- [ ] T005 [P] Add pytest unit tests for `m6_1_1_types` in `tools/benchmark/tests/test_m6_1_1_types.py` (NEW): assert `M6_1_1Cell(path="embed", concurrency=1, hidden_size=4096)` round-trips through `model_dump_json` + `model_validate_json`; assert the literal types reject unknown labels at validation time (`Phase1Classification("foo")` raises); assert `M6_1_1Run` enforces non-empty `phase_1_runs[]`; assert the discriminated `Phase2Outcome` union validates the right concrete shape per `phase_2_path`.

### Magnitude-equivalence classifier (FR-010, round-1 Q1)

- [ ] T006 [P] Implement `classify_cell(cell, per_cohort) -> Phase1Classification` in `tools/benchmark/src/vllm_grpc_bench/m6_1_1_classifier.py` (NEW) per [data-model.md § Phase1Classification](./data-model.md). The function MUST: (1) compute `spread(x) = max(x) − min(x)` over the three per-cohort means of `engine_ttft_ms`; (2) short-circuit to `drift_not_reproduced` iff `spread(engine_ttft) / mean(engine_ttft) < 0.05`; (3) check `spread(seg_ab_ms) / spread(engine_ttft_ms) ≥ 0.80` → `instrumentation_artifact`; (4) check `spread(seg_bc_ms) / spread(engine_ttft_ms) ≥ 0.80` → `channel_dependent_batching`; (5) otherwise return `inconclusive`. Pure function; no I/O, no randomness. Document the formula in the docstring so an operator reading code can verify by hand against `contracts/output.md` § "Multi-Point Timing Table" rows.
- [ ] T007 [P] Add pytest unit tests for `m6_1_1_classifier` in `tools/benchmark/tests/test_m6_1_1_classifier.py` (NEW): construct synthetic `per_cohort` inputs and assert each of the 4 outcomes is reachable:
  - all 3 cohorts within 4% spread → `drift_not_reproduced`
  - spread concentrated in `seg_ab` (≥80% of `engine_ttft` spread) → `instrumentation_artifact`
  - spread concentrated in `seg_bc` (≥80%) → `channel_dependent_batching`
  - spread evenly distributed (e.g., 50/50 between `seg_ab` and `seg_bc`) → `inconclusive`
  - edge case: `seg_cd` carries 100% of spread (post-engine emit asymmetry) → `inconclusive` (neither `seg_ab` nor `seg_bc` meets threshold) — matches spec Edge Cases line 105
  - edge case: non-monotonic cohort ordering (rest > tuned but seg_ab tuned > rest) → `inconclusive`

### Perturbation budget hard gate (FR-012, round-2 Q3)

- [ ] T008 [P] Implement `check_perturbation_budget(phase_1_run_record) -> PerturbationAudit` + `raise_if_exceeded(audit) -> None` (raises `SystemExit(4)`) in `tools/benchmark/src/vllm_grpc_bench/m6_1_1_perturbation.py` (NEW). The check MUST: (1) iterate all (cohort, cell) pairs in the run record; (2) compute mean `perturbation_audit_ns / 1000` per pair; (3) return a `PerturbationAudit` instance with `exceeded = True` and the offending pair list iff any mean exceeds 500.0 µs; (4) `raise_if_exceeded` calls `sys.exit(4)` with a stderr message naming the offending pair(s) per `contracts/cli.md` exit-code-4 message shape.
- [ ] T009 [P] Add pytest unit tests for `m6_1_1_perturbation` in `tools/benchmark/tests/test_m6_1_1_perturbation.py` (NEW): synthetic run record with all per-RPC `perturbation_audit_ns` ≤ 100,000 → no exceeded; synthetic record with one (cohort, cell) pair averaging 600 µs → `exceeded == True`; assert `raise_if_exceeded` exits code 4 via `pytest.raises(SystemExit)` and the captured stderr matches the contracts/cli.md regex.

### Contracts heading validator (FR-016, round-3 Q2, contracts/instrumentation.md § Phase 2(b))

- [ ] T010 [P] Implement `validate_contracts_heading(path="contracts/instrumentation.md") -> tuple[str, str] | None` in `tools/benchmark/src/vllm_grpc_bench/m6_1_1_contracts_check.py` (NEW). The function MUST: (1) read the file at `path`; (2) search line-by-line for the regex `^## M6\.1\.1: `; (3) return `(matched_line_verbatim, path)` on first match; (4) return `None` if no match. Used by Phase 2(b) finalisation (`m6_1_1_phase2`) to gate `phase_2_path = "phase_2b_documented"`.
- [ ] T011 [P] Add pytest unit tests for `m6_1_1_contracts_check` in `tools/benchmark/tests/test_m6_1_1_contracts_check.py` (NEW): synthetic markdown file with a valid `## M6.1.1: Channel-Dependent Batching Effect` heading → returns the line; file without the heading → returns `None`; file with the heading but at h3 (`### M6.1.1: ...`) → returns `None` (heading-level matters); use `tmp_path` fixture for the file system isolation.

### Supersedence annotation writers (FR-023, FR-024, round-3 Q2)

- [ ] T012 [P] Implement `write_methodology_supersedence_json(m6_1_path, m6_1_1_report_path, phase_2_path, summary)` and `write_methodology_supersedence_markdown(m6_1_md_path, m6_1_1_md_path)` in `tools/benchmark/src/vllm_grpc_bench/m6_1_1_supersedence.py` (NEW) per `contracts/output.md` § "Supersedence annotations". The JSON writer MUST: (1) read M6.1's JSON; (2) add a top-level `methodology_supersedence` key with `{pointer, schema_version, phase_2_path, summary}` shape; (3) write the file back preserving all other top-level keys exactly (order, whitespace MUST stay byte-stable for the round-trip; use a Pydantic-friendly writer with `model_dump(by_alias=True, exclude_none=False)` then JSON-serialise with `sort_keys=False`, `indent=2`). The markdown writer MUST add a single new line `> **Methodology supersedence (YYYY-MM-DD)**: see ` immediately under the chat_stream verdict section header (regex-match the existing heading and insert after it).
- [ ] T013 [P] Implement `write_per_row_supersedence_notes(m6_1_md_path, affected_rows, m6_1_1_baseline_section_anchor)` in the same `m6_1_1_supersedence.py`. Called only when `phase_2_choice.embed_regression_acknowledged == True`; appends an inline note `⚠ embed_regression_acknowledged: ...` to each affected (cell × cohort) row of M6.1's `supersedes_m6_under_enable_prompt_embeds` table per FR-015c.
- [ ] T014 [P] Add pytest unit tests for `m6_1_1_supersedence` in `tools/benchmark/tests/test_m6_1_1_supersedence.py` (NEW): synthetic M6.1 JSON without `methodology_supersedence` key → annotation added, all other fields byte-stable (compare pre/post via `json.loads` and assert dict equality on every original key); JSON already with `methodology_supersedence` → overwritten not duplicated; markdown writer adds one line below the chat_stream verdict heading at the right position; `write_per_row_supersedence_notes` adds the inline note to exactly the affected rows.

### CLI flag wiring (FR-025, contracts/cli.md)

- [ ] T015 Add `--m6_1_1-diagnose` and `--m6_1_1` (mutually exclusive top-level flags) and the namespaced flags listed in `contracts/cli.md` (`--m6_1_1-modal-region`, `--m6_1_1-modal-token-env`, `--m6_1_1-modal-endpoint`, `--m6_1_1-skip-deploy`, `--m6_1_1-base-seed`, `--m6_1_1-model`, `--m6_1_1-m6-1-baseline`, `--m6_1_1-report-out`, `--m6_1_1-report-json-out`, `--m6_1_1-events-sidecar-out`, `--m6_1_1-allow-engine-mismatch`) to `tools/benchmark/src/vllm_grpc_bench/__main__.py`, mirroring the existing `--m6_1` flag namespace. Wire both `--m6_1_1-diagnose` and `--m6_1_1` to argparse mutual-exclusion against all earlier mode flags (`--m3`, `--m4`, `--m5`, `--m5_1`, `--m5_1-smoke`, `--m5_2`, `--m5_2-smoke`, `--m6`, `--m6-smoke`, `--m6_1`, `--m6_1-smoke`). Dispatch `--m6_1_1-diagnose` to a new `run_m6_1_1_diagnose(...)` entry point and `--m6_1_1` to `run_m6_1_1_phase_2(...)` (implementations land in US1 T020 and US2 T026 respectively).
- [ ] T016 [P] Add pytest test for the M6.1.1 CLI surface in `tools/benchmark/tests/test_m6_1_1_cli.py` (NEW): assert all M6.1.1 flags parse with documented defaults per `contracts/cli.md`; assert `--m6_1_1-diagnose` + `--m6_1_1` rejection; assert `--m6_1_1` + `--m6_1` rejection; assert `--m6_1_1-skip-deploy` without `--m6_1_1-modal-endpoint` rejection; assert exit-code mapping matches `contracts/cli.md` § "Exit codes" (codes 1–5; code 2 from torch-pin failure at startup; code 4 from perturbation gate; code 5 from split_required). Use the same `_bypass_torch_pin(monkeypatch)` helper M6.1's tests use to bypass the FR-003 torch-pin gate for tests that exercise other gates.

**Checkpoint**: Foundational ready. User story implementation can now begin.

---

## Phase 3: User Story 1 — Phase 1 diagnostic mini-sweep (Priority: P1) 🎯 MVP

**Goal**: Run a 6-cell × 3-cohort × n=50 mini-sweep against Modal A10G eu-west-1 with the four-checkpoint instrumentation enabled on both REST and gRPC chat_stream paths; produce a multi-point timing table per cohort per cell, per-segment deltas with bootstrapped 95% CIs, and a deterministic FR-010 classification label per chat_stream cell.

**Independent Test**: Drive `python -m vllm_grpc_bench --m6_1_1-diagnose --m6_1_1-modal-region=eu-west-1` against Modal with M6.1's baseline JSON present and a fresh Modal deployment. Verify (1) the published markdown report's executive section contains a classification label per chat_stream cell, (2) the multi-point timing table has 18 rows with all 4 checkpoint + 3 segment delta values populated, (3) the JSON's `phase_1_runs[]` contains exactly one full record with per-cohort timings and the perturbation audit, (4) the FR-010 classifier output is reproducible by hand from the published table, (5) all 5 exit codes (1–5) are reachable from the corresponding upstream conditions.

### Server-side instrumentation (FR-006, FR-007, FR-008, R-1)

- [ ] T017 [US1] Modify `scripts/python/modal_bench_rest_grpc_server.py` REST chat_stream FastAPI handler per `contracts/instrumentation.md` § "REST wire format": capture 4 `time.perf_counter_ns()` checkpoints (`handler_entry`, `pre_engine`, `first_chunk`, `terminal_emit`) and emit them as a `m6_1_1_timings` sub-object on the terminal SSE event JSON payload. Also capture `perturbation_audit_ns` (the self-measured cost of the 4 checkpoint calls). Existing M6 / M6.1 SSE fields (`engine_ttft_ms`, `engine_tpot_ms`, `engine_forward_ms`) MUST be preserved EXACTLY (no key reorder, no removal, no rename — regression-tested in T037). Capture identically on embed RPCs (FR-011 audit-only controls). Document the four checkpoint sites with inline comments naming each checkpoint per the contract.
- [ ] T018 [US1] Modify `packages/frontend/src/vllm_grpc_frontend/chat.py` gRPC `ChatServicer` chat_stream method (around the existing `engine_ttft_ms` capture at `chat.py:77-84`) per `contracts/instrumentation.md` § "gRPC wire format": capture 4 `time.perf_counter_ns()` checkpoints (same names as T017) and emit them as additional trailing-metadata keys prefixed `m6_1_1_t_` (`m6_1_1_t_handler_entry`, `m6_1_1_t_pre_engine`, `m6_1_1_t_first_chunk`, `m6_1_1_t_terminal_emit`, `m6_1_1_t_perturbation_audit_ns`). Existing M6 trailing-metadata keys (`engine-ttft-ms`, `engine-tpot-ms`) MUST be preserved EXACTLY.
- [ ] T018a [P] [US1] Modify `packages/frontend/src/vllm_grpc_frontend/completions.py` gRPC `CompletionsServicer` for embed RPC paths (around the existing `engine_ttft_ms` / `engine_forward_ms` captures at `completions.py:99` + `completions.py:161-170`): capture the same 4 `time.perf_counter_ns()` checkpoints + `perturbation_audit_ns` and emit them as `m6_1_1_t_*` trailing-metadata keys. Embed cells are FR-011 audit-only controls — the wire-format emission shape is identical to chat_stream's per FR-008. Existing M6 trailing-metadata keys (`engine-forward-ms`, `engine-ttft-ms`) MUST be preserved EXACTLY.

### Client-side timing extraction (FR-007, FR-008, R-3)

- [ ] T019 [P] [US1] Implement `extract_rest_timings(sse_terminal_event: dict) -> TimingCheckpoint | None` and `extract_grpc_timings(trailing_md: dict[str, str]) -> TimingCheckpoint | None` and `compute_per_segment_delta(ckpt: TimingCheckpoint) -> PerSegmentDelta` in `tools/benchmark/src/vllm_grpc_bench/m6_1_1_timing.py` (NEW). Both extractors MUST: (1) attempt to read the M6.1.1 sub-object / prefixed keys; (2) return `TimingCheckpoint(...)` on success; (3) return `None` if any required field is absent (best-effort fallback per [R-3](./research.md) — silently skip when M6.1.1 instrumentation isn't running). `compute_per_segment_delta` is a pure conversion (ns → ms × 1e-6) per FR-009.
- [ ] T020 [P] [US1] Add pytest unit tests for `m6_1_1_timing` in `tools/benchmark/tests/test_m6_1_1_timing.py` (NEW): synthetic SSE terminal event with `m6_1_1_timings` sub-object → returns populated `TimingCheckpoint`; SSE event without the sub-object (M6 / M6.1 server) → returns `None`; gRPC trailing metadata with `m6_1_1_t_*` keys → returns populated; trailing metadata missing one key → returns `None` (no partial extraction); `compute_per_segment_delta` produces correct ms values from ns inputs; per-segment monotonicity is implicit (assert delta values ≥ 0 in the synthetic input).

### REST shim integration (FR-007, R-3)

- [ ] T021 [US1] Modify `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` to invoke `m6_1_1_timing.extract_rest_timings(terminal_event)` when parsing the terminal SSE event JSON; populate the per-RPC event record with the extracted `TimingCheckpoint` alongside the existing engine_cost trio. Existing M6 / M6.1 paths UNCHANGED — the extraction is best-effort and silently skips when the sub-object is absent.

### gRPC client integration (FR-008, R-3)

- [ ] T022 [US1] Modify the gRPC chat_stream client extraction in `tools/benchmark/src/vllm_grpc_bench/m6_engine_cost.py` (or a new helper in `m6_1_1_timing.py` invoked by the existing gRPC engine_cost extraction) to invoke `m6_1_1_timing.extract_grpc_timings(trailing_md)` and populate the per-RPC event record with the result. Same best-effort semantics as T021.

### Phase 1 diagnose orchestrator (FR-005, FR-013, round-3 Q1)

- [ ] T023 [US1] Implement `run_m6_1_1_diagnose(args) -> M6_1_1ExitCode` in `tools/benchmark/src/vllm_grpc_bench/m6_1_1_diagnose.py` (NEW). The orchestrator MUST:
  1. Call `m6_1_torch_pin.validate_torch_version()` (raises `SystemExit(2)` on mismatch — FR-003).
  2. Call M6.1's baseline loader on `--m6_1_1-m6-1-baseline` path; abort with exit code `1` if missing/malformed (FR-001).
  3. Optionally check `run_meta.engine_version` against the deployed version (FR-004); if mismatch and `--m6_1_1-allow-engine-mismatch` is False, exit `1`.
  4. Deploy (or reuse via `--m6_1_1-skip-deploy`) the Modal app with the 4-checkpoint instrumentation.
  5. Pin `seq_len` at sweep start via `m6_1_seq_len.pin_seq_len_at_sweep_start(...)`.
  6. Run the 6 cells × 3 cohorts × n=50 measurement RPCs + n=10 warmup per cohort, reusing M6.1's sequencer + warmup pattern from `m6_1_sweep` via composition.
  7. Aggregate per-cohort means + 95% CI half-widths (bootstrap n_boot=10,000) for `engine_ttft_ms`, `seg_ab_ms`, `seg_bc_ms`, `seg_cd_ms` per FR-009.
  8. Compute `PerturbationAudit` via `m6_1_1_perturbation.check_perturbation_budget(...)`; if exceeded, `m6_1_1_perturbation.raise_if_exceeded(...)` (exit code 4 — FR-012).
  9. Classify each chat_stream cell via `m6_1_1_classifier.classify_cell(...)` (FR-010).
  10. Read the existing M6.1.1 JSON file (if present); parse phase_1_runs[]; append the new `Phase1RunRecord`; handle corrupted/missing existing files per round-3 Q1 (stderr warning + start fresh).
  11. Apply the FR-017 / FR-018 re-run gate: if mixed segment-level classifications OR any `inconclusive` cell on a single run, OR uniform `drift_not_reproduced` on a single run → exit code 3.
  12. Apply the FR-017(b) / FR-018 split gate: if second run still divergent → write `phase_2_path = "split_required"`, return exit code 5.
  13. On uniform `drift_not_reproduced` after second run → write `phase_2_path = "drift_not_reproduced_confirmed"`, emit M6.1 supersedence annotations (US3 T032), return exit code 0.
  14. On uniform actionable classification (segment-level or first-run-and-no-rerun-needed) → write `phase_2_path = "phase_2_pending"`, return exit code 0.
  15. Always call `m6_1_1_reporter.write_m6_1_1_report(...)` (US1 T025) to publish markdown + JSON.
- [ ] T024 [US1] Add pytest test for `run_m6_1_1_diagnose` exit-code path coverage in `tools/benchmark/tests/test_m6_1_1_diagnose.py` (NEW). Use the `_bypass_torch_pin` pattern from M6.1's tests. Cover:
  - missing baseline → exit code 1
  - engine version mismatch without `--allow` flag → exit code 1
  - synthetic Phase 1 results triggering each classifier outcome → correct `phase_1_classifications` field + correct exit code (3 for mixed / inconclusive / drift_not_reproduced single-run)
  - `phase_1_runs[]` append-on-re-read: invoke twice; assert array grows to length 2 with the most recent run's data at index `-1`
  - corrupted existing JSON → starts fresh with stderr warning per round-3 Q1
  - perturbation budget exceeded → exit code 4 from `m6_1_1_perturbation`

### Phase 1 reporter (FR-019, FR-020, FR-021)

- [ ] T025 [US1] Implement `write_m6_1_1_report(run: M6_1_1Run, md_path: Path, json_path: Path) -> None` in `tools/benchmark/src/vllm_grpc_bench/m6_1_1_reporter.py` (NEW) per `contracts/output.md` § "Markdown report shape" + § "JSON companion shape". The reporter MUST emit:
  - **Markdown** (6 sections per FR-020 in fixed order): Executive Summary, Methodology, Multi-Point Timing Table (one sub-section per `phase_1_runs[]` entry; one table row per (cohort × cell) — 18 rows × N runs), Root-Cause Attribution (per chat_stream cell, with the formula applied), Phase 2 Outcome (branches on `phase_2_path`), Methodology Supersedence.
  - **JSON** (schema_version `m6_1_1.v1`): all top-level keys present per `contracts/output.md` § "JSON companion shape" — `run_id`, `run_meta`, `phase_1_classifications`, `phase_1_runs[]`, `multi_point_timings`, `phase_2_outcome`, `chat_stream_baseline_post_symmetrisation` (sentinel under non-Phase-2(a)), `embed_baseline_post_symmetrisation` (sentinel under non-Phase-2(a)), `embed_regression_check` (null under non-Phase-2(a)), `phase_2_choice` (null when not applicable), `m6_1_baseline_pointer`, `methodology_supersedence`.
  - Sentinel-object dispatch logic (round-2 Q1 / Q2): under `phase_2_path = "phase_2_pending"`, both baseline sentinels carry `baseline_source = "not_applicable"`, `pointer = null`, `cells = null` until US2 T028 populates them.
  - JSON serialisation via Pydantic `model_dump_json(indent=2)` for stable diffability.
- [ ] T026 [US1] Add pytest unit + golden-file tests for the M6.1.1 reporter in `tools/benchmark/tests/test_m6_1_1_reporter.py` (NEW). Cover:
  - synthetic `M6_1_1Run` with `phase_2_path = "phase_2_pending"` and one `Phase1RunRecord` → markdown contains 6 sections in order with no Phase 2 numbers; JSON has all top-level keys; sentinel-object `baseline_source == "not_applicable"`.
  - synthetic run with `phase_1_runs[]` length 2 → markdown renders both Multi-Point Timing Table sub-sections; JSON's top-level `multi_point_timings` reflects only the most recent run per round-3 Q1.
  - Reproducer test: a hand-constructed multi-point timing table → the FR-010 formula's classification output matches the published label (SC-010).
  - JSON strict-superset round-trip (M6.1-aware consumer reads M6.1.1's JSON): load M6.1's `engine_cost_baseline` keys and assert they're either present in M6.1.1's JSON or correctly sentinelled.

**Checkpoint**: User Story 1 functional. Phase 1 mini-sweep produces a deterministic classification per chat_stream cell with a reproducible-by-hand formula and an append-only `phase_1_runs[]` history.

---

## Phase 4: User Story 2 — Phase 2 fix-or-document with fresh baselines (Priority: P2)

**Goal**: Branch on Phase 1's classification (round-3 Q2 dispatch): under uniform `instrumentation_artifact` apply a symmetrisation code change (data-driven; identified by Phase 1's per-segment table) and run the n=100 verification sweep with embed regression check + fresh chat_stream + embed baselines (FR-014, FR-015, FR-015a, FR-015b, FR-015c); under uniform `channel_dependent_batching` validate `contracts/instrumentation.md` has the `m6_1_1`-keyed heading and flip `phase_2_path = "phase_2b_documented"` without a Modal sweep (FR-016).

**Independent Test**: After US1 has produced a Phase 1 report, run `python -m vllm_grpc_bench --m6_1_1 --m6_1_1-modal-region=eu-west-1`. Verify (1) under uniform `instrumentation_artifact`: harness runs n=100 sweep, publishes `chat_stream_baseline_post_symmetrisation` with 9 cells, publishes `embed_baseline_post_symmetrisation` with 9 cells, publishes `embed_regression_check` with 9 entries each within ±5% of M6.1's published mean, flips `phase_2_path = "phase_2a_verified"`. (2) Under uniform `channel_dependent_batching` with a valid `## M6.1.1: ...` heading in `contracts/instrumentation.md`: harness runs no sweep, flips `phase_2_path = "phase_2b_documented"`, sentinel objects render with `baseline_source = "m6_1"`. (3) Under non-actionable Phase 1 state: exit code 1 with actionable stderr.

### Embed regression check (FR-015b, R-8)

- [ ] T027 [P] [US2] Implement `compute_embed_regression(per_cohort_results: dict, m6_1_baseline: dict) -> EmbedRegressionCheckResult` in `tools/benchmark/src/vllm_grpc_bench/m6_1_1_embed_regression.py` (NEW). Per `contracts/output.md` § "Embed regression check": for each (embed cell × cohort), compute `delta_pct = (m6_1_1_engine_forward_ms_mean - m6_1_engine_forward_ms_mean) / m6_1_engine_forward_ms_mean`; flag `embed_regression_warning = abs(delta_pct) > 0.05`; aggregate into `EmbedRegressionCheckResult` with `n_warnings`, `all_within_tolerance`, `acknowledged_count` (the last reads `phase_2_choice.embed_regression_acknowledged`).
- [ ] T028 [P] [US2] Add pytest unit tests for `m6_1_1_embed_regression` in `tools/benchmark/tests/test_m6_1_1_embed_regression.py` (NEW): all 9 entries within ±2% → `all_within_tolerance == True`, `n_warnings == 0`; one entry at +6% drift → `n_warnings == 1`; acknowledged path reads from `Phase2Choice.embed_regression_acknowledged`.

### Phase 2 orchestrator (FR-014, FR-015, FR-015a, FR-015b, FR-015c, FR-016, round-3 Q2)

- [ ] T028a [US2] **Apply the Phase 2(a) symmetrisation code change** (ONLY applicable when the most-recent Phase 1 returned uniform `instrumentation_artifact` across all 3 chat_stream cells). The specific edit is **data-driven** and identified by reading the per-segment table in `m6_1_1-engine-cost-instrumentation.md` § "Multi-Point Timing Table"; the three options per `contracts/instrumentation.md` § "Phase 2(a) symmetrisation shape" are:
  - **Option A — move REST's pre-engine bracket forward**: edit `scripts/python/modal_bench_rest_grpc_server.py` so the REST handler's `engine_start = perf_counter()` captures *after* FastAPI ASGI deserialisation (aligns REST with gRPC's tighter bracket).
  - **Option B — move gRPC's pre-engine anchor backward**: edit `packages/frontend/src/vllm_grpc_frontend/chat.py` so the gRPC servicer's `engine_ttft_ms` bracket starts at the servicer entry rather than the post-tokenise point (aligns gRPC with REST's wider bracket).
  - **Option C — move BOTH paths to a common canonical point** (e.g., immediately before `engine.generate(...)`): edits in BOTH files; produces the strictest engine-only reading and is the methodologically cleanest choice per `contracts/instrumentation.md`.
  Commit the symmetrisation edit on the M6.1.1 branch BEFORE invoking T029's `--m6_1_1` verification sweep — T029 reads the deployment from the working tree.
  **NOT applicable** under Phase 2(b) / `drift_not_reproduced_confirmed` / `split_required` outcomes — those paths require NO code change.
  **No pre-committed implementation** at /speckit-plan time per round-1 Q3 "diagnose-first" discipline: the edit is determined by Phase 1's data, never by guesswork. If Phase 1's data is ambiguous (segment-level breakdown unclear), re-run `--m6_1_1-diagnose` before committing to an option.
- [ ] T029 [US2] Implement `run_m6_1_1_phase_2(args) -> M6_1_1ExitCode` in `tools/benchmark/src/vllm_grpc_bench/m6_1_1_phase2.py` (NEW). The orchestrator MUST:
  1. Reuse the torch-pin + baseline + engine-version gates from T023 (factor into a shared `validate_preconditions(args)` helper if not already).
  2. Read the existing `m6_1_1-engine-cost-instrumentation.json`; refuse with exit code 1 ("`--m6_1_1` requires a prior `--m6_1_1-diagnose`") if the file is absent.
  3. Read `phase_1_classifications` from the most recent run.
  4. Branch per round-3 Q2:
     - **Uniform `instrumentation_artifact`**: deploy fresh Modal app; run the full 6-cell × 3-cohort × n=100 verification sweep; aggregate per-cohort `engine_ttft_ms` means + CIs; compute `engine_cost_drift_warning` per cell (cleared iff each cohort within 5% of unweighted cohort-average); compute `chat_stream_control_drift_warning` via M6.1's existing `m6_1_drift_check` module (expected to fire per round-1 Q2); call `compute_embed_regression` (T027); populate `chat_stream_baseline_post_symmetrisation` cells (9 entries) and `embed_baseline_post_symmetrisation` cells (9 entries) with `baseline_source = "m6_1_1"`; emit `Phase2aVerifiedOutcome`; flip `phase_2_path = "phase_2a_verified"`; if any `embed_regression_warning` fires AND `phase_2_choice.embed_regression_acknowledged` is False → DO NOT auto-close (return exit code 1 with a message asking the operator to either revert or acknowledge); if acknowledged → call `write_per_row_supersedence_notes` (T013) on affected rows.
     - **Uniform `channel_dependent_batching`**: NO Modal sweep; call `m6_1_1_contracts_check.validate_contracts_heading()` (T010); on miss → exit code 1 with stderr "update contracts/instrumentation.md with `## M6.1.1: <title>` heading"; on hit → populate baseline sentinels with `baseline_source = "m6_1"`, `pointer = "docs/benchmarks/m6_1-real-prompt-embeds.json"`; emit `Phase2bDocumentedOutcome` carrying the matched heading line; flip `phase_2_path = "phase_2b_documented"`.
     - **Any other state** (`drift_not_reproduced_confirmed`, `split_required`, `inconclusive`, mixed segment-level on a single run) → exit code 1 with state-specific stderr.
  5. Always call `m6_1_1_reporter.write_m6_1_1_report` (T025) to overwrite the M6.1.1 markdown + JSON with the Phase 2 outcome.
  6. Under non-error termination, call US3 supersedence writers (T032 / T013 if applicable).
- [ ] T030 [US2] Add pytest test for `run_m6_1_1_phase_2` branch coverage in `tools/benchmark/tests/test_m6_1_1_phase2.py` (NEW). Use mocks for the Modal sweep so the test runs locally. Cover:
  - existing JSON missing → exit code 1
  - `phase_1_classifications` uniform `instrumentation_artifact` + n=100 mocked outputs cleared → `Phase2aVerifiedOutcome`, exit 0, sentinel `baseline_source = "m6_1_1"`, embed regression check passes
  - same + one embed cohort outside ±5% → `embed_regression_warning` fires, milestone refuses to close → exit code 1; with `phase_2_choice.embed_regression_acknowledged = True` → exit 0 + per-row supersedence notes written
  - uniform `channel_dependent_batching` + contracts heading present → exit 0, `Phase2bDocumentedOutcome` with matched line captured
  - same + contracts heading absent → exit code 1 with actionable stderr
  - `drift_not_reproduced_confirmed` state → exit code 1 ("Phase 2 already finalised by Phase 1 second-run confirmation")
  - `split_required` state → exit code 1 ("milestone closed at split_required; open successor sub-milestones")

### Fresh baseline emission (FR-015a, FR-015c, round-2 Q1 / Q2)

- [ ] T031 [P] [US2] Implement `build_chat_stream_baseline(...)` and `build_embed_baseline(...)` helpers in `m6_1_1_reporter.py` (extending T025). Each produces a `BaselineSentinel` instance per `data-model.md` § "BaselineSentinel". Under Phase 2(a), populate `cells` with the 9 (cell × cohort) entries from the verification sweep; under all other paths, populate the sentinel shape per the dispatch table in `data-model.md` § "BaselineSentinel". The reporter (T025) reads these and serialises into the JSON's top-level keys.

**Checkpoint**: User Story 2 functional. Phase 2 produces the appropriate terminal `phase_2_path` and emits fresh baselines (or sentinels) that M6.2 can consume via the round-2 Q1 / Q2 dispatch.

---

## Phase 5: User Story 3 — Methodology supersedence preserving M6.1's verdict table (Priority: P3)

**Goal**: M6.1's published verdict table (`supersedes_m6_under_enable_prompt_embeds` rows + cohort selection + cell shape) MUST NOT be re-computed. M6.1.1 adds (1) a top-level `methodology_supersedence` key to M6.1's JSON, (2) a one-line forward pointer in M6.1's markdown chat_stream verdict section, (3) per-row supersedence notes on affected `supersedes_m6_under_enable_prompt_embeds` rows under `embed_regression_acknowledged == True`. Annotations are additive; M6.1's other fields are byte-stable.

**Independent Test**: After M6.1.1's PR merges, open `docs/benchmarks/m6_1-real-prompt-embeds.md` and scroll to the chat_stream verdict section: a one-line forward pointer to `m6_1_1-engine-cost-instrumentation.md` is present. Open `docs/benchmarks/m6_1-real-prompt-embeds.json` and verify `methodology_supersedence` is the only new top-level key (every other M6.1 field byte-stable). A deterministic test (T034) verifies the pointer's target file exists. M6.2's spec writer reads the pointer and dispatches correctly per the round-2 Q1 / Q2 sentinel-object schema.

### Supersedence orchestration (FR-023, FR-024, round-3 Q1 / Q2)

- [ ] T032 [US3] Wire `m6_1_1_supersedence.write_methodology_supersedence_json` and `write_methodology_supersedence_markdown` (T012) into both `run_m6_1_1_diagnose` (T023) — at the `drift_not_reproduced_confirmed` close — and `run_m6_1_1_phase_2` (T029) — at the `phase_2a_verified` / `phase_2b_documented` closes. The annotation is written by the SAME invocation that publishes M6.1.1's report, in the SAME PR (FR-023 / SC-006). Under `embed_regression_acknowledged == True`, additionally call `write_per_row_supersedence_notes` (T013).
- [ ] T033 [US3] Add pytest integration test for the supersedence flow in `tools/benchmark/tests/test_m6_1_1_supersedence_integration.py` (NEW) using `tmp_path` for both M6.1 file fixtures and M6.1.1 outputs. Cover:
  - `phase_2a_verified` close → M6.1's JSON has new `methodology_supersedence` key with `summary` describing instrumentation_artifact resolution; M6.1's markdown has the one-line forward pointer; every other M6.1 JSON field byte-stable.
  - `phase_2b_documented` close → `methodology_supersedence.summary` names the channel_dependent_batching documented finding.
  - `drift_not_reproduced_confirmed` close → `methodology_supersedence.summary` records "non-reproduction in two independent n=50 Phase 1 mini-sweeps".
  - `split_required` close → M6.1's files are NOT modified (the supersedence annotation is deferred to the successor sub-milestones).
  - `embed_regression_acknowledged == True` → per-row supersedence notes appended to the affected rows; non-affected rows unchanged.

### Pointer-target validation (SC-006)

- [ ] T034 [P] [US3] Add a deterministic test in `tools/benchmark/tests/test_m6_1_1_supersedence_pointer.py` (NEW) that, after a Phase 2 close, asserts the `pointer` field in `m6_1-real-prompt-embeds.json:methodology_supersedence` resolves to an existing file relative to the repository root. (Catches typos or path drift in CI before merge.)

**Checkpoint**: User Story 3 functional. M6.1's published artifacts gain the additive supersedence annotation in the same PR that publishes M6.1.1.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Strict-superset compatibility validation, sidecar events, lint chain pass, integration smoke, documentation updates.

- [ ] T035 [P] Strict-superset JSON validation test in `tools/benchmark/tests/test_m6_1_1_json_strict_superset.py` (NEW). Load M6.1's `docs/benchmarks/m6_1-real-prompt-embeds.json` (or a frozen fixture copy) and assert every top-level key is reachable in M6.1.1's published JSON (under Phase 2(a) verification, the `engine_cost_baseline` section MUST be present; under non-Phase-2(a) outcomes the sentinel-object schema MUST cover the dispatch case). M6.1.1's NEW top-level keys MUST NOT collide with any M6.1 key.
- [ ] T036 [P] Sidecar JSONL events writer in `m6_1_1_reporter.py` per `contracts/output.md` § "Sidecar events". Each per-RPC event record is appended as one JSONL line; runs are separated by a `{"_run_separator": true, "run_id": "..."}` line. Add a pytest test in `tools/benchmark/tests/test_m6_1_1_sidecar.py` (NEW) asserting line format + run-separator behaviour.
- [ ] T037 [P] M6 / M6.1 SSE + trailing-metadata regression test in `tools/benchmark/tests/test_m6_1_1_wire_preserves_m6.py` (NEW): synthetic M6 / M6.1 server response (without M6.1.1 fields) parsed by both M6.1's M6 / M6.1 engine_cost extractor AND M6.1.1's `extract_rest_timings` / `extract_grpc_timings` extractors. The M6 extractor MUST produce identical `EngineCostSpan` data with vs without M6.1.1's `m6_1_1_timings` sub-object / `m6_1_1_t_*` keys present (FR-007 / FR-008 "existing M6 fields preserved exactly").
- [ ] T038 Quickstart validation: follow [`quickstart.md`](./quickstart.md) end-to-end on a small fixture (use the fake Modal server or a Modal preview deploy, NOT the full ~75 min Phase 2(a) sweep) and verify every documented step produces the expected outcome. Update `quickstart.md` if any step is stale.
- [ ] T038a Validate SC-002 + SC-007 wall-clock budgets against actual measured Phase 1 / Phase 2(a) data on the published M6.1.1 JSON. Read `phase_1_runs[].wall_clock_s`; assert each Phase 1 run < 2700 s (45 min); assert total across two-run fallback paths < 5400 s (90 min); under Phase 2(a) outcomes, assert `phase_2_outcome.wall_clock_s` (if recorded by reporter) < 4500 s (75 min). Record the actual numbers in the PR description for audit trail. If any budget is exceeded: halt PR; either retune the harness (e.g., reduce warmup count) or amend SC-002 / SC-007 with the measured ceiling + a short justification in spec.md.
- [ ] T039 Run the local lint chain per [`feedback_local_lint_chain`](../../specs/022-m6-1-real-prompt-embeds/checklists/requirements.md) memory: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy --strict src`, `uv run pytest` under `tools/benchmark/`. All four MUST be green. Commit any necessary fixups (e.g., `mypy --strict` may flag missing return annotations on new helpers).
- [ ] T040 [P] Update `docs/PLAN.md` § M6.1.1 to mark the milestone as "delivered YYYY-MM-DD" (mirrors M6.1's flip from "planned" to "delivered" at merge time). Update `docs/PLAN.md` § M6.2 to remove the "post-M6.1.1" qualifier in the heading. Update `README.md`'s roadmap to flip M6.1.1's status accordingly.
- [ ] T041 [P] Re-index graphify per `CLAUDE.md` § "graphify": run `graphify update .` after all code changes have landed to keep the local graph current. Verify `graphify-out/GRAPH_REPORT.md` reflects the 10 new `m6_1_1_*` modules.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion; BLOCKS all user stories.
- **User Story 1 (Phase 3, P1, MVP)**: Depends on Foundational completion. Delivers Phase 1 diagnostic mini-sweep + multi-point timing + classification.
- **User Story 2 (Phase 4, P2)**: Depends on US1 completion (Phase 2 reads US1's published Phase 1 classifications). Delivers Phase 2 fix-or-document workflow + fresh baselines.
- **User Story 3 (Phase 5, P3)**: Depends on US2 completion (supersedence is written by the Phase 2 close). Delivers M6.1 supersedence annotations preserving the verdict table.
- **Polish (Phase 6)**: Depends on all three user stories completing.

### User Story Dependencies (within M6.1.1)

- US1 is the MVP: Phase 1 mini-sweep + classifier output. Operator can stop here and read the diagnosis even without Phase 2.
- US2 builds on US1: requires US1's `phase_1_classifications` field to branch the Phase 2 path.
- US3 builds on US2: supersedence annotations are written at the Phase 2 close (or at the `drift_not_reproduced_confirmed` close in US1's T023).

### Within Each User Story

- Tests in this milestone are written ALONGSIDE implementation (the FR-010 classifier and FR-012 perturbation gate are pure functions amenable to TDD; the Modal-deployment-dependent integration is exercised via mocks).
- Module under test before its consumer: types (T004) → classifier (T006) → orchestrator (T023).

### Parallel Opportunities

- **Phase 1 Setup**: T002, T003 in parallel after T001.
- **Phase 2 Foundational**: T004–T014 all marked [P] across distinct files; T015–T016 form a sequential pair (T015 modifies `__main__.py`, T016 tests it).
- **Phase 3 US1**: T017 + T018 sequential (same file: Modal server entrypoint); T019, T020 parallel; T021, T022 parallel after T019; T023 sequential after all above; T024, T025, T026 can interleave.
- **Phase 4 US2**: T027 + T028 parallel; T029 sequential after T027 + classifier + reporter; T030, T031 can interleave.
- **Phase 5 US3**: T032 sequential (wires into T023 + T029); T033 + T034 parallel after T032.
- **Phase 6 Polish**: T035–T037 + T040–T041 all parallelizable across distinct files; T038, T039 sequential at the end.

---

## Parallel Example: User Story 1

```bash
# After T017+T018 land the server-side checkpoints, the client-side extraction can be parallelized:
Task: "T019 [P] [US1] Implement extract_rest_timings / extract_grpc_timings / compute_per_segment_delta in m6_1_1_timing.py"
Task: "T020 [P] [US1] Add pytest tests for m6_1_1_timing in test_m6_1_1_timing.py"

# T021 and T022 are different files (rest_shim.py and m6_engine_cost.py) — parallel:
Task: "T021 [US1] Wire m6_1_1_timing.extract_rest_timings into rest_shim.py"
Task: "T022 [US1] Wire m6_1_1_timing.extract_grpc_timings into m6_engine_cost.py"

# T024 (CLI test), T025 (reporter), T026 (reporter test) — different files, parallelizable:
Task: "T024 [US1] CLI exit-code coverage test in test_m6_1_1_diagnose.py"
Task: "T025 [US1] write_m6_1_1_report in m6_1_1_reporter.py"
Task: "T026 [US1] Golden-file + reproducer test for reporter in test_m6_1_1_reporter.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T003).
2. Complete Phase 2: Foundational (T004–T016).
3. Complete Phase 3: User Story 1 (T017–T026).
4. **STOP and VALIDATE**: Run Phase 1 diagnose against Modal eu-west-1; verify the multi-point timing table + classifier output reproduce by hand.
5. The classification answer is the primary deliverable — depending on the outcome, the next step is either US2 Phase 2(a) (if `instrumentation_artifact`) or US2 Phase 2(b) (if `channel_dependent_batching`) or close-immediately (if `drift_not_reproduced_confirmed` after a second Phase 1 run) or split-the-milestone (if `split_required`).

### Incremental Delivery

1. Setup + Foundational → Foundation ready.
2. US1 → run Phase 1; read the classification → MVP delivered.
3. US2 → branch on classification; complete Phase 2 → milestone substantially complete.
4. US3 → write supersedence annotations → milestone closed; ready for PR / merge / `git push`.
5. Polish → lint chain green; quickstart validated; docs updated.

### Parallel Team Strategy

Single-developer milestone (per project convention). If a second developer is available:
- Developer A: Phase 2 Foundational (T004–T016) + US1 (T017–T026).
- Developer B: US2 mocks + tests + reporter golden files (T027, T028, T030, T031, T033, T034) — can be drafted against the data model without waiting for US1's Modal-dependent code.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks.
- [Story] label maps task to specific user story for traceability.
- Each user story is independently completable and testable.
- Tests SHOULD pass before merging the task that introduces them; the per-milestone test convention is `tools/benchmark/tests/test_m6_1_1_*.py`.
- Commit after each task or logical group (the project uses `git commit` per logical unit, not per file).
- M6.1's published artifacts (`docs/benchmarks/m6_1-real-prompt-embeds.{md,json}`) are READ-ONLY except for the additive `methodology_supersedence` annotation in US3.
- Under Phase 2(a), the specific symmetrisation code change is NOT pre-committed at /speckit-plan time — Phase 1's per-segment table identifies the edit. The implementation task for the symmetrisation lands AFTER US1 publishes Phase 1's data; the operator opens a follow-up PR (or extends the M6.1.1 branch) with the specific edit before invoking `--m6_1_1`.
- Constitution Principle II forbids vLLM source modification. If the symmetrisation requires changes inside `vllm/`, halt M6.1.1 and file an upstream issue per [`quickstart.md`](./quickstart.md) § "When to STOP".
- Per project memory `feedback_check_merged_before_repro`, before drafting any task: verify the fix isn't already on `main` from a recent merge (e.g., if M6.1's recent handshake-dict fix already addressed a corner case M6.1.1 was about to re-fix).
