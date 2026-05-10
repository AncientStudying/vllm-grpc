# Contract: `vllm_grpc_bench --m4` CLI

## Synopsis

```bash
python -m vllm_grpc_bench --m4 \
    [--no-pacing | --paced] \
    [--shared-baseline | --per-axis-baseline] \
    [--baseline-n=<int>] \
    [--candidate-n=<int>] \
    [--expand-n=<int>] \
    [--baseline-cv-max=<float>] \
    [--widths=<csv-int>] \
    [--paths=<csv>] \
    [--axes=<csv>] \
    [--schema-candidates=<csv>] \
    [--skip-schema] \
    [--out=<dir>]
```

## Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--m4` | — | Required. Selects the M4 sweep entry point (`m4_sweep.run_m4_sweep`). Mutually exclusive with `--m3`. |
| `--no-pacing` / `--paced` | `--no-pacing` | Sets `MockEngineConfig.pace_tokens`. M4's default is `--no-pacing` (the FR-001 default for the M4 sweep is unpaced; FR-001 requires the paced mode to remain *available*, not be the default). |
| `--shared-baseline` / `--per-axis-baseline` | `--shared-baseline` | Selects baseline-measurement strategy. M4's default is shared. `--per-axis-baseline` exists for parity with M3 reproductions and emits a warning that the resulting verdicts are not M4-defensible. |
| `--baseline-n=<int>` | `100` | Sample count per shared baseline cohort. Minimum 100 (rejected below). |
| `--candidate-n=<int>` | `100` | Default sample count per candidate cohort before borderline-expand. |
| `--expand-n=<int>` | `250` | Sample count after borderline-expand. Must be `> --candidate-n`. |
| `--baseline-cv-max=<float>` | `0.05` | Maximum within-cohort coefficient of variation on the time metric for baseline cohorts (FR-005 / R-11). Run aborts if exceeded. |
| `--widths=<csv-int>` | `2048,4096,8192` | Hidden-size matrix. Schema candidates always start at 4096 (cascade). |
| `--paths=<csv>` | `embed,chat_stream` | Paths to measure. |
| `--axes=<csv>` | `max_message_size,keepalive,compression,http2_framing` | Channel axes to sweep. |
| `--schema-candidates=<csv>` | `packed_token_ids,oneof_flattened_input,chunk_granularity` | Schema candidates (US3) measured against per-path frozen baselines. |
| `--skip-schema` | (off) | Skip US3 entirely. Useful when iterating on US1/US2 only. |
| `--out=<dir>` | `bench-results/m4-full` | Output directory for transient per-iteration JSON. The published report path (`docs/benchmarks/m4-time-axis-tuning.{md,json}`) is fixed and not configurable from the CLI. |

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Sweep ran to completion. Report files were written. Verdicts are defensible (or empty if every candidate failed `client_bound` or every comparison was `not_measurable`). |
| `2` | Pre-flight validation failed (e.g., `--candidate-n` not greater than `--baseline-cv-max` arithmetic, mutually-exclusive flag conflict). No measurement happened. |
| `3` | A shared baseline cohort exceeded `--baseline-cv-max` (FR-005). The poisoned baseline diagnostic is printed to stderr; no verdicts emitted. |
| `4` | The harness produced an internal validation failure (e.g., M4 sweep would emit `noise_bounded`). Should never happen in production; indicates a code-level bug. |
| `5` | A schema candidate cohort failed proto compilation against the candidate namespace (Constitution I — `make proto` is the only stub generator). |

## Side effects on success (`exit 0`)

1. Writes per-iteration timing arrays to `<--out>/per-iteration/*.json` (gitignored).
2. Writes the published M4 report to `docs/benchmarks/m4-time-axis-tuning.json` (strict-superset schema per R-7).
3. Writes the human-readable companion to `docs/benchmarks/m4-time-axis-tuning.md` with: the methodology preamble, the per-axis × per-width × per-path verdict table, the per-path frozen-channel baseline summary, the schema-candidate verdicts, the Supersedes M3 table, the Negative results appendix.
4. Prints a one-line summary to stdout: `M4 sweep complete: <N> recommend, <M> no_winner, <K> client_bound. <P> M3 cells superseded.`

## Reproducibility

The harness records the random seed (default `0`), every flag value, the resolved `MockEngineConfig`, and the resolved `M4SweepConfig` into the JSON's top level so the run is reproducible from the JSON alone. Re-running with the same seed and the same flags MUST produce numerically identical cohort means and CIs (modulo non-deterministic system noise documented in the `baseline_cv_max` discipline).

## Examples

```bash
# Full M4 sweep (US1 mechanics + US2 channel sweep + US3 schema candidates):
python -m vllm_grpc_bench --m4

# US1+US2 only — skip schema candidates while iterating on the channel sweep:
python -m vllm_grpc_bench --m4 --skip-schema

# Compatibility cross-check: run with paced mode + per-axis baseline (M3 mechanics, M4 reporting):
python -m vllm_grpc_bench --m4 --paced --per-axis-baseline

# Explore a tighter baseline acceptance threshold:
python -m vllm_grpc_bench --m4 --baseline-cv-max=0.03
```
