"""M6.1.1 Modal sweep wrapper tests.

Tests the aggregator + Phase 1 / Phase 2(a) sweep wrappers via a mocked
driver context manager — no live Modal calls. The aggregator is exercised
on synthetic RPCResult lists with known timing values.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from typing import Any

import pytest
from vllm_grpc_bench.m6_1_1_sweep import (
    aggregate_multi_point_timings,
    run_m6_1_1_phase_1_sweep,
    run_m6_1_1_phase_2a_sweep,
)
from vllm_grpc_bench.m6_1_1_types import M6_1_1Cell, M6_1_1Cohort
from vllm_grpc_bench.m6_sweep import RPCResult
from vllm_grpc_bench.m6_types import EngineCostSpan

# --- aggregator -------------------------------------------------------------


def _result(
    *,
    success: bool = True,
    engine_ttft_ms: float | None = None,
    engine_forward_ms: float | None = None,
    timing_payload: dict[str, int] | None = None,
) -> RPCResult:
    return RPCResult(
        success=success,
        wall_clock_ms=100.0 if success else None,
        ttft_ms=engine_ttft_ms,
        engine_cost=EngineCostSpan(
            engine_forward_ms=engine_forward_ms,
            engine_ttft_ms=engine_ttft_ms,
            engine_tpot_ms=8.0 if engine_ttft_ms is not None else None,
        )
        if (engine_ttft_ms is not None or engine_forward_ms is not None)
        else None,
        failure_reason=None,
        m6_1_1_timing_payload=timing_payload,
    )


def _timing_payload(
    *,
    handler: int = 1_000_000,
    pre_engine: int = 2_500_000,
    first_chunk: int = 42_500_000,
    terminal: int = 44_000_000,
    perturbation: int = 240,
) -> dict[str, int]:
    return {
        "handler_entry_ns": handler,
        "pre_engine_ns": pre_engine,
        "first_chunk_ns": first_chunk,
        "terminal_emit_ns": terminal,
        "perturbation_audit_ns": perturbation,
    }


def test_aggregator_computes_mean_engine_ttft_for_chat_stream() -> None:
    cell = M6_1_1Cell(path="chat_stream", concurrency=1, hidden_size=4096)
    per_cohort: dict[M6_1_1Cohort, list[RPCResult]] = {
        "rest_https_edge": [
            _result(engine_ttft_ms=43.0, timing_payload=_timing_payload()) for _ in range(10)
        ],
        "default_grpc": [
            _result(engine_ttft_ms=47.0, timing_payload=_timing_payload()) for _ in range(10)
        ],
        "tuned_grpc_multiplexed": [
            _result(engine_ttft_ms=41.0, timing_payload=_timing_payload()) for _ in range(10)
        ],
    }
    timings = aggregate_multi_point_timings(per_cohort, cell)
    assert len(timings) == 3
    rest = next(t for t in timings if t.cohort == "rest_https_edge")
    assert rest.engine_ttft_ms_mean == pytest.approx(43.0)
    assert rest.per_segment.seg_ab_ms_mean == pytest.approx(1.5)
    assert rest.per_segment.seg_bc_ms_mean == pytest.approx(40.0)
    assert rest.per_segment.seg_cd_ms_mean == pytest.approx(1.5)
    assert rest.per_segment.n_samples == 10
    assert rest.perturbation_total_us_mean == pytest.approx(0.24)


def test_aggregator_uses_engine_forward_for_embed_cells() -> None:
    cell = M6_1_1Cell(path="embed", concurrency=1, hidden_size=4096)
    per_cohort: dict[M6_1_1Cohort, list[RPCResult]] = {
        "rest_https_edge": [
            _result(engine_forward_ms=338.0, timing_payload=_timing_payload()) for _ in range(5)
        ],
        "default_grpc": [
            _result(engine_forward_ms=340.0, timing_payload=_timing_payload()) for _ in range(5)
        ],
        "tuned_grpc_multiplexed": [
            _result(engine_forward_ms=337.0, timing_payload=_timing_payload()) for _ in range(5)
        ],
    }
    timings = aggregate_multi_point_timings(per_cohort, cell)
    rest = next(t for t in timings if t.cohort == "rest_https_edge")
    # engine_ttft_ms_mean field repurposed to carry engine_forward_ms_mean
    # for embed cells (the aggregate's path-discriminated semantics).
    assert rest.engine_ttft_ms_mean == pytest.approx(338.0)


def test_aggregator_handles_zero_samples_per_cohort() -> None:
    """Empty cohort → zero-filled aggregate; n_samples == 0."""
    cell = M6_1_1Cell(path="chat_stream", concurrency=1, hidden_size=4096)
    per_cohort: dict[M6_1_1Cohort, list[RPCResult]] = {
        "rest_https_edge": [],
        "default_grpc": [],
        "tuned_grpc_multiplexed": [],
    }
    timings = aggregate_multi_point_timings(per_cohort, cell)
    assert len(timings) == 3
    for t in timings:
        assert t.per_segment.n_samples == 0
        assert t.engine_ttft_ms_mean == 0.0


def test_aggregator_skips_failed_rpcs() -> None:
    """RPC failures contribute no samples to the aggregate."""
    cell = M6_1_1Cell(path="chat_stream", concurrency=1, hidden_size=4096)
    per_cohort: dict[M6_1_1Cohort, list[RPCResult]] = {
        "rest_https_edge": [
            _result(engine_ttft_ms=43.0, timing_payload=_timing_payload()),
            _result(success=False),
        ],
        "default_grpc": [
            _result(engine_ttft_ms=47.0, timing_payload=_timing_payload()),
        ],
        "tuned_grpc_multiplexed": [
            _result(engine_ttft_ms=41.0, timing_payload=_timing_payload()),
        ],
    }
    timings = aggregate_multi_point_timings(per_cohort, cell)
    rest = next(t for t in timings if t.cohort == "rest_https_edge")
    assert rest.per_segment.n_samples == 1


def test_aggregator_skips_rpcs_without_timing_payload() -> None:
    """RPCs missing m6_1_1_timing_payload (pre-M6.1.1 server) excluded from
    per-segment aggregates, but still contribute to engine_ttft_ms_mean."""
    cell = M6_1_1Cell(path="chat_stream", concurrency=1, hidden_size=4096)
    per_cohort: dict[M6_1_1Cohort, list[RPCResult]] = {
        "rest_https_edge": [
            _result(engine_ttft_ms=43.0, timing_payload=_timing_payload()),
            _result(engine_ttft_ms=44.0, timing_payload=None),
        ],
        "default_grpc": [],
        "tuned_grpc_multiplexed": [],
    }
    timings = aggregate_multi_point_timings(per_cohort, cell)
    rest = next(t for t in timings if t.cohort == "rest_https_edge")
    # engine_ttft_ms_mean uses both (43+44)/2 = 43.5
    assert rest.engine_ttft_ms_mean == pytest.approx(43.5)
    # per-segment uses only the one with timing data → n_samples==1
    assert rest.per_segment.n_samples == 1


# --- Phase 1 sweep wrapper -------------------------------------------------


def _fake_driver_factory(per_cell_per_cohort_ttft: dict[tuple[str, int], dict[str, float]]):
    """Return a fake `_open_endpoint_and_driver` context manager whose driver
    returns synthetic RPCResults parametrised by per-(cell, cohort) means."""

    @asynccontextmanager
    async def fake_factory(args, seq_len, base_seed):  # type: ignore[no-untyped-def]
        async def driver(cohort, m6_1_cell, seed):  # type: ignore[no-untyped-def]
            key = (m6_1_cell.path, m6_1_cell.concurrency)
            ttft = per_cell_per_cohort_ttft.get(key, {}).get(cohort, 44.0)
            return _result(
                engine_ttft_ms=ttft if m6_1_cell.path == "chat_stream" else None,
                engine_forward_ms=ttft if m6_1_cell.path == "embed" else None,
                timing_payload=_timing_payload(),
            )

        yield driver

    return fake_factory


def test_phase_1_sweep_returns_phase_1_run_record(tmp_path) -> None:
    args = argparse.Namespace(
        m6_1_1_model="Qwen/Qwen3-8B",
        m6_1_1_base_seed=42,
        m6_1_1_modal_region="eu-west-1",
        m6_1_1_modal_token_env="MODAL_BENCH_TOKEN",
    )
    record = asyncio.run(
        run_m6_1_1_phase_1_sweep(
            args,
            baseline={},
            driver_factory=_fake_driver_factory({}),
        )
    )
    assert record.n_per_cohort == 50
    # 6 cells × 3 cohorts = 18 multi_point_timings entries
    assert len(record.multi_point_timings) == 18
    # 3 chat_stream cells classified
    assert len(record.phase_1_classifications) == 3
    assert set(record.phase_1_classifications.keys()) == {
        "chat_stream_c1_h4096",
        "chat_stream_c4_h4096",
        "chat_stream_c8_h4096",
    }


def test_phase_1_sweep_classifies_drift_not_reproduced_when_uniform_ttft(tmp_path) -> None:
    """All 3 cohorts within 4% spread → drift_not_reproduced."""
    args = argparse.Namespace(
        m6_1_1_model="Qwen/Qwen3-8B",
        m6_1_1_base_seed=42,
    )
    ttfts = {
        ("chat_stream", c): {
            "rest_https_edge": 44.0,
            "default_grpc": 44.5,
            "tuned_grpc_multiplexed": 44.2,
        }
        for c in (1, 4, 8)
    }
    record = asyncio.run(
        run_m6_1_1_phase_1_sweep(args, baseline={}, driver_factory=_fake_driver_factory(ttfts))
    )
    for cls in record.phase_1_classifications.values():
        assert cls == "drift_not_reproduced"


# --- Phase 2(a) sweep wrapper ----------------------------------------------


def _m6_1_baseline_dict() -> dict[str, Any]:
    return {
        "schema_version": "m6_1.v1",
        "engine_cost_baseline": [
            {
                "cell": {"path": "embed", "concurrency": c, "hidden_size": 4096},
                "engine_cost_mean_ms": 338.0,
            }
            for c in (1, 4, 8)
        ],
    }


def test_phase_2a_sweep_returns_9_chat_stream_and_9_embed_baseline_cells(
    tmp_path,
) -> None:
    args = argparse.Namespace(
        m6_1_1_model="Qwen/Qwen3-8B",
        m6_1_1_base_seed=42,
    )
    # All cohorts produce identical embed engine_forward_ms == 338 → no warnings
    ttfts = {
        ("embed", c): {
            "rest_https_edge": 338.0,
            "default_grpc": 338.0,
            "tuned_grpc_multiplexed": 338.0,
        }
        for c in (1, 4, 8)
    }
    ttfts.update(
        {
            ("chat_stream", c): {
                "rest_https_edge": 42.0,
                "default_grpc": 42.0,
                "tuned_grpc_multiplexed": 42.0,
            }
            for c in (1, 4, 8)
        }
    )
    (
        cs_cells,
        embed_cells,
        embed_reg,
        drift_cleared,
        drift_warning,
        ctrl_warning,
        ctrl_note,
    ) = asyncio.run(
        run_m6_1_1_phase_2a_sweep(
            args,
            baseline=_m6_1_baseline_dict(),
            driver_factory=_fake_driver_factory(ttfts),
        )
    )
    assert len(cs_cells) == 9
    assert len(embed_cells) == 9
    assert embed_reg is not None
    assert embed_reg.n_warnings == 0
    # All 3 chat_stream cells cleared (zero spread)
    assert drift_cleared == {f"chat_stream_c{c}_h4096": True for c in (1, 4, 8)}
    assert ctrl_warning is True
    assert "round-1 Q2" in ctrl_note


def test_phase_2a_sweep_drift_not_cleared_when_spread_above_5pct(tmp_path) -> None:
    args = argparse.Namespace(
        m6_1_1_model="Qwen/Qwen3-8B",
        m6_1_1_base_seed=42,
    )
    ttfts = {
        ("chat_stream", 1): {
            "rest_https_edge": 40.0,
            "default_grpc": 50.0,  # ±11% spread → not cleared
            "tuned_grpc_multiplexed": 45.0,
        },
        ("chat_stream", 4): {
            "rest_https_edge": 42.0,
            "default_grpc": 42.0,
            "tuned_grpc_multiplexed": 42.0,
        },
        ("chat_stream", 8): {
            "rest_https_edge": 42.0,
            "default_grpc": 42.0,
            "tuned_grpc_multiplexed": 42.0,
        },
    }
    (_cs, _emb, _reg, drift_cleared, drift_warning, *_) = asyncio.run(
        run_m6_1_1_phase_2a_sweep(
            args, baseline=_m6_1_baseline_dict(), driver_factory=_fake_driver_factory(ttfts)
        )
    )
    assert drift_cleared["chat_stream_c1_h4096"] is False
    assert drift_warning["chat_stream_c1_h4096"] is True
    assert drift_cleared["chat_stream_c4_h4096"] is True


def test_phase_2a_sweep_embed_regression_fires_above_5pct(tmp_path) -> None:
    args = argparse.Namespace(
        m6_1_1_model="Qwen/Qwen3-8B",
        m6_1_1_base_seed=42,
    )
    ttfts = {
        ("embed", 1): {
            "rest_https_edge": 338.0,
            "default_grpc": 358.0,  # +5.9% drift vs baseline 338 → warning
            "tuned_grpc_multiplexed": 338.0,
        },
        ("embed", 4): {
            "rest_https_edge": 338.0,
            "default_grpc": 338.0,
            "tuned_grpc_multiplexed": 338.0,
        },
        ("embed", 8): {
            "rest_https_edge": 338.0,
            "default_grpc": 338.0,
            "tuned_grpc_multiplexed": 338.0,
        },
    }
    (_cs, embed_cells, embed_reg, *_) = asyncio.run(
        run_m6_1_1_phase_2a_sweep(
            args, baseline=_m6_1_baseline_dict(), driver_factory=_fake_driver_factory(ttfts)
        )
    )
    assert embed_reg is not None
    assert embed_reg.n_warnings >= 1
    # The default_grpc/embed_c1 cell is flagged
    warning_entry = next(
        e
        for e in embed_reg.per_entry
        if e.embed_regression_warning and e.cohort == "default_grpc" and e.cell.concurrency == 1
    )
    assert warning_entry.delta_pct > 0.05
    # And the embed_cells entry has regression_warning=True on that pair
    flagged_cell = next(
        e
        for e in embed_cells
        if e.cell.path == "embed" and e.cell.concurrency == 1 and e.cohort == "default_grpc"
    )
    assert flagged_cell.regression_warning is True
