from __future__ import annotations

from unittest.mock import AsyncMock, patch

import grpc
import pytest
from httpx import ASGITransport, AsyncClient
from vllm_grpc.v1 import chat_pb2  # type: ignore[import-untyped]
from vllm_grpc_proxy.main import app

_CANNED_RESPONSE = chat_pb2.ChatCompleteResponse(
    message=chat_pb2.ChatMessage(role="assistant", content="4."),
    finish_reason="stop",
    prompt_tokens=10,
    completion_tokens=3,
)

_VALID_BODY = {
    "model": "Qwen/Qwen3-0.6B",
    "messages": [{"role": "user", "content": "What is 2+2?"}],
    "max_tokens": 64,
    "seed": 42,
}


@pytest.fixture
def mock_chat_client():  # type: ignore[no-untyped-def]
    with patch("vllm_grpc_proxy.chat_router._chat_client") as mock:
        mock.complete = AsyncMock(return_value=_CANNED_RESPONSE)
        yield mock


@pytest.mark.asyncio
async def test_happy_path_returns_200_with_openai_json(mock_chat_client: AsyncMock) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json=_VALID_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "4."
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["total_tokens"] == 13
    assert body["id"].startswith("chatcmpl-")


@pytest.mark.asyncio
async def test_stream_true_returns_501(mock_chat_client: AsyncMock) -> None:
    body = {**_VALID_BODY, "stream": True}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json=body)

    assert response.status_code == 501
    error = response.json()["error"]
    assert "message" in error
    assert error["type"] == "not_implemented_error"
    mock_chat_client.complete.assert_not_called()


@pytest.mark.asyncio
async def test_grpc_unavailable_returns_502(mock_chat_client: AsyncMock) -> None:
    rpc_error = grpc.aio.AioRpcError(
        grpc.StatusCode.UNAVAILABLE,
        trailing_metadata=grpc.aio.Metadata(),  # type: ignore[arg-type]
        initial_metadata=grpc.aio.Metadata(),  # type: ignore[arg-type]
        details="connection refused",
    )
    mock_chat_client.complete = AsyncMock(side_effect=rpc_error)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json=_VALID_BODY)

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "gateway_error"


@pytest.mark.asyncio
async def test_missing_messages_returns_422() -> None:
    body = {"model": "Qwen/Qwen3-0.6B", "max_tokens": 64}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_max_tokens_zero_returns_422() -> None:
    body = {**_VALID_BODY, "max_tokens": 0}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json=body)
    assert response.status_code == 422
