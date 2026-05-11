# Contract: `vllm_grpc_bench --m5` CLI

## Synopsis

```bash
python -m vllm_grpc_bench --m5 \
    [--m5-modal-region=<string>] \
    [--m5-modal-token-env=<string>] \
    [--m5-rtt-validity-threshold-ms=<float>] \
    [--m5-rtt-exercise-threshold-ms=<float>] \
    [--m5-warmup-n=<int>] \
    [--m5-skip-deploy] \
    [--m5-modal-endpoint=<string>] \
    [--baseline-n=<int>] \
    [--candidate-n=<int>] \
    [--expand-n=<int>] \
    [--baseline-cv-warn=<float>] \
    [--widths=<csv-int>] \
    [--paths=<csv>] \
    [--axes=<csv>] \
    [--schema-candidates=<csv>] \
    [--skip-schema] \
    [--out=<dir>]
```

## Flags

### M5-specific flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--m5` | — | Required. Selects the M5 cross-host sweep entry point (`m5_sweep.run_m5_sweep`). Mutually exclusive with `--m3` and `--m4`. |
| `--m5-modal-region` | `auto-far` | Modal region for the cross-host gRPC server (research.md R-6). Sentinel `auto-far` resolves to `us-east-1` by default; operators in `us-east-1` SHOULD override to a far region (e.g., `eu-west-1`) so the measured RTT lands in the 30–100 ms band. The selected region is recorded in the M5 JSON's `m5_modal_region` field. |
| `--m5-modal-token-env` | `MODAL_BENCH_TOKEN` | Name of the environment variable from which the harness reads the bearer token used by the application-level gRPC interceptor (research.md R-1). The token MUST be set before the harness is invoked; the harness does not generate it. |
| `--m5-rtt-validity-threshold-ms` | `1.0` | FR-004 same-host-fallback threshold. The harness refuses to issue verdicts on any cohort whose measured median RTT falls below this value (mark `not_measurable` with reason `"rtt_below_validity_threshold"`). |
| `--m5-rtt-exercise-threshold-ms` | `20.0` | FR-004 RTT-bounded-axis-exercise threshold. Cohorts whose measured median RTT falls below this value (but at or above `--m5-rtt-validity-threshold-ms`) get `low_rtt_caveat: true` and the report flags them in the executive summary. |
| `--m5-warmup-n` | `32` | Number of iterations per warm-up cohort (research.md R-5). Recorded in the JSON with `discarded: true`. Set to `0` to disable warm-up (NOT recommended; the report's executive summary will flag a "no warm-up" warning). |
| `--m5-skip-deploy` | (off) | Skip the Modal deploy/teardown handshake and connect to an already-running Modal endpoint via `--m5-modal-endpoint`. Used for re-running the sweep against a long-running Modal app during iteration. The harness still runs warm-up and RTT-probe per cohort. |
| `--m5-modal-endpoint` | (unset) | Explicit Modal tunnel endpoint (`host:port`) for use with `--m5-skip-deploy`. When set, the harness does NOT deploy a new Modal app and assumes the endpoint is reachable. Required when `--m5-skip-deploy` is set. |

### Inherited M4 flags (semantics unchanged)

| Flag | Default | Purpose |
|------|---------|---------|
| `--baseline-n=<int>` | `100` | Per-path cross-host shared-baseline cohort size (FR-008). Minimum 100. |
| `--candidate-n=<int>` | `100` | Default candidate cohort size before borderline-expand (FR-009). |
| `--expand-n=<int>` | `250` | Cohort size after borderline-expand. Must be `> --candidate-n`. |
| `--baseline-cv-warn=<float>` | `0.10` | Within-cohort CV warn threshold for **baseline** cohorts. **M5's default is higher than M4's `0.05`** because real-network jitter is expected to produce 2–4× M4's loopback CV. The run never aborts on CV; cohorts above the threshold get `noisy_baseline: true`. |
| `--widths=<csv-int>` | `2048,4096,8192` | Hidden-size matrix. Schema candidates always start at 4096 (cascade). |
| `--paths=<csv>` | `embed,chat_stream` | Paths to measure. |
| `--axes=<csv>` | `max_message_size,keepalive,compression,http2_framing` | Channel axes to sweep (FR-006). |
| `--schema-candidates=<csv>` | `packed_token_ids,oneof_flattened_input,chunk_granularity` | Schema candidates (FR-011) measured against per-path M5 frozen baselines. |
| `--skip-schema` | (off) | Skip US2 entirely. Useful when iterating on US1 only. |
| `--out=<dir>` | `bench-results/m5-full` | Output directory for transient per-iteration JSON. The published report path (`docs/benchmarks/m5-cross-host-validation.{md,json}`) is fixed and not configurable from the CLI. |

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Sweep ran to completion. Report files were written. The exit is `0` regardless of within-cohort CV (FR-005); per-cohort CV is in the JSON. |
| `2` | Pre-flight validation failed (e.g., `--m5-skip-deploy` set without `--m5-modal-endpoint`, `--candidate-n` not less than `--expand-n`, `--m5-modal-token-env` env var unset). No measurement happened. |
| `3` | Modal deploy / handshake failed (e.g., tunnel URL never published, Modal token rejected, image build failed). No measurement happened; nothing to teardown. |
| `4` | The harness produced an internal validation failure (e.g., M5 sweep would emit `noise_bounded`). Should never happen in production; indicates a code-level bug. |
| `6` | Mid-run failure on the remote host (per Edge Case "remote host is unavailable mid-run"). Partially-collected cohorts are discarded; operator instructed to re-run. Modal teardown is still attempted. |
| `7` | Bearer-token rejection during the sweep (per research.md OP-3). A single rejected RPC fails the run. Modal teardown is still attempted. |
| `8` | RTT validity check failed for a critical cohort (i.e., the cross-host shared-baseline cohort's median RTT was below `--m5-rtt-validity-threshold-ms`, meaning the connection unexpectedly resolved to a same-host route). Modal teardown is still attempted. |

## Side effects on success (`exit 0`)

1. Writes per-iteration timing arrays to `<--out>/per-iteration/*.json` (gitignored).
2. Writes the published M5 report to `docs/benchmarks/m5-cross-host-validation.json` (strict-superset schema per FR-014 / research.md R-8).
3. Writes the human-readable companion to `docs/benchmarks/m5-cross-host-validation.md` with: the methodology preamble (including the cross-host topology + measured RTT distribution), the per-axis × per-width × per-path verdict table, the per-path frozen-channel baseline summary, the schema-candidate verdicts, the Supersedes M4 table (with verdict-changed rows visually distinguished per SC-004), the Negative results appendix.
4. Prints a one-line summary to stdout: `M5 sweep complete: <N> recommend, <M> no_winner, <K> client_bound, <L> server_bound. <P> M4 cells superseded (<Q> verdict-changed, <R> verdict-confirmed). RTT median <X> ms across <C> cohorts.`

## Side effects on failure

The Modal app is torn down on every failure path that occurred after deploy succeeded (exit codes 6, 7, 8 and uncaught exceptions). Exit codes 2 and 3 fail before deploy, so there is no Modal app to teardown. The harness logs the teardown attempt's outcome to stderr so the operator can verify no orphaned Modal app remains.

## Reproducibility

The M5 sweep is reproducible by a single CLI invocation:

```bash
export MODAL_BENCH_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m vllm_grpc_bench --m5 --m5-modal-region=eu-west-1
```

The harness handles deploy, sweep, teardown end-to-end. The Modal app is named per `scripts/python/modal_bench_grpc_server.py`'s `_APP_NAME` constant (`vllm-grpc-bench-mock` per research.md OP-1) and uses a per-run bearer token sourced from `$MODAL_BENCH_TOKEN`. No persistent Modal state survives a successful run.
