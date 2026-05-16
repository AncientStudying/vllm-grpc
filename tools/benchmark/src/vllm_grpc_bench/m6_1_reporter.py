"""M6.1 reporter — markdown + JSON output writers.

Per spec FR-020, FR-021, FR-022, FR-026, FR-027, FR-029, FR-030 and
``contracts/output.md`` §1 / §2.

The JSON companion is a strict superset of M6's published schema so
existing M6-aware consumers continue to work unmodified.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m6_1_types import (
    M6_1_COHORTS,
    EnginePathDifferentialRow,
    M6_1CellRecord,
    M6_1CohortKind,
    M6_1Run,
    SupersedesM6Row,
    VerdictClassification,
    cell_key,
)

_M6_1_SCHEMA_VERSION: str = "m6_1.v1"


# --- Markdown helpers --------------------------------------------------------


def _fmt_mean_ci(mean: float, half: float) -> str:
    if mean == 0.0 and half == 0.0:
        return "—"
    return f"{mean:.2f} ± {half:.2f}"


def _direction_str(direction: str | None) -> str:
    return direction or "n/a"


def _cell_label(cell_record: M6_1CellRecord) -> str:
    c = cell_record.cell
    return f"{c.path} × c={c.concurrency}"


def _classification_marker(c: VerdictClassification) -> str:
    if c == "verdict_changed":
        return "⚠"
    return ""


def _drift_flags(row: SupersedesM6Row) -> str:
    flags: list[str] = []
    if row.engine_cost_drift_warning:
        flags.append("⚠ engine drift")
    if row.chat_stream_control_drift_warning:
        flags.append("⚠ chat_stream drift")
    return ", ".join(flags) if flags else "—"


def render_executive_summary(run: M6_1Run) -> str:
    meta = run.run_meta
    lines = [
        "# M6.1 — Real-Prompt-Embeds Engine Path",
        "",
        f"**Status**: delivered {run.run_completed_at[:10]}",
        "**Branch**: 022-m6-1-real-prompt-embeds",
        "**JSON companion**: [m6_1-real-prompt-embeds.json](./m6_1-real-prompt-embeds.json)",
        "",
        "## Executive Summary",
        "",
        f"**Inference engine**: vLLM {meta.engine_version} "
        f"(M6 baseline: vLLM {meta.m6_baseline_engine_version} — see methodology note below)",
        f"**Model**: {meta.model_identifier}",
        f"**Hidden size**: {meta.hidden_size} (fixed by model architecture)",
        f"**GPU**: {meta.gpu_type} (24 GB VRAM)",
        f"**Modal region**: {meta.modal_region}",
        f"**M6_1_BASE_SEED**: {meta.M6_1_BASE_SEED}",
        f"**Pinned client torch**: {meta.torch_version} (validated at driver-start — FR-006)",
        f"**Prompt-embeds seq_len**: {meta.seq_len} "
        "(tokenised against Qwen3-8B's tokenizer from M6's `embed_<hex>` digest "
        "format — FR-028 / R-3)",
        "**M6 baseline source**: docs/benchmarks/m6-real-engine-mini-validation.json "
        "(m6_winner_deltas snapshotted in JSON RunMeta — FR-008)",
        "**Bytes axis**: NOT re-measured by M6.1; M1's findings remain authoritative "
        "— encoding is structural, not engine-dependent (FR-024).",
    ]
    return "\n".join(lines) + "\n"


def render_supersedes_m6_table(run: M6_1Run) -> str:
    header = (
        "## Supersedes M6 Under enable_prompt_embeds\n\n"
        "| # | Cell | Classification | M6 winner | M6.1 cohort means "
        "(classifier metric) | engine_cost mean | Drift flags | Notes |\n"
        "|---|------|----------------|-----------|-----------------------"
        "-----------------|------------------|-------------|-------|\n"
    )
    body: list[str] = []
    for i, row in enumerate(run.supersedes_m6_under_enable_prompt_embeds, start=1):
        cell_label = f"{row.cell.path} × c={row.cell.concurrency}"
        winner = (
            f"{row.m6_winner_cohort} Δ={row.m6_winner_delta_ms:.2f}ms"
            if row.m6_winner_cohort and row.m6_winner_delta_ms is not None
            else "(M6: no usable delta)"
        )
        means_parts = []
        for cohort in M6_1_COHORTS:
            v = row.m6_1_classifier_metric_mean_per_cohort.get(cohort, 0.0)
            means_parts.append(f"{cohort}={v:.2f}ms")
        cohort_means = " / ".join(means_parts)
        engine_cost = f"{row.engine_cost_mean_ms:.2f}ms"
        body.append(
            f"| {i} | {cell_label} | {row.classification}"
            f"{_classification_marker(row.classification)} | {winner} | "
            f"{cohort_means} | {engine_cost} | {_drift_flags(row)} | "
            f"{row.notes} |"
        )
    return header + "\n".join(body) + "\n"


def render_engine_path_differential(run: M6_1Run) -> str:
    header = (
        "## Engine Path Differential (M6.1 − M6)\n\n"
        "For each cell, the per-cohort classifier-metric delta (M6.1 mean − "
        "M6 mean) and the per-cell engine_cost_mean delta. Units are ms; "
        "95% CI half-widths are combined via the standard sqrt-of-sum-of-"
        "squared-CIs formula (FR-020).\n\n"
        "| Cell | rest_https_edge Δ (ms ± CI) | default_grpc Δ (ms ± CI) | "
        "tuned_grpc_multiplexed Δ (ms ± CI) | engine_cost_mean Δ (ms ± CI) | "
        "n_successes (per cohort) |\n"
        "|------|-----------------------------|---------------------------|"
        "--------------------------------------|----------------------------"
        "--|---------------------------|\n"
    )
    body: list[str] = []
    for row in run.engine_path_differential:
        cell_label = f"{row.cell.path} × c={row.cell.concurrency}"
        cohort_cells: list[str] = []
        for cohort in M6_1_COHORTS:
            delta = row.per_cohort_classifier_metric_delta_ms.get(cohort, 0.0)
            half = row.per_cohort_classifier_metric_delta_ci_half_width_ms.get(cohort, 0.0)
            cohort_cells.append(f"{delta:+.2f} ± {half:.2f}")
        engine_cost_str = (
            f"{row.engine_cost_mean_delta_ms:+.2f} ± "
            f"{row.engine_cost_mean_delta_ci_half_width_ms:.2f}"
        )
        n_succ = " / ".join(str(row.per_cohort_n_successes.get(c, 0)) for c in M6_1_COHORTS)
        body.append(
            f"| {cell_label} | {cohort_cells[0]} | {cohort_cells[1]} | "
            f"{cohort_cells[2]} | {engine_cost_str} | {n_succ} |"
        )
    return header + "\n".join(body) + "\n"


def render_engine_cost_per_rpc(run: M6_1Run) -> str:
    header = (
        "## Engine Cost Per RPC\n\n"
        "| Cell | engine_forward_ms (embed) | engine_ttft_ms (chat_stream) | "
        "engine_tpot_ms (chat_stream) | drift_warning |\n"
        "|------|---------------------------|------------------------------|"
        "------------------------------|---------------|\n"
    )
    body: list[str] = []
    for c in run.cells:
        cell_label = _cell_label(c)
        # Average per-cohort engine_cost — already in c.engine_cost_mean_ms.
        if c.cell.path == "embed":
            ec_str = f"{c.engine_cost_mean_ms:.2f}"
            ttft_str = "n/a"
            tpot_str = "n/a"
        else:
            ec_str = "n/a"
            ttft_str = f"{c.engine_cost_mean_ms:.2f}"
            # Average TPOT across cohorts (when present).
            tpots = [
                agg.engine_cost_mean.engine_tpot_mean_ms
                for agg in c.per_cohort.values()
                if agg.engine_cost_mean.engine_tpot_mean_ms is not None
            ]
            tpot_str = f"{sum(tpots) / max(1, len(tpots)):.2f}" if tpots else "n/a"
        body.append(
            f"| {cell_label} | {ec_str} | {ttft_str} | {tpot_str} | {c.engine_cost_drift_warning} |"
        )
    return header + "\n".join(body) + "\n"


def render_per_cohort_detail(run: M6_1Run) -> str:
    out: list[str] = ["## Per-Cohort Detail", ""]
    for c in run.cells:
        out.append(f"### {_cell_label(c)}")
        out.append("")
        out.append(
            "| Cohort | n_successes | failure_count | "
            "wall_clock mean ± CI (ms) | classifier_metric mean ± CI (ms) | "
            "engine_forward / TTFT mean ± CI (ms) |"
        )
        out.append(
            "|--------|-------------|---------------|"
            "---------------------------|-----------------------------------|"
            "--------------------------------------|"
        )
        for cohort in M6_1_COHORTS:
            agg = c.per_cohort[cohort]
            wall = _fmt_mean_ci(agg.total_wall_clock_mean_ms, agg.total_wall_clock_ci_half_width_ms)
            metric = _fmt_mean_ci(
                agg.classifier_metric_mean_ms,
                agg.classifier_metric_ci_half_width_ms,
            )
            if c.cell.path == "embed":
                ec_mean = agg.engine_cost_mean.engine_forward_mean_ms
                ec_half = agg.engine_cost_mean.engine_forward_ci_half_width_ms
            else:
                ec_mean = agg.engine_cost_mean.engine_ttft_mean_ms
                ec_half = agg.engine_cost_mean.engine_ttft_ci_half_width_ms
            ec_str = _fmt_mean_ci(ec_mean or 0.0, ec_half or 0.0)
            out.append(
                f"| {cohort} | {agg.n_successes} | {agg.failure_count} | "
                f"{wall} | {metric} | {ec_str} |"
            )
        out.append("")
    return "\n".join(out)


def render_methodology_notes(run: M6_1Run) -> str:
    meta = run.run_meta
    note_ev = (
        "NOTE: the comparison is informational; the 'Engine path differential' "
        "read is cleanest when both versions match. The legacy M6 baseline "
        "records `engine_version=unknown` because M6's version-reader helper "
        "landed post-sweep — future M6 republishes feed cleanly through the "
        "same plumbing."
        if (
            meta.engine_version != meta.m6_baseline_engine_version
            or meta.m6_baseline_engine_version == "unknown"
        )
        else ""
    )
    lines = [
        "## Methodology Notes",
        "",
        "- n=100 measurement RPCs per (cell × cohort), preceded by 10 warmup "
        "RPCs per (cell × cohort) discarded from metrics (FR-015).",
        "- 3 cohorts measured in round-robin per c-batch order to control for "
        "Modal/network/engine drift (FR-016).",
        f"- Per-RPC sampling seeds: `SamplingParams.seed = M6_1_BASE_SEED + "
        f"rpc_index`, where rpc_index is the global measurement RPC counter "
        f"(warmup excluded). `M6_1_BASE_SEED={meta.M6_1_BASE_SEED}`; recorded "
        "in RunMeta (FR-019).",
        "- Per-RPC tensor values: `torch.Generator(device='cpu').manual_seed("
        "M6_1_BASE_SEED + rpc_index)` then `torch.randn([seq_len, 4096], "
        "dtype=torch.float16, generator=...)`. Only the values vary per RPC; "
        "tensor shape is fixed (FR-028).",
        "- Per-RPC failures retried up to 3 attempts; cells with any cohort < 80 "
        "successes are classified `cell_incomplete` (FR-017).",
        "- Verdict classifier: deterministic; comparison metric is "
        "client-observed TTFT for chat_stream, total wall-clock for embed "
        "(FR-011). Cells whose M6 verdict was `no_winner_at_n100`, "
        "`cell_incomplete`, OR `verdict_buried_by_engine` classify as "
        "`no_winner_at_n100` regardless of M6.1 CI overlap (FR-010 "
        "sub-clause). engine_cost (cohort-averaged simple unweighted mean per "
        "FR-022) ≥ 5× |M6 winner delta| classifies a no-overlap cell as "
        "`verdict_buried_by_engine`. Per-cohort engine_cost disagreement > 10% "
        "sets the `engine_cost_drift_warning` flag (verdict still computed; "
        "per-cohort values surfaced).",
        "- chat_stream control-drift check (FR-029): each chat_stream cell × "
        "cohort's M6.1 95% CI on TTFT is compared against M6's published 95% "
        "CI; non-overlap on at least one cohort sets the "
        "`chat_stream_control_drift_warning` flag on that cell. Diagnostic "
        "only — verdicts still computed.",
        "- Engine instance: ONE "
        "`AsyncLLM(Qwen/Qwen3-8B, dtype=fp16, enable_prompt_embeds=True, "
        "max_model_len=2048, gpu_memory_utilization=0.92)` loaded once at "
        "sweep start (FR-014). Cold-start excluded from per-RPC latency, "
        f"recorded as scalar `cold_start_s={meta.cold_start_s:.2f}` in RunMeta. "
        "Engine config UNCHANGED from M6 per FR-007.",
        f"- Engine version comparison (FR-030): M6.1's pinned vLLM version is "
        f"**{meta.engine_version}** (read from `pyproject.toml`); the M6 "
        f"baseline JSON's recorded vLLM version is "
        f"**{meta.m6_baseline_engine_version}**.",
    ]
    if note_ev:
        lines.append(f"  {note_ev}")
    lines.append(
        f"- Client torch version: **{meta.torch_version}** (matches "
        "vllm==0.20.1's transitive pin per FR-006). The driver validates "
        "`torch.__version__` at driver-start and exits with a clear "
        "actionable error if mismatched."
    )
    return "\n".join(lines) + "\n"


def render_operator_reproducibility(run: M6_1Run) -> str:
    return (
        "## Operator Reproducibility\n\n"
        f"To reproduce this run bit-exactly: same git_sha "
        f"(`{run.run_meta.git_sha}`), same vLLM engine version "
        f"(`{run.run_meta.engine_version}`), same client torch version "
        f"(`{run.run_meta.torch_version}`), same Modal region "
        f"(`{run.run_meta.modal_region}`), same `M6_1_BASE_SEED` "
        f"(`{run.run_meta.M6_1_BASE_SEED}`), and the same M6 baseline JSON "
        "(snapshotted in `run_meta.m6_winner_deltas`). The classifier is "
        "deterministic given these inputs (SC-006).\n"
    )


def render_smoke_result_section(run: M6_1Run) -> str:
    if run.smoke_result is None:
        return ""
    sr = run.smoke_result
    out = [
        "## Smoke Result",
        "",
        f"Overall status: **{sr.overall_status}**  (wall-clock "
        f"{sr.wall_clock_s:.1f}s — SC-002 budget 300s)",
        "",
        "| Cell | Cohort | Status | Reason |",
        "|------|--------|--------|--------|",
    ]
    for o in sr.outcomes:
        out.append(
            f"| {o.cell.path} × c={o.cell.concurrency} | {o.cohort} | {o.status} | {o.reason} |"
        )
    out.append("")
    out.append(
        "_note: chat_stream control-drift check is full-sweep-only "
        "(FR-012/FR-029) — runs after the n=100 sweep completes._"
    )
    out.append("")
    return "\n".join(out)


def render_markdown(run: M6_1Run) -> str:
    sections = [
        render_executive_summary(run),
        render_supersedes_m6_table(run),
        render_engine_path_differential(run),
        render_engine_cost_per_rpc(run),
        render_per_cohort_detail(run),
        render_smoke_result_section(run),
        render_methodology_notes(run),
        render_operator_reproducibility(run),
    ]
    return "\n".join(section for section in sections if section)


def write_markdown(run: M6_1Run, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(run))
    return path


# --- JSON rendering ---------------------------------------------------------


def _supersedes_row_dict(row: SupersedesM6Row) -> dict[str, Any]:
    return {
        "cell": asdict(row.cell),
        "classification": row.classification,
        "classifier_metric": ("wall_clock_ms" if row.cell.path == "embed" else "ttft_ms"),
        "cohort_pair": list(("rest_https_edge", "tuned_grpc_multiplexed")),
        "m6_winner_cohort": row.m6_winner_cohort,
        "m6_winner_delta_ms": row.m6_winner_delta_ms,
        "m6_winner_direction": row.m6_winner_direction,
        "engine_cost_mean_ms": row.engine_cost_mean_ms,
        "engine_cost_drift_warning": row.engine_cost_drift_warning,
        "chat_stream_control_drift_warning": row.chat_stream_control_drift_warning,
        "per_cohort_classifier_metric": {
            kind: {
                "mean_ms": row.m6_1_classifier_metric_mean_per_cohort.get(kind, 0.0),
                "ci_lower_ms": row.m6_1_classifier_metric_ci_per_cohort.get(kind, (0.0, 0.0))[0],
                "ci_upper_ms": row.m6_1_classifier_metric_ci_per_cohort.get(kind, (0.0, 0.0))[1],
            }
            for kind in M6_1_COHORTS
        },
        "notes": row.notes,
    }


def _differential_row_dict(row: EnginePathDifferentialRow) -> dict[str, Any]:
    return {
        "cell": asdict(row.cell),
        "per_cohort_classifier_metric_delta_ms": dict(row.per_cohort_classifier_metric_delta_ms),
        "per_cohort_classifier_metric_delta_ci_half_width_ms": dict(
            row.per_cohort_classifier_metric_delta_ci_half_width_ms
        ),
        "engine_cost_mean_delta_ms": row.engine_cost_mean_delta_ms,
        "engine_cost_mean_delta_ci_half_width_ms": (row.engine_cost_mean_delta_ci_half_width_ms),
        "per_cohort_n_successes": dict(row.per_cohort_n_successes),
    }


def _cohort_summary(c: M6_1CellRecord) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for kind in M6_1_COHORTS:
        if kind not in c.per_cohort:
            continue
        agg = c.per_cohort[kind]
        out.append(
            {
                "cohort": kind,
                "path": c.cell.path,
                "hidden_size": c.cell.hidden_size,
                "concurrency": c.cell.concurrency,
                "n_attempted": agg.n_attempted,
                "n_successes": agg.n_successes,
                "classifier_metric_mean_ms": agg.classifier_metric_mean_ms,
                "classifier_metric_ci_half_width_ms": (agg.classifier_metric_ci_half_width_ms),
                "total_wall_clock_mean_ms": agg.total_wall_clock_mean_ms,
            }
        )
    return out


def _engine_cost_baseline_row(c: M6_1CellRecord) -> dict[str, Any]:
    """Per-cell row for the M6-shape engine_cost_baseline section."""
    return {
        "cell": asdict(c.cell),
        "engine_cost_mean_ms": c.engine_cost_mean_ms,
        "engine_cost_drift_warning": c.engine_cost_drift_warning,
        "per_cohort_engine_cost_mean_ms": c.per_cohort_engine_cost_mean_ms,
    }


def _protocol_comparison_row(c: M6_1CellRecord) -> dict[str, Any]:
    """Per-cell row for the M5.2-shape protocol_comparison_verdicts section."""
    return {
        "cell": asdict(c.cell),
        "classification": c.classification,
        "classifier_metric": c.classifier_metric,
        "cohort_pair": list(c.cohort_pair),
        "per_cohort_classifier_metric": {
            kind: {
                "mean_ms": c.per_cohort[kind].classifier_metric_mean_ms,
                "ci_lower_ms": (
                    c.per_cohort[kind].classifier_metric_mean_ms
                    - c.per_cohort[kind].classifier_metric_ci_half_width_ms
                ),
                "ci_upper_ms": (
                    c.per_cohort[kind].classifier_metric_mean_ms
                    + c.per_cohort[kind].classifier_metric_ci_half_width_ms
                ),
                "n_successes": c.per_cohort[kind].n_successes,
            }
            for kind in M6_1_COHORTS
        },
    }


def render_json(run: M6_1Run) -> dict[str, Any]:
    cells_dict_list = run.cells
    cohorts_section: list[dict[str, Any]] = []
    for c in cells_dict_list:
        cohorts_section.extend(_cohort_summary(c))

    smoke = (
        {
            "overall_status": run.smoke_result.overall_status,
            "wall_clock_s": run.smoke_result.wall_clock_s,
            "outcomes": [
                {
                    "cell": asdict(o.cell),
                    "cohort": o.cohort,
                    "status": o.status,
                    "reason": o.reason,
                }
                for o in run.smoke_result.outcomes
            ],
        }
        if run.smoke_result is not None
        else None
    )

    return {
        # === M6-strict-superset preserved fields (FR-021) ===================
        "schema_version": _M6_1_SCHEMA_VERSION,
        "run_id": run.run_id,
        "run_started_at": run.run_started_at,
        "run_completed_at": run.run_completed_at,
        "harness_version_sha": run.run_meta.git_sha,
        "modal_region": run.run_meta.modal_region,
        "modal_instance_class": run.run_meta.gpu_type,
        "modal_metadata": {"function_id": run.run_meta.modal_function_id},
        "client_external_geolocation": None,
        "rtt_distribution": {kind: asdict(rec) for kind, rec in run.rtt_distribution.items()},
        "https_edge_endpoint": None,
        "events_sidecar_path": None,
        "cohorts": cohorts_section,
        "protocol_comparison_verdicts": [_protocol_comparison_row(c) for c in cells_dict_list],
        "transport_only_verdicts": [],
        "channel_axis_recommendations": [],
        "schema_candidate_recommendations": [],
        "shared_baseline_cohorts": [],
        "smoke_run_outcome": smoke,
        "supersedes_m1_time": None,
        "supersedes_m3": None,
        "supersedes_m4": None,
        "supersedes_m5_1": None,
        "supersedes_m5_2_under_real_engine": run.m6_meta.get(
            "supersedes_m5_2_under_real_engine_passthrough", []
        ),
        "engine_cost_baseline": [_engine_cost_baseline_row(c) for c in cells_dict_list],
        "symmetry": None,
        "payload_parity_audit": None,
        # === M6.1-specific additions (strict superset per FR-021) ==========
        "supersedes_m6_under_enable_prompt_embeds": [
            _supersedes_row_dict(r) for r in run.supersedes_m6_under_enable_prompt_embeds
        ],
        "engine_path_differential": [
            _differential_row_dict(r) for r in run.engine_path_differential
        ],
        "run_meta": {
            "git_sha": run.run_meta.git_sha,
            "hostname": run.run_meta.hostname,
            "modal_function_id": run.run_meta.modal_function_id,
            "gpu_type": run.run_meta.gpu_type,
            "modal_region": run.run_meta.modal_region,
            "model_identifier": run.run_meta.model_identifier,
            "hidden_size": run.run_meta.hidden_size,
            "M6_1_BASE_SEED": run.run_meta.M6_1_BASE_SEED,
            "seq_len": run.run_meta.seq_len,
            "engine_version": run.run_meta.engine_version,
            "m6_baseline_engine_version": run.run_meta.m6_baseline_engine_version,
            "torch_version": run.run_meta.torch_version,
            "m6_winner_deltas": run.run_meta.m6_winner_deltas,
            "cold_start_s": run.run_meta.cold_start_s,
            "max_model_len": run.run_meta.max_model_len,
            "gpu_memory_utilization": run.run_meta.gpu_memory_utilization,
            "run_started_at": run.run_meta.run_started_at,
            "run_completed_at": run.run_meta.run_completed_at,
        },
        # FR-021 back-reference passthrough — preserves M6's m6_meta block so
        # M6-aware consumers indexing by `m6_meta` still resolve.
        "m6_meta": run.m6_meta,
    }


def write_json(run: M6_1Run, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(render_json(run), indent=2, sort_keys=True, default=str))
    return path


def write_m6_1_report(run: M6_1Run, md_path: Path, json_path: Path) -> None:
    """Write both the markdown report and the JSON companion (FR-020/FR-021)."""
    write_markdown(run, md_path)
    write_json(run, json_path)


__all__ = [
    "render_engine_cost_per_rpc",
    "render_engine_path_differential",
    "render_executive_summary",
    "render_json",
    "render_markdown",
    "render_methodology_notes",
    "render_operator_reproducibility",
    "render_per_cohort_detail",
    "render_smoke_result_section",
    "render_supersedes_m6_table",
    "write_json",
    "write_m6_1_report",
    "write_markdown",
]

# Suppress unused-import warning — cell_key kept for downstream callers.
_ = (cell_key, M6_1CohortKind)
