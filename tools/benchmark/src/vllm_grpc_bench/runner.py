from __future__ import annotations

import asyncio
import json
import time
from typing import Literal

import httpx

from vllm_grpc_bench.corpus import RequestSample
from vllm_grpc_bench.metrics import RequestResult


async def _send_one(
    client: httpx.AsyncClient,
    sample: RequestSample,
    target: Literal["proxy", "native"],
    concurrency: int,
) -> RequestResult:
    body = {
        "model": sample.model,
        "messages": sample.messages,
        "max_tokens": sample.max_tokens,
        "temperature": sample.temperature,
        "seed": sample.seed,
    }
    body_bytes = json.dumps(body).encode()

    t0 = time.perf_counter()
    try:
        response = await client.post(
            "/v1/chat/completions",
            content=body_bytes,
            headers={"Content-Type": "application/json"},
        )
        t1 = time.perf_counter()
        latency_ms = (t1 - t0) * 1000
        response_body = response.content
        success = 200 <= response.status_code < 300
        proxy_ms_raw = response.headers.get("x-bench-proxy-ms")
        proxy_ms = float(proxy_ms_raw) if proxy_ms_raw is not None else None
        return RequestResult(
            sample_id=sample.id,
            target=target,
            concurrency=concurrency,
            latency_ms=latency_ms,
            request_bytes=len(body_bytes),
            response_bytes=len(response_body),
            proxy_ms=proxy_ms,
            success=success,
            error=None if success else f"HTTP {response.status_code}",
        )
    except Exception as exc:
        t1 = time.perf_counter()
        return RequestResult(
            sample_id=sample.id,
            target=target,
            concurrency=concurrency,
            latency_ms=None,
            request_bytes=len(body_bytes),
            response_bytes=None,
            proxy_ms=None,
            success=False,
            error=str(exc),
        )


async def run_target(
    target: Literal["proxy", "native"],
    url: str,
    samples: list[RequestSample],
    concurrency: int,
    timeout: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[RequestResult]:
    kwargs: dict[str, object] = {"base_url": url, "timeout": timeout}
    if transport is not None:
        kwargs["transport"] = transport

    async with httpx.AsyncClient(**kwargs) as client:  # type: ignore[arg-type]
        sem = asyncio.Semaphore(concurrency)

        async def bounded(sample: RequestSample) -> RequestResult:
            async with sem:
                return await _send_one(client, sample, target, concurrency)

        return list(await asyncio.gather(*[bounded(s) for s in samples]))
