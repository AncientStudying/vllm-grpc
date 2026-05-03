from __future__ import annotations

import socket
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from vllm_grpc_proxy.chat_router import _chat_client
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
async def test_chat_bridge_end_to_end(fake_frontend: int) -> None:
    _chat_client._addr = f"localhost:{fake_frontend}"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "Qwen/Qwen3-0.6B",
                    "messages": [{"role": "user", "content": "What is 2+2?"}],
                    "max_tokens": 64,
                    "seed": 42,
                },
            )
    finally:
        _chat_client._addr = "localhost:50051"

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "4."
    assert body["usage"]["total_tokens"] > 0
    assert body["object"] == "chat.completion"


@pytest.mark.asyncio
async def test_streaming_bridge_end_to_end(fake_frontend: int) -> None:
    """FakeChatServicer yields: 'Hello' + ' world' + finish.
    Proxy emits: role-delta, 'Hello', ' world', finish, [DONE].
    """
    import json

    _chat_client._addr = f"localhost:{fake_frontend}"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "Qwen/Qwen3-0.6B",
                    "messages": [{"role": "user", "content": "Say hello."}],
                    "max_tokens": 5,
                    "seed": 42,
                    "stream": True,
                },
            )
    finally:
        _chat_client._addr = "localhost:50051"

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    data_lines = [ln for ln in response.text.split("\n") if ln.startswith("data: ")]
    assert data_lines[-1] == "data: [DONE]"

    # Concatenate all delta.content fields (skip role-delta and finish events)
    content = ""
    for line in data_lines[:-1]:  # exclude [DONE]
        payload = json.loads(line[6:])
        delta = payload["choices"][0]["delta"]
        content += delta.get("content", "")

    assert content == "Hello world"
