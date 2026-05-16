"""Tests for the M6.1 smoke gate (T034)."""

from __future__ import annotations

import io

import pytest
from vllm_grpc_bench.m6_1_smoke import (
    emit_smoke_summary,
    run_smoke_with_driver,
    smoke_exit_code,
)
from vllm_grpc_bench.m6_1_types import EngineCostSpan
from vllm_grpc_bench.m6_sweep import RPCResult


def _always_ok_driver_factory() -> object:
    async def driver(cohort: str, cell: object, seed: int) -> RPCResult:
        return RPCResult(
            success=True,
            wall_clock_ms=10.0,
            ttft_ms=10.0,
            engine_cost=EngineCostSpan(engine_forward_ms=1.0, engine_ttft_ms=1.0),
            failure_reason=None,
        )

    return driver


def _always_fail_driver_factory() -> object:
    async def driver(cohort: str, cell: object, seed: int) -> RPCResult:
        return RPCResult(
            success=False,
            wall_clock_ms=None,
            ttft_ms=None,
            engine_cost=None,
            failure_reason="synthetic failure",
        )

    return driver


def _one_cohort_fails_driver_factory(failing_cohort: str = "rest_https_edge") -> object:
    async def driver(cohort: str, cell: object, seed: int) -> RPCResult:
        if cohort == failing_cohort:
            return RPCResult(
                success=False,
                wall_clock_ms=None,
                ttft_ms=None,
                engine_cost=None,
                failure_reason="cohort failure",
            )
        return RPCResult(
            success=True,
            wall_clock_ms=10.0,
            ttft_ms=10.0,
            engine_cost=EngineCostSpan(engine_forward_ms=1.0, engine_ttft_ms=1.0),
            failure_reason=None,
        )

    return driver


@pytest.mark.asyncio
async def test_smoke_all_ok_returns_exit_zero() -> None:
    driver = _always_ok_driver_factory()
    result = await run_smoke_with_driver(driver)
    assert result.overall_status == "ok"
    assert smoke_exit_code(result) == 0
    assert len(result.outcomes) == 6


@pytest.mark.asyncio
async def test_smoke_one_pair_fails_returns_exit_one() -> None:
    driver = _one_cohort_fails_driver_factory("rest_https_edge")
    result = await run_smoke_with_driver(driver)
    assert result.overall_status == "failed"
    assert smoke_exit_code(result) == 1
    # 2 cells × 1 failing cohort = 2 failed outcomes, 4 ok.
    statuses = [o.status for o in result.outcomes]
    assert statuses.count("failed") == 2
    assert statuses.count("ok") == 4


@pytest.mark.asyncio
async def test_smoke_emits_drift_check_deferral_note() -> None:
    driver = _always_ok_driver_factory()
    result = await run_smoke_with_driver(driver)
    buf = io.StringIO()
    emit_smoke_summary(result, stream=buf)
    out = buf.getvalue()
    assert "chat_stream control-drift check is full-sweep-only" in out
    assert "FR-012/FR-029" in out


@pytest.mark.asyncio
async def test_smoke_emits_one_line_per_pair() -> None:
    driver = _always_ok_driver_factory()
    result = await run_smoke_with_driver(driver)
    buf = io.StringIO()
    emit_smoke_summary(result, stream=buf)
    pair_lines = [line for line in buf.getvalue().splitlines() if line.startswith("cell=")]
    assert len(pair_lines) == 6


@pytest.mark.asyncio
async def test_smoke_does_not_call_chat_stream_drift_check() -> None:
    """FR-012 mandate: smoke must NOT call check_chat_stream_control_drift."""
    from vllm_grpc_bench import m6_1_drift_check

    called = {"count": 0}
    original = m6_1_drift_check.check_chat_stream_control_drift

    def counter(*args: object, **kwargs: object) -> dict:
        called["count"] += 1
        return original(*args, **kwargs)  # type: ignore[no-any-return,arg-type]

    m6_1_drift_check.check_chat_stream_control_drift = counter  # type: ignore[assignment]
    try:
        driver = _always_ok_driver_factory()
        await run_smoke_with_driver(driver)
        assert called["count"] == 0
    finally:
        m6_1_drift_check.check_chat_stream_control_drift = original  # type: ignore[assignment]
