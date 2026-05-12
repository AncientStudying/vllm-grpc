# Contract: `vllm_grpc_bench --m5_2` CLI

Operator-facing CLI for the M5.2 REST transport path × gRPC tuning surface sweep. Parallel to M5.1's `--m5_1` family; reuses M5.1 flags where the semantics are unchanged.

## Synopsis

```text
uv run python -m vllm_grpc_bench --m5_2 [options]
uv run python -m vllm_grpc_bench --m5_2 --m5_2-smoke [options]
```

Triggering `--m5_2` puts the harness in M5.2 mode. M5.1 / M5 / M4 / M3 flags that are orthogonal to M5.2 (`--m3`, `--m4`, `--m5`, `--m5_1`, channel-axis selectors) MUST NOT be passed simultaneously; the CLI exits with code 2 if it detects a conflict.

`--m5_2-smoke` is a shortcut that puts M5.2 mode into pre-flight smoke gating posture per FR-005a — same codepath as `--m5_2` but with reduced cell coverage (`chat_stream c=1`, `chat_stream c=4`, `embed c=4`, `embed c=1`), reduced per-cohort `n` (5 measurement + 2 warmup), and an extended assertion surface invoked before cohorts dispatch (both REST transports reach the same Modal deploy; M5.2-additive JSON schema fields round-trip; per-cohort RTT probe within thresholds for all five cohorts). MUST be run before `--m5_2` (operator discipline; the harness does not enforce ordering, but SC-012 makes the smoke outcome a PR-description requirement).

## Flags (M5.2-specific)

| Flag | Type | Default | Meaning |
|------|------|---------|---------|
| `--m5_2` | bool | off | Enter M5.2 mode. Without this, the M5.2 code path is dormant. |
| `--m5_2-smoke` | bool | off | Pre-flight smoke gate (FR-005a). Runs the 4-cell smoke set + M5.2-specific assertions; exits with code 0 on pass / code 6 on assertion failure. Required to be passing before `--m5_2` is run for the full sweep. |
| `--m5_2-modal-region` | str | `eu-west-1` | Modal region the dual-protocol app deploys to (matches M5.1's default). Must be geographically distant from the local client so plain-TCP median RTT lands in 30–100 ms (FR-004). |
| `--m5_2-modal-token-env` | str | `MODAL_BENCH_TOKEN` | Name of the environment variable containing the bearer token. Token value is **never** logged or written to the report; only the env-var name is recorded. |
| `--m5_2-modal-endpoint` | str | None | Optional: skip deploy and use a pre-existing Modal endpoint (URL form: `grpc=tcp+plaintext://...,rest_https_edge=https://...,rest_plain_tcp=tcp+plaintext://...`). When set, `--m5_2-skip-deploy` is implied. |
| `--m5_2-skip-deploy` | bool | off | Skip the Modal deploy step and assume the endpoint at `--m5_2-modal-endpoint` is already up. Useful for re-running a sweep against an existing deployment (e.g., after a transient cohort failure). |
| `--m5_2-n` | int | `250` | Per-cohort sample size for the full sweep (FR-011). The borderline-expand cascade does NOT expand beyond this value in M5.2 — n=250 is the resolution increase M5.2 is paying for. |
| `--m5_2-warmup-n` | int | `20` | Number of warmup requests per (path × protocol-side) before measurement. Discarded; never counted toward recommend. |
| `--m5_2-rtt-validity-threshold-ms` | float | `1.0` | Same-host-fallback threshold. Cohorts whose median RTT falls below this are refused a verdict (FR-004). |
| `--m5_2-rtt-exercise-threshold-ms` | float | `20.0` | Low-RTT-caveat threshold. Cohorts whose median RTT falls below this carry `low_rtt_caveat: true` (FR-004). |
| `--m5_2-shim-overhead-warn-pct` | float | `5.0` | If FastAPI shim overhead exceeds this fraction of any cohort's median wall-clock, attach a "shim plumbing was material" warning in the report (matches M5.1). |
| `--m5_2-events-sidecar-out` | path | `bench-results/m5_2-full/{run_id}.events.jsonl.gz` | Override the gzipped events sidecar output path. The Phase-K1 narrative-summary commit copies this to `docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz`. |
| `--m5_2-report-out` | path | `docs/benchmarks/m5_2-transport-vs-tuning.{md,json}` | Override the report output paths. (Set by the regenerator, not the sweep itself — the sweep emits only the sidecar + run config per FR-012b.) |
| `--m5_2-skip-geolocation-lookup` | bool | off | Skip the best-effort `https://ipinfo.io/json` client-geolocation lookup at run start; tier (c) records `client_external_geolocation: null`. Useful in air-gapped / locked-down environments. |

Flags reused from M5/M5.1 (unchanged semantics): `--bench-results-dir`, `--seed`, `--no-progress`.

## Behavior — `--m5_2-smoke`

1. Validate flag combinations; exit code 2 if any conflict.
2. Resolve the bearer token from `$MODAL_BENCH_TOKEN` (or the env var name given by `--m5_2-modal-token-env`). Exit code 4 if missing.
3. Validate `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` are set (or `~/.modal.toml` is readable). Exit code 4 if missing.
4. Deploy the dual-protocol Modal app (or use `--m5_2-modal-endpoint` if `--m5_2-skip-deploy`). Print the three tunnel URLs (gRPC plain-TCP + REST HTTPS-edge + REST plain-TCP).
5. **Smoke-specific assertions** invoked BEFORE cohort dispatch:
    - `assert_both_rest_transports_reach_same_modal_deploy`: GET `/healthz` from both REST transports; assert identical response body + identical `modal_deploy_handle` header.
    - `assert_m5_2_json_schema_round_trips`: write M5.2-additive fields per FR-013 to a temp aggregate JSON; read them back; assert equivalence.
    - `assert_per_cohort_rtt_probe_within_thresholds_all_five_cohorts`: per-cohort RTT probe returns within `--m5_2-rtt-validity-threshold-ms` thresholds for all five cohorts (rest_https_edge, rest_plain_tcp, default_grpc, tuned_grpc_multiplexed, tuned_grpc_channels — at c=1 the two tuned cohorts collapse to tuned_grpc per FR-006).
6. Run the 4-cell smoke (`chat_stream c=1`, `chat_stream c=4`, `embed c=4`, `embed c=1`) with `n=5` measurement + `n=2` warmup per cohort.
7. Emit the smoke's events sidecar (gzipped) + smoke aggregate JSON + smoke markdown.
8. Tear down the Modal app.
9. Print a structured `M5_2 smoke gate: PASS — <timestamp>, <asserted_clauses_count>, per-cohort RTT medians (ms): rest_https_edge=<...>, rest_plain_tcp=<...>, default_grpc=<...>, tuned_grpc_*=<...>` line that the operator copy-pastes into the PR description per SC-012. Exit code 0.
10. On any assertion failure: print `M5_2_SmokeAssertionFailure: <which assertion>, <diverging field>, <observed vs expected>`. Tear down the Modal app. Exit code 6.

## Behavior — `--m5_2` (full sweep)

1. Validate flag combinations; exit code 2 if any conflict.
2. Resolve the bearer token (exit code 4 if missing).
3. Validate Modal credentials (exit code 4 if missing).
4. Deploy the dual-protocol Modal app (or skip per `--m5_2-skip-deploy`).
5. Build the 3-tier symmetry block via `m5_2_symmetry.build_symmetry_block`.
6. Invoke `m5_2_symmetry.assert_symmetry(block, concurrency_levels=[1, 4, 8])`. Exit code 5 on tier (a) or tier (b) divergence with the diverging field + cohort/pair named in stderr.
7. Probe RTT against all four endpoints (gRPC plain-TCP + REST HTTPS-edge + REST plain-TCP + healthz on the shim via each transport). Exit code 6 if any probe fails or median RTT falls below `--m5_2-rtt-validity-threshold-ms`.
8. Run warmup cohorts per protocol-side per path. Discard. Per-request warmup records are persisted to the sidecar with `phase: "warmup"` for audit but excluded from aggregates.
9. Enumerate the 18 matrix cells (2 paths × 3 widths × 3 concurrencies). For each cell, dispatch (in series, per R-4 / M5.1 R-4): rest_https_edge → rest_plain_tcp → default_grpc → tuned_grpc_multiplexed (c≥2 only) → tuned_grpc_channels (c≥2 only) → tuned_grpc (c=1 only). Per-request events written to the sidecar at issue + done time. Apply M5.1's borderline-expand cascade per cohort (but the cascade does NOT expand beyond `--m5_2-n` = 250 in M5.2 per FR-011).
10. On full-sweep completion: close the events sidecar (gzip + SHA-256 + emit final path + checksum).
11. Emit the M5.2 run config JSON (`bench-results/m5_2-full/{run_id}.run_config.json`) containing the symmetry block, the events sidecar path + SHA-256, the smoke-run-outcome metadata (the operator's previous `--m5_2-smoke` output is included by reference — recorded in the run config), the modal region/instance class, and the run's `run_started_at_iso` / `run_realized_runtime_s`. The harness MUST NOT emit markdown or aggregate JSON directly (FR-012b).
12. Tear down the Modal app cleanly. Exit code 0.

The operator then invokes the regenerator per the contract in `contracts/m5_2-regenerator.md` to produce the markdown + aggregate JSON from the sidecar + run config.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Run completed successfully (smoke pass / full sweep + sidecar emit). |
| 2 | Flag conflict (e.g., `--m5_2` plus `--m5_1`, or `--m5_2-skip-deploy` without `--m5_2-modal-endpoint`). |
| 3 | Modal deploy failed. |
| 4 | Required credential missing (`$MODAL_BENCH_TOKEN`, `$MODAL_TOKEN_ID`, `$MODAL_TOKEN_SECRET`). |
| 5 | Symmetry assertion failed (tier (a) or tier (b) divergence). Diverging field + cohort/pair named in stderr. |
| 6 | RTT validity check or smoke-specific assertion failed. Modal app is torn down before exit. |
| 7 | A cohort failed irrecoverably mid-sweep (e.g., FastAPI shim 5xx-storm on one of the REST transports). The events sidecar is closed and gzipped before exit; partial-cohort failure records are cell-level `comparison_unavailable` per FR-005. Modal app is torn down. |
| 8 | Events sidecar write failed (disk full, permission denied) or SHA-256 computation failed. |

## Examples

```bash
# Step 1 — run the smoke gate first (per SC-012):
export MODAL_BENCH_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run python -m vllm_grpc_bench --m5_2 --m5_2-smoke
# Copy the "M5_2 smoke gate: PASS" line into the PR description.

# Step 2 — run the full M5.2 sweep at n=250:
uv run python -m vllm_grpc_bench --m5_2 --m5_2-modal-region=eu-west-1

# Step 3 — produce the markdown + aggregate JSON from the sidecar:
uv run python scripts/python/regen_bench_reports.py \
    --m5_2-sidecar bench-results/m5_2-full/{run_id}.events.jsonl.gz \
    --m5_2-run-config bench-results/m5_2-full/{run_id}.run_config.json

# Override region (US-east client → US-west Modal for higher RTT):
uv run python -m vllm_grpc_bench --m5_2 --m5_2-modal-region=us-west-2

# Reuse an existing endpoint (skip deploy):
uv run python -m vllm_grpc_bench --m5_2 \
    --m5_2-modal-endpoint='grpc=tcp+plaintext://abc.modal.host:50051,rest_https_edge=https://abc-shim.modal.run,rest_plain_tcp=tcp+plaintext://abc-shim-tcp.modal.host:8000' \
    --m5_2-skip-deploy

# Air-gapped: skip the geolocation lookup:
uv run python -m vllm_grpc_bench --m5_2 --m5_2-skip-geolocation-lookup
```
