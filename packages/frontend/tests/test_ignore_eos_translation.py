from __future__ import annotations

from vllm_grpc.v1 import chat_pb2, completions_pb2
from vllm_grpc_frontend.chat_translate import (
    proto_to_sampling_params as chat_proto_to_sampling_params,
)
from vllm_grpc_frontend.completions_translate import (
    proto_to_sampling_params as completions_proto_to_sampling_params,
)


class TestChatIgnoreEosRoundTrip:
    def test_ignore_eos_true_round_trips(self) -> None:
        req = chat_pb2.ChatCompleteRequest(
            messages=[chat_pb2.ChatMessage(role="user", content="hi")],
            model="Qwen/Qwen3-8B",
            max_tokens=64,
            ignore_eos=True,
        )
        params = chat_proto_to_sampling_params(req)
        assert params.ignore_eos is True

    def test_ignore_eos_default_is_false(self) -> None:
        req = chat_pb2.ChatCompleteRequest(
            messages=[chat_pb2.ChatMessage(role="user", content="hi")],
            model="Qwen/Qwen3-8B",
            max_tokens=64,
        )
        params = chat_proto_to_sampling_params(req)
        assert params.ignore_eos is False

    def test_ignore_eos_false_explicit_round_trips(self) -> None:
        req = chat_pb2.ChatCompleteRequest(
            messages=[chat_pb2.ChatMessage(role="user", content="hi")],
            model="Qwen/Qwen3-8B",
            max_tokens=64,
            ignore_eos=False,
        )
        params = chat_proto_to_sampling_params(req)
        assert params.ignore_eos is False


class TestCompletionsIgnoreEosRoundTrip:
    def test_ignore_eos_true_round_trips(self) -> None:
        req = completions_pb2.CompletionRequest(
            model="Qwen/Qwen3-8B",
            max_tokens=64,
            prompt="hello",
            ignore_eos=True,
        )
        params = completions_proto_to_sampling_params(req)
        assert params.ignore_eos is True

    def test_ignore_eos_default_is_false(self) -> None:
        req = completions_pb2.CompletionRequest(
            model="Qwen/Qwen3-8B",
            max_tokens=64,
            prompt="hello",
        )
        params = completions_proto_to_sampling_params(req)
        assert params.ignore_eos is False

    def test_ignore_eos_with_prompt_embeds_oneof(self) -> None:
        req = completions_pb2.CompletionRequest(
            model="Qwen/Qwen3-8B",
            max_tokens=64,
            prompt_embeds=b"\x00" * 16,
            ignore_eos=True,
        )
        params = completions_proto_to_sampling_params(req)
        assert params.ignore_eos is True
