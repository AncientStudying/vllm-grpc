from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from vllm_grpc_proxy.main import app


@pytest.mark.asyncio
async def test_healthz_returns_200_when_ping_succeeds() -> None:
    with patch("vllm_grpc_proxy.main._client") as mock_client:
        mock_client.ping = AsyncMock(return_value="pong")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_healthz_returns_503_when_ping_fails() -> None:
    with patch("vllm_grpc_proxy.main._client") as mock_client:
        mock_client.ping = AsyncMock(side_effect=Exception("connection refused"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert "connection refused" in body["detail"]
