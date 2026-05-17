# M6.1.1 Instrumentation Contract

**Plan**: [../plan.md](../plan.md) | **Spec**: [../spec.md](../spec.md) | **Data model**: [../data-model.md](../data-model.md)

Describes the four-checkpoint per-RPC timing wire format on REST and gRPC chat_stream paths (FR-006, FR-007, FR-008), the perturbation budget (FR-012), and — under Phase 2(a) — the *shape* of the symmetrisation code change (without pre-committing to the specific edit, which Phase 1's data identifies).

---

## Four checkpoints

Captured by the server-side handler for **every chat_stream RPC** on **both** the REST and gRPC paths. Embed RPCs capture identically as audit controls (FR-011) — the wire-format emission shape is the same.

```text
                                                                          
        REST chat_stream                              gRPC chat_stream    
                                                                          
   ┌─────────────────────────┐                  ┌─────────────────────────┐
   │ FastAPI handler entry   │  (a) handler_entry  │ gRPC servicer entry     │
   └────────────┬────────────┘                  └────────────┬────────────┘
                │                                            │              
                │ ASGI deserialisation                        │ proto deserialisation
                │ + Modal HTTPS edge proxy                    │ + servicer thread dispatch
                ▼                                            ▼              
   ┌─────────────────────────┐                  ┌─────────────────────────┐
   │ Just before              │  (b) pre_engine    │ Just before              │
   │ engine.generate(...)    │                  │ engine.generate(...)    │
   └────────────┬────────────┘                  └────────────┬────────────┘
                │                                            │              
                │ vLLM internal: tokenise, schedule, KV-warm  │  (same — same engine)
                ▼                                            ▼              
   ┌─────────────────────────┐                  ┌─────────────────────────┐
   │ First streamed chunk    │  (c) first_chunk   │ First yielded chunk     │
   │ yielded by engine        │                  │ from generate()         │
   └────────────┬────────────┘                  └────────────┬────────────┘
                │                                            │              
                │ stream remaining tokens                    │ stream remaining tokens
                ▼                                            ▼              
   ┌─────────────────────────┐                  ┌─────────────────────────┐
   │ Terminal SSE event emit │  (d) terminal_emit │ Trailing metadata emit  │
   └─────────────────────────┘                  └─────────────────────────┘
```

Each checkpoint is captured via a single `time.perf_counter_ns()` call (Research R-2). Resolution: nanoseconds. Monotonicity guaranteed.

Per-segment deltas:
- `seg_ab_ms = (pre_engine_ns − handler_entry_ns) × 1e-6` — pre-engine bracket (ASGI / gRPC servicer overhead before engine invocation).
- `seg_bc_ms = (first_chunk_ns − pre_engine_ns) × 1e-6` — engine-internal first-token latency (tokenisation + first-batch schedule + first-token forward).
- `seg_cd_ms = (terminal_emit_ns − first_chunk_ns) × 1e-6` — post-first-token streaming pipeline (each subsequent token's tpot + final emit).

The FR-010 classifier looks at `spread(seg_ab)` and `spread(seg_bc)` across the 3 cohorts per cell. `seg_cd` is captured and published for audit but not used in classification (post-first-token streaming is not where the M6.1 spread lives — `engine_ttft_ms` measures up to first chunk).

---

## REST wire format (FR-007)

The four timestamps are emitted as fields on a `m6_1_1_timings` sub-object on the **terminal SSE event** JSON payload (the same SSE event that already carries M6's `engine_ttft_ms` and `engine_tpot_ms` top-level fields).

```json
{
  // ... existing M6 terminal SSE event fields ...
  "engine_ttft_ms": 43.5,
  "engine_tpot_ms": 12.7,
  "engine_forward_ms": null,  // chat_stream RPCs don't populate engine_forward
  // M6.1.1 additions — sub-object namespace so M6-aware parsers ignore unknown keys
  "m6_1_1_timings": {
    "handler_entry_ns": 1716480000000000000,
    "pre_engine_ns": 1716480000003200000,
    "first_chunk_ns": 1716480000046700000,
    "terminal_emit_ns": 1716480000089200000,
    "perturbation_audit_ns": 240
  }
}
```

Invariants:
- All four `*_ns` fields are integers (Python `int`; JSON number).
- All values are positive monotonic per RPC: `handler_entry_ns < pre_engine_ns < first_chunk_ns < terminal_emit_ns`.
- `perturbation_audit_ns` is the server-side measured total overhead of the 4 `perf_counter_ns()` calls themselves (FR-012); typical value ~200–500 ns; hard gate fires at >500 µs.
- M6 / M6.1 SSE event fields are PRESERVED EXACTLY (no key reorder, no removal, no rename). The `m6_1_1_timings` sub-object is purely additive.

Client extraction (`rest_shim.py`):
```python
def extract_m6_1_1_timings(terminal_event: dict) -> TimingCheckpoint | None:
    sub = terminal_event.get("m6_1_1_timings")
    if sub is None:  # M6 / M6.1 server (no M6.1.1 instrumentation) — fall through silently
        return None
    return TimingCheckpoint(
        handler_entry_ns=sub["handler_entry_ns"],
        pre_engine_ns=sub["pre_engine_ns"],
        first_chunk_ns=sub["first_chunk_ns"],
        terminal_emit_ns=sub["terminal_emit_ns"],
        perturbation_audit_ns=sub["perturbation_audit_ns"],
    )
```

---

## gRPC wire format (FR-008)

The four timestamps are emitted as additional trailing-metadata keys on the chat_stream RPC, prefixed `m6_1_1_t_` to avoid collision with M6's existing `engine_ttft_ms` and `engine_tpot_ms` trailing-metadata keys.

```
trailing-metadata:
  engine_ttft_ms = "43.5"                 # (existing M6 key — unchanged)
  engine_tpot_ms = "12.7"                 # (existing M6 key — unchanged)
  m6_1_1_t_handler_entry = "1716480000000000000"    # (new)
  m6_1_1_t_pre_engine   = "1716480000003200000"    # (new)
  m6_1_1_t_first_chunk  = "1716480000046700000"    # (new)
  m6_1_1_t_terminal_emit = "1716480000089200000"   # (new)
  m6_1_1_t_perturbation_audit_ns = "240"           # (new)
```

Invariants:
- Trailing metadata is byte-string only; values are ASCII-encoded decimal integers parsed to `int` on the client side.
- M6's `engine_ttft_ms` / `engine_tpot_ms` keys are PRESERVED EXACTLY.
- Total trailing-metadata growth: 5 new keys × ~25 bytes each ≈ 125 bytes per chat_stream RPC. Well under the ~1 KB metadata budget M6 operates within (Edge Cases line 111).

Client extraction (analogous to REST):
```python
def extract_m6_1_1_timings_grpc(trailing_md: dict[str, str]) -> TimingCheckpoint | None:
    try:
        return TimingCheckpoint(
            handler_entry_ns=int(trailing_md["m6_1_1_t_handler_entry"]),
            pre_engine_ns=int(trailing_md["m6_1_1_t_pre_engine"]),
            first_chunk_ns=int(trailing_md["m6_1_1_t_first_chunk"]),
            terminal_emit_ns=int(trailing_md["m6_1_1_t_terminal_emit"]),
            perturbation_audit_ns=int(trailing_md["m6_1_1_t_perturbation_audit_ns"]),
        )
    except (KeyError, ValueError):  # M6 / M6.1 server (no M6.1.1 instrumentation)
        return None
```

---

## Perturbation budget (FR-012)

Total time spent in the four `perf_counter_ns()` calls per RPC MUST be less than **500 µs** on average per (cohort, cell). On modern Linux/macOS the typical cost is ~50–200 ns per call; 4 calls × 200 ns = 800 ns ≪ 500 µs (1600× headroom). The budget exists to guard against future implementation regressions (e.g., adding lightweight logging at checkpoint sites).

**Hard gate (round-2 Q3)**: if any (cohort, cell) pair's mean `perturbation_audit_ns / 1000` exceeds 500 (i.e., 500 µs), the harness exits code `4`. No classifications are computed; no Phase 2 can run on the polluted Phase 1 data.

Server-side audit: the Modal server entrypoint emits `perturbation_audit_ns` alongside the four checkpoints. The value is the difference between a baseline `perf_counter_ns()` measurement (taken at handler entry, before any checkpoint capture) and the sum of the 4 individual checkpoint-call times — a self-measurement of the instrumentation cost.

---

## Phase 2(a) symmetrisation shape (data-driven; not pre-committed)

If Phase 1 returns uniform `instrumentation_artifact` across all three chat_stream cells, the operator applies a symmetrisation code change. **The specific edit is identified by Phase 1's per-segment data, not pre-committed at /speckit-plan time.** Round-1 Q1's magnitude-equivalence classifier tells the operator which segment (`seg_ab` or `seg_bc`) carries the spread, but the symmetrisation question is *which path's bracket should be moved to align with the other*.

**Shape options** (the operator picks one based on Phase 1's segment-level breakdown):

1. **Move REST's `engine_start = perf_counter()` forward** to *after* the FastAPI handler's ASGI deserialisation, so the REST bracket starts at the same conceptual point as gRPC's servicer entry. Result: REST's `engine_ttft_ms` decreases by ~5 ms; gRPC's stays constant; the per-cohort spread shrinks.
2. **Move gRPC's `engine_ttft` anchor backward** to *before* the servicer's input handling (i.e., at the gRPC interceptor entry point), so the gRPC bracket starts earlier. Result: gRPC's `engine_ttft_ms` increases by ~5 ms; REST's stays constant; the per-cohort spread shrinks.
3. **Move BOTH paths to a common pre-engine point** (e.g., immediately before `engine.generate(...)`), eliminating any cross-path pre-engine measurement asymmetry entirely. Result: both cohorts' `engine_ttft_ms` decrease by their respective pre-engine times; spread shrinks; the new bracket is the strictest "engine-only" reading.

Option 3 is the conceptually cleanest and matches the spec's "diagnose-first" intent — Phase 1 IDENTIFIES the asymmetry, Phase 2(a) ELIMINATES it. Options 1 and 2 are less rigorous (they make one path catch up to the other rather than aligning both on a canonical point). However, the operator may choose Option 1 or 2 if Phase 1 reveals an obvious "this path is wrong" pattern (e.g., REST's seg_ab is 5 ms longer than gRPC's because ASGI deserialisation is expensive; gRPC's bracket is the right reference).

The Phase 2(a) verification sweep at n=100 confirms the chosen symmetrisation cleared the drift (each cohort's `engine_ttft_ms` mean within 5% of unweighted cohort-average per FR-015 / SC-003).

---

## Phase 2(b) `contracts/instrumentation.md` update (FR-016)

Under Phase 2(b) `channel_dependent_batching`, the operator updates the project-level `contracts/instrumentation.md` (NOT this spec-feature contracts/ file) with a new section keyed by an `m6_1_1`-prefixed heading. The validator pattern is `^## M6\.1\.1: ` (regex). The section content describes the channel-dependent batching effect, its operator-facing interpretation, and how downstream milestones should read per-cohort `engine_ttft_ms` differences.

Minimal acceptable content shape (the operator writes the prose; the structure is fixed):

```markdown
## M6.1.1: Channel-Dependent Batching Effect

vLLM's continuous batching exhibits a measurable channel-dependent first-token latency
when the same engine instance serves requests via different transport paths (REST HTTPS
edge vs raw TCP gRPC). M6.1's M6.1.1 diagnosis confirmed this is a real engine effect,
not a measurement-window asymmetry.

**Operator interpretation rule.** Per-cohort `engine_ttft_ms` differences ≤ 6 ms at the
3-cohort × c ∈ {1, 4, 8} matrix shape are expected; downstream milestones (M6.2 onward)
should weight cross-cohort comparisons against M6.1.1's published per-cohort means subject
to a ±3 ms tolerance band, NOT a CI-overlap test against a single canonical engine_ttft.

**Affected fields.** `engine_ttft_ms` only. `engine_forward_ms` (embed cells) and
`engine_tpot_ms` (post-first-token streaming) are unaffected per M6.1.1 Phase 1's per-segment
breakdown.

**Authority.** M6.1.1 published 2026-MM-DD; baseline numbers in
`docs/benchmarks/m6_1-real-prompt-embeds.json` per-cohort `engine_ttft_ms` are valid;
M6.1.1's report at `docs/benchmarks/m6_1_1-engine-cost-instrumentation.md` is the diagnostic
trail.
```

Validation gate (`m6_1_1_contracts_check.py`): the regex `^## M6\.1\.1: ` must match at least one line in `contracts/instrumentation.md`. The line and its sub-content are captured into the M6.1.1 JSON's `Phase2bDocumentedOutcome.contracts_heading_text` for audit.

---

## Backward compatibility (FR-022)

Both wire-format changes are namespaced/prefixed so M6 and M6.1 instrumentation parsers continue to work unchanged:
- REST: the `m6_1_1_timings` sub-object is a NEW top-level key on the terminal SSE event; existing M6 keys are unchanged.
- gRPC: the `m6_1_1_t_*` keys are NEW trailing-metadata entries; existing M6 keys (`engine_ttft_ms`, `engine_tpot_ms`) are unchanged.

A client running M6.1's harness against a server running M6.1.1's instrumentation will silently ignore the new fields; a client running M6.1.1's harness against a server running M6.1 (or earlier) will silently fall back to `None` and skip per-segment analysis for that RPC (best-effort extraction per Research R-3).
