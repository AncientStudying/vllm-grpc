from __future__ import annotations

import socket
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from vllm_grpc_client import StreamChunk, VllmGrpcClient

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


_MESSAGES = [{"role": "user", "content": "Say hello."}]
_MODEL = "Qwen/Qwen3-0.6B"


@pytest.mark.asyncio
async def test_complete_stream_yields_stream_chunks(fake_frontend: int) -> None:
    async with VllmGrpcClient(f"localhost:{fake_frontend}") as client:
        chunks = []
        async for chunk in client.chat.complete_stream(_MESSAGES, model=_MODEL, max_tokens=5):
            chunks.append(chunk)

    assert len(chunks) == 3
    assert all(isinstance(c, StreamChunk) for c in chunks)


@pytest.mark.asyncio
async def test_complete_stream_content_accumulates(fake_frontend: int) -> None:
    async with VllmGrpcClient(f"localhost:{fake_frontend}") as client:
        content = ""
        async for chunk in client.chat.complete_stream(_MESSAGES, model=_MODEL, max_tokens=5):
            content += chunk.delta_content

    assert content == "Hello world"


@pytest.mark.asyncio
async def test_complete_stream_finish_reason_on_last_chunk(fake_frontend: int) -> None:
    async with VllmGrpcClient(f"localhost:{fake_frontend}") as client:
        chunks = []
        async for chunk in client.chat.complete_stream(_MESSAGES, model=_MODEL, max_tokens=5):
            chunks.append(chunk)

    # Non-final chunks have finish_reason=None
    assert all(c.finish_reason is None for c in chunks[:-1])
    # Final chunk has finish_reason set
    assert chunks[-1].finish_reason == "stop"
    assert chunks[-1].delta_content == ""


@pytest.mark.asyncio
async def test_complete_stream_token_index_monotonic(fake_frontend: int) -> None:
    async with VllmGrpcClient(f"localhost:{fake_frontend}") as client:
        indices = []
        async for chunk in client.chat.complete_stream(_MESSAGES, model=_MODEL, max_tokens=5):
            indices.append(chunk.token_index)

    assert indices == sorted(indices)
    assert len(set(indices)) == len(indices)  # strictly increasing
