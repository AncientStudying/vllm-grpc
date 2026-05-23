# Contract: M6.2 Wire Vocabulary

**Branch**: `027-m6-2-token-budget` | **Phase 1 output** | **Plan**: [../plan.md](../plan.md)

## Scope statement

**M6.2 adds exactly ONE additive proto field** — `bool ignore_eos` on `ChatCompleteRequest` (field 7) and `CompletionRequest` (field 8) — required by the FR-036 KV-pressure sub-probe so it can force the engine to generate to the `max_tokens` cap regardless of natural EOS. The gRPC trailing-metadata key set and REST SSE / JSON terminal-event field set carry forward from M6.1.3 unchanged: NO new trailing-metadata keys, NO new terminal-event fields.

Round-5 amendment (post-T002 investigation): the prior draft of this contract claimed "ZERO new wire vocabulary." That was authored against the round-4 sub-probe design which assumed `ignore_eos` could be set client-side without a request-payload field. Round-5 clarify Q3-Q5 introduced the sub-probe's forced-cap regime (`ignore_eos=True`) which requires the field on the request wire — T002 confirmed the field was absent, T003 added it to both proto messages + regenerated stubs, T003a wired the frontend translation (`packages/frontend/src/vllm_grpc_frontend/chat_translate.py` + `completions_translate.py` read `req.ignore_eos` and pass it to `SamplingParams(ignore_eos=...)`). The plan's Constitution I narrative was updated accordingly.

All other M6.2 schema additions are **artifact-JSON-level only**, captured in [`artifact-schema.md`](./artifact-schema.md):
- Seven new top-level artifact keys: `null_anchor_validation`, `max_tokens_axis`, `protocol_crossover`, `kv_pressure_observation`, `anchor_latency_trajectory`, `failure_summary`, `integrity_warnings`.
- Seven new per-row fields: `max_tokens`, `block_start_utc`, `block_end_utc`, `retry_attempted`, `prompt_source`, `measurement_regime`, `prompt_corpus_idx`.
- Ten-plus new `run_meta` fields: `iteration_order`, `iteration_discipline_verified`, `n_per_point`, `validate_axis_subset`, `wall_clock_start_utc`, `wall_clock_end_utc`, `total_sweep_hours`, `modal_spend_usd_estimate`, `chat_corpus_sha256`, `chat_corpus_path`, `embed_corpus_sha256`, `embed_corpus_path`, `sub_probe_ran`.

The artifact `schema_version` stays at `"m6_1_1.v1"` per FR-011 — the artifact-JSON additions are strict-superset. Pre-M6.2 readers ignore the new artifact-JSON keys cleanly; the new proto field is a default-false bool, so a pre-M6.2 client talking to a post-M6.2 server omits it and the server reads the proto3 default (`False`), preserving M6.1.x behavior.

## New wire field (M6.2 additive)

### `ignore_eos` (proto request field)

```proto
// proto/vllm_grpc/v1/chat.proto
message ChatCompleteRequest {
  // ... fields 1-6 unchanged ...
  bool ignore_eos = 7;
}

// proto/vllm_grpc/v1/completions.proto
message CompletionRequest {
  // ... fields 1-7 unchanged (1-5 scalars; 6/7 oneof input) ...
  bool ignore_eos = 8;
}
```

- **Type**: `bool`. Proto3 default `false` so omitting the field on the wire is M6.1.x-equivalent — Qwen3-8B samples EOS naturally.
- **Semantics**: when `true`, the frontend's translation layer (`chat_translate.proto_to_sampling_params` / `completions_translate.proto_to_sampling_params`) sets `SamplingParams(ignore_eos=True)`, which instructs vLLM's sampler to keep generating until the `max_tokens` cap is reached even if the model would otherwise emit EOS.
- **Who sets it**: only the FR-036 KV-pressure sub-probe blocks (`c=8 × {chat_stream, embed} × {1024, 2048}`, `n=20`). Every other call site — main-sweep budget-table rows, anchor blocks, smoke / warmup RPCs, M6.x reproductions — leaves the field at its proto3 default. The per-row `measurement_regime` field on the artifact distinguishes `"natural_eos"` (every budget-table row) from `"forced_cap_ignore_eos_true"` (sub-probe-only) so the two regimes never get mixed in analysis.
- **Backward compatibility**: M6.1.x clients (which don't know the field exists) speak to an M6.2 server unchanged — proto3 unknown-field handling drops nothing and the server reads the default `false`. M6.2 clients speaking to an M6.1.x server (which doesn't know the field) likewise get default `false` behavior on the server's `SamplingParams.ignore_eos`. The field is strict-superset on both sides.

**Why proto edit, not trailing metadata.** The M6.1.x precedent for new wire data is gRPC trailing metadata (server → client; string-keyed; no schema change). That precedent doesn't apply here because `ignore_eos` is a **request** parameter the client tells the server, not measurement data the server tells the client. Request parameters belong in the proto message; the proto-first discipline (Constitution Principle I) is satisfied by the T002 → T003 → T003a sequencing.

## Inherited wire vocabulary

The authoritative M6.1.x wire vocabulary lives in [`../../026-m6-1-3-attribution-closure/contracts/wire-vocabulary.md`](../../026-m6-1-3-attribution-closure/contracts/wire-vocabulary.md) (M6.1.3's contract document) — M6.2 reuses it unchanged. For convenience, the key categories inherited unchanged are:

### gRPC trailing metadata (extended by M6.1.1 / M6.1.2 / M6.1.3 over the M6.0a base)

- **M6.1.1 timing keys** (`m6_1_1_t_*`): per-RPC timing checkpoints emitted by the frontend servicer in `chat.py` + `completions.py`. Includes the M6.1.3-added `m6_1_1_t_pre_engine_wall_ns` (wall-clock anchor) and `m6_1_1_t_first_chunk_mono_ns` (monotonic anchor) per M6.1.3 FR-001 / FR-002 / FR-003.
- **M6.1.3 audit keys** (`m6_1_3_*`): per-RPC `tokenized_prompt_length` and `tokenized_prompt_hash` (BLAKE2b-8) emitted by the frontend servicer per M6.1.3 FR-012 / FR-013 / FR-014.
- **vLLM engine timing keys**: `RequestStateStats.arrival_time` / `first_token_ts` exposed via the engine's `EngineCoreEvent` mechanism, captured in-process by the frontend servicer.

### REST SSE / JSON terminal-event fields

The REST shim (`rest_shim.py`) reads the corresponding keys from the SSE / JSON terminal-event object (terminal_event["m6_1_1_t_*"] and terminal_event["m6_1_3_*"]) for the `rest_plain_tcp` and `rest_https_edge` cohorts. M6.1.3 added these REST-side reads; M6.2 inherits unchanged.

## Why the rest of M6.2 doesn't extend wire vocabulary

Beyond the single `ignore_eos` request field above, M6.2's new measurements (per-block wall-clock timing across the `max_tokens` axis, anchor latency trajectory, protocol crossover threshold, KV-pressure inference) are ALL derived from the existing wire-key set:

- **`wall_p50_ms` / `wall_p95_ms` / `wall_p99_ms`** per (cell, cohort, max_tokens) → aggregated from existing per-RPC timing rows extracted via `m6_1_1_timing.extract_grpc_timings(...)` / `extract_rest_timings(...)`.
- **5-segment engine-cost decomposition** per (cell, cohort, max_tokens) → computed from M6.1.3's existing `m6_1_1_t_pre_engine_wall_ns` / `m6_1_1_t_first_chunk_mono_ns` / engine timestamps. The segments don't change shape with `max_tokens`; their relative shares evolve but the extractor is unmodified.
- **TPOT** per (chat_stream cell, cohort, max_tokens) → computed from existing per-RPC token-arrival timestamps.
- **Wall-clock-ratio inference** for KV-pressure → computed from sub-probe `wall_p50_ms` values at `c=8 × {1024, 2048}` (FR-017a as amended in round-5). The sub-probe IS the new measurement, and the only wire-level addition the sub-probe needs is the `ignore_eos` field documented above; no trailing-metadata extension.
- **Symmetric mean-in-CI crossover** → computed from existing `wall_p50_ms ± CI_half_width` per cohort × per `max_tokens`. No wire-level addition.
- **Anchor latency trajectory** → computed from a sequence of standard `chat_stream c=1 × max_tokens=10` blocks at 4h cadence. No new wire keys.
- **Block-level UTC timestamps** → captured by the orchestrator using `datetime.now(UTC).isoformat()`, NOT by the wire format. The timestamps are stored on the artifact row, not transmitted via gRPC trailing metadata.
- **`prompt_source` / `measurement_regime` / `prompt_corpus_idx`** → recorded by the orchestrator from its own dispatch decisions in `m6_2_prompt_source.resolve_block_inputs(...)`, NOT read off the wire. Stored on the artifact row only.

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

- **Principle I (Proto-First)**: M6.2 makes ONE additive `.proto` edit (`bool ignore_eos` on `ChatCompleteRequest` and `CompletionRequest`), sequenced as T002 (investigate whether the field exists) → T003 (add the field + `make proto` regenerates stubs) → T003a (frontend translation reads the field into `SamplingParams`) → harness code references the field. Proto-first discipline satisfied: every wire change starts at the `.proto` file before any Python code consumes it. The artifact-JSON-level additions are not proto-tracked.
- **Principle II (Library Dependency, Not Fork)**: M6.2 modifies the frontend translation layer (`chat_translate.py` + `completions_translate.py`, ~5-10 LOC each per T003a) to pass `ignore_eos` through to vLLM's public `SamplingParams` constructor. No engine / proxy / vLLM internals are touched; the change uses vLLM's public API only.

## Forward-compatibility

If a future milestone (e.g., M6.2.1) needs to introduce a new wire key for measurement data (server → client) — e.g., a new server-emitted timing checkpoint, not a new request parameter — it MUST follow the M6.1.x precedent: gRPC trailing metadata (string-keyed; no proto schema change) + REST SSE / JSON terminal-event field. The `schema_version` MAY bump (per the M6.1.x convention) OR stay at `"m6_1_1.v1"` if the new key is strictly additive. The M6.2 reader code (in `m6_1_1_timing.extract_grpc_timings(...)` / `extract_rest_timings(...)` and `rest_shim.py`) uses `dict.get(key, None)` patterns for optional wire keys, so forward-introduced trailing-metadata keys won't break M6.2-vintage readers.

For future **request** parameters (client → server, e.g., the asymmetric-prompts diagnostic forward-referenced in FR-008), the M6.2 `ignore_eos` precedent applies: additive `.proto` field with proto3 default-value semantics, sequenced as investigate → proto edit + stub regen → frontend translation → harness reference. The default-value semantics preserve forward + backward compatibility across mixed-version client/server pairs.

## Test enforcement

The one wire-vocabulary delta (the `ignore_eos` proto field) is exercised by:

- `packages/frontend/tests/test_ignore_eos_translation.py` — round-trip tests on both translators: `ignore_eos=True` on the proto request flows through to `SamplingParams.ignore_eos=True`; default (unset) round-trips to `False`; explicit `False` round-trips to `False`; the field is read correctly when the embed request uses the `prompt_embeds` oneof variant.
- `tools/benchmark/tests/test_m6_2_sub_probe.py::test_dispatcher_called_with_ignore_eos_true_per_block_inputs` — asserts every sub-probe block dispatched through `m6_2_sub_probe.run_kv_pressure_sub_probe(...)` carries `ignore_eos=True` in its `ResolvedBlockInputs`, so the field is actually set on the wire for the FR-036 measurement regime.
- `tools/benchmark/tests/test_m6_2_prompt_source.py::test_sub_probe_uses_corpus_plus_ignore_eos` (chat + embed variants) — asserts `resolve_block_inputs(..., ignore_eos_override=True)` propagates `ignore_eos=True` and the corpus prompt-source labels.

Inherited wire-vocabulary stability is exercised by:

- `test_m6_2_artifact_schema.py::test_strict_superset_compat_with_m6_1_3` — synthesizes an M6.2 artifact and parses with M6.1.3-vintage reader; no parse error.
- `test_m6_2_validate_cli.py` + `test_m6_2_publish_cli.py` — integration tests that exercise the full extractor chain against the stub RPC driver; if M6.2 accidentally introduced a new trailing-metadata key dependency, these would fail at the extractor layer.
- `test_m6_2_kv_pressure.py::test_engine_field_absent_inference_still_fires` — explicit test that the wall-clock-ratio inference works without the best-effort `engine_kv_cache_used_fraction` key.

The M6.1.3 wire-vocabulary tests (`test_m6_1_3_proxy_edge_probes.py`, `test_m6_1_3_audit.py`) continue to enforce the inherited trailing-metadata + REST terminal-event vocabulary unchanged.
