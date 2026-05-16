"""Tests for the M6 sweep orchestrator (T029, T030).

Covers:
- Round-robin per c-batch sequencer at c=1, c=4, c=8 (Research R-8 / R-9).
- Warmup follows the same rotation (FR-022).
- Per-RPC retry semantics + cell_incomplete marking (FR-023).
- Seed mapping: same rpc_index → same seed across all 3 cohorts (FR-025).
- chat_stream RPCs carry the right ttft (mock drivers verify the spec
  contract; the actual SamplingParams.max_tokens=50 enforcement happens
  in the production driver, not in the sweep orchestrator).
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.m6_seed import MeasurementRpcIndexIterator
from vllm_grpc_bench.m6_sweep import (
    RPCDriver,
    RPCResult,
    _c_batch_sizes_for_measurement,
    _c_batch_sizes_for_warmup,
    run_cell,
)
from vllm_grpc_bench.m6_types import EngineCostSpan, M6Cell, M6CohortKind


def _baseline() -> dict[str, object]:
    """Minimal baseline with all 6 M6 cells as no_winner."""
    verdicts: list[dict[str, object]] = []
    for path in ("embed", "chat_stream"):
        verdicts.append(
            {
                "path": path,
                "hidden_size": 4096,
                "concurrency": 1,
                "grpc_cohort": "tuned_grpc",
                "rest_cohort": "rest_https_edge",
                "delta_median_ms": 0.0,
                "ci_lower_ms": 0.0,
                "ci_upper_ms": 0.0,
                "verdict": "no_winner",
            }
        )
        for c in (4, 8):
            verdicts.append(
                {
                    "path": path,
                    "hidden_size": 4096,
                    "concurrency": c,
                    "grpc_cohort": "tuned_grpc_multiplexed",
                    "rest_cohort": "rest_https_edge",
                    "delta_median_ms": 0.0,
                    "ci_lower_ms": 0.0,
                    "ci_upper_ms": 0.0,
                    "verdict": "no_winner",
                }
            )
    return {"protocol_comparison_verdicts": verdicts}


# --- c-batch sequencer (Research R-8, R-9) -----------------------------------


def test_c_batch_sizes_at_c1() -> None:
    sizes = _c_batch_sizes_for_measurement(c=1)
    assert sizes == [1] * 100
    assert sum(sizes) == 100


def test_c_batch_sizes_at_c4() -> None:
    sizes = _c_batch_sizes_for_measurement(c=4)
    assert sizes == [4] * 25
    assert sum(sizes) == 100


def test_c_batch_sizes_at_c8_uses_r9_truncation_rule() -> None:
    """At c=8 (n=100), Research R-9 mandates 12 full rounds + a final round
    of 4 to keep n=100 exact (FR-004).
    """
    sizes = _c_batch_sizes_for_measurement(c=8)
    assert sizes == [8] * 12 + [4]
    assert sum(sizes) == 100


def test_warmup_c_batch_sizes_at_c8() -> None:
    """Warmup at c=8 (n=10): 1 round of 8 + 1 round of 2."""
    sizes = _c_batch_sizes_for_warmup(c=8)
    assert sizes == [8, 2]
    assert sum(sizes) == 10


def test_warmup_c_batch_sizes_at_c1_and_c4() -> None:
    """Warmup uses the same per-c-batch rotation as measurement (FR-022).

    At c=1: 10 rounds of 1 RPC each (no concurrent fan-out possible).
    At c=4: 2 rounds of 4 + 1 final round of 2 (total 10).
    """
    assert _c_batch_sizes_for_warmup(c=1) == [1] * 10
    assert _c_batch_sizes_for_warmup(c=4) == [4, 4, 2]


# --- Mock drivers + run_cell --------------------------------------------------


def _fake_engine_cost(path: str) -> EngineCostSpan:
    if path == "embed":
        return EngineCostSpan(engine_forward_ms=12.0)
    return EngineCostSpan(engine_ttft_ms=200.0, engine_tpot_ms=30.0)


def _make_success_driver() -> tuple[RPCDriver, list[tuple[M6CohortKind, int]]]:
    """Driver that always succeeds, recording (cohort, seed) call order."""
    calls: list[tuple[M6CohortKind, int]] = []

    async def driver(cohort: M6CohortKind, cell: M6Cell, seed: int) -> RPCResult:
        calls.append((cohort, seed))
        return RPCResult(
            success=True,
            wall_clock_ms=100.0,
            ttft_ms=50.0 if cell.path == "chat_stream" else None,
            engine_cost=_fake_engine_cost(cell.path),
            failure_reason=None,
        )

    return driver, calls


@pytest.mark.asyncio
async def test_run_cell_measurement_n_is_exactly_100_at_c1() -> None:
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=1)
    driver, calls = _make_success_driver()
    rpc_iter = MeasurementRpcIndexIterator()
    record, measurements = await run_cell(driver, cell, rpc_iter, _baseline())
    for kind in ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"):
        kind_typed: M6CohortKind = kind
        assert len(measurements[kind_typed]) == 100
    assert record.classification in (
        "verdict_survives",
        "verdict_changed",
        "verdict_buried_by_engine",
        "no_winner_at_n100",
    )


@pytest.mark.asyncio
async def test_run_cell_measurement_n_is_exactly_100_at_c8() -> None:
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=8)
    driver, _calls = _make_success_driver()
    rpc_iter = MeasurementRpcIndexIterator()
    _, measurements = await run_cell(driver, cell, rpc_iter, _baseline())
    for kind in ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"):
        kind_typed: M6CohortKind = kind
        assert len(measurements[kind_typed]) == 100


@pytest.mark.asyncio
async def test_seed_cohort_independence_within_cell() -> None:
    """FR-025: the i-th measurement RPC produces the same seed across all
    3 cohorts within a cell.
    """
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=1)
    driver, _ = _make_success_driver()
    rpc_iter = MeasurementRpcIndexIterator()
    _, measurements = await run_cell(driver, cell, rpc_iter, _baseline())
    rest = measurements["rest_https_edge"]
    default = measurements["default_grpc"]
    tuned = measurements["tuned_grpc_multiplexed"]
    for i in range(100):
        assert rest[i].seed == default[i].seed == tuned[i].seed


@pytest.mark.asyncio
async def test_seed_matches_base_seed_plus_rpc_index() -> None:
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=1)
    driver, _ = _make_success_driver()
    rpc_iter = MeasurementRpcIndexIterator()
    _, measurements = await run_cell(driver, cell, rpc_iter, _baseline(), base_seed=42)
    rest = measurements["rest_https_edge"]
    for i, m in enumerate(rest):
        assert m.seed == 42 + i


@pytest.mark.asyncio
async def test_cell_incomplete_when_cohort_below_floor() -> None:
    """T030: inject failures such that one cohort lands at n_successes=79
    after 3 retries; cell must be marked cell_incomplete (FR-023).
    """
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=1)

    # Track how many measurement RPCs per cohort have been seen so we can
    # tank exactly enough to land at n_successes=79 for default_grpc.
    counts: dict[M6CohortKind, int] = {
        "rest_https_edge": 0,
        "default_grpc": 0,
        "tuned_grpc_multiplexed": 0,
    }

    async def driver(cohort: M6CohortKind, cell_: M6Cell, seed: int) -> RPCResult:
        counts[cohort] += 1
        # First 21 measurement attempts (across all retries) for default_grpc fail.
        # With max_retries=3 we burn 4 attempts per RPC; the first ~6 RPCs all fail.
        # Simplest: fail every attempt on default_grpc for the first 84 attempts
        # (21 RPCs × 4 attempts), then succeed.
        if cohort == "default_grpc" and counts[cohort] <= 84:
            return RPCResult(
                success=False,
                wall_clock_ms=None,
                ttft_ms=None,
                engine_cost=None,
                failure_reason="synthetic_failure",
            )
        return RPCResult(
            success=True,
            wall_clock_ms=100.0,
            ttft_ms=None,
            engine_cost=_fake_engine_cost(cell_.path),
            failure_reason=None,
        )

    rpc_iter = MeasurementRpcIndexIterator()
    record, _meas = await run_cell(driver, cell, rpc_iter, _baseline())
    assert record.classification == "cell_incomplete"


@pytest.mark.asyncio
async def test_per_rpc_retry_counts() -> None:
    """An RPC that fails twice and succeeds on the third attempt has
    ``retry_count == 2`` recorded on the M6RPCMeasurement.
    """
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=1)
    state = {"attempt": 0}

    async def driver(cohort: M6CohortKind, cell_: M6Cell, seed: int) -> RPCResult:
        # Only inject retries on default_grpc, only on the very first RPC.
        if cohort == "default_grpc" and seed == 42 and state["attempt"] < 2:
            state["attempt"] += 1
            return RPCResult(
                success=False,
                wall_clock_ms=None,
                ttft_ms=None,
                engine_cost=None,
                failure_reason="transient",
            )
        return RPCResult(
            success=True,
            wall_clock_ms=100.0,
            ttft_ms=None,
            engine_cost=_fake_engine_cost(cell_.path),
            failure_reason=None,
        )

    rpc_iter = MeasurementRpcIndexIterator()
    _record, measurements = await run_cell(driver, cell, rpc_iter, _baseline())
    default = measurements["default_grpc"]
    # First measurement RPC at seed=42 should have retry_count=2.
    assert default[0].retry_count == 2
    assert default[0].success is True


@pytest.mark.asyncio
async def test_chat_stream_records_ttft() -> None:
    cell = M6Cell(path="chat_stream", hidden_size=4096, concurrency=1)
    driver, _ = _make_success_driver()
    rpc_iter = MeasurementRpcIndexIterator()
    _, measurements = await run_cell(driver, cell, rpc_iter, _baseline())
    for m in measurements["rest_https_edge"]:
        assert m.ttft_ms == 50.0
