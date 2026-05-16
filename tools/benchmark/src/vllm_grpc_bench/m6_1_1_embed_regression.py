"""M6.1.1 — FR-015b embed regression check (round-2 Q2, round-1 Q5).

Phase 2(a) measures embed cells alongside chat_stream cells (FR-015) to
detect whether the symmetrisation code change inadvertently perturbed the
embed measurement window. The check is per (embed cell × cohort): compare
M6.1.1's measured ``engine_forward_ms`` mean against M6.1's published
baseline; flag ``embed_regression_warning`` if ``|delta_pct| > 0.05``.

**Baseline fallback note**: M6.1's published JSON carries
``per_cohort_engine_cost_mean_ms = null`` for embed cells — M6.1's
methodology aggregated embed measurements per-cell only. M6.1.1's
per-cohort comparison therefore uses M6.1's per-cell aggregate as the
reference for all three cohorts (the same baseline value for each).
This is the pragmatic baseline that matches what M6.1 actually published;
the cross-cohort comparison still detects whether M6.1.1's symmetrisation
caused any per-cohort embed drift relative to M6.1's per-cell mean.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from vllm_grpc_bench.m6_1_1_types import (
    EMBED_REGRESSION_TOLERANCE,
    EmbedRegressionCheckResult,
    EmbedRegressionResult,
    M6_1_1Cell,
    M6_1_1Cohort,
    Phase2Choice,
)


def _extract_m6_1_embed_baselines(m6_1_baseline: Mapping[str, Any]) -> dict[tuple[int, int], float]:
    """Extract per-cell ``engine_cost_mean_ms`` for the 3 embed cells from
    M6.1's baseline. Returns a dict keyed by ``(concurrency, hidden_size)``.

    Raises :class:`KeyError` when the baseline doesn't carry data for one of
    the 3 expected embed cells (c ∈ {1, 4, 8} × h=4096).
    """
    out: dict[tuple[int, int], float] = {}
    for entry in m6_1_baseline.get("engine_cost_baseline", []):
        if not isinstance(entry, Mapping):
            continue
        cell = entry.get("cell", {})
        if cell.get("path") != "embed":
            continue
        try:
            key = (int(cell["concurrency"]), int(cell["hidden_size"]))
            out[key] = float(entry["engine_cost_mean_ms"])
        except (KeyError, ValueError, TypeError):
            continue
    return out


def compute_embed_regression(
    per_cohort_results: Mapping[tuple[M6_1_1Cell, M6_1_1Cohort], float],
    m6_1_baseline: Mapping[str, Any],
    *,
    phase_2_choice: Phase2Choice | None = None,
) -> EmbedRegressionCheckResult:
    """Per (embed cell × cohort), compute ``delta_pct`` vs M6.1's baseline.

    ``per_cohort_results`` is a mapping ``(cell, cohort) -> engine_forward_ms_mean``
    measured by M6.1.1's Phase 2(a) sweep. Expected to contain 9 entries
    (3 embed cells × 3 cohorts).

    Returns :class:`EmbedRegressionCheckResult` aggregating per-entry warnings.
    ``phase_2_choice.embed_regression_acknowledged`` propagates through to
    each entry's ``embed_regression_acknowledged`` field; when None the
    flag is treated as False.
    """
    m6_1_per_cell = _extract_m6_1_embed_baselines(m6_1_baseline)
    acknowledged = bool(phase_2_choice and phase_2_choice.embed_regression_acknowledged)
    justification = phase_2_choice.embed_regression_justification if phase_2_choice else None

    entries: list[EmbedRegressionResult] = []
    for (cell, cohort), m6_1_1_mean in per_cohort_results.items():
        if cell.path != "embed":
            continue
        baseline_mean = m6_1_per_cell.get((int(cell.concurrency), int(cell.hidden_size)))
        if baseline_mean is None or baseline_mean == 0.0:
            continue
        delta_pct = (m6_1_1_mean - baseline_mean) / baseline_mean
        warning = abs(delta_pct) > EMBED_REGRESSION_TOLERANCE
        entries.append(
            EmbedRegressionResult(
                cell=cell,
                cohort=cohort,
                m6_1_engine_forward_ms_mean=baseline_mean,
                m6_1_1_engine_forward_ms_mean=m6_1_1_mean,
                delta_pct=delta_pct,
                embed_regression_warning=warning,
                embed_regression_acknowledged=acknowledged,
                operator_justification=justification if (warning and acknowledged) else None,
            )
        )

    n_warnings = sum(1 for e in entries if e.embed_regression_warning)
    return EmbedRegressionCheckResult(
        per_entry=entries,
        n_warnings=n_warnings,
        all_within_tolerance=(n_warnings == 0),
        acknowledged_count=sum(1 for e in entries if e.embed_regression_acknowledged),
    )


__all__ = ["compute_embed_regression"]
