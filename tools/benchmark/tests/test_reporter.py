from __future__ import annotations

import csv
import json
from pathlib import Path

from vllm_grpc_bench.metrics import (
    BenchmarkRun,
    RequestResult,
    RunMeta,
    compute_summaries,
)
from vllm_grpc_bench.reporter import write_csv, write_json, write_summary_md


def _make_run(tmp_path: Path) -> BenchmarkRun:
    meta = RunMeta(
        timestamp="2026-05-01T00:00:00+00:00",
        git_sha="abc123",
        hostname="testhost",
        corpus_path="corpus/chat_nonstreaming.json",
        concurrency_levels=[1],
        proxy_url="http://localhost:8000",
        native_url="http://localhost:8001",
    )
    raw: list[RequestResult] = [
        RequestResult(
            sample_id="s1",
            target="proxy",
            concurrency=1,
            latency_ms=50.0,
            request_bytes=100,
            response_bytes=200,
            proxy_ms=1.5,
            success=True,
        ),
        RequestResult(
            sample_id="s1",
            target="native",
            concurrency=1,
            latency_ms=40.0,
            request_bytes=100,
            response_bytes=180,
            proxy_ms=None,
            success=True,
        ),
    ]
    summaries = compute_summaries(raw)
    return BenchmarkRun(meta=meta, summaries=summaries, raw_results=raw)


def test_write_json_valid(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    out = write_json(run, tmp_path)
    assert out.exists()
    data = json.loads(out.read_text())
    assert "meta" in data
    assert "summaries" in data
    assert "raw_results" in data
    assert data["meta"]["git_sha"] == "abc123"
    assert len(data["summaries"]) == 2
    assert len(data["raw_results"]) == 2


def test_write_csv_columns(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    out = write_csv(run, tmp_path)
    assert out.exists()
    with out.open() as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames is not None
        assert "target" in reader.fieldnames
        assert "concurrency" in reader.fieldnames
        assert "sample_id" in reader.fieldnames
        assert "latency_ms" in reader.fieldnames
        assert "request_bytes" in reader.fieldnames
        assert "response_bytes" in reader.fieldnames
        assert "proxy_ms" in reader.fieldnames
        assert "success" in reader.fieldnames
        rows = list(reader)
    assert len(rows) == 2


def test_write_summary_md_contains_proxy_and_native(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    out = write_summary_md(run, tmp_path)
    assert out.exists()
    content = out.read_text()
    assert "proxy" in content.lower()
    assert "native" in content.lower()
    assert "Δ" in content or "delta" in content.lower() or "|" in content


def _make_summary(
    target: str,
    request_type: str,
    req_bytes: float,
    resp_bytes: float | None = 200.0,
    latency_p50: float = 50.0,
    throughput: float = 10.0,
) -> object:
    from vllm_grpc_bench.metrics import RunSummary

    return RunSummary(
        target=target,  # type: ignore[arg-type]
        concurrency=1,
        n_requests=5,
        n_errors=0,
        latency_p50_ms=latency_p50,
        latency_p95_ms=80.0,
        latency_p99_ms=100.0,
        throughput_rps=throughput,
        request_bytes_mean=req_bytes,
        response_bytes_mean=resp_bytes,
        proxy_ms_p50=None,
        proxy_ms_p95=None,
        proxy_ms_p99=None,
        request_type=request_type,  # type: ignore[arg-type]
    )


def test_write_wire_size_comparison_md(tmp_path: Path) -> None:
    from vllm_grpc_bench.reporter import write_wire_size_comparison_md

    summaries = [
        # Text path: native is baseline; proxy and grpc-direct show delta
        _make_summary("native", "completion-text", req_bytes=37500.0),
        _make_summary("proxy", "completion-text", req_bytes=37500.0),
        _make_summary("grpc-direct", "completion-text", req_bytes=30000.0),
        # Embed path: native is baseline; proxy and grpc-direct show delta
        _make_summary("native", "completion-embeds", req_bytes=50000.0, resp_bytes=None),
        _make_summary("proxy", "completion-embeds", req_bytes=50000.0, resp_bytes=None),
        _make_summary("grpc-direct", "completion-embeds", req_bytes=37500.0, resp_bytes=None),
    ]

    out = tmp_path / "wire-size.md"
    write_wire_size_comparison_md(summaries, out)
    assert out.exists()
    content = out.read_text()

    # Table structure
    assert "| path |" in content
    assert "Δ vs baseline" in content

    # All input types and paths present
    assert "completion-text" in content
    assert "completion-embeds" in content
    assert "native" in content
    assert "proxy" in content
    assert "grpc-direct" in content

    # Native REST is the baseline for both text and embed paths
    assert "baseline" in content
    assert "vs native-REST" in content

    # Latency table present with expected headers
    assert "latency_p50_ms" in content
    assert "throughput_rps" in content
