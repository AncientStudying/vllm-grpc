---
description: "Task list for v0.0.1 — Bench-harness refactor"
---

# Tasks: v0.0.1 — Bench-harness refactor

**Input**: Design documents from `specs/029-post-m6.2-cleanup-v0.0.1/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-surface.md, contracts/module-api.md, quickstart.md

**Tests**: No new TDD suite requested. The existing `pytest` suite is the regression gate (FR-012); test work here is **deletion** (legacy), **rename** (retained), and **new-home coverage** (FR-007, data-model Entity 8).

**Scope**: All paths under `tools/benchmark/` unless noted. `SRC = tools/benchmark/src/vllm_grpc_bench`, `TST = tools/benchmark/tests`. **Forward-only / BC-breaking** — recovery via `milestone/m*` tags.

**Gate discipline (FR-008)**: every task that changes code ends with `cd tools/benchmark && ruff check . && mypy --strict .` green before the next. Full `make lint typecheck test` at story checkpoints.

---

## Phase 1: Setup

**Purpose**: Capture the pre-refactor baseline and confirm the recovery net.

- [ ] T001 Confirm branch `chore/post-m6.2-cleanup-v0.0.1` is checked out and capture the green pre-refactor baseline: `cd tools/benchmark && make lint typecheck test` — record pass count for no-regression comparison (SC-005).
- [ ] T002 Verify the recovery net: `git tag | grep -c '^milestone/'` returns 16, and `git show milestone/m5.2-transport-tuning:tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py | head` returns content (FR-014, precondition for all deletions).
- [ ] T003 Snapshot starting counts for SC-002: record `ls $SRC/*.py | wc -l` (=84) and `ls $TST/*.py | wc -l` (=137).

**Checkpoint**: Baseline green, recovery net confirmed.

---

## Phase 2: Foundational (Generic homes — BLOCKS US1 and US2)

**Purpose**: Create the four milestone-agnostic homes with hoisted symbols. Nothing imports them yet (additive), so each lands green in isolation. Every later phase depends on these (research.md R7 step 1; data-model Entity 1).

**⚠️ CRITICAL**: No de-prefix or deletion work begins until this phase is complete.

- [ ] T004 [P] Create `$SRC/exceptions.py` with `SchemaValidationFailed` hoisted from `m5_2_regen.M5_2SchemaValidationFailed`. Gate green.
- [ ] T005 [P] Create `$SRC/timing.py` as the de-prefixed `m6_1_1_timing` (`extract_grpc_timings`, `extract_rest_timings`, `timing_checkpoint_to_payload`, `TimingCheckpoint`). Gate green.
- [ ] T006 Create `$SRC/types.py` with all hoisted types (data-model Entity 1): `CohortKind` (4-member, research.md R3), `COHORTS`, `cohorts_at_concurrency`, `CELLS`, `Cell`, `Path`, `RTTRecord`, `EndpointTuple`, `RunCohort`, `RPCResult`, `NetworkPath`, `Path_`, `RESTCohortRecord`, `RestHttpsEdgeCohortRecord`, `CloudProvider`, `NetworkPathError`, `NetworkPathHop`, `CohortOmissions` — sourced from `m3_types`/`m6_1_types`/`m6_1_2_types`/`m6_sweep`/`m6_2_types`. Gate green.
- [ ] T007 Create `$SRC/prompts.py` with the single unified seed+digest `build_chat_prompt`, `DEFAULT_CHAT_MAX_TOKENS`, and the `m6_2_prompt_source` wiring (collapsing `m3_sweep.build_chat_prompt` + `m6_rpc_driver._build_chat_prompt`, FR-003). Gate green.
- [ ] T008 Absorb `_client_kwargs` (from `m3_sweep`) into `$SRC/channel_config.py`. Gate green.

**Checkpoint**: Four homes exist and type-check; no consumer repointed yet.

---

## Phase 3: User Story 1 — Single milestone-agnostic codebase (Priority: P1) 🎯 MVP

**Goal**: The live harness imports only from generic homes / de-prefixed modules; one prompt builder, one reporter; no milestone-prefixed module name or import remains in live code.

**Independent Test**: grep live modules → zero imports of `m[0-9]` modules; `prompts.py` has one builder; one `*reporter*.py`; `make lint typecheck test` green; `python -m vllm_grpc_bench --validate --skip-deploy` completes (SC-003, SC-004, SC-006).

- [ ] T009 [US1] Repoint `$SRC/rest_cohort.py` at `prompts.build_chat_prompt` (unified) + `types`/`timing` homes; remove the M5.2 prompt path (BC break, FR-003). Gate green.
- [ ] T010 [P] [US1] Repoint `$SRC/modal_endpoint.py`, `$SRC/rtt_probe.py`, `$SRC/ttft.py`, `$SRC/symmetric_prompts.py` at `types` (and `symmetric_prompts` at the 4-member `CohortKind`). Gate green.
- [ ] T011 [US1] De-prefix `m6_2_sweep`→`$SRC/sweep.py`: rename, repoint at homes, and fold in `m6_1_seq_len.pin_seq_len_at_sweep_start` (data-model Entity 2). Gate green.
- [ ] T012 [US1] De-prefix `m6_2_rpc_driver`→`$SRC/rpc_driver.py`: rename, repoint at homes, and absorb the live helpers from `m6_rpc_driver` (`_build_chat_grpc_request`, `_build_chat_rest_payload`, `_rest_rtt_probe`) and `m6_1_rpc_driver` (`_build_embed_grpc_request`, `_build_embed_rest_payload_m6_1`, `_normalize_rest_url_for_httpx`, `_resolve_rpc_index`); import `parse_grpc_trailing_metadata`, `parse_rest_response` from the de-prefixed `engine_cost` module (T013) rather than absorbing them. Gate green.
- [ ] T013 [US1] De-prefix `m6_engine_cost`→`$SRC/engine_cost.py` (rename + repoint at homes); it is the single home for the cost parsers consumed by `rpc_driver` (no double-move into `rpc_driver`/`metrics`). Gate green.
- [ ] T014 [US1] De-prefix `m6_1_2_network_probe`→`$SRC/network_probe.py`; repoint at `types`. Gate green.
- [ ] T015 [US1] De-prefix `m6_2_validate`→`$SRC/validate.py`: rename, repoint at homes/`network_probe`/`sweep`, and **preserve the canonical/validate path constants verbatim** (`_CANONICAL_JSON/_MD`, `_VALIDATE_JSON/_MD`, FR-019, research.md R5). Gate green.
- [ ] T016 [P] [US1] De-prefix the remaining live `m6_2_*` modules → `$SRC/{resume,crossover,null_anchor,anchor_trajectory,sub_probe}.py`; repoint each at homes. Gate green.
- [ ] T017 [US1] Consolidate report generation (FR-005): replace `$SRC/reporter.py` content with the de-prefixed `m6_2_reporter`; delete the M1-era functions (`write_summary_md`, `write_cross_run_md`, `write_wire_size_comparison_md`, M1 variants) and their M1-era `m3_types` imports (research.md R4). Verify `ls $SRC/*reporter*.py | wc -l` → will be 1 after Phase 4 deletes the six `m*_reporter.py`. Gate green.
- [ ] T018 [US1] Strip the CLI in `$SRC/__main__.py` (FR-018a, contracts/cli-surface.md): remove every `--m3`…`--m6_1_3` flag group + `args.mN` dispatch branch; rename surviving `--m6_2-*`→generic; drop the `--m6_2` selector so the sweep is the default invocation. Repoint remaining imports at de-prefixed modules. Gate green.
- [ ] T019 [US1] Verify US1 invariants (contracts/module-api.md I3/I4/I5): `grep -rnE '(import|from).*\bm[0-9]' $SRC --include='*.py'` (excluding `docs/benchmarks` artifact strings) → 0 in live modules; `python -m vllm_grpc_bench --help | grep -cE '\-\-m[0-9]'` → 0; `python -m vllm_grpc_bench --validate --skip-deploy` completes; `make lint typecheck test` green.

**Checkpoint**: Live harness is milestone-agnostic and green — legacy modules still on disk but no longer imported by live code.

---

## Phase 4: User Story 2 — Legacy gone, counts hit target (Priority: P2)

**Goal**: All milestone-prefixed source modules and tests deleted; retained tests renamed; counts toward ~25 src / ~35 test.

**Independent Test**: `ls $SRC | grep -cE '^m[0-9]'` → 0; `ls $TST | grep -cE '^test_m[0-9]'` → 0; `make lint typecheck test` green (SC-001, SC-002).

- [ ] T020 [US2] `git rm` all now-orphaned legacy source modules: `$SRC/{m3_*,m4_*,m5_*,m5_1_*,m5_2_*}.py`, the `m6_*` family (`m6_sweep,m6_types,m6_reporter,m6_smoke,m6_seed,m6_supersede,m6_rpc_driver,m6_engine_cost` if fully merged), `m6_1_*`, `m6_1_1_*` (except `timing`, already moved), `m6_1_2_*` (except `network_probe`, already moved), `m6_1_3_*`. Then `mypy --strict .` confirms zero dangling imports. (SC-001 source half.)
- [ ] T021 [US2] `git rm` all legacy test files: `$TST/{test_m3_*,test_m4_*,test_m5*,test_m6_*,test_m6_1*}.py` (NOT `test_m6_2_*`). Do **not** delete `test_modal_endpoint_m5_2.py` — it covers the retained dual-transport (`with_rest_plain_tcp`) path on `modal_endpoint.py` (both `rest_plain_tcp` and `rest_https_edge` are in the kept 4-member `CohortKind`); it is renamed in T022, not deleted. Gate green.
- [ ] T022 [US2] Rename the 17 `test_m6_2_*.py` → generic names matching de-prefixed modules (`test_m6_2_sweep`→`test_sweep`, `test_m6_2_rpc_driver`→… , `test_m6_2_validate_cli`→`test_validate_cli`, `test_m6_2_cli`→`test_cli`, `test_monitor_m6_2_sweep_artifact_present`→`test_monitor_sweep_artifact_present`, …); also rename `test_modal_endpoint_m5_2.py`→`test_modal_endpoint_dual_transport.py` (milestone label dropped, coverage kept — confirm its dual-transport assertions still pass). Repoint all imports at the de-prefixed modules/homes. Gate green.
- [ ] T023 [P] [US2] Add new-home test coverage: `$TST/test_types.py`, `test_prompts.py`, `test_timing.py`, `test_exceptions.py` (data-model Entity 8) — at minimum assert `CohortKind` has 4 members, the unified builder is deterministic, and `SchemaValidationFailed` raises. Gate green.
- [ ] T024 [US2] Verify SC-001/SC-002: `ls $SRC/*.py | grep -cE '/m[0-9]'` → 0; `ls $TST/*.py | grep -cE '/test_m[0-9]'` → 0; record final `ls $SRC/*.py | wc -l` (~25–28) and `ls $TST/*.py | wc -l` (~35–37) against T003; `make lint typecheck test` green.

**Checkpoint**: Zero milestone-prefixed modules/tests; suite green; counts recorded.

---

## Phase 5: User Story 3 — Recoverability + documentation (Priority: P3)

**Goal**: The BC breaks are documented and the tag recovery path is verified intact.

**Independent Test**: `git show milestone/m5.2-transport-tuning:…m5_2_sweep.py` returns content; ANALYSIS.md has the refactor subsection; preserved artifacts resolve (SC-007, SC-008, SC-010).

- [ ] T025 [US3] Document the refactor in two places (FR-015 + constitution ADR requirement): (a) add the "Bench-harness refactor (v0.0.1)" subsection to `ANALYSIS.md` — summary, BC breaks (renamed modules, unified prompt format, dropped `tuned_grpc_channels`/`tuned_grpc` cohort members, flat CLI), and the `milestone/m*` tag recovery path; (b) author `docs/decisions/0006-bench-harness-refactor.md` (ADR) recording the non-obvious architectural choices — the three-disposition model (de-prefix / hoist-then-delete / delete), the 4-member `CohortKind` collapse, the reporter consolidation, the forward-only / no-BC-shims policy, and the data-pointer-preservation rule — citing `research.md` for detail (constitution Development Workflow: ADR MUST for non-obvious choices).
- [ ] T026 [P] [US3] Verify SC-010 preserved data pointers: `ls docs/benchmarks/m6_2-token-budget.json docs/benchmarks/m6_2-token-budget.md docs/benchmarks/m6_1_3-attribution-closure.json` all exist; grep `ANALYSIS.md` benchmark-artifact links all resolve to existing files.
- [ ] T027 [P] [US3] Verify SC-007 recoverability: `git show milestone/m5.2-transport-tuning:tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py | head` returns the legacy harness; confirm the M5.2 6-member cohort enum + M5.2 prompt builder are present at that tag.

**Checkpoint**: Recovery path proven; BC breaks documented.

---

## Phase 6: Polish & Cross-Cutting

**Purpose**: Final audits, gate, and ship.

- [ ] T028 [P] Resolve the research.md R2 audit items: decide keep-and-de-prefix vs delete for `m6_1_torch_pin` (does `validate`/`sweep` need the torch gate?), `compare.py`, `ci.py` (does a surviving CLI path use them?). Apply the decision; gate green.
- [ ] T029 [P] Evaluate the SC-002 thin-module merge candidates (`symmetric_prompts`→`prompts`, `ttft`→`metrics`) and merge **only** where cohesion improves (no contrived merges — SC-002 directional). (`engine_cost` is its own home per T013 — not a merge candidate.) Gate green.
- [ ] T030 Final full gate (FR-012): `cd tools/benchmark && make lint typecheck test` green with no new suppressions vs the T001 baseline; `python -m vllm_grpc_bench --validate --skip-deploy` completes; verify FR-018 scope — `git diff --name-only main...HEAD | grep -vE '^(tools/benchmark/|docs/benchmarks/|ANALYSIS\.md|docs/decisions/|specs/029-)'` returns empty (no `.proto`/`vllm`/`packages/*`/other-`specs` edits); run `graphify update .` from repo root (constitution Development Workflow).
- [ ] T031 Push branch and open PR (FR-017): `git push -u origin chore/post-m6.2-cleanup-v0.0.1`; `gh pr create --base main --title "v0.0.1 — Bench-harness refactor"` with a body listing the BC-break ledger (module renames, unified prompt, dropped cohort members, flat CLI) and the tag recovery path.
- [ ] T032 **[POST-MERGE]** After merge: `git switch main && git pull`; create + push the annotated tag `git tag -a v0.0.1 -m "v0.0.1 — bench-harness refactor"` && `git push origin v0.0.1` (FR-014, SC-008).

---

## Dependencies & Execution Order

- **Phase 1 (Setup)** → **Phase 2 (Foundational homes)** → **Phase 3 (US1)** → **Phase 4 (US2)** → **Phase 5 (US3)** → **Phase 6 (Polish)**.
- **Hard ordering**: homes (T004–T008) before any repoint/de-prefix (T009–T018); all live code de-prefixed/repointed (US1) before any legacy deletion (T020) — deleting earlier breaks live imports.
- **US3 + most of Polish** can begin once US2's T024 is green.

## Parallel Opportunities

- **T004, T005** parallel (independent new files); **T006, T007** serialize lightly (T007 may reference `types`).
- **T010** (shared-infra repoint, distinct files) and **T016** (independent `m6_2_*` leaf modules) are `[P]`.
- **T023** (new-home tests) parallel with T022 rename once modules exist.
- **T026, T027** (verification-only) and **T028, T029** (independent audits) are `[P]`.

## Implementation Strategy

- **MVP = Phase 1 + 2 + 3 (US1)**: a milestone-agnostic, green live harness — delivers the core value (de-tangled forward codebase) even before deletion.
- **Incremental**: US2 (deletion + counts) is the headline reduction; US3 (docs/recovery) and Polish (audits, ship) follow.
- Keep every commit bisectable and green (FR-008); one logical commit per task or small `[P]` batch, matching quickstart.md Steps 1–9.

## Notes

- Task count: **32** (vs the PLAN's ~17 estimate — the gap is the folded-in de-prefix + reporter/CLI consolidation, per clarify Q3/Q4/Q5).
- Per US1/US2/US3: US1 = 11 tasks (T009–T019), US2 = 5 (T020–T024), US3 = 3 (T025–T027); Setup 3, Foundational 5, Polish 5.
- The `docs/benchmarks/*` artifact path strings inside `validate.py` and the sweep baseline defaults are **not** milestone-prefixed *imports* and must survive the T019/T020 grep checks (FR-019) — exclude them when asserting "zero `m[0-9]` references."
