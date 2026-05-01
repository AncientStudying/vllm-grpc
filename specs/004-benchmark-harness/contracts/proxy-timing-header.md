# Contract: Proxy Timing Header (`X-Bench-Proxy-Ms`)

**Producer**: `packages/proxy/src/vllm_grpc_proxy/bench_middleware.py`
**Consumer**: `tools/benchmark/src/vllm_grpc_bench/runner.py`

---

## Purpose

The proxy emits a response header that reports the wall-clock time the proxy spent on translation work for each request, excluding gRPC round-trip time (i.e., the time waiting for the frontend to respond). This allows the benchmark harness to measure proxy overhead in isolation from model inference time.

---

## Header Specification

```
X-Bench-Proxy-Ms: <float>
```

| Property | Value |
|----------|-------|
| **Header name** | `X-Bench-Proxy-Ms` |
| **Value type** | Decimal float, milliseconds |
| **Precision** | 3 decimal places (microsecond resolution) |
| **Example** | `X-Bench-Proxy-Ms: 1.847` |

---

## Measurement Points

The middleware measures the following intervals and sums them:

1. **Pre-translation**: Time from request body fully decoded to gRPC call initiated.
   - Start: FastAPI has parsed the request body into a Pydantic model.
   - End: `stub.Complete(proto_req, ...)` is called (the coroutine has been awaited).

2. **Post-translation**: Time from gRPC response received to HTTP response serialized.
   - Start: `await stub.Complete(...)` returns the protobuf response.
   - End: `JSONResponse(...)` is constructed and ready to send.

**Total proxy translation time** = interval 1 + interval 2.

*Excluded*: gRPC connection setup, gRPC network transit, model inference on the frontend.

---

## Implementation Note

The middleware intercepts the request/response cycle by wrapping the route handler. The two timing intervals are captured within the existing `chat_router.py` handler (or via FastAPI middleware that has access to the request lifecycle), not at the ASGI transport layer, to avoid measuring ASGI overhead unrelated to translation.

Concretely, the existing `chat_completions` handler in `chat_router.py` is modified to:
1. Record `t0 = time.perf_counter()` after `openai_request_to_proto(req)` returns.
2. `await _chat_client.complete(proto_req)` — gRPC call (not timed).
3. Record `t1 = time.perf_counter()` after gRPC returns.
4. Call `proto_response_to_openai_dict(proto_resp, req.model)`.
5. Record `t2 = time.perf_counter()`.

`proxy_ms = (t1 - t0 + t2 - t1) * 1000` ... but since `t0` is set right after proto conversion, this simplifies to measuring `proto_response_to_openai_dict` time only. More precisely, `t0` should be before `openai_request_to_proto` and `t1` after it; then `t2` before `proto_response_to_openai_dict` and `t3` after. See data-model: pre-translation = `t1 - t0`, post-translation = `t3 - t2`.

---

## Harness Behaviour When Header Is Absent

- The harness always attempts to read `X-Bench-Proxy-Ms` from the response.
- If the header is absent (e.g., native server endpoint, or proxy without the middleware), `proxy_ms` is recorded as `None` for that request result.
- `None` values are excluded from proxy-time percentile calculations; no error is raised.

---

## Backward Compatibility

This header is additive. Existing clients (curl, Python SDK, integration tests) ignore unknown response headers. No callers are affected.
