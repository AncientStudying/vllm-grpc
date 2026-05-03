from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from vllm_grpc.v1 import chat_pb2
from vllm_grpc_proxy.chat_translate import (
    OpenAIChatRequest,
    format_sse_done,
    format_sse_error,
    format_sse_role_delta,
    openai_request_to_proto,
    proto_chunk_to_sse_event,
    proto_response_to_openai_dict,
)

_BASE_REQUEST = {
    "model": "Qwen/Qwen3-0.6B",
    "messages": [{"role": "user", "content": "What is 2+2?"}],
    "max_tokens": 64,
}


def _make_req(**overrides: object) -> OpenAIChatRequest:
    return OpenAIChatRequest(**{**_BASE_REQUEST, **overrides})


class TestOpenaiRequestToProto:
    def test_all_fields_present(self) -> None:
        req = _make_req(temperature=0.7, top_p=0.9, seed=42)
        proto = openai_request_to_proto(req)
        assert proto.model == "Qwen/Qwen3-0.6B"
        assert proto.max_tokens == 64
        assert proto.HasField("temperature")
        assert abs(proto.temperature - 0.7) < 1e-5
        assert proto.HasField("top_p")
        assert abs(proto.top_p - 0.9) < 1e-5
        assert proto.HasField("seed")
        assert proto.seed == 42
        assert len(proto.messages) == 1
        assert proto.messages[0].role == "user"
        assert proto.messages[0].content == "What is 2+2?"

    def test_optional_fields_absent(self) -> None:
        req = _make_req()
        proto = openai_request_to_proto(req)
        assert not proto.HasField("temperature")
        assert not proto.HasField("top_p")
        assert not proto.HasField("seed")

    def test_multiple_messages_preserved_in_order(self) -> None:
        req = _make_req(
            messages=[
                {"role": "system", "content": "Be helpful."},
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
                {"role": "user", "content": "Bye"},
            ]
        )
        proto = openai_request_to_proto(req)
        assert [m.role for m in proto.messages] == ["system", "user", "assistant", "user"]

    def test_seed_zero_is_present(self) -> None:
        req = _make_req(seed=0)
        proto = openai_request_to_proto(req)
        assert proto.HasField("seed")
        assert proto.seed == 0

    def test_empty_messages_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_req(messages=[])

    def test_max_tokens_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_req(max_tokens=0)

    def test_max_tokens_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_req(max_tokens=-1)


def _make_response(
    content: str = "4.",
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 3,
) -> chat_pb2.ChatCompleteResponse:
    return chat_pb2.ChatCompleteResponse(
        message=chat_pb2.ChatMessage(role="assistant", content=content),
        finish_reason=finish_reason,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


class TestProtoResponseToOpenaiDict:
    def test_finish_reason_stop(self) -> None:
        resp = _make_response(finish_reason="stop")
        d = proto_response_to_openai_dict(resp, "Qwen/Qwen3-0.6B")
        assert d["choices"][0]["finish_reason"] == "stop"
        assert d["object"] == "chat.completion"
        assert d["model"] == "Qwen/Qwen3-0.6B"
        assert d["id"].startswith("chatcmpl-")

    def test_finish_reason_length(self) -> None:
        resp = _make_response(finish_reason="length")
        d = proto_response_to_openai_dict(resp, "Qwen/Qwen3-0.6B")
        assert d["choices"][0]["finish_reason"] == "length"

    def test_usage_counts_correct(self) -> None:
        resp = _make_response(prompt_tokens=32, completion_tokens=10)
        d = proto_response_to_openai_dict(resp, "Qwen/Qwen3-0.6B")
        assert d["usage"]["prompt_tokens"] == 32
        assert d["usage"]["completion_tokens"] == 10
        assert d["usage"]["total_tokens"] == 42

    def test_message_content_and_role(self) -> None:
        resp = _make_response(content="hello there")
        d = proto_response_to_openai_dict(resp, "model")
        assert d["choices"][0]["message"]["content"] == "hello there"
        assert d["choices"][0]["message"]["role"] == "assistant"

    def test_choices_index_zero(self) -> None:
        d = proto_response_to_openai_dict(_make_response(), "model")
        assert d["choices"][0]["index"] == 0


_CMPL_ID = "chatcmpl-test"
_CREATED = 1700000000
_MODEL = "Qwen/Qwen3-0.6B"


def _parse_sse(line: str) -> dict[str, object]:
    assert line.startswith("data: ")
    return json.loads(line[6:])  # type: ignore[no-any-return]


class TestFormatSseRoleDelta:
    def test_role_delta_format(self) -> None:
        event = format_sse_role_delta(_CMPL_ID, _CREATED, _MODEL)
        assert event.endswith("\n\n")
        data = _parse_sse(event.strip())
        choice = data["choices"][0]  # type: ignore[index]
        assert choice["delta"] == {"role": "assistant", "content": ""}  # type: ignore[index]
        assert choice["finish_reason"] is None  # type: ignore[index]
        assert data["id"] == _CMPL_ID  # type: ignore[index]
        assert data["object"] == "chat.completion.chunk"  # type: ignore[index]


class TestProtoChunkToSseEvent:
    def test_mid_chunk_has_content_delta(self) -> None:
        chunk = chat_pb2.ChatStreamChunk(delta_content=" world", finish_reason="", token_index=1)
        event = proto_chunk_to_sse_event(chunk, _CMPL_ID, _CREATED, _MODEL)
        data = _parse_sse(event.strip())
        choice = data["choices"][0]  # type: ignore[index]
        assert choice["delta"] == {"content": " world"}  # type: ignore[index]
        assert choice["finish_reason"] is None  # type: ignore[index]

    def test_final_chunk_has_empty_delta_and_finish_reason(self) -> None:
        chunk = chat_pb2.ChatStreamChunk(delta_content="", finish_reason="stop", token_index=5)
        event = proto_chunk_to_sse_event(chunk, _CMPL_ID, _CREATED, _MODEL)
        data = _parse_sse(event.strip())
        choice = data["choices"][0]  # type: ignore[index]
        assert choice["delta"] == {}  # type: ignore[index]
        assert choice["finish_reason"] == "stop"  # type: ignore[index]

    def test_finish_reason_length(self) -> None:
        chunk = chat_pb2.ChatStreamChunk(delta_content="", finish_reason="length", token_index=3)
        event = proto_chunk_to_sse_event(chunk, _CMPL_ID, _CREATED, _MODEL)
        data = _parse_sse(event.strip())
        assert data["choices"][0]["finish_reason"] == "length"  # type: ignore[index]

    def test_model_and_created_preserved(self) -> None:
        chunk = chat_pb2.ChatStreamChunk(delta_content="hi", finish_reason="", token_index=0)
        event = proto_chunk_to_sse_event(chunk, _CMPL_ID, _CREATED, _MODEL)
        data = _parse_sse(event.strip())
        assert data["model"] == _MODEL  # type: ignore[index]
        assert data["created"] == _CREATED  # type: ignore[index]


class TestFormatSseDone:
    def test_done_format(self) -> None:
        assert format_sse_done() == "data: [DONE]\n\n"


class TestFormatSseError:
    def test_error_format(self) -> None:
        event = format_sse_error("something went wrong")
        assert event.endswith("\n\n")
        data = json.loads(event.strip()[6:])
        assert data["error"]["message"] == "something went wrong"
        assert data["error"]["type"] == "internal_error"
