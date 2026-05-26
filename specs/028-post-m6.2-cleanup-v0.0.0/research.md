# Phase 0 Research: v0.0.0 — Post-M6.2 Housekeeping

**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Date**: 2026-05-26 (re-derived after clarify cycle adding FR-003 exception for baseline-input JSONs)

The spec was sufficiently concrete (the source PLAN.md section enumerates patterns; two rounds of clarification — initial on 2026-05-26 plus the post-implement discovery cycle the same day — resolved checkpoint, summary, commit-shape, FR-003 exception, `.md` companion handling, output-only JSONs, and SC-002 metric decisions) that "research" here means **fact-finding against the live tree**, not design exploration. This document captures the concrete file-by-file enumerations the plan and tasks artifacts depend on.

---

## R1. Deletion manifest — `docs/benchmarks/`

**Decision**: 37 files in the `docs/benchmarks/` deletion set; 9 retained under FR-003 exception; 7 retained as M6.2 outputs.

After cleanup:

- **DELETE (37 files)**:
  - 21 `.md` writeups: `m3-channel-tuning-time.md`, `m3-channel-tuning.md`, `m4-time-axis-tuning.md`, `m5-cross-host-validation.md`, `m5_1-rest-vs-grpc.md`, `m5_2-transport-vs-tuning.md`, `m6-real-engine-mini-validation.md`, `m6_0a-dispatch-correction.md`, `m6_1-real-prompt-embeds.md`, `m6_1_1-audit-2026-05-16-seq-dispatch.md`, `m6_1_1-engine-cost-instrumentation.md`, `m6_1_2-methodology-discipline.md`, `m6_1_3-attribution-closure-validate.md`, `m6_1_3-attribution-closure.md`, `phase-3-modal-comparison.md`, `phase-3-modal-grpc-baseline.md`, `phase-3-modal-rest-baseline.md`, `phase-4.2-grpc-direct-baseline.md`, `phase-4.2-three-way-comparison.md`, `phase-5-streaming-comparison.md`, `phase-6-completions-comparison.md`
  - 1 events sidecar: `m5_2-transport-vs-tuning.events.jsonl.gz`
  - 2 output-only `.json` files (per 2026-05-26 Q3 clarification): `m6_1_2-methodology-discipline.json`, `m6_1_3-attribution-closure-validate.json`
  - 1 superseded redirect stub: `summary.md`
  - 12 `phase-*` JSONs (M1-era benchmarks) plus the M3 bytes-axis `m3-channel-tuning.json`: `phase-3-modal-grpc-baseline.json`, `phase-3-modal-rest-baseline.json`, `phase-4.2-grpc-direct-baseline.json`, `phase-4.2-grpc-proxy-baseline.json`, `phase-4.2-rest-baseline.json`, `phase-5-grpc-direct-streaming.json`, `phase-5-grpc-proxy-streaming.json`, `phase-5-rest-streaming.json`, `phase-6-completions-grpc-direct.json`, `phase-6-completions-native.json`, `phase-6-completions-proxy.json`, `m3-channel-tuning.json`

- **RETAIN — 9 baseline-chain JSONs (FR-003 exception, 2026-05-26 clarification)**:
  | # | Path | Read by (default-path constant) |
  |---|------|---------------------------------|
  | 1 | `m3-channel-tuning-time.json` | `m4_sweep.py:774` (`M3_TIME_REPORT_PATH`) → M4 baseline |
  | 2 | `m4-time-axis-tuning.json` | `m5_sweep.py:97` (default_factory) → M5 baseline |
  | 3 | `m5-cross-host-validation.json` | `m5_1_sweep.py:52` (`_M5_REPORT_PATH`) → M5.1 baseline |
  | 4 | `m5_1-rest-vs-grpc.json` | `m5_2_supersede.py:39` (`_M5_1_PUBLISHED_PATH`) → M5.2 baseline |
  | 5 | `m5_2-transport-vs-tuning.json` | `__main__.py:426` (M6 baseline default) |
  | 6 | `m6-real-engine-mini-validation.json` | `__main__.py:520` (M6.1 baseline default) |
  | 7 | `m6_1-real-prompt-embeds.json` | `__main__.py:574` (M6.1.1 baseline default) |
  | 8 | `m6_1_1-engine-cost-instrumentation.json` | `__main__.py:652, 756` (M6.1.2 / M6.1.3 baseline default) |
  | 9 | `m6_1_3-attribution-closure.json` | `__main__.py:846` (M6.2 baseline default) |

- **RETAIN — 7 M6.2 outputs (current milestone)**: `m6_2-publish.sweep.log`, `m6_2-token-budget-validate.json`, `m6_2-token-budget-validate.md`, `m6_2-token-budget.json`, `m6_2-token-budget.md`, `m6_2-validate.sweep.log` (6 listed; checkpoint `.checkpoint.jsonl` un-tracked per US2).

**Sub-finding R1a — audit anchor**: The retention list of 9 JSONs is verifiable by:

```bash
grep -hoE 'docs/benchmarks/[^"'\'']+\.json' tools/benchmark/src/vllm_grpc_bench/*.py \
  | sort -u \
  | while read p; do test -e "$p" && echo "$p"; done \
  | grep -v 'm6_2-'
```

The `test -e` filter is critical: the raw grep returns 10 paths because `m6_1_3_validate.py:70` defines `_PHASE_B_JSON = "docs/benchmarks/m6_1_3-attribution-closure-phase-b.json"` as an OUTPUT-only default for the never-run M6.1.3 phase-B mode (the file doesn't exist on disk; not a runtime input). Filtering to existing files yields exactly the 9 baseline-chain JSONs the retention list names. The `grep -v 'm6_2-'` drops M6.2's own outputs (which are retained under the `m6_2-*` rule, not the FR-003 exception). Any future M7+ baseline that adds to this list requires a deliberate spec amendment.

**Sub-finding R1b — discovered 2026-05-26 during /speckit-implement**: Pre-clarify, the cleanup attempted to delete all 9 baseline-chain JSONs. `make check` immediately fired 4 test failures + 8 silent skips because `tools/benchmark/tests/` runs the same source paths with default args. The clarify cycle's FR-003 exception adds these 9 paths back to the retention set, and `make check` returns to 1575 passed / 0 failed / 2 skipped (no regression vs `fea31c0`).

**Alternatives considered**:
- *Move depended-on JSONs to `tools/benchmark/tests/fixtures/`*: rejected — requires editing `tools/benchmark/src/`'s default-path constants, which FR-001 prohibits.
- *Add pytest-skip guards to the 4 failing tests*: rejected — hides real-data assertions; doesn't help the +8 silent skips; cascades to more tests as future milestones are added.
- *Globbing the deletion at `git rm` time vs. enumerating explicitly*: enumerating is safer for an irreversible operation. The `tasks.md` artifact carries the explicit enumeration.

---

## R2. Deletion manifest — `tests/integration/`

**Decision**: 5 files delete; 6 files retain. (Unchanged by clarify cycle.)

**Rationale**: Enumerated by `ls tests/integration/`. FR-004 explicitly names retentions and deletions:

| Action | File | Notes |
|---|---|---|
| DELETE | `test_m4_schema_e2e.py` | M4 era; recoverable via `milestone/m4-time-axis` |
| DELETE | `test_m4_sweep_e2e.py` | same |
| DELETE | `test_m5_modal_smoke.py` | M5 era; `milestone/m5-cross-host` |
| DELETE | `test_m5_1_modal_smoke.py` | M5.1 era; `milestone/m5.1-rest-vs-grpc` |
| DELETE | `test_m5_2_modal_smoke.py` | M5.2 era; `milestone/m5.2-transport-tuning` |
| RETAIN | `__init__.py` | Package marker; no milestone affinity |
| RETAIN | `conftest.py` | pytest fixture wiring; still active |
| RETAIN | `fake_frontend.py` | Fake gRPC frontend used by retained tests |
| RETAIN | `test_grpc_client.py` | Tests the live `packages/client/` |
| RETAIN | `test_chat_bridge.py` | Tests the live proxy chat path |
| RETAIN | `test_completions_bridge.py` | Tests the live proxy completions path |

**Sub-finding**: No CI workflow references the deleted tests. The two `test_m4_*_e2e.py` files were already failing on `fea31c0` (validated during /speckit-implement discovery: `M4SweepConfig.__init__() got an unexpected keyword argument 'baseline_cv_max'` — stale config attribute removed without removing the test). Deletion eliminates the failure noise.

---

## R3. `summary.md` reference audit

**Decision**: 4 references found across `ANALYSIS.md` and `docs/PLAN.md`; rewrite or remove each. (Unchanged by clarify cycle.)

| File | Line | Action | After-text (key fragment) |
|---|---|---|---|
| `ANALYSIS.md` | 5 | Rewrite | "…the pre-cleanup `docs/benchmarks/summary.md` redirect stub is recoverable from any milestone tag through `milestone/m6.1.3-attribution`…" |
| `ANALYSIS.md` | 14 | Rewrite | "…historical phase-4.2 / phase-5 / phase-6 source-data JSON is recoverable via `milestone/m2-ground-truth`…" |
| `ANALYSIS.md` | 64 | Rewrite | "(originally folded in from the pre-cleanup `docs/benchmarks/summary.md` § 4 per § M3 FR-018; pre-fold-in text recoverable via `milestone/m3-grpc-tuning-r1`)" |
| `docs/PLAN.md` | 869 | Remove | (entire bullet) |

**Verification (FR-003a)**: `grep -nE "\]\(docs/benchmarks/summary\.md\)|\]\(summary\.md\)" ANALYSIS.md docs/PLAN.md README.md` returns no markdown hyperlinks. Bare path mentions in code-spans (informative prose naming the deleted file) are intentional and acceptable.

---

## R4. Tag → path recovery map

**Decision**: All 16 milestone tags are reachable from the merge-base commit; spot-checks confirm.

```
milestone/m2-ground-truth
milestone/m3-grpc-tuning-r1
milestone/m3-phase-a-closure
milestone/m3-replan
milestone/m4-time-axis
milestone/m5-cross-host
milestone/m5.1-rest-vs-grpc
milestone/m5.2-transport-tuning
milestone/m6-analysis-update
milestone/m6-real-engine-mini
milestone/m6.0a-concurrent-dispatch
milestone/m6.1-real-prompt-embeds
milestone/m6.1.1-engine-cost-instr
milestone/m6.1.2-methodology
milestone/m6.1.3-attribution
milestone/m6.2-token-budget
```

Spot-checks: `git show milestone/m5.2-transport-tuning:docs/benchmarks/m5_2-transport-vs-tuning.md` returns the M5.2 report; `git show milestone/m4-time-axis:logs/m4-full-20260510-103956.log` returns the M4 sweep log. All deleted paths are within the union of files reachable from these 16 tags.

---

## R5. `logs/` inventory baseline

**Decision**: 13 index entries to un-track (11 M4 sweep logs + 2 marker files); ~52 KB total. Recoverable via `milestone/m4-time-axis`.

---

## R6. `.gitignore` rule placement and pattern semantics

**Decision**: Append a new `# v0.0.0 housekeeping (per spec FR-007)` section near the end of `.gitignore` with two rules: `logs/` and `**/*.checkpoint.jsonl`. (Unchanged by clarify cycle.)

Rule semantics:
- `logs/` (trailing slash) — matches the directory and everything under it at repo root.
- `**/*.checkpoint.jsonl` (globstar prefix) — matches checkpoint files at any depth. Preempts future sweep harnesses writing checkpoints under different parent directories.

**Anti-match verification**: `git check-ignore -v docs/benchmarks/m6_2-token-budget.json` returns no output (the M6.2 final output is NOT ignored).

---

## R7. `ANALYSIS.md` housekeeping subsection placement and content shape

**Decision**: Append a new top-level `## Repo housekeeping` section at the very end of `ANALYSIS.md`. Satisfies FR-011 (do not interrupt milestone narrative).

**Content shape** (≈12-15 lines):

```markdown
## Repo housekeeping

The repository maintains two parallel tag tracks:

- **`milestone/*` — research deliverables.** One tag per closed milestone (M2 through M6.2 as of 2026-05-26). Each tag fixes the working tree at the commit that publishes the milestone's report + sweep harness, so any pre-cleanup historical artifact (benchmark report, sweep script, era-specific integration test) is recoverable by checking out the matching tag.
- **`v*` — codebase state.** Semver-style tags (`v0.0.0`, `v0.0.1`, `v0.1.0`, …) mark maintenance and release-readiness checkpoints. `v0.0.0` marks the post-M6.2 cleanup that removed pre-M6.2 milestone-specific `.md` writeups + obsolete tests + scripts from `main`; the 9 baseline-chain JSON data files (M3→M6.2) stay tracked because the sweep harness reads them at runtime.

To recover a deleted historical narrative:

    git show milestone/m5.2-transport-tuning:docs/benchmarks/m5_2-transport-vs-tuning.md

Replace `milestone/m5.2-transport-tuning` with the milestone tag whose era owns the file, and the path with the file you want. `git tag --list 'milestone/*'` lists every available tag.
```

---

## R8. `v0.0.0` tag message format

**Decision**: Annotated tag with structured message matching the milestone-tag convention. (Unchanged by clarify cycle, but body wording updated to reflect file-count framing.)

**Proposed message body**:

```
v0.0.0 — Post-M6.2 housekeeping

First cut of the v* semver track (codebase state). Removes ~59 milestone-
era files from main (pre-M6.2 .md writeups, obsolete M4/M5 integration
tests, two stale scripts, the root draft note, the M4 sweep logs, and the
M6.2 sweep checkpoint), retaining the 9 baseline-chain JSONs the sweep
harness reads at runtime. All deleted paths recoverable via
milestone/m2-ground-truth through milestone/m6.2-token-budget.

Spec: specs/028-post-m6.2-cleanup-v0.0.0/spec.md
M6.2 research deliverable: milestone/m6.2-token-budget (already at fea31c0)
Next: v0.0.1 (bench-harness refactor), then v0.1.0 (first PyPI release).
```

---

## Decisions summary

| Topic | Decision | Source |
|---|---|---|
| Benchmark deletion count | 37 files (21 `.md` + 1 `.gz` + 2 output-only `.json` + 12 `phase-*` JSON + `summary.md`); 9 JSONs retained under FR-003 exception; 7 M6.2 outputs retained | R1 |
| Integration-test deletions | 5 files; 6 retained | R2 |
| `summary.md` reference cleanup | 4 sites: 3 rewrite + 1 removal | R3 |
| Tag coverage | All 16 milestone tags reachable; spot-checks pass | R4 |
| `logs/` un-tracking scope | 13 index entries | R5 |
| `.gitignore` rules | `logs/` + `**/*.checkpoint.jsonl`, appended in a new section | R6 |
| `ANALYSIS.md` placement | New `## Repo housekeeping` section at end-of-document, mentions FR-003 exception | R7 |
| `v0.0.0` tag format | Annotated, structured message reflecting file-count framing | R8 |

All Phase-0 unknowns resolved; ready for Phase 1 design artifacts.
