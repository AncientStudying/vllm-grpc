# Tasks: M5.2 — REST Transport Path × gRPC Tuning Surface

**Input**: Design documents from `/specs/019-m5-2-transport-tuning/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Test tasks are included — the spec's Functional Requirements (FR-001..FR-024a) require harness mechanics to be unit-tested (Constitution IV) and the plan's Phase H is "Tests". TDD discipline: write/update tests before or alongside implementation; verify they fail prior to implementing the matching production code.

**Organization**: Tasks are grouped by user story (US1, US2, US3) so each story can be implemented and validated independently. Pre-PR procedural tasks (smoke gate, payload-parity audit, K1/K2/K3 narrative commits, `gh pr create`) live in the final Polish phase because they cross user-story boundaries.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Required for user-story phase tasks (US1, US2, US3); absent on Setup, Foundational, and Polish
- Every task includes an exact file path

## Path Conventions

- Harness package: `tools/benchmark/src/vllm_grpc_bench/`
- Harness unit tests: `tools/benchmark/tests/`
- Repo-level integration tests: `tests/integration/`
- Modal-deploy scripts: `scripts/python/`
- Spec docs: `specs/019-m5-2-transport-tuning/`
- Reports + sidecar: `docs/benchmarks/`
- Narrative surfaces: `README.md`, `ANALYSIS.md` (new at repo root), `docs/PLAN.md`, `docs/benchmarks/summary.md`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the existing harness package layout is ready for M5.2's additive modules; no new top-level project is created (M5.2 extends M5.1).

- [ ] T001 Confirm M5.1 baselines exist and are loadable by reading `docs/benchmarks/m5_1-rest-vs-grpc.json` and verifying its top-level keys (`m5_1_matrix`, `supersedes_m1_time`, per-cell verdicts) are accessible — the Supersedes-M5.1 table builder reads this file directly. Emit an actionable error if the M5.1 file is missing or malformed; do NOT proceed to T002+.
- [ ] T002 [P] Add a `--m5_2`-aware section header to `tools/benchmark/src/vllm_grpc_bench/__main__.py`'s `--help` output stub (no flag parsing yet — placeholder comment block introducing the M5.2 family so reviewers can locate the new code; flags themselves land in T047).
- [ ] T003 [P] Create empty module files (each with a one-line docstring stub) at `tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py`, `tools/benchmark/src/vllm_grpc_bench/m5_2_supersede.py`, `tools/benchmark/src/vllm_grpc_bench/m5_2_events.py`, and `tools/benchmark/src/vllm_grpc_bench/m5_2_symmetry.py` so subsequent tasks have a target file to extend rather than creating from scratch.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Additive dataclasses in `m3_types.py`, the events JSONL writer + reader, the 3-tier symmetry block builder + asserter, the modal-endpoint extension exposing the third `modal.forward` tunnel, and the one-line additive change in the Modal-deploy script. These underpin every user-story phase; no story phase can begin until they exist.

**⚠️ CRITICAL**: No user story work may begin until this phase completes.

- [ ] T004 Extend `tools/benchmark/src/vllm_grpc_bench/m3_types.py` to add the `ProtocolComparisonVerdict`, `TransportOnlyVerdict`, `M5_2CohortKind`, `NetworkPath`, and `SupersedesM5_1Category` Literal type aliases per `specs/019-m5-2-transport-tuning/data-model.md` §"Verdict literals". M5.1's existing `ComparisonVerdict` literal stays in place unchanged.
- [ ] T005 [P] Extend `tools/benchmark/src/vllm_grpc_bench/m3_types.py` to add the `RestHttpsEdgeCohortRecord` frozen dataclass per `specs/019-m5-2-transport-tuning/data-model.md` §"New: RestHttpsEdgeCohortRecord" (shim overhead + connection pool fields mirrored from M5.1's `RESTCohortRecord`; M5.2-specific HTTPS-edge provenance: `network_path`, `https_edge_endpoint`, `tls_handshake_ms_first_request`, RTT median/p95, client geolocation).
- [ ] T006 [P] Extend `tools/benchmark/src/vllm_grpc_bench/m3_types.py` to add the `SupersedesM5_1Entry` frozen dataclass per `specs/019-m5-2-transport-tuning/data-model.md` §"New: SupersedesM5_1Entry" (per-(cell × gRPC cohort) row with M5.1 verdict, M5.2 verdict, CI bounds, category, rationale).
- [ ] T007 [P] Extend `tools/benchmark/src/vllm_grpc_bench/m3_types.py` to add the `ProtocolComparisonRow` and `TransportOnlyRow` frozen dataclasses per `specs/019-m5-2-transport-tuning/data-model.md` §"Extended: M5_2Run cohort root".
- [ ] T008 [P] Extend `tools/benchmark/src/vllm_grpc_bench/m3_types.py` to add the `M5_2Run` top-level frozen dataclass per `specs/019-m5-2-transport-tuning/data-model.md` §"Extended: M5_2Run cohort root" (run identity, symmetry, events sidecar provenance, payload-parity audit, smoke-run outcome, cohort records, verdicts, supersedes-M5.1, modal metadata, RTT-delta).
- [ ] T009 Add unit tests in `tools/benchmark/tests/test_m5_2_types.py` covering: (a) `ProtocolComparisonVerdict` Literal contains the seven required strings (including `rest_https_edge_recommend` and the c=1-only `tuned_grpc_recommend`); (b) `TransportOnlyVerdict` Literal contains the four required strings; (c) `M5_2CohortKind` Literal contains all six cohort names; (d) `SupersedesM5_1Category` Literal contains the five required strings including `confirmed_unavailable`; (e) `M5_2Run` accepts an empty cohort list (degenerate-run sanity); (f) M5.1's existing `RESTCohortRecord` remains importable (backward-compat regression).
- [ ] T010 [P] Implement `PerRequestEventRecord` dataclass + serialization helper in `tools/benchmark/src/vllm_grpc_bench/m5_2_events.py` per `specs/019-m5-2-transport-tuning/data-model.md` §"New: PerRequestEventRecord" and `contracts/m5_2-events-jsonl-sidecar.md` §"Line format" + §"Serialization rules". Use `json.dumps(record.__dict__, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
- [ ] T011 Implement `EventsSidecarWriter` context manager in `tools/benchmark/src/vllm_grpc_bench/m5_2_events.py` per `contracts/m5_2-events-jsonl-sidecar.md` §"Gzip protocol" and research.md R-4: buffered append to `bench-results/m5_2-full/{run_id}.events.jsonl` (un-gzipped), flush every N=1000 records, `__exit__` closes/gzips/removes-intermediate/computes-SHA-256, exposes `.result` property returning `(gzipped_path, sha256_hex)`. The gzip header MUST set `mtime=0` for byte-stable output.
- [ ] T012 [P] Implement `read_sidecar_iter(path)` generator in `tools/benchmark/src/vllm_grpc_bench/m5_2_events.py` per `contracts/m5_2-events-jsonl-sidecar.md` §"Reader contract": opens via `gzip.open(path, "rt", encoding="utf-8")`, yields `PerRequestEventRecord` instances, warns + skips on JSON-decode error or missing required field (forward-compat with future-milestone extensions). Also implement `apply_filter(records, filter_str)` parsing the `key=value AND ...` and `key IN {...}` filter syntax per `contracts/m5_2-events-jsonl-sidecar.md` §"Section-header filter syntax".
- [ ] T013 Add unit tests in `tools/benchmark/tests/test_m5_2_events_sidecar.py` covering: (a) `EventsSidecarWriter` produces deterministic byte output across two writes of equivalent record sets (re-open + re-gzip yields identical SHA-256); (b) write + read round-trip preserves every field; (c) partial trailing record from a SIGKILL'd write is skipped silently with a stderr warning; (d) SHA-256 matches `hashlib.sha256(open(gz, "rb").read()).hexdigest()`; (e) filter `cohort=rest_https_edge AND phase=measurement AND status=success` selects exactly the matching records on a fixture; (f) `cohort IN {rest_https_edge,default_grpc}` matches both literals; (g) unknown additional field in a JSONL line warns via stderr but does not raise.
- [ ] T014 [P] Implement `CrossCohortInvariants`, `IntraProtocolPairInvariants`, `PerCohortMetadata`, and `SymmetryBlock` dataclasses in `tools/benchmark/src/vllm_grpc_bench/m5_2_symmetry.py` per `specs/019-m5-2-transport-tuning/data-model.md` §"New: SymmetryBlock and its three tier sub-types".
- [ ] T015 Implement `build_symmetry_block(cohort_configs)` in `tools/benchmark/src/vllm_grpc_bench/m5_2_symmetry.py` per research.md R-3 tier (a)/(b)/(c) decomposition. Hash digests use `hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()`. Tier (c) replicates `tier_b_skipped_c1_tuned_grpc_pair: True` on each c=1 cohort entry.
- [ ] T016 Implement `assert_symmetry(block, concurrency_levels)` in `tools/benchmark/src/vllm_grpc_bench/m5_2_symmetry.py` per research.md R-3 + FR-005b: tier (a) fail-fast on any mismatch raising `SymmetryAssertionFailed(tier="a", field=<name>, cohort_a=<hash>, cohort_b=<hash>)`; tier (b) fail-fast with c=1 degeneracy skip for the tuned-gRPC pair; tier (c) audit-only (never raises).
- [ ] T017 Add unit tests in `tools/benchmark/tests/test_m5_2_symmetry.py` covering: (a) `build_symmetry_block` on five matching configs returns equal digests on tier (a) and tier (b); (b) `assert_symmetry` raises on tier (a) prompt_corpus_hash divergence with the diverging field in the exception message; (c) `assert_symmetry` raises on tier (b) `rest_client_config_digest_url_excepted` divergence; (d) at c=1 only, the tuned-gRPC pair assertion is skipped (no raise even with deliberate digest mismatch); (e) at c=4 or c=8, the tuned-gRPC pair assertion fires; (f) `tier_c` records preserve full digests including topology and URL.
- [ ] T018 Extend `scripts/python/modal_bench_rest_grpc_server.py` to add a third `modal.forward(8000, unencrypted=True)` call alongside the existing `modal.forward(8000)` HTTPS-edge call per research.md R-1 *Implementation note*. Write the resulting plain-TCP URL for the FastAPI shim to the same `modal.Dict` the harness reads, under a new key `rest_plain_tcp_url`. The existing HTTPS-edge `rest_url` key and the gRPC `grpc_url` key are unchanged. **This is the only Modal-side change M5.2 makes.**
- [ ] T019 [P] Extend `tools/benchmark/src/vllm_grpc_bench/modal_endpoint.py` to additively expose the `rest_plain_tcp_url` from the handshake `modal.Dict` alongside the existing `rest_url` (HTTPS edge) and `grpc_url`. The provider's M5.1 call-site signature is unchanged (default behavior unchanged); a new keyword `with_rest_plain_tcp=True` returns the additional URL in the result triple. M5.1's `variant="rest_grpc"` path stays correct.
- [ ] T020 Add unit tests in `tools/benchmark/tests/test_modal_endpoint_m5_2.py` covering: (a) `provide_endpoint(variant="rest_grpc", with_rest_plain_tcp=True)` returns all three URLs from a faked `modal.Dict`; (b) the legacy `with_rest_plain_tcp=False` (default) call returns only `(grpc_url, rest_url)` so M5.1 callers remain unaffected; (c) missing `rest_plain_tcp_url` key in the handshake dict raises a clear error within the timeout when `with_rest_plain_tcp=True` is set; (d) the `rest_plain_tcp_url` value follows the `tcp+plaintext://<host>:<port>` scheme prefix convention.
- [ ] T021 Extend `tools/benchmark/src/vllm_grpc_bench/rest_cohort.py` per plan.md Phase A: accept an optional `network_path: Literal["https_edge", "plain_tcp"]` keyword on `run_rest_cohort()` and `probe_rest_rtt()`; thread the tag through to per-request labelling. Default value preserves M5.1's HTTPS-edge behavior. The `RESTCohortRecord` returned for `network_path="plain_tcp"` is M5.1's existing dataclass + a new `network_path` attribute; for `network_path="https_edge"`, the cohort wraps it in a `RestHttpsEdgeCohortRecord` (per T005).
- [ ] T022 Add unit tests in `tools/benchmark/tests/test_rest_cohort_dual_transport.py` covering: (a) `run_rest_cohort(network_path="https_edge", ...)` returns a `RestHttpsEdgeCohortRecord`; (b) `run_rest_cohort(network_path="plain_tcp", ...)` returns a `RESTCohortRecord` with `network_path="plain_tcp"`; (c) M5.1's default call signature (no `network_path` kwarg) still works and returns an HTTPS-edge labelled record (back-compat); (d) the `httpx.AsyncClient` is configured with the URL scheme matching the network_path (`https://...` for `https_edge`, `http://<plain_tcp_host>:<port>` for `plain_tcp`); (e) `probe_rest_rtt(network_path="https_edge", ...)` and `probe_rest_rtt(network_path="plain_tcp", ...)` use the same `/healthz` endpoint but distinct URL schemes.

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel.

---

## Phase 3: User Story 1 — Five-Cohort Transport Sweep with HTTPS-Edge REST and Tuned-vs-Default Resolution (Priority: P1) 🎯 MVP

**Goal**: Produce `docs/benchmarks/m5_2-transport-vs-tuning.{md,json,events.jsonl.gz}` carrying two verdict families (protocol comparison + transport-only) per (path × hidden_size × concurrency) cell with 95% CI-bounded supporting numbers, per-cohort RTT (median + p95) per network path, the Supersedes-M5.1 table with five-way categorisation, and field-provenance footnotes naming the sidecar filter or aggregate-JSON key for every aggregate the markdown renders.

**Independent Test**: Run `uv run python -m vllm_grpc_bench --m5_2-smoke` (passes) then `uv run python -m vllm_grpc_bench --m5_2 --m5_2-modal-region=eu-west-1` end-to-end (or against a mocked Modal endpoint in CI). Run the regenerator on the produced sidecar + run config. Confirm the JSON validates against the M5.2-additive schema (FR-013), every cell carries verdicts in both families, every cohort carries `measured_rtt_ms_median` + `network_path`, the report's executive section names the HTTPS-edge vs plain-TCP RTT delta + the payload-parity audit confirmation, the per-cell matrix names the network path on every row, the Supersedes-M5.1 table has rows for every M5.1 cell M5.2 covers categorised correctly, and the regenerator re-run produces byte-identical artifacts.

### Tests for User Story 1 (TDD-style — write/update first)

- [ ] T023 [P] [US1] Add `tools/benchmark/tests/test_m5_2_sweep.py` covering the sweep orchestrator: (a) `enumerate_cells` produces exactly 18 `(path, hidden_size, concurrency)` tuples; (b) `dispatch_cell` schedules `rest_https_edge` → `rest_plain_tcp` → `default_grpc` → `tuned_grpc_multiplexed` (c≥2) → `tuned_grpc_channels` (c≥2) OR `tuned_grpc` (c=1) **in series** per research.md R-1; (c) at c=1 only one tuned-gRPC sub-cohort is run (degenerate; collapsed to `tuned_grpc` per FR-006); at c=4 and c=8 both `tuned_grpc_multiplexed` and `tuned_grpc_channels` are run; (d) two REST cohorts are present at every cell regardless of concurrency; (e) per-request events are emitted to the sidecar at issue and done times via the `EventsSidecarWriter`; (f) cohort failure (e.g., `rest_https_edge` 502 storm) is recorded as cell-level `comparison_unavailable` per FR-005 for verdict families depending on the failed cohort, but other verdict families on the same cell continue to emit normally; (g) the borderline-expand cascade rule continues to apply per FR-011 but does NOT expand beyond n=250.
- [ ] T024 [P] [US1] Add `tools/benchmark/tests/test_m5_2_verdict_families.py` covering `emit_cell_verdicts`: (a) protocol-comparison verdict literal computation against `rest_https_edge` produces `<grpc_cohort>_recommend` when the gRPC cohort's 95% CI clears `rest_https_edge`'s CI; (b) `rest_https_edge_recommend` when REST's CI clears each gRPC cohort's CI; (c) `no_winner` when CIs overlap; (d) `comparison_unavailable` with reason when either cohort is `server_bound`; (e) transport-only verdict literal computation between `rest_https_edge` and `rest_plain_tcp` produces the four expected literals under the same statistical rule; (f) every emitted verdict row's `grpc_cohort_network_path` is `plain_tcp` and `rest_cohort_network_path` is `https_edge` per the FR-009 cohort-network-path-naming rule.
- [ ] T025 [P] [US1] Add `tools/benchmark/tests/test_m5_2_supersede.py` covering `build_supersedes_m5_1`: (a) row category is `verdict_confirmed` when M5.1's literal matches M5.2's literal and both are CI-supported; (b) `verdict_changed` when literals differ and neither is `no_winner`; (c) `noise_resolved` when M5.1 was `no_winner` and M5.2 has a CI-supported `_recommend`; (d) `transport_dependent` when M5.2's protocol-comparison verdict differs from what the same comparison would have been against `rest_plain_tcp` (i.e., the HTTPS-edge moved the comparison); (e) `confirmed_unavailable` when both M5.1 and M5.2 are `comparison_unavailable` on the same cell; (f) every row's `m5_2_delta_median_ms` + `ci_lower_ms` + `ci_upper_ms` come from the M5.2 aggregate's protocol-comparison family (not transport-only).
- [ ] T026 [P] [US1] Add `tools/benchmark/tests/test_m5_2_regenerator.py` covering the round-trippable regenerator: (a) `regen_m5_2(sidecar, run_config, expected_sha256)` raises `SidecarChecksumMismatch` on hash mismatch and refuses to write; (b) re-asserting `assert_symmetry` at report-build time raises `SymmetryAssertionFailed` if the persisted symmetry block has been edited to a divergent state; (c) the produced markdown contains a `> Computed from events sidecar filter:` blockquote at every comparison-matrix table header and at every executive-section aggregate per FR-012b; (d) **byte-identical round trip**: running the regenerator twice on the same sidecar + config produces byte-equal markdown and JSON (`open(p, "rb").read() == open(p_rerun, "rb").read()`); (e) the JSON output has `sort_keys=True, separators=(",", ":")` ordering; (f) warmup-phase records are excluded from aggregates per FR-011; (g) the M5.1 published JSON load failure (file missing or schema-incompatible) raises with exit code 9.
- [ ] T027 [P] [US1] Add `tools/benchmark/tests/test_m5_2_reporter.py` covering report rendering: (a) JSON emitted carries every M5.1 key from M5.1's schema unchanged (additive-only assertion); (b) every protocol-comparison-verdict row has `grpc_cohort_network_path: "plain_tcp"` and `rest_cohort_network_path: "https_edge"`; (c) every transport-only-verdict row references both REST cohorts; (d) markdown executive section names the HTTPS-edge vs plain-TCP RTT delta, the payload-parity audit confirmation line, and the events sidecar SHA-256; (e) no token-shaped string appears in the emitted JSON or markdown (regex `Bearer ` and 32-char URL-safe pattern); (f) Supersedes-M5.1 table rows render with the five category literals correctly; (g) markdown row count for the per-cell matrix is `2 REST + 2 grpc_subcohorts at c>=2` × 12 cells + `2 REST + 1 tuned_grpc + 1 default_grpc at c=1` × 6 cells = correct total per FR-009; (h) negative-results appendix lists every `no_winner`/`comparison_unavailable` cell with full per-cohort CI bounds per FR-014 (e).
- [ ] T028 [P] [US1] Add `tools/benchmark/tests/test_m5_2_cli.py` covering CLI flag wiring per `contracts/m5_2-bench-cli.md`: (a) `--m5_2` triggers the M5.2 code path; (b) `--m5_2` + `--m5_1` exits 2 (flag conflict); (c) `--m5_2-smoke` triggers the smoke-coverage codepath; (d) `--m5_2-modal-region=us-west-2` overrides default region; (e) `--m5_2-skip-deploy` requires `--m5_2-modal-endpoint`; (f) missing `MODAL_BENCH_TOKEN` exits 4; (g) `--m5_2-n` defaults to 250 and accepts override; (h) exit codes 0/2/3/4/5/6/7/8/9 map per the contract; (i) `--m5_2-skip-geolocation-lookup` results in `client_external_geolocation: null` in the recorded tier_c metadata.
- [ ] T029 [P] [US1] Add `tests/integration/test_m5_2_modal_smoke.py` (Modal-secrets-gated; default-skipped) exercising the M5.2 smoke gate end-to-end per `quickstart.md` Step 2: deploy → both REST probes + gRPC probe → 4-cell smoke (`chat_stream c=1`, `chat_stream c=4`, `embed c=4`, `embed c=1`) → all M5.2-specific assertions pass (both REST transports reach same Modal deploy, M5.2 JSON schema round-trips, per-cohort RTT probe within thresholds for all five cohorts) → events sidecar emitted + gzipped + SHA-256 computed → regenerator round-trip diff against the smoke's published artifacts is empty → teardown. Verifies the three tunnel URLs are emitted (gRPC plain-TCP + REST HTTPS-edge + REST plain-TCP).

### Implementation for User Story 1

- [ ] T030 [US1] Implement `frozen_tuned_channel_config(path, hidden_size)` re-use in `tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py` per FR-007 (M5.2 does NOT re-tune; it reuses M5.1's frozen-tuned-channel composition). Import the existing helper from `m5_1_sweep.py` rather than duplicating.
- [ ] T031 [US1] Implement `enumerate_cells()` and the 18-cell scheduler in `tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py` producing the (path × hidden_size × concurrency) cross-product (2 × 3 × 3 = 18) — same matrix as M5.1 per FR-010.
- [ ] T032 [US1] Implement `dispatch_cell()` in `tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py` per research.md R-1 + plan.md Phase C: serial dispatch of `rest_https_edge` → `rest_plain_tcp` → `default_grpc` → `tuned_grpc_multiplexed` (c≥2) → `tuned_grpc_channels` (c≥2) OR `tuned_grpc` (c=1). Each cohort's per-request events are written via the injected `EventsSidecarWriter` instance; warmup records carry `phase="warmup"`. Reuses M5.1's `m5_1_grpc_cohort.run_grpc_cohort` for the three gRPC cohorts and the new dual-transport `rest_cohort.run_rest_cohort(network_path=...)` for the two REST cohorts. Apply the borderline-expand cascade per cohort but DO NOT expand beyond n=250 per FR-011.
- [ ] T033 [US1] Implement `emit_cell_verdicts()` in `tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py` per FR-009: emits two verdict-family rows per cell. Protocol-comparison family: each gRPC cohort vs `rest_https_edge` produces a `ProtocolComparisonRow` with the verdict literal, signed delta median, 95% CI bounds, and the network-path naming pair (`plain_tcp` / `https_edge`). Transport-only family: `rest_https_edge` vs `rest_plain_tcp` produces a `TransportOnlyRow` with the verdict literal, signed delta median, 95% CI bounds. Sets `comparison_unavailable` when either cohort in a row is `server_bound` per FR-005. Attaches `low_rtt_caveat` per FR-004 when measured median RTT falls below the exercise threshold.
- [ ] T034 [US1] Implement `run_m5_2_sweep()` orchestrator entry point in `tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py` per `contracts/m5_2-bench-cli.md` §"Behavior — `--m5_2`" steps 5–11: builds the 3-tier symmetry block via `m5_2_symmetry.build_symmetry_block`, asserts it (exit 5 on failure), invokes `provide_endpoint(variant="rest_grpc", with_rest_plain_tcp=True)`, performs the `https://ipinfo.io/json` geolocation lookup (skippable), runs warmup cohorts (records persisted, aggregates excluded), iterates `enumerate_cells()` calling `dispatch_cell()` + `emit_cell_verdicts()`, closes the `EventsSidecarWriter` to get the gzipped sidecar path + SHA-256, writes the `{run_id}.run_config.json`, tears down the Modal app. **MUST NOT emit the markdown or aggregate JSON directly** per FR-012b.
- [ ] T035 [US1] Implement `build_supersedes_m5_1(m5_1_cells, m5_2_cells)` in `tools/benchmark/src/vllm_grpc_bench/m5_2_supersede.py` per FR-016 + research.md R-6: load M5.1's published JSON at `docs/benchmarks/m5_1-rest-vs-grpc.json`, iterate every M5.1 cell M5.2 covers, emit one `SupersedesM5_1Entry` per (cell × gRPC cohort) pairing, set category via the five-way decision tree (`verdict_changed` / `verdict_confirmed` / `noise_resolved` / `transport_dependent` / `confirmed_unavailable`), and populate the one-line rationale. Builds at **report-build time** (called by the regenerator), not at sweep time.
- [ ] T036 [P] [US1] Implement `regen_m5_2(sidecar_path, run_config_path, expected_sha256)` entry point in `scripts/python/regen_bench_reports.py` per `contracts/m5_2-regenerator.md` §"Algorithm": SHA-256 verification → stream-decode JSONL → compute aggregates → re-assert symmetry block → build verdict-family rows → compute supersedes-M5.1 table → write deterministic markdown + JSON. Uses `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. Adds the `--m5_2-sidecar`, `--m5_2-run-config`, and `--m5_2-report-out` flag family to the script's argparse.
- [ ] T037 [P] [US1] Implement `write_m5_2_markdown(aggregates, run_config)` in `tools/benchmark/src/vllm_grpc_bench/reporter.py` per FR-014 + research.md R-5: deterministic markdown with executive section (headline finding per family, MockEngine read-instruction caveat, HTTPS-edge vs plain-TCP RTT delta, payload-parity audit metadata, smoke-run outcome, client external geolocation, events sidecar SHA-256 + path), per-cell comparison matrix (both verdict families per cell, network path named per row), Supersedes-M5.1 table, negative-results appendix. Every aggregate-rendering section MUST be preceded by a `> Computed from events sidecar filter: ...` or `> Computed from aggregate JSON key: ...` blockquote per FR-012b.
- [ ] T038 [P] [US1] Implement `write_m5_2_json(aggregates, run_config)` in `tools/benchmark/src/vllm_grpc_bench/reporter.py` per `contracts/m5_2-report-schema.md` + FR-013: emits the M5.2 top-level keys (`m5_2_run`, `symmetry`, `events_sidecar_path`, `events_sidecar_sha256`, `protocol_comparison_verdicts`, `transport_only_verdicts`, `supersedes_m5_1`, `payload_parity_audit`, `smoke_run_outcome`, `https_edge_vs_plain_tcp_rtt_delta_*_ms`, `modal_region`, `modal_instance_class`, `https_edge_endpoint`, `client_external_geolocation`). Keeps M5.1's existing keys present with empty arrays (additive-only rule). Validates the produced JSON against the schema contract in `contracts/m5_2-report-schema.md` §"Regenerator validation rule" before writing; raises `M5_2SchemaValidationFailed` on failure.
- [ ] T039 [US1] Wire the M5.2 flag family into `tools/benchmark/src/vllm_grpc_bench/__main__.py` per `contracts/m5_2-bench-cli.md`: `--m5_2`, `--m5_2-smoke`, `--m5_2-modal-region` (default `eu-west-1`), `--m5_2-modal-token-env` (default `MODAL_BENCH_TOKEN`), `--m5_2-modal-endpoint`, `--m5_2-skip-deploy`, `--m5_2-n` (default 250), `--m5_2-warmup-n` (default 20), `--m5_2-rtt-validity-threshold-ms` (default 1.0), `--m5_2-rtt-exercise-threshold-ms` (default 20.0), `--m5_2-shim-overhead-warn-pct` (default 5.0), `--m5_2-events-sidecar-out`, `--m5_2-report-out`, `--m5_2-skip-geolocation-lookup`. Conflict-check `--m5_2` against `--m3` / `--m4` / `--m5` / `--m5_1` with exit code 2.
- [ ] T040 [US1] Wire the M5.2 mode dispatcher in `tools/benchmark/src/vllm_grpc_bench/__main__.py`: when `--m5_2` is set (without `--m5_2-smoke`), calls `m5_2_sweep.run_m5_2_sweep()` and emits the sidecar + run config (does NOT call any reporter — the regenerator does that out-of-process). When `--m5_2-smoke` is set, dispatches to the same `run_m5_2_sweep()` codepath with smoke-coverage configuration per research.md R-7 (4 cells, n=5 measurement + n=2 warmup, M5.2-specific assertion surface invoked first). Honors all exit codes from `contracts/m5_2-bench-cli.md` §"Exit codes".
- [ ] T041 [US1] Implement the M5.2 smoke-specific assertion surface in `tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py` per research.md R-7: `assert_both_rest_transports_reach_same_modal_deploy(rest_https_edge_url, rest_plain_tcp_url)` (compares `/healthz` body + `modal_deploy_handle` header); `assert_m5_2_json_schema_round_trips(temp_path)` (writes a sample additive-fields JSON, reads it back, asserts equivalence); `assert_per_cohort_rtt_probe_within_thresholds_all_five_cohorts(cohort_probes, threshold_ms)`. Each assertion raises `M5_2SmokeAssertionFailure(name, diverging_field, observed, expected)`. The smoke dispatcher invokes these BEFORE cohort dispatch.
- [ ] T042 [US1] Print the structured smoke-pass line on smoke success in `tools/benchmark/src/vllm_grpc_bench/__main__.py`'s smoke handler per `contracts/m5_2-bench-cli.md` Step 9: `M5_2 smoke gate: PASS — <iso_timestamp>, asserted_clauses_count: <N>, per-cohort RTT medians (ms): rest_https_edge=<...>, rest_plain_tcp=<...>, default_grpc=<...>, tuned_grpc_*=<...>`. This line is the operator's PR-description-citable artifact per SC-012.

**Checkpoint**: User Story 1 fully functional — a maintainer can run the M5.2 smoke gate (PASS) and then the M5.2 full sweep end-to-end against Modal, produce the sidecar + run config, and re-generate the markdown + aggregate JSON via the regenerator with byte-identical round-trip.

---

## Phase 4: User Story 2 — Consolidate Running Data Analysis into a Top-Level `ANALYSIS.md` (Priority: P2)

**Goal**: A maintainer or downstream contributor who wants the cumulative findings across milestones has exactly one canonical destination — `ANALYSIS.md` at the repo root. `docs/benchmarks/summary.md` is folded into it (M3-era tables preserved byte-for-byte) and replaced with a one-line redirect; `docs/PLAN.md`'s embedded findings are replaced with `ANALYSIS.md` pointers; every `docs/benchmarks/m*.md` cross-reference is updated.

**Independent Test**: A reviewer checks out the M5.2 PR head and opens `ANALYSIS.md`. Confirms (a) file is at the repo root, (b) every milestone M1–M5.2 covered with name + delivered-or-(upcoming) status + report path(s) + headline finding(s), (c) `docs/benchmarks/summary.md` is a one-line redirect + preserved methodology preamble, (d) `docs/PLAN.md`'s milestone roadmap sections retain goals/exit criteria but have findings replaced with `ANALYSIS.md` pointers, (e) every `docs/benchmarks/m*.md` cross-reference that previously pointed at `summary.md` now points at `ANALYSIS.md`.

### Implementation for User Story 2

> **Procedural / editorial tasks** — these are maintainer-driven editorial updates that go into the K2 commit (per `quickstart.md` Step 8). The harness does not perform them; the operator does. Most are marked [P] because they touch different files.

- [ ] T043 [P] [US2] Create `ANALYSIS.md` at the repo root with the milestone-section schema from `specs/019-m5-2-transport-tuning/data-model.md` §"ANALYSIS.md milestone section schema". Sections in chronological order: M1, M2, M3, M4, M5, M5.1, M5.2. Each section: title; **Status** (delivered date or `(upcoming)`); **Report** path (or `(none — process milestone)` for M2); one-paragraph executive prose; bulleted headline finding(s) with CI-bounded numbers where applicable; **Cross-milestone notes** (e.g., "M5.2 resolves M5.1's open question on tuned-vs-default benefit on this path"). Per FR-017.
- [ ] T044 [P] [US2] Fold `docs/benchmarks/summary.md`'s M3-era §4 channel-tuning tables into `ANALYSIS.md § M3` **byte-for-byte equivalent** per FR-018. A reader who previously cited a `summary.md` table can find the same numbers in `ANALYSIS.md`. Then replace `docs/benchmarks/summary.md` with a one-line redirect to `ANALYSIS.md` plus the preserved "All benchmarks ran on …" methodology preamble (so external links resolve cleanly per Edge Cases).
- [ ] T045 [P] [US2] Edit `docs/PLAN.md` to replace every milestone's embedded findings paragraph with a single `Findings: see [\`ANALYSIS.md\`](../ANALYSIS.md) § M<N>.` pointer per FR-019. Preserve milestone goals, phase descriptions, exit criteria, and risk register intact. Each milestone's `### Status (delivered ...)` paragraph header is preserved; only the findings prose is replaced.
- [ ] T046 [US2] Audit every `docs/benchmarks/m*.md` per-milestone report for cross-references to `summary.md` (`grep -l "summary.md" docs/benchmarks/m*.md`) and update each match to `[ANALYSIS.md § M<N>](../../ANALYSIS.md#m<n>--<title-slug>)` per FR-020 and per `quickstart.md` Step 8d's `summary.md#<anchor>` → `ANALYSIS.md#m<n>--<slug>` rewrite recipe. Cross-references between sibling `m*.md` files remain in place.

**Checkpoint**: User Story 2 complete — `ANALYSIS.md` exists at the repo root as the canonical cross-phase findings destination; `summary.md` is a redirect; `PLAN.md` retains plan content with findings extracted; `docs/benchmarks/m*.md` cross-references re-pointed.

---

## Phase 5: User Story 3 — Simplify `README.md` to Goals + High-Level Phases and Validate Tooling References (Priority: P3)

**Goal**: A new contributor lands on `README.md` and answers "what is this project's goal, what are the three access paths, and where do I go to learn more?" in under three minutes. The README is ≤180 lines (down from ~285). Every Make target, demo script, env var, and external dependency reference resolves correctly. Drift discovered during validation is fixed in the same PR.

**Independent Test**: A reviewer checks out the M5.2 PR head and opens `README.md`. Confirms (a) document fits a single screen-reading session — verify with `wc -l README.md` ≤ 180; (b) Roadmap section is one-line-per-milestone + ANALYSIS.md pointers (≤25 lines); (c) every Make target referenced exists in `Makefile`; (d) every `demo/<script>` path exists and runs end-to-end against a locally-running proxy+frontend pair; (e) every env var referenced is genuinely consumed somewhere in `packages/` / `tools/` / `scripts/`; (f) every external dependency reference (`uv`, `make`, Modal, `xcode-select`) is current as of the M5.2 PR date.

### Implementation for User Story 3

> **Procedural / editorial tasks** — these go into the K3 commit (per `quickstart.md` Step 9). MUST be the last commit on the branch at `gh pr create` time per FR-024.

- [ ] T047 [US3] Simplify `README.md`'s "Benchmark Headlines" section to a single paragraph (≤80 words) with **structural numbers only** (bytes-axis from M1 — encoding-driven, transport-immune) per FR-023 + research.md R-11. Time-axis numbers and per-transport claims are moved to `ANALYSIS.md`.
- [ ] T048 [US3] Simplify `README.md`'s Roadmap section to ≤25 lines: one line per milestone (M1, M2, M3, M4, M5, M5.1, M5.2) naming the deliverable in a single sentence + linking to `ANALYSIS.md § M<N>` per FR-021 + research.md R-11.
- [ ] T049 [US3] Trim the rest of `README.md` per the section-by-section walkthrough in research.md R-11 (Three Access Paths, Prerequisites, Quick Start, Development Commands, Environment Variables, Repository Structure, CI). Target total: ≤180 lines. Verify with `wc -l README.md` in the commit message.
- [ ] T050 [P] [US3] Run the FR-022 Make-target validation pass: `grep -oE 'make [a-z-]+' README.md | sort -u`, then for each target, confirm it exists in `Makefile`. Any reference to a non-existent target is fixed (in the README if the README is wrong, or by adding the missing target if the Makefile is wrong — judgment call recorded in the PR description).
- [ ] T051 [P] [US3] Run the FR-022 demo-script validation pass: `grep -oE 'demo/[a-z0-9.-]+\.(sh|py)' README.md | sort -u`, then for each script path, confirm the file exists AND **run it end-to-end** against a locally-running proxy + frontend pair (per US3 Acceptance Scenario 2). Any reference that does not exist or that fails to run is fixed in the same PR (in the README, the demo script, or the consuming code).
- [ ] T052 [P] [US3] Run the FR-022 env-var validation pass: for each env var referenced in the README (`PROXY_PORT`, `FRONTEND_PORT`, `FRONTEND_ADDR`, `MODEL_NAME`, `PROXY_BASE_URL`, and any others), run `grep -rn "$VAR" packages/ tools/ scripts/`. Confirm genuine consumption. Any env var not consumed is removed from the README per FR-022.
- [ ] T053 [P] [US3] Run the FR-022 external-dependency reference validation: `uv` install command current vs upstream-recommended form; `make` requirement; `xcode-select --install` step; Modal `modal token new` install + auth flow; any other external prerequisite mentioned. Update the README to match current upstream-recommended commands.
- [ ] T054 [US3] Verify `wc -l README.md` outputs ≤180. The K3 commit message MUST include the before/after line count per `quickstart.md` Step 9c.

**Checkpoint**: User Story 3 complete — README is ≤180 lines with current tooling references; every drift fix is named in the PR description.

---

## Phase 6: Polish & Cross-Cutting (Procedural — Operator-Driven Pre-PR Steps)

**Purpose**: Pre-PR procedural steps that cross user-story boundaries: smoke gate (gates the full sweep), payload-parity audit (FR-005c), the three discrete narrative commits (K1/K2/K3 in order), and PR opening with explicit commit-SHA citations. These steps are NOT enforced by tooling; the operator follows `quickstart.md`'s checklist.

- [ ] T055 Run the M5.2 pre-flight smoke gate per `quickstart.md` Step 2: `uv run python -m vllm_grpc_bench --m5_2 --m5_2-smoke`. On PASS, copy the structured `M5_2 smoke gate: PASS — ...` line; the PR description cites this verbatim per SC-012. On FAIL, fix the cause before proceeding (do NOT advance to T056).
- [ ] T056 Run the full M5.2 sweep per `quickstart.md` Step 3: `uv run python -m vllm_grpc_bench --m5_2 --m5_2-modal-region=eu-west-1`. Expected wall-clock 25–30 min per SC-007. Verify the events sidecar gzipped path + SHA-256 + run config are emitted under `bench-results/m5_2-full/{run_id}.*`.
- [ ] T057 Perform the FR-005c payload-parity code-review audit per `specs/019-m5-2-transport-tuning/contracts/m5_2-payload-parity-audit.md` and `quickstart.md` Step 4: read `rest_cohort.py` + `m5_1_grpc_cohort.py` side-by-side; verify chat-path + embed-path payload parity (the regression-relevant check is that `embed_rest_https_edge` == `embed_rest_plain_tcp` == `embed_grpc` byte-for-byte); explicitly cite the past regression by name; record findings under the `payload_parity_audit` key in `bench-results/m5_2-full/{run_id}.run_config.json` with `no_regression_confirmed_against_pr: "<SHA>"`, `auditor`, `audit_date_iso`, and `measured_payload_bytes` per the audit contract. Re-audit triggered by any subsequent commit that touches the payload-construction paths.
- [ ] T058 Run the regenerator per `quickstart.md` Step 5: `uv run python scripts/python/regen_bench_reports.py --m5_2-sidecar bench-results/m5_2-full/{run_id}.events.jsonl.gz --m5_2-run-config bench-results/m5_2-full/{run_id}.run_config.json`. Then verify byte-identical round-trip per `contracts/m5_2-regenerator.md` §"Round-trip contract": re-run with `--m5_2-report-out /tmp/m5_2-roundtrip` and `diff` against the committed artifacts (both diffs MUST be empty).
- [ ] T059 **Commit K1** (per `quickstart.md` Step 7 + FR-024a): `git add docs/benchmarks/m5_2-transport-vs-tuning.md docs/benchmarks/m5_2-transport-vs-tuning.json docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz && git commit -m "[Spec Kit] Summarize M5.2 milestone findings ..."`. Capture the K1 commit SHA for the PR description. This is the **milestone-scoped narrative commit** — numbers come from the regenerator's output; nothing is recomputed inline.
- [ ] T060 **Commit K2** (per `quickstart.md` Step 8 + FR-024a): perform all US2 task-driven edits (T043 + T044 + T045 + T046) and commit as a single commit: `git add ANALYSIS.md docs/benchmarks/summary.md docs/PLAN.md docs/benchmarks/m*.md && git commit -m "[Spec Kit] Compose ANALYSIS.md § M5.2 narrative ..."`. Capture the K2 commit SHA for the PR description. K2 MUST cite K1's commit SHA in its commit message. This is the **cross-phase narrative commit**.
- [ ] T061 **Commit K3 — MUST BE THE LAST COMMIT ON THE BRANCH** (per `quickstart.md` Step 9 + FR-024): perform all US3 task-driven edits (T047 + T048 + T049 + T050 + T051 + T052 + T053 + T054) plus any drift fixes the validation pass surfaced and commit as a single commit: `git add README.md [any-drift-fix-files] && git commit -m "[Spec Kit] Refresh README narrative for M5.2 delivery ..."`. Capture the K3 commit SHA for the PR description. The commit message MUST include the before/after line count (e.g., "README: 285 → <N> lines"). The commit message MUST name each drift fix the FR-022 validation pass made.
- [ ] T062 Verify K3 is HEAD per `quickstart.md` Step 9d: `git log -1 --oneline` MUST show K3's SHA + commit message. If any later commit (e.g., from an auto-commit hook) landed after K3, soft-reset and re-commit so K3 ends up last.
- [ ] T063 Open the M5.2 PR per `quickstart.md` Step 10: `gh pr create --base main --head 019-m5-2-transport-tuning --title "M5.2 — REST transport path x gRPC tuning surface" --body "..."`. The PR body MUST cite **all three commit SHAs explicitly** (K1, K2, K3) per FR-024a + SC-015; MUST cite the smoke-gate PASS line verbatim per SC-012; MUST cite the payload-parity audit's `no_regression_confirmed_against_pr` line per SC-013; MUST list each FR-022 drift fix from T050–T053.

**Checkpoint**: M5.2 PR open with three discrete narrative commits in the operator-visible log, the smoke-gate PASS metadata cited, the payload-parity audit citation present, the round-trippable sidecar+regenerator artifacts committed, ANALYSIS.md established as the running document, and README simplified + tooling-validated.

---

## Phase 7: Unplanned Methodology Fixes (post-implementation 2026-05-12)

**Purpose**: Records the work added retroactively after Phase 3 to address gaps that the original T001–T042 task list did not anticipate. Every task here landed before the K-series narrative commits and is now part of the M5.2 PR scope. These tasks are recorded retroactively per `plan.md` § Phase L, `research.md` R-12/R-13, and `spec.md` § "Session 2026-05-12 — post-implementation revisions". They are marked `[X]` because the work is complete; they exist in `tasks.md` so a future reviewer reading the spec-kit artifacts top-to-bottom understands the full scope shipped.

### L-1: Payload-parity audit fixes (chat-path) — covered by FR-005c Step 1

- [X] T064 [P] Add `warmup_samples` to `RESTCohortResult` + `GRPCCohortResult`; persist warmup records to the sidecar with `phase="warmup"` and `rtt_at_issue_ms=0.0` per FR-012a (g). Files: `rest_cohort.py`, `m5_1_grpc_cohort.py`, `m5_2_sweep.py::write_cell_events_to_sidecar`. Recorded in [`contracts/m5_2-events-jsonl-sidecar.md` § "Field semantics" — `phase`](contracts/m5_2-events-jsonl-sidecar.md#field-semantics) (Fix B lineage).
- [X] T065 Fix REST chat `response_body_bytes` to sum across all SSE lines (including the trailing `data: [DONE]`) so the column is comparable to gRPC's per-`ChatStreamChunk` byte sum. File: `rest_cohort._single_chat_stream_request`. Recorded in [`contracts/m5_2-events-jsonl-sidecar.md` § "Field semantics" — `response_body_bytes`](contracts/m5_2-events-jsonl-sidecar.md#field-semantics) (Fix A lineage).
- [X] T066 [P] Introduce the `RequestSample`-backed chat corpus path. Add a `bucket` field to `corpus.RequestSample`; add `DEFAULT_CHAT_CORPUS_PATH = "tools/benchmark/corpus/chat_sharegpt_1000.json"`; add a `corpus`/`sample` kwarg surface to `rest_cohort.run_rest_cohort` and `m5_1_grpc_cohort.run_grpc_cohort` so both protocols consume the same `RequestSample` by `iteration % len(corpus)`. Files: `corpus.py`, `rest_cohort.py`, `m5_1_grpc_cohort.py`.
- [X] T067 [P] Add `scripts/python/gen_chat_corpus.py` that downloads `anon8231489123/ShareGPT_Vicuna_unfiltered` (pinned revision SHA `192ab21...7154ca`, source-file SHA-256 `35f0e213ce091ed9b9af2a1f0755e9d39f9ccec34ab281cd4ca60d70f6479ba4`), filters to single-turn `human → gpt` prompts in three buckets (short / medium / long), subsets to 1000 samples with seed=42, and emits `tools/benchmark/corpus/chat_sharegpt_1000.json` plus a sibling `.provenance.json`. Commit both. Recorded in [`research.md` R-12](research.md).
- [X] T068 Strengthen `contracts/m5_2-payload-parity-audit.md` Step 1 to mandate the corpus-driven path and add the "Historical note (2026-05-12, pre-corpus integration)" subsection naming the deprecated synthetic-prompt phase. Forbid "Hello world" / "M5.1 chat probe" via the audit's checklist (test below enforces).
- [X] T069 [P] Add `test_chat_payload_parity.py` (8 tests) — locks `messages`, `max_tokens`, `temperature` symmetry across REST and gRPC chat dispatch paths. Add `test_chat_corpus_parity.py` (8 tests) — locks the `RequestSample`-by-iteration discipline; forbids the legacy synthetic-prompt phrases. Files: `tools/benchmark/tests/`.

### L-2: Preemption-aware URL refresh — covered by [R-13](research.md)

- [X] T070 Add `modal_endpoint.refresh_rest_grpc_urls(app_handle)` that re-reads the Modal `modal.Dict` keys (`rest_https_edge_url`, `rest_plain_tcp_url`, `grpc_url`) with a 90 s polling timeout and returns a fresh `EndpointConfig`. File: `modal_endpoint.py`.
- [X] T071 Add `M5_2SweepConfig.refresh_endpoints_fn: Callable[[], EndpointConfig] | None` and `m5_2_sweep._is_connect_error(exc)` predicate. In `dispatch_cell`, on a connect-style exception (and `refresh_endpoints_fn is not None`), call the closure, update the cell's `EndpointConfig`, and retry the cell once. Multiple consecutive connect failures escalate to `failed_cells` instead of crashing the sweep. Files: `m5_2_sweep.py`.
- [X] T072 In `__main__._run_m5_2`, build a `refresh_endpoints_fn` closure from the active Modal app handle and thread it into `M5_2SweepConfig`. The smoke flow uses the same closure. File: `__main__.py`.
- [X] T073 [P] Add `test_m5_2_preemption_resilience.py` (8 tests) — fakes a connect-style exception on first dispatch, verifies the retry path calls `refresh_endpoints_fn`, updates the endpoint, and the cell completes on retry. Also verifies the escalation path (multiple consecutive failures → `failed_cells` entry, sweep continues). File: `tools/benchmark/tests/`.

### L-3: Per-cell isolation + skeleton run_config + verbose error reporting

- [X] T074 Add per-cell try/except in `dispatch_cell` catching everything except `KeyboardInterrupt` / `SystemExit`, recording `{path, hidden_size, concurrency, exception_type, exception_repr, traceback}` to `M5_2Run.failed_cells: list[dict]`. A clean run has `failed_cells == []`. File: `m5_2_sweep.py`.
- [X] T075 Add `_write_skeleton_run_config()` called BEFORE the first cell dispatches. Writes `bench-results/m5_2-full/{run_id}.run_config.json` with `run_id`, `run_started_at_iso`, `seed`, `symmetry`, `modal_region`, `https_edge_endpoint`, and `failed_cells: []`. The sweep patches `run_realized_runtime_s` + `failed_cells` at the end of the run. File: `m5_2_sweep.py`.
- [X] T076 Print verbose error reporting from the CLI's `_run_m5_2` error handler: emit `type(exc).__name__`, `repr(exc)`, and the full traceback on any uncaught exception so the operator sees the underlying failure mode without re-running with `--verbose`. File: `__main__.py`.
- [X] T077 Document the `failed_cells` key in the regenerator contract ([`contracts/m5_2-regenerator.md` § Inputs](contracts/m5_2-regenerator.md#inputs)) as OPTIONAL — older run configs without it remain valid; the regenerator does NOT raise `RunConfigInvalid` on absence. Document it in the report-schema contract ([`contracts/m5_2-report-schema.md` § "Top-level keys"](contracts/m5_2-report-schema.md#top-level-keys-additive-to-m51)) as an OPTIONAL top-level key.
- [X] T078 Document the new behaviors in [`contracts/m5_2-bench-cli.md`](contracts/m5_2-bench-cli.md) Behavior section: corpus load step, skeleton run_config write, per-cell isolation, preemption recovery log lines, verbose error reporting on uncaught exceptions.
- [X] T079 Update [`quickstart.md`](quickstart.md) Step 1.5 (corpus regen instructions), Step 3 (corpus loading + preemption recovery notes), and the troubleshooting section (failed_cells + pre-first-cell ConnectError).
- [X] T080 Update [`data-model.md`](data-model.md) with `failed_cells` on `M5_2Run`, extended `RequestSample` (with `bucket`), and the `M5_2SweepConfig` additions (`chat_corpus_path`, `refresh_endpoints_fn`). Add the `failed_cells` row to the JSON schema delta table.
- [X] T081 Update [`spec.md`](spec.md) with the "Session 2026-05-12 — post-implementation revisions" subsection (4 Q/A entries). Strengthen FR-005c with Step 1's chat-corpus mandate. Strengthen FR-016 with topology-aware framing requirement + the forbidden-phrases list ("shifted", "surfaces the change", "was wrong", "superseded").
- [X] T082 Update [`research.md`](research.md) with R-12 (ShareGPT corpus methodology) and R-13 (preemption-aware URL refresh). Update the closing summary to "13 R-items".

**Checkpoint**: All retroactive scope captured under Phase 7. The K-series narrative commits land **after** this checkpoint; Phase 6's procedural steps (T055–T063) remain the gating sequence to PR.

---

## Dependencies & Execution Order

### Phase Order

1. **Phase 1: Setup** (T001–T003) — must complete before Phase 2.
2. **Phase 2: Foundational** (T004–T022) — must complete before any user-story phase. All Phase 2 tasks marked [P] can run in parallel; sequential dependencies are within `m3_types.py` edits (T004 before T005–T009) and within `m5_2_symmetry.py` (T014 before T015 before T016 before T017).
3. **Phase 3: User Story 1 (P1)** (T023–T042) — depends on Phase 2 completion. **This is the MVP** — delivers a runnable M5.2 sweep + regenerator + report. Stop here for a viable demo; US2/US3 are documentation refactors.
4. **Phase 4: User Story 2 (P2)** (T043–T046) — depends on Phase 3 completion (US2 task T043's ANALYSIS.md § M5.2 section cites US1's report). Can run in parallel with Phase 5 task drafting *until* T058 (regenerator round-trip diff) completes, because K2 commits the consolidation as a single unit.
5. **Phase 5: User Story 3 (P3)** (T047–T054) — depends on Phase 4 completion (US3's "high-level phase summary" links to ANALYSIS.md § M<N> destinations created by US2). Can be drafted in parallel with Phase 4 edits, but the K3 commit MUST land after K2.
6. **Phase 6: Polish** (T055–T063) — operator-driven procedural steps. T055 (smoke gate) before T056 (full sweep). T056 before T057 (audit). T057 before T058 (regenerator) — the audit's PR-SHA reference goes into the run config the regenerator reads. T058 before T059 (K1 commit). T059 before T060 (K2 cites K1). T060 before T061 (K3 last on branch). T061 before T062 before T063 (PR open).
7. **Phase 7: Unplanned methodology fixes** (T064–T082) — retroactive scope completed 2026-05-12 between Phase 3 and Phase 6. T064–T069 (L-1 chat-payload-parity + ShareGPT corpus) gate the FR-005c audit at T057. T070–T073 (L-2 preemption resilience) gate the full sweep at T056 surviving Modal preemption. T074–T076 (L-3 per-cell isolation + skeleton config + verbose errors) gate every sweep producing recoverable artifacts on partial failure. T077–T082 (docs sync) gate the regenerator and the spec-kit artifacts being consistent with shipped code at the K2 commit at T060.

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Phase 2. Independent — produces the report.
- **User Story 2 (P2)**: Depends on US1's report being committed (T059) before T060 lands ANALYSIS.md § M5.2. ANALYSIS.md sections for M1–M5.1 can be drafted in parallel with US1's runtime work.
- **User Story 3 (P3)**: Depends on US2 (US3's phase summary links into ANALYSIS.md anchors created by US2). The README simplification's *structure* can be drafted in parallel with US2's drafting; the K3 commit lands after K2.

### Within Each User Story

- Tests (T023–T029 for US1) MUST be written and FAIL before implementation per Constitution IV.
- Models / dataclasses (Phase 2) before services / orchestration (US1 implementation).
- Sweep + regenerator before reporter (T034 + T035 + T036 before T037 + T038).
- CLI wiring (T039 + T040) last in US1 implementation so the entry point is hooked up after the codepath is implementable.

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel (T002, T003 — independent files).
- Foundational dataclass additions (T005, T006, T007, T008) can run in parallel after T004; events module (T010, T012) can run in parallel with the symmetry module (T014); modal_endpoint extension (T019) can run in parallel with rest_cohort extension (T021).
- US1 test tasks marked [P] (T023–T029) can all run in parallel.
- US1 implementation marked [P] (T036, T037, T038) can run in parallel — different files.
- US2 editorial tasks (T043, T044, T045) can be drafted in parallel — different files; T046 (cross-reference audit) runs after the others land.
- US3 validation tasks marked [P] (T050, T051, T052, T053) can run in parallel — orthogonal validation passes.

---

## Parallel Example: Phase 2 Foundational

```bash
# Launch the additive dataclasses in parallel (different sections of m3_types.py — coordinate file locks):
Task: "Extend m3_types.py with RestHttpsEdgeCohortRecord (T005)"
Task: "Extend m3_types.py with SupersedesM5_1Entry (T006)"
Task: "Extend m3_types.py with ProtocolComparisonRow + TransportOnlyRow (T007)"
Task: "Extend m3_types.py with M5_2Run root (T008)"

# Launch the events sidecar and symmetry modules in parallel (independent files):
Task: "Implement PerRequestEventRecord + serialization in m5_2_events.py (T010)"
Task: "Implement SymmetryBlock + tier dataclasses in m5_2_symmetry.py (T014)"

# Launch unit tests in parallel:
Task: "test_m5_2_types.py (T009)"
Task: "test_m5_2_events_sidecar.py (T013)"
Task: "test_m5_2_symmetry.py (T017)"
```

## Parallel Example: User Story 1 Tests

```bash
# Launch all US1 unit/integration tests together (TDD — write first, expect to fail):
Task: "test_m5_2_sweep.py (T023)"
Task: "test_m5_2_verdict_families.py (T024)"
Task: "test_m5_2_supersede.py (T025)"
Task: "test_m5_2_regenerator.py (T026)"
Task: "test_m5_2_reporter.py (T027)"
Task: "test_m5_2_cli.py (T028)"
Task: "test_m5_2_modal_smoke.py — Modal-secrets-gated (T029)"
```

## Parallel Example: User Story 3 Tooling Validation

```bash
# Launch the four orthogonal FR-022 validation passes in parallel:
Task: "Make-target validation (T050)"
Task: "Demo-script validation + run end-to-end (T051)"
Task: "Env-var consumption validation (T052)"
Task: "External-dependency reference validation (T053)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories).
3. Complete Phase 3: User Story 1 (T023–T042).
4. Run T055 (smoke gate PASS) + T056 (full sweep) + T057 (payload-parity audit) + T058 (regenerator).
5. **STOP and VALIDATE**: A maintainer can run the M5.2 sweep end-to-end, produce the sidecar, regenerate byte-identical artifacts, and inspect the report's two verdict families per cell, the Supersedes-M5.1 table with five-way categories, and the executive section's HTTPS-edge vs plain-TCP RTT delta. The MVP delivers the **technical answer** to M5.1's two open questions, even before the documentation refactors land.

### Incremental Delivery

1. Phase 1 + 2 + 3 → MVP. Stop or continue.
2. Add User Story 2 (Phase 4) → Test ANALYSIS.md independently → Continue.
3. Add User Story 3 (Phase 5) → Test README independently → Continue.
4. Phase 6 (Polish) wraps the three discrete narrative commits and opens the PR.

### Parallel Team Strategy

With multiple developers:
1. Team completes Setup + Foundational together (Phase 1–2; ~T001–T022).
2. Once Phase 2 is done:
   - Developer A: User Story 1 (Phase 3) — the high-rigor implementation work.
   - Developer B: User Story 2 — drafts ANALYSIS.md sections M1–M5.1 (the M5.2 section is drafted after US1's report lands).
   - Developer C: User Story 3 — drafts the simplified README structure + runs the FR-022 tooling-validation passes.
3. K1 → K2 → K3 commit sequence in Phase 6 is operator-driven (single maintainer) regardless of how many developers contributed to the draft state, to preserve the ordered commit log per FR-024a.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks.
- [Story] label maps task to specific user story for traceability.
- Each user story should be independently completable and testable.
- Verify tests fail before implementing.
- Commit after each task or logical group during implementation; the three operator-visible Phase-6 commits (K1, K2, K3) are the PR-narrative commits and MUST be ordered as specified.
- Stop at any checkpoint to validate the story independently.
- Avoid: vague tasks, same-file conflicts (sequential ordering enforced for `m3_types.py` and `__main__.py`), cross-story dependencies that break independence.
- **Constitution V — Honest Measurement**: every `no_winner` / `comparison_unavailable` cell is fully published in the negative-results appendix with per-cohort CI bounds. No metric is selectively omitted because it is neutral or negative relative to a thesis.
- **The payload-parity audit (T057) is a code-review step, not an automated test**. It catches the regression mode where both protocols compute the wrong payload self-consistently — a failure mode no within-harness assertion can detect.
