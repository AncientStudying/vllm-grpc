from __future__ import annotations

from types import TracebackType

import grpc.aio

from vllm_grpc_client.chat import ChatClient


class VllmGrpcClient:
    def __init__(self, addr: str, timeout: float = 30.0) -> None:
        self._addr = addr
        self._timeout = timeout
        self._channel: grpc.aio.Channel | None = None

    async def __aenter__(self) -> VllmGrpcClient:
        self._channel = grpc.aio.insecure_channel(self._addr)
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
