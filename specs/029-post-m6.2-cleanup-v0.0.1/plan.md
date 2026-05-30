# Implementation Plan: v0.0.1 — Bench-harness refactor

**Branch**: `chore/post-m6.2-cleanup-v0.0.1` (spec slot `029-post-m6.2-cleanup-v0.0.1`)
**Date**: 2026-05-29
**Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/029-post-m6.2-cleanup-v0.0.1/spec.md`

## Summary

Collapse the bench harness under `tools/benchmark/src/vllm_grpc_bench/` (84 source modules / 137 test files) into a single milestone-agnostic, forward-only codebase, landing in the ~25-module / ~35-test direction. The operation is a **structural refactor** scoped entirely to `tools/benchmark/` — no `.proto`, `vllm`-dependency, `packages/`, `proxy`, or `frontend` changes. Backward compatibility is broken deliberately (module names, import paths, CLI flags, the REST-cohort prompt bytes); the recovery path for everything removed or changed is the corresponding `milestone/m*` annotated tag (all 16 present on origin since `v0.0.0`).

**Approach** — driven by a complete live→legacy import map (Phase 0). Every legacy module is assigned one of three dispositions:

1. **De-prefix** (rename milestone→generic; the module is live forward code): the 8 non-type `m6_2_*` modules (`m6_2_sweep`→`sweep`, etc.) plus three mostly-live legacy helpers (`m6_1_1_timing`→`timing`, `m6_1_2_network_probe`→`network_probe`, `m6_engine_cost`→`engine_cost`).
2. **Hoist-then-delete** (legacy module, a few live symbols): `m3_types`, `m3_sweep`, `m6_1_types`, `m6_1_2_types`, `m6_sweep`, `m5_2_regen`, and the live helper functions inside `m6_rpc_driver` / `m6_1_rpc_driver` / `m6_1_seq_len`. Live symbols move into the four generic homes (`types.py`, `prompts.py`, `timing.py`, `exceptions.py`) or the de-prefixed `rpc_driver.py`/`sweep.py`; the rest of the module is deleted.
3. **Delete outright** (pure legacy, zero live importers): `m4_*`, `m5_*`, `m5_1_*`, `m5_2_*` (minus the one hoisted exception), the `m6_*` reporting/smoke/supersede/types family, and the entire `m6_1_*` / `m6_1_1_*` / `m6_1_2_*` / `m6_1_3_*` set — plus all their tests.

Three consolidations ride along: the seven report generators → one `reporter.py` (M1-era reporter content deleted, M6.2 reporter content de-prefixed in); the two chat-prompt builders → one seed+digest builder in `prompts.py` (`rest_cohort` repointed; M5.2 format dropped); the milestone CLI surface → a flat de-prefixed surface (all `--mN` flags and dispatch removed; `--m6_2-*` → generic; `--m6_2` selector dropped so the sweep is the default invocation). **Data pointers stay milestone-named** (FR-019): baseline-chain inputs, the published `m6_2-token-budget.{json,md}` deliverable, and `validate`'s hardcoded canonical-path constants — because re-targeting the harness to a new milestone is M7 work, out of scope here.

Ships as one PR with bisectable commits in dependency order (hoist homes → unify prompt → de-prefix/merge live modules → consolidate reporter → strip CLI → delete legacy + rename tests → docs + tag), each leaving `ruff` + `mypy --strict` green.

## Technical Context

**Language/Version**: Python 3.12 (per `tools/benchmark/pyproject.toml`).
**Primary Dependencies**: No new dependencies. Existing harness deps unchanged (`grpcio`, `httpx`, `torch` for local drivers, `modal` for deploys). No `vllm` import surface change.
**Storage**: Filesystem + git object database. The `docs/benchmarks/` data artifacts are read (baseline inputs) and their names preserved; no new data store.
**Testing**: `make lint typecheck test` (the existing CI gate — `ruff`, `mypy --strict`, `pytest`). The fake-backed validate smoke is the end-to-end gate: `python -m vllm_grpc_bench.validate` (de-prefixed from `--m6_2-validate --m6_2-skip-deploy`), covered by the renamed `test_validate_cli.py` (formerly `test_m6_2_validate_cli.py`).
**Target Platform**: Developer workstation (macOS/Linux); CI runners (Linux). No runtime/service platform impact.
**Project Type**: Internal benchmark tooling refactor (`v*` semver track, codebase-state beat).
**Performance Goals**: One-shot refactor; success is measured in invariants, not service latency. No measured-behavior change to the sweep (FR-011): sweep methodology, metric definitions, and report data shape are preserved.
**Constraints**:
  - Scope confined to `tools/benchmark/` — no `.proto`/`vllm`/`packages/`/`proxy`/`frontend` edits (FR-018).
  - No backward-compat shims, aliases, or re-export stubs (FR-009); recovery is via tags only.
  - `mypy --strict` + `ruff` green after **each** module-level step — bisectable (FR-008, FR-012).
  - Data pointers (baseline inputs, canonical deliverable, validate constants) preserved verbatim (FR-019).
  - No live import of a milestone-prefixed module, and no milestone-prefixed module/test name, on the final branch (FR-010, SC-001).
**Scale/Scope**: From **84 src modules / 137 test files** → ~25–28 src / ~35–37 test (directional; SC-002 is invariant-gated). Concretely: ~55 legacy modules removed or merged, 4 generic homes created, 11 modules de-prefixed, 17 `m6_2_*` tests + 20 shared tests renamed/retained, ~117 legacy test files deleted, ~30 legacy CLI flag groups removed.

No `NEEDS CLARIFICATION` items remain — all resolved across the spec's two `## Clarifications` sessions (7 Q&A). The Phase 0 import map (below) resolves the spec's three deferred plan-level items (full hoist set, shared-module disposition, de-prefix/rename map).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| **I. Proto-First** | N/A | No `.proto` edits; no generated-stub changes. The harness consumes already-generated stubs unchanged. |
| **II. Library Dependency, Not Fork** | N/A | No `vllm` source touched; no dependency pin change. |
| **III. Phase Discipline** | **PASS** | `v0.0.1` is the canonical bench-harness-refactor beat per `docs/PLAN.md` § "v0.0.1 — Bench-harness refactor (planned)". No `v0.1.0` (PyPI) or M7/M8 (corpus/model) work leaks in — FR-018 forbids `packages/*` and out-of-`tools/benchmark` edits; FR-019 explicitly defers harness re-targeting to M7. The aggressive de-prefix/consolidation is *within* the v0.0.1 deliverable (the PLAN's ~25-module target requires it). |
| **IV. CI is the Merge Gate** | **PASS** | FR-012 keeps all three gates (lint, type-check, tests) green with no suppressions; FR-008 enforces green-after-each-step so no commit breaks the gate. Deleting legacy tests does not weaken the gate — the deleted tests cover deleted code; retained tests are renamed, not dropped. |
| **V. Honest Measurement** | **PASS** | FR-011 preserves sweep methodology, metric definitions, and report data shape; FR-019 preserves every benchmark data artifact filename and baseline-chain input on disk. No measurement is lost or altered — only the code that produces it is reorganized, and the old harness stays reachable via tags. |

**Quality Standards check**: `mypy --strict` is already the harness gate (FR-012); the refactor keeps every retained module strict-clean. Translation-logic unit tests (JSON↔proto) live in the retained `test_chat_*`/`test_completions_*`/`test_grpc_client` integration tests outside `tools/benchmark/` and are untouched. No new RPC is added.

**Post-Phase 1 re-check**: Re-evaluated after design artifacts written — no new violations. PASS (see § Post-Design Constitution Re-Check).

## Project Structure

### Documentation (this feature)

```text
specs/029-post-m6.2-cleanup-v0.0.1/
├── spec.md              # /speckit-specify + 2× /speckit-clarify output
├── plan.md              # This file (/speckit-plan output)
├── research.md          # Phase 0 — legacy-module disposition table, hoist map, CLI rename, BC-break ledger
├── data-model.md        # Phase 1 — module/symbol entities: generic homes, de-prefix map, delete list, test rename map
├── quickstart.md        # Phase 1 — operator runbook: ordered refactor steps + per-step verification
├── contracts/
│   ├── cli-surface.md   # The de-prefixed CLI contract (flag rename table, removed flags, default invocation)
│   └── module-api.md    # The post-refactor package layout + generic-home public symbols
├── checklists/
│   └── requirements.md  # /speckit-specify quality checklist (already present)
└── tasks.md             # /speckit-tasks output (NOT created here)
```

### Source Code (repository root)

```text
tools/benchmark/
├── src/vllm_grpc_bench/
│   ├── __init__.py            # retained
│   ├── __main__.py            # CLI stripped to the de-prefixed sweep surface (FR-018a)
│   │   # ── generic homes (FR-001) ──
│   ├── types.py               # NEW: CohortKind(4), COHORTS, CELLS, Cell, Path, RTTRecord,
│   │                          #      EndpointTuple, RunCohort, RPCResult, network-path types, …
│   ├── prompts.py             # NEW: unified seed+digest chat builder, DEFAULT_CHAT_MAX_TOKENS
│   │                          #      (absorbs m6_2_prompt_source; symmetric_prompts merge candidate)
│   ├── timing.py              # de-prefixed m6_1_1_timing (extract_grpc/rest_timings, …)
│   ├── exceptions.py          # NEW: SchemaValidationFailed (from m5_2_regen)
│   │   # ── de-prefixed live sweep code (FR-004) ──
│   ├── sweep.py               # ← m6_2_sweep (+ m6_1_seq_len merge candidate)
│   ├── rpc_driver.py          # ← m6_2_rpc_driver (+ live helpers from m6_rpc_driver, m6_1_rpc_driver)
│   ├── validate.py            # ← m6_2_validate (canonical-path constants PRESERVED, FR-019)
│   ├── resume.py crossover.py null_anchor.py anchor_trajectory.py sub_probe.py  # ← m6_2_*
│   ├── engine_cost.py         # ← m6_engine_cost (single home for cost parsers; not merged)
│   ├── network_probe.py       # ← m6_1_2_network_probe
│   │   # ── retained shared infra (some merge candidates) ──
│   ├── reporter.py            # CONSOLIDATED: M6.2 reporter content; M1-era reporter deleted (FR-005)
│   ├── runner.py metrics.py modal_endpoint.py rest_cohort.py rest_shim.py
│   ├── channel_config.py      # (absorbs _client_kwargs from m3_sweep)
│   ├── corpus.py mock_engine.py fake_server.py io.py ci.py compare.py rtt_probe.py
│   └── ttft.py symmetric_prompts.py   # merge candidates (→ metrics / prompts)
│   #   DELETED: m3_*, m4_*, m5_*, m5_1_*, m5_2_*, m6_(sweep|types|reporter|smoke|seed|
│   #            supersede|rpc_driver), m6_1_*, m6_1_1_*, m6_1_2_*, m6_1_3_*
└── tests/
    ├── conftest.py
    ├── test_sweep.py test_rpc_driver.py test_validate.py test_reporter.py …  # renamed from test_m6_2_*
    ├── test_types.py test_prompts.py test_timing.py test_exceptions.py        # new-home coverage
    ├── test_runner.py test_metrics.py test_corpus.py test_modal_endpoint.py … # retained shared
    #   DELETED: test_m3_*, test_m4_*, test_m5*, test_m6_*, test_m6_1*…(non-m6_2)
```

**Structure Decision**: Single-package internal tool. The refactor reorganizes `tools/benchmark/src/vllm_grpc_bench/` in place; no new package or directory is introduced. Generic homes sit alongside de-prefixed live modules and retained shared infra. Data artifacts under `docs/benchmarks/` are read but not renamed (FR-019).

## Complexity Tracking

> No constitution violations — this section is intentionally empty. The aggressive scope (de-prefix + consolidation beyond a literal hoist-and-delete) is not a complexity violation: it is the depth the PLAN's stated ~25-module target requires, and it *reduces* complexity (fewer modules, one reporter, one builder, no milestone strata).

## Post-Design Constitution Re-Check

Re-evaluated after Phase 1 artifacts (research.md, data-model.md, contracts/, quickstart.md):

- **III Phase Discipline** — still PASS: the disposition table (research.md) confirms every change lands inside `tools/benchmark/`; the only `docs/` edits are `ANALYSIS.md` (FR-015, required output), a new ADR under `docs/decisions/` (FR-015 / constitution Development Workflow), and preserved benchmark artifacts (FR-019). No M7 re-targeting performed.
- **IV CI is the Merge Gate** — still PASS: the per-step bisectable sequence (quickstart.md) keeps `mypy --strict` + `ruff` + `pytest` green at every commit; the test rename map (data-model.md) preserves coverage of all retained code.
- **V Honest Measurement** — still PASS: data-model.md's "preserved data pointers" entity confirms no artifact filename or baseline input changes.

No new violations. Gate holds.
