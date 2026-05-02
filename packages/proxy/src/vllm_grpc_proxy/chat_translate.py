from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field
from vllm_grpc.v1 import chat_pb2


class OpenAIChatMessage(BaseModel):
    role: str
    content: str


class OpenAIChatRequest(BaseModel):
    model: str
    messages: list[OpenAIChatMessage] = Field(min_length=1)
    max_tokens: int = Field(gt=0)
    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None
    stream: bool = False


def openai_request_to_proto(req: OpenAIChatRequest) -> chat_pb2.ChatCompleteRequest:
    kwargs: dict[str, Any] = {
        "messages": [chat_pb2.ChatMessage(role=m.role, content=m.content) for m in req.messages],
        "model": req.model,
        "max_tokens": req.max_tokens,
    }
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    if req.top_p is not None:
        kwargs["top_p"] = req.top_p
    if req.seed is not None:
        kwargs["seed"] = req.seed
    return chat_pb2.ChatCompleteRequest(**kwargs)


def proto_response_to_openai_dict(
    resp: chat_pb2.ChatCompleteResponse,
    model: str,
) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": resp.message.role,
                    "content": resp.message.content,
                },
                "finish_reason": resp.finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
            "total_tokens": resp.prompt_tokens + resp.completion_tokens,
        },
    }
