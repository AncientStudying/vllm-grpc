from __future__ import annotations

import io
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import grpc
import grpc.aio
import pytest
from vllm_grpc.v1 import completions_pb2
from vllm_grpc_client.completions import CompletionResult, CompletionsClient


def _make_channel() -> MagicMock:
    return MagicMock(spec=grpc.aio.Channel)


_CANNED_RESPONSE = completions_pb2.CompletionResponse(
    generated_text="hello world",
    finish_reason="stop",
    prompt_tokens=5,
    completion_tokens=3,
)

_FAKE_CHUNKS = [
    completions_pb2.CompletionStreamChunk(delta_text="hello", finish_reason="", token_index=0),
    completions_pb2.CompletionStreamChunk(delta_text=" world", finish_reason="", token_index=1),
    completions_pb2.CompletionStreamChunk(delta_text="", finish_reason="stop", token_index=2),
]


@pytest.mark.asyncio
async def test_complete_text_prompt() -> None:
    channel = _make_channel()
    client = CompletionsClient(channel)

    mock_stub = MagicMock()
    mock_stub.Complete = AsyncMock(return_value=_CANNED_RESPONSE)

    with patch(
        "vllm_grpc_client.completions.completions_pb2_grpc.CompletionsServiceStub",
        return_value=mock_stub,
    ):
        result = await client.complete(model="m", max_tokens=10, prompt="hello")

    assert isinstance(result, CompletionResult)
    assert result.generated_text == "hello world"
    assert result.finish_reason == "stop"
    assert result.prompt_tokens == 5
    assert result.completion_tokens == 3


class _FakeStreamCall:
    """Minimal async-iterable that also exposes .cancel() like a gRPC call object."""

    def __init__(self, chunks: list[completions_pb2.CompletionStreamChunk]) -> None:
        self._chunks = chunks
        self.cancel = MagicMock()

    def __aiter__(self) -> AsyncIterator[completions_pb2.CompletionStreamChunk]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[completions_pb2.CompletionStreamChunk]:
        for c in self._chunks:
            yield c


@pytest.mark.asyncio
async def test_complete_stream_yields_chunks() -> None:
    channel = _make_channel()
    client = CompletionsClient(channel)

    mock_call = _FakeStreamCall(_FAKE_CHUNKS)

    mock_stub = MagicMock()
    mock_stub.CompleteStream = MagicMock(return_value=mock_call)

    with patch(
        "vllm_grpc_client.completions.completions_pb2_grpc.CompletionsServiceStub",
        return_value=mock_stub,
    ):
        chunks = []
        async for chunk in client.complete_stream(model="m", max_tokens=10, prompt="hello"):
            chunks.append(chunk)

    assert len(chunks) == 3
    assert chunks[0].delta_text == "hello"
    assert chunks[0].finish_reason is None
    assert chunks[2].finish_reason == "stop"


@pytest.mark.asyncio
async def test_complete_prompt_embeds_serialized_as_bytes() -> None:
    torch = pytest.importorskip("torch")
    channel = _make_channel()
    client = CompletionsClient(channel)

    captured_req: list[completions_pb2.CompletionRequest] = []

    async def _fake_complete(
        req: completions_pb2.CompletionRequest, **kwargs: object
    ) -> completions_pb2.CompletionResponse:
        captured_req.append(req)
        return _CANNED_RESPONSE

    mock_stub = MagicMock()
    mock_stub.Complete = _fake_complete

    tensor = torch.zeros(4, 8, dtype=torch.float32)
    with patch(
        "vllm_grpc_client.completions.completions_pb2_grpc.CompletionsServiceStub",
        return_value=mock_stub,
    ):
        await client.complete(model="m", max_tokens=5, prompt_embeds=tensor)

    assert len(captured_req) == 1
    req = captured_req[0]
    assert req.WhichOneof("input") == "prompt_embeds"
    # Verify it's raw bytes (not base64 — just non-empty bytes)
    assert len(req.prompt_embeds) > 0
    # Verify we can round-trip it
    loaded = torch.load(io.BytesIO(req.prompt_embeds), weights_only=True)
    assert loaded.shape == (4, 8)


@pytest.mark.asyncio
async def test_complete_both_inputs_raises_value_error() -> None:
    torch = pytest.importorskip("torch")
    channel = _make_channel()
    client = CompletionsClient(channel)
    tensor = torch.zeros(4, 8)
    with pytest.raises(ValueError, match="Exactly one"):
        await client.complete(model="m", max_tokens=5, prompt="hi", prompt_embeds=tensor)


@pytest.mark.asyncio
async def test_complete_neither_input_raises_value_error() -> None:
    channel = _make_channel()
    client = CompletionsClient(channel)
    with pytest.raises(ValueError, match="Exactly one"):
        await client.complete(model="m", max_tokens=5)


@pytest.mark.asyncio
async def test_complete_grpc_error_propagates() -> None:
    channel = _make_channel()
    client = CompletionsClient(channel)

    rpc_error = grpc.aio.AioRpcError(
        grpc.StatusCode.INTERNAL,
        trailing_metadata=grpc.aio.Metadata(),  # type: ignore[arg-type]
        initial_metadata=grpc.aio.Metadata(),  # type: ignore[arg-type]
        details="engine error",
    )
    mock_stub = MagicMock()
    mock_stub.Complete = AsyncMock(side_effect=rpc_error)

    with (
        patch(
            "vllm_grpc_client.completions.completions_pb2_grpc.CompletionsServiceStub",
            return_value=mock_stub,
        ),
        pytest.raises(grpc.aio.AioRpcError),
    ):
        await client.complete(model="m", max_tokens=5, prompt="hi")
