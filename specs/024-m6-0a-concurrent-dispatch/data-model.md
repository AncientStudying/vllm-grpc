# Phase 1 Data Model: M6.0a — Concurrent Dispatch Restoration

**Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md)

## Scope

M6.0a is a harness-only correction (FR-014) — it touches Python dispatch primitives in `tools/benchmark/`, adds one strict-superset field (`dispatch_mode`) to M6.1.1's existing JSON manifest, and publishes two new docs files. There is no relational data, no persistent storage, no new wire-format. The "entities" enumerated here are the conceptual units the spec references; they map onto existing Python types or single-file artifacts.

## Entities

### 1. M6 Measurement Batch

**Source**: Spec § Key Entities

**Definition**: A group of RPCs (one per cohort × batch index) dispatched at a single concurrency level `c` within a single cell.

**Realisation**:

- **M6 / M6.1 path**: a `batch_indices: list[int]` of length `c` allocated by the round-robin per-c-batch index allocator (`_run_measurement` and `_run_measurement_m6_1`). Within a c-batch, every cohort iterates the same `batch_indices` to preserve cohort-symmetric seeds (`compute_rpc_seed(idx, base_seed)`).
- **M6.1.1 path**: implicit — `_measure_cell` does not have a c-batch concept; instead, all `n_measurement` RPCs per cohort are dispatched under a Semaphore(c)-bounded `asyncio.gather` so peak in-flight stays at `c`.

**Pre-fix behaviour**: peak in-flight = 1 (sequential `await` loop over `batch_indices` and `range(n_measurement)`).

**Post-fix behaviour**: peak in-flight = `c` (per-cohort `asyncio.gather` — M6 / M6.1 — or Semaphore(c)-bounded gather — M6.1.1). Across cohorts within a cell, dispatch remains sequential (matches M5.1's "in series" cohort orchestration documented at `m5_1_sweep.py:246`).

**Invariants** (asserted by `tests/test_m6_concurrent_dispatch.py`):

- `peak_in_flight(c) == c` for `c ∈ {1, 4, 8}` (FR-001 + Acceptance Scenarios 1.1 / 1.2 / 1.3).
- Seed determinism: `(cohort, idx) → seed` mapping is unchanged under post-fix vs pre-fix dispatch (FR-002 + Acceptance Scenario 1.4).
- Retry policy unchanged: a single RPC failure in a concurrent batch follows the same `_run_one_rpc_with_retry` / inner-retry-loop semantics as a single RPC failure in the sequential pre-fix harness (Edge Case: "What if a single RPC in a concurrent batch fails partway?").

### 2. Dispatch Mode

**Source**: Spec § Key Entities + FR-007

**Definition**: Categorical attribute of every benchmark run, valued `"sequential"` (pre-fix) or `"concurrent"` (post-fix).

**Realisation**:

- In code: enum-like `Literal["sequential", "concurrent"]` constant; no runtime branching — `"concurrent"` is unconditional after PR-1 lands. The literal is referenced only at manifest-emission time inside `m6_1_1_reporter.py`.
- In manifest: a new top-level key on M6.1.1's JSON output:
  ```json
  {
    "dispatch_mode": "concurrent",
    ...
  }
  ```
- Backward-compatibility (FR-007): pre-existing M6.1.1 / M6.2-aware readers ignore the unknown key. An absent `dispatch_mode` is read as `"sequential"` (retroactive interpretation of the 2026-05-16 audit baseline, which did not emit the key).

**Invariants**:

- The corrected-dispatch run MUST emit `dispatch_mode: "concurrent"` (FR-007).
- The audit baseline (preserved verbatim per FR-011) does NOT receive a retroactive `dispatch_mode: "sequential"` annotation.
- No third value is permitted (`automatic`, `unknown`, `mixed` — explicitly prohibited at the contract level in [`contracts/output.md`](./contracts/output.md)).

### 3. In-Flight Concurrency Probe

**Source**: Spec § Key Entities + FR-003

**Definition**: A counting fake driver used by the regression test to assert peak simultaneous driver entries.

**Realisation** (`tools/benchmark/tests/test_m6_concurrent_dispatch.py`):

```python
class _ConcurrencyProbe:
    def __init__(self) -> None:
        self.in_flight: int = 0
        self.peak: int = 0
        self.records: list[tuple[str, int]] = []  # (cohort, seed) triples for determinism check

    async def __call__(self, cohort: str, cell: Any, seed: int) -> RPCResult:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        self.records.append((cohort, seed))
        try:
            await asyncio.sleep(0)  # yield so sibling coros can enter
            return RPCResult(success=True, wall_clock_ms=1.0, ttft_ms=0.5, engine_cost=None, failure_reason=None)
        finally:
            self.in_flight -= 1
```

**Invariants**:

- `peak == c` after exercising any measurement-loop entry point at concurrency `c` (asserted by the test).
- Path-agnostic: the probe is invoked identically regardless of `cell.path` (chat_stream / embed / embed-prompt-embeds) — path selection happens *inside* the production driver, never in the probe (FR-003).

### 4. Sequential-Baseline Audit Artifact

**Source**: Spec § Key Entities + FR-011

**Definition**: The file `docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md` committed at `b63947a`. Preserved verbatim as the "before" data set.

**Realisation**:

- File path: `docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md`.
- Commit anchor: `b63947a` (`docs(m6_1_1): commit second live Phase 1 run as audit data`).
- Format: 6-section markdown (Executive Summary / Methodology / Multi-Point Timing Table / Root-Cause Attribution / Phase 2 Outcome / Methodology Supersedence) with a prepended audit-callout header explaining the 3 open methodology issues at the time of commit.
- Companion JSON: NONE — the audit run crashed during JSON serialisation (the tuple-key bug fixed at `14a9a0c`). Only markdown exists for this run.

**Invariants** (FR-011):

- No edits to the file body. Ever.
- Only additive forward cross-links may reference it (PR-2's `docs/benchmarks/m6_0a-dispatch-correction.md` will link IN; the audit file does not link OUT to PR-2-era artifacts).
- The pre-existing audit-callout header already contains a forward pointer to M6.0a (committed at `b63947a`); this is the read-side mechanism for future visitors landing on the audit file directly.

### 5. Corrected M6.1.1 Run Artifact

**Source**: Spec § Key Entities + FR-007 / FR-008 / FR-009 / FR-010

**Definition**: The definitive Phase 1 run after the dispatch fix. Lives at `docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}` (the canonical slot kept clean by the `m6_1_1-audit-` prefix naming choice in `b63947a`).

**Realisation**:

- Markdown: `docs/benchmarks/m6_1_1-engine-cost-instrumentation.md` — 6-section format matching M6.1.1's `m6_1_1_reporter` output, with `dispatch_mode: "concurrent"` annotated in the methodology section header.
- JSON: `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` — strict-superset of M6.1's `engine_cost_baseline` schema with the new top-level `dispatch_mode` key.
- Source: emitted by `_default_write_report` (already in `m6_1_1_diagnose.py` per commit `501ea28`) using the `_sanitize_for_json` helper (already in `m6_1_1_reporter.py` per commit `14a9a0c`) extended in PR-1 to inject `dispatch_mode`.

**Invariants**:

- Identical sweep parameters to the audit baseline (FR-008): `Qwen/Qwen3-8B` fp16, Modal A10G eu-west-1, base seed 42, n=50 per cohort per cell, 500 µs perturbation budget, `vllm==0.20.1`, `torch==2.11.0`, audit-baseline `uv.lock` transitive set.
- `dispatch_mode == "concurrent"` (FR-007).
- Phase 2 verdict is one of three explicit buckets: `"below 5 %"` / `"at or above 10 %"` / `"intermediate per FR-010 classifier output"` (FR-010).
- Per-chat_stream-cell per-cohort `engine_ttft_ms` spread is reported alongside the audit baseline spread values for direct comparison (FR-009).

### 6. Dispatch-Correction Note

**Source**: Spec § Key Entities + FR-012 / FR-013

**Definition**: The standalone explainer at `docs/benchmarks/m6_0a-dispatch-correction.md` cross-linking the audit baseline, the corrected run, and PLAN.md's M6.0a section.

**Realisation**:

- File path: `docs/benchmarks/m6_0a-dispatch-correction.md`.
- Sections (1-page max per FR-012):
  1. **What broke**: 2–3 sentences on the sequential-dispatch bug.
  2. **The fix**: 2–3 sentences on the `asyncio.gather` pattern restoration.
  3. **The regression test**: 1 sentence pointing to `tools/benchmark/tests/test_m6_concurrent_dispatch.py`.
  4. **Before vs after**: side-by-side per-cohort `engine_ttft_ms` spread table (chat_stream cells × `c=1` / `c=4` / `c=8`).
  5. **Implication for M6.x findings**: 3-row table flagging which findings are dispatch-sensitive (M6 / M6.1 per-cohort drift) vs dispatch-robust (M6 engine-cost dominance; M6.1 engine-path equivalence).
  6. **Cross-links**: bulleted links to (a) audit baseline, (b) corrected run, (c) PR #27, (d) PLAN.md M6.0a section.

**Invariants** (FR-013):

- All four cross-links present and stable.
- Section 5 explicitly enumerates dispatch-sensitive vs dispatch-robust findings (drives SC-007 — reader can determine M6.x finding-sensitivity in ≤ 5 min).
- No re-derivation of M6 / M6.1 main verdicts; the note is scoped to the dispatch bug only (FR-015 + Phase Discipline).

## Relationships

```text
M6 Measurement Batch  ──(executed by)──>  M6 / M6.1 / M6.1.1 dispatch entry point
                                          │
                                          │ peak in-flight = c  (post-fix, FR-001)
                                          ▼
                                          In-Flight Concurrency Probe  (asserts in test)

M6.1.1 manifest emission  ──(injects)──>  Dispatch Mode  (top-level key "concurrent")
                          │
                          │ FR-007 strict-superset
                          ▼
                          Sequential-Baseline Audit Artifact  ──(retroactively read as)──>  dispatch_mode = "sequential"  (no edit to audit file)

Corrected M6.1.1 Run Artifact  ──(cross-linked from)──>  Dispatch-Correction Note  ──(cross-linked from)──>  M6.1 narrative, PR #27, PLAN.md
```

## Out-of-scope (deferred)

The following data shapes are NOT introduced by M6.0a (per FR-014 / FR-015 / Phase Discipline):

- No new RPC types, RPC fields, or wire-format keys on REST or gRPC.
- No new CLI flags or environment variables.
- No new harness module under `tools/benchmark/src/vllm_grpc_bench/` (the fix lands in five existing modules' dispatch entry points; see [plan.md § Project Structure](./plan.md#project-structure)).
- No changes to M6.1.1's `phase_1_runs[]` append-on-re-read pattern (preserved verbatim).
- No new sentinel-object schemas; `dispatch_mode` is a flat top-level string field.
- No re-derivation of M6.1's verdict-supersedes table (per-cohort drift sub-finding picks up a one-line cross-link annotation in PR-2 per FR-016, but the table body is unchanged).
