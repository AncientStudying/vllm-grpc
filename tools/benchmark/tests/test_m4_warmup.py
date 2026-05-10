"""US1 — baseline-warmup behavior on ``_measure_cell``.

The warmup pass discards the first ``warmup_n`` RPCs per cohort so cold-start
cost (channel setup, first-RPC HTTP/2 negotiation, protobuf descriptor
caches) is paid before sampling begins. The returned cohort must have
exactly ``cell.iterations`` samples regardless of warmup.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.m3_types import BenchmarkCell, M4SweepConfig
from vllm_grpc_bench.m4_sweep import _measure_cell


@pytest.mark.asyncio
async def test_measure_cell_with_warmup_returns_iterations_samples() -> None:
    cell = BenchmarkCell(
        path="embed",
        hidden_size=2048,
        channel_config=M1_BASELINE,
        corpus_subset="m1_embed",
        iterations=15,
    )
    cohort = await _measure_cell(cell, seed=0, pace_tokens=False, warmup_n=5)
    # Aggregator was given exactly cell.iterations measured samples.
    assert len(cohort.samples) == 15
    assert cohort.cell.iterations == 15
    # n_successful is bounded by cell.iterations (not cell.iterations + warmup_n).
    assert cohort.n_successful <= 15


@pytest.mark.asyncio
async def test_measure_cell_warmup_zero_matches_unwarmed_count() -> None:
    cell = BenchmarkCell(
        path="embed",
        hidden_size=2048,
        channel_config=M1_BASELINE,
        corpus_subset="m1_embed",
        iterations=12,
    )
    cohort = await _measure_cell(cell, seed=0, pace_tokens=False, warmup_n=0)
    assert len(cohort.samples) == 12


def test_warmup_n_default_in_sweep_config() -> None:
    cfg = M4SweepConfig()
    assert cfg.warmup_n == 10


def test_warmup_n_negative_rejected() -> None:
    with pytest.raises(ValueError, match="warmup_n"):
        M4SweepConfig(warmup_n=-1)
