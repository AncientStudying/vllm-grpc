from __future__ import annotations

import asyncio
import os

import grpc
from vllm_grpc.v1 import chat_pb2_grpc, completions_pb2_grpc, health_pb2_grpc

from vllm_grpc_frontend.chat import ChatServicer
from vllm_grpc_frontend.completions import CompletionsServicer
from vllm_grpc_frontend.health import HealthServicer


async def serve() -> None:
    from transformers import AutoTokenizer
    from vllm import AsyncEngineArgs, AsyncLLMEngine

    model_name = os.environ.get("MODEL_NAME", "Qwen/Qwen3-0.6B")
    engine = AsyncLLMEngine.from_engine_args(
        AsyncEngineArgs(model=model_name, enable_prompt_embeds=True)
    )
    tokenizer = AutoTokenizer.from_pretrained(model_name)

    host = os.environ.get("FRONTEND_HOST", "0.0.0.0")
    port = os.environ.get("FRONTEND_PORT", "50051")
    server = grpc.aio.server()
    health_pb2_grpc.add_HealthServicer_to_server(HealthServicer(), server)
    chat_pb2_grpc.add_ChatServiceServicer_to_server(ChatServicer(engine, tokenizer), server)
    completions_pb2_grpc.add_CompletionsServiceServicer_to_server(
        CompletionsServicer(engine), server
    )
    server.add_insecure_port(f"{host}:{port}")
    await server.start()
    print(f"Frontend gRPC server listening on {host}:{port}", flush=True)
    await server.wait_for_termination()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
