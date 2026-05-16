"""M6.1 verdict classifier + M6 baseline loader.

Per spec FR-008, FR-009, FR-010, FR-013, FR-017, FR-022, FR-029 and research
R-4 / R-8: the classifier loads the M6 published baseline JSON, extracts
per-cell winner deltas, and applies the 5-category discrimination rule
deterministically against M6.1 measurements.

The classifier proper is implemented in :func:`classify_cell` (T022). This
module also owns the pre-RPC baseline loader :func:`load_and_validate_m6_baseline`
(T011) which is called at sweep start to fail-fast on missing or malformed
baseline files (FR-009 / FR-013 hard precondition).
"""

from __future__ import annotations

import json
from pathlib import Path

from vllm_grpc_bench.m6_1_types import (
    M6_1_BURIED_BY_ENGINE_FACTOR,
    M6_1_CELL_COMPLETE_FLOOR,
    M6_1_COHORTS,
    M6_1Cell,
    M6_1CellRecord,
    M6_1CohortKind,
    M6_1PerCohortAggregate,
    VerdictClassification,
    cell_key,
    make_cells,
)

# Cells that are required to be present in the M6 baseline before M6.1 can run.
_REQUIRED_CELLS: tuple[tuple[str, int, int], ...] = tuple(
    (c.path, c.hidden_size, c.concurrency) for c in make_cells()
)

# M6 verdicts that map to "no usable winner delta" per FR-010 sub-clause.
_NO_USABLE_BASELINE_M6_VERDICTS: frozenset[str] = frozenset(
    {"no_winner_at_n100", "cell_incomplete", "verdict_buried_by_engine"}
)


class M6BaselineMissingCellError(RuntimeError):
    """Raised when the M6 baseline JSON does not contain a row for a required cell."""

    def __init__(self, cell: tuple[str, int, int]) -> None:
        self.cell = cell
        super().__init__(
            f"M6 baseline JSON is missing the row for cell "
            f"path={cell[0]!r}, hidden_size={cell[1]}, concurrency={cell[2]}. "
            "M6.1 sweep cannot proceed (FR-009)."
        )


def _row_cell_tuple(row: dict[str, object]) -> tuple[str, int, int]:
    cell = row.get("cell")
    if not isinstance(cell, dict):
        raise ValueError(f"M6 baseline row missing 'cell' object: {row!r}")
    path = cell.get("path")
    hidden_size = cell.get("hidden_size")
    concurrency = cell.get("concurrency")
    if not (
        isinstance(path, str) and isinstance(hidden_size, int) and isinstance(concurrency, int)
    ):
        raise ValueError(f"M6 baseline row has malformed 'cell': {cell!r}")
    return (path, hidden_size, concurrency)


def _extract_m6_winner_delta(
    row: dict[str, object],
) -> tuple[float | None, str | None]:
    """Return ``(|delta_median_ms|, direction)`` extracted from an M6 cell row.

    Returns ``(None, None)`` if M6's classification was in the "no usable
    baseline" set per FR-010 sub-clause (``no_winner_at_n100``,
    ``cell_incomplete``, OR ``verdict_buried_by_engine``).
    """
    classification = row.get("classification")
    if classification in _NO_USABLE_BASELINE_M6_VERDICTS:
        return None, None
    pcm = row.get("per_cohort_classifier_metric")
    if not isinstance(pcm, dict):
        return None, None
    rest = pcm.get("rest_https_edge", {})
    grpc = pcm.get("tuned_grpc_multiplexed", {})
    if not (isinstance(rest, dict) and isinstance(grpc, dict)):
        return None, None
    rest_mean = rest.get("mean_ms")
    grpc_mean = grpc.get("mean_ms")
    if not (isinstance(rest_mean, (int, float)) and isinstance(grpc_mean, (int, float))):
        return None, None
    delta = float(rest_mean) - float(grpc_mean)
    direction: str = "grpc_wins" if delta > 0 else "rest_wins"
    return abs(delta), direction


def load_and_validate_m6_baseline(
    path: str | Path,
) -> tuple[dict[str, float | None], dict[str, str | None], str, dict[str, object]]:
    """Load and validate the M6 published baseline JSON.

    Returns a 4-tuple of:
    1. ``m6_winner_deltas``: keyed by ``cell_key(M6_1Cell)``; values are
       ``|delta_median_ms|`` for cells with a usable M6 winner delta, else
       ``None`` per FR-010 sub-clause.
    2. ``m6_winner_directions``: same key shape; values are
       ``"rest_wins"`` / ``"grpc_wins"`` for cells with a usable delta, else
       ``None``.
    3. ``m6_baseline_engine_version``: M6's recorded engine_version (or
       ``"unknown"`` if absent — FR-030 non-blocking on mismatch).
    4. ``m6_meta``: the full ``m6_meta`` block from the baseline JSON, for
       passthrough back-reference per FR-021 strict-superset compatibility.

    Raises :class:`M6BaselineMissingCellError` if any of the 6 required M6.1
    cells is missing from ``supersedes_m5_2_under_real_engine[]``.
    """
    file_path = Path(path)
    payload = json.loads(file_path.read_text())

    rows = payload.get("supersedes_m5_2_under_real_engine")
    if not isinstance(rows, list):
        raise ValueError(
            f"M6 baseline at {file_path} is missing 'supersedes_m5_2_under_real_engine[]' "
            "(FR-008 / FR-009)"
        )

    by_cell: dict[tuple[str, int, int], dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        by_cell[_row_cell_tuple(row)] = row

    m6_winner_deltas: dict[str, float | None] = {}
    m6_winner_directions: dict[str, str | None] = {}
    for cell_tuple in _REQUIRED_CELLS:
        if cell_tuple not in by_cell:
            raise M6BaselineMissingCellError(cell_tuple)
        row = by_cell[cell_tuple]
        cell_obj = M6_1Cell(
            path=cell_tuple[0],  # type: ignore[arg-type]
            hidden_size=cell_tuple[1],  # type: ignore[arg-type]
            concurrency=cell_tuple[2],  # type: ignore[arg-type]
        )
        key = cell_key(cell_obj)
        delta, direction = _extract_m6_winner_delta(row)
        m6_winner_deltas[key] = delta
        m6_winner_directions[key] = direction

    m6_meta_raw = payload.get("m6_meta", {})
    m6_meta = m6_meta_raw if isinstance(m6_meta_raw, dict) else {}
    ev = m6_meta.get("engine_version")
    m6_baseline_engine_version = ev if isinstance(ev, str) and ev else "unknown"

    return m6_winner_deltas, m6_winner_directions, m6_baseline_engine_version, m6_meta


# --- Verdict classifier (T022) ----------------------------------------------


def _cohort_classifier_mean(
    agg: M6_1PerCohortAggregate,
) -> float:
    return agg.classifier_metric_mean_ms


def _cohort_classifier_ci(agg: M6_1PerCohortAggregate) -> tuple[float, float]:
    half = agg.classifier_metric_ci_half_width_ms
    mean = agg.classifier_metric_mean_ms
    return (mean - half, mean + half)


def _cis_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Closed-interval overlap test on two 95% CIs."""
    return not (a[1] < b[0] or b[1] < a[0])


def cohort_pair_for(cell: M6_1Cell) -> tuple[M6_1CohortKind, M6_1CohortKind]:
    """Return the canonical comparison cohort pair for ``cell``.

    M6.1 uses the same pair M6 used: ``(rest_https_edge, tuned_grpc_multiplexed)``.
    """
    del cell
    return ("rest_https_edge", "tuned_grpc_multiplexed")


def compute_engine_cost_mean_ms(
    per_cohort: dict[M6_1CohortKind, M6_1PerCohortAggregate],
    path: str,
) -> tuple[float, dict[M6_1CohortKind, float]]:
    """Compute the per-cell engine_cost_mean and per-cohort means.

    FR-022 — simple unweighted average of the three per-cohort means.
    Path-discriminated: ``engine_forward_ms`` for embed, ``engine_ttft_ms``
    for chat_stream.
    """
    per_cohort_means: dict[M6_1CohortKind, float] = {}
    for cohort, agg in per_cohort.items():
        if path == "embed":
            val = agg.engine_cost_mean.engine_forward_mean_ms
        else:
            val = agg.engine_cost_mean.engine_ttft_mean_ms
        per_cohort_means[cohort] = float(val) if val is not None else 0.0
    cell_mean = sum(per_cohort_means.values()) / max(1, len(per_cohort_means))
    return cell_mean, per_cohort_means


def compute_engine_cost_drift_warning(
    per_cohort_means: dict[M6_1CohortKind, float],
) -> bool:
    """Return True if any pair of per-cohort means disagree by >10% (FR-022)."""
    values = list(per_cohort_means.values())
    for i, a in enumerate(values):
        for b in values[i + 1 :]:
            base = min(abs(a), abs(b))
            if base == 0:
                if a != b:
                    return True
                continue
            if abs(a - b) / base > 0.10:
                return True
    return False


def classify_cell(
    cell_record_dict: dict[str, object] | None,
    cell: M6_1Cell,
    per_cohort: dict[M6_1CohortKind, M6_1PerCohortAggregate],
    m6_winner_delta_ms: float | None,
    m6_winner_direction: str | None,
) -> tuple[VerdictClassification, str, float, bool, dict[M6_1CohortKind, float] | None]:
    """Apply FR-010's deterministic discrimination rule.

    Returns ``(classification, reason, engine_cost_mean_ms, engine_cost_drift_warning,
    per_cohort_engine_cost_mean_ms_or_None)``.

    Algorithm (R-8 step ordering preserved):

    1. If any cohort ``n_successes < 80`` → ``cell_incomplete``.
    2. Compute per-cell ``engine_cost_mean`` (FR-022 simple unweighted average).
    3. Compute ``engine_cost_drift_warning`` (any cohort pair > 10% — FR-022).
    4. If ``m6_winner_delta_ms is None`` → ``no_winner_at_n100`` regardless
       of M6.1 CI overlap (FR-010 sub-clause).
    5. Test M6.1 cohort-pair CI overlap:
       a. Non-overlap + direction match → ``verdict_survives``.
       b. Non-overlap + direction flip → ``verdict_changed``.
       c. Overlap + engine_cost_mean ≥ 5× M6 winner delta → ``verdict_buried_by_engine``.
       d. Overlap + engine_cost_mean < 5× M6 winner delta → ``no_winner_at_n100``.
    """
    del cell_record_dict  # reserved for future use; signature documented by T022

    # Step 1: cell_incomplete precondition (FR-017).
    min_n = min(agg.n_successes for agg in per_cohort.values())
    engine_cost_mean_ms, per_cohort_engine_cost = compute_engine_cost_mean_ms(per_cohort, cell.path)
    drift_warning = compute_engine_cost_drift_warning(per_cohort_engine_cost)
    drift_surface = per_cohort_engine_cost if drift_warning else None
    if min_n < M6_1_CELL_COMPLETE_FLOOR:
        return (
            "cell_incomplete",
            f"At least one cohort had n_successes={min_n} < {M6_1_CELL_COMPLETE_FLOOR} (FR-017).",
            engine_cost_mean_ms,
            drift_warning,
            drift_surface,
        )

    # Step 4: FR-010 sub-clause (no usable M6 baseline).
    if m6_winner_delta_ms is None:
        return (
            "no_winner_at_n100",
            "M6 baseline had no usable winner delta for this cell "
            "(M6 verdict was no_winner_at_n100 / cell_incomplete / verdict_buried_by_engine) "
            "— FR-010 sub-clause.",
            engine_cost_mean_ms,
            drift_warning,
            drift_surface,
        )

    # Step 5: M6.1 cohort-pair CI overlap.
    pair = cohort_pair_for(cell)
    rest_agg = per_cohort[pair[0]]
    grpc_agg = per_cohort[pair[1]]
    rest_ci = _cohort_classifier_ci(rest_agg)
    grpc_ci = _cohort_classifier_ci(grpc_agg)
    rest_mean = _cohort_classifier_mean(rest_agg)
    grpc_mean = _cohort_classifier_mean(grpc_agg)
    m6_1_delta = rest_mean - grpc_mean
    m6_1_direction = "grpc_wins" if m6_1_delta > 0 else "rest_wins"

    if not _cis_overlap(rest_ci, grpc_ci):
        if m6_1_direction == m6_winner_direction:
            return (
                "verdict_survives",
                f"M6.1 CIs non-overlapping in same direction as M6 "
                f"winner ({m6_winner_direction}); |Δ|={abs(m6_1_delta):.2f}ms.",
                engine_cost_mean_ms,
                drift_warning,
                drift_surface,
            )
        return (
            "verdict_changed",
            f"M6.1 CIs non-overlapping in OPPOSITE direction "
            f"({m6_1_direction}) from M6 winner ({m6_winner_direction}); "
            f"|Δ|={abs(m6_1_delta):.2f}ms.",
            engine_cost_mean_ms,
            drift_warning,
            drift_surface,
        )

    # CIs overlap.
    if engine_cost_mean_ms >= M6_1_BURIED_BY_ENGINE_FACTOR * m6_winner_delta_ms:
        return (
            "verdict_buried_by_engine",
            f"M6.1 CIs overlap AND engine_cost_mean ({engine_cost_mean_ms:.2f}ms) "
            f"≥ 5× M6 winner delta ({m6_winner_delta_ms:.2f}ms).",
            engine_cost_mean_ms,
            drift_warning,
            drift_surface,
        )
    return (
        "no_winner_at_n100",
        f"M6.1 CIs overlap AND engine_cost_mean ({engine_cost_mean_ms:.2f}ms) "
        f"< 5× M6 winner delta ({m6_winner_delta_ms:.2f}ms).",
        engine_cost_mean_ms,
        drift_warning,
        drift_surface,
    )


# --- Engine path differential (T028) ----------------------------------------


def _ci_half_width_combined(a: float, b: float) -> float:
    """Standard CI of a difference of independent means."""
    return float((a * a + b * b) ** 0.5)


def compute_engine_path_differential(
    m6_1_cell_record: M6_1CellRecord,
    m6_baseline_cell: dict[str, object],
) -> dict[str, object]:
    """Compute the M6.1 − M6 differential row for a single cell (US2).

    Returns the kwargs for :class:`EnginePathDifferentialRow`.
    """
    per_cohort = m6_1_cell_record.per_cohort
    pcm_m6 = m6_baseline_cell.get("per_cohort_classifier_metric", {})
    if not isinstance(pcm_m6, dict):
        pcm_m6 = {}

    deltas: dict[M6_1CohortKind, float] = {}
    ci_widths: dict[M6_1CohortKind, float] = {}
    successes: dict[M6_1CohortKind, int] = {}

    for cohort in M6_1_COHORTS:
        agg = per_cohort[cohort]
        m6_entry = pcm_m6.get(cohort, {}) if isinstance(pcm_m6, dict) else {}
        if not isinstance(m6_entry, dict):
            m6_entry = {}
        m6_mean = float(m6_entry.get("mean_ms", 0.0)) if "mean_ms" in m6_entry else 0.0
        m6_ci_lower = m6_entry.get("ci_lower_ms")
        m6_ci_upper = m6_entry.get("ci_upper_ms")
        m6_half_width = 0.0
        if isinstance(m6_ci_lower, (int, float)) and isinstance(m6_ci_upper, (int, float)):
            m6_half_width = (float(m6_ci_upper) - float(m6_ci_lower)) / 2.0
        m6_1_half_width = agg.classifier_metric_ci_half_width_ms
        deltas[cohort] = agg.classifier_metric_mean_ms - m6_mean
        ci_widths[cohort] = _ci_half_width_combined(m6_1_half_width, m6_half_width)
        successes[cohort] = agg.n_successes

    # Engine cost delta — uses the cell-level simple unweighted mean.
    m6_engine_cost_mean = 0.0
    m6_engine_cost_cell_value = m6_baseline_cell.get("engine_cost_mean_ms")
    if isinstance(m6_engine_cost_cell_value, (int, float)):
        m6_engine_cost_mean = float(m6_engine_cost_cell_value)
    engine_cost_delta = m6_1_cell_record.engine_cost_mean_ms - m6_engine_cost_mean
    # M6 baseline JSON doesn't publish an engine_cost CI half-width directly;
    # use M6.1 CI half-width as the lone non-zero term in the combined formula.
    # (Documented in research R-8 / spec FR-020 — combined CI half-width =
    # sqrt(M6.1_half_width^2 + M6_half_width^2); M6's half-width is treated as
    # 0 when absent, which yields just the M6.1 half-width.)
    # We derive an engine_cost CI half-width proxy from the per-cohort
    # classifier-metric CIs (same n=100 sample size assumption).
    engine_cost_ci_half_width = sum(ci_widths.values()) / max(1, len(ci_widths))

    return {
        "cell": m6_1_cell_record.cell,
        "per_cohort_classifier_metric_delta_ms": deltas,
        "per_cohort_classifier_metric_delta_ci_half_width_ms": ci_widths,
        "engine_cost_mean_delta_ms": engine_cost_delta,
        "engine_cost_mean_delta_ci_half_width_ms": engine_cost_ci_half_width,
        "per_cohort_n_successes": successes,
    }


__all__ = [
    "M6BaselineMissingCellError",
    "classify_cell",
    "cohort_pair_for",
    "compute_engine_cost_drift_warning",
    "compute_engine_cost_mean_ms",
    "compute_engine_path_differential",
    "load_and_validate_m6_baseline",
]
