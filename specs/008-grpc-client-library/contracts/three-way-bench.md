# Contract: Three-Way Benchmark Comparison

## Scope

Changes to `tools/benchmark/src/vllm_grpc_bench/` and `scripts/python/bench_modal.py` required to produce three-way REST / gRPC-via-proxy / gRPC-direct comparisons.

---

## metrics.py — New Dataclasses

### ThreeWayRow

```python
@dataclass
class ThreeWayRow:
    metric:      str           # e.g. "latency_p50_ms"
    concurrency: int
    value_a:     float | None  # REST
    value_b:     float | None  # gRPC-via-proxy
    value_c:     float | None  # gRPC-direct
    delta_pct_b: float | None  # (b - a) / a * 100; None if either is None or a == 0
    delta_pct_c: float | None  # (c - a) / a * 100; None if either is None or a == 0
```

### ThreeWayReport

```python
@dataclass
class ThreeWayReport:
    label_a: str              # e.g. "REST"
    label_b: str              # e.g. "gRPC-proxy"
    label_c: str              # e.g. "gRPC-direct"
    rows:    list[ThreeWayRow]
    meta_a:  RunMeta
    meta_b:  RunMeta
    meta_c:  RunMeta
```

---

## compare.py — New Function

```python
def compare_three_way(
    run_a:    BenchmarkRun,
    run_b:    BenchmarkRun,
    run_c:    BenchmarkRun,
    label_a:  str = "REST",
    label_b:  str = "gRPC-proxy",
    label_c:  str = "gRPC-direct",
) -> ThreeWayReport
```

Metrics covered (same set as `compare_cross`): `latency_p50_ms`, `latency_p95_ms`, `latency_p99_ms`, `throughput_rps`, `request_bytes_mean`, `response_bytes_mean`.

---

## reporter.py — New Function

```python
def write_three_way_md(report: ThreeWayReport, path: Path) -> None
```

Writes a markdown table with columns: `metric | concurrency | {label_a} | {label_b} | Δ vs {label_a} | {label_c} | Δ vs {label_a}`. Does not write the file if the report is empty.

---

## __main__.py — New Subcommand

```
python -m vllm_grpc_bench compare-three-way \
    --result-a PATH \   # required; JSON from a REST run
    --result-b PATH \   # required; JSON from a gRPC-proxy run
    --result-c PATH \   # required; JSON from a gRPC-direct run
    [--label-a LABEL]   # default: "rest"
    [--label-b LABEL]   # default: "grpc-proxy"
    [--label-c LABEL]   # default: "grpc-direct"
    [--output PATH]     # optional; prints to stdout if omitted
```

Follows the same validation and error-reporting pattern as `compare-cross`. Exits non-zero if any result file is missing or unparseable.

---

## bench_modal.py — Orchestration Extension

### New constant

```python
_GRPC_DIRECT_RESULTS = _RESULTS_DIR / "phase-4.2-grpc-direct-raw.json"
```

### Revised orchestration order

```
1. REST phase
   ├── spawn_rest_for_bench()   — Modal REST deployment
   ├── run REST harness         — writes _REST_RESULTS
   └── stop REST deployment

2. gRPC phase  (single Modal deployment, shared across sub-phases)
   ├── serve_grpc_for_bench()   — Modal gRPC deployment (stays alive)
   ├── run proxy harness        — writes _GRPC_RESULTS  (via local proxy subprocess)
   ├── run grpc-direct harness  — writes _GRPC_DIRECT_RESULTS (no proxy subprocess)
   └── stop gRPC deployment

3. Comparison
   ├── load _REST_RESULTS, _GRPC_RESULTS, _GRPC_DIRECT_RESULTS
   ├── compare_three_way()
   └── write five output files (see Output Files below)
```

The gRPC serve function stays alive between the proxy and direct harness runs to avoid a second cold start (~75 s) and to keep hardware conditions identical for both runs.

### Output Files

Written to `docs/benchmarks/` only after all three targets complete without error:

| File | Description |
|------|-------------|
| `phase-4.2-grpc-direct-baseline.json` | Raw harness results — gRPC-direct target |
| `phase-4.2-grpc-direct-baseline.md` | Summary markdown — gRPC-direct target |
| `phase-4.2-three-way-comparison.md` | Three-way report: REST / gRPC-proxy / gRPC-direct |
| `phase-4.2-rest-baseline.json` | Re-committed REST raw results (same data as phase-4.1) |
| `phase-4.2-grpc-proxy-baseline.json` | Re-committed gRPC-proxy raw results (same data as phase-4.1) |

If any target fails, none of these files are written and the command exits non-zero.
