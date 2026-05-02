# Data Model: Phase 4.1 — Real Comparative Baselines (Modal)

**Branch**: `007-modal-real-baselines` | **Date**: 2026-05-02

This document covers only the additions and changes to the Phase 4 data model.
The Phase 4 data model (`specs/004-benchmark-harness/data-model.md`) remains the
authoritative source for all entities not listed here.

---

## Modified Entities

### RunMeta (extended)

Three optional fields are added to `tools/benchmark/src/vllm_grpc_bench/metrics.py`.
All existing fields are unchanged. Default is `None` for local/CI runs.

| Field | Type | Description |
|-------|------|-------------|
| `modal_function_id` | `str \| None` | Modal function call ID returned by `modal.Dict` from the serve function; `None` for local runs |
| `gpu_type` | `str \| None` | GPU type string as reported by Modal (e.g., `"A10G"`); `None` for local runs |
| `cold_start_s` | `float \| None` | Provisioning + server startup time in seconds, measured inside the serve function; `None` for local runs |

**Serialization note**: `build_run_meta()` is extended to accept these fields as keyword arguments with `None` defaults. The deserializer in `__main__.py._deserialize_run()` uses `.get()` for these keys so existing CI baseline JSON files deserialize without error.

---

## New Entities

### CrossRunReport

Output of `compare_cross(run_a, run_b, label_a, label_b)`. Presents head-to-head
metrics from two separate `BenchmarkRun` objects aligned by concurrency level.

| Field | Type | Description |
|-------|------|-------------|
| `label_a` | `str` | Human-readable label for run A (e.g., `"REST"`) |
| `label_b` | `str` | Human-readable label for run B (e.g., `"gRPC"`) |
| `rows` | `list[CrossRunRow]` | One row per `(metric_name, concurrency)` combination |
| `meta_a` | `RunMeta` | Metadata from run A |
| `meta_b` | `RunMeta` | Metadata from run B |

#### CrossRunRow (nested in CrossRunReport)

| Field | Type | Description |
|-------|------|-------------|
| `metric` | `str` | Metric name (e.g., `"latency_p50_ms"`) |
| `concurrency` | `int` | Concurrency level |
| `value_a` | `float \| None` | Metric value from run A at this concurrency; `None` if not measured |
| `value_b` | `float \| None` | Metric value from run B at this concurrency; `None` if not measured |
| `delta_pct` | `float \| None` | `(value_b - value_a) / value_a`; `None` if either value is absent or `value_a == 0` |

**Metrics included** (drawn from `RunSummary` fields for the relevant target):

| Metric | From REST run | From gRPC run |
|--------|---------------|---------------|
| `latency_p50_ms` | `native` summary | `proxy` summary |
| `latency_p95_ms` | `native` summary | `proxy` summary |
| `latency_p99_ms` | `native` summary | `proxy` summary |
| `throughput_rps` | `native` summary | `proxy` summary |
| `request_bytes_mean` | `native` summary | `proxy` summary |
| `response_bytes_mean` | `native` summary | `proxy` summary |

`proxy_ms_*` fields are omitted from the cross-run comparison (not meaningful for
the REST target, which has no proxy translation layer).

---

## New Output Files

These files are produced by `bench_modal.py` after a successful run and committed
to the repository by the developer:

| Path | Format | Description |
|------|--------|-------------|
| `docs/benchmarks/phase-3-modal-rest-baseline.json` | JSON (`BenchmarkRun`) | REST run result with extended `RunMeta` |
| `docs/benchmarks/phase-3-modal-rest-baseline.md` | Markdown | Human-readable summary of the REST run |
| `docs/benchmarks/phase-3-modal-grpc-baseline.json` | JSON (`BenchmarkRun`) | gRPC proxy run result with extended `RunMeta` |
| `docs/benchmarks/phase-3-modal-grpc-baseline.md` | Markdown | Human-readable summary of the gRPC run |
| `docs/benchmarks/phase-3-modal-comparison.md` | Markdown | Head-to-head `CrossRunReport` rendered as tables |

---

## Module → Entity Mapping (additions)

| Module | Owns / Produces |
|--------|----------------|
| `compare.py` (extended) | `compare_cross()` → `CrossRunReport` |
| `metrics.py` (extended) | Extended `RunMeta`; new `CrossRunReport`, `CrossRunRow` dataclasses |
| `scripts/python/bench_modal.py` | Orchestrates both Modal runs; writes all five output files above |

---

## Coordination via modal.Dict

`bench_modal.py` uses a `modal.Dict` named `"vllm-grpc-bench-modal"` (separate
from `modal_frontend_serve.py`'s `"vllm-grpc-serve"` to avoid collisions).

| Key | Written by | Read by | Content |
|-----|-----------|---------|---------|
| `rest_addr` | `serve_rest_for_bench` (inside Modal) | `bench_modal.py` local entrypoint | `"host:port"` of the REST tunnel |
| `rest_cold_start_s` | `serve_rest_for_bench` | `bench_modal.py` local entrypoint | `float` — time from function start to server healthy |
| `rest_stop` | `bench_modal.py` local entrypoint | `serve_rest_for_bench` | `True` when benchmarks are done |
| `grpc_addr` | `serve_grpc_for_bench` (inside Modal) | `bench_modal.py` local entrypoint | `"host:port"` of the gRPC tunnel |
| `grpc_cold_start_s` | `serve_grpc_for_bench` | `bench_modal.py` local entrypoint | `float` |
| `grpc_stop` | `bench_modal.py` local entrypoint | `serve_grpc_for_bench` | `True` when benchmarks are done |
