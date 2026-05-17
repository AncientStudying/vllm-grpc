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


def test_resolve_rpc_index_handles_smoke_warmup_seed_zero() -> None:
    """Regression: smoke + warmup pass seed=0; driver must NOT compute a
    negative rpc_index (would crash build_torch_generator_for_rpc)."""
    from vllm_grpc_bench.m6_1_rpc_driver import _resolve_rpc_index

    # Smoke + warmup convention: seed=0 → clamp to rpc_index=0.
    assert _resolve_rpc_index(0, base_seed=42) == 0
    assert _resolve_rpc_index(0, base_seed=1) == 0

    # Measurement RPCs: seed = base_seed + rpc_index.
    assert _resolve_rpc_index(42, base_seed=42) == 0
    assert _resolve_rpc_index(43, base_seed=42) == 1
    assert _resolve_rpc_index(141, base_seed=42) == 99


def test_smoke_seed_builds_valid_payload() -> None:
    """End-to-end regression for the smoke/warmup seed=0 → torch.save path."""
    from vllm_grpc_bench.m6_1_rpc_driver import _resolve_rpc_index

    rpc_index = _resolve_rpc_index(0, base_seed=42)
    # If the clamp is missing this raises ValueError("rpc_index must be >= 0").
    raw = build_torch_save_bytes(seq_len=8, hidden_size=4096, rpc_index=rpc_index, base_seed=42)
    assert raw[:4] == b"PK\x03\x04"


# --- M6.1.2: REST URL scheme normalization for httpx ------------------------


def test_normalize_rest_url_for_httpx_rewrites_tcp_plaintext() -> None:
    """Modal publishes plain-TCP tunnels as ``tcp+plaintext://host:port``;
    httpx only speaks HTTP/HTTPS, so the driver must rewrite the scheme to
    ``http://``. M5.2 documents the same transform at
    m5_2_sweep.py:1280-1283; M6.1.2's provide_m6_1_2_rpc_driver applies it
    inline via _normalize_rest_url_for_httpx. Regression: a live Modal
    sweep failed with UnsupportedProtocol("tcp+plaintext://") because the
    raw URL was being passed straight to httpx.
    """
    from vllm_grpc_bench.m6_1_rpc_driver import _normalize_rest_url_for_httpx

    assert (
        _normalize_rest_url_for_httpx("tcp+plaintext://r439.modal.host:43209")
        == "http://r439.modal.host:43209"
    )


def test_normalize_rest_url_for_httpx_passes_https_unchanged() -> None:
    """HTTPS edge URLs are httpx-compatible already; no rewrite."""
    from vllm_grpc_bench.m6_1_rpc_driver import _normalize_rest_url_for_httpx

    url = "https://ta-01krv2x8qxtbbrr9zc28t0mk2x.w.modal.host"
    assert _normalize_rest_url_for_httpx(url) == url


def test_normalize_rest_url_for_httpx_prepends_http_to_bare_host_port() -> None:
    """Bare ``host:port`` → assume plain HTTP. Matches the M5.2 fallback."""
    from vllm_grpc_bench.m6_1_rpc_driver import _normalize_rest_url_for_httpx

    assert _normalize_rest_url_for_httpx("r439.modal.host:43209") == "http://r439.modal.host:43209"
