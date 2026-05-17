"""M6.0a — Regression tests for concurrent in-flight dispatch.

See ``specs/024-m6-0a-concurrent-dispatch/contracts/dispatch.md`` for the
invariant: within a single (cell × cohort) measurement the harness MUST
dispatch RPCs so that the peak number of simultaneously in-flight RPCs
equals ``cell.concurrency``. These tests parametrise the path-agnostic
``_ConcurrencyProbe`` over the three measurement-loop entry points
(``m6_sweep._run_measurement``, ``m6_1_sweep._run_measurement_m6_1``, and
``m6_1_1_sweep._measure_cell``) plus the three warmup entry points, and
assert ``probe.peak == cell.concurrency`` (FR-001, FR-003, FR-005a).

The seed-determinism subset asserts FR-002: ``compute_rpc_seed(idx,
base_seed)`` is a pure function of ``(idx, base_seed)``, so the SET of
``(cohort, seed)`` pairs emitted under concurrent dispatch matches the
deterministic sequence emitted under sequential dispatch.

Parametrisation count:

* peak-in-flight: 3 concurrency levels (1, 4, 8) × 3 entry points = 9
* warmup-symmetry: 1 concurrency level (4) × 3 entry points = 3
* seed-determinism: 2 concurrency levels (1, 4) × 3 entry points = 6
* total = 18
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from vllm_grpc_bench.m6_1_1_sweep import _measure_cell
from vllm_grpc_bench.m6_1_1_types import M6_1_1_BASE_SEED, M6_1_1Cell
from vllm_grpc_bench.m6_1_seed import DEFAULT_M6_1_BASE_SEED
from vllm_grpc_bench.m6_1_seed import compute_rpc_seed as compute_rpc_seed_m6_1
from vllm_grpc_bench.m6_1_sweep import _run_measurement_m6_1, _run_warmup_m6_1
from vllm_grpc_bench.m6_1_types import M6_1Cell
from vllm_grpc_bench.m6_seed import DEFAULT_M6_BASE_SEED
from vllm_grpc_bench.m6_seed import compute_rpc_seed as compute_rpc_seed_m6
from vllm_grpc_bench.m6_sweep import (
    RPCResult,
    _run_measurement,
    _run_warmup,
)
from vllm_grpc_bench.m6_types import M6_COHORTS, M6Cell

# ----------------------------------------------------------------------------
# In-Flight Concurrency Probe (per contracts/dispatch.md)
# ----------------------------------------------------------------------------


class _ConcurrencyProbe:
    """Counting fake ``RPCDriver`` that records peak in-flight + per-call records.

    Conforms to the project's ``RPCDriver`` callable signature
    ``(cohort, cell, seed) -> Awaitable[RPCResult]`` so the same probe
    instance drives M6, M6.1, and M6.1.1 measurement loops uniformly.

    The ``await asyncio.sleep(0)`` yield is load-bearing: it lets sibling
    coroutines within an ``asyncio.gather(...)`` enter ``__call__`` before
    any one of them exits. Without it the probe would register ``peak == c``
    even under sequential dispatch because each task entered briefly before
    the next started — the sleep yield enforces real overlap.
    """

    def __init__(self) -> None:
        self.in_flight: int = 0
        self.peak: int = 0
        self.records: list[tuple[str, int]] = []

    async def __call__(self, cohort: Any, cell: Any, seed: int) -> RPCResult:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        self.records.append((str(cohort), seed))
        try:
            await asyncio.sleep(0)
            return RPCResult(
                success=True,
                wall_clock_ms=1.0,
                ttft_ms=0.5,
                engine_cost=None,
                failure_reason=None,
            )
        finally:
            self.in_flight -= 1


# ----------------------------------------------------------------------------
# Peak in-flight tests (FR-001, FR-003, Acceptance Scenarios 1.1 / 1.2 / 1.3)
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 4, 8])
async def test_m6_measurement_peak_in_flight_equals_c(concurrency: int) -> None:
    probe = _ConcurrencyProbe()
    cell = M6Cell(path="chat_stream", hidden_size=4096, concurrency=concurrency)  # type: ignore[arg-type]
    rpc_indices = list(range(concurrency * 2))
    await _run_measurement(probe, cell, rpc_indices, DEFAULT_M6_BASE_SEED)
    assert probe.peak == concurrency, (
        f"m6 _run_measurement c={concurrency}: peak={probe.peak} (expected {concurrency})"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 4, 8])
async def test_m6_1_measurement_peak_in_flight_equals_c(concurrency: int) -> None:
    probe = _ConcurrencyProbe()
    cell = M6_1Cell(path="chat_stream", hidden_size=4096, concurrency=concurrency)  # type: ignore[arg-type]
    rpc_indices = list(range(concurrency * 2))
    await _run_measurement_m6_1(probe, cell, rpc_indices, DEFAULT_M6_1_BASE_SEED)
    assert probe.peak == concurrency, (
        f"m6_1 _run_measurement_m6_1 c={concurrency}: peak={probe.peak} (expected {concurrency})"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 4, 8])
async def test_m6_1_1_measurement_peak_in_flight_equals_c(concurrency: int) -> None:
    probe = _ConcurrencyProbe()
    cell = M6_1_1Cell(path="chat_stream", hidden_size=4096, concurrency=concurrency)  # type: ignore[arg-type]
    # n_warmup=1 keeps the warmup peak at 1 so the measurement peak dominates;
    # n_measurement=concurrency*2 ensures the semaphore-bounded gather has
    # enough work to actually saturate to c concurrent tasks.
    await _measure_cell(
        probe,
        cell,
        n_measurement=concurrency * 2,
        n_warmup=1,
        base_seed=M6_1_1_BASE_SEED,
    )
    assert probe.peak == concurrency, (
        f"m6_1_1 _measure_cell c={concurrency}: peak={probe.peak} (expected {concurrency})"
    )


# ----------------------------------------------------------------------------
# Warmup symmetry tests (FR-005a — warmup must dispatch concurrently too)
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m6_warmup_peak_in_flight_at_c4() -> None:
    probe = _ConcurrencyProbe()
    cell = M6Cell(path="chat_stream", hidden_size=4096, concurrency=4)
    await _run_warmup(probe, cell)
    assert probe.peak == 4, f"m6 _run_warmup c=4: peak={probe.peak} (expected 4)"


@pytest.mark.asyncio
async def test_m6_1_warmup_peak_in_flight_at_c4() -> None:
    probe = _ConcurrencyProbe()
    cell = M6_1Cell(path="chat_stream", hidden_size=4096, concurrency=4)
    await _run_warmup_m6_1(probe, cell)
    assert probe.peak == 4, f"m6_1 _run_warmup_m6_1 c=4: peak={probe.peak} (expected 4)"


@pytest.mark.asyncio
async def test_m6_1_1_warmup_peak_in_flight_at_c4() -> None:
    probe = _ConcurrencyProbe()
    cell = M6_1_1Cell(path="chat_stream", hidden_size=4096, concurrency=4)
    # n_warmup=4 = c so the warmup gather saturates to peak=4; n_measurement=1
    # keeps the measurement peak strictly below the warmup peak.
    await _measure_cell(probe, cell, n_measurement=1, n_warmup=4, base_seed=M6_1_1_BASE_SEED)
    assert probe.peak == 4, f"m6_1_1 _measure_cell warmup c=4: peak={probe.peak} (expected 4)"


# ----------------------------------------------------------------------------
# Seed-determinism tests (FR-002 — concurrent dispatch preserves the deterministic
# seed sequence; only the emission ORDER varies, the SET of (cohort, seed) records
# is bit-identical to the pre-fix harness)
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 4])
async def test_m6_seed_set_preserved_under_dispatch(concurrency: int) -> None:
    probe = _ConcurrencyProbe()
    cell = M6Cell(path="chat_stream", hidden_size=4096, concurrency=concurrency)  # type: ignore[arg-type]
    n_indices = concurrency * 2
    rpc_indices = list(range(n_indices))
    await _run_measurement(probe, cell, rpc_indices, DEFAULT_M6_BASE_SEED)
    expected = {
        (cohort, compute_rpc_seed_m6(idx, DEFAULT_M6_BASE_SEED))
        for cohort in M6_COHORTS
        for idx in rpc_indices
    }
    assert set(probe.records) == expected, (
        f"m6 c={concurrency}: emitted (cohort, seed) set differs from expected; "
        f"missing={expected - set(probe.records)}, "
        f"extra={set(probe.records) - expected}"
    )
    assert len(probe.records) == len(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 4])
async def test_m6_1_seed_set_preserved_under_dispatch(concurrency: int) -> None:
    probe = _ConcurrencyProbe()
    cell = M6_1Cell(path="chat_stream", hidden_size=4096, concurrency=concurrency)  # type: ignore[arg-type]
    n_indices = concurrency * 2
    rpc_indices = list(range(n_indices))
    await _run_measurement_m6_1(probe, cell, rpc_indices, DEFAULT_M6_1_BASE_SEED)
    expected = {
        (cohort, compute_rpc_seed_m6_1(idx, DEFAULT_M6_1_BASE_SEED))
        for cohort in M6_COHORTS
        for idx in rpc_indices
    }
    assert set(probe.records) == expected, (
        f"m6_1 c={concurrency}: emitted (cohort, seed) set differs from expected; "
        f"missing={expected - set(probe.records)}, "
        f"extra={set(probe.records) - expected}"
    )
    assert len(probe.records) == len(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 4])
async def test_m6_1_1_seed_set_preserved_under_dispatch(concurrency: int) -> None:
    probe = _ConcurrencyProbe()
    cell = M6_1_1Cell(path="chat_stream", hidden_size=4096, concurrency=concurrency)  # type: ignore[arg-type]
    n_measurement = concurrency * 2
    # n_warmup=0 isolates the measurement seed sequence (warmup carries seed=0
    # which is the smoke/warmup convention per feedback_smoke_warmup_seed_zero).
    await _measure_cell(
        probe,
        cell,
        n_measurement=n_measurement,
        n_warmup=0,
        base_seed=M6_1_1_BASE_SEED,
    )
    # M6.1.1 uses the simpler ``seed = base_seed + i`` mapping (no
    # compute_rpc_seed shim) — match that exactly.
    expected = {
        (cohort, M6_1_1_BASE_SEED + i) for cohort in M6_COHORTS for i in range(n_measurement)
    }
    assert set(probe.records) == expected, (
        f"m6_1_1 c={concurrency}: emitted (cohort, seed) set differs from expected; "
        f"missing={expected - set(probe.records)}, "
        f"extra={set(probe.records) - expected}"
    )
    assert len(probe.records) == len(expected)
