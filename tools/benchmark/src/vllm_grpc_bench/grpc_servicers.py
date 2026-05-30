"""In-process gRPC servicers for the bench harness (v0.0.1 home).

De-prefixed home for the production-shape gRPC servicers that wrap
``MockEngine`` without vllm/torch deps, plus the in-process server bring-up
helpers. Hoisted from the former ``m3_sweep`` module at Phase 4 (T020):

* :class:`ChatServicer` / :class:`CompletionsServicer` (formerly
  ``M3ChatServicer`` / ``M3CompletionsServicer``) are deployed to Modal by
  ``scripts/python/modal_bench_grpc_server.py`` +
  ``scripts/python/modal_bench_rest_grpc_server.py``.
* :func:`serve_in_process` / :func:`serve_in_process_adapter` stand up a local
  server for the in-process endpoint-provider path (``test_endpoint_provider``).

The legacy M1–M5.2 sweep/aggregation machinery that also lived in ``m3_sweep``
was deleted; only this live servicer surface survives.
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import grpc
from vllm_grpc.v1 import (
    chat_pb2,
    chat_pb2_grpc,
    completions_pb2,
    completions_pb2_grpc,
    health_pb2,
    health_pb2_grpc,
)

from vllm_grpc_bench.channel_config import ChannelConfig
from vllm_grpc_bench.mock_engine import MockEngine

# ---------------------------------------------------------------------------
# Thin servicers that wrap MockEngine without vllm/torch deps
# ---------------------------------------------------------------------------


class ChatServicer(chat_pb2_grpc.ChatServiceServicer):  # type: ignore[misc]
    def __init__(self, engine: MockEngine) -> None:
        self._engine = engine

    async def Complete(  # noqa: N802 — matches generated stub
        self,
        request: chat_pb2.ChatCompleteRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> chat_pb2.ChatCompleteResponse:
        prompt = _request_prompt_text(request)
        params = SimpleNamespace(max_tokens=int(request.max_tokens or 64))
        request_id = str(uuid.uuid4())
        final = None
        async for output in self._engine.generate(prompt, params, request_id=request_id):
            final = output
        assert final is not None
        comp = final.outputs[0]
        return chat_pb2.ChatCompleteResponse(
            message=chat_pb2.ChatMessage(role="assistant", content=comp.text),
            finish_reason=comp.finish_reason or "stop",
            prompt_tokens=len(final.prompt_token_ids),
            completion_tokens=len(comp.token_ids),
        )

    async def CompleteStream(  # noqa: N802
        self,
        request: chat_pb2.ChatCompleteRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> AsyncIterator[chat_pb2.ChatStreamChunk]:
        prompt = _request_prompt_text(request)
        params = SimpleNamespace(max_tokens=int(request.max_tokens or 64))
        request_id = str(uuid.uuid4())
        prev = ""
        idx = 0
        async for output in self._engine.generate(prompt, params, request_id=request_id):
            comp = output.outputs[0]
            delta = comp.text[len(prev) :]
            prev = comp.text
            if delta:
                yield chat_pb2.ChatStreamChunk(
                    delta_content=delta, finish_reason="", token_index=idx
                )
                idx += 1
            if comp.finish_reason:
                yield chat_pb2.ChatStreamChunk(
                    delta_content="",
                    finish_reason=comp.finish_reason or "stop",
                    token_index=idx,
                )
                return


class _BenchHealthServicer(health_pb2_grpc.HealthServicer):  # type: ignore[misc]
    """Minimal Health.Ping servicer for the RTT probe (R-3).

    Registered on every in-process server bring-up so the probe can drive a
    no-op unary RPC against the same channel the cohort is about to use. The
    response carries a constant payload, so cohort timings are unaffected;
    only ``rtt_probe.measure_rtt`` exercises this method.
    """

    async def Ping(  # noqa: N802
        self,
        request: health_pb2.HealthRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> health_pb2.HealthResponse:
        return health_pb2.HealthResponse(message="ok")


class CompletionsServicer(completions_pb2_grpc.CompletionsServiceServicer):  # type: ignore[misc]
    def __init__(self, engine: MockEngine) -> None:
        self._engine = engine

    async def Complete(  # noqa: N802
        self,
        request: completions_pb2.CompletionRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> completions_pb2.CompletionResponse:
        prompt = _completion_prompt(request)
        params = SimpleNamespace(max_tokens=int(request.max_tokens or 10))
        request_id = str(uuid.uuid4())
        final = None
        async for output in self._engine.generate(prompt, params, request_id=request_id):
            final = output
        assert final is not None
        comp = final.outputs[0]
        return completions_pb2.CompletionResponse(
            generated_text=comp.text,
            finish_reason=comp.finish_reason or "stop",
            prompt_tokens=len(final.prompt_token_ids),
            completion_tokens=len(comp.token_ids),
        )


def _request_prompt_text(request: chat_pb2.ChatCompleteRequest) -> str:
    parts = [m.content for m in request.messages if m.content]
    return "\n".join(parts) if parts else "default"


def _completion_prompt(request: completions_pb2.CompletionRequest) -> str:
    which = request.WhichOneof("input")
    if which == "prompt_embeds":
        digest = hashlib.blake2b(request.prompt_embeds, digest_size=8).hexdigest()
        return f"embeds:{digest}"
    return request.prompt or "default"


# ---------------------------------------------------------------------------
# Server bring-up
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def serve_in_process(
    engine: MockEngine,
    cfg: ChannelConfig,
) -> AsyncIterator[str]:
    """Start a gRPC server with the bench servicers; yield ``host:port``."""
    server_kwargs: dict[str, Any] = {}
    if cfg.server_options:
        server_kwargs["options"] = list(cfg.server_options)
    if cfg.compression is not grpc.Compression.NoCompression:
        server_kwargs["compression"] = cfg.compression
    server = grpc.aio.server(**server_kwargs)
    chat_pb2_grpc.add_ChatServiceServicer_to_server(ChatServicer(engine), server)
    completions_pb2_grpc.add_CompletionsServiceServicer_to_server(
        CompletionsServicer(engine), server
    )
    # Health servicer is additive — only the RTT probe calls it. Cohort
    # drivers never hit Health.Ping, so per-RPC timings are unchanged.
    health_pb2_grpc.add_HealthServicer_to_server(_BenchHealthServicer(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        yield f"127.0.0.1:{port}"
    finally:
        await server.stop(grace=0.5)


@contextlib.asynccontextmanager
async def serve_in_process_adapter(
    engine: MockEngine,
    channel_config: ChannelConfig,
) -> AsyncIterator[tuple[str, grpc.ChannelCredentials | None, tuple[tuple[str, str], ...] | None]]:
    """``EndpointProvider``-conforming wrapper around :func:`serve_in_process`.

    Yields an ``(addr, credentials, metadata)`` tuple where ``credentials`` and
    ``metadata`` are ``None`` (insecure local channel, no per-RPC auth).
    ``modal_endpoint.provide_endpoint`` is the production counterpart, yielding
    a Modal-tunnel target with TLS credentials and a bearer-token metadata pair.
    """
    async with serve_in_process(engine, channel_config) as addr:
        yield (addr, None, None)


__all__ = [
    "ChatServicer",
    "CompletionsServicer",
    "serve_in_process",
    "serve_in_process_adapter",
]
