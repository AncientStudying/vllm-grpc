# Implementation Plan: M6.1.2 — Methodology Discipline: Topology Proof + 3-Cohort Reintroduction + Harness QoL

**Branch**: `025-m6-1-2-methodology-discipline` | **Date**: 2026-05-17 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/025-m6-1-2-methodology-discipline/spec.md`

## Summary

M6.1.2 is a methodology-discipline bundle that ships three additive harness changes before M6.2 introduces the `max_tokens` axis. Scoped by `spike/m6-1-roadmap-additions` items #1 + #2 + #3 ([`docs/spikes/m6-1-roadmap-additions/`](../../docs/spikes/m6-1-roadmap-additions/)). The bundle is harness-only: no engine-cost code changes, no Modal endpoint code changes, no classifier changes; strict-superset artifact-schema additions, a restored M5.2-era cohort, and a carry-forward of an already-implemented stderr ergonomic.

**Three deliverables** (each a User Story in the spec):

1. **Per-sweep `tcptraceroute` topology probe** (P1, Story 1) — runs once at sweep start, in parallel across cohorts, with a 30s per-cohort timeout. Writes a top-level `network_paths` block to the artifact JSON with `endpoint_ip`, ordered `hops` (each with best-effort per-hop `cloud_provider` annotation), cohort-level `cloud_provider` (enum `"AWS"` / `"Microsoft Azure"` / `"GCP"` / `"unknown"`), `region`, `probe_method: "tcptraceroute"`, `probed_at_utc`. Three loud-stderr warnings: probe-binary-missing per cohort, every-probe-failed in one sweep (FR-005a), cohort-CSP-mismatch vs spike-expected pattern (FR-006). The probe is methodology-supporting, not measurement-critical — never aborts the sweep.

2. **Reintroduce the `rest_plain_tcp` cohort** (P2, Story 2) — restore M5.2's 4-cohort split (`rest_https_edge`, `rest_plain_tcp`, `default_grpc`, `tuned_grpc_multiplexed`) at `c ≥ 2`; M5.2's tuned-pair collapse-at-c=1 rule (`default_grpc` and `tuned_grpc_multiplexed` collapse to a single gRPC cohort at singleton concurrency) is preserved verbatim. Uses M6.0a-corrected concurrent dispatch and the M6.1.1-expansion classifier instrumentation already in place — no special-casing. Top-level `cohort_set` array + optional `cohort_omissions` map distinguish design-intentional cohort omission from runtime cohort failure.

3. **Timestamped progress lines** (P3, Story 3) — carry forward the `_stderr_ts()` helper + emit-site changes from spike commit `3763687` verbatim (5 files: `m6_sweep.py`, `m6_1_sweep.py`, `m6_1_1_sweep.py`, `test_m6_quickstart_format.py`, `traceroute_probe.py`). M6.1.2 adds its own `_stderr_ts()` in `m6_1_2_sweep.py` so M6.1.2-launched progress lines also carry the prefix. The new FR-005a / FR-006 warning lines (introduced by Story 1) also carry the same prefix per FR-020 (round-2 Q5 clarification).

**Technical approach.** Build a parallel `m6_1_2_*` module family mirroring M6.1.1's naming pattern (M6.1.1 has 11 named files under `tools/benchmark/src/vllm_grpc_bench/`; M6.1.2 will add ~5 more). The `--m6_1_2` (full sweep) and `--m6_1_2-validate` (smoke-equivalent validation sweep) top-level CLI mode flags are mutually exclusive with each other and with all M5.x / M6 / M6.1 / M6.1.1 mode flags (FR-026). The 12 `--m6_1_2-*` namespaced sub-flags mirror M6.1.1's set; defaults for `--m6_1_2-modal-region` (`"eu-west-1"`), `--m6_1_2-base-seed` (`42`), `--m6_1_2-model` (`"Qwen/Qwen3-8B"`) are explicitly sourced verbatim from M6.1.1's `__main__.py:541-572` (FR-027 round-3 Q2 clarification — silent default drift on these three would confound FR-024's "directly comparable cell-by-cell against M6.1.1's published baseline" property).

**The reintroduced `rest_plain_tcp` cohort.** Spike #2's code-surface enumeration confirmed: M5.2's `rest_plain_tcp` cohort wiring survives — `m5_2_sweep.py:241-246` still defines the cohort; `rest_cohort.py` (22 KB) and `rest_shim.py` (24 KB) compile cleanly; `scripts/python/modal_bench_rest_grpc_server.py:188-194` still spawns the `modal.forward(_REST_PORT, unencrypted=True)` plain-TCP tunnel and `:208` exports `rest_plain_tcp_url` to the handshake dict. The gap is on the M6.x side: `m6_1_rpc_driver.py:305-345` has dispatch paths for the 3 inherited cohorts only — adding a 4th cohort case (mirroring `rest_https_edge`'s `httpx.AsyncClient` shape, but pointing at `rest_plain_tcp_url` instead of `rest_https_edge_url`) is the bulk of Story 2's code surface. M5.2's `m5_2_symmetry.py` is NOT ported forward — prompt-symmetry is M6.1.3's territory per the spec's out-of-scope note + spike #5.

**The TCP-SYN topology probe.** The spike's `docs/spikes/m6-1-roadmap-additions/traceroute_probe.py` is the working reference but uses UDP/ICMP `traceroute` (dies at AWS/Azure firewall ≈ hop 5 per the spike's TL;DR). M6.1.2 ports the pattern (subprocess invocation, hop parsing, parallel-per-cohort execution) but swaps `traceroute -n -w -q -m` → `tcptraceroute` with port (e.g., `tcptraceroute -n -w 2 -q 1 -m 18 <host> <port>`) so SYN packets reach past the cloud edge. Net-new module `m6_1_2_network_probe.py` owns subprocess invocation + hop-line parsing + IP-range / whois attribution. No existing project utility covers CSP IP-range attribution (Explore confirmed zero hits across `tools/`/`scripts/`); the new module fetches AWS/Azure/GCP published IP-range files (refreshed per-probe-cycle with a documented cache-staleness budget) and applies ARIN whois lookups for transit ASNs on a best-effort, no-retry basis (round-3 Q1 clarification).

**The smoke-equivalent validation sweep.** Distinct from project "smoke" CLI mode (round-1 Q5 clarification): no `--m6_1_2-smoke` flag exists; the `--m6_1_2-validate` flag dispatches a single n=50 sweep covering the full M6.1.1 6-cell matrix (`embed × {c=1, c=4, c=8}`, `chat_stream × {c=1, c=4, c=8}` — sourced from `m6_1_types.py:72-82` `M6_1_CELLS`) with the new 4th cohort and the `network_paths` probe enabled. Cost ~$0.40 (cap $0.50 per SC-008). Resulting artifact at `docs/benchmarks/m6_1_2-methodology-discipline.{md,json}` (FR-029 round-2 Q4) is directly comparable cell-by-cell against M6.1.1's published 3-cohort × 6-cell × n=50 baseline at `docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}`.

## Technical Context

**Language/Version**: Python 3.12 (project standard; matches M5.x / M6 / M6.1 / M6.1.1 harness, frontend, proxy, and Modal app).

**Primary Dependencies**:

- `vllm` + `torch` — UNCHANGED from M6.1.1's pinned set (FR-022: M6.1.2 modifies no engine-cost code or Modal-endpoint code). Operator runs `uv sync --frozen` against the existing `uv.lock` to inherit M6.1.1's versions.
- `grpcio` + `grpcio-tools` — UNCHANGED.
- `httpx` (REST client used by `rest_cohort.py` / `rest_shim.py`) — UNCHANGED; the `rest_plain_tcp` cohort reuses the existing client path with a plain-TCP endpoint URL.
- `modal` — UNCHANGED (M6.1.2 does not change `scripts/python/modal_bench_rest_grpc_server.py`; spike confirmed the `rest_plain_tcp_url` export still exists at line 188-208).
- `tcptraceroute` — **NEW external binary dependency** on the operator's machine; installed via `brew install tcptraceroute` (macOS) or `apt install tcptraceroute` / `dnf install tcptraceroute` (Linux). Invoked via `subprocess.run` from the new `m6_1_2_network_probe.py` module. If absent, FR-005's error-block-and-continue behavior fires per cohort (the sweep is not aborted; topology evidence is recorded as `error: "tcptraceroute_unavailable"`).
- AWS / Azure / GCP IP-range files — fetched per-probe-cycle from public URLs (`https://ip-ranges.amazonaws.com/ip-ranges.json`, `https://www.microsoft.com/en-us/download/details.aspx?id=56519` for Azure JSON, `https://www.gstatic.com/ipranges/cloud.json` for GCP) and cached locally with a documented staleness budget. Staleness handling is an implementation detail (FR-007); a 24-hour cache TTL is the proposed plan-level default.

**Storage**:

- Outputs: `docs/benchmarks/m6_1_2-methodology-discipline.{md,json}` — NEW (FR-029); the published artifact for `--m6_1_2` (full sweep) and `--m6_1_2-validate` (smoke-equivalent validation sweep). The `--m6_1_2-validate` sweep overwrites the same canonical path; the operator may opt-out via `--m6_1_2-report-out` / `--m6_1_2-report-json-out` overrides per FR-027.
- Outputs: `docs/benchmarks/m6_1_2-events.jsonl` — sidecar events file (NEW, mirroring M6.1.1's `m6_1_1-events.jsonl` convention).
- Inputs: `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` — READ-ONLY M6.1.1 baseline; consumed via `--m6_1_2-m6-1-1-baseline` (default path; FR-027) for per-cell comparison reference.
- Modifications: `ANALYSIS.md` — UPDATED to cite the multi-CSP finding from spike #1, replacing the looser "different network path" phrasing (FR-008).
- Modifications: `contracts/instrumentation.md` (or equivalent canonical schema doc — the actual filename is resolved in Phase 1's contracts work, with a fallback to a NEW `contracts/instrumentation.md` if none exists) — UPDATED to document `network_paths`, `cohort_set`, `cohort_omissions` as part of the M6.1.2-forward artifact schema (FR-009 + FR-016).
- CSP IP-range cache: `~/.cache/vllm-grpc/ip-ranges/` (or equivalent platform XDG path) — NEW operator-machine local cache for AWS/Azure/GCP IP-range JSON files. Cache TTL 24h; cache miss triggers a re-fetch.

**Testing**: `pytest` + `pytest-asyncio` (project convention). Coverage tiers:

- **Unit tests** — `tools/benchmark/tests/test_m6_1_2_network_probe.py` (NEW):
  - CSP attribution: feed canned IPs (one AWS, one Azure, one GCP, one transit-ASN, one truly-unknown) into `attribute_cloud_provider()` and assert the enum value.
  - Hop-parser: feed canned `tcptraceroute` stdout (captured from the spike's reference run) into `parse_tcptraceroute_output()` and assert the `hops[]` list shape matches FR-003.
  - Probe-timeout: mock a `subprocess.run` that hangs ≥ 30s; assert the probe gives up at the 30s mark and returns `{ error: "probe_timeout", ... }` (FR-002a).
  - Probe-binary-missing: mock a `subprocess.run` raising `FileNotFoundError`; assert the cohort entry contains `{ error: "tcptraceroute_unavailable", ... }` (FR-005).
- **Unit tests** — `tools/benchmark/tests/test_m6_1_2_artifact_schema.py` (NEW):
  - `cohort_set` / `cohort_omissions` strict-superset evolution: synthesize an M6.1.2 artifact, parse it with an M6.1.1-vintage reader (the M6.1.1 reporter's JSON loader), assert no parse error and the M6.1.2-only keys are ignored cleanly (SC-006).
  - The new fields' shape: `cohort_set` is a sorted JSON array; `cohort_omissions` keys are cohort names that are NOT in `cohort_set`; cohort names in `cohort_set` + cohort names in `cohort_omissions` together must equal `{"rest_https_edge", "rest_plain_tcp", "default_grpc", "tuned_grpc_multiplexed"}` (i.e., the canonical 4-cohort universe).
- **Unit tests** — `tools/benchmark/tests/test_m6_1_2_cli.py` (NEW):
  - All `--m6_1_2-*` flags parse with their documented defaults (FR-026 + FR-027 + the verbatim-inheritance constraint from round-3 Q2).
  - Mutual exclusion: `--m6_1_2` + `--m6_1_2-validate` → argparse error; `--m6_1_2` + `--m6_1_1-diagnose` → argparse error; full pairwise sweep against all 14 mode flags listed in FR-026.
  - Default-inheritance regression: assert `--m6_1_2-modal-region` defaults to `"eu-west-1"`, `--m6_1_2-base-seed` defaults to `42`, `--m6_1_2-model` defaults to `"Qwen/Qwen3-8B"` — fail loudly if any of those silently drifts during a future refactor.
- **Unit tests** — `tools/benchmark/tests/test_m6_1_2_progress_format.py` (NEW; parallel pattern to `test_m6_quickstart_format.py`):
  - Each stderr line emitted during a sweep matches the regex `^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\]` (SC-005).
  - The new FR-005a all-probes-fail warning + FR-006 cohort-CSP-mismatch warning lines also match the same regex (round-2 Q5 / FR-020).
- **Integration test** — `tools/benchmark/tests/test_m6_1_2_smoke_validate_cli.py` (NEW): a CLI-only test that exercises `--m6_1_2-validate --m6_1_2-skip-deploy` against a stub RPC driver that returns canned timings, end-to-end through the sweep orchestrator + reporter, asserting the resulting artifact JSON parses + contains `network_paths` + `cohort_set` + all expected per-cell rows. No Modal compute required.
- **CI gate (Constitution Principle IV)**: All new tests run in the same `pytest` invocation as the existing M6.1.1 test suite; failure blocks the M6.1.2 PR merge gate. The local-lint chain (`ruff check`, `ruff format --check`, `mypy --strict`, `pytest`) per [`feedback_local_lint_chain`](../../specs/022-m6-1-real-prompt-embeds/checklists/requirements.md) memory must pass before push.

**Target Platform**:

- **Code changes**: operator workstation only — no Modal compute required for code/lint/test gates.
- **Smoke-equivalent validation sweep** (the `--m6_1_2-validate` run): Modal A10G GPU instance in `eu-west-1` (FR-027 default, sourced verbatim from M6.1.1). Driven from operator workstation; operator workstation must have `tcptraceroute` installed for the topology probe to populate cleanly.
- **Full M6.1.2 sweep** (the `--m6_1_2` run): same as validate (no separate environmental requirement). M6.1.2's full sweep is the same shape as the validation sweep — the only operator-visible distinction is that `--m6_1_2-validate` is the suggested mode for the M6.1.2 PR validation gate.

**Project Type**: Sibling library + benchmark harness — Python monorepo with `proxy/`, `frontend/`, `client/`, `proto/`, `tools/benchmark/`, `scripts/`, `docs/benchmarks/`. M6.1.2 is a methodology-discipline sub-milestone (additive to M6 / M6.1 / M6.1.1 harness), not a library / CLI / web-service in the conventional product sense.

**Performance Goals**:

- SC-001: `--m6_1_2-validate` sweep completes in ≤ 35 min wall-clock on Modal A10G `eu-west-1` (M6.1.1's baseline ~27 min + bounded ~120s probe overhead from FR-002a/FR-001a + cohort-count expansion 3→4 ≈ ~33% extra cohort wall-clock; the 35 min target leaves headroom).
- SC-002: `network_paths` block is non-empty, with one entry per cohort (4 entries at `c ≥ 2`, 3 at `c = 1`); for a deploy conforming to the spike-confirmed topology pattern, `rest_plain_tcp.cloud_provider == "AWS"` and `rest_plain_tcp.region == "us-west-1"`.
- SC-003: Per-cell rows include all 4 cohorts at `c ≥ 2` (3 at `c = 1`); the `rest_plain_tcp` cohort participates in M6.1.1's classifier on the same terms as the inherited cohorts.
- SC-004: A reader can compute `rest_plain_tcp` vs `default_grpc` and `rest_plain_tcp` vs `rest_https_edge` per chat_stream cell from the published markdown — the protocol-only and multi-cloud-routing differentials are each a single subtraction.
- SC-005: Every stderr line from the progress reporter (and the new FR-005a/FR-006 warning lines) matches the timestamp regex.
- SC-006: M6.1.1-aware reader parses the M6.1.2 artifact JSON without parse error (strict-superset).
- SC-007: ANALYSIS.md + `contracts/instrumentation.md` updates land in the same PR as the code change, not deferred.
- SC-008: Total Modal compute ≤ $0.50 (target $0.40).
- SC-009: M6.1.3 / M6.2 / M7 / M8 operators inherit the conventions zero-config.
- SC-010: A reader unfamiliar with M6.x reads the published markdown + `contracts/instrumentation.md` and can determine cohort routing + isolate-which-variable subtractions in ≤ 5 min.

**Constraints**:

- **Harness-only scope** (FR-022): all code changes confined to `tools/benchmark/src/vllm_grpc_bench/` and `tools/benchmark/tests/`. No edits to `proxy/`, `frontend/`, `client/`, `proto/`, `scripts/python/modal_bench_rest_grpc_server.py`, or any vLLM / torch source.
- **No `.proto` edits**: the bundle is Python-only + JSON-schema + markdown (Constitution Principle I).
- **No engine path changes** (FR-022): the M6.1.1 Modal endpoint is reused unchanged; `provide_m6_endpoint` + `provide_m6_1_rpc_driver` are not modified.
- **Verdict-body preservation** (FR-023): M6 / M6.1 / M6.1.1 published artifact bodies are read-only; cross-references from prior artifacts to M6.1.2 are out of scope for this milestone.
- **Strict-superset schema** (FR-004 + FR-016): `network_paths`, `cohort_set`, `cohort_omissions` are added to the M6.1.2 artifact JSON as top-level keys without bumping `schema_version`; pre-existing M6.1.1 / M6.2-aware readers ignore the unknown keys without error.
- **Tool-specific probe binary** (FR-002, round-2 Q3): `tcptraceroute` only — no cross-platform fallbacks (`traceroute -T`, `mtr -T`); operator installs via platform package manager once.
- **Probe timeout + parallelism** (FR-001a + FR-002a): per-cohort 30s timeout; cohorts probed in parallel via `asyncio.to_thread(subprocess.run, ...)` + `asyncio.gather`. Worst-case probe wall-clock bounded at ~30s.
- **Probe is methodology-supporting, not measurement-critical** (FR-005 + FR-005a): probe failure NEVER aborts the sweep — single-cohort failure records a per-cohort error block; all-cohort failure records error blocks for all cohorts + emits a loud stderr warning at sweep start.
- **Cohort-set semantics** (FR-016): `cohort_set` array lists cohorts that ACTUALLY RAN; `cohort_omissions` map names INTENTIONALLY OMITTED cohorts with reasons; runtime cohort failures are recorded ONLY in per-cell error rows, never in `cohort_omissions`. The distinction is the entire point of the split.
- **Verbatim default inheritance from M6.1.1** (FR-027 + round-3 Q2): `--m6_1_2-modal-region` defaults to `"eu-west-1"`, `--m6_1_2-base-seed` defaults to `42`, `--m6_1_2-model` defaults to `"Qwen/Qwen3-8B"` — sourced from `__main__.py:541/563/568`. The regression test in `test_m6_1_2_cli.py` is the spec-level guard against silent drift.
- **No `--m6_1_2-smoke` flag** (FR-024 + round-1 Q5): the smoke-equivalent validation sweep is dispatched via `--m6_1_2-validate`, NOT via a project-vocabulary "smoke" mode (which uses small `n` + small cell subset; M6.1.2's validation sweep uses n=50 + full 6-cell matrix).
- **Per-hop CSP annotation is best-effort** (FR-003 + round-3 Q1): the `hops[].cloud_provider` field is populated when the IP-range / whois lookup resolves; `null` (or absent) otherwise; no retry / rate-limit handling.

**Scale/Scope**:

- **New module files**: 5 — `m6_1_2_types.py`, `m6_1_2_sweep.py`, `m6_1_2_reporter.py`, `m6_1_2_validate.py`, `m6_1_2_network_probe.py`. Combined: ~800–1200 LOC.
- **Modified module files**: 2 — `m6_1_rpc_driver.py` (add `rest_plain_tcp` dispatch path; ~30–50 LOC), `__main__.py` (add `--m6_1_2-*` argparse wiring + mutual exclusion + dispatch to `run_m6_1_2(...)` / `run_m6_1_2_validate(...)`; ~80–120 LOC).
- **New test files**: 4 — `test_m6_1_2_network_probe.py`, `test_m6_1_2_artifact_schema.py`, `test_m6_1_2_cli.py`, `test_m6_1_2_progress_format.py`, plus 1 integration test `test_m6_1_2_smoke_validate_cli.py`. Combined: ~600–1000 LOC.
- **Modified doc files**: 2 — `ANALYSIS.md` (one-line multi-CSP correction citing spike #1), `contracts/instrumentation.md` (or new file if absent; documents `network_paths` + `cohort_set` + `cohort_omissions` schema).
- **New benchmark artifact**: `docs/benchmarks/m6_1_2-methodology-discipline.{md,json}` — produced by the `--m6_1_2-validate` PR validation sweep.
- **External binary install**: `tcptraceroute` — single-line `brew install` / `apt install` for the operator; documented in `quickstart.md`.
- **Modal compute**: ~$0.40 (cap $0.50) per SC-008 — single sweep of the `--m6_1_2-validate` run on Modal A10G `eu-west-1`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against the 5 principles in `.specify/memory/constitution.md` (v1.0.0):

| Principle | Status | Notes |
|---|---|---|
| **I. Proto-First** | **PASS** | M6.1.2 makes no `.proto` edits. The three deliverables are: a JSON-schema strict-superset addition (`network_paths` / `cohort_set` / `cohort_omissions` top-level keys), a Python-only cohort restoration (`rest_plain_tcp` → `httpx.AsyncClient` against an existing Modal-side tunnel URL), and a verbatim carry-forward of an `_stderr_ts()` helper from the spike branch. JSON manifests are not proto-tracked; the cohort restoration touches `m6_1_rpc_driver.py` (Python) + the existing Modal handshake-dict export (no proto schema involved). |
| **II. Library Dependency, Not Fork** | **PASS** | M6.1.2 uses `vllm` + `torch` + `grpcio` + `httpx` + `modal` as ordinary pinned dependencies. No vLLM, torch, or Modal source modification. The new `tcptraceroute` dependency is a system binary, not a Python package fork (operator installs via platform package manager). The new IP-range attribution logic fetches public CSP-published JSON files; no fork or vendoring of upstream attribution libraries. |
| **III. Phase Discipline** | **PASS** | M6.1.2 is a canonical milestone in [`docs/PLAN.md`](../../docs/PLAN.md) (since 2026-05-17 Draft v7) — M6.1.2 §234-258. Spec scope matches PLAN.md M6.1.2: three sub-items (#1 + #2 + #3) from `spike/m6-1-roadmap-additions`. Out-of-scope items (FR-022/FR-023 cross-cutting): engine-cost code changes (M6.1.3's `engine_compute_variation` work), prompt-symmetry restoration (M6.1.3 phase B per spike #5), `max_tokens` axis (M6.2), corpus expansion (M7), multi-model (M8), proxy-edge probes (M6.1.3 item #4), classifier-degeneracy fix (separate M6.1.1 issue). The `cohort_set` + `cohort_omissions` enumeration explicitly preserves the M6.1.2 default 4-cohort matrix while letting M6.2/M7/M8 declare divergence — phase-discipline-compliant inheritance. |
| **IV. CI is the Merge Gate** | **PASS** | All new test files (`test_m6_1_2_*.py`) run in the same `pytest` invocation as the existing M6.1.1 test suite; failure blocks the M6.1.2 PR merge. Local-lint chain (`ruff check`, `ruff format --check`, `mypy --strict`, `pytest`) per [`feedback_local_lint_chain`](../../specs/022-m6-1-real-prompt-embeds/checklists/requirements.md) memory must pass before push. The default-inheritance regression test (`test_m6_1_2_cli.py`'s `--m6_1_2-modal-region` / `-base-seed` / `-model` assertions) prevents silent default drift via CI. The integration test (`test_m6_1_2_smoke_validate_cli.py`) exercises the full CLI → sweep-orchestrator → reporter path against a stub driver, catching wiring regressions without Modal compute. |
| **V. Honest Measurement** | **PASS** | The whole milestone IS a methodology-discipline addition aimed at making cohort-comparison conclusions self-describing. Topology evidence (`network_paths`) is captured per-sweep so claims like "HTTPS-Edge has higher latency" carry the supporting data in the same artifact. The probe is recorded faithfully even when it fails (`network_paths.<cohort> = { error: ... }`) — no silent omission. The cohort-CSP-mismatch warning (FR-006) loudly surfaces methodology-disrupting topology changes rather than absorbing them silently. The `cohort_set` / `cohort_omissions` split distinguishes design omission from runtime failure — no narrative-massaged "cohort missing" ambiguity. The smoke-equivalent validation sweep's artifact (`docs/benchmarks/m6_1_2-methodology-discipline.{md,json}`) commits alongside the code change per Principle V's "all benchmark numbers MUST be committed alongside the code". |

**Result: 5/5 PASS. No violations. Complexity Tracking is empty.**

Re-check after Phase 1 design: see "Post-Design Constitution Check" at the end of this document.

## Project Structure

### Documentation (this feature)

```text
specs/025-m6-1-2-methodology-discipline/
├── plan.md                     # This file (/speckit-plan output)
├── research.md                 # Phase 0 — research items + decisions (/speckit-plan output)
├── data-model.md               # Phase 1 — entity shapes for the new artifact-JSON additions and the network-probe dataclasses (/speckit-plan output)
├── quickstart.md               # Phase 1 — operator playbook: install tcptraceroute, run --m6_1_2-validate, inspect network_paths, file the M6.1.2 PR (/speckit-plan output)
├── contracts/
│   ├── cli.md                  # The --m6_1_2 + --m6_1_2-validate CLI surface + 12 namespaced sub-flags + mutual exclusion + verbatim-inheritance defaults
│   ├── network-paths.md        # The network_paths block schema (per-cohort cloud_provider enum, per-hop best-effort annotation, error-case shape, strict-superset evolution)
│   └── artifact-schema.md      # The cohort_set + cohort_omissions top-level fields and their interaction with the per-cell error-row convention
├── spec.md                     # Feature spec (existing, 13 Q/A clarifications across 3 rounds)
├── checklists/
│   └── requirements.md         # Spec quality checklist (existing)
└── tasks.md                    # /speckit-tasks output (NOT created by /speckit-plan)
```

### Source Code (repository root — extending existing layout)

M6.1.2 adds 5 new `m6_1_2_*` modules + 1 new RPC-driver path + CLI wiring. Net new code under `tools/benchmark/`, no other repository area touched.

```text
tools/benchmark/src/vllm_grpc_bench/
├── m6_1_2_types.py             # NEW — dataclass definitions: M6_1_2Cell (likely identical-shape to M6_1Cell from m6_1_types.py:72-82; the 6-cell matrix is REUSED, not redefined), M6_1_2CohortKind (the 4-cohort literal type), M6_1_2_COHORTS tuple (`("rest_https_edge", "rest_plain_tcp", "default_grpc", "tuned_grpc_multiplexed")`), M6_1_2NetworkPath dataclass, M6_1_2NetworkPathHop dataclass, M6_1_2CohortOmission dataclass.
├── m6_1_2_sweep.py             # NEW — sweep orchestrator: dispatches the full M6.1.1 6-cell × 4-cohort matrix (3-cohort at c=1 per the tuned-pair collapse rule); calls m6_1_2_network_probe.run_topology_probe(...) at sweep start (before warmup); inherits M6.0a-corrected concurrent dispatch from m6_1_1_sweep.py's _measure_cell pattern; emits _stderr_ts()-prefixed progress lines (porting the spike 3763687 pattern verbatim).
├── m6_1_2_reporter.py          # NEW — render_json() / render_markdown() / write_m6_1_2_report() — mirrors m6_1_1_reporter.py:407-485 but emits the new top-level network_paths + cohort_set + cohort_omissions keys per FR-003 / FR-016. Strict-superset over M6.1.1's manifest shape: every M6.1.1 top-level key is preserved verbatim and the new ones are added.
├── m6_1_2_validate.py          # NEW — entry point for --m6_1_2-validate: invokes m6_1_2_sweep.run_m6_1_2_sweep(...) at n=50 with the full M6.1.1 6-cell matrix; on completion, writes the artifact to docs/benchmarks/m6_1_2-methodology-discipline.{md,json}; returns exit code matching the CLI contract.
├── m6_1_2_network_probe.py     # NEW — owns the tcptraceroute subprocess invocation, per-cohort 30s timeout (FR-002a), parallel-across-cohorts execution (FR-001a), output parsing into M6_1_2NetworkPath dataclass, CSP attribution via AWS/Azure/GCP IP-range JSON files + ARIN whois fallback (FR-007), per-hop best-effort cloud_provider annotation (FR-003 + round-3 Q1), loud-stderr warnings for FR-005a (all-fail) + FR-006 (cohort-CSP-mismatch).
├── m6_1_rpc_driver.py          # MODIFY — add a 4th cohort dispatch path for "rest_plain_tcp" mirroring "rest_https_edge"'s shape (httpx.AsyncClient against rest_plain_tcp_url instead of rest_https_edge_url). Touches lines 305-345 (the existing 3-cohort match block). ~30-50 LOC net new.
├── __main__.py                 # MODIFY — add `--m6_1_2` + `--m6_1_2-validate` (mutually exclusive top-level mode flags per FR-026) and the 12 `--m6_1_2-*` namespaced sub-flags from FR-027. Mirrors M6.1.1's argparse pattern at lines 525-600. Wire `--m6_1_2` to `run_m6_1_2_sweep(...)` and `--m6_1_2-validate` to `run_m6_1_2_validate(...)`. Mutual-exclusion list per FR-026 (rejects against `--m6_1_1-diagnose`, `--m6_1_1`, `--m6_1`, `--m6_1-smoke`, `--m6`, `--m6-smoke`, `--m5_2`, `--m5_2-smoke`, `--m5_1`, `--m5_1-smoke`, `--m5`, `--m4`, `--m3`).
├── m6_sweep.py                 # MODIFY (already on spike branch) — _stderr_ts() helper + 3 stderr emit sites prefixed (carries forward verbatim from spike commit 3763687 per FR-021).
├── m6_1_sweep.py               # MODIFY (already on spike branch) — _stderr_ts() helper + 3 stderr emit sites prefixed (carries forward verbatim from spike commit 3763687 per FR-021).
├── m6_1_1_sweep.py             # MODIFY (already on spike branch) — _stderr_ts() helper + 4 stderr emit sites prefixed (carries forward verbatim from spike commit 3763687 per FR-021).
├── m6_1_types.py               # READ-ONLY reference — M6_1_CELLS at lines 72-82 (the canonical 6-cell matrix) is REUSED by M6_1_2; M6_1_COHORTS at lines 84-88 is the 3-cohort baseline that M6.1.2 extends to 4.
├── m6_1_1_reporter.py          # UNCHANGED — M6.1.1's reporter stays frozen so the M6.1.1 historical re-run capability (per FR-028) remains identical to what it produces today.
├── m6_1_1_sweep.py             # UNCHANGED (for the M6.1.1 path) — already on spike 3763687 for timestamp helper; the cell-iteration / cohort-iteration / classifier dispatch logic is preserved verbatim per FR-028.
├── m6_1_rpc_driver.py          # MODIFY (see above) — adds the 4th cohort dispatch path; the existing 3-cohort paths are unchanged per FR-017.
├── m5_2_sweep.py               # READ-ONLY reference — M5_2CellMeasurement at lines 241-246 + tuned-pair-collapse-at-c=1 rule at lines 228-237 is the canonical pattern M6.1.2 ports.
├── m5_2_symmetry.py            # READ-ONLY reference — NOT ported forward to M6.1.2 per the spec's out-of-scope note (prompt-symmetry is M6.1.3 phase B territory).
├── rest_cohort.py              # READ-ONLY reference (UNCHANGED) — confirmed compiling; the `rest_plain_tcp` cohort uses the existing httpx.AsyncClient code path.
└── rest_shim.py                # READ-ONLY reference (UNCHANGED) — confirmed compiling.

tools/benchmark/tests/
├── test_m6_1_2_network_probe.py        # NEW — unit tests for the probe module: CSP attribution, hop-parser, probe-timeout, probe-binary-missing.
├── test_m6_1_2_artifact_schema.py      # NEW — unit tests for the artifact-JSON additions: strict-superset compat with M6.1.1 reader; cohort_set / cohort_omissions semantics.
├── test_m6_1_2_cli.py                  # NEW — unit tests for argparse: flag presence, defaults (with verbatim-inheritance regression), mutual exclusion.
├── test_m6_1_2_progress_format.py      # NEW — unit tests for the stderr timestamp regex on progress + warning lines.
├── test_m6_1_2_smoke_validate_cli.py   # NEW — integration test: --m6_1_2-validate against a stub driver, end-to-end through the orchestrator + reporter, asserts JSON artifact contents.
└── test_m6_quickstart_format.py        # MODIFY (already on spike branch) — _strip_ts_prefix() helper + extended assertions, per spike commit 3763687.

docs/benchmarks/
├── m6_1_1-engine-cost-instrumentation.{md,json}     # READ-ONLY — M6.1.1's published baseline; consumed via --m6_1_2-m6-1-1-baseline (FR-027 default).
└── m6_1_2-methodology-discipline.{md,json}          # NEW — M6.1.2's published artifact, produced by the --m6_1_2-validate PR validation sweep (FR-029).

ANALYSIS.md                                          # MODIFY — one-line correction citing spike #1's multi-CSP finding (FR-008).
contracts/instrumentation.md                         # MODIFY (or create if absent) — document network_paths + cohort_set + cohort_omissions as part of the M6.1.2-forward artifact schema (FR-009 + FR-016).
CLAUDE.md                                            # MODIFY — update SPECKIT plan reference between markers (Phase 1 step 3 of /speckit-plan).
```

**Structure Decision**: M6.1.2 is structurally parallel to M6.1.1 — a new `m6_1_2_*` module family lands alongside the existing `m6_1_1_*` modules without modifying them. This preserves the "one mode flag per milestone" pattern (FR-026) AND keeps M6.1.1's historical re-run capability frozen (FR-028). The cell matrix is REUSED from `m6_1_types.py:72-82` (`M6_1_CELLS`) rather than redefined — M6.1.2 is not introducing a new cell shape, only adding a 4th cohort and a new probe to the same cells. The cohort iteration is the only true structural delta: M6.1.2 defines `M6_1_2_COHORTS = ("rest_https_edge", "rest_plain_tcp", "default_grpc", "tuned_grpc_multiplexed")` and replaces M6.1.1's `for cohort in M6_1_COHORTS` references with `for cohort in M6_1_2_COHORTS` in the new `m6_1_2_sweep.py`. The `m6_1_2_network_probe.py` module is the only genuinely net-new functionality (no existing project utility covers CSP IP-range attribution); the other four `m6_1_2_*` modules port + extend M6.1.1's pattern.

## Complexity Tracking

> Empty — Constitution Check passed 5/5 with no violations.

Per the project's `feedback_thorough_clarify_cycles` memory, the spec underwent 3 rounds of clarification (13 Q/A bullets total — 5 in round 1, 1 user follow-up, 5 in round 2, 2 in round 3) before this plan was written. The plan inherits those decisions verbatim. The only genuinely new architectural concept is CSP IP-range attribution (the new `m6_1_2_network_probe.py` module), and even that is bounded — public IP-range files are well-defined, the ARIN whois fallback is best-effort with no retry, and the per-hop annotation is optional per FR-003. The new external binary dependency (`tcptraceroute`) is a single-line install with a documented error-block-and-continue fallback per FR-005.

---

## Phase 0: Outline & Research

See [`research.md`](./research.md) for the research items and their decisions. All NEEDS CLARIFICATION items were resolved during the 3-round spec clarification; Phase 0 captures the implementation-level investigation (R-1 through R-8) that complements those spec-level decisions.

**Output**: `research.md` with all NEEDS CLARIFICATION resolved (none in Technical Context).

## Phase 1: Design & Contracts

See [`data-model.md`](./data-model.md), [`contracts/cli.md`](./contracts/cli.md), [`contracts/network-paths.md`](./contracts/network-paths.md), [`contracts/artifact-schema.md`](./contracts/artifact-schema.md), [`quickstart.md`](./quickstart.md).

Agent context update: the SPECKIT plan reference in `/Users/bsansom/projects/vllm-grpc/CLAUDE.md` between the `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers is updated as part of Phase 1 step 3 to point at this plan's path.

**Output**: `data-model.md`, `contracts/cli.md`, `contracts/network-paths.md`, `contracts/artifact-schema.md`, `quickstart.md`, updated `CLAUDE.md`.

## Post-Design Constitution Check

Re-evaluated against the 5 principles after Phase 1 design artifacts were drafted:

| Principle | Status | Post-design notes |
|---|---|---|
| I. Proto-First | **PASS** | Confirmed by [`contracts/cli.md`](./contracts/cli.md), [`contracts/network-paths.md`](./contracts/network-paths.md), [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) — every contract describes Python / JSON / CLI surfaces; zero `.proto` impact. The cohort restoration touches Python (`m6_1_rpc_driver.py`) + existing Modal handshake-dict keys (`rest_plain_tcp_url`, already exported pre-M6.1.2). |
| II. Library Dependency, Not Fork | **PASS** | Confirmed by [`data-model.md`](./data-model.md) — every M6.1.2 edit lands in `tools/benchmark/`. The vLLM `AsyncLLM` invocation, Modal endpoint provisioning, `provide_m6_endpoint` / `provide_m6_1_rpc_driver` factories, and the gRPC frontend are unchanged. The new `tcptraceroute` dependency is a system binary; the new IP-range attribution logic fetches public CSP-published JSON files (no fork or vendoring). |
| III. Phase Discipline | **PASS** | Confirmed by [`contracts/network-paths.md`](./contracts/network-paths.md) + [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) — the `network_paths` / `cohort_set` / `cohort_omissions` schemas exactly match what M6.1.2 needs and no more. M6.1.3 (proxy-edge probes), M6.2 (`max_tokens` axis), M7 (corpus), M8 (multi-model) functionality stays out — the schemas are forward-extensible via the same strict-superset mechanism but M6.1.2 itself adds only what its three Stories require. The default 4-cohort universe (`rest_https_edge`, `rest_plain_tcp`, `default_grpc`, `tuned_grpc_multiplexed`) is the contract's closed set; downstream cohort additions for M8 follow the same FR-016 cohort_set mechanism. |
| IV. CI is the Merge Gate | **PASS** | [`quickstart.md`](./quickstart.md) operator playbook includes the local-lint-chain step (`ruff check`, `ruff format --check`, `mypy --strict`, `pytest`) before any push per [`feedback_local_lint_chain`](../../specs/022-m6-1-real-prompt-embeds/checklists/requirements.md) memory. The new test files exercise the default-inheritance regression (CI catches silent drift on `--m6_1_2-modal-region` / `-base-seed` / `-model`) AND the integration path (`test_m6_1_2_smoke_validate_cli.py` exercises the full CLI → orchestrator → reporter path without Modal). |
| V. Honest Measurement | **PASS** | [`contracts/network-paths.md`](./contracts/network-paths.md) + [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) mandate: (a) the probe is run on every M6.1.2 sweep — no opt-out flag; (b) failure modes are recorded faithfully (`error: <reason>`) rather than dropped; (c) the FR-006 loud-stderr cohort-CSP-mismatch warning fires when topology drifts from the spike-expected pattern, surfacing methodology disruption rather than absorbing it; (d) `cohort_set` / `cohort_omissions` split distinguishes design omission from runtime failure — no narrative-massaged "cohort missing" ambiguity; (e) the smoke-equivalent validation sweep artifact (`docs/benchmarks/m6_1_2-methodology-discipline.{md,json}`) commits alongside the code change per Constitution V's "all benchmark numbers MUST be committed alongside the code". |

**Result: 5/5 PASS post-design. No new complexity introduced.**
