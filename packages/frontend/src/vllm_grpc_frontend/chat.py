from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import grpc
from vllm_grpc.v1 import chat_pb2, chat_pb2_grpc

from vllm_grpc_frontend.chat_translate import (
    messages_to_prompt,
    output_to_stream_chunk,
    proto_to_sampling_params,
    request_output_to_proto,
)


class ChatServicer(chat_pb2_grpc.ChatServiceServicer):  # type: ignore[misc]
    def __init__(self, engine: Any, tokenizer: Any) -> None:
        self._engine = engine
        self._tokenizer = tokenizer

    async def Complete(
        self,
        request: chat_pb2.ChatCompleteRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> chat_pb2.ChatCompleteResponse:
        prompt = messages_to_prompt(request.messages, self._tokenizer)
        params = proto_to_sampling_params(request)
        request_id = str(uuid.uuid4())

        final = None
        async for output in self._engine.generate(prompt, params, request_id=request_id):
            final = output

        assert final is not None, "Engine produced no output"
        return request_output_to_proto(final)

    async def CompleteStream(
        self,
        request: chat_pb2.ChatCompleteRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> AsyncIterator[chat_pb2.ChatStreamChunk]:
        prompt = messages_to_prompt(request.messages, self._tokenizer)
        params = proto_to_sampling_params(request)
        request_id = str(uuid.uuid4())

        prev_text = ""
        token_index = 0
        try:
            async for output in self._engine.generate(prompt, params, request_id=request_id):
                completion = output.outputs[0]
                chunk = output_to_stream_chunk(output, token_index, prev_text)
                prev_text = completion.text
                if chunk.delta_content:
                    yield chunk
                    token_index += 1
                if completion.finish_reason:
                    yield chat_pb2.ChatStreamChunk(
                        delta_content="",
                        finish_reason=completion.finish_reason,
                        token_index=token_index,
                    )
                    return
        except asyncio.CancelledError:
            return
        except Exception as exc:
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))
