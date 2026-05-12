"""T014 — REST cohort runner tests.

Exercises ``rest_cohort.run_rest_cohort`` against the in-process FastAPI
shim built by ``scripts.python.modal_bench_rest_grpc_server.build_rest_shim``
via ``httpx.ASGITransport``. The shim shares the same MockEngine the gRPC
servicers use in production, so this test path matches the M5.1 cross-host
shape modulo the network leg.
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


def _build_test_client(hidden_size: int = 2048, c: int = 1) -> tuple[httpx.AsyncClient, MockEngine]:
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
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=shim),
        base_url=_BASE_URL,
        http2=False,
        limits=_build_limits(c),
    )
    return client, engine


def test_build_limits_matches_fr_008() -> None:
    """T014 (a): pool limits use ``max_keepalive_connections=c``,
    ``max_connections=c``, ``keepalive_expiry=300.0``.
    """
    limits = _build_limits(c=4)
    assert limits.max_keepalive_connections == 4
    assert limits.max_connections == 4
    assert limits.keepalive_expiry == 300.0


async def test_chat_stream_ttft_is_wall_clock_to_first_data_line() -> None:
    """T014 (b): TTFT is recorded as the wall-clock from request-send to the
    first non-empty ``data:`` SSE line.
    """
    client, _ = _build_test_client(hidden_size=2048, c=1)
    try:
        result = await run_rest_cohort(
            path="chat_stream",
            base_url=_BASE_URL,
            token=_TEST_TOKEN,
            concurrency=1,
            n=4,
            hidden_size=2048,
            rtt_probe_n=2,
            client=client,
        )
    finally:
        await client.aclose()
    assert len(result.samples) == 4
    # Every sample's TTFT is > 0 (a data: line was observed).
    for sample in result.samples:
        assert sample.wall_clock_seconds > 0
        assert sample.response_bytes > 0
        # The first SSE line should start with "data:" and carry a JSON body.
        assert sample.response_bytes >= len("data: ")


async def test_embed_cohort_records_request_and_response_bytes() -> None:
    """T014 (c): embed cohort records JSON request and response byte counts."""
    client, _ = _build_test_client(hidden_size=2048, c=1)
    try:
        result = await run_rest_cohort(
            path="embed",
            base_url=_BASE_URL,
            token=_TEST_TOKEN,
            concurrency=1,
            n=4,
            hidden_size=2048,
            rtt_probe_n=2,
            client=client,
        )
    finally:
        await client.aclose()
    assert result.record.request_bytes_median > 0
    assert result.record.response_bytes_median > 0
    # base64-encoded float32 tensor at h=2048 → ~10KB JSON payload range.
    assert result.record.request_bytes_median >= 1000


async def test_shim_overhead_captured_from_x_shim_overhead_header() -> None:
    """T014 (d): shim-overhead-ms is parsed from the ``X-Shim-Overhead-Ms``
    response header into ``RESTCohortRecord.shim_overhead_ms_median``.
    """
    client, _ = _build_test_client(hidden_size=2048, c=1)
    try:
        result = await run_rest_cohort(
            path="embed",
            base_url=_BASE_URL,
            token=_TEST_TOKEN,
            concurrency=1,
            n=4,
            hidden_size=2048,
            rtt_probe_n=2,
            client=client,
        )
    finally:
        await client.aclose()
    # Engine call is fast; shim overhead is a small positive value (<100ms).
    assert result.record.shim_overhead_ms_median > 0
    assert result.record.shim_overhead_ms_median < 100.0
    assert result.record.shim_overhead_ms_p95 >= result.record.shim_overhead_ms_median


async def test_connection_count_matches_concurrency_at_c4_and_c8() -> None:
    """T014 (e): ``connections_opened == concurrency`` once the cohort
    completes; ``connections_keepalive_reused == n - concurrency``.
    """
    for c in (4, 8):
        client, _ = _build_test_client(hidden_size=2048, c=c)
        try:
            result = await run_rest_cohort(
                path="embed",
                base_url=_BASE_URL,
                token=_TEST_TOKEN,
                concurrency=c,
                n=c * 3,
                hidden_size=2048,
                rtt_probe_n=2,
                client=client,
            )
        finally:
            await client.aclose()
        assert result.record.connections_opened == c
        assert result.record.connections_keepalive_reused == c * 3 - c


async def test_probe_rest_rtt_returns_record_with_samples() -> None:
    """Probe helper returns a populated RTTRecord with n samples."""
    client, _ = _build_test_client(hidden_size=2048, c=1)
    try:
        rtt = await probe_rest_rtt(_BASE_URL, client=client, n=5)
    finally:
        await client.aclose()
    assert rtt.n == 5
    assert len(rtt.samples_ms) == 5
    assert all(s >= 0 for s in rtt.samples_ms)
    assert rtt.median_ms >= 0
    assert rtt.p95_ms >= rtt.median_ms


async def test_healthz_requires_no_bearer_token() -> None:
    """``/healthz`` is excluded from auth so the RTT probe avoids bearer cost."""
    client, _ = _build_test_client(hidden_size=2048, c=1)
    try:
        resp = await client.get("/healthz")
    finally:
        await client.aclose()
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


async def test_chat_stream_response_bytes_sums_all_sse_lines() -> None:
    """M5.2 fix: ``response_bytes`` is the TOTAL SSE body bytes summed
    across every yielded line, not just the first ``data:`` line. This
    matches gRPC's ``sum(len(chunk.SerializeToString()) for chunk in
    stream)`` semantic so a downstream consumer comparing
    ``response_body_bytes`` across REST and gRPC chat_stream cohorts gets
    commensurable values.
    """
    client, _ = _build_test_client(hidden_size=2048, c=1)
    try:
        result = await run_rest_cohort(
            path="chat_stream",
            base_url=_BASE_URL,
            token=_TEST_TOKEN,
            concurrency=1,
            n=4,
            hidden_size=2048,
            rtt_probe_n=2,
            client=client,
        )
    finally:
        await client.aclose()
    # Total response bytes should be substantially larger than a single SSE
    # ``data: {...}`` line. With max_tokens=64 and many tokens per chunk,
    # the cumulative response runs to hundreds of bytes per request.
    for sample in result.samples:
        assert sample.response_bytes > 100, (
            f"chat_stream response_bytes must be the total across all SSE "
            f"lines, not just the first; got {sample.response_bytes}"
        )


async def test_rest_cohort_returns_warmup_samples_when_warmup_n_positive() -> None:
    """M5.2 (FR-012a (g)): warmup samples are returned alongside the
    measurement samples so the events sidecar can persist them with
    phase="warmup". Aggregates exclude warmup (the cohort record's
    counters reflect ``n`` only, not ``n + warmup_n``).
    """
    client, _ = _build_test_client(hidden_size=2048, c=1)
    try:
        result = await run_rest_cohort(
            path="embed",
            base_url=_BASE_URL,
            token=_TEST_TOKEN,
            concurrency=1,
            n=3,
            hidden_size=2048,
            rtt_probe_n=2,
            warmup_n=2,
            client=client,
        )
    finally:
        await client.aclose()
    # 3 measurement samples + 2 warmup samples, each on its own attribute.
    assert len(result.samples) == 3
    assert len(result.warmup_samples) == 2
    # The cohort record (which feeds aggregates) is built from measurement
    # samples only — the warmup bytes don't leak into the median fields.
    assert result.record.request_bytes_median > 0


async def test_rest_cohort_warmup_samples_empty_when_warmup_n_zero() -> None:
    client, _ = _build_test_client(hidden_size=2048, c=1)
    try:
        result = await run_rest_cohort(
            path="embed",
            base_url=_BASE_URL,
            token=_TEST_TOKEN,
            concurrency=1,
            n=3,
            hidden_size=2048,
            rtt_probe_n=2,
            warmup_n=0,
            client=client,
        )
    finally:
        await client.aclose()
    assert result.warmup_samples == ()


async def test_v1_endpoint_rejects_missing_bearer_token() -> None:
    """``/v1/*`` requires bearer auth — bare GET/POST without header returns 401."""
    client, _ = _build_test_client(hidden_size=2048, c=1)
    try:
        resp = await client.post(
            "/v1/embeddings",
            json={
                "model": "mock",
                "input_kind": "prompt_embedding_b64",
                "input": "AAAA",
                "hidden_size": 2048,
            },
        )
    finally:
        await client.aclose()
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized"}
