# Phase 0 Research: v0.0.1 — Bench-harness refactor

**Date**: 2026-05-29
**Method**: Static import analysis of `tools/benchmark/src/vllm_grpc_bench/*.py` (Python AST-level grep of every `from … import` / `import …` statement), partitioning modules into a **live set** (the `m6_2_*` family + non-milestone-prefixed shared infra) and a **legacy set** (everything `m3`/`m4`/`m5`/`m6`-prefixed except `m6_2_*`), then enumerating every live→legacy edge.

## R1 — The live→legacy import surface (resolves spec's "full hoist set" deferral)

Two distinct kinds of legacy import in the live set:

**(a) `__main__.py` legacy-CLI dispatch** — ~30 imports of legacy sweep/reporter/smoke/supersede modules (`m4_sweep`, `m5_sweep`, `m5_1_sweep`, `m5_2_sweep`, `m5_2_symmetry`, `m6_sweep`, `m6_reporter`, `m6_smoke`, `m6_supersede`, `m6_types`, `m6_rpc_driver`, `m6_1_sweep`, `m6_1_smoke`, `m6_1_supersede`, `m6_1_torch_pin`, `m6_1_1_diagnose`, `m6_1_1_phase2`, `m6_1_2_validate`, `m6_1_3_validate`, plus `m3_types.{M4SweepConfig,PacingMode}`, `m3_sweep`, `m4_sweep`). **Decision**: these are *removed*, not hoisted — they are the `--m3`…`--m6_1_3` CLI dispatch branches that FR-018a deletes. Resolving the tangle here is a *deletion*, which is why `__main__` shrinks dramatically rather than gaining hoisted imports.

**(b) genuine live helper/type dependencies** — the live forward harness (`m6_2_*` + shared infra that survives) imports real symbols from legacy modules. This is the actual hoist surface:

| Legacy module | Live importers | Live symbols used |
|---|---|---|
| `m3_types` | `m6_2_rpc_driver`, `modal_endpoint`, `reporter`, `rest_cohort`, `rtt_probe`, `symmetric_prompts`, `ttft` | `RTTRecord`, `EndpointTuple`, `RunCohort`, `M5_2CohortKind`, `NetworkPath`, `Path_`, `RESTCohortRecord`, `RestHttpsEdgeCohortRecord` (+ M1-era types used only by the M1-era reporter → deleted, see R4) |
| `m3_sweep` | `m6_2_rpc_driver`, `rest_cohort` | `_client_kwargs`, `DEFAULT_CHAT_MAX_TOKENS`, `build_chat_prompt` |
| `m6_1_2_types` | 10 `m6_2_*` modules | `M6_1_2_COHORTS`, `M6_1_2CohortKind`, `cohorts_at_concurrency`, `M6_1_2CloudProvider`, `M6_1_2NetworkPath`, `M6_1_2NetworkPathError`, `M6_1_2NetworkPathHop`, `M6_1_2CohortOmissions` |
| `m6_1_types` | `m6_2_reporter`, `m6_2_rpc_driver`, `m6_2_sweep`, `m6_2_validate` | `M6_1_CELLS`, `M6_1Cell`, `M6_1Path` |
| `m6_1_1_timing` | `m6_2_rpc_driver`, `rest_cohort` | `extract_grpc_timings`, `extract_rest_timings`, `timing_checkpoint_to_payload` |
| `m6_engine_cost` | `m6_2_rpc_driver` | `parse_grpc_trailing_metadata`, `parse_rest_response` |
| `m6_rpc_driver` | `m6_2_rpc_driver`, `m6_2_prompt_source` | `_build_chat_grpc_request`, `_build_chat_rest_payload`, `_rest_rtt_probe`, `_build_chat_prompt` |
| `m6_1_rpc_driver` | `m6_2_rpc_driver` | `_build_embed_grpc_request`, `_build_embed_rest_payload_m6_1`, `_normalize_rest_url_for_httpx`, `_resolve_rpc_index` |
| `m6_sweep` | `m6_2_rpc_driver` | `RPCResult` |
| `m6_1_2_network_probe` | `m6_2_validate` | `run_topology_probe` (module is 675 LOC, mostly live) |
| `m6_1_seq_len` | `m6_2_validate` | `pin_seq_len_at_sweep_start` (90 LOC) |
| `m5_2_regen` | `reporter` | `M5_2SchemaValidationFailed` |

## R2 — Legacy-module disposition (resolves "shared-module survive/merge" + "de-prefix map")

Every legacy module gets exactly one disposition:

**De-prefix (rename whole module; it is live forward code):**

| From | To | Rationale |
|---|---|---|
| `m6_2_sweep` | `sweep.py` | the live sweep orchestrator |
| `m6_2_rpc_driver` | `rpc_driver.py` | live drivers; absorbs live helpers from `m6_rpc_driver` + `m6_1_rpc_driver` (R3) |
| `m6_2_validate` | `validate.py` | live validate/smoke entry; canonical-path constants preserved (R5) |
| `m6_2_resume` | `resume.py` | live resume logic |
| `m6_2_crossover` | `crossover.py` | live crossover analysis |
| `m6_2_null_anchor` | `null_anchor.py` | live anchor logic |
| `m6_2_anchor_trajectory` | `anchor_trajectory.py` | live anchor logic |
| `m6_2_sub_probe` | `sub_probe.py` | live sub-probe |
| `m6_1_1_timing` | `timing.py` | satisfies the FR-001 `timing.py` home; module is ~all live |
| `m6_1_2_network_probe` | `network_probe.py` | 675 LOC, `run_topology_probe` live for `validate` |
| `m6_engine_cost` | `engine_cost.py` | live cost parsers (merge candidate → `metrics.py`) |

**Merge into a generic home / de-prefixed module (content folded, source deleted):**

| From | Into | Symbols |
|---|---|---|
| `m6_2_types` | `types.py` | all M6.2 dataclasses/enums |
| `m6_2_reporter` | `reporter.py` | M6.2 report builders (replaces M1-era reporter content, R4) |
| `m6_2_prompt_source` | `prompts.py` | prompt-source wiring + unified builder |
| `m6_1_seq_len` | `sweep.py` | `pin_seq_len_at_sweep_start` (single function, called at sweep start) |
| live helpers of `m6_rpc_driver` | `rpc_driver.py` / `prompts.py` | chat request/payload builders; `_build_chat_prompt` → unified builder in `prompts.py` |
| live helpers of `m6_1_rpc_driver` | `rpc_driver.py` | embed request/payload builders, url normalizer, rpc-index resolver |

**Hoist symbols then delete (legacy module, few live symbols):**

| From | Hoist to | Then |
|---|---|---|
| `m3_types` | `types.py` (live types), `exceptions.py` (none) | delete; M1-era types (R4) deleted, not hoisted |
| `m3_sweep` | `prompts.py` (`DEFAULT_CHAT_MAX_TOKENS`, `build_chat_prompt`→unified), `channel_config.py` (`_client_kwargs`) | delete |
| `m6_1_types` | `types.py` (`M6_1_CELLS`→`CELLS`, `M6_1Cell`→`Cell`, `M6_1Path`→`Path`) | delete |
| `m6_1_2_types` | `types.py` (`COHORTS`, `CohortKind`, `cohorts_at_concurrency`, cloud/network types) | delete |
| `m6_sweep` | `types.py` (`RPCResult`) | delete |
| `m5_2_regen` | `exceptions.py` (`SchemaValidationFailed`) | delete |

**Delete outright (zero live importers — pure legacy + tests):** all remaining `m4_*`, `m5_*`, `m5_1_*`, `m5_2_*` (except the one `m5_2_regen` symbol), `m6_reporter`, `m6_smoke`, `m6_seed`, `m6_supersede`, `m6_types`, `m6_rpc_driver` (after helper extraction), `m6_1_sweep`, `m6_1_smoke`, `m6_1_seed`, `m6_1_supersede`, `m6_1_torch_pin`, `m6_1_drift_check`, `m6_1_reporter`, `m6_1_1_*` (except `timing`), `m6_1_2_*` (except `network_probe`), `m6_1_3_*`.

> **Open audit item (deferred to implementation, low-risk):** `m6_1_torch_pin` (torch-version gate) is imported only by `__main__`'s deleted `m6`/`m6_1` CLI branches. If the surviving `validate`/`sweep` real-engine path needs the torch-pin gate, de-prefix it to `torch_pin.py`; otherwise delete. Default: delete unless `validate` references it. Same audit for `compare.py` and `ci.py` (M1-era shared tools — keep if a surviving CLI path uses them, else delete).

## R3 — CohortKind collapse (implements clarify Q1)

`M5_2CohortKind` = 6 members; `M6_1_2CohortKind` = 4 (a strict subset). Only `symmetric_prompts` imports the 6-member `M5_2CohortKind`; all 10 live `m6_2_*` importers use the 4-member `M6_1_2CohortKind`. **Decision**: `types.CohortKind = Literal["rest_https_edge","rest_plain_tcp","default_grpc","tuned_grpc_multiplexed"]` (4 members). `symmetric_prompts` is repointed; the dropped `tuned_grpc_channels`/`tuned_grpc` are recoverable via the M5.2 tag. Aliases `M6_1_2_COHORTS`→`COHORTS`, `cohorts_at_concurrency` retained (renamed) in `types.py`.

## R4 — Reporter consolidation (implements clarify Q4 + FR-005)

`reporter.py` today is the **M1-era** reporter (`write_json`/`write_csv`/`write_summary_md`/`write_cross_run_md`/`write_wire_size_comparison_md`) pulling ~11 M1-era types from `m3_types` (`CellVerdict`, `Citation`, `M5_1Cell`, `Recommendation`, `Run`, `SchemaCandidateResult`, `SupersedesM1Entry`, `SupersedesM4Entry`, `SupersessionEntry`, …). These are consumed only by the legacy CLI paths being deleted. **Decision**: the consolidated `reporter.py` takes the **M6.2** reporter's content (de-prefixed from `m6_2_reporter`); the M1-era functions and their M1-era `m3_types` dependencies are deleted (not hoisted to `types.py`). Net: one `reporter.py`, no M1-era report vocabulary. (Verify at implementation that no surviving path calls `write_summary_md` et al.; the live `m6_2` reporter is self-contained.)

## R5 — Data pointers preserved (implements clarify Q6 + FR-019)

Confirmed three classes of milestone-named path the refactor must **not** touch:
- **Baseline inputs** (sweep reads): default `docs/benchmarks/m6_1_3-attribution-closure.json` anchor + the M3→M6.1.x chain (the 9 JSONs retained by v0.0.0's FR-003).
- **Published deliverable**: `docs/benchmarks/m6_2-token-budget.{json,md}` on disk, ANALYSIS-linked.
- **Validate constants** (`m6_2_validate.py` → `validate.py`): `_CANONICAL_JSON/_CANONICAL_MD = "docs/benchmarks/m6_2-token-budget.{json,md}"`, `_VALIDATE_JSON/_VALIDATE_MD = "…-validate.{json,md}"`. `validate` *compares against* the canonical deliverable; de-prefixing the constant would point it at a nonexistent file. **Decision**: code de-prefixes, these string constants stay verbatim. Re-targeting to a new milestone's artifacts is M7 scope.

## R6 — CLI surface (implements clarify Q5 + FR-018a)

`__main__.py` exposes milestone flag groups for `--m3`…`--m6_1_3` (≈30 groups, 72 `args.mN` dispatch references) plus ~16 `--m6_2-*` flags. **Decision**: remove every `--mN` flag and its argparse subparser/dispatch branch (they call deleted code); rename the surviving `--m6_2-*` flags to generic (`--m6_2-modal-region`→`--modal-region`, `--m6_2-n`→`--n`, `--m6_2-validate`→`--validate`, `--m6_2-resume`→`--resume`, `--m6_2-skip-deploy`→`--skip-deploy`, etc.); drop the `--m6_2` selector entirely so the de-prefixed sweep is the **default** invocation (`python -m vllm_grpc_bench [--modal-region …]`). Full rename table in `contracts/cli-surface.md`. BC break; old invocations recoverable via M6.2 tag.

## R7 — Bisectable ordering (supports FR-008)

The dependency DAG dictates the safe order (each step green under `mypy --strict` + `ruff` before the next):
1. **Create generic homes** with hoisted symbols (`types.py`, `prompts.py`, `timing.py`, `exceptions.py`) — additive, nothing imports them yet.
2. **Unify the chat-prompt builder** in `prompts.py`; repoint `rest_cohort` (BC break lands here, isolated).
3. **Repoint shared infra** (`reporter`→will-consolidate, `rest_cohort`, `modal_endpoint`, `rtt_probe`, `ttft`, `symmetric_prompts`, `channel_config`) at the homes.
4. **De-prefix the live modules** one at a time (rename + repoint), absorbing legacy helpers (`m6_rpc_driver`/`m6_1_rpc_driver`→`rpc_driver`, `m6_1_seq_len`→`sweep`).
5. **Consolidate the reporter** (`m6_2_reporter`→`reporter.py`; delete M1-era content).
6. **Strip the CLI** (remove `--mN`, rename `--m6_2-*`, drop selector).
7. **Delete legacy modules + rename tests** (now zero importers remain).
8. **Docs + tag** (`ANALYSIS.md` subsection; `v0.0.1` annotated tag at merge).

## R8 — Recoverability (supports FR-014 / SC-007)

All 16 `milestone/m*` tags (M2→M6.2) confirmed present locally and on origin (created/pushed in v0.0.0). `git show milestone/m5.2-transport-tuning:tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py` returns content; the M5.2 prompt builder and 6-member cohort enum live there. No tag is created or moved by v0.0.1 except the new `v0.0.1` at merge.

## Decisions summary

- **Decision**: three-disposition model (de-prefix / hoist-then-delete / delete) over a flat "hoist 4 homes + delete." **Rationale**: the import map shows legacy modules carry live *helper functions*, not just types, so several need whole-module de-prefix or function-level merge. **Alternative rejected**: literal PLAN Step A/B/C (would leave `m6_2_` prefix and miss the ~25 target).
- **Decision**: `__main__` legacy tangle resolved by deletion, not hoist. **Rationale**: those imports drive deleted CLI subcommands. **Alternative rejected**: keeping legacy CLI (violates forward-only + FR-018a).
- **Decision**: consolidated `reporter.py` = M6.2 content; M1-era reporter deleted. **Rationale**: M1-era functions serve only deleted paths. **Alternative rejected**: hoisting M1-era report types to `types.py` (dead vocabulary, violates FR-009 spirit).
- **Decision**: data pointers stay milestone-named. **Rationale**: re-targeting is M7 scope; renaming orphans artifacts + breaks `validate`. **Alternative rejected**: de-prefix output names (breaks the baseline chain and ANALYSIS links).
