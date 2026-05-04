#!/usr/bin/env python
"""Demo: gRPC-direct chat completion via VllmGrpcClient (no proxy).

Access path: VllmGrpcClient → gRPC frontend → vLLM
This path skips the HTTP proxy entirely — the client speaks proto directly
to the frontend over a persistent gRPC channel. Response bytes are ~89%
smaller than REST for non-streaming chat (65 B vs 611 B in Phase 4.2 results).

Usage:
    uv run python demo/grpc-direct.py

Requires: frontend on $FRONTEND_ADDR (default localhost:50051)
          make run-frontend
"""

import asyncio
import os
import sys

import grpc
from vllm_grpc_client import VllmGrpcClient

FRONTEND_ADDR = os.environ.get("FRONTEND_ADDR", "localhost:50051")


async def main() -> None:
    try:
        async with VllmGrpcClient(FRONTEND_ADDR) as client:
            response = await client.chat.complete(
                messages=[{"role": "user", "content": "What is 2+2?"}],
                model="Qwen/Qwen3-0.6B",
                max_tokens=64,
                seed=42,
            )
            print(response.content)
    except grpc.RpcError as exc:
        print(f"ERROR: gRPC error connecting to {FRONTEND_ADDR}: {exc}", file=sys.stderr)
        sys.exit(1)


asyncio.run(main())
