"""M6 per-RPC sampling-seed mapping (T018).

Per FR-025 / research R-7: ``SamplingParams.seed = M6_BASE_SEED + rpc_index``
where ``rpc_index`` is the global measurement-RPC counter (warmup excluded)
that increments in the round-robin per c-batch sequence; the same i-th
measurement RPC produces the same seed across all 3 cohorts within a cell.
"""

from __future__ import annotations

DEFAULT_M6_BASE_SEED: int = 42


def compute_rpc_seed(rpc_index: int, m6_base_seed: int = DEFAULT_M6_BASE_SEED) -> int:
    """Return the sampling seed for measurement RPC ``rpc_index``.

    ``rpc_index`` MUST be a non-negative integer that counts measurement RPCs
    across the full sweep (warmup RPCs do NOT advance the counter — they
    have no seed per FR-025).
    """
    if rpc_index < 0:
        raise ValueError(f"rpc_index must be >= 0, got {rpc_index}")
    return m6_base_seed + rpc_index


class MeasurementRpcIndexIterator:
    """Counts measurement RPCs across the whole sweep (warmup excluded).

    The same ``rpc_index`` is reused for the i-th measurement RPC across all
    3 cohorts within a cell, so the iterator is consumed cell-by-cell:
    advance ``M6_MEASUREMENT_N`` indices per cell, then the next cell's
    measurement RPCs start at the next index.

    Pattern::

        it = MeasurementRpcIndexIterator()
        for cell in cells:
            indices = it.allocate(M6_MEASUREMENT_N)
            # indices[i] is the same rpc_index for the i-th measurement RPC
            # in each of the 3 cohorts within this cell.

    The iterator does NOT advance during warmup; warmup RPCs carry
    ``rpc_index=None`` and ``seed=None`` per FR-025 / data-model.md.
    """

    def __init__(self) -> None:
        self._next: int = 0

    @property
    def next_index(self) -> int:
        return self._next

    def allocate(self, count: int) -> list[int]:
        """Allocate ``count`` consecutive measurement indices."""
        if count < 0:
            raise ValueError(f"count must be >= 0, got {count}")
        out = list(range(self._next, self._next + count))
        self._next += count
        return out


def build_global_rpc_index_iterator() -> MeasurementRpcIndexIterator:
    """Factory used by the sweep entry-point."""
    return MeasurementRpcIndexIterator()
