# Implementation Plan: M6.2 — Token-Budget Characterization (Production Latency Budgets Across `max_tokens` Axis)

**Branch**: `027-m6-2-token-budget` | **Date**: 2026-05-19 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/027-m6-2-token-budget/spec.md`

## Summary

M6.2 lifts `max_tokens` from M6.1.x's fixed cap (10 for embed, 50 for chat_stream — held constant as the protocol-isolation control) to a **six-point measurement axis `{10, 50, 256, 512, 1024, 2048}`** under each (cell × cohort) pair, producing per-cohort p50/p95/p99 wall-clock latency budgets across realistic production response lengths.

**Three user stories** (from [spec.md](./spec.md)):

1. **Per-cohort latency budget table** (P1, US1) — 6 cells × 4 cohorts × 6 caps = 144 measurement points. Null-anchor validation at `max_tokens=10/50` against M6.1.3's published CIs.
2. **Protocol-crossover threshold** (P2, US2) — symmetric mean-in-CI rule (spec round-1 Q3).
3. **KV-cache pressure observation** (P3, US3) — wall-clock-ratio inference at threshold 2.2 (spec round-3 Q3), computed from the KV-pressure **sub-probe** per FR-036 (NOT the main-sweep budget-table rows).

**Four exogenous-confound controls** (spec round-4):

- FR-030 cohort-innermost block iteration (eliminates between-cohort time-of-day bias).
- FR-031 intra-sweep anchor re-measurement at 4h cadence (makes drift observable).
- FR-032 per-block UTC timestamps + iteration-discipline machine check (verifiable post-hoc).
- FR-033 in-window retry once, no end-of-sweep retry pass (preserves FR-030 under transient failures).

**Three-regime prompt-source split (spec round-5 — Option D)**:

- **Null-anchor cells** (`max_tokens ∈ {10, 50}`): synthetic seed-derived prompts (M6.1.x byte-identical). Preserves FR-012/FR-013 cross-milestone anchor comparison.
- **Interior-cap cells** (`max_tokens ∈ {256, 512, 1024, 2048}`): ShareGPT corpus (chat) or ShareGPT-derived embeddings at hidden_size=4096 (embed). Production-realistic, methodologically consistent across cell-types.
- **KV-pressure sub-probe** (`c=8 × {1024, 2048} × {chat_stream, embed} × 4 cohorts`, `n=20`, `ignore_eos=True`): ShareGPT corpus regime + forced-cap generation. The ONLY measurement that drives FR-017a's wall-clock-ratio inference + threshold 2.2 comparison.

The sub-probe is **additive** to the budget table: the budget-table c=8 rows continue to use the interior-cap regime (natural EOS), the sub-probe emits to the `KVPressureObservation` entity only. The reporter labels each clearly: budget-table = "production latency under cap" (Story 1); sub-probe = "KV-ceiling forced-cap regime" (Story 3).

**Four sweep-level integrity warning channels** (publish-blocking-eligible; operator decides): FR-014 (null-anchor cross-milestone drift), FR-029 (failure-summary threshold), FR-009/SC-010 (cohort-CSP mismatch), SC-016 (intra-sweep latency drift). Plus one soft diagnostic: SC-017 (iteration-discipline broken; informational only).

**Implementation discipline (FR-028 — project-wide convention from M6.1.3)**: M6.2 is produced by **copying the M6.1.3 `m6_1_3_*` module family into an `m6_2_*` namespace and refactoring only the deltas**. Regenerating the measurement path from scratch is FORBIDDEN. Round-5's additions extend this discipline: the new `m6_2_prompt_source.py` and `m6_2_sub_probe.py` modules are net-new (no copy source); the changes to existing RPC builders (`m6_rpc_driver.py`, `m6_1_rpc_driver.py`) are additive parameterization (`max_tokens`, `ignore_eos`) — no behavioral change to existing call sites that pass the M6.1.x defaults.

**Round-3 deferral (FR-004)**: Publish-mode `n` (and the wall-clock + Modal-spend caps FR-021/FR-023) deferred to a future clarify cycle gated on validate-sweep variance data. The publish-mode orchestrator MUST refuse `--m6_2` invocation if `--m6_2-n` is unset. The validate sweep runs at `n=20` pinned on the 3-point axis subset `{10, 50, 2048}` (~2.3-2.5 h wall-clock, ~$4 Modal spend). The KV-pressure sub-probe runs at `n=20` pinned (independent of round-3 deferral).

**Phase 1 prerequisite (round-5 FR-035)**: A new ShareGPT-derived embed corpus at `hidden_size=4096` MUST exist and be committed before `--m6_2-validate` is invoked. Generated offline via an adapted `scripts/python/gen_embed_corpus.py`: feed each of the 1000 ShareGPT prompts through Qwen3-8B's embedding layer, save 1000 `.pt` files at variable `seq_len × 4096` (fp16, ~400-800 MB), build `tools/benchmark/corpus/completions_embeds_qwen3_8b/manifest.json` with per-entry SHA + `source_prompt_id` + `seq_len` + `bucket`.

**Two published artifacts** (FR-015): `docs/benchmarks/m6_2-token-budget.{md,json}` (canonical) and `docs/benchmarks/m6_2-token-budget-validate.{md,json}` (validate sibling).

**M6.1.3 forward-pointing annotation** (FR-019): single leading `> **Note**:` line in M6.1.3's published markdown pointing forward to M6.2. Reciprocal "Method / Background" cross-reference in M6.2's body.

## Technical Context

**Language/Version**: Python 3.12 (project standard).

**Primary Dependencies**:

- `vllm` + `torch` — UNCHANGED from M6.1.3. Operator runs `uv sync --frozen --all-groups` on macOS per ANALYSIS.md M6.0a + `feedback_local_lint_chain` memory.
- `grpcio` + `grpcio-tools` — UNCHANGED. Zero new wire keys per FR-011; schema stays at `"m6_1_1.v1"`.
- `httpx` — UNCHANGED.
- `modal` — UNCHANGED. No modifications to Modal endpoint code; M6.2 is harness-only.
- `tcptraceroute` — INHERITED from M6.1.2 (FR-009).

**Storage**:

- Outputs: `docs/benchmarks/m6_2-token-budget.{md,json}` (publish, FR-015); `docs/benchmarks/m6_2-token-budget-validate.{md,json}` (validate, FR-015); `docs/benchmarks/m6_2-events.jsonl` (sidecar).
- Inputs: `docs/benchmarks/m6_1_3-attribution-closure.json` (READ-ONLY M6.1.3 baseline; FR-013 null-anchor + FR-031 trajectory threshold reference); `tools/benchmark/corpus/chat_sharegpt_1000.json` (READ-ONLY chat corpus per FR-034); `tools/benchmark/corpus/completions_embeds_qwen3_8b/` (READ-ONLY embed corpus per FR-035 — NEW, generated offline as Phase 1 prerequisite).
- Modifications: `docs/benchmarks/m6_1_3-attribution-closure.md` — ONE leading note line per FR-019 (markdown only; JSON untouched).
- Modifications: `contracts/instrumentation.md` — extended with M6.2's additive top-level keys + per-row fields + three-regime prompt-source documentation + KV-pressure sub-probe contract + four sweep-level integrity-header firing rules.

**Testing**: `pytest` + `pytest-asyncio`. Coverage tiers:

- **Unit tests — `test_m6_2_iteration_order.py`** (NEW): FR-030 cohort-innermost discipline; FR-032 per-block UTC timestamps + `iteration_discipline_verified` machine check + wall-clock timeline subsection.
- **Unit tests — `test_m6_2_anchor_trajectory.py`** (NEW): FR-031 4h cadence + per-cohort `latency_drift_warning` + SC-016 sweep-level integrity header at ≥ 2 of 4.
- **Unit tests — `test_m6_2_crossover.py`** (NEW): symmetric mean-in-CI rule; US2 #2 inconclusive base verdict; US2 #3 CIs overlap at 10/50; FR-016 validate-mode coarse 4-value vocabulary.
- **Unit tests — `test_m6_2_kv_pressure.py`** (NEW): FR-017a wall-clock-ratio inference computed from sub-probe rows; best-effort engine-field capture; cross-validation narrative; OOM-observed handling.
- **Unit tests — `test_m6_2_retry_policy.py`** (NEW): FR-033 in-window retry once; retry-failure handling; end-of-sweep retry forbidden; retry-stays-in-time-window assertion.
- **Unit tests — `test_m6_2_null_anchor.py`** (NEW): FR-012 / FR-013 cross-milestone comparison; FR-014 sweep-level integrity header at ≥ 3 of 48 anchor cells.
- **Unit tests — `test_m6_2_artifact_schema.py`** (NEW): 144-row latency budget table; strict-superset compat with M6.1.3-vintage readers; validate-mode `not_validated` rendering; per-row `prompt_source` + `measurement_regime` + `prompt_corpus_idx` field discipline; `run_meta` schema extensions.
- **Unit tests — `test_m6_2_cli.py`** (NEW): argparse — flag presence, defaults (verbatim-inheritance regression from M6.1.3), mutual exclusion against 17 prior mode flags, round-3 deferral gate enforcement, `--m6_2-asymmetric-prompts` NOT-shipped enforcement (FR-008).
- **Unit tests — `test_m6_2_prompt_source.py`** (NEW per round-5): FR-034 three-regime chat prompt source (synthetic at null anchors, ShareGPT corpus at interior caps + sub-probe); FR-035 three-regime embed prompt source (random tensor at null anchors, ShareGPT-derived embed corpus at interior caps + sub-probe); `symmetric_prompts.assign_symmetric_prompt` cohort-invariance per iteration index; `prompt_corpus_idx` is `None` for synthetic regimes and equals `iter_idx` for corpus regimes; corpus SHA validation (`chat_corpus_sha256` / `embed_corpus_sha256` in `run_meta` match the on-disk corpus provenance files; SC-018 corpus-drift error fires on mismatch).
- **Unit tests — `test_m6_2_sub_probe.py`** (NEW per round-5): FR-036 sub-probe contract — 16 blocks (4 cohorts × 2 cell-types × 2 caps) at `n=20`, each with `ignore_eos=True`; sub-probe results emit to `KVPressureObservation` only (NOT to the latency budget table); FR-017a wall-clock-ratio inference uses sub-probe `wall_p50_ms` not budget-table rows; sub-probe runs in both publish and validate modes; SC-019 sub-probe schema invariants.
- **Integration test — `test_m6_2_validate_cli.py`** (NEW): `--m6_2-validate --m6_2-skip-deploy` against stub driver; asserts validate-sibling artifact JSON contents (3-point axis subset, axis-restricted disclaimer, KV-pressure inference from sub-probe, anchor trajectory start+end).
- **Integration test — `test_m6_2_publish_cli.py`** (NEW): `--m6_2 --m6_2-n=50 --m6_2-skip-deploy` against stub driver (n=50 for test speed); asserts full 6-point axis × 4-cohort × 6-cell table, full crossover vocabulary, `iteration_discipline_verified = true`, wall-clock-timeline subsection, sub-probe contract.
- **CI gate (Constitution IV)**: All new tests run in the same `pytest` invocation as M6.1.x suites; failure blocks merge. Local-lint chain (`ruff check`, `ruff format --check`, `mypy --strict`, `pytest`) per `feedback_local_lint_chain` memory before push.

**Target Platform**:

- Code changes: operator workstation only — no Modal compute for code/lint/test gates.
- Embed corpus generation (Phase 1 prerequisite per FR-035): Modal A10G or local GPU for the offline embedding pass; ~10-30 min compute to embed 1000 prompts through Qwen3-8B's embedding layer.
- Validate sweep (`--m6_2-validate`): Modal A10G in `eu-west-1` (FR-020 default, verbatim inheritance from M6.1.3).
- Publish sweep (`--m6_2`): same Modal config. ~20-48 h wall-clock; tunnel must stay alive; FR-026 preemption-recurrence threshold (2) handles transient preemption.

**Performance Goals**:

- SC-001 / SC-002 / SC-003 / ... / SC-017 / SC-018 / SC-019 — full list in spec.md §"Success Criteria". Round-5 additions: SC-018 (three-regime prompt-source discipline + corpus SHA validation); SC-019 (sub-probe contract — 16 blocks × n=20 × ignore_eos=True, wall-clock-ratio inference from sub-probe rows).

**Constraints**:

- **No frontend / proxy / engine path changes** (FR-006, FR-007, FR-010, FR-027). M6.2 is harness-only.
- **No `.proto` edits** (Constitution I). M6.2 adds zero new wire keys.
- **Strict-superset schema** (FR-011 + SC-007). All M6.2 additions are additive top-level JSON keys or additive per-row fields; `schema_version` stays at `"m6_1_1.v1"`.
- **Copy-then-refactor discipline** (FR-028 — project-wide convention from M6.1.3). M6.2 modules are produced by copying the M6.1.3 `m6_1_3_*` family into `m6_2_*` and refactoring only the deltas the `max_tokens` axis + FR-030/031/032/033 confound controls + round-5 three-regime split + sub-probe require.
- **Cohort-innermost discipline** (FR-030). Cohort-outermost iteration FORBIDDEN.
- **In-window retry only** (FR-033). End-of-sweep retries FORBIDDEN.
- **Round-3 deferral** (FR-004). Publish orchestrator refuses `--m6_2` if `--m6_2-n` is unset.
- **No `--m6_2-asymmetric-prompts` flag** (FR-008 + spec round-3 Q1). Flag MUST NOT be added to argparse.
- **Three-regime prompt source** (FR-034 / FR-035 — round-5). Null anchors use synthetic; interior caps + sub-probe use ShareGPT corpus (chat) or ShareGPT-derived embed corpus (embed). The orchestrator MUST select the regime per `(cell, max_tokens)` block, not per-cohort or per-iteration.
- **KV-pressure sub-probe additive** (FR-036 — round-5). Sub-probe results emit to `KVPressureObservation` ONLY; budget-table c=8 rows continue to use the interior-cap regime.
- **`ignore_eos = True` only at sub-probe blocks** (FR-003 (b) + FR-036 — round-5). Main-sweep budget-table rows preserve `ignore_eos = False` (natural EOS) at every `max_tokens` axis point including 2048.
- **Embed corpus generation Phase 1 prerequisite** (FR-035). `tools/benchmark/corpus/completions_embeds_qwen3_8b/` MUST exist + be committed before `--m6_2-validate`.
- **Inherited 4-cohort matrix + 5-segment decomposition + concurrent dispatch + symmetric-prompts helper** (FR-006, FR-007, FR-008, FR-010, FR-011). Zero re-derivation. M6.1.3 classifier / audit / variance helpers / `symmetric_prompts.assign_symmetric_prompt` / `m6_1_2_network_probe` / `m6_1_1_timing` / `m6_1_2_types` / `m6_1_types` imported by reference, NOT copied.
- **Verdict-body preservation** (FR-019). M6.1.3 markdown receives exactly ONE leading note line; JSON untouched.

**Scale/Scope**:

- **New module files**: 8 — `m6_2_types.py`, `m6_2_sweep.py`, `m6_2_reporter.py`, `m6_2_validate.py`, `m6_2_crossover.py`, `m6_2_anchor_trajectory.py`, **`m6_2_prompt_source.py`** (NEW per round-5), **`m6_2_sub_probe.py`** (NEW per round-5). Combined: ~1500–2200 LOC.
- **Modified module files**: 3 — `__main__.py` (~80-120 LOC argparse wiring), **`m6_rpc_driver.py`** (parameterize `max_tokens` + `ignore_eos`; ~10-15 LOC), **`m6_1_rpc_driver.py`** (same; ~10-15 LOC), **`corpus.py`** (add embed-corpus-at-hidden_size loader for the new `completions_embeds_qwen3_8b/`; ~30-40 LOC).
- **READ-ONLY (imported) module files**: 10 — `m6_1_3_classifier.py`, `m6_1_3_audit.py`, `m6_1_3_variance.py` (helper functions), `symmetric_prompts.py` (`assign_symmetric_prompt` now wired into M6.2), `m6_1_2_network_probe.py`, `m6_1_1_timing.py`, `m6_1_2_types.py`, `m6_1_types.py`, `m6_1_3_sweep.py` (for `cohorts_at_concurrency`), `m3_types.py`.
- **New test files**: 10 — the 8 unit-test files listed in Testing + 2 integration tests. Combined: ~1800–2500 LOC.
- **Modified doc files**: 2 — `contracts/instrumentation.md` (M6.2 schema + three-regime prompt source + sub-probe contract + integrity-header firing rules); `docs/benchmarks/m6_1_3-attribution-closure.md` (single leading-note line per FR-019).
- **New benchmark artifacts**: 2 — validate sibling, canonical publish (FR-015).
- **New corpus artifact**: 1 — `tools/benchmark/corpus/completions_embeds_qwen3_8b/` directory containing 1000 `.pt` files (~400-800 MB at fp16) + `manifest.json` + provenance metadata (FR-035 Phase 1 prerequisite).
- **New script**: `scripts/python/gen_embed_corpus_qwen3_8b.py` (or adaptation of the existing `gen_embed_corpus.py` with a `--model qwen3-8b` flag) — offline corpus generator. ~150-200 LOC.
- **Modal compute**: ~$4 validate + round-3-pinned bound for publish (~$20-$40 provisional) + ~$1-2 one-time for embed corpus generation. Sub-probe adds < 2% to the publish wall-clock (~30 min – 1 h at n=20).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against the 5 principles in `.specify/memory/constitution.md` (v1.0.0):

| Principle | Status | Notes |
|---|---|---|
| **I. Proto-First** | **PASS** | Zero new wire keys. All M6.2 additions are JSON-level artifact additions. `schema_version` unchanged. Round-5's `ignore_eos` parameter is a Python sampling-params keyword, not a `.proto` field. The new embed corpus stores `torch.save` tensors per-file; the wire format passing them to the engine is the M6.1.x `prompt_embeds` field that already exists. |
| **II. Library Dependency, Not Fork** | **PASS** | No engine / proxy / frontend changes. The embed-corpus generator (FR-035) is an offline script that uses `vllm`'s public `LLM` / `LLMEngine` API for the embedding pass — no upstream patching. The `symmetric_prompts.assign_symmetric_prompt` function being newly wired in M6.2 is a project-internal change to call a previously-unused function in our own module, not an upstream contribution. |
| **III. Phase Discipline** | **PASS** | M6.2 scope matches PLAN.md M6.2 entry. Out-of-scope held firm: M7 (corpus diversity beyond ShareGPT), M8 (additional models, max_model_len > 2048), upstream vLLM contributions. The new embed corpus generation IS in scope — it's the M6.2 implementation prerequisite for the FR-035 three-regime split, NOT a new corpus-diversity deliverable. ShareGPT (the source) is M5.2-vintage; deriving embeddings from it for M6.2 is reuse of existing prompt content. |
| **IV. CI is the Merge Gate** | **PASS** | 10 new test files exercise the round-5 deltas (prompt source three-regime, sub-probe, corpus SHA validation) on top of the round-4 controls (cohort iteration, anchor trajectory, crossover, KV-pressure, retry, null-anchor, artifact schema, CLI). Local-lint chain mandatory. `iteration_discipline_verified` machine check + 0.5% clock-anomaly budget CI-verifiable from artifact JSON. |
| **V. Honest Measurement** | **PASS** | Round-5 IS an honest-measurement upgrade: the synthetic-prompt + natural-EOS regime M6.1.x relied on silently broke the M6.2 spec's `max_tokens=2048` and `wall_clock_ratio_c8_2048_over_1024` claims (Qwen3-8B EOS-samples at ~50-200 tokens regardless of cap on the synthetic probe). The three-regime split surfaces what each measurement actually answers: budget-table rows = natural-EOS production behavior; sub-probe = forced-cap KV-ceiling. The reporter labels each, the JSON's `prompt_source` + `measurement_regime` fields make it machine-checkable, and the `chat_corpus_sha256` / `embed_corpus_sha256` `run_meta` fields make corpus provenance audit-able. SC-018's corpus-drift error fails the post-sweep validator if the artifact-recorded SHAs diverge from the on-disk corpus — the operator cannot silently swap a corpus mid-cycle. |

**Result: 5/5 PASS. No violations. Complexity Tracking is empty.**

Re-check after Phase 1 design: see "Post-Design Constitution Check" at the end of this document.

## Project Structure

### Documentation (this feature)

```text
specs/027-m6-2-token-budget/
├── plan.md                     # This file (/speckit-plan output)
├── research.md                 # Phase 0 — research items + decisions
├── data-model.md               # Phase 1 — entity shapes (extended with round-5 prompt_source + measurement_regime + sub-probe fields)
├── quickstart.md               # Phase 1 — operator playbook (Stage 0 now includes the corpus generation prerequisite)
├── contracts/
│   ├── cli.md                  # The --m6_2 + --m6_2-validate CLI surface + round-3 deferral gate. No new CLI flags from round-5 (corpus paths are spec-pinned, not parametrizable).
│   ├── artifact-schema.md      # Top-level keys + per-row fields + four publish-blocking-eligible sweep-level integrity-header rules + symmetric mean-in-CI crossover rule + wall-clock-ratio inference rule + validate-mode rendering rules + ROUND-5 ADDITIONS: prompt_source vocabulary + measurement_regime vocabulary + sub-probe rendering rules + corpus SHA validation rules.
│   ├── iteration-order.md      # FR-030/031/032/033 confound controls + ROUND-5 ADDITIONS: sub-probe step in the orchestrator outer loop, FR-030 discipline preserved within the sub-probe.
│   ├── wire-vocabulary.md      # M6.2 adds zero new wire vocabulary (REUSED unchanged from prior round; the round-5 ignore_eos parameter is a Python sampling-params keyword, not a wire-format key).
│   └── prompt-source.md        # NEW PER ROUND-5 — the three-regime prompt source contract: null-anchor synthetic regime, interior-cap corpus regime, sub-probe corpus regime; corpus paths + SHA pinning; assign_symmetric_prompt operative wiring; ignore_eos parameter plumbing; per-row prompt_source + measurement_regime + prompt_corpus_idx field semantics.
├── spec.md                     # Feature spec (existing, 27 Q/A clarifications across 5 rounds — round 5 added prompt source, ignore_eos handling, KV-pressure sub-probe)
└── tasks.md                    # /speckit-tasks output (NOT created by /speckit-plan)
```

### Source Code (repository root — extending existing layout)

M6.2 adds 8 new modules + 3 modified existing files + 1 new offline script + 1 new corpus artifact. Harness-only; no frontend / proxy / engine path changes.

```text
tools/benchmark/src/vllm_grpc_bench/
├── m6_2_types.py                 # NEW — dataclass definitions extending M6_1_3*: M6_2SweepArtifact (additive top-level fields), M6_2MeasurementPoint (extends per-cell row with max_tokens, block_start_utc, block_end_utc, retry_attempted, prompt_source, measurement_regime, prompt_corpus_idx), M6_2NullAnchor, M6_2CrossoverThreshold, M6_2KVPressureObservation (with sub_probe_n_rpcs + sub_probe_prompt_source + wall_clock_ratio + wall_clock_inference_label + kv_cache_used_fraction_peak + scheduling_stall_signals + oom_observed), M6_2AnchorLatencyTrajectory, M6_2RunMeta (with iteration_order, iteration_discipline_verified, n_per_point, validate_axis_subset, wall_clock_start_utc, wall_clock_end_utc, total_sweep_hours, modal_spend_usd_estimate, chat_corpus_sha256, chat_corpus_path, embed_corpus_sha256, embed_corpus_path). Per data-model.md.
├── m6_2_sweep.py                 # NEW — sweep orchestrator: outer (cell × max_tokens) loop with cohort innermost per FR-030; calls into m6_2_prompt_source.resolve_block_inputs(cell, max_tokens) to get the correct prompt-source regime per block; per-block UTC timestamp capture per FR-032; in-window retry-once per FR-033; FR-031 4h re-anchor invocation; FR-009 network_paths probe co-firing; iteration_discipline_verified machine check at sweep end; FR-004 round-3 deferral gate (refuses `--m6_2` if `--m6_2-n` unset); KV-pressure SUB-PROBE invocation after the main 144-point sweep completes (delegates to m6_2_sub_probe.run_kv_pressure_sub_probe(...)). Inherits M6.0a concurrent dispatch + M6.1.x classifier instrumentation + M6.1.2 4-cohort iteration + M6.1.3 5-segment decomposition verbatim from imported modules.
├── m6_2_reporter.py              # NEW — render_json() / render_markdown() / write_m6_2_report() — mirrors m6_1_3_reporter.py but adds four primary sections (Production latency budget / TPOT curves / Engine-cost decomposition curves / Protocol crossover threshold) + six auxiliary subsections (KV-cache pressure consumes sub-probe results NOT budget-table c=8 rows + Null anchor validation + Anchor latency trajectory + Failure summary + Sweep wall-clock timeline + Method/Background forward-cross-reference). Per-row rendering displays prompt_source + measurement_regime alongside latency fields so operators see which regime produced each row. Four publish-blocking-eligible sweep-level integrity headers + 1 soft iteration-discipline diagnostic rendered conditionally at the top of the markdown body. Validate-mode rendering: interior-cap rows marked `not_validated`; section 4 axis-restricted disclaimer; coarse 4-value crossover vocabulary; "Sweep wall-clock timeline" omitted if sweep < 8h. Sub-probe results render in the "KV-cache pressure" subsection with explicit "forced_cap_ignore_eos_true" regime labels distinguishing them from budget-table c=8 rows. Two-path output routing per FR-015.
├── m6_2_validate.py              # NEW — single CLI entry function run_m6_2(args, *, sweep_mode: Literal["publish", "validate"]); mode-inferred output path per FR-015; records sweep_mode + iteration_order + chat_corpus_sha256 + embed_corpus_sha256 in run_meta; FR-004 round-3 deferral gate enforcement; SC-018 corpus-SHA validation before sweep start (compares the artifact's pending sha256 against the on-disk corpus provenance file).
├── m6_2_crossover.py             # NEW — compute_per_cell_crossover(...) implementing the symmetric mean-in-CI rule per spec round-1 Q3 (geometric, stats-library-free); compute_kv_pressure_inference(...) consuming the KV-pressure SUB-PROBE measurements (NOT budget-table rows) per FR-017a + spec round-3 Q3 + round-5 amendment. Both pure functions; unit-testable.
├── m6_2_anchor_trajectory.py     # NEW — compute_anchor_block(cohorts, ...) for FR-031 lightweight re-anchoring (chat_stream c=1 × max_tokens=10, n=20); compute_anchor_latency_trajectory(snapshots, ...) per-cohort trajectory aggregation; compute_intra_sweep_drift_header_fired(trajectory) → bool per SC-016 (≥ 2 of 4 cohorts drifted). Note: the anchor block uses the SYNTHETIC prompt regime (same as the null-anchor cells) to preserve the M6.1.3 baseline comparison. Pure functions.
├── m6_2_prompt_source.py         # NEW (round-5) — three-regime prompt source helpers. resolve_block_inputs(cell, max_tokens, iter_idx, cohort, base_seed) returns the per-block input parameters: (prompt_text or embed_tensor_bytes, prompt_source label, prompt_corpus_idx, ignore_eos bool, max_tokens). Resolution logic: (a) null-anchor cells (max_tokens ∈ {10, 50}) → synthetic regime (calls m6_rpc_driver._build_chat_prompt(seed) for chat OR m6_1_rpc_driver.build_torch_save_bytes(rpc_index, base_seed) for embed); (b) interior-cap cells → corpus regime (calls symmetric_prompts.assign_symmetric_prompt(iter_idx, cohort, chat_corpus) for chat OR symmetric_prompts.assign_symmetric_prompt(iter_idx, cohort, embed_corpus) for embed); (c) sub-probe blocks → corpus regime + ignore_eos=True. Plus load_chat_corpus() (loads chat_sharegpt_1000.json + verifies SHA against chat_sharegpt_1000.provenance.json), load_embed_corpus() (loads completions_embeds_qwen3_8b/ + verifies SHA against manifest.json), validate_corpus_sha_at_publish_time(...) (SC-018 corpus-drift error firing rule). Pure functions modulo file I/O for corpus loading.
├── m6_2_sub_probe.py             # NEW (round-5) — KV-pressure sub-probe orchestrator per FR-036. run_kv_pressure_sub_probe(rpc_driver, cohorts, base_seed, n=20) runs 16 sub-probe blocks (4 cohorts × 2 cell-types {chat_stream, embed} × 2 caps {1024, 2048}) cohort-innermost per FR-030 within each (cell-type, max_tokens) tuple. Each block sets ignore_eos=True at the SamplingParams layer + uses the FR-034/FR-035 corpus regime via m6_2_prompt_source.resolve_block_inputs(...). Per-block UTC timestamps per FR-032; in-window retry-once per FR-033 (sub-probe blocks are subject to the same retry policy as main-sweep blocks). Returns list[M6_2KVPressureObservation] populated with sub_probe_n_rpcs=20, sub_probe_prompt_source label, wall_p50_ms/wall_p95_ms per cohort × cell-type × cap. The wall-clock-ratio inference itself is computed by m6_2_crossover.compute_kv_pressure_inference(...) consuming the sub-probe rows. Sub-probe runs in BOTH publish and validate modes (the sub-probe is the only path to a meaningful KV-pressure characterization per FR-017a + round-5 Q5 additive contract).
├── m6_1_3_classifier.py          # READ-ONLY — IMPORTED by m6_2_sweep / m6_2_reporter unchanged. M6.2 makes no classifier changes.
├── m6_1_3_audit.py               # READ-ONLY — IMPORTED for audit field propagation; M6.2 carries the audit fields through unchanged per FR-011.
├── m6_1_3_variance.py            # READ-ONLY (helper functions: compute_ci_half_width(samples) used by m6_2_crossover + m6_2_anchor_trajectory).
├── symmetric_prompts.py          # READ-ONLY (cross-milestone helper from M6.1.3) — `assign_symmetric_prompt(iter_idx, cohort, corpus)` is NEWLY WIRED per round-5 FR-008 amendment + FR-034/FR-035 (the function existed in M6.1.3 but was never called from any sweep module; M6.2 makes it operative).
├── m6_1_2_network_probe.py       # READ-ONLY — IMPORTED for FR-009 network_paths topology probe; extended to 4h cadence via m6_2_sweep's invocation pattern (the underlying probe is unmodified).
├── m6_1_1_timing.py              # READ-ONLY — IMPORTED for wire-key extractor; M6.2 adds no new wire keys.
├── m6_1_2_types.py               # READ-ONLY — M6_1_2_COHORTS imported.
├── m6_1_types.py                 # READ-ONLY — M6_1_CELLS imported.
├── m6_1_3_sweep.py               # READ-ONLY — cohorts_at_concurrency() imported.
├── m6_1_3_reporter.py            # UNCHANGED — M6.1.3 reporter stays frozen per the M6.1.x freeze rule on prior milestones.
├── m6_1_3_validate.py            # UNCHANGED.
├── m6_1_3_types.py               # UNCHANGED — extended by m6_2_types.py via additive top-level / per-row fields, not by in-place edit.
├── m6_rpc_driver.py              # MODIFY (round-5) — parameterize `max_tokens` and `ignore_eos` on the chat request builders. Currently `_build_chat_grpc_request(seed)` hardcodes `max_tokens=M6_CHAT_MAX_TOKENS=50` and never sets `ignore_eos`. Change to `_build_chat_grpc_request(seed, *, max_tokens, ignore_eos=False, prompt=None)` — accepts an optional `prompt` parameter (for the corpus regime; defaults to None which falls back to the synthetic `_build_chat_prompt(seed)`), plus the parameterized `max_tokens` and `ignore_eos`. Mirror changes on `_build_chat_rest_payload`. Per-RPC callers in m6_rpc_driver's chat drivers + m6_1_rpc_driver's chat drivers (re-exports from m6_rpc_driver) flow the new parameters through. ~25-40 LOC net new (parameterization + per-RPC plumbing of the new args; the existing call sites in M6 / M6.0a / M6.1 / M6.1.1 / M6.1.2 / M6.1.3 stay binary-compatible because the new parameters are kwargs with M6.1.x-default values).
├── m6_1_rpc_driver.py            # MODIFY (round-5) — parameterize `max_tokens` and `ignore_eos` on the embed request builders. Currently `_build_embed_grpc_request(...)` and `_build_embed_rest_payload_m6_1(...)` hardcode `max_tokens=10` and never set `ignore_eos`. Change to accept `max_tokens` and `ignore_eos` kwargs (M6.1.x-default values preserve backward compatibility for the historical re-runs). Additionally, the corpus-regime call sites need a path to pass pre-computed embeddings from the new ShareGPT-derived corpus instead of synthesizing random tensors per-RPC — add `prompt_embeds_override: bytes | None = None` to the builder signatures; when provided, the builder ships the override bytes instead of calling `build_torch_save_bytes`. ~25-40 LOC net new.
├── corpus.py                     # MODIFY (round-5) — add `load_completions_embeds_qwen3_8b(corpus_dir: Path | None = None) -> list[CompletionEmbedSample]` (the existing `load_completions_corpus("embeds", ...)` is hardwired to the 20-entry hidden_size=1024 corpus; M6.2 needs the new 1000-entry hidden_size=4096 corpus at a different path). Plus `verify_corpus_sha(corpus_path: Path, expected_sha: str) -> None` (SC-018 corpus-drift error helper, raises CorpusDriftError on mismatch). ~30-40 LOC net new.
└── __main__.py                   # MODIFY — argparse wiring for `--m6_2` + `--m6_2-validate` + `--m6_2-*` namespaced sub-flags. Mutual-exclusion against 17 prior mode flags. Round-3 deferral gate (refuse `--m6_2` if `--m6_2-n` unset per FR-004). `--m6_2-asymmetric-prompts` MUST NOT be added per FR-008. No corpus-path CLI flag (corpus paths spec-pinned per FR-034 / FR-035; only operator override would be unsupported corpus). ~80-120 LOC.

packages/frontend/src/vllm_grpc_frontend/
├── chat.py                       # READ-ONLY — UNCHANGED from M6.1.3.
└── completions.py                # READ-ONLY — UNCHANGED from M6.1.3.

scripts/python/
└── gen_embed_corpus_qwen3_8b.py  # NEW (round-5) — adapted from existing scripts/python/gen_embed_corpus.py. Takes the ShareGPT chat corpus (tools/benchmark/corpus/chat_sharegpt_1000.json) as input; feeds each prompt through Qwen3-8B's embedding layer; saves 1000 .pt files at variable seq_len × 4096 (fp16); builds manifest.json with per-entry SHA + source_prompt_id + seq_len + bucket metadata + top-level corpus_sha256. Runs on Modal A10G or local GPU; ~10-30 min compute time. Phase 1 prerequisite per FR-035. ~150-200 LOC.

tools/benchmark/corpus/
├── chat_sharegpt_1000.json                  # EXISTING — M5.2-vintage chat corpus; reused unchanged for the chat interior-cap regime per FR-034.
├── chat_sharegpt_1000.provenance.json       # EXISTING — provenance file with corpus_sha256; read by load_chat_corpus() for SHA validation.
├── completions_embeds/                       # EXISTING (READ-ONLY) — 20-entry hidden_size=1024 corpus; M5.2-vintage; NOT used by M6.2 (incompatible with Qwen3-8B hidden_size=4096).
└── completions_embeds_qwen3_8b/              # NEW (round-5) — 1000-entry hidden_size=4096 embed corpus generated offline by gen_embed_corpus_qwen3_8b.py.
    ├── 0000.pt                                # Per-prompt embedding tensors (variable seq_len × 4096, fp16).
    ├── 0001.pt
    ├── ...
    ├── 0999.pt
    └── manifest.json                          # Per-entry SHA + source_prompt_id + seq_len + bucket + top-level corpus_sha256.

tools/benchmark/tests/
├── test_m6_2_iteration_order.py       # NEW — FR-030 cohort-innermost; FR-032 timestamps + iteration_discipline_verified + wall-clock timeline.
├── test_m6_2_anchor_trajectory.py     # NEW — FR-031 4h cadence + per-cohort drift + SC-016 sweep-level header.
├── test_m6_2_crossover.py             # NEW — symmetric mean-in-CI + edge cases + validate-mode vocabulary.
├── test_m6_2_kv_pressure.py           # NEW — FR-017a wall-clock-ratio from SUB-PROBE rows (not budget-table) + best-effort engine field + cross-validation narrative + OOM observed.
├── test_m6_2_retry_policy.py          # NEW — FR-033 in-window retry + retry-stays-in-window + end-of-sweep retry forbidden.
├── test_m6_2_null_anchor.py           # NEW — FR-012/FR-013 cross-milestone + FR-014 sweep-level header at ≥ 3 of 48.
├── test_m6_2_artifact_schema.py       # NEW — 144-row table + strict-superset compat + validate `not_validated` + per-row prompt_source + measurement_regime + prompt_corpus_idx + run_meta extensions.
├── test_m6_2_cli.py                   # NEW — argparse + defaults + mutual exclusion + round-3 deferral gate + asymmetric-prompts NOT-shipped.
├── test_m6_2_prompt_source.py         # NEW (round-5) — three-regime chat + three-regime embed + assign_symmetric_prompt cohort-invariance + corpus SHA validation (SC-018 drift error).
├── test_m6_2_sub_probe.py             # NEW (round-5) — 16-block contract + n=20 + ignore_eos=True + additive (not in budget table) + FR-017a uses sub-probe rows + runs in both publish + validate modes.
├── test_m6_2_validate_cli.py          # NEW — integration test for --m6_2-validate.
└── test_m6_2_publish_cli.py           # NEW — integration test for --m6_2 --m6_2-n=50.

docs/benchmarks/
├── m6_1_3-attribution-closure.{md,json}   # READ-ONLY (JSON); MODIFY (markdown: single leading note line per FR-019).
├── m6_2-token-budget.{md,json}            # NEW — canonical M6.2 publish artifact.
├── m6_2-token-budget-validate.{md,json}   # NEW — validate sibling.
└── m6_2-events.jsonl                      # NEW — sidecar JSONL with per-block UTC timestamps + retry markers + prompt_source per row.

contracts/instrumentation.md                # MODIFY — extend with M6.2's additive top-level keys + per-row fields (max_tokens, block_start_utc, block_end_utc, retry_attempted, prompt_source, measurement_regime, prompt_corpus_idx) + four publish-blocking-eligible sweep-level integrity-header rules + soft iteration-discipline diagnostic + symmetric mean-in-CI crossover rule + wall-clock-ratio inference rule + three-regime prompt source contract (FR-034/FR-035) + KV-pressure sub-probe contract (FR-036) + corpus SHA validation rule (SC-018) + validate-mode rendering rules + FR-027 project-wide convention propagation.
CLAUDE.md                                   # READ-ONLY — already points at this plan (updated during the prior /speckit-plan run); no change needed this round.
```

**Structure Decision**: M6.2 mirrors M6.1.3's parallel-module pattern (which mirrors M6.1.2 / M6.1.1). A new `m6_2_*` module family lands alongside existing `m6_1_3_*` / `m6_1_2_*` / `m6_1_1_*` families without modifying them. Round-5 adds two new modules to the M6.2 family (`m6_2_prompt_source.py` and `m6_2_sub_probe.py`) and one new offline script (`gen_embed_corpus_qwen3_8b.py`) plus three modified existing files (RPC builders + corpus loader). The cell matrix, cohort tuple, 5-segment decomposition, classifier primitives, audit fields, symmetric-prompts helper (now operative), network_paths probe, and wire extractor are all REUSED by import per FR-006 / FR-007 / FR-008 / FR-010 / FR-011 / FR-027.

Five structural deltas vs M6.1.3 (one more than the prior plan):

1. **`max_tokens` inner axis** — the orchestrator's inner-loop iteration adds a 6-point axis under each (cell, cohort) pair.
2. **Four exogenous-confound controls (FR-030/031/032/033)** — net-new to M6.2; three new modules carry the implementation (`m6_2_anchor_trajectory.py`, FR-032/033 logic in `m6_2_sweep.py`, FR-030 discipline machine-checked in the orchestrator).
3. **Three-regime prompt source split (FR-034/FR-035 — round-5)** — net-new to M6.2; `m6_2_prompt_source.py` carries the regime resolution + corpus loading + SHA validation; `symmetric_prompts.assign_symmetric_prompt` newly wired.
4. **KV-pressure sub-probe (FR-036 — round-5)** — net-new to M6.2; `m6_2_sub_probe.py` carries the sub-probe orchestration; FR-017a operates on sub-probe rows.
5. **No frontend / proxy / engine path changes** — M6.2 is harness-only (RPC builders modified for parameterization but no behavioral change at the call sites that pass M6.1.x defaults).

The 8 new `m6_2_*` modules split by concern: `_types` / `_sweep` / `_reporter` / `_validate` (the standard four), `_crossover` + `_anchor_trajectory` (round-4 additions, pure-function), `_prompt_source` + `_sub_probe` (round-5 additions, pure-function with file I/O for corpus loading + sub-probe orchestration). The split is intentional — each module is unit-testable in isolation.

## Implementation Methodology: Copy-Then-Refactor Pattern (project-wide convention from M6.1.3)

Every new M6.2 module that has an M6.1.3 (or M6.1.2 / M6.1.1) analog MUST be implemented as a **copy-then-refactor**, NOT a from-scratch reimplementation. Mirrors the M6.1.3-plan-§254 project-wide convention per FR-028.

### Per-module copy-source and refactor-delta table

| New module | Copy source | Refactor delta |
|------------|-------------|----------------|
| `m6_2_types.py` | `m6_1_3_types.py` | Rename `M6_1_3*` → `M6_2*` for M6.2-specific types. Add `M6_2SweepMode`, `M6_2MeasurementPoint` (extends per-cell row with max_tokens, block_start_utc, block_end_utc, retry_attempted, **prompt_source, measurement_regime, prompt_corpus_idx — round-5**), `M6_2NullAnchor`, `M6_2CrossoverThreshold`, `M6_2KVPressureObservation` (with **sub_probe_n_rpcs, sub_probe_prompt_source — round-5**), `M6_2AnchorLatencySnapshot/Trajectory`, `M6_2SweepArtifact` (additive top-level fields), `M6_2RunMeta` (additive run_meta fields including **chat_corpus_sha256, chat_corpus_path, embed_corpus_sha256, embed_corpus_path — round-5**). Keep `M6_1_2_COHORTS` + `M6_1_CELLS` imports. |
| `m6_2_sweep.py` | `m6_1_3_sweep.py` | Rename `M6_1_3*` → `M6_2*`. Add 6-point `max_tokens` axis iteration with cohort-innermost per FR-030; per-block UTC timestamp capture per FR-032; in-window retry-once per FR-033; FR-031 4h re-anchor + FR-009 network_paths co-firing; iteration_discipline_verified check; FR-004 round-3 deferral gate; **call into m6_2_prompt_source.resolve_block_inputs(...) per block to get regime-correct prompt + ignore_eos kwargs — round-5**; **invoke m6_2_sub_probe.run_kv_pressure_sub_probe(...) after the 144-point main sweep completes — round-5**. Remove M6.1.3's multi-run loop. Keep cohorts_at_concurrency() import. |
| `m6_2_reporter.py` | `m6_1_3_reporter.py` | Rename. Add four primary sections + six auxiliary subsections; four sweep-level integrity headers + 1 soft diagnostic; validate-mode rendering rules; per-row prompt_source + measurement_regime + prompt_corpus_idx columns **(round-5)**; KV-cache pressure subsection consumes sub-probe results NOT budget-table c=8 rows **(round-5)**; sub-probe results explicitly labeled "forced_cap_ignore_eos_true" regime **(round-5)**. Remove M6.1.3's between-run-variance section + Phase B trigger. Keep cohort_set / cohort_omissions / network_paths inheritance. |
| `m6_2_validate.py` | `m6_1_3_validate.py` | Rename `run_m6_1_3` → `run_m6_2`. Modify output-path inference (canonical vs validate sibling per FR-015); record iteration_order + **chat_corpus_sha256 + embed_corpus_sha256 — round-5** in run_meta. Add FR-004 round-3 deferral gate enforcement. Add **SC-018 corpus-SHA validation before sweep start (round-5)** — load both corpora via m6_2_prompt_source.load_chat_corpus + load_embed_corpus, verify SHAs against on-disk provenance files, raise CorpusDriftError on mismatch. |
| `m6_2_crossover.py` | NEW (no analog) | Net-new: compute_per_cell_crossover(...) per spec round-1 Q3 (symmetric mean-in-CI rule); compute_kv_pressure_inference(...) per FR-017a + round-3 Q3 + **round-5 amendment (consumes SUB-PROBE measurements, not budget-table c=8 rows)**. Pure functions. |
| `m6_2_anchor_trajectory.py` | NEW (no analog) | Net-new: compute_anchor_block(...) lightweight n=20 re-anchor block at chat_stream c=1 × max_tokens=10 (uses SYNTHETIC regime to preserve M6.1.3 baseline comparison); compute_anchor_latency_trajectory(...) per-cohort aggregation; compute_intra_sweep_drift_header_fired(...) per SC-016. Pure functions. |
| `m6_2_prompt_source.py` | **NEW PER ROUND-5 (no analog)** | Net-new: `resolve_block_inputs(cell, max_tokens, iter_idx, cohort, base_seed, ignore_eos_override=None)` returns the per-block input dict (prompt_text or embed_tensor_bytes, prompt_source label, prompt_corpus_idx, ignore_eos bool, max_tokens). Regime resolution per FR-034 (chat) / FR-035 (embed): null-anchor cells → synthetic; interior-cap cells → corpus; sub-probe blocks → corpus + ignore_eos=True via `ignore_eos_override`. Plus `load_chat_corpus()` (loads chat_sharegpt_1000.json + verifies SHA), `load_embed_corpus()` (loads completions_embeds_qwen3_8b/ + verifies SHA), `validate_corpus_sha_at_publish_time()` (SC-018 fail-fast on drift). Calls into `symmetric_prompts.assign_symmetric_prompt(iter_idx, cohort, corpus)` for corpus regimes. Pure modulo file I/O. |
| `m6_2_sub_probe.py` | **NEW PER ROUND-5 (no analog)** | Net-new: `run_kv_pressure_sub_probe(rpc_driver, cohorts, chat_corpus, embed_corpus, base_seed, n=20, sweep_orchestrator_clock)` runs 16 sub-probe blocks (4 cohorts × 2 cell-types × 2 caps) cohort-innermost within each (cell-type, max_tokens) tuple per FR-030. Each block calls `m6_2_prompt_source.resolve_block_inputs(...)` with `ignore_eos_override=True` for the corpus-regime input + sets `ignore_eos=True` at the SamplingParams layer via the modified RPC builder signature. Per-block UTC timestamps per FR-032; in-window retry-once per FR-033. Returns `list[M6_2KVPressureObservation]` populated. The wall-clock-ratio inference + threshold-2.2 comparison are computed by `m6_2_crossover.compute_kv_pressure_inference(...)` consuming the sub-probe rows. Sub-probe runs in both publish and validate modes per SC-019. |
| `test_m6_2_validate_cli.py` | `test_m6_1_3_validate_cli.py` | Rename + retarget assertions to M6.2's validate sibling. Add round-5 assertions: per-row prompt_source field present; KV-pressure subsection consumes sub-probe rows; corpus SHAs in run_meta match on-disk provenance. |
| `test_m6_2_publish_cli.py` | `test_m6_1_3_publish_multirun_cli.py` | Rename + retarget. Remove M6.1.3 multi-run/variance assertions. Add round-5 assertions: full 6-point axis × 4-cohort × 6-cell table; full crossover vocabulary; iteration_discipline_verified=true; wall-clock timeline; sub-probe contract (16 blocks × n=20 × ignore_eos=True). |

### What this methodology does NOT apply to

**Modifications to existing files** (`__main__.py`, **`m6_rpc_driver.py`**, **`m6_1_rpc_driver.py`**, **`corpus.py`** — the latter three new this round per round-5) are **in-place additive edits**, not copy-then-refactor. The RPC-builder modifications add kwargs with M6.1.x-default values so existing call sites stay binary-compatible.

**The new offline script `gen_embed_corpus_qwen3_8b.py`** is adapted from the existing `gen_embed_corpus.py` — light copy-then-refactor (change hidden_size + model + output corpus directory), bounded delta.

**Unit tests for net-new modules** (8 + 2 integration = 10 total) are written against the contracts and data model directly — there's no prior-milestone test to copy.

## Complexity Tracking

> Empty — Constitution Check passed 5/5 with no violations.

Per the project's `feedback_thorough_clarify_cycles` memory, the spec underwent 5 rounds of clarification (27 Q/A bullets total — 6 in round 1, 1 in round 2, 3 in round 3, 5 in round 4, **5 in round 5**) before this plan reached its current state. Round 5's additions (three-regime prompt source split, ignore_eos handling at sub-probe only, KV-pressure sub-probe as additive Story-3 instrument, ShareGPT-derived embed corpus at hidden_size=4096) are bounded by FR-034 / FR-035 / FR-036 + SC-018 / SC-019 / amended FR-003/008/017a. Genuinely new architectural concepts (the three-regime split surface, the sub-probe orchestration, the corpus SHA validation, the `assign_symmetric_prompt` wiring) are each carried by exactly one module + one test file.

**Two open deferrals** (one unchanged from prior plan, one new in round-5 sense):

1. **Publish-mode `n`** (FR-004 / FR-021 / FR-023) — gated on validate-sweep variance data; publish-mode orchestrator MUST refuse `--m6_2` if `--m6_2-n` is unset. Pinned in a future clarify cycle. Unchanged from prior plan.
2. **ShareGPT-derived embed corpus generation** (FR-035) — Phase 1 prerequisite. Implementation deliverable; the corpus MUST exist and be committed before `--m6_2-validate` is invoked. Not a clarify-deferral; an engineering-task-ordering constraint.

---

## Phase 0: Outline & Research

See [`research.md`](./research.md) for the research items and their decisions. All NEEDS CLARIFICATION items were resolved during the 5-round `/speckit-clarify` cycle. Phase 0 captures the implementation-level investigation (R-1 through R-11, with R-9 through R-11 new in this re-run for round-5 items) that complements those spec-level decisions.

**Output**: `research.md` with all NEEDS CLARIFICATION resolved (none in Technical Context).

## Phase 1: Design & Contracts

See [`data-model.md`](./data-model.md), [`contracts/cli.md`](./contracts/cli.md), [`contracts/artifact-schema.md`](./contracts/artifact-schema.md), [`contracts/iteration-order.md`](./contracts/iteration-order.md), [`contracts/wire-vocabulary.md`](./contracts/wire-vocabulary.md), [`contracts/prompt-source.md`](./contracts/prompt-source.md) (NEW round-5), [`quickstart.md`](./quickstart.md).

Agent context update: the SPECKIT plan reference in `/Users/bsansom/projects/vllm-grpc/CLAUDE.md` between the `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers already points at this plan from the prior plan run; no change needed this round.

**Output**: `data-model.md`, `contracts/cli.md`, `contracts/artifact-schema.md`, `contracts/iteration-order.md`, `contracts/wire-vocabulary.md`, `contracts/prompt-source.md`, `quickstart.md`.

## Post-Design Constitution Check

Re-evaluated against the 5 principles after Phase 1 design artifacts were drafted:

| Principle | Status | Post-design notes |
|---|---|---|
| I. Proto-First | **PASS** | Confirmed by [`contracts/wire-vocabulary.md`](./contracts/wire-vocabulary.md) — M6.2 adds zero new wire keys. Round-5's `ignore_eos` parameter is a Python sampling-params keyword, not a `.proto` field. The new embed corpus stores `torch.save` tensors using the existing M6.1.x `prompt_embeds` wire format. Zero `.proto` impact. |
| II. Library Dependency, Not Fork | **PASS** | Confirmed by [`data-model.md`](./data-model.md) + [`contracts/prompt-source.md`](./contracts/prompt-source.md) — every M6.2 edit lands in `tools/benchmark/` or `scripts/python/`. No frontend / proxy / engine path changes. The embed-corpus generator uses `vllm`'s public `LLM` API for the embedding pass — no upstream patching. |
| III. Phase Discipline | **PASS** | Confirmed by [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) + [`contracts/prompt-source.md`](./contracts/prompt-source.md) — schemas match exactly what M6.2 needs. M7 (corpus diversity beyond ShareGPT) / M8 (additional models, max_model_len > 2048) functionality stays out. The new ShareGPT-derived embed corpus is an M6.2 implementation prerequisite, not a corpus-diversity deliverable — ShareGPT IS the M5.2/M6.x corpus; deriving embeddings from it is reuse, not expansion. |
| IV. CI is the Merge Gate | **PASS** | [`quickstart.md`](./quickstart.md) includes the local-lint-chain step + the embed-corpus-generation prerequisite. 10 test files exercise the round-4 confound controls + round-5 prompt source + sub-probe + corpus SHA validation. Integration tests exercise full CLI → orchestrator → reporter without Modal. SC-018 corpus-drift error is CI-verifiable. |
| V. Honest Measurement | **PASS** | [`contracts/prompt-source.md`](./contracts/prompt-source.md) + [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) mandate the round-5 methodology guarantees: (a) FR-034/FR-035 three-regime split exposes what each measurement answers (production EOS vs forced KV ceiling vs M6.1.x-baseline-comparable null anchors); (b) FR-036 sub-probe with `ignore_eos=True` makes the wall-clock-ratio inference meaningful; (c) per-row `prompt_source` + `measurement_regime` + `prompt_corpus_idx` fields make the regime machine-checkable; (d) SC-018 corpus-SHA validation makes the corpus provenance audit-able and fails the post-sweep validator on drift — operator cannot silently swap a corpus mid-cycle. Combined with the round-4 confound controls (FR-030/031/032/033) and the four sweep-level integrity warning channels, the M6.2 artifact surfaces every threat to cohort-comparison validity explicitly. |

**Result: 5/5 PASS post-design. No new complexity introduced.**
