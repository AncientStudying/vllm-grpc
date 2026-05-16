"""Tests for the M6.1 gRPC embed driver (T018).

Asserts the wire format (ZIP magic prefix), round-trip through the frontend's
``decode_embeds``, and bit-reproducibility per RPC index (FR-028 / SC-006).
"""

from __future__ import annotations

import base64

import torch
from vllm_grpc_bench.m6_1_rpc_driver import (
    _build_embed_grpc_request,
    _build_embed_rest_payload_m6_1,
    build_torch_save_bytes,
)


def test_grpc_request_has_zip_magic_prefix() -> None:
    req = _build_embed_grpc_request(seq_len=8, hidden_size=4096, rpc_index=0, base_seed=42)
    assert req.prompt_embeds[:4] == b"PK\x03\x04"
    assert req.max_tokens == 10
    assert req.seed == 42


def test_grpc_payload_round_trips_via_decode_embeds() -> None:
    from vllm_grpc_frontend.completions_translate import decode_embeds

    req = _build_embed_grpc_request(seq_len=8, hidden_size=4096, rpc_index=3, base_seed=42)
    tensor = decode_embeds(req.prompt_embeds)
    assert tensor.shape == (8, 4096)
    assert tensor.dtype == torch.float16


def test_grpc_payload_bit_reproducible_per_rpc_index() -> None:
    req1 = _build_embed_grpc_request(seq_len=8, hidden_size=4096, rpc_index=7, base_seed=42)
    req2 = _build_embed_grpc_request(seq_len=8, hidden_size=4096, rpc_index=7, base_seed=42)
    assert req1.prompt_embeds == req2.prompt_embeds


def test_grpc_payload_differs_across_rpc_indices() -> None:
    req1 = _build_embed_grpc_request(seq_len=8, hidden_size=4096, rpc_index=0, base_seed=42)
    req2 = _build_embed_grpc_request(seq_len=8, hidden_size=4096, rpc_index=1, base_seed=42)
    assert req1.prompt_embeds != req2.prompt_embeds


def test_rest_payload_has_torch_b64_input_kind() -> None:
    payload = _build_embed_rest_payload_m6_1(seq_len=8, hidden_size=4096, rpc_index=0, base_seed=42)
    assert payload["input_kind"] == "prompt_embedding_torch_b64"
    assert payload["hidden_size"] == 4096
    assert payload["max_tokens"] == 10
    assert payload["seed"] == 42
    raw = base64.b64decode(payload["input"])
    assert raw[:4] == b"PK\x03\x04"


def test_rest_payload_round_trips_via_decode_embeds() -> None:
    from vllm_grpc_frontend.completions_translate import decode_embeds

    payload = _build_embed_rest_payload_m6_1(seq_len=8, hidden_size=4096, rpc_index=5, base_seed=42)
    raw = base64.b64decode(payload["input"])
    tensor = decode_embeds(raw)
    assert tensor.shape == (8, 4096)
    assert tensor.dtype == torch.float16


def test_build_torch_save_bytes_zip_magic() -> None:
    raw = build_torch_save_bytes(seq_len=8, hidden_size=4096, rpc_index=0, base_seed=42)
    assert raw[:4] == b"PK\x03\x04"
