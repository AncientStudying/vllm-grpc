from __future__ import annotations

from vllm_grpc_bench.metrics import BenchmarkRun, ComparisonReport, RegressionEntry, RunSummary

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
