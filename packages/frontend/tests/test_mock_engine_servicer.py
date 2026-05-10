"""T016: smoke integration test proving MockEngine drops into the real servicers.

Runs under packages/frontend/tests/conftest.py which mocks the ``vllm`` module
so the real ``ChatServicer`` / ``CompletionsServicer`` import successfully.
This test does not depend on a real gRPC channel — it calls the servicer
methods directly with an AsyncMock context, which is sufficient to prove
the drop-in interface contract from ``contracts/mock-engine-interface.md``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from vllm_grpc.v1 import chat_pb2, completions_pb2
from vllm_grpc_bench.mock_engine import MockEngine, MockEngineConfig
from vllm_grpc_frontend.chat import ChatServicer
from vllm_grpc_frontend.completions import CompletionsServicer


@pytest.mark.asyncio
async def test_chat_servicer_accepts_mock_engine() -> None:
    engine = MockEngine(MockEngineConfig(hidden_size=2048, tokens_per_second=1000.0))
    tokenizer = MagicMock()
    tokenizer.apply_chat_template.return_value = "<prompt>"
    servicer = ChatServicer(engine, tokenizer)

    request = chat_pb2.ChatCompleteRequest(
        messages=[chat_pb2.ChatMessage(role="user", content="say hi")],
        model="mock-engine",
        max_tokens=8,
    )
    response = await servicer.Complete(request, AsyncMock())
    assert response.message.role == "assistant"
    assert response.message.content  # non-empty deterministic text
    assert response.finish_reason in ("stop", "length")


@pytest.mark.asyncio
async def test_completions_servicer_text_path_accepts_mock_engine() -> None:
    engine = MockEngine(MockEngineConfig(hidden_size=2048, tokens_per_second=1000.0))
    servicer = CompletionsServicer(engine)
    request = completions_pb2.CompletionRequest(
        model="mock-engine",
        max_tokens=8,
        prompt="What is gRPC?",
    )
    response = await servicer.Complete(request, AsyncMock())
    assert response.generated_text  # deterministic non-empty text
    assert response.finish_reason in ("stop", "length")
    assert response.completion_tokens >= 1
