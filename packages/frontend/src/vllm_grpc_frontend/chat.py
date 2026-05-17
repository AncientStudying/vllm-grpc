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
        # M6.1.1 (FR-012): self-calibrate perturbation budget at servicer
        # entry via 5 back-to-back perf_counter_ns reads.
        _pa_t0 = time.perf_counter_ns()
        time.perf_counter_ns()
        time.perf_counter_ns()
        time.perf_counter_ns()
        _pa_t4 = time.perf_counter_ns()
        perturbation_audit_ns = _pa_t4 - _pa_t0
        # M6.1.1 checkpoint (a): handler_entry — servicer entry point.
        handler_entry_ns = time.perf_counter_ns()
        prompt = messages_to_prompt(request.messages, self._tokenizer)
        params = proto_to_sampling_params(request)
        request_id = str(uuid.uuid4())

        # M6 (FR-008 / R-2): track TTFT + TPOT for chat_stream path.
        # M6.1.1 checkpoint (b): pre_engine — just before engine.generate.
        pre_engine_ns = time.perf_counter_ns()
        start = time.perf_counter()
        first_token_at: float | None = None
        last_token_at: float | None = None
        token_count = 0
        first_chunk_ns: int | None = None
        # M6.1.2 — engine-internal RequestStateStats snapshots, captured at
        # first-chunk (queued/scheduled/first_token) and refreshed at
        # terminal-emit (last_token). Default 0 means the upstream engine did
        # not populate the field; downstream consumers check
        # TimingCheckpoint.has_engine_stats before deriving seg_queue / seg_prefill.
        engine_arrival_ns: int = 0
        engine_queued_ns: int = 0
        engine_scheduled_ns: int = 0
        engine_first_token_ns: int = 0
        engine_last_token_ns: int = 0

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
                        # M6.1.1 checkpoint (c): first_chunk — captured on the
                        # same code path that sets first_token_at.
                        first_chunk_ns = time.perf_counter_ns()
                        # M6.1.2 — snapshot engine RequestStateStats. metrics
                        # is a live reference, so we materialise scalar values
                        # now (engine may keep mutating it).
                        if output.metrics is not None:
                            engine_arrival_ns = (
                                int(output.metrics.arrival_time * 1e9)
                                if output.metrics.arrival_time
                                else 0
                            )
                            engine_queued_ns = (
                                int(output.metrics.queued_ts * 1e9)
                                if output.metrics.queued_ts
                                else 0
                            )
                            engine_scheduled_ns = (
                                int(output.metrics.scheduled_ts * 1e9)
                                if output.metrics.scheduled_ts
                                else 0
                            )
                            engine_first_token_ns = (
                                int(output.metrics.first_token_ts * 1e9)
                                if output.metrics.first_token_ts
                                else 0
                            )
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
                    # M6.1.1 checkpoint (d): terminal_emit — captured just
                    # before the trailing metadata is set.
                    terminal_emit_ns = time.perf_counter_ns()
                    # M6.1.2 — refresh last_token_ts at terminal-emit. The engine
                    # advances it on every yielded token; the final value is the
                    # one we want.
                    if output.metrics is not None and output.metrics.last_token_ts:
                        engine_last_token_ns = int(output.metrics.last_token_ts * 1e9)
                    first_chunk_for_md = (
                        first_chunk_ns if first_chunk_ns is not None else terminal_emit_ns
                    )
                    context.set_trailing_metadata(
                        (
                            # Existing M6 keys — preserved exactly.
                            ("engine-ttft-ms", f"{engine_ttft_ms:.3f}"),
                            ("engine-tpot-ms", f"{engine_tpot_ms:.3f}"),
                            # M6.1.1 (FR-008): additive m6_1_1_t_* keys.
                            ("m6_1_1_t_handler_entry", str(handler_entry_ns)),
                            ("m6_1_1_t_pre_engine", str(pre_engine_ns)),
                            ("m6_1_1_t_first_chunk", str(first_chunk_for_md)),
                            ("m6_1_1_t_terminal_emit", str(terminal_emit_ns)),
                            (
                                "m6_1_1_t_perturbation_audit_ns",
                                str(perturbation_audit_ns),
                            ),
                            # M6.1.2 — engine-internal RequestStateStats
                            # timestamps from vLLM. 0 when the engine didn't
                            # populate the field.
                            ("m6_1_1_t_engine_arrival_ns", str(engine_arrival_ns)),
                            ("m6_1_1_t_engine_queued_ns", str(engine_queued_ns)),
                            ("m6_1_1_t_engine_scheduled_ns", str(engine_scheduled_ns)),
                            ("m6_1_1_t_engine_first_token_ns", str(engine_first_token_ns)),
                            ("m6_1_1_t_engine_last_token_ns", str(engine_last_token_ns)),
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
