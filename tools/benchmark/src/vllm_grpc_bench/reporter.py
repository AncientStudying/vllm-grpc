from __future__ import annotations

import csv
import dataclasses
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from vllm_grpc_bench.anchor_trajectory import (
    compute_insufficient_snapshots_header_fired,
    compute_intra_sweep_drift_header_fired,
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
