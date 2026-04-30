from __future__ import annotations

import asyncio
import os

import grpc
from vllm_grpc.v1 import health_pb2_grpc  # type: ignore[import-untyped]

from vllm_grpc_frontend.health import HealthServicer


async def serve() -> None:
    host = os.environ.get("FRONTEND_HOST", "0.0.0.0")
    port = os.environ.get("FRONTEND_PORT", "50051")
    server = grpc.aio.server()
    health_pb2_grpc.add_HealthServicer_to_server(HealthServicer(), server)
    server.add_insecure_port(f"{host}:{port}")
    await server.start()
    print(f"Frontend gRPC server listening on {host}:{port}", flush=True)
    await server.wait_for_termination()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
