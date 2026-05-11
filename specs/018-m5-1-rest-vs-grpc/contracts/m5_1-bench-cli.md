# Contract: `vllm_grpc_bench --m5_1` CLI

Operator-facing CLI for the M5.1 REST-vs-gRPC head-to-head sweep. Parallel to M5's `--m5` family; reuses M5 flags where the semantics are unchanged.

## Synopsis

```text
uv run python -m vllm_grpc_bench --m5_1 [options]
```

Triggering `--m5_1` puts the harness in M5.1 mode. M5/M4/M3 flags that are orthogonal to M5.1 (`--m3`, `--m4`, `--m5`, channel-axis selectors) MUST NOT be passed simultaneously; the CLI exits non-zero if it detects a conflict.

## Flags (M5.1-specific)

| Flag | Type | Default | Meaning |
|------|------|---------|---------|
| `--m5_1` | bool | off | Enter M5.1 mode. Without this, the M5.1 code path is dormant. |
| `--m5_1-modal-region` | str | `eu-west-1` | Modal region the dual-protocol app deploys to. Must be geographically distant from the local client so measured median RTT lands in 30–100 ms (FR-004). |
| `--m5_1-modal-token-env` | str | `MODAL_BENCH_TOKEN` | Name of the environment variable containing the bearer token. Token value is **never** logged or written to the report; only this env-var name is recorded. |
| `--m5_1-modal-endpoint` | str | None | Optional: skip deploy and use a pre-existing Modal endpoint (URL form: `grpc=tcp+plaintext://...,rest=https://...`). When set, `--m5_1-skip-deploy` is implied. |
| `--m5_1-skip-deploy` | bool | off | Skip the Modal deploy step and assume the endpoint at `--m5_1-modal-endpoint` is already up. Useful for re-running a sweep against an existing deployment. |
| `--m5_1-rtt-validity-threshold-ms` | float | `1.0` | Same-host-fallback threshold. Cohorts whose median RTT falls below this are refused a verdict (FR-004). |
| `--m5_1-rtt-exercise-threshold-ms` | float | `20.0` | Low-RTT-caveat threshold. Cohorts whose median RTT falls below this carry `low_rtt_caveat: true` (FR-004). |
| `--m5_1-warmup-n` | int | `20` | Number of warmup requests per (path × protocol) before measurement. Discarded; never counted toward recommend. |
| `--m5_1-shim-overhead-warn-pct` | float | `5.0` | If FastAPI shim overhead exceeds this fraction of any cohort's median wall-clock, attach a "shim plumbing was material" warning in the report. |
| `--m5_1-report-out` | path | `docs/benchmarks/m5_1-rest-vs-grpc.{md,json}` | Override the report output paths. |

Flags reused from M5 (unchanged semantics): `--bench-results-dir`, `--seed`, `--no-progress`.

## Behavior

1. Validate flag combinations; exit code 2 if any conflict.
2. Resolve the bearer token from `$MODAL_BENCH_TOKEN` (or the env var name given by `--m5_1-modal-token-env`). Exit code 4 if missing.
3. Validate `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` are set (or `~/.modal.toml` is readable). Exit code 4 if missing.
4. Deploy the dual-protocol Modal app via `modal_endpoint.provide_endpoint(variant="rest_grpc")` (or use `--m5_1-modal-endpoint` if `--m5_1-skip-deploy`). Print the two tunnel URLs (gRPC plain-TCP + REST HTTPS).
5. Probe RTT against both endpoints. Exit code 6 if either probe fails or median RTT falls below `--m5_1-rtt-validity-threshold-ms`.
6. Run warmup cohorts per protocol per path. Discard.
7. Enumerate the 18 matrix cells (2 paths × 3 widths × 3 concurrencies). For each cell, dispatch (in series): REST cohort → tuned-gRPC sub-cohort(s) → default-gRPC control. Apply M5's borderline-expand cascade per cohort.
8. Emit per-cell comparison verdicts via `m5_1_sweep.emit_cell_verdicts`.
9. Build the supersedes-M1-time table via `m5_1_supersede.build_supersedes_m1_time`.
10. Render Markdown + JSON reports via `reporter.write_m5_1_report`. Commit them to `docs/benchmarks/m5_1-rest-vs-grpc.{md,json}`.
11. Tear down the Modal app cleanly. Exit code 0.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Run completed successfully; report committed. |
| 2 | Flag conflict (e.g., `--m5_1` plus `--m4`). |
| 3 | Modal deploy failed. |
| 4 | Required credential missing (`$MODAL_BENCH_TOKEN`, `$MODAL_TOKEN_ID`, `$MODAL_TOKEN_SECRET`). |
| 6 | RTT validity check failed on either protocol (median RTT below `--m5_1-rtt-validity-threshold-ms`). |
| 7 | A cohort failed irrecoverably mid-sweep (e.g., FastAPI shim 5xx-storm on the REST side). Modal app is torn down before exit. |
| 8 | Report rendering failed (output paths not writable, JSON schema validation failed against M5 superset). |

## Examples

```bash
# Full M5.1 sweep, default region, default thresholds:
export MODAL_BENCH_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run python -m vllm_grpc_bench --m5_1

# Override region (US-east client → US-west Modal for higher RTT):
uv run python -m vllm_grpc_bench --m5_1 --m5_1-modal-region=us-west-2

# Reuse an existing endpoint (skip deploy):
uv run python -m vllm_grpc_bench --m5_1 \
    --m5_1-modal-endpoint='grpc=tcp+plaintext://abc.modal.host:50051,rest=https://abc.modal.host' \
    --m5_1-skip-deploy

# Lower the shim-overhead warning threshold to 1%:
uv run python -m vllm_grpc_bench --m5_1 --m5_1-shim-overhead-warn-pct=1.0
```
