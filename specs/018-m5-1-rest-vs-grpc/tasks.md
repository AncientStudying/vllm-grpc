# Tasks: M5.1 — REST vs gRPC Head-to-Head on Real Wire

**Input**: Design documents from `/specs/018-m5-1-rest-vs-grpc/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Test tasks are included — the spec's Functional Requirements (FR-001..FR-016) require harness mechanics to be unit-tested (Constitution IV) and the plan's Phase G is "Tests". TDD discipline: write/update tests before or alongside implementation; verify they fail prior to implementing the matching production code.

**Organization**: Tasks are grouped by user story (US1, US2, US3) so each story can be implemented and validated independently.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Required for user-story phase tasks (US1, US2, US3); absent on Setup, Foundational, and Polish
- Every task includes an exact file path

## Path Conventions

- Harness package: `tools/benchmark/src/vllm_grpc_bench/`
- Harness unit tests: `tools/benchmark/tests/`
- Repo-level integration tests: `tests/integration/`
- Modal-deploy scripts: `scripts/python/`
- Spec docs: `specs/018-m5-1-rest-vs-grpc/`
- Reports: `docs/benchmarks/`
- Narrative surfaces: `README.md`, `docs/benchmarks/summary.md`, `docs/PLAN.md`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the existing harness package layout is ready for M5.1's additive modules; no new top-level project is created (M5.1 extends M5).

- [X] T001 Confirm M5 baselines exist and are loadable by reading `docs/benchmarks/m5-cross-host-validation.json` and verifying the per-axis `recommend` verdicts and per-(path × hidden_size) frozen-channel composition logic are accessible from `tools/benchmark/src/vllm_grpc_bench/channel_config.py` (no edits expected; this is a precondition check that emits an actionable error if the M5 file is missing or malformed).
- [X] T002 [P] Add a `--m5_1`-aware section header to `tools/benchmark/src/vllm_grpc_bench/__main__.py`'s `--help` output stub (no flag parsing yet — placeholder comment block introducing the M5.1 family so reviewers can locate the new code; flags themselves land in T040).
- [X] T003 [P] Create empty module files (each with a one-line docstring stub) at `tools/benchmark/src/vllm_grpc_bench/m5_1_sweep.py`, `tools/benchmark/src/vllm_grpc_bench/m5_1_supersede.py`, and `tools/benchmark/src/vllm_grpc_bench/rest_cohort.py` so subsequent tasks have a target file to extend rather than creating from scratch.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Additive dataclasses in `m3_types.py` and modal-endpoint provider extension. These types underpin every user-story phase; no story phase can begin until they exist.

**⚠️ CRITICAL**: No user story work may begin until this phase completes.

- [X] T004 Extend `tools/benchmark/src/vllm_grpc_bench/m3_types.py` to add the `ComparisonVerdict`, `GRPCSubCohortKind`, and `Protocol` Literal type aliases per `specs/018-m5-1-rest-vs-grpc/data-model.md` §"Verdict literals".
- [X] T005 [P] Extend `tools/benchmark/src/vllm_grpc_bench/m3_types.py` to add the `RESTCohortRecord` frozen dataclass per `specs/018-m5-1-rest-vs-grpc/data-model.md` §"New: RESTCohortRecord" (shim overhead median/p95, connection-pool stats, JSON byte counts).
- [X] T006 [P] Extend `tools/benchmark/src/vllm_grpc_bench/m3_types.py` to add the `ShimOverheadRecord` frozen dataclass per `specs/018-m5-1-rest-vs-grpc/data-model.md` §"New: ShimOverheadRecord".
- [X] T007 [P] Extend `tools/benchmark/src/vllm_grpc_bench/m3_types.py` to add the `SupersedesM1Entry` frozen dataclass per `specs/018-m5-1-rest-vs-grpc/data-model.md` §"New: SupersedesM1Entry" (per-(path × c) row with width-keyed verdict map, classification, rationale, comparison_basis).
- [X] T008 [P] Extend `tools/benchmark/src/vllm_grpc_bench/m3_types.py` to add the `CellVerdict` and `M5_1Cell` frozen dataclasses per `specs/018-m5-1-rest-vs-grpc/data-model.md` §"New: M5_1Cell".
- [X] T009 [P] Extend `tools/benchmark/src/vllm_grpc_bench/m3_types.py` to add the `M5_1RunMetadata` frozen dataclass per `specs/018-m5-1-rest-vs-grpc/data-model.md` §"Run-level field additions".
- [X] T010 Extend `tools/benchmark/src/vllm_grpc_bench/m3_types.py`'s existing `CohortResult` dataclass with the additive M5.1 fields (`protocol`, `grpc_channel_model`, `connection_count`, `shim_overhead_ms`, `comparison_cell_key`) per `specs/018-m5-1-rest-vs-grpc/data-model.md` §"Cohort-level field additions"; all new fields default to `None` so existing M5 call sites remain valid.
- [X] T011 Add unit tests in `tools/benchmark/tests/test_m5_1_types.py` covering: (a) `ComparisonVerdict` Literal contains the six required strings, (b) `GRPCSubCohortKind` Literal contains the four required strings, (c) `CohortResult` instantiated with M5-only fields still works (backward-compat), (d) `M5_1Cell.verdicts` accepts a list of `CellVerdict`, (e) `SupersedesM1Entry` rejects a `classification` value outside the three allowed literals.
- [X] T012 Extend `tools/benchmark/src/vllm_grpc_bench/modal_endpoint.py` to add a `variant="rest_grpc"` keyword to `provide_endpoint(...)` and a corresponding `_provide_rest_grpc_endpoint` async generator that deploys the dual-protocol Modal app and yields a `(grpc_url, rest_url, bearer_token)` triple; the existing `variant="grpc"` path is unchanged so M5 continues to work. Per `specs/018-m5-1-rest-vs-grpc/contracts/m5_1-modal-app.md` §"Handshake with harness".
- [X] T013 Add unit tests in `tools/benchmark/tests/test_modal_endpoint_rest.py` covering: (a) `provide_endpoint(variant="rest_grpc")` returns both URLs from a faked `modal.Dict`, (b) the legacy `variant="grpc"` call path remains unchanged (regression), (c) missing `rest` key in the dict raises a clear error within timeout, (d) bearer-token env-var name (not value) is recorded in the returned metadata.

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel.

---

## Phase 3: User Story 1 — Tuned-gRPC vs REST Head-to-Head on Real Wire (Priority: P1) 🎯 MVP

**Goal**: Produce `docs/benchmarks/m5_1-rest-vs-grpc.{md,json}` carrying a verdict per (path × hidden_size × concurrency) cell with 95% CI-bounded supporting numbers, the run's RTT distribution, and the Modal deploy handle so the engine variable is verifiably held constant across the head-to-head.

**Independent Test**: Run `uv run python -m vllm_grpc_bench --m5_1 --m5_1-modal-region=eu-west-1` end-to-end (or against a mocked Modal endpoint in CI). Confirm the JSON validates against the M5-additive schema (FR-014), every cell carries a verdict literal, every cohort carries `rtt_ms_median`, the report's executive section names the headline finding, and the report's per-cell matrix lists the dual gRPC sub-cohorts at c ≥ 2 plus the default-gRPC control at every cell.

### Tests for User Story 1 (TDD-style — write/update first)

- [X] T014 [P] [US1] Add `tools/benchmark/tests/test_rest_cohort.py` covering the REST cohort runner: (a) `httpx.AsyncClient` is constructed with `http2=False` and `Limits(max_keepalive_connections=c, max_connections=c, keepalive_expiry=300.0)` per FR-008, (b) SSE chat-stream TTFT is the wall-clock from request-send to first non-empty `data:` line per FR-009, (c) JSON embed cohort records `request_bytes_median` / `response_bytes_median` per FR-010, (d) shim-overhead-ms is captured from a stubbed server-side timing header, (e) `connections_opened` matches the configured pool size at c=4 and c=8 against a faked endpoint.
- [X] T015 [P] [US1] Add `tools/benchmark/tests/test_m5_1_sweep.py` covering the sweep orchestrator: (a) `enumerate_cells` produces exactly 18 `(path, hidden_size, concurrency)` tuples, (b) `dispatch_cell` schedules REST → tuned-gRPC sub-cohort(s) → default-gRPC control **in series** per research.md R-4, (c) at c=1 only one tuned-gRPC sub-cohort is run (degenerate); at c=4 and c=8 both `tuned_grpc_multiplexed` and `tuned_grpc_channels` are run, (d) `emit_cell_verdicts` produces `comparison_unavailable` when either side's cohort has `server_bound=true`, (e) `emit_cell_verdicts` produces the expected verdict literal (`tuned_grpc_*_recommend` / `rest_recommend` / `no_winner`) under fixed-fixture CI-overlap conditions per FR-013, (f) **borderline-expand cascade per FR-012**: when a fixture forces a borderline outcome (95% CIs touch at n=100), `dispatch_cell` expands the affected cohort to n ≥ 250 on each protocol independently (REST, tuned-gRPC sub-cohort, default-gRPC); when the borderline does NOT fire, the cohort stays at n=100. Verify the cascade fires per-cohort, not per-cell (one borderline cohort does not trigger expansion of its peer cohorts at the same cell).
- [X] T016 [P] [US1] Add `tools/benchmark/tests/test_m5_1_cli.py` covering CLI flag wiring (parallel to `test_m5_cli.py`): (a) `--m5_1` triggers the M5.1 code path; (b) `--m5_1` + `--m5` exits 2 (flag conflict); (c) `--m5_1-modal-region=us-west-2` overrides default region; (d) `--m5_1-skip-deploy` requires `--m5_1-modal-endpoint`; (e) missing `MODAL_BENCH_TOKEN` exits 4; (f) exit codes 0/2/3/4/6/7/8 map per `contracts/m5_1-bench-cli.md`.
- [X] T017 [P] [US1] Add `tests/integration/test_m5_1_modal_smoke.py` (Modal-secrets-gated; default-skipped) exercising deploy → dual-protocol probe → one tiny REST cohort + one tiny gRPC cohort → teardown per `contracts/m5_1-modal-app.md` §"Local smoke test". Verifies both tunnel URLs are emitted, bearer-authenticated `/healthz` (REST) and `Health.Ping` (gRPC) succeed, and `modal app list` no longer shows the app after `app.stop.aio()`.

### Implementation for User Story 1

- [X] T018 [US1] Implement the FastAPI shim builder `build_rest_shim(engine: MockEngine) -> FastAPI` in `scripts/python/modal_bench_rest_grpc_server.py` per `contracts/m5_1-rest-shim-endpoints.md`: `POST /v1/chat/completions` (SSE on `stream=true`, JSON otherwise), `POST /v1/embeddings` (JSON; base64-decode `input` when `input_kind="prompt_embedding_b64"`), `GET /healthz` (unauthenticated, `{"ok": true}` body). Bearer-token middleware short-circuits before body parsing per research.md R-8. **Timing instrumentation**: both `/v1/*` handlers MUST emit the `X-Shim-Overhead-Ms` response header (handler-entry to MockEngine-return wall-clock in milliseconds, six-decimal precision) on the initial response line — for SSE responses, before the first `data:` event — per `contracts/m5_1-rest-shim-endpoints.md` §"Response headers (timing instrumentation)". `/healthz` MUST NOT emit this header.
- [X] T019 [US1] Implement the dual-protocol Modal app entry point in `scripts/python/modal_bench_rest_grpc_server.py` per `contracts/m5_1-modal-app.md`: single `modal.App("vllm-grpc-bench-rest-grpc-mock")`, CPU-only `debian_slim` image with `fastapi` + `uvicorn[standard]` added, container function that constructs one `MockEngine` singleton then concurrently starts the gRPC server (port 50051, `BearerTokenInterceptor`, M3 servicers) and the uvicorn REST server (port 8000, `workers=1`).
- [X] T020 [US1] Add the `modal.forward()` orchestration to `scripts/python/modal_bench_rest_grpc_server.py`: `modal.forward(8000)` (HTTPS for REST) and `modal.forward(50051, unencrypted=True)` (plain-TCP for gRPC per M5's ALPN-incompatibility constraint). Write both URLs and a `ready=True` flag to the `modal.Dict` the harness reads. Per `contracts/m5_1-modal-app.md` §"Exposed tunnel ports".
- [X] T021 [P] [US1] Implement `run_rest_cohort()` in `tools/benchmark/src/vllm_grpc_bench/rest_cohort.py`: c-worker `asyncio.gather` dispatch, each worker holding one keep-alive HTTP/1.1 connection; SSE chat path measures TTFT as wall-clock from request-send to first non-empty `data:` line; JSON embed path measures wall-clock from send to recv; per-request shim overhead read from the `X-Shim-Overhead-Ms` response header per `contracts/m5_1-rest-shim-endpoints.md` §"Response headers (timing instrumentation)" (units: milliseconds; aggregated into `RESTCohortRecord.shim_overhead_ms_median` / `shim_overhead_ms_p95`); per-cohort `RESTCohortRecord` produced. Per `contracts/m5_1-rest-shim-endpoints.md` and research.md R-3.
- [X] T022 [P] [US1] Implement `probe_rest_rtt()` in `tools/benchmark/src/vllm_grpc_bench/rest_cohort.py`: `GET /healthz` over the cohort's keep-alive connection immediately before measurement starts; returns median + p95 over a small probe burst. Reuses M5's RTT-probe semantics from `tools/benchmark/src/vllm_grpc_bench/rtt_probe.py`.
- [X] T023 [US1] Implement `frozen_tuned_channel_config(path, hidden_size)` helper in `tools/benchmark/src/vllm_grpc_bench/m5_1_sweep.py` per FR-006: loads M5's per-axis `recommend` verdicts from `docs/benchmarks/m5-cross-host-validation.json` at the matching (path, hidden_size); falls back to M1-default values when M5 emitted `no_winner` on an axis. Reuses `channel_config.py` loaders.
- [X] T024 [US1] Implement `enumerate_cells()` and the 18-cell scheduler in `tools/benchmark/src/vllm_grpc_bench/m5_1_sweep.py` producing the (path × hidden_size × concurrency) cross-product (2 × 3 × 3 = 18).
- [X] T025 [US1] Implement `dispatch_cell()` in `tools/benchmark/src/vllm_grpc_bench/m5_1_sweep.py` per research.md R-4: serial dispatch of REST cohort → tuned-gRPC sub-cohort(s) → default-gRPC control. At c=1 dispatches only one tuned-gRPC sub-cohort (degenerate); at c ≥ 2 dispatches both `tuned_grpc_multiplexed` (single channel, c HTTP/2 streams) and `tuned_grpc_channels` (c independent channels, one serial RPC per channel). Reuses M5's gRPC cohort runner for both sub-cohorts and the default-gRPC control, and **honors the FR-012 n≥100 → n≥250 borderline-expand cascade per-cohort** (one borderline cohort triggers only its own expansion, not its peer cohorts at the same cell — verified by T015 subcase (f)). Per FR-006 / FR-007 / FR-012.
- [X] T026 [US1] Implement `emit_cell_verdicts()` in `tools/benchmark/src/vllm_grpc_bench/m5_1_sweep.py` per FR-005 / FR-013: takes the REST cohort and each gRPC sub-cohort, computes (gRPC − REST) delta on the time metric (TTFT for `chat_stream`, wall-clock for `embed`), computes 95% CI on the delta, emits the appropriate `ComparisonVerdict` literal. Sets `comparison_unavailable` when either side's cohort is `server_bound`. Attaches `low_rtt_caveat` per FR-004 when measured median RTT falls below the exercise threshold.
- [X] T027 [US1] Implement the full sweep orchestrator entry point `run_m5_1_sweep()` in `tools/benchmark/src/vllm_grpc_bench/m5_1_sweep.py`: invokes `provide_endpoint(variant="rest_grpc")`, runs warmup cohorts (discarded), iterates `enumerate_cells()` calling `dispatch_cell()` then `emit_cell_verdicts()`, builds the `M5_1RunMetadata` record, returns it for the reporter. Tears down the Modal app on context exit.
- [X] T028 [P] [US1] Extend `tools/benchmark/src/vllm_grpc_bench/reporter.py` with `write_m5_1_report(metadata: M5_1RunMetadata, json_out: Path, md_out: Path)` per `contracts/m5_1-report-schema.md`. Emits the additive M5.1 JSON keys (`m5_1_matrix`, `supersedes_m1_time`, `rest_shim_meta`, `auth_token_env_var`) plus the additive per-cohort fields (`protocol`, `grpc_channel_model`, `connection_count`, `shim_overhead_ms`, `comparison_cell_key`, `rest_cohort_record`). Each cohort entry MUST also carry the M5-inherited `sample_size` field (already on `CohortResult`) so T015 subcase (f) and T052 can verify that the FR-012 borderline-expand cascade fired where expected (cohorts that hit borderline carry `sample_size >= 250`; cohorts that did not stay at `sample_size == 100`). Validates the additive-only rule (no rename/removal of M5 keys).
- [X] T029 [US1] Extend `tools/benchmark/src/vllm_grpc_bench/reporter.py` with the M5.1 Markdown sections: executive (headline finding + MockEngine read-instruction caveat per Edge Cases / FR-015), per-(path × hidden_size × concurrency) comparison matrix (one block per path, table per hidden_size with concurrency rows and verdict columns), REST shim-overhead appendix per FR-010, "Negative results — do not re-run speculatively" appendix per Constitution V / FR-015.
- [X] T030 [P] [US1] Add `tools/benchmark/tests/test_m5_1_reporter.py` covering report rendering: (a) JSON emitted carries every M5 key from M5's schema unchanged (additive-only assertion), (b) every cohort has a `comparison_cell_key` resolving to an entry in `m5_1_matrix[*]`, (c) `len(verdicts) == 3` at c ≥ 2 cells (unless `comparison_unavailable`), `len(verdicts) == 2` at c=1 cells, (d) no token-shaped string appears in the emitted JSON or Markdown (regex `Bearer ` and 32-char URL-safe pattern), (e) executive Markdown section names the headline finding when fed a fixed-fixture `M5_1RunMetadata`.
- [X] T031 [US1] Wire the M5.1 flag family into `tools/benchmark/src/vllm_grpc_bench/__main__.py` per `contracts/m5_1-bench-cli.md`: `--m5_1`, `--m5_1-modal-region` (default `eu-west-1`), `--m5_1-modal-token-env` (default `MODAL_BENCH_TOKEN`), `--m5_1-modal-endpoint`, `--m5_1-skip-deploy`, `--m5_1-rtt-validity-threshold-ms` (default `1.0`), `--m5_1-rtt-exercise-threshold-ms` (default `20.0`), `--m5_1-warmup-n` (default `20`), `--m5_1-shim-overhead-warn-pct` (default `5.0`), `--m5_1-report-out`. Conflict-checks `--m5_1` against `--m3` / `--m4` / `--m5` (exit code 2).
- [X] T032 [US1] Wire the M5.1 mode dispatcher in `tools/benchmark/src/vllm_grpc_bench/__main__.py`: when `--m5_1` is set, calls `m5_1_sweep.run_m5_1_sweep()` and then `reporter.write_m5_1_report()` with the configured output paths; honors all exit codes from `contracts/m5_1-bench-cli.md` §"Exit codes".

**Checkpoint**: User Story 1 fully functional — a maintainer can run the M5.1 sweep end-to-end against Modal and obtain a published report with verdicts at every cell.

---

## Phase 4: User Story 2 — Refresh the Executive Narrative to Cite Cross-Host Numbers (Priority: P2)

**Goal**: After the M5.1 report lands on the PR branch (US1), the maintainer updates `README.md`, `docs/benchmarks/summary.md`, and `docs/PLAN.md` to flip M5.1 from "(upcoming)" to "(delivered)" and to cite M5.1's cross-host numbers as the canonical time-claim evidence — unconditional on outcome shape per Clarifications 2026-05-11. The refresh commit MUST be the last commit on the branch at `gh pr create` time per FR-019.

**Independent Test**: A reviewer checks out the M5.1 PR head and reads `README.md`, `docs/benchmarks/summary.md`, and `docs/PLAN.md`; confirms M5.1 is marked "(delivered)" with run date + report path, the executive prose cites M5.1's numbers (or an honest mixed-results framing), M1 bytes-axis claims are unchanged, and `git log -1 --oneline` shows the narrative-refresh commit at `HEAD`.

### Implementation for User Story 2

> **Procedural tasks** — these are maintainer-driven editorial updates, not harness code. The harness does not enforce ordering; the maintainer follows `quickstart.md`'s pre-PR checklist.

- [ ] T033 [US2] Run the full M5.1 sweep via `uv run python -m vllm_grpc_bench --m5_1 --m5_1-modal-region=eu-west-1` (or operator-chosen region), then commit the produced `docs/benchmarks/m5_1-rest-vs-grpc.{md,json}` files with message `[Spec Kit] Publish M5.1 report` per `quickstart.md` §Step 4. This is the prerequisite commit US2's narrative refresh cites.
- [ ] T034 [P] [US2] Edit `README.md` to flip the "Milestone 5.1 — REST vs gRPC Head-to-Head on Real Wire (upcoming)" section to "(delivered)" with the run date and the published report path `docs/benchmarks/m5_1-rest-vs-grpc.md`; embed the headline finding in the same prose style M5's "(delivered)" section uses; replace any executive bullets that cite M1's loopback-era REST-vs-gRPC time numbers with M5.1's cross-host numbers (or an honest mixed-results framing if results contradict); leave M1 bytes-axis claims unchanged. Per FR-017 and `quickstart.md` §5b.
- [ ] T035 [P] [US2] Edit `docs/benchmarks/summary.md` to apply the same narrative refresh: replace any "REST vs gRPC" comparison block citing M1's c=1 numbers as canonical time evidence with M5.1's per-(path × c) verdict pattern; embed the M5.1 report path and run date; preserve M1 bytes-axis claims. Per FR-018 and `quickstart.md` §5c.
- [ ] T036 [P] [US2] Edit `docs/PLAN.md` to flip the "Milestone 5.1 — REST vs gRPC Head-to-Head on Real Wire (upcoming)" section to "(delivered)" with the same headline-finding embed style M5 uses. Per FR-018 and `quickstart.md` §5d.
- [ ] T037 [US2] Audit `README.md` for indirectly-stale milestone-status text (M5 status correctness, milestone numbering, milestone delivery dates) and fix in the same edit. Per FR-017(e).
- [ ] T038 [US2] Commit T034–T037 as a single commit with message `[Spec Kit] Refresh README + executive narrative for M5.1 delivery`; verify with `git log -1 --oneline` that this commit is at `HEAD` per FR-019 / `quickstart.md` §5e. If any auto-commit hook lands a subsequent change, soft-reset and re-commit per `quickstart.md` §5f.
- [ ] T039 [US2] Open the PR with `gh pr create --base main --head 018-m5-1-rest-vs-grpc` using the body template from `quickstart.md` §Step 6; the body MUST cite T038's commit SHA explicitly as "narrative refreshed for M5.1 delivery — see commit `<sha>`" per FR-019 / SC-008.

**Checkpoint**: User Story 2 complete — the PR's first reviewer-facing diff is the current narrative state; M5.1 milestone reads "(delivered)" on all three narrative surfaces.

---

## Phase 5: User Story 3 — Supersession Table Tying M5.1 to M1's Time Claims (Priority: P3)

**Goal**: The M5.1 report carries an explicit "Supersedes M1 (time-axis)" table that maps every M1 time-axis cell M5.1's matrix covers to the M5.1 verdict pattern across widths, the supporting CI-bounded numbers, and a one-line rationale. M1 bytes-axis claims are explicitly **not** in the table. Verdict-changed rows are visually distinguished from verdict-confirmed rows.

**Independent Test**: A reader opens `docs/benchmarks/m5_1-rest-vs-grpc.md`, locates the "Supersedes M1 (time-axis)" table, and confirms (a) every M1 time-axis cell M5.1 covers has a row, (b) verdict-changed rows are visually distinguishable, (c) M1 bytes claims are absent from the table and explicitly preserved in the executive prose per FR-021.

### Tests for User Story 3

- [X] T040 [P] [US3] Add `tools/benchmark/tests/test_m5_1_supersede.py` covering `build_supersedes_m1_time()`: (a) loads M1's published time-axis cells from a fixture file structured like `docs/benchmarks/phase-3-modal-comparison.md`, (b) produces one `SupersedesM1Entry` per (path, concurrency) M5.1 covers, (c) `classification == "verdict_confirmed"` when every width matches M1's verdict; `"verdict_changed"` when any width contradicts; `"mixed"` when widths split, (d) `comparison_basis == "m1_real_vllm_vs_m5_1_mock_engine"` is always set, (e) rationale text contains the MockEngine continuity caveat when verdict changes per Edge Case 2.

### Implementation for User Story 3

- [X] T041 [US3] Implement `load_m1_time_axis_cells()` in `tools/benchmark/src/vllm_grpc_bench/m5_1_supersede.py`: loads M1's published "REST vs gRPC" comparison cells and returns a list of `(path, concurrency, m1_verdict_literal, source_report_path)` tuples per research.md R-5. **Strategy — fixture-first**: ship a hand-curated `tools/benchmark/tests/fixtures/m1_time_axis_cells.json` containing the manually-extracted M1 verdicts; `load_m1_time_axis_cells()` reads this JSON rather than parsing freeform Markdown from `docs/benchmarks/summary.md` / `docs/benchmarks/phase-3-modal-comparison.md` directly (the Markdown files remain the source-of-truth reference, but the loader treats the JSON fixture as authoritative for the supersession run). **Fixture JSON schema**: a top-level array of objects, each carrying `{"m1_path": "chat_completion" | "embed_completion", "m1_concurrency": 1 | 4 | 8, "m1_verdict_literal": "<short string e.g. 'REST faster'>", "m1_source_report": "<repo-relative-path#anchor e.g. docs/benchmarks/phase-3-modal-comparison.md#chat-c1>"}`. The four fields map 1:1 to the tuple `load_m1_time_axis_cells()` returns. **Path-name mapping**: M1 uses `chat_completion` / `embed_completion` (non-streaming) while M5.1 uses `chat_stream` / `embed`; the loader emits M1's literal `chat_completion` / `embed_completion` in the `m1_path` field of `SupersedesM1Entry` (per `data-model.md` §SupersedesM1Entry), and T042's builder applies the mapping `{"chat_completion": "chat_stream", "embed_completion": "embed"}` when joining M1 cells to M5.1 matrix entries.
- [X] T042 [US3] Implement `build_supersedes_m1_time(m5_1_matrix, m1_cells)` in `tools/benchmark/src/vllm_grpc_bench/m5_1_supersede.py` per FR-020: for each M1 cell, applies the path-name mapping `{"chat_completion": "chat_stream", "embed_completion": "embed"}` (per T041) to find the matching M5.1 (path, concurrency) verdicts across all three widths; builds the `SupersedesM1Entry` with width-keyed verdict map, supporting deltas + CIs, classification, comparison_basis, and rationale (one sentence; MockEngine continuity caveat appended on `verdict_changed`). The `m1_path` field of the emitted `SupersedesM1Entry` retains M1's literal naming (`chat_completion` / `embed_completion`) so a reader cross-referencing M1's reports can locate the source row directly.
- [X] T043 [US3] Extend `tools/benchmark/src/vllm_grpc_bench/reporter.py` with a "Supersedes M1 (time-axis)" Markdown table renderer per FR-020: per-row columns (path, concurrency, M1 verdict, M5.1 width-keyed verdicts, classification, rationale); `verdict_changed` rows visually distinguished (bold row or `verdict_changed: true` cell flag). Append below the per-cell comparison matrix section.
- [X] T044 [US3] Extend `tools/benchmark/src/vllm_grpc_bench/reporter.py`'s executive section with the explicit "M1 bytes-axis claims remain in force unchanged" statement per FR-021 / SC-004 so a future reader does not interpret M5.1's silence on bytes as a quiet retraction.
- [X] T045 [US3] Wire `m5_1_supersede.build_supersedes_m1_time(...)` into `m5_1_sweep.run_m5_1_sweep()` so the resulting list lands on `M5_1RunMetadata.supersedes_m1_time` before `write_m5_1_report` is called.

**Checkpoint**: User Story 3 complete — the report's supersession table answers "which M1 time-axis conclusions did cross-host head-to-head measurement change?" in under one minute per SC-004.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, cross-cutting hygiene, and the operator-triggered end-to-end run that produces the publishable report. Required before merge.

- [X] T046 [P] Run `make check` and confirm all 274+ harness unit tests pass (M5.1 additions land green).
- [X] T047 [P] Validate `docs/benchmarks/m5_1-rest-vs-grpc.json` against the M5-additive-superset rule in `tools/benchmark/tests/test_m5_1_reporter.py`'s `test_additive_only` check.
- [X] T048 [P] Grep `docs/benchmarks/m5_1-rest-vs-grpc.{md,json}` for any token-shaped string (`git grep -E '[A-Za-z0-9_-]{20,}' docs/benchmarks/m5_1*`); confirm no bearer-token value leaked into the report per SC-001 / Constitution V.
- [ ] T049 Run `tests/integration/test_m5_1_modal_smoke.py` against real Modal credentials (CI smoke run with `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` set); confirm deploy → both-probes → tiny cohorts → teardown completes under 90s wall-clock per `contracts/m5_1-modal-app.md`.
- [ ] T050 Walk through `specs/018-m5-1-rest-vs-grpc/quickstart.md` end-to-end from a clean shell: token generation → sweep run → report inspection → narrative refresh → PR creation. Capture any quickstart instruction that diverged from observed behavior and fix in the same task (quickstart edits, not code edits).
- [ ] T051 Verify `git log --oneline -5` on the PR branch immediately before `gh pr create` shows the `[Spec Kit] Refresh README + executive narrative for M5.1 delivery` commit at `HEAD` per FR-019 / SC-008. If not, follow `quickstart.md` §5f recovery.
- [ ] T052 Verify SC-007 wall-clock budget. (a) Record the M5.1 sweep's total wall-clock from T033's run logs (or from `run_started_at` / `run_completed_at` in `docs/benchmarks/m5_1-rest-vs-grpc.json`); (b) assert the elapsed time is ≤ 60 minutes per SC-007; (c) if elapsed > 60 minutes, file the divergence in the PR description (root-cause one paragraph: which phase inflated — Modal deploy, cohort dispatch, borderline-expand cascades, or teardown), and either re-run with a tighter region/threshold or document the inflation as accepted (the budget is a target, not a hard cap, per `plan.md` §"Scale/Scope"). The 60-minute target documented in `specs/018-m5-1-rest-vs-grpc/quickstart.md` §"Cost expectation" treats > 90 minutes as a regression worth investigating.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No upstream dependencies; can start immediately. T001 is a precondition check; T002/T003 create file stubs.
- **Foundational (Phase 2)**: Depends on Phase 1; BLOCKS Phase 3 / 4 / 5. The dataclass additions (T004–T010) must land before any user-story implementation can reference them. `modal_endpoint` extension (T012) must land before any cross-host run is attempted.
- **User Story 1 (Phase 3)**: Depends on Phase 2 complete. Internal ordering: tests (T014–T017) ideally precede implementation; within implementation, T018–T020 (Modal app) and T021–T022 (REST cohort runner) can proceed in parallel; T023–T027 (sweep orchestrator) depends on the cohort runner; T028–T030 (reporter + report tests) depends on the sweep producing `M5_1RunMetadata`; T031–T032 (CLI) depends on T027.
- **User Story 2 (Phase 4)**: Depends on Phase 3 producing the report (`T033` produces the report; T034–T037 cite it). T038 must be the last commit on the branch.
- **User Story 3 (Phase 5)**: Depends on Phase 2 (dataclasses) for `SupersedesM1Entry`; depends on Phase 3 for the `m5_1_matrix` content the supersession reads. Can land in parallel with Phase 4's editorial tasks once Phase 3 is complete.
- **Polish (Phase 6)**: Depends on Phases 3, 4, 5 (in any order between US2 and US3, but both before T046).

### User Story Dependencies

- **US1 (P1)**: Independent of US2 and US3 in terms of implementation. Produces the report that US2 cites and the matrix data US3 reads.
- **US2 (P2)**: Cites US1's report; T033 is the bridge task that commits US1's output before US2's editorial commits.
- **US3 (P3)**: Reads US1's `m5_1_matrix`; can be implemented and tested without US2's narrative refresh having landed.

### Within Each User Story

- Tests for a story (where included) may be written FIRST and verified to FAIL before the matching production code lands; or written alongside implementation under the discretion of the implementer (the spec does not mandate strict TDD ordering, only that tests exist and pass at PR time per Constitution IV).
- Models / dataclasses before services (Phase 2 ordering captures this).
- Services / runners before the orchestrator that composes them.
- Orchestrator before the reporter that consumes its output.
- CLI wiring last (depends on the orchestrator entry point).

### Parallel Opportunities

- Phase 1: T002 and T003 are [P] and can run in parallel.
- Phase 2: T005, T006, T007, T008, T009 are all [P] — five additive dataclasses in the same file but on independent additive blocks; they can be reviewed in parallel even if landed in a single PR commit.
- Phase 3 implementation: T021 and T022 ([P], both in `rest_cohort.py` — same file but independent functions); T018, T019, T020 (Modal app, can land in parallel); T028, T030 (reporter implementation and reporter tests, [P]).
- Phase 3 tests: T014, T015, T016, T017 all [P] (independent test files).
- Phase 4: T034, T035, T036 are [P] (three independent files).
- Phase 6: T046, T047, T048 are [P].

---

## Parallel Example: User Story 1 Implementation

```bash
# After Phase 2 completes, launch these in parallel (they touch independent files):
Task: "Implement REST cohort runner in tools/benchmark/src/vllm_grpc_bench/rest_cohort.py (T021–T022)"
Task: "Implement Modal dual-protocol app in scripts/python/modal_bench_rest_grpc_server.py (T018–T020)"

# Tests for US1 (all independent files):
Task: "Add tools/benchmark/tests/test_rest_cohort.py (T014)"
Task: "Add tools/benchmark/tests/test_m5_1_sweep.py (T015)"
Task: "Add tools/benchmark/tests/test_m5_1_cli.py (T016)"
Task: "Add tests/integration/test_m5_1_modal_smoke.py (T017)"
```

## Parallel Example: User Story 2 Editorial Pass

```bash
# After T033 lands the report, three editorial edits proceed in parallel:
Task: "Edit README.md to flip M5.1 milestone to (delivered) (T034)"
Task: "Edit docs/benchmarks/summary.md to cite M5.1 numbers (T035)"
Task: "Edit docs/PLAN.md to flip M5.1 milestone (T036)"

# Then merge into a single commit (T038) and verify HEAD ordering.
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T003).
2. Complete Phase 2: Foundational (T004–T013) — **critical blocking phase**.
3. Complete Phase 3: User Story 1 (T014–T032).
4. **STOP and VALIDATE**: Run the M5.1 sweep end-to-end against Modal. Inspect `docs/benchmarks/m5_1-rest-vs-grpc.{md,json}`. Confirm every cell has a verdict, every cohort has RTT, the report's executive section names a headline finding.
5. The MVP is shippable here — a maintainer can read the report directly from US1 even without US2's narrative refresh.

### Incremental Delivery

1. Phase 1 + Phase 2 → foundation ready.
2. Phase 3 (US1) → MVP shippable: report committed, raw evidence available.
3. Phase 4 (US2) → narrative refresh: README + summary + PLAN updated; PR-ready.
4. Phase 5 (US3) → reporting hygiene: supersession table extends the report.
5. Phase 6 → polish, schema validation, smoke test, quickstart walkthrough, PR.

### Suggested MVP Scope

**MVP = Phases 1, 2, 3 only.** US1 produces the publishable report with verdicts at every cell. The narrative refresh (US2) is an editorial overlay; the supersession table (US3) is reporting hygiene. Both add value but neither is required to ship the headline result.

### Pre-PR Procedural Gate

Per FR-019 and `quickstart.md` §5f: the narrative-refresh commit (T038) MUST be the last commit on the branch at `gh pr create` time. The harness does not enforce this — the maintainer follows the quickstart checklist. If a hook lands a subsequent commit (e.g., `after_implement` auto-commit hook landed in `.specify/extensions.yml`), soft-reset and re-commit per `quickstart.md` §5f.

---

## Notes

- [P] tasks = different files (or independent additive blocks in the same file), no dependencies on incomplete tasks.
- [Story] label maps task to user story for traceability; Setup / Foundational / Polish have no [Story] label.
- Each user story is independently testable per its "Independent Test" criteria.
- Constitution IV: harness mechanics tested under `make check`; full M5.1 sweep is operator-triggered, not part of CI's runtime budget.
- Constitution V: `comparison_unavailable` cells, `low_rtt_caveat` annotations, and negative-result appendix are explicit honesty mechanisms; the narrative refresh (T034) is unconditional on outcome shape per Clarifications 2026-05-11.
- M1 bytes-axis claims are NEVER touched — they remain in force unchanged because they are structural (encoding choice) and immune to RTT (FR-021).
- The pre-PR README update (T038) is procedural; the maintainer's checklist is in `specs/018-m5-1-rest-vs-grpc/quickstart.md`.
