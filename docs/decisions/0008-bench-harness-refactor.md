# ADR 0008 — Bench-harness refactor: forward-only de-prefix of the milestone-stratified harness (v0.0.1)

**Status:** accepted (2026-05-30) · feature `specs/029-post-m6.2-cleanup-v0.0.1/` · see also ADR [0006](0006-cli-keep-bench-add-sweep.md) (CLI) and [0007](0007-m3-sweep-servicer-relocation.md) (servicer relocation)

> **Numbering note.** The feature's `tasks.md` (T025) named this ADR `0006-bench-harness-refactor.md`. By the time it was authored, `0006` and `0007` had already been taken by the two mid-flight course-correction ADRs written during T018/T020, so this lands as **0008**. It is the *primary* ADR for the refactor; 0006/0007 are its two in-flight corrections.

## Context

After M6.2 closed, `tools/benchmark/` carried every milestone's sweep harness
side-by-side: **84 source modules / 137 test files**, the large majority named by
milestone (`m3_*`, `m4_*`, `m5_*`, `m5_1_*`, `m5_2_*`, the `m6_*` / `m6_1_*` /
`m6_1_1_*` / `m6_1_2_*` / `m6_1_3_*` families, and the live `m6_2_*` family). The
milestone stratification was load-bearing during the research beats — each milestone
froze the prior one's harness so results stayed reproducible — but on `main` it left
a maintainer facing a tree organized by *when code was written* rather than *what it
does*, with duplicate cohort enums, two divergent chat-prompt builders, and an M1-era
reporter intermixed with the M6.2 one.

The constitution requires an ADR for non-obvious architectural choices. Several
choices here are non-obvious and irreversible-on-`main` (BC breaks), so they are
recorded here, citing `research.md` (R1–R8) for the supporting analysis.

## Decision

Refactor the live tree into a **forward-only codebase organized by function, not by
milestone** — no backward-compat shims, re-export aliases, dead enum members, dual
code paths, or milestone prefixes "just in case." Recovery of anything removed is
delegated entirely to the `milestone/m*` tags (R8 / SC-007), which frees `main` to be
optimized purely as a clean forward tree.

The non-obvious sub-decisions:

1. **Three-disposition model, not a flat "hoist 4 homes + delete"** (research R2).
   The live→legacy import map (R1) showed legacy modules carry live *helper
   functions*, not just types, so a flat hoist would either leave the `m6_2_` prefix
   or strand live helpers. Each legacy module gets exactly one of:
   - **De-prefix** (rename the whole live module): `m6_2_sweep`→`sweep`,
     `m6_2_rpc_driver`→`rpc_driver`, `m6_2_validate`→`validate`, `…resume`,
     `…crossover`, `…null_anchor`, `…anchor_trajectory`, `…sub_probe`,
     `m6_1_1_timing`→`timing`, `m6_1_2_network_probe`→`network_probe`,
     `m6_engine_cost`→`engine_cost`, `m6_1_seq_len`→`seq_len`.
   - **Merge** into a generic home / de-prefixed module (fold content, delete source):
     `m6_2_types`→`types`, `m6_2_reporter`→`reporter`, `m6_2_prompt_source`→`prompts`,
     plus the live helpers of `m6_rpc_driver`/`m6_1_rpc_driver`.
   - **Hoist-then-delete** (few live symbols in an otherwise-legacy module):
     `RPCResult` from `m6_sweep`, the cohort web from `m6_1_2_types`/`m6_1_types`,
     `SchemaValidationFailed` from `m5_2_regen`, the timing surface, the prompt
     default — moved **in-place** into the four homes, then the source `git rm`'d.
   *Alternative rejected:* the literal PLAN Step-A/B/C flat hoist — would leave the
   `m6_2_` prefix and miss the reduction target.

2. **Four generic homes created first, additively** (research R7 ordering). `types.py`,
   `prompts.py`, `timing.py`, `exceptions.py` have no inbound legacy deps, so they were
   created and populated before anything imported them — keeping every intermediate
   step green under `mypy --strict` + `ruff` (bisectable, FR-008).

3. **`CohortKind` collapses to 4 members** (research R3 / clarify Q1). `M5_2CohortKind`
   was 6 members; the forward `m6_2_*` family already used the 4-member subset
   (`rest_https_edge`, `rest_plain_tcp`, `default_grpc`, `tuned_grpc_multiplexed`). The
   home `types.CohortKind` is the 4-member literal; `symmetric_prompts` was repointed
   and its dead `tuned_grpc_channels`/`tuned_grpc` branches stripped (forward-only).

4. **One `reporter.py`, one chat-prompt builder, one schema-error type** (R4 + SC-003).
   The two divergent chat-prompt builders unify to a single seed+digest
   `build_chat_prompt(seed)` in `prompts.py` (the M5.2 `iteration`/`cell_id` builder is
   dropped; `rest_cohort` repointed — a deliberate prompt-byte BC break). The reporter
   consolidates to a single module.

5. **Forward-only / no-BC-shims policy.** Breaking backward compatibility is an
   explicit, accepted goal — module names, import paths, the CLI surface, and the
   prompt bytes a cohort sends all change with **no** compatibility aliases. Defensible
   *because* every break is backed by a `milestone/m*` tag (R8).

6. **Data-pointer-preservation rule** (research R5 / SC-010). *Code* de-prefixes;
   milestone-named **data paths do not.** The published deliverable
   `docs/benchmarks/m6_2-token-budget.{json,md}`, the baseline-chain JSON inputs the
   sweep reads at runtime (e.g. `m6_1_3-attribution-closure.json`), and `validate`'s
   hardcoded `_CANONICAL_*` / `_VALIDATE_*` path constants stay verbatim — de-prefixing
   them would orphan published artifacts and break `validate`'s compare-against-canonical
   step. Re-targeting output names is M7 scope.

## Consequences

- **Headline reduction:** 84→**35** source modules (−58%), 137→**41** test files
  (−70%). The exact count is *directional* (research R2 / SC-002) — thin modules merge
  only where cohesion genuinely improves; no contrived merges to hit a number. The
  result lands above the early "~25/~35" estimate because ADR 0006/0007 retained more
  surface than first planned (see below).
- **Hard invariants met (SC-001/SC-003, contract I3):** zero milestone-prefixed module
  names, zero milestone-prefixed import statements across `src`+`tests` (literal zero,
  no carve-outs), exactly one `CohortKind` (4 members), one chat-prompt builder, one
  reporter, one schema-error type.
- **Two mid-flight corrections,** surfaced by the `mypy --strict` forcing function and
  the retained-tooling audit, recorded as their own ADRs:
  - **ADR 0006** — the literal "sweep is the *default* invocation" collided with the
    README/Makefile-documented `bench` (proxy-vs-native) default + `compare*`
    subcommands, which the spec *retains*. Resolved: keep `bench` as the no-arg default
    + `compare*`; the de-prefixed sweep is a new `sweep` subcommand. Makefile admitted
    to the FR-018 edit fence.
  - **ADR 0007** — `m3_sweep` was *not* pure legacy: it held the live `ChatServicer`/
    `CompletionsServicer` deployed by the out-of-fence Modal bench scripts. Relocated to
    a new retained `grpc_servicers.py`; the M1 `bench` reporter writers
    (`write_json`/`write_csv`/`write_summary_md`) were likewise found live and **kept**,
    not deleted as R4 originally predicted.
- **BC breaks (all recoverable via `milestone/m*` tags):** renamed modules/import
  paths; changed REST-cohort prompt bytes; dropped `tuned_grpc_channels`/`tuned_grpc`
  cohort members; flat CLI (old `--mN` invocations no longer parse). Documented for
  users in `ANALYSIS.md` → "Bench-harness refactor (v0.0.1)" (FR-015).
- **Symbol-name de-prefix — APPROVED (2026-05-30), not deferred.** The Phase 3 de-prefix
  (T009–T018) renamed module names + imports only; milestone-flavored *symbol* names
  (`M6_2SweepArtifact`, `M6_2_MAX_TOKENS_AXIS`, the `M6_1_2_COHORTS`/`M6_1Path` home
  aliases, `M5_2*`, …) were left intact, and whether to also rename the ~30 public symbols
  was raised as a decision-gated task (T028a). **The owner decided to proceed with the
  symbol cleanup** — so v0.0.1 carries milestone-agnosticism through to the *symbol* level,
  not just imports. SC-003 is therefore interpreted at the symbol level: no public symbol
  in the harness carries a milestone prefix. (Had it been declined, SC-003 would have meant
  only import-level agnosticism.) The mechanical rename is executed under T028a (one symbol
  cluster at a time, gate green after each, collisions like `Path`/`Cell` resolved first);
  every rename is a tag-recoverable BC break, consistent with the forward-only policy above.

## References

- `specs/029-post-m6.2-cleanup-v0.0.1/research.md` — R1 (import surface), R2
  (disposition model), R3 (cohort collapse), R4 (reporter), R5 (data pointers), R7
  (bisectable ordering), R8 (recoverability), Decisions summary.
- `specs/029-post-m6.2-cleanup-v0.0.1/spec.md` — FR-004/006/015/016/018a, SC-001/002/003/007/010.
- ADR 0006 (CLI), ADR 0007 (servicer relocation) — the two in-flight corrections.
