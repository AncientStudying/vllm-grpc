# Data Model: v0.0.0 — Post-M6.2 Housekeeping

**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Research**: [research.md](./research.md)
**Date**: 2026-05-26 (re-derived after clarify cycle adding FR-003 exception)

This feature has no runtime data model (no persisted entities, no database). The "data model" here is the **set of inputs and outputs that the cleanup operates on** — concrete file paths, tags, and configuration rules — captured in five tables. The tasks artifact references this document by row.

---

## Entity 1 — Deletion manifest

One row per file the cleanup removes (whether by `git rm` for tracked content or `git rm --cached` for index-only entries). Each row carries enough context that a reviewer can audit "is this safe to delete?" without leaving the table.

**Schema**: `{ path, action, owning_milestone_tag, on_disk_after, commit_group }`

- `path` — repo-relative path. Slash-prefixed when at repo root.
- `action` — `git rm` (untrack + delete from working tree) or `git rm --cached` (untrack but keep on disk).
- `owning_milestone_tag` — the `milestone/*` tag that exposes the deleted content for recovery. Required.
- `on_disk_after` — whether the file stays present on the operator's local working tree after the operation. `false` for `git rm`; `true` for `git rm --cached`.
- `commit_group` — which of the five PR commits this row lands in.

### Manifest rows (59 total — down from 68 after FR-003 exception retained 9 JSONs)

| # | path | action | owning_milestone_tag | on_disk_after | commit_group |
|---|------|--------|---------------------|---------------|--------------|
| 1 | `M6_2-ANALYSIS-FRAMING-DRAFT.md` | `git rm` | n/a (content already merged into `ANALYSIS.md` at `fea31c0`; reachable via `milestone/m6.2-token-budget`) | false | 1 |
| 2 | `docs/benchmarks/phase-3-modal-comparison.md` | `git rm` | `milestone/m3-replan` | false | 1 |
| 3 | `docs/benchmarks/phase-3-modal-grpc-baseline.json` | `git rm` | `milestone/m3-replan` | false | 1 |
| 4 | `docs/benchmarks/phase-3-modal-grpc-baseline.md` | `git rm` | `milestone/m3-replan` | false | 1 |
| 5 | `docs/benchmarks/phase-3-modal-rest-baseline.json` | `git rm` | `milestone/m3-replan` | false | 1 |
| 6 | `docs/benchmarks/phase-3-modal-rest-baseline.md` | `git rm` | `milestone/m3-replan` | false | 1 |
| 7 | `docs/benchmarks/phase-4.2-grpc-direct-baseline.json` | `git rm` | `milestone/m2-ground-truth` | false | 1 |
| 8 | `docs/benchmarks/phase-4.2-grpc-direct-baseline.md` | `git rm` | `milestone/m2-ground-truth` | false | 1 |
| 9 | `docs/benchmarks/phase-4.2-grpc-proxy-baseline.json` | `git rm` | `milestone/m2-ground-truth` | false | 1 |
| 10 | `docs/benchmarks/phase-4.2-rest-baseline.json` | `git rm` | `milestone/m2-ground-truth` | false | 1 |
| 11 | `docs/benchmarks/phase-4.2-three-way-comparison.md` | `git rm` | `milestone/m2-ground-truth` | false | 1 |
| 12 | `docs/benchmarks/phase-5-grpc-direct-streaming.json` | `git rm` | `milestone/m2-ground-truth` | false | 1 |
| 13 | `docs/benchmarks/phase-5-grpc-proxy-streaming.json` | `git rm` | `milestone/m2-ground-truth` | false | 1 |
| 14 | `docs/benchmarks/phase-5-rest-streaming.json` | `git rm` | `milestone/m2-ground-truth` | false | 1 |
| 15 | `docs/benchmarks/phase-5-streaming-comparison.md` | `git rm` | `milestone/m2-ground-truth` | false | 1 |
| 16 | `docs/benchmarks/phase-6-completions-comparison.md` | `git rm` | `milestone/m2-ground-truth` | false | 1 |
| 17 | `docs/benchmarks/phase-6-completions-grpc-direct.json` | `git rm` | `milestone/m2-ground-truth` | false | 1 |
| 18 | `docs/benchmarks/phase-6-completions-native.json` | `git rm` | `milestone/m2-ground-truth` | false | 1 |
| 19 | `docs/benchmarks/phase-6-completions-proxy.json` | `git rm` | `milestone/m2-ground-truth` | false | 1 |
| 20 | `docs/benchmarks/m3-channel-tuning-time.md` | `git rm` | `milestone/m3-phase-a-closure` | false | 1 |
| 21 | `docs/benchmarks/m3-channel-tuning.json` | `git rm` | `milestone/m3-grpc-tuning-r1` | false | 1 |
| 22 | `docs/benchmarks/m3-channel-tuning.md` | `git rm` | `milestone/m3-grpc-tuning-r1` | false | 1 |
| 23 | `docs/benchmarks/m4-time-axis-tuning.md` | `git rm` | `milestone/m4-time-axis` | false | 1 |
| 24 | `docs/benchmarks/m5-cross-host-validation.md` | `git rm` | `milestone/m5-cross-host` | false | 1 |
| 25 | `docs/benchmarks/m5_1-rest-vs-grpc.md` | `git rm` | `milestone/m5.1-rest-vs-grpc` | false | 1 |
| 26 | `docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz` | `git rm` | `milestone/m5.2-transport-tuning` | false | 1 |
| 27 | `docs/benchmarks/m5_2-transport-vs-tuning.md` | `git rm` | `milestone/m5.2-transport-tuning` | false | 1 |
| 28 | `docs/benchmarks/m6-real-engine-mini-validation.md` | `git rm` | `milestone/m6-real-engine-mini` | false | 1 |
| 29 | `docs/benchmarks/m6_0a-dispatch-correction.md` | `git rm` | `milestone/m6.0a-concurrent-dispatch` | false | 1 |
| 30 | `docs/benchmarks/m6_1-real-prompt-embeds.md` | `git rm` | `milestone/m6.1-real-prompt-embeds` | false | 1 |
| 31 | `docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md` | `git rm` | `milestone/m6.1.1-engine-cost-instr` | false | 1 |
| 32 | `docs/benchmarks/m6_1_1-engine-cost-instrumentation.md` | `git rm` | `milestone/m6.1.1-engine-cost-instr` | false | 1 |
| 33 | `docs/benchmarks/m6_1_2-methodology-discipline.json` | `git rm` | `milestone/m6.1.2-methodology` | false | 1 |
| 34 | `docs/benchmarks/m6_1_2-methodology-discipline.md` | `git rm` | `milestone/m6.1.2-methodology` | false | 1 |
| 35 | `docs/benchmarks/m6_1_3-attribution-closure-validate.json` | `git rm` | `milestone/m6.1.3-attribution` | false | 1 |
| 36 | `docs/benchmarks/m6_1_3-attribution-closure-validate.md` | `git rm` | `milestone/m6.1.3-attribution` | false | 1 |
| 37 | `docs/benchmarks/m6_1_3-attribution-closure.md` | `git rm` | `milestone/m6.1.3-attribution` | false | 1 |
| 38 | `docs/benchmarks/summary.md` | `git rm` | any pre-2026-05-26 tag | false | 1 |
| 39 | `tests/integration/test_m4_schema_e2e.py` | `git rm` | `milestone/m4-time-axis` | false | 1 |
| 40 | `tests/integration/test_m4_sweep_e2e.py` | `git rm` | `milestone/m4-time-axis` | false | 1 |
| 41 | `tests/integration/test_m5_modal_smoke.py` | `git rm` | `milestone/m5-cross-host` | false | 1 |
| 42 | `tests/integration/test_m5_1_modal_smoke.py` | `git rm` | `milestone/m5.1-rest-vs-grpc` | false | 1 |
| 43 | `tests/integration/test_m5_2_modal_smoke.py` | `git rm` | `milestone/m5.2-transport-tuning` | false | 1 |
| 44 | `scripts/python/reprocess_m5_supersede.py` | `git rm` | `milestone/m5.2-transport-tuning` | false | 1 |
| 45 | `scripts/setup/phase2-env.sh` | `git rm` | `milestone/m2-ground-truth` | false | 1 |
| 46 | `logs/m4-full-20260510-103956.log` | `git rm --cached` | `milestone/m4-time-axis` | true | 2 |
| 47 | `logs/m4-full-20260510-104041.log` | `git rm --cached` | `milestone/m4-time-axis` | true | 2 |
| 48 | `logs/m4-full-20260510-104111.log` | `git rm --cached` | `milestone/m4-time-axis` | true | 2 |
| 49 | `logs/m4-full-20260510-134830.log` | `git rm --cached` | `milestone/m4-time-axis` | true | 2 |
| 50 | `logs/m4-full-20260510-135937.log` | `git rm --cached` | `milestone/m4-time-axis` | true | 2 |
| 51 | `logs/m4-full-20260510-140027.log` | `git rm --cached` | `milestone/m4-time-axis` | true | 2 |
| 52 | `logs/m4-full-20260510-140459.log` | `git rm --cached` | `milestone/m4-time-axis` | true | 2 |
| 53 | `logs/m4-full-20260510-143034.log` | `git rm --cached` | `milestone/m4-time-axis` | true | 2 |
| 54 | `logs/m4-full-20260510-145546.log` | `git rm --cached` | `milestone/m4-time-axis` | true | 2 |
| 55 | `logs/m4-full-20260510-150308.log` | `git rm --cached` | `milestone/m4-time-axis` | true | 2 |
| 56 | `logs/m4-full-20260510-150604.log` | `git rm --cached` | `milestone/m4-time-axis` | true | 2 |
| 57 | `logs/m4-full.current` | `git rm --cached` | `milestone/m4-time-axis` | true | 2 |
| 58 | `logs/m4-full.pid` | `git rm --cached` | `milestone/m4-time-axis` | true | 2 |
| 59 | `docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl` | `git rm --cached` | `milestone/m6.2-token-budget` | true | 3 |

**Note**: Rows 46–58 are typically issued as a single `git rm -r --cached logs/` command (recursive un-tracking of the directory's 13 index entries); the row-by-row split is for audit traceability.

---

## Entity 2 — Retained JSONs (FR-003 exception, added 2026-05-26 clarify cycle)

The 9 `docs/benchmarks/*.json` files in the M3→M6.2 baseline chain that MUST remain tracked because `tools/benchmark/src/` reads them at runtime via default-path constants. FR-001 forbids editing those source defaults, so the cleanup cannot delete these files.

**Schema**: `{ path, source_reference, role }`

| # | path | source reference | role |
|---|------|------------------|------|
| 1 | `docs/benchmarks/m3-channel-tuning-time.json` | `m4_sweep.py:774` (`M3_TIME_REPORT_PATH`) | M4 baseline input |
| 2 | `docs/benchmarks/m4-time-axis-tuning.json` | `m5_sweep.py:97` (default_factory) | M5 baseline input |
| 3 | `docs/benchmarks/m5-cross-host-validation.json` | `m5_1_sweep.py:52` (`_M5_REPORT_PATH`) | M5.1 baseline input |
| 4 | `docs/benchmarks/m5_1-rest-vs-grpc.json` | `m5_2_supersede.py:39` (`_M5_1_PUBLISHED_PATH`) | M5.2 baseline input |
| 5 | `docs/benchmarks/m5_2-transport-vs-tuning.json` | `__main__.py:426` (`--m6-m5-2-baseline` default) | M6 baseline input |
| 6 | `docs/benchmarks/m6-real-engine-mini-validation.json` | `__main__.py:520` (`--m6_1-m6-baseline` default) | M6.1 baseline input |
| 7 | `docs/benchmarks/m6_1-real-prompt-embeds.json` | `__main__.py:574` (`--m6_1_1-m6-1-baseline` default) | M6.1.1 baseline input |
| 8 | `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` | `__main__.py:652, 756` (`--m6_1_2-...` / `--m6_1_3-...` defaults) | M6.1.2 + M6.1.3 baseline input |
| 9 | `docs/benchmarks/m6_1_3-attribution-closure.json` | `__main__.py:846` (`--m6_2-m6-1-3-baseline` default) | M6.2 baseline input |

**Audit anchor** (run from repo root):

```bash
grep -hoE 'docs/benchmarks/[^"'\'']+\.json' tools/benchmark/src/vllm_grpc_bench/*.py \
  | sort -u \
  | while read p; do test -e "$p" && echo "$p"; done \
  | grep -v 'm6_2-'
```

Returns exactly this 9-file list. The `test -e` filter excludes `m6_1_3-attribution-closure-phase-b.json` (an OUTPUT-only default in `m6_1_3_validate.py:70` for the never-run phase-B mode; not a runtime input); the `grep -v 'm6_2-'` excludes M6.2's own outputs (retained under the `m6_2-*` rule, not the FR-003 exception). Any addition to this list requires a deliberate spec amendment.

---

## Entity 3 — Gitignore rules

One row per `.gitignore` rule added. (Unchanged by clarify cycle.)

**Schema**: `{ pattern, scope_statement, anti_match_examples, commit_group }`

| pattern | scope_statement | anti_match_examples | commit_group |
|---|---|---|---|
| `logs/` | Ignore the `logs/` directory and everything beneath it. | A hypothetical `tools/benchmark/src/.../logs.py` Python module wouldn't be matched — the rule matches by directory boundary, not substring. | 4 |
| `**/*.checkpoint.jsonl` | Ignore any path ending in `.checkpoint.jsonl` at any depth. | `docs/benchmarks/m6_2-token-budget.json` (final M6.2 output — keeps tracked); `m6_2-checkpoint.md` (different suffix — keeps tracked). | 4 |

---

## Entity 4 — ANALYSIS reference rewrites

One row per `summary.md` reference to be removed or rewritten. Driven by R3. (Unchanged by clarify cycle.)

**Schema**: `{ file, line, action, before_substring, after_substring, commit_group }`

| file | line | action | after-text (key fragment) | commit_group |
|---|---|---|---|---|
| `ANALYSIS.md` | 5 | rewrite | "…the pre-cleanup `docs/benchmarks/summary.md` redirect stub is recoverable from any milestone tag through `milestone/m6.1.3-attribution`…" | 1 |
| `ANALYSIS.md` | 14 | rewrite | "…historical phase-4.2 / phase-5 / phase-6 source-data JSON is recoverable via `milestone/m2-ground-truth`…" | 1 |
| `ANALYSIS.md` | 64 | rewrite | "(originally folded in from the pre-cleanup `docs/benchmarks/summary.md` § 4 per § M3 FR-018; pre-fold-in text recoverable via `milestone/m3-grpc-tuning-r1`)" | 1 |
| `docs/PLAN.md` | 869 | remove | (bullet removed) | 1 |

---

## Entity 5 — Tag artifacts

One row per git tag the cleanup interacts with. (Unchanged by clarify cycle.)

| tag | role | commit | action | commit_group |
|---|---|---|---|---|
| `milestone/m6.2-token-budget` | M6.2 research deliverable | `fea31c0` | **verify still present + pushed**; do not re-create | (post-merge verification only) |
| `v0.0.0` | Post-M6.2 cleanup checkpoint (codebase state) | merge commit | **create + push** (annotated; structured per R8) | 6 (post-merge) |

**Note**: There are also 14 pre-existing `milestone/*` tags and the in-progress `milestone/m6.2-token-budget` tag — all 16 must remain reachable for FR-012.

---

## Cross-table invariants

- **I-1**: For every row in Entity 1 with `action = 'git rm'`, there exists a tag in Entity 5 of role `milestone deliverable` whose tree contains the row's `path`. (FR-012.)
- **I-2**: For every row in Entity 1 with `action = 'git rm --cached'`, the row's path is matched by at least one rule in Entity 3, so the file's reappearance on disk is not re-tracked. (FR-007 / FR-008 coupling.)
- **I-3**: Every row in Entity 4 lands in `commit_group = 1`, alongside the working-tree deletions that motivate it.
- **I-4**: No row across any entity references a path under `tools/benchmark/src/`, `packages/`, `proto/`, or `frontend/`. (FR-001 source preservation.)
- **I-5** (new in 2026-05-26 clarify cycle): No row in Entity 1 has a `path` value that appears in Entity 2 (FR-003 exception list). I.e., the deletion manifest and the retention list are disjoint. Verifiable by `comm -12 <(<entity1.paths> sort) <(<entity2.paths> sort)` returning empty.

---

## Mapping back to functional requirements

| FR / SC | Entity / rows |
|---|---|
| FR-001 (source preservation) | Invariant I-4 |
| FR-002 (root draft delete) | Entity 1 row 1 |
| FR-003 (benchmark deletions) | Entity 1 rows 2–38 |
| FR-003 exception (baseline-input JSONs) | Entity 2 (all 9 rows), Invariant I-5 |
| FR-003a (summary.md reference cleanup) | Entity 4 (all 4 rows) |
| FR-004 (integration-test deletions) | Entity 1 rows 39–43 |
| FR-005 / FR-006 (script deletions) | Entity 1 rows 44–45 |
| FR-007 (gitignore rules) | Entity 3 (both rows) |
| FR-008 (un-tracking) | Entity 1 rows 46–59 |
| FR-009 / FR-010 / FR-011 (ANALYSIS housekeeping subsection) | (Not table-driven — single-section append; spec'd in research § R7 and quickstart.) |
| FR-012 (recoverability) | Invariant I-1 |
| FR-013 / FR-014 (CI / smoke gates) | (Not table-driven — runtime verification in quickstart.) |
| FR-015 (v0.0.0 tag) | Entity 5 row 2 |
| FR-016 (m6.2 tag persistence) | Entity 5 row 1 |
| SC-001 (zero deletion-target tracked files) | Entities 1 + 4 (post-execution count must be zero, with the FR-003 exception list explicitly excluded from the count) |
| SC-002 (≥50 fewer tracked files) | Entity 1 size (59 file-index removals) — comfortably ≥50 |
| SC-003 (clean fresh-clone) | Entity 3 (gitignore prevents recurrence) |
| SC-004 (recovery spot-check) | Invariant I-1 + research § R4 spot-checks |
| SC-005 / SC-006 (CI / smoke green) | (Quickstart Step 6.) Pre-validated 2026-05-26: 1575/0/2 green with the FR-003 exception in place. |
| SC-007 (30-second recovery) | Research § R7 housekeeping subsection content |
| SC-008 (both tags reachable post-merge) | Entity 5 (both rows post-state) |
