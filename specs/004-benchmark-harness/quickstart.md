# Quickstart: Benchmark Harness

**Phase 4 — Metrics and Benchmark Harness**

---

## Prerequisites

- Phase 3 bridge is working: `make check` passes, `make run-proxy` and `make run-frontend` start successfully.
- `uv sync --all-packages` has been run (workspace includes `tools/benchmark`).
- For live benchmarks: vLLM is available locally (either `vllm-metal` or CPU vLLM) and the model `Qwen/Qwen3-0.6B` has been downloaded.

---

## 1. Run a Live Head-to-Head Benchmark

Start both servers in separate terminals:

```bash
# Terminal 1 — vLLM native OpenAI server (port 8001)
uv run --with vllm python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen3-0.6B --port 8001

# Terminal 2 — frontend (port 50051)
make run-frontend

# Terminal 3 — proxy bridge (port 8000)
make run-proxy
```

Then in a fourth terminal:

```bash
make bench
```

This runs the harness against both endpoints and writes reports to `bench-results/`:

```
bench-results/
├── results.json    # structured measurements
├── results.csv     # flat table (importable into spreadsheets)
└── summary.md      # markdown comparison table
```

View the summary:

```bash
cat bench-results/summary.md
```

---

## 2. Commit the Phase 3 Baseline

After confirming the results look reasonable:

```bash
# Save the real-run baseline
cp bench-results/results.json docs/benchmarks/phase-3-baseline.json
cp bench-results/summary.md docs/benchmarks/phase-3-baseline.md

# Commit
git add docs/benchmarks/phase-3-baseline.json docs/benchmarks/phase-3-baseline.md
git commit -m "Add Phase 3 non-streaming benchmark baseline"
```

---

## 3. Run the CI Smoke Test Locally

The CI smoke test uses stub HTTP servers instead of a live model. To run it locally:

```bash
make bench-ci
```

This starts two `FakeHTTPServer` instances (serving pre-recorded responses), runs the harness against them, and writes results to `bench-ci-results/`. No live model is needed.

To commit the CI baseline (run once after Phase 3 baseline is established):

```bash
cp bench-ci-results/results.json docs/benchmarks/phase-3-ci-baseline.json
git add docs/benchmarks/phase-3-ci-baseline.json
git commit -m "Add Phase 3 CI stub benchmark baseline"
```

---

## 4. Compare Results Against a Baseline

To check for regressions against the real baseline:

```bash
make bench-compare BASELINE=docs/benchmarks/phase-3-baseline.json RESULTS=bench-results/results.json
```

Or using the harness directly:

```bash
python -m vllm_grpc_bench compare \
  docs/benchmarks/phase-3-baseline.json \
  bench-results/results.json \
  --threshold 0.10
```

Exit code `0` means no regressions. Exit code `1` means at least one metric degraded > 10%.

---

## 5. Understand the Report

The `summary.md` contains a comparison table with these columns:

| Metric | Proxy | Native | Δ |
|--------|-------|--------|---|
| Latency P50 (ms) @ concurrency=1 | … | … | … |
| Latency P95 (ms) @ concurrency=1 | … | … | … |
| … | | | |

**Δ** is `(proxy − native) / native`. Negative values mean the proxy is **faster** than native; positive values mean it is **slower**. A value of `0.00` means they are equivalent.

The `proxy_ms` rows show the proxy's internal translation time only (excludes gRPC/model time). This appears only for the proxy target; it is absent for native.

---

## 6. Add a New Metric

To add a new measurement to the harness (e.g., time-to-first-token for Phase 5):

1. **Add the field to `RequestResult`** in `tools/benchmark/src/vllm_grpc_bench/metrics.py`. Make it `float | None` and default to `None`.

2. **Populate it in `runner.py`**: Inside the request-send loop, compute the new value from the response and assign it to the field on the `RequestResult` you're building.

3. **Add aggregation to `RunSummary`** in `metrics.py`: Add a corresponding field (e.g., `ttft_p50_ms`) and compute it from the `RequestResult` list using `_percentile()`.

4. **Add it to the CSV writer** in `reporter.py`: Add the field name to the `fieldnames` list passed to `csv.DictWriter`.

5. **Add it to the markdown table** in `reporter.py`: Add a row in the `_build_summary_table()` function.

6. **Write a test** in `tools/benchmark/tests/test_metrics.py` verifying the new field is computed correctly.

7. **Update `docs/benchmarks/` methodology note** if the new metric changes the documented measurement approach.

No changes to `compare.py` or `__main__.py` are needed — comparison is driven dynamically from the fields present in both result files.

---

## Make Targets Reference

| Target | Description |
|--------|-------------|
| `make bench` | Live head-to-head benchmark (requires both servers running) |
| `make bench-ci` | CI smoke test with stub servers (no live model) |
| `make bench-compare BASELINE=… RESULTS=…` | Compare two result files |

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `ConnectionRefusedError` on proxy or native | Server not running | Start the required server first |
| All results show `success: false` | Wrong port or endpoint path | Check `--proxy-url` / `--native-url` match running servers |
| `proxy_ms` is `None` for all proxy requests | Proxy middleware not installed | Ensure `bench_middleware.py` is wired into the proxy `main.py` |
| CI benchmark is slow (>60s) | FakeHTTPServer delay too high | Check `FAKE_DELAY_MS` env var; default is 5ms |
