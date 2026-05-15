"""M6 verdict classifier + M5.2 baseline reader (T022 / T031-T033 / T046).

Phase 2 ships the baseline-precondition loader + the M5.2 cohort-name
mapping helper (R-6). Phase 3 (US1) adds the deterministic
``classify_cell`` implementation per Research R-7 — pure function of
(M6 numeric inputs, M5.2 winner-delta snapshot) → ``M6CellRecord``.

Both smoke and full sweep validate the M5.2 baseline file via
:func:`load_and_validate_m5_2_baseline` before any Modal compute is
consumed (FR-014 sub-clause "M5.2 baseline file precondition").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m6_engine_cost import compute_drift_warning
from vllm_grpc_bench.m6_types import (
    M6_BURIED_BY_ENGINE_FACTOR,
    M6_CELL_COMPLETE_FLOOR,
    M6_CELLS,
    M6_CHAT_MAX_TOKENS,
    ClassifierMetric,
    M5_2WinnerDirection,
    M6Cell,
    M6CellRecord,
    M6CohortKind,
    M6Concurrency,
    M6Path,
    M6PerCohortAggregate,
    VerdictClassification,
)

_DEFAULT_M5_2_BASELINE_PATH = Path("docs/benchmarks/m5_2-transport-vs-tuning.json")


class M5_2BaselineMissingCellError(RuntimeError):
    """Raised when the M5.2 baseline JSON lacks a verdict row for an M6 cell.

    Maps to ``--m6`` exit code 1 and ``--m6-smoke`` exit code 2 per
    ``contracts/cli.md``. The error message names the failing cell.
    """

    def __init__(self, cell: tuple[M6Path, int, M6Concurrency], grpc_cohort: str):
        self.cell = cell
        self.grpc_cohort = grpc_cohort
        path, hidden_size, c = cell
        super().__init__(
            f"M5.2 baseline missing cell entry: path={path} hidden_size={hidden_size} "
            f"concurrency={c} grpc_cohort={grpc_cohort} (expected at "
            f"protocol_comparison_verdicts[] in the M5.2 baseline JSON)"
        )


def map_m6_grpc_cohort_to_m5_2_lookup(concurrency: M6Concurrency) -> str:
    """R-6 cohort-name reconciliation for M5.2 winner-delta lookup.

    M6's ``tuned_grpc_multiplexed`` cohort maps to M5.2's published
    ``tuned_grpc`` at c=1 (M5.2's c=1 sweeps used ``tuned_grpc`` because
    the multiplexed/channels distinction has no meaning at single
    concurrency), and to ``tuned_grpc_multiplexed`` at c≥2. M6's own
    published cohort name remains ``tuned_grpc_multiplexed`` for all 6
    cells — the mapping only affects the M5.2-baseline lookup direction.
    """
    return "tuned_grpc" if concurrency == 1 else "tuned_grpc_multiplexed"


def _find_baseline_row(
    verdicts: list[dict[str, Any]],
    path: M6Path,
    hidden_size: int,
    concurrency: M6Concurrency,
    grpc_cohort: str,
) -> dict[str, Any] | None:
    for row in verdicts:
        if (
            row.get("path") == path
            and int(row.get("hidden_size", -1)) == hidden_size
            and int(row.get("concurrency", -1)) == concurrency
            and row.get("grpc_cohort") == grpc_cohort
            and row.get("rest_cohort") == "rest_https_edge"
        ):
            return row
    return None


def load_and_validate_m5_2_baseline(
    path: Path = _DEFAULT_M5_2_BASELINE_PATH,
) -> dict[str, Any]:
    """Load + validate the M5.2 baseline JSON.

    Returns the parsed JSON object. Raises
    :class:`M5_2BaselineMissingCellError` if any of the 6 M6 cells lacks a
    matching ``protocol_comparison_verdicts[]`` row under the R-6 cohort
    mapping. Raises ``FileNotFoundError`` if the file is missing and
    ``json.JSONDecodeError`` if the file is not valid JSON.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"M5.2 baseline JSON not found at {path}; M6 cannot proceed without it "
            f"(FR-014 sub-clause 'M5.2 baseline file precondition')."
        )
    data: dict[str, Any] = json.loads(path.read_text())
    verdicts = data.get("protocol_comparison_verdicts")
    if not isinstance(verdicts, list):
        raise M5_2BaselineMissingCellError(
            cell=("embed", 4096, 1),
            grpc_cohort="(missing protocol_comparison_verdicts[] in baseline JSON)",
        )
    for cell_tuple in M6_CELLS:
        path_, h, c = cell_tuple
        grpc_cohort_name = map_m6_grpc_cohort_to_m5_2_lookup(c)
        row = _find_baseline_row(verdicts, path_, h, c, grpc_cohort_name)
        if row is None:
            raise M5_2BaselineMissingCellError(cell=(path_, h, c), grpc_cohort=grpc_cohort_name)
        # Also check the default_grpc row at the same cell — the classifier
        # consumes either grpc cohort depending on cohort_pair choice; we
        # validate the tuned cohort here since that's the M5.2-canonical
        # winner-direction source per R-5/R-6.
    return data


def get_m5_2_winner_delta(
    baseline: dict[str, Any],
    cell: M6Cell,
) -> tuple[float | None, str | None]:
    """Look up the M5.2 winner delta + verdict for a given M6 cell.

    Returns ``(|delta_median_ms|, verdict_string)``. If M5.2's verdict for
    the cell is ``no_winner``, the magnitude is None per FR-014's
    "M5.2 verdict was no_winner" sub-case.
    """
    verdicts = baseline.get("protocol_comparison_verdicts")
    if not isinstance(verdicts, list):
        return None, None
    grpc_cohort_name = map_m6_grpc_cohort_to_m5_2_lookup(cell.concurrency)
    row = _find_baseline_row(
        verdicts, cell.path, cell.hidden_size, cell.concurrency, grpc_cohort_name
    )
    if row is None:
        return None, None
    verdict_str = row.get("verdict")
    delta_raw = row.get("delta_median_ms")
    if verdict_str == "no_winner" or delta_raw is None:
        return None, verdict_str if isinstance(verdict_str, str) else None
    try:
        return abs(float(delta_raw)), verdict_str if isinstance(verdict_str, str) else None
    except (TypeError, ValueError):
        return None, verdict_str if isinstance(verdict_str, str) else None


def snapshot_m5_2_winner_deltas(baseline: dict[str, Any]) -> dict[str, float | None]:
    """Snapshot the per-cell M5.2 winner deltas at sweep launch (T033 / FR-018).

    Returns a mapping keyed ``"{path}_c{c}_h{hidden_size}"`` with the
    absolute magnitude of the M5.2 ``delta_median_ms`` for each of the 6
    M6 cells, or ``None`` for cells where M5.2's verdict was ``no_winner``.
    Stored unchanged on ``M6RunMeta.m5_2_winner_deltas`` so re-runs against
    a different baseline file produce a different verdict table — i.e., the
    classifier is deterministic given the same snapshot (FR-014).
    """
    out: dict[str, float | None] = {}
    for path_, h, c in M6_CELLS:
        cell = M6Cell(path=path_, hidden_size=h, concurrency=c)
        delta, _verdict = get_m5_2_winner_delta(baseline, cell)
        out[f"{path_}_c{c}_h{h}"] = delta
    return out


def _classifier_metric_for_path(path: M6Path) -> ClassifierMetric:
    """FR-014 comparison metric per path: TTFT for chat_stream, wall_clock for embed."""
    return "ttft_ms" if path == "chat_stream" else "wall_clock_ms"


def _direction_from_m5_2_row(row: dict[str, Any]) -> M5_2WinnerDirection | None:
    """M5.2 winner direction inferred from the row's ``verdict`` field.

    The M5.2 published JSON uses verdict literals like ``tuned_grpc_recommend``
    (gRPC wins), ``default_grpc_recommend`` (gRPC wins), ``rest_https_edge_recommend``
    (REST wins), ``no_winner`` (None).
    """
    v = row.get("verdict", "")
    if not isinstance(v, str):
        return None
    if v == "rest_https_edge_recommend":
        return "rest_wins"
    if v in ("tuned_grpc_recommend", "tuned_grpc_multiplexed_recommend", "default_grpc_recommend"):
        return "grpc_wins"
    return None


def _ci_bounds(agg: M6PerCohortAggregate) -> tuple[float, float]:
    """Return (lower, upper) of the classifier-metric 95% CI for one cohort."""
    half = agg.classifier_metric_ci_half_width_ms
    mean = agg.classifier_metric_mean_ms
    return (mean - half, mean + half)


def _cis_overlap(a: M6PerCohortAggregate, b: M6PerCohortAggregate) -> bool:
    """True iff the two cohorts' classifier-metric 95% CIs overlap."""
    a_low, a_high = _ci_bounds(a)
    b_low, b_high = _ci_bounds(b)
    return not (a_high < b_low or b_high < a_low)


def _direction_from_m6_delta(rest_mean: float, grpc_mean: float) -> M5_2WinnerDirection:
    """Infer M6 direction from the (rest_mean - grpc_mean) sign.

    Convention: smaller mean wins (lower latency / TTFT is better).
    """
    return "rest_wins" if rest_mean < grpc_mean else "grpc_wins"


def classify_cell(
    cell: M6Cell,
    per_cohort: dict[M6CohortKind, M6PerCohortAggregate],
    baseline: dict[str, Any],
    *,
    classifier_grpc_cohort: M6CohortKind = "tuned_grpc_multiplexed",
) -> M6CellRecord:
    """Deterministic per-cell classifier (T031, Research R-7 / FR-014).

    Pure function of (cell, per-cohort aggregates, M5.2 baseline JSON).
    Returns exactly one terminal classification per ``VerdictClassification``.

    Step ordering matches R-7:
      1. ``cell_incomplete`` if any cohort has < 80 successes (FR-023).
      2. Compute classifier_metric per cohort (TTFT for chat_stream,
         wall_clock for embed — FR-014).
      3. Compute per-cell ``engine_cost_mean`` (cohort-averaged).
      4. Compute ``engine_cost_drift_warning`` flag (>10% pairwise).
      5. Lookup M5.2 winner delta (R-6 cohort-name mapping); None if M5.2
         verdict was no_winner.
      6. Apply discrimination rule:
         - M5.2 was no_winner → ``no_winner_at_n100`` regardless of M6 CIs.
         - M6 CIs non-overlapping:
             same direction as M5.2 → ``verdict_survives``
             opposite direction    → ``verdict_changed``
         - M6 CIs overlap:
             ``engine_cost_mean >= 5 * |m5_2_winner_delta|`` →
                                     ``verdict_buried_by_engine``
             else                  → ``no_winner_at_n100``

    The ``classifier_grpc_cohort`` parameter picks which gRPC cohort to
    compare against ``rest_https_edge`` for the cohort-pair test; defaults
    to ``tuned_grpc_multiplexed`` (the M6 published cohort; the lookup
    side maps to ``tuned_grpc`` at c=1 per R-6).
    """
    # Step 1: cell_incomplete precondition (FR-023).
    if any(p.n_successes < M6_CELL_COMPLETE_FLOOR for p in per_cohort.values()):
        return _make_incomplete_record(cell, per_cohort)

    # Step 2: classifier metric is path-discriminated (computed by the
    # sweep; aggregates already carry the right values per-cohort).
    classifier_metric = _classifier_metric_for_path(cell.path)

    # Step 3: per-cohort engine_cost mean (path-discriminated).
    per_cohort_engine_means: dict[M6CohortKind, float] = {}
    for kind, agg in per_cohort.items():
        ec = agg.engine_cost_mean
        # TTFT is the classifier_metric for chat_stream; engine_forward_ms
        # for embed (FR-014 comparison metric per path).
        mean = ec.engine_forward_mean_ms if cell.path == "embed" else ec.engine_ttft_mean_ms
        per_cohort_engine_means[kind] = mean if mean is not None else 0.0

    engine_cost_mean_ms = (
        sum(per_cohort_engine_means.values()) / len(per_cohort_engine_means)
        if per_cohort_engine_means
        else 0.0
    )

    # Step 4: drift warning (FR-014 sub-clause).
    drift = compute_drift_warning(per_cohort_engine_means)

    # Step 5: M5.2 winner-delta lookup via R-6 cohort name.
    m5_2_delta, m5_2_verdict_str = get_m5_2_winner_delta(baseline, cell)
    grpc_cohort_name = map_m6_grpc_cohort_to_m5_2_lookup(cell.concurrency)
    row = _find_baseline_row(
        baseline.get("protocol_comparison_verdicts", []) or [],
        cell.path,
        cell.hidden_size,
        cell.concurrency,
        grpc_cohort_name,
    )
    m5_2_direction = _direction_from_m5_2_row(row) if row is not None else None

    # Step 6: M6 cohort-pair CI overlap + discrimination rule.
    cohort_pair: tuple[M6CohortKind, M6CohortKind] = (
        "rest_https_edge",
        classifier_grpc_cohort,
    )
    rest_agg = per_cohort["rest_https_edge"]
    grpc_agg = per_cohort[classifier_grpc_cohort]
    cis_overlap = _cis_overlap(rest_agg, grpc_agg)
    m6_direction = _direction_from_m6_delta(
        rest_agg.classifier_metric_mean_ms, grpc_agg.classifier_metric_mean_ms
    )

    classification: VerdictClassification
    reason_parts: list[str] = []
    if m5_2_delta is None:
        # M5.2 verdict was no_winner — FR-014 sub-case forbids
        # survives/changed regardless of M6 CIs.
        classification = "no_winner_at_n100"
        reason_parts.append(f"M5.2 verdict was {m5_2_verdict_str!r}; M6 cannot supersede")
    elif not cis_overlap:
        if m5_2_direction is not None and m6_direction == m5_2_direction:
            classification = "verdict_survives"
            reason_parts.append(
                f"M6 cohort-pair CIs non-overlapping; direction matches M5.2 ({m5_2_direction})"
            )
        else:
            classification = "verdict_changed"
            reason_parts.append(
                f"M6 cohort-pair CIs non-overlapping; direction flipped from "
                f"M5.2 ({m5_2_direction}) to M6 ({m6_direction})"
            )
    elif engine_cost_mean_ms >= M6_BURIED_BY_ENGINE_FACTOR * m5_2_delta:
        classification = "verdict_buried_by_engine"
        reason_parts.append(
            f"M6 cohort-pair CIs overlap AND engine_cost_mean "
            f"({engine_cost_mean_ms:.2f} ms) >= 5× M5.2 winner delta "
            f"({m5_2_delta:.2f} ms)"
        )
    else:
        classification = "no_winner_at_n100"
        reason_parts.append(
            f"M6 cohort-pair CIs overlap; engine_cost_mean "
            f"({engine_cost_mean_ms:.2f} ms) < 5× M5.2 winner delta "
            f"({m5_2_delta:.2f} ms)"
        )

    return M6CellRecord(
        cell=cell,
        per_cohort=per_cohort,
        classification=classification,
        classification_reason="; ".join(reason_parts),
        classifier_metric=classifier_metric,
        cohort_pair=cohort_pair,
        m5_2_winner_delta_ms=m5_2_delta,
        m5_2_winner_direction=m5_2_direction,
        engine_cost_mean_ms=engine_cost_mean_ms,
        engine_cost_drift_warning=drift,
        per_cohort_engine_cost_mean_ms=per_cohort_engine_means if drift else None,
    )


def _make_incomplete_record(
    cell: M6Cell,
    per_cohort: dict[M6CohortKind, M6PerCohortAggregate],
) -> M6CellRecord:
    """Build the M6CellRecord for a cell that fell below the FR-023 floor.

    ``cell_incomplete`` is a 5th terminal classification (NOT folded into
    a verdict bucket; see FR-023 / data-model.md). All FR-014 sub-clauses
    are skipped — the cohort_pair / m5_2_delta / engine_cost fields take
    documented defaults so downstream renderers don't have to special-case.
    """
    classifier_metric = _classifier_metric_for_path(cell.path)
    min_successes = min(p.n_successes for p in per_cohort.values())
    reason = f"cell_incomplete: min n_successes across cohorts = {min_successes} (< 80)"
    return M6CellRecord(
        cell=cell,
        per_cohort=per_cohort,
        classification="cell_incomplete",
        classification_reason=reason,
        classifier_metric=classifier_metric,
        cohort_pair=("rest_https_edge", "tuned_grpc_multiplexed"),
        m5_2_winner_delta_ms=None,
        m5_2_winner_direction=None,
        engine_cost_mean_ms=0.0,
        engine_cost_drift_warning=False,
        per_cohort_engine_cost_mean_ms=None,
    )


# Re-export so callers can ``from m6_supersede import M6_*`` without
# touching m6_types directly for these classifier-specific constants.
__all__ = [
    "M5_2BaselineMissingCellError",
    "M6_BURIED_BY_ENGINE_FACTOR",
    "M6_CELL_COMPLETE_FLOOR",
    "M6_CHAT_MAX_TOKENS",
    "_DEFAULT_M5_2_BASELINE_PATH",
    "classify_cell",
    "get_m5_2_winner_delta",
    "load_and_validate_m5_2_baseline",
    "map_m6_grpc_cohort_to_m5_2_lookup",
    "snapshot_m5_2_winner_deltas",
]
