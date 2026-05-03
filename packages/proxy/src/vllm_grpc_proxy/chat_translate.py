from __future__ import annotations

import json
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


def _sse_chunk_payload(
    completion_id: str, created: int, model: str, delta: dict[str, Any], finish_reason: Any
) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload)}\n\n"


def format_sse_role_delta(completion_id: str, created: int, model: str) -> str:
    """First SSE event: role delta with empty content."""
    return _sse_chunk_payload(
        completion_id, created, model, {"role": "assistant", "content": ""}, None
    )


def proto_chunk_to_sse_event(
    chunk: chat_pb2.ChatStreamChunk,
    completion_id: str,
    created: int,
    model: str,
) -> str:
    """Format one ChatStreamChunk as an OpenAI-compatible SSE data line."""
    if chunk.finish_reason:
        delta: dict[str, Any] = {}
        finish_reason: Any = chunk.finish_reason
    else:
        delta = {"content": chunk.delta_content}
        finish_reason = None
    return _sse_chunk_payload(completion_id, created, model, delta, finish_reason)


def format_sse_done() -> str:
    return "data: [DONE]\n\n"


def format_sse_error(message: str) -> str:
    payload = {"error": {"message": message, "type": "internal_error"}}
    return f"data: {json.dumps(payload)}\n\n"


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
