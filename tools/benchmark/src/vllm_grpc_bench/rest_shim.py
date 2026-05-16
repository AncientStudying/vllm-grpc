"""M5.1 FastAPI REST shim builder.

Exposes :func:`build_rest_shim` — a thin FastAPI app that wraps a
``MockEngine`` directly (no gRPC translation under the hood) and emits the
``X-Shim-Overhead-Ms`` response header on every ``/v1/*`` response per
``specs/018-m5-1-rest-vs-grpc/contracts/m5_1-rest-shim-endpoints.md``.

The Modal deploy script (``scripts/python/modal_bench_rest_grpc_server.py``)
imports this builder so the shim mechanics are unit-testable from the
harness without a Modal SDK install. Tests drive the shim via
``httpx.AsyncClient(transport=httpx.ASGITransport(app=shim))``.

Pydantic request models are declared at module scope (not inside
``build_rest_shim``) so FastAPI's ``TypeAdapter`` can resolve their
forward refs under ``from __future__ import annotations``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from fastapi import FastAPI


# M6 fix: vLLM v1's ``input_processor._validate_params`` enforces
# ``isinstance(params, SamplingParams)`` and rejects any duck-typed shim
# class. Import the real type if vLLM is available; fall back to an
# ad-hoc class for unit-test paths where vLLM is not installed (macOS
# dev machine; MockEngine just reads ``.max_tokens`` and ``.seed``).
try:
    from vllm import SamplingParams as _VLLMSamplingParams

    _HAS_VLLM_SAMPLING_PARAMS = True
except ImportError:
    _VLLMSamplingParams = None
    _HAS_VLLM_SAMPLING_PARAMS = False


def _build_sampling_params(max_tokens: int, seed: int | None) -> Any:
    """Return a SamplingParams instance the engine will accept.

    Uses real ``vllm.SamplingParams`` when available; otherwise falls
    back to a duck-typed object with the same attribute surface
    (``MockEngine`` in the unit-test paths only reads attributes).
    """
    if _HAS_VLLM_SAMPLING_PARAMS and _VLLMSamplingParams is not None:
        kwargs: dict[str, Any] = {"max_tokens": max_tokens}
        if seed is not None:
            kwargs["seed"] = seed
        return _VLLMSamplingParams(**kwargs)

    class _MockSamplingParams:
        def __init__(self, mt: int, sd: int | None) -> None:
            self.max_tokens = mt
            self.seed = sd

    return _MockSamplingParams(max_tokens, seed)


class _ChatMessage(BaseModel):
    role: str
    content: str


class _ChatRequest(BaseModel):
    model: str = "mock"
    messages: list[_ChatMessage]
    stream: bool = True
    max_tokens: int = 512
    temperature: float = 1.0
    # M6 (FR-025): per-RPC sampling seed forwarded to the engine so the
    # REST cohort's engine output is reproducible across runs at fixed
    # M6_BASE_SEED. Pre-M6 callers leave seed=None and the engine's
    # default seeding applies.
    seed: int | None = None


class _EmbedRequest(BaseModel):
    model: str = "mock"
    input_kind: str = "prompt_embedding_b64"
    input: str
    hidden_size: int
    # M5.1 — apples-to-apples with gRPC CompletionsService.Complete (M3
    # methodology): the embed cohort exercises ``engine.generate`` with a
    # prompt-embedding-shaped input, not ``engine.encode``. ``max_tokens``
    # matches M3's default so the engine work is held constant.
    max_tokens: int = 10
    # M6 (FR-025): per-RPC sampling seed forwarded to the engine.
    seed: int | None = None


def build_rest_shim(engine: Any, expected_token: str) -> FastAPI:
    """Build the FastAPI app M5.1's REST cohort hits."""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, StreamingResponse

    shim = FastAPI()
    expected_header = f"Bearer {expected_token}"

    @shim.middleware("http")
    async def _bearer_auth(request: Request, call_next: Any) -> Any:
        if request.url.path == "/healthz":
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if auth != expected_header:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    @shim.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @shim.post("/v1/chat/completions")
    async def chat_completions(req: _ChatRequest) -> Any:
        handler_entry = time.perf_counter()
        prompt = "".join(m.content for m in req.messages)
        sampling = _build_sampling_params(req.max_tokens, req.seed)
        request_id = f"rest-chat-{uuid.uuid4().hex}"

        if req.stream:
            # Pull the first chunk synchronously so the X-Shim-Overhead-Ms
            # header (handler-entry → MockEngine first-output wall-clock) can
            # be set on the StreamingResponse before any data: line is sent.
            # The buffered first_chunk is then re-emitted as the first SSE
            # event — no duplicate engine work.
            engine_start = time.perf_counter()
            gen = engine.generate(prompt, sampling, request_id=request_id)
            try:
                first_chunk: Any | None = await gen.__anext__()
            except StopAsyncIteration:
                first_chunk = None
            overhead_ms = (time.perf_counter() - handler_entry) * 1000.0
            completion_id = f"chatcmpl-{uuid.uuid4().hex}"

            # M6 (FR-008 / R-4): track TTFT + TPOT for engine_cost emission
            # on the terminal SSE event. ``first_token_at`` is when the
            # first non-empty token was observed; ``last_token_at`` /
            # ``token_count`` continuously updated until the stream ends.
            first_token_at: float | None = None
            last_token_at: float | None = None
            token_count = 0

            def _format_chunk(chunk: Any) -> bytes:
                completion = chunk.outputs[0] if chunk.outputs else None
                if completion is None:
                    return b""
                payload = {
                    "id": completion_id,
                    "choices": [
                        {
                            "delta": {"content": completion.text},
                            "index": 0,
                        }
                    ],
                }
                return f"data: {json.dumps(payload)}\n\n".encode()

            async def _sse_body() -> AsyncIterator[bytes]:
                nonlocal first_token_at, last_token_at, token_count
                if first_chunk is not None:
                    completion = first_chunk.outputs[0] if first_chunk.outputs else None
                    if completion is not None and completion.text:
                        now = time.perf_counter()
                        if first_token_at is None:
                            first_token_at = now
                        last_token_at = now
                        token_count = len(getattr(completion, "token_ids", []) or [])
                    payload = _format_chunk(first_chunk)
                    if payload:
                        yield payload
                async for chunk in gen:
                    completion = chunk.outputs[0] if chunk.outputs else None
                    if completion is not None and completion.text:
                        now = time.perf_counter()
                        if first_token_at is None:
                            first_token_at = now
                        last_token_at = now
                        token_count = len(getattr(completion, "token_ids", []) or [])
                    payload = _format_chunk(chunk)
                    if payload:
                        yield payload
                # M6 terminal event carries finish_reason + engine_cost so
                # the harness reads TTFT + TPOT from the SSE stream before
                # the [DONE] sentinel (contracts/instrumentation.md §2).
                engine_ttft_ms = (first_token_at - engine_start) * 1000.0 if first_token_at else 0.0
                if token_count > 1 and last_token_at is not None and first_token_at is not None:
                    engine_tpot_ms = (
                        (last_token_at - first_token_at) * 1000.0 / max(token_count - 1, 1)
                    )
                else:
                    engine_tpot_ms = 0.0
                terminal = {
                    "id": completion_id,
                    "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                    "engine_cost": {
                        "engine_ttft_ms": engine_ttft_ms,
                        "engine_tpot_ms": engine_tpot_ms,
                    },
                }
                yield f"data: {json.dumps(terminal)}\n\n".encode()
                yield b"data: [DONE]\n\n"

            sse_response = StreamingResponse(_sse_body(), media_type="text/event-stream")
            sse_response.headers["X-Shim-Overhead-Ms"] = f"{overhead_ms:.6f}"
            sse_response.headers["Cache-Control"] = "no-cache"
            return sse_response

        full_text = ""
        async for chunk in engine.generate(prompt, sampling, request_id=request_id):
            if chunk.outputs:
                full_text = chunk.outputs[0].text
        overhead_ms = (time.perf_counter() - handler_entry) * 1000.0
        json_response = JSONResponse(
            {
                "id": f"chatcmpl-{uuid.uuid4().hex}",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": full_text},
                        "index": 0,
                        "finish_reason": "stop",
                    }
                ],
            }
        )
        json_response.headers["X-Shim-Overhead-Ms"] = f"{overhead_ms:.6f}"
        return json_response

    @shim.post("/v1/embeddings")
    async def embeddings(req: _EmbedRequest) -> Any:
        """M5.1 'embed' cohort endpoint.

        Despite the OpenAI-style URL, this calls ``engine.generate`` with a
        prompt-embedding-shaped input — matching ``M3CompletionsServicer.
        Complete``'s engine call so the protocol comparison holds the
        engine operation constant. The URL kept its ``/v1/embeddings`` name
        for continuity with the contract doc and existing test wiring; the
        operation is 'completion-from-embedding', not 'return embedding'.
        """
        handler_entry = time.perf_counter()
        if req.input_kind not in ("prompt_embedding_b64", "text"):
            return JSONResponse({"error": "unsupported input_kind"}, status_code=422)
        if req.hidden_size not in (2048, 4096, 8192):
            return JSONResponse({"error": "hidden_size must be 2048/4096/8192"}, status_code=422)
        if req.input_kind == "prompt_embedding_b64":
            try:
                raw_bytes = base64.b64decode(req.input, validate=True)
            except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
                return JSONResponse({"error": "input not valid base64"}, status_code=400)
            # Mirror M3CompletionsServicer._completion_prompt: hash the raw
            # embedding bytes into a deterministic prompt token so the engine
            # produces stable per-request output across both protocols.
            digest = hashlib.blake2b(raw_bytes, digest_size=8).hexdigest()
            prompt: Any = f"embeds:{digest}"
        else:
            prompt = req.input

        sampling = _build_sampling_params(req.max_tokens, req.seed)
        request_id = f"rest-embed-{uuid.uuid4().hex}"
        # M6 (FR-008 / R-4): time the engine.generate() call so the unary
        # response carries engine_cost.engine_forward_ms (top-level field).
        engine_start = time.perf_counter()
        # Drain the generator to its final chunk (parity with M3 Complete RPC).
        final_text = ""
        final_finish = "stop"
        async for output in engine.generate(prompt, sampling, request_id=request_id):
            if output.outputs:
                comp = output.outputs[0]
                final_text = comp.text
                final_finish = comp.finish_reason or "stop"
        engine_forward_ms = (time.perf_counter() - engine_start) * 1000.0
        overhead_ms = (time.perf_counter() - handler_entry) * 1000.0
        response = JSONResponse(
            {
                "model": "mock",
                "generated_text": final_text,
                "finish_reason": final_finish,
                "engine_cost": {"engine_forward_ms": engine_forward_ms},
            }
        )
        response.headers["X-Shim-Overhead-Ms"] = f"{overhead_ms:.6f}"
        return response

    return shim
