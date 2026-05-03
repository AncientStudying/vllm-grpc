from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Any

from pydantic import BaseModel, model_validator
from vllm_grpc.v1 import completions_pb2


class OpenAICompletionRequest(BaseModel):
    model: str
    max_tokens: int = 16
    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None
    stream: bool = False
    prompt: str | None = None
    prompt_embeds: str | None = None  # base64-encoded torch.save() bytes

    @model_validator(mode="after")
    def exactly_one_input(self) -> OpenAICompletionRequest:
        has_prompt = self.prompt is not None
        has_embeds = self.prompt_embeds is not None
        if has_prompt == has_embeds:  # both True or both False
            raise ValueError("Exactly one of prompt or prompt_embeds must be provided")
        return self


def openai_request_to_proto(req: OpenAICompletionRequest) -> completions_pb2.CompletionRequest:
    kwargs: dict[str, Any] = {
        "model": req.model,
        "max_tokens": req.max_tokens,
    }
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    if req.top_p is not None:
        kwargs["top_p"] = req.top_p
    if req.seed is not None:
        kwargs["seed"] = req.seed
    if req.prompt is not None:
        kwargs["prompt"] = req.prompt
    else:
        assert req.prompt_embeds is not None
        kwargs["prompt_embeds"] = base64.b64decode(req.prompt_embeds)
    return completions_pb2.CompletionRequest(**kwargs)


def build_completion_response(
    proto_resp: completions_pb2.CompletionResponse,
    model: str,
) -> dict[str, Any]:
    return {
        "id": f"cmpl-{uuid.uuid4()}",
        "object": "text_completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "text": proto_resp.generated_text,
                "index": 0,
                "logprobs": None,
                "finish_reason": proto_resp.finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": proto_resp.prompt_tokens,
            "completion_tokens": proto_resp.completion_tokens,
            "total_tokens": proto_resp.prompt_tokens + proto_resp.completion_tokens,
        },
    }


def format_completion_chunk(
    chunk: completions_pb2.CompletionStreamChunk,
    completion_id: str,
    model: str,
    created: int,
) -> str:
    payload = {
        "id": completion_id,
        "object": "text_completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "text": chunk.delta_text,
                "index": 0,
                "logprobs": None,
                "finish_reason": None,
            }
        ],
    }
    return f"data: {json.dumps(payload)}\n\n"


def format_completion_final(
    chunk: completions_pb2.CompletionStreamChunk,
    completion_id: str,
    model: str,
    created: int,
) -> str:
    payload = {
        "id": completion_id,
        "object": "text_completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "text": "",
                "index": 0,
                "logprobs": None,
                "finish_reason": chunk.finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(payload)}\n\n"


def format_done() -> str:
    return "data: [DONE]\n\n"


def format_completion_error(message: str) -> str:
    payload = {"error": {"message": message, "type": "server_error", "code": None}}
    return f"data: {json.dumps(payload)}\n\n"
