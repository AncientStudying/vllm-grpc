# Phase 0 Research: M6.1.3 — Phase 1 Attribution Closure

**Branch**: `026-m6-1-3-attribution-closure` | **Date**: 2026-05-17 | **Plan**: [plan.md](./plan.md)

## Overview

Phase 0 captures the implementation-level research that complements the spec-level decisions made during the 4-round `/speckit-clarify` cycle (18 Q/A bullets total). The Technical Context in [`plan.md`](./plan.md) has no `NEEDS CLARIFICATION` markers — every architecturally-significant choice was resolved during clarify. Phase 0 here documents the code-surface investigation needed to write the data model and contracts cleanly.

## Research Items

### R-1 — M6.1.2 + M6.1.1 module file set + naming convention inheritance

**Decision**: M6.1.3 mirrors M6.1.2's parallel-module pattern (which mirrors M6.1.1's). Files: `m6_1_3_types.py`, `m6_1_3_sweep.py`, `m6_1_3_reporter.py`, `m6_1_3_validate.py`, `m6_1_3_classifier.py`, `m6_1_3_audit.py`, `m6_1_3_variance.py`, plus the cross-milestone `symmetric_prompts.py`. Each `m6_1_3_*` follows the `m6_1_3_<role>.py` pattern.

**Rationale**: M6.1.1 established the "one module per concern" convention; M6.1.2 inherited it with 5 modules; M6.1.3 inherits with 8 (more concerns: 7-bucket classifier extension, pooled audit aggregation, between-run variance compute, plus the shared helper). The split is intentional — classifier / audit / variance modules each carry significant pure-function logic that's easier to unit-test in isolation than as part of a larger orchestrator module. The parallel-module pattern (vs in-place modification of `m6_1_1_*` / `m6_1_2_*` files) is mandated by FR-037 (M6.1.1 / M6.1.2 historical re-runnability stays frozen).

**Alternatives considered**:
- Modify `m6_1_1_classifier.py` / `m6_1_1_reporter.py` / `m6_1_1_timing.py` in-place per the literal text of FR-008 / FR-009 ("the M6.1.1-expansion classifier (`m6_1_1_classifier.py`) MUST extend...") — REJECTED because in-place modification breaks FR-037's freeze on `--m6_1_1-diagnose` historical output. The spec's literal file references are a vestige from spec-authoring; the planning-round resolution is parallel `m6_1_3_*` modules that extend rather than replace.
- Bundle audit + variance + classifier into one larger `m6_1_3_classifier.py` — REJECTED; the three concerns have separable test surfaces (audit doesn't depend on variance; variance doesn't depend on the 7-bucket label set; classifier consumes both as input). Module-per-concern matches the M6.1.1 pattern.
- Keep `symmetric_prompts.py` under `m6_1_3_*` namespace (e.g., `m6_1_3_symmetric_prompts.py`) — REJECTED per FR-019 round-2 Q4. The shared helper is explicitly cross-milestone (M5.2 + M6.1.3 + M6.2 + M7 + M8 all import); a milestone-prefixed name would mis-signal ownership. The unprefixed name signals shared infrastructure.

### R-2 — In-process clock comparability between frontend servicer and vLLM engine core

**Decision**: The proxy-edge probes use `time.time_ns()` for the wall-clock anchor (compatible with vLLM's `time.time()`-sourced `RequestStateStats.arrival_time`) and `time.monotonic_ns()` for the monotonic anchor (compatible with vLLM's `time.monotonic()`-sourced `RequestStateStats.first_token_ts`). Both are captured inside the frontend servicer process; the engine runs in-process with the servicer (confirmed by spike #4 reading `vllm/v1/engine/__init__.py:149-153`), so monotonic-clock cross-process caveats do NOT apply.

**Rationale**: Spike #4's investigation is the load-bearing evidence. The vLLM source explicitly cautions that `EngineCoreEvent` monotonic timestamps "should not be compared with timestamps from other processes" — but the AsyncLLM engine and the frontend servicer share a single Python process (the servicer calls `self._engine.generate(...)` directly), so the caveat is inapplicable. `time.time_ns()` and `time.time()` both source from `CLOCK_REALTIME`; `time.monotonic_ns()` and `time.monotonic()` both source from `CLOCK_MONOTONIC`. The negative-value assertion (FR-006) is the runtime canary against any future platform that violates this assumption.

**Alternatives considered**:
- Use `time.perf_counter_ns()` for the egress anchor — REJECTED; `perf_counter` is monotonic but its epoch is undefined, so subtracting against vLLM's `first_token_ts` (which uses `time.monotonic()`) would produce a meaningless delta.
- Capture both anchors on the engine side (modify vLLM) — REJECTED per the spec's out-of-scope note ("upstream vLLM contributions — the probes work entirely client-side"). The engine is in-process; the frontend servicer has the same clock access.
- Capture both anchors on the frontend side AND on the engine side, compare both diffs — REJECTED as over-engineering; one-sided capture is sufficient to bisect the gap.

### R-3 — Per-RPC negative-value assertion implementation

**Decision**: The assertion fires in the per-RPC aggregator (likely inside `m6_1_3_classifier.py` or the aggregation path in `m6_1_3_sweep.py`'s `aggregate_multi_point_timings` equivalent), not at the wire-extraction layer (`m6_1_1_timing.py`). Implementation: after computing `seg_ingress_ms` and `seg_egress_ms` per RPC, check that both are `≥ 0`; if either is negative, mark the row as a clock anomaly (a new optional boolean field on `PerSegmentDelta` or its successor) and log the four raw `_ns` values to stderr.

**Rationale**: Putting the assertion in the aggregator preserves the extractor's pure-data role (`m6_1_1_timing.py` just reads keys; it doesn't validate physical constraints). The aggregator already iterates per-RPC for stats computation; adding the check is one branch per RPC. The configurable cell-level fraction (FR-006 + `/speckit-plan` deliverable) is checked once per cell after aggregation, not per-RPC.

**Alternatives considered**:
- Check at extraction time in `m6_1_1_timing.py` — REJECTED; the extractor doesn't know about per-cell context, so it can't apply the cell-level downgrade-to-`inconclusive` logic. Splitting the check between layers would scatter the assertion logic.
- Treat negative values as silently `0` and continue — REJECTED; SC-013's 0.5% RPC budget is the explicit signal that clock anomalies are real and must NOT be silently absorbed.
- Use Python `assert` statements — REJECTED; CPython optimizes out `assert` at `-O`, which would silently disable the assertion in production-like runs. Use explicit `if value < 0: ...` checks instead.

### R-4 — BLAKE2b-8 hash collision probability

**Decision**: 8-byte (64-bit) BLAKE2b digest is sufficient for the audit's collision-distinction purpose. Per spike #5's collision-probability calculation: at the expected per-cell RPC volume (5 runs × 50 RPCs × 4 cohorts × 6 cells = 6000 hashes per multi-run sweep), birthday-collision probability at 64 bits is ≈ `(6000² / 2) / 2^64 ≈ 10⁻¹²` — negligible.

**Rationale**: The hash purpose is to distinguish H1 (different token-id sequences across cohorts) from H2 (same token-id sequences with different per-cohort prompts at the text level — encoding drift). Both detections work with a small per-cohort hash-distribution sample; the hash just needs to be a stable identifier of the token-id list, not cryptographically collision-resistant. BLAKE2b at `digest_size=8` is the natural choice — fast, standard library, deterministic.

**Alternatives considered**:
- BLAKE2b at `digest_size=32` (256-bit) — REJECTED; over-engineered; longer hash inflates the wire payload by 24 bytes per RPC × 6000 RPCs = ~144 KB of unnecessary metadata per multi-run sweep.
- SHA-256 truncated to 8 bytes — REJECTED; BLAKE2b is faster (especially for short inputs like token-id lists) and equally collision-resistant at the same digest size.
- Python's built-in `hash()` truncated to 8 bytes — REJECTED; `hash()` is randomized per-interpreter-run (PYTHONHASHSEED), so the same token-id list would hash differently across runs, defeating the distribution-comparison purpose.

### R-5 — Multi-run preemption-aware URL refresh pattern

**Decision**: Port the M5.2 preemption-aware URL refresh pattern from `m5_2_sweep.py` (the exact line range needs Phase 1 confirmation from the code; spike #6 cited the existence of the pattern). The new `m6_1_3_sweep.py` orchestrator wraps each Phase 1 run invocation in a try/except that detects Modal tunnel rotation (typically surfaces as connection errors against the `*.modal.run` / `*.modal.host` URLs) and re-runs the deploy-handshake to get fresh URLs before retrying. The preemption count is tracked per multi-run sequence; after the second preemption (strictly > 2 per FR-028 round-3 Q3), the orchestrator aborts the remaining runs.

**Rationale**: Spike #6 explicitly flagged the M5.2 pattern as the reusable pattern: "M5.2 had a preemption-aware URL refresh precisely because of this. M6.1.3 should reuse that pattern (it's already in `m5_2_sweep.py`; just needs porting to the diagnose loop)." Importing M5.2's pattern directly (vs duplicating) is the M5.2 → M6.1.3 inheritance per FR-028. The pinned threshold (2) per round-3 Q3 means the orchestrator allows one transient recovery cleanly and aborts after a second failure.

**Alternatives considered**:
- Use Modal's own retry mechanism (the Modal SDK has built-in retry hooks for transient errors) — REJECTED; the project's existing pattern is operator-controlled retry via URL refresh, not SDK-level retry. Changing this would create an inconsistent error-handling model across milestones.
- Treat preemption as fatal (abort on first occurrence) — REJECTED per FR-028 round-3 Q3 explicit pin at "more than 2 times" (allows one recovery).
- Make the preemption-retry behavior optional via a CLI flag — REJECTED; the spec doesn't add a flag for this, and the M5.2 precedent doesn't either. Preemption-aware refresh is the default behavior.

### R-6 — Shared `symmetric_prompts.py` module location and M5.2 back-compat mechanic

**Decision**: New module at `tools/benchmark/src/vllm_grpc_bench/symmetric_prompts.py` (unprefixed by milestone to signal cross-milestone ownership). M5.2 back-compat via the **import-update-in-place** mechanic: update `m5_2_sweep.py`'s import line from `from .m5_2_symmetry import ...` to `from .symmetric_prompts import ...`, and either (a) DELETE `m5_2_symmetry.py` entirely, or (b) keep it as a re-export shim (`from .symmetric_prompts import *  # noqa: F401, F403`) for any downstream code that imports it directly. Option (a) is cleaner; option (b) is safer if any out-of-tree consumer imports `m5_2_symmetry` directly.

**Rationale**: The spec defers the specific mechanic to `/speckit-plan` per FR-019 round-2 Q4 ("specific module name, location, and re-export mechanic are `/speckit-plan` deliverables; the spec-level decision is 'shared helper, not port-in-place nor duplicate'"). The unprefixed name (`symmetric_prompts.py` not `m6_1_3_symmetric_prompts.py`) signals shared infrastructure that M6.2 / M7 / M8 will inherit directly via import. Update-in-place of `m5_2_sweep.py`'s import line is one-line scope; the re-export shim mechanic is also one-line but adds a deprecated path. Plan-level pick: **option (b) re-export shim** — minimum risk, no out-of-tree consumers known but the shim has zero cost; defer the eventual `m5_2_symmetry.py` deletion to a separate cleanup PR if any consumer references it.

**Alternatives considered**:
- New module under a `shared/` subpackage (e.g., `tools/benchmark/src/vllm_grpc_bench/shared/symmetric_prompts.py`) — REJECTED; the project doesn't have a `shared/` namespace convention. Adding one for a single module is over-engineering; the unprefixed name signals shared-ness adequately.
- Relocate to `tools/benchmark/src/vllm_grpc_bench/m6_1_3_symmetric_prompts.py` with M5.2's import updated to that path — REJECTED per FR-019 round-2 Q4. The milestone-prefixed name would mis-signal ownership (suggesting M6.1.3 owns the module rather than the M6.x family sharing it).
- Keep `m5_2_symmetry.py` as the canonical module (no relocation); M6.1.3 imports from there — REJECTED per FR-019's "shared helper, not port-in-place nor duplicate" — the M5.2-prefixed name signals M5.2 ownership, conflicting with the cross-milestone shared intent.

### R-7 — Three-path artifact output routing

**Decision**: The `m6_1_3_validate.py` entry function `run_m6_1_3(args, *, sweep_mode)` infers the output path from the mode flag + modifier values:
1. `sweep_mode == "validate"` → `docs/benchmarks/m6_1_3-attribution-closure-validate.{md,json}`.
2. `sweep_mode == "full"` AND `--m6_1_3-diagnose-repeat == 1` AND `--m6_1_3-diagnose-n != 50` (i.e., differs from the default) → `docs/benchmarks/m6_1_3-attribution-closure-phase-b.{md,json}` (Phase B mode per FR-038 round-2 Q1).
3. `sweep_mode == "full"` otherwise (default modifiers: `repeat=5`, `n=50`) → `docs/benchmarks/m6_1_3-attribution-closure.{md,json}` (canonical publish).
4. If the operator explicitly passes `--m6_1_3-report-out` or `--m6_1_3-report-json-out`, those overrides take precedence regardless of inferred path.

**Rationale**: The Phase B mode is distinguished from the canonical publish run by the modifier-flag combination, not by a separate top-level mode flag (per FR-038's "the orchestrator infers the Phase B output path when `--m6_1_3-diagnose-n` differs from the default 50 AND `--m6_1_3-diagnose-repeat=1`"). The inference logic is in `m6_1_3_validate.py` (the single entry function); the path is then passed to the reporter as the explicit `report_out` value.

**Alternatives considered**:
- Add a separate `--m6_1_3-phase-b` mode flag — REJECTED per round-2 Q2's CLI shape decision (paired mode flags `--m6_1_3` + `--m6_1_3-validate` are the only two top-level flags; Phase B is a modifier combination).
- Have the operator pass `--m6_1_3-report-out` explicitly for every Phase B run — REJECTED; the path inference is the operator-ergonomic default. Explicit override remains available.
- Use a single canonical output path that gets overwritten by each run — REJECTED per round-2 Q1 (operator footgun risk with clobbering).

### R-8 — Compound-label vocabulary alphabetical ordering implementation

**Decision**: FR-008a mandates alphabetical ordering within tied pairs for the compound-label `<top>_<runner_up>` suffix. Implementation: `sorted([top_id, runner_up_id])` where both are drawn from the canonical 6-row mapping (`channel_batching`, `queue_batching`, `engine_compute`, `frontend_arrival`, `proxy_ingress`, `proxy_egress` — note `frontend_arrival` is dormant per round-4 Q1 and never participates). The label is then `f"multi_factor_{sorted_top}_{sorted_runner_up}"`.

**Rationale**: Alphabetical ordering ensures deterministic label generation regardless of which segment scored highest (one of the two top-share segments) vs which scored slightly lower (runner-up). Without sorting, the same near-tie could produce `multi_factor_engine_compute_proxy_egress` in one run and `multi_factor_proxy_egress_engine_compute` in another, defeating reproducibility. The sorted form is canonical.

**Alternatives considered**:
- Order by descending share (`<top>` is always the higher-share segment) — REJECTED per FR-008a's explicit alphabetical rule. Share-ordering would make the label depend on the exact spread, which adds noise; alphabetical is stable.
- Sort by the classifier-label order (the order they appear in FR-008's 5-bucket fallback list) — REJECTED; this ordering isn't documented anywhere as canonical, so readers would have to consult the FR list to verify a label's correctness.
- Render with a separator other than `_` (e.g., `multi_factor_<a>+<b>`) — REJECTED; underscore is the project's convention for compound identifiers, and the `+` would conflict with shell argument parsing.

### R-9 — Audit per-RPC sidecar field placement

**Decision**: Extend the existing `m6_1_1` sidecar JSONL pattern (per M6.1.1's existing `events.jsonl` format). The orchestrator (`m6_1_3_sweep.py`) writes per-RPC rows to `docs/benchmarks/m6_1_3-events.jsonl` with the schema `{run_idx, cell_id, cohort, iter_idx, tokenized_prompt_length, tokenized_prompt_hash, ...m6_1_1_*timing_fields...}`. The orchestrator builds the row from the extractor's parsed `TimingCheckpoint` (per FR-015 round-1 Q1 — orchestrator-derived from extractor output, NOT a parallel emission path).

**Rationale**: Round-1 Q1 explicitly resolved the wire-vs-sidecar question: wire emission is the canonical source; sidecar is the orchestrator-derived per-RPC view. The extractor in `m6_1_1_timing.py` reads the new audit keys (`m6_1_3_tokenized_prompt_length`, `m6_1_3_tokenized_prompt_hash`) per FR-013 and populates new optional fields on `TimingCheckpoint`. The orchestrator then writes the sidecar row using those parsed values.

**Alternatives considered**:
- Frontend-servicer writes the sidecar directly (bypassing the wire) — REJECTED per round-1 Q1.
- Sidecar field is a JSON-embedded sub-object (`{"audit": {"tokenized_prompt_length": ..., "tokenized_prompt_hash": ...}}`) — REJECTED; the existing sidecar pattern is flat, and the additive-strict-superset principle (round-3 Q1) extends to sidecar columns too — pre-M6.1.3 readers should see the new fields as flat top-level keys they can ignore.
- Separate per-RPC audit sidecar file (`m6_1_3-audit.jsonl`) — REJECTED; the events.jsonl convention is the project standard; splitting the sidecar would create a new file pattern for downstream consumers.

### R-10 — Wire-key emission sites in the frontend servicers

**Decision**: Per FR-001 / FR-002 / FR-003 / FR-012 / FR-013 / FR-014:
- `packages/frontend/src/vllm_grpc_frontend/chat.py:CompleteStream` — emit 4 keys (2 proxy-edge `m6_1_1_*` + 2 audit `m6_1_3_*`) via `context.set_trailing_metadata(...)`. Chat has only the streaming RPC; no unary path.
- `packages/frontend/src/vllm_grpc_frontend/completions.py:CompleteStream` — emit 4 keys (same as chat).
- `packages/frontend/src/vllm_grpc_frontend/completions.py:Complete` — emit 2 audit keys only (`m6_1_3_*`); NO proxy-edge keys per FR-003 (streaming-only constraint).
- The probe checkpoints are captured INSIDE the existing handler functions, at the existing `pre_engine_ns` and `first_chunk_ns` capture sites; the audit values are computed AFTER `messages_to_prompt` / `apply_chat_template` resolves the final token-id list.

**Rationale**: Spike #4 enumerated the code surfaces precisely (the spike's "Code surfaces and edit-size estimate" table). The probe sites are alongside existing `time.perf_counter_ns()` captures; the audit sites are post-tokenization (before the request hits the engine). gRPC's `set_trailing_metadata` is the standard wire mechanism for emitting key-value pairs at end-of-stream; REST cohorts get the equivalent via the SSE / JSON terminal event handled by `rest_shim.py` (terminal-event handler reads the same key names).

**Alternatives considered**:
- Emit the probe checkpoints via gRPC initial metadata (vs trailing) — REJECTED; the engine hasn't seen the request at initial-metadata time, so `engine_arrival_ns` isn't available yet; the comparison only makes sense at end-of-stream when the engine has emitted its `first_token_ts`.
- Emit the audit keys via initial metadata (the tokenized prompt IS available before the engine starts) — POSSIBLE but REJECTED for consistency; both key families ride the same wire mechanism (trailing metadata for gRPC; terminal event for REST) so the extractor logic is uniform.
- Capture probe checkpoints in a middleware layer (interceptor) — REJECTED; the gRPC interceptor pattern would see the request but wouldn't have access to the engine's internal `RequestStateStats` instance. Capture has to happen in the handler function itself.

### R-11 — Implementation methodology: copy-then-refactor vs from-scratch reimplementation

**Decision**: Every new M6.1.3 module that has an M6.1.2 (or M6.1.1) analog MUST be implemented as a **copy-then-refactor**, NOT a from-scratch reimplementation. The implementer starts by `cp`-ing the prior-milestone module to the new file name, renames the type / function identifiers to M6.1.3 equivalents, and then applies the refactor delta (add / modify / keep) per the per-module table in [`plan.md`](./plan.md)'s "Implementation Methodology: Copy-Then-Refactor Pattern" section. Net-new modules (`m6_1_3_audit.py`, `m6_1_3_variance.py`, plus the integration test `test_m6_1_3_publish_multirun_cli.py`) have no copy source and are implemented from the contracts + data model directly.

**Rationale**:

The parallel-module pattern (`m6_1_1_*` / `m6_1_2_*` / `m6_1_3_*` siblings frozen per FR-037) is structurally correct — it guarantees the historical re-runnability guarantee that lets reviewers reproduce M6.1.1 / M6.1.2 baselines against the same harness commit that ships M6.1.3. But the **implementation procedure** of writing each new module from scratch (which has been the de-facto pattern through M6.1.1 → M6.1.2) loses information: bug fixes / improvements landed in M6.1.2's modules do NOT carry into M6.1.3 automatically. The implementer must remember every prior-milestone fix and re-derive it — error-prone, and the user observed several regressions during M6.1.2 from exactly this failure mode.

Copy-then-refactor:
- **Inherits every prior-milestone fix automatically** — the new module starts at the prior milestone's already-fixed state, not the original from-spec design.
- **Constrains the diff to the refactor delta** — code review can verify exactly what changed and what stayed identical, rather than reviewing a full reimplementation.
- **Reduces cognitive load** — the implementer reads M6.1.2's module and asks "what do I change for M6.1.3?" instead of "what does this milestone need from scratch?".
- **Surfaces M6.1.2-specific design choices that should be preserved** — when the refactor delta is "keep X", the implementer is forced to read and understand X rather than re-deriving it.

**Trade-off** (acknowledged in plan.md): code duplication accumulates across the milestone family. This is the explicit cost of the parallel-module pattern + FR-037's freeze. The duplication is bounded by the milestone count and by FR-037 (only the latest active milestone receives shared-bug-fix updates; M6.1.1 / M6.1.2 stay frozen). Future consolidation can extract truly-shared logic — the symmetric-prompts case (FR-019 + round-2 Q4) is the first such extraction.

**Special cases**:

- `m6_1_3_classifier.py` has no M6.1.2 analog (M6.1.2's FR-022 explicitly forbade classifier changes), so the copy source is `m6_1_1_classifier.py`. The refactor extends from 5-bucket to 7-bucket per FR-008 + FR-008a; the inherited 5-bucket logic is preserved per FR-008's "MUST be preserved unchanged" clause.
- `symmetric_prompts.py` is a verbatim relocation from `m5_2_symmetry.py` per FR-019 + round-2 Q4 + R-6. The "refactor" is the relocation itself + the re-export shim at `m5_2_symmetry.py` for M5.2 back-compat.
- Net-new modules (`m6_1_3_audit.py`, `m6_1_3_variance.py`, `test_m6_1_3_publish_multirun_cli.py`) have no copy source — their algorithmic spec lives in the contracts + data model. The mitigation is keeping those contracts comprehensive enough that the implementer doesn't have to derive the algorithm from first principles.
- Modifications to **existing files** (frontend servicers, `rest_shim.py`, `m6_1_1_timing.py`, `__main__.py`) are in-place additive edits, NOT copy-then-refactor. The existing additive-only constraint stands.

**Alternatives considered**:
- **From-scratch reimplementation** (the de-facto status quo through M6.1.2) — REJECTED per the user's methodology critique at the close of `/speckit-plan` round. Documented regression evidence: bug fixes landed in M6.1.2's modules failed to carry into the next milestone's implementation.
- **Extract a shared base module** (e.g., `m6_x_sweep_base.py` that all milestone sweeps inherit / import from) — REJECTED for this milestone; would break FR-037's freeze on prior milestones (any change to the shared module would change M6.1.1's / M6.1.2's behavior). A separate refactor to consolidate truly-shared logic is a candidate for a future milestone, but is out of scope for M6.1.3.
- **Document the procedure outside the spec-kit artifacts** (e.g., in `CLAUDE.md` or as a constitution amendment) — DEFERRED. The constitution-amendment process per the Governance section (semver bump, Sync Impact Report, template review) is heavier than the M6.1.3 documentation lift; future M6.2 / M7 / M8 can either inherit the M6.1.3 documentation directly or promote this to a project-wide rule via the amendment process. Surfaced in plan.md's "Project-wide convention question" subsection.

## Cross-references

- Spec: [`spec.md`](./spec.md) — the 45-FR + 13-SC + 18-Clarification contract this research informs.
- Spike notes: [`docs/spikes/m6-1-roadmap-additions/`](../../docs/spikes/m6-1-roadmap-additions/) — items #4, #5, #6 are M6.1.3.
  - `03-proxy-edge-instrumentation-gap.md` — R-2 / R-3 / R-10 source.
  - `04-engine-compute-variation-rootcause.md` — R-4 source.
  - `05-run-to-run-variance.md` — R-5 source (preemption-aware refresh).
- M6.1.2 precedent: [`specs/025-m6-1-2-methodology-discipline/plan.md`](../025-m6-1-2-methodology-discipline/plan.md) — the structural template M6.1.3 mirrors (parallel `m6_1_3_*` modules; FR-032 inherits the 4-cohort matrix + `network_paths` + `cohort_set` verbatim).
- M6.1.1 precedent: [`specs/023-m6-1-1-engine-cost-instrumentation/plan.md`](../023-m6-1-1-engine-cost-instrumentation/plan.md) — the 5-bucket classifier M6.1.3 extends.
- M6.0a precedent for additive-strict-superset JSON evolution: [`specs/024-m6-0a-concurrent-dispatch/contracts/output.md`](../024-m6-0a-concurrent-dispatch/contracts/output.md).
- vLLM source confirmation: `vllm/v1/engine/__init__.py:149-153` (monotonic-clock source), `vllm/v1/metrics/stats.py:202-217` (`RequestStateStats` field clock sources).

## Output

All NEEDS CLARIFICATION items resolved. Plan's Technical Context has zero unresolved markers. Phase 0 complete; Phase 1 design proceeds against the decisions above.
