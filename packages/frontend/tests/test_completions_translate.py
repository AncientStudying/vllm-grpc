from __future__ import annotations

import io
from typing import Any

import pytest

torch: Any = pytest.importorskip("torch")

from vllm_grpc.v1 import completions_pb2  # noqa: E402
from vllm_grpc_frontend.completions_translate import (  # noqa: E402
    decode_embeds,
    proto_to_sampling_params,
)


def _make_tensor_bytes(tensor: Any) -> bytes:
    buf = io.BytesIO()
    torch.save(tensor, buf)
    return buf.getvalue()


def test_decode_embeds_valid_float32() -> None:
    raw = _make_tensor_bytes(torch.zeros(4, 8))
    tensor = decode_embeds(raw)
    assert tensor.shape == (4, 8)
    assert tensor.dtype == torch.float32


def test_decode_embeds_valid_bfloat16() -> None:
    raw = _make_tensor_bytes(torch.zeros(4, 8, dtype=torch.bfloat16))
    tensor = decode_embeds(raw)
    assert tensor.dtype == torch.bfloat16


def test_decode_embeds_valid_float16() -> None:
    raw = _make_tensor_bytes(torch.zeros(4, 8, dtype=torch.float16))
    tensor = decode_embeds(raw)
    assert tensor.dtype == torch.float16


def test_decode_embeds_wrong_dtype() -> None:
    raw = _make_tensor_bytes(torch.zeros(4, 8, dtype=torch.int64))
    with pytest.raises(ValueError, match="dtype"):
        decode_embeds(raw)


def test_decode_embeds_wrong_ndim() -> None:
    raw = _make_tensor_bytes(torch.zeros(8))
    with pytest.raises(ValueError, match="2-D"):
        decode_embeds(raw)


def test_decode_embeds_corrupted_bytes() -> None:
    with pytest.raises(ValueError, match="Failed to deserialize"):
        decode_embeds(b"not valid")


def test_proto_to_sampling_params_temperature_top_p_seed() -> None:
    req = completions_pb2.CompletionRequest(
        model="test",
        max_tokens=16,
        temperature=0.5,
        top_p=0.9,
        seed=42,
        prompt="hi",
    )
    params = proto_to_sampling_params(req)
    assert params.max_tokens == 16
    assert params.temperature == pytest.approx(0.5)
    assert params.top_p == pytest.approx(0.9)
    assert params.seed == 42


def test_proto_to_sampling_params_absent_optional_fields() -> None:
    req = completions_pb2.CompletionRequest(
        model="test",
        max_tokens=32,
        prompt="hi",
    )
    params = proto_to_sampling_params(req)
    assert params.max_tokens == 32
    assert params.temperature == pytest.approx(1.0)
    assert params.top_p == pytest.approx(1.0)
    assert not hasattr(params, "seed") or params.seed is None
