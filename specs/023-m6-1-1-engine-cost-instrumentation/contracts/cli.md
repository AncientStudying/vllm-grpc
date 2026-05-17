# M6.1.1 CLI Contract

**Plan**: [../plan.md](../plan.md) | **Spec**: [../spec.md](../spec.md) | **Data model**: [../data-model.md](../data-model.md)

Exposed via `python -m vllm_grpc_bench` (the existing harness entrypoint). All M6.1.1 flags are namespaced `--m6_1_1-*`. The two top-level mode flags are mutually exclusive within a single invocation (FR-025).

---

## Mode flags

| Flag | Phase | Required by | Default | Description |
| :-- | :-- | :-- | :-- | :-- |
| `--m6_1_1-diagnose` | Phase 1 | spec FR-013 | (none) | Run the 6 cells × 3 cohorts × n=50 mini-sweep with four-checkpoint instrumentation. Writes/updates `docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}` and appends a new `phase_1_runs[]` entry per round-3 Q1. |
| `--m6_1_1` | Phase 2 | spec FR-014 / FR-016 / round-3 Q2 | (none) | Branches internally on the most-recent Phase 1 classification: under uniform `instrumentation_artifact` runs the full n=100 verification sweep + embed regression check + fresh baseline emission; under uniform `channel_dependent_batching` validates `contracts/instrumentation.md` carries an `m6_1_1`-keyed heading and flips `phase_2_path = "phase_2b_documented"`; under any other state refuses with exit code `1`. |

The two flags are mutually exclusive with each other and with `--m6_1`, `--m6_1-smoke`, `--m6`, `--m6-smoke`, `--m5_2`, `--m5_1`, `--m5`, `--m4`, `--m3` (FR-013, FR-025).

---

## Auxiliary flags

Default values match M6.1 + the additional M6.1.1-specific paths per Research R-9.

| Flag | Default | Required by | Description |
| :-- | :-- | :-- | :-- |
| `--m6_1_1-modal-region` | `eu-west-1` | FR-002 / FR-026 | Modal region for the deployment. Same as M6.1's default to keep network-stack characteristics constant. |
| `--m6_1_1-modal-token-env` | `MODAL_BENCH_TOKEN` | FR-026 | Environment variable name carrying the Modal auth token. |
| `--m6_1_1-modal-endpoint` | (none) | FR-026 | Optional; format `grpc=tcp+plaintext://host:port,rest_https_edge=https://host`. Required when `--m6_1_1-skip-deploy` is passed. |
| `--m6_1_1-skip-deploy` | `False` | FR-026 / Research R-5 | Skip Modal app deployment; use an already-running endpoint. Requires `--m6_1_1-modal-endpoint`. |
| `--m6_1_1-base-seed` | `42` | FR-027 | Base RNG seed. Matches M6 / M6.1 default. |
| `--m6_1_1-model` | `Qwen/Qwen3-8B` | FR-027 | HuggingFace model identifier. Reused from M6.1; changing it invalidates the M6.1 baseline comparison (FR-004). |
| `--m6_1_1-m6-1-baseline` | `docs/benchmarks/m6_1-real-prompt-embeds.json` | FR-001 / FR-027 | Path to M6.1's published JSON (hard precondition input). |
| `--m6_1_1-report-out` | `docs/benchmarks/m6_1_1-engine-cost-instrumentation.md` | FR-027 / Research R-9 | Markdown output path. |
| `--m6_1_1-report-json-out` | `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` | FR-027 / Research R-9 | JSON companion output path. |
| `--m6_1_1-events-sidecar-out` | `docs/benchmarks/m6_1_1-events.jsonl` | Research R-9 | Per-RPC events sidecar (JSONL). |
| `--m6_1_1-allow-engine-mismatch` | `False` | FR-004 | Acknowledgement flag for an `engine_version` divergence between M6.1's baseline and the deployment. Annotates the published report. |

---

## Exit codes

Five non-zero exit codes per spec (round-2 + round-3 hard gates):

| Code | Meaning | Required by | Stderr message shape |
| :-- | :-- | :-- | :-- |
| `0` | Success | — | (none) |
| `1` | Missing baseline / missing contracts heading / `--m6_1_1` invoked in non-actionable state | FR-001, FR-004, FR-016, round-3 Q2 | `m6.1.1: <reason>; see <suggested-flag>` |
| `2` | Torch pin mismatch | FR-003 | `m6.1.1: torch=={actual} on client; expected torch==2.11.0; pip install torch==2.11.0` |
| `3` | Phase 1 re-run needed (mixed / inconclusive / drift_not_reproduced single-run) | FR-017, FR-018 | `m6.1.1: <classification pattern>; re-run --m6_1_1-diagnose` |
| `4` | Instrumentation perturbation budget exceeded | FR-012, round-2 Q3 | `m6.1.1: perturbation > 500 µs on {cohort, cell}; reduce checkpoint cost and re-run --m6_1_1-diagnose` |
| `5` | Milestone split required (heterogeneous Phase 2 disallowed) | FR-017(b), FR-018, round-2 Q4 | `m6.1.1: still-divergent after 2 Phase 1 runs; open successor sub-milestones M6.1.1a / M6.1.1b before any code or doc change` |

Exit codes are stable across milestone versions — M6.2 (when written) MUST NOT reuse these codes for different semantics.

---

## Mutual exclusions and preconditions

| Combination | Result |
| :-- | :-- |
| `--m6_1_1-diagnose` + `--m6_1_1` | exit `2` from argparse (mutual exclusion) |
| `--m6_1_1` without prior `--m6_1_1-diagnose` (M6.1.1 report file absent) | exit `1` ("`--m6_1_1` requires a prior `--m6_1_1-diagnose` to produce classifiable results") |
| `--m6_1_1` while `phase_1_classifications` indicate any non-actionable state | exit `1` with state-specific guidance (round-3 Q2 case (c)) |
| `--m6_1_1-skip-deploy` without `--m6_1_1-modal-endpoint` | exit `2` from argparse |
| Missing `MODAL_BENCH_TOKEN` env var | exit `4` per FR-026 (matches M6.1 convention; note: exit `4` here is the *argparse* invariant, separate from FR-012's perturbation gate — the harness sets distinct codes by entry point) |

---

## Worked invocations

### Phase 1 — diagnostic mini-sweep
```bash
export MODAL_BENCH_TOKEN="..."
python -m vllm_grpc_bench --m6_1_1-diagnose --m6_1_1-modal-region=eu-west-1
# → publishes docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}
# → exit 0 if classifications are uniform-actionable; exit 3 on re-run-needed states; exit 4 on perturbation overrun
```

### Phase 2(a) — verification sweep after symmetrisation
```bash
# (Operator has applied the symmetrisation code change and committed.)
python -m vllm_grpc_bench --m6_1_1 --m6_1_1-modal-region=eu-west-1
# → runs 6 cells × 3 cohorts × n=100 + embed regression check + fresh baselines
# → flips phase_2_path = "phase_2a_verified" in the M6.1.1 JSON
# → emits methodology_supersedence annotations on M6.1's published artifacts (FR-023 / FR-024)
```

### Phase 2(b) — doc-only path
```bash
# (Operator has updated contracts/instrumentation.md with `## M6.1.1: Channel-Dependent Batching Effect`.)
python -m vllm_grpc_bench --m6_1_1
# → no Modal sweep; validates contracts heading is present; flips phase_2_path = "phase_2b_documented"
```

### Force re-deploy reuse (skip deploy)
```bash
python -m vllm_grpc_bench --m6_1_1-diagnose --m6_1_1-skip-deploy \
  --m6_1_1-modal-endpoint=grpc=tcp+plaintext://my-modal-app:50051,rest_https_edge=https://my-modal-app.modal.run
# → reuses an already-running deployment; useful when re-running Phase 1 without paying for redeploy
```

---

## Invariants

- **CLI surface is parallel to M6.1's**: every M6.1 flag has a `--m6_1_1-*` analogue with the same default semantics (modulo path naming per Research R-9).
- **The two mode flags are the only entry points**: there is no `--m6_1_1-smoke` because the Phase 1 mini-sweep IS the smoke-equivalent (FR-028).
- **All exit codes have a single canonical message**: tests assert the message shape via regex (the worded prefix is part of the contract surface).
- **Re-runs are idempotent at the file level**: re-running `--m6_1_1-diagnose` produces the same `phase_1_runs[-1]` entry given identical inputs (modulo timestamps and Modal scheduling jitter).
