# M6.1.1 — Operator Quickstart

**Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md) | **Data model**: [data-model.md](./data-model.md) | **Contracts**: [cli](./contracts/cli.md) · [instrumentation](./contracts/instrumentation.md) · [output](./contracts/output.md)

Step-by-step playbook for running M6.1.1 end-to-end. The flow has two stages — Phase 1 diagnose, then Phase 2 (one of four paths). Most invocations exit in 30–75 minutes; the worst case (two Phase 1 runs + Phase 2(a) verification) is ~3 hours total and ≈ $5 Modal compute.

---

## Prerequisites

1. **Branch**: `023-m6-1-1-engine-cost-instrumentation` checked out.
2. **M6.1 baseline JSON present**: `docs/benchmarks/m6_1-real-prompt-embeds.json` exists and is readable. (This is the hard precondition input — FR-001.)
3. **torch pin**: `pip show torch | grep Version` returns `2.11.0`. If not, `pip install torch==2.11.0` in your project venv. (FR-003 — the harness will exit code 2 at startup otherwise.)
4. **Modal auth**: `modal token new` configured; `export MODAL_BENCH_TOKEN="<token>"`. (FR-026.)
5. **Local lint chain clean** (per `feedback_local_lint_chain` memory): `ruff check`, `ruff format --check`, `mypy --strict`, `pytest` all green on the current branch before any push.

---

## Stage 1 — Phase 1 diagnostic mini-sweep

```bash
python -m vllm_grpc_bench --m6_1_1-diagnose --m6_1_1-modal-region=eu-west-1
```

Wall-clock: ~30 minutes (cold-start Modal app deploy ~3 min + 900 measurement RPCs + 180 warmup + reporter). Cost: <$1.

**Possible outcomes**:

| Exit code | Meaning | Action |
| :-- | :-- | :-- |
| `0` | Uniform classification on all 3 chat_stream cells; ready for Phase 2 | Proceed to Stage 2 |
| `1` | Missing baseline / engine version mismatch / etc. | Read stderr; either fix the precondition or pass `--m6_1_1-allow-engine-mismatch` |
| `2` | torch pin mismatch | `pip install torch==2.11.0` and re-run |
| `3` | Mixed / inconclusive / drift_not_reproduced single-run | Re-run `--m6_1_1-diagnose` (Stage 1a) |
| `4` | Perturbation budget exceeded (> 500 µs / RPC) | Review the four-checkpoint code; reduce overhead; re-run |

### Stage 1a — re-run Phase 1 (only if Stage 1 returned exit code 3)

```bash
python -m vllm_grpc_bench --m6_1_1-diagnose --m6_1_1-modal-region=eu-west-1
```

The harness reads the existing `m6_1_1-engine-cost-instrumentation.json`, appends a new `phase_1_runs[]` entry per round-3 Q1, and re-evaluates the classification logic. After this second run:

| Run 2 outcome | Exit code | Phase 2 path |
| :-- | :-- | :-- |
| Uniform classification across all 3 cells | `0` | Proceed to Stage 2 |
| Uniform `drift_not_reproduced` after both runs | `0` | `phase_2_path = "drift_not_reproduced_confirmed"`; M6.1.1 closes — skip to Stage 3 |
| Still divergent / still inconclusive | `5` | `phase_2_path = "split_required"`; M6.1.1 cannot close — open successor sub-milestones M6.1.1a / M6.1.1b |

---

## Stage 2 — Phase 2 (branches on classification)

Open `docs/benchmarks/m6_1_1-engine-cost-instrumentation.md` and read § "Phase 1 classifications" in the Executive Summary.

### Stage 2a — Phase 1 returned uniform `instrumentation_artifact`

This means the engine_ttft_ms spread is concentrated in `seg_ab` (pre-engine bracket asymmetry between REST and gRPC). The fix is a code change to symmetrise the bracketing — see [contracts/instrumentation.md § "Phase 2(a) symmetrisation shape"](./contracts/instrumentation.md) for the three options.

1. **Apply the symmetrisation**: edit `scripts/python/modal_bench_rest_grpc_server.py` (and possibly `packages/frontend/src/vllm_grpc_frontend/completions.py`) per the multi-point table's evidence. Commit on the M6.1.1 branch.
2. **Verify with Phase 2(a) sweep**:
   ```bash
   python -m vllm_grpc_bench --m6_1_1 --m6_1_1-modal-region=eu-west-1
   ```
   Wall-clock: ~75 minutes. Cost: ~$1.50.

3. **Read the verification report**: `docs/benchmarks/m6_1_1-engine-cost-instrumentation.md` now shows `phase_2_path = "phase_2a_verified"` (if SC-003 satisfied) with the fresh `chat_stream_baseline_post_symmetrisation` + `embed_baseline_post_symmetrisation` sections populated.

4. **Embed regression check** (FR-015b): inspect the executive summary's "Embed regression check" line. If `n_warnings > 0`:
   - **Preferred**: identify and revert the perturbing change; re-run Phase 2(a).
   - **Acknowledge**: edit the M6.1.1 JSON's `phase_2_choice` (or pass an acknowledgement flag in a future revision) to set `embed_regression_acknowledged = True` with a one-sentence justification; commit.

5. **Methodology supersedence annotations** (FR-023 / FR-024): the harness automatically writes the additive annotations to `m6_1-real-prompt-embeds.{md,json}`. Verify with `git diff docs/benchmarks/m6_1-real-prompt-embeds.{md,json}`.

### Stage 2b — Phase 1 returned uniform `channel_dependent_batching`

This means the engine_ttft_ms spread is concentrated in `seg_bc` (the engine itself is seeing different first-token latencies per cohort — a real continuous-batching effect). The fix is doc-only: publish the finding in `contracts/instrumentation.md` with an operator-facing interpretation rule.

1. **Edit `contracts/instrumentation.md`** (the project-level file, NOT the spec-feature one):
   ```markdown
   ## M6.1.1: Channel-Dependent Batching Effect

   vLLM's continuous batching exhibits channel-dependent first-token latency...
   (see contracts/instrumentation.md template in spec-feature contracts/instrumentation.md for the
   expected section content)
   ```
   The heading MUST start with the literal `## M6.1.1: ` prefix — the validator in `m6_1_1_contracts_check.py` matches on regex `^## M6\.1\.1: `.

2. **Run `--m6_1_1`** to validate and finalize:
   ```bash
   python -m vllm_grpc_bench --m6_1_1
   ```
   Wall-clock: <1 minute (no Modal sweep). The harness reads the contracts file, validates the heading is present, flips `phase_2_path = "phase_2b_documented"`, writes the supersedence annotations to M6.1's files.

3. **Verify outputs**:
   - `docs/benchmarks/m6_1_1-engine-cost-instrumentation.md` § "Phase 2 Outcome" links to the contracts heading.
   - `docs/benchmarks/m6_1-real-prompt-embeds.{md,json}` carry the methodology_supersedence annotation.

### Stage 2c — Phase 1 returned `drift_not_reproduced_confirmed` (after two runs)

The harness has already written the report. No further action needed:
- `phase_2_path = "drift_not_reproduced_confirmed"`.
- M6.1's `engine_cost_drift_warning` flag is preserved as published.
- `methodology_supersedence` annotation records the non-reproduction.

Verify the report and proceed to Stage 3.

### Stage 2d — Phase 1 returned `split_required`

M6.1.1 cannot close as a single milestone. Open successor sub-milestones following the proposed split shape recorded in `phase_2_choice`:
- Typical split: M6.1.1a (cells classified `instrumentation_artifact` → fix path) + M6.1.1b (cells classified `channel_dependent_batching` → doc path).
- Alternate split: M6.1.1a (segment-level cells) + M6.1.1c (re-run Phase 1 with expanded checkpoints to resolve inconclusive).

Each successor sub-milestone goes through its own `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement` cycle. M6.2 cannot proceed until at least one successor publishes (SC-008 anchor = `not_applicable`).

---

## Stage 3 — Commit and ship

1. **Local lint chain** (per `feedback_local_lint_chain` memory):
   ```bash
   cd tools/benchmark
   uv run ruff check
   uv run ruff format --check
   uv run mypy --strict src
   uv run pytest
   ```
   All four MUST pass.

2. **Inspect git diff**: expect changes to
   - `tools/benchmark/src/vllm_grpc_bench/m6_1_1_*.py` (10 new modules per plan.md)
   - `tools/benchmark/src/vllm_grpc_bench/__main__.py` (CLI flags)
   - `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` (M6.1.1 timing extraction)
   - `tools/benchmark/tests/test_m6_1_1_*.py` (new unit tests)
   - `scripts/python/modal_bench_rest_grpc_server.py` (4 checkpoints × 2 transports)
   - `docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}` (NEW published artifacts)
   - `docs/benchmarks/m6_1-real-prompt-embeds.{md,json}` (additive methodology_supersedence annotation)
   - Under Phase 2(b): `contracts/instrumentation.md` (new section)
   - Under Phase 2(a) `instrumentation_artifact`: the symmetrisation edit in `modal_bench_rest_grpc_server.py` and/or `completions.py`

3. **Commit + PR**:
   ```bash
   git add -A
   git commit -m "$(cat <<'EOF'
   feat(m6_1_1): close engine_cost_drift_warning methodology gap

   Phase 1 diagnosed M6.1's chat_stream engine_ttft spread as <classification>.
   Phase 2(<path>) <action summary>.
   M6.2 anchor: <chat_stream_baseline_post_symmetrisation OR documented_in_contracts>.

   Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
   EOF
   )"
   git push -u origin 023-m6-1-1-engine-cost-instrumentation
   gh pr create --title "M6.1.1 — engine-cost instrumentation diagnosis & symmetrisation" --body-file <PR template>
   ```

4. **CI verification**: the 4 standard CI jobs (ruff check, ruff format check, mypy strict, pytest) MUST pass on the PR before merge. Per Constitution Principle IV, no `--no-verify` and no skip directives.

---

## Recovery: I ran Phase 1 twice and now my JSON is huge

`phase_1_runs[]` grows by one entry per `--m6_1_1-diagnose` invocation. The JSON size stays manageable (each entry ~50-200 KB for 18 (cell × cohort) sub-tables). If the file grows beyond your editor's comfort zone:
- The markdown report is human-readable and renders both runs side-by-side.
- For programmatic analysis use `jq` against the JSON: `jq '.phase_1_runs[-1].multi_point_timings' < m6_1_1-engine-cost-instrumentation.json`.

## Recovery: I want to discard a botched Phase 1 run

`phase_1_runs[]` is append-only (round-3 Q1). To truly discard a run:
1. `git checkout docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` to revert to the previously committed state.
2. Re-run `--m6_1_1-diagnose` — the harness will read the reverted file and start fresh.

If no previous commit exists (first run was the botched one):
1. `rm docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` and re-run `--m6_1_1-diagnose`.

## Recovery: My M6.1.1 deployment crashed mid-sweep

The harness handles partial-run state per M6.1's existing pattern: cells with `n_successes < n_per_cohort` are flagged `cell_incomplete` and excluded from classification. Re-run `--m6_1_1-diagnose` to retry; the new run is a fresh entry in `phase_1_runs[]`.

If the Modal app deployment itself is in a bad state (handshake-dict stale, etc.), see [`feedback_smoke_warmup_seed_zero`](../022-m6-1-real-prompt-embeds/spec.md) — M6.1's modal_bench_rest_grpc_server.py already pops handshake keys at startup to handle stale state.

---

## When to STOP and do something else

- **Phase 2(b) and the documented interpretation isn't operator-actionable** — if you can't write a clear "downstream milestone reads engine_ttft like this" rule in `contracts/instrumentation.md`, the data isn't ready for `channel_dependent_batching` closure. Open M6.1.1c instead (re-run with expanded checkpoints).
- **Phase 2(a) symmetrisation requires changes inside vLLM** — Constitution Principle II forbids vLLM source modification. If the fix the data suggests touches `vllm/`, file an upstream issue and pause M6.1.1 until the fix is available as a vLLM release. Bump M6.1.1's `engine_version` precondition (FR-004) to the next release accordingly.
- **You've run Phase 1 four+ times and still get inconclusive** — the four-checkpoint instrumentation isn't fine-grained enough to localise the spread. Open a successor sub-milestone with 6+ checkpoints (split `seg_bc` into pre-tokenise / tokenise / first-batch-schedule / first-forward sub-segments) before closing M6.1.1.
