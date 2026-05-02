from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vllm_grpc_bench.metrics import BenchmarkRun, RequestResult, RunMeta, RunSummary


def load_run(path: Path) -> BenchmarkRun:
    """Deserialize a BenchmarkRun from a results JSON file written by write_json()."""
    data: dict[str, Any] = json.loads(path.read_text())

    meta_d: dict[str, Any] = data["meta"]
    _cs = meta_d.get("cold_start_s")
    meta = RunMeta(
        timestamp=str(meta_d["timestamp"]),
        git_sha=str(meta_d["git_sha"]),
        hostname=str(meta_d["hostname"]),
        corpus_path=str(meta_d["corpus_path"]),
        concurrency_levels=[int(v) for v in meta_d["concurrency_levels"]],
        proxy_url=str(meta_d["proxy_url"]),
        native_url=str(meta_d["native_url"]),
        modal_function_id=str(meta_d["modal_function_id"])
        if meta_d.get("modal_function_id")
        else None,
        gpu_type=str(meta_d["gpu_type"]) if meta_d.get("gpu_type") else None,
        cold_start_s=float(_cs) if _cs is not None else None,
    )

    def _f(d: dict[str, Any], key: str) -> float | None:
        v = d.get(key)
        return float(v) if v is not None else None

    summaries = [
        RunSummary(
            target=s["target"],
            concurrency=int(s["concurrency"]),
            n_requests=int(s["n_requests"]),
            n_errors=int(s["n_errors"]),
            latency_p50_ms=_f(s, "latency_p50_ms"),
            latency_p95_ms=_f(s, "latency_p95_ms"),
            latency_p99_ms=_f(s, "latency_p99_ms"),
            throughput_rps=_f(s, "throughput_rps"),
            request_bytes_mean=float(s["request_bytes_mean"]),
            response_bytes_mean=_f(s, "response_bytes_mean"),
            proxy_ms_p50=_f(s, "proxy_ms_p50"),
            proxy_ms_p95=_f(s, "proxy_ms_p95"),
            proxy_ms_p99=_f(s, "proxy_ms_p99"),
        )
        for s in data["summaries"]
    ]
    raw = [
        RequestResult(
            sample_id=str(r["sample_id"]),
            target=r["target"],
            concurrency=int(r["concurrency"]),
            latency_ms=_f(r, "latency_ms"),
            request_bytes=int(r["request_bytes"]),
            response_bytes=(
                int(r["response_bytes"]) if r.get("response_bytes") is not None else None
            ),
            proxy_ms=_f(r, "proxy_ms"),
            success=bool(r["success"]),
            error=str(r["error"]) if r.get("error") is not None else None,
        )
        for r in data.get("raw_results", [])
    ]
    return BenchmarkRun(meta=meta, summaries=summaries, raw_results=raw)
