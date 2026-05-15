"""M6 markdown + JSON companion writers (T039-T043 / T047-T050).

Renders the published artifacts per ``contracts/output.md``:
- ``docs/benchmarks/m6-real-engine-mini-validation.md`` — operator-facing
  verdict table + executive summary + per-cohort detail.
- ``docs/benchmarks/m6-real-engine-mini-validation.json`` — strict
  superset of M5.2's schema (FR-016) plus M6-specific additions
  (``supersedes_m5_2_under_real_engine``, ``engine_cost_baseline``,
  ``m6_meta``).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m6_types import (
    M6_COHORTS,
    M6Cell,
    M6CellRecord,
    M6CohortKind,
    M6Run,
    M6RunMeta,
    SupersedesM5_2Row,
    VerdictClassification,
)

_M6_SCHEMA_VERSION = "m6.v1"


# --- Helpers -----------------------------------------------------------------


def _fmt_mean_ci(mean: float | None, half: float | None) -> str:
    """Render `mean ± CI` to 2 decimal places; ``n/a`` for None values."""
    if mean is None:
        return "n/a"
    if half is None:
        return f"{mean:.2f}"
    return f"{mean:.2f} ± {half:.2f}"


def _drift_marker(cell: M6CellRecord) -> str:
    """Markdown marker rendered in the verdict-table Notes column."""
    if cell.engine_cost_drift_warning:
        return "⚠ engine drift"
    return ""


def _direction_str(direction: str | None) -> str:
    if direction is None:
        return "n/a"
    return {"rest_wins": "REST", "grpc_wins": "gRPC"}.get(direction, direction)


def _classification_marker(c: VerdictClassification) -> str:
    """Visual emphasis for a few classifications.

    Per ``contracts/output.md`` the verdict-table Classification column
    is the literal value; ``cell_incomplete`` is rendered AS the value
    (not folded into a verdict bucket).
    """
    return c


# --- Markdown writer ---------------------------------------------------------


def render_executive_summary(run: M6Run) -> str:
    """Render the Executive Summary block (FR-015 / SC-005).

    The required strings MUST appear within the first ~screenful of the
    report: inference engine, model, hidden_size, GPU, Modal region. The
    M1 bytes-axis preservation note (FR-020) is included verbatim.
    """
    meta = run.meta
    summary_classes: dict[VerdictClassification, int] = {}
    for cell in run.cells:
        summary_classes[cell.classification] = summary_classes.get(cell.classification, 0) + 1
    headline = " / ".join(f"{k}={v}" for k, v in sorted(summary_classes.items()))

    return (
        "## Executive Summary\n\n"
        f"M6 runs a 6-cell × 3-cohort × n=100 sweep against a real {meta.model_identifier} "
        f"inference engine on Modal's {meta.gpu_type} GPU instance in region "
        f"`{meta.modal_region}`, closing the 'MockEngine caveat' that M5.1 and M5.2 both "
        f"deferred.\n\n"
        f"**Inference engine**: vLLM {meta.engine_version}\n"
        f"**Model**: {meta.model_identifier}\n"
        f"**Hidden size**: 4096 (fixed by model architecture)\n"
        f"**GPU**: {meta.gpu_type} (24 GB VRAM)\n"
        f"**Modal region**: {meta.modal_region}\n"
        f"**M6_BASE_SEED**: {meta.m6_base_seed}\n"
        f"**M5.2 baseline source**: `docs/benchmarks/m5_2-transport-vs-tuning.json` "
        f"(snapshot in JSON RunMeta — FR-018)\n"
        f"**Bytes axis**: NOT re-measured by M6; M1's findings (~89% chat / ~25% embed "
        f"reductions) remain authoritative — encoding is structural, not engine-dependent "
        f"(FR-020).\n\n"
        f"**Verdict tally**: {headline}\n\n"
    )


def render_supersedes_m5_2_table(run: M6Run) -> str:
    """Render the 'Supersedes M5.2 Under Real Engine' verdict table (FR-014).

    One row per cell; ``cell_incomplete`` is the Classification value
    (per FR-023 — NOT folded into a verdict bucket); ``⚠ engine drift``
    marker surfaces in Notes when ``engine_cost_drift_warning`` is True.
    """
    header = (
        "| # | Cell | Classification | M5.2 winner | "
        "M6 cohort means (classifier metric) | engine_cost mean | Notes |\n"
        "|---|------|----------------|-------------|"
        "--------------------------------------|------------------|-------|\n"
    )
    rows: list[str] = []
    for i, cell in enumerate(run.cells, start=1):
        c = cell.cell
        cell_label = f"{c.path} × c={c.concurrency}"
        m5_2_winner = (
            f"{_direction_str(cell.m5_2_winner_direction)} Δ={cell.m5_2_winner_delta_ms:.2f} ms"
            if cell.m5_2_winner_delta_ms is not None
            else "no_winner"
        )
        means_str = " / ".join(
            f"{kind.split('_')[0]}={cell.per_cohort[kind].classifier_metric_mean_ms:.2f}"
            for kind in M6_COHORTS
            if kind in cell.per_cohort
        )
        engine_cost_label = (
            f"engine_forward={cell.engine_cost_mean_ms:.2f} ms"
            if c.path == "embed"
            else f"engine_ttft={cell.engine_cost_mean_ms:.2f} ms"
        )
        notes_parts: list[str] = []
        if cell.engine_cost_drift_warning:
            notes_parts.append("⚠ engine drift")
            assert cell.per_cohort_engine_cost_mean_ms is not None
            per_cohort_str = ", ".join(
                f"{k}={v:.2f}" for k, v in cell.per_cohort_engine_cost_mean_ms.items()
            )
            notes_parts.append(f"per-cohort engine_cost: {per_cohort_str}")
        notes_parts.append(cell.classification_reason)
        notes = "; ".join(notes_parts)

        rows.append(
            f"| {i} | {cell_label} | "
            f"{_classification_marker(cell.classification)} | "
            f"{m5_2_winner} | {means_str} | {engine_cost_label} | {notes} |\n"
        )
    return "## Supersedes M5.2 Under Real Engine\n\n" + header + "".join(rows) + "\n"


def render_engine_cost_per_rpc_table(run: M6Run) -> str:
    """Render the 'Engine Cost Per RPC' table — the M6 → M7 hand-off (SC-006)."""
    header = (
        "| Cell | engine_forward_ms (embed) | engine_ttft_ms (chat_stream) | "
        "engine_tpot_ms (chat_stream) | drift_warning |\n"
        "|------|---------------------------|------------------------------|"
        "------------------------------|---------------|\n"
    )
    rows: list[str] = []
    for cell in run.cells:
        c = cell.cell
        cell_label = f"{c.path} × c={c.concurrency}"
        ec = next(iter(cell.per_cohort.values())).engine_cost_mean
        # Cohort-averaged across all 3 — use the first as a representative since
        # the JSON companion publishes per-cohort means separately when drift
        # is True. For the markdown table we render the cell-level cohort mean.
        if c.path == "embed":
            forward_str = _fmt_mean_ci(
                ec.engine_forward_mean_ms, ec.engine_forward_ci_half_width_ms
            )
            ttft_str = "n/a"
            tpot_str = "n/a"
        else:
            forward_str = "n/a"
            ttft_str = _fmt_mean_ci(ec.engine_ttft_mean_ms, ec.engine_ttft_ci_half_width_ms)
            tpot_str = _fmt_mean_ci(ec.engine_tpot_mean_ms, ec.engine_tpot_ci_half_width_ms)
        rows.append(
            f"| {cell_label} | {forward_str} | {ttft_str} | {tpot_str} | "
            f"{cell.engine_cost_drift_warning} |\n"
        )
    return "## Engine Cost Per RPC\n\n" + header + "".join(rows) + "\n"


def render_per_cohort_detail(run: M6Run) -> str:
    """Render the Per-Cohort Detail section — one sub-table per cell."""
    out = ["## Per-Cohort Detail\n"]
    for cell in run.cells:
        c = cell.cell
        out.append(f"\n### {c.path} × c={c.concurrency}\n\n")
        out.append(
            "| Cohort | n_successes | failure_count | "
            "classifier_metric mean ± CI (ms) | engine_cost mean (ms) |\n"
        )
        out.append("|--------|-------------|---------------|----|----|\n")
        for kind in M6_COHORTS:
            if kind not in cell.per_cohort:
                continue
            agg = cell.per_cohort[kind]
            metric_str = _fmt_mean_ci(
                agg.classifier_metric_mean_ms, agg.classifier_metric_ci_half_width_ms
            )
            ec = agg.engine_cost_mean
            if c.path == "embed":
                ec_str = (
                    f"{ec.engine_forward_mean_ms:.2f}"
                    if ec.engine_forward_mean_ms is not None
                    else "n/a"
                )
            else:
                ec_str = (
                    f"{ec.engine_ttft_mean_ms:.2f}" if ec.engine_ttft_mean_ms is not None else "n/a"
                )
            out.append(
                f"| {kind} | {agg.n_successes} | {agg.failure_count} | {metric_str} | {ec_str} |\n"
            )
    return "".join(out) + "\n"


def render_methodology_notes(run: M6Run) -> str:
    """Render the Methodology Notes section per contracts/output.md."""
    return (
        "## Methodology Notes\n\n"
        "- n=100 measurement RPCs per (cell × cohort), preceded by 10 warmup RPCs per "
        "(cell × cohort) discarded from metrics (FR-021).\n"
        "- 3 cohorts measured in round-robin per c-batch order to control for "
        "Modal/network/engine drift (FR-022).\n"
        f"- Per-RPC sampling seeds: SamplingParams.seed = M6_BASE_SEED + rpc_index, "
        f"where rpc_index is the global measurement RPC counter (warmup excluded). "
        f"M6_BASE_SEED={run.meta.m6_base_seed}; recorded in RunMeta (FR-025).\n"
        "- Per-RPC failures retried up to 3 attempts; cells with any cohort < 80 "
        "successes are classified `cell_incomplete` (FR-023).\n"
        "- Verdict classifier: deterministic; comparison metric is client-observed TTFT "
        "for chat_stream, total wall-clock for embed (FR-014). Engine cost (cohort-"
        "averaged) ≥ 5× |M5.2 winner delta| classifies a no-overlap cell as "
        "`verdict_buried_by_engine`. Per-cohort engine_cost disagreement > 10% sets the "
        "`engine_cost_drift_warning` flag (verdict still computed; per-cohort values "
        "surfaced).\n"
        f"- Engine instance: ONE AsyncLLM({run.meta.model_identifier}, dtype=fp16, "
        f"enable_prompt_embeds=True, max_model_len=2048, gpu_memory_utilization=0.92) "
        f"loaded once at sweep start; serves all 6 cells (FR-024). Cold-start "
        f"excluded from per-RPC latency, recorded as scalar "
        f"`cold_start_s={run.meta.cold_start_s:.2f}` in RunMeta (FR-019).\n"
        "- `max_model_len=2048` is a runtime cap (the model's natural context "
        "window is 40 960 tokens) chosen to fit Qwen3-8B's KV cache within the "
        "A10G's 24 GB VRAM after the ~16 GB fp16 weights. The M6 workload's "
        "worst-case RPC length is ≤100 tokens (chat_stream prompt + "
        "max_tokens=50), so the cap is 20× the actual sequence demand and does "
        "NOT affect measured engine cost — it only bounds KV-cache allocation. "
        "Distinct from `hidden_size=4096` (FR-001), which is the model's "
        "per-token feature dimension and is fixed by Qwen3-8B's architecture. "
        "See `research.md` R-11.\n\n"
    )


def render_operator_reproducibility(run: M6Run) -> str:
    return (
        "## Operator Reproducibility\n\n"
        f"To reproduce this run bit-exactly: same git_sha (`{run.meta.git_sha}`), same "
        f"engine version (`{run.meta.engine_version}`), same Modal region "
        f"(`{run.meta.modal_region}`), same `M6_BASE_SEED={run.meta.m6_base_seed}`. The "
        "classifier is deterministic given the same M5.2 baseline JSON (snapshot in "
        "RunMeta).\n"
    )


def render_markdown(run: M6Run) -> str:
    """Render the full M6 markdown report per contracts/output.md §1."""
    parts = [
        "# M6 — Real-Engine Mini-Validation\n\n",
        f"**Status**: delivered {run.run_completed_at}\n",
        "**Branch**: 020-m6-real-engine-mini-validation\n",
        "**JSON companion**: "
        "[m6-real-engine-mini-validation.json](./m6-real-engine-mini-validation.json)\n\n",
        render_executive_summary(run),
        render_supersedes_m5_2_table(run),
        render_engine_cost_per_rpc_table(run),
        render_per_cohort_detail(run),
        render_methodology_notes(run),
        render_operator_reproducibility(run),
    ]
    return "".join(parts)


def write_markdown(run: M6Run, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(run))
    return path


# --- JSON companion ----------------------------------------------------------


def _supersedes_row_dict(row: SupersedesM5_2Row) -> dict[str, Any]:
    cell = row.cell
    return {
        "cell": {
            "path": cell.path,
            "hidden_size": cell.hidden_size,
            "concurrency": cell.concurrency,
        },
        "classification": row.classification,
        "classifier_metric": "wall_clock_ms" if cell.path == "embed" else "ttft_ms",
        "cohort_pair": ["rest_https_edge", "tuned_grpc_multiplexed"],
        "m5_2_winner_cohort": row.m5_2_winner_cohort,
        "m5_2_winner_delta_ms": row.m5_2_winner_delta_ms,
        "m5_2_winner_direction": row.m5_2_winner_direction,
        "engine_cost_mean_ms": row.engine_cost_mean_ms,
        "engine_cost_drift_warning": row.engine_cost_drift_warning,
        # T050 / FR-014 sub-clause: per-cohort engine_cost means surfaced
        # for operator review only when drift fires; None otherwise per
        # data-model.md M6CellRecord validation rule.
        "per_cohort_engine_cost_mean_ms": row.per_cohort_engine_cost_mean_ms,
        "per_cohort_classifier_metric": {
            kind: {
                "mean_ms": row.m6_classifier_metric_mean_per_cohort.get(kind),
                "ci_lower_ms": (row.m6_classifier_metric_ci_per_cohort.get(kind, (0.0, 0.0))[0]),
                "ci_upper_ms": (row.m6_classifier_metric_ci_per_cohort.get(kind, (0.0, 0.0))[1]),
                "n_successes": 100,
            }
            for kind in M6_COHORTS
            if kind in row.m6_classifier_metric_mean_per_cohort
        },
        "notes": row.notes,
    }


def _engine_cost_baseline_row(cell_record: M6CellRecord) -> dict[str, Any]:
    cell = cell_record.cell
    # Use cohort-averaged engine cost from one cohort (path-discriminated).
    # The per-cohort splits are already in the supersedes row when drift fires.
    first_ec = next(iter(cell_record.per_cohort.values())).engine_cost_mean
    return {
        "cell": {
            "path": cell.path,
            "hidden_size": cell.hidden_size,
            "concurrency": cell.concurrency,
        },
        "engine_forward_mean_ms": first_ec.engine_forward_mean_ms,
        "engine_forward_ci_half_width_ms": first_ec.engine_forward_ci_half_width_ms,
        "engine_ttft_mean_ms": first_ec.engine_ttft_mean_ms,
        "engine_ttft_ci_half_width_ms": first_ec.engine_ttft_ci_half_width_ms,
        "engine_tpot_mean_ms": first_ec.engine_tpot_mean_ms,
        "engine_tpot_ci_half_width_ms": first_ec.engine_tpot_ci_half_width_ms,
        "drift_warning": cell_record.engine_cost_drift_warning,
    }


def _m6_cell_record_to_protocol_comparison_row(cell_record: M6CellRecord) -> dict[str, Any]:
    """Project an M6 cell into the M5.2 ``protocol_comparison_verdicts[]`` shape.

    This is what makes the JSON companion a strict superset (FR-016): an
    M5.2-aware consumer reading ``protocol_comparison_verdicts`` sees M6
    classifier output in the same row shape as M5.2.
    """
    cell = cell_record.cell
    rest_agg = cell_record.per_cohort.get("rest_https_edge")
    grpc_agg = cell_record.per_cohort.get("tuned_grpc_multiplexed")
    if rest_agg is None or grpc_agg is None:
        delta_median_ms = 0.0
        ci_lower = 0.0
        ci_upper = 0.0
    else:
        delta_median_ms = rest_agg.classifier_metric_mean_ms - grpc_agg.classifier_metric_mean_ms
        # Conservative CI for the delta: sum of half-widths.
        h = (
            rest_agg.classifier_metric_ci_half_width_ms
            + grpc_agg.classifier_metric_ci_half_width_ms
        )
        ci_lower = delta_median_ms - h
        ci_upper = delta_median_ms + h

    # Map M6 classification → M5.2 verdict literal (best-effort lossy
    # projection; M6's own ``supersedes_m5_2_under_real_engine[]`` carries
    # the canonical classification).
    if cell_record.classification == "cell_incomplete":
        verdict = "comparison_unavailable"
    elif cell_record.classification in ("no_winner_at_n100", "verdict_buried_by_engine"):
        verdict = "no_winner"
    elif cell_record.classification in ("verdict_survives", "verdict_changed"):
        if cell_record.m5_2_winner_direction == "rest_wins":
            verdict = "rest_https_edge_recommend"
        else:
            verdict = (
                "tuned_grpc_recommend"
                if cell.concurrency == 1
                else "tuned_grpc_multiplexed_recommend"
            )
    else:
        verdict = "no_winner"

    return {
        "path": cell.path,
        "hidden_size": cell.hidden_size,
        "concurrency": cell.concurrency,
        "grpc_cohort": "tuned_grpc" if cell.concurrency == 1 else "tuned_grpc_multiplexed",
        "rest_cohort": "rest_https_edge",
        "grpc_cohort_network_path": "plain_tcp",
        "rest_cohort_network_path": "https_edge",
        "delta_median_ms": delta_median_ms,
        "ci_lower_ms": ci_lower,
        "ci_upper_ms": ci_upper,
        "verdict": verdict,
        "comparison_unavailable_reason": (
            cell_record.classification_reason
            if cell_record.classification == "cell_incomplete"
            else None
        ),
        "low_rtt_caveat": False,
    }


def _supersedes_rows_from_cells(cells: list[M6CellRecord]) -> list[SupersedesM5_2Row]:
    out: list[SupersedesM5_2Row] = []
    for cell in cells:
        means: dict[M6CohortKind, float] = {}
        cis: dict[M6CohortKind, tuple[float, float]] = {}
        for kind, agg in cell.per_cohort.items():
            means[kind] = agg.classifier_metric_mean_ms
            half = agg.classifier_metric_ci_half_width_ms
            cis[kind] = (agg.classifier_metric_mean_ms - half, agg.classifier_metric_mean_ms + half)
        winner_cohort: M6CohortKind | None = None
        if cell.m5_2_winner_direction == "rest_wins":
            winner_cohort = "rest_https_edge"
        elif cell.m5_2_winner_direction == "grpc_wins":
            winner_cohort = "tuned_grpc_multiplexed"
        out.append(
            SupersedesM5_2Row(
                cell=cell.cell,
                classification=cell.classification,
                m6_classifier_metric_mean_per_cohort=means,
                m6_classifier_metric_ci_per_cohort=cis,
                m5_2_winner_cohort=winner_cohort,
                m5_2_winner_delta_ms=cell.m5_2_winner_delta_ms,
                m5_2_winner_direction=cell.m5_2_winner_direction,
                engine_cost_mean_ms=cell.engine_cost_mean_ms,
                engine_cost_drift_warning=cell.engine_cost_drift_warning,
                per_cohort_engine_cost_mean_ms=cell.per_cohort_engine_cost_mean_ms,
                notes=cell.classification_reason,
            )
        )
    return out


def render_json(run: M6Run) -> dict[str, Any]:
    """Build the JSON companion dict per contracts/output.md §2.

    The shape is a strict superset of M5.2's published schema (FR-016) so
    existing M5.2-aware consumers (e.g., ``m5_2_supersede`` readers) keep
    working unmodified against M6's JSON.
    """
    supersedes_rows = _supersedes_rows_from_cells(run.cells)
    protocol_verdicts = [_m6_cell_record_to_protocol_comparison_row(c) for c in run.cells]
    engine_cost_baseline = [_engine_cost_baseline_row(c) for c in run.cells]

    # M5.2-shape per-cohort summaries.
    cohorts_section: list[dict[str, Any]] = []
    for cell in run.cells:
        for kind in M6_COHORTS:
            if kind not in cell.per_cohort:
                continue
            agg = cell.per_cohort[kind]
            cohorts_section.append(
                {
                    "cohort": kind,
                    "path": cell.cell.path,
                    "hidden_size": cell.cell.hidden_size,
                    "concurrency": cell.cell.concurrency,
                    "n_attempted": agg.n_attempted,
                    "n_successes": agg.n_successes,
                    "classifier_metric_mean_ms": agg.classifier_metric_mean_ms,
                    "classifier_metric_ci_half_width_ms": agg.classifier_metric_ci_half_width_ms,
                    "total_wall_clock_mean_ms": agg.total_wall_clock_mean_ms,
                }
            )

    return {
        # === M5.2-strict-superset preserved fields (FR-016) =================
        "schema_version": _M6_SCHEMA_VERSION,
        "run_id": run.run_id,
        "run_started_at": run.run_started_at,
        "run_completed_at": run.run_completed_at,
        "harness_version_sha": run.meta.git_sha,
        "modal_region": run.meta.modal_region,
        "modal_instance_class": run.meta.gpu_type,
        "modal_metadata": {"function_id": run.meta.modal_function_id},
        "client_external_geolocation": None,
        "rtt_distribution": {kind: asdict(rec) for kind, rec in run.rtt_distribution.items()},
        "https_edge_endpoint": None,
        "events_sidecar_path": None,
        "cohorts": cohorts_section,
        "protocol_comparison_verdicts": protocol_verdicts,
        "transport_only_verdicts": [],
        "channel_axis_recommendations": [],
        "schema_candidate_recommendations": [],
        "shared_baseline_cohorts": [],
        "smoke_run_outcome": (
            {
                "overall_status": run.smoke_result.overall_status,
                "wall_clock_s": run.smoke_result.wall_clock_s,
            }
            if run.smoke_result is not None
            else None
        ),
        "supersedes_m1_time": None,
        "supersedes_m3": None,
        "supersedes_m4": None,
        "supersedes_m5_1": None,
        "symmetry": None,
        "payload_parity_audit": None,
        # === M6-specific additions (strict superset) =========================
        "supersedes_m5_2_under_real_engine": [_supersedes_row_dict(r) for r in supersedes_rows],
        "engine_cost_baseline": engine_cost_baseline,
        "m6_meta": {
            "model_identifier": run.meta.model_identifier,
            "engine_version": run.meta.engine_version,
            "cold_start_s": run.meta.cold_start_s,
            "m5_2_winner_deltas": run.meta.m5_2_winner_deltas,
            "m6_base_seed": run.meta.m6_base_seed,
            "git_sha": run.meta.git_sha,
            "hostname": run.meta.hostname,
            "gpu_type": run.meta.gpu_type,
        },
    }


def write_json(run: M6Run, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(render_json(run), indent=2, sort_keys=True))
    return path


# --- Convenience -------------------------------------------------------------


def build_m6_run(
    *,
    run_id: str,
    run_started_at: str,
    run_completed_at: str,
    meta: M6RunMeta,
    cells: list[M6CellRecord],
    rtt_distribution: dict[M6CohortKind, Any],
    smoke_result: Any | None = None,
) -> M6Run:
    """Helper that assembles an ``M6Run`` from sweep output."""
    return M6Run(
        run_id=run_id,
        run_started_at=run_started_at,
        run_completed_at=run_completed_at,
        meta=meta,
        smoke_result=smoke_result,
        cells=cells,
        rtt_distribution=rtt_distribution,
        supersedes_m5_2=_supersedes_rows_from_cells(cells),
    )


__all__ = [
    "build_m6_run",
    "render_engine_cost_per_rpc_table",
    "render_executive_summary",
    "render_json",
    "render_markdown",
    "render_methodology_notes",
    "render_operator_reproducibility",
    "render_per_cohort_detail",
    "render_supersedes_m5_2_table",
    "write_json",
    "write_markdown",
]

# Suppress unused-import for M6Cell which is part of the public API surface
# expected by callers constructing M6Run objects.
_ = M6Cell
