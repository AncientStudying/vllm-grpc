from __future__ import annotations

import base64
import io
import json

import pytest
from vllm_grpc.v1 import completions_pb2
from vllm_grpc_proxy.completions_translate import (
    OpenAICompletionRequest,
    build_completion_response,
    format_completion_chunk,
    format_completion_final,
    format_done,
    openai_request_to_proto,
)


def test_openai_request_text_only_valid() -> None:
    req = OpenAICompletionRequest(model="m", prompt="hi")
    assert req.prompt == "hi"
    assert req.prompt_embeds is None


def test_openai_request_embeds_only_valid() -> None:
    req = OpenAICompletionRequest(model="m", prompt_embeds="YWJj")
    assert req.prompt_embeds == "YWJj"
    assert req.prompt is None


def test_openai_request_both_inputs_raises() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OpenAICompletionRequest(model="m", prompt="hi", prompt_embeds="YWJj")


def test_openai_request_neither_input_raises() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OpenAICompletionRequest(model="m")


def test_build_completion_response_shape() -> None:
    proto_resp = completions_pb2.CompletionResponse(
        generated_text="hello",
        finish_reason="stop",
        prompt_tokens=5,
        completion_tokens=3,
    )
    resp = build_completion_response(proto_resp, "test-model")
    assert resp["object"] == "text_completion"
    assert resp["choices"][0]["text"] == "hello"
    assert resp["choices"][0]["finish_reason"] == "stop"
    assert resp["usage"]["total_tokens"] == 8
    assert resp["id"].startswith("cmpl-")


def test_openai_request_to_proto_text() -> None:
    req = OpenAICompletionRequest(model="m", max_tokens=10, prompt="hello", seed=42)
    proto = openai_request_to_proto(req)
    assert proto.prompt == "hello"
    assert proto.WhichOneof("input") == "prompt"
    assert proto.seed == 42


def test_openai_request_to_proto_embeds() -> None:
    torch = pytest.importorskip("torch")
    buf = io.BytesIO()
    torch.save(torch.zeros(4, 8), buf)
    b64 = base64.b64encode(buf.getvalue()).decode()
    req = OpenAICompletionRequest(model="m", prompt_embeds=b64)
    proto = openai_request_to_proto(req)
    assert proto.WhichOneof("input") == "prompt_embeds"
    assert len(proto.prompt_embeds) > 0


def test_format_completion_chunk() -> None:
    chunk = completions_pb2.CompletionStreamChunk(delta_text="tok", finish_reason="", token_index=0)
    event = format_completion_chunk(chunk, "cmpl-abc", "m", 12345)
    payload = json.loads(event.strip().removeprefix("data: "))
    assert payload["object"] == "text_completion"
    assert payload["choices"][0]["text"] == "tok"
    assert payload["choices"][0]["finish_reason"] is None


def test_format_completion_final() -> None:
    chunk = completions_pb2.CompletionStreamChunk(
        delta_text="", finish_reason="stop", token_index=3
    )
    event = format_completion_final(chunk, "cmpl-abc", "m", 12345)
    payload = json.loads(event.strip().removeprefix("data: "))
    assert payload["choices"][0]["text"] == ""
    assert payload["choices"][0]["finish_reason"] == "stop"


def test_format_done() -> None:
    assert format_done() == "data: [DONE]\n\n"
