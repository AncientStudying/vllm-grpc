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
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from fastapi import FastAPI


class _ChatMessage(BaseModel):
    role: str
    content: str


class _ChatRequest(BaseModel):
    model: str = "mock"
    messages: list[_ChatMessage]
    stream: bool = True
    max_tokens: int = 512
    temperature: float = 1.0


class _EmbedRequest(BaseModel):
    model: str = "mock"
    input_kind: str = "prompt_embedding_b64"
    input: str
    hidden_size: int


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

        class _SamplingParams:
            def __init__(self, max_tokens: int) -> None:
                self.max_tokens = max_tokens

        sampling = _SamplingParams(req.max_tokens)
        request_id = f"rest-chat-{uuid.uuid4().hex}"

        if req.stream:
            # Pull the first chunk synchronously so the X-Shim-Overhead-Ms
            # header (handler-entry → MockEngine first-output wall-clock) can
            # be set on the StreamingResponse before any data: line is sent.
            # The buffered first_chunk is then re-emitted as the first SSE
            # event — no duplicate engine work.
            gen = engine.generate(prompt, sampling, request_id=request_id)
            try:
                first_chunk: Any | None = await gen.__anext__()
            except StopAsyncIteration:
                first_chunk = None
            overhead_ms = (time.perf_counter() - handler_entry) * 1000.0
            completion_id = f"chatcmpl-{uuid.uuid4().hex}"

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
                if first_chunk is not None:
                    payload = _format_chunk(first_chunk)
                    if payload:
                        yield payload
                async for chunk in gen:
                    payload = _format_chunk(chunk)
                    if payload:
                        yield payload
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
        handler_entry = time.perf_counter()
        if req.input_kind not in ("prompt_embedding_b64", "text"):
            return JSONResponse({"error": "unsupported input_kind"}, status_code=422)
        if req.hidden_size not in (2048, 4096, 8192):
            return JSONResponse({"error": "hidden_size must be 2048/4096/8192"}, status_code=422)
        if req.input_kind == "prompt_embedding_b64":
            try:
                _raw = base64.b64decode(req.input, validate=True)
            except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
                return JSONResponse({"error": "input not valid base64"}, status_code=400)
            prompt = f"embed-h{req.hidden_size}-l{len(req.input)}"
        else:
            prompt = req.input
        request_id = f"rest-embed-{uuid.uuid4().hex}"
        import numpy as np

        embedding_bytes: bytes = b""
        async for out in engine.encode(prompt, request_id=request_id):
            arr = out.outputs[0].embedding
            embedding_bytes = np.asarray(arr, dtype=np.float32).tobytes()
            break
        overhead_ms = (time.perf_counter() - handler_entry) * 1000.0
        response = JSONResponse(
            {
                "model": "mock",
                "data": [
                    {
                        "embedding": base64.b64encode(embedding_bytes).decode("ascii"),
                        "index": 0,
                    }
                ],
            }
        )
        response.headers["X-Shim-Overhead-Ms"] = f"{overhead_ms:.6f}"
        return response

    return shim
