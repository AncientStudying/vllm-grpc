from __future__ import annotations

import csv
import dataclasses
import json
from collections import defaultdict
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
        "ttft_ms",
        "tpot_ms",
        "token_count",
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
                    "ttft_ms": r.ttft_ms,
                    "tpot_ms": r.tpot_ms,
                    "token_count": r.token_count,
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


# Metrics rendered for any single-target run (no comparison column).
_SINGLE_TARGET_METRICS: list[tuple[str, str, int]] = [
    ("latency_p50_ms", "Latency P50 (ms)", 2),
    ("latency_p95_ms", "Latency P95 (ms)", 2),
    ("latency_p99_ms", "Latency P99 (ms)", 2),
    ("throughput_rps", "Throughput (rps)", 2),
    ("request_bytes_mean", "Request bytes (mean)", 0),
    ("response_bytes_mean", "Response bytes (mean)", 0),
    ("ttft_p50_ms", "TTFT P50 (ms)", 2),
    ("ttft_p95_ms", "TTFT P95 (ms)", 2),
    ("ttft_p99_ms", "TTFT P99 (ms)", 2),
    ("tpot_p50_ms", "TPOT P50 (ms)", 2),
    ("tpot_p95_ms", "TPOT P95 (ms)", 2),
    ("tpot_p99_ms", "TPOT P99 (ms)", 2),
]

# Human-readable display names for targets that aren't proxy/native.
_TARGET_DISPLAY_NAMES: dict[str, str] = {
    "grpc-direct": "gRPC-direct",
}


def write_summary_md(run: BenchmarkRun, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "summary.md"

    by_concurrency: dict[int, dict[str, RunSummary]] = {}
    for s in run.summaries:
        by_concurrency.setdefault(s.concurrency, {})[s.target] = s

    lines: list[str] = [
        "# Benchmark Summary",
        "",
        f"**Run**: {run.meta.timestamp}  ",
        f"**Commit**: {run.meta.git_sha}  ",
        f"**Host**: {run.meta.hostname}  ",
    ]
    if run.meta.gpu_type:
        lines.append(f"**GPU**: {run.meta.gpu_type}  ")
    if run.meta.cold_start_s is not None:
        lines.append(f"**Cold start**: {run.meta.cold_start_s:.1f}s  ")
    lines.append("")

    for conc in sorted(by_concurrency.keys()):
        targets = by_concurrency[conc]
        p = targets.get("proxy")
        n = targets.get("native")

        lines += [f"## Concurrency = {conc}", ""]

        if p is not None or n is not None:
            lines += ["| Metric | Proxy | Native | Δ |", "|--------|-------|--------|---|"]
            for field, label, prec in [
                ("latency_p50_ms", "Latency P50 (ms)", 2),
                ("latency_p95_ms", "Latency P95 (ms)", 2),
                ("latency_p99_ms", "Latency P99 (ms)", 2),
                ("throughput_rps", "Throughput (rps)", 2),
                ("request_bytes_mean", "Request bytes (mean)", 0),
                ("response_bytes_mean", "Response bytes (mean)", 0),
                ("ttft_p50_ms", "TTFT P50 (ms)", 2),
                ("ttft_p95_ms", "TTFT P95 (ms)", 2),
                ("ttft_p99_ms", "TTFT P99 (ms)", 2),
                ("tpot_p50_ms", "TPOT P50 (ms)", 2),
                ("tpot_p95_ms", "TPOT P95 (ms)", 2),
                ("tpot_p99_ms", "TPOT P99 (ms)", 2),
            ]:
                pval: float | None = getattr(p, field) if p else None
                nval: float | None = getattr(n, field) if n else None
                lines.append(_row(label, pval, nval, precision=prec))
            for field, label, prec in [
                ("proxy_ms_p50", "Proxy ms P50", 3),
                ("proxy_ms_p95", "Proxy ms P95", 3),
                ("proxy_ms_p99", "Proxy ms P99", 3),
            ]:
                pval = getattr(p, field) if p else None
                lines.append(_row(label, pval, None, precision=prec, proxy_only=True))
            lines.append("")

        # Render a flat table for every target that isn't proxy or native.
        for tgt in sorted(t for t in targets if t not in ("proxy", "native")):
            s = targets[tgt]
            label = _TARGET_DISPLAY_NAMES.get(tgt, tgt)
            sep = "-" * (len(label) + 2)
            lines += [
                f"| Metric | {label} |",
                f"|--------|{sep}|",
            ]
            for field_name, metric_label, precision in _SINGLE_TARGET_METRICS:
                val: float | None = getattr(s, field_name)
                lines.append(f"| {metric_label} | {_fmt(val, precision)} |")
            lines.append("")

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
    "ttft_p50_ms": ("TTFT P50 (ms)", 2),
    "ttft_p95_ms": ("TTFT P95 (ms)", 2),
    "ttft_p99_ms": ("TTFT P99 (ms)", 2),
    "tpot_p50_ms": ("TPOT P50 (ms)", 2),
    "tpot_p95_ms": ("TPOT P95 (ms)", 2),
    "tpot_p99_ms": ("TPOT P99 (ms)", 2),
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


_COMPLETIONS_LATENCY_METRICS: list[tuple[str, str, int]] = [
    ("latency_p50_ms", "Latency P50 (ms)", 2),
    ("latency_p95_ms", "Latency P95 (ms)", 2),
    ("latency_p99_ms", "Latency P99 (ms)", 2),
    ("throughput_rps", "Throughput (rps)", 2),
    ("request_bytes_mean", "Request bytes (mean)", 0),
    ("response_bytes_mean", "Response bytes (mean)", 0),
]


def write_wire_size_comparison_md(
    summaries: list[RunSummary],
    output_path: Path,
) -> Path:
    """Render Phase 6 completions report: wire-size summary + per-concurrency latency tables."""
    completion_summaries = [
        s for s in summaries if s.request_type in ("completion-text", "completion-embeds")
    ]

    lines: list[str] = [
        "# Phase 6 Completions Benchmark: Wire-Size and Latency",
        "",
        "## Methodology",
        "",
        "- **Native REST**: vLLM's own OpenAI-compatible REST endpoint (text and embeds)",
        "- **Proxy REST**: gRPC proxy REST facade; base64-encodes `torch.save()` bytes for embeds",
        "- **gRPC-direct**: raw proto `bytes` field, no base64 encoding",
        "- Baseline for text completions is native REST (the conventional approach).",
        "- Baseline for embed completions is native REST (isolates protocol from proxy overhead).",
        "",
        "## Wire-Size Summary",
        "",
        "| path | input_type | req_bytes_mean | resp_bytes_mean | Δ vs baseline |",
        "|------|------------|----------------|-----------------|---------------|",
    ]

    # Wire-size: average request/response bytes across concurrency levels
    groups: dict[tuple[str, str], list[RunSummary]] = defaultdict(list)
    for s in completion_summaries:
        groups[(s.target, s.request_type)].append(s)

    group_req_bytes: dict[tuple[str, str], float] = {}
    group_resp_bytes: dict[tuple[str, str], float | None] = {}
    for key, group in groups.items():
        req_vals = [s.request_bytes_mean for s in group if s.request_bytes_mean is not None]
        group_req_bytes[key] = sum(req_vals) / len(req_vals) if req_vals else 0.0
        resp_vals = [s.response_bytes_mean for s in group if s.response_bytes_mean is not None]
        group_resp_bytes[key] = sum(resp_vals) / len(resp_vals) if resp_vals else None

    native_text_bytes = group_req_bytes.get(("native", "completion-text"))
    for target in ("native", "proxy", "grpc-direct"):
        key = (target, "completion-text")
        if key not in group_req_bytes:
            continue
        req_bytes = group_req_bytes[key]
        resp_bytes = group_resp_bytes.get(key)
        resp_str = f"{resp_bytes:.0f}" if resp_bytes is not None else "N/A"
        if target == "native" or native_text_bytes is None:
            delta_str = "baseline"
        else:
            pct = (req_bytes / native_text_bytes - 1) * 100
            sign = "+" if pct >= 0 else ""
            delta_str = f"{sign}{pct:.1f}% vs native-REST"
        lines.append(f"| {target} | completion-text | {req_bytes:.0f} | {resp_str} | {delta_str} |")

    native_embed_bytes = group_req_bytes.get(("native", "completion-embeds"))
    for target in ("native", "proxy", "grpc-direct"):
        key = (target, "completion-embeds")
        if key not in group_req_bytes:
            continue
        req_bytes = group_req_bytes[key]
        resp_bytes = group_resp_bytes.get(key)
        resp_str = f"{resp_bytes:.0f}" if resp_bytes is not None else "N/A"
        if target == "native" or native_embed_bytes is None:
            delta_str = "baseline"
        else:
            pct = (req_bytes / native_embed_bytes - 1) * 100
            sign = "+" if pct >= 0 else ""
            delta_str = f"{sign}{pct:.1f}% vs native-REST"
        lines.append(
            f"| {target} | completion-embeds | {req_bytes:.0f} | {resp_str} | {delta_str} |"
        )

    lines.append("")

    # Latency section: per concurrency, sub-sections per input type
    summary_index: dict[tuple[str, str, int], RunSummary] = {}
    for s in completion_summaries:
        summary_index[(s.target, s.request_type, s.concurrency)] = s

    concurrencies = sorted({s.concurrency for s in completion_summaries})

    for conc in concurrencies:
        lines += [f"## Concurrency = {conc}", ""]

        for req_type, section_title in [
            ("completion-text", "Text Prompt Completions"),
            ("completion-embeds", "Prompt-Embed Completions"),
        ]:
            n = summary_index.get(("native", req_type, conc))
            p = summary_index.get(("proxy", req_type, conc))
            g = summary_index.get(("grpc-direct", req_type, conc))
            if n is None and p is None and g is None:
                continue

            lines += [
                f"### {section_title}",
                "",
                "| metric | native | proxy | Δ vs native | gRPC-direct | Δ vs native |",
                "|--------|--------|-------|-------------|-------------|-------------|",
            ]
            for field, label, precision in _COMPLETIONS_LATENCY_METRICS:
                nv: float | None = getattr(n, field) if n else None
                pv: float | None = getattr(p, field) if p else None
                gv: float | None = getattr(g, field) if g else None
                lines.append(
                    f"| {label} | {_fmt(nv, precision)} | {_fmt(pv, precision)}"
                    f" | {_delta(pv, nv)} | {_fmt(gv, precision)} | {_delta(gv, nv)} |"
                )
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
