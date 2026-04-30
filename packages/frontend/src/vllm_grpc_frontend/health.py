from __future__ import annotations

import grpc
from vllm_grpc.v1 import health_pb2, health_pb2_grpc  # type: ignore[import-untyped]


class HealthServicer(health_pb2_grpc.HealthServicer):  # type: ignore[misc]
    async def Ping(
        self,
        request: health_pb2.HealthRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> health_pb2.HealthResponse:
        return health_pb2.HealthResponse(message="pong")
