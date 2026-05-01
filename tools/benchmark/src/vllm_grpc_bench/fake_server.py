"""Standalone stub HTTP server for CI and bench-ci smoke tests.

Usage:
    python -m vllm_grpc_bench.fake_server --port 8900 [--include-proxy-header]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os

_CANNED_BODY = json.dumps(
    {
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
).encode()

_DELAY_MS = float(os.environ.get("FAKE_DELAY_MS", "5"))


async def _handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    include_proxy_header: bool,
) -> None:
    content_length = 0
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
        lower = line.lower()
        if lower.startswith(b"content-length:"):
            content_length = int(line.split(b":", 1)[1].strip())

    if content_length:
        await reader.readexactly(content_length)

    await asyncio.sleep(_DELAY_MS / 1000)

    extra_headers = "X-Bench-Proxy-Ms: 1.500\r\n" if include_proxy_header else ""

    response = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(_CANNED_BODY)}\r\n"
        f"Connection: close\r\n"
        f"{extra_headers}"
        f"\r\n"
    ).encode() + _CANNED_BODY

    writer.write(response)
    await writer.drain()
    writer.close()


async def serve(port: int, include_proxy_header: bool) -> None:
    server = await asyncio.start_server(
        lambda r, w: _handle(r, w, include_proxy_header),
        host="127.0.0.1",
        port=port,
    )
    addr = server.sockets[0].getsockname()
    print(f"FakeHTTPServer listening on {addr[0]}:{addr[1]}", flush=True)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fake HTTP server for benchmark CI")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument(
        "--include-proxy-header",
        action="store_true",
        help="Emit X-Bench-Proxy-Ms header in responses",
    )
    args = parser.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve(args.port, args.include_proxy_header))


if __name__ == "__main__":
    main()
