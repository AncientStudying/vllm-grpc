from __future__ import annotations

import asyncio
import json

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

_STREAMING_TOKENS = ["Hello", " world", "!"]


def _sse_chunk(token: str, finish_reason: str | None = None) -> bytes:
    payload = {
        "id": "chatcmpl-fake",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "Qwen/Qwen3-0.6B",
        "choices": [
            {
                "index": 0,
                "delta": {} if finish_reason else {"content": token},
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


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


def _make_streaming_transport() -> httpx.MockTransport:
    body = b"".join(
        [_sse_chunk("", None)]
        + [_sse_chunk(t, None) for t in _STREAMING_TOKENS]
        + [_sse_chunk("", "stop"), b"data: [DONE]\n\n"]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )

    return httpx.MockTransport(handler)


@pytest.fixture
def fake_http_server() -> httpx.MockTransport:
    return _make_transport(include_proxy_header=False)


@pytest.fixture
def fake_http_server_with_proxy_header() -> httpx.MockTransport:
    return _make_transport(include_proxy_header=True)


@pytest.fixture
def fake_streaming_server() -> httpx.MockTransport:
    return _make_streaming_transport()
