"""M6.1.3 — Multi-run between-run variance + Phase B trigger verdict
(FR-024 / FR-025 / FR-026 / FR-027 / FR-043 / FR-044 + round-2 Q3).

Net-new module per the plan's table — no copy source. The algorithmic
spec lives in ``specs/026-m6-1-3-attribution-closure/contracts/
artifact-schema.md`` "Between-Run Variance reporter section" +
``contracts/classifier.md`` "The ``inconclusive_high_variance``
outer-override label".

The module's role is to characterize run-to-run variance for the
multi-run publish sweep (``--m6_1_3`` at ``repeat=5``) and convert that
characterization into two downstream signals:

* **Outer-override** (FR-026): a cell whose between-run stddev exceeds
  the unified high-variance threshold × within-run CI half-width is
  re-labelled ``inconclusive_high_variance (<inner>)`` by the classifier.
  The inner label remains as a parenthetical so the reader sees both
  signals.
* **Phase B trigger** (FR-043 / FR-044 / round-2 Q3): the set of cells
  carrying ``inconclusive_high_variance`` derives the Phase B
  publication requirement. The unified threshold (round-2 Q3) drives both
  signals from a single ``/speckit-plan`` knob.

Per FR-025 + round-2 Q5: the variance section is suppressed when fewer
than 3 runs were collected (single-run validate sweep, or operator
override ``--m6_1_3-diagnose-repeat < 3``). In the suppressed case the
Phase B trigger verdict falls back to the FR-044 override text.

Per FR-027: a cohort with 0 successful RPCs in one of the N runs has its
contribution dropped for the cell × cohort variance estimate. If 3+
runs fail for the same cohort × cell, the variance compute emits ``None``
for ``mean_of_means_ms`` / ``stddev_of_means_ms`` and the classifier
emits a ``cohort_unhealthy`` warning (carried in the artifact's
``classifier_notes`` list).
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from typing import TYPE_CHECKING

from vllm_grpc_bench.m6_1_3_types import (
    M6_1_2CohortKind,
    M6_1_3BetweenRunVariance,
    M6_1_3BetweenRunVarianceCell,
    M6_1_3PhaseBTriggerVerdict,
)

if TYPE_CHECKING:
    from vllm_grpc_bench.m6_1_3_reporter import M6_1_3CellMeasurement


# Per FR-025: the variance section renders only when at least 3 runs
# were collected. Single-run validate sweeps and 2-run operator overrides
# suppress the section.
_MIN_RUNS_FOR_VARIANCE: int = 3

# Per FR-027: a cohort that fails (n_successes == 0) in ≥ this many runs
# triggers a ``None`` variance estimate + ``cohort_unhealthy`` classifier
# warning. The threshold is set so a 5-run sweep tolerates 2 failures but
# emits ``None`` once the data drops below a meaningful variance estimate.
_COHORT_UNHEALTHY_FAILURE_THRESHOLD: int = 3


def _cell_id(path: str, concurrency: int) -> str:
    """Canonical cell identifier — mirrors ``m6_1_3_reporter._cell_id``.

    Kept here to avoid a circular import (the reporter imports this
    module via the artifact's ``between_run_variance`` field; this
    module imports the reporter only at TYPE_CHECKING time).
    """
    return f"{path}_c{concurrency}"


def should_render_variance_section(
    phase_1_runs: Sequence[Sequence[M6_1_3CellMeasurement]],
) -> bool:
    """FR-025: True iff ``len(phase_1_runs) >= 3``.

    Single-run validate sweeps (``repeat=1``) and 2-run operator
    overrides suppress the between-run variance section — there's no
    meaningful variance estimate from < 3 runs. The reporter checks this
    before emitting the section.
    """
    return len(phase_1_runs) >= _MIN_RUNS_FOR_VARIANCE


def compute_between_run_variance(
    phase_1_runs: Sequence[Sequence[M6_1_3CellMeasurement]],
) -> M6_1_3BetweenRunVariance:
    """Compute per-cell-cohort between-run variance per FR-024.

    For each ``(cell_id, cohort)`` pair, collects the per-run
    ``engine_ttft_ms_mean`` values (one per run) and emits the
    cross-run mean + stddev + healthy-run count. Per FR-027:

    * Runs where the cohort had ``n_successes == 0`` are dropped from
      the per-cohort sample (the cohort didn't contribute usable
      timings).
    * If ``≥ 3`` runs fail for the same cohort × cell, the variance
      estimate is ``None`` (insufficient signal). The classifier wrapper
      surfaces a ``cohort_unhealthy`` warning in this case.
    * Otherwise, ``mean_of_means_ms`` + ``stddev_of_means_ms`` are
      computed from the healthy runs.

    Returns a nested dict ``{cell_id: {cohort: M6_1_3BetweenRunVarianceCell}}``
    suitable for direct embedding in :class:`M6_1_3SweepArtifact`.
    """
    n_total_runs = len(phase_1_runs)
    if n_total_runs == 0:
        return {}

    # Group ``engine_ttft_ms_mean`` per ``(cell_id, cohort)`` across runs.
    # Drop runs where the cohort had 0 successes per FR-027.
    by_cell_cohort: dict[str, dict[M6_1_2CohortKind, list[float]]] = {}
    for run_measurements in phase_1_runs:
        for m in run_measurements:
            if m.n_successes == 0 or m.engine_ttft_ms_mean is None:
                continue
            cell_id = _cell_id(m.path, m.concurrency)
            by_cell_cohort.setdefault(cell_id, {}).setdefault(m.cohort, []).append(
                float(m.engine_ttft_ms_mean)
            )

    result: M6_1_3BetweenRunVariance = {}
    for cell_id in sorted(by_cell_cohort.keys()):
        per_cohort_means = by_cell_cohort[cell_id]
        cell_dict: dict[M6_1_2CohortKind, M6_1_3BetweenRunVarianceCell] = {}
        for cohort in sorted(per_cohort_means.keys()):
            means = per_cohort_means[cohort]
            n_healthy = len(means)
            n_failed = n_total_runs - n_healthy
            if n_failed >= _COHORT_UNHEALTHY_FAILURE_THRESHOLD:
                # Per FR-027: emit None when 3+ runs failed for this cohort.
                cell_dict[cohort] = M6_1_3BetweenRunVarianceCell(
                    mean_of_means_ms=None,
                    stddev_of_means_ms=None,
                    n_runs=n_healthy,
                )
                continue
            if n_healthy < 2:
                # Can't compute stddev with fewer than 2 samples even if
                # < 3 failed (e.g., a 2-run sweep where one cohort failed
                # in run 1). Emit None means/stddev.
                cell_dict[cohort] = M6_1_3BetweenRunVarianceCell(
                    mean_of_means_ms=means[0] if n_healthy == 1 else None,
                    stddev_of_means_ms=None,
                    n_runs=n_healthy,
                )
                continue
            mean_of_means = float(sum(means) / n_healthy)
            stddev_of_means = float(statistics.stdev(means))
            cell_dict[cohort] = M6_1_3BetweenRunVarianceCell(
                mean_of_means_ms=mean_of_means,
                stddev_of_means_ms=stddev_of_means,
                n_runs=n_healthy,
            )
        result[cell_id] = cell_dict
    return result


def should_fire_inconclusive_high_variance(
    cell_variance: M6_1_3BetweenRunVarianceCell,
    cell_ci_halfwidth_ms: float,
    threshold: float,
) -> bool:
    """Unified high-variance gate per FR-026 + FR-043 + round-2 Q3.

    Fires when the between-run ``stddev_of_means_ms`` exceeds
    ``threshold × cell_ci_halfwidth_ms``. Both signals come from a
    single ``/speckit-plan`` knob (the unified threshold) — the
    outer-override (FR-026) and Phase B publication requirement
    (FR-043) share one tuning dial.

    Returns ``False`` when the variance estimate is unavailable
    (``stddev_of_means_ms is None``, e.g. due to FR-027 cohort_unhealthy
    drop) or when the CI half-width is non-positive (degenerate cell).
    """
    if cell_variance.stddev_of_means_ms is None:
        return False
    if cell_ci_halfwidth_ms <= 0:
        return False
    return cell_variance.stddev_of_means_ms > threshold * cell_ci_halfwidth_ms


def reduce_cell_variance(
    per_cohort: dict[M6_1_2CohortKind, M6_1_3BetweenRunVarianceCell],
) -> M6_1_3BetweenRunVarianceCell | None:
    """Collapse per-cohort variance entries into a single cell-level value.

    The classifier outer-override operates on ONE
    :class:`M6_1_3BetweenRunVarianceCell` per cell. Multiple cohorts'
    variances per cell are collapsed by picking the MAX
    ``stddev_of_means_ms`` (the worst-case cohort — most likely to fire
    the outer override). Ties broken by max ``mean_of_means_ms`` for
    determinism. Returns ``None`` if no cohort has a non-None
    ``stddev_of_means_ms`` (FR-027 cohort_unhealthy collapse).
    """
    candidates = [cell for cell in per_cohort.values() if cell.stddev_of_means_ms is not None]
    if not candidates:
        return None
    # Max by stddev, then max by mean as deterministic tie-breaker.
    return max(
        candidates,
        key=lambda c: (
            c.stddev_of_means_ms or 0.0,
            c.mean_of_means_ms or 0.0,
        ),
    )


def compute_phase_b_trigger(
    classifications: dict[str, str],
    *,
    variance_section_suppressed: bool,
) -> M6_1_3PhaseBTriggerVerdict:
    """Phase B publication-requirement verdict per FR-043 + FR-044 +
    round-2 Q3.

    The trigger is mechanical: cells carrying ``inconclusive_high_variance``
    are the Phase B trigger cells. The verdict's ``required`` flag is
    True iff any cell triggers; ``trigger_cells`` is the alphabetically-
    sorted list of cell IDs.

    When the variance section is suppressed (< 3 runs accumulated, per
    FR-025), the trigger verdict is unavailable — the reporter renders
    the FR-044 override fallback text instead of a Phase-required /
    not-required determination.
    """
    if variance_section_suppressed:
        return M6_1_3PhaseBTriggerVerdict(
            required=False,
            trigger_cells=[],
            variance_section_suppressed=True,
        )
    trigger_cells = sorted(
        cell_id
        for cell_id, label in classifications.items()
        if label.startswith("inconclusive_high_variance")
    )
    return M6_1_3PhaseBTriggerVerdict(
        required=bool(trigger_cells),
        trigger_cells=trigger_cells,
        variance_section_suppressed=False,
    )


def compute_cell_ci_halfwidth_ms(
    per_cohort: dict[M6_1_2CohortKind, float],
) -> float:
    """Cell-level within-run CI half-width — used as the denominator of
    the unified high-variance threshold per FR-026 + round-2 Q3.

    Takes the per-cohort engine_ttft CI half-widths (in ms) and returns
    a single cell-level value. We use the MAX across cohorts so the
    threshold is the most-conservative gate (the cohort with the
    widest within-run uncertainty drives the comparison). Returns 0.0
    when no cohort had a CI estimate.
    """
    halfwidths = [hw for hw in per_cohort.values() if hw > 0]
    if not halfwidths:
        return 0.0
    return float(max(halfwidths))


__all__ = [
    "compute_between_run_variance",
    "compute_cell_ci_halfwidth_ms",
    "compute_phase_b_trigger",
    "reduce_cell_variance",
    "should_fire_inconclusive_high_variance",
    "should_render_variance_section",
]
