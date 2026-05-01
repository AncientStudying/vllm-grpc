from __future__ import annotations

import os

import grpc
from vllm_grpc.v1 import (  # type: ignore[import-untyped]
    chat_pb2,
    chat_pb2_grpc,
    health_pb2,
    health_pb2_grpc,
)

_HEALTH_DEADLINE_SECONDS = 2.0
_CHAT_DEADLINE_SECONDS = 30.0


class GrpcHealthClient:
    def __init__(self, addr: str | None = None) -> None:
        self._addr = addr or os.environ.get("FRONTEND_ADDR", "localhost:50051")

    async def ping(self) -> str:
        async with grpc.aio.insecure_channel(self._addr) as channel:
            stub = health_pb2_grpc.HealthStub(channel)
            response: health_pb2.HealthResponse = await stub.Ping(
                health_pb2.HealthRequest(),
                timeout=_HEALTH_DEADLINE_SECONDS,
            )
        return str(response.message)


class GrpcChatClient:
    def __init__(self, addr: str | None = None) -> None:
        self._addr = addr or os.environ.get("FRONTEND_ADDR", "localhost:50051")

    async def complete(self, req: chat_pb2.ChatCompleteRequest) -> chat_pb2.ChatCompleteResponse:
        async with grpc.aio.insecure_channel(self._addr) as channel:
            stub = chat_pb2_grpc.ChatServiceStub(channel)
            response: chat_pb2.ChatCompleteResponse = await stub.Complete(
                req,
                timeout=_CHAT_DEADLINE_SECONDS,
            )
        return response
