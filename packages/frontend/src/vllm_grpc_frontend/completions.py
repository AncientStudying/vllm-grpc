from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import grpc
from vllm_grpc.v1 import completions_pb2, completions_pb2_grpc

from vllm_grpc_frontend.completions_translate import decode_embeds, proto_to_sampling_params


def _prompt_embeds_to_text_digest(raw_bytes: bytes) -> str:
    """Hash opaque prompt_embeds bytes to a deterministic text prompt.

    M5.x's ``M3CompletionsServicer`` treats ``prompt_embeds`` as an
    opaque binary payload and hashes it to ``"embeds:<8-byte hex>"`` so
    the engine call path is symmetric with the REST shim (which already
    hashes b64-decoded prompt_embeds in the same way before calling
    ``engine.generate``). Under MockEngine this was a no-op formality;
    under real vLLM it keeps the embed cohort's engine work apples-to-
    apples between REST and gRPC — both paths feed the engine a short
    text prompt of the same shape.

    Callers who want REAL prompt-embeddings inference (vLLM's
    ``enable_prompt_embeds`` path with actual embedding tensors) should
    fall through to :func:`decode_embeds` when the request payload is a
    valid torch.save-pickled tensor — that's preserved by the try /
    except below.
    """
    digest = hashlib.blake2b(raw_bytes, digest_size=8).hexdigest()
    return f"embeds:{digest}"


def _resolve_prompt_embeds_input(raw_bytes: bytes) -> Any:
    """Return the engine input for a ``prompt_embeds`` request.

    Tries :func:`decode_embeds` first (real prompt-embeddings path);
    falls back to a text digest if the bytes aren't a torch.save pickle
    (M6 / M5.x harness path — opaque bytes used as a payload-size knob
    for transport-cost measurement, with engine work matching the REST
    cohort's text-prompt path).
    """
    try:
        tensor = decode_embeds(raw_bytes)
    except ValueError:
        return _prompt_embeds_to_text_digest(raw_bytes)
    return {"prompt_embeds": tensor}


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
            engine_input = _resolve_prompt_embeds_input(request.prompt_embeds)
        else:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Exactly one of prompt or prompt_embeds must be set",
            )
            return completions_pb2.CompletionResponse()

        params = proto_to_sampling_params(request)
        request_id = str(uuid.uuid4())

        # M6 (FR-008 / R-1 / R-2): wrap engine.generate() with a wall-clock
        # timer to publish engine-forward-ms via gRPC trailing metadata. The
        # wrapper is a no-op for M5.x callers that ignore trailing metadata.
        start = time.perf_counter()
        final = None
        async for output in self._engine.generate(engine_input, params, request_id=request_id):
            final = output
        engine_forward_ms = (time.perf_counter() - start) * 1000.0
        context.set_trailing_metadata((("engine-forward-ms", f"{engine_forward_ms:.3f}"),))

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
            engine_input = _resolve_prompt_embeds_input(request.prompt_embeds)
        else:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Exactly one of prompt or prompt_embeds must be set",
            )
            return

        params = proto_to_sampling_params(request)
        request_id = str(uuid.uuid4())

        # M6 (FR-008 / R-2): track TTFT + TPOT for streaming-completions
        # path. Emit on the final stream chunk's trailing metadata.
        start = time.perf_counter()
        first_token_at: float | None = None
        last_token_at: float | None = None
        token_count = 0

        prev_text = ""
        token_index = 0
        try:
            async for output in self._engine.generate(engine_input, params, request_id=request_id):
                completion = output.outputs[0]
                delta = completion.text[len(prev_text) :]
                prev_text = completion.text
                if delta:
                    now = time.perf_counter()
                    if first_token_at is None:
                        first_token_at = now
                    last_token_at = now
                    token_count = len(completion.token_ids)
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
