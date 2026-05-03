from __future__ import annotations

from unittest.mock import patch

import pytest
from vllm_grpc_bench.metrics import (
    BenchmarkConfig,
    RequestResult,
    _percentile,
    build_run_meta,
    compute_summaries,
)


def _make_result(
    sample_id: str = "s1",
    target: str = "proxy",
    concurrency: int = 1,
    latency_ms: float | None = 100.0,
    request_bytes: int = 50,
    response_bytes: int | None = 200,
    proxy_ms: float | None = None,
    success: bool = True,
    error: str | None = None,
    ttft_ms: float | None = None,
    tpot_ms: float | None = None,
    token_count: int | None = None,
) -> RequestResult:
    return RequestResult(
        sample_id=sample_id,
        target=target,  # type: ignore[arg-type]
        concurrency=concurrency,
        latency_ms=latency_ms,
        request_bytes=request_bytes,
        response_bytes=response_bytes,
        proxy_ms=proxy_ms,
        success=success,
        error=error,
        ttft_ms=ttft_ms,
        tpot_ms=tpot_ms,
        token_count=token_count,
    )


class TestPercentile:
    def test_empty_returns_none(self) -> None:
        assert _percentile([], 50) is None

    def test_single_value(self) -> None:
        assert _percentile([42.0], 50) == 42.0
        assert _percentile([42.0], 99) == 42.0

    def test_sorted_list(self) -> None:
        result = _percentile([10.0, 20.0, 30.0, 40.0, 50.0], 50)
        assert result == pytest.approx(30.0)

    def test_unsorted_list(self) -> None:
        result = _percentile([50.0, 10.0, 30.0, 20.0, 40.0], 50)
        assert result == pytest.approx(30.0)

    def test_p95_large_list(self) -> None:
        vals = list(range(1, 101, 1))
        result = _percentile([float(v) for v in vals], 95)
        assert result is not None
        assert result >= 95.0


class TestComputeSummaries:
    def test_all_success_non_none_p50(self) -> None:
        results = [_make_result(latency_ms=100.0 + i * 10) for i in range(5)]
        summaries = compute_summaries(results)
        assert len(summaries) == 1
        s = summaries[0]
        assert s.latency_p50_ms is not None
        assert s.latency_p95_ms is not None
        assert s.latency_p99_ms is not None

    def test_all_errors_none_latencies(self) -> None:
        results = [
            _make_result(latency_ms=None, response_bytes=None, success=False, error="timeout")
            for _ in range(3)
        ]
        summaries = compute_summaries(results)
        s = summaries[0]
        assert s.latency_p50_ms is None
        assert s.latency_p95_ms is None
        assert s.latency_p99_ms is None
        assert s.response_bytes_mean is None
        assert s.n_errors == 3

    def test_proxy_ms_none_when_no_header(self) -> None:
        results = [_make_result(proxy_ms=None) for _ in range(3)]
        summaries = compute_summaries(results)
        s = summaries[0]
        assert s.proxy_ms_p50 is None
        assert s.proxy_ms_p95 is None
        assert s.proxy_ms_p99 is None

    def test_proxy_ms_computed_when_present(self) -> None:
        results = [_make_result(proxy_ms=1.5 + i * 0.1) for i in range(5)]
        summaries = compute_summaries(results)
        s = summaries[0]
        assert s.proxy_ms_p50 is not None

    def test_groups_by_target_and_concurrency(self) -> None:
        results = [
            _make_result(target="proxy", concurrency=1),
            _make_result(target="proxy", concurrency=4),
            _make_result(target="native", concurrency=1),
        ]
        summaries = compute_summaries(results)
        assert len(summaries) == 3

    def test_request_bytes_mean(self) -> None:
        results = [_make_result(request_bytes=100), _make_result(request_bytes=200)]
        summaries = compute_summaries(results)
        assert summaries[0].request_bytes_mean == pytest.approx(150.0)


class TestComputeSummariesStreaming:
    def test_ttft_none_when_not_provided(self) -> None:
        results = [_make_result() for _ in range(3)]
        summaries = compute_summaries(results)
        s = summaries[0]
        assert s.ttft_p50_ms is None
        assert s.ttft_p95_ms is None
        assert s.ttft_p99_ms is None
        assert s.tpot_p50_ms is None
        assert s.tpot_p95_ms is None
        assert s.tpot_p99_ms is None

    def test_ttft_computed_from_results(self) -> None:
        results = [_make_result(ttft_ms=10.0 + i * 2) for i in range(5)]
        summaries = compute_summaries(results)
        s = summaries[0]
        assert s.ttft_p50_ms is not None
        assert s.ttft_p95_ms is not None
        assert s.ttft_p99_ms is not None

    def test_tpot_computed_from_results(self) -> None:
        results = [_make_result(tpot_ms=5.0 + i * 1.0) for i in range(5)]
        summaries = compute_summaries(results)
        s = summaries[0]
        assert s.tpot_p50_ms is not None
        assert s.tpot_p95_ms is not None
        assert s.tpot_p99_ms is not None

    def test_ttft_values_are_monotone_p50_le_p99(self) -> None:
        results = [_make_result(ttft_ms=float(i)) for i in range(1, 11)]
        summaries = compute_summaries(results)
        s = summaries[0]
        assert s.ttft_p50_ms is not None
        assert s.ttft_p99_ms is not None
        assert s.ttft_p50_ms <= s.ttft_p99_ms

    def test_failed_results_excluded_from_ttft(self) -> None:
        good = [_make_result(success=True, ttft_ms=10.0) for _ in range(3)]
        bad = [_make_result(success=False, ttft_ms=None, latency_ms=None) for _ in range(2)]
        summaries = compute_summaries(good + bad)
        s = summaries[0]
        assert s.ttft_p50_ms is not None
        assert s.n_errors == 2


class TestBuildRunMeta:
    def test_populates_all_fields(self) -> None:
        cfg = BenchmarkConfig(
            proxy_url="http://localhost:8000",
            native_url="http://localhost:8001",
            corpus_path="tools/benchmark/corpus/chat_nonstreaming.json",
            concurrency_levels=[1, 4],
            timeout_seconds=30.0,
            output_dir="bench-results",
        )
        meta = build_run_meta(cfg)
        assert meta.timestamp
        assert meta.git_sha
        assert meta.hostname
        assert meta.corpus_path == cfg.corpus_path
        assert meta.concurrency_levels == [1, 4]
        assert meta.proxy_url == "http://localhost:8000"
        assert meta.native_url == "http://localhost:8001"

    def test_git_sha_fallback_on_error(self) -> None:
        cfg = BenchmarkConfig(
            proxy_url="http://localhost:8000",
            native_url="http://localhost:8001",
            corpus_path="corpus.json",
            concurrency_levels=[1],
            timeout_seconds=30.0,
            output_dir="out",
        )
        with patch("subprocess.check_output", side_effect=Exception("no git")):
            meta = build_run_meta(cfg)
        assert meta.git_sha == "unknown"
