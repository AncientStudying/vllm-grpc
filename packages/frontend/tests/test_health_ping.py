from unittest.mock import AsyncMock

import pytest
from vllm_grpc.v1 import health_pb2  # type: ignore[import-untyped]
from vllm_grpc_frontend.health import HealthServicer


@pytest.mark.asyncio
async def test_ping_returns_pong() -> None:
    servicer = HealthServicer()
    request = health_pb2.HealthRequest()
    context = AsyncMock()
    response = await servicer.Ping(request, context)
    assert response.message == "pong"


@pytest.mark.asyncio
async def test_ping_returns_health_response_type() -> None:
    servicer = HealthServicer()
    context = AsyncMock()
    response = await servicer.Ping(health_pb2.HealthRequest(), context)
    assert isinstance(response, health_pb2.HealthResponse)
