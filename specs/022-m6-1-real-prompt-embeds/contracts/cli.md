# Contract: M6.1 CLI Surface

**Plan**: [../plan.md](../plan.md)
**Spec FRs**: FR-012 (smoke), FR-025 (full sweep CLI), FR-023 (progress output), FR-026 (output paths)

The M6.1 CLI surface follows the existing M6 pattern in
`tools/benchmark/src/vllm_grpc_bench/__main__.py`: a top-level `--m6_1`
(full sweep) or `--m6_1-smoke` (smoke gate) flag toggles the M6.1 dispatch
path, and a parallel set of namespaced flags configures the run.

The `--m6_1` namespace uses an underscore between `m6` and `1` to match the
output file basenames (`m6_1-real-prompt-embeds.{md,json}`) and the branch
name (`022-m6-1-real-prompt-embeds`), per spec round-2 Q1 canonicalisation.

---

## Full sweep

### Invocation

```bash
python -m vllm_grpc_bench --m6_1 [options...]
```

### Required flags

| Flag | Type | Description |
|---|---|---|
| `--m6_1` | bool | Top-level dispatch flag. Mutually exclusive with `--m5_1`, `--m5_2`, `--m6`, etc. |

### M6.1-namespaced flags (all optional, with defaults)

| Flag | Type | Default | Description |
|---|---|---|---|
| `--m6_1-modal-region` | str | `eu-west-1` | Modal region for the deploy. Matches FR-025. |
| `--m6_1-modal-token-env` | str | `MODAL_TOKEN_ID` | Env var name carrying the Modal token (mirrors `--m6-modal-token-env`). |
| `--m6_1-modal-endpoint` | str | (autodiscovered) | Override the autodiscovered Modal endpoint (advanced; mirrors `--m6-modal-endpoint`). |
| `--m6_1-skip-deploy` | bool | False | Skip Modal deploy and reuse a pre-deployed app (advanced; mirrors `--m6-skip-deploy`). |
| `--m6_1-base-seed` | int | `42` | `M6_1_BASE_SEED` constant for FR-019. Recorded in RunMeta (FR-027). |
| `--m6_1-model` | str | `Qwen/Qwen3-8B` | Model identifier passed to the Modal app via the same env var M6 uses (reused unchanged per FR-007). |
| `--m6_1-events-sidecar-out` | path | (auto under `docs/benchmarks/`) | Per-RPC events JSONL sidecar output path. Mirrors `--m6-events-sidecar-out`. |
| `--m6_1-report-out` | path | `docs/benchmarks/m6_1-real-prompt-embeds.md` | Markdown report output (FR-026). |
| `--m6_1-report-json-out` | path | `docs/benchmarks/m6_1-real-prompt-embeds.json` | JSON companion output (FR-026). |
| `--m6_1-rtt-validity-ms` | float | (M6 default) | RTT probe validity threshold (ms). Mirrors `--m6-rtt-validity-ms`. |
| `--m6_1-rtt-exercise-ms` | float | (M6 default) | RTT probe exercise threshold (ms). Mirrors `--m6-rtt-exercise-ms`. |
| `--m6_1-shim-overhead-warn-pct` | float | (M6 default) | REST shim overhead warning threshold (% of total wall-clock). Mirrors `--m6-shim-overhead-warn-pct`. |
| `--m6_1-run-id` | str | (auto: ISO timestamp + git_sha suffix) | Override the auto-generated run identifier. |
| `--m6_1-m6-baseline` | path | `docs/benchmarks/m6-real-engine-mini-validation.json` | Override the M6 baseline JSON path (advanced; default matches FR-008/FR-009). |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Full sweep completed; all 6 cells received a terminal classification; report written. |
| `1` | Sweep aborted at launch — M6 baseline JSON pre-check failed (FR-009). File missing, isn't valid JSON, or doesn't contain entries for all 6 M6.1 cells. Error message names the failing precondition. |
| `2` | Sweep aborted at launch — client `torch` pre-check failed (FR-006). Either `torch` is not importable on the client, or `torch.__version__` does not match the pinned `2.11.0`. Error message names both detected and expected versions. |
| `3` | Sweep aborted mid-run — Modal deploy failure or model-load failure (the throwaway forward-pass per M6's R-10 surfaced an OOM or load error). |
| `4` | Sweep ran but published JSON validation failed against the M6 strict-superset schema (FR-021). Report still written for investigation. |

### Stdout / stderr contract (FR-023)

- **stderr**: startup banner, per-(cell × cohort) progress lines (18 total), completion banner. Format:
  - Startup: `M6.1 sweep: 6 cells × 3 cohorts × n=100, runtime ETA ≤90 min, model=<model_id>, region=<region>, torch=<version>, vllm=<version>`
  - Per-(cell × cohort) progress: `[i/18] <cell.path> × c=<cell.concurrency> / <cohort> — <successes>/100 succ — <wall_ms> ms — ETA <minutes>m`
  - Completion: `M6.1 sweep complete: verdict table at <report_path> (5 verdict_survives / 1 cell_incomplete — example)`
- **stdout**: the final report path (so the harness composes with shell pipes).

---

## Smoke gate

### Invocation

```bash
python -m vllm_grpc_bench --m6_1-smoke [options...]
```

### Smoke-specific flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `--m6_1-smoke` | bool | — | Top-level dispatch flag for smoke mode. Mutually exclusive with `--m6_1`. |

The smoke gate inherits all `--m6_1-*` flags above (modal region, base seed,
model, etc.). It does NOT honour `--m6_1-events-sidecar-out`,
`--m6_1-report-out`, or `--m6_1-report-json-out` because smoke does not write
a persistent diagnostic file (FR-012).

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All 6 (cell × cohort) pairs in the smoke matrix passed — FR-012. |
| `1` | One or more (cell × cohort) pairs failed — FR-012. Per-pair stderr summary lines name the failing pairs. (Missing-`torch` failures are caught earlier by the FR-006 pre-check and surface as code `2`, not as a code-`1` RPC failure.) |
| `2` | Smoke aborted at launch — either pre-check failed: the M6 baseline JSON pre-check (FR-013) OR the client `torch` pre-check (FR-006). Smoke collapses both pre-check failures under a single non-RPC code because smoke's design intent is "wiring validation, not failure-mode discrimination". Full-sweep mode splits these into codes `1` (baseline) and `2` (torch) so the operator can tell them apart when ~80 min of compute is on the line. |

### Stdout / stderr contract (FR-012)

- **stderr only** — no persistent diagnostic file.
- One summary line per (cell × cohort) pair (6 total), format: `cell=<path>×c=<c> cohort=<cohort> status=<ok|failed> reason=<short string>`.
- **One additional one-line stderr note**: `note: chat_stream control-drift check is full-sweep-only (FR-012/FR-029) — will run after the n=100 sweep completes`. Always printed at the end of smoke output regardless of overall status.
- No startup or completion banner (smoke is short).
- **stdout**: empty on success; empty on failure (the failure semantics are conveyed via exit code + stderr).

---

## CLI cross-cutting rules

1. **Mutual exclusion**: `--m6_1` and `--m6_1-smoke` are mutually exclusive with each other AND with all earlier mode flags (`--m5_1`, `--m5_1-smoke`, `--m5_2`, `--m5_2-smoke`, `--m6`, `--m6-smoke`). Argparse rejection.
2. **Operator triggering**: Both `--m6_1` and `--m6_1-smoke` are operator-triggered. Neither is a CI gate. M6.1 does not introduce any GitHub Actions workflow.
3. **Modal compute**: Both modes consume Modal A10G compute. The harness MUST NOT silently retry the entire sweep on transient failure beyond FR-017's per-RPC 3-retry rule.
4. **Reproducibility**: Re-running `python -m vllm_grpc_bench --m6_1` on the same git sha + Modal region + base seed + engine version + M6 baseline JSON MUST produce bit-identical verdict classifications (SC-006). Per-RPC seeds, classifier algorithm, and engine code path are all deterministic; cohort-mean classifier metrics may vary within published CIs but verdict categories MUST match.
5. **Engine config reuse**: The Modal app deployed for `--m6_1` reuses the same env vars / config that M6 uses (`M6_USE_REAL_ENGINE=true`, `M6_MODEL=Qwen/Qwen3-8B`, etc. — see M6 contracts/cli.md). No `--m6_1`-specific Modal env vars are introduced because the engine launch is identical to M6's per FR-007; M6.1's `--m6_1` dispatch is purely a client-side change.
