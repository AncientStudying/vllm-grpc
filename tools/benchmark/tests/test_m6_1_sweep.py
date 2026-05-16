"""Tests for ``m6_1_sweep`` — sweep orchestrator wiring (T025)."""

from __future__ import annotations

import asyncio

import pytest
from vllm_grpc_bench.m6_1_sweep import (
    _MeasurementRpcIndexIterator,
    apply_chat_stream_drift_flags,
    build_differential_rows,
    build_supersedes_rows,
    run_full_sweep_with_driver,
    summarize_verdict_tally,
)
from vllm_grpc_bench.m6_1_types import (
    EngineCostAggregate,
    EngineCostSpan,
    M6_1Cell,
    M6_1CellRecord,
    M6_1PerCohortAggregate,
)
from vllm_grpc_bench.m6_sweep import RPCResult


def _fake_driver_factory(success_count_for_warmup: int = 999) -> object:
    """Returns an async callable suitable as an RPCDriver."""
    state = {"warmup_count": 0}

    async def driver(cohort: str, cell: object, seed: int) -> RPCResult:
        # Warmup RPCs carry seed=0; measurement RPCs have non-zero seeds.
        if seed == 0:
            state["warmup_count"] += 1
            if state["warmup_count"] > success_count_for_warmup:
                return RPCResult(
                    success=False,
                    wall_clock_ms=None,
                    ttft_ms=None,
                    engine_cost=None,
                    failure_reason="warmup cap",
                )
        # Deterministic synthetic latencies: rest_https_edge=200, default=150, grpc=100.
        wall = {
            "rest_https_edge": 200.0,
            "default_grpc": 150.0,
            "tuned_grpc_multiplexed": 100.0,
        }.get(cohort, 100.0)
        return RPCResult(
            success=True,
            wall_clock_ms=wall,
            ttft_ms=wall,
            engine_cost=EngineCostSpan(
                engine_forward_ms=5.0, engine_ttft_ms=5.0, engine_tpot_ms=1.0
            ),
            failure_reason=None,
        )

    return driver


def test_rpc_iter_skips_warmup() -> None:
    it = _MeasurementRpcIndexIterator()
    a = it.allocate(100)
    b = it.allocate(100)
    assert a[0] == 0
    assert a[-1] == 99
    assert b[0] == 100
    assert b[-1] == 199


@pytest.mark.asyncio
async def test_sweep_produces_six_cell_records() -> None:
    driver = _fake_driver_factory()
    deltas = {
        "embed_c1_h4096": 80.0,
        "embed_c4_h4096": 80.0,
        "embed_c8_h4096": 80.0,
        "chat_stream_c1_h4096": 80.0,
        "chat_stream_c4_h4096": 80.0,
        "chat_stream_c8_h4096": 80.0,
    }
    directions = {k: "grpc_wins" for k in deltas}
    cells, _measurements = await run_full_sweep_with_driver(
        driver, deltas, directions, base_seed=42
    )
    assert len(cells) == 6
    classifications = [c.classification for c in cells]
    # All cohorts pass with non-overlapping CIs (rest=200 vs grpc=100) →
    # verdict_survives in same direction (grpc_wins).
    assert all(c == "verdict_survives" for c in classifications)


@pytest.mark.asyncio
async def test_sweep_cell_incomplete_when_warmup_fails() -> None:
    driver = _fake_driver_factory(success_count_for_warmup=5)  # warmup pool of 5 only
    deltas = {
        "embed_c1_h4096": 80.0,
        "embed_c4_h4096": 80.0,
        "embed_c8_h4096": 80.0,
        "chat_stream_c1_h4096": 80.0,
        "chat_stream_c4_h4096": 80.0,
        "chat_stream_c8_h4096": 80.0,
    }
    directions = {k: "grpc_wins" for k in deltas}
    cells, _ = await run_full_sweep_with_driver(driver, deltas, directions)
    # First cell consumes warmup pool; remaining cells all get cell_incomplete
    # because warmup can't accumulate the floor.
    assert any(c.classification == "cell_incomplete" for c in cells)


def _embed_cell_record(concurrency: int) -> M6_1CellRecord:
    pc = {
        "rest_https_edge": M6_1PerCohortAggregate(
            cohort="rest_https_edge",
            n_attempted=100,
            n_successes=100,
            failure_count=0,
            classifier_metric_mean_ms=200.0,
            classifier_metric_ci_half_width_ms=1.0,
            total_wall_clock_mean_ms=200.0,
            total_wall_clock_ci_half_width_ms=1.0,
            engine_cost_mean=EngineCostAggregate(
                engine_forward_mean_ms=5.0, engine_forward_ci_half_width_ms=0.1
            ),
        ),
        "default_grpc": M6_1PerCohortAggregate(
            cohort="default_grpc",
            n_attempted=100,
            n_successes=100,
            failure_count=0,
            classifier_metric_mean_ms=150.0,
            classifier_metric_ci_half_width_ms=1.0,
            total_wall_clock_mean_ms=150.0,
            total_wall_clock_ci_half_width_ms=1.0,
            engine_cost_mean=EngineCostAggregate(
                engine_forward_mean_ms=5.0, engine_forward_ci_half_width_ms=0.1
            ),
        ),
        "tuned_grpc_multiplexed": M6_1PerCohortAggregate(
            cohort="tuned_grpc_multiplexed",
            n_attempted=100,
            n_successes=100,
            failure_count=0,
            classifier_metric_mean_ms=100.0,
            classifier_metric_ci_half_width_ms=1.0,
            total_wall_clock_mean_ms=100.0,
            total_wall_clock_ci_half_width_ms=1.0,
            engine_cost_mean=EngineCostAggregate(
                engine_forward_mean_ms=5.0, engine_forward_ci_half_width_ms=0.1
            ),
        ),
    }
    return M6_1CellRecord(
        cell=M6_1Cell(path="embed", hidden_size=4096, concurrency=concurrency),
        per_cohort=pc,
        classification="verdict_survives",
        classification_reason="synthetic",
        classifier_metric="wall_clock_ms",
        cohort_pair=("rest_https_edge", "tuned_grpc_multiplexed"),
        m6_winner_delta_ms=80.0,
        m6_winner_direction="grpc_wins",
        engine_cost_mean_ms=5.0,
        engine_cost_drift_warning=False,
        per_cohort_engine_cost_mean_ms=None,
        chat_stream_control_drift_warning=False,
    )


def test_apply_drift_flags_no_change_when_no_overlap_violation() -> None:
    cell = _embed_cell_record(1)
    out = apply_chat_stream_drift_flags([cell], [])
    assert out[0].chat_stream_control_drift_warning is False


def test_build_supersedes_rows_six_entries() -> None:
    cells = [_embed_cell_record(c) for c in (1, 4, 8)]
    cells.extend([_embed_cell_record(c) for c in (1, 4, 8)])  # mock chat_stream too
    rows = build_supersedes_rows(cells, {f"embed_c{c}_h4096": "grpc_wins" for c in (1, 4, 8)})
    assert len(rows) == 6
    assert all(r.m6_winner_cohort == "tuned_grpc_multiplexed" for r in rows[:3])


def test_summarize_verdict_tally_counts() -> None:
    cells = [_embed_cell_record(c) for c in (1, 4, 8)]
    tally = summarize_verdict_tally(cells)
    assert "3 verdict_survives" in tally


def test_build_differential_rows_populated_for_all_cells() -> None:
    cells = [_embed_cell_record(c) for c in (1, 4, 8)]
    rows = build_differential_rows(cells, [])
    assert len(rows) == 3
    for r in rows:
        assert "rest_https_edge" in r.per_cohort_classifier_metric_delta_ms
        assert "default_grpc" in r.per_cohort_classifier_metric_delta_ms
        assert "tuned_grpc_multiplexed" in r.per_cohort_classifier_metric_delta_ms


# Asyncio sanity — make sure pytest doesn't deadlock on the fake driver.
def test_sweep_does_not_deadlock() -> None:
    driver = _fake_driver_factory()
    deltas = {f"embed_c{c}_h4096": 80.0 for c in (1, 4, 8)} | {
        f"chat_stream_c{c}_h4096": 80.0 for c in (1, 4, 8)
    }
    directions = {k: "grpc_wins" for k in deltas}
    cells, _ = asyncio.run(run_full_sweep_with_driver(driver, deltas, directions))
    assert len(cells) == 6
