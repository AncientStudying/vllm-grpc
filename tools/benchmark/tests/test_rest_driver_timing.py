"""M6.2 REST driver timing extraction tests.

Asserts that ``_drive_rest_chat_stream_m6_2`` and ``_drive_rest_embed_m6_2``
parse the M6.1.1 ``m6_1_1_timings`` sub-object from the REST shim's terminal
SSE event (chat) or JSON body (embed) and populate
:attr:`RPCResult.m6_1_1_timing_payload` so the M6.2 per-segment aggregator
can decompose REST cohorts the same way it decomposes gRPC. Regression for
observation 105 (REST drivers previously dropped timing instrumentation,
making the REST regression diagnostically opaque).
"""

from __future__ import annotations

import json

import httpx
import pytest
from vllm_grpc_bench.rpc_driver import (
    _drive_rest_chat_stream_m6_2,
    _drive_rest_embed_m6_2,
)
from vllm_grpc_bench.types import Cell as M6_1Cell


def _valid_m6_1_1_sub_object() -> dict[str, int]:
    return {
        "handler_entry_ns": 1_000_000,
        "pre_engine_ns": 2_500_000,
        "first_chunk_ns": 42_500_000,
        "terminal_emit_ns": 44_000_000,
        "perturbation_audit_ns": 240,
    }


def _make_chat_stream_transport(*, with_timing: bool) -> httpx.MockTransport:
    """Mock /v1/chat/completions returning SSE chunks with optional final
    terminal event carrying ``m6_1_1_timings``."""

    def _chunk(delta: str | None, terminal: dict[str, object] | None) -> bytes:
        body: dict[str, object] = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": delta} if delta is not None else {},
                    "finish_reason": "stop" if terminal is not None else None,
                }
            ],
        }
        if terminal is not None:
            body.update(terminal)
        return f"data: {json.dumps(body)}\n\n".encode()

    terminal: dict[str, object] = {
        "engine_cost": {
            "engine_ttft_ms": 43.5,
            "engine_tpot_ms": 12.7,
            "engine_forward_ms": 80.0,
        },
    }
    if with_timing:
        terminal["m6_1_1_timings"] = _valid_m6_1_1_sub_object()

    body_bytes = b"".join(
        [
            _chunk("Hello", None),
            _chunk(" world", None),
            _chunk(None, terminal),
            b"data: [DONE]\n\n",
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body_bytes,
        )

    return httpx.MockTransport(handler)


def _make_embed_transport(*, with_timing: bool) -> httpx.MockTransport:
    """Mock /v1/embeddings returning a JSON body with optional m6_1_1_timings."""
    body: dict[str, object] = {
        "data": [{"embedding": [0.0]}],
        "engine_cost": {"engine_forward_ms": 80.0},
    }
    if with_timing:
        body["m6_1_1_timings"] = _valid_m6_1_1_sub_object()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


# --- chat_stream ------------------------------------------------------------


@pytest.mark.asyncio
async def test_rest_chat_stream_populates_m6_1_1_timing_payload() -> None:
    transport = _make_chat_stream_transport(with_timing=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        result = await _drive_rest_chat_stream_m6_2(
            client,
            "http://test",
            {"authorization": "Bearer t"},
            seed=1,
            timeout_s=5.0,
            max_tokens=10,
            ignore_eos=False,
            prompt=None,
        )
    assert result.success is True
    assert result.m6_1_1_timing_payload is not None
    assert result.m6_1_1_timing_payload["handler_entry_ns"] == 1_000_000
    assert result.m6_1_1_timing_payload["pre_engine_ns"] == 2_500_000
    assert result.m6_1_1_timing_payload["first_chunk_ns"] == 42_500_000
    assert result.m6_1_1_timing_payload["terminal_emit_ns"] == 44_000_000


@pytest.mark.asyncio
async def test_rest_chat_stream_populates_engine_cost() -> None:
    """Regression: REST chat stream must surface engine_cost so the aggregator
    can compute tpot_ms / ttft_ms / forward_ms per cohort."""
    transport = _make_chat_stream_transport(with_timing=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        result = await _drive_rest_chat_stream_m6_2(
            client,
            "http://test",
            {"authorization": "Bearer t"},
            seed=1,
            timeout_s=5.0,
            max_tokens=10,
            ignore_eos=False,
            prompt=None,
        )
    assert result.engine_cost is not None
    assert result.engine_cost.engine_tpot_ms == pytest.approx(12.7)


@pytest.mark.asyncio
async def test_rest_chat_stream_degrades_to_none_when_timing_absent() -> None:
    """Pre-M6.1.1 shim emits no m6_1_1_timings sub-object — payload stays None
    rather than carrying a partial / malformed dict."""
    transport = _make_chat_stream_transport(with_timing=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        result = await _drive_rest_chat_stream_m6_2(
            client,
            "http://test",
            {"authorization": "Bearer t"},
            seed=1,
            timeout_s=5.0,
            max_tokens=10,
            ignore_eos=False,
            prompt=None,
        )
    assert result.success is True
    assert result.m6_1_1_timing_payload is None
    # engine_cost should still come through (the shim emits that under M6, not M6.1.1)
    assert result.engine_cost is not None


# --- embed ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rest_embed_populates_m6_1_1_timing_payload() -> None:
    transport = _make_embed_transport(with_timing=True)
    cell = M6_1Cell(path="embed", hidden_size=4096, concurrency=1)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        result = await _drive_rest_embed_m6_2(
            client,
            "http://test",
            {"authorization": "Bearer t"},
            cell,
            seq_len=8,
            rpc_index=0,
            base_seed=42,
            timeout_s=5.0,
            max_tokens=10,
            ignore_eos=False,
            prompt_embeds_override=None,
        )
    assert result.success is True
    assert result.m6_1_1_timing_payload is not None
    assert result.m6_1_1_timing_payload["handler_entry_ns"] == 1_000_000
    assert result.m6_1_1_timing_payload["pre_engine_ns"] == 2_500_000


@pytest.mark.asyncio
async def test_rest_embed_degrades_to_none_when_timing_absent() -> None:
    transport = _make_embed_transport(with_timing=False)
    cell = M6_1Cell(path="embed", hidden_size=4096, concurrency=1)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        result = await _drive_rest_embed_m6_2(
            client,
            "http://test",
            {"authorization": "Bearer t"},
            cell,
            seq_len=8,
            rpc_index=0,
            base_seed=42,
            timeout_s=5.0,
            max_tokens=10,
            ignore_eos=False,
            prompt_embeds_override=None,
        )
    assert result.success is True
    assert result.m6_1_1_timing_payload is None
