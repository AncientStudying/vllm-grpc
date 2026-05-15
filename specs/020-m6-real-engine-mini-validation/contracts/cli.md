# Contract: M6 CLI Surface

**Plan**: [../plan.md](../plan.md)
**Spec FRs**: FR-011 (smoke), FR-017 (full sweep CLI), FR-026 (progress output)

The M6 CLI surface follows the existing M5.x pattern in `tools/benchmark/src/vllm_grpc_bench/__main__.py`: a top-level `--m6` (full sweep) or `--m6-smoke` (smoke gate) flag toggles the M6 dispatch path, and a parallel set of namespaced flags configures the run.

---

## Full sweep

### Invocation

```bash
python -m vllm_grpc_bench --m6 [options...]
```

### Required flags

| Flag | Type | Description |
|---|---|---|
| `--m6` | bool | Top-level dispatch flag. MUST be the only top-level mode flag (mutually exclusive with `--m5_1`, `--m5_2`, etc.). |

### M6-namespaced flags (all optional, with defaults)

| Flag | Type | Default | Description |
|---|---|---|---|
| `--m6-modal-region` | str | `eu-west-1` | Modal region for the deploy. Matches FR-006 / Assumption "Region" / M5.2 default. |
| `--m6-modal-token-env` | str | `MODAL_TOKEN_ID` | Env var name carrying the Modal token (mirrors `--m5_2-modal-token-env`). |
| `--m6-modal-endpoint` | str | (autodiscovered) | Override the autodiscovered Modal endpoint (advanced; mirrors `--m5_2-modal-endpoint`). |
| `--m6-skip-deploy` | bool | False | Skip Modal deploy and reuse a pre-deployed app (advanced; mirrors `--m5_2-skip-deploy`). |
| `--m6-base-seed` | int | `42` | `M6_BASE_SEED` constant for FR-025. Recorded in RunMeta (FR-018). |
| `--m6-model` | str | `Qwen/Qwen3-7B` | Model identifier passed to the Modal app via `M6_MODEL` env var. R-10. |
| `--m6-events-sidecar-out` | path | (auto under `docs/benchmarks/`) | Per-RPC events JSONL sidecar output path. Mirrors `--m5_2-events-sidecar-out`. |
| `--m6-report-out` | path | `docs/benchmarks/m6-real-engine-mini-validation.md` | Markdown report output (FR-013). |
| `--m6-report-json-out` | path | `docs/benchmarks/m6-real-engine-mini-validation.json` | JSON companion output (FR-013). |
| `--m6-rtt-validity-ms` | float | (M5.2 default) | RTT probe validity threshold (ms). Mirrors `--m5_2-rtt-validity-ms`. |
| `--m6-rtt-exercise-ms` | float | (M5.2 default) | RTT probe exercise threshold (ms). Mirrors `--m5_2-rtt-exercise-ms`. |
| `--m6-shim-overhead-warn-pct` | float | (M5.2 default) | REST shim overhead warning threshold (% of total wall-clock). Mirrors `--m5_2-shim-overhead-warn-pct`. |
| `--m6-run-id` | str | (auto: ISO timestamp + git_sha suffix) | Override the auto-generated run identifier. |
| `--m6-m5-2-baseline` | path | `docs/benchmarks/m5_2-transport-vs-tuning.json` | Override the M5.2 baseline JSON path (advanced; default matches FR-014). |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Full sweep completed; all 6 cells received a terminal classification; report written. |
| `1` | Sweep aborted at launch — M5.2 baseline file precondition failed (FR-014 sub-clause). Error message names the failing precondition. |
| `2` | Sweep aborted mid-run — Modal deploy failure or model-load failure (the throwaway forward-pass per R-10 surfaced an OOM or load error). |
| `3` | Sweep ran but published JSON validation failed against the M5.2 strict-superset schema (FR-016). Report still written for investigation. |

### Stdout / stderr contract (FR-026)

- **stderr**: startup banner, per-(cell × cohort) progress lines (18 total), completion banner. Format:
  - Startup: `M6 sweep: 6 cells × 3 cohorts × n=100, runtime ETA ≤90 min, model=<model_id>, region=<region>`
  - Per-(cell × cohort) progress: `[i/18] <cell.path> × c=<cell.concurrency> / <cohort> — <successes>/100 succ — <wall_ms> ms — ETA <minutes>m`
  - Completion: `M6 sweep complete: verdict table at <report_path> (5 verdict_survives / 1 cell_incomplete — example)`
- **stdout**: the final report path (so the harness composes with shell pipes).

---

## Smoke gate

### Invocation

```bash
python -m vllm_grpc_bench --m6-smoke [options...]
```

### Smoke-specific flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `--m6-smoke` | bool | — | Top-level dispatch flag for smoke mode. Mutually exclusive with `--m6`. |

The smoke gate inherits all `--m6-*` flags above (modal region, base seed, model, etc.). It does NOT honour `--m6-events-sidecar-out`, `--m6-report-out`, or `--m6-report-json-out` because smoke does not write a persistent diagnostic file (FR-011).

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All 6 (cell × cohort) pairs in the smoke matrix passed — FR-011. |
| `1` | One or more (cell × cohort) pairs failed — FR-011. Per-pair stderr summary lines name the failing pairs. |
| `2` | Smoke aborted at launch — M5.2 baseline file precondition failed (FR-014 sub-clause). Same as full-sweep code 1. |

### Stdout / stderr contract (FR-011)

- **stderr only** — no persistent diagnostic file.
- One summary line per (cell × cohort) pair (6 total), format: `cell=<path>×c=<c> cohort=<cohort> status=<ok|failed> reason=<short string>`.
- No startup or completion banner (smoke is short).
- **stdout**: empty on success; empty on failure (the failure semantics are conveyed via exit code + stderr).

---

## CLI cross-cutting rules

1. **Mutual exclusion**: `--m6` and `--m6-smoke` are mutually exclusive with each other AND with all M5.x mode flags (`--m5_1`, `--m5_1-smoke`, `--m5_2`, `--m5_2-smoke`, etc.). Argparse rejection.
2. **Operator triggering**: Both `--m6` and `--m6-smoke` are operator-triggered. Neither is a CI gate. M6 does not introduce any GitHub Actions workflow.
3. **Modal compute**: Both modes consume Modal A10G compute. The harness MUST NOT silently retry the entire sweep on transient failure beyond FR-023's per-RPC 3-retry rule.
4. **Reproducibility**: Re-running `python -m vllm_grpc_bench --m6` on the same git sha + Modal region + base seed + engine version MUST produce bit-exact identical engine output sequences (per FR-025), and the verdict table MUST be deterministic given the same M5.2 baseline JSON (per FR-014).
