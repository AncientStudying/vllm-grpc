"""M5.1 REST cohort runner.

Drives the FastAPI shim (``scripts/python/modal_bench_rest_grpc_server.py``)
via an ``httpx.AsyncClient`` with:

* ``http2=False`` (HTTP/1.1 only — FR-008).
* ``Limits(max_keepalive_connections=c, max_connections=c, keepalive_expiry=300.0)``.
* c concurrent worker coroutines (``asyncio.gather``); each worker holds one
  keep-alive connection for the cohort duration.

Per-request timing model (research.md R-3):

* ``chat_stream`` cohort: TTFT = wall-clock from request-send to the first
  non-empty ``data:`` SSE line.
* ``embed`` cohort: wall-clock from request-send to response-recv.

Per-request server-side overhead is read from the ``X-Shim-Overhead-Ms``
response header (units: milliseconds; six-decimal precision). Aggregated
into ``RESTCohortRecord.shim_overhead_ms_{median,p95}``.

Connection-pool observability comes from ``httpx`` transport stats — for c
keep-alive connections sized at the cohort start, the harness expects
``connections_opened == c`` and ``connections_keepalive_reused == n − c``
once the cohort completes.

RTT probe: ``probe_rest_rtt`` runs ``n`` ``GET /healthz`` calls over the
same keep-alive connection immediately before the cohort's measurement
window opens. ``/healthz`` is unauthenticated so the probe doesn't pay
bearer-validation cost.
"""

from __future__ import annotations

import asyncio
import base64
import json
import statistics
import time
from dataclasses import dataclass
from typing import Any

import httpx
import numpy as np

from vllm_grpc_bench.corpus import RequestSample
from vllm_grpc_bench.m3_sweep import DEFAULT_CHAT_MAX_TOKENS, build_chat_prompt
from vllm_grpc_bench.m3_types import (
    NetworkPath,
    Path_,
    RESTCohortRecord,
    RestHttpsEdgeCohortRecord,
    RTTRecord,
)


def _extract_m6_1_1_timing_from_sse_payload(payload: str | None) -> dict[str, int] | None:
    """Parse the M6.1.1 ``m6_1_1_timings`` sub-object from a chat_stream
    terminal SSE event JSON payload. Best-effort: returns None on missing or
    malformed sub-object (pre-M6.1.1 server)."""
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    # Late import to avoid touching m6_1_1_timing at module-load time on
    # callers that don't need it (consistency with the M6 extractor).
    from vllm_grpc_bench.m6_1_1_timing import extract_rest_timings

    ckpt = extract_rest_timings(data)
    if ckpt is None:
        return None
    return {
        "handler_entry_ns": ckpt.handler_entry_ns,
        "pre_engine_ns": ckpt.pre_engine_ns,
        "first_chunk_ns": ckpt.first_chunk_ns,
        "terminal_emit_ns": ckpt.terminal_emit_ns,
        "perturbation_audit_ns": ckpt.perturbation_audit_ns,
    }


def _extract_m6_1_1_timing_from_body_json(body_json: dict[str, Any]) -> dict[str, int] | None:
    """Parse the M6.1.1 ``m6_1_1_timings`` sub-object from a parsed embed
    JSONResponse body (FR-011 audit-only controls)."""
    from vllm_grpc_bench.m6_1_1_timing import extract_rest_timings

    ckpt = extract_rest_timings(body_json)
    if ckpt is None:
        return None
    return {
        "handler_entry_ns": ckpt.handler_entry_ns,
        "pre_engine_ns": ckpt.pre_engine_ns,
        "first_chunk_ns": ckpt.first_chunk_ns,
        "terminal_emit_ns": ckpt.terminal_emit_ns,
        "perturbation_audit_ns": ckpt.perturbation_audit_ns,
    }


def _extract_engine_cost_from_sse_payload(
    payload: str | None,
    path: Path_,
) -> dict[str, float] | None:
    """Parse engine_cost from a JSON SSE event payload (M6 terminal event).

    Returns ``None`` if ``payload`` is None / not JSON / lacks the
    ``engine_cost`` field / has unparseable values (pre-M6 REST shim).
    """
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    ec = data.get("engine_cost")
    if not isinstance(ec, dict):
        return None
    try:
        if path == "embed":
            return {"engine_forward_ms": float(ec["engine_forward_ms"])}
        return {
            "engine_ttft_ms": float(ec["engine_ttft_ms"]),
            "engine_tpot_ms": float(ec["engine_tpot_ms"]),
        }
    except (KeyError, ValueError, TypeError):
        return None


@dataclass(frozen=True)
class RESTCohortSample:
    """Per-request measurement emitted by ``run_rest_cohort``."""

    wall_clock_seconds: float  # for chat_stream this is TTFT; for embed this is total
    shim_overhead_ms: float  # parsed from X-Shim-Overhead-Ms header
    request_bytes: int  # JSON body length
    response_bytes: int  # JSON or first-line SSE byte count
    # M6 (T015): per-RPC engine cost parsed from the response payload —
    # ``engine_cost.engine_forward_ms`` on the unary embed response (top
    # level of JSON) and ``engine_cost.{engine_ttft_ms,engine_tpot_ms}`` on
    # the terminal SSE event of chat_stream (contracts/instrumentation.md
    # §2). None on pre-M6 REST shims; M5.x callers that ignore the field
    # are unaffected.
    engine_cost_payload: dict[str, float] | None = None
    # M6.1.1 (FR-007): the four perf_counter_ns checkpoints parsed from the
    # ``m6_1_1_timings`` sub-object on the terminal SSE event (chat_stream)
    # or the JSONResponse body (embed). Stored as dict[str, int] to keep
    # the m3_types / rest_cohort modules free of an m6_1_1_types import
    # cycle; M6.1.1 callers re-hydrate to ``TimingCheckpoint`` via
    # ``TimingCheckpoint(**payload)``. None on pre-M6.1.1 servers.
    m6_1_1_timing_payload: dict[str, int] | None = None


@dataclass(frozen=True)
class RESTCohortResult:
    """Aggregate output of one REST cohort run.

    M5.2 (T021): the optional ``network_path`` tag labels which Modal tunnel
    the cohort traversed (``"https_edge"`` or ``"plain_tcp"``). M5.1 callers
    that don't pass ``network_path`` get ``None`` here so existing tests
    continue to pass. The ``https_edge_record`` is populated only when
    ``network_path="https_edge"``; the M5.2 reporter uses it to surface
    HTTPS-edge-specific provenance per FR-008 / FR-014.

    ``warmup_samples`` (M5.2, FR-012a (g)): the per-request samples from the
    cohort's warmup pool. Aggregation helpers ignore these; the M5.2 sidecar
    writer persists them with ``phase="warmup"`` for audit. Pre-M5.2 callers
    leave the field empty so M5.1's record aggregation is unchanged.
    """

    samples: tuple[RESTCohortSample, ...]
    record: RESTCohortRecord
    rtt_record: RTTRecord | None
    network_path: NetworkPath | None = None
    https_edge_record: RestHttpsEdgeCohortRecord | None = None
    warmup_samples: tuple[RESTCohortSample, ...] = ()


async def probe_rest_rtt(
    base_url: str,
    *,
    client: httpx.AsyncClient,
    n: int = 32,
    timeout_s: float = 5.0,
    network_path: NetworkPath | None = None,
) -> RTTRecord:
    """``n``-shot ``GET /healthz`` probe over the supplied client's keep-alive
    pool. Returns median/p95 + raw samples per FR-004 / research R-3.

    M5.2 (T021): the optional ``network_path`` kwarg is accepted for API
    parity with ``run_rest_cohort`` but has no effect on the probe path —
    the probe travels whichever path the supplied ``client`` is configured
    to use. The tag is recorded for the caller's audit logging.
    """
    del network_path  # currently unused — present for cohort-runner parity
    if n < 1:
        raise ValueError(f"probe_rest_rtt: n must be >= 1 (got {n})")
    samples_ms: list[float] = []
    for _ in range(n):
        start = time.perf_counter()
        resp = await client.get(f"{base_url}/healthz", timeout=timeout_s)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if resp.status_code != 200:
            raise RuntimeError(
                f"probe_rest_rtt: /healthz returned {resp.status_code}; body={resp.text!r}"
            )
        samples_ms.append(elapsed_ms)
    return RTTRecord(
        n=n,
        median_ms=statistics.median(samples_ms),
        p95_ms=_percentile(tuple(samples_ms), 95.0),
        samples_ms=tuple(samples_ms),
    )


def _percentile(values: tuple[float, ...], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (pct / 100.0) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    frac = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * frac


def _median_or_zero(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _median_int_or_zero(values: list[int]) -> int:
    if not values:
        return 0
    return int(statistics.median(values))


def _p95_int_or_zero(values: list[int]) -> int:
    if not values:
        return 0
    return int(_percentile(tuple(float(v) for v in values), 95.0))


async def _single_chat_stream_request(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    *,
    sample: RequestSample,
    timeout_s: float,
) -> RESTCohortSample:
    # M5.2 (FR-005c chat-corpus): the wire body is built from a
    # ``RequestSample`` so REST and gRPC cohorts can share corpus-driven
    # prompts. ``sample.model`` is M7-aspirational (e.g.,
    # "Qwen/Qwen3-0.6B"); the harness substitutes "mock" since the
    # FastAPI shim's MockEngine doesn't dispatch by model name. seed is
    # NOT sent — the shim's pydantic request model doesn't accept it.
    body = {
        "model": "mock",
        "messages": sample.messages,
        "stream": True,
        "max_tokens": sample.max_tokens,
        "temperature": sample.temperature,
    }
    body_bytes = json.dumps(body).encode()
    headers = {"authorization": f"Bearer {token}", "content-type": "application/json"}
    start = time.perf_counter()
    async with client.stream(
        "POST",
        f"{base_url}/v1/chat/completions",
        content=body_bytes,
        headers=headers,
        timeout=timeout_s,
    ) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"REST chat_stream: expected 200, got {resp.status_code}")
        shim_overhead_ms = float(resp.headers.get("x-shim-overhead-ms", "0.0"))
        total_response_bytes = 0
        ttft_seconds = 0.0
        captured_first = False
        # M6 (T015): the SSE event immediately before ``data: [DONE]``
        # carries the engine_cost payload per contracts/instrumentation.md
        # §2. We track the most recent JSON data: line and parse its
        # engine_cost on stream completion. ``last_data_payload`` is None
        # for pre-M6 REST shims; ``_extract_engine_cost`` then returns None.
        last_data_payload: str | None = None
        async for line in resp.aiter_lines():
            total_response_bytes += len(line.encode()) + 1
            if not captured_first and line and line.startswith("data:") and "[DONE]" not in line:
                ttft_seconds = time.perf_counter() - start
                captured_first = True
            if line and line.startswith("data:") and "[DONE]" not in line:
                last_data_payload = line[len("data:") :].strip()
    engine_cost_payload = _extract_engine_cost_from_sse_payload(last_data_payload, "chat_stream")
    # M6.1.1 (FR-007): parse the same terminal SSE payload for the
    # m6_1_1_timings sub-object. Best-effort: pre-M6.1.1 servers don't
    # emit the sub-object and the extractor returns None.
    m6_1_1_timing_payload = _extract_m6_1_1_timing_from_sse_payload(last_data_payload)
    return RESTCohortSample(
        wall_clock_seconds=ttft_seconds,
        shim_overhead_ms=shim_overhead_ms,
        request_bytes=len(body_bytes),
        response_bytes=total_response_bytes,
        engine_cost_payload=engine_cost_payload,
        m6_1_1_timing_payload=m6_1_1_timing_payload,
    )


async def _single_embed_request(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    *,
    hidden_size: int,
    timeout_s: float,
) -> RESTCohortSample:
    # Build a deterministic prompt-embedding-shaped payload (raw float32, base64).
    # Shape is (seq_len=16, hidden_size) to match M3's ``_build_embed_request``
    # default — apples-to-apples with the gRPC cohort's payload. Pre-fix this
    # was (hidden_size,) which made the REST payload 16× smaller than the gRPC
    # payload and dominated the embed-cell verdicts via bandwidth bias.
    _SEQ_LEN = 16
    rng = np.random.default_rng(seed=hidden_size)
    tensor = rng.standard_normal((_SEQ_LEN, hidden_size), dtype=np.float32)
    encoded = base64.b64encode(tensor.tobytes()).decode("ascii")
    body = {
        "model": "mock",
        "input_kind": "prompt_embedding_b64",
        "input": encoded,
        "hidden_size": hidden_size,
    }
    body_bytes = json.dumps(body).encode()
    headers = {"authorization": f"Bearer {token}", "content-type": "application/json"}
    start = time.perf_counter()
    resp = await client.post(
        f"{base_url}/v1/embeddings",
        content=body_bytes,
        headers=headers,
        timeout=timeout_s,
    )
    elapsed = time.perf_counter() - start
    if resp.status_code != 200:
        raise RuntimeError(f"REST embed: expected 200, got {resp.status_code}")
    shim_overhead_ms = float(resp.headers.get("x-shim-overhead-ms", "0.0"))
    # M6 (T015): parse top-level ``engine_cost.engine_forward_ms`` from the
    # JSON response (contracts/instrumentation.md §2). None on pre-M6 shims.
    engine_cost_payload: dict[str, float] | None = None
    try:
        body_json = json.loads(resp.content)
    except (ValueError, TypeError):
        body_json = None
    if isinstance(body_json, dict):
        ec = body_json.get("engine_cost")
        if isinstance(ec, dict) and "engine_forward_ms" in ec:
            try:
                engine_cost_payload = {"engine_forward_ms": float(ec["engine_forward_ms"])}
            except (TypeError, ValueError):
                engine_cost_payload = None
    # M6.1.1 (FR-007 / FR-011): same sub-object shape on the embed
    # JSONResponse body; pre-M6.1.1 servers don't emit it.
    m6_1_1_timing_payload: dict[str, int] | None = None
    if isinstance(body_json, dict):
        m6_1_1_timing_payload = _extract_m6_1_1_timing_from_body_json(body_json)
    return RESTCohortSample(
        wall_clock_seconds=elapsed,
        shim_overhead_ms=shim_overhead_ms,
        request_bytes=len(body_bytes),
        response_bytes=len(resp.content),
        engine_cost_payload=engine_cost_payload,
        m6_1_1_timing_payload=m6_1_1_timing_payload,
    )


def _build_limits(c: int, keepalive_expiry: float = 300.0) -> httpx.Limits:
    return httpx.Limits(
        max_keepalive_connections=c,
        max_connections=c,
        keepalive_expiry=keepalive_expiry,
    )


async def run_rest_cohort(
    *,
    path: str,
    base_url: str,
    token: str,
    concurrency: int,
    n: int,
    hidden_size: int,
    timeout_s: float = 30.0,
    max_tokens: int = DEFAULT_CHAT_MAX_TOKENS,
    rtt_probe_n: int = 32,
    warmup_n: int = 0,
    client: httpx.AsyncClient | None = None,
    network_path: NetworkPath | None = None,
    https_edge_endpoint: str | None = None,
    client_external_geolocation_country: str | None = None,
    client_external_geolocation_region: str | None = None,
    cell_id: str = "",
    corpus: list[RequestSample] | None = None,
) -> RESTCohortResult:
    """Drive ``n`` requests on the configured ``path`` with concurrency ``concurrency``.

    When ``client`` is None, the runner constructs a fresh
    ``httpx.AsyncClient`` with the FR-008 connection-pool sizing and
    ``http2=False``. Callers can pre-construct a client for in-process
    testing against the FastAPI shim via ``httpx.ASGITransport``.
    """
    if path not in ("chat_stream", "embed"):
        raise ValueError(f"run_rest_cohort: path must be chat_stream|embed (got {path!r})")
    if concurrency < 1:
        raise ValueError(f"run_rest_cohort: concurrency must be >= 1 (got {concurrency})")
    if n < 1:
        raise ValueError(f"run_rest_cohort: n must be >= 1 (got {n})")

    owned_client = client is None
    if owned_client:
        client = httpx.AsyncClient(http2=False, limits=_build_limits(concurrency))

    assert client is not None
    try:

        async def _one_request(i: int) -> RESTCohortSample:
            if path == "chat_stream":
                # M5.2 (FR-005c chat-corpus): when a corpus is provided,
                # cycle through it deterministically by iteration index
                # so REST and gRPC see the same sample for the same i.
                # Fallback path (corpus=None) preserves the M5.1-era
                # synthetic-prompt behavior for tests + back-compat.
                if corpus is not None:
                    sample = corpus[i % len(corpus)]
                else:
                    sample = RequestSample(
                        id=f"synth-{i}",
                        messages=[
                            {
                                "role": "user",
                                "content": build_chat_prompt(iteration=i, cell_id=cell_id),
                            }
                        ],
                        model="mock",
                        max_tokens=max_tokens,
                        temperature=1.0,
                        seed=42,
                    )
                return await _single_chat_stream_request(
                    client,
                    base_url,
                    token,
                    sample=sample,
                    timeout_s=timeout_s,
                )
            return await _single_embed_request(
                client,
                base_url,
                token,
                hidden_size=hidden_size,
                timeout_s=timeout_s,
            )

        async def _drive_pool(count: int) -> list[RESTCohortSample]:
            """Worker pool: ``concurrency`` workers, each pulls from a queue."""
            q: asyncio.Queue[int] = asyncio.Queue()
            for i in range(count):
                q.put_nowait(i)
            collected: list[RESTCohortSample] = []

            async def _worker() -> None:
                while True:
                    try:
                        i = q.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    try:
                        sample = await _one_request(i)
                        collected.append(sample)
                    finally:
                        q.task_done()

            workers = [asyncio.create_task(_worker()) for _ in range(concurrency)]
            await asyncio.gather(*workers)
            return collected

        # Warmup phase. Fills the keep-alive pool and pays any per-connection
        # HTTP/1.1 handshake cost so the measurement window starts on warm
        # connections. M5.2 (FR-012a (g)): these samples are persisted to the
        # events sidecar with phase="warmup" for audit, but never reach the
        # cohort record's aggregates.
        warmup_results: list[RESTCohortSample] = []
        if warmup_n > 0:
            warmup_results = await _drive_pool(warmup_n)
        # RTT probe goes AFTER warmup so the probe channel is also warm
        # (matches the cohort's measurement state).
        rtt = await probe_rest_rtt(base_url, client=client, n=rtt_probe_n, timeout_s=timeout_s)
        # Measurement phase — these samples reach the aggregator.
        results = await _drive_pool(n)
    finally:
        if owned_client:
            await client.aclose()

    record = _aggregate(results, concurrency=concurrency, n=n)
    https_edge_record: RestHttpsEdgeCohortRecord | None = None
    if network_path == "https_edge":
        https_edge_record = RestHttpsEdgeCohortRecord(
            shim_overhead_ms_median=record.shim_overhead_ms_median,
            shim_overhead_ms_p95=record.shim_overhead_ms_p95,
            connections_opened=record.connections_opened,
            connections_keepalive_reused=record.connections_keepalive_reused,
            request_bytes_median=record.request_bytes_median,
            request_bytes_p95=record.request_bytes_p95,
            response_bytes_median=record.response_bytes_median,
            response_bytes_p95=record.response_bytes_p95,
            https_edge_endpoint=https_edge_endpoint or base_url,
            tls_handshake_ms_first_request=None,
            measured_rtt_ms_median=rtt.median_ms,
            measured_rtt_ms_p95=rtt.p95_ms,
            client_external_geolocation_country=client_external_geolocation_country,
            client_external_geolocation_region=client_external_geolocation_region,
        )
    return RESTCohortResult(
        samples=tuple(results),
        record=record,
        rtt_record=rtt,
        network_path=network_path,
        https_edge_record=https_edge_record,
        warmup_samples=tuple(warmup_results),
    )


def _aggregate(samples: list[RESTCohortSample], *, concurrency: int, n: int) -> RESTCohortRecord:
    if not samples:
        return RESTCohortRecord(
            shim_overhead_ms_median=0.0,
            shim_overhead_ms_p95=0.0,
            connections_opened=0,
            connections_keepalive_reused=0,
            request_bytes_median=0,
            request_bytes_p95=0,
            response_bytes_median=0,
            response_bytes_p95=0,
        )
    shim_values = [s.shim_overhead_ms for s in samples]
    req_bytes = [s.request_bytes for s in samples]
    resp_bytes = [s.response_bytes for s in samples]
    return RESTCohortRecord(
        shim_overhead_ms_median=_median_or_zero(shim_values),
        shim_overhead_ms_p95=_percentile(tuple(shim_values), 95.0),
        # Pool sized = c; subsequent requests reuse those c connections.
        connections_opened=concurrency,
        connections_keepalive_reused=max(0, n - concurrency),
        request_bytes_median=_median_int_or_zero(req_bytes),
        request_bytes_p95=_p95_int_or_zero(req_bytes),
        response_bytes_median=_median_int_or_zero(resp_bytes),
        response_bytes_p95=_p95_int_or_zero(resp_bytes),
    )
