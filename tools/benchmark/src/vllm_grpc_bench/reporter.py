from __future__ import annotations

import csv
import dataclasses
import json
from pathlib import Path

from vllm_grpc_bench.metrics import BenchmarkRun, RunSummary


def _to_dict(obj: object) -> object:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_dict(i) for i in obj]
    return obj


def write_json(run: BenchmarkRun, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "results.json"
    out.write_text(json.dumps(_to_dict(run), indent=2))
    return out


def write_csv(run: BenchmarkRun, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "results.csv"
    fieldnames = [
        "target",
        "concurrency",
        "sample_id",
        "latency_ms",
        "request_bytes",
        "response_bytes",
        "proxy_ms",
        "success",
    ]
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in run.raw_results:
            writer.writerow(
                {
                    "target": r.target,
                    "concurrency": r.concurrency,
                    "sample_id": r.sample_id,
                    "latency_ms": r.latency_ms,
                    "request_bytes": r.request_bytes,
                    "response_bytes": r.response_bytes,
                    "proxy_ms": r.proxy_ms,
                    "success": r.success,
                }
            )
    return out


def _fmt(value: float | None, precision: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{precision}f}"


def _delta(proxy: float | None, native: float | None) -> str:
    if proxy is None or native is None or native == 0:
        return "N/A"
    pct = (proxy - native) / native * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _row(
    label: str,
    pv: float | None,
    nv: float | None,
    precision: int = 2,
    proxy_only: bool = False,
) -> str:
    pf = _fmt(pv, precision)
    nf = "N/A" if proxy_only else _fmt(nv, precision)
    delta = "N/A" if proxy_only else _delta(pv, nv)
    return f"| {label} | {pf} | {nf} | {delta} |"


def write_summary_md(run: BenchmarkRun, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "summary.md"

    by_concurrency: dict[int, dict[str, object]] = {}
    for s in run.summaries:
        by_concurrency.setdefault(s.concurrency, {})[s.target] = s

    lines: list[str] = [
        "# Benchmark Summary",
        "",
        f"**Run**: {run.meta.timestamp}  ",
        f"**Commit**: {run.meta.git_sha}  ",
        f"**Host**: {run.meta.hostname}  ",
        "",
    ]

    for conc in sorted(by_concurrency.keys()):
        targets = by_concurrency[conc]
        proxy = targets.get("proxy")
        native = targets.get("native")

        p = proxy if isinstance(proxy, RunSummary) else None
        n = native if isinstance(native, RunSummary) else None

        pp50 = p.latency_p50_ms if p else None
        pp95 = p.latency_p95_ms if p else None
        pp99 = p.latency_p99_ms if p else None
        pthr = p.throughput_rps if p else None
        preq = p.request_bytes_mean if p else None
        prsp = p.response_bytes_mean if p else None
        ppm50 = p.proxy_ms_p50 if p else None
        ppm95 = p.proxy_ms_p95 if p else None
        ppm99 = p.proxy_ms_p99 if p else None
        np50 = n.latency_p50_ms if n else None
        np95 = n.latency_p95_ms if n else None
        np99 = n.latency_p99_ms if n else None
        nthr = n.throughput_rps if n else None
        nreq = n.request_bytes_mean if n else None
        nrsp = n.response_bytes_mean if n else None
        lines += [
            f"## Concurrency = {conc}",
            "",
            "| Metric | Proxy | Native | Δ |",
            "|--------|-------|--------|---|",
            _row("Latency P50 (ms)", pp50, np50),
            _row("Latency P95 (ms)", pp95, np95),
            _row("Latency P99 (ms)", pp99, np99),
            _row("Throughput (rps)", pthr, nthr),
            _row("Request bytes (mean)", preq, nreq, precision=0),
            _row("Response bytes (mean)", prsp, nrsp, precision=0),
            _row("Proxy ms P50", ppm50, None, precision=3, proxy_only=True),
            _row("Proxy ms P95", ppm95, None, precision=3, proxy_only=True),
            _row("Proxy ms P99", ppm99, None, precision=3, proxy_only=True),
            "",
        ]

    out.write_text("\n".join(lines))
    return out
