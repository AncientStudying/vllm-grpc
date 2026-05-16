"""M6.1 chat_stream control-drift check (FR-029, R-6).

Runs ONCE per full sweep, AFTER all 6 cells classified. For each chat_stream
cell × cohort, compares M6.1's 95% CI on the classifier metric (TTFT) against
M6's published 95% CI; sets ``chat_stream_control_drift_warning=True`` for
that cell if at least one cohort's CIs do not overlap.

NOT run during smoke — smoke's n=10 CIs are too wide for meaningful overlap
detection (FR-012 mandate).
"""

from __future__ import annotations

from vllm_grpc_bench.m6_1_types import (
    M6_1_COHORTS,
    M6_1Cell,
    M6_1CellRecord,
    M6_1CohortKind,
)


def _cis_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return not (a[1] < b[0] or b[1] < a[0])


def _find_m6_cell(
    m6_baseline_rows: list[dict[str, object]], cell: M6_1Cell
) -> dict[str, object] | None:
    for row in m6_baseline_rows:
        c = row.get("cell")
        if not isinstance(c, dict):
            continue
        if (
            c.get("path") == cell.path
            and c.get("hidden_size") == cell.hidden_size
            and c.get("concurrency") == cell.concurrency
        ):
            return row
    return None


def check_chat_stream_control_drift(
    m6_1_cells: list[M6_1CellRecord],
    m6_baseline_rows: list[dict[str, object]],
) -> dict[tuple[str, int], bool]:
    """Return per-(cell.path, cell.concurrency) → drift flag.

    Embed cells trivially get ``False``. Chat_stream cells get ``True`` if
    at least one cohort's M6.1 CI does not overlap M6's published CI for the
    same (cell, cohort).
    """
    flags: dict[tuple[str, int], bool] = {}
    for cell_record in m6_1_cells:
        cell = cell_record.cell
        key = (cell.path, cell.concurrency)
        if cell.path != "chat_stream":
            flags[key] = False
            continue
        m6_row = _find_m6_cell(m6_baseline_rows, cell)
        if m6_row is None:
            # Missing baseline row → don't flag (loader would have raised).
            flags[key] = False
            continue
        pcm_m6 = m6_row.get("per_cohort_classifier_metric", {})
        if not isinstance(pcm_m6, dict):
            flags[key] = False
            continue
        any_non_overlap = False
        for cohort in M6_1_COHORTS:
            m6_1_agg = cell_record.per_cohort.get(cohort)
            if m6_1_agg is None:
                continue
            half = m6_1_agg.classifier_metric_ci_half_width_ms
            mean = m6_1_agg.classifier_metric_mean_ms
            m6_1_ci = (mean - half, mean + half)
            m6_entry = pcm_m6.get(cohort, {})
            if not isinstance(m6_entry, dict):
                continue
            m6_ci_lower = m6_entry.get("ci_lower_ms")
            m6_ci_upper = m6_entry.get("ci_upper_ms")
            if not (
                isinstance(m6_ci_lower, (int, float)) and isinstance(m6_ci_upper, (int, float))
            ):
                continue
            if not _cis_overlap(m6_1_ci, (float(m6_ci_lower), float(m6_ci_upper))):
                any_non_overlap = True
                break
        flags[key] = any_non_overlap
    return flags


def drift_warning_for_cell(cell: M6_1Cell, flags: dict[tuple[str, int], bool]) -> bool:
    """Lookup helper for the reporter."""
    return flags.get((cell.path, cell.concurrency), False)


__all__ = [
    "check_chat_stream_control_drift",
    "drift_warning_for_cell",
]


# Type-only re-export so callers don't need to import M6_1CohortKind separately.
_ = M6_1CohortKind
