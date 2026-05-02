# Quickstart: Phase 4.1 — Real Comparative Baselines (Modal)

**Branch**: `007-modal-real-baselines` | **Date**: 2026-05-02

This guide walks through running `make bench-modal` from scratch and committing
the resulting baseline files.

---

## Prerequisites

1. Modal token configured:
   ```bash
   modal token new   # or: modal token set --token-id ... --token-secret ...
   ```

2. Model weights pre-staged (if not already done from Phase 3.1):
   ```bash
   make download-weights
   ```

3. Workspace synced:
   ```bash
   make bootstrap
   ```

---

## Step 1: Run the full benchmark

```bash
make bench-modal
```

Expected output (abridged):

```
[REST] Spawning Modal REST serve function...
[REST] Waiting for REST tunnel address...
[REST] Tunnel address: tcp://XYZ.modal.run:12345
[REST] Running harness (concurrency=1,4,8)...
[REST] REST run complete. Tearing down REST deployment.

[gRPC] Spawning Modal gRPC serve function...
[gRPC] Waiting for gRPC tunnel address...
[gRPC] Tunnel address: tcp://ABC.modal.run:54321
[gRPC] Starting local proxy on :8000 → ABC.modal.run:54321
[gRPC] Running harness (concurrency=1,4,8)...
[gRPC] gRPC run complete. Stopping proxy. Tearing down gRPC deployment.

[COMPARE] Generating comparison report...

Results written:
  bench-results/results-rest.json
  bench-results/results-grpc.json
  docs/benchmarks/phase-3-modal-rest-baseline.json
  docs/benchmarks/phase-3-modal-rest-baseline.md
  docs/benchmarks/phase-3-modal-grpc-baseline.json
  docs/benchmarks/phase-3-modal-grpc-baseline.md
  docs/benchmarks/phase-3-modal-comparison.md
```

Total wall-clock time: ~15–30 minutes (dominated by two cold starts of ~5 min each
plus harness runs of ~5 min each at concurrency 1,4,8 × 10 samples).

---

## Step 2: Review the comparison report

```bash
cat docs/benchmarks/phase-3-modal-comparison.md
```

The report shows P50/P95/P99 latency, wire bytes per request/response, and
throughput for REST vs gRPC at each concurrency level. Verify:
- All metrics have values (no `—` entries unless expected)
- Cold-start is visible in the metadata section but not in per-request latency
- The model version and GPU type are recorded

---

## Step 3: Re-run the offline compare (optional)

Useful if you want to regenerate the report after editing the formatter:

```bash
python -m vllm_grpc_bench compare-cross \
  --result-a docs/benchmarks/phase-3-modal-rest-baseline.json \
  --result-b docs/benchmarks/phase-3-modal-grpc-baseline.json \
  --label-a REST --label-b gRPC \
  --output docs/benchmarks/phase-3-modal-comparison.md
```

Completes in under 30 seconds. No Modal or network access required.

---

## Step 4: Commit the baselines

```bash
git add docs/benchmarks/phase-3-modal-rest-baseline.json \
        docs/benchmarks/phase-3-modal-rest-baseline.md \
        docs/benchmarks/phase-3-modal-grpc-baseline.json \
        docs/benchmarks/phase-3-modal-grpc-baseline.md \
        docs/benchmarks/phase-3-modal-comparison.md
git commit -m "Phase 4.1: commit real Modal REST + gRPC baselines"
```

---

## Verifying CI passes

After committing the baselines, the CI job uses them for regression detection on
future PRs. To verify the check works locally:

```bash
# Simulate a CI regression check (should exit 0 — baseline vs itself):
python -m vllm_grpc_bench compare \
  docs/benchmarks/phase-3-modal-rest-baseline.json \
  docs/benchmarks/phase-3-modal-rest-baseline.json
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `Waiting for REST tunnel address...` hangs | Modal cold start > 600 s | Increase `_ADDR_POLL_TIMEOUT_S` constant in `bench_modal.py`; retry |
| Harness exits with code 3 | Tunnel dropped before harness finished | Retry; check Modal dashboard for function logs |
| Proxy subprocess exits immediately | `FRONTEND_ADDR` already in use or wrong address format | Check harness output; verify gRPC tunnel address |
| `compare_cross` fails with schema error | Old result file schema vs new `RunMeta` fields | Ensure both result files were produced by this phase's code |
| CI regression check fails on new PR | A metric regressed beyond 10% threshold | Investigate the regression; update baseline only if change is intentional |
