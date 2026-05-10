# M5 Quickstart — reproducing the cross-host validation sweep

This is the minimal recipe a contributor follows to reproduce the M5 measurements end-to-end. The harness handles Modal deploy, sweep, and teardown in a single CLI invocation (per SC-005). It assumes you've already cloned the repo and installed the workspace (`uv sync`).

## Prerequisites

- macOS Apple Silicon (M2/M3) or Linux x86-64 (local client).
- Python 3.12 (managed by `uv`).
- `make` and `protoc` on `PATH`.
- Modal CLI authentication. Either:
  - `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` set in the environment, OR
  - `~/.modal.toml` populated via `modal token new` (the standard Modal CLI flow).
- A Modal workspace where you have permission to create CPU-only apps and TCP-tunnels. The project's existing workspace satisfies this.
- ~1–3 hours of mostly-idle bandwidth on the local client (the sweep is RTT-bounded; CPU load on the local client is light).
- (Optional) the cross-repo graph at `cross-repo.json`, refreshed via `/ground-truth-refresh` if the lockfile pins have changed.

## One-time setup

```bash
# Generate a per-run bearer token (used for application-level auth on the gRPC server).
export MODAL_BENCH_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"

# (Optional, if you haven't done this for any earlier milestone.) Regenerate proto stubs.
make proto
```

The bearer token MUST be set before the harness is invoked; the harness does NOT generate it (so the token is auditable and re-runs against the same Modal app within its lifetime work).

## Run the full M5 sweep

```bash
# Full sweep — US1 cross-host channel sweep + US2 cross-host schema candidates + US3 supersession reporting.
# Default flags: --m5-modal-region=auto-far (resolves to us-east-1 unless overridden)
#                --m5-rtt-validity-threshold-ms=1.0
#                --m5-rtt-exercise-threshold-ms=20.0
#                --m5-warmup-n=32
#                --baseline-n=100 --candidate-n=100 --expand-n=250 --baseline-cv-warn=0.10
uv run python -m vllm_grpc_bench --m5 --m5-modal-region=eu-west-1
```

**Operators in `us-east-1`**: the default `--m5-modal-region=auto-far` resolves to `us-east-1`, which produces sub-20 ms RTT from your local client. The harness will run to completion but every cohort will carry `low_rtt_caveat: true` and the executive summary will surface a warning. Pass `--m5-modal-region=eu-west-1` (or `ap-southeast-1`) to land in the 30–100 ms target band.

The run writes:

- `bench-results/m5-full/per-iteration/*.json` — transient per-iteration timings (gitignored).
- `docs/benchmarks/m5-cross-host-validation.json` — the published JSON (strict-superset of `m4-time-axis-tuning.json`).
- `docs/benchmarks/m5-cross-host-validation.md` — the human-readable companion.

stdout summary:

```text
M5 sweep complete: <N> recommend, <M> no_winner, <K> client_bound, <L> server_bound. <P> M4 cells superseded (<Q> verdict-changed, <R> verdict-confirmed). RTT median <X> ms across <C> cohorts.
```

If the executive summary's reported RTT median is below 20 ms, re-run with a farther region — the low-RTT-caveat verdicts are recorded but they do not resolve M4's loopback caveat (SC-001).

## Iterating while developing

```bash
# Harness-mechanics unit tests (no Modal contact required):
uv run pytest tools/benchmark/tests/test_m5_sweep.py tools/benchmark/tests/test_rtt_probe.py tools/benchmark/tests/test_m5_supersede.py -q

# Modal-smoke integration test (deploys a tiny Modal app, runs one 10-iteration cohort, tears down):
MODAL_BENCH_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  uv run pytest tests/integration/test_m5_modal_smoke.py -q

# US1 only (skip schema candidates while iterating on the channel sweep):
uv run python -m vllm_grpc_bench --m5 --m5-modal-region=eu-west-1 --skip-schema

# Re-run against a long-running Modal app you've already deployed by hand:
uv run python -m vllm_grpc_bench --m5 --m5-skip-deploy --m5-modal-endpoint=r3.modal.host:54321
```

## Failure modes and re-runs

| Exit code | Meaning | Action |
|-----------|---------|--------|
| `2` | Pre-flight validation failed (token env var unset, flag conflict). | Fix the flag / env var and re-run. No Modal app deployed. |
| `3` | Modal deploy / handshake failed. | Check Modal credentials and workspace quota; re-run. No teardown needed. |
| `6` | Remote host unavailable mid-run. | Re-run from scratch (partial cohorts discarded per Edge Cases). Teardown attempted automatically. |
| `7` | Bearer-token rejection during sweep. | Confirm no other client is hitting the deployed Modal app; re-run with a fresh token. Teardown attempted automatically. |
| `8` | RTT validity check failed (shared-baseline median RTT < 1 ms). | Connection unexpectedly resolved to same-host route. Investigate (likely a Modal misconfiguration); re-run. Teardown attempted automatically. |

The harness logs the teardown attempt's outcome to stderr on every non-zero exit, so you can verify no orphaned Modal app remains. To check manually:

```bash
modal app list | grep vllm-grpc-bench-mock
modal app stop vllm-grpc-bench-mock  # if any orphan is listed
```

## Cost expectation

A typical successful run on Modal CPU-only instance class costs well under one Modal CPU-instance-hour-class (~$0.10–$0.30 per run). The container runs for the duration of the sweep (1–3 hours typical, 8 hours generous-budget). The local client uses negligible CPU; the bandwidth used is small (cohort iterations are short proto messages, ~10 KB/iter for embed at hidden_size=4096, smaller for chat_stream).

## Reading the report

The Markdown companion is the primary reader-facing artifact. The section ordering is:

1. **Methodology preamble** — cross-host topology, measured RTT distribution, Modal region.
2. **Channel-sweep verdict table** — per axis × hidden_size × path, M5 verdict and supporting CIs.
3. **Frozen-channel baselines** — per-path winners that anchor the schema sweep.
4. **Schema-candidate verdicts** — per candidate at the canonical width (and cascaded widths where applicable).
5. **Supersedes M4 table** — every M4 cell M5 supersedes, with verdict-changed rows visually distinguished (per SC-004).
6. **Negative results appendix** — schema candidates with no measurable effect.
7. **Executive summary footer** — run wall-clock, total cohort count, server_bound count, RTT range, region.

Readers wanting a single-glance comparison between M4 and M5 should jump to section 5; the supersession table is the answer to "did M5 change anything M4 said."
