# Quickstart: M6.0a — Concurrent Dispatch Restoration

**Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md)

## Audience

The operator implementing M6.0a end-to-end. Prerequisites: familiarity with the project's `feedback_local_lint_chain` (ruff / mypy / pytest local-CI parity), Modal token setup, and the M5.1 / M6.1.1 sweep operator playbooks.

## Pre-flight checks

```bash
# 1. Confirm you're on the M6.0a branch.
git status   # → On branch 024-m6-0a-concurrent-dispatch, clean

# 2. Confirm M6.1.1 PR #27 is still open (held open during M6.0a per FR-018).
gh pr view 27 --json state --jq '.state'   # → OPEN

# 3. Confirm the audit baseline is preserved at b63947a.
git show b63947a:docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md | head -5
#  → "# M6.1.1 — Audit Data, Sequential-Dispatch Baseline (2026-05-16)"
```

## PR-1: harness fix + regression test

This PR is harness-only — no Modal compute, no published benchmark artifact. It exists to unblock M6.1.1 PR #27 the moment it merges.

### Step 1 — apply the fix to five dispatch entry points

Per [plan.md § Project Structure](./plan.md#project-structure):

1. `tools/benchmark/src/vllm_grpc_bench/m6_sweep.py:189` (`_run_warmup`) and `:219` (`_run_measurement`).
2. `tools/benchmark/src/vllm_grpc_bench/m6_1_sweep.py:141` (`_run_warmup_m6_1`) and `:160` (`_run_measurement_m6_1`).
3. `tools/benchmark/src/vllm_grpc_bench/m6_1_1_sweep.py:233` (`_measure_cell` — both warmup and measurement loops).

Use the patterns in [contracts/dispatch.md](./contracts/dispatch.md). Within-cohort gather; across-cohort sequential. Round-robin per-c-batch index allocator unchanged on M6 / M6.1 paths.

### Step 2 — update `concurrency` field docstrings (FR-006)

In `m6_types.py`, `m6_1_types.py`, `m6_1_1_types.py`: revise the docstring on each `Cell` dataclass's `concurrency: int` field from "metadata tag for round-robin sequencing" to "actual in-flight parallelism (peak concurrent RPCs per cohort within a c-batch)".

### Step 3 — extend `m6_1_1_reporter.py` to emit `dispatch_mode`

In the manifest assembly path (the function that builds the top-level dict before `json.dumps`):

```python
manifest["dispatch_mode"] = "concurrent"
```

Place it adjacent to `schema_version` for discoverability. Per [contracts/output.md](./contracts/output.md), the value is unconditional `"concurrent"` after PR-1 lands.

### Step 4 — author the regression test

Create `tools/benchmark/tests/test_m6_concurrent_dispatch.py` per the design in [contracts/dispatch.md](./contracts/dispatch.md). Three parametrised tests:

- `test_concurrent_dispatch_peak` — covers `(concurrency, entry_point)` ∈ `{1, 4, 8} × {m6, m6_1, m6_1_1}` (9 cases). Asserts `probe.peak == concurrency`.
- `test_warmup_concurrent_dispatch_peak` — covers `concurrency == 4` × all 3 entry points (3 cases). Asserts warmup also bursts concurrently per FR-005a.
- `test_seed_determinism_under_concurrent_dispatch` — covers `concurrency ∈ {1, 4}` × all 3 entry points (6 cases). Records `(cohort, seed)` triples emitted by the probe and asserts the set equals the pre-fix harness's known-good seed sequence (per FR-002 + Acceptance Scenario 1.4).

### Step 5 — local lint chain (per `feedback_local_lint_chain`)

```bash
ruff check tools/benchmark
ruff format --check tools/benchmark
mypy --strict tools/benchmark/src/vllm_grpc_bench tools/benchmark/tests
pytest tools/benchmark/tests -k "concurrent_dispatch or m6_1_1 or m6_1 or m6_sweep" -x
```

All four gates MUST pass before push. The new regression test file MUST be picked up by the `-k` filter. Any failure means halt-and-fix before opening PR-1.

### Step 6 — open PR-1

```bash
git push -u origin 024-m6-0a-concurrent-dispatch
gh pr create --base main --title "M6.0a PR-1: Restore concurrent dispatch in M6 / M6.1 / M6.1.1 measurement loops" --body "$(cat <<'EOF'
## Summary

- Restores `asyncio.gather`-based concurrent dispatch to five M6.x measurement / warmup entry points (peak in-flight = c per FR-001).
- Adds path-agnostic regression test asserting `probe.peak == c` at c=1/4/8 across all three entry points (FR-003).
- Extends `m6_1_1_reporter.py` to emit `dispatch_mode: "concurrent"` as a strict-superset top-level manifest key (FR-007).
- Reverts `concurrency` field docstring from "metadata-only" back to M5.x in-flight semantics (FR-006).

## Test plan

- [ ] `pytest tools/benchmark/tests/test_m6_concurrent_dispatch.py` passes all 18 parametrisations.
- [ ] No regression in existing M6.1.1 / M6.1 / M6 unit tests.
- [ ] Local lint chain (ruff check, ruff format --check, mypy --strict, pytest) clean.
- [ ] M6.1.1 PR #27 unblocked once this merges.

## Context

M6.0a — Concurrent Dispatch Restoration. See [`docs/PLAN.md`](docs/PLAN.md) § M6.0a and [`specs/024-m6-0a-concurrent-dispatch/spec.md`](specs/024-m6-0a-concurrent-dispatch/spec.md). The bug was discovered during M6.1.1's first live Phase 1 run (2026-05-16); the audit baseline is committed at b63947a.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

After PR-1 merges, M6.1.1 PR #27 can rebase onto the updated `main` and proceed to its own merge gate.

---

## PR-2: corrected-dispatch re-run + dispatch-correction note

This PR is the data-publish PR. It depends on PR-1 being merged to `main` first.

### Step 1 — pin to audit-baseline dependency versions (FR-008)

Per [research.md § R-5](./research.md#r-5--version-pinning-mechanism-for-the-pr-2-corrected-dispatch-re-run):

```bash
# From M6.0a's branch (or a fresh branch off main after PR-1 merges):
git fetch origin
git checkout 024-m6-0a-concurrent-dispatch  # or a sibling branch off main

# Pin lockfile to b63947a's resolved set:
git checkout b63947a -- uv.lock
uv sync --frozen

# Verify the audit-baseline pins are in place:
uv pip show vllm  | grep '^Version:'   # expect: 0.20.1
uv pip show torch | grep '^Version:'   # expect: 2.11.0
```

### Step 2 — confirm Modal token and region

```bash
modal token new   # if not already authenticated
export MODAL_BENCH_TOKEN="$(modal token current)"   # or the project's standard secret name
```

Audit-baseline region is `eu-west-1`; do not change it (FR-008).

### Step 3 — run the corrected-dispatch sweep

```bash
python -m vllm_grpc_bench --m6_1_1-diagnose --m6_1_1-modal-region=eu-west-1 2>&1 | tee /tmp/m6_0a-rerun.log
```

Expected wall-clock (per SC-002): ≤ 45 min. Audit baseline ran in 26.7 min under sequential dispatch — the corrected run may be slightly faster (concurrent dispatch reduces total wall-clock if the engine is throughput-limited) or modestly slower (if Modal-side queueing adds overhead). Either is within the SC-002 budget.

Operator should see per-pair progress lines from `M6_1_1ProgressReporter` (already landed on the M6.1.1 branch).

### Step 4 — verify artifact emission

```bash
# Markdown:
ls -la docs/benchmarks/m6_1_1-engine-cost-instrumentation.md
head -30 docs/benchmarks/m6_1_1-engine-cost-instrumentation.md
#  expect a "Dispatch mode: concurrent" line in the methodology section.

# JSON:
ls -la docs/benchmarks/m6_1_1-engine-cost-instrumentation.json
jq -r '.dispatch_mode' docs/benchmarks/m6_1_1-engine-cost-instrumentation.json
#  expect: "concurrent"

# Phase 2 verdict bucket (per FR-010 + SC-003):
jq -r '.phase_2_outcome' docs/benchmarks/m6_1_1-engine-cost-instrumentation.json
#  expect: one of "below 5 %", "at or above 10 %", "intermediate per FR-010 classifier output"
```

### Step 5 — author the dispatch-correction note

Create `docs/benchmarks/m6_0a-dispatch-correction.md` per [data-model.md § Dispatch-Correction Note](./data-model.md#6-dispatch-correction-note). The note is a single page with six sections (What broke / The fix / The regression test / Before vs after / Implication for M6.x findings / Cross-links). Pull the per-cohort spread numbers from the audit baseline markdown (`docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md` Multi-Point Timing Table) and the corrected-run markdown.

### Step 6 — add M6.1 cross-link annotation (FR-016)

In `docs/benchmarks/m6_1-real-prompt-embeds.md`, locate the per-cohort drift section (the one that originally fired `engine_cost_drift_warning`) and append a one-line cross-link annotation:

```markdown
> **M6.0a methodology-supersedence note**: the per-cohort `engine_ttft_ms` drift reported in this section is interpreted under the corrected-dispatch baseline established by [M6.0a's dispatch-correction note](./m6_0a-dispatch-correction.md). See M6.0a for the dispatch-sensitive vs dispatch-robust classification of M6.1's findings.
```

### Step 7 — local lint chain (per `feedback_local_lint_chain`)

```bash
ruff check tools/benchmark
ruff format --check tools/benchmark
mypy --strict tools/benchmark/src/vllm_grpc_bench tools/benchmark/tests
pytest tools/benchmark/tests -x
```

PR-2 contains no new code (it's a data-publish PR), so the lint chain primarily verifies that the artifact files don't break any existing doc-link checks.

### Step 8 — open PR-2

```bash
git add docs/benchmarks/m6_1_1-engine-cost-instrumentation.md \
        docs/benchmarks/m6_1_1-engine-cost-instrumentation.json \
        docs/benchmarks/m6_0a-dispatch-correction.md \
        docs/benchmarks/m6_1-real-prompt-embeds.md
git commit -m "M6.0a PR-2: Publish corrected-dispatch artifact + dispatch-correction note

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

git push
gh pr create --base main --title "M6.0a PR-2: Corrected-dispatch artifact + dispatch-correction note" --body "$(cat <<'EOF'
## Summary

- Publishes the corrected-dispatch M6.1.1 Phase 1 artifact (`docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}`) with `dispatch_mode: concurrent` top-level key.
- Adds the dispatch-correction note (`docs/benchmarks/m6_0a-dispatch-correction.md`) cross-linking audit baseline, corrected run, PR #27, and PLAN.md M6.0a.
- Annotates M6.1's published narrative with a methodology-supersedence cross-link in the per-cohort drift section.

## Test plan

- [ ] Dispatch-correction note renders cleanly on GitHub.
- [ ] All four cross-links resolve (audit baseline / corrected run / PR #27 / PLAN.md).
- [ ] M6.1 cross-link annotation lands in the correct narrative section.
- [ ] Phase 2 verdict bucket recorded as a single explicit manifest field.

## Context

M6.0a PR-2 of 2. Depends on PR-1 (already merged). See [`specs/024-m6-0a-concurrent-dispatch/spec.md`](specs/024-m6-0a-concurrent-dispatch/spec.md).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Validation checklist (operator-runnable)

After both PRs merge:

- [ ] `git log --oneline main | grep "M6.0a"` shows both PRs.
- [ ] `jq -r '.dispatch_mode' docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` returns `"concurrent"`.
- [ ] `pytest tools/benchmark/tests/test_m6_concurrent_dispatch.py -v` passes 18 parametrisations.
- [ ] `docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md` is byte-identical to its `b63947a` version (`git diff b63947a -- docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md` returns empty).
- [ ] M6.1.1 PR #27 has merged (M6.0a PR-1 was the only blocker).
- [ ] `docs/benchmarks/m6_0a-dispatch-correction.md` renders cleanly and all four cross-links resolve.

## Estimated wall-clock budget

| Phase | Wall-clock | Modal cost |
|---|---|---|
| PR-1 (harness fix + regression test) | ~1 h author + lint + PR | $0 |
| PR-2 (Modal re-run) | ~30–45 min on Modal A10G eu-west-1 (SC-002) | ≤ $1 (SC-006) |
| PR-2 (dispatch-correction note) | ~30 min author + cross-link verification | $0 |
| **Total** | **~2 h operator time + 30–45 min Modal** | **≤ $1** |
