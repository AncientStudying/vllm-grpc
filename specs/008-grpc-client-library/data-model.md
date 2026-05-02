# Data Model: Phase 4.2 — Direct gRPC Client Library

## New Package: packages/client

### VllmGrpcClient

Top-level async context manager. Holds a single persistent gRPC channel.

```
VllmGrpcClient
  addr: str              # "host:port" — required, positional
  timeout: float = 30.0 # default per-call timeout in seconds

  # Sub-clients (exposed as properties)
  .chat → ChatClient

  # Context manager protocol
  __aenter__() → self    # opens grpc.aio channel
  __aexit__(...)         # closes channel cleanly
```

### ChatClient

Sub-client for the `ChatService` RPC. Exposed as `VllmGrpcClient.chat`.

```
ChatClient
  _channel: grpc.aio.Channel   # shared with parent, not owned

  complete(
    messages:    list[dict[str, str]],  # [{"role": ..., "content": ...}]
    model:       str,
    max_tokens:  int,
    temperature: float | None = None,
    top_p:       float | None = None,
    seed:        int | None   = None,
    timeout:     float | None = None,  # overrides client default if set
  ) → ChatCompleteResult
```

### ChatCompleteResult

Typed return value from `ChatClient.complete()`. Callers never touch protobuf directly.

```
ChatCompleteResult   (dataclass)
  content:           str        # assistant message content
  role:              str        # always "assistant"
  finish_reason:     str        # "stop" | "length" | ...
  prompt_tokens:     int
  completion_tokens: int
```

---

## New Entities in tools/benchmark/src/vllm_grpc_bench/

### ThreeWayRow  (new dataclass in metrics.py)

One metric at one concurrency level, across three targets.

```
ThreeWayRow   (dataclass)
  metric:         str           # field name, e.g. "latency_p50_ms"
  concurrency:    int
  value_a:        float | None  # REST
  value_b:        float | None  # gRPC-via-proxy
  value_c:        float | None  # gRPC-direct
  delta_pct_b:    float | None  # (b - a) / a; None if either is None or a == 0
  delta_pct_c:    float | None  # (c - a) / a; None if either is None or a == 0
```

### ThreeWayReport  (new dataclass in metrics.py)

Full three-way comparison output.

```
ThreeWayReport   (dataclass)
  label_a:  str             # e.g. "REST"
  label_b:  str             # e.g. "gRPC-proxy"
  label_c:  str             # e.g. "gRPC-direct"
  rows:     list[ThreeWayRow]
  meta_a:   RunMeta
  meta_b:   RunMeta
  meta_c:   RunMeta
```

---

## Modified Entities

### runner.py — target literal extended

```
# Before
Literal["proxy", "native"]

# After
Literal["proxy", "native", "grpc-direct"]
```

### runner.py — new function

```
run_grpc_target(
  addr:        str,                  # host:port of gRPC frontend
  samples:     list[RequestSample],
  concurrency: int,
  timeout:     float,
) → list[RequestResult]
# target field on each result = "grpc-direct"
# request_bytes  = len(ChatCompleteRequest.SerializeToString())
# response_bytes = len(ChatCompleteResponse.SerializeToString())
```

---

## packages/gen Modification

### py.typed marker

New empty file: `packages/gen/src/vllm_grpc/py.typed`

No schema changes. No generated code changes. Effect: removes `# type: ignore[import-untyped]` obligation from all consumers.

---

## Output Files (docs/benchmarks/)

| File | Description |
|------|-------------|
| `phase-4.2-grpc-direct-baseline.json` | Raw harness results for gRPC-direct target |
| `phase-4.2-grpc-direct-baseline.md` | Summary markdown for gRPC-direct |
| `phase-4.2-three-way-comparison.md` | Three-way report: REST / gRPC-proxy / gRPC-direct |
