# Phase 0 Research: M6.2 — Token-Budget Characterization

**Branch**: `027-m6-2-token-budget` | **Date**: 2026-05-19 | **Plan**: [plan.md](./plan.md)

## Overview

Phase 0 captures the implementation-level research that complements the spec-level decisions made during the 5-round `/speckit-clarify` cycle (27 Q/A bullets total — 6 in round 1, 1 in round 2, 3 in round 3, 5 in round 4, 5 in round 5). The Technical Context in [`plan.md`](./plan.md) has no `NEEDS CLARIFICATION` markers — every architecturally-significant choice was resolved during clarify. Phase 0 here documents the code-surface investigation needed to write the data model and contracts cleanly.

Two open implementation-side prerequisites (neither blocks Phase 1 / Phase 2):

1. **Publish-mode `n`** (FR-004) — clarify-deferred to a future cycle gated on validate-sweep variance data. The publish-mode orchestrator MUST refuse `--m6_2` invocation until pinned.
2. **ShareGPT-derived embed corpus generation** (FR-035) — engineering deliverable; the corpus MUST exist and be committed before `--m6_2-validate` is invoked. Generated offline via `gen_embed_corpus_qwen3_8b.py`.

## Research Items

### R-1 — M6.1.3 module file set + naming convention inheritance

**Decision**: M6.2 mirrors M6.1.3's parallel-module pattern. Files: `m6_2_types.py`, `m6_2_sweep.py`, `m6_2_reporter.py`, `m6_2_validate.py`, `m6_2_crossover.py`, `m6_2_anchor_trajectory.py`, plus round-5 additions `m6_2_prompt_source.py` and `m6_2_sub_probe.py`. Eight new modules total; each follows the `m6_2_<role>.py` pattern.

**Rationale**: M6.1.1 established the "one module per concern" convention; M6.1.2 inherited it with 5 modules; M6.1.3 inherited with 8 (extra concerns: 7-bucket classifier, pooled audit, between-run variance, shared helper); M6.2 inherits with 8 (the 4 standard `_types`/`_sweep`/`_reporter`/`_validate` modules + 4 net-new pure-function or pure-orchestration modules for crossover, anchor trajectory, prompt source, sub-probe). The parallel-module pattern (vs in-place modification of `m6_1_3_*` files) preserves the M6.1.3 FR-037 freeze rule for historical re-runnability.

**Alternatives considered**:
- Modify `m6_1_3_sweep.py` in-place — REJECTED (breaks M6.1.3 freeze).
- Bundle `_prompt_source` + `_sub_probe` into `m6_2_sweep.py` — REJECTED (test isolation; sub-probe orchestration + corpus-loading I/O are separable concerns from main-sweep iteration).
- Combine `_crossover` + `_prompt_source` into a single "M6.2 helpers" module — REJECTED (the concerns are unrelated — crossover is a pure math function over per-cell rows; prompt-source is corpus loading + regime dispatch with file I/O).

### R-2 — Sweep iteration order: cohort-innermost block iteration (FR-030)

**Decision**: The orchestrator iterates `for cell in M6_1_CELLS: for max_tokens in M6_2_MAX_TOKENS_AXIS: for cohort in cohorts_at_concurrency(cell): for rpc in range(n): ...`. Cohort is innermost per FR-030. The `(cell × max_tokens)` outer-loop order is cells-first then max_tokens within each cell — keeps each cell's per-cohort × per-max_tokens block in a contiguous wall-clock window for reporter clarity.

**Rationale**: Cohort-innermost is the FR-030 spec-level decision (round-4 Q1). Cells-first outer order pairs naturally with the reporter's per-cell rendering and the wall-clock timeline subsection's per-cell readability. The `iteration_discipline_verified` machine check (FR-032) inspects per-block UTC timestamps post-hoc.

**Alternatives considered**:
- Max_tokens-outermost, cells-middle — REJECTED (interleaves cells across the wall clock; harder reporter aggregation).
- Randomized `(cell, max_tokens)` outer order — REJECTED (FR-030 controls between-cohort bias; outer randomization adds noise without methodological benefit).
- Cohort-outermost — FORBIDDEN per FR-030.

### R-3 — Intra-sweep anchor re-measurement implementation (FR-031)

**Decision**: `m6_2_anchor_trajectory.compute_anchor_block(...)` invoked at sweep start, end, and every 4-hour wall-clock mark in publish mode. Block is `chat_stream × c=1 × max_tokens=10`, `n=20`, cohort-innermost. The anchor block uses the **synthetic prompt regime** (the M6.1.x `_build_chat_prompt(seed)` path) — NOT the corpus regime introduced in round-5 — so the anchor measurements stay byte-comparable with M6.1.3's published anchor CIs. Validate-mode (sweep < 8h) runs start + end only.

**Rationale**: 4h cadence aligns with FR-009 `network_paths` for a unified "sweep health check" tick. Cell choice (chat_stream c=1 × max_tokens=10) is cheap, network-sensitive, symmetric. n=20 is sensitive enough at the M6.1.3 CI half-width threshold. Using synthetic prompts (not the corpus regime) at the anchor block preserves the intent of FR-031 — to detect intra-sweep drift relative to the M6.1.3 baseline; switching to corpus prompts would make the trajectory measure prompt-source drift instead of network/temporal drift.

**Alternatives considered**:
- 2h cadence — REJECTED (doubles cumulative overhead without proportional detection benefit).
- Larger anchor block (n=50) — REJECTED (n=20 is already sensitive enough).
- Multiple anchor cells — REJECTED (chat_stream c=1 has highest network sensitivity; doubling cells doubles overhead without detection improvement).
- Corpus-regime anchor block — REJECTED at this layer (would measure prompt-source drift instead of network drift; would also break the M6.1.3-baseline-comparison interpretation).

### R-4 — Per-block UTC timestamp capture (FR-032)

**Decision**: `block_start_utc = datetime.now(UTC).isoformat()` immediately before per-block dispatch loop; `block_end_utc = datetime.now(UTC).isoformat()` immediately after (including any in-window retry). Stored on per-row `M6_2MeasurementPoint`. Iteration sequence accumulated as ordered list for post-hoc `iteration_discipline_verified` check.

**Rationale**: Per-block granularity (not per-RPC) is sufficient for the time-of-day attribution purpose. ISO-8601 is readable, sortable, timezone-explicit. Storage cost negligible.

**Alternatives considered**:
- Per-RPC timestamps — REJECTED (over-granular; inflates artifact ~1 MB unnecessarily).
- Unix timestamps — REJECTED (less readable; lexicographic comparison requires conversion).
- Duration-only (no start/end) — REJECTED (FR-030 discipline check needs WHEN, not just HOW LONG).

### R-5 — In-window retry policy implementation (FR-033)

**Decision**: Per-block dispatch wrapped in try/except catching the canonical transient set (`grpc.RpcError` with retry-eligible codes, `asyncio.TimeoutError`, `httpx.RequestError`, single-RPC engine-OOM-without-crash). One retry within the current `(cell, max_tokens)` tuple's time window. Retry success → `retry_attempted = true`, latency fields populated from retry measurements. Both attempts fail → `failed_<reason>` per FR-029. End-of-sweep retries FORBIDDEN.

**Rationale**: Conservative transient-error scope. Single retry per FR-033. Multiple retries would extend in-window dispatch and risk slipping into the 4h-mark cadence boundary; end-of-sweep retries would violate FR-030.

**Alternatives considered**:
- Retry twice — REJECTED (FR-033 pins count at 1).
- End-of-sweep retry pass — REJECTED at round-4 Q5 (FR-030 violation).
- No retries — REJECTED at round-4 Q5 (transient failures common at multi-day sweeps).

### R-6 — Symmetric mean-in-CI crossover rule implementation (spec round-1 Q3)

**Decision**: `m6_2_crossover.compute_per_cell_crossover(...)` implements the symmetric mean-in-CI rule. For each cell: identify M6.1.3-winning cohort + second-place cohort from the M6.1.3 baseline; iterate the axis in ascending order; check `(winner_p50 ∈ [second_p50 ± second_ci_half]) OR (second_p50 ∈ [winner_p50 ± winner_ci_half])` at each axis point; return smallest where predicate fires. CI half-width = `1.96 × stderr` (95% normal approximation).

Validate-mode operates on the 3-point axis subset `{10, 50, 2048}` and uses the coarse 4-value vocabulary per FR-016. Inputs to the crossover compute are the budget-table rows (interior-cap regime per round-5 FR-034) — NOT the sub-probe rows.

**Rationale**: Geometric, stats-library-free, symmetric (either direction satisfies), unambiguous.

**Alternatives considered**:
- CI-overlap ≥ 50% — REJECTED at round-1 Q3 ("which 50%?" ambiguity).
- Welch's t-test p > 0.05 — REJECTED (stats library dependency).
- Asymmetric mean-in-CI — REJECTED (less conservative).

### R-7 — Wall-clock-ratio KV-pressure inference (FR-017a) — sources from SUB-PROBE per round-5

**Decision**: `m6_2_crossover.compute_kv_pressure_inference(...)` computes `R = wall_p50_ms(c=8, max_tokens=2048) / wall_p50_ms(c=8, max_tokens=1024)` using the **KV-pressure sub-probe rows** (FR-036, round-5), NOT the main-sweep budget-table c=8 rows. The sub-probe sets `ignore_eos=True` so the engine generates to the cap on every RPC; the ratio reflects forced-2048 vs forced-1024 engine cost. `R > 2.2` → `kv_pressure_inferred_<chat_stream|embed>`; otherwise `kv_pressure_not_observable`.

**Rationale (round-5 amendment)**: Round-5 surfaced that the main-sweep budget-table c=8 rows use the natural-EOS regime — Qwen3-8B EOS-samples at ~50-200 tokens regardless of cap on the synthetic probe, AND even with the round-5 ShareGPT corpus regime the natural completion length per prompt varies (no guarantee of cap-reaching generation). The wall-clock-ratio inference is meaningful ONLY when both numerator and denominator reflect actual cap-length generation — the sub-probe is the only measurement that provides that. The 2.2 threshold + the ~2.0 expected baseline are calibrated against forced-cap generation; using natural-EOS rows would produce a degenerate ratio (~1.0 to 1.5 depending on completion length) and the threshold would never fire even under real KV pressure.

Engine-side `kv_cache_used_fraction_peak` extracted best-effort from per-RPC trailing metadata; `None` if absent. Cross-validation narrative.

**Alternatives considered**:
- Use main-sweep c=8 budget-table rows directly — REJECTED at round-5 Q5 (natural-EOS distribution renders threshold moot).
- Inter-token-latency dispersion proxy — REJECTED at round-3 Q3 (complexity without benefit).
- Engine-log scraping — REJECTED at round-3 Q3 (brittle).

### R-8 — Modal preemption recovery + sweep resume at the 20-48h budget

**Decision**: M6.2 inherits the M6.1.3 FR-028 preemption-recurrence threshold (pinned at 2). At the 20-48h budget, mid-sweep preemption is meaningfully more likely than M6.1.x sweeps. Orchestrator's auto-resume re-establishes Modal tunnel + deploy handshake; resumes main iteration at the `(cell, max_tokens, cohort)` block where preemption occurred. Per-block UTC timestamps capture resume time, making time-of-day drift visible; `iteration_discipline_verified` may fire false on significant resume drift (informational; not auto-aborting).

**Rationale**: Pinned threshold (2) is M6.1.3-inherited; tightening risks false-aborts at long wall-clock, relaxing masks repeated infrastructure issues.

**Alternatives considered**:
- Tighten to 1 — REJECTED (false-abort risk).
- Relax to 3 — REJECTED (masks repeated issues).
- Resume-drift abort knob — REJECTED as out-of-scope.

### R-9 — Three-regime prompt source resolution (FR-034 + FR-035 — round-5)

**Decision**: `m6_2_prompt_source.resolve_block_inputs(cell, max_tokens, iter_idx, cohort, base_seed, ignore_eos_override=None)` is the single entry point the sweep orchestrator + sub-probe orchestrator call to get per-block input parameters. The function returns a dict containing `prompt_text` OR `embed_tensor_bytes` (mutually exclusive based on cell-type), `prompt_source` label (one of `synthetic_seed_derived` / `corpus_sharegpt` / `synthetic_random_tensor` / `corpus_sharegpt_embed`), `prompt_corpus_idx` (the `iter_idx` for corpus regimes; `None` for synthetic regimes), `ignore_eos` (`True` if the caller is the sub-probe orchestrator with `ignore_eos_override=True`; `False` otherwise), `max_tokens` (the cap value).

Regime resolution table:

| Cell-type | `max_tokens` | Regime | Builder called | `prompt_source` |
|---|---|---|---|---|
| chat_stream | 10 or 50 (null anchor) | synthetic | `m6_rpc_driver._build_chat_prompt(seed)` | `synthetic_seed_derived` |
| chat_stream | 256, 512, 1024, 2048 (interior cap) | corpus | `symmetric_prompts.assign_symmetric_prompt(iter_idx, cohort, chat_corpus)` | `corpus_sharegpt` |
| chat_stream | sub-probe at c=8 × {1024, 2048} | corpus + `ignore_eos=True` | same as interior-cap | `corpus_sharegpt` |
| embed | 10 or 50 (null anchor) | synthetic random tensor | `m6_1_rpc_driver.build_torch_save_bytes(rpc_index, base_seed)` | `synthetic_random_tensor` |
| embed | 256, 512, 1024, 2048 (interior cap) | corpus | load `.pt` from `completions_embeds_qwen3_8b/{idx:04d}.pt` where `idx = iter_idx % len(corpus)` | `corpus_sharegpt_embed` |
| embed | sub-probe at c=8 × {1024, 2048} | corpus + `ignore_eos=True` | same as interior-cap | `corpus_sharegpt_embed` |

`load_chat_corpus()` and `load_embed_corpus()` both verify the on-disk corpus SHA against the respective provenance files (`chat_sharegpt_1000.provenance.json` and `completions_embeds_qwen3_8b/manifest.json`'s top-level `corpus_sha256`) before returning the corpus list. Mismatch raises `CorpusDriftError`.

**Rationale**: The three-regime split is the round-5 Option D answer. Putting the resolution in a single pure-function module (modulo file I/O for corpus loading) makes it independently testable: unit tests can synthesize calls at each regime and assert the dispatch is correct, without needing a full sweep orchestrator. Calling `assign_symmetric_prompt(iter_idx, cohort, corpus)` for corpus regimes makes the previously-defined-but-never-called helper operative; the function's `cohort` parameter is documented as "intentionally ignored — kept for call-site readability".

`prompt_corpus_idx = iter_idx` for corpus regimes (not `iter_idx % len(corpus)`) so the field captures the raw iteration index; the modular arithmetic happens inside `assign_symmetric_prompt` already.

**Alternatives considered**:
- Per-RPC regime resolution (instead of per-block) — REJECTED (overengineering; the regime is a function of `(cell, max_tokens)` not of individual RPCs within a block).
- Fold prompt-source resolution into `m6_2_sweep.py` — REJECTED (test isolation; the regime logic is reusable by `m6_2_sub_probe.py`).
- Resolve regime by inspecting `ignore_eos` (i.e., infer regime from caller) — REJECTED (`ignore_eos` is a downstream effect; the regime decision IS the upstream cause).
- Use a different cell-type-bucketing structure (e.g., resolve by cell name regex) — REJECTED (the `(cell, max_tokens)` tuple is the natural key; cell-name regex would be fragile to renames).

### R-10 — KV-pressure sub-probe orchestration (FR-036 — round-5)

**Decision**: `m6_2_sub_probe.run_kv_pressure_sub_probe(rpc_driver, cohorts, chat_corpus, embed_corpus, base_seed, n=20, sweep_orchestrator_clock)` runs after the main 144-point sweep completes (in publish mode) or alongside the main 72-point sweep (in validate mode — sub-probe is unconditional per SC-019).

Sub-probe iteration: 16 blocks total = 4 cohorts × 2 cell-types {chat_stream, embed} × 2 caps {1024, 2048}. The orchestrator iterates `for cell_type in (chat_stream, embed): for max_tokens in (1024, 2048): for cohort in cohorts: run_block(...)` — cohort-innermost per FR-030 (within each `(cell_type, max_tokens)` tuple, the 4 cohorts run contiguously).

Each block invokes `m6_2_prompt_source.resolve_block_inputs(cell=f"{cell_type}_c8", max_tokens, iter_idx, cohort, base_seed, ignore_eos_override=True)` to get the corpus-regime input + `ignore_eos=True` kwarg. The RPC builder is called with the new `max_tokens` + `ignore_eos` + `prompt` (or `prompt_embeds_override`) kwargs per the round-5 RPC-builder parameterization. Per-block UTC timestamps captured per FR-032. In-window retry-once per FR-033 (sub-probe blocks subject to the same retry policy as main-sweep blocks; retries stay within the current `(cell_type, max_tokens)` tuple's time window).

Sub-probe output: `list[M6_2KVPressureObservation]` with 8 records (4 cohorts × 2 cell-types) — each carries `wall_clock_ratio_c8_2048_over_1024 = wall_p50_ms(2048) / wall_p50_ms(1024)` per cohort × cell-type, `wall_clock_inference_label` (computed via `m6_2_crossover.compute_kv_pressure_inference(...)` against threshold 2.2), `kv_cache_used_fraction_peak` (best-effort), `oom_observed`, `sub_probe_n_rpcs = 20`, `sub_probe_prompt_source` (`corpus_sharegpt` for chat, `corpus_sharegpt_embed` for embed).

The 16 sub-probe blocks emit per-block measurements only to `KVPressureObservation` (8 records derived from the 16 blocks, since each record aggregates the 1024 + 2048 measurements). They do NOT emit to the main-sweep budget table — the budget table's c=8 × {1024, 2048} rows remain populated by the interior-cap regime per round-5 Q5 additive contract.

**Wall-clock cost**: 16 blocks × n=20 ≈ 320 sub-probe RPCs. At chat_stream c=8 × max_tokens=2048 with `ignore_eos=True`, each RPC is ~8-9 s (concurrent dispatch amortizes 8x). Block wall-clock ~20-25 s. 16 blocks × ~25 s = ~7 minutes lower bound; plus channel setup per cohort and network round-trip overhead, realistic upper bound ~30 min – 1 h. < 2% of the publish wall-clock budget regardless of round-3 main-sweep `n` selection.

**Rationale**: Sub-probe is a self-contained orchestration unit. Putting it in its own module lets it be unit-tested with synthetic timing data without needing the main-sweep orchestrator. Running after the main sweep (in publish mode) keeps the main-sweep wall-clock predictable; running alongside (in validate mode) keeps the validate sweep tightly bounded. The sub-probe IS the only path to FR-017a's meaningful wall-clock-ratio inference, so it MUST run in both modes per SC-019.

**Alternatives considered**:
- Embed sub-probe into `m6_2_sweep.py` as a final iteration step — REJECTED (test isolation; sub-probe has its own n + ignore_eos + scope semantics that differ from the main sweep).
- Run sub-probe before main sweep — REJECTED (the main-sweep `iteration_discipline_verified` check would have to be redesigned to account for the sub-probe's `(cell_type, max_tokens)` blocks not being part of the 144-point matrix; running after the main sweep keeps the discipline check clean).
- Replace budget-table c=8 rows with sub-probe measurements — REJECTED at round-5 Q5 (mixes methodology within the budget table).
- Skip sub-probe in validate mode (run in publish only) — REJECTED at round-5 Q5 (validate is the only mode where FR-017a's KV-pressure inference is exercisable before publish; SC-019 mandates both modes).

### R-11 — Embed corpus offline generation (FR-035 — round-5 prerequisite)

**Decision**: `scripts/python/gen_embed_corpus_qwen3_8b.py` is an adapted version of the existing `scripts/python/gen_embed_corpus.py` that:

1. Loads `tools/benchmark/corpus/chat_sharegpt_1000.json` (the same SHA-pinned ShareGPT corpus used for the chat regime per FR-034).
2. Loads Qwen3-8B (`Qwen/Qwen3-8B`) via `vllm.LLM` with `enable_prompt_embeds=False` (we only need the embedding layer, not generation) OR via direct `transformers.AutoModel` access — investigation needed in implementation but the public-API constraint per Constitution II rules out internal vLLM monkey-patching.
3. For each of the 1000 ShareGPT prompts: tokenize → run through the embedding layer → get a `seq_len × 4096` fp16 tensor → save via `torch.save(...)` to `tools/benchmark/corpus/completions_embeds_qwen3_8b/{idx:04d}.pt`.
4. Compute per-file SHA-256, plus the top-level `corpus_sha256` over the sorted file-SHA list, and write `tools/benchmark/corpus/completions_embeds_qwen3_8b/manifest.json` with per-entry `{id, source_prompt_id, seq_len, bucket, file_sha256, embed_file}` plus top-level `corpus_sha256` + `source_chat_corpus_sha256` + `model` + `hidden_size` + `generated_at_utc`.

Total artifact size: 1000 files × variable `seq_len × 4096 × 2 bytes (fp16)` ≈ avg `seq_len = 80` → ~640 KB/file × 1000 = ~640 MB. Plus the manifest (~200 KB).

Generation runtime: ~10-30 min on Modal A10G or local GPU. Memory: ~16 GB GPU RAM (Qwen3-8B fp16).

**Phase 1 prerequisite**: The corpus MUST exist and be committed to `tools/benchmark/corpus/completions_embeds_qwen3_8b/` (with `manifest.json`) before `--m6_2-validate` is invoked. The `m6_2_validate.py` driver verifies the corpus exists + the SHA matches the artifact's `embed_corpus_sha256` at sweep start (SC-018); a missing corpus or SHA drift fails fast.

**Rationale**: The existing `completions_embeds/` corpus is at hidden_size=1024 (M5.2-vintage, incompatible with Qwen3-8B). Building a new corpus from ShareGPT at hidden_size=4096 keeps the embed-cell regime methodologically consistent with the chat-cell regime (both use ShareGPT-derived inputs). The corpus is a one-time offline artifact — generation cost is bounded (~10-30 min compute, ~$0.50-1 Modal spend) and committed to the repo for reproducibility. Per-file SHA + top-level corpus SHA enables SC-018's drift validation.

**Alternatives considered**:
- Embed at fp32 (8 bytes/element instead of 2) — REJECTED (4x storage cost; ~2.6 GB; the model's prompt_embeds path already accepts fp16 per the M6.1.x precedent).
- Use a different prompt source (e.g., longer-form alignment prompts) — REJECTED at round-5 Q1/Q2 (ShareGPT is the spec-pinned source; consistency with chat regime).
- Embed at hidden_size=1024 (reuse the existing M5.2 corpus structure) — REJECTED (Qwen3-8B's hidden_size IS 4096; the M5.2 corpus is incompatible).
- Generate the corpus on the operator workstation (no GPU) — REJECTED (Qwen3-8B's embedding layer requires ~16 GB VRAM; CPU fallback is impractical at 1000-prompt scale).

## Phase 0 closure

All 11 research items are resolved. No NEEDS CLARIFICATION markers remain. The Technical Context in [`plan.md`](./plan.md) is complete.

Proceed to Phase 1: write/update [`data-model.md`](./data-model.md), [`contracts/cli.md`](./contracts/cli.md), [`contracts/artifact-schema.md`](./contracts/artifact-schema.md), [`contracts/iteration-order.md`](./contracts/iteration-order.md), [`contracts/wire-vocabulary.md`](./contracts/wire-vocabulary.md), [`contracts/prompt-source.md`](./contracts/prompt-source.md) (new round-5), [`quickstart.md`](./quickstart.md). `CLAUDE.md` agent-context reference already points at this plan.
