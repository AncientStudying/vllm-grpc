from __future__ import annotations

import time
from collections.abc import AsyncIterator

import grpc
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from vllm_grpc_proxy.chat_translate import (
    OpenAIChatRequest,
    format_sse_done,
    format_sse_error,
    format_sse_role_delta,
    openai_request_to_proto,
    proto_chunk_to_sse_event,
    proto_response_to_openai_dict,
)
from vllm_grpc_proxy.grpc_client import GrpcChatClient

router = APIRouter()
_chat_client = GrpcChatClient()


async def _stream_sse(req: OpenAIChatRequest, http_request: Request) -> AsyncIterator[str]:
    import uuid

    completion_id = f"chatcmpl-{uuid.uuid4()}"
    created = int(time.time())
    proto_req = openai_request_to_proto(req)
    yield format_sse_role_delta(completion_id, created, req.model)
    try:
        async for chunk in _chat_client.stream_complete(proto_req):
            if await http_request.is_disconnected():
                return
            yield proto_chunk_to_sse_event(chunk, completion_id, created, req.model)
        yield format_sse_done()
    except grpc.aio.AioRpcError as exc:
        yield format_sse_error(exc.details() or "Internal error")


@router.post("/v1/chat/completions")
async def chat_completions(req: OpenAIChatRequest, request: Request) -> Response:
    if req.stream:
        return StreamingResponse(
            _stream_sse(req, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    t0 = time.perf_counter()
    proto_req = openai_request_to_proto(req)
    t1 = time.perf_counter()

    try:
        proto_resp = await _chat_client.complete(proto_req)
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

    t2 = time.perf_counter()
    body = proto_response_to_openai_dict(proto_resp, req.model)
    t3 = time.perf_counter()

    proxy_ms = (t1 - t0 + t3 - t2) * 1000
    return JSONResponse(body, headers={"X-Bench-Proxy-Ms": f"{proxy_ms:.3f}"})
