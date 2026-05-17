# Phase 0 Research: M6.0a — Concurrent Dispatch Restoration

**Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md)

## Scope

M6.0a's Technical Context has zero `NEEDS CLARIFICATION` markers — all are resolved at spec time through the 6 clarification Q/A bullets in [spec.md](./spec.md#clarifications). This document captures the **implementation-level investigation** that complements the spec-level decisions: confirming the canonical reference pattern is portable, enumerating exact dispatch entry-point sites, verifying determinism invariants hold, and surveying existing tests for sequential-dispatch assumptions that the fix might break.

## Research Items

### R-1 — Canonical concurrent-dispatch pattern in M5.1

**Question**: Which exact code in M5.1 is the reference pattern M6.0a ports, and what is its shape?

**Decision**: Port the pattern at `tools/benchmark/src/vllm_grpc_bench/m5_1_grpc_cohort.py:387` (and its REST-side analog at `tools/benchmark/src/vllm_grpc_bench/rest_cohort.py`):

```python
await asyncio.gather(*(_channel_worker(i) for i in range(concurrency)))
# OR (queue-drain variant for multiplexed mode at line 407):
await asyncio.gather(*(_worker() for _ in range(concurrency)))
```

The function `run_grpc_cohort` (line 303) opens a single channel (or `c` channels in `tuned_grpc_channels` mode), then dispatches `c` concurrent workers via `asyncio.gather`. M5.1's documented "in series" cohort orchestration (`m5_1_sweep.py:246` comment "Run the cell's REST + tuned-gRPC sub-cohort(s) + default-gRPC control in series") confirms that across-cohort orchestration is sequential while within-cohort dispatch is c-concurrent. This is the exact pattern Acceptance Scenario 1.1 ("peak observed concurrent driver entries equals 4") requires.

**Rationale**: M5.1 is the last milestone with verified-working concurrent dispatch. Its pattern is battle-tested across the M5.1 / M5.2 publishing cycles. Porting it verbatim minimises invention risk and matches the spec's Assumptions section ("M5.1 / M5.2 use a true concurrent dispatch pattern ... and that pattern is the canonical reference the M6 harness will port").

**Alternatives considered**:

- *Hand-rolled `asyncio.Semaphore`-bounded gather over the full RPC range*: matches the spec's "peak in-flight = c" invariant slightly more literally (steady c-in-flight stream rather than batched bursts) but is unnecessary for M6 / M6.1's c-batch-aligned pattern. Used only for M6.1.1's `_measure_cell` where no c-batch structure exists.
- *`asyncio.TaskGroup`* (Python 3.11+): functionally equivalent to `asyncio.gather` but project standard is `gather` (consistent with M5.1 / M5.2). No reason to introduce a second pattern.
- *`anyio.create_task_group`*: cross-library; project uses asyncio directly throughout. Rejected.

### R-2 — Complete enumeration of sequential-dispatch entry points

**Question**: Which exact code locations dispatch RPCs sequentially under M6 / M6.1 / M6.1.1, and how many separate edits are needed?

**Decision**: Five entry points across three files (confirmed by inspection during plan drafting):

1. `tools/benchmark/src/vllm_grpc_bench/m6_sweep.py:189` — `_run_warmup` — inner `for _ in range(size): for _attempt in range(M6_RPC_RETRY_MAX + 1): await driver(...)` sequential within each (cohort, c-batch) pair.
2. `tools/benchmark/src/vllm_grpc_bench/m6_sweep.py:219` — `_run_measurement` — inner `for idx in batch_indices: await _run_one_rpc_with_retry(...)` sequential within each (cohort, c-batch) pair. Round-robin c-batch index allocator preserves cohort-symmetric seeds.
3. `tools/benchmark/src/vllm_grpc_bench/m6_1_sweep.py:141` — `_run_warmup_m6_1` — same pattern as `m6_sweep._run_warmup`.
4. `tools/benchmark/src/vllm_grpc_bench/m6_1_sweep.py:160` — `_run_measurement_m6_1` — same pattern as `m6_sweep._run_measurement`.
5. `tools/benchmark/src/vllm_grpc_bench/m6_1_1_sweep.py:233` — `_measure_cell` — both warmup (`for _ in range(n_warmup): await driver(cohort, m6_1_cell, 0)`) and measurement (`for i in range(n_measurement): seed = base_seed + i; result = await driver(...)`) loops sequential. M6.1.1's `_measure_cell` does NOT delegate to M6.1's measurement loops — it has its own simpler pattern (no c-batch chunking, no retry-with-budget).

**Rationale**: A `grep -n "_run_measurement\|_run_warmup\|asyncio.gather\|for idx in"` across all M6.x sweep modules surfaced exactly these five sites. The M6.1.1 sweep was initially expected to delegate to M6.1's loops; confirmed by code reading that it does NOT — it has its own dispatch primitives. All five must be patched in PR-1 for FR-005 ("M6, M6.1, and M6.1.1 MUST inherit the corrected dispatch behaviour") to hold.

**Alternatives considered**:

- *Patch only `_run_measurement_m6_1` and have M6.1.1 delegate*: would require additional refactoring of `_measure_cell` to call into `_run_measurement_m6_1`. Larger change surface; rejected in favour of in-place fix at the five existing sites.
- *Extract a shared `dispatch_concurrent(driver, cohort, indices, c)` helper used by all five sites*: cleaner long-term but introduces a fourth abstraction layer in the harness. Deferred (out of M6.0a scope; could land in a follow-up refactor).

### R-3 — Determinism preservation under concurrent dispatch

**Question**: Does `compute_rpc_seed(idx, base_seed)` (M6 / M6.1) and `seed = base_seed + i` (M6.1.1) remain bit-identical under concurrent dispatch?

**Decision**: **Yes, trivially.** Both seed-mapping functions are pure functions of `(idx, base_seed)` — no async-ordering coupling. `compute_rpc_seed` (`tools/benchmark/src/vllm_grpc_bench/m6_1_seed.py:24`) is:

```python
def compute_rpc_seed(rpc_index: int, base_seed: int = DEFAULT_M6_1_BASE_SEED) -> int:
```

The function does not read any global state, scheduler state, or completion-order information. Concurrent dispatch changes the *order in which results arrive*, not the *seed used for each RPC*. The cohort-symmetric invariant (M6's FR-025: every cohort's i-th RPC within a c-batch shares the same `rpc_index` → same seed) is preserved.

**Rationale**: Acceptance Scenario 1.4 mandates seed determinism as a hard precondition. The regression test (`tests/test_m6_concurrent_dispatch.py`) records `(cohort, idx, seed)` triples via the `_ConcurrencyProbe` fake driver and asserts the sequence is bit-identical to the pre-fix harness's sequence at `c=1` and `c=4`. If async-ordering coupling were ever introduced (e.g., by a future refactor that reads `asyncio.current_task()` inside the seed function), the test would catch it.

**Alternatives considered**:

- *Add a per-RPC-completion seed assignment (consume from a shared iterator at completion time)*: would couple to ordering and break determinism. Rejected at design time.
- *Use `random.SystemRandom` with explicit seeding per RPC*: irrelevant — the existing pure-function approach already preserves determinism.

### R-4 — Regression test design (path-agnostic In-Flight Concurrency Probe)

**Question**: What is the minimal test shape that satisfies FR-003 (path-agnostic; covers `c=1`, `c=4`, `c=8`) and FR-004 (failure blocks CI)?

**Decision**: A single test file `tools/benchmark/tests/test_m6_concurrent_dispatch.py` with a `_ConcurrencyProbe` fake driver:

```python
class _ConcurrencyProbe:
    def __init__(self) -> None:
        self.in_flight = 0
        self.peak = 0
        self.records: list[tuple[str, int, int]] = []  # (cohort, idx, seed) triples

    async def __call__(self, cohort: str, cell: Any, seed: int) -> RPCResult:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        self.records.append((cohort, 0, seed))  # idx populated by the loop
        try:
            await asyncio.sleep(0)  # yield so siblings can enter
            return RPCResult(success=True, ...)
        finally:
            self.in_flight -= 1
```

Parametrise over `(concurrency, measurement_loop) ∈ {(1, m6), (4, m6), (8, m6), (1, m6_1), (4, m6_1), (8, m6_1), (1, m6_1_1), (4, m6_1_1), (8, m6_1_1)}` and assert `probe.peak == concurrency`.

**Rationale**: The fake driver matches the project's `RPCDriver` callable signature (`(cohort, cell, seed) -> RPCResult`). The single-yield `asyncio.sleep(0)` is enough to give other coros a chance to enter the probe before any one exits — under sequential dispatch the probe will only ever see `peak == 1`. The parametrisation gives 9 test cases from one file. Path-agnostic per FR-003: the probe doesn't care whether the underlying path is chat_stream / embed / embed-prompt-embeds, because path selection happens *inside* the driver, after dispatch.

**Alternatives considered**:

- *Wrap a real RPC driver with a Semaphore-counting decorator*: more faithful to production but adds Modal / endpoint setup overhead to the test path. Unit tests should not hit Modal. Rejected.
- *Hard-coded `assert in_flight >= 2` rather than `== c`*: weaker assertion. The spec is explicit on `== c` (Acceptance Scenarios 1.1 / 1.2 / 1.3). Use the strict assertion.
- *Three separate test files, one per measurement loop*: matches the structure better but `pytest.mark.parametrize` is cleaner and gives a single failure dashboard. Project convention favours parametrisation.

### R-5 — Version pinning mechanism for the PR-2 corrected-dispatch re-run

**Question**: What concrete command pins the PR-2 re-run environment to the audit baseline's resolved dependency set (`vllm==0.20.1`, `torch==2.11.0`, audit-baseline `uv.lock`)?

**Decision**: `uv sync --frozen` invoked against the `uv.lock` committed at `b63947a`. Concrete operator sequence:

```bash
# 1. From the M6.0a branch (PR-1 already merged to main, or use M6.0a's branch directly):
git fetch origin
git checkout 024-m6-0a-concurrent-dispatch

# 2. Pin lockfile to b63947a's resolved set:
git checkout b63947a -- uv.lock

# 3. Frozen sync — installs exactly what audit baseline used:
uv sync --frozen

# 4. Verify pins:
uv pip show vllm | grep '^Version:'   # → Version: 0.20.1
uv pip show torch | grep '^Version:'  # → Version: 2.11.0

# 5. Restore lockfile to its post-fix state (no commit needed):
git checkout HEAD -- uv.lock
uv sync --frozen
```

**Rationale**: `uv sync --frozen` is the project's standard reproducible-environment mechanism (matches `feedback_local_lint_chain` memory's emphasis on local-CI parity). Pinning the lockfile to `b63947a` precisely is feasible because `uv.lock` was already committed at that revision (verified by `git show b63947a -- uv.lock`). Step 5 is optional — the re-run only needs the audit-baseline environment during the sweep; afterwards the operator restores the lockfile to current `main` to continue normal development.

**Alternatives considered**:

- *Run the corrected-dispatch sweep from a `git worktree` rooted at `b63947a` with the PR-1 patch applied on top*: cleaner isolation but heavier setup. Operator preference per `feedback_local_lint_chain` is for in-place `uv sync --frozen` swaps.
- *Pin via `pyproject.toml` edits*: would touch transitive dependencies' indirect pins; `uv.lock` is the single source of truth. Rejected.
- *Skip explicit pinning and accept whatever `main` resolves at run time*: violates FR-008. Rejected at clarification time (spec Session 2 Q1).

### R-6 — Survey of existing tests for sequential-dispatch assumptions

**Question**: Do any existing tests under `tools/benchmark/tests/` (M5.x / M6 / M6.1 / M6.1.1) assert sequential dispatch in a way that would break after PR-1 lands?

**Decision**: **No assertions in existing tests presume sequential dispatch.** Investigation findings:

- M5.1 / M5.2 cohort tests (`test_m5_1_*.py`) assert concurrent dispatch peak counts via Semaphore-counting probes that mirror the design in R-4; they continue to pass after PR-1 (their assertions are `peak >= c` or `peak == c`, both of which hold).
- M6 / M6.1 / M6.1.1 unit tests for `_run_measurement` / `_measure_cell` use small `c=1` cells (the most common test cell shape) where peak in-flight under sequential and concurrent dispatch is identical (`== 1`).
- M6.1.1 unit tests for the classifier, perturbation gate, reporter, supersedence writer, etc., operate on synthetic in-memory inputs and do not exercise the dispatch loop at all.
- No `assert len(in_flight) == 1` or equivalent sequential-only assertion exists in the test corpus.

**Rationale**: A `grep -rn "in_flight\|peak\|concurrent\|sequential" tools/benchmark/tests/` returned only the M5.1 / M5.2 concurrency probes (which assert `>= c` or `== c`) and a handful of unrelated string matches. The PR-1 fix is therefore non-breaking for the existing test suite.

**Alternatives considered**:

- *Add a regression sentinel test that asserts sequential dispatch at some specific code path (negative test)*: nonsensical — sequential dispatch is the bug being removed. Rejected.

## Phase 0 outcome

All six research items resolved. No NEEDS CLARIFICATION items added to the plan (zero present at start; zero discovered during Phase 0). Ready for Phase 1 design.
