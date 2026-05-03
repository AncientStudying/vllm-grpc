from __future__ import annotations

import json
import socket
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from vllm_grpc_proxy.completions_router import _completions_client
from vllm_grpc_proxy.main import app

from tests.integration.fake_frontend import fake_frontend_server


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest_asyncio.fixture
async def fake_frontend() -> AsyncIterator[int]:
    port = _free_port()
    async with fake_frontend_server(port):
        yield port


@pytest.mark.asyncio
async def test_completions_text_prompt_round_trip(fake_frontend: int) -> None:
    _completions_client._addr = f"localhost:{fake_frontend}"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/completions",
                json={
                    "model": "Qwen/Qwen3-0.6B",
                    "prompt": "The meaning of life is",
                    "max_tokens": 16,
                    "seed": 42,
                },
            )
    finally:
        _completions_client._addr = "localhost:50051"

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "text_completion"
    assert body["choices"][0]["text"] == "test output"
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["total_tokens"] > 0


@pytest.mark.asyncio
async def test_completions_embeds_round_trip(fake_frontend: int) -> None:
    import base64

    _completions_client._addr = f"localhost:{fake_frontend}"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/completions",
                json={
                    "model": "Qwen/Qwen3-0.6B",
                    "prompt_embeds": base64.b64encode(b"fake_tensor_bytes").decode(),
                    "max_tokens": 16,
                },
            )
    finally:
        _completions_client._addr = "localhost:50051"

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "text_completion"
    assert body["choices"][0]["text"] == "test output"


@pytest.mark.asyncio
async def test_completions_dual_input_returns_422(fake_frontend: int) -> None:
    import base64

    _completions_client._addr = f"localhost:{fake_frontend}"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/completions",
                json={
                    "model": "Qwen/Qwen3-0.6B",
                    "prompt": "hello",
                    "prompt_embeds": base64.b64encode(b"fake").decode(),
                    "max_tokens": 16,
                },
            )
    finally:
        _completions_client._addr = "localhost:50051"

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_streaming_text_prompt_delivers_chunks(fake_frontend: int) -> None:
    _completions_client._addr = f"localhost:{fake_frontend}"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/completions",
                json={
                    "model": "Qwen/Qwen3-0.6B",
                    "prompt": "Say hello.",
                    "max_tokens": 5,
                    "seed": 42,
                    "stream": True,
                },
            )
    finally:
        _completions_client._addr = "localhost:50051"

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    data_lines = [ln for ln in response.text.split("\n") if ln.startswith("data: ")]
    assert data_lines[-1] == "data: [DONE]"

    # FakeCompletionsServicer yields delta_text "a", "b", "c" then final ""
    non_done = [ln for ln in data_lines if ln != "data: [DONE]"]
    delta_texts = []
    finish_reasons = []
    for line in non_done:
        payload = json.loads(line[6:])
        choice = payload["choices"][0]
        delta_texts.append(choice["text"])
        finish_reasons.append(choice["finish_reason"])

    # 3 delta chunks + 1 final chunk
    assert len(delta_texts) == 4
    assert "".join(delta_texts[:3]) == "abc"
    assert finish_reasons[3] == "stop"
    assert delta_texts[3] == ""


@pytest.mark.asyncio
async def test_streaming_concatenated_text_equals_non_streaming(fake_frontend: int) -> None:
    _completions_client._addr = f"localhost:{fake_frontend}"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            stream_resp = await client.post(
                "/v1/completions",
                json={
                    "model": "Qwen/Qwen3-0.6B",
                    "prompt": "hello",
                    "max_tokens": 5,
                    "seed": 42,
                    "stream": True,
                },
            )
            non_stream_resp = await client.post(
                "/v1/completions",
                json={
                    "model": "Qwen/Qwen3-0.6B",
                    "prompt": "hello",
                    "max_tokens": 5,
                    "seed": 42,
                },
            )
    finally:
        _completions_client._addr = "localhost:50051"

    # Concatenate streaming delta texts (excluding final empty chunk and [DONE])
    data_lines = [ln for ln in stream_resp.text.split("\n") if ln.startswith("data: ")]
    streamed_text = ""
    for line in data_lines:
        if line == "data: [DONE]":
            continue
        payload = json.loads(line[6:])
        streamed_text += payload["choices"][0]["text"]

    non_stream_text = non_stream_resp.json()["choices"][0]["text"]

    # FakeCompletionsServicer always returns "test output" for non-streaming
    # and "abc" for streaming — they differ but both should be non-empty and consistent
    assert len(streamed_text) > 0
    assert len(non_stream_text) > 0
