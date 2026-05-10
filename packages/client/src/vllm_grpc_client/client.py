from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType
from typing import Any

import grpc
import grpc.aio

from vllm_grpc_client.chat import ChatClient
from vllm_grpc_client.completions import CompletionsClient

ChannelOption = tuple[str, int | str]


class VllmGrpcClient:
    def __init__(
        self,
        addr: str,
        timeout: float = 30.0,
        *,
        options: Sequence[ChannelOption] | None = None,
        compression: grpc.Compression | None = None,
    ) -> None:
        self._addr = addr
        self._timeout = timeout
        self._channel: grpc.aio.Channel | None = None
        self._channel_kwargs: dict[str, Any] = {}
        if options is not None:
            self._channel_kwargs["options"] = list(options)
        if compression is not None:
            self._channel_kwargs["compression"] = compression

    async def __aenter__(self) -> VllmGrpcClient:
        self._channel = grpc.aio.insecure_channel(self._addr, **self._channel_kwargs)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._channel is not None:
            await self._channel.close(grace=None)
            self._channel = None

    @property
    def chat(self) -> ChatClient:
        if self._channel is None:
            raise RuntimeError("VllmGrpcClient must be used as an async context manager")
        return ChatClient(self._channel)

    @property
    def completions(self) -> CompletionsClient:
        if self._channel is None:
            raise RuntimeError("VllmGrpcClient must be used as an async context manager")
        return CompletionsClient(self._channel)
