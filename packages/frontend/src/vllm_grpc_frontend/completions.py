from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import grpc
from vllm_grpc.v1 import completions_pb2, completions_pb2_grpc

from vllm_grpc_frontend.completions_translate import decode_embeds, proto_to_sampling_params


class CompletionsServicer(completions_pb2_grpc.CompletionsServiceServicer):  # type: ignore[misc]
    def __init__(self, engine: Any) -> None:
        self._engine = engine

    async def Complete(
        self,
        request: completions_pb2.CompletionRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> completions_pb2.CompletionResponse:
        which = request.WhichOneof("input")
        if which == "prompt":
            engine_input: Any = request.prompt
        elif which == "prompt_embeds":
            try:
                engine_input = decode_embeds(request.prompt_embeds)
            except ValueError as exc:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
                return completions_pb2.CompletionResponse()
        else:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Exactly one of prompt or prompt_embeds must be set",
            )
            return completions_pb2.CompletionResponse()

        if which == "prompt_embeds":
            engine_input = {"prompt_embeds": engine_input}

        params = proto_to_sampling_params(request)
        request_id = str(uuid.uuid4())

        final = None
        async for output in self._engine.generate(engine_input, params, request_id=request_id):
            final = output

        assert final is not None, "Engine produced no output"
        completion = final.outputs[0]
        return completions_pb2.CompletionResponse(
            generated_text=completion.text,
            finish_reason=completion.finish_reason or "stop",
            prompt_tokens=len(final.prompt_token_ids),
            completion_tokens=len(completion.token_ids),
        )

    async def CompleteStream(
        self,
        request: completions_pb2.CompletionRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> AsyncIterator[completions_pb2.CompletionStreamChunk]:
        which = request.WhichOneof("input")
        if which == "prompt":
            engine_input: Any = request.prompt
        elif which == "prompt_embeds":
            try:
                engine_input = decode_embeds(request.prompt_embeds)
            except ValueError as exc:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
                return
        else:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Exactly one of prompt or prompt_embeds must be set",
            )
            return

        if which == "prompt_embeds":
            engine_input = {"prompt_embeds": engine_input}

        params = proto_to_sampling_params(request)
        request_id = str(uuid.uuid4())

        prev_text = ""
        token_index = 0
        try:
            async for output in self._engine.generate(engine_input, params, request_id=request_id):
                completion = output.outputs[0]
                delta = completion.text[len(prev_text) :]
                prev_text = completion.text
                if delta:
                    if not context.is_active():  # type: ignore[attr-defined]
                        return
                    yield completions_pb2.CompletionStreamChunk(
                        delta_text=delta,
                        finish_reason="",
                        token_index=token_index,
                    )
                    token_index += 1
                if completion.finish_reason:
                    if not context.is_active():  # type: ignore[attr-defined]
                        return
                    yield completions_pb2.CompletionStreamChunk(
                        delta_text="",
                        finish_reason=completion.finish_reason or "stop",
                        token_index=token_index,
                    )
                    return
        except asyncio.CancelledError:
            return
        except Exception as exc:
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))
