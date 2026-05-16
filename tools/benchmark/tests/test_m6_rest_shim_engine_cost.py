"""Tests for the M6 REST shim engine_cost emission (T010).

Asserts that ``/v1/embeddings`` carries a top-level ``engine_cost`` object
with ``engine_forward_ms`` (FR-008 / contracts/instrumentation.md §2), and
that the terminal SSE event on ``/v1/chat/completions?stream=true``
carries an ``engine_cost`` object with ``engine_ttft_ms`` and
``engine_tpot_ms`` immediately before the ``[DONE]`` sentinel.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import numpy as np
import pytest
from vllm_grpc_bench.mock_engine import MockEngine, MockEngineConfig
from vllm_grpc_bench.rest_shim import build_rest_shim

_TOKEN = "test-token"


def _build_shim() -> Any:
    engine = MockEngine(
        MockEngineConfig(
            hidden_size=4096,
            seed=0,
            tokens_per_second=200.0,
            max_tokens_per_stream=8,
            pace_tokens=False,
        )
    )
    return build_rest_shim(engine, expected_token=_TOKEN)


@pytest.mark.asyncio
async def test_embed_endpoint_emits_engine_cost() -> None:
    shim = _build_shim()
    seq_len, hidden = 16, 4096
    rng = np.random.default_rng(seed=42)
    tensor = rng.standard_normal((seq_len, hidden), dtype=np.float32)
    encoded = base64.b64encode(tensor.tobytes()).decode("ascii")
    body = {
        "model": "mock",
        "input_kind": "prompt_embedding_b64",
        "input": encoded,
        "hidden_size": hidden,
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
    ec = payload["engine_cost"]
    assert "engine_forward_ms" in ec
    assert isinstance(ec["engine_forward_ms"], (int, float))
    assert ec["engine_forward_ms"] >= 0


@pytest.mark.asyncio
async def test_chat_stream_terminal_event_carries_engine_cost() -> None:
    shim = _build_shim()
    body = {
        "model": "mock",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
        "max_tokens": 4,
    }
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=shim), base_url="http://shim"
        ) as client,
        client.stream(
            "POST",
            "/v1/chat/completions",
            content=json.dumps(body).encode(),
            headers={
                "authorization": f"Bearer {_TOKEN}",
                "content-type": "application/json",
            },
        ) as resp,
    ):
        assert resp.status_code == 200
        data_lines: list[str] = []
        async for line in resp.aiter_lines():
            if line.startswith("data:") and "[DONE]" not in line:
                data_lines.append(line[len("data:") :].strip())

    # The LAST data: event (just before [DONE]) MUST carry engine_cost.
    assert data_lines, "expected at least one SSE data: event"
    terminal = json.loads(data_lines[-1])
    assert "engine_cost" in terminal, "terminal SSE event missing engine_cost"
    ec = terminal["engine_cost"]
    assert "engine_ttft_ms" in ec
    assert "engine_tpot_ms" in ec
    assert isinstance(ec["engine_ttft_ms"], (int, float))
    assert isinstance(ec["engine_tpot_ms"], (int, float))
    # finish_reason must be set on the terminal event (data-model.md).
    assert terminal["choices"][0].get("finish_reason") is not None
