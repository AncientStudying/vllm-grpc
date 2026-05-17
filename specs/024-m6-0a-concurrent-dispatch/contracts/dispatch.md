# Contract: Concurrent Dispatch Invariant

**Plan**: [../plan.md](../plan.md) | **Spec**: [../spec.md](../spec.md)

## Purpose

Define the operational contract for in-flight RPC concurrency in the M6 / M6.1 / M6.1.1 benchmark harness after M6.0a's correction. This contract is consumed by:

- The regression test `tools/benchmark/tests/test_m6_concurrent_dispatch.py` (FR-003, asserts the invariant).
- Future M6.x sub-milestones (M6.2 in particular) that inherit the corrected dispatch.
- M6.x consumers reading the published JSON manifest's `dispatch_mode` field (FR-007).

## Invariant Statement

Within a single (cell × cohort) measurement, the benchmark harness MUST dispatch RPCs so that the peak number of simultaneously in-flight RPCs equals `cell.concurrency` (denoted `c`). Specifically:

- **Within a cohort**: up to `c` RPCs may be in-flight against the engine at any moment.
- **Across cohorts within a cell**: dispatch is sequential — cohort A's c-concurrent batch completes before cohort B's c-concurrent batch begins. This matches M5.1's canonical "in series" cohort orchestration (`m5_1_sweep.py:246`).
- **Across cells within a sweep**: dispatch is sequential — cell `(chat_stream, h=4096, c=4)` completes before cell `(chat_stream, h=4096, c=8)` begins. This is unchanged from pre-fix behaviour and is not part of M6.0a's scope.

Stated as a single operational rule:

> **Peak observed `in_flight` count at any single moment during a sweep MUST equal `cell.concurrency` for the currently-active cell, regardless of the underlying benchmark path (chat_stream, embed, or embed-prompt-embeds).**

## Reference Implementation Pattern

The canonical M5.1 pattern at `tools/benchmark/src/vllm_grpc_bench/m5_1_grpc_cohort.py:387` is the reference:

```python
# Within a single cohort: c concurrent workers via asyncio.gather.
await asyncio.gather(*(_channel_worker(i) for i in range(concurrency)))
```

For M6 / M6.1's c-batch-aligned measurement loop, the equivalent pattern is:

```python
# tools/benchmark/src/vllm_grpc_bench/m6_sweep.py:_run_measurement (post-fix)
for size in sizes:
    batch_indices = [next(rpc_iter) for _ in range(size) if rpc_iter has more]
    if not batch_indices:
        break
    for cohort in cohorts:
        # Within (cohort, c-batch): c-concurrent dispatch.
        results = await asyncio.gather(*(
            _run_one_rpc_with_retry(driver, cohort, cell, compute_rpc_seed(idx, base_seed))
            for idx in batch_indices
        ))
        for idx, (result, retry_count) in zip(batch_indices, results):
            per_cohort[cohort].append(M6RPCMeasurement(...))
```

For M6.1.1's `_measure_cell` (no c-batch chunking), the equivalent pattern uses `asyncio.Semaphore(c)`:

```python
# tools/benchmark/src/vllm_grpc_bench/m6_1_1_sweep.py:_measure_cell (post-fix)
for cohort in M6_1_COHORTS:
    cohort_start = time.monotonic()
    sem = asyncio.Semaphore(cell.concurrency)

    async def _one(i: int) -> RPCResult:
        async with sem:
            seed = base_seed + i
            return await driver(cohort, m6_1_cell, seed)

    results = await asyncio.gather(*(_one(i) for i in range(n_measurement)))
    per_cohort[cohort].extend(results)
    if reporter is not None:
        successes = sum(1 for r in results if r.success)
        reporter.emit_cell_cohort(cell, cohort, successes, time.monotonic() - cohort_start)
```

For the warmup variants (`_run_warmup`, `_run_warmup_m6_1`, M6.1.1's `_measure_cell` warmup loop) the pattern is analogous — each warmup RPC keeps its inner retry-until-success loop, but the *outer* "fire `size` warmups per cohort" loop becomes `asyncio.gather`:

```python
# tools/benchmark/src/vllm_grpc_bench/m6_sweep.py:_run_warmup (post-fix)
async def _warmup_one(cohort: M6CohortKind) -> int:
    for _attempt in range(M6_RPC_RETRY_MAX + 1):
        result = await driver(cohort, cell, 0)
        if result.success:
            return 1
    return 0

for size in sizes:
    for cohort in cohorts:
        # size = c → c-concurrent warmup attempts per cohort.
        attempt_results = await asyncio.gather(*(_warmup_one(cohort) for _ in range(size)))
        successes[cohort] += sum(attempt_results)
```

## In-Flight Concurrency Probe (Test Driver)

The regression test asserts the invariant via a counting fake driver. The probe MUST conform to the project's `RPCDriver` callable signature:

```python
RPCDriver = Callable[[str, Cell, int], Awaitable[RPCResult]]
```

…where the three arguments are `(cohort, cell, seed)`. The probe records `peak` (maximum simultaneously-in-flight count) and `records` (sequence of `(cohort, seed)` tuples for determinism inspection).

**Probe shape** (reproduced from `tools/benchmark/tests/test_m6_concurrent_dispatch.py`, finalised in PR-1):

```python
class _ConcurrencyProbe:
    def __init__(self) -> None:
        self.in_flight: int = 0
        self.peak: int = 0
        self.records: list[tuple[str, int]] = []  # (cohort, seed) tuples

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

**Probe usage** — three parametrised tests assert the invariant for each measurement-loop entry point:

```python
@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 4, 8])
@pytest.mark.parametrize("entry_point", ["m6", "m6_1", "m6_1_1"])
async def test_concurrent_dispatch_peak(concurrency: int, entry_point: str) -> None:
    probe = _ConcurrencyProbe()
    cell = _make_cell_for(entry_point, concurrency)
    await _invoke_measurement_loop(entry_point, probe, cell)
    assert probe.peak == concurrency, (
        f"{entry_point} at c={concurrency}: expected peak={concurrency}, got {probe.peak}"
    )
```

## Required Invariants for the Probe

The probe MUST:

1. **Be path-agnostic** (FR-003) — the `cell.path` field is ignored; the probe is invoked identically for chat_stream / embed / embed-prompt-embeds.
2. **Yield via `asyncio.sleep(0)`** so sibling coros within an `asyncio.gather` get a chance to enter the probe before any one exits. Without this yield the test would pass under sequential dispatch as well — `peak` would still register at `c` because each task entered briefly before the next started. The yield enforces real overlap.
3. **Match the production `RPCDriver` signature exactly** — `(cohort, cell, seed) -> RPCResult`. Drift in the signature breaks the contract.
4. **Return a successful `RPCResult`** with placeholder timings; downstream aggregation logic uses `success=True` to count measurements correctly.

## Negative Invariants (what the contract prohibits)

- **No `dispatch_mode = "automatic"` or `"mixed"`**: the only valid post-fix value is `"concurrent"`. The harness MUST NOT support a runtime-switchable dispatch mode (FR-005 — no parallel-fork code path).
- **No global concurrency cap above `c`**: the harness MUST NOT introduce an "always c-concurrent regardless of cell" mode. Each cell drives its own peak; `c=1` cells stay strictly singleton-in-flight (Acceptance Scenario 1.3).
- **No async-ordering coupling in seed assignment**: `compute_rpc_seed(idx, base_seed)` (M6 / M6.1) and `seed = base_seed + i` (M6.1.1) MUST remain pure functions of `(idx, base_seed)`. A regression test asserts `(cohort, seed)` records under `c=4` match the pre-fix harness's deterministic seed sequence (FR-002 + Acceptance Scenario 1.4).
- **No cross-cohort gather**: cohorts MUST iterate sequentially. A pattern like `await asyncio.gather(*(_one(cohort, idx) for cohort in cohorts for idx in batch_indices))` would yield peak `3 * c` (three cohorts × c), which violates the "peak in-flight = c" invariant (Acceptance Scenario 1.1 — equals 4, not 12).

## Versioning

This contract has no explicit version number. It is governed by the spec's clarification bullets and the `dispatch_mode` enum (which has exactly two values: `"sequential"`, `"concurrent"` — `"sequential"` is the absent-key default for pre-M6.0a manifests). Future changes to the dispatch invariant MUST start a new milestone (e.g., M6.0b) with its own spec cycle; the M6.0a contract is not designed for in-place evolution.
