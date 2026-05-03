from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import grpc
import grpc.aio
from vllm_grpc.v1 import chat_pb2, chat_pb2_grpc


@dataclass(frozen=True)
class ChatCompleteResult:
    content: str
    role: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class StreamChunk:
    delta_content: str
    finish_reason: str | None  # None on non-final chunks; "stop" or "length" on final
    token_index: int


class ChatClient:
    def __init__(self, channel: grpc.aio.Channel) -> None:
        self._channel = channel

    def _build_request(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float | None,
        top_p: float | None,
        seed: int | None,
    ) -> chat_pb2.ChatCompleteRequest:
        proto_messages = [
            chat_pb2.ChatMessage(role=m["role"], content=m["content"]) for m in messages
        ]
        kwargs: dict[str, object] = {}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if seed is not None:
            kwargs["seed"] = seed
        return chat_pb2.ChatCompleteRequest(
            messages=proto_messages,
            model=model,
            max_tokens=max_tokens,
            **kwargs,
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float | None = None,
        top_p: float | None = None,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> ChatCompleteResult:
        stub = chat_pb2_grpc.ChatServiceStub(self._channel)
        req = self._build_request(messages, model, max_tokens, temperature, top_p, seed)
        response: chat_pb2.ChatCompleteResponse = await stub.Complete(req, timeout=timeout)
        return ChatCompleteResult(
            content=response.message.content,
            role=response.message.role,
            finish_reason=response.finish_reason,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float | None = None,
        top_p: float | None = None,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[StreamChunk]:
        stub = chat_pb2_grpc.ChatServiceStub(self._channel)
        req = self._build_request(messages, model, max_tokens, temperature, top_p, seed)
        call = stub.CompleteStream(req, timeout=timeout)
        try:
            async for proto_chunk in call:
                yield StreamChunk(
                    delta_content=proto_chunk.delta_content,
                    finish_reason=proto_chunk.finish_reason or None,
                    token_index=proto_chunk.token_index,
                )
        except grpc.aio.AioRpcError:
            raise
        finally:
            call.cancel()
