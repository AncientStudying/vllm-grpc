# Contract: Engine-Cost Instrumentation Wire Format

**Plan**: [../plan.md](../plan.md)
**Spec FRs**: FR-008 (engine cost source-side instrumentation), FR-014 sub-clause (engine_cost_drift_warning)
**Research**: [R-1](../research.md#r-1-asyncllm-has-no-native-per-request-timing-surface), [R-2](../research.md#r-2-engine-cost-on-grpc-published-via-trailing-metadata-not-proto-extension), [R-4](../research.md#r-4-rest-shim-engine_cost-json-schema-mirrors-grpc-trailing-metadata)

This document fixes the wire-format contracts for emitting and consuming per-RPC engine cost across the three M6 cohorts. The same logical data (`engine_forward_ms` / `engine_ttft_ms` / `engine_tpot_ms`) is emitted via two transport-specific channels — gRPC trailing metadata and REST JSON payload fields — and consumed into a single in-memory shape (`EngineCostSpan`, see [data-model.md](../data-model.md)).

---

## 1. Server-side timing wrapper (greenfield)

### Where it lives

`packages/frontend/src/vllm_grpc_frontend/{chat.py, completions.py}` — the gRPC frontend that proxies between gRPC requests and `AsyncLLM.generate()` calls.

### Embed (unary RPC; `completions.py` embed path)

```python
import time
# Pseudocode — actual impl uses the existing engine wrapper class
async def serve_embed(request, context):
    request_id = ...  # from request
    sampling_params = ...  # built from request
    prompt = ...  # extracted from request
    start = time.perf_counter()
    final_output = await drain_to_final(self._engine.generate(prompt, sampling_params, request_id))
    end = time.perf_counter()
    engine_forward_ms = (end - start) * 1000.0
    # Build response (existing code)
    response = build_embed_response(final_output)
    # Emit engine_cost via gRPC trailing metadata
    context.set_trailing_metadata((
        ("engine-forward-ms", f"{engine_forward_ms:.3f}"),
    ))
    return response
```

### Chat_stream (streaming RPC; `chat.py` chat_stream path)

```python
import time
# Pseudocode
async def serve_chat_stream(request, context):
    request_id = ...
    sampling_params = ...
    prompt = build_chat_prompt(request)
    start = time.perf_counter()
    first_token_at: Optional[float] = None
    last_token_at: Optional[float] = None
    token_count = 0
    async for output in self._engine.generate(prompt, sampling_params, request_id):
        if first_token_at is None and output.outputs[0].text:
            first_token_at = time.perf_counter()
        # Yield chunks to client (existing code)
        chunk = build_chat_chunk(output)
        yield chunk
        if output.outputs[0].text:
            last_token_at = time.perf_counter()
            token_count = len(output.outputs[0].token_ids)
    end = time.perf_counter()

    engine_ttft_ms = (first_token_at - start) * 1000.0 if first_token_at else 0.0
    if token_count > 1 and last_token_at:
        engine_tpot_ms = ((last_token_at - first_token_at) * 1000.0) / max(token_count - 1, 1)
    else:
        engine_tpot_ms = 0.0
    # Emit engine_cost on the FINAL stream chunk's trailing metadata
    context.set_trailing_metadata((
        ("engine-ttft-ms", f"{engine_ttft_ms:.3f}"),
        ("engine-tpot-ms", f"{engine_tpot_ms:.3f}"),
    ))
```

### Trailing metadata key naming convention

| Path | Key | Type (on wire) | Format |
|---|---|---|---|
| embed | `engine-forward-ms` | string | f"{value:.3f}" |
| chat_stream | `engine-ttft-ms` | string | f"{value:.3f}" |
| chat_stream | `engine-tpot-ms` | string | f"{value:.3f}" |

**Notes**:
- gRPC metadata keys MUST be lowercase ASCII (gRPC spec).
- Values are floats encoded as strings to 3-decimal precision (microsecond resolution).
- Keys are emitted on the **trailing** metadata (after the final response message), not the initial metadata (which would force the value to be known at request-receive time).
- For chat_stream, trailing metadata is emitted on stream completion regardless of whether `max_tokens` was hit or EOS was reached.

---

## 2. REST shim wire format

### Where it lives

`tools/benchmark/src/vllm_grpc_bench/rest_shim.py` — the FastAPI shim that exposes OpenAI-compatible REST endpoints in front of the gRPC frontend.

### Embed (unary; `POST /v1/embeddings`)

```json
{
  "object": "list",
  "data": [
    { "object": "embedding", "index": 0, "embedding": [...] }
  ],
  "model": "Qwen/Qwen3-7B",
  "usage": { "prompt_tokens": 8, "total_tokens": 8 },
  "engine_cost": {
    "engine_forward_ms": 12.345
  }
}
```

The `engine_cost` field is added at the top level of the JSON response, alongside the existing OpenAI-compatible fields. The `X-Shim-Overhead-Ms` HTTP header (existing M5.x convention) is preserved unchanged.

### Chat_stream (streaming SSE; `POST /v1/chat/completions` with `stream=true`)

The SSE event stream emits incremental `data:` events with chunks (existing OpenAI SSE shape). The terminal event (the one immediately before `data: [DONE]`) carries the engine_cost payload:

```text
data: {"id":"...","choices":[{"delta":{"content":"<token>"},"index":0}]}

data: {"id":"...","choices":[{"delta":{"content":"<token>"},"index":0}]}

...

data: {"id":"...","choices":[{"delta":{},"index":0,"finish_reason":"length"}],"engine_cost":{"engine_ttft_ms":234.567,"engine_tpot_ms":41.234}}

data: [DONE]
```

The `engine_cost` field is added at the top level of the **final** SSE event's data payload (the one with `finish_reason` set). Per-token chunks remain unchanged.

### REST cohort field naming

The JSON field names match the gRPC trailing metadata keys with underscores (Python convention) instead of hyphens (gRPC convention):

| Path | gRPC trailing meta key | REST JSON field | Type (in JSON) |
|---|---|---|---|
| embed | `engine-forward-ms` | `engine_cost.engine_forward_ms` | float |
| chat_stream | `engine-ttft-ms` | `engine_cost.engine_ttft_ms` | float |
| chat_stream | `engine-tpot-ms` | `engine_cost.engine_tpot_ms` | float |

---

## 3. Harness-side parser (consumes both transports)

### Where it lives

`tools/benchmark/src/vllm_grpc_bench/m6_engine_cost.py` — new module with parser functions for both transport routes.

```python
# Pseudocode
def parse_grpc_trailing_metadata(metadata: Sequence[Tuple[str, str]], path: Literal["embed", "chat_stream"]) -> Optional[EngineCostSpan]:
    """Read engine_cost values from gRPC trailing metadata.
    Returns None if any required key is missing (treated as RPC failure for engine_cost purposes;
    the parent RPC may still have succeeded transport-wise — flag as instrumentation gap)."""
    md = dict(metadata)
    try:
        if path == "embed":
            return EngineCostSpan(engine_forward_ms=float(md["engine-forward-ms"]),
                                  engine_ttft_ms=None, engine_tpot_ms=None)
        else:  # chat_stream
            return EngineCostSpan(engine_forward_ms=None,
                                  engine_ttft_ms=float(md["engine-ttft-ms"]),
                                  engine_tpot_ms=float(md["engine-tpot-ms"]))
    except (KeyError, ValueError):
        return None

def parse_rest_response(response_json: dict, path: Literal["embed", "chat_stream"]) -> Optional[EngineCostSpan]:
    """Read engine_cost values from REST JSON payload (top-level engine_cost object).
    For chat_stream, response_json is the FINAL SSE event's data payload."""
    ec = response_json.get("engine_cost")
    if ec is None:
        return None
    try:
        if path == "embed":
            return EngineCostSpan(engine_forward_ms=float(ec["engine_forward_ms"]),
                                  engine_ttft_ms=None, engine_tpot_ms=None)
        else:
            return EngineCostSpan(engine_forward_ms=None,
                                  engine_ttft_ms=float(ec["engine_ttft_ms"]),
                                  engine_tpot_ms=float(ec["engine_tpot_ms"]))
    except (KeyError, ValueError):
        return None
```

### Caller integration

| Cohort | Parser invocation site |
|---|---|
| `default_grpc`, `tuned_grpc_multiplexed` | `m5_1_grpc_cohort.py` after `await response_with_call()` — read `call.trailing_metadata()` and pass to `parse_grpc_trailing_metadata()`. |
| `rest_https_edge` | `rest_cohort.py` after the HTTP response (or after final SSE event for chat_stream) — pass JSON body to `parse_rest_response()`. |

---

## 4. Engine-cost drift warning (FR-014 sub-clause)

### Computation

```python
def compute_drift_warning(per_cohort_engine_cost_mean_ms: Dict[M6CohortKind, float]) -> bool:
    """Return True iff any pair of cohorts disagrees by more than 10%.
    Per FR-014 sub-clause: the comparison is pairwise, threshold 10% of the smaller value."""
    means = list(per_cohort_engine_cost_mean_ms.values())
    if len(means) < 2:
        return False
    for i in range(len(means)):
        for j in range(i + 1, len(means)):
            a, b = means[i], means[j]
            if min(a, b) <= 0:
                continue  # avoid division-by-zero; degenerate case
            if abs(a - b) / min(a, b) > 0.10:
                return True
    return False
```

### Effect on classification

The warning **does NOT promote a cell to `cell_incomplete`** — the cell still gets a verdict per FR-014's discrimination rule. The warning is published in the JSON `M6CellRecord.engine_cost_drift_warning: bool` and surfaced in the markdown report's verdict table (e.g., a `⚠ engine drift` annotation in the relevant row).

When the warning is True, the per-cohort engine_cost values MUST be surfaced in the JSON (`per_cohort_engine_cost_mean_ms` field) and in the markdown report (footnote under the verdict row) so the operator can investigate.

---

## 5. Failure modes and observability

| Failure mode | Symptom in M6 | Action |
|---|---|---|
| gRPC trailing metadata key missing | `parse_grpc_trailing_metadata()` returns None for an RPC | Treat as RPC failure for engine_cost purposes; if cohort's engine_cost mean cannot be computed (all RPCs missing engine_cost), classify cell as `cell_incomplete` regardless of n_successes (since FR-014's classifier needs engine_cost). Alternative: log warning and skip drift check for that cohort. (Decision deferred to /tasks if it materialises.) |
| REST JSON `engine_cost` field missing | Same | Same |
| gRPC trailing metadata key value not parseable as float | Same | Same |
| One cohort emits engine_cost in different units than another (e.g., gRPC frontend updated, REST shim stale) | `engine_cost_drift_warning` flag fires | Operator investigates; per-cohort values surfaced |
| Engine forward pass returns 0 ms (degenerate case) | `engine_cost_mean_ms == 0` | Drift check skips division-by-zero (see code above); verdict still computed |
