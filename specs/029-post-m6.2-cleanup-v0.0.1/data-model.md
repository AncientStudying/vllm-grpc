# Phase 1 Data Model: v0.0.1 — Bench-harness refactor

The "entities" of a refactor are **modules**, **symbols**, **tests**, **CLI flags**, and **preserved data pointers**. This file is the authoritative map `/speckit-tasks` decomposes.

## Entity 1 — Generic home modules (created; FR-001)

| Module | Owns (hoisted symbols) | Sources |
|---|---|---|
| `types.py` | `CohortKind` (4-member, FR R3), `COHORTS`, `cohorts_at_concurrency`, `CELLS`, `Cell`, `Path`, `RTTRecord`, `EndpointTuple`, `RunCohort`, `RPCResult`, `NetworkPath`, `Path_`, `RESTCohortRecord`, `RestHttpsEdgeCohortRecord`, `CloudProvider`, `NetworkPathError`, `NetworkPathHop`, `CohortOmissions` | `m3_types`, `m6_1_types`, `m6_1_2_types`, `m6_sweep`, `m6_2_types` |
| `prompts.py` | `DEFAULT_CHAT_MAX_TOKENS`, `build_chat_prompt` (unified seed+digest), prompt-source wiring | `m3_sweep`, `m6_rpc_driver._build_chat_prompt`, `m6_2_prompt_source` |
| `timing.py` | `extract_grpc_timings`, `extract_rest_timings`, `timing_checkpoint_to_payload`, `TimingCheckpoint` | de-prefixed `m6_1_1_timing` |
| `exceptions.py` | `SchemaValidationFailed` | `m5_2_regen.M5_2SchemaValidationFailed` |

**Validation rules**: every home is `mypy --strict` clean; no home imports any milestone-prefixed module; `CohortKind` has exactly 4 members (SC-003).

## Entity 2 — De-prefixed live modules (renamed; FR-004)

| From (legacy name) | To (generic name) | Absorbs |
|---|---|---|
| `m6_2_sweep.py` | `sweep.py` | — (seq_len NOT absorbed: `m6_2_sweep` never called `pin_seq_len_at_sweep_start`; see `seq_len.py` row — corrected during T011) |
| `m6_1_seq_len.py` | `seq_len.py` | — (own cohesive home; live caller is `validate.py`, not `sweep.py`) |
| `m6_2_rpc_driver.py` | `rpc_driver.py` | live helpers of `m6_rpc_driver`, `m6_1_rpc_driver` + transitively the embed seed/tensor helpers `build_torch_save_bytes`/`build_torch_generator_for_rpc` from `m6_1_seed` (T012 discovery — absorbed as private `_`-prefixed; `m6_1_seed`'s remaining symbols have no live consumers → that module is deleted in T020, no separate home) |
| `m6_2_validate.py` | `validate.py` | — (canonical-path constants preserved, Entity 5) |
| `m6_2_resume.py` | `resume.py` | — |
| `m6_2_crossover.py` | `crossover.py` | — |
| `m6_2_null_anchor.py` | `null_anchor.py` | — |
| `m6_2_anchor_trajectory.py` | `anchor_trajectory.py` | — |
| `m6_2_sub_probe.py` | `sub_probe.py` | — |
| `m6_2_types.py` | `sweep_types.py` | — (own sweep-domain types home — T015pre; cohort/cloud symbols alias from `types`, network-probe dataclasses → `network_probe` in T014) |
| `m6_2_prompt_source.py` | `prompts.py` (**merged**) | resolver + corpus loaders folded into the prompt home — T015pre; module deleted, count 88→87 |
| `m6_1_1_timing.py` | `timing.py` | (= Entity 1 timing home) |
| `m6_1_2_network_probe.py` | `network_probe.py` | — (T014: repointed at `types` home; the 3 network-probe dataclasses `M6_1_2NetworkPath`/`Hop`/`Error` are **re-exported by the `types` home** facade — defs stay in `m6_1_2_types` until Phase 4, RPCResult pattern — rather than network_probe-owned, to keep the module a cycle-free leaf consumer; resolves the T006 deferral note in favor of data-model Entity 1) |
| `m6_engine_cost.py` | `engine_cost.py` | single de-prefixed home for cost parsers (imported by `rpc_driver`; not a merge candidate) |

## Entity 3 — Retained shared infra (repointed at homes)

`__init__.py`, `__main__.py` (CLI stripped — Entity 6), `runner.py`, `metrics.py`, `reporter.py` (consolidated — Entity 4), `modal_endpoint.py`, `rest_cohort.py`, `rest_shim.py`, `channel_config.py` (absorbs `_client_kwargs`), `corpus.py`, `mock_engine.py`, `fake_server.py`, `io.py`, `rtt_probe.py`.

**Merge candidates** (merge only where cohesion improves — SC-002 directional, not forced): `symmetric_prompts.py`→`prompts.py`; `ttft.py`→`metrics.py` (tiny). (`engine_cost.py` is its own de-prefixed home, not a merge candidate.) **Audit-then-decide**: `compare.py`, `ci.py`, `m6_1_torch_pin` (keep+de-prefix if a surviving path uses them, else delete — research.md R2 open item).

## Entity 4 — Reporter consolidation (FR-005)

| Action | Detail |
|---|---|
| Keep name | `reporter.py` |
| New content | de-prefixed `m6_2_reporter` builders |
| Delete | M1-era `reporter.py` functions (`write_summary_md`, `write_cross_run_md`, `write_wire_size_comparison_md`, M1 `write_json`/`write_csv` variants) + their M1-era `m3_types` imports |
| Delete (modules) | `m6_reporter`, `m6_1_reporter`, `m6_1_1_reporter`, `m6_1_2_reporter`, `m6_1_3_reporter` |
| Invariant | exactly one report-generation module remains (SC-003) |

## Entity 5 — Preserved data pointers (MUST NOT change; FR-019)

| Pointer | Where | Why preserved |
|---|---|---|
| `docs/benchmarks/m6_1_3-attribution-closure.json` (+ M3→M6.1.x chain) | sweep baseline-input defaults | other milestones' frozen outputs; re-target = M7 scope |
| `docs/benchmarks/m6_2-token-budget.{json,md}` | published deliverable on disk | ANALYSIS-linked; frozen |
| `_CANONICAL_JSON/_CANONICAL_MD`, `_VALIDATE_JSON/_VALIDATE_MD` | `validate.py` constants | `validate` compares against the canonical file |

## Entity 6 — CLI flag surface (FR-018a; full table in contracts/cli-surface.md)

| Class | Action |
|---|---|
| `--m3 … --m6_1_3` flag groups + dispatch | **remove** (call deleted code) |
| `--m6_2` selector | **drop** (sweep becomes default invocation) |
| `--m6_2-<x>` operator flags | **rename** → `--<x>` |
| Invariant | `--help` shows zero milestone-prefixed flags (SC-009) |

## Entity 7 — Deleted legacy modules (zero live importers)

All `m4_*`, `m5_*`, `m5_1_*`, `m5_2_*` (after `m5_2_regen` symbol hoist), `m6_reporter/smoke/seed/supersede/types/rpc_driver` (after helper extraction), `m6_1_*` (after `m6_1_types`/`m6_1_rpc_driver`/`m6_1_seq_len` extraction), `m6_1_1_*` (except `timing`), `m6_1_2_*` (except `network_probe`), `m6_1_3_*`, `m3_types`/`m3_sweep`/`m6_sweep` (after hoist). **Target: zero milestone-prefixed source modules** (SC-001).

## Entity 8 — Test files (delete legacy / rename retained; FR-007)

| Class | Count (today) | Action |
|---|---|---|
| `test_m6_2_*.py` | 17 | **rename** to match de-prefixed modules (`test_m6_2_sweep`→`test_sweep`, `test_m6_2_validate_cli`→`test_validate_cli`, …) |
| non-milestone-prefixed (`test_runner`, `test_metrics`, `test_corpus`, `test_modal_endpoint`, `test_reporter`, `test_rtt_probe`, `test_rest_cohort`, …) | 20 | **retain**; repoint imports at homes; add `test_types`/`test_prompts`/`test_timing`/`test_exceptions` coverage for the new homes |
| `test_m3_*`, `test_m4_*`, `test_m5*`, `test_m6_*`, `test_m6_1*` (non-m6_2) | ~100 | **delete** (cover deleted code) |
| Invariant | zero milestone-prefixed test files (SC-001); count lands ~35–37 |

## Relationships / ordering

`types.py`,`prompts.py`,`timing.py`,`exceptions.py` (Entity 1) have **no inbound** legacy deps → created first. De-prefixed modules (Entity 2) depend on Entity 1 → second. Reporter consolidation (Entity 4) depends on Entity 1/2 → third. CLI strip (Entity 6) depends on de-prefixed modules existing → fourth. Legacy deletion (Entity 7) + test rename (Entity 8) require zero remaining importers → last. (Matches research.md R7.)
