"""T009 — ``serve_in_process_adapter`` parity with ``serve_in_process``.

The adapter is a thin ``EndpointProvider``-conforming wrapper around the
existing M3 in-process server bring-up: same gRPC server, same servicers,
same loopback bind. It yields an ``(addr, None, None)`` tuple — insecure
channel, no per-RPC metadata — so M4 callers that supply no explicit
``endpoint_provider`` keep producing bit-identical cohorts (T010 covers the
end-to-end sweep equivalence; this file covers the adapter-level contract).
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.m3_sweep import serve_in_process, serve_in_process_adapter
from vllm_grpc_bench.m3_types import BenchmarkCell
from vllm_grpc_bench.m4_sweep import _measure_cell
from vllm_grpc_bench.mock_engine import MockEngine, MockEngineConfig


@pytest.mark.asyncio
async def test_adapter_yields_endpoint_tuple_with_none_credentials_and_metadata() -> None:
    """The adapter yields ``(addr, None, None)`` — credentials and metadata are
    deliberately absent so M4's in-process driver stays on the insecure-channel
    code path that produced the published M4 numbers.
    """
    engine = MockEngine(MockEngineConfig(hidden_size=2048, seed=0))
    async with serve_in_process_adapter(engine, M1_BASELINE) as (target, credentials, metadata):
        assert isinstance(target, str)
        assert target.startswith("127.0.0.1:"), f"expected loopback target, got {target!r}"
        # Port portion is a positive integer assigned by the OS.
        port_str = target.split(":", 1)[1]
        assert port_str.isdigit() and int(port_str) > 0
        assert credentials is None
        assert metadata is None


@pytest.mark.asyncio
async def test_adapter_address_shape_matches_serve_in_process() -> None:
    """The adapter's yielded address has the same shape (``127.0.0.1:<port>``)
    as ``serve_in_process`` — same server bring-up, same port-assignment
    strategy, same lifecycle.
    """
    engine = MockEngine(MockEngineConfig(hidden_size=2048, seed=0))
    async with serve_in_process(engine, M1_BASELINE) as addr_direct:
        assert addr_direct.startswith("127.0.0.1:")
    async with serve_in_process_adapter(engine, M1_BASELINE) as (
        addr_adapter,
        _credentials,
        _metadata,
    ):
        assert addr_adapter.startswith("127.0.0.1:")
    # Ports differ run-to-run (OS-assigned), but the prefix shape is identical.


@pytest.mark.asyncio
async def test_measure_cell_with_explicit_adapter_produces_matching_cohort_shape() -> None:
    """Running ``_measure_cell`` once with the default ``endpoint_provider`` and
    once with an explicit ``serve_in_process_adapter`` produces cohorts with
    identical structural fingerprints (cell_id, sample count, measurability).

    Wall-clock timings necessarily differ between two measurements; this test
    asserts the cohort *shape* is preserved by the adapter abstraction.
    """
    cell = BenchmarkCell(
        path="embed",
        hidden_size=2048,
        channel_config=M1_BASELINE,
        corpus_subset="m1_embed",
        iterations=12,
    )
    default_cohort = await _measure_cell(cell, seed=0, pace_tokens=False, warmup_n=0)
    explicit_cohort = await _measure_cell(
        cell,
        seed=0,
        pace_tokens=False,
        warmup_n=0,
        endpoint_provider=serve_in_process_adapter,
    )

    assert default_cohort.cell.cell_id == explicit_cohort.cell.cell_id
    assert len(default_cohort.samples) == len(explicit_cohort.samples) == 12
    assert default_cohort.measurable == explicit_cohort.measurable
    assert default_cohort.n_successful == explicit_cohort.n_successful
    # Cohorts produced by the adapter must carry the same defaults as the
    # legacy path on every M5-introduced optional field.
    for c in (default_cohort, explicit_cohort):
        assert c.rtt_record is None
        assert c.server_overhead_estimate_ms is None
        assert c.server_bound is False
        assert c.low_rtt_caveat is False
        assert c.discarded is False
