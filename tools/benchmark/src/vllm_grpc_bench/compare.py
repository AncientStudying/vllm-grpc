from __future__ import annotations

from vllm_grpc_bench.metrics import (
    BenchmarkRun,
    ComparisonReport,
    CrossRunReport,
    CrossRunRow,
    RegressionEntry,
    RunSummary,
)

_METRIC_FIELDS = [
    ("latency_p50_ms", "latency_p50"),
    ("latency_p95_ms", "latency_p95"),
    ("latency_p99_ms", "latency_p99"),
    ("throughput_rps", "throughput_rps"),
    ("response_bytes_mean", "response_bytes_mean"),
    ("proxy_ms_p50", "proxy_ms_p50"),
    ("proxy_ms_p95", "proxy_ms_p95"),
    ("proxy_ms_p99", "proxy_ms_p99"),
]


def compare(
    baseline: BenchmarkRun,
    new_run: BenchmarkRun,
    threshold: float = 0.10,
) -> ComparisonReport:
    baseline_index: dict[tuple[str, int], RunSummary] = {
        (s.target, s.concurrency): s for s in baseline.summaries
    }

    regressions: list[RegressionEntry] = []

    for new_s in new_run.summaries:
        base_s = baseline_index.get((new_s.target, new_s.concurrency))
        if base_s is None:
            continue
        for field_name, label in _METRIC_FIELDS:
            base_val = getattr(base_s, field_name)
            new_val = getattr(new_s, field_name)
            if base_val is None or new_val is None or base_val == 0:
                continue
            delta_pct = (new_val - base_val) / base_val
            if delta_pct > threshold:
                regressions.append(
                    RegressionEntry(
                        metric=f"{new_s.target} {label} @ concurrency={new_s.concurrency}",
                        target=new_s.target,
                        concurrency=new_s.concurrency,
                        baseline_value=base_val,
                        new_value=new_val,
                        delta_pct=delta_pct,
                    )
                )

    return ComparisonReport(
        baseline_path="",
        new_run_path="",
        regressions=regressions,
        has_regression=len(regressions) > 0,
        threshold=threshold,
    )


# Metrics extracted from each run for cross-run comparison.
# REST run uses the "native" target; gRPC run uses the "proxy" target.
_CROSS_METRIC_FIELDS = [
    "latency_p50_ms",
    "latency_p95_ms",
    "latency_p99_ms",
    "throughput_rps",
    "request_bytes_mean",
    "response_bytes_mean",
]

_REST_TARGET = "native"
_GRPC_TARGET = "proxy"


def compare_cross(
    run_a: BenchmarkRun,
    run_b: BenchmarkRun,
    label_a: str = "run-a",
    label_b: str = "run-b",
) -> CrossRunReport:
    """Compare two separate BenchmarkRun objects (e.g. REST vs gRPC) by concurrency level."""
    # Index run_a by concurrency, picking the dominant target for each run.
    # run_a is the REST run (native target); run_b is the gRPC run (proxy target).
    index_a: dict[int, RunSummary] = {}
    for s in run_a.summaries:
        if s.target == _REST_TARGET:
            index_a[s.concurrency] = s

    index_b: dict[int, RunSummary] = {}
    for s in run_b.summaries:
        if s.target == _GRPC_TARGET:
            index_b[s.concurrency] = s

    all_concurrencies = sorted(set(index_a) | set(index_b))
    rows: list[CrossRunRow] = []

    for conc in all_concurrencies:
        s_a = index_a.get(conc)
        s_b = index_b.get(conc)
        for field_name in _CROSS_METRIC_FIELDS:
            val_a = getattr(s_a, field_name) if s_a is not None else None
            val_b = getattr(s_b, field_name) if s_b is not None else None
            if val_a is not None and val_b is not None and val_a != 0:
                delta_pct = (val_b - val_a) / val_a
            else:
                delta_pct = None
            rows.append(
                CrossRunRow(
                    metric=field_name,
                    concurrency=conc,
                    value_a=val_a,
                    value_b=val_b,
                    delta_pct=delta_pct,
                )
            )

    return CrossRunReport(
        label_a=label_a,
        label_b=label_b,
        rows=rows,
        meta_a=run_a.meta,
        meta_b=run_b.meta,
    )
