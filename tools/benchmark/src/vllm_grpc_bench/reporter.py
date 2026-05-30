from __future__ import annotations

import csv
import dataclasses
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from vllm_grpc_bench.anchor_trajectory import (
    compute_insufficient_snapshots_header_fired,
    compute_intra_sweep_drift_header_fired,
)
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
from vllm_grpc_bench.null_anchor import (
    compute_null_anchor_drift_header_fired,
)
from vllm_grpc_bench.sweep import (
    compute_failure_summary_header_fired,
)
from vllm_grpc_bench.sweep_types import (
    M6_2_INTERIOR_CAP_MAX_TOKENS,
    M6_2_VALIDATE_MAX_TOKENS_AXIS,
    M6_2AnchorLatencyTrajectory,
    M6_2MeasurementPoint,
    M6_2PromptSource,
    M6_2SweepArtifact,
    M6_2SweepMode,
)
from vllm_grpc_bench.types import (
    CELLS,
    CohortKind,
    M6_1_2NetworkPath,
    M6_1_2NetworkPathError,
)


# === LEGACY M1–M5.2 report writers (consumed by __main__ milestone CLI +
# legacy modules/tests; deleted in the T017-tail after the T018 CLI strip) ===
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


def _fmt_legacy(value: float | None, precision: int = 2) -> str:
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
    pf = _fmt_legacy(pv, precision)
    nf = "N/A" if proxy_only else _fmt_legacy(nv, precision)
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
                lines.append(f"| {metric_label} | {_fmt_legacy(val, precision)} |")
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
            va = _fmt_legacy(row.value_a, precision)
            vb = _fmt_legacy(row.value_b, precision)
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
    """Render the M1 completions report: wire-size summary + per-concurrency latency tables."""
    completion_summaries = [
        s for s in summaries if s.request_type in ("completion-text", "completion-embeds")
    ]

    lines: list[str] = [
        "# Completions Benchmark: Wire-Size and Latency (M1)",
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
                    f"| {label} | {_fmt_legacy(nv, precision)} | {_fmt_legacy(pv, precision)}"
                    f" | {_delta(pv, nv)} | {_fmt_legacy(gv, precision)} | {_delta(gv, nv)} |"
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
            va = _fmt_legacy(row.value_a, precision)
            vb = _fmt_legacy(row.value_b, precision)
            vc = _fmt_legacy(row.value_c, precision)

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


# ---------------------------------------------------------------------------
# M5.2 reporter (T037 + T038)
#
# The M5.2 reporter is invoked by the regenerator (not the sweep); inputs are
# an :class:`M5_2Aggregates` (built from the events sidecar) plus the run
# config dict (loaded from the run config JSON the sweep wrote). Output is
# byte-deterministic markdown + aggregate JSON, suitable for
# byte-identical-round-trip verification by the operator's pre-PR diff.
# ---------------------------------------------------------------------------


def _m5_2_aggregates_to_json_payload(
    aggregates: Any,  # M5_2Aggregates — typed dynamically to avoid an import cycle
    run_config: dict[str, Any],
) -> dict[str, Any]:
    """Build the strict-superset M5.2 aggregate JSON payload.

    Every M5.1 / M5 / M4 top-level key remains present (empty arrays where
    M5.2 doesn't measure that axis); the M5.2-specific keys are
    appended per ``contracts/m5_2-report-schema.md``.
    """
    geo = run_config.get("client_external_geolocation")
    return {
        # M5/M5.1 keys preserved empty for back-compat per FR-013.
        "run_id": run_config.get("run_id", ""),
        "run_started_at": run_config.get("run_started_at_iso", ""),
        "run_completed_at": run_config.get("run_started_at_iso", ""),
        "harness_version_sha": "",
        "shared_baseline_cohorts": [],
        "channel_axis_recommendations": [],
        "schema_candidate_recommendations": [],
        "supersedes_m4": [],
        "supersedes_m3": [],
        "supersedes_m1_time": [],
        "m5_1_matrix": [],
        "rtt_distribution": {},
        "modal_metadata": {
            "modal_app_handle": run_config.get("symmetry", {})
            .get("tier_a", {})
            .get("modal_deploy_handle", ""),
            "modal_region": run_config.get("modal_region", ""),
            "modal_instance_class": run_config.get("modal_instance_class", ""),
        },
        "cohorts": [],
        # M5.2-specific top-level keys per data-model.md JSON delta.
        "m5_2_run": {
            "run_id": run_config.get("run_id", ""),
            "run_started_at_iso": run_config.get("run_started_at_iso", ""),
            "run_realized_runtime_s": run_config.get("run_realized_runtime_s", 0.0),
            "seed": run_config.get("seed", 0),
        },
        "symmetry": run_config.get("symmetry", {}),
        "events_sidecar_path": aggregates.sidecar_path or run_config.get("events_sidecar_path", ""),
        "events_sidecar_sha256": aggregates.sidecar_sha256
        or run_config.get("events_sidecar_sha256", ""),
        "protocol_comparison_verdicts": [
            {
                "ci_lower_ms": row.ci_lower_ms,
                "ci_upper_ms": row.ci_upper_ms,
                "comparison_unavailable_reason": row.comparison_unavailable_reason,
                "concurrency": row.concurrency,
                "delta_median_ms": row.delta_median_ms,
                "grpc_cohort": row.grpc_cohort,
                "grpc_cohort_network_path": row.grpc_cohort_network_path,
                "hidden_size": row.hidden_size,
                "low_rtt_caveat": row.low_rtt_caveat,
                "path": row.path,
                "rest_cohort": row.rest_cohort,
                "rest_cohort_network_path": row.rest_cohort_network_path,
                "verdict": row.verdict,
            }
            for row in aggregates.protocol_comparison_verdicts
        ],
        "transport_only_verdicts": [
            {
                "ci_lower_ms": row.ci_lower_ms,
                "ci_upper_ms": row.ci_upper_ms,
                "comparison_unavailable_reason": row.comparison_unavailable_reason,
                "concurrency": row.concurrency,
                "delta_median_ms": row.delta_median_ms,
                "hidden_size": row.hidden_size,
                "low_rtt_caveat": row.low_rtt_caveat,
                "path": row.path,
                "verdict": row.verdict,
            }
            for row in aggregates.transport_only_verdicts
        ],
        "supersedes_m5_1": [
            {
                "category": entry.category,
                "concurrency": entry.concurrency,
                "grpc_cohort": entry.grpc_cohort,
                "hidden_size": entry.hidden_size,
                "m5_1_verdict": entry.m5_1_verdict,
                "m5_2_ci_lower_ms": entry.m5_2_ci_lower_ms,
                "m5_2_ci_upper_ms": entry.m5_2_ci_upper_ms,
                "m5_2_delta_median_ms": entry.m5_2_delta_median_ms,
                "m5_2_verdict": entry.m5_2_verdict,
                "path": entry.path,
                "rationale": entry.rationale,
            }
            for entry in aggregates.supersedes_m5_1
        ],
        "payload_parity_audit": run_config.get("payload_parity_audit")
        or {
            "no_regression_confirmed_against_pr": "",
            "measured_payload_bytes": {},
        },
        "smoke_run_outcome": run_config.get("smoke_run_outcome")
        or {
            "iso": "",
            "asserted_clauses_count": 0,
            "per_cohort_rtt_probe_medians_ms": {},
        },
        "https_edge_vs_plain_tcp_rtt_delta_median_ms": (
            aggregates.https_edge_vs_plain_tcp_rtt_delta_median_ms
        ),
        "https_edge_vs_plain_tcp_rtt_delta_p95_ms": (
            aggregates.https_edge_vs_plain_tcp_rtt_delta_p95_ms
        ),
        "modal_region": run_config.get("modal_region", ""),
        "modal_instance_class": run_config.get("modal_instance_class", ""),
        "https_edge_endpoint": run_config.get("https_edge_endpoint", ""),
        "client_external_geolocation": geo,
    }


_M5_2_REQUIRED_TOP_LEVEL_KEYS = frozenset(
    {
        "m5_2_run",
        "symmetry",
        "events_sidecar_path",
        "events_sidecar_sha256",
        "protocol_comparison_verdicts",
        "transport_only_verdicts",
        "supersedes_m5_1",
        "payload_parity_audit",
        "smoke_run_outcome",
        "https_edge_vs_plain_tcp_rtt_delta_median_ms",
        "https_edge_vs_plain_tcp_rtt_delta_p95_ms",
        "modal_region",
        "modal_instance_class",
        "https_edge_endpoint",
        "client_external_geolocation",
    }
)


def write_m5_2_json(aggregates: Any, run_config: dict[str, Any], path: Path) -> Path:
    """Write the M5.2 aggregate JSON deterministically.

    Encoding: ``json.dumps(..., sort_keys=True, separators=(",", ":"),
    ensure_ascii=False)`` so byte-identical round-trip holds across
    regenerator invocations on equivalent inputs.

    Validates the payload against the schema contract before writing;
    raises :class:`M5_2SchemaValidationFailed` on missing keys.
    """
    from vllm_grpc_bench.m5_2_regen import M5_2SchemaValidationFailed

    payload = _m5_2_aggregates_to_json_payload(aggregates, run_config)
    missing = _M5_2_REQUIRED_TOP_LEVEL_KEYS - payload.keys()
    if missing:
        raise M5_2SchemaValidationFailed(
            f"M5.2 JSON missing required top-level keys: {sorted(missing)}"
        )
    # Defensive: refuse to write any string containing the literal "Bearer "
    # (token-shaped string guard, matching M5.1's convention).
    import re

    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if re.search(r"Bearer ", blob):
        raise RuntimeError(
            "write_m5_2_json: bearer-token-shaped string detected; refusing to write"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(blob)
    return path


def write_m5_2_markdown(aggregates: Any, run_config: dict[str, Any], path: Path) -> Path:
    """Render the M5.2 Markdown report deterministically per FR-014.

    The report is structured as:

    1. Executive section — headline finding per verdict family; HTTPS-edge
       vs plain-TCP RTT delta; payload-parity audit metadata; smoke-gate
       outcome; client external geolocation; events sidecar SHA-256 + path.
    2. Per-cell comparison matrix — both verdict families per cell;
       network path named on every row.
    3. Supersedes-M5.1 table.
    4. Negative-results appendix — every no_winner / comparison_unavailable
       cell with full per-cohort CI bounds.
    5. Field-provenance footnotes — sidecar filter / aggregate-JSON key
       blockquotes at each section header per FR-012b.
    """
    lines: list[str] = ["# M5.2: REST Transport Path × gRPC Tuning Surface", ""]

    # Executive section.
    lines.append("## Executive summary")
    lines.append("")
    lines.append(
        "> Computed from aggregate JSON key: `https_edge_vs_plain_tcp_rtt_delta_median_ms`."
    )
    lines.append("")
    n_protocol = len(aggregates.protocol_comparison_verdicts)
    n_transport = len(aggregates.transport_only_verdicts)
    n_unavailable = sum(
        1 for r in aggregates.protocol_comparison_verdicts if r.verdict == "comparison_unavailable"
    )
    n_low_rtt = sum(1 for r in aggregates.protocol_comparison_verdicts if r.low_rtt_caveat)
    n_noise_resolved = sum(1 for e in aggregates.supersedes_m5_1 if e.category == "noise_resolved")
    n_transport_dependent = sum(
        1 for e in aggregates.supersedes_m5_1 if e.category == "transport_dependent"
    )
    lines.append(
        f"- 18-cell five-cohort sweep at n=250. "
        f"{n_protocol} protocol-comparison rows; {n_transport} transport-only rows; "
        f"{n_unavailable} `comparison_unavailable`; {n_low_rtt} `low_rtt_caveat`."
    )
    lines.append(
        f"- HTTPS-edge vs plain-TCP RTT delta: "
        f"median {aggregates.https_edge_vs_plain_tcp_rtt_delta_median_ms:+.2f} ms, "
        f"p95 {aggregates.https_edge_vs_plain_tcp_rtt_delta_p95_ms:+.2f} ms."
    )
    lines.append(
        f"- Supersedes-M5.1: {n_noise_resolved} `noise_resolved` "
        f"(n=250 resolution increase paid off); "
        f"{n_transport_dependent} `transport_dependent` "
        f"(HTTPS-edge moved the verdict)."
    )
    audit = run_config.get("payload_parity_audit") or {}
    lines.append(
        f"- Payload-parity audit (FR-005c): no regression confirmed against PR "
        f"`{audit.get('no_regression_confirmed_against_pr', '<unrecorded>')}`."
    )
    smoke = run_config.get("smoke_run_outcome") or {}
    lines.append(
        f"- Smoke-gate outcome (FR-005a + SC-012): "
        f"`{smoke.get('iso', '<unrecorded>')}`, "
        f"asserted clauses: {smoke.get('asserted_clauses_count', 0)}."
    )
    geo = run_config.get("client_external_geolocation")
    if geo:
        lines.append(
            f"- Client external geolocation: country=`{geo.get('country')}`, "
            f"region=`{geo.get('region')}`."
        )
    lines.append(
        f"- Events sidecar SHA-256: `{aggregates.sidecar_sha256}` at `{aggregates.sidecar_path}`."
    )
    lines.append(
        "- **Read instruction**: M5.2 measures MockEngine (engine cost held "
        "constant across protocols) so the verdict reflects transport + framing "
        "only. Real-engine re-validation is deferred to M7."
    )
    lines.append("")

    # Per-cell comparison matrix.
    lines.append("## Per-cell comparison matrix")
    lines.append("")
    lines.append("> Computed from events sidecar filter: `phase=measurement AND status=success`.")
    lines.append("")
    cells = sorted(
        {(r.path, r.hidden_size, r.concurrency) for r in aggregates.protocol_comparison_verdicts}
    )
    for path_name, hidden_size, concurrency in cells:
        lines.append(f"### {path_name} × h{hidden_size} × c={concurrency}")
        lines.append("")
        lines.append(
            "| family | gRPC cohort | gRPC net | REST cohort | REST net | "
            "verdict | Δ median (ms) | 95% CI (ms) |"
        )
        lines.append(
            "|--------|-------------|----------|-------------|----------|"
            "---------|---------------|-------------|"
        )
        for row in aggregates.protocol_comparison_verdicts:
            if (row.path, row.hidden_size, row.concurrency) != (
                path_name,
                hidden_size,
                concurrency,
            ):
                continue
            lines.append(
                f"| protocol | `{row.grpc_cohort}` | "
                f"`{row.grpc_cohort_network_path}` | "
                f"`{row.rest_cohort}` | `{row.rest_cohort_network_path}` | "
                f"`{row.verdict}` | {row.delta_median_ms:+.1f} | "
                f"[{row.ci_lower_ms:+.1f}, {row.ci_upper_ms:+.1f}] |"
            )
        for row in aggregates.transport_only_verdicts:
            if (row.path, row.hidden_size, row.concurrency) != (
                path_name,
                hidden_size,
                concurrency,
            ):
                continue
            lines.append(
                f"| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | "
                f"https_edge / plain_tcp | "
                f"`{row.verdict}` | {row.delta_median_ms:+.1f} | "
                f"[{row.ci_lower_ms:+.1f}, {row.ci_upper_ms:+.1f}] |"
            )
        lines.append("")

    # Supersedes-M5.1 table.
    if aggregates.supersedes_m5_1:
        lines.append("## Supersedes M5.1")
        lines.append("")
        lines.append("> Computed from aggregate JSON key: `supersedes_m5_1`.")
        lines.append("")
        lines.append(
            "| cell | gRPC cohort | M5.1 verdict | M5.2 verdict | "
            "Δ median (ms) | 95% CI | category | rationale |"
        )
        lines.append(
            "|------|-------------|--------------|--------------|"
            "---------------|--------|----------|-----------|"
        )
        for entry in sorted(
            aggregates.supersedes_m5_1,
            key=lambda e: (e.path, e.hidden_size, e.concurrency, e.grpc_cohort),
        ):
            lines.append(
                f"| {entry.path}:h{entry.hidden_size}:c{entry.concurrency} | "
                f"`{entry.grpc_cohort}` | `{entry.m5_1_verdict}` | "
                f"`{entry.m5_2_verdict}` | {entry.m5_2_delta_median_ms:+.1f} | "
                f"[{entry.m5_2_ci_lower_ms:+.1f}, {entry.m5_2_ci_upper_ms:+.1f}] | "
                f"`{entry.category}` | {entry.rationale} |"
            )
        lines.append("")

    # Negative results appendix.
    lines.append("## Negative results — do not re-run speculatively")
    lines.append("")
    lines.append(
        "> Computed from aggregate JSON key: "
        "`protocol_comparison_verdicts` filtered by verdict ∈ "
        "{no_winner, comparison_unavailable}."
    )
    lines.append("")
    negative_rows = [
        r
        for r in aggregates.protocol_comparison_verdicts
        if r.verdict in ("no_winner", "comparison_unavailable")
    ] + [
        r
        for r in aggregates.transport_only_verdicts
        if r.verdict in ("no_winner", "comparison_unavailable")
    ]
    if not negative_rows:
        lines.append("- (none — every cell produced a head-to-head verdict)")
    else:
        for r in sorted(
            negative_rows,
            key=lambda r: (r.path, r.hidden_size, r.concurrency, getattr(r, "grpc_cohort", "")),
        ):
            family = "protocol" if hasattr(r, "grpc_cohort") else "transport"
            cohort_label = (
                f"`{r.grpc_cohort}` vs `rest_https_edge`"
                if hasattr(r, "grpc_cohort")
                else "`rest_https_edge` vs `rest_plain_tcp`"
            )
            lines.append(
                f"- ({family}) {r.path}:h{r.hidden_size}:c{r.concurrency} / "
                f"{cohort_label}: `{r.verdict}` "
                f"(Δ {r.delta_median_ms:+.1f} ms, "
                f"CI [{r.ci_lower_ms:+.1f}, {r.ci_upper_ms:+.1f}])"
            )
    lines.append("")

    # M1 bytes-axis + M5 transport-axis preservation note per FR-014 (d).
    lines.append("## Preserved findings (NOT superseded by M5.2)")
    lines.append("")
    lines.append(
        "- M1 bytes-axis (encoding-driven, transport-immune): the ~89% chat "
        "response byte reduction and ~25% embed request byte reduction "
        "stand unchanged. M5.2 measures time only."
    )
    lines.append(
        "- M5 transport-axis (channel-tuning component): the per-axis "
        "tuned-channel recommendations from `docs/benchmarks/m5-cross-host-validation.md` "
        "remain in force; M5.2 reuses M5's frozen-tuned channel composition "
        "without re-tuning (FR-007)."
    )
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


# === M6.2 report writers (consolidated into reporter.py, T017 / FR-005) ===
__all__ = [
    "EARLY_EOS_AUDIT_MIN_MAX_TOKENS",
    "EARLY_EOS_RATIO_THRESHOLD",
    "INTEGRITY_CHANNELS",
    "NOT_VALIDATED_MARKER",
    "SC011_CLOCK_ANOMALY_FRACTION_THRESHOLD",
    "build_integrity_warnings",
    "compute_clock_anomaly_fraction",
    "compute_implied_output_tokens",
    "fill_validate_mode_placeholders",
    "render_json",
    "render_markdown",
    "write_m6_2_report",
]


# --- Canonical labels + thresholds ------------------------------------------

INTEGRITY_CHANNELS: frozenset[str] = frozenset(
    {
        "null_anchor_drift",
        "failure_summary_threshold",
        "cohort_csp_mismatch",
        "intra_sweep_latency_drift",
        "iteration_discipline_broken",
        "clock_anomaly_warning",
        "trajectory_insufficient_snapshots",
    }
)
"""Canonical channel labels the reporter may emit into ``integrity_warnings``.

The first four are publish-blocking-eligible per FR-014 / FR-029 / FR-009 /
SC-016. ``iteration_discipline_broken`` is a soft diagnostic per FR-032 /
SC-017. ``clock_anomaly_warning`` is the SC-011 0.5% RPC-budget gate; the
reporter computes the fraction and emits the label when it crosses the
threshold. ``trajectory_insufficient_snapshots`` is the C1 round-8
soft-diagnostic channel that fires when any cohort has fewer than 2
post-warmup anchor snapshots — purely informational, NOT publish-blocking,
distinct from ``intra_sweep_latency_drift``."""


NOT_VALIDATED_MARKER: str = "not_validated"
"""Sentinel used in ``failed_reason`` for the validate-mode interior-cap
placeholder rows (``max_tokens ∈ {256, 512, 1024}``). Per
``contracts/artifact-schema.md`` validate-mode rendering rules."""


SC011_CLOCK_ANOMALY_FRACTION_THRESHOLD: float = 0.005
"""SC-011 wire-format clock-anomaly tolerance: ≥ 0.5% of RPCs flagged
fires the ``clock_anomaly_warning`` integrity header."""


EARLY_EOS_RATIO_THRESHOLD: float = 0.5
"""Audit-section trigger: a ``chat_stream`` cell whose
``implied_output_tokens / max_tokens`` falls below this fraction is flagged
in the "Prompt-driven early-EOS audit" section. 0.5 catches blocks that
terminate via natural EOS at < half the cap — the regime where per-cohort
``wall_p50_ms`` ceases to be a like-for-like protocol comparison and starts
reflecting prompt-content variance instead."""


EARLY_EOS_AUDIT_MIN_MAX_TOKENS: int = 256
"""Audit-section gate: only inspect cells at ``max_tokens >= 256``. Below this
the cap is too tight for natural EOS to fire meaningfully before the cap,
so a small ``implied_output_tokens`` is the *expected* hit-the-cap regime
rather than an audit-worthy short response."""


# --- Section renderers ------------------------------------------------------


def _fmt(value: float | None, *, decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{decimals}f}"


def compute_implied_output_tokens(point: M6_2MeasurementPoint) -> float | None:
    """Back out the per-RPC output-token count implied by the block's
    aggregated wall-clock and segment decomposition.

    Returns ``(wall_p50_ms - seg_prefill_ms - seg_egress_ms) / tpot_ms`` when
    all four numerators/denominators are populated and ``tpot_ms > 0``;
    otherwise returns ``None``. Used by
    :func:`_render_early_eos_audit` to flag chat-stream cells whose
    natural-EOS termination undershoots the ``max_tokens`` cap by more than
    ``1 - EARLY_EOS_RATIO_THRESHOLD``.

    This is best-effort: the segment fields come from the M6.1.1 timing
    payload (which a fake-driver test fixture may not populate). When the
    helper returns ``None`` the audit treats the cell as non-flagged
    (insufficient evidence).
    """
    wall = point.wall_p50_ms
    tpot = point.tpot_ms
    if wall is None or tpot is None or tpot <= 0:
        return None
    prefill = point.seg_prefill_ms or 0.0
    egress = point.seg_egress_ms or 0.0
    implied = (wall - prefill - egress) / tpot
    return max(0.0, implied)


def _flatten_measurements(artifact: M6_2SweepArtifact) -> list[M6_2MeasurementPoint]:
    """Flatten ``artifact.per_cell`` into a stable, deterministic list."""
    out: list[M6_2MeasurementPoint] = []
    for cell_id in sorted(artifact.per_cell.keys()):
        per_cohort = artifact.per_cell[cell_id]
        for cohort in sorted(per_cohort.keys()):
            per_cap = per_cohort[cohort]
            for max_tokens in sorted(per_cap.keys()):
                out.append(per_cap[max_tokens])
    return out


def _iter_cell_ids() -> list[str]:
    """Canonical iteration order over the 6 M6.1 cells."""
    return [f"{path}_c{c}" for path, _h, c in CELLS]


def fill_validate_mode_placeholders(
    per_cell: dict[str, dict[CohortKind, dict[int, M6_2MeasurementPoint]]],
    *,
    sweep_mode: M6_2SweepMode,
    block_start_utc: str,
    block_end_utc: str,
) -> dict[str, dict[CohortKind, dict[int, M6_2MeasurementPoint]]]:
    """Insert ``failed_reason="not_validated"`` placeholders for interior caps
    that were not measured in validate mode (axis = ``{10, 50, 2048}``).

    Publish mode is a no-op. The placeholders ensure the validate artifact's
    ``per_cell`` block carries 144 entries (72 measured + 72 placeholders),
    per FR-016 + the data-model.md invariant. Each placeholder carries empty
    latency fields and the canonical synthetic / corpus regime markers
    appropriate for its ``(cell, max_tokens)`` per the round-5 R-9 regime
    table. Operates on a shallow copy of the input.
    """
    if sweep_mode != "validate":
        return per_cell
    out: dict[str, dict[CohortKind, dict[int, M6_2MeasurementPoint]]] = {
        cell: {cohort: dict(per_cap) for cohort, per_cap in per_cohort.items()}
        for cell, per_cohort in per_cell.items()
    }
    for cell_id in out:
        cell_type = "embed" if cell_id.startswith("embed") else "chat_stream"
        for cohort, per_cap in out[cell_id].items():
            for max_tokens in M6_2_INTERIOR_CAP_MAX_TOKENS:
                if max_tokens in M6_2_VALIDATE_MAX_TOKENS_AXIS:
                    continue
                if max_tokens in per_cap:
                    continue
                # Interior caps always use corpus regime per R-9.
                prompt_source: M6_2PromptSource = (
                    "corpus_sharegpt_embed" if cell_type == "embed" else "corpus_sharegpt"
                )
                per_cap[max_tokens] = M6_2MeasurementPoint(
                    cell_id=cell_id,
                    cohort=cohort,
                    max_tokens=max_tokens,
                    n_rpcs=0,
                    wall_p50_ms=None,
                    wall_p95_ms=None,
                    wall_p99_ms=None,
                    wall_p50_ms_ci_half_width=None,
                    tpot_ms=None,
                    seg_ab_ms=None,
                    seg_queue_ms=None,
                    seg_prefill_ms=None,
                    seg_ingress_ms=None,
                    seg_egress_ms=None,
                    failed_reason=NOT_VALIDATED_MARKER,
                    block_start_utc=block_start_utc,
                    block_end_utc=block_end_utc,
                    retry_attempted=False,
                    clock_anomaly=False,
                    prompt_source=prompt_source,
                    measurement_regime="natural_eos",
                    prompt_corpus_idx=None,
                )
    return out


def compute_clock_anomaly_fraction(measurements: Iterable[M6_2MeasurementPoint]) -> float:
    """SC-011: fraction of measurement rows with ``clock_anomaly=True`` over
    rows that carried RPC traffic (``n_rpcs > 0``).

    ``not_validated`` placeholders are excluded from both numerator and
    denominator. Returns ``0.0`` when no traffic rows are present."""
    rows = [m for m in measurements if m.n_rpcs > 0 and m.failed_reason != NOT_VALIDATED_MARKER]
    if not rows:
        return 0.0
    flagged = sum(1 for m in rows if m.clock_anomaly)
    return flagged / len(rows)


def _has_cohort_csp_mismatch(
    network_paths: dict[
        CohortKind,
        list[M6_1_2NetworkPath | M6_1_2NetworkPathError],
    ],
) -> bool:
    """FR-009 / SC-010: fire ``cohort_csp_mismatch`` if any cohort's
    consecutive ``network_paths`` snapshots reveal a CSP / region change."""
    for snapshots in network_paths.values():
        prior: tuple[str, str | None] | None = None
        for entry in snapshots:
            if isinstance(entry, M6_1_2NetworkPath):
                key: tuple[str, str | None] = (entry.cloud_provider, entry.region)
            else:
                continue
            if prior is None:
                prior = key
                continue
            if key != prior:
                return True
            prior = key
    return False


def build_integrity_warnings(artifact: M6_2SweepArtifact) -> list[str]:
    """Compose the canonical ``integrity_warnings`` list for the artifact.

    Channels fire independently per the rules in
    ``contracts/artifact-schema.md`` "Leading sweep-level integrity warning
    headers". The list preserves a stable, ordered output for diff-friendly
    artifact rendering. Returns an empty list when no channel fires.
    """
    measurements = _flatten_measurements(artifact)
    # ``not_validated`` placeholders are a validate-mode artifact-rendering
    # convention, not true block failures — exclude them from the FR-029
    # sweep-level header rule so the threshold reflects real failures only.
    real_measurements = [m for m in measurements if m.failed_reason != NOT_VALIDATED_MARKER]
    warnings: list[str] = []
    if compute_null_anchor_drift_header_fired(artifact.null_anchor_validation):
        warnings.append("null_anchor_drift")
    if compute_failure_summary_header_fired(real_measurements):
        warnings.append("failure_summary_threshold")
    if _has_cohort_csp_mismatch(artifact.network_paths):
        warnings.append("cohort_csp_mismatch")
    if compute_intra_sweep_drift_header_fired(artifact.anchor_latency_trajectory):
        warnings.append("intra_sweep_latency_drift")
    if compute_insufficient_snapshots_header_fired(artifact.anchor_latency_trajectory):
        warnings.append("trajectory_insufficient_snapshots")
    if not artifact.run_meta.iteration_discipline_verified:
        warnings.append("iteration_discipline_broken")
    if compute_clock_anomaly_fraction(measurements) >= SC011_CLOCK_ANOMALY_FRACTION_THRESHOLD:
        warnings.append("clock_anomaly_warning")
    return warnings


# --- JSON rendering ---------------------------------------------------------


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert non-JSON-serialisable values to JSON-safe shapes.

    Mirrors :func:`m6_1_3_reporter._sanitize_for_json`. Tuple keys collapse
    to ``"part0|part1|..."``; dataclass instances flatten via
    ``dataclasses.asdict``.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _sanitize_for_json(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            key = "|".join(str(part) for part in k) if isinstance(k, tuple) else k
            out[key] = _sanitize_for_json(v)
        return out
    if isinstance(obj, list):
        return [_sanitize_for_json(item) for item in obj]
    return obj


def render_json(artifact: M6_2SweepArtifact) -> dict[str, Any]:
    """Build the dict ready for ``json.dumps`` per
    ``contracts/artifact-schema.md`` "JSON top-level structure".
    """
    per_cell: dict[str, dict[str, dict[str, Any]]] = {}
    for cell_id, per_cohort in artifact.per_cell.items():
        per_cell[cell_id] = {}
        for cohort, per_cap in per_cohort.items():
            per_cell[cell_id][str(cohort)] = {
                str(max_tokens): _sanitize_for_json(point) for max_tokens, point in per_cap.items()
            }

    network_paths: dict[str, list[Any]] = {}
    for cohort, snapshots in artifact.network_paths.items():
        network_paths[str(cohort)] = [_sanitize_for_json(s) for s in snapshots]

    payload: dict[str, Any] = {
        "schema_version": artifact.schema_version,
        "dispatch_mode": artifact.dispatch_mode,
        "run_id": artifact.run_id,
        "run_started_at": artifact.run_started_at,
        "run_completed_at": artifact.run_completed_at,
        "run_meta": _sanitize_for_json(artifact.run_meta),
        "network_paths": network_paths,
        "cohort_set": list(artifact.cohort_set),
        "per_cell": per_cell,
        "null_anchor_validation": [_sanitize_for_json(a) for a in artifact.null_anchor_validation],
        "max_tokens_axis": list(artifact.max_tokens_axis),
        "protocol_crossover": [_sanitize_for_json(c) for c in artifact.protocol_crossover],
        "kv_pressure_observation": [
            _sanitize_for_json(k) for k in artifact.kv_pressure_observation
        ],
        "anchor_latency_trajectory": {
            str(cohort): _sanitize_for_json(traj)
            for cohort, traj in artifact.anchor_latency_trajectory.items()
        },
        "failure_summary": dict(artifact.failure_summary),
        "integrity_warnings": list(artifact.integrity_warnings),
    }
    if artifact.cohort_omissions:
        payload["cohort_omissions"] = dict(artifact.cohort_omissions)
    return payload


# --- Markdown rendering: leading headers ------------------------------------


_CHANNEL_DESCRIPTIONS: dict[str, str] = {
    "null_anchor_drift": (
        "≥ 2 of the 22 cross-checkable null-anchor cells drifted against the M6.1.3 "
        "baseline (FR-014 / SC-004). Operator decides publish vs rerun."
    ),
    "failure_summary_threshold": (
        "≥ 3 blocks failed across the table OR one (cell, max_tokens) tuple saw all 4 "
        "cohorts fail (FR-029 / SC-014). Operator decides publish vs rerun."
    ),
    "cohort_csp_mismatch": (
        "A cohort's `network_paths` trajectory shows a CSP or region change between "
        "snapshots (FR-009 / SC-010). Cross-cohort comparison may be confounded."
    ),
    "intra_sweep_latency_drift": (
        "≥ 2 of 4 cohorts' anchor-latency trajectories drifted beyond M6.1.3's CI "
        "half-width (FR-031 / SC-016). Cross-block comparison may be confounded."
    ),
    "iteration_discipline_broken": (
        "FR-030 cohort-innermost block iteration was NOT preserved end-to-end "
        "(soft diagnostic, FR-032 / SC-017). Informational only."
    ),
    "clock_anomaly_warning": (
        "≥ 0.5% of RPCs flagged for wire-format clock anomaly (SC-011). "
        "Wall-clock measurements may be unreliable; inspect the events sidecar."
    ),
    "trajectory_insufficient_snapshots": (
        "At least one cohort has fewer than 2 post-warmup anchor snapshots "
        "(C1 round-8 amendment, FR-031). The intra-sweep drift verdict for "
        "that cohort was suppressed. Soft diagnostic — informational only, "
        "validate-mode start+end trajectories naturally hit this fallback."
    ),
}


def _render_leading_integrity_headers(artifact: M6_2SweepArtifact) -> list[str]:
    """Render leading callouts for any fired integrity-warning channels.

    Each fired channel produces a `> **WARNING (<channel>)**: …` callout
    above the section content. ``iteration_discipline_broken`` renders as a
    softer ``> **DIAGNOSTIC**:`` note rather than ``WARNING``.
    """
    lines: list[str] = []
    for channel in artifact.integrity_warnings:
        if channel not in INTEGRITY_CHANNELS:
            continue
        desc = _CHANNEL_DESCRIPTIONS.get(channel, "(no description)")
        prefix = "DIAGNOSTIC" if channel == "iteration_discipline_broken" else "WARNING"
        lines.append(f"> **{prefix} ({channel})**: {desc}")
        lines.append(">")
    if lines and lines[-1] == ">":
        lines.pop()  # trim the trailing continuation marker
    if lines:
        lines.append("")
    return lines


# --- Markdown rendering: run meta + method/background ----------------------


def _render_run_meta(artifact: M6_2SweepArtifact) -> list[str]:
    rm = artifact.run_meta
    lines = [
        "# M6.2 — Token-Budget Characterization",
        "",
        f"- run_id: `{artifact.run_id}`",
        f"- sweep_mode: `{rm.sweep_mode}`",
        f"- modal_region: `{rm.modal_region}`",
        f"- model: `{rm.model_identifier}`",
        f"- base_seed: `{rm.base_seed}`",
        f"- iteration_order: `{rm.iteration_order}`",
        f"- iteration_discipline_verified: `{rm.iteration_discipline_verified}`",
        f"- n_per_point: `{rm.n_per_point}`",
        f"- validate_axis_subset: `{rm.validate_axis_subset}`",
        f"- wall_clock_start_utc: `{rm.wall_clock_start_utc}`",
        f"- wall_clock_end_utc: `{rm.wall_clock_end_utc}`",
        f"- total_sweep_hours: `{rm.total_sweep_hours:.3f}`",
        f"- chat_corpus_sha256: `{rm.chat_corpus_sha256}`",
        f"- embed_corpus_sha256: `{rm.embed_corpus_sha256}`",
        f"- sub_probe_ran: `{rm.sub_probe_ran}`",
        f"- preemption_events: `{getattr(rm, 'preemption_events', 0)}`",
        f"- run_started_at: `{artifact.run_started_at}`",
        f"- run_completed_at: `{artifact.run_completed_at}`",
        "",
    ]
    return lines


def _render_method_background() -> list[str]:
    """Section 10 — FR-019 reciprocal cross-reference to M6.1.3."""
    return [
        "## Method / Background",
        "",
        "This milestone builds on M6.1.3's published per-cohort attribution at "
        "`max_tokens=10/50`; see "
        "[m6_1_3-attribution-closure.md](m6_1_3-attribution-closure.md) for the "
        "baseline CIs and cohort omissions. The null-anchor validation section "
        "below pairs each cross-checkable M6.2 anchor measurement against that "
        "baseline (FR-012 / FR-013).",
        "",
    ]


# --- Section 1: Production latency budget (T023) ----------------------------


def _row_status(point: M6_2MeasurementPoint) -> str:
    """One-line per-row marker used in the latency budget table."""
    if point.failed_reason == NOT_VALIDATED_MARKER:
        return "`not_validated`"
    if point.failed_reason is not None:
        return f"`failed_{point.failed_reason}`"
    return "ok"


def _render_production_latency_budget(
    artifact: M6_2SweepArtifact,
    *,
    sweep_mode: M6_2SweepMode,
) -> list[str]:
    """Section 1 — per-cell × per-cohort × per-max_tokens p50/p95/p99 table.

    144 rows in publish mode (or ``failed_<reason>`` markers); validate mode
    renders 72 measured rows + 72 ``not_validated`` placeholders. Per-row
    ``prompt_source`` / ``measurement_regime`` / ``prompt_corpus_idx`` columns
    record the three-regime audit trail (round-5 FR-034 / FR-035).
    """
    lines: list[str] = ["## Production latency budget", ""]
    if sweep_mode == "validate":
        lines.append(
            "Validate-mode axis subset is `{10, 50, 2048}`; interior caps "
            "(`{256, 512, 1024}`) carry `not_validated` placeholders. Use the "
            "publish-mode artifact for the full 6-point budget."
        )
        lines.append("")
    lines.append(
        "| cell | cohort | max_tokens | n | wall_p50_ms | wall_p95_ms | wall_p99_ms | "
        "prompt_source | regime | corpus_idx | status |"
    )
    lines.append(
        "|------|--------|-----------:|---:|------------:|------------:|------------:|"
        "---------------|--------|-----------:|--------|"
    )
    for cell_id in _iter_cell_ids():
        per_cohort = artifact.per_cell.get(cell_id, {})
        for cohort in sorted(per_cohort.keys()):
            per_cap = per_cohort[cohort]
            for max_tokens in sorted(per_cap.keys()):
                p = per_cap[max_tokens]
                corpus_idx = "—" if p.prompt_corpus_idx is None else str(p.prompt_corpus_idx)
                lines.append(
                    f"| `{cell_id}` | `{cohort}` | {max_tokens} | {p.n_rpcs} | "
                    f"{_fmt(p.wall_p50_ms)} | {_fmt(p.wall_p95_ms)} | "
                    f"{_fmt(p.wall_p99_ms)} | `{p.prompt_source}` | "
                    f"`{p.measurement_regime}` | {corpus_idx} | {_row_status(p)} |"
                )
    lines.append("")
    return lines


# --- Section 1b: Prompt-driven early-EOS audit ------------------------------


def _render_early_eos_audit(artifact: M6_2SweepArtifact) -> list[str]:
    """Section 1b — flag chat_stream cells whose natural-EOS termination
    undershoots the ``max_tokens`` cap by more than
    ``1 - EARLY_EOS_RATIO_THRESHOLD``.

    Why this exists: with ``iteration_order="cohort_innermost_block"`` and a
    per-block ``iter_idx = len(measurements)`` (sweep.py), adjacent
    cohort blocks for the same ``(cell, max_tokens)`` draw *consecutive*
    corpus indices via cohort-blind ``assign_symmetric_prompt``. At large
    ``max_tokens`` a "short" / stub prompt that hits natural EOS early
    produces a ``wall_p50_ms`` that's 2–8× faster than peer cohorts at the
    same cell — purely from prompt content, not from protocol cost. This
    audit makes that confound visible so a downstream reader doesn't
    mistake prompt-distribution variance for a cohort anomaly.

    Scope: chat_stream cells only (``tpot_ms`` is undefined for embed
    cells); ``measurement_regime == "natural_eos"`` only (sub-probe forced-cap
    rows live in §"KV-cache pressure" and are intentionally cap-pinned);
    ``max_tokens >= EARLY_EOS_AUDIT_MIN_MAX_TOKENS`` (below the cap is too
    tight for natural EOS to fire meaningfully before it).

    Emits nothing when no cells qualify — the section stays silent on the
    happy path to keep the report clean.
    """
    flagged: list[tuple[M6_2MeasurementPoint, float, float]] = []
    for point in _flatten_measurements(artifact):
        if not point.cell_id.startswith("chat_stream"):
            continue
        if point.measurement_regime != "natural_eos":
            continue
        if point.failed_reason is not None:
            continue
        if point.max_tokens < EARLY_EOS_AUDIT_MIN_MAX_TOKENS:
            continue
        implied = compute_implied_output_tokens(point)
        if implied is None:
            continue
        ratio = implied / point.max_tokens if point.max_tokens > 0 else 0.0
        if ratio < EARLY_EOS_RATIO_THRESHOLD:
            flagged.append((point, implied, ratio))

    if not flagged:
        return []

    lines: list[str] = ["## Prompt-driven early-EOS audit", ""]
    lines.append(
        f"The cells below terminated via natural EOS at fewer than "
        f"`{EARLY_EOS_RATIO_THRESHOLD:.0%}` of the `max_tokens` cap "
        f"(threshold `EARLY_EOS_RATIO_THRESHOLD = {EARLY_EOS_RATIO_THRESHOLD}`, "
        f"minimum cap `EARLY_EOS_AUDIT_MIN_MAX_TOKENS = "
        f"{EARLY_EOS_AUDIT_MIN_MAX_TOKENS}`). Each cell draws a single "
        f"corpus prompt per block (see `sweep.py:546` + "
        f"`assign_symmetric_prompt`); adjacent cohort blocks for the same "
        f"`(cell, max_tokens)` draw *different* prompts, so per-cohort "
        f"`wall_p50_ms` at high `max_tokens` in `natural_eos` regime "
        f"confounds protocol cost with prompt-content distribution. The "
        f"flagged rows are not protocol pathologies — they are cells whose "
        f"corpus prompt elicited a short response and stopped early."
    )
    lines.append("")
    lines.append(
        "For a clean cohort-axis protocol comparison at large `max_tokens` "
        'use either the §"TPOT curves" table (protocol-invariant per-token '
        'decode cost) or the §"KV-cache pressure" sub-probe (forced-cap '
        "via `ignore_eos=True`, prompt-content held constant)."
    )
    lines.append("")
    lines.append(
        "| cell | cohort | max_tokens | corpus_idx | wall_p50_ms | tpot_ms | "
        "implied_output_tokens | implied/cap |"
    )
    lines.append(
        "|------|--------|-----------:|-----------:|------------:|--------:|"
        "---------------------:|------------:|"
    )
    for point, implied, ratio in flagged:
        corpus_idx = "—" if point.prompt_corpus_idx is None else str(point.prompt_corpus_idx)
        lines.append(
            f"| `{point.cell_id}` | `{point.cohort}` | {point.max_tokens} | "
            f"{corpus_idx} | {_fmt(point.wall_p50_ms)} | "
            f"{_fmt(point.tpot_ms)} | {implied:.0f} | {ratio:.2f} |"
        )
    lines.append("")
    return lines


# --- Section 2: TPOT curves (T024) ------------------------------------------


def _render_tpot_curves(
    artifact: M6_2SweepArtifact,
    *,
    sweep_mode: M6_2SweepMode,
) -> list[str]:
    """Section 2 — chat_stream-only TPOT vs max_tokens.

    One row per (chat_stream_c{1,4,8}, cohort, max_tokens) tuple with the
    ``tpot_ms`` value. Validate mode marks interior caps ``not_validated``.
    """
    lines: list[str] = ["## TPOT curves", ""]
    if sweep_mode == "validate":
        lines.append(
            "Interior caps not measured in validate mode (`not_validated`). "
            "Curves at `{10, 50, 2048}` only."
        )
        lines.append("")
    lines.append("| cell | cohort | max_tokens | tpot_ms | status |")
    lines.append("|------|--------|-----------:|--------:|--------|")
    for cell_id in _iter_cell_ids():
        if not cell_id.startswith("chat_stream"):
            continue
        per_cohort = artifact.per_cell.get(cell_id, {})
        for cohort in sorted(per_cohort.keys()):
            per_cap = per_cohort[cohort]
            for max_tokens in sorted(per_cap.keys()):
                p = per_cap[max_tokens]
                lines.append(
                    f"| `{cell_id}` | `{cohort}` | {max_tokens} | "
                    f"{_fmt(p.tpot_ms)} | {_row_status(p)} |"
                )
    lines.append("")
    return lines


# --- Section 3: Engine-cost decomposition curves (T025) ---------------------


def _render_engine_cost_decomposition(
    artifact: M6_2SweepArtifact,
    *,
    sweep_mode: M6_2SweepMode,
) -> list[str]:
    """Section 3 — segment-share evolution as a function of max_tokens.

    M6.1.3 5-segment decomposition (seg_ab_ms / seg_queue_ms / seg_prefill_ms
    / seg_ingress_ms / seg_egress_ms) per (cell, cohort, max_tokens). Validate
    mode marks interior caps ``not_validated``.
    """
    lines: list[str] = ["## Engine-cost decomposition curves", ""]
    if sweep_mode == "validate":
        lines.append(
            "Interior caps not measured in validate mode (`not_validated`). "
            "Decomposition only available at `{10, 50, 2048}`."
        )
        lines.append("")
    lines.append(
        "| cell | cohort | max_tokens | seg_ab_ms | seg_queue_ms | "
        "seg_prefill_ms | seg_ingress_ms | seg_egress_ms | status |"
    )
    lines.append(
        "|------|--------|-----------:|----------:|-------------:|"
        "---------------:|---------------:|--------------:|--------|"
    )
    for cell_id in _iter_cell_ids():
        per_cohort = artifact.per_cell.get(cell_id, {})
        for cohort in sorted(per_cohort.keys()):
            per_cap = per_cohort[cohort]
            for max_tokens in sorted(per_cap.keys()):
                p = per_cap[max_tokens]
                lines.append(
                    f"| `{cell_id}` | `{cohort}` | {max_tokens} | "
                    f"{_fmt(p.seg_ab_ms)} | {_fmt(p.seg_queue_ms)} | "
                    f"{_fmt(p.seg_prefill_ms)} | {_fmt(p.seg_ingress_ms)} | "
                    f"{_fmt(p.seg_egress_ms)} | {_row_status(p)} |"
                )
    lines.append("")
    return lines


# --- Section 4: Protocol crossover threshold (US2 placeholder) -------------


def _render_protocol_crossover(
    artifact: M6_2SweepArtifact,
    *,
    sweep_mode: M6_2SweepMode,
) -> list[str]:
    """Section 4 — per-cell crossover threshold from the symmetric mean-in-CI
    rule (User Story 2). Renders the records produced by
    :func:`crossover.compute_per_cell_crossover` (US2 task T034 fills the
    artifact field; this reporter section consumes whatever's there).
    """
    lines: list[str] = ["## Protocol crossover threshold", ""]
    if sweep_mode == "validate":
        lines.append(
            "> **Note**: Validate-mode crossover analysis is restricted to the "
            "3-point axis subset `{10, 50, 2048}`; interior-cap crossover "
            "thresholds are unobservable in validate mode. Use the publish-mode "
            "artifact for fine-grained crossover threshold attribution."
        )
        lines.append("")
    if not artifact.protocol_crossover:
        lines.append(
            "_No crossover thresholds populated_ (User Story 2 implementation "
            "pending; see tasks.md T034 / T035)."
        )
        lines.append("")
        return lines
    lines.append("| cell | m6_1_3_base_verdict | crossover_max_tokens | evidence |")
    lines.append("|------|---------------------|---------------------:|----------|")
    for record in artifact.protocol_crossover:
        crossover = "—" if record.crossover_max_tokens is None else str(record.crossover_max_tokens)
        lines.append(
            f"| `{record.cell_id}` | `{record.m6_1_3_base_verdict}` | "
            f"{crossover} | {record.crossover_evidence} |"
        )
    lines.append("")
    return lines


# --- Section 5: KV-cache pressure (US3 placeholder) ------------------------


def _render_kv_pressure(artifact: M6_2SweepArtifact) -> list[str]:
    """Section 5 — KV-cache pressure subsection sourced from the FR-036
    sub-probe (NOT budget-table c=8 rows). US3 (T037 / T038 / T039 / T040)
    populates ``artifact.kv_pressure_observation``; this renderer consumes
    whatever is there.
    """
    lines: list[str] = ["## KV-cache pressure", ""]
    if not artifact.kv_pressure_observation:
        lines.append(
            "_No KV-pressure observations populated_ (User Story 3 sub-probe "
            "implementation pending; see tasks.md T037 / T038 / T039 / T040)."
        )
        lines.append("")
        return lines
    lines.append(
        "Measurements below are from the forced-cap sub-probe regime "
        "(`ignore_eos=True`) — distinct from the budget-table c=8 rows which "
        "use natural EOS under cap."
    )
    lines.append("")
    lines.append(
        "| cohort | cell_type | wall_clock_ratio_2048/1024 | inference | "
        "kv_cache_used_fraction_peak | oom | n |"
    )
    lines.append(
        "|--------|-----------|--------------------------:|-----------|"
        "----------------------------:|----:|--:|"
    )
    for obs in artifact.kv_pressure_observation:
        ratio = _fmt(obs.wall_clock_ratio_c8_2048_over_1024, decimals=3)
        peak = _fmt(obs.kv_cache_used_fraction_peak, decimals=3)
        lines.append(
            f"| `{obs.cohort}` | `{obs.cell_type}` | {ratio} | "
            f"`{obs.wall_clock_inference_label}` | {peak} | "
            f"{obs.oom_observed} | {obs.sub_probe_n_rpcs} |"
        )
    lines.append("")
    return lines


# --- Section 6: Null anchor validation (T026) ------------------------------


def _render_null_anchor_validation(artifact: M6_2SweepArtifact) -> list[str]:
    """Section 6 — per-(cell, cohort, max_tokens) drift verdict at the
    null-anchor caps. 22 cross-checkable cells carry `PASS|WARN|FAIL`;
    26 new-baseline cells carry `new_baseline_marker`. The FR-014 sweep-level
    integrity header above the table (rendered separately via
    :func:`_render_leading_integrity_headers`) summarizes the firing rule.
    """
    lines: list[str] = ["## Null anchor validation", ""]
    cross_checkable = [a for a in artifact.null_anchor_validation if not a.new_baseline_marker]
    new_baseline = [a for a in artifact.null_anchor_validation if a.new_baseline_marker]

    if not artifact.null_anchor_validation:
        lines.append("_No null-anchor records populated._")
        lines.append("")
        return lines

    drifted = sum(1 for a in cross_checkable if a.drift_verdict in {"WARN", "FAIL"})
    lines.append(
        f"Cross-checkable cells: {len(cross_checkable)} (≥ 2 drifted → fires "
        f"FR-014 `null_anchor_drift` header; currently {drifted} drifted). "
        f"New-baseline cells: {len(new_baseline)} (excluded from the count "
        "by construction)."
    )
    lines.append("")
    lines.append("### Cross-checkable cells (drift verdict against M6.1.3 baseline)")
    lines.append("")
    lines.append(
        "| cell | cohort | max_tokens | m6_2_p50 | m6_1_3_p50 | drift_fraction | verdict |"
    )
    lines.append(
        "|------|--------|-----------:|---------:|-----------:|---------------:|---------|"
    )
    for a in sorted(cross_checkable, key=lambda x: (x.cell_id, x.cohort, x.max_tokens)):
        lines.append(
            f"| `{a.cell_id}` | `{a.cohort}` | {a.max_tokens} | "
            f"{_fmt(a.m6_2_wall_p50_ms)} | {_fmt(a.m6_1_3_wall_p50_ms)} | "
            f"{_fmt(a.drift_fraction, decimals=3)} | `{a.drift_verdict}` |"
        )
    lines.append("")
    if new_baseline:
        lines.append("### New-baseline cells (no M6.1.3 reference; recorded for posterity)")
        lines.append("")
        lines.append("| cell | cohort | max_tokens | m6_2_p50 | marker |")
        lines.append("|------|--------|-----------:|---------:|--------|")
        for a in sorted(new_baseline, key=lambda x: (x.cell_id, x.cohort, x.max_tokens)):
            lines.append(
                f"| `{a.cell_id}` | `{a.cohort}` | {a.max_tokens} | "
                f"{_fmt(a.m6_2_wall_p50_ms)} | `new_baseline_marker` |"
            )
        lines.append("")
    return lines


# --- Section 7: Anchor latency trajectory (T030) ---------------------------


def _render_anchor_latency_trajectory(artifact: M6_2SweepArtifact) -> list[str]:
    """Section 7 — per-cohort intra-sweep anchor-latency trajectory.

    Per FR-031: 8-10 snapshots/cohort in publish mode; 2 in validate. Each
    snapshot row carries the sweep-hour mark + UTC timestamp + p50/p95/p99.
    Per-cohort ``latency_drift_warning`` line fires when the trajectory
    spread exceeds M6.1.3's baseline CI half-width. SC-016 sweep-level
    ``intra_sweep_latency_drift`` integrity header rendering lives in
    :func:`_render_leading_integrity_headers`.
    """
    lines: list[str] = ["## Anchor latency trajectory", ""]
    if not artifact.anchor_latency_trajectory:
        lines.append("_No anchor snapshots populated._")
        lines.append("")
        return lines
    for cohort in sorted(artifact.anchor_latency_trajectory.keys()):
        trajectory: M6_2AnchorLatencyTrajectory = artifact.anchor_latency_trajectory[cohort]
        lines.append(f"### `{cohort}`")
        lines.append("")
        spread = _fmt(trajectory.max_minus_min_wall_p50_ms, decimals=3)
        warning = trajectory.latency_drift_warning
        lines.append(f"- max_minus_min_wall_p50_ms: `{spread}`; latency_drift_warning: `{warning}`")
        lines.append("")
        lines.append(
            "| sweep_hour_mark | snapshot_timestamp | wall_p50_ms | wall_p95_ms | wall_p99_ms |"
        )
        lines.append(
            "|----------------:|--------------------|------------:|------------:|------------:|"
        )
        for s in trajectory.snapshots:
            lines.append(
                f"| {s.sweep_hour_mark:.2f} | `{s.snapshot_timestamp}` | "
                f"{_fmt(s.wall_p50_ms)} | {_fmt(s.wall_p95_ms)} | {_fmt(s.wall_p99_ms)} |"
            )
        lines.append("")
    return lines


# --- Section 8: Failure summary (T027) -------------------------------------


def _render_failure_summary(artifact: M6_2SweepArtifact) -> list[str]:
    """Section 8 — per-reason tally of ``failed_<reason>`` markers across the
    full latency budget table. Always present per FR-029 / SC-014.

    Excludes the validate-mode ``not_validated`` placeholder count (it isn't
    a true failure). Includes the ``systemic_failure_<reason>`` tag when any
    (cell, max_tokens) tuple has all 4 cohorts failed with the same reason.
    """
    lines: list[str] = ["## Failure summary", ""]
    measurements = _flatten_measurements(artifact)
    failures: dict[str, int] = {}
    for p in measurements:
        if p.failed_reason is None or p.failed_reason == NOT_VALIDATED_MARKER:
            continue
        failures[p.failed_reason] = failures.get(p.failed_reason, 0) + 1
    if not failures:
        lines.append("_No measurement-cell failures._")
        lines.append("")
        return lines
    lines.append("| failed_reason | count |")
    lines.append("|---------------|------:|")
    for reason in sorted(failures.keys()):
        lines.append(f"| `{reason}` | {failures[reason]} |")
    lines.append("")
    # Systemic failure tag — any (cell, max_tokens) tuple with all 4 cohorts
    # failed on the same reason.
    by_tuple: dict[tuple[str, int], list[M6_2MeasurementPoint]] = {}
    for p in measurements:
        if p.failed_reason is None or p.failed_reason == NOT_VALIDATED_MARKER:
            continue
        by_tuple.setdefault((p.cell_id, p.max_tokens), []).append(p)
    systemic: list[str] = []
    for (cell_id, max_tokens), blocks in by_tuple.items():
        reasons = {b.failed_reason for b in blocks if b.failed_reason is not None}
        if len(blocks) == 4 and len(reasons) == 1:
            systemic.append(
                f"`systemic_failure_{next(iter(reasons))}` at "
                f"`({cell_id}, max_tokens={max_tokens})`"
            )
    if systemic:
        lines.append("**Systemic failures** (all 4 cohorts at the same tuple):")
        lines.append("")
        for s in systemic:
            lines.append(f"- {s}")
        lines.append("")
    return lines


# --- Section 9: Sweep wall-clock timeline (T028) ---------------------------


def _render_sweep_wall_clock_timeline(
    artifact: M6_2SweepArtifact,
    *,
    sweep_mode: M6_2SweepMode,
) -> list[str]:
    """Section 9 — one row per (cell, max_tokens) tuple with each cohort's
    block start UTC + duration in minutes. Visual verification of the FR-030
    cohort-innermost discipline. Publish mode renders unconditionally;
    validate mode renders only when total sweep ≥ 8h (otherwise low-signal).
    """
    if sweep_mode == "validate" and artifact.run_meta.total_sweep_hours < 8.0:
        return []
    lines: list[str] = ["## Sweep wall-clock timeline", ""]
    measurements = _flatten_measurements(artifact)
    by_tuple: dict[tuple[str, int], list[M6_2MeasurementPoint]] = {}
    for p in measurements:
        if p.failed_reason == NOT_VALIDATED_MARKER:
            continue
        by_tuple.setdefault((p.cell_id, p.max_tokens), []).append(p)
    if not by_tuple:
        lines.append("_No measured blocks to render._")
        lines.append("")
        return lines
    lines.append("| cell | max_tokens | cohort | block_start_utc | duration_min | retry |")
    lines.append("|------|-----------:|--------|-----------------|-------------:|-------|")
    for (cell_id, max_tokens), blocks in sorted(by_tuple.items()):
        for p in sorted(blocks, key=lambda b: b.block_start_utc):
            duration_min = _duration_minutes(p.block_start_utc, p.block_end_utc)
            lines.append(
                f"| `{cell_id}` | {max_tokens} | `{p.cohort}` | "
                f"`{p.block_start_utc}` | {duration_min:.2f} | {p.retry_attempted} |"
            )
    lines.append("")
    return lines


def _duration_minutes(start_utc: str, end_utc: str) -> float:
    """Difference between two ISO-8601 UTC strings in minutes. Returns 0.0 on
    parse failure (defensive: timestamps come from the orchestrator and are
    well-formed in practice)."""
    import datetime as _dt

    try:
        start = _dt.datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
        end = _dt.datetime.fromisoformat(end_utc.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (end - start).total_seconds() / 60.0


# --- Section: Network paths -------------------------------------------------


def _render_network_paths(artifact: M6_2SweepArtifact) -> list[str]:
    """Render the per-cohort network_paths trajectory. The FR-009 /
    SC-010 ``cohort_csp_mismatch`` integrity header lives at the leading
    headers section; this subsection shows the underlying trajectory.
    """
    lines: list[str] = ["## Network paths", ""]
    if not artifact.network_paths:
        lines.append("_No network probe snapshots._")
        lines.append("")
        return lines
    lines.append("| cohort | snapshot # | cloud_provider | region | endpoint_ip | status |")
    lines.append("|--------|-----------:|----------------|--------|-------------|--------|")
    for cohort in sorted(artifact.network_paths.keys()):
        for idx, entry in enumerate(artifact.network_paths[cohort]):
            if isinstance(entry, M6_1_2NetworkPath):
                lines.append(
                    f"| `{cohort}` | {idx} | {entry.cloud_provider} | "
                    f"{entry.region or '—'} | `{entry.endpoint_ip}` | ok |"
                )
            else:
                lines.append(f"| `{cohort}` | {idx} | — | — | — | error: `{entry.error}` |")
    lines.append("")
    return lines


# --- Markdown top-level rendering ------------------------------------------


def render_markdown(artifact: M6_2SweepArtifact, *, sweep_mode: M6_2SweepMode) -> str:
    """Render the full M6.2 markdown report.

    Section order follows ``contracts/artifact-schema.md``: leading integrity
    callouts → run meta → primary sections 1-4 → auxiliary subsections 5-9 →
    network paths → method/background.
    """
    lines: list[str] = []
    lines.extend(_render_run_meta(artifact))
    lines.extend(_render_leading_integrity_headers(artifact))
    lines.extend(_render_production_latency_budget(artifact, sweep_mode=sweep_mode))
    lines.extend(_render_early_eos_audit(artifact))
    lines.extend(_render_tpot_curves(artifact, sweep_mode=sweep_mode))
    lines.extend(_render_engine_cost_decomposition(artifact, sweep_mode=sweep_mode))
    lines.extend(_render_protocol_crossover(artifact, sweep_mode=sweep_mode))
    lines.extend(_render_kv_pressure(artifact))
    lines.extend(_render_null_anchor_validation(artifact))
    lines.extend(_render_anchor_latency_trajectory(artifact))
    lines.extend(_render_failure_summary(artifact))
    lines.extend(_render_sweep_wall_clock_timeline(artifact, sweep_mode=sweep_mode))
    lines.extend(_render_network_paths(artifact))
    lines.extend(_render_method_background())
    return "\n".join(lines) + "\n"


# --- Atomic two-path writer (FR-015) ---------------------------------------


def write_m6_2_report(
    artifact: M6_2SweepArtifact,
    md_path: Path,
    json_path: Path,
    *,
    sweep_mode: M6_2SweepMode,
) -> None:
    """Write the markdown + JSON pair atomically per FR-015 two-path routing.

    Output paths are resolved upstream by :func:`m6_2_validate.infer_output_path`;
    this writer trusts the paths it receives without re-inferring them.
    """
    payload = render_json(artifact)
    md = render_markdown(artifact, sweep_mode=sweep_mode)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
