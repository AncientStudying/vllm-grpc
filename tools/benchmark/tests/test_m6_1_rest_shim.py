"""Tests for the M6.1 REST shim ``input_kind`` extension (T021).

Asserts:
* ``prompt_embedding_torch_b64`` round-trips through ``decode_embeds`` and
  routes through the real prompt-embeds engine path.
* The existing ``prompt_embedding_b64`` path is unchanged (FR-004 regression
  guard).
* Malformed base64 → HTTP 400; malformed torch.save bytes → HTTP 422.
"""

from __future__ import annotations

import base64
import io
import json
from typing import Any

import httpx
import numpy as np
import pytest
import torch
from vllm_grpc_bench.mock_engine import MockEngine, MockEngineConfig
from vllm_grpc_bench.rest_shim import build_rest_shim

_TOKEN = "test-token"


class _RecordingEngine:
    """Wraps MockEngine; records ``prompt`` for one of its calls."""

    def __init__(self, base: MockEngine) -> None:
        self._base = base
        self.last_prompt: Any = None

    async def generate(self, prompt: Any, sampling_params: Any, *, request_id: str) -> Any:
        self.last_prompt = prompt
        async for chunk in self._base.generate(prompt, sampling_params, request_id=request_id):
            yield chunk


def _build_recording_shim() -> tuple[Any, _RecordingEngine]:
    base = MockEngine(
        MockEngineConfig(
            hidden_size=4096,
            seed=0,
            tokens_per_second=200.0,
            max_tokens_per_stream=8,
            pace_tokens=False,
        )
    )
    rec = _RecordingEngine(base)
    return build_rest_shim(rec, expected_token=_TOKEN), rec


def _torch_save_b64(seq_len: int, hidden_size: int) -> str:
    t = torch.randn((seq_len, hidden_size), dtype=torch.float16)
    buf = io.BytesIO()
    torch.save(t, buf)
    return base64.b64encode(buf.getvalue()).decode("ascii")


@pytest.mark.asyncio
async def test_torch_b64_path_routes_to_prompt_embeds_dict() -> None:
    shim, rec = _build_recording_shim()
    body = {
        "model": "mock",
        "input_kind": "prompt_embedding_torch_b64",
        "input": _torch_save_b64(8, 4096),
        "hidden_size": 4096,
        "max_tokens": 10,
        "seed": 42,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=shim), base_url="http://shim"
    ) as client:
        resp = await client.post(
            "/v1/embeddings",
            content=json.dumps(body).encode(),
            headers={
                "authorization": f"Bearer {_TOKEN}",
                "content-type": "application/json",
            },
        )
    assert resp.status_code == 200
    payload = resp.json()
    assert "engine_cost" in payload
    assert "engine_forward_ms" in payload["engine_cost"]
    # Engine saw a dict with prompt_embeds (real engine path).
    assert isinstance(rec.last_prompt, dict)
    assert "prompt_embeds" in rec.last_prompt
    assert rec.last_prompt["prompt_embeds"].shape == (8, 4096)
    assert rec.last_prompt["prompt_embeds"].dtype == torch.float16


@pytest.mark.asyncio
async def test_legacy_b64_path_still_routes_to_text_digest() -> None:
    """FR-004 regression guard — the M5.x / M6 path is unchanged."""
    shim, rec = _build_recording_shim()
    rng = np.random.default_rng(seed=0)
    tensor = rng.standard_normal((16, 4096), dtype=np.float32)
    body = {
        "model": "mock",
        "input_kind": "prompt_embedding_b64",
        "input": base64.b64encode(tensor.tobytes()).decode("ascii"),
        "hidden_size": 4096,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=shim), base_url="http://shim"
    ) as client:
        resp = await client.post(
            "/v1/embeddings",
            content=json.dumps(body).encode(),
            headers={
                "authorization": f"Bearer {_TOKEN}",
                "content-type": "application/json",
            },
        )
    assert resp.status_code == 200
    # Engine saw a text digest (NOT a dict).
    assert isinstance(rec.last_prompt, str)
    assert rec.last_prompt.startswith("embeds:")


@pytest.mark.asyncio
async def test_torch_b64_invalid_base64_returns_400() -> None:
    shim, _ = _build_recording_shim()
    body = {
        "model": "mock",
        "input_kind": "prompt_embedding_torch_b64",
        "input": "!!!not base64!!!",
        "hidden_size": 4096,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=shim), base_url="http://shim"
    ) as client:
        resp = await client.post(
            "/v1/embeddings",
            content=json.dumps(body).encode(),
            headers={
                "authorization": f"Bearer {_TOKEN}",
                "content-type": "application/json",
            },
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_torch_b64_malformed_returns_422() -> None:
    shim, _ = _build_recording_shim()
    # Valid base64 but the decoded bytes are NOT a torch.save payload.
    body = {
        "model": "mock",
        "input_kind": "prompt_embedding_torch_b64",
        "input": base64.b64encode(b"not a torch save file").decode("ascii"),
        "hidden_size": 4096,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=shim), base_url="http://shim"
    ) as client:
        resp = await client.post(
            "/v1/embeddings",
            content=json.dumps(body).encode(),
            headers={
                "authorization": f"Bearer {_TOKEN}",
                "content-type": "application/json",
            },
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_unsupported_input_kind_returns_422() -> None:
    shim, _ = _build_recording_shim()
    body = {
        "model": "mock",
        "input_kind": "not_a_real_kind",
        "input": "x",
        "hidden_size": 4096,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=shim), base_url="http://shim"
    ) as client:
        resp = await client.post(
            "/v1/embeddings",
            content=json.dumps(body).encode(),
            headers={
                "authorization": f"Bearer {_TOKEN}",
                "content-type": "application/json",
            },
        )
    assert resp.status_code == 422
