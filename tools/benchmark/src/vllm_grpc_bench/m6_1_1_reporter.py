"""M6.1.1 — markdown + JSON reporter (FR-019, FR-020, FR-021, FR-022).

Produces ``docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}``:

* **Markdown** — 6-section structure in fixed order per FR-020.
* **JSON companion** — schema_version ``m6_1_1.v1`` with sentinel-object
  dispatch for the two baseline sections (round-2 Q1 / Q2). Strict-superset
  compatibility with M6.1's JSON schema (FR-022).

The reporter is pure: it accepts a populated :class:`M6_1_1Run` (or its
constituent pieces) and writes the two artifacts. ``phase_1_runs[]`` is
append-only per round-3 Q1 — the caller (Phase 1 diagnose orchestrator)
provides the accumulated list.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m6_1_1_types import (
    BaselineCellEntry,
    BaselineSentinel,
    DriftNotReproducedConfirmedOutcome,
    M6_1_1Cell,
    M6_1_1Cohort,
    M6_1_1Run,
    MultiPointTimings,
    Phase1RunRecord,
    Phase2aVerifiedOutcome,
    Phase2bDocumentedOutcome,
    Phase2Path,
    SplitRequiredOutcome,
)

# --- Sentinel-object builders (round-2 Q1 / Q2) -----------------------------


def build_sentinel(phase_2_path: Phase2Path, *, is_embed: bool = False) -> BaselineSentinel:
    """Build a baseline sentinel under any ``phase_2_path``.

    Under non-Phase-2(a) outcomes, ``cells=None``. Under
    ``phase_2a_verified`` the caller populates ``cells`` separately via
    the Phase 2 orchestrator (T031).
    """
    del is_embed  # currently both sentinels dispatch the same way
    if phase_2_path == "phase_2a_verified":
        return BaselineSentinel(
            phase_2_path=phase_2_path,
            baseline_source="m6_1_1",
            pointer="docs/benchmarks/m6_1_1-engine-cost-instrumentation.json",
            cells=None,  # populated by Phase 2(a) orchestrator (T031)
        )
    if phase_2_path == "phase_2b_documented":
        return BaselineSentinel(
            phase_2_path=phase_2_path,
            baseline_source="m6_1",
            pointer="docs/benchmarks/m6_1-real-prompt-embeds.json",
            cells=None,
        )
    if phase_2_path == "drift_not_reproduced_confirmed":
        return BaselineSentinel(
            phase_2_path=phase_2_path,
            baseline_source="m6_1",
            pointer="docs/benchmarks/m6_1-real-prompt-embeds.json",
            cells=None,
        )
    # phase_2_pending and split_required
    return BaselineSentinel(
        phase_2_path=phase_2_path,
        baseline_source="not_applicable",
        pointer=None,
        cells=None,
    )


# --- Phase 2(a) baseline builders (FR-015a / FR-015c, T031) -----------------


def _baseline_cell_entry_chat_stream(
    cell: M6_1_1Cell,
    cohort: M6_1_1Cohort,
    *,
    engine_ttft_ms_mean: float,
    engine_ttft_ms_ci_half_width: float,
    engine_tpot_ms_mean: float,
    engine_tpot_ms_ci_half_width: float,
    n_successes: int,
) -> BaselineCellEntry:
    """Build a chat_stream cell entry. ``engine_forward_*`` fields are None
    (chat_stream cells don't carry a forward-pass time)."""
    return BaselineCellEntry(
        cell=cell,
        cohort=cohort,
        engine_ttft_ms_mean=engine_ttft_ms_mean,
        engine_ttft_ms_ci_half_width=engine_ttft_ms_ci_half_width,
        engine_tpot_ms_mean=engine_tpot_ms_mean,
        engine_tpot_ms_ci_half_width=engine_tpot_ms_ci_half_width,
        engine_forward_ms_mean=None,
        engine_forward_ms_ci_half_width=None,
        n_successes=n_successes,
        regression_warning=None,
    )


def _baseline_cell_entry_embed(
    cell: M6_1_1Cell,
    cohort: M6_1_1Cohort,
    *,
    engine_forward_ms_mean: float,
    engine_forward_ms_ci_half_width: float,
    n_successes: int,
    regression_warning: bool | None,
) -> BaselineCellEntry:
    """Build an embed cell entry. ``engine_ttft_*`` and ``engine_tpot_*``
    fields are None (embed RPCs don't have a streaming time-to-first-token)."""
    return BaselineCellEntry(
        cell=cell,
        cohort=cohort,
        engine_ttft_ms_mean=None,
        engine_ttft_ms_ci_half_width=None,
        engine_tpot_ms_mean=None,
        engine_tpot_ms_ci_half_width=None,
        engine_forward_ms_mean=engine_forward_ms_mean,
        engine_forward_ms_ci_half_width=engine_forward_ms_ci_half_width,
        n_successes=n_successes,
        regression_warning=regression_warning,
    )


def build_chat_stream_baseline(
    cells: list[BaselineCellEntry],
) -> BaselineSentinel:
    """Build a populated ``chat_stream_baseline_post_symmetrisation`` sentinel
    under Phase 2(a) (round-2 Q1). The 9 entries (3 chat_stream cells × 3
    cohorts) are supplied by the Phase 2 orchestrator from the verification
    sweep's aggregates.
    """
    return BaselineSentinel(
        phase_2_path="phase_2a_verified",
        baseline_source="m6_1_1",
        pointer="docs/benchmarks/m6_1_1-engine-cost-instrumentation.json",
        cells=cells,
    )


def build_embed_baseline(
    cells: list[BaselineCellEntry],
) -> BaselineSentinel:
    """Build a populated ``embed_baseline_post_symmetrisation`` sentinel
    under Phase 2(a) (round-2 Q2, FR-015c). The 9 entries (3 embed cells × 3
    cohorts) carry ``regression_warning`` flags from FR-015b.
    """
    return BaselineSentinel(
        phase_2_path="phase_2a_verified",
        baseline_source="m6_1_1",
        pointer="docs/benchmarks/m6_1_1-engine-cost-instrumentation.json",
        cells=cells,
    )


# --- Markdown writer (FR-020 6-section structure) ---------------------------


def render_markdown(run: M6_1_1Run) -> str:
    """Render the 6-section markdown report per FR-020.

    Section order is invariant across all ``phase_2_path`` values; section
    content adapts to the run's state.
    """
    sections: list[str] = []
    sections.append(_render_executive_summary(run))
    sections.append(_render_methodology(run))
    sections.append(_render_multi_point_timing_tables(run))
    sections.append(_render_root_cause_attribution(run))
    sections.append(_render_phase_2_outcome(run))
    sections.append(_render_methodology_supersedence(run))
    return "\n\n".join(sections).rstrip() + "\n"


def _render_executive_summary(run: M6_1_1Run) -> str:
    path = run.run_meta.phase_2_path
    icon = {
        "phase_2a_verified": "✅",
        "phase_2b_documented": "📝",
        "phase_2_pending": "⏳",
        "drift_not_reproduced_confirmed": "⚠",
        "split_required": "🪓",
    }.get(path, "")
    cs_classes = (
        ", ".join(
            f"{k.removeprefix('chat_stream_')}={v}"
            for k, v in sorted(run.phase_1_classifications.items())
            if k.startswith("chat_stream_")
        )
        or "(no chat_stream classifications)"
    )
    return (
        "# M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation\n\n"
        f"**Run**: `{run.run_id}` | **Phase 2 path**: `{path}` {icon}\n"
        f"**Phase 1 classifications** (chat_stream cells): {cs_classes}\n"
        f"**Phase 1 runs recorded**: {len(run.phase_1_runs)}"
    )


def _render_methodology(run: M6_1_1Run) -> str:
    meta = run.run_meta
    return (
        "## Methodology\n\n"
        f"- **Model**: `{meta.model_identifier}`, hidden_size={meta.hidden_size}\n"
        f"- **Engine**: vllm=={meta.engine_version} "
        f"(M6.1 baseline recorded: {meta.m6_1_baseline_engine_version})\n"
        "- **Dispatch mode**: concurrent (peak in-flight = c, per M6.0a)\n"
        f"- **Hardware**: {meta.gpu_type} on Modal `{meta.modal_region}`\n"
        f"- **Torch pin**: {meta.torch_version} (FR-003)\n"
        f"- **Phase 1 sample size**: n={meta.phase_1_n} per cohort per cell\n"
        f"- **Base seed**: {meta.M6_1_1_BASE_SEED} (matches M6 / M6.1)\n"
        f"- **Seq len pinned at sweep start**: {meta.seq_len}\n"
        f"- **Perturbation budget**: 500 µs per RPC (FR-012 hard gate, exit code 4)"
    )


def _render_multi_point_timing_tables(run: M6_1_1Run) -> str:
    """One sub-section per phase_1_runs[] entry (round-3 Q1)."""
    out = ["## Multi-Point Timing Table"]
    if not run.phase_1_runs:
        out.append("\n(no Phase 1 runs recorded)")
        return "\n".join(out)
    for idx, prun in enumerate(run.phase_1_runs):
        out.append(f"\n### Run {idx + 1} — `{prun.run_id}` (n={prun.n_per_cohort})")
        out.append("")
        out.append(
            "| cell | cohort | engine_ttft_ms (±CI) | seg_ab_ms (±CI) | "
            "seg_bc_ms (±CI) | seg_cd_ms (±CI) | perturbation µs | n |"
        )
        out.append(
            "|------|--------|----------------------|------------------|------------------|------------------|------------------|---|"
        )
        for mpt in prun.multi_point_timings:
            out.append(_format_timing_row(mpt))
    return "\n".join(out)


def _format_timing_row(mpt: MultiPointTimings) -> str:
    seg = mpt.per_segment
    cell_label = f"{mpt.cell.path} c={mpt.cell.concurrency}"
    return (
        f"| {cell_label} | {mpt.cohort} | "
        f"{mpt.engine_ttft_ms_mean:.2f} ± {mpt.engine_ttft_ms_ci_half_width:.2f} | "
        f"{seg.seg_ab_ms_mean:.2f} ± {seg.seg_ab_ms_ci_half_width:.2f} | "
        f"{seg.seg_bc_ms_mean:.2f} ± {seg.seg_bc_ms_ci_half_width:.2f} | "
        f"{seg.seg_cd_ms_mean:.2f} ± {seg.seg_cd_ms_ci_half_width:.2f} | "
        f"{mpt.perturbation_total_us_mean:.2f} | "
        f"{seg.n_samples} |"
    )


def _render_root_cause_attribution(run: M6_1_1Run) -> str:
    """One sub-section per chat_stream cell, with the FR-010 formula applied."""
    out = ["## Root-Cause Attribution"]
    cs_cells = sorted(
        (k, v) for k, v in run.phase_1_classifications.items() if k.startswith("chat_stream_")
    )
    if not cs_cells:
        out.append("\n(no chat_stream classifications)")
        return "\n".join(out)
    for cell_key, classification in cs_cells:
        out.append(f"\n### {cell_key}: `{classification}`")
        out.append("")
        out.append(_classification_narrative(classification))
    return "\n".join(out)


def _classification_narrative(classification: str) -> str:
    text = {
        "instrumentation_artifact": (
            "The pre-engine bracket (`seg_ab`) carries ≥80% of the "
            "`engine_ttft_ms` per-cohort spread. The per-cohort difference is "
            "measurement-window asymmetry between transport paths, not engine cost. "
            "Phase 2(a) symmetrisation will eliminate the asymmetry."
        ),
        "channel_dependent_batching": (
            "The engine-internal first-token segment (`seg_bc`) carries ≥80% of "
            "the spread. The engine itself sees different first-token latencies "
            "per cohort — this is a real engine behaviour under continuous "
            "batching. Phase 2(b) documents the interpretation rule."
        ),
        "drift_not_reproduced": (
            "Per-cohort `engine_ttft_ms` spread/mean < 5%. The M6.1 drift "
            "observation is not reproduced under M6.1.1 instrumentation. A "
            "second confirming run is required before closing."
        ),
        "inconclusive": (
            "Neither `seg_ab` nor `seg_bc` carries ≥80% of the `engine_ttft_ms` "
            "spread; the distribution is mixed. A second Phase 1 run is "
            "required to disambiguate."
        ),
    }
    return text.get(classification, "(unrecognised classification)")


def _render_phase_2_outcome(run: M6_1_1Run) -> str:
    out = ["## Phase 2 Outcome"]
    outcome = run.phase_2_outcome
    path = run.run_meta.phase_2_path
    if outcome is None and path == "phase_2_pending":
        out.append(
            "\nPhase 2 not yet run. Under `instrumentation_artifact` apply "
            "symmetrisation and run `--m6_1_1`; under `channel_dependent_batching` "
            "update `contracts/instrumentation.md` and run `--m6_1_1`."
        )
        return "\n".join(out)
    if isinstance(outcome, Phase2aVerifiedOutcome):
        cleared = sum(1 for v in outcome.drift_cleared_per_cell.values() if v)
        total = len(outcome.drift_cleared_per_cell)
        out.append(
            f"\n**Phase 2(a) verified**: drift cleared on {cleared}/{total} chat_stream cells. "
            f"Verification sweep n={outcome.n_per_cohort} per cohort per cell."
        )
        if outcome.chat_stream_control_drift_warning:
            note = outcome.chat_stream_control_drift_note
            out.append(f"\n`chat_stream_control_drift_warning=True` ({note}).")
    elif isinstance(outcome, Phase2bDocumentedOutcome):
        out.append(
            f"\n**Phase 2(b) documented**: `{outcome.contracts_heading_path}` "
            f"carries the matched heading `{outcome.contracts_heading_text}`."
        )
    elif isinstance(outcome, DriftNotReproducedConfirmedOutcome):
        out.append(f"\n**drift_not_reproduced_confirmed**: {outcome.note}")
        run_a, run_b = outcome.confirming_run_ids
        out.append(f"Confirming run IDs: `{run_a}`, `{run_b}`.")
    elif isinstance(outcome, SplitRequiredOutcome):
        out.append("\n**split_required**: heterogeneous Phase 2 disallowed (round-2 Q4).")
        out.append(f"Proposed shape: {outcome.proposed_split_shape}")
        out.append(f"Operator note: {outcome.operator_note}")
    return "\n".join(out)


def _render_methodology_supersedence(run: M6_1_1Run) -> str:
    out = ["## Methodology Supersedence"]
    if run.methodology_supersedence:
        pointer = run.methodology_supersedence
        out.append("\nForward pointer written into M6.1's published markdown:")
        out.append(f"\n> {pointer}")
    else:
        out.append("\n(no supersedence annotation written for this run state)")
    return "\n".join(out)


# --- JSON writer (FR-021 strict-superset; round-2 Q1 sentinel dispatch) ----


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert non-JSON-serialisable values to JSON-safe shapes.

    JSON requires string / int / float / bool / None keys; ``dict[tuple, ...]``
    raises ``TypeError`` in ``json.dumps`` even though tuples are valid Python
    dict keys. M6.1.1 has one such field today —
    :class:`PerturbationAudit.per_cohort_per_cell` keyed by
    ``(cohort, cell_str)`` — but this helper handles any future additions.

    Tuple keys collapse to ``"part0|part1|..."`` strings. Tuple *values* (e.g.
    :class:`DriftNotReproducedConfirmedOutcome.confirming_run_ids`) are left
    alone — ``json.dumps`` already converts them to lists.
    """
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            key = "|".join(str(part) for part in k) if isinstance(k, tuple) else k
            out[key] = _sanitize_for_json(v)
        return out
    if isinstance(obj, list):
        return [_sanitize_for_json(item) for item in obj]
    return obj


def render_json(run: M6_1_1Run) -> dict[str, Any]:
    """Render the M6.1.1 JSON companion as a plain dict ready for json.dumps.

    Strict-superset compatibility (FR-022): every M6 / M6.1-aware reader's
    expected top-level keys are present; new M6.1.1 keys are additive and
    namespaced so they don't collide.
    """
    payload = {
        "schema_version": run.schema_version,
        # M6.0a (FR-007 strict-superset): every manifest emitted by the
        # corrected harness carries ``dispatch_mode: "concurrent"``. Absent
        # ``dispatch_mode`` retroactively means ``"sequential"`` so
        # pre-M6.0a manifests (e.g., the 2026-05-16 audit baseline) parse
        # unchanged. ``schema_version`` is NOT bumped — the addition is
        # purely additive at the top level.
        "dispatch_mode": "concurrent",
        "run_id": run.run_id,
        "run_started_at": run.run_started_at,
        "run_completed_at": run.run_completed_at,
        "run_meta": dataclasses.asdict(run.run_meta),
        "phase_1_classifications": dict(run.phase_1_classifications),
        "phase_1_runs": [_phase_1_run_to_dict(r) for r in run.phase_1_runs],
        "multi_point_timings": [dataclasses.asdict(mpt) for mpt in run.multi_point_timings],
        "phase_2_outcome": (
            dataclasses.asdict(run.phase_2_outcome) if run.phase_2_outcome is not None else None
        ),
        "phase_2_choice": (
            dataclasses.asdict(run.phase_2_choice) if run.phase_2_choice is not None else None
        ),
        "chat_stream_baseline_post_symmetrisation": dataclasses.asdict(
            run.chat_stream_baseline_post_symmetrisation
        ),
        "embed_baseline_post_symmetrisation": dataclasses.asdict(
            run.embed_baseline_post_symmetrisation
        ),
        "embed_regression_check": (
            dataclasses.asdict(run.embed_regression_check)
            if run.embed_regression_check is not None
            else None
        ),
        "m6_1_baseline_pointer": run.m6_1_baseline_pointer,
        "methodology_supersedence": run.methodology_supersedence,
    }
    sanitized = _sanitize_for_json(payload)
    assert isinstance(sanitized, dict)  # narrows for mypy — top-level is always dict
    return sanitized


def _phase_1_run_to_dict(prun: Phase1RunRecord) -> dict[str, Any]:
    return dataclasses.asdict(prun)


# --- Public entry point -----------------------------------------------------


def write_sidecar_events(
    sidecar_path: Path,
    *,
    run_id: str,
    events: list[dict[str, Any]],
) -> None:
    """Append a Phase 1 / Phase 2 run's per-RPC events to the sidecar JSONL.

    Each invocation prepends a separator line of the form
    ``{"_run_separator": true, "run_id": "..."}`` so consumers can split
    by run, then appends each event as one JSONL line. The sidecar is
    append-only across all ``--m6_1_1-diagnose`` and ``--m6_1_1`` runs
    (round-3 Q1: phase_1_runs[] preservation extends to per-RPC events).
    """
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    separator = {"_run_separator": True, "run_id": run_id}
    with sidecar_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(separator, ensure_ascii=False) + "\n")
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def write_m6_1_1_report(run: M6_1_1Run, md_path: Path, json_path: Path) -> None:
    """Write the markdown report + JSON companion atomically.

    Both files are overwritten on each invocation (round-3 Q1: the JSON's
    ``phase_1_runs[]`` is the accumulator; the rest reflect the most recent
    run).
    """
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(run), encoding="utf-8")
    json_path.write_text(
        json.dumps(render_json(run), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "build_chat_stream_baseline",
    "build_embed_baseline",
    "build_sentinel",
    "render_json",
    "render_markdown",
    "write_m6_1_1_report",
    "write_sidecar_events",
]


# --- Optional: M6.1 strict-superset key check (FR-022) ----------------------


def assert_strict_superset(m6_1_1_json: dict[str, Any], m6_1_keys: list[str]) -> None:
    """Assert every M6.1 top-level key is reachable in M6.1.1's published JSON.

    Used by T035's strict-superset validation test. The check is one-way: M6.1
    keys missing from M6.1.1 = violation; M6.1.1 having extra keys is the
    whole point.

    The pointer fields on the sentinel objects refer to M6.1's data when
    ``baseline_source == "m6_1"``, satisfying the "reachable" contract.
    """
    m6_1_1_keys = set(m6_1_1_json.keys())
    missing = [
        k for k in m6_1_keys if k not in m6_1_1_keys and not _has_sentinel_alias(k, m6_1_1_json)
    ]
    if missing:
        raise AssertionError(
            f"M6.1.1 JSON missing M6.1 keys (strict-superset violation): {missing}"
        )


_M6_1_KEY_ALIASES: dict[str, str] = {
    # M6.1's `engine_cost_baseline` is reachable through M6.1.1's
    # baseline sentinels — when ``baseline_source == "m6_1"`` the pointer
    # field carries the M6.1 path.
    "engine_cost_baseline": "chat_stream_baseline_post_symmetrisation",
    "supersedes_m6_under_enable_prompt_embeds": "methodology_supersedence",
}


def _has_sentinel_alias(m6_1_key: str, m6_1_1_json: dict[str, Any]) -> bool:
    alias = _M6_1_KEY_ALIASES.get(m6_1_key)
    if alias is None:
        return False
    return alias in m6_1_1_json
