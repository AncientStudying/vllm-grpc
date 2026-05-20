# Contract: M6.2 Wire Vocabulary

**Branch**: `027-m6-2-token-budget` | **Phase 1 output** | **Plan**: [../plan.md](../plan.md)

## Scope statement

**M6.2 adds ZERO new wire vocabulary.** The gRPC trailing-metadata key set and REST SSE / JSON terminal-event field set carry forward from M6.1.3 unchanged. M6.2 makes NO `.proto` edits, NO new trailing-metadata keys, NO new terminal-event fields.

All M6.2 schema additions are **artifact-JSON-level only**, captured in [`artifact-schema.md`](./artifact-schema.md):
- Four new top-level artifact keys: `null_anchor_validation`, `max_tokens_axis`, `protocol_crossover`, `kv_pressure_observation`, `anchor_latency_trajectory`, `failure_summary`, `integrity_warnings`.
- Four new per-row fields: `max_tokens`, `block_start_utc`, `block_end_utc`, `retry_attempted`.
- Eight new `run_meta` fields: `iteration_order`, `iteration_discipline_verified`, `n_per_point`, `validate_axis_subset`, `wall_clock_start_utc`, `wall_clock_end_utc`, `total_sweep_hours`, `modal_spend_usd_estimate`.

The artifact `schema_version` stays at `"m6_1_1.v1"` per FR-011. Pre-M6.2 readers ignore unknown keys cleanly per the M6.1.x strict-superset convention.

## Inherited wire vocabulary

The authoritative M6.1.x wire vocabulary lives in [`../../026-m6-1-3-attribution-closure/contracts/wire-vocabulary.md`](../../026-m6-1-3-attribution-closure/contracts/wire-vocabulary.md) (M6.1.3's contract document) — M6.2 reuses it unchanged. For convenience, the key categories inherited unchanged are:

### gRPC trailing metadata (extended by M6.1.1 / M6.1.2 / M6.1.3 over the M6.0a base)

- **M6.1.1 timing keys** (`m6_1_1_t_*`): per-RPC timing checkpoints emitted by the frontend servicer in `chat.py` + `completions.py`. Includes the M6.1.3-added `m6_1_1_t_pre_engine_wall_ns` (wall-clock anchor) and `m6_1_1_t_first_chunk_mono_ns` (monotonic anchor) per M6.1.3 FR-001 / FR-002 / FR-003.
- **M6.1.3 audit keys** (`m6_1_3_*`): per-RPC `tokenized_prompt_length` and `tokenized_prompt_hash` (BLAKE2b-8) emitted by the frontend servicer per M6.1.3 FR-012 / FR-013 / FR-014.
- **vLLM engine timing keys**: `RequestStateStats.arrival_time` / `first_token_ts` exposed via the engine's `EngineCoreEvent` mechanism, captured in-process by the frontend servicer.

### REST SSE / JSON terminal-event fields

The REST shim (`rest_shim.py`) reads the corresponding keys from the SSE / JSON terminal-event object (terminal_event["m6_1_1_t_*"] and terminal_event["m6_1_3_*"]) for the `rest_plain_tcp` and `rest_https_edge` cohorts. M6.1.3 added these REST-side reads; M6.2 inherits unchanged.

## Why M6.2 doesn't extend wire vocabulary

M6.2's new measurements (per-block wall-clock timing across the `max_tokens` axis, anchor latency trajectory, protocol crossover threshold, KV-pressure inference) are ALL derived from the existing wire-key set:

- **`wall_p50_ms` / `wall_p95_ms` / `wall_p99_ms`** per (cell, cohort, max_tokens) → aggregated from existing per-RPC timing rows extracted via `m6_1_1_timing.extract_per_rpc_timing(...)`.
- **5-segment engine-cost decomposition** per (cell, cohort, max_tokens) → computed from M6.1.3's existing `m6_1_1_t_pre_engine_wall_ns` / `m6_1_1_t_first_chunk_mono_ns` / engine timestamps. The segments don't change shape with `max_tokens`; their relative shares evolve but the extractor is unmodified.
- **TPOT** per (chat_stream cell, cohort, max_tokens) → computed from existing per-RPC token-arrival timestamps.
- **Wall-clock-ratio inference** for KV-pressure → computed from existing latency budget measurements at `c=8 × {1024, 2048}`. No engine-side instrumentation required (FR-017a).
- **Symmetric mean-in-CI crossover** → computed from existing `wall_p50_ms ± CI_half_width` per cohort × per `max_tokens`. No wire-level addition.
- **Anchor latency trajectory** → computed from a sequence of standard `chat_stream c=1 × max_tokens=10` blocks at 4h cadence. No new wire keys.
- **Block-level UTC timestamps** → captured by the orchestrator using `datetime.now(UTC).isoformat()`, NOT by the wire format. The timestamps are stored on the artifact row, not transmitted via gRPC trailing metadata.

### Best-effort engine field

The single best-effort wire-key consumption M6.2 introduces is `engine_kv_cache_used_fraction` — an existing vLLM engine field that MAY be exposed via gRPC trailing metadata (the exact mechanism depends on whether vLLM exposes it; the spec is best-effort per FR-017). The wire-key extraction MUST gracefully degrade when the field is absent:

```python
def extract_kv_cache_used_fraction_peak(per_rpc_metadata: dict) -> float | None:
    """Best-effort extraction of vLLM's engine_kv_cache_used_fraction.
    Returns None if the engine doesn't expose the field — the regime is still
    characterized via FR-017a's wall-clock-ratio inference."""
    return per_rpc_metadata.get("engine_kv_cache_used_fraction")
```

The wall-clock-ratio inference (FR-017a) does NOT depend on this engine field — it's computed entirely from existing latency budget measurements per the [`artifact-schema.md`](./artifact-schema.md) KV-pressure section. The engine field, if present, cross-validates the inference; the narrative cites both signals.

## Constitution alignment

This contract is the load-bearing evidence for the Constitution Principle I ("Proto-First") and Principle II ("Library Dependency, Not Fork") PASS verdicts in [`../plan.md`](../plan.md)'s Constitution Check:

- **Principle I (Proto-First)**: M6.2 makes ZERO `.proto` edits because it adds ZERO new wire keys. The artifact-JSON-level additions are not proto-tracked. Confirmed.
- **Principle II (Library Dependency, Not Fork)**: M6.2 modifies NO frontend / proxy / engine code because it adds ZERO new wire keys. The M6.1.3 in-process clock-alignment + audit-key emission already covers everything M6.2 needs. Confirmed.

## Forward-compatibility

If a future milestone (e.g., M6.2.1) needs to introduce a new wire key (e.g., for the asymmetric-prompts diagnostic forward-referenced in FR-008), it MUST follow the M6.1.x precedent: gRPC trailing metadata (string-keyed; no proto schema change) + REST SSE / JSON terminal-event field. The `schema_version` MAY bump (per the M6.1.x convention) OR stay at `"m6_1_1.v1"` if the new key is strictly additive. The M6.2 reader code (in `m6_1_1_timing.extract_per_rpc_timing(...)` and `rest_shim.py`) uses `dict.get(key, None)` patterns for optional wire keys, so forward-introduced keys won't break M6.2-vintage readers.

## Test enforcement

Wire-vocabulary inheritance is implicitly tested by:

- `test_m6_2_artifact_schema.py::test_strict_superset_compat_with_m6_1_3` — synthesizes an M6.2 artifact and parses with M6.1.3-vintage reader; no parse error.
- `test_m6_2_validate_cli.py` + `test_m6_2_publish_cli.py` — integration tests that exercise the full extractor chain against the stub RPC driver; if M6.2 accidentally introduced a new wire-key dependency, these would fail at the extractor layer.
- `test_m6_2_kv_pressure.py::test_engine_field_absent_inference_still_fires` — explicit test that the wall-clock-ratio inference works without the best-effort `engine_kv_cache_used_fraction` key.

No dedicated wire-vocabulary test file exists for M6.2 because there's no wire-vocabulary delta to test. The M6.1.3 wire-vocabulary tests (`test_m6_1_3_proxy_edge_probes.py`, `test_m6_1_3_audit.py`) continue to enforce the inherited vocabulary unchanged.
