# Quickstart: M6.1.3 — Phase 1 Attribution Closure

**Branch**: `026-m6-1-3-attribution-closure` | **Phase 1 output** | **Plan**: [plan.md](./plan.md)

This is the operator playbook for landing M6.1.3 and producing its three published artifacts under `docs/benchmarks/m6_1_3-attribution-closure*.{md,json}`. Follow the phases in order. Each phase has its own merge gate.

## Phase 0 — One-time setup (operator workstation)

### Verify M6.1.2 inheritance

M6.1.3 inherits M6.1.2's full convention set verbatim per FR-032 — 4-cohort matrix, `network_paths` topology probe, `cohort_set` / `cohort_omissions` metadata, timestamped progress lines. Verify M6.1.2 is on the branch:

```sh
git checkout 026-m6-1-3-attribution-closure
git log -1 --oneline                 # Should show the round-4 clarify commit a24d83f
ls -la docs/benchmarks/m6_1_2-methodology-discipline.json  # Should exist (M6.1.2 published artifact)
```

If M6.1.2 has NOT landed: M6.1.3 cannot proceed (per spec Assumptions). Land M6.1.2 first via its `/speckit-implement` cycle, then return here.

### Verify `tcptraceroute` (inherited from M6.1.2)

The M6.1.2 topology probe requires `tcptraceroute` on the operator's machine. Re-verify it's installed:

```sh
tcptraceroute --version  # Should print version info; no "command not found"
```

If absent, install per the M6.1.2 quickstart (`brew install tcptraceroute` on macOS with the one-time `chown root:wheel + chmod u+s` setuid fixup, or `apt install tcptraceroute` / `dnf install tcptraceroute` on Linux).

### Local environment

```sh
uv sync --frozen   # Inherits M6.1.1 + M6.1.2's pinned vllm + torch + grpcio versions
```

## Phase 1 — Implement the new modules (no Modal compute)

**Implementation methodology** (per [`plan.md`](./plan.md) "Implementation Methodology: Copy-Then-Refactor Pattern" + R-11): each new M6.1.3 module that has a prior-milestone analog starts as a **`cp` from that analog**, renamed appropriately, and then refactored to add M6.1.3's feature. Do NOT reimplement from scratch — prior-milestone fixes carry forward automatically when the implementation starts from the prior milestone's already-fixed state. The per-module copy-source + refactor-delta table in `plan.md` is the canonical reference; per-step commands below operationalize it.

Implementation order follows the data-model dependency graph (each module depends on earlier ones):

### Step 1 — Relocate the symmetric-prompts helper (FR-019 + round-2 Q4 + R-6)

```sh
# Verbatim relocation: move M5.2's symmetric-prompt logic to the new shared location.
cp tools/benchmark/src/vllm_grpc_bench/m5_2_symmetry.py \
   tools/benchmark/src/vllm_grpc_bench/symmetric_prompts.py
# Edit symmetric_prompts.py to update its module-level docstring (e.g., "M5.2-era
# cohort-prompt symmetry helper, relocated as a cross-milestone shared module
# per M6.1.3 FR-019.") — but do NOT change any function signatures or behavior.

# Convert m5_2_symmetry.py to a one-line re-export shim for M5.2 back-compat:
cat > tools/benchmark/src/vllm_grpc_bench/m5_2_symmetry.py <<'EOF'
"""Back-compat re-export shim: real implementation lives in symmetric_prompts.py
since M6.1.3 (per FR-019 + round-2 Q4 + R-6). Imports here for the M5.2
historical sweep (m5_2_sweep.py) continue working unchanged per FR-037."""

from .symmetric_prompts import *  # noqa: F401, F403
EOF
```

Run `uv run pytest tools/benchmark/tests/test_m5_2*.py` to confirm M5.2's historical tests still pass against the shim.

### Step 2 — Copy `m6_1_2_types.py` → `m6_1_3_types.py`, rename + extend

```sh
cp tools/benchmark/src/vllm_grpc_bench/m6_1_2_types.py \
   tools/benchmark/src/vllm_grpc_bench/m6_1_3_types.py
```

Refactor delta (per `plan.md` table + [`data-model.md`](./data-model.md)):
- Find-replace `M6_1_2` → `M6_1_3` for type identifiers that are M6.1.3-specific (e.g., `M6_1_2SweepArtifact` → `M6_1_3SweepArtifact`).
- Keep `M6_1_2_COHORTS` as an explicit import (not a rename) — the 4-cohort tuple is INHERITED per FR-032.
- Add the new dataclasses + literals per `data-model.md`: `M6_1_3SweepMode`, classifier label literals (`M6_1_3BaseLabel`, `M6_1_3OuterLabel`, `M6_1_3AbbreviatedIdentifier`, `M6_1_3CompoundLabel`, `M6_1_3PrimaryLabel`), `M6_1_3TimingCheckpointExtension`, `M6_1_3PerSegmentDeltaExtension`, `M6_1_3PerSegmentAggregateExtension`, `M6_1_3BetweenRunVariance` + cell type, `M6_1_3PerCohortAuditDistribution`, `M6_1_3PerCellAuditAggregate`, `M6_1_3PerRunAuditVerdict`, `M6_1_3PhaseBTriggerVerdict`, `M6_1_3SweepArtifact` (extends `M6_1_2SweepArtifact` with `between_run_variance: M6_1_3BetweenRunVariance | None`).

### Step 3 — Add the 4 wire keys to the frontend servicers (additive in-place edits, NOT copy-then-refactor)

These are in-place edits to existing handler functions, not new modules. Locate the existing M6.1.1 `pre_engine_ns` and `first_chunk_ns` capture sites; add the new captures alongside.

`packages/frontend/src/vllm_grpc_frontend/chat.py:CompleteStream` (FR-001 + FR-002 + FR-012 + FR-013):
- Add `m6_1_1_t_pre_engine_wall_ns = time.time_ns()` at the existing `pre_engine_ns` site.
- Add `m6_1_1_t_first_chunk_mono_ns = time.monotonic_ns()` at the existing `first_chunk_ns` site.
- Add `tokenized_prompt_length = len(token_ids)` and `tokenized_prompt_hash = hashlib.blake2b(b"".join(t.to_bytes(4, 'little') for t in token_ids), digest_size=8).hexdigest()` after `messages_to_prompt`.
- Append the 4 keys to the existing `context.set_trailing_metadata(...)` call.

`packages/frontend/src/vllm_grpc_frontend/completions.py:CompleteStream` (same 4-key emission as chat.py).

`packages/frontend/src/vllm_grpc_frontend/completions.py:Complete` (unary; FR-014 audit-only — FR-003 streaming-only for proxy-edge means no proxy-edge keys on unary):
- Add only the audit captures + the 2 audit keys in trailing metadata.

### Step 4 — Extend `m6_1_1_timing.py` (additive in-place edit, NOT copy-then-refactor)

In-place extension of the existing M6.1.1 extractor. Add 4 new `_opt_int` / `_opt_str` reads per FR-004:
- `pre_engine_wall_ns=_opt_int(trailing_metadata, "m6_1_1_t_pre_engine_wall_ns")`
- `first_chunk_mono_ns=_opt_int(trailing_metadata, "m6_1_1_t_first_chunk_mono_ns")`
- `tokenized_prompt_length=_opt_int(trailing_metadata, "m6_1_3_tokenized_prompt_length")`
- `tokenized_prompt_hash=_opt_str(trailing_metadata, "m6_1_3_tokenized_prompt_hash")`

The existing `TimingCheckpoint` dataclass gains 4 new optional fields per `M6_1_3TimingCheckpointExtension`.

### Step 5 — Extend `rest_shim.py` (additive in-place edit, NOT copy-then-refactor)

In-place extension of the REST SSE / JSON terminal-event handler. Read the same 4 keys from the terminal event object; populate the same 4 `TimingCheckpoint` optional fields.

### Step 6 — Copy `m6_1_1_classifier.py` → `m6_1_3_classifier.py`, extend

`m6_1_3_classifier.py` has **no M6.1.2 analog** (M6.1.2's FR-022 forbade classifier changes), so the copy source is `m6_1_1_classifier.py`.

```sh
cp tools/benchmark/src/vllm_grpc_bench/m6_1_1_classifier.py \
   tools/benchmark/src/vllm_grpc_bench/m6_1_3_classifier.py
```

Refactor delta (per `plan.md` table + [`contracts/classifier.md`](./contracts/classifier.md)):
- Rename the top-level entry function (e.g., `classify_m6_1_1` → `classify_m6_1_3`) — keep the inherited 5-bucket helper functions unchanged so the legacy fallback path stays identical to M6.1.1 per FR-008's "preserved unchanged" guarantee.
- Add the 7-bucket extension: `proxy_ingress_dominated` + `proxy_egress_dominated` checks against `seg_ingress_ms` / `seg_egress_ms` per FR-008.
- Add FR-008a's highest-share-wins / compound-label tie-breaking with the 5pp dominance margin; emit the alphabetically-sorted `multi_factor_<top>_<runner_up>` compound label per R-8.
- Add FR-026's `inconclusive_high_variance` outer override; consume `between_run_variance` argument from the caller (`m6_1_3_sweep.py` per Step 11).
- Add FR-008a row-4 dormancy enforcement (round-4 Q1): `frontend_arrival_jitter` MUST NOT fire as primary attribution in the 7-bucket tree; MUST NOT appear inside `multi_factor_*`.
- Add the legacy fallback: when `seg_ingress_ms` / `seg_egress_ms` are absent on the input (pre-M6.1.3 manifest rehydration), fall back to the inherited 5-bucket logic.

### Step 7 — Implement `m6_1_3_audit.py` (NET-NEW, no copy source)

No prior milestone has a per-cohort prompt-content audit module. Write from the contracts directly:
- Pooled audit aggregation per FR-016 + round-1 Q5 (pool per-RPC rows across `phase_1_runs[]`; `n_rpcs = N × n` per cohort).
- H1 / H2 / rejection criterion logic per FR-016.
- Per-run verdict + FR-016a + round-2 Q5 appendix-conditional rendering (byte-non-identical disagreement detection).
- FR-017 / FR-018 spec-decision recommendation extraction.

Algorithmic spec lives in [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) audit section + [`data-model.md`](./data-model.md) audit dataclasses. Reference these throughout implementation.

### Step 8 — Implement `m6_1_3_variance.py` (NET-NEW, no copy source)

No prior milestone has a between-run variance module. Write from the contracts directly:
- `compute_between_run_variance(phase_1_runs)` per FR-024 returns per-cell × cohort `(mean_of_means_ms, stddev_of_means_ms, n_runs)`.
- FR-027 cohort-unhealthy handling: drop run contributions per cohort × cell on per-run failure; emit `cohort_unhealthy` warning at 3+ failed runs.
- FR-043 + round-2 Q3 unified high-variance threshold check (between-run stddev ÷ within-run CI half-width).
- `compute_phase_b_trigger(...)` derives the FR-044 verdict line mechanically from the cell-label list (cells carrying `inconclusive_high_variance`).

Algorithmic spec in [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) variance section + [`contracts/classifier.md`](./contracts/classifier.md) outer-override section.

### Step 9 — Copy `m6_1_2_reporter.py` → `m6_1_3_reporter.py`, rename + extend

```sh
cp tools/benchmark/src/vllm_grpc_bench/m6_1_2_reporter.py \
   tools/benchmark/src/vllm_grpc_bench/m6_1_3_reporter.py
```

Refactor delta (per `plan.md` table + [`contracts/artifact-schema.md`](./contracts/artifact-schema.md)):
- Rename `m6_1_2*` references to `m6_1_3*` (functions + types).
- Keep the M6.1.2-inherited rendering of `cohort_set` / `cohort_omissions` / `network_paths` blocks.
- Add `seg_ingress` + `seg_egress` per-cell timing-table columns per FR-009.
- Add classification narratives for the 2 new `proxy_*_dominated` base labels per FR-009.
- Add compound-label narrative with abbreviated identifiers + per-segment shares per FR-009 + round-2 Q2.
- Add one-line identifier legend at start of classifier-narratives section per FR-009a + round-2 Q2.
- Add "Per-Cohort Prompt-Content Audit" section + H1 verdict line per FR-016.
- Add conditional per-run audit appendix per FR-016a + round-2 Q5.
- Add spec-decision recommendation block per FR-017 / FR-018.
- Add "Between-Run Variance" section conditional on `len(phase_1_runs) >= 3` per FR-025.
- Add Phase B trigger verdict line at end of variance section with FR-044 override fallback.
- Add three-path output routing per FR-038 + round-2 Q1 + R-7.

### Step 10 — Copy `m6_1_2_sweep.py` → `m6_1_3_sweep.py`, rename + extend

```sh
cp tools/benchmark/src/vllm_grpc_bench/m6_1_2_sweep.py \
   tools/benchmark/src/vllm_grpc_bench/m6_1_3_sweep.py
```

Refactor delta (per `plan.md` table + [`data-model.md`](./data-model.md) orchestration semantics):
- Rename `M6_1_2*` references to `M6_1_3*` for M6.1.3-specific types.
- Keep the topology-probe call (probe-once-per-sweep per FR-030 — inherited from M6.1.2 verbatim).
- **Import** `cohorts_at_concurrency()` from `m6_1_2_sweep.py` rather than duplicating the function (4-cohort iteration + tuned-pair-collapse-at-c=1 rule preserved per FR-032).
- Add the multi-run loop per FR-022 (`config.repeat` from `--m6_1_3-diagnose-repeat`, default 5 under `--m6_1_3`, 1 under `--m6_1_3-validate`).
- Add the preemption-aware URL refresh per FR-028 (port the M5.2 pattern from `m5_2_sweep.py` per R-5; pinned > 2 abort threshold per round-3 Q3).
- Add post-loop calls: `m6_1_3_audit.compute_pooled_verdict(phase_1_runs)`, `m6_1_3_variance.compute_between_run_variance(phase_1_runs)`, classifier invocation with `between_run_variance` argument.
- Modify the orchestrator's return type to `M6_1_3SweepArtifact`.

### Step 11 — Copy `m6_1_2_validate.py` → `m6_1_3_validate.py`, rename + extend

```sh
cp tools/benchmark/src/vllm_grpc_bench/m6_1_2_validate.py \
   tools/benchmark/src/vllm_grpc_bench/m6_1_3_validate.py
```

Refactor delta (per `plan.md` table + R-7):
- Rename `run_m6_1_2` → `run_m6_1_3`; keep the single-entry-function-for-both-modes pattern from round-2 Q2.
- Modify the output-path inference logic per R-7: validate sibling under `--m6_1_3-validate`; canonical publish under default `--m6_1_3`; Phase B sibling under `--m6_1_3 --m6_1_3-diagnose-repeat=1 --m6_1_3-diagnose-n=200`.
- Record `sweep_mode` in `run_meta.sweep_mode` artifact metadata.

### Step 12 — Extend `__main__.py` (additive in-place edit, NOT copy-then-refactor)

In-place addition of the M6.1.3 argparse wiring. Locate the existing M6.1.2 argparse block (`--m6_1_2` + `--m6_1_2-validate` + sub-flags); add the parallel M6.1.3 block alongside. Add the 3 modifier flags (`--m6_1_3-diagnose-repeat`, `--m6_1_3-diagnose-n`, `--m6_1_3-symmetric-prompts`) and the 11 namespaced sub-flags per [`contracts/cli.md`](./contracts/cli.md). Add mutual-exclusion list per FR-034. Wire both `--m6_1_3` and `--m6_1_3-validate` to `run_m6_1_3(args, sweep_mode=...)`.

### Step 13 — Extend `contracts/instrumentation.md` (additive in-place edit)

In-place addition to the existing instrumentation contract. Add the 7 new sections per FR-011 + SC-010:
1. 4 new wire keys (2 `m6_1_1_*` proxy-edge + 2 `m6_1_3_*` audit).
2. 2 new derived segments (`seg_ingress_ms`, `seg_egress_ms`).
3. 7-bucket classifier + canonical 6-row mapping table.
4. Compound-label vocabulary (`multi_factor_*`) + 5pp dominance margin.
5. `inconclusive_high_variance` outer override + unified high-variance threshold.
6. `between_run_variance` top-level block.
7. `frontend_arrival_jitter` dormancy note.
8. Additive-strict-superset versioning convention (round-3 Q1).

### Step 14 — Write the new unit + integration tests

Each test file under `tools/benchmark/tests/` is **net-new** (no test-file copy source — the surfaces being tested are M6.1.3-specific):
- `test_m6_1_3_classifier.py`
- `test_m6_1_3_audit.py`
- `test_m6_1_3_variance.py`
- `test_m6_1_3_proxy_edge_probes.py`
- `test_m6_1_3_cli.py`
- `test_m6_1_3_symmetric_prompts.py`
- `test_m6_1_3_artifact_schema.py`

Except for the validate integration test, which IS a copy-then-refactor:

```sh
cp tools/benchmark/tests/test_m6_1_2_smoke_validate_cli.py \
   tools/benchmark/tests/test_m6_1_3_validate_cli.py
```

Refactor delta: rename M6.1.2 fixtures + assertions to M6.1.3; switch the mode flag from `--m6_1_2-validate` to `--m6_1_3-validate`; add assertions for the validate-sibling output path, the new per-cell `seg_ingress_ms` / `seg_egress_ms` columns, the audit reporter section, the 7-bucket classifier output. Keep the stub-driver pattern + the `--m6_1_3-skip-deploy` invocation shape.

`test_m6_1_3_publish_multirun_cli.py` is net-new (M6.1.2 had only the validate integration test; the multi-run scenario is M6.1.3-specific). Implement against the contracts directly.

### Local lint chain (mandatory pre-push gate)

Per [`feedback_local_lint_chain`](../../.claude/projects/-Users-bsansom-projects-vllm-grpc/memory/feedback_local_lint_chain.md) memory + Constitution Principle IV: CI runs four separate gates. Run all four locally before pushing:

```sh
uv run ruff check tools/benchmark/ packages/frontend/
uv run ruff format --check tools/benchmark/ packages/frontend/
uv run mypy --strict tools/benchmark/src/vllm_grpc_bench/m6_1_3_*.py \
                     tools/benchmark/src/vllm_grpc_bench/symmetric_prompts.py \
                     tools/benchmark/src/vllm_grpc_bench/m5_2_symmetry.py \
                     packages/frontend/src/vllm_grpc_frontend/chat.py \
                     packages/frontend/src/vllm_grpc_frontend/completions.py
uv run pytest tools/benchmark/tests/test_m6_1_3_*.py
```

All four MUST pass before push. The Constitution Principle IV prohibition on `--no-verify` applies.

### Unit + integration test the new modules

Each new test file under `tools/benchmark/tests/` (per [`plan.md`](./plan.md) Testing section):

```sh
# Unit tests
uv run pytest tools/benchmark/tests/test_m6_1_3_classifier.py            # 7-bucket + compound + outer override
uv run pytest tools/benchmark/tests/test_m6_1_3_audit.py                 # pooled verdict + appendix conditional
uv run pytest tools/benchmark/tests/test_m6_1_3_variance.py              # variance compute + Phase B trigger
uv run pytest tools/benchmark/tests/test_m6_1_3_proxy_edge_probes.py     # wire round-trip + negative-value assertion
uv run pytest tools/benchmark/tests/test_m6_1_3_cli.py                   # argparse + defaults + mutual exclusion
uv run pytest tools/benchmark/tests/test_m6_1_3_symmetric_prompts.py     # shared helper + M5.2 back-compat
uv run pytest tools/benchmark/tests/test_m6_1_3_artifact_schema.py       # three-path scheme + 5-segment sum

# Integration tests (no Modal compute)
uv run pytest tools/benchmark/tests/test_m6_1_3_validate_cli.py          # --m6_1_3-validate end-to-end against stub driver
uv run pytest tools/benchmark/tests/test_m6_1_3_publish_multirun_cli.py  # --m6_1_3 --m6_1_3-diagnose-repeat=3 end-to-end (uses repeat=3 for test speed)
```

### Pre-flight verification of M5.2 back-compat

The shared `symmetric_prompts.py` helper must NOT break M5.2's historical re-runnability per FR-037:

```sh
# Re-run M5.2's historical sweep against the latest code (no Modal compute via --m5_2-skip-deploy stub):
uv run python -m vllm_grpc_bench --m5_2 --m5_2-skip-deploy=stub --m5_2-base-seed=42 \
    | head -10
# Should NOT raise "ImportError: cannot import name from m5_2_symmetry" or similar.
# Output should match the pre-M6.1.3 baseline (compare against git stash of the M5.2 output before this branch).
```

## Phase 2 — Run the validation sweep (CI gate for the M6.1.3 PR)

Per FR-039 + SC-001 + SC-008 + SC-013. The validate sweep is the M6.1.3 PR-merge wiring gate.

### Pre-flight checks

```sh
# Confirm tcptraceroute reachable (inherited M6.1.2 dependency):
tcptraceroute --version

# Confirm M6.1.1 baseline exists (--m6_1_3-m6-1-1-baseline default points here):
ls -la docs/benchmarks/m6_1_1-engine-cost-instrumentation.json

# Confirm M6.1.2 baseline exists (inheritance per FR-032):
ls -la docs/benchmarks/m6_1_2-methodology-discipline.json

# Confirm Modal token env var:
echo "${MODAL_BENCH_TOKEN:-<unset>}"

# Confirm the M6.1.3 CLI surface parses:
uv run python -m vllm_grpc_bench --m6_1_3-validate --help | head -30
```

### Run the validation sweep

```sh
uv run python -m vllm_grpc_bench --m6_1_3-validate \
    --m6_1_3-modal-region=eu-west-1 \
    --m6_1_3-base-seed=42 \
    --m6_1_3-model="Qwen/Qwen3-8B"
```

The three explicit `--m6_1_3-*` arguments match the defaults verbatim (per FR-036) — shown explicitly so the operator can spot-check the verbatim-inheritance contract is being respected. Omitting them is equivalent.

Expected sweep behavior:
- ~15 min wall-clock on Modal A10G `eu-west-1` (single run at `repeat=1` + `n=50`).
- Probe completes in ~5-30s at sweep start (inherited M6.1.2 behavior; parallel-across-cohorts, 30s per-cohort timeout).
- Loud stderr warnings if FR-005a (all-probes-fail) or FR-006 (cohort-CSP-mismatch) fires (inherited M6.1.2 behavior).
- New: FR-006 clock-anomaly negative-value assertion may fire on a small fraction of RPCs under healthy conditions; assertion logs the offending `_ns` values for diagnosis. SC-013's 0.5% RPC budget applies.
- Total Modal compute: ~$0.29.

### Inspect the validate-sibling artifact

```sh
# Verify the new top-level keys are present:
jq 'keys' docs/benchmarks/m6_1_3-attribution-closure-validate.json
# Should include (at minimum): schema_version, dispatch_mode, run_meta, phase_1_classifications,
# phase_1_runs (1 entry for validate), multi_point_timings, network_paths, cohort_set,
# cohort_omissions, between_run_variance (null for validate — repeat=1 < 3).

# Verify the canonical 5-segment sum invariant (SC-002 + round-4 Q1):
jq '.multi_point_timings.chat_stream_c1 | to_entries | map({
  cohort: .key,
  engine_ttft_ms: .value.engine_ttft_ms.mean,
  seg_sum: (.value.seg_ab_ms.mean + .value.seg_queue_ms.mean + .value.seg_prefill_ms.mean
            + .value.seg_ingress_ms.mean + .value.seg_egress_ms.mean),
  delta_ms: ((.value.seg_ab_ms.mean + .value.seg_queue_ms.mean + .value.seg_prefill_ms.mean
              + .value.seg_ingress_ms.mean + .value.seg_egress_ms.mean) - .value.engine_ttft_ms.mean)
})' docs/benchmarks/m6_1_3-attribution-closure-validate.json
# Expected: delta_ms within ±1 ms per SC-002.

# Verify clock-anomaly rate (SC-013 dual-gate):
jq '.multi_point_timings | to_entries | map({
  cell: .key,
  worst_cohort_clock_anomaly_fraction: (.value | to_entries | map(.value.audit.clock_anomaly_fraction) | max)
})' docs/benchmarks/m6_1_3-attribution-closure-validate.json
# Expected: worst_cohort_clock_anomaly_fraction < 0.005 (0.5%) per SC-013.

# Verify the 7-bucket classifier is exercised (no `inconclusive_high_variance` on validate — multi-run-only per FR-026):
jq '.phase_1_classifications' docs/benchmarks/m6_1_3-attribution-closure-validate.json
# Expected labels: any of the 7 base + multi_factor_* compounds.
# NOT expected: inconclusive_high_variance (validate has repeat=1; outer override needs >=3 runs).
```

If the validate sweep passes all the above checks, proceed to Phase 3. If any check fails — particularly the SC-013 dual-gate — the M6.1.3 PR is held until the cause is diagnosed (do NOT proceed to the ~75 min publish run).

## Phase 3 — Run the publishing sweep

Per FR-039 + SC-001 + SC-006 + SC-009 + SC-013. This is the M6.1.3 milestone-publishing run.

### Run the publish sweep

```sh
uv run python -m vllm_grpc_bench --m6_1_3 \
    --m6_1_3-modal-region=eu-west-1 \
    --m6_1_3-base-seed=42 \
    --m6_1_3-model="Qwen/Qwen3-8B"
```

Expected sweep behavior:
- ~75 min wall-clock on Modal A10G `eu-west-1` (5 runs × ~15 min per single-sweep run).
- Topology probe runs ONCE at first run's start per FR-030; subsequent runs reuse the captured `network_paths` block.
- Preemption-aware URL refresh per FR-028 — if Modal preempts the function mid-sequence, the orchestrator detects, refreshes URLs (porting the M5.2 pattern), and continues. Aborts after > 2 preemptions per round-3 Q3 pinned threshold.
- Total Modal compute: ~$1.45 (5 × ~$0.29).

### Inspect the canonical publish artifact

```sh
# Verify phase_1_runs[] accumulates 5 entries (SC-006):
jq '.phase_1_runs | length' docs/benchmarks/m6_1_3-attribution-closure.json
# Expected: 5

# Verify between_run_variance block is populated (SC-006):
jq '.between_run_variance.chat_stream_c4' docs/benchmarks/m6_1_3-attribution-closure.json
# Expected: per-cohort {mean_of_means_ms, stddev_of_means_ms, n_runs} entries

# Verify Phase B trigger verdict appears in the published markdown (FR-044):
grep -A 5 "Phase B trigger verdict" docs/benchmarks/m6_1_3-attribution-closure.md
# Expected: either "Phase B required: <cells>" or "Phase B not required"

# Verify M6.1.1's two inconclusive cells re-classify (SC-003):
jq '.phase_1_classifications.chat_stream_c4 // .phase_1_classifications.chat_stream_c8' \
    docs/benchmarks/m6_1_3-attribution-closure.json
# Expected: one of the 7 base labels, a multi_factor_* compound, or `inconclusive_high_variance (...)`.

# Verify SC-013 dual-gate on the canonical artifact:
jq '.multi_point_timings | to_entries | map({
  cell: .key,
  worst_cohort_clock_anomaly_fraction: (.value | to_entries | map(.value.audit.clock_anomaly_fraction) | max)
})' docs/benchmarks/m6_1_3-attribution-closure.json
# Expected: worst_cohort_clock_anomaly_fraction < 0.005 per SC-013.

# Verify the audit verdict at chat_stream_c1 + the spec-decision recommendation (FR-016 / FR-017 / FR-018):
grep -A 10 "Recommendation" docs/benchmarks/m6_1_3-attribution-closure.md | head -15
# Expected: either symmetric-prompts recommendation (FR-017) or Phase C follow-up (FR-018) or H2 encoding-drift note.
```

## Phase 4 — Conditional Phase B run

Per FR-043 + round-3 Q3 unified threshold. Phase B is required ONLY if Phase A's publish-run reporter emitted `"Phase B required: <cells>"`. If the publish run emitted `"Phase B not required"`, skip Phase 4 entirely.

### When required

```sh
uv run python -m vllm_grpc_bench --m6_1_3 \
    --m6_1_3-diagnose-repeat=1 --m6_1_3-diagnose-n=200 \
    --m6_1_3-modal-region=eu-west-1 \
    --m6_1_3-base-seed=42 \
    --m6_1_3-model="Qwen/Qwen3-8B"
```

Expected:
- ~60 min single-run sweep at n=200 (4× the M6.1.1 baseline).
- Writes to `docs/benchmarks/m6_1_3-attribution-closure-phase-b.{md,json}` per FR-045 + R-7 (path inferred from modifier combination).
- Reporter renders "Phase B: n=200 Power Test" comparison section with per-cell CI half-widths at n=200 vs n=50.
- Cells whose CI half-width does NOT shrink by ~`sqrt(4) = 2×` are called out per FR-045 (evidence V2/V3/V4 variance dominates sample-size scaling).
- Total Modal compute: ~$1.16.

### Inspect the Phase B sibling artifact

```sh
# Verify the CI half-width comparison block:
jq '.phase_b_ci_comparison' docs/benchmarks/m6_1_3-attribution-closure-phase-b.json

# Verify cross-reference to Phase A artifact:
grep -n "m6_1_3-attribution-closure.md" docs/benchmarks/m6_1_3-attribution-closure-phase-b.md
# Expected: "Comparison against the canonical [Phase A artifact](m6_1_3-attribution-closure.md)."
```

## Phase 5 — Land the M6.1.1 forward-pointing annotation

Per FR-031 + round-3 Q2. Single leading note line at the top of M6.1.1's published markdown body:

```sh
# Edit docs/benchmarks/m6_1_1-engine-cost-instrumentation.md and add this EXACT line above the existing H1 title:
> **Note**: This milestone's c=4 / c=8 verdicts were updated by [M6.1.3](m6_1_3-attribution-closure.md). See that artifact for attributed labels and Phase B variance characterization.

# Verify the line lands above the H1:
head -3 docs/benchmarks/m6_1_1-engine-cost-instrumentation.md
# Expected: the > Note line, then the existing H1 (# M6.1.1 — ...)
```

No other modification to M6.1.1's body is permitted per FR-031.

## Phase 6 — Update `contracts/instrumentation.md`

Per FR-011 + SC-010. Extend the existing instrumentation contract with the M6.1.3 additions:

1. 4 new wire keys (2 `m6_1_1_*` proxy-edge + 2 `m6_1_3_*` audit) per [`contracts/wire-vocabulary.md`](./contracts/wire-vocabulary.md).
2. 2 new derived segments (`seg_ingress_ms`, `seg_egress_ms`) per FR-005.
3. 7-bucket classifier + canonical mapping table per [`contracts/classifier.md`](./contracts/classifier.md).
4. Compound-label vocabulary (`multi_factor_*`) + 5pp dominance margin per FR-008a.
5. `inconclusive_high_variance` outer override + unified high-variance threshold per FR-026 + round-2 Q3.
6. `between_run_variance` top-level block per FR-024.
7. `frontend_arrival_jitter` dormancy note per round-4 Q1.
8. Additive-strict-superset versioning convention per round-3 Q1.

SC-007: a reader unfamiliar with M6.x can determine the per-cell label, the c=1 root-cause finding, the c=4 between-run variance fraction, and the audit recommendation in under 5 min from `docs/benchmarks/m6_1_3-attribution-closure.md` + the updated `contracts/instrumentation.md`.

## Phase 7 — Land the PR

### Pre-PR checks

```sh
# Final lint chain (all four gates):
uv run ruff check tools/benchmark/ packages/frontend/
uv run ruff format --check tools/benchmark/ packages/frontend/
uv run mypy --strict tools/benchmark/src/vllm_grpc_bench/m6_1_3_*.py \
                     tools/benchmark/src/vllm_grpc_bench/symmetric_prompts.py \
                     packages/frontend/src/vllm_grpc_frontend/
uv run pytest tools/benchmark/tests/

# Verify all three M6.1.3 artifacts exist + parse (Phase B may be absent if FR-043 trigger didn't fire):
jq -e '.schema_version' docs/benchmarks/m6_1_3-attribution-closure.json
jq -e '.schema_version' docs/benchmarks/m6_1_3-attribution-closure-validate.json
[ -f docs/benchmarks/m6_1_3-attribution-closure-phase-b.json ] && \
    jq -e '.schema_version' docs/benchmarks/m6_1_3-attribution-closure-phase-b.json

# Verify M6.1.1's leading note line landed:
grep -q "updated by \[M6.1.3\]" docs/benchmarks/m6_1_1-engine-cost-instrumentation.md
echo "M6.1.1 leading note: $?"  # Should print 0

# Verify contracts/instrumentation.md was updated:
grep -q "between_run_variance\|inconclusive_high_variance\|proxy_ingress_dominated" contracts/instrumentation.md
echo "contracts/instrumentation.md updated: $?"  # Should print 0
```

### Open the PR

Per [`feedback_pr_creation_deferred`](../../.claude/projects/-Users-bsansom-projects-vllm-grpc/memory/feedback_pr_creation_deferred.md) memory: PR creation is a separate gate from push. **Confirm with the user before `gh pr create`.**

PR description should reference:
- Spec: `specs/026-m6-1-3-attribution-closure/spec.md` (18 Q/A clarifications across 4 rounds)
- Plan: `specs/026-m6-1-3-attribution-closure/plan.md`
- Published artifacts: `docs/benchmarks/m6_1_3-attribution-closure.{md,json}` + validate sibling + (if produced) Phase B sibling
- PLAN.md M6.1.3 section: `docs/PLAN.md` §259-307
- M6.1.1 + M6.1.2 baselines consumed: `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` + `docs/benchmarks/m6_1_2-methodology-discipline.json`

## Troubleshooting

### Negative-value assertion (FR-006) fires above 0.5% RPC budget (SC-013)

The clock-anomaly fraction exceeded SC-013's 0.5% budget on either the validate-sibling or canonical-publish artifact (dual-gate per round-3 Q5). The PR is held until the cause is diagnosed. Likely causes:
- **Platform clock-source drift**: a future vLLM version changed `arrival_time` or `first_token_ts` clock source. Investigate by reading `vllm/v1/engine/__init__.py` and `vllm/v1/metrics/stats.py`; if the source has changed, M6.1.3's instrumentation needs an upstream-aware shim (out of scope for this milestone; file a follow-up).
- **In-process clock skew**: extremely unlikely on a single Python process; if it happens, capture the offending RPC's raw `_ns` values from the FR-006 stderr log and report.

### Multi-run loop hits Modal preemption

Per FR-028 + round-3 Q3 pinned threshold: the orchestrator allows one transient recovery (URL refresh + continue) but aborts after > 2 preemptions in a single multi-run sequence. If the sweep aborts incomplete, the published artifact's `phase_1_runs[]` contains the runs that completed (≥ 3 for variance compute, < 5 for the full Phase A); the variance table carries the `n_runs_actual < n_runs_requested` annotation; the reporter renders a "multi-run incomplete" warning.

Re-run the publish sweep when Modal is healthier (typically within a few hours for deploy-rollover-related preemption patterns).

### Phase B trigger verdict says "trigger verdict unavailable"

The operator ran `--m6_1_3 --m6_1_3-diagnose-repeat=N` for some `N < 3`. The FR-025 variance section is suppressed (requires `≥ 3` runs for variance compute), so FR-044 cannot derive the trigger verdict. The reporter emits the override fallback message per FR-044.

Re-run with the default `repeat=5` (or at least `repeat=3`) to get a valid Phase B trigger verdict.

### `inconclusive_high_variance` fires on a cell that previously classified cleanly under M6.1.1

This is a legitimate finding per round-2 Q3 + FR-026 — the M6.1.1 single-run interpretation was within-run-noise honest, but the M6.1.3 multi-run characterization revealed between-run variance that dominates attribution. The reporter renders both the outer override AND the inner attribution as a parenthetical; the published markdown documents the situation per the classifier-narratives section. Recommend Phase C (multi-deploy) or Phase D (multi-seed) as the next investigation step if the cell's headline verdict matters for downstream operator decisions.

### Compound label fires (`multi_factor_*`) — is this a methodology problem?

No. Compound labels per FR-008a + round-1 Q4 are first-class members of the cell-label space; they faithfully report the near-tie situation where two segments contribute within the 5pp dominance margin. The reporter narrative cites the specific shares so the reader can judge — this is honest measurement (Constitution Principle V). If a compound label appears on chat_stream_c4 / chat_stream_c8 in the M6.1.3 publish run, that IS the attribution; M6.1.1's `inconclusive` is more honestly "split between two factors" than "unknown".

### Shared `symmetric_prompts.py` helper breaks M5.2's historical re-run (FR-019 back-compat regression)

Per R-6, the re-export shim at `m5_2_symmetry.py` should make M5.2's `from .m5_2_symmetry import ...` continue working without code changes. If M5.2's sweep raises `ImportError`, the shim's wildcard re-export missed a symbol — add the symbol explicitly to the shim or to `symmetric_prompts.py`'s `__all__` export list.

### M5.2 + M6.1.3 produce different symmetric-prompt outputs

A regression in the shared helper. Both invocations should produce identical per-cohort prompt assignments for the same iteration index per FR-019 + R-6. Re-run `test_m6_1_3_symmetric_prompts.py::test_m5_2_back_compat` to identify which input → output pair diverged.

### `--m6_1_3-modal-region` / `--m6_1_3-base-seed` / `--m6_1_3-model` default doesn't match M6.1.2's

A drift regression — fail the CI test in `test_m6_1_3_cli.py::test_m6_1_3_inheritable_defaults_match_m6_1_2`. Fix the M6.1.3 default to match M6.1.2's verbatim (which matches M6.1.1's). Round-2 carry-over + round-3 Q2 + FR-036 explicitly guard against this.

### M6.1.1's or M6.1.2's historical re-run produces different output after M6.1.3 lands

Serious regression — per FR-037, M6.1.1's `--m6_1_1-diagnose` and M6.1.2's `--m6_1_2` / `--m6_1_2-validate` semantics MUST stay frozen. Investigate: did any of the modifications to `m6_1_1_timing.py` (the extractor extension) accidentally change extraction logic for the existing fields? Did the `symmetric_prompts.py` helper relocation break M5.2's behavior despite the re-export shim? The extractor extension should ONLY add new optional fields; the existing field-extraction paths are unchanged.

## Cross-references

- Plan: [`plan.md`](./plan.md)
- Data model: [`data-model.md`](./data-model.md)
- CLI contract: [`contracts/cli.md`](./contracts/cli.md)
- Wire-vocabulary contract: [`contracts/wire-vocabulary.md`](./contracts/wire-vocabulary.md)
- Classifier contract: [`contracts/classifier.md`](./contracts/classifier.md)
- Artifact-schema contract: [`contracts/artifact-schema.md`](./contracts/artifact-schema.md)
- Spec: [`spec.md`](./spec.md)
- Research: [`research.md`](./research.md)
- PLAN.md M6.1.3 section: `docs/PLAN.md` §259-307
- M6.1.2 quickstart precedent: `specs/025-m6-1-2-methodology-discipline/quickstart.md`
- M6.1.1 quickstart precedent: `specs/023-m6-1-1-engine-cost-instrumentation/quickstart.md`
