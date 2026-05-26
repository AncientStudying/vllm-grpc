# Data Model: v0.0.0 — Post-M6.2 Housekeeping

**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Research**: [research.md](./research.md)
**Date**: 2026-05-26

This feature has no runtime data model (no persisted entities, no database). The "data model" here is the **set of inputs and outputs that the cleanup operates on** — concrete file paths, tags, and configuration rules — captured in four tables. The tasks artifact references this document by row.

---

## Entity 1 — Deletion manifest

One row per file the cleanup removes (whether by `git rm` for tracked content or `git rm --cached` for index-only entries). Each row carries enough context that a reviewer can audit "is this safe to delete?" without leaving the table.

**Schema**: `{ path, action, owning_milestone_tag, on_disk_after, size_bytes_approx, commit_group }`

- `path` — repo-relative path. Slash-prefixed when at repo root.
- `action` — `git rm` (untrack + delete from working tree), `git rm --cached` (untrack but keep on disk), or `git rm` followed by intentional regeneration (none in v0.0.0).
- `owning_milestone_tag` — the `milestone/*` tag that exposes the deleted content for recovery. Required.
- `on_disk_after` — whether the file stays present on the operator's local working tree after the operation. `false` for `git rm` (file is removed); `true` for `git rm --cached` (file is kept).
- `size_bytes_approx` — order-of-magnitude size of the deletion target, for SC-002 verification.
- `commit_group` — which of the five PR commits this row lands in.

### Manifest rows (67 total)

| # | path | action | owning_milestone_tag | on_disk_after | size_bytes_approx | commit_group |
|---|------|--------|---------------------|---------------|-------------------|--------------|
| 1 | `M6_2-ANALYSIS-FRAMING-DRAFT.md` | `git rm` | n/a (content already merged into `ANALYSIS.md` at `fea31c0`; reachable via `milestone/m6.2-token-budget`) | false | 16 384 | 1 |
| 2 | `docs/benchmarks/phase-3-modal-comparison.md` | `git rm` | `milestone/m3-replan` | false | — | 1 |
| 3 | `docs/benchmarks/phase-3-modal-grpc-baseline.json` | `git rm` | `milestone/m3-replan` | false | — | 1 |
| 4 | `docs/benchmarks/phase-3-modal-grpc-baseline.md` | `git rm` | `milestone/m3-replan` | false | — | 1 |
| 5 | `docs/benchmarks/phase-3-modal-rest-baseline.json` | `git rm` | `milestone/m3-replan` | false | — | 1 |
| 6 | `docs/benchmarks/phase-3-modal-rest-baseline.md` | `git rm` | `milestone/m3-replan` | false | — | 1 |
| 7 | `docs/benchmarks/phase-4.2-grpc-direct-baseline.json` | `git rm` | `milestone/m2-ground-truth` | false | — | 1 |
| 8 | `docs/benchmarks/phase-4.2-grpc-direct-baseline.md` | `git rm` | `milestone/m2-ground-truth` | false | — | 1 |
| 9 | `docs/benchmarks/phase-4.2-grpc-proxy-baseline.json` | `git rm` | `milestone/m2-ground-truth` | false | — | 1 |
| 10 | `docs/benchmarks/phase-4.2-rest-baseline.json` | `git rm` | `milestone/m2-ground-truth` | false | — | 1 |
| 11 | `docs/benchmarks/phase-4.2-three-way-comparison.md` | `git rm` | `milestone/m2-ground-truth` | false | — | 1 |
| 12 | `docs/benchmarks/phase-5-grpc-direct-streaming.json` | `git rm` | `milestone/m2-ground-truth` | false | — | 1 |
| 13 | `docs/benchmarks/phase-5-grpc-proxy-streaming.json` | `git rm` | `milestone/m2-ground-truth` | false | — | 1 |
| 14 | `docs/benchmarks/phase-5-rest-streaming.json` | `git rm` | `milestone/m2-ground-truth` | false | — | 1 |
| 15 | `docs/benchmarks/phase-5-streaming-comparison.md` | `git rm` | `milestone/m2-ground-truth` | false | — | 1 |
| 16 | `docs/benchmarks/phase-6-completions-comparison.md` | `git rm` | `milestone/m2-ground-truth` | false | — | 1 |
| 17 | `docs/benchmarks/phase-6-completions-grpc-direct.json` | `git rm` | `milestone/m2-ground-truth` | false | — | 1 |
| 18 | `docs/benchmarks/phase-6-completions-native.json` | `git rm` | `milestone/m2-ground-truth` | false | — | 1 |
| 19 | `docs/benchmarks/phase-6-completions-proxy.json` | `git rm` | `milestone/m2-ground-truth` | false | — | 1 |
| 20 | `docs/benchmarks/m3-channel-tuning-time.json` | `git rm` | `milestone/m3-phase-a-closure` | false | — | 1 |
| 21 | `docs/benchmarks/m3-channel-tuning-time.md` | `git rm` | `milestone/m3-phase-a-closure` | false | — | 1 |
| 22 | `docs/benchmarks/m3-channel-tuning.json` | `git rm` | `milestone/m3-grpc-tuning-r1` | false | — | 1 |
| 23 | `docs/benchmarks/m3-channel-tuning.md` | `git rm` | `milestone/m3-grpc-tuning-r1` | false | — | 1 |
| 24 | `docs/benchmarks/m4-time-axis-tuning.json` | `git rm` | `milestone/m4-time-axis` | false | — | 1 |
| 25 | `docs/benchmarks/m4-time-axis-tuning.md` | `git rm` | `milestone/m4-time-axis` | false | — | 1 |
| 26 | `docs/benchmarks/m5-cross-host-validation.json` | `git rm` | `milestone/m5-cross-host` | false | — | 1 |
| 27 | `docs/benchmarks/m5-cross-host-validation.md` | `git rm` | `milestone/m5-cross-host` | false | — | 1 |
| 28 | `docs/benchmarks/m5_1-rest-vs-grpc.json` | `git rm` | `milestone/m5.1-rest-vs-grpc` | false | — | 1 |
| 29 | `docs/benchmarks/m5_1-rest-vs-grpc.md` | `git rm` | `milestone/m5.1-rest-vs-grpc` | false | — | 1 |
| 30 | `docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz` | `git rm` | `milestone/m5.2-transport-tuning` | false | — | 1 |
| 31 | `docs/benchmarks/m5_2-transport-vs-tuning.json` | `git rm` | `milestone/m5.2-transport-tuning` | false | — | 1 |
| 32 | `docs/benchmarks/m5_2-transport-vs-tuning.md` | `git rm` | `milestone/m5.2-transport-tuning` | false | — | 1 |
| 33 | `docs/benchmarks/m6-real-engine-mini-validation.json` | `git rm` | `milestone/m6-real-engine-mini` | false | — | 1 |
| 34 | `docs/benchmarks/m6-real-engine-mini-validation.md` | `git rm` | `milestone/m6-real-engine-mini` | false | — | 1 |
| 35 | `docs/benchmarks/m6_0a-dispatch-correction.md` | `git rm` | `milestone/m6.0a-concurrent-dispatch` | false | — | 1 |
| 36 | `docs/benchmarks/m6_1-real-prompt-embeds.json` | `git rm` | `milestone/m6.1-real-prompt-embeds` | false | — | 1 |
| 37 | `docs/benchmarks/m6_1-real-prompt-embeds.md` | `git rm` | `milestone/m6.1-real-prompt-embeds` | false | — | 1 |
| 38 | `docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md` | `git rm` | `milestone/m6.1.1-engine-cost-instr` | false | — | 1 |
| 39 | `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` | `git rm` | `milestone/m6.1.1-engine-cost-instr` | false | — | 1 |
| 40 | `docs/benchmarks/m6_1_1-engine-cost-instrumentation.md` | `git rm` | `milestone/m6.1.1-engine-cost-instr` | false | — | 1 |
| 41 | `docs/benchmarks/m6_1_2-methodology-discipline.json` | `git rm` | `milestone/m6.1.2-methodology` | false | — | 1 |
| 42 | `docs/benchmarks/m6_1_2-methodology-discipline.md` | `git rm` | `milestone/m6.1.2-methodology` | false | — | 1 |
| 43 | `docs/benchmarks/m6_1_3-attribution-closure-validate.json` | `git rm` | `milestone/m6.1.3-attribution` | false | — | 1 |
| 44 | `docs/benchmarks/m6_1_3-attribution-closure-validate.md` | `git rm` | `milestone/m6.1.3-attribution` | false | — | 1 |
| 45 | `docs/benchmarks/m6_1_3-attribution-closure.json` | `git rm` | `milestone/m6.1.3-attribution` | false | — | 1 |
| 46 | `docs/benchmarks/m6_1_3-attribution-closure.md` | `git rm` | `milestone/m6.1.3-attribution` | false | — | 1 |
| 47 | `docs/benchmarks/summary.md` | `git rm` | any pre-2026-05-26 tag | false | — | 1 |
| 48 | `tests/integration/test_m4_schema_e2e.py` | `git rm` | `milestone/m4-time-axis` | false | — | 1 |
| 49 | `tests/integration/test_m4_sweep_e2e.py` | `git rm` | `milestone/m4-time-axis` | false | — | 1 |
| 50 | `tests/integration/test_m5_modal_smoke.py` | `git rm` | `milestone/m5-cross-host` | false | — | 1 |
| 51 | `tests/integration/test_m5_1_modal_smoke.py` | `git rm` | `milestone/m5.1-rest-vs-grpc` | false | — | 1 |
| 52 | `tests/integration/test_m5_2_modal_smoke.py` | `git rm` | `milestone/m5.2-transport-tuning` | false | — | 1 |
| 53 | `scripts/python/reprocess_m5_supersede.py` | `git rm` | `milestone/m5.2-transport-tuning` | false | — | 1 |
| 54 | `scripts/setup/phase2-env.sh` | `git rm` | `milestone/m2-ground-truth` | false | — | 1 |
| 55 | `logs/m4-full-20260510-103956.log` | `git rm --cached` | `milestone/m4-time-axis` | true | — | 2 |
| 56 | `logs/m4-full-20260510-104041.log` | `git rm --cached` | `milestone/m4-time-axis` | true | — | 2 |
| 57 | `logs/m4-full-20260510-104111.log` | `git rm --cached` | `milestone/m4-time-axis` | true | — | 2 |
| 58 | `logs/m4-full-20260510-134830.log` | `git rm --cached` | `milestone/m4-time-axis` | true | — | 2 |
| 59 | `logs/m4-full-20260510-135937.log` | `git rm --cached` | `milestone/m4-time-axis` | true | — | 2 |
| 60 | `logs/m4-full-20260510-140027.log` | `git rm --cached` | `milestone/m4-time-axis` | true | — | 2 |
| 61 | `logs/m4-full-20260510-140459.log` | `git rm --cached` | `milestone/m4-time-axis` | true | — | 2 |
| 62 | `logs/m4-full-20260510-143034.log` | `git rm --cached` | `milestone/m4-time-axis` | true | — | 2 |
| 63 | `logs/m4-full-20260510-145546.log` | `git rm --cached` | `milestone/m4-time-axis` | true | — | 2 |
| 64 | `logs/m4-full-20260510-150308.log` | `git rm --cached` | `milestone/m4-time-axis` | true | — | 2 |
| 65 | `logs/m4-full-20260510-150604.log` | `git rm --cached` | `milestone/m4-time-axis` | true | — | 2 |
| 66 | `logs/m4-full.current` + `logs/m4-full.pid` (covered by `git rm -r --cached logs/`) | `git rm --cached` | `milestone/m4-time-axis` | true | — | 2 |
| 67 | `docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl` | `git rm --cached` | `milestone/m6.2-token-budget` (committed as part of `3646f8e` spec-bundle) | true | ~141 lines | 3 |

**Size totals (from R-baseline survey)**:
- `docs/benchmarks/` deletion subset: ~2.6 MB
- `tests/integration/` deletion subset: ~8 KB (the 5 M4/M5 smoke files; the 6 retained files account for the remaining ~144 KB)
- `scripts/python/reprocess_m5_supersede.py`: ~360 KB directory size (single file inside dominates)
- `scripts/setup/phase2-env.sh`: ~4 KB
- `M6_2-ANALYSIS-FRAMING-DRAFT.md`: 16 KB
- `logs/` un-tracking: 52 KB
- **Sum**: ~3.04 MB — comfortably above SC-002's "at least 3 MB" floor.

---

## Entity 2 — Gitignore rules

One row per `.gitignore` rule added. Each rule has a defensible scope statement.

**Schema**: `{ pattern, scope_statement, anti_match_examples, commit_group }`

| pattern | scope_statement | anti_match_examples | commit_group |
|---|---|---|---|
| `logs/` | Ignore the `logs/` directory and everything beneath it. Captures the M4 sweep harness's chronological log writes plus its `m4-full.current` / `m4-full.pid` marker files. Any future sweep harness writing to `logs/` is automatically covered. | `tools/benchmark/src/.../logs.py` (a hypothetical Python module — wouldn't be matched because the rule is anchored to the `logs/` directory at repo root or any subdirectory's `logs/` subtree; matches by directory boundary, not by substring). | 4 |
| `**/*.checkpoint.jsonl` | Ignore any path ending in `.checkpoint.jsonl` at any depth. Captures the M6.2 sweep's `docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl` plus any future sweep's analogous checkpoint files. The globstar prefix preempts future harness changes that move checkpoints to e.g. `tools/benchmark/checkpoints/`. | `docs/benchmarks/m6_2-token-budget.json` (final M6.2 output — keeps tracked); `m6_2-checkpoint.md` (not a `.checkpoint.jsonl` suffix — keeps tracked). | 4 |

---

## Entity 3 — ANALYSIS reference rewrites

One row per `summary.md` reference to be removed or rewritten. Driven by R3.

**Schema**: `{ file, line, action, before_substring, after_substring, commit_group }`

| file | line | action | before (paraphrased) | after (paraphrased) | commit_group |
|---|---|---|---|---|---|
| `ANALYSIS.md` | 5 | rewrite | "…`docs/benchmarks/summary.md` (the M1/M3-era summary) has been folded into § M1 and § M3 below and now lives as a one-line redirect." | "…the original M1/M3-era summary has been folded into § M1 and § M3 below; the pre-cleanup `docs/benchmarks/summary.md` redirect stub is recoverable from any milestone tag through `milestone/m6.1.3-attribution`." | 1 |
| `ANALYSIS.md` | 14 | rewrite | "**Report**: [`docs/benchmarks/summary.md`](docs/benchmarks/summary.md) § 1–3 (folded in below) — `docs/benchmarks/phase-4.2-*.json`, `phase-5-*.json`, `phase-6-*.json` for source data" | "**Report**: see § M1 fold-in below — historical phase-4.2 / phase-5 / phase-6 source-data JSON is recoverable via `milestone/m2-ground-truth` (see Repo housekeeping)." | 1 |
| `ANALYSIS.md` | 64 | rewrite | "### § M3 fold-in (from `docs/benchmarks/summary.md` § 4, byte-for-byte equivalent per FR-018)" | "### § M3 fold-in (originally folded in from the pre-cleanup `docs/benchmarks/summary.md` § 4 per § M3 FR-018; pre-fold-in text recoverable via `milestone/m3-grpc-tuning-r1`)" | 1 |
| `docs/PLAN.md` | 869 | remove | "- A short benchmark write-up at `docs/benchmarks/summary.md` covering the headline numbers for all three paths across non-streaming and streaming" | (bullet removed; preceding/following bullets reflow normally) | 1 |

**Note**: Line numbers are accurate at spec-time (verified via `grep -n`). The implementer should re-run `grep -n "summary\.md" ANALYSIS.md docs/PLAN.md` immediately before editing to confirm — line numbers may shift if any unrelated commit lands in between.

---

## Entity 4 — Tag artifacts

One row per git tag the cleanup interacts with.

**Schema**: `{ tag, role, commit, action, message_shape, commit_group }`

| tag | role | commit | action | message_shape | commit_group |
|---|---|---|---|---|---|
| `milestone/m6.2-token-budget` | M6.2 research deliverable | `fea31c0` | **verify still present + pushed**; do not re-create | Already created and pushed on 2026-05-26; spec FR-016 requires it to remain reachable. | (post-merge; verification step only — no new commit) |
| `v0.0.0` | Post-M6.2 cleanup checkpoint (codebase state) | merge commit (TBD at PR merge time) | **create + push** | Annotated; structured per R8 (subject + body + cross-references) | 6 (post-merge; not part of the PR's commit list) |

**Note**: There are also 14 pre-existing `milestone/*` tags (M2 through M6.1.3) and the in-progress `milestone/m6.2-token-budget` tag — all 16 must remain reachable for FR-012 (recoverability). The cleanup does not delete or move any tag.

---

## Cross-table invariants

- **I-1**: For every row in Entity 1 (Deletion manifest) with `action = 'git rm'`, there exists a tag in Entity 4 (Tag artifacts) of role `milestone deliverable` whose tree contains the row's `path`. (FR-012.)
- **I-2**: For every row in Entity 1 with `action = 'git rm --cached'`, the row's path is matched by at least one rule in Entity 2 (Gitignore rules), so the file's reappearance on disk is not re-tracked. (FR-007 / FR-008 coupling.)
- **I-3**: Every row in Entity 3 (ANALYSIS reference rewrites) lands in `commit_group = 1`, alongside the working-tree deletions that motivate it. (Atomic from the reviewer's perspective — the deletion and the link removal happen together.)
- **I-4**: No row across any entity references a path under `tools/benchmark/src/`, `packages/`, `proto/`, or `frontend/`. (FR-001 source preservation.)

---

## Mapping back to functional requirements

| FR / SC | Entity / rows |
|---|---|
| FR-001 (source preservation) | Invariant I-4 |
| FR-002 (root draft delete) | Entity 1 row 1 |
| FR-003 (benchmark deletions) | Entity 1 rows 2–47 |
| FR-003a (summary.md reference cleanup) | Entity 3 (all 4 rows) |
| FR-004 (integration-test deletions) | Entity 1 rows 48–52 |
| FR-005 / FR-006 (script deletions) | Entity 1 rows 53–54 |
| FR-007 (gitignore rules) | Entity 2 (both rows) |
| FR-008 (un-tracking) | Entity 1 rows 55–67 |
| FR-009 / FR-010 / FR-011 (ANALYSIS housekeeping subsection) | (Not table-driven — single-section append; spec'd in research § R7 and quickstart.) |
| FR-012 (recoverability) | Invariant I-1 |
| FR-013 / FR-014 (CI / smoke gates) | (Not table-driven — runtime verification in quickstart Step 8.) |
| FR-015 (v0.0.0 tag) | Entity 4 row 2 |
| FR-016 (m6.2 tag persistence) | Entity 4 row 1 |
| SC-001 (zero deletion-target tracked files) | Entities 1 + 3 (post-execution count must be zero) |
| SC-002 (≥3 MB reduction) | Entity 1 size totals (~3.04 MB) |
| SC-003 (clean fresh-clone) | Entity 2 (gitignore prevents recurrence) |
| SC-004 (recovery spot-check) | Invariant I-1 + research § R4 spot-checks |
| SC-005 / SC-006 (CI / smoke green) | (Quickstart Steps 8 + 9.) |
| SC-007 (30-second recovery) | Research § R7 housekeeping subsection content |
| SC-008 (both tags reachable post-merge) | Entity 4 (both rows post-state) |
