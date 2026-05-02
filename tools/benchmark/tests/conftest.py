from __future__ import annotations

import asyncio

import httpx
import pytest

_CANNED_RESPONSE = {
    "id": "chatcmpl-fake",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "Qwen/Qwen3-0.6B",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello!"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
}


def _make_transport(include_proxy_header: bool, delay_ms: float = 5.0) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(delay_ms / 1000)
        headers: dict[str, str] = {}
        if include_proxy_header:
            headers["x-bench-proxy-ms"] = "1.500"
        return httpx.Response(
            200,
            headers=headers,
            json=_CANNED_RESPONSE,
        )

    return httpx.MockTransport(handler)


@pytest.fixture
def fake_http_server() -> httpx.MockTransport:
    return _make_transport(include_proxy_header=False)


@pytest.fixture
def fake_http_server_with_proxy_header() -> httpx.MockTransport:
    return _make_transport(include_proxy_header=True)
