from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    pass


@dataclass
class BenchmarkConfig:
    proxy_url: str
    native_url: str
    corpus_path: str
    concurrency_levels: list[int]
    timeout_seconds: float
    output_dir: str
    compare_to: str | None = None
    regression_threshold: float = 0.10


@dataclass
class RequestResult:
    sample_id: str
    target: Literal["proxy", "native"]
    concurrency: int
    latency_ms: float | None
    request_bytes: int
    response_bytes: int | None
    proxy_ms: float | None
    success: bool
    error: str | None = None


@dataclass
class RunSummary:
    target: Literal["proxy", "native"]
    concurrency: int
    n_requests: int
    n_errors: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    latency_p99_ms: float | None
    throughput_rps: float | None
    request_bytes_mean: float
    response_bytes_mean: float | None
    proxy_ms_p50: float | None
    proxy_ms_p95: float | None
    proxy_ms_p99: float | None


@dataclass
class RunMeta:
    timestamp: str
    git_sha: str
    hostname: str
    corpus_path: str
    concurrency_levels: list[int]
    proxy_url: str
    native_url: str
    modal_function_id: str | None = None
    gpu_type: str | None = None
    cold_start_s: float | None = None


@dataclass
class CrossRunRow:
    metric: str
    concurrency: int
    value_a: float | None
    value_b: float | None
    delta_pct: float | None


@dataclass
class CrossRunReport:
    label_a: str
    label_b: str
    rows: list[CrossRunRow]
    meta_a: RunMeta
    meta_b: RunMeta


@dataclass
class BenchmarkRun:
    meta: RunMeta
    summaries: list[RunSummary]
    raw_results: list[RequestResult] = field(default_factory=list)


@dataclass
class RegressionEntry:
    metric: str
    target: str
    concurrency: int
    baseline_value: float
    new_value: float
    delta_pct: float


@dataclass
class ComparisonReport:
    baseline_path: str
    new_run_path: str
    regressions: list[RegressionEntry]
    has_regression: bool
    threshold: float


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    sorted_vals = sorted(values)
    idx = (p / 100) * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= len(sorted_vals):
        return sorted_vals[lo]
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def compute_summaries(results: list[RequestResult]) -> list[RunSummary]:
    groups: dict[tuple[Literal["proxy", "native"], int], list[RequestResult]] = {}
    for r in results:
        key = (r.target, r.concurrency)
        groups.setdefault(key, []).append(r)

    summaries: list[RunSummary] = []
    for (target, concurrency), group in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        successful = [r for r in group if r.success]
        latencies = [r.latency_ms for r in successful if r.latency_ms is not None]
        proxy_times = [r.proxy_ms for r in successful if r.proxy_ms is not None]
        resp_bytes = [r.response_bytes for r in successful if r.response_bytes is not None]

        total_latency = sum(latencies) if latencies else None
        throughput = (len(successful) / (total_latency / 1000)) if total_latency else None

        summaries.append(
            RunSummary(
                target=target,
                concurrency=concurrency,
                n_requests=len(group),
                n_errors=len(group) - len(successful),
                latency_p50_ms=_percentile(latencies, 50),
                latency_p95_ms=_percentile(latencies, 95),
                latency_p99_ms=_percentile(latencies, 99),
                throughput_rps=throughput,
                request_bytes_mean=sum(r.request_bytes for r in group) / len(group),
                response_bytes_mean=(sum(resp_bytes) / len(resp_bytes)) if resp_bytes else None,
                proxy_ms_p50=_percentile(proxy_times, 50),
                proxy_ms_p95=_percentile(proxy_times, 95),
                proxy_ms_p99=_percentile(proxy_times, 99),
            )
        )
    return summaries


def build_run_meta(
    config: BenchmarkConfig,
    *,
    modal_function_id: str | None = None,
    gpu_type: str | None = None,
    cold_start_s: float | None = None,
) -> RunMeta:
    try:
        git_sha = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
    except Exception:
        git_sha = "unknown"

    return RunMeta(
        timestamp=datetime.now(tz=UTC).isoformat(),
        git_sha=git_sha,
        hostname=socket.gethostname(),
        corpus_path=config.corpus_path,
        concurrency_levels=config.concurrency_levels,
        proxy_url=config.proxy_url,
        native_url=config.native_url,
        modal_function_id=modal_function_id,
        gpu_type=gpu_type,
        cold_start_s=cold_start_s,
    )
