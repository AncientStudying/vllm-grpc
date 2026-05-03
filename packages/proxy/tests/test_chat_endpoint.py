from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import grpc
import pytest
from httpx import ASGITransport, AsyncClient
from vllm_grpc.v1 import chat_pb2
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

_FAKE_CHUNKS = [
    chat_pb2.ChatStreamChunk(delta_content="Hello", finish_reason="", token_index=0),
    chat_pb2.ChatStreamChunk(delta_content=" world", finish_reason="", token_index=1),
    chat_pb2.ChatStreamChunk(delta_content="", finish_reason="stop", token_index=2),
]


async def _fake_stream(
    chunks: list[chat_pb2.ChatStreamChunk],
) -> AsyncIterator[chat_pb2.ChatStreamChunk]:
    for chunk in chunks:
        yield chunk


@pytest.fixture
def mock_chat_client() -> Any:
    with patch("vllm_grpc_proxy.chat_router._chat_client") as mock:
        mock.complete = AsyncMock(return_value=_CANNED_RESPONSE)
        mock.stream_complete = MagicMock(return_value=_fake_stream(_FAKE_CHUNKS))
        yield mock


@pytest.mark.asyncio
async def test_happy_path_returns_200_with_openai_json(mock_chat_client: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json=_VALID_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "4."
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["total_tokens"] == 13
    assert body["id"].startswith("chatcmpl-")
    proxy_ms_header = response.headers.get("x-bench-proxy-ms")
    assert proxy_ms_header is not None
    assert float(proxy_ms_header) > 0


@pytest.mark.asyncio
async def test_stream_true_returns_sse_content_type(mock_chat_client: Any) -> None:
    body = {**_VALID_BODY, "stream": True}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json=body)

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    mock_chat_client.complete.assert_not_called()


@pytest.mark.asyncio
async def test_stream_event_sequence(mock_chat_client: Any) -> None:
    # _FAKE_CHUNKS: "Hello" (token 0), " world" (token 1), "" finish_reason="stop" (token 2)
    # Expected SSE sequence:
    #   [0] role-delta  {"role":"assistant","content":""}
    #   [1] "Hello"     {"content":"Hello"}
    #   [2] " world"    {"content":" world"}
    #   [3] finish      {"delta":{},"finish_reason":"stop"}
    #   [4] [DONE]
    body = {**_VALID_BODY, "stream": True}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json=body)

    lines = [ln for ln in response.text.split("\n") if ln.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    assert len(lines) == 5  # role-delta + 2 content + finish + [DONE]

    first = json.loads(lines[0][6:])
    assert first["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    assert first["choices"][0]["finish_reason"] is None

    second = json.loads(lines[1][6:])
    assert second["choices"][0]["delta"] == {"content": "Hello"}

    third = json.loads(lines[2][6:])
    assert third["choices"][0]["delta"] == {"content": " world"}

    fourth = json.loads(lines[3][6:])
    assert fourth["choices"][0]["delta"] == {}
    assert fourth["choices"][0]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_stream_completion_id_consistent(mock_chat_client: Any) -> None:
    body = {**_VALID_BODY, "stream": True}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json=body)

    data_lines = [
        ln for ln in response.text.split("\n") if ln.startswith("data: ") and ln != "data: [DONE]"
    ]
    ids = {json.loads(ln[6:])["id"] for ln in data_lines}
    assert len(ids) == 1  # all chunks share the same completion ID


@pytest.mark.asyncio
async def test_stream_grpc_error_emits_error_event(mock_chat_client: Any) -> None:
    rpc_error = grpc.aio.AioRpcError(
        grpc.StatusCode.INTERNAL,
        trailing_metadata=grpc.aio.Metadata(),  # type: ignore[arg-type]
        initial_metadata=grpc.aio.Metadata(),  # type: ignore[arg-type]
        details="engine crashed",
    )

    async def _error_stream(*_: object, **__: object) -> AsyncIterator[chat_pb2.ChatStreamChunk]:
        raise rpc_error
        yield  # make it an async generator

    mock_chat_client.stream_complete = MagicMock(return_value=_error_stream())
    body = {**_VALID_BODY, "stream": True}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json=body)

    assert response.status_code == 200  # header already sent
    assert "text/event-stream" in response.headers["content-type"]
    assert "data: [DONE]" not in response.text
    data_lines = [ln for ln in response.text.split("\n") if ln.startswith("data: ")]
    # role-delta is emitted before the gRPC stream, so there are 2 events: role-delta + error
    assert len(data_lines) == 2
    err = json.loads(data_lines[-1][6:])
    assert "error" in err


@pytest.mark.asyncio
async def test_grpc_unavailable_returns_502(mock_chat_client: Any) -> None:
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


@pytest.mark.asyncio
async def test_non_stream_unaffected_by_streaming_changes(mock_chat_client: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", json=_VALID_BODY)
    assert response.status_code == 200
    assert response.json()["object"] == "chat.completion"
