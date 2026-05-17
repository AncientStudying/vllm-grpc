# Implementation Plan: M6.0a — Concurrent Dispatch Restoration

**Branch**: `024-m6-0a-concurrent-dispatch` | **Date**: 2026-05-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/024-m6-0a-concurrent-dispatch/spec.md`

## Summary

Restore real `asyncio.gather`-based concurrent in-flight dispatch to the M6 / M6.1 / M6.1.1 benchmark harness, which silently inherited M5.x's cell × cohort × concurrency matrix but dropped the per-cohort concurrent-worker pattern in favour of a sequential `await` loop. Under sequential dispatch, the harness at `c=4` or `c=8` only ever has one RPC in-flight, so the M6.1.1 FR-010 classifier — which tests for engine continuous-batching effects that presuppose overlapping requests — cannot mechanistically distinguish channel-dependent batching from chronological state drift. This was discovered during M6.1.1's first live Phase 1 run (2026-05-16) and blocks closure of M6.1.1's PR #27.

**Two-PR sequence (FR-018).** PR-1 ships the harness-only dispatch fix to five measurement / warmup entry points (`m6_sweep._run_warmup` + `_run_measurement`, `m6_1_sweep._run_warmup_m6_1` + `_run_measurement_m6_1`, `m6_1_1_sweep._measure_cell`) plus a path-agnostic Semaphore-counting regression test (`tests/test_m6_concurrent_dispatch.py`). PR-1 unblocks M6.1.1's PR #27 the moment it merges. PR-2 ships the corrected-dispatch artifact (`docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}` with a new `dispatch_mode: concurrent` strict-superset key per FR-007) and the dispatch-correction note (`docs/benchmarks/m6_0a-dispatch-correction.md` per FR-012/FR-013) after the Modal re-run completes.

**Technical approach (PR-1).** Port M5.1's canonical concurrent-dispatch pattern (`m5_1_grpc_cohort.run_grpc_cohort:387`) into M6.x's measurement loops. The pattern within a single cell is: **across cohorts → sequential; within a cohort → c-concurrent**. This matches M5.1's documented "in series" cohort orchestration (`m5_1_sweep.py:246` comment) and the spec's Acceptance Scenario 1.1 ("peak observed concurrent driver entries equals 4"). Concretely:

1. **M6 / M6.1 c-batch path** — preserve the round-robin per-c-batch index allocator (`compute_rpc_seed(idx, base_seed)` cohort-symmetric mapping is the entire reason for this structure — FR-002 / FR-025 in M6's spec). Replace `for idx in batch_indices: await driver(...)` with `await asyncio.gather(*(_one(cohort, idx) for idx in batch_indices))` *inside* the existing `for size in sizes: for cohort in cohorts` outer loop. Net effect: size=c → c concurrent per (cohort, c-batch) pair; cohort iteration stays sequential.
2. **M6.1.1 `_measure_cell` path** — M6.1.1 uses a simpler `seed = base_seed + i` mapping and no c-batch chunking. Switch to `asyncio.Semaphore(c)`-bounded `asyncio.gather` over the full `n_measurement` index range, per cohort, so the engine sees a steady c-in-flight stream rather than burst-then-drain c-batch waves. This matches M5.1's `_worker()` + queue pattern (`m5_1_grpc_cohort.py:407`).
3. **Warmup symmetry (FR-005a)** — port the same pattern into `_run_warmup` / `_run_warmup_m6_1` and M6.1.1's `_measure_cell` warmup loop. Each warmup RPC keeps its existing inner retry-until-success loop; only the *outer* "fire N warmup RPCs per cohort" loop becomes concurrent.

**Determinism preservation (FR-002).** `compute_rpc_seed(idx, base_seed)` (M6 / M6.1) and `seed = base_seed + i` (M6.1.1) are both pure functions of `(idx, base_seed)` — no async-ordering coupling. The regression test exercises seed-stability indirectly through the `c=1` no-regression case (Acceptance Scenario 1.3); seeds for the `c=1` path under the corrected harness must equal seeds the pre-fix harness emitted. The retry policy (`_run_one_rpc_with_retry` and the warmup inner-retry-loop) is unchanged — concurrent dispatch is purely a structural change to the dispatch step (Edge Case: "What if a single RPC in a concurrent batch fails partway?").

**Technical approach (PR-2).** After PR-1 lands and propagates to `main`, the operator pins `uv sync --frozen` against the audit-baseline lockfile resolution at commit `b63947a` (FR-008 version-pin parity), then runs `python -m vllm_grpc_bench --m6_1_1-diagnose --m6_1_1-modal-region=eu-west-1` against Modal A10G `eu-west-1`. The existing M6.1.1 sweep wiring (`M6_1_1ProgressReporter`, `_default_write_report`, `_sanitize_for_json` — all already landed on `023-m6-1-1-engine-cost-instrumentation`) handles artifact emission. M6.1.1's reporter (`m6_1_1_reporter.py:_sanitize_for_json`) is extended to inject a new top-level `dispatch_mode: concurrent` key on every emitted manifest (FR-007 strict-superset — no schema version bump). The dispatch-correction note (`docs/benchmarks/m6_0a-dispatch-correction.md`) is hand-authored from PR-2 review against the side-by-side per-cohort spread comparison (audit baseline vs corrected run, per FR-009 + FR-012).

## Technical Context

**Language/Version**: Python 3.12 (project standard; matches M5.x / M6 / M6.1 / M6.1.1 harness, frontend, proxy, and Modal app).

**Primary Dependencies**:

- `vllm==0.20.1` (UNCHANGED from audit baseline — FR-008 version-pin parity).
- `torch==2.11.0` client-side pin (UNCHANGED from audit baseline — FR-008).
- `grpcio` + `grpcio-tools` (UNCHANGED — pinned via `uv sync --frozen` against `b63947a` lockfile).
- `FastAPI` + `uvicorn` (UNCHANGED).
- `modal` (UNCHANGED).
- Existing `vllm_grpc_bench` harness (modifies 5 dispatch entry points across `m6_sweep.py`, `m6_1_sweep.py`, `m6_1_1_sweep.py`; reuses `m6_1_seed`, `m6_1_seq_len`, `m6_1_torch_pin`, `m6_engine_cost`, `m6_1_1_*` modules unchanged).
- `vllm_grpc_frontend` (UNCHANGED — FR-014: harness-only fix, no engine / endpoint / model changes).

**Storage**:

- Outputs (PR-2): `docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}` — NEW corrected-dispatch artifact with `dispatch_mode: concurrent` annotation (FR-007 / FR-009).
- Outputs (PR-2): `docs/benchmarks/m6_0a-dispatch-correction.md` — NEW dispatch-correction note (FR-012 / FR-013).
- Inputs: `docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md` — READ-ONLY audit baseline preserved verbatim per FR-011 (committed at `b63947a`).
- Additive annotation (PR-2): `docs/benchmarks/m6_1-real-prompt-embeds.md` picks up a methodology-supersedence cross-link in the per-cohort drift section (FR-016).
- Lockfile dependency: `uv.lock` at commit `b63947a` is the version-pin reference (FR-008).

**Testing**: `pytest` + `pytest-asyncio` (project convention). Coverage tiers:

- **Unit / regression tests (PR-1)** — `tools/benchmark/tests/test_m6_concurrent_dispatch.py`:
  - Path-agnostic `_ConcurrencyProbe` fake driver (asyncio.Semaphore-style in-flight counter) wraps the driver signature `(cohort, cell, seed) -> RPCResult`.
  - Parametrised over `concurrency ∈ {1, 4, 8}` × measurement-loop entry-point `∈ {_run_measurement (m6), _run_measurement_m6_1 (m6_1), _measure_cell (m6_1_1)}`.
  - Each test asserts `probe.peak == concurrency` after exercising the loop (FR-003 + Acceptance Scenarios 1.1 / 1.2 / 1.3).
  - One additional test exercises the warmup variants (`_run_warmup`, `_run_warmup_m6_1`, `_measure_cell` warmup loop) at `c=4` to verify FR-005a warmup symmetry.
  - One seed-determinism test exercises `c=1` and `c=4` end-to-end, comparing the set of `(cohort, idx, seed)` triples recorded by the probe against the pre-fix harness's deterministic seed sequence (FR-002 + Acceptance Scenario 1.4).
- **CI gate (FR-004)** — the new tests run in the same `pytest` invocation as the existing M6.1.1 test suite; failure blocks the M6.1.1 PR #27 merge gate.

**Target Platform**:

- **PR-1 (code change)**: operator workstation only — no Modal compute.
- **PR-2 (corrected-dispatch re-run)**: Modal A10G GPU instance in `eu-west-1` (matches audit baseline per FR-008). Driven from operator workstation; client requires `torch==2.11.0` (FR-008 audit-baseline pin).

**Project Type**: Sibling library + benchmark harness — Python monorepo with `proxy/`, `frontend/`, `client/`, `proto/`, `tools/benchmark/`, `scripts/`, `docs/benchmarks/`. M6.0a is a methodology-correction sub-milestone (corrective to M6 / M6.1 / M6.1.1 harness), not a library / CLI / web-service in the conventional product sense.

**Performance Goals**:

- SC-001: `_ConcurrencyProbe.peak == c` at `c ∈ {1, 4, 8}` across all three measurement-loop entry points.
- SC-002: PR-2 corrected-dispatch re-run completes on Modal A10G `eu-west-1` in ≤ 45 min wall-clock (audit baseline ran in 26.7 min; the corrected dispatch concurrency may compress that further or extend it modestly if engine-side queueing changes).
- SC-003: PR-2 re-run produces a definitive Phase 2 classification bucket recorded as a single explicit manifest field.
- SC-004: Dispatch-correction note published and cross-linked within 7 days of PR-2 re-run.
- SC-005: Spot-check of any M6 / M6.1 published cell under corrected dispatch falls within the published 95 % CI (no main-verdict regression).
- SC-006: PR-2 total Modal compute ≤ $1.
- SC-007: Reader can determine in ≤ 5 min which M6.x findings are dispatch-sensitive vs robust from the dispatch-correction note alone.

**Constraints**:

- **Harness-only scope** (FR-014): all code changes confined to `tools/benchmark/src/vllm_grpc_bench/` and `tools/benchmark/tests/`. No edits to `proxy/`, `frontend/`, `client/`, `proto/`, `scripts/python/modal_bench_rest_grpc_server.py`, or any vLLM / torch source.
- **No `.proto` edits**: the dispatch fix is purely Python concurrency restructuring; no wire-format changes (Constitution Principle I).
- **No engine path changes** (FR-014): the M6.1.1 Modal endpoint is reused unchanged; `provide_m6_endpoint` + `provide_m6_1_rpc_driver` are not modified.
- **Audit baseline preserved verbatim** (FR-011): `docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md` is read-only; no body edits, only additive forward cross-links from new artifacts.
- **Strict-superset schema** (FR-007): the new top-level `dispatch_mode` key is added to M6.1.1's JSON manifest without bumping `schema_version`; pre-existing M6.1.1 / M6.2-aware readers ignore the unknown key without error. Absent `dispatch_mode` MUST be read as `sequential` for retroactive interpretation of the audit baseline.
- **Version-pin parity** (FR-008): the PR-2 re-run pins to `vllm==0.20.1`, `torch==2.11.0`, `Qwen/Qwen3-8B`, and the audit-baseline `uv.lock`-resolved transitive set (`uv sync --frozen` against `b63947a`'s lockfile).
- **Determinism preservation** (FR-002): seed-per-RPC mapping under the corrected harness is bit-identical to the pre-fix harness for any `(cohort, idx, base_seed)` triple; concurrent dispatch must not perturb `compute_rpc_seed` or the M6.1.1 `base_seed + i` mapping.
- **No parallel-fork code path** (FR-005): the operator does not choose between sequential and concurrent dispatch — the fix is unconditional. There is no `--m6-sequential-dispatch` flag, no environment variable, no legacy mode.
- **Two-PR sequence** (FR-018): PR-1 (harness fix + regression test) merges first and MAY merge before PR-2's Modal re-run completes; PR-2 (corrected-dispatch artifact + dispatch-correction note) opens after the re-run produces "after" data.
- **PLAN.md scope discipline**: M6.0a MUST NOT redesign the M6.1.1 FR-010 magnitude-equivalence classifier (open methodology issue at PR #27 comment `4468600646`); MUST NOT modify M6 / M6.1 main verdict tables (dispatch-robust per FR-015); MUST NOT introduce a `dispatch_mode = automatic` enum value or any third dispatch mode beyond `sequential` / `concurrent`.

**Scale/Scope**:

- **PR-1 code change**: ~50–150 lines net change across 3 files (`m6_sweep.py`, `m6_1_sweep.py`, `m6_1_1_sweep.py`) — each measurement / warmup function gains an `asyncio.gather` call site and loses a sequential `await` loop. Plus ~100–200 lines for the regression test file.
- **PR-1 docstring updates**: `concurrency` field docstrings in `m6_types.py`, `m6_1_types.py`, `m6_1_1_types.py` revised from "metadata tag for round-robin sequencing" → "actual in-flight parallelism" (FR-006).
- **PR-1 reporter extension**: `m6_1_1_reporter.py` gains a `dispatch_mode: concurrent` injection at manifest write-time (~5 lines). This actually ships in PR-1 because the corrected harness must emit the annotation from the first run forward; PR-2 just consumes that annotation.
- **PR-2 Modal sweep**: 6 cells × 3 cohorts × n=50 measurement RPCs + 10 warmup × cohort = ~1,080 RPCs total. Single ~30–45 min wall-clock run. ≤ $1 compute.
- **PR-2 doc**: ~1 page of markdown with a side-by-side per-cohort spread table; one new docs file plus an additive M6.1 cross-link annotation.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against the 5 principles in `.specify/memory/constitution.md` (v1.0.0):

| Principle | Status | Notes |
|---|---|---|
| **I. Proto-First** | **PASS** | M6.0a makes no `.proto` edits. The fix is purely Python `asyncio` restructuring inside `tools/benchmark/src/vllm_grpc_bench/`. The new `dispatch_mode` JSON field is a strict-superset addition to M6.1.1's manifest schema (FR-007) — JSON is not proto-tracked; M6.1.1's manifest never had a corresponding `.proto` schema. |
| **II. Library Dependency, Not Fork** | **PASS** | M6.0a uses `vllm==0.20.1` and `torch==2.11.0` as ordinary pinned dependencies — identical to the audit baseline (FR-008). No vLLM or torch source modification. The dispatch fix is a Python-level concurrency refactor on the *caller* side of the engine; the engine itself, the Modal endpoint, and the vLLM `AsyncLLM` invocation pattern are untouched (FR-014). |
| **III. Phase Discipline** | **PASS** | M6.0a is a canonical milestone in [`docs/PLAN.md`](../../docs/PLAN.md) (since 2026-05-16, drafted during the M6.1.1 cycle when the dispatch-mode bug surfaced). Spec scope matches PLAN.md M6.0a §: harness fix + regression test + corrected re-run + dispatch-correction note. Out-of-scope items (FR-010 classifier degeneracy → separate M6.1.1 issue; M6 main-verdict re-run → out-of-scope dispatch-robust; M6.1 main-verdict re-run → out-of-scope dispatch-robust; M6.2 `max_tokens` axis; M7 corpus; M8 multi-model) are explicit per FR-014 + FR-015 + the spec's Assumptions and Edge Cases. PR-2's dispatch-correction note ships scope-bounded — bug + fix + before/after, not a full methodology re-derivation. |
| **IV. CI is the Merge Gate** | **PASS** | PR-1's regression test (`tests/test_m6_concurrent_dispatch.py`) is wired into the same `pytest` invocation as the existing M6.1.1 test suite (FR-004); failure blocks PR-1 from merging AND blocks M6.1.1's PR #27 from merging. All PR-1 changes pass `ruff check`, `ruff format --check`, `mypy --strict`, and `pytest` per [`feedback_local_lint_chain`](../../specs/022-m6-1-real-prompt-embeds/checklists/requirements.md) memory before push. PR-2 contains no code beyond the `m6_1_1_reporter.py` `dispatch_mode` injection that's already covered by PR-1's test surface; the artifact + note PR runs the same CI gate. |
| **V. Honest Measurement** | **PASS** | M6.0a IS a methodology correction. The audit baseline is preserved verbatim (FR-011) — the "before" data is not retroactively re-classified or rewritten. The corrected-dispatch run publishes its `engine_ttft_ms` per-cohort spread numbers alongside the audit baseline numbers (FR-009) so the comparison is auditable. Phase 2 verdict is recorded as a single explicit manifest field (FR-010) with raw spread numbers under the intermediate band; the classifier-degeneracy issue is documented as out-of-M6.0a-scope rather than papered over. The M6.1 narrative annotation (FR-016) keeps the methodology-supersedence trail unbroken. The 2-PR sequence (FR-018) means PR-1's harness fix ships *before* the data exists — explicitly acknowledging that the fix's correctness rests on the regression test, not on a favourable re-run outcome. |

**Result: 5/5 PASS. No violations. Complexity Tracking is empty.**

Re-check after Phase 1 design: see "Post-Design Constitution Check" at the end of this document.

## Project Structure

### Documentation (this feature)

```text
specs/024-m6-0a-concurrent-dispatch/
├── plan.md                     # This file (/speckit-plan output)
├── research.md                 # Phase 0 — research items + decisions (/speckit-plan output)
├── data-model.md               # Phase 1 — entity shapes (/speckit-plan output)
├── quickstart.md               # Phase 1 — operator playbook (/speckit-plan output)
├── contracts/
│   ├── dispatch.md             # The concurrent-dispatch invariant (peak in-flight = c) and the In-Flight Concurrency Probe fake-driver contract
│   └── output.md               # The dispatch_mode strict-superset schema addition to M6.1.1's JSON manifest
├── spec.md                     # Feature spec (existing, 6 Q/A clarifications across 2 rounds)
├── checklists/
│   └── requirements.md         # Spec quality checklist (existing)
└── tasks.md                    # /speckit-tasks output (NOT created by /speckit-plan)
```

### Source Code (repository root — extending existing layout)

M6.0a is a surgical correction to the M6 / M6.1 / M6.1.1 harness. No new module is created; 3 existing modules are edited at 5 specific dispatch entry points. One new test file lands.

```text
tools/benchmark/src/vllm_grpc_bench/
├── m6_sweep.py                # MODIFY — 2 entry points:
│                              #   • _run_warmup (m6_sweep.py:189) — replace `for _ in range(size): for _attempt in range(): await driver(...)` with per-(cohort × c-batch) `asyncio.gather(*(_warmup_one() for _ in range(size)))` preserving the inner retry-until-success loop.
│                              #   • _run_measurement (m6_sweep.py:219) — replace `for cohort: for idx in batch_indices: await ...` with `for cohort in cohorts: results = await asyncio.gather(*(_one(cohort, idx) for idx in batch_indices))`. Round-robin per-c-batch index allocator unchanged (preserves cohort-symmetric seeds per FR-002 / M6's FR-025).
├── m6_1_sweep.py              # MODIFY — 2 entry points (same pattern as m6_sweep):
│                              #   • _run_warmup_m6_1 (m6_1_sweep.py:141).
│                              #   • _run_measurement_m6_1 (m6_1_sweep.py:160).
├── m6_1_1_sweep.py            # MODIFY — 1 entry point:
│                              #   • _measure_cell (m6_1_1_sweep.py:233) — warmup and measurement loops both restructured:
│                              #     • Warmup: per-cohort `asyncio.gather(*(driver(cohort, m6_1_cell, 0) for _ in range(n_warmup)))` (FR-005a).
│                              #     • Measurement: per-cohort Semaphore(c)-bounded gather over `range(n_measurement)` — steady c-in-flight stream rather than burst-then-drain.
├── m6_types.py                # MODIFY — `concurrency` field docstring on M6Cell: revise from "metadata tag for round-robin sequencing" → "actual in-flight parallelism (peak concurrent RPCs per cohort within a c-batch)" (FR-006).
├── m6_1_types.py              # MODIFY — same docstring revision on M6_1Cell (FR-006).
├── m6_1_1_types.py            # MODIFY — same docstring revision on M6_1_1Cell (FR-006).
├── m6_1_1_reporter.py         # MODIFY — emit a top-level `dispatch_mode: "concurrent"` key on every manifest write (`_sanitize_for_json` augmented; ~5 lines). FR-007 strict-superset addition; ships in PR-1 so the first corrected-dispatch sweep emits the annotation correctly.
├── m6_rpc_driver.py           # UNCHANGED — RPC driver signature `(cohort, cell, seed) -> RPCResult` unaffected by the dispatch fix.
├── m6_1_rpc_driver.py         # UNCHANGED — M6.1 / M6.1.1 RPC driver inherits the same signature.
├── m6_1_torch_pin.py          # UNCHANGED — version-pin parity is operator-enforced via `uv sync --frozen` (FR-008), not via a code change.
├── m6_1_seed.py               # UNCHANGED — `compute_rpc_seed(idx, base_seed)` already async-order-independent (pure function).
├── m6_1_seq_len.py            # UNCHANGED.
├── m6_engine_cost.py          # UNCHANGED — engine_cost trio parsers preserved verbatim.
└── m5_1_grpc_cohort.py        # READ-ONLY reference — canonical `asyncio.gather(*(_channel_worker(i) for i in range(concurrency)))` pattern at line 387 is the pattern M6.0a ports.

tools/benchmark/tests/
└── test_m6_concurrent_dispatch.py  # NEW — path-agnostic regression test:
                                #   • _ConcurrencyProbe fake driver (asyncio.Semaphore-style in-flight counter).
                                #   • parametrised over (concurrency ∈ {1, 4, 8}) × (measurement-loop entry-point ∈ {_run_measurement, _run_measurement_m6_1, _measure_cell}).
                                #   • Each test asserts probe.peak == concurrency (FR-003 + Acceptance Scenarios 1.1 / 1.2 / 1.3).
                                #   • Additional warmup-loop test at c=4 (FR-005a).
                                #   • Seed-determinism test asserting (cohort, idx, seed) triples are bit-identical to the pre-fix harness sequence (FR-002).

docs/benchmarks/
├── m6_1_1-audit-2026-05-16-seq-dispatch.md          # READ-ONLY (FR-011) — preserved verbatim; no edits; only additive forward cross-links from new artifacts may reference it.
├── m6_1_1-engine-cost-instrumentation.{md,json}     # NEW (PR-2) — corrected-dispatch artifact with `dispatch_mode: "concurrent"` top-level key.
├── m6_0a-dispatch-correction.md                     # NEW (PR-2) — short standalone explainer cross-linking the audit baseline, the corrected run, PR #27, and PLAN.md M6.0a section (FR-012 / FR-013).
└── m6_1-real-prompt-embeds.md                       # MODIFY (PR-2) — additive cross-link annotation in the per-cohort drift section pointing at the M6.0a dispatch-correction note (FR-016).

CLAUDE.md                       # MODIFY — update SPECKIT plan reference between markers (Phase 1 step 3 of /speckit-plan).
```

**Structure Decision**: M6.0a is a surgical correction to existing dispatch entry points, NOT an additive milestone. The five edits land in three existing harness modules; no `m6_0a_*` module is created (such a module would imply M6.0a is parallel to M6.1.1, but M6.0a is a *correction inside* the M6 family — naming a module `m6_0a_*` would muddle that). The strict-superset `dispatch_mode` field lands in M6.1.1's existing reporter (`m6_1_1_reporter.py`), not in a new reporter — M6.0a inherits M6.1.1's manifest emission infrastructure wholesale (the audit baseline is itself an M6.1.1 manifest; the corrected run is also an M6.1.1 manifest; the only difference is the new top-level key). The regression test lives in a single new file (`test_m6_concurrent_dispatch.py`) under `tools/benchmark/tests/`, matching the existing convention for cross-cutting harness tests.

## Complexity Tracking

> Empty — Constitution Check passed 5/5 with no violations.

Per the project's `feedback_thorough_clarify_cycles` memory, the spec underwent 2 rounds of clarification (6 Q/A bullets total) before this plan was written. The plan inherits those decisions verbatim. No new external dependencies. No new architectural concept — the dispatch fix ports an existing canonical pattern (M5.1's `asyncio.gather` + `_channel_worker` from `m5_1_grpc_cohort.py:387`). The new `dispatch_mode` field is a single-key strict-superset addition that requires no schema-version coordination.

---

## Phase 0: Outline & Research

See [`research.md`](./research.md) for the 6 research items (R-1 through R-6) and their decisions. All NEEDS CLARIFICATION items were resolved during the 2-round spec clarification; Phase 0 captures the implementation-level investigation that complements those spec-level decisions.

**Output**: `research.md` with all NEEDS CLARIFICATION resolved (none in Technical Context).

## Phase 1: Design & Contracts

See [`data-model.md`](./data-model.md), [`contracts/dispatch.md`](./contracts/dispatch.md), [`contracts/output.md`](./contracts/output.md), [`quickstart.md`](./quickstart.md).

Agent context update: the SPECKIT plan reference in `/Users/bsansom/projects/vllm-grpc/CLAUDE.md` between the `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers is updated as part of Phase 1 step 3 to point at this plan's path.

**Output**: `data-model.md`, `contracts/dispatch.md`, `contracts/output.md`, `quickstart.md`, updated `CLAUDE.md`.

## Post-Design Constitution Check

Re-evaluated against the 5 principles after Phase 1 design artifacts were drafted:

| Principle | Status | Post-design notes |
|---|---|---|
| I. Proto-First | **PASS** | Confirmed by [`contracts/dispatch.md`](./contracts/dispatch.md) + [`contracts/output.md`](./contracts/output.md) — the dispatch invariant is a Python `asyncio` contract (zero `.proto` impact); the `dispatch_mode` field is a JSON manifest top-level key (M6.1.1's manifest is not proto-tracked). |
| II. Library Dependency, Not Fork | **PASS** | Confirmed by [`data-model.md`](./data-model.md) — every M6.0a edit lands in `tools/benchmark/src/vllm_grpc_bench/`. The vLLM `AsyncLLM` invocation, Modal endpoint provisioning, and `provide_m6_endpoint` / `provide_m6_1_rpc_driver` factories are unchanged. The fix is a Python-level `asyncio.gather` restructuring on the caller side of the engine boundary. |
| III. Phase Discipline | **PASS** | Confirmed by [`contracts/dispatch.md`](./contracts/dispatch.md) — the dispatch invariant ("peak in-flight = c, sequential across cohorts, concurrent within a cohort") is exactly the M5.1-canonical pattern from `m5_1_grpc_cohort.py:387`. No M6.2 / M7 / M8 functionality leaks in. The strict-superset `dispatch_mode` enum has exactly two values (`sequential`, `concurrent`); a third value or an `automatic` variant is prohibited at the contract level. |
| IV. CI is the Merge Gate | **PASS** | [`quickstart.md`](./quickstart.md) operator playbook includes the local-lint-chain step (`ruff check`, `ruff format --check`, `mypy --strict`, `pytest`) before any push per [`feedback_local_lint_chain`](../../specs/022-m6-1-real-prompt-embeds/checklists/requirements.md) memory. The new regression test file is parametrised so failure on ANY of (c=1, c=4, c=8) × (m6, m6_1, m6_1_1) blocks the merge gate. |
| V. Honest Measurement | **PASS** | [`contracts/output.md`](./contracts/output.md) mandates: `dispatch_mode` is emitted on EVERY corrected-dispatch run (no silent omission); absent `dispatch_mode` retroactively means `sequential` (FR-007); the audit-baseline numbers are preserved verbatim alongside the corrected-dispatch numbers in PR-2's markdown (FR-009 / FR-011); the dispatch-correction note publishes raw side-by-side data, not a narrative-massaged summary (FR-012). Under the intermediate-band classifier outcome, raw per-cohort spread numbers are recorded alongside the classifier label (FR-010) so a reviewer can apply manual interpretation — M6.0a cannot smuggle a clean closure verdict when the data is ambiguous. |

**Result: 5/5 PASS post-design. No new complexity introduced.**
