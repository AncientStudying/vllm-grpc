---
description: "Task list for M4 — Time-Axis Channel & Schema Tuning"
---

# Tasks: M4 — Time-Axis Channel & Schema Tuning

**Input**: Design documents from `/specs/016-m4-time-axis-tuning/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Tests are **REQUIRED** for this milestone (Constitution IV "CI is the Merge Gate" + research.md R-13 — harness mechanics are CI-tested with deterministic small fixtures; the operator-driven full sweep is not part of CI). Test tasks below precede the implementation they validate.

**Organization**: Tasks are grouped by user story (US1 / US2 / US3) so each story can be implemented and tested independently per the spec's priority ordering. Within each story, tests come before implementation; implementation honors the spec's FRs and the contracts under `specs/016-m4-time-axis-tuning/contracts/`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- All file paths are repository-relative

## Path Conventions

- Harness modules: `tools/benchmark/src/vllm_grpc_bench/`
- Harness tests: `tools/benchmark/tests/`
- Integration tests: `tests/integration/`
- Production proto: `proto/vllm_grpc/v1/` (untouched in M4)
- Candidate proto namespace: `proto/vllm_grpc/v1/m4-candidates/` (new)
- Generated stubs: `packages/gen/` (production) and `packages/gen/vllm_grpc_m4_candidates/` (candidates)
- Published reports: `docs/benchmarks/`

---

## Phase 1: Setup (Pre-Flight)

**Purpose**: Confirm the workspace is healthy before extending it.

- [ ] T001 Verify `make proto` regenerates production stubs cleanly with no diff against committed state (pre-flight; protects subsequent US3 changes from masking unrelated drift)
- [ ] T002 [P] Verify `uv run pytest tools/benchmark/tests/` is currently green on the merge base (defines the test surface M4 extends)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Extend shared dataclasses and verdict literals that every story consumes.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T003 Extend `tools/benchmark/src/vllm_grpc_bench/m3_types.py`: add `"client_bound"` to the `Verdict` literal (preserve `"noise_bounded"` for M3-report compatibility); add `BaselineRole` literal (`"m1_shared"`, `"frozen_channel"`); add new dataclasses `ExpansionRecord`, `FrozenChannelBaseline`, `SupersessionEntry`, and `M4SweepConfig` per `specs/016-m4-time-axis-tuning/data-model.md`
- [ ] T004 Extend `Cohort` and `Run` dataclasses in `tools/benchmark/src/vllm_grpc_bench/m3_types.py` with the M4 additions (`Cohort`: `is_baseline`, `baseline_role`, `expansion_record`, `client_bound`, `time_to_first_token_seconds` cohort-level summary; `Run`: `pacing_mode`, `shared_baseline_cohort_ids`, `frozen_channel_baselines`, `supersedes`, `candidate_sizing_policy`, `loopback_caveat_axes`) per `data-model.md` (depends on T003 — same file)
- [ ] T005 [P] Add unit tests for the seven validation invariants from `data-model.md` § "Validation invariants" in `tools/benchmark/tests/test_m4_types.py` (no `noise_bounded` in M4; shared-baseline coverage; frozen-baseline coverage; expansion-record presence; TTFT presence on chat_stream; loopback-caveat consistency; supersession completeness)

**Checkpoint**: Foundation ready — US1, US2, US3 may begin.

---

## Phase 3: User Story 1 — Redesigned Harness Produces Defensible Time Verdicts (Priority: P1) 🎯 MVP

**Goal**: Add no-pacing mode to the mock engine, add shared-baseline orchestration, promote TTFT to a first-class chat_stream verdict metric, add `client_bound` cohort detection, and add the borderline-expand sample-size cascade. This is the *prerequisite axis* named in `docs/PLAN.md` — without it, no M4 verdict is defensible.

**Independent Test** (per spec US1 acceptance scenarios): a reviewer runs a small `--m4` sweep with `--no-pacing` and `--shared-baseline` enabled and confirms (a) chat_stream cohort total wall-clock under no-pacing is materially lower than under paced mode, (b) exactly one M1_BASELINE cohort per path is recorded, (c) chat_stream verdicts are computed on TTFT and labeled, (d) two consecutive shared-baseline runs produce baseline cohorts whose 95% CIs overlap.

### Tests for User Story 1 (write FIRST, ensure they FAIL before implementation)

- [ ] T006 [P] [US1] Test: `MockEngineConfig(pace_tokens=False)` produces a chat_stream cohort whose mean wall-clock is materially lower than the paced default, in `tools/benchmark/tests/test_mock_engine.py` (covers acceptance scenario US1.1 / FR-001)
- [ ] T007 [P] [US1] Test: shared-baseline orchestrator records exactly one M1_BASELINE cohort per path for an entire run, in `tools/benchmark/tests/test_m4_sweep.py` (covers acceptance scenario US1.2 / FR-002)
- [ ] T008 [US1] Test: borderline-expand mechanic — a candidate cohort whose initial 95% CI overlaps the baseline's 95% CI is replaced (not appended) by an n=250 re-measurement; non-overlapping cohort is not, in `tools/benchmark/tests/test_m4_sweep.py` (covers FR-002 / R-4) (depends on T007 — same file)
- [ ] T009 [P] [US1] Test: `client_bound` detection — a candidate cohort whose mean delta vs. baseline is below baseline within-cohort std-dev is tagged `client_bound` and excluded from `recommend` tallies, in `tools/benchmark/tests/test_m4_client_bound.py` (covers FR-004 / R-5)
- [ ] T010 [P] [US1] Test: baseline-CV failure path — when shared-baseline cohort variance exceeds `--baseline-cv-max`, the harness exits 3 with a diagnostic and emits no verdicts, in `tools/benchmark/tests/test_m4_baseline_cv.py` (covers FR-005 / R-11)
- [ ] T011 [P] [US1] Test: TTFT-first-class verdict — the recommendation builder labels chat_stream verdicts as TTFT-driven and emits the per-cohort TTFT summary as a first-class field (not a re-analysis-only field), in `tools/benchmark/tests/test_m4_recommendations.py` (covers acceptance scenario US1.3 / FR-003 / R-10)

### Implementation for User Story 1

- [ ] T012 [US1] Add `pace_tokens: bool = True` field to `MockEngineConfig` in `tools/benchmark/src/vllm_grpc_bench/mock_engine.py`; relax `tokens_per_second` validation when `pace_tokens=False` (FR-001 / R-1)
- [ ] T013 [US1] Update streaming loop in `tools/benchmark/src/vllm_grpc_bench/mock_engine.py` to skip `await asyncio.sleep(interval)` when `pace_tokens=False` (depends on T012 — same file)
- [ ] T014 [P] [US1] Extract TTFT-derivation helpers from `tools/benchmark/src/vllm_grpc_bench/m3_sweep.py` into a new shared module `tools/benchmark/src/vllm_grpc_bench/ttft.py` so M3 reanalyze and M4 sweep consume identical math (R-10)
- [ ] T015 [P] [US1] Create `tools/benchmark/src/vllm_grpc_bench/m4_sweep.py` skeleton with `run_m4_sweep(config: M4SweepConfig) -> Run` signature, M4SweepConfig import, and stub helpers (`measure_shared_baseline`, `measure_candidate`, `build_recommendations`, `validate_run`)
- [ ] T016 [US1] Implement shared-baseline orchestration AND the four-axis sweep driver loop in `tools/benchmark/src/vllm_grpc_bench/m4_sweep.py`: measure the M1_BASELINE cohort once per path at n ≥ `config.baseline_n`; record cohort id + metadata; populate `Run.shared_baseline_cohort_ids` and tag the cohorts with `is_baseline=True, baseline_role="m1_shared"`. Then drive the four-axis sweep: for each `(axis, width, path, candidate_config)` tuple from `config.axes × config.widths × config.paths × <per-axis candidate configs>`, where the per-axis candidate config list comes from the existing `tools/benchmark/src/vllm_grpc_bench/channel_config.py` module (M3's named presets per axis — reused unchanged in M4), invoke `measure_candidate` against the shared baseline at n ≥ `config.candidate_n` and append the resulting cohort to `Run.cohorts` (FR-002 / FR-006 / R-2) (depends on T015)
- [ ] T017 [US1] Implement baseline-CV check in `tools/benchmark/src/vllm_grpc_bench/m4_sweep.py`: compute coefficient of variation on the time metric across the baseline cohort; abort with exit 3 and a stderr diagnostic naming the cohort id and observed CV when it exceeds `config.baseline_cv_max` (FR-005 / R-11) (depends on T016 — same file)
- [ ] T018 [US1] Implement borderline-expand mechanic in `tools/benchmark/src/vllm_grpc_bench/m4_sweep.py`: detect CI overlap (`candidate.ci_low ≤ baseline.ci_high AND candidate.ci_high ≥ baseline.ci_low`); replace the n=100 cohort with an n=250 re-measurement (do not append samples); populate `ExpansionRecord` on the cohort (FR-002 / R-4) (depends on T017 — same file)
- [ ] T019 [US1] Implement `client_bound` detection in `tools/benchmark/src/vllm_grpc_bench/m4_sweep.py`: tag a candidate cohort `client_bound=True` when `(candidate.wall_clock_mean - baseline.wall_clock_mean)` is smaller than the baseline cohort's within-cohort std-dev; exclude such cohorts from `recommend` tallies (FR-004 / R-5) (depends on T018 — same file)
- [ ] T020 [US1] Implement `m4_sweep.build_recommendations(run: Run) -> list[Recommendation]` in `tools/benchmark/src/vllm_grpc_bench/m4_sweep.py`: apply the FR-008 strict-CI-clearance rule (candidate's 95% CI strictly clears the comparison baseline's 95% CI under the metric's direction-of-improvement) to each non-baseline cohort against its shared-baseline reference; for chat_stream cohorts use TTFT (consumes `tools/benchmark/src/vllm_grpc_bench/ttft.py` from T014) as the primary verdict metric and record total wall-clock as a secondary diagnostic; for embed cohorts use total per-RPC wall-clock as the primary metric; exclude `client_bound`-tagged cohorts from `recommend` tallies (FR-003 / FR-008 / R-10) (depends on T014, T019)
- [ ] T021 [US1] Add CLI flags to `tools/benchmark/src/vllm_grpc_bench/__main__.py` per `specs/016-m4-time-axis-tuning/contracts/m4-bench-cli.md`: `--m4`, `--no-pacing`, `--paced`, `--shared-baseline`, `--per-axis-baseline`, `--baseline-n`, `--candidate-n`, `--expand-n`, `--baseline-cv-max`, `--widths`, `--paths`, `--axes`, `--out`. Validate mutual-exclusion and arithmetic (`--candidate-n < --expand-n`) with exit code 2 on violation
- [ ] T022 [US1] Wire `--m4` flag to invoke `m4_sweep.run_m4_sweep` in `tools/benchmark/src/vllm_grpc_bench/__main__.py` (depends on T021 — same file; depends on T020 for the recommendation builder)
- [ ] T023 [P] [US1] Test: CLI flag wiring (defaults, mutual-exclusion `--no-pacing` vs `--paced`, mutual-exclusion `--shared-baseline` vs `--per-axis-baseline`, exit code 2 on arithmetic violation, exit code 3 on baseline-CV failure) in `tools/benchmark/tests/test_m4_cli.py` (covers contract `m4-bench-cli.md`)

**Checkpoint**: User Story 1 complete — the harness mechanics work end-to-end on a small fixture; the four acceptance scenarios from spec US1 pass. The full M4 sweep is not yet wired (no channel sweep, no schema candidates) but the methodology infrastructure is in place and verifiable.

---

## Phase 4: User Story 2 — Definitive Channel Sweep Closes M3's Noise-Bounded Cells (Priority: P2)

**Goal**: Run the four-axis channel sweep (`max_message_size`, keepalive, compression, HTTP/2 framing) at hidden_size 2048 / 4096 / 8192 against the shared M1_BASELINE for both paths, attach loopback caveat notes to the deterministic axis set, build the per-path frozen-channel baselines that US3 consumes, and emit the published M4 report including the Supersedes M3 table.

**Independent Test** (per spec US2 acceptance scenarios): a reviewer reads `docs/benchmarks/m4-time-axis-tuning.md` and confirms (a) every chat_stream and embed cell M3 marked `noise_bounded` carries a non-`noise_bounded` M4 verdict, (b) every `recommend` cites a 95% CI strictly clearing the shared-baseline's 95% CI, (c) the Supersedes M3 table maps each superseded M3 cell with a one-line rationale, (d) loopback-masked axes carry the FR-010 caveat note.

### Tests for User Story 2

- [ ] T024 [P] [US2] Test: `validate_run` rejects construction of a `Recommendation(verdict="noise_bounded")` from the M4 sweep, in `tools/benchmark/tests/test_m4_validator.py` (covers FR-007)
- [ ] T025 [P] [US2] Test: loopback-caveat tagging is deterministic — single-host runs always tag `{keepalive, http2_framing} ∩ axes` with the caveat regardless of observed deltas, in `tools/benchmark/tests/test_m4_loopback_caveat.py` (covers FR-010 / R-6)
- [ ] T026 [P] [US2] Test: per-path frozen-channel baseline composition — for each path, the cohort combines that path's per-axis winners at hidden_size 4096; absent any winner, the axis falls back to M3 default; the combined config is measured as its own n ≥ 100 cohort, in `tools/benchmark/tests/test_m4_frozen_baseline.py` (covers FR-011 / R-3)
- [ ] T027 [P] [US2] Test: `m4_supersede` reads `docs/benchmarks/m3-channel-tuning-time.json` and produces a `SupersessionEntry` for every M3 cell with verdict `noise_bounded`, mapping to the matching M4 cell on `(path, hidden_size, axis, config_name)`, in `tools/benchmark/tests/test_m4_supersede.py` (covers FR-007 / FR-009)
- [ ] T028 [P] [US2] Test: M4 JSON output is a strict superset of M3's `m3-channel-tuning-time.json` schema — every M3 top-level field and every M3 per-cohort field is preserved with identical semantics; M4-only fields are additive, in `tools/benchmark/tests/test_m4_report_schema.py` (covers FR-015 / contract `m4-report-schema.md` / R-7)

### Implementation for User Story 2

- [ ] T029 [US2] Implement per-path frozen-channel baseline composition in `tools/benchmark/src/vllm_grpc_bench/m4_sweep.py`: after the channel sweep completes, for each path build a `ChannelConfig` combining that path's per-axis winners at hidden_size 4096 (M3-default for axes with no winner); measure as a cohort at n ≥ `config.baseline_n`; record `FrozenChannelBaseline` and tag the cohort with `is_baseline=True, baseline_role="frozen_channel"` (FR-011 / R-3) (depends on US1 complete)
- [ ] T030 [US2] Implement loopback caveat tagging in `tools/benchmark/src/vllm_grpc_bench/m4_sweep.py`: when run topology is single-host, set `Run.loopback_caveat_axes = list({"keepalive", "http2_framing"} ∩ set(config.axes))` (FR-010 / R-6) (depends on T029 — same file)
- [ ] T031 [US2] Implement `validate_run(run)` in `tools/benchmark/src/vllm_grpc_bench/m4_sweep.py` enforcing the seven invariants from `data-model.md` § "Validation invariants" — most importantly FR-007 (no `noise_bounded`); raise `ValueError` (mapped to exit code 4) on violation (depends on T030 — same file)
- [ ] T032 [P] [US2] Create `tools/benchmark/src/vllm_grpc_bench/m4_supersede.py`: read `docs/benchmarks/m3-channel-tuning-time.json` (verdicts live on the top-level `recommendations` array, NOT on cohort records); for each entry in `m3.recommendations` whose `verdict == "noise_bounded"`, resolve its `cell_id` to the matching M3 cohort and generate a `SupersessionEntry(m3_cell_id, m3_verdict, m4_cell_id, m4_verdict, rationale)` against the matching M4 cell on `(path, hidden_size, axis, config_name)` (FR-007 / FR-009)
- [ ] T033 [US2] Extend `tools/benchmark/src/vllm_grpc_bench/reporter.py` to emit the M4 markdown layout: methodology preamble, per-axis × per-width × per-path verdict table (TTFT-driven for chat_stream, total wall-clock for embed), per-path frozen-channel baseline summary, Supersedes M3 table, loopback-caveat notes section, expansion-records section (FR-009 / FR-016)
- [ ] T034 [US2] Extend `tools/benchmark/src/vllm_grpc_bench/reporter.py` to emit the M4 JSON in the strict-superset schema per `specs/016-m4-time-axis-tuning/contracts/m4-report-schema.md`: every M3 field preserved verbatim; M4 additions written under the new top-level and per-cohort keys (FR-015 / R-7) (depends on T033 — same file)
- [ ] T035 [P] [US2] Integration test: end-to-end small-fixture `--m4 --skip-schema` run for one chat_stream and one embed cell at hidden_size 4096 emits a non-`noise_bounded` verdict, populates a `SupersessionEntry`, and writes JSON readable by an M3-shape parser, in `tests/integration/test_m4_sweep_e2e.py`

**Checkpoint**: User Story 2 complete — the channel sweep produces a definitive M4 report with verdicts for every M3 `noise_bounded` cell. US3 may now begin (it consumes the per-path frozen-channel baselines from T029).

---

## Phase 5: User Story 3 — Schema Candidates Measured Against the New Baseline (Priority: P3)

**Goal**: Author the three deferred-from-M3 schema candidates as isolated `.proto` files under `proto/vllm_grpc/v1/m4-candidates/`, regenerate stubs via `make proto`, measure each candidate independently against its per-path frozen-channel baseline at hidden_size 4096 (4096-first cascade; expand to 2048 + 8192 on `recommend` or borderline), and append the Schema Candidates section + Negative-results appendix to the M4 report.

**Independent Test** (per spec US3 acceptance scenarios): a reviewer reads the schema-candidates section of `docs/benchmarks/m4-time-axis-tuning.md` and confirms (a) each named candidate has a verdict at hidden_size 4096 against the per-path frozen baseline, (b) bytes and time deltas with 95% CIs are reported per candidate, (c) candidates with `recommend` or borderline 4096 results are also measured at 2048 and 8192, (d) candidates with overlapping CIs on both metrics appear in the Negative-results appendix.

### Tests for User Story 3

- [ ] T036 [P] [US3] Test: candidate stub compilation — `from packages.gen.vllm_grpc_m4_candidates import packed_token_ids, oneof_flattened_input, chunk_granularity` succeeds after `make proto`, in `tools/benchmark/tests/test_m4_proto_candidates.py` (covers Constitution I + contract `m4-proto-candidates.md`)
- [ ] T037 [P] [US3] Test: schema-candidate cascade rule — at hidden_size 4096, a `recommend` candidate triggers re-measurement at 2048 and 8192; an overlapping-CI candidate does not; the cascade decision is recorded in the per-candidate result, in `tools/benchmark/tests/test_m4_schema_cascade.py` (covers FR-013 + spec Assumptions)
- [ ] T038 [P] [US3] Test: schema-candidate verdict pairs against the per-path frozen baseline (not the shared M1_BASELINE, not M3's bytes baseline), in `tools/benchmark/tests/test_m4_schema_baseline.py` (covers FR-011)
- [ ] T039 [P] [US3] Test: a schema candidate with overlapping CIs on both bytes and time at all measured widths is recorded as a negative result with full supporting numbers and named in the Negative-results appendix, in `tools/benchmark/tests/test_m4_schema_negative_appendix.py` (covers FR-014 / Constitution V)
- [ ] T039a [P] [US3] Test: `--schema-candidates=<csv>` filters which schema candidates run; `--skip-schema` skips US3 entirely (no schema cohorts measured, no schema section in the report); both flags appear in `--help` output, in `tools/benchmark/tests/test_m4_cli_schema.py` (covers contract `m4-bench-cli.md` for the US3-introduced flags from T046)

### Implementation for User Story 3

- [ ] T040 [P] [US3] Create directory `proto/vllm_grpc/v1/m4-candidates/` with a `.gitkeep` placeholder and a `README.md` explaining that this namespace holds isolated candidate proto files for M4 measurement and is **not** wired into production proxy/frontend/client code
- [ ] T041 [P] [US3] Author `proto/vllm_grpc/v1/m4-candidates/packed_token_ids.proto` per `specs/016-m4-time-axis-tuning/contracts/m4-proto-candidates.md` § "Candidate (a)": minimal candidate variation against production chat-completion shape that exercises packed encoding control on the token-id field
- [ ] T042 [P] [US3] Author `proto/vllm_grpc/v1/m4-candidates/oneof_flattened_input.proto` per `specs/016-m4-time-axis-tuning/contracts/m4-proto-candidates.md` § "Candidate (b)": replaces the production `oneof` input union with a flat message + explicit kind enum
- [ ] T043 [P] [US3] Author `proto/vllm_grpc/v1/m4-candidates/chunk_granularity.proto` per `specs/016-m4-time-axis-tuning/contracts/m4-proto-candidates.md` § "Candidate (c)": candidate streaming chunk message with a configurable chunk-size hint (1, 4, 16 tokens per chunk drive separate cohorts)
- [ ] T044 [US3] Update `Makefile` (or equivalent build script) to include `proto/vllm_grpc/v1/m4-candidates/*.proto` in the `make proto` target so stubs land in `packages/gen/vllm_grpc_m4_candidates/<candidate>/` (Constitution I — `make proto` is the only stub generator) (depends on T041, T042, T043)
- [ ] T045 [US3] Implement schema-candidate cohort building in `tools/benchmark/src/vllm_grpc_bench/m4_sweep.py`: import the matching candidate stubs (only when measuring that cohort); serialize messages through the candidate proto; measure the cohort against the per-path frozen baseline at hidden_size 4096; cascade to 2048 + 8192 on `recommend` or borderline; record per-width per-metric verdict (FR-011 / FR-012 / FR-013) (depends on T029 from US2 and T044)
- [ ] T046 [US3] Add `--schema-candidates`, `--skip-schema` CLI flags to `tools/benchmark/src/vllm_grpc_bench/__main__.py` per `specs/016-m4-time-axis-tuning/contracts/m4-bench-cli.md` (depends on T021 — same file)
- [ ] T047 [US3] Extend `tools/benchmark/src/vllm_grpc_bench/reporter.py` with the Schema Candidates section (per-candidate, per-width verdict table; bytes and time deltas with CIs; cascade outcome) and the Negative-results appendix (per FR-014) (depends on T034 — same file)
- [ ] T048 [P] [US3] Integration test: end-to-end small-fixture `--m4` run for one schema candidate at hidden_size 4096 emits a per-candidate verdict against the per-path frozen baseline; a candidate with both metrics overlapping baseline CIs lands in the Negative-results appendix, in `tests/integration/test_m4_schema_e2e.py`

**Checkpoint**: All three user stories complete — full M4 sweep runs end-to-end against fixtures.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation updates, full-sweep validation, publication of the M4 report.

- [ ] T049 [P] Update `docs/PLAN.md` § "M4 — Time-Axis Channel & Schema Tuning" to mark the milestone "active" once US1 (Phase B) lands, and add per-US delivery notes as US2 and US3 land
- [ ] T050 [P] Update `README.md` "Milestone Roadmap" section if the M4 deliverable summary changes (e.g., once schema candidates produce a winner, the M4 line should mention it)
- [ ] T051 Run `specs/016-m4-time-axis-tuning/quickstart.md` validation locally on a quiet commodity host: full `--m4` sweep; verify exit 0; confirm `docs/benchmarks/m4-time-axis-tuning.{md,json}` materializes; spot-check that the JSON is parseable by an M3-shape reader (FR-015 / SC-005)
- [ ] T052 (Operator-driven, post-T051) Commit the published `docs/benchmarks/m4-time-axis-tuning.{md,json}` from the validated sweep run; include the run's seed and host details in the markdown's methodology preamble
- [ ] T053 Update `docs/PLAN.md` to mark M4 as **delivered** once T052 lands; cross-link the M4 report from the milestone overview

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — pre-flight only.
- **Phase 2 (Foundational)**: Depends on Setup completion. **Blocks all user stories** (T003, T004 introduce types every story consumes).
- **Phase 3 (US1)**: Depends on Phase 2. The MVP — closing US1 alone delivers the harness redesign that downstream milestones (M5, M6) inherit.
- **Phase 4 (US2)**: Depends on Phase 2 and Phase 3 (US2 measures candidates against the shared baseline US1 introduces). Per-path frozen-channel baselines from US2 (T029) gate US3.
- **Phase 5 (US3)**: Depends on Phase 2, US1 (Phase 3) for the harness, and US2 (T029 specifically) for the per-path frozen-channel baselines.
- **Phase 6 (Polish)**: Depends on the user stories the operator chooses to publish. T051 / T052 require all three user stories complete to publish a full report; if M4 is shipped incrementally, partial reports may publish after US1+US2 (skipping US3 with `--skip-schema`).

### User Story Dependencies

- **US1 (P1)**: No dependencies on other user stories. This is the MVP — shipping just US1 already delivers the harness redesign. M5 / M6 inherit it.
- **US2 (P2)**: Depends on US1 (uses the shared-baseline orchestrator + TTFT-first-class verdict + `client_bound` detection + borderline-expand). Independently testable in the sense that the `docs/benchmarks/m4-time-axis-tuning.md` channel-sweep section is reviewable against M3 cells without needing US3.
- **US3 (P3)**: Depends on US1 (harness) and on US2's per-path frozen-channel baseline (T029). Independently testable: the schema-candidates section of the report is reviewable on its own merits (does each candidate have a verdict at hidden_size 4096 against the per-path frozen baseline?).

### Within Each User Story

- Tests are written FIRST and FAIL before implementation (Constitution IV).
- Models / dataclass extensions before services / orchestration logic.
- Orchestration logic before CLI wiring.
- CLI wiring before integration tests.
- Story complete before moving to the next priority.

### Parallel Opportunities

- T001, T002 (Phase 1) are independent → both [P]-eligible.
- T005 (Phase 2) is independent of T003/T004 since it only writes a new test file → [P].
- US1 tests (T006, T007, T009, T010, T011) live in different files → all [P]-eligible. T008 is sequential within `test_m4_sweep.py` after T007.
- US1 implementation: T014, T015 are different files from each other and from existing modules → both [P]. T012/T013 are sequential within `mock_engine.py`. T016–T020 are sequential within `m4_sweep.py`.
- US2 tests (T024–T028) live in different files → all [P]-eligible.
- US2 implementation: T029–T031 are sequential within `m4_sweep.py`; T032 is in a new file → [P]. T033/T034 are sequential within `reporter.py`. T035 is a different file → [P].
- US3 tests (T036–T039, T039a) live in different files → all [P]-eligible.
- US3 implementation: T040–T043 are different files → all [P]-eligible. T044 (Makefile) depends on T041–T043. T045 / T046 / T047 are each in single files within their phase. T048 is a new file → [P].
- Polish: T049 / T050 are different files → both [P].

### Story-Level Parallelism

Once Phase 2 is complete, US2 cannot start until US1 (Phase 3) lands the shared-baseline orchestrator, and US3 cannot start until US2 lands the per-path frozen-channel baseline (T029). The stories are *priority-ordered* but not *fully independent* in the sense that US2's verdicts depend on US1's mechanics and US3's verdicts depend on US2's frozen baselines. Within each phase, however, the parallel opportunities above hold.

---

## Parallel Example: User Story 1 Tests

```bash
# Launch all US1 tests (modulo T008 which sequences after T007 in the same file):
uv run pytest tools/benchmark/tests/test_mock_engine.py::test_pace_tokens_false &
uv run pytest tools/benchmark/tests/test_m4_sweep.py::test_shared_baseline_one_per_path &
uv run pytest tools/benchmark/tests/test_m4_client_bound.py &
uv run pytest tools/benchmark/tests/test_m4_baseline_cv.py &
uv run pytest tools/benchmark/tests/test_m4_recommendations.py::test_ttft_first_class &
wait
```

## Parallel Example: User Story 3 Proto Authoring

```bash
# T041, T042, T043 are different files — author in parallel:
edit proto/vllm_grpc/v1/m4-candidates/packed_token_ids.proto      # T041
edit proto/vllm_grpc/v1/m4-candidates/oneof_flattened_input.proto # T042
edit proto/vllm_grpc/v1/m4-candidates/chunk_granularity.proto     # T043
make proto   # T044 — sequenced after the three .proto files exist
```

---

## Implementation Strategy

### MVP (User Story 1 Only)

1. Phase 1: Setup (T001, T002)
2. Phase 2: Foundational (T003 → T004 → T005)
3. Phase 3: User Story 1 (T006–T023)
4. **STOP and VALIDATE**: Run a small `--m4 --skip-schema --axes=compression --widths=4096 --paths=chat_stream` sweep; confirm the four US1 acceptance scenarios pass.
5. Decision point: ship US1 standalone (delivers methodology to M5 / M6) or proceed to US2.

### Incremental Delivery

1. US1 → harness + small-fixture verification → optional partial PR.
2. US2 → channel sweep + Supersedes M3 table → optional partial PR (this satisfies SC-001 / SC-002).
3. US3 → schema candidates + Negative-results appendix → final PR (this satisfies SC-003).
4. T051 / T052 → published `docs/benchmarks/m4-time-axis-tuning.{md,json}` from the validated sweep.

### Bundled Delivery (single PR for the whole milestone)

1. Phase 1 → Phase 2 → US1 → US2 → US3 → Phase 6 in one branch; PR description summarizes all three user stories. This matches M3's PR cadence (PR #17 closed P1 channel sweep + harness; PR #18/#19 followed for the time re-analysis). Choice between incremental and bundled is a workflow concern (deferred from `/speckit-clarify`); both paths are supported by the dependency graph.

---

## Notes

- **Constitution I (Proto-First)**: T040–T044 are the only proto-touching work. Production `proto/vllm_grpc/v1/{chat,completions}.proto` is **not** edited — candidates live in the `m4-candidates/` sibling namespace. Stubs land via `make proto` only; no hand-written equivalents.
- **Constitution V (Honest Measurement)**: T019 (`client_bound`), T030 (loopback caveat), T039 + T047 (negative-results appendix), T031 (`validate_run` rejects `noise_bounded`) are the four enforcement points. Removing or weakening any of them constitutes a constitution violation that requires plan amendment.
- **Test independence**: every `[P]` test task above writes to a distinct file. Tasks marked sequential (e.g., T008 after T007) share a file; running them in parallel would cause merge conflicts.
- **Adoption is out of scope**: A `recommend` verdict from T045 does not modify production proto. Adoption is a follow-up change tracked separately and is a maintainer judgment call.
- **Cross-host transport mode is out of scope**: T030's loopback caveat is the in-scope mechanism. Cross-host re-measurement to upgrade `keepalive` / `http2_framing` verdicts is deferred to a future milestone (per spec Assumptions).
