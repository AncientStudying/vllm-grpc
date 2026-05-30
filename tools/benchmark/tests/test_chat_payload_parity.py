"""FR-003 chat-prompt unification tests.

v0.0.1 collapses the formerly divergent chat-prompt builders into a single
``prompts.build_chat_prompt`` keyed by an integer seed. Pre-v0.0.1 the harness
carried two builders: M5.2's ``build_chat_prompt(iteration, cell_id)`` →
``"M5.2 chat probe iter=.. cell=.."`` and M6's ``_build_chat_prompt(seed)`` →
``"M6 chat probe seed=.. digest=.."``. The forward harness keeps only the
seed-keyed form, so REST and gRPC cohorts see byte-identical engine-input
chat content for the same seed regardless of protocol.

These tests lock in the unified contract so a future maintainer can't
re-introduce a per-protocol builder without an explicit code + test change.
Recovery of the dropped M5.2 builder is via the ``milestone/m5.2-*`` tag.
"""

from __future__ import annotations

import json

import httpx
import pytest
from vllm_grpc_bench.prompts import DEFAULT_CHAT_MAX_TOKENS, build_chat_prompt
from vllm_grpc_bench.rest_cohort import run_rest_cohort

_TEST_TOKEN = "test-bearer-abcdef0123"


def test_default_chat_max_tokens_is_64() -> None:
    """FR-005c: REST and gRPC must agree on max_tokens; the forward harness
    keeps 64 (M5.1's gRPC-only override to 32 stays retired)."""
    assert DEFAULT_CHAT_MAX_TOKENS == 64


def test_build_chat_prompt_is_deterministic() -> None:
    assert build_chat_prompt(7) == build_chat_prompt(7)


def test_build_chat_prompt_varies_with_seed() -> None:
    base = build_chat_prompt(0)
    assert build_chat_prompt(1) != base
    assert build_chat_prompt(99) != base


def test_build_chat_prompt_uses_unified_format_not_legacy() -> None:
    """The prompt format must not regress to any pre-v0.0.1 string: the
    legacy REST ``Hello world`` form, the legacy gRPC ``M5.1 chat probe``
    form, or the dropped M5.2 ``iter=../cell=..`` form. The unified builder
    is seed-keyed."""
    prompt = build_chat_prompt(42)
    assert "Hello world" not in prompt  # legacy REST format
    assert "M5.1 chat probe" not in prompt  # legacy gRPC format
    assert "M5.2 chat probe" not in prompt  # dropped M5.2 iter/cell_id format
    assert "seed=42" in prompt


@pytest.mark.asyncio
async def test_rest_cohort_chat_uses_shared_prompt_helper() -> None:
    """End-to-end: the REST cohort's actual wire body's ``messages[0].content``
    field matches the unified ``build_chat_prompt(seed)`` for the matching
    iteration. Captures the request via httpx.MockTransport.
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
        )

    # 3 measurement requests captured.
    assert len(captured_bodies) == 3
    # Each prompt matches the unified helper for its iteration seed.
    for i, body in enumerate(captured_bodies):
        expected = build_chat_prompt(i)
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
        )
    assert captured_bodies[0]["max_tokens"] == 128
