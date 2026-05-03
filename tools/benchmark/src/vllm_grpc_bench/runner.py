from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Literal

import httpx
from vllm_grpc.v1 import chat_pb2

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


def _build_request_proto(sample: RequestSample) -> chat_pb2.ChatCompleteRequest:
    kwargs: dict[str, object] = {}
    if sample.temperature is not None:
        kwargs["temperature"] = sample.temperature
    if sample.seed is not None:
        kwargs["seed"] = sample.seed
    return chat_pb2.ChatCompleteRequest(
        messages=[
            chat_pb2.ChatMessage(role=m["role"], content=m["content"]) for m in sample.messages
        ],
        model=sample.model,
        max_tokens=sample.max_tokens,
        **kwargs,
    )


async def run_grpc_target(
    addr: str,
    samples: list[RequestSample],
    concurrency: int,
    timeout: float,
) -> list[RequestResult]:
    from vllm_grpc_client import VllmGrpcClient

    async with VllmGrpcClient(addr, timeout=timeout) as grpc_client:
        sem = asyncio.Semaphore(concurrency)

        async def _send_one_grpc(sample: RequestSample) -> RequestResult:
            req_proto = _build_request_proto(sample)
            request_bytes = len(req_proto.SerializeToString())
            t0 = time.perf_counter()
            try:
                result = await grpc_client.chat.complete(
                    messages=sample.messages,
                    model=sample.model,
                    max_tokens=sample.max_tokens,
                    temperature=sample.temperature,
                    seed=sample.seed,
                    timeout=timeout,
                )
                t1 = time.perf_counter()
                response_proto = chat_pb2.ChatCompleteResponse(
                    message=chat_pb2.ChatMessage(
                        role=result.role,
                        content=result.content,
                    ),
                    finish_reason=result.finish_reason,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                )
                return RequestResult(
                    sample_id=sample.id,
                    target="grpc-direct",
                    concurrency=concurrency,
                    latency_ms=(t1 - t0) * 1000,
                    request_bytes=request_bytes,
                    response_bytes=len(response_proto.SerializeToString()),
                    proxy_ms=None,
                    success=True,
                    error=None,
                )
            except Exception as exc:
                t1 = time.perf_counter()
                return RequestResult(
                    sample_id=sample.id,
                    target="grpc-direct",
                    concurrency=concurrency,
                    latency_ms=(t1 - t0) * 1000,
                    request_bytes=request_bytes,
                    response_bytes=None,
                    proxy_ms=None,
                    success=False,
                    error=str(exc),
                )

        async def bounded_grpc(sample: RequestSample) -> RequestResult:
            async with sem:
                return await _send_one_grpc(sample)

        return list(await asyncio.gather(*[bounded_grpc(s) for s in samples]))


async def _send_one_streaming(
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
        "stream": True,
    }
    body_bytes = json.dumps(body).encode()

    t0 = time.perf_counter()
    t_first: float | None = None
    t_last: float | None = None
    token_count = 0
    try:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            content=body_bytes,
            headers={"Content-Type": "application/json"},
        ) as response:
            success = 200 <= response.status_code < 300
            async for line in response.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                t_now = time.perf_counter()
                try:
                    payload = json.loads(line[6:])
                    delta = payload["choices"][0]["delta"]
                    content = delta.get("content", "")
                except (KeyError, json.JSONDecodeError):
                    continue
                if content:
                    token_count += 1
                    if t_first is None:
                        t_first = t_now
                    t_last = t_now
        t1 = time.perf_counter()
        latency_ms = (t1 - t0) * 1000
        ttft_ms = (t_first - t0) * 1000 if t_first is not None else None
        tpot_ms = (
            (t_last - t_first) * 1000 / (token_count - 1)
            if t_last is not None and t_first is not None and token_count > 1
            else None
        )
        return RequestResult(
            sample_id=sample.id,
            target=target,
            concurrency=concurrency,
            latency_ms=latency_ms,
            request_bytes=len(body_bytes),
            response_bytes=None,
            proxy_ms=None,
            success=success,
            error=None if success else f"HTTP {response.status_code}",
            ttft_ms=ttft_ms,
            tpot_ms=tpot_ms,
            token_count=token_count if token_count > 0 else None,
        )
    except Exception as exc:
        t1 = time.perf_counter()
        return RequestResult(
            sample_id=sample.id,
            target=target,
            concurrency=concurrency,
            latency_ms=(t1 - t0) * 1000,
            request_bytes=len(body_bytes),
            response_bytes=None,
            proxy_ms=None,
            success=False,
            error=str(exc),
        )


async def run_target_streaming(
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
                return await _send_one_streaming(client, sample, target, concurrency)

        return list(await asyncio.gather(*[bounded(s) for s in samples]))


async def run_grpc_target_streaming(
    addr: str,
    samples: list[RequestSample],
    concurrency: int,
    timeout: float,
) -> list[RequestResult]:
    from vllm_grpc_client import VllmGrpcClient

    async with VllmGrpcClient(addr, timeout=timeout) as grpc_client:
        sem = asyncio.Semaphore(concurrency)

        async def _send_one_grpc_stream(sample: RequestSample) -> RequestResult:
            req_proto = _build_request_proto(sample)
            request_bytes = len(req_proto.SerializeToString())
            t0 = time.perf_counter()
            t_first: float | None = None
            t_last: float | None = None
            token_count = 0
            try:
                async for chunk in grpc_client.chat.complete_stream(
                    messages=sample.messages,
                    model=sample.model,
                    max_tokens=sample.max_tokens,
                    temperature=sample.temperature,
                    seed=sample.seed,
                    timeout=timeout,
                ):
                    if chunk.delta_content:
                        t_now = time.perf_counter()
                        token_count += 1
                        if t_first is None:
                            t_first = t_now
                        t_last = t_now
                t1 = time.perf_counter()
                ttft_ms = (t_first - t0) * 1000 if t_first is not None else None
                tpot_ms = (
                    (t_last - t_first) * 1000 / (token_count - 1)
                    if t_last is not None and t_first is not None and token_count > 1
                    else None
                )
                return RequestResult(
                    sample_id=sample.id,
                    target="grpc-direct",
                    concurrency=concurrency,
                    latency_ms=(t1 - t0) * 1000,
                    request_bytes=request_bytes,
                    response_bytes=None,
                    proxy_ms=None,
                    success=True,
                    error=None,
                    ttft_ms=ttft_ms,
                    tpot_ms=tpot_ms,
                    token_count=token_count if token_count > 0 else None,
                )
            except Exception as exc:
                t1 = time.perf_counter()
                return RequestResult(
                    sample_id=sample.id,
                    target="grpc-direct",
                    concurrency=concurrency,
                    latency_ms=(t1 - t0) * 1000,
                    request_bytes=request_bytes,
                    response_bytes=None,
                    proxy_ms=None,
                    success=False,
                    error=str(exc),
                )

        async def bounded_grpc_stream(sample: RequestSample) -> RequestResult:
            async with sem:
                return await _send_one_grpc_stream(sample)

        return list(await asyncio.gather(*[bounded_grpc_stream(s) for s in samples]))


async def run_completions_proxy_text(
    url: str,
    samples: list[Any],  # list[CompletionTextSample]
    concurrency: int,
    timeout: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[RequestResult]:
    """Measure wire size for text-prompt completions via REST proxy."""
    kwargs: dict[str, object] = {"base_url": url, "timeout": timeout}
    if transport is not None:
        kwargs["transport"] = transport

    async with httpx.AsyncClient(**kwargs) as client:  # type: ignore[arg-type]
        sem = asyncio.Semaphore(concurrency)

        async def _send_one_text(sample: Any) -> RequestResult:
            body = {
                "model": sample.model,
                "prompt": sample.prompt,
                "max_tokens": sample.max_tokens,
                "seed": sample.seed,
            }
            body_bytes = json.dumps(body).encode()
            t0 = time.perf_counter()
            try:
                response = await client.post(
                    "/v1/completions",
                    content=body_bytes,
                    headers={"Content-Type": "application/json"},
                )
                t1 = time.perf_counter()
                success = 200 <= response.status_code < 300
                return RequestResult(
                    sample_id=str(sample.id),
                    target="proxy",
                    concurrency=concurrency,
                    latency_ms=(t1 - t0) * 1000,
                    request_bytes=len(body_bytes),
                    response_bytes=len(response.content),
                    proxy_ms=None,
                    success=success,
                    error=None if success else f"HTTP {response.status_code}",
                    request_type="completion-text",
                )
            except Exception as exc:
                t1 = time.perf_counter()
                return RequestResult(
                    sample_id=str(sample.id),
                    target="proxy",
                    concurrency=concurrency,
                    latency_ms=(t1 - t0) * 1000,
                    request_bytes=len(body_bytes),
                    response_bytes=None,
                    proxy_ms=None,
                    success=False,
                    error=str(exc),
                    request_type="completion-text",
                )

        async def bounded_text(sample: Any) -> RequestResult:
            async with sem:
                return await _send_one_text(sample)

        return list(await asyncio.gather(*[bounded_text(s) for s in samples]))


async def run_completions_proxy_embeds(
    url: str,
    samples: list[Any],  # list[CompletionEmbedSample]
    concurrency: int,
    timeout: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[RequestResult]:
    """Measure wire size for embedding-prompt completions via REST proxy (base64-encoded bytes)."""
    import base64

    kwargs: dict[str, object] = {"base_url": url, "timeout": timeout}
    if transport is not None:
        kwargs["transport"] = transport

    async with httpx.AsyncClient(**kwargs) as client:  # type: ignore[arg-type]
        sem = asyncio.Semaphore(concurrency)

        async def _send_one_embeds(sample: Any) -> RequestResult:
            b64_embeds = base64.b64encode(sample.tensor_bytes).decode()
            body = {
                "model": "Qwen/Qwen3-0.6B",
                "prompt_embeds": b64_embeds,
                "max_tokens": sample.max_tokens,
                "seed": sample.seed,
            }
            body_bytes = json.dumps(body).encode()
            t0 = time.perf_counter()
            try:
                response = await client.post(
                    "/v1/completions",
                    content=body_bytes,
                    headers={"Content-Type": "application/json"},
                )
                t1 = time.perf_counter()
                success = 200 <= response.status_code < 300
                return RequestResult(
                    sample_id=str(sample.id),
                    target="proxy",
                    concurrency=concurrency,
                    latency_ms=(t1 - t0) * 1000,
                    request_bytes=len(body_bytes),
                    response_bytes=len(response.content),
                    proxy_ms=None,
                    success=success,
                    error=None if success else f"HTTP {response.status_code}",
                    request_type="completion-embeds",
                )
            except Exception as exc:
                t1 = time.perf_counter()
                return RequestResult(
                    sample_id=str(sample.id),
                    target="proxy",
                    concurrency=concurrency,
                    latency_ms=(t1 - t0) * 1000,
                    request_bytes=len(body_bytes),
                    response_bytes=None,
                    proxy_ms=None,
                    success=False,
                    error=str(exc),
                    request_type="completion-embeds",
                )

        async def bounded_embeds(sample: Any) -> RequestResult:
            async with sem:
                return await _send_one_embeds(sample)

        return list(await asyncio.gather(*[bounded_embeds(s) for s in samples]))


async def run_completions_grpc_direct(
    addr: str,
    samples: list[Any],  # list[CompletionTextSample] — text prompt path
    concurrency: int,
    timeout: float,
) -> list[RequestResult]:
    """Measure wire size for text-prompt completions via gRPC direct path."""
    from vllm_grpc.v1 import completions_pb2
    from vllm_grpc_client import VllmGrpcClient

    async with VllmGrpcClient(addr, timeout=timeout) as grpc_client:
        sem = asyncio.Semaphore(concurrency)

        async def _send_one_grpc_completion(sample: Any) -> RequestResult:
            proto_req = completions_pb2.CompletionRequest(
                model=sample.model,
                max_tokens=sample.max_tokens,
                seed=sample.seed,
                prompt=sample.prompt,
            )
            request_bytes = len(proto_req.SerializeToString())
            t0 = time.perf_counter()
            try:
                result = await grpc_client.completions.complete(
                    model=sample.model,
                    max_tokens=sample.max_tokens,
                    prompt=sample.prompt,
                    seed=sample.seed,
                    timeout=timeout,
                )
                t1 = time.perf_counter()
                response_proto = completions_pb2.CompletionResponse(
                    generated_text=result.generated_text,
                    finish_reason=result.finish_reason,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                )
                return RequestResult(
                    sample_id=str(sample.id),
                    target="grpc-direct",
                    concurrency=concurrency,
                    latency_ms=(t1 - t0) * 1000,
                    request_bytes=request_bytes,
                    response_bytes=len(response_proto.SerializeToString()),
                    proxy_ms=None,
                    success=True,
                    error=None,
                    request_type="completion-text",
                )
            except Exception as exc:
                t1 = time.perf_counter()
                return RequestResult(
                    sample_id=str(sample.id),
                    target="grpc-direct",
                    concurrency=concurrency,
                    latency_ms=(t1 - t0) * 1000,
                    request_bytes=request_bytes,
                    response_bytes=None,
                    proxy_ms=None,
                    success=False,
                    error=str(exc),
                    request_type="completion-text",
                )

        async def bounded_grpc_completion(sample: Any) -> RequestResult:
            async with sem:
                return await _send_one_grpc_completion(sample)

        return list(await asyncio.gather(*[bounded_grpc_completion(s) for s in samples]))
