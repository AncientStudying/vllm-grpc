from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator

import grpc
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from vllm_grpc_proxy.completions_translate import (
    OpenAICompletionRequest,
    build_completion_response,
    format_completion_chunk,
    format_completion_error,
    format_completion_final,
    format_done,
    openai_request_to_proto,
)
from vllm_grpc_proxy.grpc_client import GrpcCompletionsClient

router = APIRouter()
_completions_client = GrpcCompletionsClient()


async def _stream_sse(req: OpenAICompletionRequest, http_request: Request) -> AsyncIterator[str]:
    completion_id = f"cmpl-{uuid.uuid4()}"
    created = int(time.time())
    proto_req = openai_request_to_proto(req)
    try:
        async for chunk in _completions_client.stream_complete(proto_req):
            if await http_request.is_disconnected():
                return
            if chunk.finish_reason:
                yield format_completion_final(chunk, completion_id, req.model, created)
            else:
                yield format_completion_chunk(chunk, completion_id, req.model, created)
        yield format_done()
    except grpc.aio.AioRpcError as exc:
        yield format_completion_error(exc.details() or "Internal error")


@router.post("/v1/completions")
async def completions(req: OpenAICompletionRequest, request: Request) -> Response:
    if req.stream:
        return StreamingResponse(
            _stream_sse(req, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    proto_req = openai_request_to_proto(req)
    try:
        proto_resp = await _completions_client.complete(proto_req)
    except grpc.aio.AioRpcError as exc:
        code = exc.code()
        if code == grpc.StatusCode.UNAVAILABLE:
            return JSONResponse(
                {"error": {"message": "Frontend unavailable", "type": "gateway_error"}},
                status_code=502,
            )
        if code == grpc.StatusCode.DEADLINE_EXCEEDED:
            return JSONResponse(
                {"error": {"message": "Frontend timed out", "type": "gateway_error"}},
                status_code=504,
            )
        if code == grpc.StatusCode.INVALID_ARGUMENT:
            msg = exc.details() or "Invalid request"
            return JSONResponse(
                {"error": {"message": msg, "type": "invalid_request_error"}},
                status_code=422,
            )
        return JSONResponse(
            {"error": {"message": "Internal server error", "type": "internal_error"}},
            status_code=500,
        )

    body = build_completion_response(proto_resp, req.model)
    return JSONResponse(body)
