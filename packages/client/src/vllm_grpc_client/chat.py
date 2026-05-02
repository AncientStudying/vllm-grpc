from __future__ import annotations

from dataclasses import dataclass

import grpc
import grpc.aio
from vllm_grpc.v1 import chat_pb2, chat_pb2_grpc


@dataclass
class ChatCompleteResult:
    content: str
    role: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int


class ChatClient:
    def __init__(self, channel: grpc.aio.Channel) -> None:
        self._channel = channel

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

        req = chat_pb2.ChatCompleteRequest(
            messages=proto_messages,
            model=model,
            max_tokens=max_tokens,
            **kwargs,
        )

        response: chat_pb2.ChatCompleteResponse = await stub.Complete(req, timeout=timeout)

        return ChatCompleteResult(
            content=response.message.content,
            role=response.message.role,
            finish_reason=response.finish_reason,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )
