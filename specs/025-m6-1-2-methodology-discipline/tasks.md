---
description: "Task list for M6.1.2 — Methodology Discipline: Topology Proof + 3-Cohort Reintroduction + Harness QoL"
---

# Tasks: M6.1.2 — Methodology Discipline

**Input**: Design documents from `/specs/025-m6-1-2-methodology-discipline/`
**Prerequisites**: plan.md, spec.md (32 FRs + 10 SCs + 13 Q/A across 3 clarify rounds), research.md (R-1 through R-8), data-model.md, contracts/{cli,network-paths,artifact-schema}.md, quickstart.md

**Tests**: Test tasks are required, not optional. The default-inheritance regression test in `test_m6_1_2_cli.py` is a spec-level guard against silent drift on `--m6_1_2-modal-region` / `-base-seed` / `-model` (FR-027 + round-3 Q2). The artifact-schema strict-superset test (FR-004 + SC-006) is required to prove the M6.1.1-backward-compatibility property. The probe unit tests (timeout, binary-missing, output-parser) are required because the probe is net-new code with no prior project precedent.

**Organization**: Tasks are grouped by user story per the spec's P1/P2/P3 priority:

- **US1 (P1)**: Per-sweep `tcptraceroute` topology probe (the most novel code surface).
- **US2 (P2)**: Reintroduce the `rest_plain_tcp` cohort (cohort iteration + RPC-driver patch; depends on US1's `m6_1_2_types.py` for cohort enum).
- **US3 (P3)**: Timestamp progress lines on stderr (mostly a verbatim carry-forward of spike commit `3763687`; fully independent of US1/US2).

The cross-cutting glue (CLI wiring, reporter, `--m6_1_2-validate` entry point, validation sweep, ANALYSIS.md update, `contracts/instrumentation.md` update) lands in Phase 6 — Polish & cross-cutting concerns.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1 / US2 / US3); omitted for Setup / Foundational / Polish
- Exact file paths in every description

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm branch state + external dependencies, cherry-pick the spike's timestamped-progress-line commit so US3's code is on-branch before US1/US2 work begins.

- [ ] T001 Verify branch `025-m6-1-2-methodology-discipline` is checked out and clean (`git status` returns clean tree; `git rev-parse --abbrev-ref HEAD` returns `025-m6-1-2-methodology-discipline`)
- [ ] T002 Verify `tcptraceroute` (Michael Toren's binary) is installed and on PATH per FR-002 + round-2 Q3 (`tcptraceroute --version` returns a version string; if absent, install via `brew install tcptraceroute` on macOS or `apt install tcptraceroute` / `dnf install tcptraceroute` on Linux per [`quickstart.md`](./quickstart.md) Phase 0)
- [ ] T003 Verify M6.1.1's published JSON exists at `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` (the `--m6_1_2-m6-1-1-baseline` default per [`contracts/cli.md`](./contracts/cli.md)); confirm it parses (`jq -e '.dispatch_mode' docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` returns `"concurrent"`)
- [ ] T004 Cherry-pick the spike's timestamped-progress-line commit `3763687` from `spike/m6-1-roadmap-additions` to the M6.1.2 branch (`git cherry-pick 3763687`); if cherry-pick conflicts, re-create the 5-file change set manually per [`data-model.md`](./data-model.md) "Modified Files" table

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define the shared dataclasses and literals in `m6_1_2_types.py` — every subsequent task in US1 / US2 / Phase 6 imports from this module, so it must land first.

- [ ] T005 Create `tools/benchmark/src/vllm_grpc_bench/m6_1_2_types.py` with the dataclass + literal definitions per [`data-model.md`](./data-model.md) "Python Dataclasses" section: `M6_1_2CohortKind`, `M6_1_2_COHORTS` (4-element tuple), `M6_1_2CloudProvider` (4-element enum), `M6_1_2NetworkPathHop` (`hop_number`, `ip`, `rtt_ms_or_null`, `cloud_provider`), `M6_1_2NetworkPath` (`endpoint_ip`, `hops`, `cloud_provider`, `region`, `probe_method`, `probed_at_utc`), `M6_1_2NetworkPathError` (`error`, `probe_method`, `probed_at_utc`, `detail`), `M6_1_2CohortOmissions` (type alias `dict[M6_1_2CohortKind, str]`). All dataclasses use `@dataclass(frozen=True)` for immutability. Top of the file imports `M6_1_CELLS` and `M6_1Path` from `m6_1_types` per R-2 (cell matrix reused, not redefined). Module passes `mypy --strict`.

**Checkpoint**: `tools/benchmark/src/vllm_grpc_bench/m6_1_2_types.py` is in place; US1, US2, US3 phases may begin in parallel where their files don't overlap.

---

## Phase 3: User Story 1 — Per-Sweep Topology Probe (Priority: P1) 🎯 MVP

**Goal**: Implement the `tcptraceroute` topology probe in `m6_1_2_network_probe.py` plus the loud-stderr warning emitters (FR-005a, FR-006). The probe runs once per sweep, in parallel across cohorts, with a 30s per-cohort timeout, and writes per-cohort `M6_1_2NetworkPath` or `M6_1_2NetworkPathError` entries that feed the artifact JSON's `network_paths` top-level block (per [`contracts/network-paths.md`](./contracts/network-paths.md)).

**Independent Test** (per [`spec.md`](./spec.md) Story 1 Independent Test + SC-002 + SC-006): Synthesize an M6.1.2 artifact (via the integration test in T015) and confirm: (a) `jq '.network_paths' artifact.json` returns a non-empty object keyed by cohort, (b) each cohort entry contains the FR-003 minimum schema, (c) an M6.1.1-vintage reader parses the artifact silently ignoring the new `network_paths` key (strict-superset confirmed).

### Tests for User Story 1

- [ ] T006 [P] [US1] Create `tools/benchmark/tests/test_m6_1_2_network_probe.py` with unit tests for the CSP-attribution helper: `test_attribute_aws_ip()` feeds canned IPs from `https://ip-ranges.amazonaws.com/ip-ranges.json` (e.g., `54.193.31.244` for AWS us-west-1) and asserts the returned tuple is `("AWS", "us-west-1")`; `test_attribute_azure_ip()` feeds an Azure IP (e.g., `20.125.113.97`) and asserts `("Microsoft Azure", ...)`; `test_attribute_gcp_ip()` feeds a GCP IP and asserts `("GCP", ...)`; `test_attribute_unknown_ip()` feeds a non-CSP IP (e.g., `8.8.4.4` after whois fails) and asserts `("unknown", None)` per round-3 Q1 + FR-007 + the Key Entity enum. Uses pytest fixtures with pre-loaded canned IP-range JSON to avoid live network fetches.
- [ ] T007 [P] [US1] Add to `tools/benchmark/tests/test_m6_1_2_network_probe.py`: `test_parse_tcptraceroute_output_success()` feeds canned `tcptraceroute` stdout (captured from the spike's reference run at [`docs/spikes/m6-1-roadmap-additions/traceroute_probe.output.txt`](../../docs/spikes/m6-1-roadmap-additions/traceroute_probe.output.txt) — adapted from `traceroute` to `tcptraceroute` format) and asserts the parsed `hops[]` list matches the FR-003 schema (`hop_number`, `ip`, `rtt_ms_or_null` per hop); `test_parse_tcptraceroute_output_asterisks()` feeds output with timeout-asterisk hops and asserts `ip == None`, `rtt_ms_or_null == None`; `test_parse_tcptraceroute_output_empty()` feeds empty stdout and asserts an empty `hops[]` list.
- [ ] T008 [P] [US1] Add to `tools/benchmark/tests/test_m6_1_2_network_probe.py`: `test_probe_timeout()` mocks a `subprocess.run` that hangs (use `monkeypatch` to raise `subprocess.TimeoutExpired`), invokes the probe, asserts the returned object is `M6_1_2NetworkPathError(error="probe_timeout", ...)` per FR-002a + round-1 Q1; `test_probe_binary_missing()` mocks `subprocess.run` raising `FileNotFoundError`, asserts the returned object is `M6_1_2NetworkPathError(error="tcptraceroute_unavailable", ...)` per FR-005; `test_probe_subprocess_error()` mocks a non-zero exit, asserts `error="subprocess_error"` with the stderr line in `detail`.
- [ ] T009 [P] [US1] Add to `tools/benchmark/tests/test_m6_1_2_network_probe.py`: `test_probe_runs_parallel_across_cohorts()` uses 4 mock endpoints with varying `subprocess.run` durations (e.g., 1s, 2s, 1s, 1s); asserts total wall-clock < 5s, confirming parallel execution per FR-001a (sequential would be ≥5s).
- [ ] T010 [P] [US1] Create `tools/benchmark/tests/test_m6_1_2_artifact_schema.py` with strict-superset compatibility tests: `test_m6_1_2_artifact_parses_with_m6_1_1_reader()` per [`contracts/network-paths.md`](./contracts/network-paths.md) — synthesize an M6.1.2 artifact with `network_paths` populated, parse with M6.1.1's `m6_1_1_reporter.parse_json` (or equivalent loader), assert no parse error AND the M6.1.1-known top-level keys are intact; `test_network_paths_block_keys()` asserts every cohort entry's keys match the FR-003 minimum schema.

### Implementation for User Story 1

- [ ] T011 [US1] Create `tools/benchmark/src/vllm_grpc_bench/m6_1_2_network_probe.py` skeleton:
  - Module-level constants: `_TCPTRACEROUTE_FLAGS = ("-n", "-w", "2", "-q", "1", "-m", "18")` per R-5; `_PER_COHORT_TIMEOUT_S = 30` per FR-002a; `_PROBE_METHOD = "tcptraceroute"` per FR-002.
  - Module-level helper `_stderr_ts()` (copied verbatim from spike commit `3763687`'s `m6_1_1_sweep.py` implementation per R-7 — uses `from datetime import UTC, datetime`).
  - Function signature stubs: `attribute_cloud_provider(ip: str) -> tuple[M6_1_2CloudProvider, str | None]`, `parse_tcptraceroute_output(stdout: str) -> list[M6_1_2NetworkPathHop]`, `_fetch_csp_ip_ranges(refresh: bool = False) -> dict[str, list[dict]]`, `_whois_lookup(ip: str, timeout: float = 5.0) -> str | None`, `run_topology_probe(handshake_dict: dict, cohorts: tuple[M6_1_2CohortKind, ...], per_cohort_timeout_seconds: float = 30.0) -> dict[M6_1_2CohortKind, M6_1_2NetworkPath | M6_1_2NetworkPathError]`.
- [ ] T012 [US1] Implement `parse_tcptraceroute_output(...)` in `tools/benchmark/src/vllm_grpc_bench/m6_1_2_network_probe.py`: parse line-by-line per `tcptraceroute`'s output format (one hop per line, format: `<hop_num>  <ip> (<reverse_dns>)  <rtt1> ms` OR `<hop_num>  * * *` for asterisk hops). Returns ordered list of `M6_1_2NetworkPathHop`. Make T007's tests pass.
- [ ] T013 [US1] Implement `_fetch_csp_ip_ranges(...)` and `attribute_cloud_provider(...)` per R-6 + [`contracts/network-paths.md`](./contracts/network-paths.md) "CSP attribution algorithm": fetch AWS / Azure / GCP IP-range JSON from public URLs with a 24h cache TTL at `~/.cache/vllm-grpc/ip-ranges/`; linear search per IP against parsed prefix list; fall back to ARIN whois (single attempt, 5s timeout, no retry per round-3 Q1); final fallback `("unknown", None)`. Make T006's tests pass.
- [ ] T014 [US1] Implement `run_topology_probe(...)` in `tools/benchmark/src/vllm_grpc_bench/m6_1_2_network_probe.py`: extract per-cohort endpoint URL from the Modal handshake-dict keys (`rest_https_edge_url`, `rest_plain_tcp_url`, `grpc` — the existing spike-tested keys per [`docs/spikes/m6-1-roadmap-additions/traceroute_probe.py`](../../docs/spikes/m6-1-roadmap-additions/traceroute_probe.py) lines 121-132); parse each URL into `(host, port)` via a local helper mirroring the spike's `_parse_url()` at lines 50-67 (handles `tcp+plaintext://host:port`, `http://host:port`, `https://host[:443]`); invoke `subprocess.run(["tcptraceroute", *_TCPTRACEROUTE_FLAGS, host, str(port)], capture_output=True, text=True, timeout=30, check=False)` per R-5; catch `subprocess.TimeoutExpired` → `M6_1_2NetworkPathError(error="probe_timeout")`, catch `FileNotFoundError` → `M6_1_2NetworkPathError(error="tcptraceroute_unavailable")`, catch non-zero exit with parseable stderr → `M6_1_2NetworkPathError(error="subprocess_error", detail=stderr_line)`. Run cohorts in parallel via `asyncio.gather(*(asyncio.to_thread(_probe_one_cohort, cohort, host, port) for cohort, host, port in ...))` per FR-001a. Make T008 + T009 tests pass.
- [ ] T015 [US1] Add the FR-005a all-probes-failed warning and FR-006 cohort-CSP-mismatch warning emitters to `tools/benchmark/src/vllm_grpc_bench/m6_1_2_network_probe.py`: after `run_topology_probe` returns, if EVERY value is a `M6_1_2NetworkPathError`, emit `print(f"{_stderr_ts()} WARNING: every cohort probe failed ({reason_summary}); `network_paths` block contains error records only — topology evidence is unavailable for this sweep", file=sys.stderr, flush=True)` per FR-005a; for each cohort whose `cloud_provider` differs from the spike-confirmed expectation (`rest_https_edge` → `"Microsoft Azure"`; `*.modal.host` cohorts → `"AWS"`), emit `print(f"{_stderr_ts()} WARNING: cohort {cohort} entered {actual_csp} rather than expected {expected_csp}; topology has changed", file=sys.stderr, flush=True)` per FR-006. Both warnings carry the `_stderr_ts()` prefix per FR-020 + round-2 Q5.
- [ ] T016 [US1] Run the unit tests for US1: `uv run pytest tools/benchmark/tests/test_m6_1_2_network_probe.py tools/benchmark/tests/test_m6_1_2_artifact_schema.py -v` — assert all tests defined in T006-T010 pass. If any fail, fix the implementation; re-run.

**Checkpoint**: `tools/benchmark/src/vllm_grpc_bench/m6_1_2_network_probe.py` is in place and unit-tested. `network_paths` JSON-block schema is testable via `test_m6_1_2_artifact_schema.py`. US1's MVP is complete — the probe can be invoked standalone against a Modal deploy and produces an artifact-ready `network_paths` dict.

---

## Phase 4: User Story 2 — Reintroduce the `rest_plain_tcp` Cohort (Priority: P2)

**Goal**: Add the `rest_plain_tcp` cohort dispatch case in `m6_1_rpc_driver.py` (the only file with a 3-cohort gap per spike #2's code-surface enumeration). Add cohort iteration logic with the M5.2-inherited tuned-pair-collapse-at-c=1 rule (per `m5_2_sweep.py:228-237`). The artifact's top-level `cohort_set` array + optional `cohort_omissions` map become the wire-format vocabulary for the 4-cohort split per [`contracts/artifact-schema.md`](./contracts/artifact-schema.md).

**Independent Test** (per [`spec.md`](./spec.md) Story 2 Independent Test + SC-003 + SC-004): The Phase 7 validation sweep's per-cell rows include all 4 cohorts at `c ≥ 2` (3 at `c = 1` per the tuned-pair collapse rule); a reader can compute `rest_plain_tcp` vs `default_grpc` per chat_stream cell to obtain the protocol-only differential.

### Tests for User Story 2

- [ ] T017 [P] [US2] Add to `tools/benchmark/tests/test_m6_1_2_artifact_schema.py`: `test_cohort_set_omissions_invariant()` per [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) — assert `set(cohort_set) ∪ set(cohort_omissions.keys()) == {"rest_https_edge", "rest_plain_tcp", "default_grpc", "tuned_grpc_multiplexed"}` AND `set(cohort_set) ∩ set(cohort_omissions.keys()) == set()` per FR-016; `test_invariant_violation_raises_before_write()` builds a malformed `(cohort_set, cohort_omissions)` and asserts the reporter's pre-write validation raises `ValueError`; `test_absent_and_empty_cohort_omissions_equivalent()` per round-2 Q2 — assert absent key and empty `{}` are read identically as "no intentional omissions".
- [ ] T018 [P] [US2] Add to `tools/benchmark/tests/test_m6_1_2_artifact_schema.py`: `test_cohort_set_alphabetical_ordering()` — assert `cohort_set` array is sorted alphabetically per [`data-model.md`](./data-model.md) "Cohort iteration semantics" note (reader-script stability).
- [ ] T019 [P] [US2] Add to `tools/benchmark/tests/test_m6_1_2_artifact_schema.py`: `test_cohort_set_at_c1_excludes_tuned_multiplexed()` — synthesize an artifact from a sweep that only ran `c=1` cells; assert `"tuned_grpc_multiplexed"` is NOT in `cohort_set` (collapsed into `default_grpc` per FR-011); assert `cohort_omissions` is absent (structural collapse, not intentional omission, per [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) "What does NOT belong in `cohort_omissions`").

### Implementation for User Story 2

- [ ] T020 [US2] Patch `tools/benchmark/src/vllm_grpc_bench/m6_1_rpc_driver.py` (lines 305-345 area per R-4): add a 4th branch to the cohort dispatch match statement for `"rest_plain_tcp"` mirroring `"rest_https_edge"`'s `httpx.AsyncClient` shape (lines 313 region) but pointing at `rest_plain_tcp_url` from the Modal handshake dict (the URL is already exported per `scripts/python/modal_bench_rest_grpc_server.py:208`). The reused REST shim path (`rest_cohort.py` + `rest_shim.py`) handles the plain-TCP transport — no new client code required. Existing 3-cohort paths are UNCHANGED per FR-017.
- [ ] T021 [P] [US2] Add a helper `cohorts_at_concurrency(c: int) -> tuple[M6_1_2CohortKind, ...]` to `tools/benchmark/src/vllm_grpc_bench/m6_1_2_types.py` per [`data-model.md`](./data-model.md) "Cohort iteration semantics" — returns `("rest_https_edge", "rest_plain_tcp", "default_grpc")` at `c == 1` (tuned-pair collapse per FR-011) and `M6_1_2_COHORTS` (all 4) at `c ≥ 2`. Helper has a docstring citing FR-011 + M5.2's `m5_2_sweep.py:228-237` precedent.
- [ ] T022 [P] [US2] Add a helper `build_cohort_set_and_omissions(actual_cohorts_run: set[M6_1_2CohortKind], intentional_omissions: dict[M6_1_2CohortKind, str] | None) -> tuple[list[M6_1_2CohortKind], M6_1_2CohortOmissions | None]` to `tools/benchmark/src/vllm_grpc_bench/m6_1_2_types.py`: validates the FR-016 invariant (cohort_set ∪ omissions.keys() == canonical 4-cohort universe AND ∩ == ∅); raises `ValueError` on violation per [`contracts/artifact-schema.md`](./contracts/artifact-schema.md); returns `(sorted(actual_cohorts_run), intentional_omissions if intentional_omissions else None)` — absent `None` means "no intentional omissions" per round-2 Q2.
- [ ] T023 [US2] Run the US2 unit tests: `uv run pytest tools/benchmark/tests/test_m6_1_2_artifact_schema.py::test_cohort_set_omissions_invariant tools/benchmark/tests/test_m6_1_2_artifact_schema.py::test_invariant_violation_raises_before_write tools/benchmark/tests/test_m6_1_2_artifact_schema.py::test_absent_and_empty_cohort_omissions_equivalent tools/benchmark/tests/test_m6_1_2_artifact_schema.py::test_cohort_set_alphabetical_ordering tools/benchmark/tests/test_m6_1_2_artifact_schema.py::test_cohort_set_at_c1_excludes_tuned_multiplexed -v` — all 5 tests pass.

**Checkpoint**: `m6_1_rpc_driver.py` dispatches the 4th cohort. `cohorts_at_concurrency` and `build_cohort_set_and_omissions` helpers in `m6_1_2_types.py` give the orchestrator (Phase 6) the iteration logic and pre-write validation it needs.

---

## Phase 5: User Story 3 — Timestamped Progress Lines (Priority: P3)

**Goal**: Verify the spike's `3763687` cherry-pick (T004) is on-branch, then extend the `_stderr_ts()` pattern to the new `m6_1_2_sweep.py` module so M6.1.2-launched progress lines (and the FR-005a / FR-006 warning lines from US1) carry the same `[YYYY-MM-DDTHH:MM:SSZ]` prefix. Per FR-018 + FR-019 + FR-021 + round-2 Q5.

**Independent Test** (per [`spec.md`](./spec.md) Story 3 Independent Test + SC-005): Every stderr line from the M6.1.2 progress reporter (and the new warning emitters) matches the regex `^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\]`.

### Tests for User Story 3

- [ ] T024 [P] [US3] Create `tools/benchmark/tests/test_m6_1_2_progress_format.py` (parallel pattern to `test_m6_quickstart_format.py` per [`data-model.md`](./data-model.md) "Modified Files" table): `test_m6_1_2_progress_lines_have_iso_prefix()` runs `m6_1_2_sweep`'s progress reporter against a stub driver, captures stderr, asserts every line matches `^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\]` per SC-005 + FR-018 + FR-019; `test_m6_1_2_warning_lines_have_iso_prefix()` synthesizes the FR-005a all-fail scenario + FR-006 mismatch scenario, captures stderr, asserts both warning lines also match the regex per FR-020 + round-2 Q5.

### Implementation for User Story 3

- [ ] T025 [US3] Verify the spike cherry-pick (T004) landed cleanly: `git show HEAD~..HEAD --stat | grep -E "(m6_sweep|m6_1_sweep|m6_1_1_sweep|test_m6_quickstart_format)"` shows the 4-5 spike-touched files in the recent history; `grep -n "_stderr_ts" tools/benchmark/src/vllm_grpc_bench/m6_sweep.py tools/benchmark/src/vllm_grpc_bench/m6_1_sweep.py tools/benchmark/src/vllm_grpc_bench/m6_1_1_sweep.py` returns the helper definition + emit-site usages.
- [ ] T026 [US3] When `tools/benchmark/src/vllm_grpc_bench/m6_1_2_sweep.py` is created (Phase 6 T029), it MUST carry a `_stderr_ts()` helper at the top using the modern import shape (`from datetime import UTC, datetime`; helper body `return datetime.now(UTC).strftime("[%Y-%m-%dT%H:%M:%SZ]")`) per R-7. EVERY `print(..., file=sys.stderr, flush=True)` call site in `m6_1_2_sweep.py` MUST be prefixed with `_stderr_ts() + " " + ...`. Same applies to `m6_1_2_validate.py` (Phase 6 T031) and `m6_1_2_network_probe.py` (US1 T015 already enforces this for the FR-005a + FR-006 warnings). Linked as a checklist item to T029 + T031 — verify at sweep-orchestrator implementation time.
- [ ] T027 [US3] Run the US3 unit tests: `uv run pytest tools/benchmark/tests/test_m6_1_2_progress_format.py -v` — both tests pass.

**Checkpoint**: M6.1.2-emitted stderr is uniformly timestamped. Long-running sweep logs are diagnosable from stderr alone per Story 3's user-value framing.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Wire the three Stories together through the sweep orchestrator, reporter, validate entry point, and CLI. Run the smoke-equivalent validation sweep on Modal A10G eu-west-1. Update ANALYSIS.md + `contracts/instrumentation.md`. Pass the full lint chain. Push the branch.

### Cross-cutting glue (orchestrator + reporter + validate + CLI)

- [ ] T028 [P] Create `tools/benchmark/src/vllm_grpc_bench/m6_1_2_reporter.py` mirroring `m6_1_1_reporter.py:407-485` (per [`data-model.md`](./data-model.md) "Module Surface Map"): `render_json(...)` produces the M6.1.2 artifact JSON with every M6.1.1-inherited top-level key PLUS the three NEW keys `network_paths` (from US1's `run_topology_probe` output), `cohort_set` (alphabetically sorted per [`data-model.md`](./data-model.md)), and `cohort_omissions` (optional dict; absent / None when no intentional omissions); `render_markdown(...)` produces the human-readable companion at `docs/benchmarks/m6_1_2-methodology-discipline.md` with the per-cell tables matching M6.1.1's shape plus a new "Network paths" section citing the `network_paths` block; `write_m6_1_2_report(...)` invokes `build_cohort_set_and_omissions(...)` from `m6_1_2_types` to enforce the FR-016 invariant BEFORE writing the JSON. Strict-superset over M6.1.1's manifest shape (FR-004 + FR-016).
- [ ] T029 Create `tools/benchmark/src/vllm_grpc_bench/m6_1_2_sweep.py` orchestrator (per [`data-model.md`](./data-model.md) "Cohort iteration semantics"): `run_m6_1_2_sweep(config: M6_1_2Config) -> M6_1_2SweepArtifact`. Sequence per R-8: (1) Modal deploy + handshake (reuses `provide_m6_endpoint` / `provide_m6_1_rpc_driver` UNCHANGED per FR-022), (2) call `m6_1_2_network_probe.run_topology_probe(handshake_dict, cohorts=M6_1_2_COHORTS, per_cohort_timeout_seconds=30)` per FR-001, (3) iterate `M6_1_CELLS` (REUSED per R-2; from `m6_1_types.py:72-82`) — for each `(path, _, c)` cell, call `cohorts_at_concurrency(c)` (per T021), then for each cohort run warmup then measurement via `m6_1_rpc_driver.py`'s dispatch (T020's 4-cohort table), (4) call `m6_1_2_reporter.write_m6_1_2_report(...)`. Top of file carries the `_stderr_ts()` helper per T026; every `print(..., file=sys.stderr, flush=True)` call prefixed. Inherits M6.0a-corrected concurrent dispatch from `m6_1_1_sweep.py`'s `_measure_cell` pattern (per FR-022 — no engine-cost / dispatch-mechanics changes).
- [ ] T030 [P] Create `tools/benchmark/src/vllm_grpc_bench/m6_1_2_validate.py` per [`data-model.md`](./data-model.md) "Module Surface Map": `run_m6_1_2_validate(args: argparse.Namespace) -> int`. Invokes `run_m6_1_2_sweep(...)` with `n_measurement=50`, `M6_1_CELLS` (the full M6.1.1 6-cell matrix per FR-024 + round-1 Q4), `M6_1_2_COHORTS` (4-element); writes the artifact to the canonical path `docs/benchmarks/m6_1_2-methodology-discipline.{md,json}` per FR-029 (overridable via `args.m6_1_2_report_out` / `args.m6_1_2_report_json_out`); returns 0 on success, non-zero per the exit-code table in [`contracts/cli.md`](./contracts/cli.md).
- [ ] T031 [P] Create `tools/benchmark/src/vllm_grpc_bench/m6_1_2_full.py` (the `--m6_1_2` entry-point counterpart to `m6_1_2_validate.py`): `run_m6_1_2_sweep_full(args: argparse.Namespace) -> int`. Same sweep shape as T030 per FR-024 ("Identical sweep shape to `--m6_1_2-validate`") — the distinction is operator-intent (publishable artifact vs harness-wiring confidence-builder). Optionally distinct artifact filename via the operator's `args.m6_1_2_report_out` override; default writes to the same `docs/benchmarks/m6_1_2-methodology-discipline.{md,json}` paths per FR-029.
- [ ] T032 Patch `tools/benchmark/src/vllm_grpc_bench/__main__.py` (lines 525-600 area, mirroring M6.1.1's argparse block): add `--m6_1_2` (action `store_true`), `--m6_1_2-validate` (action `store_true`), and the 12 namespaced sub-flags per [`contracts/cli.md`](./contracts/cli.md) with the EXACT defaults shown there: `--m6_1_2-modal-region` defaults to `"eu-west-1"`, `--m6_1_2-base-seed` defaults to `42`, `--m6_1_2-model` defaults to `"Qwen/Qwen3-8B"` (verbatim from M6.1.1 per FR-027 + round-3 Q2). Add `--m6_1_2` and `--m6_1_2-validate` to the mutual-exclusion list against all 13 prior mode flags listed in FR-026. Dispatch wiring: if `args.m6_1_2`: `return run_m6_1_2_sweep_full(args)`; if `args.m6_1_2_validate`: `return run_m6_1_2_validate(args)`.

### CLI tests

- [ ] T033 [P] Create `tools/benchmark/tests/test_m6_1_2_cli.py` (per [`contracts/cli.md`](./contracts/cli.md) "Default-inheritance regression test"): `test_m6_1_2_inheritable_defaults_match_m6_1_1()` parses `["--m6_1_2-validate"]` and asserts `args.m6_1_2_modal_region == "eu-west-1"`, `args.m6_1_2_base_seed == 42`, `args.m6_1_2_model == "Qwen/Qwen3-8B"` — fails loudly if a future refactor silently drifts any of the three (FR-027 + round-3 Q2); `test_m6_1_2_modes_mutually_exclusive()` asserts `["--m6_1_2", "--m6_1_2-validate"]` raises argparse error; `test_m6_1_2_rejects_against_m6_1_1_diagnose()` asserts `["--m6_1_2-validate", "--m6_1_1-diagnose"]` raises argparse error; `test_m6_1_2_full_subflag_set_parses()` parses every flag listed in [`contracts/cli.md`](./contracts/cli.md) with non-default values and asserts each is captured in the Namespace.
- [ ] T034 [P] Create `tools/benchmark/tests/test_m6_1_2_smoke_validate_cli.py` (integration test per [`plan.md`](./plan.md) "Testing" section): exercise `--m6_1_2-validate --m6_1_2-skip-deploy` against a stub RPC driver that returns canned timings; assert the resulting artifact JSON parses + contains `network_paths` (with stub-injected probe results) + `cohort_set` + per-cell rows for all 4 cohorts (3 at `c=1`); no Modal compute required. Catches wiring regressions end-to-end.
- [ ] T035 Run the full lint chain locally per [`feedback_local_lint_chain`](../../.claude/projects/-Users-bsansom-projects-vllm-grpc/memory/feedback_local_lint_chain.md) memory + Constitution Principle IV — all four MUST pass before push: `uv run ruff check tools/benchmark/`, `uv run ruff format --check tools/benchmark/`, `uv run mypy --strict tools/benchmark/src/vllm_grpc_bench/m6_1_2_*.py`, `uv run pytest tools/benchmark/tests/test_m6_1_2_*.py`. Fix any failures BEFORE Phase 7.

### Validation sweep (Modal compute)

- [ ] T036 Set `MODAL_BENCH_TOKEN` env var (per [`contracts/cli.md`](./contracts/cli.md) `--m6_1_2-modal-token-env` default); verify Modal CLI auth status (`modal token current`).
- [ ] T037 Run the smoke-equivalent validation sweep per [`quickstart.md`](./quickstart.md) Phase 2: `uv run python -m vllm_grpc_bench --m6_1_2-validate --m6_1_2-modal-region=eu-west-1 --m6_1_2-base-seed=42 --m6_1_2-model="Qwen/Qwen3-8B"`. Expected wall-clock ≤ 35 min per SC-001; expected Modal compute ≤ $0.50 per SC-008 (target $0.40). The CLI defaults make the three explicit args redundant per FR-027; they're included for operator-spot-check.
- [ ] T038 Inspect the artifact per [`quickstart.md`](./quickstart.md) Phase 2 verification: `jq 'keys' docs/benchmarks/m6_1_2-methodology-discipline.json` returns the new top-level keys (`cohort_set`, `network_paths`, optionally `cohort_omissions`) plus M6.1.1-inherited keys; `jq '.cohort_set' docs/benchmarks/m6_1_2-methodology-discipline.json` returns the alphabetically-sorted 4-element array; `jq '.network_paths | to_entries | map({cohort: .key, cloud_provider: .value.cloud_provider, region: .value.region})' docs/benchmarks/m6_1_2-methodology-discipline.json` returns the spike-confirmed topology pattern per SC-002. If FR-006's cohort-CSP-mismatch warning fired, stop and update `ANALYSIS.md` (T040) per the NEW topology, not the spike's (architectural change is methodology-significant — flag in the PR description).
- [ ] T039 Compute the protocol-only and multi-cloud-routing differentials per SC-004 to confirm Story 2's value-prop holds: `jq` snippets from [`quickstart.md`](./quickstart.md) Phase 2 "Verify the protocol-only differential is computable" — the per-chat_stream-cell `rest_plain_tcp.engine_ttft_ms.mean - default_grpc.engine_ttft_ms.mean` (protocol-only) and `rest_plain_tcp.engine_ttft_ms.mean - rest_https_edge.engine_ttft_ms.mean` (multi-cloud-routing) deltas are both computable in a single subtraction. Record the deltas in the markdown report (T028's `render_markdown`).

### Documentation updates (FR-008 + FR-009 + SC-007)

- [ ] T040 Edit `ANALYSIS.md` per FR-008 + [`quickstart.md`](./quickstart.md) Phase 2 "Update ANALYSIS.md": search for the existing "different network path" phrasing in M5 / M6 sections; replace with the multi-CSP framing — "cohorts enter Modal via entirely different cloud providers (Microsoft Azure for `*.modal.run`; AWS us-west-1 for `*.modal.host`); see [`docs/spikes/m6-1-roadmap-additions/01-topology-traceroute-findings.md`](docs/spikes/m6-1-roadmap-additions/01-topology-traceroute-findings.md) for the live traceroute proof and [`docs/benchmarks/m6_1_2-methodology-discipline.json`](docs/benchmarks/m6_1_2-methodology-discipline.json) for per-sweep evidence in the `network_paths` block." If T038 surfaced an FR-006 mismatch, cite the NEW topology, not the spike's.
- [ ] T041 [P] Edit `contracts/instrumentation.md` (create if absent per [`plan.md`](./plan.md) Storage / FR-009): add a section documenting `network_paths` (cite [`contracts/network-paths.md`](./contracts/network-paths.md)), `cohort_set`, and `cohort_omissions` (cite [`contracts/artifact-schema.md`](./contracts/artifact-schema.md)) as part of the M6.1.2-forward artifact schema. Both updates (T040 + T041) MUST land in the same PR as the code change per SC-007.

### Push & PR

- [ ] T042 Final lint chain re-run: `uv run ruff check tools/benchmark/ && uv run ruff format --check tools/benchmark/ && uv run mypy --strict tools/benchmark/src/vllm_grpc_bench/m6_1_2_*.py && uv run pytest tools/benchmark/tests/test_m6_1_2_*.py` — all four green (Constitution Principle IV); plus assert the full repo regression suite doesn't ERROR on M6.1.2-touched paths: `uv run pytest tools/benchmark/tests/ -q` — failures must be PRE-EXISTING (compare against the baseline failure set on `main`), not introduced by M6.1.2.
- [ ] T043 Push the branch: `git push -u origin 025-m6-1-2-methodology-discipline`. Per [`feedback_pr_creation_deferred`](../../.claude/projects/-Users-bsansom-projects-vllm-grpc/memory/feedback_pr_creation_deferred.md) memory — PR creation is a SEPARATE gate from push; pause and ask the operator before `gh pr create`. The PR description (when authorized) references: spec (`specs/025-m6-1-2-methodology-discipline/spec.md`, 13 Q/A across 3 clarify rounds), plan (`specs/025-m6-1-2-methodology-discipline/plan.md`), published artifact (`docs/benchmarks/m6_1_2-methodology-discipline.{md,json}`), and PLAN.md M6.1.2 section (`docs/PLAN.md` §234-258).

---

## Dependencies & Story Completion Order

```text
Phase 1 (Setup, T001–T004)
   │
   ├─→ T004 (spike cherry-pick) is a hard precondition for US3 verification
   │
   ▼
Phase 2 (Foundational, T005)
   │   m6_1_2_types.py imported by EVERYTHING below
   ▼
Phase 3 (US1, T006–T016) ──────┐
   │   network_probe.py        │
   │                            │
Phase 4 (US2, T017–T023) ──────┤── US3 (T024–T027) is independent and may run in parallel
   │   rpc_driver patch +       │   with US1/US2 once T004 (cherry-pick) lands
   │   cohort iterator helpers  │
   │                            │
   ▼                            ▼
Phase 6 (Polish, T028–T043)
   │   T028 reporter depends on US1 (network_paths) + US2 (cohort_set / cohort_omissions)
   │   T029 sweep orchestrator depends on US1 + US2 + US3
   │   T030 validate.py + T031 full.py depend on T029
   │   T032 CLI wiring depends on T030 + T031
   │   T033/T034 CLI tests depend on T032
   │   T035 lint chain depends on all code being in place
   │   T036–T039 validation sweep depends on T032
   │   T040–T041 docs depend on T038 (the published artifact)
   │   T042–T043 push depends on T040–T041 landing in the same commit
```

**Within-story parallel opportunities**:

- **Phase 3 (US1)**: T006 + T007 + T008 + T009 + T010 are all `[P]` — different test functions in independent files. Run them in parallel during test-authoring.
- **Phase 4 (US2)**: T017 + T018 + T019 are `[P]` test functions; T021 + T022 are `[P]` helper functions (different additions to the same file, BUT can be authored in parallel and merged).
- **Phase 5 (US3)**: T024 is `[P]`; T025 is verification only (read-only); T026 is a constraint linked to T029/T031 (verified at orchestrator implementation time).
- **Phase 6**: T028 + T030 + T031 are `[P]` (different new files); T033 + T034 are `[P]` (different test files); T041 is `[P]` against T040 (different doc files).

---

## Implementation Strategy

### MVP (US1 only)

A minimal M6.1.2 with ONLY US1 in scope produces a runnable `--m6_1_2-validate` sweep that:
- Captures the `network_paths` block at sweep start.
- Runs the inherited 3-cohort matrix (no `rest_plain_tcp`).
- Emits timestamped progress lines (inherited from the spike cherry-pick).
- Writes the artifact to `docs/benchmarks/m6_1_2-methodology-discipline.{md,json}`.

This MVP delivers Story 1's value-prop (per-sweep topology evidence in the artifact) AND validates the strict-superset schema evolution. It is a publishable methodology-discipline addition on its own. US2 and US3 then layer in incrementally.

### Incremental delivery

1. **Slice 1 (US1 alone)**: Phases 1, 2, 3, and a reduced Phase 6 (T028/T029/T030/T032/T035/T037 minus the `cohort_set` / `cohort_omissions` work). Operator gets a topology-evidence-only M6.1.2.
2. **Slice 2 (+ US2)**: Phase 4 + T017–T019/T021/T022 + the `cohort_set` / `cohort_omissions` work in T028. Operator gets the 4-cohort split + the cohort-set enumeration in the artifact.
3. **Slice 3 (+ US3 verification)**: Phase 5 (T024/T025/T027). Confirms the spike cherry-pick survives the M6.1.2-specific orchestrator + warning emitters.
4. **Slice 4 (publish)**: Phases 7's docs + push (T040–T043). The published artifact + ANALYSIS.md correction + `contracts/instrumentation.md` schema doc.

Each slice is independently mergeable. The recommended PR shape is a **single PR** (M6.1.2 is small enough; 5 new modules + 2 modified files + 5 test files + 2 doc updates is the same scale as M6.1.1's PR #27). If the operator prefers a two-PR sequence (e.g., MVP slice as PR-1, US2 + US3 as PR-2), that's compatible with the spec's `cohort_omissions: {"rest_plain_tcp": "deferred to M6.1.2 PR-2"}` capability — but the default-inheritance regression test (T033) requires Phase 6 to land before the PR opens, so a single PR is simpler.

---

## Validation

**Format check** (per the protocol's "Format Validation" requirement):
- All 43 tasks use the strict `- [ ] [TaskID] [P?] [Story?] Description with file path` format.
- Setup phase (T001–T004): no Story label (correct).
- Foundational phase (T005): no Story label (correct).
- US1 phase (T006–T016): every task has `[US1]` label (correct).
- US2 phase (T017–T023): every task has `[US2]` label (correct).
- US3 phase (T024–T027): every task has `[US3]` label (correct).
- Polish phase (T028–T043): no Story label (correct — these are cross-cutting).
- Every task description names a concrete file path (or paths) where the edit lands.

**Independent test criteria** (one per story, sourced from spec.md):
- US1 Independent Test (per spec Story 1): synthesize an M6.1.2 artifact, confirm `network_paths` block populates cleanly + an M6.1.1-vintage reader parses without error. Exercised by T010 (artifact-schema test) + T038 (validation-sweep inspection).
- US2 Independent Test (per spec Story 2): per-cell rows include all 4 cohorts at `c ≥ 2` (3 at `c = 1`); reader computes `rest_plain_tcp` vs `default_grpc` per cell in a single subtraction. Exercised by T034 (integration test) + T038 + T039 (validation-sweep differential check).
- US3 Independent Test (per spec Story 3): every stderr line matches the timestamp regex. Exercised by T024 (progress-format test).

**MVP boundary**: User Story 1 alone (Slice 1 above) delivers a publishable methodology-discipline addition. The spec's P1/P2/P3 priorities flow cleanly into the slicing.
