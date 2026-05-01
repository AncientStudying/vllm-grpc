from __future__ import annotations

import grpc
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from vllm_grpc_proxy.chat_translate import (
    OpenAIChatRequest,
    openai_request_to_proto,
    proto_response_to_openai_dict,
)
from vllm_grpc_proxy.grpc_client import GrpcChatClient

router = APIRouter()
_chat_client = GrpcChatClient()


@router.post("/v1/chat/completions")
async def chat_completions(req: OpenAIChatRequest) -> Response:
    if req.stream:
        err = {"message": "Streaming not yet implemented", "type": "not_implemented_error"}
        return JSONResponse({"error": err}, status_code=501)

    proto_req = openai_request_to_proto(req)
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

    return JSONResponse(proto_response_to_openai_dict(proto_resp, req.model))
