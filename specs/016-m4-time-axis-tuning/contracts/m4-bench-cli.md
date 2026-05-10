# Contract: `vllm_grpc_bench --m4` CLI

## Synopsis

```bash
python -m vllm_grpc_bench --m4 \
    [--no-pacing | --paced] \
    [--shared-baseline | --per-axis-baseline] \
    [--baseline-n=<int>] \
    [--candidate-n=<int>] \
    [--expand-n=<int>] \
    [--warmup-n=<int>] \
    [--baseline-cv-warn=<float>] \
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
| `--warmup-n=<int>` | `10` | Discarded leading RPCs per cohort. Reuses the same server + channel as the measurement so cold-start cost (channel setup, HTTP/2 negotiation, protobuf descriptor caches) is paid before sampling begins. Set to 0 to disable. |
| `--baseline-cv-warn=<float>` | `0.05` | Within-cohort CV warn threshold on the verdict metric for **baseline** cohorts (FR-005 / R-11). The run never aborts on CV; cohorts above this threshold get a `noisy_baseline: true` flag in the JSON and are named in a closing stderr warning so the report reader can adjudicate. |
| `--widths=<csv-int>` | `2048,4096,8192` | Hidden-size matrix. Schema candidates always start at 4096 (cascade). |
| `--paths=<csv>` | `embed,chat_stream` | Paths to measure. |
| `--axes=<csv>` | `max_message_size,keepalive,compression,http2_framing` | Channel axes to sweep. |
| `--schema-candidates=<csv>` | `packed_token_ids,oneof_flattened_input,chunk_granularity` | Schema candidates (US3) measured against per-path frozen baselines. |
| `--skip-schema` | (off) | Skip US3 entirely. Useful when iterating on US1/US2 only. |
| `--out=<dir>` | `bench-results/m4-full` | Output directory for transient per-iteration JSON. The published report path (`docs/benchmarks/m4-time-axis-tuning.{md,json}`) is fixed and not configurable from the CLI. |

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Sweep ran to completion. Report files were written. The exit is `0` regardless of within-cohort CV (FR-005); per-cohort CV is in the JSON. |
| `2` | Pre-flight validation failed (e.g., `--candidate-n` not greater than `--expand-n`, mutually-exclusive flag conflict). No measurement happened. |
| `4` | The harness produced an internal validation failure (e.g., M4 sweep would emit `noise_bounded`). Should never happen in production; indicates a code-level bug. |
| `5` | A schema candidate cohort failed proto compilation against the candidate namespace (Constitution I — `make proto` is the only stub generator). |

Exit `3` is no longer used. The previous "abort on noisy baseline" behavior was removed in favor of the FR-005 record-and-report model — see `research.md` R-11.

## Side effects on success (`exit 0`)

1. Writes per-iteration timing arrays to `<--out>/per-iteration/*.json` (gitignored).
2. Writes the published M4 report to `docs/benchmarks/m4-time-axis-tuning.json` (strict-superset schema per R-7).
3. Writes the human-readable companion to `docs/benchmarks/m4-time-axis-tuning.md` with: the methodology preamble, the per-axis × per-width × per-path verdict table, the per-path frozen-channel baseline summary, the schema-candidate verdicts, the Supersedes M3 table, the Negative results appendix.
4. Prints a one-line summary to stdout: `M4 sweep complete: <N> recommend, <M> no_winner, <K> client_bound. <P> M3 cells superseded.`

## Reproducibility

The harness records the random seed (default `0`), every flag value, the resolved `MockEngineConfig`, and the resolved `M4SweepConfig` into the JSON's top level so the run is reproducible from the JSON alone. Re-running with the same seed and the same flags MUST produce numerically identical cohort means and CIs (modulo non-deterministic system noise visible per-cohort under the `time_cv` / `ttft_cv` fields).

## Examples

```bash
# Full M4 sweep (US1 mechanics + US2 channel sweep + US3 schema candidates):
python -m vllm_grpc_bench --m4

# US1+US2 only — skip schema candidates while iterating on the channel sweep:
python -m vllm_grpc_bench --m4 --skip-schema

# Compatibility cross-check: run with paced mode + per-axis baseline (M3 mechanics, M4 reporting):
python -m vllm_grpc_bench --m4 --paced --per-axis-baseline

# Tighten the baseline-CV warn threshold (still does not abort the run):
python -m vllm_grpc_bench --m4 --baseline-cv-warn=0.03
```
