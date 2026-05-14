"""T022 — REST cohort dual-transport extension (M5.2).

Asserts that the ``network_path`` kwarg on ``run_rest_cohort`` and
``probe_rest_rtt`` plumbs the M5.2-specific HTTPS-edge provenance through
the cohort result. The cohort runner returns a ``RESTCohortResult`` whose
``network_path`` field labels which Modal tunnel the cohort traversed;
when ``network_path="https_edge"`` the ``https_edge_record`` carries the
M5.2-specific HTTPS-edge fields (endpoint, RTT, geolocation).
"""

from __future__ import annotations

import httpx
from vllm_grpc_bench.mock_engine import MockEngine, MockEngineConfig
from vllm_grpc_bench.rest_cohort import (
    _build_limits,
    probe_rest_rtt,
    run_rest_cohort,
)
from vllm_grpc_bench.rest_shim import build_rest_shim

_TEST_TOKEN = "test-bearer-abcdef0123"
_BASE_URL = "http://test"


def _build_test_client(hidden_size: int = 2048, c: int = 1) -> httpx.AsyncClient:
    engine = MockEngine(
        MockEngineConfig(
            hidden_size=hidden_size,
            seed=0,
            tokens_per_second=200.0,
            max_tokens_per_stream=64,
            pace_tokens=False,
        )
    )
    shim = build_rest_shim(engine, expected_token=_TEST_TOKEN)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=shim),
        base_url=_BASE_URL,
        http2=False,
        limits=_build_limits(c),
    )


async def test_https_edge_path_returns_https_edge_record() -> None:
    client = _build_test_client()
    try:
        result = await run_rest_cohort(
            path="embed",
            base_url=_BASE_URL,
            token=_TEST_TOKEN,
            concurrency=1,
            n=3,
            hidden_size=2048,
            rtt_probe_n=2,
            client=client,
            network_path="https_edge",
            https_edge_endpoint="https://abc.modal.run",
            client_external_geolocation_country="US",
            client_external_geolocation_region="US-CA",
        )
    finally:
        await client.aclose()

    assert result.network_path == "https_edge"
    assert result.https_edge_record is not None
    edge = result.https_edge_record
    assert edge.network_path == "https_edge"
    assert edge.https_edge_endpoint == "https://abc.modal.run"
    assert edge.client_external_geolocation_country == "US"
    assert edge.client_external_geolocation_region == "US-CA"
    # RTT fields mirror the cohort's probe result.
    assert result.rtt_record is not None
    assert edge.measured_rtt_ms_median == result.rtt_record.median_ms


async def test_plain_tcp_path_returns_plain_rest_record_only() -> None:
    """When ``network_path="plain_tcp"`` the cohort result's
    ``https_edge_record`` is None (the wrapper is HTTPS-edge-specific) but
    the result is still tagged with ``network_path="plain_tcp"``.
    """
    client = _build_test_client()
    try:
        result = await run_rest_cohort(
            path="embed",
            base_url=_BASE_URL,
            token=_TEST_TOKEN,
            concurrency=1,
            n=3,
            hidden_size=2048,
            rtt_probe_n=2,
            client=client,
            network_path="plain_tcp",
        )
    finally:
        await client.aclose()

    assert result.network_path == "plain_tcp"
    assert result.https_edge_record is None
    # M5.1's existing record dataclass is still present.
    assert result.record.connections_opened == 1


async def test_default_call_signature_returns_no_network_path() -> None:
    """M5.1 back-compat: omitting ``network_path`` preserves the M5.1
    behavior — the result has ``network_path=None`` and no HTTPS-edge
    record so M5.1 callers continue to work unchanged.
    """
    client = _build_test_client()
    try:
        result = await run_rest_cohort(
            path="embed",
            base_url=_BASE_URL,
            token=_TEST_TOKEN,
            concurrency=1,
            n=2,
            hidden_size=2048,
            rtt_probe_n=2,
            client=client,
        )
    finally:
        await client.aclose()

    assert result.network_path is None
    assert result.https_edge_record is None


async def test_probe_rest_rtt_accepts_network_path_tag() -> None:
    """``probe_rest_rtt`` accepts ``network_path`` for parity with
    ``run_rest_cohort`` and the probe still returns a valid RTTRecord."""
    client = _build_test_client()
    try:
        rtt_edge = await probe_rest_rtt(_BASE_URL, client=client, n=3, network_path="https_edge")
        rtt_tcp = await probe_rest_rtt(_BASE_URL, client=client, n=3, network_path="plain_tcp")
    finally:
        await client.aclose()

    assert rtt_edge.n == 3
    assert rtt_tcp.n == 3
    assert all(s >= 0 for s in rtt_edge.samples_ms)


async def test_https_edge_record_field_byte_parity_with_underlying_record() -> None:
    """The HTTPS-edge record mirrors every field from the underlying
    ``RESTCohortRecord`` so the M5.2 reporter can iterate both cohorts
    uniformly via a duck-typed accessor."""
    client = _build_test_client()
    try:
        result = await run_rest_cohort(
            path="embed",
            base_url=_BASE_URL,
            token=_TEST_TOKEN,
            concurrency=1,
            n=3,
            hidden_size=2048,
            rtt_probe_n=2,
            client=client,
            network_path="https_edge",
        )
    finally:
        await client.aclose()

    assert result.https_edge_record is not None
    edge = result.https_edge_record
    rec = result.record
    assert edge.shim_overhead_ms_median == rec.shim_overhead_ms_median
    assert edge.shim_overhead_ms_p95 == rec.shim_overhead_ms_p95
    assert edge.connections_opened == rec.connections_opened
    assert edge.connections_keepalive_reused == rec.connections_keepalive_reused
    assert edge.request_bytes_median == rec.request_bytes_median
    assert edge.request_bytes_p95 == rec.request_bytes_p95
    assert edge.response_bytes_median == rec.response_bytes_median
    assert edge.response_bytes_p95 == rec.response_bytes_p95
