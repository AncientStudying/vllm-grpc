# Phase 0 Research: M6 — Real-Engine Mini-Validation

**Branch**: `020-m6-real-engine-mini-validation` | **Date**: 2026-05-14
**Plan**: [plan.md](./plan.md)

This document consolidates the research items that informed the plan. The 5-round clarification process (see [`spec.md`](./spec.md) `## Clarifications`) settled all NEEDS CLARIFICATION items at spec time, so this file's purpose is to record the codebase-state findings and design decisions that shape implementation but are not spec-level contracts.

Each item: **Decision** → **Rationale** → **Alternatives considered**.

---

## R-1: AsyncLLM has no native per-request timing surface

**Decision**: The gRPC frontend wraps `AsyncLLM.generate()` with its own wall-clock timer to compute `engine_forward_ms` (embed) and `engine_ttft_ms` / `engine_tpot_ms` (chat_stream). vLLM's `RequestOutput` does not expose per-request timing, so this is greenfield instrumentation.

**Rationale**:
- Confirmed via cross-repo graphify path search: `RequestOutput` carries token output and finish reason but no per-request timing fields.
- Constitution Principle II ("Library Dependency, Not Fork") requires that any vLLM gap be addressed in our adapter code, not by patching upstream.
- The wrapper lives in `packages/frontend/src/vllm_grpc_frontend/{chat.py, completions.py}` and is the only place per-RPC engine timing is computed; the harness reads it back via gRPC trailing metadata (R-2) or REST JSON payload (R-4).

**Alternatives considered**:
- Patching vLLM to emit timing in `RequestOutput.metrics` — rejected by Principle II.
- Subtracting transport baselines to derive engine cost — rejected at spec time (FR-008 forbids this).
- Adding a separate "engine-only" cohort that bypasses transport — rejected at spec time (FR-008 forbids this).

---

## R-2: Engine cost on gRPC published via trailing metadata, not proto extension

**Decision**: For the gRPC cohorts (`default_grpc`, `tuned_grpc_multiplexed`), the gRPC frontend emits per-RPC `engine_cost` via gRPC **trailing metadata** rather than by adding fields to the response message body. Metadata key naming convention:
- For embed: trailing metadata key `engine-forward-ms` with the float value formatted to 3 decimal places as a string (gRPC metadata is string keys/values).
- For chat_stream: trailing metadata keys `engine-ttft-ms` and `engine-tpot-ms` (also string-formatted floats), set on the final stream chunk's trailing metadata.

**Rationale**:
- FR-008 explicitly allows either response-body or trailing-metadata routes ("via gRPC response or trailing metadata").
- Constitution Principle I ("Proto-First") requires `.proto` edits before any wire-format change. Choosing trailing metadata keeps the existing `proto/vllm_grpc/v1/{chat.proto, completions.proto}` schemas untouched, which avoids triggering the `make proto` regeneration cycle and keeps the M5.2-aware proto consumers (proxy + client library) compatible.
- Trailing metadata on a streaming RPC is naturally emitted at stream completion, which is exactly when the final TTFT/TPOT values are known.
- Phase Discipline (Principle III) — adding a proto field is functionally a wire-format change that should be deferred to a future milestone if needed beyond M6's narrow scope.

**Alternatives considered**:
- Add `engine_cost` field to `ChatCompleteResponse` and `ChatStreamChunk` — would require proto edits + stub regeneration + downstream proxy/client awareness. Rejected for Phase Discipline + Proto-First reasons.
- Side-channel HTTP/2 pings — non-standard, hard to correlate to specific RPCs.
- Server-Sent Events / WebSocket sidecar — adds new transport surface for one ephemeral metric. Overkill.

---

## R-3: Modal A10G + Qwen3-7B fp16 memory budget

**Decision**: Qwen3-7B is loaded at fp16 precision on the Modal A10G instance. The Modal app pins the model size to ensure the loaded weights + KV cache for c=8 chat_stream fit within the A10G's 24 GB VRAM.

**Rationale**:
- PLAN.md M6 § states: "Qwen3-7B fp16 ≈ 14 GB, fits with KV-cache headroom — no A100 needed."
- Headroom budget: 24 GB total − 14 GB weights ≈ 10 GB for KV cache, activations, and CUDA overhead. At c=8 with chat_stream max_tokens=50 and h=4096, KV cache per request ≈ a few hundred MB; 8 concurrent requests easily fits within the 10 GB headroom.
- An OOM during smoke (Edge case "GPU memory exceeds A10G's 24 GB") MUST surface as a model-loading failure rather than a silent worker-pod kill. Achieved by adding a startup smoke step in the Modal app that loads the model and runs a single throwaway forward pass before exposing the gRPC + REST endpoints.

**Alternatives considered**:
- Quantisation to int8/int4 — would fit easily, but changes the engine cost characteristics being measured. Out of scope for M6 (deferred to M8 model-expansion).
- A100 instead of A10G — over-provisioned; 80 GB VRAM not needed at h=4096; conflicts with PLAN.md A10G commitment and SC-001 runtime budget assumptions.

---

## R-4: REST shim engine_cost JSON schema mirrors gRPC trailing metadata

**Decision**: The REST shim (`tools/benchmark/src/vllm_grpc_bench/rest_shim.py`) emits engine_cost as a top-level JSON object on each response payload, parallel to the gRPC trailing-metadata contract. Schema:

```json
{
  // ... existing OpenAI-compatible response fields ...
  "engine_cost": {
    // For embed (unary):
    "engine_forward_ms": 12.345
    // For chat_stream (streaming): emitted on the FINAL SSE event:
    // "engine_ttft_ms": 234.567,
    // "engine_tpot_ms": 41.234
  }
}
```

For chat_stream's SSE response, the engine_cost object is included on the terminal `[DONE]` event's data payload (since TTFT and TPOT are only known when the stream completes). The harness's `rest_cohort.py` parses this top-level field on the final SSE event.

**Rationale**:
- FR-008 mandates "dedicated fields added to the JSON response payload by the REST shim (mirroring the gRPC contract on a different transport)."
- Top-level `engine_cost` object keeps backward compatibility with OpenAI-compatible REST consumers (existing fields like `id`, `choices`, `usage` are unchanged); a new top-level key is non-breaking.
- Putting the engine_cost on the final SSE event mirrors the gRPC trailing-metadata-on-stream-completion semantics from R-2.
- Field names match the gRPC trailing metadata keys (`engine_forward_ms`, `engine_ttft_ms`, `engine_tpot_ms`) for cross-cohort consistency in `m6_engine_cost.py`'s parsing layer.

**Alternatives considered**:
- HTTP response headers (`X-Engine-Forward-Ms`) — works for unary but doesn't compose with SSE (headers are sent at HTTP response start, before TTFT is known for streaming). Plus headers force string-typing whereas JSON natively types floats. Rejected.
- Per-SSE-event engine cost — emit incremental engine cost with each token chunk. Heavier and not needed: M6 only consumes total TTFT and aggregate TPOT, not per-token costs.
- Side JSONL stream — adds another transport channel; complicates the REST shim.

---

## R-5: M5.2 published JSON schema for winner-delta lookup

**Decision**: The M6 verdict classifier reads M5.2 winner deltas from `docs/benchmarks/m5_2-transport-vs-tuning.json` at the JSON path `protocol_comparison_verdicts[]`, where each entry has the shape:

```json
{
  "path": "chat_stream" | "embed",
  "hidden_size": 2048 | 4096 | 8192,
  "concurrency": 1 | 4 | 8,
  "grpc_cohort": "tuned_grpc" | "default_grpc" | "tuned_grpc_multiplexed" | "tuned_grpc_channels",
  "rest_cohort": "rest_https_edge" | "rest_plain_tcp",
  "delta_median_ms": <float>,        // signed; sign indicates direction
  "ci_lower_ms": <float>,
  "ci_upper_ms": <float>,
  "verdict": "tuned_grpc_recommend" | "rest_https_edge_recommend" | "no_winner" | ...
}
```

The classifier extracts `|delta_median_ms|` per cell as `M5.2_winner_delta` for the FR-014 5× rule. It uses the `(path, hidden_size=4096, concurrency, grpc_cohort, rest_cohort)` tuple to find the relevant M5.2 row.

**Rationale**:
- Confirmed by direct inspection of the published `docs/benchmarks/m5_2-transport-vs-tuning.json` file (sample row inspected during plan research).
- FR-014's "M5.2 baseline file precondition" requires validating that all 6 M6 cells have corresponding entries in this array; the classifier aborts at sweep launch if any cell entry is missing.

**Alternatives considered**:
- Reading from a different M5.2 JSON file (e.g., the events sidecar) — wrong file shape; per-RPC events, not aggregated verdicts.
- Using `verdict` string instead of `delta_median_ms` magnitude — verdict string carries direction but not magnitude; the 5× rule needs magnitude.

---

## R-6: M5.2 cohort name reconciliation at c=1 vs c≥2

**Decision**: When the M6 classifier looks up M5.2 winner deltas, the gRPC cohort identifier depends on concurrency:
- **At c=1**: M6's `tuned_grpc_multiplexed` cohort maps to M5.2's published `tuned_grpc` cohort (M5.2's c=1 sweeps used `tuned_grpc` because multiplexed/channels distinction has no meaning at single concurrency).
- **At c≥2**: M6's `tuned_grpc_multiplexed` cohort maps to M5.2's published `tuned_grpc_multiplexed` cohort (the names match).
- **REST cohort**: Always `rest_https_edge` at all concurrencies.
- **`default_grpc` cohort**: Always `default_grpc` at all concurrencies.

The mapping is implemented as a deterministic function in `m6_supersede.py` and applied transparently when reading M5.2 winner deltas. M6's published JSON `protocol_comparison_verdicts` rows use M6's own cohort names (always `tuned_grpc_multiplexed`); the mapping only affects the lookup direction (M6 cell → M5.2 cohort name), not the M6 output naming.

**Rationale**:
- Confirmed by direct inspection of `docs/benchmarks/m5_2-transport-vs-tuning.json`: row 1 (chat_stream c=1 h=2048) uses `grpc_cohort: tuned_grpc`; row 3 (chat_stream c=4 h=2048) uses `grpc_cohort: tuned_grpc_multiplexed`.
- PLAN.md M6 § cell #1 explicitly mentions "M5.2's largest c=1 gRPC win (−51 ms tuned_grpc)" — confirming the c=1 cohort identifier is `tuned_grpc`.
- M6 spec's FR-002 lists `tuned_grpc_multiplexed` as the cohort to exercise across all 6 cells; the underlying tuned-channel-config is the same (max_message_size=16MiB, etc. — see M3 frozen config), so M6 measures it consistently and only renames at the M5.2-lookup boundary.

**Alternatives considered**:
- Update the M6 spec to require running BOTH `tuned_grpc` (c=1) AND `tuned_grpc_multiplexed` (c≥2) — would require spec amendment and re-clarification. Rejected: the underlying channel config is identical; the cohort name distinction is M5.2's legacy.
- Skip the c=1 cell — would lose the most likely-to-survive verdict (PLAN.md cell #1). Rejected.
- Look up by `verdict` field instead of cohort name — verdict naming also differs across c=1 vs c≥2 (e.g. `tuned_grpc_recommend` vs `tuned_grpc_multiplexed_recommend`). Same root cause.

---

## R-7: Verdict classifier algorithm

**Decision**: The classifier in `m6_supersede.py` implements FR-014's deterministic discrimination rule as the following pure function of (M6 measurement data, M5.2 baseline JSON):

```text
For each of the 6 M6 cells (path, c=1|4|8 at h=4096):
  1. If any cohort has n_successes < 80 (FR-023):
       → terminal classification = cell_incomplete
       → SKIP all further verdict computation for this cell.

  2. Compute classifier_metric per cohort:
       - For embed: client-observed total per-RPC wall-clock mean and 95% CI (FR-014).
       - For chat_stream: client-observed TTFT mean and 95% CI (FR-014).

  3. Compute engine_cost_mean per cell as the cohort-averaged mean of engine_cost
     (engine_forward_ms for embed, engine_ttft_ms for chat_stream — matches the
     classifier_metric's path-specific axis).

  4. Compute engine_cost_drift_warning flag:
       - If any pair of cohorts' engine_cost_mean disagree by >10%, set flag.
       - Flag does NOT promote cell to cell_incomplete (FR-014 sub-clause).

  5. Lookup M5.2_winner_delta:
       - Read protocol_comparison_verdicts[] row for (path, h=4096, c, grpc_cohort, rest_cohort)
         using the R-6 cohort-name mapping.
       - If the row's verdict ∈ {"tuned_grpc_recommend", "tuned_grpc_multiplexed_recommend",
         "default_grpc_recommend", ...} AND |delta_median_ms| > 0:
            M5.2_winner_delta = |delta_median_ms|, M5.2_winner_direction = sign(delta_median_ms)
         Else (M5.2 verdict was no_winner):
            M5.2_winner_delta = None.

  6. Compute M6 cohort-pair CI overlap (the 3 cohorts produce 3 pairwise comparisons:
     rest_https_edge vs default_grpc, rest_https_edge vs tuned_grpc_multiplexed,
     default_grpc vs tuned_grpc_multiplexed). The relevant pair is the one M5.2
     classified — i.e., the (rest_cohort, grpc_cohort) pair from the M5.2 row.

  7. Apply FR-014 discrimination rule:
       - If M5.2_winner_delta is None:
            If M6 pair CIs overlap → no_winner_at_n100
            If M6 pair CIs are non-overlapping → no_winner_at_n100 (no M5.2 baseline
              to compare direction against; conservative).
       - Else if M6 pair CIs are non-overlapping:
            If sign(M6_delta) == M5.2_winner_direction → verdict_survives
            Else → verdict_changed
       - Else (M6 pair CIs overlap):
            If engine_cost_mean ≥ 5 × M5.2_winner_delta → verdict_buried_by_engine
            Else → no_winner_at_n100

  8. Write per-cell verdict + classifier_metric values + engine_cost_mean +
     engine_cost_drift_warning flag + n_successes + failure_count to M6 report
     and JSON companion.
```

**Rationale**:
- Direct implementation of FR-014's discrimination rules + FR-023's `cell_incomplete` precondition + FR-014's `engine_cost_drift_warning` sub-clause.
- Pure function of inputs ⇒ deterministic ⇒ unit-testable on synthetic inputs without Modal access (per Constitution Principle IV / Quality Standards).
- Step 1 ordering (`cell_incomplete` first) prevents wasted classifier work on cells that won't get a verdict.

**Alternatives considered**:
- Compute all metrics first, then check `cell_incomplete` — wastes computation; same outcome.
- Allow operator post-hoc reclassification — explicitly forbidden by FR-014 ("operator post-hoc re-classification is not permitted").
- Use `delta_median_ms` directly instead of `|delta_median_ms|` for the 5× rule — would conflate sign + magnitude. The rule cares about magnitude only.

---

## R-8: Per-cohort warmup × round-robin per c-batch interaction

**Decision**: Within each cell, the warmup phase (FR-021: 10 throwaway RPCs per cohort) and the measurement phase (FR-022: round-robin per c-batch across 3 cohorts × 100 RPCs) are sequenced as follows:

```text
For each cell (in cell-order: embed/c=1, embed/c=4, embed/c=8, chat_stream/c=1, ...):

  # Warmup phase — round-robin per c-batch as well, to keep per-cohort context-switch costs
  # absorbed into warmup rather than leaking into measurement
  For warmup_round in 1..ceil(10/c):
    For cohort in [rest_https_edge, default_grpc, tuned_grpc_multiplexed]:
      Fire min(c, 10 - warmup_round*c) concurrent RPCs of cohort, await; discard results.
    # Each cohort accumulates 10 successful warmup RPCs (FR-023 silent retries warmup
    # failures; if warmup cannot succeed, mark cell cell_incomplete per FR-023).

  # Measurement phase
  For measurement_round in 1..(100/c):
    For cohort in [rest_https_edge, default_grpc, tuned_grpc_multiplexed]:
      Fire c concurrent RPCs of cohort, await; record measurements.

  # Per-cell totals: 30 warmup RPCs (10/cohort × 3 cohorts) + 300 measurement RPCs
  # (100/cohort × 3 cohorts) = 330 RPCs/cell for c∈{1,4,8}.
  # At c=8: 100/c = 12.5 — see R-9 below for the rounding rule.
```

The harness module that drives this is `m6_sweep.py`; it composes existing cohort-execution helpers from `rest_cohort.py` and `m5_1_grpc_cohort.py` (modified to read engine_cost; see R-2/R-4).

**Rationale**:
- FR-021 mandates per-cohort warmup excluded from metrics.
- FR-022 mandates round-robin per c-batch for measurement; the spec also says "Warmup RPCs (FR-021) MUST follow the same per-c-batch rotation as the measurement RPCs."
- Composing both into a single sweep loop keeps the implementation simple and the timing within each cell tight (no large gaps between cohorts).
- Warmup retry semantics: FR-023 says warmup failures are silently retried until 10 successes accumulate; if warmup cannot succeed, the cell is marked `cell_incomplete` without measurement RPCs being attempted.

**Alternatives considered**:
- Warmup all 30 RPCs as a contiguous block (10 cohort A, 10 cohort B, 10 cohort C) before measurement starts — violates the "warmup follows the same rotation" sub-clause of FR-022 and risks cohort-A's warmup state going cold before cohort-A's measurement begins.
- Skip the c-batch round-robin during warmup (just do per-cohort sequential warmup) — see above.

---

## R-9: Round-robin per c-batch at c=8 — rounding rule

**Decision**: At c=8, `100/c = 12.5` rounds. The implementation runs **13 rounds** of c-batches (8 RPCs each), then **drops the last 4 RPCs** of cohort C (the third cohort) so that each cohort accumulates exactly 100 measurement RPCs. This keeps n=100 stable per FR-004 and keeps the round-robin invariant (each round fires the same number of RPCs per cohort).

Concretely at c=8:
- Rounds 1–12: each round fires 8 cohort-A + 8 cohort-B + 8 cohort-C = 24 RPCs (total: 96 per cohort after 12 rounds).
- Round 13: fire 8 cohort-A + 8 cohort-B + 4 cohort-C (skip last 4 RPCs of cohort C), total 100/100/100 across cohorts.

For warmup at c=8 (10 RPCs/cohort): rounds 1 fires 8 RPCs/cohort, round 2 fires 2 RPCs/cohort to top up to 10. Same pattern.

**Rationale**:
- FR-004's n=100 measurement RPCs per cohort is the load-bearing invariant; it must hold exactly (CIs depend on n).
- Round 13's truncation only affects the LAST 4 RPCs of the LAST cohort within a cell, minimising the drift difference between cohorts.
- Alternative — running 12 rounds and getting 96/96/96 — would violate FR-004.
- Alternative — running 13 full rounds and getting 104/104/104 — would also violate FR-004 (n=100 exactly).

**Alternatives considered**:
- Use n=96 (multiple of 8) or n=120 (multiple of 8 that round-trips at c=4 too) — would change spec FR-004's n=100. Rejected: requires re-clarification.
- Drop the last 4 RPCs of cohort A instead — equivalent symmetry; chose cohort C arbitrarily (latest-completed cohort within the cell).

---

## R-10: Modal app real-engine launch convention

**Decision**: The existing `scripts/python/modal_bench_rest_grpc_server.py` Modal app gains a flag (or env var) to swap the MockEngine for a real `AsyncLLM` instance loaded with Qwen3-7B fp16. Implementation pattern:

```python
# In scripts/python/modal_bench_rest_grpc_server.py:

USE_REAL_ENGINE = os.environ.get("M6_USE_REAL_ENGINE", "false").lower() == "true"
M6_MODEL = os.environ.get("M6_MODEL", "Qwen/Qwen3-7B")

@app.function(gpu="A10G", ...)
def serve_bench():
    if USE_REAL_ENGINE:
        from vllm import AsyncEngineArgs, AsyncLLM
        engine_args = AsyncEngineArgs(
            model=M6_MODEL,
            dtype="float16",
            enable_prompt_embeds=True,  # Phase 6.1
        )
        engine = AsyncLLM.from_engine_args(engine_args)
        # Run a single throwaway forward pass to surface OOM/load-failures as
        # explicit errors rather than silent worker-pod kills (Edge case
        # "GPU memory exceeds A10G's 24 GB").
        _smoke_check_engine(engine)
    else:
        engine = MockEngine(MockEngineConfig(...))  # existing M5.x path

    # Wire engine into both gRPC and REST servicers (existing pattern)
    ...
```

The harness's `--m6` CLI flag sets the `M6_USE_REAL_ENGINE=true` env var on the Modal function deploy. The smoke gate (FR-011) and the full sweep (FR-017) both deploy with this env var set.

**Rationale**:
- Confirmed by codebase mapping: the Modal app currently only instantiates MockEngine; adding a flag-gated branch is the minimal additive change.
- Env var (rather than a Modal function arg) keeps the M5.x deploy path unchanged for backward compatibility — the env var defaults to MockEngine.
- The throwaway forward-pass at startup catches OOM/model-load failures before the smoke gate's per-cohort RPCs start, surfacing them as a clear startup error per the spec edge case.
- Phase 6.1's `enable_prompt_embeds=True` is preserved.

**Alternatives considered**:
- Two parallel Modal apps (one MockEngine, one real engine) — duplicates the gRPC + REST server wiring code and proto stubs. Rejected: more divergence to maintain.
- Deploy-time selection via `modal deploy --tag ...` — not natively supported by Modal in the way needed here.

---

## Coverage Summary

All NEEDS CLARIFICATION items in the Technical Context were resolved during the 5-round spec clarification process; this Phase 0 file documented codebase-state findings + design decisions only. No items remain unresolved.
