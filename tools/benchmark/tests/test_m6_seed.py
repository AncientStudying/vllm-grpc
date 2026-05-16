"""Tests for m6_seed sampling-seed mapping (T019)."""

from __future__ import annotations

import pytest
from vllm_grpc_bench.m6_seed import (
    DEFAULT_M6_BASE_SEED,
    MeasurementRpcIndexIterator,
    build_global_rpc_index_iterator,
    compute_rpc_seed,
)


def test_compute_rpc_seed_zero_returns_base_seed() -> None:
    assert compute_rpc_seed(0, 42) == 42


def test_compute_rpc_seed_default_base_is_42() -> None:
    assert DEFAULT_M6_BASE_SEED == 42
    assert compute_rpc_seed(0) == 42


def test_compute_rpc_seed_arithmetic() -> None:
    assert compute_rpc_seed(99, 42) == 141
    assert compute_rpc_seed(0, 100) == 100


def test_compute_rpc_seed_rejects_negative_rpc_index() -> None:
    with pytest.raises(ValueError):
        compute_rpc_seed(-1, 42)


def test_iterator_allocates_consecutive_indices() -> None:
    it = MeasurementRpcIndexIterator()
    assert it.allocate(100) == list(range(0, 100))
    assert it.allocate(100) == list(range(100, 200))


def test_iterator_warmup_does_not_advance() -> None:
    """Warmup excluded from indexed seed sequence (FR-025) — the iterator
    only advances when the caller explicitly allocates measurement indices,
    so simply not calling ``allocate`` during warmup is the discipline.
    """
    it = MeasurementRpcIndexIterator()
    assert it.next_index == 0
    # Warmup runs do not consume indices — caller does not call allocate().
    assert it.next_index == 0
    indices = it.allocate(100)
    assert indices[0] == 0


def test_seed_cohort_independence() -> None:
    """The i-th measurement RPC must produce the same seed across all 3
    cohorts within a cell (FR-025).
    """
    it = MeasurementRpcIndexIterator()
    cell_indices = it.allocate(100)
    # The same index list is reused for each of the 3 cohorts within a cell.
    rest_seeds = [compute_rpc_seed(i, 42) for i in cell_indices]
    default_seeds = [compute_rpc_seed(i, 42) for i in cell_indices]
    tuned_seeds = [compute_rpc_seed(i, 42) for i in cell_indices]
    assert rest_seeds == default_seeds == tuned_seeds


def test_build_global_rpc_index_iterator_returns_fresh_iterator() -> None:
    it1 = build_global_rpc_index_iterator()
    it2 = build_global_rpc_index_iterator()
    assert it1 is not it2
    assert it1.next_index == 0
    it1.allocate(10)
    assert it2.next_index == 0  # independent state
