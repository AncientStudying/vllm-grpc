from __future__ import annotations

import os

import grpc
from vllm_grpc.v1 import health_pb2, health_pb2_grpc  # type: ignore[import-untyped]

_DEADLINE_SECONDS = 2.0


class GrpcHealthClient:
    def __init__(self, addr: str | None = None) -> None:
        self._addr = addr or os.environ.get("FRONTEND_ADDR", "localhost:50051")

    async def ping(self) -> str:
        async with grpc.aio.insecure_channel(self._addr) as channel:
            stub = health_pb2_grpc.HealthStub(channel)
            response: health_pb2.HealthResponse = await stub.Ping(
                health_pb2.HealthRequest(),
                timeout=_DEADLINE_SECONDS,
            )
        return str(response.message)
