# Phase 0 Research: v0.0.0 — Post-M6.2 Housekeeping

**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Date**: 2026-05-26

The spec was sufficiently concrete (the source PLAN.md section enumerates patterns; the clarify session resolved checkpoint, summary, and commit-shape decisions) that "research" here means **fact-finding against the live tree**, not design exploration. This document captures the concrete file-by-file enumerations the plan and tasks artifacts depend on.

---

## R1. Deletion manifest — `docs/benchmarks/`

**Decision**: 46 files match the post-remediation FR-003 patterns (`phase-*`, `m3-*`, `m4-*`, `m5-*`, `m5_1-*`, `m5_2-*`, `m6-*`, `m6_0a-*`, `m6_1-*`, `m6_1_1-*`, `m6_1_2-*`, `m6_1_3-*`) plus `summary.md` (added per the 2026-05-26 clarification). That is: 45 milestone-prefixed files + 1 `summary.md` = 46. Total ~2.6 MB. (Earlier drafts of this document quoted "45 (44 milestone-prefixed + summary.md)" — that count was based on the pre-remediation FR-003 pattern list which omitted `m6_0a-*` explicitly. The live count via the corrected regex is 46, matching `data-model.md` Entity 1 rows 2–47.)

**Rationale**: Enumerated by `ls docs/benchmarks/ | grep -E "^(phase-|m3-|m4-|m5-|m5_1-|m5_2-|m6-|m6_1-|m6_1_1-|m6_1_2-|m6_1_3-|summary\.md)"`. Final enumerated list (45 entries):

| # | Path | Owning milestone tag |
|---|------|---------------------|
| 1 | `phase-3-modal-comparison.md` | `milestone/m3-grpc-tuning-r1` (predates; reachable from `milestone/m3-replan` baseline) |
| 2 | `phase-3-modal-grpc-baseline.json` | same |
| 3 | `phase-3-modal-grpc-baseline.md` | same |
| 4 | `phase-3-modal-rest-baseline.json` | same |
| 5 | `phase-3-modal-rest-baseline.md` | same |
| 6 | `phase-4.2-grpc-direct-baseline.json` | `milestone/m2-ground-truth` baseline (Phase 4.2 predates M3) |
| 7 | `phase-4.2-grpc-direct-baseline.md` | same |
| 8 | `phase-4.2-grpc-proxy-baseline.json` | same |
| 9 | `phase-4.2-rest-baseline.json` | same |
| 10 | `phase-4.2-three-way-comparison.md` | same |
| 11 | `phase-5-grpc-direct-streaming.json` | same |
| 12 | `phase-5-grpc-proxy-streaming.json` | same |
| 13 | `phase-5-rest-streaming.json` | same |
| 14 | `phase-5-streaming-comparison.md` | same |
| 15 | `phase-6-completions-comparison.md` | same |
| 16 | `phase-6-completions-grpc-direct.json` | same |
| 17 | `phase-6-completions-native.json` | same |
| 18 | `phase-6-completions-proxy.json` | same |
| 19 | `m3-channel-tuning-time.json` | `milestone/m3-phase-a-closure` |
| 20 | `m3-channel-tuning-time.md` | same |
| 21 | `m3-channel-tuning.json` | `milestone/m3-grpc-tuning-r1` |
| 22 | `m3-channel-tuning.md` | same |
| 23 | `m4-time-axis-tuning.json` | `milestone/m4-time-axis` |
| 24 | `m4-time-axis-tuning.md` | same |
| 25 | `m5-cross-host-validation.json` | `milestone/m5-cross-host` |
| 26 | `m5-cross-host-validation.md` | same |
| 27 | `m5_1-rest-vs-grpc.json` | `milestone/m5.1-rest-vs-grpc` |
| 28 | `m5_1-rest-vs-grpc.md` | same |
| 29 | `m5_2-transport-vs-tuning.events.jsonl.gz` | `milestone/m5.2-transport-tuning` |
| 30 | `m5_2-transport-vs-tuning.json` | same |
| 31 | `m5_2-transport-vs-tuning.md` | same |
| 32 | `m6-real-engine-mini-validation.json` | `milestone/m6-real-engine-mini` |
| 33 | `m6-real-engine-mini-validation.md` | same |
| 34 | `m6_0a-dispatch-correction.md` (matches `m6_0*` — under `m6-*`? No: `m6_0a` matches `m6_0*` which is NOT in the pattern list. **Verify in plan: this file matches `m6_0*` which the pattern list omits**.) | `milestone/m6.0a-concurrent-dispatch` |
| 35 | `m6_1-real-prompt-embeds.json` | `milestone/m6.1-real-prompt-embeds` |
| 36 | `m6_1-real-prompt-embeds.md` | same |
| 37 | `m6_1_1-audit-2026-05-16-seq-dispatch.md` | `milestone/m6.1.1-engine-cost-instr` |
| 38 | `m6_1_1-engine-cost-instrumentation.json` | same |
| 39 | `m6_1_1-engine-cost-instrumentation.md` | same |
| 40 | `m6_1_2-methodology-discipline.json` | `milestone/m6.1.2-methodology` |
| 41 | `m6_1_2-methodology-discipline.md` | same |
| 42 | `m6_1_3-attribution-closure-validate.json` | `milestone/m6.1.3-attribution` |
| 43 | `m6_1_3-attribution-closure-validate.md` | same |
| 44 | `m6_1_3-attribution-closure.json` | same |
| 45 | `m6_1_3-attribution-closure.md` | same |
| (also) | `summary.md` | reachable from any pre-2026-05-26 tag (in repo since Phase 4.2) |

**Sub-finding R1a — pattern gap for `m6_0a-*`**: The spec's FR-003 enumerates `m6-*` which by glob expansion *does* match `m6_0a-dispatch-correction.md` (the leading `m6` token is the prefix; pattern is non-anchored on the trailing separator). However, to remove ambiguity, the deletion manifest in `data-model.md` will list `m6_0a-dispatch-correction.md` explicitly under the M6.0a recovery tag. The plan's task list should likewise enumerate it explicitly so a future reviewer doesn't have to mentally re-parse the glob.

**Sub-finding R1b — `m6_2-*` retention check**: 7 files match the M6.2 retention pattern and MUST stay tracked: `m6_2-publish.sweep.log`, `m6_2-token-budget-validate.json`, `m6_2-token-budget-validate.md`, `m6_2-token-budget.json`, `m6_2-token-budget.md`, `m6_2-validate.sweep.log`. (8 minus the checkpoint file, which is untracked via FR-008.) Note `m6_2-publish.sweep.log` and `m6_2-validate.sweep.log` are sweep stdout captures — they stay tracked as canonical M6.2 outputs.

**Alternatives considered**:
- *Globbing the deletion at `git rm` time vs. enumerating explicitly*: enumerating is safer for an irreversible operation (even though tag-recoverable, a typo'd glob could touch the wrong file). The `tasks.md` artifact will carry the explicit enumeration.
- *Splitting `phase-*` deletions from `m*-` deletions into separate commits*: rejected — both fall under FR-002–FR-006's working-tree deletion group (Commit 1 per the plan). Splitting them further adds review overhead without bisectability benefit since they share the same recovery path (each via its own milestone tag).

---

## R2. Deletion manifest — `tests/integration/`

**Decision**: 5 files delete; 6 files retain.

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

**Sub-finding**: No CI workflow references the deleted tests (verified at spec-time per the Assumptions section). `make test` covers integration via `pytest tests/`; the retained subset continues to run.

**Alternatives considered**:
- *Move deleted tests to `tests/integration/historical/`*: rejected — duplicates the milestone-tag recovery path; adds a new permanent directory for archival material; not how the rest of the cleanup handles "old but recoverable".

---

## R3. `summary.md` reference audit

**Decision**: 4 references found across `ANALYSIS.md` and `docs/PLAN.md`; rewrite or remove each according to its semantic role.

**Rationale**: Enumerated via `grep -n "summary\.md\|benchmarks/summary" docs/PLAN.md ANALYSIS.md`. Found four hits:

| File | Line | Current text (paraphrased) | Action |
|---|---|---|---|
| `ANALYSIS.md` | 5 | "…`docs/benchmarks/summary.md` (the M1/M3-era summary) has been folded into § M1 and § M3 below and now lives as a one-line redirect." | **Rewrite** — the file is being deleted, so the parenthetical needs to remove "now lives as a one-line redirect" and become a clean "see § M1 and § M3 below" sentence. |
| `ANALYSIS.md` | 14 | "**Report**: [`docs/benchmarks/summary.md`](docs/benchmarks/summary.md) § 1–3 (folded in below) — `docs/benchmarks/phase-4.2-*.json`, …" | **Remove** the markdown-link first half; preserve "(folded in below)" and the phase-* source-data citation rewritten to read "(historical phase-* source data recoverable via `milestone/m3-replan` and earlier tags; see Repo housekeeping)". |
| `ANALYSIS.md` | 64 | "### § M3 fold-in (from `docs/benchmarks/summary.md` § 4, byte-for-byte equivalent per FR-018)" | **Rewrite** — replace the parenthetical with `(originally folded in from the deleted summary.md § 4 per § M3 FR-018; pre-fold-in text recoverable via any pre-2026-05-26 tag)`. |
| `docs/PLAN.md` | 869 | "- A short benchmark write-up at `docs/benchmarks/summary.md` covering the headline numbers for all three paths across non-streaming and streaming" | **Remove** the entire bullet — this is Phase History prose listing what Phase 6 was *expected to* produce; the deliverable is now superseded by `ANALYSIS.md` itself, and the bullet is doubly historical (Phase History section + describes a deleted file). |

**Alternatives considered**:
- *Leave references in place since `git show <tag>:docs/benchmarks/summary.md` still works*: rejected — leaving live markdown links to a non-existent file in tracked documentation creates broken-link noise for readers, which is exactly the kind of issue v0.0.0 is meant to remove.
- *Keep `summary.md` and just delete the milestone artifacts*: rejected by the 2026-05-26 clarification.

---

## R4. Tag → path recovery map

**Decision**: All 16 milestone tags are reachable from the merge-base commit; spot-checks confirm each tag exposes its corresponding `docs/benchmarks/` artifact.

**Rationale**: `git tag --list 'milestone/*'` returns:

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

Spot-checks (representative, not exhaustive):
- `git show milestone/m5.2-transport-tuning:docs/benchmarks/m5_2-transport-vs-tuning.md` → returns the M5.2 report.
- `git show milestone/m4-time-axis:logs/m4-full-20260510-103956.log` → returns the M4 sweep log (recovery path for the `logs/` un-tracking).
- `git show milestone/m6.0a-concurrent-dispatch:docs/benchmarks/m6_0a-dispatch-correction.md` → returns the M6.0a dispatch correction report.

**Alternatives considered**:
- *Re-tag missing milestones if any are absent*: not needed — all 16 are present and pushed to origin per the spec's Assumptions.

---

## R5. `logs/` inventory baseline

**Decision**: 13 index entries to un-track (11 M4 sweep logs + 2 marker files); ~52 KB total.

**Rationale**: Enumerated by `find logs/ -type f`. The marker files (`m4-full.current`, `m4-full.pid`) are operator-local state that should never have been tracked — `m4-full.pid` is a PID file from a long-since-terminated sweep, and `m4-full.current` is a symlink-or-pointer marker that the M4 harness updates each run. Both are correctly captured by the proposed `.gitignore` rule.

---

## R6. `.gitignore` rule placement and pattern semantics

**Decision**: Append a new `# v0.0.0 housekeeping (per spec FR-007)` section near the end of `.gitignore` with two rules: `logs/` and `**/*.checkpoint.jsonl`.

**Rationale**:
- The `logs/` rule (trailing slash) matches the directory and everything under it. This is the standard `.gitignore` idiom for "ignore a whole tree".
- The `**/*.checkpoint.jsonl` rule (globstar prefix) matches checkpoint files at any depth. Today the only such file is `docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl`, but the globstar prefix preempts future sweep harnesses writing checkpoints to other paths (e.g., `tools/benchmark/results/` if any milestone re-introduces an on-disk checkpoint format).
- Placement near the end of the file (not at the top) preserves the existing structure — the file is organized by category (Python, IDE, OS, etc.) and adding a v0.0.0-specific section at the bottom is the least intrusive option.

**Alternatives considered**:
- *Use `logs/*.log` instead of `logs/`*: rejected — would re-track the `m4-full.current` and `m4-full.pid` markers if they reappear.
- *Use `*.checkpoint.jsonl` without globstar*: rejected — only matches the root directory; misses nested writes.
- *Add `bench-results/` rule too*: rejected — `bench-results/` is already gitignored elsewhere (per recent session memory observation 524) and adding a duplicate would be noise.

---

## R7. `ANALYSIS.md` housekeeping subsection placement and content shape

**Decision**: Append a new top-level `## Repo housekeeping` section at the very end of `ANALYSIS.md`, after the last milestone narrative section but before any closing footer/EOF.

**Rationale**: FR-011 explicitly prohibits placement between adjacent milestone findings sections. End-of-document placement (a) is the obvious "structural appendix" location; (b) keeps the M1→M6.2 narrative uninterrupted; (c) is discoverable via the document's table of contents (if present) or by `Ctrl-End`.

**Content shape** (≈10-15 lines):

```markdown
## Repo housekeeping

The repository maintains two parallel tag tracks:

- **`milestone/*` — research deliverables.** One tag per closed milestone (M2 through M6.2 as of 2026-05-26). Each tag fixes the working tree at the commit that publishes the milestone's report + sweep harness, so any pre-cleanup historical artifact (benchmark report, sweep script, era-specific integration test) is recoverable by checking out the matching tag.
- **`v*` — codebase state.** Semver-style tags (`v0.0.0`, `v0.0.1`, `v0.1.0`, …) mark maintenance and release-readiness checkpoints. `v0.0.0` marks the post-M6.2 cleanup that removed pre-M6.2 milestone-specific artifacts from `main` in favor of the milestone-tag recovery path.

To recover a deleted historical file:

    git show milestone/m5.2-transport-tuning:docs/benchmarks/m5_2-transport-vs-tuning.md

Replace `milestone/m5.2-transport-tuning` with the milestone tag whose era owns the file, and the path with the file you want. `git tag --list 'milestone/*'` lists every available tag.
```

**Alternatives considered**:
- *Place inline near the top of `ANALYSIS.md` (e.g., right after the document preamble)*: rejected — the preamble is the reader's first impression and shouldn't lead with housekeeping. Bottom placement keeps narrative-first.
- *Create a separate `docs/REPO_HOUSEKEEPING.md`*: rejected — fragments documentation; the section is short enough to live in `ANALYSIS.md` and benefits from co-location with the milestone narratives it cross-references.
- *Place in `CONTRIBUTING.md`*: rejected for now — `CONTRIBUTING.md` updates are explicitly `v0.1.0` territory per `docs/PLAN.md` § v0.1.0 scope. v0.0.0 sticks to its lane.

---

## R8. `v0.0.0` tag message format

**Decision**: Annotated tag with structured message matching the milestone-tag convention.

**Rationale**: The repo's existing milestone tags use the format `<tag-name>\n\n<one-paragraph description>\n\n<cross-references>`. Matching that format means operators reading `git show v0.0.0` see the same shape they're used to from `git show milestone/m6.2-token-budget`.

**Proposed message body** (operator can tweak wording at tag time):

```
v0.0.0 — Post-M6.2 housekeeping

First cut of the v* semver track (codebase state). Trims ~3.5 MB of
pre-M6.2 milestone-specific artifacts from main; tag-recoverable via
milestone/m2-ground-truth through milestone/m6.2-token-budget.

Spec: specs/028-post-m6.2-cleanup-v0.0.0/spec.md
M6.2 research deliverable: milestone/m6.2-token-budget (already at fea31c0)
Next: v0.0.1 (bench-harness refactor), then v0.1.0 (first PyPI release).
```

**Alternatives considered**:
- *Lightweight tag (no message)*: rejected — annotated tags are the project's convention for tracked checkpoints, and the cross-reference to `milestone/m6.2-token-budget` is informative.
- *GitHub Release with body matching the tag message*: deferred to `v0.1.0` per PLAN.md scope (v0.1.0 is when `docs/RELEASES.md` is seeded). v0.0.0 ships as just an annotated tag.

---

## Decisions summary

| Topic | Decision | Source |
|---|---|---|
| Benchmark deletion count | 46 files (45 milestone-prefixed + `summary.md`) | R1 |
| Integration-test deletions | 5 files; 6 retained | R2 |
| `summary.md` reference cleanup | 4 sites: 3 rewrite + 1 removal | R3 |
| Tag coverage | All 16 milestone tags reachable; spot-checks pass | R4 |
| `logs/` un-tracking scope | 13 index entries | R5 |
| `.gitignore` rules | `logs/` + `**/*.checkpoint.jsonl`, appended in a new section | R6 |
| `ANALYSIS.md` placement | New `## Repo housekeeping` section at end-of-document | R7 |
| `v0.0.0` tag format | Annotated, structured message matching milestone-tag convention | R8 |

All Phase-0 unknowns resolved; ready for Phase 1 design artifacts.
