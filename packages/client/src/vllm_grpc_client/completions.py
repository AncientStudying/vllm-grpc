from __future__ import annotations

import io
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import grpc
import grpc.aio
from vllm_grpc.v1 import completions_pb2, completions_pb2_grpc

if TYPE_CHECKING:
    import torch


@dataclass(frozen=True)
class CompletionResult:
    generated_text: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class CompletionStreamChunk:
    delta_text: str
    finish_reason: str | None  # None on non-final; "stop"/"length" on final
    token_index: int


class CompletionsClient:
    def __init__(self, channel: grpc.aio.Channel) -> None:
        self._channel = channel

    def _build_request(
        self,
        model: str,
        max_tokens: int,
        prompt: str | None,
        prompt_embeds: torch.Tensor | None,
        temperature: float | None,
        top_p: float | None,
        seed: int | None,
    ) -> completions_pb2.CompletionRequest:
        if (prompt is None) == (prompt_embeds is None):
            raise ValueError("Exactly one of prompt or prompt_embeds must be provided")
        kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if seed is not None:
            kwargs["seed"] = seed
        if prompt is not None:
            kwargs["prompt"] = prompt
        else:
            import torch as _torch  # deferred import

            buf = io.BytesIO()
            _torch.save(prompt_embeds, buf)
            kwargs["prompt_embeds"] = buf.getvalue()
        return completions_pb2.CompletionRequest(**kwargs)

    async def complete(
        self,
        model: str,
        max_tokens: int,
        *,
        prompt: str | None = None,
        prompt_embeds: torch.Tensor | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> CompletionResult:
        req = self._build_request(
            model, max_tokens, prompt, prompt_embeds, temperature, top_p, seed
        )
        stub = completions_pb2_grpc.CompletionsServiceStub(self._channel)
        response: completions_pb2.CompletionResponse = await stub.Complete(req, timeout=timeout)
        return CompletionResult(
            generated_text=response.generated_text,
            finish_reason=response.finish_reason,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )

    async def complete_stream(
        self,
        model: str,
        max_tokens: int,
        *,
        prompt: str | None = None,
        prompt_embeds: torch.Tensor | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[CompletionStreamChunk]:
        req = self._build_request(
            model, max_tokens, prompt, prompt_embeds, temperature, top_p, seed
        )
        stub = completions_pb2_grpc.CompletionsServiceStub(self._channel)
        call = stub.CompleteStream(req, timeout=timeout)
        try:
            async for proto_chunk in call:
                yield CompletionStreamChunk(
                    delta_text=proto_chunk.delta_text,
                    finish_reason=proto_chunk.finish_reason or None,
                    token_index=proto_chunk.token_index,
                )
        except grpc.aio.AioRpcError:
            raise
        finally:
            call.cancel()
