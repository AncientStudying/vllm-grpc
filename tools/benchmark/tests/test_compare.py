from __future__ import annotations

import pytest
from vllm_grpc_bench.compare import compare
from vllm_grpc_bench.metrics import BenchmarkRun, RunMeta, RunSummary


def _meta() -> RunMeta:
    return RunMeta(
        timestamp="2026-05-01T00:00:00+00:00",
        git_sha="abc",
        hostname="h",
        corpus_path="c.json",
        concurrency_levels=[1],
        proxy_url="http://localhost:8000",
        native_url="http://localhost:8001",
    )


def _make_summary(
    target: str = "proxy",
    concurrency: int = 1,
    latency_p50: float = 100.0,
    latency_p95: float = 120.0,
    latency_p99: float = 130.0,
) -> RunSummary:
    return RunSummary(
        target=target,  # type: ignore[arg-type]
        concurrency=concurrency,
        n_requests=10,
        n_errors=0,
        latency_p50_ms=latency_p50,
        latency_p95_ms=latency_p95,
        latency_p99_ms=latency_p99,
        throughput_rps=10.0,
        request_bytes_mean=100.0,
        response_bytes_mean=200.0,
        proxy_ms_p50=None,
        proxy_ms_p95=None,
        proxy_ms_p99=None,
    )


def _make_run(summaries: list[RunSummary]) -> BenchmarkRun:
    return BenchmarkRun(meta=_meta(), summaries=summaries, raw_results=[])


class TestCompare:
    def test_identical_runs_no_regressions(self) -> None:
        s = _make_summary()
        baseline = _make_run([s])
        new_run = _make_run([s])
        report = compare(baseline, new_run, threshold=0.10)
        assert not report.has_regression
        assert report.regressions == []

    def test_one_metric_11_percent_worse_is_regression(self) -> None:
        baseline = _make_run([_make_summary(latency_p95=100.0)])
        new_run = _make_run([_make_summary(latency_p95=112.0)])
        report = compare(baseline, new_run, threshold=0.10)
        assert report.has_regression
        assert len(report.regressions) >= 1
        reg = next(r for r in report.regressions if "p95" in r.metric)
        assert reg.delta_pct == pytest.approx(0.12, abs=0.001)

    def test_one_metric_9_percent_worse_no_regression(self) -> None:
        baseline = _make_run([_make_summary(latency_p95=100.0)])
        new_run = _make_run([_make_summary(latency_p95=109.0)])
        report = compare(baseline, new_run, threshold=0.10)
        p95_regressions = [r for r in report.regressions if "p95" in r.metric]
        assert len(p95_regressions) == 0

    def test_none_field_in_new_run_skipped(self) -> None:
        s_base = _make_summary(latency_p50=100.0)
        s_new = _make_summary()
        s_new.latency_p50_ms = None
        baseline = _make_run([s_base])
        new_run = _make_run([s_new])
        report = compare(baseline, new_run, threshold=0.10)
        p50_regressions = [r for r in report.regressions if "p50" in r.metric]
        assert len(p50_regressions) == 0

    def test_all_improvements_no_regression(self) -> None:
        baseline = _make_run([_make_summary(latency_p50=100.0, latency_p95=120.0)])
        new_run = _make_run([_make_summary(latency_p50=80.0, latency_p95=90.0)])
        report = compare(baseline, new_run, threshold=0.10)
        assert not report.has_regression

    def test_missing_concurrency_in_new_run_skipped(self) -> None:
        baseline = _make_run([_make_summary(concurrency=1), _make_summary(concurrency=4)])
        new_run = _make_run([_make_summary(concurrency=1)])
        report = compare(baseline, new_run, threshold=0.10)
        assert not report.has_regression
