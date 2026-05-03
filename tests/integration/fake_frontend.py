from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import grpc
import grpc.aio
from vllm_grpc.v1 import (  # type: ignore[import-untyped]
    chat_pb2,
    chat_pb2_grpc,
    completions_pb2,
    completions_pb2_grpc,
)


class FakeChatServicer(chat_pb2_grpc.ChatServiceServicer):  # type: ignore[misc]
    async def Complete(
        self,
        request: chat_pb2.ChatCompleteRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> chat_pb2.ChatCompleteResponse:
        return chat_pb2.ChatCompleteResponse(
            message=chat_pb2.ChatMessage(role="assistant", content="4."),
            finish_reason="stop",
            prompt_tokens=10,
            completion_tokens=3,
        )

    async def CompleteStream(
        self,
        request: chat_pb2.ChatCompleteRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> AsyncIterator[chat_pb2.ChatStreamChunk]:
        yield chat_pb2.ChatStreamChunk(delta_content="Hello", finish_reason="", token_index=0)
        yield chat_pb2.ChatStreamChunk(delta_content=" world", finish_reason="", token_index=1)
        yield chat_pb2.ChatStreamChunk(delta_content="", finish_reason="stop", token_index=2)


class FakeCompletionsServicer(completions_pb2_grpc.CompletionsServiceServicer):  # type: ignore[misc]
    async def Complete(
        self,
        request: completions_pb2.CompletionRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> completions_pb2.CompletionResponse:
        return completions_pb2.CompletionResponse(
            generated_text="test output",
            finish_reason="stop",
            prompt_tokens=5,
            completion_tokens=3,
        )

    async def CompleteStream(
        self,
        request: completions_pb2.CompletionRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> AsyncIterator[completions_pb2.CompletionStreamChunk]:
        for i, delta in enumerate(["a", "b", "c"]):
            yield completions_pb2.CompletionStreamChunk(
                delta_text=delta, finish_reason="", token_index=i
            )
        yield completions_pb2.CompletionStreamChunk(
            delta_text="", finish_reason="stop", token_index=3
        )


@asynccontextmanager
async def fake_frontend_server(port: int) -> AsyncIterator[None]:
    server = grpc.aio.server()
    chat_pb2_grpc.add_ChatServiceServicer_to_server(FakeChatServicer(), server)
    completions_pb2_grpc.add_CompletionsServiceServicer_to_server(FakeCompletionsServicer(), server)
    server.add_insecure_port(f"localhost:{port}")
    await server.start()
    try:
        yield
    finally:
        await server.stop(grace=0)
