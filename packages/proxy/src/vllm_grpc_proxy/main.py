from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import grpc
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from vllm_grpc_proxy.grpc_client import GrpcHealthClient

_client = GrpcHealthClient()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> Response:
    try:
        await _client.ping()
        return JSONResponse({"status": "ok"})
    except grpc.aio.AioRpcError as exc:
        return JSONResponse(
            {"status": "error", "detail": str(exc.details())},
            status_code=503,
        )
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "detail": str(exc)},
            status_code=503,
        )
