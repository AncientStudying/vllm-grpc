from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import grpc
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from vllm_grpc_proxy.chat_router import router as chat_router
from vllm_grpc_proxy.completions_router import router as completions_router
from vllm_grpc_proxy.grpc_client import GrpcHealthClient

_client = GrpcHealthClient()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(chat_router)
app.include_router(completions_router)


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


def main() -> None:
    """Console-script entry point: launch the REST proxy with uvicorn.

    Host/port read from the environment (``PROXY_HOST`` / ``PROXY_PORT``),
    mirroring the ``make run-proxy`` target's defaults.
    """
    import uvicorn

    host = os.environ.get("PROXY_HOST", "0.0.0.0")
    port = int(os.environ.get("PROXY_PORT", "8000"))
    uvicorn.run("vllm_grpc_proxy.main:app", host=host, port=port)


if __name__ == "__main__":
    main()
