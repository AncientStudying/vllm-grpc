# Quickstart: v0.0.0 — Post-M6.2 Housekeeping

**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Date**: 2026-05-26 (re-derived after clarify cycle adding FR-003 exception)

Operator runbook for executing the v0.0.0 cleanup locally and verifying every functional requirement and success criterion before opening the PR. The whole runbook takes ~10–15 minutes from a fresh clone, dominated by `make lint typecheck test` runtime.

---

## Prerequisites

- Clean working tree on branch `chore/post-m6.2-cleanup-v0.0.0`. `git status` should show no unstaged changes; only the spec/plan/research/data-model artifacts from this milestone series should be in `git log` since `fea31c0` (the M6.2 merge commit).
- `make`, `python` (≥3.12), `ruff`, `mypy`, `pytest` all functional locally (the standard project toolchain).
- All 16 `milestone/*` tags fetched: `git fetch --tags origin` and `git tag --list 'milestone/*' | wc -l` returns `16`.
- `gh` CLI authenticated (only needed for opening the PR at the end).

---

## Step 0 — Baseline measurement (one minute)

Capture the pre-cleanup baselines so the post-cleanup verification has real comparison points. The primary SC-002 input is the **tracked-file count** (per the 2026-05-26 clarification — file cleanup is the primary value of the beat).

```bash
# Primary SC-002 metric: tracked file count at fea31c0 baseline.
git ls-files | wc -l | tee /tmp/v0.0.0-file-count-baseline.txt

# Secondary: tracked size for headline framing (not the SC-002 floor).
du -sh \
  docs/benchmarks/ \
  tests/integration/ \
  scripts/python/ \
  scripts/setup/ \
  M6_2-ANALYSIS-FRAMING-DRAFT.md \
  logs/ \
  2>&1 | tee /tmp/v0.0.0-size-baseline.txt
```

Expected baseline (2026-05-26 measurement): tracked files at `fea31c0` ≈ 1180; tracked sizes `docs/benchmarks 3.4M`, `tests/integration 152K`, `scripts/python 360K`, `scripts/setup 4K`, `M6_2-ANALYSIS-FRAMING-DRAFT.md 16K`, `logs 52K`.

Confirm M6.2 fake-backed smoke is green pre-cleanup:

```bash
make check 2>&1 | tail -20
# Expected: 1575 passed / 0 failed / 2 skipped (or comparable green state)
#
# Pre-existing baseline note: at fea31c0, the obsolete tests
# `tests/integration/test_m4_schema_e2e.py::test_m4_with_schema_candidates_end_to_end`
# and `tests/integration/test_m4_sweep_e2e.py::test_m4_skip_schema_end_to_end` may
# fail (M4SweepConfig signature drift); both files are in Commit 1's deletion set,
# so the failure resolves once Commit 1 lands. Per FR-013's "no regression vs
# fea31c0" framing, this is acceptable.
```

---

## Step 1 — Commit 1: Working-tree deletions + summary.md reference cleanup

Covers FR-002–FR-006 and FR-003a. **45 file-index removals in this commit** (1 root draft + 37 in `docs/benchmarks/` + 5 in `tests/integration/` + 1 in `scripts/python/` + 1 in `scripts/setup/`, plus 4 reference rewrites).

**FR-003 exception (per 2026-05-26 clarification)**: the following 9 baseline-chain JSONs MUST NOT be deleted. They are runtime inputs to `tools/benchmark/src/`:

- `docs/benchmarks/m3-channel-tuning-time.json`
- `docs/benchmarks/m4-time-axis-tuning.json`
- `docs/benchmarks/m5-cross-host-validation.json`
- `docs/benchmarks/m5_1-rest-vs-grpc.json`
- `docs/benchmarks/m5_2-transport-vs-tuning.json`
- `docs/benchmarks/m6-real-engine-mini-validation.json`
- `docs/benchmarks/m6_1-real-prompt-embeds.json`
- `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json`
- `docs/benchmarks/m6_1_3-attribution-closure.json`

Audit anchor: `grep -hoE 'docs/benchmarks/[^"'\'']+\.json' tools/benchmark/src/vllm_grpc_bench/*.py | sort -u` returns this list (plus M6.2's own outputs).

```bash
# Root draft note (FR-002)
git rm M6_2-ANALYSIS-FRAMING-DRAFT.md

# Benchmark milestone artifacts — .md writeups, 1 .gz sidecar, 2 output-only .json,
# 13 phase-* files, summary.md, m3-channel-tuning.json (bytes-axis output, not chain input).
# The 9 baseline-chain JSONs in the FR-003 exception list above are NOT included.
git rm \
  docs/benchmarks/phase-3-modal-comparison.md \
  docs/benchmarks/phase-3-modal-grpc-baseline.json \
  docs/benchmarks/phase-3-modal-grpc-baseline.md \
  docs/benchmarks/phase-3-modal-rest-baseline.json \
  docs/benchmarks/phase-3-modal-rest-baseline.md \
  docs/benchmarks/phase-4.2-grpc-direct-baseline.json \
  docs/benchmarks/phase-4.2-grpc-direct-baseline.md \
  docs/benchmarks/phase-4.2-grpc-proxy-baseline.json \
  docs/benchmarks/phase-4.2-rest-baseline.json \
  docs/benchmarks/phase-4.2-three-way-comparison.md \
  docs/benchmarks/phase-5-grpc-direct-streaming.json \
  docs/benchmarks/phase-5-grpc-proxy-streaming.json \
  docs/benchmarks/phase-5-rest-streaming.json \
  docs/benchmarks/phase-5-streaming-comparison.md \
  docs/benchmarks/phase-6-completions-comparison.md \
  docs/benchmarks/phase-6-completions-grpc-direct.json \
  docs/benchmarks/phase-6-completions-native.json \
  docs/benchmarks/phase-6-completions-proxy.json \
  docs/benchmarks/m3-channel-tuning-time.md \
  docs/benchmarks/m3-channel-tuning.json \
  docs/benchmarks/m3-channel-tuning.md \
  docs/benchmarks/m4-time-axis-tuning.md \
  docs/benchmarks/m5-cross-host-validation.md \
  docs/benchmarks/m5_1-rest-vs-grpc.md \
  docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz \
  docs/benchmarks/m5_2-transport-vs-tuning.md \
  docs/benchmarks/m6-real-engine-mini-validation.md \
  docs/benchmarks/m6_0a-dispatch-correction.md \
  docs/benchmarks/m6_1-real-prompt-embeds.md \
  docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md \
  docs/benchmarks/m6_1_1-engine-cost-instrumentation.md \
  docs/benchmarks/m6_1_2-methodology-discipline.json \
  docs/benchmarks/m6_1_2-methodology-discipline.md \
  docs/benchmarks/m6_1_3-attribution-closure-validate.json \
  docs/benchmarks/m6_1_3-attribution-closure-validate.md \
  docs/benchmarks/m6_1_3-attribution-closure.md \
  docs/benchmarks/summary.md

# Integration tests (FR-004)
git rm \
  tests/integration/test_m4_schema_e2e.py \
  tests/integration/test_m4_sweep_e2e.py \
  tests/integration/test_m5_modal_smoke.py \
  tests/integration/test_m5_1_modal_smoke.py \
  tests/integration/test_m5_2_modal_smoke.py

# Stale scripts (FR-005, FR-006)
git rm scripts/python/reprocess_m5_supersede.py
git rm scripts/setup/phase2-env.sh
```

**Reference rewrites (FR-003a)** — confirm line numbers first:

```bash
grep -n "summary\.md" ANALYSIS.md docs/PLAN.md
# Expected hits: ANALYSIS.md:5, ANALYSIS.md:14, ANALYSIS.md:64, docs/PLAN.md:869
```

Apply the four edits per the `data-model.md` Entity 4 table. Stage and commit:

```bash
git add -u ANALYSIS.md docs/PLAN.md

git commit -m "$(cat <<'EOF'
v0.0.0(1/5): trim pre-M6.2 milestone artifacts + obsolete tests

Removes the pre-M6.2 working-tree clutter named in spec FR-002 through
FR-006 and cleans the four dangling `docs/benchmarks/summary.md`
references in `ANALYSIS.md` and `docs/PLAN.md` (FR-003a).

Per the FR-003 exception (2026-05-26 clarification), the 9 baseline-chain
JSONs that `tools/benchmark/src/` reads at runtime stay tracked:
  - m3-channel-tuning-time.json, m4-time-axis-tuning.json
  - m5-cross-host-validation.json, m5_1-rest-vs-grpc.json
  - m5_2-transport-vs-tuning.json
  - m6-real-engine-mini-validation.json, m6_1-real-prompt-embeds.json
  - m6_1_1-engine-cost-instrumentation.json, m6_1_3-attribution-closure.json

All deleted paths remain reachable through their owning `milestone/m*`
tag — see specs/028-post-m6.2-cleanup-v0.0.0/data-model.md Entity 1 for
the path → tag map and § "Repo housekeeping" (added in commit 5/5) for
the operator-facing recovery procedure.

Files touched: 45 deletions, 4 documentation edits (3 in ANALYSIS.md,
1 in docs/PLAN.md). No source code under tools/benchmark/src/,
packages/, proto/, or frontend/ is modified.
EOF
)"
```

**Verify after commit**:

```bash
# FR-002 verification
test ! -e M6_2-ANALYSIS-FRAMING-DRAFT.md && echo "FR-002 OK"

# FR-003 verification — JSONs in the FR-003 exception MUST exist; all others matching the prefixes MUST be gone.
for f in m3-channel-tuning-time.json m4-time-axis-tuning.json m5-cross-host-validation.json \
         m5_1-rest-vs-grpc.json m5_2-transport-vs-tuning.json m6-real-engine-mini-validation.json \
         m6_1-real-prompt-embeds.json m6_1_1-engine-cost-instrumentation.json \
         m6_1_3-attribution-closure.json; do
  test -e "docs/benchmarks/$f" || { echo "FR-003 EXCEPTION FAIL: $f missing"; exit 1; }
done
echo "FR-003 exception OK (all 9 baseline-chain JSONs present)"

# Pattern check: deletion-target prefixes should match only the 9 retained chain JSONs + m6_2-* outputs.
ls docs/benchmarks/ | grep -cE '^(phase-|m3-|m4-|m5-|m5_1-|m5_2-|m6-|m6_0a-|m6_1-|m6_1_1-|m6_1_2-|m6_1_3-)|^summary\.md$'
# Expected: 9 (the 9 baseline-chain JSONs; everything else with these prefixes is gone)

# FR-004 verification (the 6 retained files are present, no obsolete files)
ls tests/integration/ | grep -v __pycache__
# Expected: __init__.py conftest.py fake_frontend.py test_chat_bridge.py test_completions_bridge.py test_grpc_client.py

# FR-003a verification (no broken markdown links remain)
grep -nE "\]\(docs/benchmarks/summary\.md\)|\]\(summary\.md\)" ANALYSIS.md docs/PLAN.md README.md
# Expected: no output (informative prose mentions of the deleted path in code-spans are intentional)
```

---

## Step 2 — Commit 2: Un-track the `logs/` directory

Covers FR-008 for the `logs/` portion.

```bash
git rm -r --cached logs/
git commit -m "$(cat <<'EOF'
v0.0.0(2/5): un-track logs/ (M4 sweep stdout captures)

git rm --cached removes the 13 M4-era log files from the index; they stay
on disk for any operator who has run the M4 sweep, but a fresh clone no
longer carries them. The `.gitignore` rule landed in commit 4/5 prevents
re-tracking.

Recoverable via `milestone/m4-time-axis`.
EOF
)"
```

**Verify**: `git ls-files logs/ | wc -l` returns `0`.

---

## Step 3 — Commit 3: Un-track the M6.2 checkpoint

Covers FR-008 for the checkpoint portion.

```bash
git rm --cached docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl
git commit -m "$(cat <<'EOF'
v0.0.0(3/5): un-track M6.2 sweep checkpoint

The `*.checkpoint.jsonl` family is mid-sweep runtime state, not a published
artifact — the canonical M6.2 outputs are `m6_2-token-budget.{json,md}` and
those stay tracked. This file was bundled into the spec commit (3646f8e)
by the `after_specify` auto-commit hook; this commit reverses that.

The file stays on the operator's disk; the `.gitignore` rule landed in
commit 4/5 prevents re-tracking. Recoverable from `milestone/m6.2-token-budget`.
EOF
)"
```

**Verify**: `git ls-files docs/benchmarks/ | grep checkpoint` returns empty; `test -e docs/benchmarks/m6_2-token-budget.json.checkpoint.jsonl && echo "On-disk OK"`.

---

## Step 4 — Commit 4: `.gitignore` rules

Covers FR-007.

```bash
cat >> .gitignore <<'EOF'

# v0.0.0 housekeeping (per spec FR-007)
logs/
**/*.checkpoint.jsonl
EOF

git add .gitignore
git commit -m "$(cat <<'EOF'
v0.0.0(4/5): gitignore logs/ and checkpoint files

Prevents `logs/` and `**/*.checkpoint.jsonl` paths from re-entering the
index. The globstar prefix on the checkpoint pattern preempts future
sweep harnesses that may write checkpoints under different parent
directories.
EOF
)"
```

**Verify**:

```bash
git check-ignore -v logs/probe.log
# Expected: .gitignore:<line> logs/    logs/probe.log

git check-ignore -v docs/benchmarks/anything.checkpoint.jsonl
# Expected: .gitignore:<line> **/*.checkpoint.jsonl    docs/benchmarks/anything.checkpoint.jsonl

# Confirm M6.2 final outputs are NOT ignored
git check-ignore -v docs/benchmarks/m6_2-token-budget.json
# Expected: no output (not ignored)
```

---

## Step 5 — Commit 5: `ANALYSIS.md` "Repo housekeeping" subsection

Covers FR-009, FR-010, FR-011.

Append to the end of `ANALYSIS.md`:

```markdown
## Repo housekeeping

The repository maintains two parallel tag tracks:

- **`milestone/*` — research deliverables.** One tag per closed milestone (M2 through M6.2 as of 2026-05-26). Each tag fixes the working tree at the commit that publishes the milestone's report + sweep harness, so any pre-cleanup historical artifact (benchmark report, sweep script, era-specific integration test) is recoverable by checking out the matching tag.
- **`v*` — codebase state.** Semver-style tags (`v0.0.0`, `v0.0.1`, `v0.1.0`, …) mark maintenance and release-readiness checkpoints. `v0.0.0` marks the post-M6.2 cleanup that removed pre-M6.2 milestone-specific `.md` writeups + obsolete tests + scripts from `main`; the 9 baseline-chain JSON data files (M3→M6.2) stay tracked because the sweep harness reads them at runtime.

To recover a deleted historical narrative:

    git show milestone/m5.2-transport-tuning:docs/benchmarks/m5_2-transport-vs-tuning.md

Replace `milestone/m5.2-transport-tuning` with the milestone tag whose era owns the file, and the path with the file you want. `git tag --list 'milestone/*'` lists every available tag.
```

```bash
git add ANALYSIS.md
git commit -m "$(cat <<'EOF'
v0.0.0(5/5): ANALYSIS.md "Repo housekeeping" section

Adds a short end-of-document subsection documenting the v*/milestone/* dual
tag convention and providing the canonical `git show <tag>:<path>` recovery
incantation. Placement at end-of-document keeps the milestone narrative
flow uninterrupted (spec FR-011). Acknowledges the FR-003 exception that
keeps the 9 baseline-chain JSONs tracked.

Covers FR-009, FR-010, FR-011.
EOF
)"
```

**Verify**:

```bash
grep -n "^## Repo housekeeping$" ANALYSIS.md
# Expected: exactly one match, at a line near end-of-file

time git show milestone/m5.2-transport-tuning:docs/benchmarks/m5_2-transport-vs-tuning.md | head -1
# Expected: M5.2 report's first line, in well under 1 second (SC-007 budget is 30 s)
```

---

## Step 6 — Pre-PR verification

Run the full quality gate. **FR-013 + SC-005 + FR-014 + SC-006 gate.**

```bash
make check 2>&1 | tee /tmp/v0.0.0-postcleanup.txt
echo "Exit code: $?"
# Expected: 0 (all green; the previously-failing M4 obsolete tests are gone)
```

Compute the SC-002 file-count delta. **SC-002 gate.**

```bash
git ls-files | wc -l | tee /tmp/v0.0.0-file-count-after.txt
# Compute delta against /tmp/v0.0.0-file-count-baseline.txt — should show ≥50 fewer files.

baseline=$(cat /tmp/v0.0.0-file-count-baseline.txt)
after=$(cat /tmp/v0.0.0-file-count-after.txt)
echo "Reduction: $((baseline - after)) tracked files (SC-002 floor: ≥50)"
```

Pre-push FR-001 source-preservation check:

```bash
git diff --name-only fea31c0..HEAD -- tools/benchmark/src/ packages/ proto/ frontend/ | wc -l
# Expected: 0 (FR-001 invariant — no source file modified by any of Commits 1–5)
```

---

## Step 7 — Open the PR

```bash
git push -u origin chore/post-m6.2-cleanup-v0.0.0

gh pr create \
  --base main \
  --title "v0.0.0 — Post-M6.2 housekeeping" \
  --body "$(cat <<'EOF'
## Summary

- Removes ~59 tracked files of pre-M6.2 milestone-specific clutter from `main` per spec [028-post-m6.2-cleanup-v0.0.0](specs/028-post-m6.2-cleanup-v0.0.0/spec.md).
- Five bisectable commits; each independently revertable. No source-code changes under `tools/benchmark/src/`, `packages/`, `proto/`, or `frontend/`.
- **FR-003 exception (per 2026-05-26 clarification)**: 9 baseline-chain JSONs in `docs/benchmarks/` stay tracked — the M3→M6.2 sweep harness reads them at runtime via default-path constants. Audit anchor: `grep -hoE 'docs/benchmarks/[^"'\'']+\.json' tools/benchmark/src/vllm_grpc_bench/*.py | sort -u`.
- All deleted paths recoverable via the corresponding `milestone/m*` tag; the new `ANALYSIS.md` § "Repo housekeeping" documents the recovery path.

## Test plan

- [ ] `make check` green on the branch (FR-013 / SC-005 / FR-014 / SC-006).
- [ ] `ls docs/benchmarks/` shows only `m6_2-*` files + the 9 FR-003 exception JSONs (SC-001).
- [ ] Working-tree count reduction ≥50 tracked files vs `fea31c0` (SC-002).
- [ ] `git show milestone/m5.2-transport-tuning:docs/benchmarks/m5_2-transport-vs-tuning.md` returns the M5.2 report (SC-004 spot check).
- [ ] `git check-ignore -v logs/probe.log` and `git check-ignore -v docs/benchmarks/anything.checkpoint.jsonl` both confirm the new rules fire (FR-007).
- [ ] `git diff --name-only fea31c0..HEAD -- tools/benchmark/src/ packages/ proto/ frontend/ | wc -l` returns 0 (FR-001).
- [ ] Both `v0.0.0` and `milestone/m6.2-token-budget` tags reachable from the merge commit after merge + tag creation (SC-008).

## Post-merge actions

1. On `main` at the merge commit, run `git tag -a v0.0.0` with the message body from `research.md` § R8.
2. `git push origin v0.0.0`.
3. Confirm `git show v0.0.0` displays the structured message and the merge commit.

EOF
)"
```

---

## Step 8 — Post-merge: `v0.0.0` tag creation

After the PR merges to `main`:

```bash
git checkout main && git pull origin main
git log -1   # confirm the merge commit hash

git tag -a v0.0.0 -m "$(cat <<'EOF'
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
EOF
)"

git push origin v0.0.0
```

**Verify**:

```bash
git ls-remote --tags origin v0.0.0 milestone/m6.2-token-budget
# Expected: both present on origin (SC-008)
```

---

## Rollback procedure

Each commit is independently revertable. Recovery of any individual deleted file (without a full commit revert) stays available through the milestone-tag mechanism documented in the new `ANALYSIS.md` § "Repo housekeeping".

---

## Acceptance checklist (mirrors spec § Success Criteria)

- [ ] SC-001: `ls docs/benchmarks/` returns only `m6_2-*` files + the 9 FR-003 exception JSONs.
- [ ] SC-002: ≥50 fewer tracked files (`git ls-files | wc -l` delta vs `fea31c0`).
- [ ] SC-003: Fresh `git clone` produces clean `git status` on a sweep-naive machine.
- [ ] SC-004: All 16 milestone tags' representative files recoverable via `git show <tag>:<path>`.
- [ ] SC-005: `make lint typecheck test` exit code 0 (Step 6).
- [ ] SC-006: M6.2 fake-backed smoke (`test_m6_2_validate_cli.py` + `test_m6_2_publish_cli.py` within `make test`) exit code 0.
- [ ] SC-007: Reader can recover an arbitrary deleted narrative in ≤30 seconds using the new subsection.
- [ ] SC-008: `git ls-remote --tags origin v0.0.0 milestone/m6.2-token-budget` shows both tags.
