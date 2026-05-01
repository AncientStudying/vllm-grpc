# Data Model: Metrics and Benchmark Harness (Phase 4)

**Branch**: `004-benchmark-harness` | **Date**: 2026-05-01

---

## Entities

### BenchmarkConfig

Configuration for a single benchmark run. Derived from CLI arguments.

| Field | Type | Description |
|-------|------|-------------|
| `proxy_url` | `str` | Base URL of the proxy bridge endpoint (e.g., `http://localhost:8000`) |
| `native_url` | `str` | Base URL of the native vLLM OpenAI server (e.g., `http://localhost:8001`) |
| `corpus_path` | `Path` | Path to the JSON corpus file |
| `concurrency_levels` | `list[int]` | Concurrency levels to test (default: `[1, 4, 8]`) |
| `timeout_seconds` | `float` | Per-request timeout (default: `30.0`) |
| `output_dir` | `Path` | Directory where report files are written |
| `compare_to` | `Path \| None` | Path to a baseline JSON file for comparison (optional) |
| `regression_threshold` | `float` | Fractional threshold for regression detection (default: `0.10`) |

---

### RequestSample

One item in the benchmark corpus. Loaded from `corpus/chat_nonstreaming.json`.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique identifier for the sample (e.g., `"sample-001"`) |
| `messages` | `list[dict]` | List of `{"role": ..., "content": ...}` dicts matching OpenAI format |
| `model` | `str` | Model name to request (e.g., `"Qwen/Qwen3-0.6B"`) |
| `max_tokens` | `int` | Maximum tokens to generate (default: `10` to cap inference time) |
| `temperature` | `float` | Sampling temperature; `0.0` for determinism |
| `seed` | `int` | Random seed for reproducibility |

Serialized to JSON and sent as the HTTP request body verbatim.

---

### RequestResult

Measurements for a single request sent to a single endpoint.

| Field | Type | Description |
|-------|------|-------------|
| `sample_id` | `str` | ID of the `RequestSample` that produced this result |
| `target` | `Literal["proxy", "native"]` | Which endpoint was called |
| `concurrency` | `int` | Concurrency level active during this request |
| `latency_ms` | `float \| None` | Wall-clock time from request sent to response received, in milliseconds; `None` on error |
| `request_bytes` | `int` | Byte length of the UTF-8 encoded HTTP request body |
| `response_bytes` | `int \| None` | Byte length of the UTF-8 encoded HTTP response body; `None` on error |
| `proxy_ms` | `float \| None` | Proxy translation time from `X-Bench-Proxy-Ms` header; `None` if absent or on error |
| `success` | `bool` | `True` if HTTP 2xx was returned; `False` otherwise |
| `error` | `str \| None` | Error message if `success` is `False`; `None` otherwise |

---

### RunSummary

Aggregated statistics for all `RequestResult` objects sharing the same `target` and `concurrency` level.

| Field | Type | Description |
|-------|------|-------------|
| `target` | `Literal["proxy", "native"]` | Which endpoint |
| `concurrency` | `int` | Concurrency level |
| `n_requests` | `int` | Total requests issued |
| `n_errors` | `int` | Requests that returned a non-2xx response |
| `latency_p50_ms` | `float \| None` | 50th-percentile latency; `None` if all requests errored |
| `latency_p95_ms` | `float \| None` | 95th-percentile latency |
| `latency_p99_ms` | `float \| None` | 99th-percentile latency |
| `throughput_rps` | `float \| None` | Completed requests per second at this concurrency level |
| `request_bytes_mean` | `float` | Mean request body bytes |
| `response_bytes_mean` | `float \| None` | Mean response body bytes; `None` if all requests errored |
| `proxy_ms_p50` | `float \| None` | 50th-percentile proxy translation time; `None` if header absent |
| `proxy_ms_p95` | `float \| None` | 95th-percentile proxy translation time |
| `proxy_ms_p99` | `float \| None` | 99th-percentile proxy translation time |

---

### BenchmarkRun

Top-level container for a complete benchmark execution. This is the structure persisted to `results.json`.

| Field | Type | Description |
|-------|------|-------------|
| `meta` | `RunMeta` | Run metadata (see below) |
| `summaries` | `list[RunSummary]` | One `RunSummary` per `(target, concurrency)` combination |
| `raw_results` | `list[RequestResult]` | All individual request results |

#### RunMeta (nested in BenchmarkRun)

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | `str` | ISO-8601 timestamp of run start |
| `git_sha` | `str` | Git commit SHA at time of run (from `git rev-parse HEAD`) |
| `hostname` | `str` | Machine hostname |
| `corpus_path` | `str` | Relative path to the corpus file used |
| `concurrency_levels` | `list[int]` | Concurrency levels tested |
| `proxy_url` | `str` | Proxy endpoint URL |
| `native_url` | `str` | Native endpoint URL |

---

### ComparisonReport

Output of comparing a new `BenchmarkRun` against a committed baseline run.

| Field | Type | Description |
|-------|------|-------------|
| `baseline_path` | `str` | Path to the baseline JSON file |
| `new_run_path` | `str` | Path to the new results JSON file |
| `regressions` | `list[RegressionEntry]` | List of metrics that exceed the regression threshold |
| `has_regression` | `bool` | `True` if `regressions` is non-empty |
| `threshold` | `float` | The regression threshold used (e.g., `0.10` for 10%) |

#### RegressionEntry (nested in ComparisonReport)

| Field | Type | Description |
|-------|------|-------------|
| `metric` | `str` | Human-readable metric name (e.g., `"proxy latency_p95 @ concurrency=4"`) |
| `target` | `str` | `"proxy"` or `"native"` |
| `concurrency` | `int` | Concurrency level |
| `baseline_value` | `float` | Baseline measurement |
| `new_value` | `float` | New measurement |
| `delta_pct` | `float` | Fractional change: `(new - baseline) / baseline` |

---

## State Transitions

The benchmark harness has no persistent state across runs. The only durable artifacts are:

1. **Corpus** (`tools/benchmark/corpus/*.json`): Static input fixtures. Never modified at runtime.
2. **Results** (`output_dir/results.json`, `results.csv`, `summary.md`): Written once per run, never updated in place.
3. **Baseline** (`docs/benchmarks/*.json`): Written by a developer after a successful local run; committed to the repository. Read-only from the harness's perspective.

---

## Module → Entity Mapping

| Module | Owns / Produces |
|--------|----------------|
| `corpus.py` | Loads `RequestSample` list from JSON file |
| `runner.py` | Produces `RequestResult` objects |
| `metrics.py` | Aggregates `RequestResult` → `RunSummary`; computes `RunMeta` |
| `reporter.py` | Consumes `BenchmarkRun` → writes `results.json`, `results.csv`, `summary.md` |
| `compare.py` | Consumes two `BenchmarkRun` objects → produces `ComparisonReport` |
| `__main__.py` | Orchestrates all modules; owns `BenchmarkConfig` |
