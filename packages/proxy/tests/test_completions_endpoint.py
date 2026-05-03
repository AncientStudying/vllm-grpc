from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import grpc
import pytest
from httpx import ASGITransport, AsyncClient
from vllm_grpc.v1 import completions_pb2
from vllm_grpc_proxy.main import app

_CANNED_RESPONSE = completions_pb2.CompletionResponse(
    generated_text="test output",
    finish_reason="stop",
    prompt_tokens=5,
    completion_tokens=3,
)

_VALID_TEXT_BODY = {
    "model": "Qwen/Qwen3-0.6B",
    "prompt": "hello",
    "max_tokens": 16,
    "seed": 42,
}

_FAKE_CHUNKS = [
    completions_pb2.CompletionStreamChunk(delta_text="a", finish_reason="", token_index=0),
    completions_pb2.CompletionStreamChunk(delta_text="b", finish_reason="", token_index=1),
    completions_pb2.CompletionStreamChunk(delta_text="c", finish_reason="", token_index=2),
    completions_pb2.CompletionStreamChunk(delta_text="", finish_reason="stop", token_index=3),
]


async def _fake_stream(
    chunks: list[completions_pb2.CompletionStreamChunk],
) -> AsyncIterator[completions_pb2.CompletionStreamChunk]:
    for chunk in chunks:
        yield chunk


@pytest.fixture
def mock_completions_client() -> Any:
    with patch("vllm_grpc_proxy.completions_router._completions_client") as mock:
        mock.complete = AsyncMock(return_value=_CANNED_RESPONSE)
        mock.stream_complete = MagicMock(return_value=_fake_stream(_FAKE_CHUNKS))
        yield mock


@pytest.mark.asyncio
async def test_non_streaming_text_prompt_returns_200(mock_completions_client: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/completions", json=_VALID_TEXT_BODY)
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "text_completion"
    assert body["choices"][0]["text"] == "test output"
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["id"].startswith("cmpl-")


@pytest.mark.asyncio
async def test_non_streaming_embeds_prompt_returns_200(mock_completions_client: Any) -> None:
    import base64

    body = {
        "model": "Qwen/Qwen3-0.6B",
        "prompt_embeds": base64.b64encode(b"fake_tensor_bytes").decode(),
        "max_tokens": 16,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/completions", json=body)
    assert response.status_code == 200
    assert response.json()["object"] == "text_completion"


@pytest.mark.asyncio
async def test_both_inputs_returns_422() -> None:
    import base64

    body = {
        "model": "Qwen/Qwen3-0.6B",
        "prompt": "hello",
        "prompt_embeds": base64.b64encode(b"fake").decode(),
        "max_tokens": 16,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/completions", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_neither_input_returns_422() -> None:
    body = {"model": "Qwen/Qwen3-0.6B", "max_tokens": 16}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/completions", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_streaming_returns_event_stream(mock_completions_client: Any) -> None:
    body = {**_VALID_TEXT_BODY, "stream": True}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/completions", json=body)
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_streaming_sse_sequence(mock_completions_client: Any) -> None:
    body = {**_VALID_TEXT_BODY, "stream": True}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/completions", json=body)
    lines = [ln for ln in response.text.split("\n") if ln.startswith("data: ")]
    # 3 delta chunks + 1 final + [DONE]
    assert lines[-1] == "data: [DONE]"
    assert len(lines) == 5
    first = json.loads(lines[0][6:])
    assert first["object"] == "text_completion"
    assert first["choices"][0]["text"] == "a"
    assert first["choices"][0]["finish_reason"] is None
    last_data = json.loads(lines[3][6:])
    assert last_data["choices"][0]["text"] == ""
    assert last_data["choices"][0]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_streaming_consistent_id(mock_completions_client: Any) -> None:
    body = {**_VALID_TEXT_BODY, "stream": True}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/completions", json=body)
    data_lines = [
        ln for ln in response.text.split("\n") if ln.startswith("data: ") and ln != "data: [DONE]"
    ]
    ids = {json.loads(ln[6:])["id"] for ln in data_lines}
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_grpc_unavailable_returns_502(mock_completions_client: Any) -> None:
    rpc_error = grpc.aio.AioRpcError(
        grpc.StatusCode.UNAVAILABLE,
        trailing_metadata=grpc.aio.Metadata(),  # type: ignore[arg-type]
        initial_metadata=grpc.aio.Metadata(),  # type: ignore[arg-type]
        details="connection refused",
    )
    mock_completions_client.complete = AsyncMock(side_effect=rpc_error)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/completions", json=_VALID_TEXT_BODY)
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_grpc_invalid_argument_returns_422_from_grpc(mock_completions_client: Any) -> None:
    rpc_error = grpc.aio.AioRpcError(
        grpc.StatusCode.INVALID_ARGUMENT,
        trailing_metadata=grpc.aio.Metadata(),  # type: ignore[arg-type]
        initial_metadata=grpc.aio.Metadata(),  # type: ignore[arg-type]
        details="bad tensor dtype",
    )
    mock_completions_client.complete = AsyncMock(side_effect=rpc_error)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/completions", json=_VALID_TEXT_BODY)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_streaming_grpc_error_emits_error_event(mock_completions_client: Any) -> None:
    rpc_error = grpc.aio.AioRpcError(
        grpc.StatusCode.INTERNAL,
        trailing_metadata=grpc.aio.Metadata(),  # type: ignore[arg-type]
        initial_metadata=grpc.aio.Metadata(),  # type: ignore[arg-type]
        details="engine crashed",
    )

    async def _error_stream(
        *_: object, **__: object
    ) -> AsyncIterator[completions_pb2.CompletionStreamChunk]:
        raise rpc_error
        yield  # make it a generator

    mock_completions_client.stream_complete = MagicMock(return_value=_error_stream())
    body = {**_VALID_TEXT_BODY, "stream": True}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/completions", json=body)
    assert "data: [DONE]" not in response.text
    data_lines = [ln for ln in response.text.split("\n") if ln.startswith("data: ")]
    assert len(data_lines) >= 1
    err = json.loads(data_lines[-1][6:])
    assert "error" in err
