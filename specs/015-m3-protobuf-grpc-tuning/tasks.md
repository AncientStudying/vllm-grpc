---

description: "Task list for M3 — Protobuf & gRPC Tuning"
---

# Tasks: M3 — Protobuf & gRPC Tuning

**Input**: Design documents from `/specs/015-m3-protobuf-grpc-tuning/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: Test tasks are included because both contract files (`contracts/mock-engine-interface.md`, `contracts/m3-bench-cli.md`) explicitly enumerate test obligations — those obligations are treated as binding here.

**Organization**: Tasks are grouped by user story. US1 (P1, bytes-axis) shipped as the milestone MVP in PR #17. US2 (P2, schema-level) is deferred to M4 per the 2026-05-10 spec clarifications. US3 (P1.5, Phase A wall-clock re-analysis) is the in-flight closure work for M3.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, or US3)
- File paths are absolute or repo-relative as noted

## Path Conventions

This is a Python `uv` workspace. Touched roots:

- `tools/benchmark/src/vllm_grpc_bench/` — bench harness (most new code lands here)
- `tools/benchmark/tests/` — bench harness tests
- `tools/benchmark/corpus/` — prompt fixtures
- `packages/frontend/src/vllm_grpc_frontend/` — server-side gRPC; channel options injected
- `packages/proxy/src/vllm_grpc_proxy/` — proxy gRPC client; channel options injected
- `packages/client/src/vllm_grpc_client/` — direct-grpc client; channel options injected
- `proto/vllm_grpc/v1/` — protobuf sources (P2 only)
- `docs/benchmarks/` — published reports
- `docs/decisions/` — ADRs

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm starting state and prepare runtime dependencies.

- [X] T001 Verify baseline: `make install`, `make proto`, `make check` all green; confirm `grpcio==1.80.0` and `vllm` pin in `pyproject.toml [dependency-groups] graph-targets` match `research.md` R-3 citations; if `uv.lock` has bumped since last cross-repo refresh, run `/ground-truth-refresh` (per project Constitution Workflow: "Graphify MUST be re-indexed at the start of each new phase") so M2 citations resolve cleanly during M3 work.
- [X] T002 [P] Add `numpy>=1.26` to `tools/benchmark/pyproject.toml` `[project] dependencies` (consumed by `mock_engine.py` for embedding tensors and `ci.py` for the t-distribution math; current bench package has no numpy direct dep). Run `uv lock` after.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Wire up everything both US1 and US2 need before either can run a sweep cell. After this phase, `python -m vllm_grpc_bench --m3 --smoke --axis max_message_size --width 2048 --path embed` returns exit 0.

**⚠️ CRITICAL**: No US1/US2 work begins until this phase is complete.

### Foundational implementation

- [X] T003 [P] Implement the CI estimator in `tools/benchmark/src/vllm_grpc_bench/ci.py` per `research.md` R-1: mean, sample stddev (`numpy.std(ddof=1)`), 95% CI bounds via the t-distribution with a hard-coded critical-value table covering n ∈ {10, 20, 30, 50, 100} (no `scipy` dependency). Also export `is_winner(baseline_ci_high, candidate_ci_low) -> bool` for SC-003 evaluation.
- [X] T004 [P] Implement `ChannelConfig` dataclass + the seven named presets (`M1_BASELINE`, `MAX_MSG_16MIB`, `MAX_MSG_UNLIMITED`, `KEEPALIVE_AGGRESSIVE`, `KEEPALIVE_RELAXED`, `COMPRESSION_GZIP`, `HTTP2_BDP_PROBE`) in `tools/benchmark/src/vllm_grpc_bench/channel_config.py` per `data-model.md` § ChannelConfig. Include the kebab-case `name` validator and the `_ALLOWED_ARGS` allowlist that rejects typos in grpcio arg names.
- [X] T005 [P] Implement `MockEngineConfig` + `MockEngine` in `tools/benchmark/src/vllm_grpc_bench/mock_engine.py` per `contracts/mock-engine-interface.md`: `generate(prompt, sampling_params, request_id)` async-iterator paced at `tokens_per_second`; `encode(prompt, request_id)` yielding one `EmbeddingRequestOutput` of shape `[hidden_size]` seeded from `hash(prompt) ^ config.seed`. Determinism, hidden_size shape parity, and the two `ValueError` / `RuntimeError` failure modes are all required.
- [X] T006 [P] Define the in-process data-model dataclasses (`BenchmarkCell`, `Sample`, `RunCohort`, `Recommendation` with the `verdict` literal `{"recommend","no_winner","not_measurable"}`, `ProtoRevision`) in `tools/benchmark/src/vllm_grpc_bench/m3_types.py` per `data-model.md`. Include the validation invariants (e.g. `path/corpus_subset` mismatch raises, `Recommendation` with `verdict=="recommend"` requires `candidate_ci_lower > baseline_ci_upper`).
- [X] T007 [P] Add the long-stream synthetic prompt fixture at `tools/benchmark/corpus/m3_long_stream.json` per `research.md` R-7 (deterministic seed; the mock produces ≥1024 tokens at ~50 ms/token so total wall-clock ≥ 50 s and crosses `KEEPALIVE_AGGRESSIVE` ping intervals multiple times).
- [X] T008 Plumb `ChannelConfig.server_options` and `ChannelConfig.compression` into `packages/frontend/src/vllm_grpc_frontend/main.py` so `grpc.aio.server(options=..., compression=...)` honours an injected `ChannelConfig` (default = `ChannelConfig.M1_BASELINE`, which produces the existing call-with-no-options behaviour — preserves M1 wire shape exactly when no override is set). Depends on T004.
- [X] T009 [P] Plumb `ChannelConfig.client_options` and `ChannelConfig.compression` into every `grpc.aio.insecure_channel(...)` call in `packages/proxy/src/vllm_grpc_proxy/grpc_client.py` (`ping`, `complete`, `complete_stream`, completions equivalents — five sites) via a single helper that takes a `ChannelConfig` and returns the args. Depends on T004.
- [X] T010 [P] Plumb `ChannelConfig.client_options` and `ChannelConfig.compression` into `packages/client/src/vllm_grpc_client/client.py`'s `grpc.aio.insecure_channel(self._addr)` call. Depends on T004.
- [X] T011 Implement `m3_sweep.py` orchestrator in `tools/benchmark/src/vllm_grpc_bench/m3_sweep.py`: cartesian-product cell construction (axis × width × path × candidate-config), per-cell server bring-up via `frontend.main` in-process with the cell's server options, per-cell channel construction via the helper from T009, drive `iterations` RPCs collecting `Sample`s (populating **all** fields per `data-model.md` § Sample — including `mean_inter_token_seconds` / `inter_token_seconds_stddev` computed from `time.perf_counter()` recorded at each `async for` boundary on the streaming path per spec AS US1-3, the typed `error_kind` literal on RPC failure, and `off_canonical=True` when `BenchmarkCell.hidden_size ∉ {2048, 4096, 8192}`), aggregate into `RunCohort`s, compute `Recommendation`s using `ci.is_winner`. Depends on T003, T004, T005, T006.
- [X] T012 Add `--m3` mode to `tools/benchmark/src/vllm_grpc_bench/__main__.py` per `contracts/m3-bench-cli.md`: full argparse with `--axis`, `--width` (accepts the three canonical values, `all`, **or any positive integer for off-canonical exploratory runs** per the relaxed contract), `--path`, `--iters-per-cell`, `--out-dir`, `--smoke`, `--seed`, `--p2-revision`, `--frozen-channel`; exit codes 0/2/3/4 per the contract; `--smoke` writes to `bench-results/m3-smoke-<timestamp>.json` and skips CI math. Depends on T011.

### Foundational tests

- [X] T013 [P] Tests for `ci.py` in `tools/benchmark/tests/test_ci.py`: mean/stddev correctness against a hand-checked sample; `is_winner` behaviour at the boundary (lower CI just above vs. just below baseline upper CI); n=30 critical value within 0.5% of the published t-table value. Depends on T003.
- [X] T014 [P] Tests for `channel_config.py` in `tools/benchmark/tests/test_channel_config.py`: each named preset constructs successfully; kebab-case validator rejects `Bad_Name` and `_leading-dash`; `_ALLOWED_ARGS` allowlist rejects typos like `grpc.max_messag_size`; `M1_BASELINE` has empty `server_options` and empty `client_options`. Depends on T004.
- [X] T015 [P] Tests for `mock_engine.py` in `tools/benchmark/tests/test_mock_engine.py` per the contract: hidden_size shape correctness at all three canonical widths **plus one off-canonical width** (e.g. 1536) — verifying the mock accepts the value, the embedding tensor has exactly that length, and (when wired through a `BenchmarkCell`) the resulting `Sample.off_canonical == True`; determinism across two calls with identical inputs (byte-equality); streaming pacing within ±10% of `tokens_per_second`; empty-prompt → `ValueError`; duplicate `request_id` → `RuntimeError`. Depends on T005.
- [X] T016 [P] [US1-prep] Smoke integration test at `packages/frontend/tests/test_mock_engine_servicer.py`: `ChatServicer(engine=MockEngine(...))` and `CompletionsServicer(engine=MockEngine(...))` start, accept one RPC each, return well-formed responses — proves the drop-in claim from `contracts/mock-engine-interface.md`. Depends on T005, T008.
- [X] T017 [P] Smoke test for the CLI in `tools/benchmark/tests/test_m3_sweep_smoke.py`: `python -m vllm_grpc_bench --m3 --smoke --axis max_message_size --width 2048 --path embed` returns exit 0 and writes the expected `bench-results/m3-smoke-*.json` artefact. Depends on T012.
- [X] T018 [P] Argument-validation test in `tools/benchmark/tests/test_m3_cli_args.py`: `--p2-revision foo` without `--frozen-channel` returns exit 2 with a clear stderr message naming the missing flag. Depends on T012.

**Checkpoint**: Foundation ready — `make check` green, smoke run exits 0. US1 can begin.

---

## Phase 3: User Story 1 — gRPC channel-level tuning measurements (Priority: P1) 🎯 MVP

**Goal**: Produce defensible, statistically-grounded recommendations (or honestly-recorded null results) for all four channel-level axes — `max_message_size`, keepalive, compression, HTTP/2 framing — across the three canonical embedding widths and both paths (embed + chat-completion streaming). Publish the results in `docs/benchmarks/m3-channel-tuning.{md,json}` with grpcio-source citations on every recommendation.

**Independent Test**: A reviewer runs `python -m vllm_grpc_bench --m3` end-to-end, then opens `docs/benchmarks/m3-channel-tuning.md` and confirms (a) every axis × width × path cell has a verdict (recommend / no_winner / not_measurable), (b) each `recommend` has both a supporting delta with CI bounds and a `~/.graphify/repos/grpc/grpc/...` citation, and (c) SC-001 and SC-002 are answered without rerunning the benchmark.

### Implementation for User Story 1

- [X] T019 [US1] Run the **`max_message_size` axis sweep** at all three widths × both paths (default vs. `MAX_MSG_16MIB` vs. `MAX_MSG_UNLIMITED`) via `python -m vllm_grpc_bench --m3 --axis max_message_size`. Record the resulting `Recommendation` block — per FR-006 / SC-002, identify the embedding width at which the default first becomes binding for the embed path (or document that it doesn't bind at any canonical width and explain why, per `research.md` R-3a's expectation). Citation: `~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py` (channel-args plumbing) and `~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc` (defaults).
- [X] T020 [US1] Run the **keepalive axis sweep** at all three widths × both paths (default vs. `KEEPALIVE_AGGRESSIVE` vs. `KEEPALIVE_RELAXED`) via `python -m vllm_grpc_bench --m3 --axis keepalive`. The streaming-path runs MUST include the `m3_long_stream.json` long-stream cohort (per FR-011 + spec Edge Case "Aggressive keepalive can cause the upstream servicer to drop long-streaming connections"). Record verdicts. Citation: `~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc` (keepalive timer logic).
- [X] T021 [US1] Run the **compression axis sweep** at all three widths × both paths (`NoCompression` vs. `COMPRESSION_GZIP`) via `python -m vllm_grpc_bench --m3 --axis compression`. Record verdicts honestly per Constitution V — gzip on dense float embeds is expected to *enlarge* the payload; that negative result MUST be recorded, not omitted. Citation: `~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc` (frame-level compression handling).
- [X] T022 [US1] Run the **HTTP/2 framing axis sweep** at all three widths × both paths (default flow-control window vs. `HTTP2_BDP_PROBE`) via `python -m vllm_grpc_bench --m3 --axis http2_framing`. Long-stream cohort included on the streaming path. Record verdicts. Citation: `~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc` and `bdp_estimator.cc`.
- [X] T023 [US1] Author `docs/benchmarks/m3-channel-tuning.md` with the format from `quickstart.md` § "What success looks like": one section per axis (max_message_size, keepalive, compression, HTTP/2 framing), per-section a width × path table of `(verdict, mean delta — both absolute AND percent change vs. baseline per spec AS US1-1, CI bounds, citation)`, a methodology note that explicitly calls out the "deltas vs. M1-baseline channel config measured on M3 hardware" rule (`research.md` R-8 / spec FR-005 clarifier), and an executive summary that answers SC-001 directly. Off-canonical-width rows (if any from exploratory runs) are presented in a separate sub-table marked exploratory and explicitly excluded from primary recommendations. Depends on T019, T020, T021, T022.
- [X] T024 [US1] Emit the machine-readable companion `docs/benchmarks/m3-channel-tuning.json` from the same `RunCohort` data per `data-model.md`'s schema. Depends on T019, T020, T021, T022.
- [X] T025 [P] [US1] Cross-link from `docs/benchmarks/summary.md` to the new M3 channel-tuning report; add an M3 row to summary.md's comparison table reflecting any wins recorded in T023. Depends on T023.
- [X] T026 [US1] Verify SC-001 (per-axis recommendations exist for each canonical width), SC-002 (max_message_size binding width identified or explicitly stated as non-binding at canonical widths), SC-003 (every "recommend" verdict has `candidate_ci_lower > baseline_ci_upper` in the JSON), SC-005 (every "recommend" has a citation), and FR-007 (citations resolve via the M2 ground-truth workflow — spot-check at least three by running `graphify path "<symbol>" "<related>" --graph ~/.graphify/repos/grpc/grpc/src/python/grpcio/graphify-out/graph.json`). Depends on T023, T024.
- [X] T027 [US1] **P1 closure gate (FR-008)**: confirm in `m3-channel-tuning.json` that all four axes have a recorded verdict in `{recommend, no_winner, not_measurable}`. Tag the frozen P1-channel-config that becomes the P2 baseline (the union of each axis's winning configuration if `recommend`, else the M1_BASELINE setting for that axis); emit it under `docs/benchmarks/m3-channel-tuning.json` as `p1_frozen_config` so US2 can reference by name. Depends on T026.

**Checkpoint**: P1 closes — US1 ships independently as the M3 MVP. The README's M3 section can already be updated with channel-tuning findings even before US2 begins.

---

## Phase 4: User Story 2 — Schema-level (protobuf) message-shape tuning (Priority: P2) — DEFERRED to M4

**Status (2026-05-10)**: ⛔ This phase is **deferred to milestone M4** (`docs/PLAN.md`) per the 2026-05-10 clarifications session in `spec.md`. Rationale: US2 candidates (`packed`, `oneof` flattening, alternative streaming chunk granularity) are most likely to manifest as TTFT wins, and TTFT becomes a defensible verdict metric only under the M4 harness changes (FR-012 / FR-013 / FR-014). Running US2 against the current harness would replicate the bytes-only verdict pattern that motivated the M4 split. T028–T034 below remain as drafted for traceability and will be re-spec'd as part of feature 016 (M4) when that milestone is opened — they will not execute on this branch.

**Goal (preserved as drafted)**: With the P1 channel configuration frozen, measure whether at least one protobuf message-shape candidate moves wire bytes or decode time below the P1 baseline at hidden_size=4096. Document the result honestly even if the candidate loses.

**Independent Test (preserved as drafted)**: A reviewer reads `docs/benchmarks/m3-schema-tuning.md` and finds (a) the candidate proto change documented with the actual `.proto` diff, (b) the P1 channel config it was measured against (linked from `p1_frozen_config` in T027), (c) a verdict block with CI bounds, (d) a citation per FR-009, and (e) explicit notes on whether existing M1 clients must regenerate stubs.

**Gate (preserved as drafted)**: ⛔ Originally gated on T027 (FR-008). T027 is now closed (PR #17), so the gate-on-P1 condition is met. The deferral to M4 is a scope decision, not a gating issue.

### Implementation for User Story 2

- [ ] T028 [US2] Edit `proto/vllm_grpc/v1/chat.proto` to apply the first P2 candidate from `research.md` R-9: mark the chat-completion token-id field as packed (proto3 default-on for repeated scalar fields, but verify the encoding actually changes — if the field is already packed, switch the candidate to the alternative described in R-9 such as `oneof` flattening of the input union, and document the substitution in the `ProtoRevision.description`). Commit on a side-branch or behind a feature toggle so M1 client behaviour is preserved on `main` until the P2 verdict is in.
- [ ] T029 [US2] Run `make proto` to regenerate stubs under `packages/gen/` per Constitution I (Proto-First); confirm CI's "proto stub compile check" still passes. **Then run a pre-flight wire-byte-change verification** before committing to the P2 sweep: serialize one fixture chat-completion message under both the pre-T028 stub and the post-T028 stub, and assert `len(new_bytes) != len(old_bytes)`. If they're equal (e.g., proto3 packed encoding is already default-on for the field T028 targeted, per `research.md` R-9's flagged risk), do not proceed to T030 — instead substitute the alternative candidate from R-9 (`oneof` flattening of the input union, or alternative streaming chunk granularity), update the `ProtoRevision.description`, re-run T028 + T029 + this preflight, then proceed. Depends on T028.
- [ ] T030 [US2] Run the P2 sweep: `python -m vllm_grpc_bench --m3 --p2-revision chat-token-ids-packed --frozen-channel <name from p1_frozen_config> --width 4096 --path chat_stream` (and `--path embed` if the candidate touches embed-path messages). Record verdicts. Depends on T029, T027.
- [ ] T031 [US2] Author `docs/benchmarks/m3-schema-tuning.md`: candidate description, the actual `.proto` diff, frozen P1 channel config reference, verdict + CI bounds, vLLM/grpcio citation per FR-009, compatibility implications. Depends on T030.
- [ ] T032 [US2] Emit `docs/benchmarks/m3-schema-tuning.json` from the same `RunCohort` data. Depends on T030.
- [ ] T033 [US2] Document client-compat implications per FR-009: explicitly flag whether the candidate forces existing M1 clients to regenerate stubs; if it does, weigh that against any wire-byte win in the report's recommendation section. Depends on T031.
- [ ] T034 [US2] Verify SC-004 (at least one P2 candidate measured against the P1 baseline; deltas recorded — even if the candidate loses, the negative result is captured per Constitution V) and SC-005 (citation present). Depends on T031, T032.

**Checkpoint**: US2 ships. Both stories are independently testable and the M3 milestone is complete.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Cleanup, documentation, and merge readiness. **Note (2026-05-10)**: Phase 5 now runs *after* Phase 6 (US3 / Phase A) lands. T037 and T039 are scoped to the US1+US3 deliverables on this branch (US2 deferred to M4); T036's ADR also covers the Phase A immediate-predecessor-baseline pairing rule and the `noise_bounded` verdict literal added under FR-005.

- [ ] T035 [P] Update the README.md "Milestone 3 — Protobuf & gRPC Tuning" section if findings changed the project's narrative (e.g. if a channel-axis recommendation graduates into the project's reference configuration, or if a candidate is rejected and that influences M5 planning). Cross-link both M3 reports (bytes + time). The 2026-05-10 milestone-roadmap renumbering (M4 = Time-Axis, M5 = Corpus, M6 = Models) has already landed; only the M3-section internals need a touch-up here.
- [ ] T036 Add an ADR at `docs/decisions/ADR-NNN-m3-statistical-methodology.md` documenting (a) the n=30 / 95%-CI / lower-CI-vs-upper-CI win rule chosen in `/speckit-clarify` and `research.md` R-1, (b) the immediate-predecessor M1_BASELINE pairing rule used in Phase A per `research.md` R-12, and (c) the `noise_bounded` verdict literal added under FR-005 — per Constitution Workflow ("`docs/decisions/` MUST receive an ADR for any non-obvious architectural choice"). The 95%-CI win bar and the noise-bounded verdict are both non-obvious and worth recording.
- [ ] T037 Run `quickstart.md` end-to-end as a fresh-eyes walkthrough (smoke run + one narrowed axis sweep + one Phase A `--reanalyze` invocation). Capture any documentation drift and patch quickstart.md inline. (US2 / `--p2-revision` invocation is removed from the walkthrough since US2 is deferred to M4.)
- [ ] T038 [P] Run `make check` once more on the merged branch state — confirm 189+ passed, 0 new skips, 0 regressions vs. the M2-merge baseline (PR #17 already lifted the baseline from the original 145).
- [ ] T039 Author the PR description summarizing US1 + US3 findings (US2 explicitly deferred), linking both M3 reports (bytes from PR #17 plus time from this branch), and flagging the M4 hand-off (the `noise_bounded` cells listed in `m3-channel-tuning-time.md`'s Limitations section are M4's input). Confirm the M3 time report and the `summary.md` cross-link update land in the same PR so reviewers can verify SC-006 citation discipline against the actual report.

---

## Phase 6: User Story 3 — Phase A wall-clock time re-analysis (Priority: P1.5)

**Goal**: Extend the published P1 channel-tuning report to cover wall-clock time deltas using the data already in `bench-results/m3-full/m3-channel-tuning.json` — no new sweeps. Defensible time verdicts where the existing harness produced clean signal (compression both paths; embed total wall-clock across all axes; TTFT for chat_stream); honest `noise_bounded` verdicts where the harness can't (chat_stream total wall-clock under any axis, per `research.md` R-11), with explicit M4 hand-off in the Limitations section.

**Independent Test**: A reviewer reads `docs/benchmarks/m3-channel-tuning-time.md` and confirms (a) every axis × width × path cell has a time-metric verdict in `{recommend, no_winner, not_measurable, noise_bounded}`, (b) every chat_stream verdict is computed on TTFT and labeled as such, (c) every `recommend` carries CI-bounded supporting numbers and a citation, (d) the Limitations section names the specific cells M4 must re-measure under the harness redesign.

**Gate**: ⛔ Phase 6 starts after PR #17 merges to `main` (the bytes-axis closure) so the time report has the bytes report to cross-link from.

### Implementation for User Story 3

- [ ] T040 [P] [US3] Extend `tools/benchmark/src/vllm_grpc_bench/m3_sweep.build_recommendations` with two new metric paths: `metric="time"` (uses cohort `time_seconds` mean+CI; intended for embed cells) and `metric="ttft"` (computes per-cohort TTFT mean + 95% CI from `samples[i].time_to_first_token_seconds`; intended for chat_stream cells). Both new paths use **immediate-predecessor M1_BASELINE pairing** (sort cohorts by run-order via the existing JSON layout, pair each candidate with the most recent preceding M1_BASELINE at matching path/width/corpus_subset) per `research.md` R-12. Add a `noise_bounded` verdict literal: emitted when σ_baseline_drift (computed from the spread of consecutive M1_BASELINE cohorts at the same cell) exceeds the candidate's expected effect size. Update the `Recommendation` dataclass invariants to allow `verdict="noise_bounded"` with a populated `notes` field naming the dominating noise source. Depends on the existing T011 m3_sweep module.
- [ ] T041 [P] [US3] Add tests at `tools/benchmark/tests/test_m3_sweep_metrics.py` covering: TTFT computation correctness against a hand-checked sample, immediate-predecessor pairing (when multiple baselines exist, the pre-candidate one is chosen), noise_bounded emission when σ_baseline_drift > expected_win, no regression on existing `metric="bytes"` behaviour for PR-#17-style verdicts. Depends on T040.
- [ ] T042 [US3] Add a `--reanalyze <existing-json>` flag to `python -m vllm_grpc_bench --m3` in `__main__.py` that reads an existing sweep JSON, runs `build_recommendations` with `metric="time"` for embed cohorts and `metric="ttft"` for chat_stream cohorts, and writes a sibling `<existing-json-stem>-time.json`. Exit codes match the existing `--m3` mode contract. Update `contracts/m3-bench-cli.md` with the new flag. Depends on T040.
- [ ] T043 [US3] Run `python -m vllm_grpc_bench --m3 --reanalyze bench-results/m3-full/m3-channel-tuning.json` to produce `bench-results/m3-full/m3-channel-tuning-time.json`. Inspect the verdicts, record observations (which cells produced clean verdicts, which fell to `noise_bounded`, the breakdown of `recommend` / `no_winner` / `not_measurable` by axis × path). Depends on T042.
- [ ] T044 [US3] Author `docs/benchmarks/m3-channel-tuning-time.md` per the M3 report style: per-axis time-metric verdicts (TTFT for chat_stream cells, total wall-clock for embed cells), each with cohort-pair baseline, candidate CIs, citation, and verdict. Methodology section explicitly cites R-11 / R-12 / R-13 / R-14 (mock-pacing dilution, baseline drift, TTFT rationale, Phase A vs. M4 split). Limitations section names every `noise_bounded` cell as an M4 input. Cross-link to `m3-channel-tuning.md` (the bytes report from PR #17). Depends on T043.
- [ ] T045 [US3] Emit `docs/benchmarks/m3-channel-tuning-time.json` from the same data, slim format (no per-iteration samples, mirroring the bytes JSON). Add a `p1_frozen_config_time` field paralleling the existing `p1_frozen_config`: union of each axis's time-metric winner if `recommend`, else M1_BASELINE for that axis (also M1_BASELINE if any axis emitted `noise_bounded` since we cannot freeze a config we couldn't verdict). Depends on T043.
- [ ] T046 [US3] Update `docs/benchmarks/summary.md` §4: add a sub-table for the time-metric verdicts (rows: axis, time-metric verdict, supporting Δ%, citation), tagged TTFT-for-chat_stream / wall-clock-for-embed where applicable, and a cross-link to `m3-channel-tuning-time.md`. Note the M4 hand-off explicitly. Depends on T044, T045.
- [ ] T047 [US3] Verify SC-006 (per-axis time-metric recommendations exist for each canonical width OR are explicitly recorded as `noise_bounded` with supporting σ_baseline_drift numbers), FR-014 (every chat_stream verdict labeled TTFT), and the new `noise_bounded` verdict literal's notes-field invariant (every `noise_bounded` cell names its dominating noise source). Spot-check one TTFT computation by hand: pull `time_to_first_token_seconds` for one chat_stream baseline cohort's 30 samples, compute mean and CI manually, compare to the JSON. Depends on T044, T045.

**Checkpoint**: Phase 6 closes — Phase A re-analysis published. Outstanding `noise_bounded` cells documented in the report's Limitations section as inputs to M4. M3 closes after Phase 5 polish runs over the combined US1+US3 deliverables.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup; **BLOCKS** US1 and US2.
- **US1 (Phase 3)**: Depends on Foundational; the four axis sweeps (T019–T022) gate report authoring (T023, T024); SC verification (T026) gates P1 closure (T027).
- **US2 (Phase 4)**: ⛔ Hard-gated on T027 (FR-008). Cannot begin partial.
- **Polish (Phase 5)**: Depends on US1 (T035 can proceed after T026 even if US2 isn't done; T036/T038/T039 require both US1 and US2 if US2 is in scope for this PR).

### User Story Dependencies

- **US1 (P1)**: Independent. Ships as M3 MVP after T027.
- **US2 (P2)**: Hard-gated on US1 closure (FR-008 → T027). Per the user's explicit sequencing direction in `/speckit-clarify`, partial P1 closure does not unblock P2.

### Within Each User Story

- US1: each axis sweep (T019–T022) is independent of the others — they could be parallelized by separate operators, but in practice are run by the same harness sequentially since they share the same machine. The report tasks (T023, T024) require all four axes done.
- US2: T028 → T029 → T030 → T031/T032/T033 → T034 is a strict chain. **Status (2026-05-10)**: deferred to M4; this chain does not execute on the 015 branch.
- US3 (Phase A): T040 [P] T041 → T042 → T043 → T044 [P] T045 → T046 → T047. The `--reanalyze` path (T042) requires the new metric paths in `build_recommendations` (T040). Report authoring (T044, T045) waits on the re-analysis run (T043). Verification (T047) gates Phase 5 polish on the US3 deliverables.

### Parallel Opportunities

- **Phase 1**: T002 [P] runs alongside T001's verifications.
- **Phase 2 — implementation block**: T003, T004, T005, T006, T007 are all [P] (different files, no inter-dependency). After T004 lands, T009 and T010 [P] alongside T008.
- **Phase 2 — test block**: T013, T014, T015, T016, T017, T018 are all [P] once their respective implementation tasks land.
- **Phase 3**: T019 / T020 / T021 / T022 *could* run in parallel on multiple machines, but operationally run sequentially on one host. T025 [P] runs alongside T026 once T023 is published.
- **Phase 5**: T035 [P] alongside T036; T038 [P] alongside T039.
- **Phase 6 (US3)**: T040 [P] (recommendation builder extensions) runs alongside T041 [P] (the matching unit tests). T044 [P] (markdown report) runs alongside T045 [P] (JSON companion) once the re-analysis (T043) is done.

### Critical-Path Sketch

```text
T001 → T002  (Setup)
       │
       ├──► T003,T004,T005,T006,T007 (parallel, foundational impl block A)
       │      │
       │      ├──► T008,T009,T010 (plumbing, depends on T004)
       │      ├──► T011 (sweep orchestrator, depends on T003,T004,T005,T006)
       │      └──► T013,T014,T015 (foundational tests, depend on impls)
       │             │
       │             └──► T012 (CLI mode, depends on T011)
       │                     │
       │                     └──► T016,T017,T018 (integration tests)
       │                              │
       │                              └──► T019,T020,T021,T022 (US1 axis sweeps, sequential on one host)
       │                                       │
       │                                       └──► T023,T024 → T025,T026 → T027 (P1 closes — shipped in PR #17)
       │                                                                          │
       │                                                                          ├──► T028 → T029 → T030 → T031,T032,T033 → T034 (US2 — DEFERRED to M4)
       │                                                                          │
       │                                                                          └──► T040,T041 → T042 → T043 → T044,T045 → T046 → T047 (US3 / Phase A)
       │                                                                                                                              │
       │                                                                                                                              └──► T035–T039 (Polish, scoped to US1+US3)
```

---

## Implementation Strategy

### MVP (User Story 1 only — P1 channel-level tuning)

The original two-PR plan was Phases 1–3 (US1) then Phase 4+5 (US2+Polish). **Updated 2026-05-10** after PR #17 merged:

- **PR 1 (shipped 2026-05-10, PR #17)** = Phases 1–3 (Setup + Foundational + US1, bytes-axis closure) → published `docs/benchmarks/m3-channel-tuning.{md,json}`, closed P1 on the bytes metric, opened FR-008 gate.
- **PR 2 (next, this branch)** = Phase 6 (US3 / Phase A wall-clock re-analysis) + Phase 5 (Polish, scoped to US1+US3 deliverables) → publishes `docs/benchmarks/m3-channel-tuning-time.{md,json}`, closes M3.
- **PR 3 (deferred to M4)** = US2 (proto-shape candidates) + Phase B harness redesign — re-spec'd as feature 016 in `docs/PLAN.md`'s M4 entry.

This split reflects the 2026-05-10 spec clarifications (wall-clock as primary metric) and the empirical finding that the M3 harness cannot defensibly verdict chat_stream total wall-clock without the M4 redesign. Bytes-axis numbers are already in front of reviewers; the time-axis interim numbers ship next.

### Single-PR option

No longer applicable: PR #17 already closed the bytes-axis chunk. Remaining work flows as PR 2 above.

### Test discipline

- All Foundational tests (T013–T018) MUST pass green before any US1 sweep is run — otherwise sweep results are unattributable to channel tuning vs. plumbing bugs.
- Foundational tests are CPU-only and CI-eligible (per the smoke mode); they should run in `make check` going forward.
- US1 and US2 sweep results are not unit tests — they're benchmark artefacts. Do not gate `make check` on them.
- US3 (Phase A) tests (T041) are CPU-only and DO run in `make check` — they're unit tests for the recommendation builder's new metric paths and the `noise_bounded` verdict logic. The Phase A re-analysis output (T043) is a benchmark artefact and is not in `make check`.

---

## Format Validation

Spot-check confirms every task above adheres to `- [ ] TXXX [P?] [Story?] description with file path` per the skill's CRITICAL formatting rule.

- Setup tasks: T001, T002 — no story label ✅
- Foundational tasks: T003–T018 — no story label (T016 carries `[US1-prep]` for human readability, not as a Story label proper; it lives in Foundational because it verifies foundational artefacts) ✅
- US1 tasks: T019–T027 — all carry `[US1]` ✅
- US2 tasks: T028–T034 — all carry `[US2]` ✅ (deferred to M4)
- Polish tasks: T035–T039 — no story label ✅
- US3 tasks: T040–T047 — all carry `[US3]` ✅
