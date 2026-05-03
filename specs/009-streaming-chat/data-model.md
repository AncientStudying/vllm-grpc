# Data Model: Streaming Chat Completions (Phase 5)

**Branch**: `009-streaming-chat` | **Date**: 2026-05-02

---

## Entities

### 1. `ChatStreamChunk` (protobuf message — new)

The atomic unit of a server-streaming gRPC response. One message is emitted per output token.

| Field | Type | Proto tag | Notes |
|-------|------|-----------|-------|
| `delta_content` | `string` | 1 | Incremental text for this token. Empty on the final chunk. |
| `finish_reason` | `string` | 2 | `""` on non-final chunks. `"stop"` or `"length"` on the final chunk. |
| `token_index` | `int32` | 3 | Zero-based position of this token in the output sequence. |

**Validation rules**:
- Exactly one chunk per token. The final chunk has `finish_reason != ""` and `delta_content == ""` (empty delta, non-empty finish reason — matches OpenAI's SSE convention).
- `token_index` is strictly monotonically increasing within a single stream.

**State transitions** (from the producer's perspective):
```
GENERATING → GENERATING → ... → FINAL
  (delta_content="tok", finish_reason="")   (delta_content="", finish_reason="stop")
```

---

### 2. `StreamChunk` (Python dataclass — new, `packages/client`)

The typed Python representation of `ChatStreamChunk` surfaced by `VllmGrpcClient`.

| Field | Type | Notes |
|-------|------|-------|
| `delta_content` | `str` | Incremental text. Empty on final chunk. |
| `finish_reason` | `str \| None` | `None` on non-final; `"stop"` or `"length"` on final. |
| `token_index` | `int` | Zero-based token position. |

**Mapping from proto**: `finish_reason` converts `""` → `None`; all other fields are direct copies.

---

### 3. Extended `RequestResult` (benchmark, `tools/benchmark`)

Extends the existing `RequestResult` dataclass with streaming-specific timing fields.

**New fields** (added alongside existing fields):

| Field | Type | Notes |
|-------|------|-------|
| `ttft_ms` | `float \| None` | Time from request send to first non-empty token received. `None` for non-streaming requests or on error. |
| `tpot_ms` | `float \| None` | Mean inter-token delivery time: `(t_last − t_first) / (token_count − 1)`. `None` if `token_count < 2` or non-streaming. |
| `token_count` | `int \| None` | Number of delta chunks received (excluding the final empty chunk). `None` for non-streaming. |

**Existing fields unchanged**: `sample_id`, `target`, `concurrency`, `latency_ms`, `request_bytes`, `response_bytes`, `proxy_ms`, `success`, `error`.

---

### 4. Extended `RunSummary` (benchmark, `tools/benchmark`)

Extends `RunSummary` with TTFT and TPOT percentile columns.

**New fields**:

| Field | Type | Notes |
|-------|------|-------|
| `ttft_p50_ms` | `float \| None` | P50 TTFT across all successful requests in this group. |
| `ttft_p95_ms` | `float \| None` | P95 TTFT. |
| `ttft_p99_ms` | `float \| None` | P99 TTFT. |
| `tpot_p50_ms` | `float \| None` | P50 TPOT. |
| `tpot_p95_ms` | `float \| None` | P95 TPOT. |
| `tpot_p99_ms` | `float \| None` | P99 TPOT. |

**Existing fields unchanged**.

`None` for all TTFT/TPOT fields when the target group contains no streaming results (e.g., non-streaming baseline runs).

---

### 5. `RunMeta` (benchmark — unchanged)

No changes to `RunMeta`. Streaming vs. non-streaming is implied by which `RunSummary` fields are populated.

---

## Entity Relationships

```
ChatCompleteRequest  ──(gRPC server-streaming)──▶  ChatStreamChunk (0..N)
                                                        │
                                           vllm_grpc_client
                                                        │
                                                   StreamChunk  (Python, 1:1 mapping)

RequestResult  (has 0..1 ttft_ms, tpot_ms, token_count)
     │
RunSummary  (aggregates N RequestResults → percentile fields)
```

---

## Proto Schema Delta

The updated `chat.proto` adds one message and one RPC to the existing `ChatService`:

```protobuf
// NEW — one per output token in a streaming response
message ChatStreamChunk {
  string delta_content = 1;
  string finish_reason = 2;
  int32  token_index   = 3;
}

service ChatService {
  rpc Complete       (ChatCompleteRequest) returns (ChatCompleteResponse);  // existing
  rpc CompleteStream (ChatCompleteRequest) returns (stream ChatStreamChunk); // NEW
}
```

The full updated proto is the authoritative source in `contracts/chat-proto.md`.
