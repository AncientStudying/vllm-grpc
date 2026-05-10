---
description: "Task list for M5 — Cross-Host Time-Axis Validation"
---

# Tasks: M5 — Cross-Host Time-Axis Validation

**Input**: Design documents from `/specs/017-m5-cross-host-validation/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Tests are **REQUIRED** for this milestone (Constitution IV "CI is the Merge Gate" — harness mechanics are CI-tested with deterministic small fixtures; the operator-driven full sweep is not part of CI; the Modal-side smoke is secrets-gated). Test tasks below precede the implementation they validate.

**Organization**: Tasks are grouped by user story (US1 / US2 / US3) so each story can be implemented and tested independently per the spec's priority ordering. Within each story, tests come before implementation; implementation honors the spec's FRs and the contracts under `specs/017-m5-cross-host-validation/contracts/`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- All file paths are repository-relative

## Path Conventions

- Harness modules: `tools/benchmark/src/vllm_grpc_bench/`
- Harness tests: `tools/benchmark/tests/`
- Integration tests: `tests/integration/`
- Modal app: `scripts/python/modal_bench_grpc_server.py` (new)
- Production proto: `proto/vllm_grpc/v1/` (untouched in M5)
- Candidate proto namespace: `proto/vllm_grpc/v1/m4-candidates/` (untouched — consumed verbatim from M4)
- Generated stubs: `packages/gen/` (untouched — M5 reuses M4-generated stubs)
- Published reports: `docs/benchmarks/`

---

## Phase 1: Setup (Pre-Flight)

**Purpose**: Confirm the workspace is healthy before extending it.

- [ ] T001 Verify `make proto` regenerates production + `m4-candidates` stubs cleanly with no diff against committed state (pre-flight; protects subsequent refactors from masking unrelated drift)
- [ ] T002 [P] Verify `uv run pytest tools/benchmark/tests/` is currently green on the merge base (defines the test surface M5 extends)
- [ ] T003 [P] Verify `modal` CLI is importable in the workspace (`uv run python -c "import modal; print(modal.__version__)"`) — Modal is needed by `modal_endpoint.py` (Phase 3); failing here means the dep needs to be added to `tools/benchmark/pyproject.toml`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Extend shared dataclasses, add the `EndpointProvider` Protocol, and refactor `m4_sweep.py` to accept an endpoint provider — all of which US1/US2/US3 consume. The M4 default behavior must remain bit-identical.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T004 Extend `tools/benchmark/src/vllm_grpc_bench/m3_types.py`: add `"server_bound"` to the `Verdict` literal (preserve `"client_bound"` and `"noise_bounded"` for M3/M4 compatibility); add new dataclasses `RTTRecord`, `RTTSummary`, `SupersedesM4Entry`, `M5CrossHostBaseline`, `M5RunMetadata` per `specs/017-m5-cross-host-validation/data-model.md`
- [ ] T005 Extend `CohortResult` and `Recommendation` dataclasses in `tools/benchmark/src/vllm_grpc_bench/m3_types.py` with the M5 additive optional fields (`CohortResult`: `rtt_record`, `server_overhead_estimate_ms`, `server_bound`, `low_rtt_caveat`, `discarded` — all default to None/False; `Recommendation`: `supersedes_m4_cell` defaults to None) per `data-model.md` (depends on T004 — same file)
- [ ] T006 Add `EndpointProvider` Protocol and `EndpointTuple` TypeAlias to `tools/benchmark/src/vllm_grpc_bench/m3_types.py` per `data-model.md` (depends on T005 — same file)
- [ ] T007 [P] Add `serve_in_process_adapter` wrapper to `tools/benchmark/src/vllm_grpc_bench/m3_sweep.py`: an async context manager that wraps the existing `serve_in_process(engine, channel_config)` and yields `(addr, None, None)` — i.e., insecure channel + no call metadata. Conforms to `EndpointProvider` Protocol so M4 callers can pass it explicitly. Existing `serve_in_process` is untouched (additive change only)
- [ ] T008 Refactor `tools/benchmark/src/vllm_grpc_bench/m4_sweep.py`: add `endpoint_provider: EndpointProvider = serve_in_process_adapter` keyword argument to every function that currently calls `serve_in_process(engine, cfg)` directly (per the M4 sweep entry points and the per-cell measurement helpers); replace the in-place `async with serve_in_process(engine, drive_cell.channel_config) as addr:` block with `async with endpoint_provider(engine, drive_cell.channel_config) as (target, credentials, metadata):`; thread `target`, `credentials`, and `metadata` into the gRPC channel construction site (use `grpc.aio.secure_channel(target, credentials, options=...)` when credentials is non-None, else `grpc.aio.insecure_channel(target, options=...)`); pass `metadata` into every per-RPC call via the `metadata=` kwarg. Existing M4 callers without an explicit `endpoint_provider` argument get the `serve_in_process_adapter` default, preserving bit-identical M4 behavior (depends on T007 — different files but T007 provides the adapter)
- [ ] T009 [P] Test: `serve_in_process_adapter` yields the same address shape and lifecycle as `serve_in_process`; using it in a small fixture sweep produces a cohort whose timings match the legacy direct-`serve_in_process` path within float-equality tolerance, in `tools/benchmark/tests/test_endpoint_provider.py` (covers T007 backward-compat guarantee)
- [ ] T010 [P] Test: `m4_sweep.run_m4_sweep` invoked without an explicit `endpoint_provider` argument produces a `Run` whose cohort fingerprint (cohort_id, n, sample-array length, recommendation list) is byte-identical to the pre-refactor version on a small fixture, in `tools/benchmark/tests/test_m4_sweep.py` (modified). This is the critical bit-identical-M4-reproduction guard for T008
- [ ] T011 [P] Test: validation invariants for the new dataclasses — `RTTRecord` rejects `n < 1` and negative samples; `SupersedesM4Entry.verdict_changed` is `True` iff either verdict-time or verdict-bytes literal differs between M4 and M5; `CohortResult` with `discarded=True` is silently skipped by aggregation helpers, in `tools/benchmark/tests/test_m5_types.py` (new) (covers data-model.md)

**Checkpoint**: Foundation ready — US1, US2, US3 may begin. The M4 sweep is verifiably bit-identical to before the refactor (T010 gate).

---

## Phase 3: User Story 1 — Resolve M4's Loopback-Flagged Channel Verdicts on Real Wire (Priority: P1) 🎯 MVP

**Goal**: Stand up the cross-host gRPC server on Modal (CPU-only, TLS-terminated, bearer-token-auth), deploy/teardown via a single CLI invocation, run an active RTT probe before each cohort, classify cohorts as `server_bound` when remote server overhead dominates transport, annotate `low_rtt_caveat` when measured RTT is below the exercise threshold, run the four-axis × three-width × two-path channel sweep against the M5 cross-host shared-baseline cohort, and emit the channel-sweep section of the M5 report. This is the *prerequisite axis* of M5 — without it, no M5 verdict is defensible.

**Independent Test** (per spec US1 acceptance scenarios): a reviewer runs `uv run python -m vllm_grpc_bench --m5 --m5-modal-region=eu-west-1` and confirms (a) every axis × hidden_size 2048 / 4096 / 8192 × path cell carries a verdict, (b) cells M4 flagged with the loopback caveat carry an M5 verdict (`recommend` or `no_winner`) with `loopback_caveat: false`, (c) every cohort entry in the JSON includes a measured RTT distribution, (d) any verdict that contradicts M4 appears as a "Supersedes M4" row (though the full Supersedes-M4 table is US3's deliverable; US1 emits the per-verdict `supersedes_m4_cell` field).

### Tests for User Story 1 (write FIRST, ensure they FAIL before implementation)

- [ ] T012 [P] [US1] Test: `rtt_probe.measure_rtt` runs N consecutive unary `Health.Check` RPCs against a stub server, returns an `RTTRecord` whose `n`, `median_ms`, `p95_ms`, and `samples_ms` match the synthetic timings within float tolerance, in `tools/benchmark/tests/test_rtt_probe.py` (new) (covers research.md R-3 / FR-004)
- [ ] T013 [P] [US1] Test: `rtt_probe.measure_rtt` gates verdict emission — when median RTT < 1.0 ms, the caller is expected to mark the cohort `not_measurable` with reason `"rtt_below_validity_threshold"`; verify the helper returns a recognizable sentinel or raises a documented exception, in `tools/benchmark/tests/test_rtt_probe.py` (covers FR-004)
- [ ] T014 [P] [US1] Test: `low_rtt_caveat` annotator sets the flag iff `rtt_record.median_ms < rtt_exercise_threshold_ms` (default 20.0 ms); cohorts above the threshold do NOT get the flag, in `tools/benchmark/tests/test_m5_sweep.py` (new)
- [ ] T015 [P] [US1] Test: `server_bound` classifier — given a synthetic cohort with median_wallclock=200ms, RTT=80ms, and an `m4_client_overhead_floor_ms=2ms`, the classifier computes `server_overhead_estimate_ms = 118ms` and sets `server_bound=True` iff `server_overhead_estimate_ms > max(2 × 80ms, 50ms) = 160ms` AND CV-comparison gate trips; flips to `False` when CV is comparable to M4 loopback CV, in `tools/benchmark/tests/test_m5_server_bound.py` (new) (covers research.md R-4 / FR-005)
- [ ] T016 [P] [US1] Test: warm-up cohort handling — when `--m5-warmup-n=32` is set, the first cohort per path is tagged `discarded=True` and is excluded from every aggregate computation (shared-baseline construction, recommendation building, run-level RTT summary); when `--m5-warmup-n=0`, no warm-up cohort is emitted and the reporter logs a closing stderr warning, in `tools/benchmark/tests/test_m5_sweep.py` (covers research.md R-5)
- [ ] T017 [P] [US1] Test: M5 cross-host shared-baseline — `m5_sweep` records exactly one M5 baseline cohort per path against the cross-host endpoint with the M1-default channel configuration, sized at n ≥ `--baseline-n` (default 100); the cohort is NOT a copy of any M3 or M4 baseline cohort, in `tools/benchmark/tests/test_m5_sweep.py` (covers FR-008)
- [ ] T018 [P] [US1] Test: bearer-token plumbing — `modal_endpoint.provide_endpoint` reads the bearer token from the env var named by `token_env`, attaches it as `("authorization", f"Bearer {token}")` call metadata in the yielded `EndpointTuple`, and refuses to enter the context manager when the env var is unset (raises `RuntimeError` with a clear message), in `tools/benchmark/tests/test_modal_endpoint.py` (new) — uses a Modal-stub to avoid real network contact (covers FR-002 / research.md R-1)
- [ ] T019 [P] [US1] Test: CLI flag wiring for the M5-specific flags (`--m5`, `--m5-modal-region`, `--m5-modal-token-env`, `--m5-rtt-validity-threshold-ms`, `--m5-rtt-exercise-threshold-ms`, `--m5-warmup-n`, `--m5-skip-deploy`, `--m5-modal-endpoint`), including mutual-exclusion (`--m5` vs `--m4` vs `--m3`) and arithmetic gates (`--m5-skip-deploy` requires `--m5-modal-endpoint`), with exit code 2 on violation, in `tools/benchmark/tests/test_m5_cli.py` (new) (covers contract `m5-bench-cli.md`)
- [ ] T020 [P] [US1] Test: M5 report layout — given a synthetic small `Run` containing M5 cohorts, the reporter writes a JSON file with the new top-level fields (`m5_methodology_version`, `m5_modal_region`, `m5_rtt_summary_ms`, etc. per `m5-report-schema.md`) and a Markdown file whose section order matches `quickstart.md` "Reading the report", in `tools/benchmark/tests/test_m5_reporter.py` (new) (covers contract `m5-report-schema.md`)

### Implementation for User Story 1

- [ ] T021 [P] [US1] Create `tools/benchmark/src/vllm_grpc_bench/rtt_probe.py` with `measure_rtt(channel: grpc.aio.Channel, n: int = 32, metadata: tuple[tuple[str,str], ...] | None = None) -> RTTRecord` per research.md R-3: runs `n` consecutive `health_pb2.HealthCheckRequest()` unary RPCs against the same channel, captures per-call wall-clock, returns an `RTTRecord(n, median_ms, p95_ms, samples_ms)`. Imports the health stub from `packages/gen/` (existing M3 stubs)
- [ ] T022 [P] [US1] Create `scripts/python/modal_bench_grpc_server.py` per `contracts/m5-modal-app.md`: defines `app = modal.App("vllm-grpc-bench-mock")`; image is `modal.Image.debian_slim(python_version="3.12").pip_install(grpcio, grpcio-tools, numpy, protobuf).add_local_python_source(vllm_grpc_frontend, vllm_grpc_gen, vllm_grpc_bench)`; CPU-only `@app.function`; `BearerTokenInterceptor` gRPC ServerInterceptor; `serve_bench(token, region)` async function registers **both** the M3 production servicers (`M3CompletionsServicer`, `M3ChatServicer`) **and** the three M4 candidate servicers (`PackedTokenIdsServicer`, `OneofFlattenedInputServicer`, `ChunkGranularityServicer` from `packages.gen.vllm_grpc_m4_candidates`) on the same gRPC port 50051 — candidate protos are in a distinct proto namespace so service names do not collide — then opens `modal.forward(50051, unencrypted=False)`, publishes endpoint + token + region + ready=True to `modal.Dict("vllm-grpc-bench-mock-handshake")`, blocks on `teardown==True`, then stops the gRPC server cleanly
- [ ] T023 [US1] Create `tools/benchmark/src/vllm_grpc_bench/modal_endpoint.py` per research.md R-2: `provide_endpoint(engine, channel_config, *, region, token_env) -> AsyncIterator[EndpointTuple]` is an `@asynccontextmanager` that (a) reads bearer token from env, (b) enters `app.run.aio()` against the Modal app from T022, (c) calls `serve_bench.spawn.aio(token=..., region=...)`, (d) polls `modal.Dict("vllm-grpc-bench-mock-handshake")` for `ready==True` with timeout 120s (raise on timeout for exit code 3), (e) yields `(endpoint, grpc.ssl_channel_credentials(), (("authorization", f"Bearer {token}"),))`, (f) on exit signals `teardown=True` and awaits the spawned call to drain (depends on T022)
- [ ] T024 [US1] Create `tools/benchmark/src/vllm_grpc_bench/m5_sweep.py` skeleton with `run_m5_sweep(config: M5SweepConfig) -> Run` signature, `M5SweepConfig` dataclass (with `modal_region`, `token_env`, `rtt_validity_threshold_ms`, `rtt_exercise_threshold_ms`, `warmup_n`, plus all M4SweepConfig fields by composition), and stub helpers (`run_warmup_cohorts`, `measure_m5_shared_baseline`, `classify_server_bound`, `annotate_low_rtt_caveat`)
- [ ] T025 [US1] Implement warm-up cohort discard in `tools/benchmark/src/vllm_grpc_bench/m5_sweep.py`: `run_warmup_cohorts` runs one cohort per path with the cross-host endpoint at n = `config.warmup_n` (default 32), tags `discarded=True`, appends to `Run.cohorts` (so the JSON records the warm-up cost for reader visibility), but excludes from every aggregate computation. Logs a closing stderr warning when `config.warmup_n == 0` (depends on T024 — same file)
- [ ] T026 [US1] Implement M5 cross-host shared-baseline measurement in `tools/benchmark/src/vllm_grpc_bench/m5_sweep.py`: `measure_m5_shared_baseline` measures one cohort per path at n ≥ `config.baseline_n` against the cross-host endpoint with M1-default channel configuration; tags `is_baseline=True, baseline_role="m1_shared"`; rejects with exit code 8 when median RTT < `config.rtt_validity_threshold_ms`; populates `Run.shared_baseline_cohort_ids` and an `M5CrossHostBaseline` record (depends on T025 — same file)
- [ ] T027 [US1] Implement `server_bound` classifier in `tools/benchmark/src/vllm_grpc_bench/m5_sweep.py`: `classify_server_bound(cohort, rtt_record, m4_client_overhead_floor_ms_for_path)` computes `server_overhead_estimate_ms = cohort.wall_clock_median - rtt_record.median_ms - m4_client_overhead_floor_ms_for_path`; flags `server_bound=True` when `server_overhead_estimate_ms > max(2 * rtt_record.median_ms, 50.0)` AND `cohort.time_cv > (m4_loopback_cv_for_path * 2.0)`. Loads the per-path `m4_client_overhead_floor_ms` and `m4_loopback_cv` constants from `docs/benchmarks/m4-time-axis-tuning.json` on harness startup (R-4) (depends on T026 — same file)
- [ ] T028 [US1] Implement `low_rtt_caveat` annotator in `tools/benchmark/src/vllm_grpc_bench/m5_sweep.py`: `annotate_low_rtt_caveat(cohort, rtt_record, threshold_ms)` sets `cohort.low_rtt_caveat = rtt_record.median_ms < threshold_ms` (depends on T027 — same file)
- [ ] T029 [US1] Implement the channel-sweep driver in `tools/benchmark/src/vllm_grpc_bench/m5_sweep.py`: for each `(axis, width, path, candidate_config)` tuple from `config.axes × config.widths × config.paths × <per-axis candidate configs>` (reuse `tools/benchmark/src/vllm_grpc_bench/channel_config.py` presets unchanged), call `rtt_probe.measure_rtt` first, refuse-or-annotate per FR-004, then delegate the per-cell candidate measurement to `m4_sweep.measure_candidate` (passing `endpoint_provider=modal_endpoint.provide_endpoint`) at n ≥ `config.candidate_n` with the borderline-expand cascade inherited from M4. Append the cohort to `Run.cohorts` with the RTT record, server_bound flag, and low_rtt_caveat annotation. Always set `cohort.loopback_caveat=False` (FR-007) (depends on T028, T008 — m4_sweep refactor must be done)
- [ ] T030 [US1] Implement M5 recommendation builder in `tools/benchmark/src/vllm_grpc_bench/m5_sweep.py`: `build_m5_recommendations(run: Run) -> list[Recommendation]` applies the FR-009 strict-CI-clearance rule against the M5 shared-baseline; excludes cohorts flagged `client_bound`, `server_bound`, or `discarded` from `recommend` tallies; populates `Recommendation.supersedes_m4_cell` from a lookup against `m4-time-axis-tuning.json` when the M5 cell matches an M4 cell on `(axis, hidden_size, path, config_name)`. Skips `noise_bounded` literal (raises `ValueError` if any recommendation would carry it — same guard as M4 FR-007) (depends on T029 — same file)
- [ ] T031 [US1] Add the M5 CLI flags listed in `contracts/m5-bench-cli.md` to `tools/benchmark/src/vllm_grpc_bench/__main__.py`: `--m5`, `--m5-modal-region` (default `auto-far`), `--m5-modal-token-env` (default `MODAL_BENCH_TOKEN`), `--m5-rtt-validity-threshold-ms` (default 1.0), `--m5-rtt-exercise-threshold-ms` (default 20.0), `--m5-warmup-n` (default 32), `--m5-skip-deploy`, `--m5-modal-endpoint`. Validate mutual-exclusion (`--m5` vs `--m4` vs `--m3`), arithmetic gates (`--m5-skip-deploy` requires `--m5-modal-endpoint`), and env-var presence; exit code 2 on violation
- [ ] T032 [US1] Wire `--m5` flag to invoke `m5_sweep.run_m5_sweep` in `tools/benchmark/src/vllm_grpc_bench/__main__.py`; when `--m5-skip-deploy` is set, swap `modal_endpoint.provide_endpoint` for a thin `static_endpoint_provider(target, token)` that yields the explicit endpoint without deploying (depends on T031 — same file; depends on T030 for the orchestrator entry point)
- [ ] T033 [P] [US1] Extend `tools/benchmark/src/vllm_grpc_bench/reporter.py` with M5 report layout: emit the new top-level fields (`m5_methodology_version=1`, `m5_modal_app_name`, `m5_modal_region`, `m5_runtime_wallclock_seconds`, `m5_rtt_summary_ms`, `rtt_validity_threshold_ms`, `rtt_exercise_threshold_ms`, `warmup_n`, `server_bound_overhead_threshold_ms`, `server_bound_cohort_count`); emit per-cohort `rtt_record`, `server_overhead_estimate_ms`, `server_bound`, `low_rtt_caveat`, `discarded` (with M3/M4 cohorts emitting these as `null`/`false`/etc. to preserve strict-superset shape); write to `docs/benchmarks/m5-cross-host-validation.json`. The Markdown companion section order matches `quickstart.md` "Reading the report"; the supersedes_m4 array is left empty (populated by US3)
- [ ] T034 [P] [US1] Integration test (Modal-secrets-gated): `tests/integration/test_m5_modal_smoke.py` deploys the Modal app via `app.run.aio()`, runs a single 10-iteration cohort via `--m5-skip-deploy=false --baseline-n=10 --candidate-n=10 --widths=4096 --paths=embed --axes=max_message_size --schema-candidates=`, asserts the resulting JSON contains exactly one shared-baseline cohort + one candidate cohort each with `rtt_record.median_ms > 1.0`, `loopback_caveat==false`, and `m5_modal_region` populated; gated by `pytest.skipif(not (os.environ.get("MODAL_TOKEN_ID") and os.environ.get("MODAL_TOKEN_SECRET") and os.environ.get("MODAL_BENCH_TOKEN")))`. Teardown is verified by `modal app list | grep vllm-grpc-bench-mock` returning empty after the test

**Checkpoint**: User Story 1 complete — the cross-host channel sweep runs end-to-end on a small fixture against a real Modal deployment; the four acceptance scenarios from spec US1 pass; the M5 JSON carries every cohort's RTT record and the loopback caveat field is `false` on every M5 cohort. Schema candidates (US2) and the full Supersedes-M4 table (US3) are not yet wired but the cross-host infrastructure is in place and verifiable.

---

## Phase 4: User Story 2 — Re-Measure Schema Candidates Against the Cross-Host Frozen Baseline (Priority: P2)

**Goal**: Build per-path frozen-channel baselines from US1's per-axis winners (measured against the cross-host endpoint at hidden_size 4096), run the three named schema candidates (packed scalars on token-id, `oneof` flattening, alternative chunk granularity) against those baselines at hidden_size 4096, cascade to 2048 and 8192 for `recommend`/borderline candidates, emit verdicts on both bytes and time metrics, and append negative results to a "Negative results — do not re-run speculatively" appendix.

**Independent Test** (per spec US2 acceptance scenarios): a reviewer reads the schema-candidates section of `docs/benchmarks/m5-cross-host-validation.md` and confirms (a) each named candidate has a verdict at 4096 against the M5-derived frozen baseline (not M4's), (b) each verdict reports bytes and time deltas with 95% CIs, (c) borderline-or-recommend candidates have cascaded 2048 and 8192 measurements, (d) negative-result candidates appear in the named appendix, (e) each schema verdict cites its M4 predecessor and shows match-or-supersede.

### Tests for User Story 2

- [ ] T035 [P] [US2] Test: M5 frozen-channel baseline composition — for each path, the cohort combines that path's per-axis winners from US1 at hidden_size 4096; absent any US1 winner, the axis falls back to M3 default; the combined config is measured as its own n ≥ 100 cohort against the cross-host endpoint, in `tools/benchmark/tests/test_m5_frozen_baseline.py` (new) (covers FR-010)
- [ ] T036 [P] [US2] Test: schema-candidate 4096-first cascade — a candidate whose 4096 verdict on either bytes or time is `recommend` OR borderline (CI bounds touch baseline CI) triggers measurement at 2048 AND 8192; a candidate whose 4096 verdict is `no_winner` with CIs cleanly inside the baseline CI does NOT trigger the cascade, in `tools/benchmark/tests/test_m5_schema_cascade.py` (new) (covers FR-012)
- [ ] T037 [P] [US2] Test: negative-results appendix — candidates whose 95% CIs overlap the M5 baseline CI on both bytes and time at 4096 are added to a `negative_results: list[NegativeResultEntry]` field on `Run`; the reporter emits them as an "Appendix: Negative results — do not re-run speculatively" section in the Markdown, in `tools/benchmark/tests/test_m5_negative_results.py` (new) (covers FR-013)
- [ ] T038 [P] [US2] Test: schema-candidate cohorts inherit the M5 cross-host instrumentation — every schema cohort entry carries an `rtt_record`, a `server_overhead_estimate_ms`, a `server_bound` flag, and a `low_rtt_caveat` flag just like channel-sweep cohorts, in `tools/benchmark/tests/test_m5_sweep.py` (extension)

### Implementation for User Story 2

- [ ] T039 [US2] Implement M5 frozen-channel baseline builder in `tools/benchmark/src/vllm_grpc_bench/m5_sweep.py`: `build_m5_frozen_channel_baselines(run: Run) -> dict[Path, FrozenChannelBaseline]` reads the channel-sweep verdicts (from `build_m5_recommendations`) and composes per-path winning channel configs at hidden_size 4096; measures each composed config as its own n ≥ 100 cohort against the cross-host endpoint; tags `is_baseline=True, baseline_role="frozen_channel"`; appends to `Run.cohorts` and `Run.frozen_channel_baselines` (depends on T030)
- [ ] T040 [US2] Implement schema-candidate driver in `tools/benchmark/src/vllm_grpc_bench/m5_sweep.py`: for each named candidate in `config.schema_candidates` (default `["packed_token_ids", "oneof_flattened_input", "chunk_granularity"]`), import the matching servicer + stub variant from `packages/gen/vllm_grpc_m4_candidates/` (reuse M4's namespace verbatim), wire it into a fresh Modal-side servicer registration for the candidate run (the M5 Modal app registers candidate variants alongside the production-shape servicers — see T041), then measure the candidate cohort against the M5 frozen-channel baseline; emit verdicts on bytes AND time per FR-012 (depends on T039 — same file)
- [ ] T041 [US2] Extend the harness's per-cohort gRPC channel construction in `tools/benchmark/src/vllm_grpc_bench/m5_sweep.py` to switch between calling the production servicer methods (for channel-sweep cohorts) and the candidate servicer methods (for schema-candidate cohorts) against the same Modal endpoint — no Modal redeploy needed since T022 already registers all servicers on port 50051. The active schema-candidate name (`packed_token_ids` | `oneof_flattened_input` | `chunk_granularity`) on the candidate sweep config determines which servicer stub the per-cohort client invokes (depends on T022, T040)
- [ ] T042 [US2] Implement schema-candidate cascade logic in `tools/benchmark/src/vllm_grpc_bench/m5_sweep.py`: after the 4096 cohort lands, if either bytes or time verdict is `recommend` OR borderline, schedule additional cohorts at 2048 and 8192; if `no_winner` cleanly, skip cascade and mark as negative-result candidate (FR-012 / FR-013) (depends on T040 — same file)
- [ ] T043 [US2] Implement negative-results collection in `tools/benchmark/src/vllm_grpc_bench/m5_sweep.py`: candidates whose 4096 CIs overlap the baseline CI on both metrics are added to `Run.negative_results` with the supporting numbers; the reporter (T044) emits them in an appendix (depends on T042 — same file)
- [ ] T044 [P] [US2] Extend `tools/benchmark/src/vllm_grpc_bench/reporter.py` with schema-candidate section emission: per-candidate verdict table (bytes + time CIs, M4 verdict citation, M5 verdict, supersedes-flag); "Negative results — do not re-run speculatively" appendix; both written to `m5-cross-host-validation.md` and recorded in the JSON's `schema_candidate_results` array (preserving M4's schema for that field, additively extended with `m5_supersedes_m4_candidate`)

**Checkpoint**: User Story 2 complete — schema candidates are measured against the M5 frozen-channel baseline; the cascade rule fires correctly; negative results are appendixed. The Supersedes-M4 supersession table is not yet emitted (US3's deliverable) but per-verdict `supersedes_m4_cell` fields are populated.

---

## Phase 5: User Story 3 — Single-Glance Comparison of M4 and M5 Verdicts (Priority: P3)

**Goal**: Emit the "Supersedes M4" table that names every M4 cell M5 supersedes (every loopback-caveated M4 cell + any M4 cell whose M5 verdict differs on either metric), with verdict-changed rows visually distinguished from verdict-confirmed rows, in both the JSON's top-level `supersedes_m4` array and the Markdown companion's table section.

**Independent Test** (per spec US3 acceptance scenarios): a reviewer opens `docs/benchmarks/m5-cross-host-validation.md` and confirms (a) every M4 cell with `loopback_caveat: true` has a corresponding "Supersedes M4" row, (b) verdict-changed rows are visually distinguished (e.g., bold or in a separate sub-table), (c) every M5 supersession row cites the M4 source by cell coordinates (axis, hidden_size, path) and the M4 verdict literal.

### Tests for User Story 3

- [ ] T045 [P] [US3] Test: `m5_supersede.build_supersedes_m4_table` reads `docs/benchmarks/m4-time-axis-tuning.json` plus an in-memory `Run` and produces a `SupersedesM4Entry` for every M4 cell where (a) `loopback_caveat == True` OR (b) `m4_verdict_time != m5_verdict_time` OR `m4_verdict_bytes != m5_verdict_bytes`; `verdict_changed` is set correctly on each entry; **`expected_class` is set per the four-value classifier with synthetic input exercising each of `verdict_confirmed`, `loopback_resolution`, `transport_resolution`, `unexpected_supersession`**, in `tools/benchmark/tests/test_m5_supersede.py` (new) (covers FR-015 / SC-004 / spec Edge Cases)
- [ ] T046 [P] [US3] Test: `m5_supersede` emits zero entries when M5 confirms every M4 verdict and no M4 cell was loopback-caveated (trivial control case), in `tools/benchmark/tests/test_m5_supersede.py` (covers FR-015 boundary)
- [ ] T047 [P] [US3] Test: reporter emits a Markdown "Supersedes M4" table whose rows are sorted by `verdict_changed` descending (changed rows first), then by `(path, axis, hidden_size)`; the table headers include `M4 Verdict (time/bytes)`, `M5 Verdict (time/bytes)`, `M5 CI`, `Rationale`, and a visual changed-marker (e.g., a leading `**[changed]**`), in `tools/benchmark/tests/test_m5_reporter.py` (extension) (covers SC-004 visual distinction)

### Implementation for User Story 3

- [ ] T048 [US3] Create `tools/benchmark/src/vllm_grpc_bench/m5_supersede.py` per FR-015: `build_supersedes_m4_table(run: Run, m4_report_path: Path) -> list[SupersedesM4Entry]` reads the M4 JSON, joins each M4 cell against the matching M5 cell on `(path, hidden_size, axis, config_name)`, emits a `SupersedesM4Entry` per cell that meets the FR-015 conditions, populates `verdict_changed`, and writes a one-line rationale combining the verdict transition and the supporting CI delta (e.g., `"real RTT exposed a 5.4% TTFT reduction under keepalive=enabled at hidden_size 4096"`). **Also populates `expected_class` per the four-value classifier**: `verdict_confirmed` when verdicts match; `loopback_resolution` when M4 had `loopback_caveat == True` AND verdict changed; `transport_resolution` when axis ∈ {`keepalive`, `http2_framing`} AND M4 had no loopback caveat AND verdict changed; `unexpected_supersession` when axis ∈ {`max_message_size`, `compression`} AND verdict changed. Citation discovery for time-metric verdict-changed rows is delegated to T050a
- [ ] T049 [US3] Wire `m5_supersede.build_supersedes_m4_table` into `tools/benchmark/src/vllm_grpc_bench/m5_sweep.py` as the final orchestration step (after `build_m5_frozen_channel_baselines` and the schema sweep); populate `Run.supersedes_m4` (depends on T048)
- [ ] T050 [P] [US3] Extend `tools/benchmark/src/vllm_grpc_bench/reporter.py` with the "Supersedes M4" table section: emit JSON `supersedes_m4` array (top-level); emit Markdown table with verdict-changed rows visually distinguished and sorted-first per SC-004; **`unexpected_supersession` rows additionally carry a leading `**[unexpected]**` marker and are grouped under a separate `### Unexpected supersessions — investigate before adopting` sub-heading per spec Edge Cases** (depends on T044 reporter scaffold)

- [ ] T050a [US3] Extend `tools/benchmark/src/vllm_grpc_bench/m5_supersede.py` and `tools/benchmark/src/vllm_grpc_bench/reporter.py` to emit cross-repo citations per FR-017 + the M2 ground-truth workflow: for every `SupersedesM4Entry` whose `verdict_changed == True` AND whose verdict change is on the time metric (`m4_verdict_time != m5_verdict_time`), populate the entry's `citations: tuple[Citation, ...]` field with one or more `Citation(repo, file_path, identifier, justification)` entries sourced via `cross-repo.json` for cross-repo paths and the targeted single-repo graphs (`~/.graphify/repos/vllm-project/vllm/` and `~/.graphify/repos/grpc/grpc/`) for repo-specific evidence, per CLAUDE.md navigation rules. Citation discovery is driven by the supersession's `(axis, m5_verdict_time)` and a small per-axis hint table (e.g., `keepalive` → grpc C-core HTTP/2 keepalive sources; `compression` → grpcio Python wrapper compression options + grpc C-core compression registry). The Markdown reporter inlines citations as footnotes under each rationale; the JSON `supersedes_m4[i].citations` array carries the structured tuple (covers FR-017) (depends on T048)

- [ ] T050b [P] [US3] Test: citation emission — `m5_supersede.build_supersedes_m4_table` populates `citations` only on time-metric verdict-changed entries (`m4_verdict_time != m5_verdict_time`), and emits zero citations on bytes-only changes or on `verdict_confirmed` rows; integration assertion: the smoke fixture's verdict-changed time-metric row carries at least one `Citation` whose `repo` is `vllm-project/vllm` or `grpc/grpc` and whose `file_path` is non-empty, in `tools/benchmark/tests/test_m5_supersede.py` (extension of T045's test file) (covers FR-017)

**Checkpoint**: User Story 3 complete — the "Supersedes M4" table is emitted in both JSON and Markdown; verdict-changed rows are visually distinguished; the M4 report stays unedited (forward-only supersession per FR-015).

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation update, type-check / lint pass, end-to-end small-sweep verification, and gitignore additions.

- [ ] T051 [P] Update `docs/PLAN.md` v4: tick M5 from "upcoming" to "active" while implementation is in flight, then to "delivered" once the M5 report lands. Cite the M5 report path
- [ ] T052 [P] Add `bench-results/m5-full/` to `.gitignore` (per plan.md "transient per-iteration timing arrays land under `bench-results/m5-full/` (gitignored)")
- [ ] T053 [P] Run `uv run ruff format tools/benchmark/src/vllm_grpc_bench/ scripts/python/modal_bench_grpc_server.py tools/benchmark/tests/ tests/integration/test_m5_modal_smoke.py` and `uv run ruff check ...` until clean; fix any newly-introduced issues
- [ ] T054 [P] Run `uv run mypy --strict tools/benchmark/src/vllm_grpc_bench/` and confirm zero errors (Constitution IV requires `mypy --strict` zero on every runtime-imported module). The new `modal_endpoint.py`, `m5_sweep.py`, `m5_supersede.py`, and `rtt_probe.py` modules MUST type-check strict
- [ ] T055 [P] Add `modal` to `tools/benchmark/pyproject.toml` (or the workspace-level `pyproject.toml` if that's where benchmark deps live) — verify the dep is captured in `uv.lock`. The `vllm_grpc_bench` package imports `modal` from `modal_endpoint.py`, so this must be a first-class declared dep, not a transitive
- [ ] T056 End-to-end small-fixture verification: run `uv run python -m vllm_grpc_bench --m5 --m5-modal-region=eu-west-1 --baseline-n=20 --candidate-n=20 --widths=4096 --paths=embed --axes=max_message_size --schema-candidates=packed_token_ids` and confirm (a) exit code 0, (b) `docs/benchmarks/m5-cross-host-validation.{md,json}` is written, (c) the run-level RTT median is > 20 ms, (d) the JSON `supersedes_m4` array contains at least one entry pointing at the M4 `keepalive` loopback-caveat cells (even though we didn't sweep keepalive — the supersession-table builder catches every M4 loopback-caveat cell whose M5 cell EXISTS; for cells we didn't measure, no supersession row is emitted). Manual operator step; not a `pytest` test
- [ ] T057 Update the `M5 status (in flight on 017-m5-cross-host-validation)` section of the project-status memory once the harness lands and once the published report lands (auto-memory is the right home for this — the spec/plan/tasks are immutable history)

---

## Dependency Graph

```text
Phase 1 (Setup): T001 → T002 [P] → T003 [P]
                            │
                            ▼
Phase 2 (Foundational): T004 → T005 → T006 → T007 [P] → T008
                                                 │       │
                                                 ▼       ▼
                                              T009 [P], T010 [P], T011 [P]
                                                 │
                                                 ▼
                                         Checkpoint: foundation ready
                                                 │
            ┌────────────────────────────────────┼────────────────────────────────────┐
            ▼                                    ▼                                    ▼
Phase 3 (US1, P1, MVP):              Phase 4 (US2, P2):                  Phase 5 (US3, P3):
  T012..T020 [tests, mostly P]         T035..T038 [tests, mostly P]        T045..T047, T050b [tests, mostly P]
       │                                    │                                    │
       ▼                                    ▼                                    ▼
  T021..T034 (impl, mixed P)            T039..T044 (impl, mixed P)          T048..T050a (impl)
       │                                    │                                    │
       ▼                                    ▼                                    ▼
  Checkpoint: cross-host             Checkpoint: schema                  Checkpoint: supersedes-M4
  channel sweep landed               candidates landed                   table landed
                                          │
                                          ▼
                                     Phase 6 (Polish): T051..T057
```

**Critical-path execution order**: T001 → T002/T003 (parallel) → T004 → T005 → T006 → T007 → T008 → US1 (T012..T034) → US2 (T035..T044) → US3 (T045..T050b) → Polish (T051..T057).

**Parallel opportunities**:
- Phase 1: T002 || T003 (different concerns).
- Phase 2: T009 || T010 || T011 (all post-T008 tests, different files).
- Phase 3 (US1): T012 || T013 || T014 || T015 || T016 || T017 || T018 || T019 || T020 (all tests, different files). Within implementation: T021 || T022 (rtt_probe and Modal app are independent files); T033 (reporter) parallel to T034 (integration test) parallel to T024..T030 (m5_sweep).
- Phase 4 (US2): T035 || T036 || T037 || T038 (all tests, different files). T044 parallel to T039..T043.
- Phase 5 (US3): T045 || T046 || T047 || T050b (all tests, different files / extension). T050 parallel to T048..T049; T050a sequential after T048.
- Phase 6: T051 || T052 || T053 || T054 || T055 (all independent polish concerns).

## Implementation Strategy

**MVP scope = User Story 1 (Phase 3)**. After Phase 3 ships, M5's headline-value claim (resolving M4's loopback caveat) is fully delivered: the cross-host channel sweep produces verdicts with `loopback_caveat: false` on every cell, and `Recommendation.supersedes_m4_cell` is populated per-verdict. A reviewer can already answer "did keepalive matter on real wire?" without needing US2 or US3.

**Incremental delivery**:
1. Land Phase 1 + Phase 2 in a PR — the M4 sweep is verifiably bit-identical, the new dataclasses are in place, no functional change ships to users yet.
2. Land US1 in a follow-up PR — M5 headline value delivered; the published report shows channel-sweep verdicts under cross-host transport but the schema-candidate section and Supersedes-M4 table are empty placeholders.
3. Land US2 in a follow-up PR — schema candidates re-measured; report grows the schema section and negative-results appendix.
4. Land US3 in a follow-up PR — Supersedes-M4 table populated; report becomes self-contained for the M4-vs-M5 comparison.
5. Land Phase 6 polish (PLAN.md tick, gitignore, lint/type cleanup) in the same PR as US3 or as a final polish PR.

Each PR is independently testable (US1 produces a complete cross-host channel report; US2 produces a complete schema-candidate report against US1's frozen baseline; US3 produces the supersession table; all three are reviewable in isolation).

**Risk-driven sequencing notes**:
- T008 (m4_sweep refactor) is the highest-leverage change in Phase 2 — it must keep M4 reproductions bit-identical. T010 is the explicit guard for this.
- T022 (Modal app) and T023 (harness-side handshake) are the highest-Modal-coupling tasks in Phase 3 — if Modal's TLS-tunnel or `modal.Dict` API changes between schedule and execution, these are the tasks that take the hit. The smoke test T034 catches any breakage end-to-end.
- T029 / T030 (channel sweep + recommendation builder) consume the most M4 internals; they are the place where a subtle M4 contract violation would show up. The bit-identical guard (T010) protects against the most common failure mode (an inadvertent behavioral change in m4_sweep).
- T048 (m5_supersede) is purely a JSON-join over M4 + M5 reports; it has no cross-host dependencies and could in principle ship before US1's full sweep lands (against a synthetic M5 JSON). It's sequenced after US1+US2 only because there's no M5 JSON to join against until US1 lands.
