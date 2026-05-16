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
    """REST embed-cell request body.

    Three ``input_kind`` values are accepted (all coexist indefinitely per
    spec FR-004 — no deprecation, no migration mandate):

    * ``prompt_embedding_b64`` — raw float32 ``tensor.tobytes()`` bytes
      (M5.x / M6 wire format). The shim hashes them to a short text digest
      via ``blake2b`` and feeds that text to ``engine.generate``; engine work
      is text-prompt unary completion. Used by M5.x / M6 reproductions.
    * ``prompt_embedding_torch_b64`` — base64-encoded ``torch.save(tensor)``
      bytes (M6.1+ wire format). The shim calls ``decode_embeds`` to
      deserialise and ships ``{"prompt_embeds": tensor}`` directly to
      ``engine.generate(...)``, driving the real prompt-embeds engine path
      via ``enable_prompt_embeds=True``. Used by M6.1+ sweeps. See
      ``docs/benchmarks/m6_1-real-prompt-embeds.md`` § "Engine path
      differential" for the operator-facing decision aid.
    * ``text`` — plain text prompt fed straight to the engine.
    """

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
        # M6.1.1 (FR-012): self-calibrate the perturbation budget at handler
        # entry. Five back-to-back perf_counter_ns reads yield 4 deltas whose
        # sum approximates the cost the 4 real checkpoint reads add to this
        # request. Captured once per RPC.
        _pa_t0 = time.perf_counter_ns()
        time.perf_counter_ns()
        time.perf_counter_ns()
        time.perf_counter_ns()
        _pa_t4 = time.perf_counter_ns()
        perturbation_audit_ns = _pa_t4 - _pa_t0
        # M6.1.1 checkpoint (a): handler_entry — captured after calibration so
        # the calibration cost doesn't perturb the user-facing seg_ab span.
        handler_entry_ns = time.perf_counter_ns()
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
            # M6.1.1 checkpoint (b): pre_engine — just before engine.generate.
            pre_engine_ns = time.perf_counter_ns()
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
            # M6.1.1 checkpoint (c): first_chunk — captured on the same code
            # path that sets ``first_token_at`` so the two are sampled at the
            # same instant.
            first_chunk_ns: int | None = None

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
                nonlocal first_token_at, last_token_at, token_count, first_chunk_ns
                if first_chunk is not None:
                    completion = first_chunk.outputs[0] if first_chunk.outputs else None
                    if completion is not None and completion.text:
                        now = time.perf_counter()
                        if first_token_at is None:
                            first_token_at = now
                            first_chunk_ns = time.perf_counter_ns()
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
                            first_chunk_ns = time.perf_counter_ns()
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
                # M6.1.1 checkpoint (d): terminal_emit — captured just before
                # the JSON payload is yielded onto the SSE stream.
                terminal_emit_ns = time.perf_counter_ns()
                terminal = {
                    "id": completion_id,
                    "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                    "engine_cost": {
                        "engine_ttft_ms": engine_ttft_ms,
                        "engine_tpot_ms": engine_tpot_ms,
                    },
                    # M6.1.1 (FR-007): additive sub-object. M6 / M6.1 parsers
                    # ignore unknown keys; M6.1.1 client extracts via
                    # m6_1_1_timing.extract_rest_timings.
                    "m6_1_1_timings": {
                        "handler_entry_ns": handler_entry_ns,
                        "pre_engine_ns": pre_engine_ns,
                        # first_chunk_ns is None if the stream produced no
                        # token (cold-start failures etc.); fall back to
                        # terminal_emit_ns so the segment delta is zero rather
                        # than negative.
                        "first_chunk_ns": (
                            first_chunk_ns if first_chunk_ns is not None else terminal_emit_ns
                        ),
                        "terminal_emit_ns": terminal_emit_ns,
                        "perturbation_audit_ns": perturbation_audit_ns,
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
        # M6.1.1 (FR-011 audit-only controls): same 4-checkpoint instrumentation
        # as chat_stream so embed cells expose the same per-segment audit. The
        # wire-format emission is a top-level ``m6_1_1_timings`` key on the
        # JSONResponse body (analogous to chat_stream's terminal SSE event
        # sub-object).
        _pa_t0 = time.perf_counter_ns()
        time.perf_counter_ns()
        time.perf_counter_ns()
        time.perf_counter_ns()
        _pa_t4 = time.perf_counter_ns()
        perturbation_audit_ns = _pa_t4 - _pa_t0
        handler_entry_ns = time.perf_counter_ns()
        handler_entry = time.perf_counter()
        if req.input_kind not in (
            "prompt_embedding_b64",
            "prompt_embedding_torch_b64",
            "text",
        ):
            return JSONResponse({"error": "unsupported input_kind"}, status_code=422)
        if req.hidden_size not in (2048, 4096, 8192):
            return JSONResponse({"error": "hidden_size must be 2048/4096/8192"}, status_code=422)
        if req.input_kind == "prompt_embedding_torch_b64":
            # M6.1 (FR-003): base64-decoded torch.save bytes, deserialised by
            # decode_embeds and shipped to the engine via {"prompt_embeds":
            # tensor} — drives enable_prompt_embeds=True real-engine path.
            try:
                raw_bytes = base64.b64decode(req.input, validate=True)
            except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
                return JSONResponse({"error": "input not valid base64"}, status_code=400)
            try:
                from vllm_grpc_frontend.completions_translate import decode_embeds

                tensor = decode_embeds(raw_bytes)
            except (ValueError, Exception) as exc:  # noqa: BLE001
                return JSONResponse(
                    {"error": f"decode_embeds failed: {exc}"},
                    status_code=422,
                )
            prompt: Any = {"prompt_embeds": tensor}
        elif req.input_kind == "prompt_embedding_b64":
            try:
                raw_bytes = base64.b64decode(req.input, validate=True)
            except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
                return JSONResponse({"error": "input not valid base64"}, status_code=400)
            # Mirror M3CompletionsServicer._completion_prompt: hash the raw
            # embedding bytes into a deterministic prompt token so the engine
            # produces stable per-request output across both protocols.
            digest = hashlib.blake2b(raw_bytes, digest_size=8).hexdigest()
            prompt = f"embeds:{digest}"
        else:
            prompt = req.input

        sampling = _build_sampling_params(req.max_tokens, req.seed)
        request_id = f"rest-embed-{uuid.uuid4().hex}"
        # M6 (FR-008 / R-4): time the engine.generate() call so the unary
        # response carries engine_cost.engine_forward_ms (top-level field).
        # M6.1.1 checkpoint (b): pre_engine.
        pre_engine_ns = time.perf_counter_ns()
        engine_start = time.perf_counter()
        # Drain the generator to its final chunk (parity with M3 Complete RPC).
        final_text = ""
        final_finish = "stop"
        first_chunk_ns: int | None = None
        async for output in engine.generate(prompt, sampling, request_id=request_id):
            # M6.1.1 checkpoint (c): first_chunk — captured on the first
            # yielded output to mirror chat_stream's first-token semantics.
            if first_chunk_ns is None:
                first_chunk_ns = time.perf_counter_ns()
            if output.outputs:
                comp = output.outputs[0]
                final_text = comp.text
                final_finish = comp.finish_reason or "stop"
        engine_forward_ms = (time.perf_counter() - engine_start) * 1000.0
        overhead_ms = (time.perf_counter() - handler_entry) * 1000.0
        # M6.1.1 checkpoint (d): terminal_emit — captured just before the
        # JSONResponse is constructed.
        terminal_emit_ns = time.perf_counter_ns()
        response = JSONResponse(
            {
                "model": "mock",
                "generated_text": final_text,
                "finish_reason": final_finish,
                "engine_cost": {"engine_forward_ms": engine_forward_ms},
                # M6.1.1 (FR-011): same shape as chat_stream's sub-object so
                # one client extractor handles both REST endpoints.
                "m6_1_1_timings": {
                    "handler_entry_ns": handler_entry_ns,
                    "pre_engine_ns": pre_engine_ns,
                    "first_chunk_ns": (
                        first_chunk_ns if first_chunk_ns is not None else terminal_emit_ns
                    ),
                    "terminal_emit_ns": terminal_emit_ns,
                    "perturbation_audit_ns": perturbation_audit_ns,
                },
            }
        )
        response.headers["X-Shim-Overhead-Ms"] = f"{overhead_ms:.6f}"
        return response

    return shim
