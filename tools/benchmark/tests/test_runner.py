from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from vllm_grpc_bench.corpus import RequestSample
from vllm_grpc_bench.runner import run_target, run_target_streaming


def _make_sample(n: int = 1) -> list[RequestSample]:
    return [
        RequestSample(
            id=f"s{i}",
            messages=[{"role": "user", "content": "hi"}],
            model="test",
            max_tokens=5,
            temperature=0.0,
            seed=42,
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_run_target_with_proxy_header(
    fake_http_server_with_proxy_header: httpx.MockTransport,
) -> None:
    samples = _make_sample(3)
    results = await run_target(
        target="proxy",
        url="http://fake",
        samples=samples,
        concurrency=1,
        timeout=10.0,
        transport=fake_http_server_with_proxy_header,
    )
    assert len(results) == 3
    for r in results:
        assert r.latency_ms is not None
        assert r.latency_ms > 0
        assert r.request_bytes > 0
        assert r.response_bytes is not None
        assert r.response_bytes > 0
        assert r.proxy_ms is not None
        assert r.proxy_ms == pytest.approx(1.5)
        assert r.success is True


@pytest.mark.asyncio
async def test_run_target_without_proxy_header(
    fake_http_server: httpx.MockTransport,
) -> None:
    samples = _make_sample(3)
    results = await run_target(
        target="native",
        url="http://fake",
        samples=samples,
        concurrency=1,
        timeout=10.0,
        transport=fake_http_server,
    )
    assert len(results) == 3
    for r in results:
        assert r.proxy_ms is None
        assert r.success is True


@pytest.mark.asyncio
async def test_run_target_concurrency_4(
    fake_http_server: httpx.MockTransport,
) -> None:
    samples = _make_sample(4)
    results = await run_target(
        target="native",
        url="http://fake",
        samples=samples,
        concurrency=4,
        timeout=10.0,
        transport=fake_http_server,
    )
    assert len(results) == 4
    for r in results:
        assert r.concurrency == 4


@pytest.mark.asyncio
async def test_run_target_request_bytes_matches_body(
    fake_http_server: httpx.MockTransport,
) -> None:
    sample = _make_sample(1)[0]
    results = await run_target(
        target="proxy",
        url="http://fake",
        samples=[sample],
        concurrency=1,
        timeout=10.0,
        transport=fake_http_server,
    )
    expected_body = json.dumps(
        {
            "model": sample.model,
            "messages": sample.messages,
            "max_tokens": sample.max_tokens,
            "temperature": sample.temperature,
            "seed": sample.seed,
        }
    ).encode()
    assert results[0].request_bytes == len(expected_body)


class TestRunTargetStreaming:
    @pytest.mark.asyncio
    async def test_returns_ttft_and_tpot(self, fake_streaming_server: httpx.MockTransport) -> None:
        samples = _make_sample(1)
        results = await run_target_streaming(
            target="proxy",
            url="http://fake",
            samples=samples,
            concurrency=1,
            timeout=10.0,
            transport=fake_streaming_server,
        )
        assert len(results) == 1
        r = results[0]
        assert r.success is True
        assert r.ttft_ms is not None
        assert r.ttft_ms >= 0
        assert r.tpot_ms is not None
        assert r.tpot_ms >= 0

    @pytest.mark.asyncio
    async def test_token_count_matches_streamed_tokens(
        self, fake_streaming_server: httpx.MockTransport
    ) -> None:
        samples = _make_sample(1)
        results = await run_target_streaming(
            target="native",
            url="http://fake",
            samples=samples,
            concurrency=1,
            timeout=10.0,
            transport=fake_streaming_server,
        )
        r = results[0]
        # fake server emits 3 content tokens: "Hello", " world", "!"
        assert r.token_count == 3

    @pytest.mark.asyncio
    async def test_latency_ms_positive(self, fake_streaming_server: httpx.MockTransport) -> None:
        samples = _make_sample(2)
        results = await run_target_streaming(
            target="proxy",
            url="http://fake",
            samples=samples,
            concurrency=1,
            timeout=10.0,
            transport=fake_streaming_server,
        )
        for r in results:
            assert r.latency_ms is not None
            assert r.latency_ms > 0

    @pytest.mark.asyncio
    async def test_target_label_preserved(self, fake_streaming_server: httpx.MockTransport) -> None:
        samples = _make_sample(1)
        results = await run_target_streaming(
            target="native",
            url="http://fake",
            samples=samples,
            concurrency=1,
            timeout=10.0,
            transport=fake_streaming_server,
        )
        assert results[0].target == "native"


def _make_completion_text_sample(n: int = 1) -> list[Any]:
    from dataclasses import dataclass

    @dataclass
    class FakeSample:
        id: int
        prompt: str
        model: str
        max_tokens: int
        seed: int
        bucket: str = "short"

    return [
        FakeSample(id=i, prompt="hello", model="Qwen/Qwen3-0.6B", max_tokens=10, seed=42)
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_run_completions_proxy_text_request_type(
    fake_http_server: httpx.MockTransport,
) -> None:
    from vllm_grpc_bench.runner import run_completions_proxy_text

    samples = _make_completion_text_sample(2)
    results = await run_completions_proxy_text(
        url="http://fake",
        samples=samples,
        concurrency=1,
        timeout=10.0,
        transport=fake_http_server,
    )
    assert len(results) == 2
    for r in results:
        assert r.request_type == "completion-text"
        assert r.request_bytes > 0


@pytest.mark.asyncio
async def test_run_completions_proxy_embeds_request_type(
    fake_http_server: httpx.MockTransport,
) -> None:
    from dataclasses import dataclass

    from vllm_grpc_bench.runner import run_completions_proxy_embeds

    @dataclass
    class FakeEmbedSample:
        id: int
        tensor_bytes: bytes
        max_tokens: int
        seed: int
        seq_len: int
        bucket: str

    samples = [
        FakeEmbedSample(
            id=0, tensor_bytes=b"fake", max_tokens=10, seed=42, seq_len=8, bucket="short"
        )
    ]
    results = await run_completions_proxy_embeds(
        url="http://fake",
        samples=samples,
        concurrency=1,
        timeout=10.0,
        transport=fake_http_server,
    )
    assert len(results) == 1
    assert results[0].request_type == "completion-embeds"
    assert results[0].request_bytes > 0


@pytest.mark.asyncio
async def test_run_completions_native_embeds_request_type(
    fake_http_server: httpx.MockTransport,
) -> None:
    from dataclasses import dataclass

    from vllm_grpc_bench.runner import run_completions_native_embeds

    @dataclass
    class FakeEmbedSample:
        id: int
        tensor_bytes: bytes
        max_tokens: int
        seed: int
        seq_len: int
        bucket: str

    samples = [
        FakeEmbedSample(
            id=0, tensor_bytes=b"fake", max_tokens=10, seed=42, seq_len=8, bucket="short"
        )
    ]
    results = await run_completions_native_embeds(
        url="http://fake",
        samples=samples,
        concurrency=1,
        timeout=10.0,
        transport=fake_http_server,
    )
    assert len(results) == 1
    assert results[0].target == "native"
    assert results[0].request_type == "completion-embeds"
    assert results[0].request_bytes > 0
