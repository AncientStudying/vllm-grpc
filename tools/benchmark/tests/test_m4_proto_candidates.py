"""US3 / T036 — candidate stubs are importable after ``make proto``.

Constitution I (Proto-First) requires every wire-format change to start with
a ``.proto`` edit and forbids hand-written equivalents. This test confirms
the three M4 candidates emit usable Python stubs.

The candidate stubs land at ``vllm_grpc.v1.m4_candidates.<candidate>_pb2``
(the proto packages map to that path); the contract document phrased the
import path as ``packages.gen.vllm_grpc_m4_candidates.<candidate>``, but the
intent is "these stubs are importable after ``make proto``" and that is
satisfied by the actual installed package layout.
"""

from __future__ import annotations


def test_packed_token_ids_stub_importable() -> None:
    from vllm_grpc.v1.m4_candidates import packed_token_ids_pb2

    chunk = packed_token_ids_pb2.ChatStreamChunk(
        delta_content="hi", finish_reason="", token_index=0, token_ids=[1, 2, 3]
    )
    serialized = chunk.SerializeToString()
    decoded = packed_token_ids_pb2.ChatStreamChunk.FromString(serialized)
    assert list(decoded.token_ids) == [1, 2, 3]


def test_oneof_flattened_input_stub_importable() -> None:
    from vllm_grpc.v1.m4_candidates import oneof_flattened_input_pb2

    req = oneof_flattened_input_pb2.CompletionRequest(
        model="m",
        max_tokens=10,
        input_kind=oneof_flattened_input_pb2.INPUT_KIND_PROMPT,
        prompt="hello",
    )
    decoded = oneof_flattened_input_pb2.CompletionRequest.FromString(req.SerializeToString())
    assert decoded.prompt == "hello"
    assert decoded.input_kind == oneof_flattened_input_pb2.INPUT_KIND_PROMPT


def test_chunk_granularity_stub_importable() -> None:
    from vllm_grpc.v1.m4_candidates import chunk_granularity_pb2

    chunk = chunk_granularity_pb2.ChatStreamChunk(
        delta_content="abcd",
        finish_reason="",
        token_index=0,
        tokens_in_chunk=4,
        token_ids=[1, 2, 3, 4],
    )
    decoded = chunk_granularity_pb2.ChatStreamChunk.FromString(chunk.SerializeToString())
    assert decoded.tokens_in_chunk == 4
    assert list(decoded.token_ids) == [1, 2, 3, 4]
