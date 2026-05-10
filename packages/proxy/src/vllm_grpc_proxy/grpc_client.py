from __future__ import annotations

import os
from collections.abc import AsyncIterator, Sequence
from typing import Any

import grpc
from vllm_grpc.v1 import (
    chat_pb2,
    chat_pb2_grpc,
    completions_pb2,
    completions_pb2_grpc,
    health_pb2,
    health_pb2_grpc,
)

_HEALTH_DEADLINE_SECONDS = 2.0
_CHAT_DEADLINE_SECONDS = 30.0

ChannelOption = tuple[str, int | str]


def _channel_kwargs(
    options: Sequence[ChannelOption] | None,
    compression: grpc.Compression | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if options is not None:
        kwargs["options"] = list(options)
    if compression is not None:
        kwargs["compression"] = compression
    return kwargs


class GrpcHealthClient:
    def __init__(
        self,
        addr: str | None = None,
        *,
        options: Sequence[ChannelOption] | None = None,
        compression: grpc.Compression | None = None,
    ) -> None:
        self._addr = addr or os.environ.get("FRONTEND_ADDR", "localhost:50051")
        self._kwargs = _channel_kwargs(options, compression)

    async def ping(self) -> str:
        async with grpc.aio.insecure_channel(self._addr, **self._kwargs) as channel:
            stub = health_pb2_grpc.HealthStub(channel)
            response: health_pb2.HealthResponse = await stub.Ping(
                health_pb2.HealthRequest(),
                timeout=_HEALTH_DEADLINE_SECONDS,
            )
        return str(response.message)


class GrpcChatClient:
    def __init__(
        self,
        addr: str | None = None,
        *,
        options: Sequence[ChannelOption] | None = None,
        compression: grpc.Compression | None = None,
    ) -> None:
        self._addr = addr or os.environ.get("FRONTEND_ADDR", "localhost:50051")
        self._kwargs = _channel_kwargs(options, compression)

    async def complete(self, req: chat_pb2.ChatCompleteRequest) -> chat_pb2.ChatCompleteResponse:
        async with grpc.aio.insecure_channel(self._addr, **self._kwargs) as channel:
            stub = chat_pb2_grpc.ChatServiceStub(channel)
            response: chat_pb2.ChatCompleteResponse = await stub.Complete(
                req,
                timeout=_CHAT_DEADLINE_SECONDS,
            )
        return response

    async def stream_complete(
        self, req: chat_pb2.ChatCompleteRequest
    ) -> AsyncIterator[chat_pb2.ChatStreamChunk]:
        async with grpc.aio.insecure_channel(self._addr, **self._kwargs) as channel:
            stub = chat_pb2_grpc.ChatServiceStub(channel)
            call = stub.CompleteStream(req, timeout=_CHAT_DEADLINE_SECONDS)
            try:
                async for chunk in call:
                    yield chunk
            finally:
                call.cancel()


class GrpcCompletionsClient:
    def __init__(
        self,
        addr: str | None = None,
        *,
        options: Sequence[ChannelOption] | None = None,
        compression: grpc.Compression | None = None,
    ) -> None:
        self._addr = addr or os.environ.get("FRONTEND_ADDR", "localhost:50051")
        self._kwargs = _channel_kwargs(options, compression)

    async def complete(
        self, req: completions_pb2.CompletionRequest
    ) -> completions_pb2.CompletionResponse:
        async with grpc.aio.insecure_channel(self._addr, **self._kwargs) as channel:
            stub = completions_pb2_grpc.CompletionsServiceStub(channel)
            response: completions_pb2.CompletionResponse = await stub.Complete(
                req,
                timeout=_CHAT_DEADLINE_SECONDS,
            )
        return response

    async def stream_complete(
        self, req: completions_pb2.CompletionRequest
    ) -> AsyncIterator[completions_pb2.CompletionStreamChunk]:
        async with grpc.aio.insecure_channel(self._addr, **self._kwargs) as channel:
            stub = completions_pb2_grpc.CompletionsServiceStub(channel)
            call = stub.CompleteStream(req, timeout=_CHAT_DEADLINE_SECONDS)
            try:
                async for chunk in call:
                    yield chunk
            finally:
                call.cancel()
