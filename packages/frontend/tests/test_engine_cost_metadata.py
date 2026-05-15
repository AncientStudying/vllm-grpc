"""Tests for the M6 engine-cost trailing-metadata emission (T007).

Asserts that:
- ``ChatServicer.Complete`` (unary) emits ``engine-forward-ms``.
- ``CompletionsServicer.Complete`` (unary embed) emits ``engine-forward-ms``.
- ``ChatServicer.CompleteStream`` emits ``engine-ttft-ms`` AND
  ``engine-tpot-ms`` on stream completion.
- ``CompletionsServicer.CompleteStream`` emits ``engine-ttft-ms`` AND
  ``engine-tpot-ms`` on stream completion.

All values are floats encoded as strings (gRPC metadata wire format per
``contracts/instrumentation.md`` §1).
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import grpc
import pytest
from vllm_grpc.v1 import chat_pb2, completions_pb2
from vllm_grpc_frontend.chat import ChatServicer
from vllm_grpc_frontend.completions import CompletionsServicer


def _make_output(
    text: str = "4.",
    finish_reason: str | None = "stop",
    output_token_ids: list[int] | None = None,
) -> MagicMock:
    output = MagicMock()
    output.prompt_token_ids = list(range(10))
    comp = MagicMock()
    comp.text = text
    comp.finish_reason = finish_reason
    comp.token_ids = output_token_ids or list(range(3))
    output.outputs = [comp]
    return output


class _CapturingContext:
    """Synchronous stand-in for grpc.aio.ServicerContext.

    ``set_trailing_metadata`` is a synchronous method on the real
    ``grpc.aio.ServicerContext`` (per the gRPC Python public API). Using
    a plain object here lets us capture the value without an async-mock
    warning that would obscure assertions.
    """

    def __init__(self) -> None:
        self.trailing_metadata: tuple[tuple[str, str], ...] | None = None
        self._active = True

    def set_trailing_metadata(self, md: tuple[tuple[str, str], ...]) -> None:
        self.trailing_metadata = md

    def is_active(self) -> bool:
        return self._active

    async def abort(self, code: object, details: str) -> None:
        raise RuntimeError(f"abort({code}, {details!r})")


# --- Chat unary ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_complete_emits_engine_forward_ms() -> None:
    async def _gen(prompt: object, params: object, *, request_id: str):  # type: ignore[no-untyped-def]
        yield _make_output()

    engine = MagicMock()
    engine.generate = _gen
    tokenizer = MagicMock()
    tokenizer.apply_chat_template.return_value = "<prompt>"
    servicer = ChatServicer(engine, tokenizer)
    ctx = _CapturingContext()
    req = chat_pb2.ChatCompleteRequest(
        messages=[chat_pb2.ChatMessage(role="user", content="2+2?")],
        model="mock",
        max_tokens=4,
    )
    await servicer.Complete(req, cast(grpc.aio.ServicerContext[Any, Any], ctx))
    assert ctx.trailing_metadata is not None
    md = dict(ctx.trailing_metadata)
    assert "engine-forward-ms" in md
    assert float(md["engine-forward-ms"]) >= 0.0


# --- Chat stream --------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_complete_stream_emits_ttft_and_tpot() -> None:
    async def _gen(prompt: object, params: object, *, request_id: str):  # type: ignore[no-untyped-def]
        # Two chunks with text + a terminator chunk.
        yield _make_output(text="A", finish_reason=None, output_token_ids=[1])
        yield _make_output(text="AB", finish_reason=None, output_token_ids=[1, 2])
        yield _make_output(text="AB", finish_reason="stop", output_token_ids=[1, 2])

    engine = MagicMock()
    engine.generate = _gen
    tokenizer = MagicMock()
    tokenizer.apply_chat_template.return_value = "<prompt>"
    servicer = ChatServicer(engine, tokenizer)
    ctx = _CapturingContext()
    req = chat_pb2.ChatCompleteRequest(
        messages=[chat_pb2.ChatMessage(role="user", content="hi")],
        model="mock",
        max_tokens=4,
    )
    chunks = [
        chunk
        async for chunk in servicer.CompleteStream(
            req, cast(grpc.aio.ServicerContext[Any, Any], ctx)
        )
    ]
    assert chunks, "expected at least one stream chunk"
    assert ctx.trailing_metadata is not None
    md = dict(ctx.trailing_metadata)
    assert "engine-ttft-ms" in md
    assert "engine-tpot-ms" in md
    assert float(md["engine-ttft-ms"]) >= 0.0
    assert float(md["engine-tpot-ms"]) >= 0.0


# --- Completions unary (embed) ------------------------------------------------


@pytest.mark.asyncio
async def test_completions_complete_emits_engine_forward_ms() -> None:
    async def _gen(prompt: object, params: object, *, request_id: str):  # type: ignore[no-untyped-def]
        yield _make_output()

    engine = MagicMock()
    engine.generate = _gen
    servicer = CompletionsServicer(engine)
    ctx = _CapturingContext()
    req = completions_pb2.CompletionRequest(prompt="hello", max_tokens=4)
    await servicer.Complete(req, cast(grpc.aio.ServicerContext[Any, Any], ctx))
    assert ctx.trailing_metadata is not None
    md = dict(ctx.trailing_metadata)
    assert "engine-forward-ms" in md


# --- Completions stream -------------------------------------------------------


@pytest.mark.asyncio
async def test_completions_complete_stream_emits_ttft_and_tpot() -> None:
    async def _gen(prompt: object, params: object, *, request_id: str):  # type: ignore[no-untyped-def]
        yield _make_output(text="A", finish_reason=None, output_token_ids=[1])
        yield _make_output(text="AB", finish_reason=None, output_token_ids=[1, 2])
        yield _make_output(text="AB", finish_reason="stop", output_token_ids=[1, 2])

    engine = MagicMock()
    engine.generate = _gen
    servicer = CompletionsServicer(engine)
    ctx = _CapturingContext()
    req = completions_pb2.CompletionRequest(prompt="hi", max_tokens=4)
    chunks = [
        chunk
        async for chunk in servicer.CompleteStream(
            req, cast(grpc.aio.ServicerContext[Any, Any], ctx)
        )
    ]
    assert chunks
    assert ctx.trailing_metadata is not None
    md = dict(ctx.trailing_metadata)
    assert "engine-ttft-ms" in md
    assert "engine-tpot-ms" in md
