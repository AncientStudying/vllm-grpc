from __future__ import annotations

import asyncio
import time
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

        # M6 (FR-008 / R-1 / R-2): wrap engine.generate() with a wall-clock
        # timer to publish engine-forward-ms via gRPC trailing metadata.
        start = time.perf_counter()
        final = None
        async for output in self._engine.generate(prompt, params, request_id=request_id):
            final = output
        engine_forward_ms = (time.perf_counter() - start) * 1000.0
        context.set_trailing_metadata((("engine-forward-ms", f"{engine_forward_ms:.3f}"),))

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

        # M6 (FR-008 / R-2): track TTFT + TPOT for chat_stream path.
        start = time.perf_counter()
        first_token_at: float | None = None
        last_token_at: float | None = None
        token_count = 0

        prev_text = ""
        token_index = 0
        try:
            async for output in self._engine.generate(prompt, params, request_id=request_id):
                completion = output.outputs[0]
                chunk = output_to_stream_chunk(output, token_index, prev_text)
                prev_text = completion.text
                if chunk.delta_content:
                    now = time.perf_counter()
                    if first_token_at is None:
                        first_token_at = now
                    last_token_at = now
                    token_count = len(completion.token_ids)
                    yield chunk
                    token_index += 1
                if completion.finish_reason:
                    engine_ttft_ms = (first_token_at - start) * 1000.0 if first_token_at else 0.0
                    if token_count > 1 and last_token_at is not None and first_token_at is not None:
                        engine_tpot_ms = (
                            (last_token_at - first_token_at) * 1000.0 / max(token_count - 1, 1)
                        )
                    else:
                        engine_tpot_ms = 0.0
                    context.set_trailing_metadata(
                        (
                            ("engine-ttft-ms", f"{engine_ttft_ms:.3f}"),
                            ("engine-tpot-ms", f"{engine_tpot_ms:.3f}"),
                        )
                    )
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
