from __future__ import annotations

import csv
import dataclasses
import json
from pathlib import Path

from vllm_grpc_bench.metrics import (
    BenchmarkRun,
    CrossRunReport,
    RunMeta,
    RunSummary,
    ThreeWayReport,
)


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


def _meta_section(label: str, meta: RunMeta) -> list[str]:
    lines = [f"**{label}**:  "]
    lines.append(f"- Timestamp: {meta.timestamp}  ")
    lines.append(f"- Git SHA: {meta.git_sha}  ")
    lines.append(f"- Host: {meta.hostname}  ")
    if meta.gpu_type:
        lines.append(f"- GPU: {meta.gpu_type}  ")
    if meta.modal_function_id:
        lines.append(f"- Modal function: {meta.modal_function_id}  ")
    if meta.cold_start_s is not None:
        lines.append(f"- Cold start: {meta.cold_start_s:.1f}s  ")
    return lines


_CROSS_METRIC_LABELS: dict[str, tuple[str, int]] = {
    "latency_p50_ms": ("Latency P50 (ms)", 2),
    "latency_p95_ms": ("Latency P95 (ms)", 2),
    "latency_p99_ms": ("Latency P99 (ms)", 2),
    "throughput_rps": ("Throughput (rps)", 2),
    "request_bytes_mean": ("Request bytes (mean)", 0),
    "response_bytes_mean": ("Response bytes (mean)", 0),
}


def write_cross_run_md(report: CrossRunReport, output_path: Path) -> Path:
    """Render a CrossRunReport as a markdown head-to-head table."""
    la = report.label_a
    lb = report.label_b

    lines: list[str] = [
        f"# Benchmark Comparison: {la} vs {lb}",
        "",
        "## Run Metadata",
        "",
    ]
    lines += _meta_section(la, report.meta_a)
    lines.append("")
    lines += _meta_section(lb, report.meta_b)
    lines.append("")

    # Group rows by concurrency
    concurrencies: list[int] = sorted({r.concurrency for r in report.rows})
    for conc in concurrencies:
        conc_rows = [r for r in report.rows if r.concurrency == conc]
        by_metric = {r.metric: r for r in conc_rows}

        lines += [
            f"## Concurrency = {conc}",
            "",
            f"| Metric | {la} | {lb} | Δ |",
            "|--------|" + "-" * (len(la) + 2) + "|" + "-" * (len(lb) + 2) + "|---|",
        ]

        for field_name, (label, precision) in _CROSS_METRIC_LABELS.items():
            row = by_metric.get(field_name)
            if row is None:
                lines.append(f"| {label} | — | — | — |")
                continue
            va = _fmt(row.value_a, precision)
            vb = _fmt(row.value_b, precision)
            if row.delta_pct is not None:
                sign = "+" if row.delta_pct >= 0 else ""
                dlt = f"{sign}{row.delta_pct * 100:.1f}%"
            else:
                dlt = "—"
            lines.append(f"| {label} | {va} | {vb} | {dlt} |")

        lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))
    return output_path


def write_three_way_md(report: ThreeWayReport, path: Path) -> None:
    if not report.rows:
        return

    la, lb, lc = report.label_a, report.label_b, report.label_c

    lines: list[str] = [
        f"# Three-Way Benchmark Comparison: {la} / {lb} / {lc}",
        "",
        "## Run Metadata",
        "",
    ]
    lines += _meta_section(la, report.meta_a)
    lines.append("")
    lines += _meta_section(lb, report.meta_b)
    lines.append("")
    lines += _meta_section(lc, report.meta_c)
    lines.append("")

    concurrencies = sorted({r.concurrency for r in report.rows})
    for conc in concurrencies:
        conc_rows = [r for r in report.rows if r.concurrency == conc]
        by_metric = {r.metric: r for r in conc_rows}

        sep_a = "-" * (len(la) + 2)
        sep_b = "-" * (len(lb) + 2)
        sep_delta = "-" * (len(f"Δ vs {la}") + 2)
        sep_c = "-" * (len(lc) + 2)

        lines += [
            f"## Concurrency = {conc}",
            "",
            f"| metric | concurrency | {la} | {lb} | Δ vs {la} | {lc} | Δ vs {la} |",
            f"|--------|-------------|{sep_a}|{sep_b}|{sep_delta}|{sep_c}|{sep_delta}|",
        ]

        for field_name, (label, precision) in _CROSS_METRIC_LABELS.items():
            row = by_metric.get(field_name)
            if row is None:
                lines.append(f"| {label} | {conc} | — | — | — | — | — |")
                continue
            va = _fmt(row.value_a, precision)
            vb = _fmt(row.value_b, precision)
            vc = _fmt(row.value_c, precision)

            def _dpct(v: float | None) -> str:
                if v is None:
                    return "—"
                sign = "+" if v >= 0 else ""
                return f"{sign}{v:.1f}%"

            lines.append(
                f"| {label} | {conc} | {va} | {vb} | {_dpct(row.delta_pct_b)}"
                f" | {vc} | {_dpct(row.delta_pct_c)} |"
            )

        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
