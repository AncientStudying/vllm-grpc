from __future__ import annotations

from unittest.mock import MagicMock

from vllm_grpc.v1 import chat_pb2
from vllm_grpc_frontend.chat_translate import (
    messages_to_prompt,
    proto_to_sampling_params,
    request_output_to_proto,
)


def _make_request(
    *,
    max_tokens: int = 64,
    temperature: float | None = None,
    top_p: float | None = None,
    seed: int | None = None,
) -> chat_pb2.ChatCompleteRequest:
    kwargs: dict[str, object] = {
        "messages": [chat_pb2.ChatMessage(role="user", content="hi")],
        "model": "Qwen/Qwen3-0.6B",
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if top_p is not None:
        kwargs["top_p"] = top_p
    if seed is not None:
        kwargs["seed"] = seed
    return chat_pb2.ChatCompleteRequest(**kwargs)


def _make_output(
    text: str = "hello",
    finish_reason: str = "stop",
    prompt_token_ids: list[int] | None = None,
    output_token_ids: list[int] | None = None,
) -> MagicMock:
    output = MagicMock()
    output.prompt_token_ids = prompt_token_ids or [1, 2, 3, 4, 5]
    comp = MagicMock()
    comp.text = text
    comp.finish_reason = finish_reason
    comp.token_ids = output_token_ids or [6, 7, 8]
    output.outputs = [comp]
    return output


class TestProtoToSamplingParams:
    def test_seed_present(self) -> None:
        req = _make_request(seed=42)
        params = proto_to_sampling_params(req)
        assert params.seed == 42

    def test_seed_absent_no_seed_attr(self) -> None:
        req = _make_request()
        params = proto_to_sampling_params(req)
        assert params.seed is None

    def test_seed_zero_is_set(self) -> None:
        req = _make_request(seed=0)
        params = proto_to_sampling_params(req)
        assert params.seed == 0

    def test_temperature_default_when_absent(self) -> None:
        req = _make_request()
        params = proto_to_sampling_params(req)
        assert abs(params.temperature - 1.0) < 1e-5

    def test_temperature_explicit(self) -> None:
        req = _make_request(temperature=0.5)
        params = proto_to_sampling_params(req)
        assert abs(params.temperature - 0.5) < 1e-5

    def test_top_p_default_when_absent(self) -> None:
        req = _make_request()
        params = proto_to_sampling_params(req)
        assert abs(params.top_p - 1.0) < 1e-5

    def test_max_tokens_passed_through(self) -> None:
        req = _make_request(max_tokens=128)
        params = proto_to_sampling_params(req)
        assert params.max_tokens == 128


class TestRequestOutputToProto:
    def test_finish_reason_stop_with_token_counts(self) -> None:
        output = _make_output(
            text="2 + 2 = 4",
            finish_reason="stop",
            prompt_token_ids=list(range(10)),
            output_token_ids=list(range(5)),
        )
        resp = request_output_to_proto(output)
        assert resp.message.role == "assistant"
        assert resp.message.content == "2 + 2 = 4"
        assert resp.finish_reason == "stop"
        assert resp.prompt_tokens == 10
        assert resp.completion_tokens == 5

    def test_finish_reason_length(self) -> None:
        output = _make_output(finish_reason="length")
        resp = request_output_to_proto(output)
        assert resp.finish_reason == "length"

    def test_role_always_assistant(self) -> None:
        resp = request_output_to_proto(_make_output())
        assert resp.message.role == "assistant"


class TestOutputToStreamChunk:
    def test_delta_is_new_text_only(self) -> None:
        from vllm_grpc_frontend.chat_translate import output_to_stream_chunk

        output = _make_output(text="Hello world", finish_reason="stop")
        chunk = output_to_stream_chunk(output, token_index=1, prev_text="Hello")
        assert chunk.delta_content == " world"
        assert chunk.token_index == 1
        assert chunk.finish_reason == ""

    def test_empty_prev_text_gives_full_text(self) -> None:
        from vllm_grpc_frontend.chat_translate import output_to_stream_chunk

        output = _make_output(text="Hi", finish_reason=None)
        chunk = output_to_stream_chunk(output, token_index=0, prev_text="")
        assert chunk.delta_content == "Hi"
        assert chunk.token_index == 0

    def test_finish_reason_is_always_empty(self) -> None:
        from vllm_grpc_frontend.chat_translate import output_to_stream_chunk

        output = _make_output(text="done", finish_reason="stop")
        chunk = output_to_stream_chunk(output, token_index=5, prev_text="don")
        assert chunk.finish_reason == ""


class TestMessagesToPrompt:
    def test_apply_chat_template_called(self) -> None:
        tokenizer = MagicMock()
        tokenizer.apply_chat_template.return_value = "<prompt>"
        messages = [chat_pb2.ChatMessage(role="user", content="hello")]
        result = messages_to_prompt(messages, tokenizer)
        assert result == "<prompt>"
        tokenizer.apply_chat_template.assert_called_once_with(
            [{"role": "user", "content": "hello"}],
            tokenize=False,
            add_generation_prompt=True,
        )
