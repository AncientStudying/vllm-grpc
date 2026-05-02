from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from vllm_grpc.v1 import chat_pb2
from vllm_grpc_frontend.chat import ChatServicer


def _make_output(
    text: str = "4.",
    finish_reason: str = "stop",
    prompt_token_ids: list[int] | None = None,
    output_token_ids: list[int] | None = None,
) -> MagicMock:
    output = MagicMock()
    output.prompt_token_ids = prompt_token_ids or list(range(10))
    comp = MagicMock()
    comp.text = text
    comp.finish_reason = finish_reason
    comp.token_ids = output_token_ids or list(range(3))
    output.outputs = [comp]
    return output


async def _fake_generate(prompt: str, params: object, *, request_id: str):  # type: ignore[no-untyped-def]
    yield _make_output()


def _make_servicer(finish_reason: str = "stop") -> tuple[ChatServicer, MagicMock]:
    async def _gen(prompt: str, params: object, *, request_id: str):  # type: ignore[no-untyped-def]
        yield _make_output(finish_reason=finish_reason)

    engine = MagicMock()
    engine.generate = _gen
    tokenizer = MagicMock()
    tokenizer.apply_chat_template.return_value = "<prompt>"
    return ChatServicer(engine, tokenizer), tokenizer


def _make_request(seed: int | None = None) -> chat_pb2.ChatCompleteRequest:
    kwargs: dict[str, object] = {
        "messages": [chat_pb2.ChatMessage(role="user", content="What is 2+2?")],
        "model": "Qwen/Qwen3-0.6B",
        "max_tokens": 64,
    }
    if seed is not None:
        kwargs["seed"] = seed
    return chat_pb2.ChatCompleteRequest(**kwargs)


@pytest.mark.asyncio
async def test_complete_returns_response_fields() -> None:
    servicer, _ = _make_servicer()
    context = AsyncMock()
    resp = await servicer.Complete(_make_request(), context)
    assert resp.message.role == "assistant"
    assert resp.message.content == "4."
    assert resp.finish_reason == "stop"
    assert resp.prompt_tokens == 10
    assert resp.completion_tokens == 3


@pytest.mark.asyncio
async def test_complete_with_seed() -> None:
    servicer, _ = _make_servicer()
    context = AsyncMock()
    resp = await servicer.Complete(_make_request(seed=42), context)
    assert resp.message.role == "assistant"


@pytest.mark.asyncio
async def test_complete_without_seed() -> None:
    servicer, _ = _make_servicer()
    context = AsyncMock()
    resp = await servicer.Complete(_make_request(), context)
    assert resp.message.role == "assistant"


@pytest.mark.asyncio
async def test_complete_finish_reason_length() -> None:
    servicer, _ = _make_servicer(finish_reason="length")
    context = AsyncMock()
    resp = await servicer.Complete(_make_request(), context)
    assert resp.finish_reason == "length"
