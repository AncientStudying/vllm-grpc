from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import grpc
import pytest
from vllm_grpc.v1 import completions_pb2
from vllm_grpc_frontend.completions import CompletionsServicer


def _make_output(
    text: str = "test output",
    finish_reason: str = "stop",
    prompt_token_ids: list[int] | None = None,
    output_token_ids: list[int] | None = None,
) -> MagicMock:
    output = MagicMock()
    output.prompt_token_ids = prompt_token_ids if prompt_token_ids is not None else list(range(5))
    comp = MagicMock()
    comp.text = text
    comp.finish_reason = finish_reason
    comp.token_ids = output_token_ids if output_token_ids is not None else list(range(3))
    output.outputs = [comp]
    return output


def _make_engine(outputs: list[MagicMock]) -> MagicMock:
    async def _gen(inp: object, params: object, *, request_id: str):  # type: ignore[no-untyped-def]
        for out in outputs:
            yield out

    engine = MagicMock()
    engine.generate = _gen
    return engine


def _make_text_request(prompt: str = "hello") -> completions_pb2.CompletionRequest:
    return completions_pb2.CompletionRequest(
        model="test",
        max_tokens=16,
        prompt=prompt,
    )


@pytest.mark.asyncio
async def test_complete_with_text_prompt() -> None:
    output = _make_output(
        text="test output",
        finish_reason="stop",
        prompt_token_ids=list(range(5)),
        output_token_ids=list(range(3)),
    )
    engine = _make_engine([output])
    servicer = CompletionsServicer(engine)
    context = AsyncMock()

    resp = await servicer.Complete(_make_text_request("hello"), context)

    assert resp.generated_text == "test output"
    assert resp.finish_reason == "stop"
    assert resp.prompt_tokens == 5
    assert resp.completion_tokens == 3


@pytest.mark.asyncio
async def test_complete_with_prompt_embeds() -> None:
    fake_tensor = MagicMock()
    output = _make_output(
        text="embedded output",
        finish_reason="stop",
        prompt_token_ids=list(range(4)),
        output_token_ids=list(range(2)),
    )

    captured_input: list[object] = []

    async def _gen(inp: object, params: object, *, request_id: str):  # type: ignore[no-untyped-def]
        captured_input.append(inp)
        yield output

    engine = MagicMock()
    engine.generate = _gen
    servicer = CompletionsServicer(engine)
    context = AsyncMock()

    req = completions_pb2.CompletionRequest(
        model="test",
        max_tokens=16,
        prompt_embeds=b"fakeBytes",
    )

    with patch("vllm_grpc_frontend.completions.decode_embeds", return_value=fake_tensor):
        resp = await servicer.Complete(req, context)

    assert captured_input == [{"prompt_embeds": fake_tensor}]
    assert resp.generated_text == "embedded output"


@pytest.mark.asyncio
async def test_complete_no_input_invalid_argument() -> None:
    engine = MagicMock()
    servicer = CompletionsServicer(engine)
    context = AsyncMock()

    # A request with neither prompt nor prompt_embeds set
    req = completions_pb2.CompletionRequest(model="test", max_tokens=16)
    await servicer.Complete(req, context)

    context.abort.assert_called_once_with(
        grpc.StatusCode.INVALID_ARGUMENT,
        "Exactly one of prompt or prompt_embeds must be set",
    )


@pytest.mark.asyncio
async def test_complete_stream_yields_chunks() -> None:
    """Engine yields 2 cumulative outputs → 3 chunks (delta a, delta b, final empty)."""
    outputs = [
        _make_output(text="a", finish_reason=""),
        _make_output(text="ab", finish_reason="stop"),
    ]
    engine = _make_engine(outputs)
    servicer = CompletionsServicer(engine)
    context = MagicMock()
    context.is_active.return_value = True

    chunks = []
    async for chunk in servicer.CompleteStream(_make_text_request(), context):
        chunks.append(chunk)

    assert len(chunks) == 3
    assert chunks[0].delta_text == "a"
    assert chunks[0].finish_reason == ""
    assert chunks[0].token_index == 0
    assert chunks[1].delta_text == "b"
    assert chunks[1].finish_reason == ""
    assert chunks[1].token_index == 1
    assert chunks[2].delta_text == ""
    assert chunks[2].finish_reason == "stop"
    assert chunks[2].token_index == 2


@pytest.mark.asyncio
async def test_complete_stream_3_tokens_4_chunks() -> None:
    """Engine yields 3 incremental outputs → 4 chunks (3 delta + 1 final)."""
    outputs = [
        _make_output(text="x", finish_reason=""),
        _make_output(text="xy", finish_reason=""),
        _make_output(text="xyz", finish_reason="stop"),
    ]
    engine = _make_engine(outputs)
    servicer = CompletionsServicer(engine)
    context = MagicMock()
    context.is_active.return_value = True

    chunks = []
    async for chunk in servicer.CompleteStream(_make_text_request(), context):
        chunks.append(chunk)

    assert len(chunks) == 4
    assert chunks[0].delta_text == "x"
    assert chunks[1].delta_text == "y"
    assert chunks[2].delta_text == "z"
    assert chunks[3].delta_text == ""
    assert chunks[3].finish_reason == "stop"
    assert chunks[3].token_index == 3


@pytest.mark.asyncio
async def test_complete_stream_client_cancel() -> None:
    """When context.is_active() returns False, streaming stops."""
    outputs = [
        _make_output(text="a", finish_reason=""),
        _make_output(text="ab", finish_reason=""),
        _make_output(text="abc", finish_reason="stop"),
    ]
    engine = _make_engine(outputs)
    servicer = CompletionsServicer(engine)
    context = MagicMock()

    # Return True for first check, then False to simulate cancellation
    call_count: list[int] = [0]

    def is_active_side_effect() -> bool:
        call_count[0] += 1
        return call_count[0] <= 1

    context.is_active.side_effect = is_active_side_effect

    chunks = []
    async for chunk in servicer.CompleteStream(_make_text_request(), context):
        chunks.append(chunk)

    # Should have stopped yielding after is_active() returned False
    assert len(chunks) <= 2
