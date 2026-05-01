# Contract: Benchmark Harness CLI

**Module**: `vllm_grpc_bench` (entry point: `python -m vllm_grpc_bench`)

---

## Invocation

```
python -m vllm_grpc_bench [OPTIONS]
```

---

## Required Arguments

| Flag | Type | Description |
|------|------|-------------|
| `--proxy-url URL` | `str` | Base URL of the proxy bridge endpoint |
| `--native-url URL` | `str` | Base URL of the native vLLM OpenAI endpoint |

---

## Optional Arguments

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--corpus PATH` | `Path` | `tools/benchmark/corpus/chat_nonstreaming.json` | Path to JSON corpus file |
| `--concurrency LEVELS` | `str` | `"1,4,8"` | Comma-separated list of concurrency levels |
| `--timeout SECONDS` | `float` | `30.0` | Per-request HTTP timeout |
| `--output-dir DIR` | `Path` | `./bench-results` | Directory where output files are written |
| `--compare-to PATH` | `Path` | *(none)* | Path to a baseline `results.json` for regression comparison |
| `--regression-threshold FLOAT` | `float` | `0.10` | Fractional threshold for flagging a regression (0.10 = 10%) |
| `--save-baseline PATH` | `Path` | *(none)* | If set, copies `results.json` to this path after the run |

---

## Subcommand: `compare`

```
python -m vllm_grpc_bench compare BASELINE_PATH NEW_RESULTS_PATH [--threshold FLOAT]
```

Compares two `results.json` files and prints a regression report to stdout. Exits with code `1` if any metric regresses beyond the threshold.

| Argument | Description |
|----------|-------------|
| `BASELINE_PATH` | Path to the committed baseline `results.json` |
| `NEW_RESULTS_PATH` | Path to the new run's `results.json` |
| `--threshold FLOAT` | Regression threshold (default `0.10`) |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Run completed successfully; no regressions (or `--compare-to` not specified) |
| `1` | Run completed; one or more metric regressions exceed the threshold |
| `2` | Usage error (bad arguments) |
| `3` | Runtime error (endpoint unreachable, corpus file missing, etc.) |

---

## Output Files

Written to `--output-dir`:

| File | Description |
|------|-------------|
| `results.json` | Full structured results (see `data-model.md` → `BenchmarkRun`) |
| `results.csv` | Flat CSV with one row per `(target, concurrency, request_id)` measurement |
| `summary.md` | Markdown table comparing proxy and native across all metrics and concurrency levels |

---

## Corpus JSON Format

The corpus is a JSON array of `RequestSample` objects:

```json
[
  {
    "id": "sample-001",
    "messages": [{"role": "user", "content": "Say hello in one word."}],
    "model": "Qwen/Qwen3-0.6B",
    "max_tokens": 10,
    "temperature": 0.0,
    "seed": 42
  }
]
```

Each `RequestSample` is serialized verbatim as the HTTP request body to `POST /v1/chat/completions`.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BENCH_PROXY_URL` | *(none)* | Fallback for `--proxy-url` if flag not provided |
| `BENCH_NATIVE_URL` | *(none)* | Fallback for `--native-url` if flag not provided |
