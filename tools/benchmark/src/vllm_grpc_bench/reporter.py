from __future__ import annotations

import csv
import dataclasses
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m3_types import (
    CellVerdict,
    Citation,
    M5_1Cell,
    M5_1RunMetadata,
    Recommendation,
    Run,
    RunCohort,
    SchemaCandidateResult,
    SupersedesM1Entry,
    SupersedesM4Entry,
    SupersessionEntry,
)
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


# ---------------------------------------------------------------------------
# M4 report (strict-superset JSON + companion markdown)
# ---------------------------------------------------------------------------


def _cohort_to_m4_dict(c: RunCohort) -> dict[str, object]:
    """Strict-superset JSON shape per ``m4-report-schema.md``.

    Every M3 per-cohort field is preserved verbatim; M4-only fields are
    additive.
    """
    expansion = asdict(c.expansion_record) if c.expansion_record is not None else None
    ttft = c.time_to_first_token_seconds
    return {
        "cell_id": c.cell.cell_id,
        "path": c.cell.path,
        "hidden_size": c.cell.hidden_size,
        "config_name": c.cell.channel_config.name,
        "config_axis": c.cell.channel_config.axis,
        "corpus_subset": c.cell.corpus_subset,
        "iterations": c.cell.iterations,
        "n_successful": c.n_successful,
        "measurable": c.measurable,
        "off_canonical": c.cell.off_canonical,
        "bytes": {
            "mean": c.bytes_mean,
            "ci_low": c.bytes_ci_low,
            "ci_high": c.bytes_ci_high,
        },
        "time_seconds": {
            "mean": c.time_mean,
            "ci_low": c.time_ci_low,
            "ci_high": c.time_ci_high,
        },
        "is_baseline": c.is_baseline,
        "baseline_role": c.baseline_role,
        "expansion_record": expansion,
        "client_bound": c.client_bound,
        "time_to_first_token_seconds": (
            {"mean": ttft[0], "ci_low": ttft[1], "ci_high": ttft[2]} if ttft is not None else None
        ),
        # FR-005 / R-11: within-cohort CV on the verdict metric, surfaced for
        # reader adjudication. `noisy_baseline` is set on baseline cohorts whose
        # verdict-metric CV exceeded the run's `baseline_cv_warn` threshold.
        "time_cv": c.time_cv,
        "ttft_cv": c.ttft_cv,
        "noisy_baseline": c.noisy_baseline,
    }


def _supersession_to_dict(entry: SupersessionEntry) -> dict[str, object]:
    return {
        "m3_cell_id": entry.m3_cell_id,
        "m3_verdict": entry.m3_verdict,
        "m4_cell_id": entry.m4_cell_id,
        "m4_verdict": entry.m4_verdict,
        "rationale": entry.rationale,
    }


def _schema_candidate_to_dict(result: SchemaCandidateResult) -> dict[str, object]:
    return {
        "candidate_name": result.candidate_name,
        "proto_file": result.proto_file,
        "measured_widths": list(result.measured_widths),
        "per_width": [
            {
                "hidden_size": pw.hidden_size,
                "frozen_baseline_cohort_id": pw.frozen_baseline_cohort_id,
                "candidate_cohort_id": pw.candidate_cohort_id,
                "bytes_verdict": pw.bytes_verdict,
                "time_verdict": pw.time_verdict,
                "primary_metric": pw.primary_metric,
                "delta_bytes_pct": pw.delta_bytes_pct,
                "delta_time_pct": pw.delta_time_pct,
                "ci_overlap_initial": pw.ci_overlap_initial,
                "expanded": pw.expanded,
            }
            for pw in result.per_width
        ],
        "is_negative_result": result.is_negative_result,
        "notes": result.notes,
    }


def write_m4_json(run: Run, path: Path) -> Path:
    """Write the M4 report JSON in the strict-superset schema (FR-015 / R-7)."""
    payload: dict[str, object] = {
        "mode": run.mode,
        "axes": list(run.axes),
        "widths": list(run.widths),
        "paths": list(run.paths),
        "iterations_per_cell": run.iterations_per_cell,
        "seed": run.seed,
        "p2_revision": run.p2_revision,
        "frozen_channel": run.frozen_channel,
        "cohorts": [_cohort_to_m4_dict(c) for c in run.cohorts],
        "pacing_mode": run.pacing_mode,
        "shared_baseline_cohort_ids": run.shared_baseline_cohort_ids,
        "frozen_channel_baselines": (
            {
                p: {
                    "path": fb.path,
                    "cohort_id": fb.cohort_id,
                    "channel_config_name": fb.channel_config_name,
                    "per_axis_winners": dict(fb.per_axis_winners),
                    "measured_at_hidden_size": fb.measured_at_hidden_size,
                }
                for p, fb in run.frozen_channel_baselines.items()
            }
            if run.frozen_channel_baselines is not None
            else None
        ),
        "supersedes": [_supersession_to_dict(e) for e in run.supersedes],
        "candidate_sizing_policy": run.candidate_sizing_policy,
        "loopback_caveat_axes": (
            list(run.loopback_caveat_axes) if run.loopback_caveat_axes is not None else None
        ),
        "schema_candidate_results": [
            _schema_candidate_to_dict(r) for r in run.schema_candidate_results
        ],
        "recommendations": [
            {
                "axis": r.axis,
                "applies_to_path": r.applies_to_path,
                "applies_to_widths": sorted(r.applies_to_widths),
                "verdict": r.verdict,
                "winning_config": (r.winning_config.name if r.winning_config is not None else None),
                "winning_delta_pct": r.winning_delta_pct,
                "winning_metric": r.winning_metric,
                "baseline_ci_upper": r.baseline_ci_upper,
                "candidate_ci_lower": r.candidate_ci_lower,
                "citation": r.citation,
                "notes": r.notes,
                "corpus_subset": r.corpus_subset,
            }
            for r in run.recommendations
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def write_m4_markdown(run: Run, path: Path) -> Path:
    """Write the human-readable M4 report companion."""
    lines: list[str] = [
        "# M4: Time-Axis Channel & Schema Tuning",
        "",
        "## Methodology",
        "",
        f"- Pacing mode: `{run.pacing_mode}`",
        f"- Shared baseline cohort ids: `{run.shared_baseline_cohort_ids}`",
        f"- Sample policy: {run.candidate_sizing_policy}",
        f"- Loopback caveat axes: {run.loopback_caveat_axes}",
        f"- Seed: {run.seed}",
        "",
        "## Verdicts",
        "",
        "| axis | path | hidden_size | verdict | winning_config | Δ% | citation |",
        "|------|------|-------------|---------|----------------|----|----------|",
    ]
    for r in run.recommendations:
        widths = ",".join(str(w) for w in sorted(r.applies_to_widths))
        winning = r.winning_config.name if r.winning_config is not None else "-"
        delta = f"{r.winning_delta_pct:+.2f}%" if r.winning_delta_pct is not None else "-"
        lines.append(
            f"| {r.axis} | {r.applies_to_path} | {widths} | {r.verdict} "
            f"| {winning} | {delta} | {r.citation} |"
        )

    baseline_cohorts = [c for c in run.cohorts if c.is_baseline]
    if baseline_cohorts:
        lines += [
            "",
            "## Baseline within-cohort CV (FR-005)",
            "",
            "Per-cohort coefficient of variation (stddev/mean) on the verdict metric. "
            "The harness records this for every baseline cohort; cohorts marked "
            "`noisy` exceeded the run's `--baseline-cv-warn` threshold and verdicts "
            "derived from them carry extra uncertainty (see research.md R-11).",
            "",
            "| baseline cohort | role | metric | CV | noisy? |",
            "|-----------------|------|--------|----|--------|",
        ]
        for c in baseline_cohorts:
            metric = "ttft" if c.cell.path == "chat_stream" else "time"
            cv = c.ttft_cv if metric == "ttft" else c.time_cv
            cv_str = f"{cv:.4f}" if cv is not None else "n/a"
            noisy = "yes" if c.noisy_baseline else "no"
            lines.append(
                f"| `{c.cell.cell_id}` | {c.baseline_role} | {metric} | {cv_str} | {noisy} |"
            )

    if run.frozen_channel_baselines:
        lines += ["", "## Per-path frozen-channel baselines", ""]
        for path_name, fb in run.frozen_channel_baselines.items():
            lines.append(
                f"- **{path_name}** → cohort `{fb.cohort_id}` "
                f"@ hidden_size={fb.measured_at_hidden_size}; "
                f"per-axis winners: {fb.per_axis_winners}"
            )

    if run.supersedes:
        lines += [
            "",
            "## Supersedes M3",
            "",
            "| M3 cell | M3 verdict | M4 cell | M4 verdict | rationale |",
            "|---------|------------|---------|------------|-----------|",
        ]
        for entry in run.supersedes:
            lines.append(
                f"| {entry.m3_cell_id} | {entry.m3_verdict} "
                f"| {entry.m4_cell_id} | {entry.m4_verdict} | {entry.rationale} |"
            )

    if run.loopback_caveat_axes:
        lines += [
            "",
            "## Loopback caveat",
            "",
            "These axes' verdicts apply to single-host loopback runs only — "
            "RTT-bounded behaviour cannot manifest on `127.0.0.1` (R-6):",
            "",
        ]
        for axis in run.loopback_caveat_axes:
            lines.append(f"- `{axis}`")

    if run.schema_candidate_results:
        lines += ["", "## Schema candidates", ""]
        for sc in run.schema_candidate_results:
            lines.append(
                f"### `{sc.candidate_name}` "
                f"({'negative result' if sc.is_negative_result else 'measured'})"
            )
            if sc.notes:
                lines.append(f"> {sc.notes}")
            lines.append("")
            if sc.per_width:
                lines.append("| width | bytes | time | primary | Δbytes% | Δtime% | expanded |")
                lines.append("|-------|-------|------|---------|---------|--------|----------|")
                for pw in sc.per_width:
                    lines.append(
                        f"| {pw.hidden_size} | {pw.bytes_verdict} | "
                        f"{pw.time_verdict} | {pw.primary_metric} | "
                        f"{pw.delta_bytes_pct} | {pw.delta_time_pct} | "
                        f"{pw.expanded} |"
                    )
                lines.append("")
        negatives = [r for r in run.schema_candidate_results if r.is_negative_result]
        if negatives:
            lines += ["", "## Negative results", ""]
            for sc in negatives:
                lines.append(
                    f"- `{sc.candidate_name}` — bytes and time both `no_winner` "
                    f"at every measured width (FR-014)."
                )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


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


# ---------------------------------------------------------------------------
# M5 report (strict-superset of M4 JSON + Markdown companion)
# ---------------------------------------------------------------------------


def _cohort_to_m5_1_dict(c: RunCohort, sample_size: int) -> dict[str, object]:
    """M5.1 cohort shape: M5 superset + protocol/grpc_channel_model/etc.

    ``sample_size`` is explicitly threaded so the reporter can record the
    actual cohort n (M5.1 cohorts don't carry it on ``RunCohort.cell.iterations``
    because the dispatcher tracks n separately).
    """
    base = _cohort_to_m5_dict(c)
    base["sample_size"] = sample_size
    base["protocol"] = c.protocol
    base["grpc_channel_model"] = c.grpc_channel_model
    base["connection_count"] = c.connection_count
    base["shim_overhead_ms"] = c.shim_overhead_ms
    base["comparison_cell_key"] = c.comparison_cell_key
    if c.rest_cohort_record is not None:
        base["rest_cohort_record"] = {
            "shim_overhead_ms_median": c.rest_cohort_record.shim_overhead_ms_median,
            "shim_overhead_ms_p95": c.rest_cohort_record.shim_overhead_ms_p95,
            "connections_opened": c.rest_cohort_record.connections_opened,
            "connections_keepalive_reused": c.rest_cohort_record.connections_keepalive_reused,
            "request_bytes_median": c.rest_cohort_record.request_bytes_median,
            "request_bytes_p95": c.rest_cohort_record.request_bytes_p95,
            "response_bytes_median": c.rest_cohort_record.response_bytes_median,
            "response_bytes_p95": c.rest_cohort_record.response_bytes_p95,
        }
    else:
        base["rest_cohort_record"] = None
    return base


def _cohort_to_m5_dict(c: RunCohort) -> dict[str, object]:
    """M5 cohort shape: M4 fields + RTT/server_bound/low_rtt_caveat/discarded.

    Per contract m5-report-schema.md, the M5 cohort entry is a strict
    superset of M4's. Schema-additive only; M4-reader compatibility
    preserved by emitting ``loopback_caveat: false`` on every M5 cohort
    (FR-007 says M5 cells never carry the loopback caveat).
    """
    base = _cohort_to_m4_dict(c)
    base["loopback_caveat"] = False  # M4-reader compat: every M5 cell is `false`.
    base["rtt_record"] = (
        {
            "n": c.rtt_record.n,
            "median_ms": c.rtt_record.median_ms,
            "p95_ms": c.rtt_record.p95_ms,
            "samples_ms": list(c.rtt_record.samples_ms),
        }
        if c.rtt_record is not None
        else None
    )
    base["server_overhead_estimate_ms"] = c.server_overhead_estimate_ms
    base["server_bound"] = c.server_bound
    base["low_rtt_caveat"] = c.low_rtt_caveat
    base["discarded"] = c.discarded
    return base


def _citation_to_dict(citation: Citation) -> dict[str, object]:
    return {
        "repo": citation.repo,
        "file_path": citation.file_path,
        "identifier": citation.identifier,
        "justification": citation.justification,
    }


def _supersedes_m4_to_dict(entry: SupersedesM4Entry) -> dict[str, object]:
    return {
        "m4_axis": entry.m4_axis,
        "m4_hidden_size": entry.m4_hidden_size,
        "m4_path": entry.m4_path,
        "m4_verdict_time": entry.m4_verdict_time,
        "m4_verdict_bytes": entry.m4_verdict_bytes,
        "m4_loopback_caveat": entry.m4_loopback_caveat,
        "m5_verdict_time": entry.m5_verdict_time,
        "m5_verdict_bytes": entry.m5_verdict_bytes,
        "m5_supporting_ci_lower": entry.m5_supporting_ci_lower,
        "m5_supporting_ci_upper": entry.m5_supporting_ci_upper,
        "rationale": entry.rationale,
        "verdict_changed": entry.verdict_changed,
        "expected_class": entry.expected_class,
        "citations": [_citation_to_dict(c) for c in entry.citations],
    }


def _m5_recommendation_to_dict(r: Recommendation) -> dict[str, object]:
    out: dict[str, object] = {
        "axis": r.axis,
        "applies_to_path": r.applies_to_path,
        "applies_to_widths": sorted(r.applies_to_widths),
        "verdict": r.verdict,
        "winning_config": r.winning_config.name if r.winning_config is not None else None,
        "winning_delta_pct": r.winning_delta_pct,
        "winning_metric": r.winning_metric,
        "baseline_ci_upper": r.baseline_ci_upper,
        "candidate_ci_lower": r.candidate_ci_lower,
        "citation": r.citation,
        "notes": r.notes,
        "corpus_subset": r.corpus_subset,
        "supersedes_m4_cell": (
            _supersedes_m4_to_dict(r.supersedes_m4_cell)
            if r.supersedes_m4_cell is not None
            else None
        ),
    }
    return out


def write_m5_json(run: Run, path: Path) -> Path:
    """Write the M5 report JSON in the strict-superset schema (FR-014)."""
    meta = run.m5_metadata
    rtt_summary = (
        {
            "min": meta.m5_rtt_summary_ms.min_ms,
            "median": meta.m5_rtt_summary_ms.median_ms,
            "p95": meta.m5_rtt_summary_ms.p95_ms,
            "max": meta.m5_rtt_summary_ms.max_ms,
        }
        if meta is not None
        else None
    )
    payload: dict[str, object] = {
        # --- M4-shape fields (preserved unchanged) ---
        "mode": run.mode,
        "axes": list(run.axes),
        "widths": list(run.widths),
        "paths": list(run.paths),
        "iterations_per_cell": run.iterations_per_cell,
        "seed": run.seed,
        "p2_revision": run.p2_revision,
        "frozen_channel": run.frozen_channel,
        "pacing_mode": run.pacing_mode,
        "shared_baseline_cohort_ids": run.shared_baseline_cohort_ids,
        "frozen_channel_baselines": (
            {
                p: {
                    "path": fb.path,
                    "cohort_id": fb.cohort_id,
                    "channel_config_name": fb.channel_config_name,
                    "per_axis_winners": dict(fb.per_axis_winners),
                    "measured_at_hidden_size": fb.measured_at_hidden_size,
                }
                for p, fb in run.frozen_channel_baselines.items()
            }
            if run.frozen_channel_baselines is not None
            else None
        ),
        "cohorts": [_cohort_to_m5_dict(c) for c in run.cohorts],
        "supersedes": [_supersession_to_dict(e) for e in run.supersedes],
        "candidate_sizing_policy": run.candidate_sizing_policy,
        "loopback_caveat_axes": (
            list(run.loopback_caveat_axes) if run.loopback_caveat_axes is not None else None
        ),
        "schema_candidate_results": [
            _schema_candidate_to_dict(r) for r in run.schema_candidate_results
        ],
        "recommendations": [_m5_recommendation_to_dict(r) for r in run.recommendations],
        # --- M5-only top-level additions ---
        "m5_methodology_version": meta.m5_methodology_version if meta is not None else 1,
        "m5_modal_app_name": meta.m5_modal_app_name if meta is not None else None,
        "m5_modal_region": meta.m5_modal_region if meta is not None else None,
        "m5_runtime_wallclock_seconds": (
            meta.m5_runtime_wallclock_seconds if meta is not None else None
        ),
        "m5_rtt_summary_ms": rtt_summary,
        "rtt_validity_threshold_ms": (meta.rtt_validity_threshold_ms if meta is not None else None),
        "rtt_exercise_threshold_ms": (meta.rtt_exercise_threshold_ms if meta is not None else None),
        "warmup_n": meta.warmup_n if meta is not None else None,
        "server_bound_overhead_threshold_ms": (
            meta.server_bound_overhead_threshold_ms if meta is not None else None
        ),
        "server_bound_cohort_count": (meta.server_bound_cohort_count if meta is not None else 0),
        "m5_cross_host_baselines": {
            p: {
                "path": b.path,
                "cohort_id": b.cohort_id,
                "modal_app_name": b.modal_app_name,
                "modal_region": b.modal_region,
                "measured_rtt": {
                    "n": b.measured_rtt.n,
                    "median_ms": b.measured_rtt.median_ms,
                    "p95_ms": b.measured_rtt.p95_ms,
                    "samples_ms": list(b.measured_rtt.samples_ms),
                },
                "n": b.n,
            }
            for p, b in run.m5_cross_host_baselines.items()
        },
        "supersedes_m4": [_supersedes_m4_to_dict(e) for e in run.supersedes_m4],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def write_m5_markdown(run: Run, path: Path) -> Path:
    """Write the human-readable M5 report companion.

    Section order matches quickstart.md "Reading the report":
      1. Methodology preamble
      2. Channel-sweep verdict table
      3. Frozen-channel baselines (US2)
      4. Schema-candidate verdicts (US2)
      5. Supersedes M4 table (US3) — verdict-changed rows distinguished
      6. Negative results appendix (US2)
      7. Executive summary footer
    """
    meta = run.m5_metadata
    lines: list[str] = [
        "# M5: Cross-Host Time-Axis Validation",
        "",
        "## Methodology",
        "",
    ]
    if meta is not None:
        rtt = meta.m5_rtt_summary_ms
        lines += [
            f"- Modal app: `{meta.m5_modal_app_name}` (region `{meta.m5_modal_region}`)",
            f"- Methodology version: `{meta.m5_methodology_version}`",
            f"- Runtime wall-clock: {meta.m5_runtime_wallclock_seconds:.1f} s",
            (
                f"- Measured RTT (run-wide, ms): "
                f"min={rtt.min_ms:.2f} median={rtt.median_ms:.2f} "
                f"p95={rtt.p95_ms:.2f} max={rtt.max_ms:.2f}"
            ),
            (
                f"- Thresholds: validity={meta.rtt_validity_threshold_ms} ms · "
                f"exercise={meta.rtt_exercise_threshold_ms} ms · "
                f"server_bound_overhead_floor={meta.server_bound_overhead_threshold_ms} ms"
            ),
            f"- Warmup cohort size per path: {meta.warmup_n}",
            (
                "- Server-bound cohorts excluded from recommendations: "
                f"{meta.server_bound_cohort_count}"
            ),
        ]
    lines += [
        f"- Pacing mode: `{run.pacing_mode}`",
        f"- Shared baseline cohort ids: `{run.shared_baseline_cohort_ids}`",
        f"- Sample policy: {run.candidate_sizing_policy}",
        f"- Seed: {run.seed}",
        "",
        "## Verdicts",
        "",
        "| axis | path | hidden_size | verdict | winning_config | Δ% | citation |",
        "|------|------|-------------|---------|----------------|----|----------|",
    ]
    for r in run.recommendations:
        widths = ",".join(str(w) for w in sorted(r.applies_to_widths))
        winning = r.winning_config.name if r.winning_config is not None else "-"
        delta = f"{r.winning_delta_pct:+.2f}%" if r.winning_delta_pct is not None else "-"
        lines.append(
            f"| {r.axis} | {r.applies_to_path} | {widths} | {r.verdict} "
            f"| {winning} | {delta} | {r.citation} |"
        )

    if run.frozen_channel_baselines:
        lines += ["", "## Per-path frozen-channel baselines", ""]
        for path_name, fb in run.frozen_channel_baselines.items():
            lines.append(
                f"- **{path_name}** → cohort `{fb.cohort_id}` "
                f"@ hidden_size={fb.measured_at_hidden_size}; "
                f"per-axis winners: {fb.per_axis_winners}"
            )

    if run.schema_candidate_results:
        lines += ["", "## Schema candidates", ""]
        for sc in run.schema_candidate_results:
            lines.append(
                f"### `{sc.candidate_name}` "
                f"({'negative result' if sc.is_negative_result else 'measured'})"
            )
            if sc.notes:
                lines.append(f"> {sc.notes}")
            lines.append("")

    # Supersedes M4 table — sort verdict-changed first, then unexpected
    # supersessions get their own sub-heading per spec Edge Cases.
    if run.supersedes_m4:
        normal_entries = [
            e for e in run.supersedes_m4 if e.expected_class != "unexpected_supersession"
        ]
        normal_entries.sort(
            key=lambda e: (not e.verdict_changed, e.m4_path, e.m4_axis, e.m4_hidden_size)
        )
        unexpected = [e for e in run.supersedes_m4 if e.expected_class == "unexpected_supersession"]
        lines += [
            "",
            "## Supersedes M4",
            "",
            (
                "| flag | M4 cell | M4 verdict (time/bytes) | M5 verdict (time/bytes) | "
                "M5 CI | class | rationale |"
            ),
            "|------|---------|-------------------------|-------------------------|-------|-------|-----------|",
        ]
        for e in normal_entries:
            marker = "**[changed]**" if e.verdict_changed else ""
            m4 = f"{e.m4_axis}/h{e.m4_hidden_size}/{e.m4_path}"
            m4v = f"{e.m4_verdict_time}/{e.m4_verdict_bytes}"
            m5v = f"{e.m5_verdict_time}/{e.m5_verdict_bytes}"
            ci = f"[{e.m5_supporting_ci_lower:.4g}, {e.m5_supporting_ci_upper:.4g}]"
            rationale = e.rationale
            if e.citations:
                cite_refs = "; ".join(
                    f"{c.repo}:{c.file_path}" + (f"#{c.identifier}" if c.identifier else "")
                    for c in e.citations
                )
                rationale = f"{rationale} (citations: {cite_refs})"
            lines.append(
                f"| {marker} | `{m4}` | {m4v} | {m5v} | {ci} | {e.expected_class} | {rationale} |"
            )
        if unexpected:
            lines += [
                "",
                "### Unexpected supersessions — investigate before adopting",
                "",
                (
                    "| flag | M4 cell | M4 verdict (time/bytes) | M5 verdict (time/bytes) | "
                    "M5 CI | rationale |"
                ),
                "|------|---------|-------------------------|-------------------------|-------|-----------|",
            ]
            for e in unexpected:
                m4 = f"{e.m4_axis}/h{e.m4_hidden_size}/{e.m4_path}"
                m4v = f"{e.m4_verdict_time}/{e.m4_verdict_bytes}"
                m5v = f"{e.m5_verdict_time}/{e.m5_verdict_bytes}"
                ci = f"[{e.m5_supporting_ci_lower:.4g}, {e.m5_supporting_ci_upper:.4g}]"
                lines.append(
                    f"| **[unexpected]** | `{m4}` | {m4v} | {m5v} | {ci} | {e.rationale} |"
                )

    # Negative results appendix (US2).
    negatives = [r for r in run.schema_candidate_results if r.is_negative_result]
    if negatives:
        lines += [
            "",
            "## Appendix: Negative results — do not re-run speculatively",
            "",
        ]
        for sc in negatives:
            lines.append(
                f"- `{sc.candidate_name}` — bytes and time both `no_winner` "
                f"at every measured width (FR-013)."
            )

    # Executive summary footer.
    if meta is not None:
        n_recommend = sum(1 for r in run.recommendations if r.verdict == "recommend")
        n_no_winner = sum(1 for r in run.recommendations if r.verdict == "no_winner")
        n_client_bound = sum(1 for r in run.recommendations if r.verdict == "client_bound")
        n_server_bound = sum(1 for r in run.recommendations if r.verdict == "server_bound")
        n_cohorts = sum(1 for c in run.cohorts if not c.discarded)
        lines += [
            "",
            "## Executive summary",
            "",
            (
                f"- Runtime wall-clock: {meta.m5_runtime_wallclock_seconds:.1f} s · "
                f"non-discarded cohorts: {n_cohorts} · "
                f"region: {meta.m5_modal_region}"
            ),
            (
                f"- Verdicts: {n_recommend} recommend · {n_no_winner} no_winner · "
                f"{n_client_bound} client_bound · {n_server_bound} server_bound"
            ),
            (
                f"- RTT median: {meta.m5_rtt_summary_ms.median_ms:.1f} ms · "
                f"p95: {meta.m5_rtt_summary_ms.p95_ms:.1f} ms"
            ),
            f"- M4 cells superseded: {len(run.supersedes_m4)} "
            f"({sum(1 for e in run.supersedes_m4 if e.verdict_changed)} verdict-changed)",
        ]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


# ---------------------------------------------------------------------------
# M5.1 report writers (specs/018-m5-1-rest-vs-grpc/contracts/m5_1-report-schema.md)
# ---------------------------------------------------------------------------


def _cell_verdict_to_dict(v: CellVerdict) -> dict[str, Any]:
    return {
        "grpc_sub_cohort": v.grpc_sub_cohort,
        "verdict": v.verdict,
        "delta_pct": v.delta_pct,
        "ci_pct": list(v.ci_pct),
        "metric": v.metric,
    }


def _m5_1_cell_to_dict(cell: M5_1Cell) -> dict[str, Any]:
    return {
        "path": cell.path,
        "hidden_size": cell.hidden_size,
        "concurrency": cell.concurrency,
        "comparison_cell_key": cell.comparison_cell_key,
        "rest_cohort_key": cell.rest_cohort_key,
        "tuned_grpc_multiplexed_cohort_key": cell.tuned_grpc_multiplexed_cohort_key,
        "tuned_grpc_channels_cohort_key": cell.tuned_grpc_channels_cohort_key,
        "default_grpc_cohort_key": cell.default_grpc_cohort_key,
        "verdicts": [_cell_verdict_to_dict(v) for v in cell.verdicts],
        "comparison_unavailable": cell.comparison_unavailable,
        "comparison_unavailable_reason": cell.comparison_unavailable_reason,
        "rtt_ms_median": cell.rtt_ms_median,
        "rtt_ms_p95": cell.rtt_ms_p95,
        "low_rtt_caveat": cell.low_rtt_caveat,
    }


def _supersedes_m1_entry_to_dict(entry: SupersedesM1Entry) -> dict[str, Any]:
    return {
        "m1_path": entry.m1_path,
        "m1_concurrency": entry.m1_concurrency,
        "m1_verdict_literal": entry.m1_verdict_literal,
        "m1_source_report": entry.m1_source_report,
        "m5_1_verdict_per_width": {str(k): v for k, v in entry.m5_1_verdict_per_width.items()},
        "m5_1_supporting_delta_pct": {
            str(k): v for k, v in entry.m5_1_supporting_delta_pct.items()
        },
        "m5_1_supporting_ci_pct": {
            str(k): list(v) for k, v in entry.m5_1_supporting_ci_pct.items()
        },
        "classification": entry.classification,
        "comparison_basis": entry.comparison_basis,
        "rationale": entry.rationale,
    }


def _m5_1_run_metadata_to_dict(meta: M5_1RunMetadata) -> dict[str, Any]:
    shim_overhead = meta.shim_overhead
    return {
        "modal_app_handle": meta.modal_app_handle,
        "modal_region": meta.modal_region,
        "modal_instance_class": meta.modal_instance_class,
        "rest_shim_version_sha": meta.rest_shim_version_sha,
        "rest_shim_uvicorn_workers": meta.rest_shim_uvicorn_workers,
        "auth_token_env_var": meta.auth_token_env_var,
        "shim_overhead": {
            "shim_overhead_ms_median_across_run": shim_overhead.shim_overhead_ms_median_across_run,
            "shim_overhead_ms_p95_across_run": shim_overhead.shim_overhead_ms_p95_across_run,
            "shim_overhead_ms_max_across_run": shim_overhead.shim_overhead_ms_max_across_run,
            "shim_overhead_material_in_any_cohort": (
                shim_overhead.shim_overhead_material_in_any_cohort
            ),
        },
        "m5_1_matrix": [_m5_1_cell_to_dict(c) for c in meta.m5_1_matrix],
        "supersedes_m1_time": [_supersedes_m1_entry_to_dict(e) for e in meta.supersedes_m1_time],
    }


def write_m5_1_json(
    run_metadata: M5_1RunMetadata,
    cohorts: list[RunCohort],
    sample_size: int,
    path: Path,
    *,
    run_id: str = "",
    run_started_at: str = "",
    run_completed_at: str = "",
    harness_version_sha: str = "",
) -> Path:
    """Write the M5.1 report JSON per the strict-superset schema (FR-014).

    Every M5 top-level key is present (with empty arrays where M5.1 does not
    measure that axis); M5.1-specific keys live in new namespaces:
    ``m5_1_matrix``, ``supersedes_m1_time``, ``rest_shim_meta``,
    ``auth_token_env_var``.
    """
    meta_dict = _m5_1_run_metadata_to_dict(run_metadata)
    payload = {
        # M5 keys (preserved for compatibility; empty arrays where N/A).
        "run_id": run_id,
        "run_started_at": run_started_at,
        "run_completed_at": run_completed_at,
        "harness_version_sha": harness_version_sha,
        "shared_baseline_cohorts": [],
        "channel_axis_recommendations": [],
        "schema_candidate_recommendations": [],
        "supersedes_m4": [],
        "supersedes_m3": [],
        "rtt_distribution": {},
        "modal_metadata": {
            "modal_app_handle": meta_dict["modal_app_handle"],
            "modal_region": meta_dict["modal_region"],
            "modal_instance_class": meta_dict["modal_instance_class"],
        },
        # M5.1-specific top-level keys.
        "m5_1_matrix": meta_dict["m5_1_matrix"],
        "supersedes_m1_time": meta_dict["supersedes_m1_time"],
        "rest_shim_meta": {
            "shim_version_sha": meta_dict["rest_shim_version_sha"],
            "uvicorn_workers": meta_dict["rest_shim_uvicorn_workers"],
            "shim_overhead_ms_median_across_run": meta_dict["shim_overhead"][
                "shim_overhead_ms_median_across_run"
            ],
            "shim_overhead_ms_p95_across_run": meta_dict["shim_overhead"][
                "shim_overhead_ms_p95_across_run"
            ],
            "shim_overhead_ms_max_across_run": meta_dict["shim_overhead"][
                "shim_overhead_ms_max_across_run"
            ],
            "shim_overhead_material_in_any_cohort": meta_dict["shim_overhead"][
                "shim_overhead_material_in_any_cohort"
            ],
        },
        "auth_token_env_var": meta_dict["auth_token_env_var"],
        # Cohort-level entries.
        "cohorts": [_cohort_to_m5_1_dict(c, sample_size) for c in cohorts],
    }
    # Token-shaped string guard (defensive; the harness never threads tokens
    # into the report, but a regex check costs nothing).
    import re

    blob = json.dumps(payload, default=str)
    if re.search(r"Bearer ", blob):
        raise RuntimeError(
            "write_m5_1_json: bearer-token-shaped string detected in report payload; "
            "refusing to write"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(blob if False else json.dumps(payload, indent=2, default=str))
    return path


def write_m5_1_markdown(run_metadata: M5_1RunMetadata, path: Path) -> Path:
    """Render the M5.1 Markdown report per FR-015."""
    lines: list[str] = ["# M5.1: REST vs gRPC Head-to-Head on Real Wire", ""]
    matrix = list(run_metadata.m5_1_matrix)

    lines.append("## Executive summary")
    lines.append("")
    n_unavailable = sum(1 for c in matrix if c.comparison_unavailable)
    n_low_rtt = sum(1 for c in matrix if c.low_rtt_caveat)
    lines.append(
        f"- 18-cell head-to-head matrix (2 paths × 3 widths × 3 concurrencies). "
        f"{n_unavailable} `comparison_unavailable`, {n_low_rtt} `low_rtt_caveat`."
    )
    lines.append(
        "- Bytes-axis findings from M1 (89% chat response reduction, ~25% embed "
        "request reduction) remain in force unchanged (FR-021) — M5.1 measures "
        "time only."
    )
    lines.append(
        "- **Read instruction**: M5.1 measures MockEngine, not real vLLM. Engine "
        "cost is held constant across protocols so the verdict reflects the "
        "transport + framing component only. Real-engine re-validation is "
        "deferred to M7."
    )
    lines.append(
        "- **Methodology — Modal tunnel topology**: both protocols use Modal's "
        "plain-TCP `modal.forward(..., unencrypted=True)` so the network path is "
        "held constant. The original spec assumed REST would use Modal's HTTPS "
        "edge (TLS-terminated, anycast-routed near client); the smoke run "
        "measured a ~2× RTT gap that would have dominated every verdict. The "
        "FR-019 'REST uses Modal-managed TLS' assumption is voided for M5.1, "
        "accepted per Constitution V. M1 ran REST over the HTTPS edge — that "
        "difference is part of why M5.1 supersedes M1's time-axis findings."
    )
    lines.append("")

    lines.append("## Per-cell comparison matrix")
    lines.append("")
    for path_name in ("chat_stream", "embed"):
        path_cells = [c for c in matrix if c.path == path_name]
        if not path_cells:
            continue
        lines.append(f"### {path_name}")
        lines.append("")
        for hidden_size in (2048, 4096, 8192):
            width_cells = [c for c in path_cells if c.hidden_size == hidden_size]
            if not width_cells:
                continue
            lines.append(f"#### h={hidden_size}")
            lines.append("")
            lines.append("| concurrency | sub-cohort | verdict | delta % | 95% CI |")
            lines.append("|-------------|------------|---------|---------|--------|")
            for cell in sorted(width_cells, key=lambda c: c.concurrency):
                if cell.comparison_unavailable:
                    lines.append(f"| {cell.concurrency} | — | comparison_unavailable | — | — |")
                else:
                    for v in cell.verdicts:
                        lines.append(
                            f"| {cell.concurrency} | `{v.grpc_sub_cohort}` | "
                            f"`{v.verdict}` | {v.delta_pct:+.1f}% | "
                            f"[{v.ci_pct[0]:+.1f}, {v.ci_pct[1]:+.1f}] |"
                        )
            lines.append("")

    lines.append("## REST shim overhead appendix")
    lines.append("")
    shim = run_metadata.shim_overhead
    lines.append(f"- Median across run: {shim.shim_overhead_ms_median_across_run:.3f} ms")
    lines.append(f"- p95 across run: {shim.shim_overhead_ms_p95_across_run:.3f} ms")
    lines.append(f"- Max across run: {shim.shim_overhead_ms_max_across_run:.3f} ms")
    if shim.shim_overhead_material_in_any_cohort:
        lines.append(
            "- ⚠️ Shim plumbing was material (>5ms) in at least one cohort — "
            "REST-side time includes a non-negligible FastAPI handler overhead."
        )
    lines.append("")

    if run_metadata.supersedes_m1_time:
        lines.append("## Supersedes M1 (time-axis)")
        lines.append("")
        lines.append("| M1 path | c | M1 verdict | M5.1 verdicts by width | classification |")
        lines.append("|---------|---|------------|-----------------------|----------------|")
        for entry in run_metadata.supersedes_m1_time:
            wm = entry.m5_1_verdict_per_width
            widths_str = ", ".join(f"h{w}={wm[w]}" for w in sorted(wm))
            marker = "**" if entry.classification == "verdict_changed" else ""
            lines.append(
                f"| {marker}{entry.m1_path}{marker} | {entry.m1_concurrency} | "
                f"{entry.m1_verdict_literal} | {widths_str} | "
                f"{marker}{entry.classification}{marker} |"
            )
        lines.append("")

    lines.append("## Negative results — do not re-run speculatively")
    lines.append("")
    negative = [c for c in matrix if any(v.verdict == "no_winner" for v in c.verdicts)]
    if negative:
        lines.append(
            "Cells with at least one `no_winner` verdict (Constitution V — these "
            "are honestly reported negative results, not measurement bugs):"
        )
        lines.append("")
        for cell in negative:
            no_winners = [v for v in cell.verdicts if v.verdict == "no_winner"]
            for v in no_winners:
                lines.append(
                    f"- {cell.comparison_cell_key} / `{v.grpc_sub_cohort}`: "
                    f"delta {v.delta_pct:+.1f}% "
                    f"(CI [{v.ci_pct[0]:+.1f}, {v.ci_pct[1]:+.1f}])"
                )
    else:
        lines.append("- (none — every cell produced a head-to-head verdict)")
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path
