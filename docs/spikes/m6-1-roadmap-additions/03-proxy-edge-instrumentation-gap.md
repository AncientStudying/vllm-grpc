# Spike #4 — Proxy-edge instrumentation gap (M6.1.3 scoping note)

**Branch**: `spike/m6-1-roadmap-additions`
**Date**: 2026-05-17
**Status**: ✅ Read-only investigation complete. Implementation deferred to **M6.1.3**.

## Recap of the gap

M6.1.1's Phase 1 re-run left c=4 and c=8 chat_stream cells `inconclusive` because a meaningful share of `engine_ttft_ms` spread is unattributed:

| Cell | spread(ttft) | spread(seg_ab) | spread(seg_queue) | spread(seg_prefill) | **unattributed** |
|---|---:|---:|---:|---:|---:|
| chat_stream c=4 | 26.5 ms | 0.17 | ~0 | 9.4 | **~17 ms (64%)** |
| chat_stream c=8 | 13.3 ms | 0.16 | ~0 | 8.3 | **~5 ms (37%)** |

The gap lives between the frontend's `time.perf_counter_ns()` checkpoints and vLLM's `RequestStateStats` engine-core timestamps — specifically:

- **Ingress gap**: `pre_engine_ns` (frontend) → `arrival_time` (vLLM frontend)
- **Egress gap**: `first_token_ts` (vLLM engine core) → `first_chunk_ns` (frontend)

These are the asyncio handoff legs between the in-process frontend servicer and the in-process AsyncLLM engine. M6.1.1's instrumentation captures both endpoints but the two clocks they're on (`perf_counter_ns` vs `monotonic`/`wall`) prevent direct subtraction.

## What I confirmed (vLLM source)

`vllm/v1/metrics/stats.py:202-217` and `vllm/v1/engine/__init__.py:149-153`:

| Field | Clock | Source |
|---|---|---|
| `RequestStateStats.arrival_time` | **wall-clock** (`time.time()`) | engine frontend, on request arrival |
| `RequestStateStats.queued_ts` | **monotonic** (`time.monotonic()`) | engine-core event timestamp |
| `RequestStateStats.scheduled_ts` | **monotonic** | engine-core event timestamp |
| `RequestStateStats.first_token_ts` | **monotonic** | engine core, on first token emit |
| `RequestStateStats.last_token_ts` | **monotonic** | engine core, on each token (overwritten) |

`EngineCoreEvent.new_event` docstring (line 138-141) explicitly cautions:

> The timestamp is a monotonic timestamps and is used for by the engine frontend to calculate intervals between engine core events. **These timestamps should not be compared with timestamps from other processes.**

Crucially, the engine runs **in-process** with our frontend servicer (`self._engine.generate(...)` calls a direct in-process AsyncLLM iterator). So `time.monotonic()` is the same clock everywhere in the servicer's process — the cross-process caveat does not apply.

## The two probes that close the gap

| New checkpoint | Where | Bridges |
|---|---|---|
| `m6_1_1_t_pre_engine_wall_ns = time.time_ns()` | alongside existing `pre_engine_ns` capture | wall-clock anchor for comparison against `arrival_time` |
| `m6_1_1_t_first_chunk_mono_ns = time.monotonic_ns()` | alongside existing `first_chunk_ns` capture | monotonic anchor for comparison against `first_token_ts` |

Then on the client extractor side:

```python
seg_ingress_ms = (engine_arrival_ns - pre_engine_wall_ns) * 1e-6  # proxy → engine handoff
seg_egress_ms  = (first_chunk_mono_ns - engine_first_token_ns) * 1e-6  # engine → proxy yield
```

Both should be `≥ 0`; negative values are a sanity-check failure (would indicate a clock-source mismatch on some platform). M6.1.3 should add a wire-format assertion to surface this.

## Code surfaces and edit-size estimate

| File | Edit | Lines |
|---|---|---|
| `packages/frontend/src/vllm_grpc_frontend/chat.py` | 2 new `time.time_ns()` / `time.monotonic_ns()` captures + 2 new trailing-metadata keys; **streaming path only** (`CompleteStream`) — `Complete` is unary and the gap doesn't apply | ~8 |
| `packages/frontend/src/vllm_grpc_frontend/completions.py` | Same as chat — `Complete` and `CompleteStream` both need it (embed uses unary, chat_stream uses streaming) | ~16 |
| `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` | Same probes added to SSE / JSON terminal events | ~10 |
| `tools/benchmark/src/vllm_grpc_bench/m6_1_1_types.py` | Add `pre_engine_wall_ns` / `first_chunk_mono_ns` optional fields to `TimingCheckpoint`; add `seg_ingress_ms` / `seg_egress_ms` optional fields to `PerSegmentDelta` + `PerSegmentAggregate`; extend `SegmentName` Literal | ~25 |
| `tools/benchmark/src/vllm_grpc_bench/m6_1_1_timing.py` | Add the two new keys to the extractor's `_opt_int` map | ~6 |
| `tools/benchmark/src/vllm_grpc_bench/m6_1_1_sweep.py` | Add `seg_ingress` / `seg_egress` to `aggregate_multi_point_timings` | ~15 |
| `tools/benchmark/src/vllm_grpc_bench/m6_1_1_classifier.py` | Extend 5-bucket decision tree to 7-bucket with `proxy_ingress_dominated` / `proxy_egress_dominated` labels; legacy fallback unchanged | ~25 |
| `tools/benchmark/src/vllm_grpc_bench/m6_1_1_reporter.py` | 2 new columns in the multi-point timing table; classification narratives for the two new labels; `classifier_notes` text update | ~20 |
| `tools/benchmark/tests/test_m6_1_1_*.py` | Round-trip tests for the new fields, classifier-boundary tests for the 2 new labels, sanity-check for negative-gap assertion | ~60 |

**Total**: ~185 lines. Roughly the same scope as M6.1.1's M6.1.2-expansion classifier upgrade. Achievable in a single milestone.

## What this won't tell us — flag for M6.1.3 design

The probes **bisect** the gap into ingress + egress, but they don't a priori reveal *what's inside each*. Possible explanations for the unattributed 17 ms at c=4:

1. **Asyncio scheduling under concurrent in-flight requests.** At c=4 the event loop is juggling 4 chat_stream coroutines + the engine's loop; if the loop scheduler isn't fair, ingress and egress get jittered together.
2. **GIL contention** between the frontend's response-formatting Python code (tokenizer encode/decode, gRPC trailer build) and vLLM's engine driver.
3. **gRPC trailer-emit serialization** inside grpcio's C core. The `context.set_trailing_metadata(...)` call schedules but doesn't synchronously send — the actual wire emit happens later.
4. **Network send queueing** inside grpcio's HTTP/2 frame writer (different from the network wire itself).

The probes will tell us *whether* the gap is on the ingress side, the egress side, or split — and that bisection points to which of (1-4) is dominant. M6.1.3 should plan for an **iterate** option: ship the two probes, run a Phase 1 sweep, see where the budget lands. If the egress side carries most of it and we still want to bisect further, add a `m6_1_1_t_trailer_emit_dispatched_ns` checkpoint (right after `context.set_trailing_metadata(...)`) in a follow-up.

## Wire-format compatibility

The two new keys are additive at the gRPC trailing-metadata layer (the same strict-superset pattern M6.1.1's expansion used for the RequestStateStats keys). Pre-M6.1.3 manifests parse cleanly — extractor's `_opt_int` returns 0 for absent keys, `TimingCheckpoint.has_proxy_edge_probes` returns False, classifier falls back to the 5-bucket scheme.

`schema_version` does **not** bump — stays at `m6_1_1.v1`. Additive optional fields per the M6.1.1 expansion precedent.

## Recommended M6.1.3 scope

- **Primary**: Add proxy-edge probes (this finding). Re-run Phase 1 to see whether c=4 / c=8 reduce to an attributed label.
- **Bundled** (per the earlier roadmap proposal): items #5 (`engine_compute_variation` root-cause) + #6 (run-to-run variance) — they share the "re-run Phase 1 with more questions" infrastructure and shouldn't trigger separate Modal-deploy cycles.
- **Out of scope for M6.1.3**: deeper bisection (item from the "what this won't tell us" list above). If the probes show the budget is, e.g., gRPC trailer-emit, that becomes M6.1.4 territory.

## Disposition

- Item #4 marked done at the spike level. No code change on this branch.
- M6.1.3 spec/plan can cite this note for the design decision (clock-alignment via in-process monotonic; two probes; 7-bucket classifier).
