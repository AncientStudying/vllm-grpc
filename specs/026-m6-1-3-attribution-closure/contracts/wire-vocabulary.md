# Contract: M6.1.3 Wire Vocabulary Extension

**Branch**: `026-m6-1-3-attribution-closure` | **Phase 1 output** | **Plan**: [../plan.md](../plan.md)

## Purpose

M6.1.3 adds 4 new wire keys to the M6.1.1-rooted vocabulary: 2 proxy-edge probe checkpoints (`m6_1_1_*` prefix; extends M6.1.1's existing key family) and 2 per-cohort prompt-content audit fields (`m6_1_3_*` prefix; new instrumentation category). Both prefix families are emitted via gRPC trailing metadata (gRPC cohorts) or REST SSE / JSON terminal event (REST cohorts). Per FR-010 + round-3 Q1, **`schema_version` stays at `"m6_1_1.v1"` for both prefix families** — the prefix distinguishes naming categories within an extensible vocabulary; it is not a versioning signal.

## Wire keys

### Proxy-edge probes (FR-001 + FR-002, `m6_1_1_*` prefix)

| Key | Type | Source | Streaming-only? | Notes |
|-----|------|--------|-----------------|-------|
| `m6_1_1_t_pre_engine_wall_ns` | `int` (nanoseconds since epoch, `time.time_ns()`) | Frontend servicer (`packages/frontend/src/vllm_grpc_frontend/chat.py:CompleteStream` + `completions.py:CompleteStream`) | YES (FR-003) | Wall-clock anchor for comparison against vLLM's `RequestStateStats.arrival_time` (which uses `time.time()`). Captured alongside the existing `m6_1_1_t_pre_engine_ns` (perf_counter-based) capture site. |
| `m6_1_1_t_first_chunk_mono_ns` | `int` (nanoseconds, `time.monotonic_ns()`) | Same servicers + RPC handlers | YES (FR-003) | Monotonic anchor for comparison against vLLM's `RequestStateStats.first_token_ts` (which uses `time.monotonic()`). Captured alongside the existing `m6_1_1_t_first_chunk_ns` (perf_counter-based) capture site. |

**Streaming-only constraint** (FR-003 + AS 1.7): both proxy-edge keys are emitted ONLY on `CompleteStream` handlers. The unary `Complete` path in `completions.py` does NOT emit these keys because the ingress / egress gap is a streaming-only phenomenon — there is no first-chunk-vs-engine-emit delta to bisect on a unary RPC. The extractor (`m6_1_1_timing.py`) treats absent fields as `None` and does NOT fire the FR-006 negative-value assertion for unary rows.

### Prompt-content audit (FR-012 + FR-013, `m6_1_3_*` prefix)

| Key | Type | Source | Both streaming + unary? | Notes |
|-----|------|--------|-------------------------|-------|
| `m6_1_3_tokenized_prompt_length` | `int` (count of token ids fed into prefill) | Frontend servicer (all RPCs per FR-014) | YES | Captured after `messages_to_prompt` / `apply_chat_template` for chat_stream; post-tokenization for embed. The exact count of token ids the engine will see at prefill. |
| `m6_1_3_tokenized_prompt_hash` | `str` (16-char hex; BLAKE2b digest_size=8) | Frontend servicer (all RPCs per FR-014) | YES | `blake2b(b"".join(t.to_bytes(4, 'little') for t in token_ids), digest_size=8).hex()` — fixed-width hex encoding of the BLAKE2b-8 hash of the serialized token id list. Per R-4, collision probability at 6000 hashes per multi-run sweep is ≈ 10⁻¹². |

**Both-RPC-kinds constraint** (FR-014): the audit keys are emitted on EVERY RPC (chat_stream's `CompleteStream` AND embed's `Complete` unary path) because the H1 prompt-content drift hypothesis applies regardless of streaming. The unary `Complete` path in `completions.py` emits the audit keys but NOT the proxy-edge keys.

## Wire emission mechanisms

### gRPC cohorts (`default_grpc`, `tuned_grpc_multiplexed`)

Trailing metadata via `context.set_trailing_metadata([(key, value), ...])` at the end of the handler. All values are converted to strings per gRPC's trailing-metadata semantics:

```python
# Inside packages/frontend/src/vllm_grpc_frontend/chat.py:CompleteStream
import time
import hashlib

# At existing pre_engine_ns capture site:
m6_1_1_t_pre_engine_wall_ns = time.time_ns()  # FR-001 wall-clock anchor

# At existing first_chunk_ns capture site (after engine yields first chunk):
m6_1_1_t_first_chunk_mono_ns = time.monotonic_ns()  # FR-001 monotonic anchor

# Post-messages_to_prompt / apply_chat_template (after token_ids is resolved):
token_id_bytes = b"".join(t.to_bytes(4, 'little') for t in token_ids)
m6_1_3_tokenized_prompt_length = len(token_ids)
m6_1_3_tokenized_prompt_hash = hashlib.blake2b(token_id_bytes, digest_size=8).hexdigest()

# At end of handler (alongside existing trailing metadata):
context.set_trailing_metadata([
    # ... existing M6.1.1 trailing-metadata keys ...
    ("m6_1_1_t_pre_engine_wall_ns", str(m6_1_1_t_pre_engine_wall_ns)),
    ("m6_1_1_t_first_chunk_mono_ns", str(m6_1_1_t_first_chunk_mono_ns)),
    ("m6_1_3_tokenized_prompt_length", str(m6_1_3_tokenized_prompt_length)),
    ("m6_1_3_tokenized_prompt_hash", m6_1_3_tokenized_prompt_hash),
])
```

### REST cohorts (`rest_https_edge`, `rest_plain_tcp`)

SSE terminal event (or JSON terminal-event object for non-SSE REST endpoints) carries the keys as flat top-level fields:

```jsonc
// Terminal SSE event (the final `data: { ... }` chunk in the stream)
{
  "event": "completion_done",
  "m6_1_1_t_pre_engine_wall_ns": "1747512345678901234",
  "m6_1_1_t_first_chunk_mono_ns": "9876543210987654321",
  "m6_1_3_tokenized_prompt_length": "47",
  "m6_1_3_tokenized_prompt_hash": "a1b2c3d4e5f60718",
  // ... existing M6.1.1 terminal-event keys ...
}
```

The `rest_shim.py` terminal-event handler reads these keys and populates the same `TimingCheckpoint` optional fields as the gRPC extractor.

## Extractor mapping (in `m6_1_1_timing.py`)

The existing M6.1.1 extractor is extended with 4 new optional reads via the established `_opt_int` / `_opt_str` patterns:

```python
# In tools/benchmark/src/vllm_grpc_bench/m6_1_1_timing.py:
def extract_timing_checkpoint(trailing_metadata: dict[str, str]) -> TimingCheckpoint:
    return TimingCheckpoint(
        # ... existing M6.1.1 fields ...
        # NEW M6.1.3 fields (additive optional):
        pre_engine_wall_ns=_opt_int(trailing_metadata, "m6_1_1_t_pre_engine_wall_ns"),
        first_chunk_mono_ns=_opt_int(trailing_metadata, "m6_1_1_t_first_chunk_mono_ns"),
        tokenized_prompt_length=_opt_int(trailing_metadata, "m6_1_3_tokenized_prompt_length"),
        tokenized_prompt_hash=_opt_str(trailing_metadata, "m6_1_3_tokenized_prompt_hash"),
    )
```

`_opt_int` returns `None` (or the existing convention's sentinel) when the key is absent, preserving the M6.1.1 wire-compatibility precedent. Pre-M6.1.3 manifests rehydrated by the M6.1.3 reader produce `TimingCheckpoint` instances with the new fields as `None`; `has_proxy_edge_probes` (a new computed property) returns `False`; the classifier's legacy fallback emits a 5-bucket label per FR-010.

## Derived segments (computed from the wire keys)

The per-RPC aggregator (in `m6_1_3_classifier.py` per R-3 + R-10) derives two new segments per FR-005:

```python
def compute_proxy_edge_segments(
    checkpoint: TimingCheckpoint,
    request_state_stats: RequestStateStats,
) -> M6_1_3PerSegmentDeltaExtension:
    """Per FR-005 + FR-006 + R-3."""
    seg_ingress_ms = None
    seg_egress_ms = None
    is_clock_anomaly = False

    if checkpoint.pre_engine_wall_ns is not None and request_state_stats.arrival_time is not None:
        # vLLM's arrival_time is time.time() in seconds; convert to ns for the subtraction
        engine_arrival_ns = int(request_state_stats.arrival_time * 1e9)
        seg_ingress_ms = (engine_arrival_ns - checkpoint.pre_engine_wall_ns) * 1e-6
        if seg_ingress_ms < 0:
            # FR-006 negative-value assertion fires
            log_clock_anomaly(checkpoint, "seg_ingress_ms", seg_ingress_ms)
            is_clock_anomaly = True
            seg_ingress_ms = None  # Excluded from aggregation

    if checkpoint.first_chunk_mono_ns is not None and request_state_stats.first_token_ts is not None:
        # vLLM's first_token_ts is time.monotonic() in seconds; convert to ns
        engine_first_token_ns = int(request_state_stats.first_token_ts * 1e9)
        seg_egress_ms = (checkpoint.first_chunk_mono_ns - engine_first_token_ns) * 1e-6
        if seg_egress_ms < 0:
            log_clock_anomaly(checkpoint, "seg_egress_ms", seg_egress_ms)
            is_clock_anomaly = True
            seg_egress_ms = None

    return M6_1_3PerSegmentDeltaExtension(
        seg_ingress_ms=seg_ingress_ms,
        seg_egress_ms=seg_egress_ms,
        is_clock_anomaly=is_clock_anomaly,
    )
```

## Additive-strict-superset versioning convention (FR-010 + round-3 Q1)

**Both** wire prefix families (`m6_1_1_*` for proxy-edge probes AND `m6_1_3_*` for audit keys) leave `schema_version` at `"m6_1_1.v1"`. The prefix is a **naming** convention distinguishing instrumentation categories within an extensible vocabulary; it is **not** a versioning signal.

The convention binds future milestones:
- M6.2 adds a `max_tokens` axis (per PLAN.md M6.2). If M6.2 introduces new wire keys (e.g., `m6_2_*` prefix for token-budget instrumentation), `schema_version` stays at `"m6_1_1.v1"` and consumers detect M6.2 instrumentation via key-presence inspection — NOT via a version bump.
- M7 adds corpus diversity. Same rule: new optional keys; same schema_version.
- M8 adds multi-model. Same rule.

The only legitimate reason to bump `schema_version` is a **wire-breaking change** — e.g., a key's value type changes from `int` to `str`, or an existing key is removed. M6.1.3 does neither.

## Wire-format compatibility

| Reader vintage | Reads M6.1.1 manifests? | Reads M6.1.2 manifests? | Reads M6.1.3 manifests? | Notes |
|---|---|---|---|---|
| M6.1.1 reader (pre-M6.1.2) | YES (native) | YES (ignores `network_paths`, `cohort_set`, `cohort_omissions` per M6.1.2 strict-superset) | YES (ignores M6.1.3 additions PLUS M6.1.2 additions; new wire keys parsed as absent → `None`; new derived segments stay at default `None`; classifier falls back to 5-bucket) | Strict-superset cleanly evolves through M6.1.2 → M6.1.3 |
| M6.1.2 reader (pre-M6.1.3) | YES (M6.1.2 inherits M6.1.1 schema) | YES (native) | YES (ignores `between_run_variance` + new audit fields + new derived segments; new classifier labels parsed as unknown enum values → handled per existing M6.1.1 / M6.1.2 fallback) | Strict-superset per FR-010 + round-3 Q1 |
| M6.1.3 reader (this milestone) | YES (with `has_proxy_edge_probes=False`, classifier falls back to 5-bucket) | YES (with all M6.1.3 features off; classifier still 5-bucket) | YES (native; full 7-bucket + compound + outer override) | Forward-compatible with future M6.2 / M7 / M8 via the same convention |

The integration test `test_m6_1_3_proxy_edge_probes.py` exercises the cross-vintage compatibility:

```python
def test_m6_1_3_artifact_parses_with_m6_1_1_reader() -> None:
    """FR-010 + SC-008: an M6.1.1-vintage reader parses an M6.1.3 artifact
    without error, ignoring the new top-level keys and the new per-cell
    segment columns and the new classifier labels."""
    m6_1_3_artifact = synthesize_artifact_with_proxy_edge_probes_and_audit_and_variance()
    from vllm_grpc_bench.m6_1_1_reporter import parse_json  # M6.1.1's reader
    result = parse_json(m6_1_3_artifact)  # Must not raise
    assert "between_run_variance" not in result.__dict__  # M6.1.1 reader doesn't know the field
    assert result.schema_version == "m6_1_1.v1"  # Unchanged per FR-010
```

## Cross-references

- Plan: [`../plan.md`](../plan.md) — Technical Context.
- Data model: [`../data-model.md`](../data-model.md) — `M6_1_3TimingCheckpointExtension`, `M6_1_3PerSegmentDeltaExtension`, `M6_1_3PerSegmentAggregateExtension`.
- CLI contract: [`./cli.md`](./cli.md).
- Classifier contract: [`./classifier.md`](./classifier.md) — how the new keys feed the 7-bucket decision tree.
- Artifact-schema contract: [`./artifact-schema.md`](./artifact-schema.md) — how the new keys land in the published artifact JSON.
- Spec: [`../spec.md`](../spec.md) — FR-001 / FR-002 / FR-003 / FR-004 / FR-005 / FR-006 / FR-007 / FR-010 / FR-011 / FR-012 / FR-013 / FR-014 / FR-015 + round-3 Q1.
- Spike #4 reference: [`docs/spikes/m6-1-roadmap-additions/03-proxy-edge-instrumentation-gap.md`](../../../docs/spikes/m6-1-roadmap-additions/03-proxy-edge-instrumentation-gap.md) — feasibility evidence + code-surface enumeration.
- Spike #5 reference: [`docs/spikes/m6-1-roadmap-additions/04-engine-compute-variation-rootcause.md`](../../../docs/spikes/m6-1-roadmap-additions/04-engine-compute-variation-rootcause.md) — audit-field hypothesis space.
- vLLM source: `vllm/v1/engine/__init__.py:149-153`, `vllm/v1/metrics/stats.py:202-217`.
