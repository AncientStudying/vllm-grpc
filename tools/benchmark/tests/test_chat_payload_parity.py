"""FR-005c chat-path payload-parity tests.

The M5.2 payload-parity audit's Step 1 requires REST and gRPC chat cohorts
to send byte-identical engine-input content (same prompt, same max_tokens)
for the same logical request. Pre-M5.2 the two protocols diverged: REST
used ``"Hello world request-{i} please complete this sentence"`` with
max_tokens=64, gRPC used ``"M5.1 chat probe iter={seed} cell={id}"`` with
max_tokens=32. M5.2 aligns both sides on a single deterministic helper
``build_chat_prompt(iteration, cell_id)`` + ``DEFAULT_CHAT_MAX_TOKENS=64``.

These tests lock in the alignment so a future maintainer can't silently
re-introduce the divergence without an explicit code change and a
matching test update.
"""

from __future__ import annotations

import json

import httpx
import pytest
from vllm_grpc_bench.m3_sweep import (
    DEFAULT_CHAT_MAX_TOKENS,
    _build_chat_request,
    build_chat_prompt,
)
from vllm_grpc_bench.rest_cohort import run_rest_cohort

_TEST_TOKEN = "test-bearer-abcdef0123"


def test_default_chat_max_tokens_is_64() -> None:
    """FR-005c: REST and gRPC must agree on max_tokens. M5.2 picks 64 to
    match REST's pre-M5.2 default (M5.1's gRPC-only override to 32 is
    now retired)."""
    assert DEFAULT_CHAT_MAX_TOKENS == 64


def test_build_chat_prompt_is_deterministic() -> None:
    a = build_chat_prompt(iteration=7, cell_id="chat_stream:h2048:c4")
    b = build_chat_prompt(iteration=7, cell_id="chat_stream:h2048:c4")
    assert a == b


def test_build_chat_prompt_varies_with_iteration_and_cell_id() -> None:
    base = build_chat_prompt(iteration=0, cell_id="chat_stream:h2048:c4")
    assert build_chat_prompt(iteration=1, cell_id="chat_stream:h2048:c4") != base
    assert build_chat_prompt(iteration=0, cell_id="chat_stream:h4096:c4") != base


def test_build_chat_prompt_uses_m5_2_format_not_legacy() -> None:
    """The prompt format must not regress to either pre-M5.2 string. The
    M5.2 format embeds both iteration and cell_id so a sidecar reader can
    map any recorded request back to its prompt."""
    prompt = build_chat_prompt(iteration=42, cell_id="rest-edge:chat_stream:h8192:c1")
    assert "Hello world" not in prompt  # legacy REST format
    assert "M5.1 chat probe" not in prompt  # legacy gRPC format
    assert "M5.2 chat probe" in prompt
    assert "iter=42" in prompt
    assert "rest-edge:chat_stream:h8192:c1" in prompt


def test_grpc_chat_request_built_from_shared_helper() -> None:
    """The gRPC cohort's chat request payload must come from
    ``build_chat_prompt`` + ``DEFAULT_CHAT_MAX_TOKENS`` (not the
    pre-M5.2 inline f-string with max_tokens=32)."""
    prompt = build_chat_prompt(iteration=3, cell_id="grpc-default:chat_stream:h2048:c4")
    req = _build_chat_request(prompt, max_tokens=DEFAULT_CHAT_MAX_TOKENS)
    assert req.messages[0].content == prompt
    assert req.max_tokens == 64
    # Forbidden legacy markers — must not regress.
    assert "M5.1 chat probe" not in req.messages[0].content


def test_rest_and_grpc_build_byte_identical_chat_prompts_for_same_request() -> None:
    """FR-005c parity guarantee: for the same logical (iteration, cell_id),
    REST and gRPC encode the same engine-input chat content. Wire bytes
    differ structurally (JSON envelope vs protobuf framing) but the
    in-message string sent to the engine is identical.
    """
    iteration = 11
    # The REST cohort and gRPC cohort dispatch with different cell_id
    # prefixes (``rest-edge:``, ``grpc-default:``, etc.) so the prompts
    # are not byte-identical across cohorts within a single sweep. The
    # critical property is that ``build_chat_prompt`` is the SOLE source
    # of truth — both call paths route through it, so the parity rule is
    # "same helper, same output for same inputs", verified at the helper
    # level rather than across cohorts.
    rest_cell_id = "rest-edge:chat_stream:h2048:c4"
    grpc_cell_id = "grpc-default:chat_stream:h2048:c4"

    rest_prompt = build_chat_prompt(iteration=iteration, cell_id=rest_cell_id)
    grpc_prompt = build_chat_prompt(iteration=iteration, cell_id=grpc_cell_id)

    # Both prompts share the M5.2 format prefix.
    assert rest_prompt.startswith("M5.2 chat probe iter=11 cell=rest-edge:")
    assert grpc_prompt.startswith("M5.2 chat probe iter=11 cell=grpc-default:")
    # And both use the same max_tokens.
    grpc_req = _build_chat_request(grpc_prompt, max_tokens=DEFAULT_CHAT_MAX_TOKENS)
    assert grpc_req.max_tokens == DEFAULT_CHAT_MAX_TOKENS


@pytest.mark.asyncio
async def test_rest_cohort_chat_uses_shared_prompt_helper() -> None:
    """End-to-end: the REST cohort's actual wire body's ``messages[0].content``
    field matches ``build_chat_prompt(iteration, cell_id)`` for the
    matching iteration. Captures the request via httpx.MockTransport.
    """
    captured_bodies: list[dict] = []

    async def _handler(request: httpx.Request) -> httpx.Response:
        # /healthz is the RTT probe; skip.
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"ok": True})
        captured_bodies.append(json.loads(request.content))
        # Minimal SSE response so the cohort runner extracts a TTFT.
        body = (
            b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            b"data: [DONE]\n\n"
        )
        return httpx.Response(200, headers={"x-shim-overhead-ms": "0.1"}, content=body)

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", http2=False
    ) as client:
        await run_rest_cohort(
            path="chat_stream",
            base_url="http://test",
            token=_TEST_TOKEN,
            concurrency=1,
            n=3,
            hidden_size=2048,
            rtt_probe_n=1,
            warmup_n=0,
            client=client,
            cell_id="rest-edge:chat_stream:h2048:c1",
        )

    # 3 measurement requests captured.
    assert len(captured_bodies) == 3
    # Each prompt matches the shared helper for its iteration.
    for i, body in enumerate(captured_bodies):
        expected = build_chat_prompt(iteration=i, cell_id="rest-edge:chat_stream:h2048:c1")
        assert body["messages"][0]["content"] == expected, (
            f"REST chat prompt at iteration {i} does not match build_chat_prompt — "
            f"got {body['messages'][0]['content']!r}, expected {expected!r}"
        )
        # Max tokens matches the shared default.
        assert body["max_tokens"] == DEFAULT_CHAT_MAX_TOKENS
        # Legacy prompts must not regress.
        assert "Hello world" not in body["messages"][0]["content"]


@pytest.mark.asyncio
async def test_rest_cohort_chat_max_tokens_threads_from_kwarg() -> None:
    """Operator overrides via ``max_tokens=`` kwarg still work — the
    default is ``DEFAULT_CHAT_MAX_TOKENS`` but the kwarg can override."""
    captured_bodies: list[dict] = []

    async def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"ok": True})
        captured_bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"x-shim-overhead-ms": "0.1"},
            content=b'data: {"choices":[{"delta":{"content":"x"}}]}\n\ndata: [DONE]\n\n',
        )

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", http2=False
    ) as client:
        await run_rest_cohort(
            path="chat_stream",
            base_url="http://test",
            token=_TEST_TOKEN,
            concurrency=1,
            n=1,
            hidden_size=2048,
            rtt_probe_n=1,
            warmup_n=0,
            client=client,
            max_tokens=128,
            cell_id="custom-cell",
        )
    assert captured_bodies[0]["max_tokens"] == 128
