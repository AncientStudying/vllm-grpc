from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import grpc
import grpc.aio
from vllm_grpc.v1 import chat_pb2, chat_pb2_grpc  # type: ignore[import-untyped]


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


@asynccontextmanager
async def fake_frontend_server(port: int) -> AsyncIterator[None]:
    server = grpc.aio.server()
    chat_pb2_grpc.add_ChatServiceServicer_to_server(FakeChatServicer(), server)
    server.add_insecure_port(f"localhost:{port}")
    await server.start()
    try:
        yield
    finally:
        await server.stop(grace=0)
