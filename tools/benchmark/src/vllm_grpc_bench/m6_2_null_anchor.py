"""M6.2 — null-anchor cross-milestone comparison helpers (FR-012 / FR-013 / FR-014).

Pairs each M6.2 anchor measurement (at ``max_tokens ∈ {10, 50}``) against the
M6.1.3 published CI. The 48-cell anchor pool splits per FR-012 into:

- **22 cross-checkable cells**: cells M6.1.3 published a CI for. The verdict
  is ``PASS`` (inside M6.1.3 CI), ``WARN`` (outside CI but within 2× half-
  width), or ``FAIL`` (outside 2× half-width).
- **26 new-baseline cells**: cells M6.1.3 did NOT publish (the 2 cohort
  omissions × 13 cells, or the chat_stream × max_tokens=10 + embed ×
  max_tokens=50 quadrants depending on the cross-checkable definition). Each
  carries ``new_baseline_marker = True`` and ``drift_verdict = None``.

The FR-014 sweep-level ``null_anchor_drift`` integrity header fires when
≥ ``M6_2_NULL_ANCHOR_DRIFT_COUNT_THRESHOLD`` (2 by default) cross-checkable
cells carry ``drift_verdict ∈ {WARN, FAIL}``. New-baseline cells are
excluded from this count by construction (their verdict is ``None``).
"""

from __future__ import annotations

from vllm_grpc_bench.m6_1_2_types import M6_1_2CohortKind
from vllm_grpc_bench.m6_2_types import (
    M6_2_NULL_ANCHOR_DRIFT_COUNT_THRESHOLD,
    M6_2DriftVerdict,
    M6_2NullAnchor,
)

__all__ = [
    "compute_drift_verdict",
    "compute_null_anchor_drift_header_fired",
    "make_new_baseline_anchor",
    "make_null_anchor",
]


def compute_drift_verdict(
    m6_2_wall_p50_ms: float,
    m6_1_3_wall_p50_ms: float,
    m6_1_3_ci_half_width: float,
) -> M6_2DriftVerdict:
    """FR-012 / FR-013 verdict rule.

    ``PASS``: ``|m6_2 - m6_1_3| <= ci_half_width``.
    ``WARN``: ``ci_half_width < |m6_2 - m6_1_3| <= 2 * ci_half_width``.
    ``FAIL``: ``|m6_2 - m6_1_3| > 2 * ci_half_width``.
    """
    delta = abs(m6_2_wall_p50_ms - m6_1_3_wall_p50_ms)
    if delta <= m6_1_3_ci_half_width:
        return "PASS"
    if delta <= 2.0 * m6_1_3_ci_half_width:
        return "WARN"
    return "FAIL"


def make_null_anchor(
    *,
    cell_id: str,
    cohort: M6_1_2CohortKind,
    max_tokens: int,
    m6_2_wall_p50_ms: float | None,
    m6_1_3_wall_p50_ms: float,
    m6_1_3_ci_half_width: float,
) -> M6_2NullAnchor:
    """Build a cross-checkable :class:`M6_2NullAnchor` (M6.1.3 baseline present).

    ``m6_2_wall_p50_ms=None`` (M6.2 anchor block failed) yields
    ``drift_verdict="FAIL"`` and ``drift_fraction=None``.
    """
    if m6_2_wall_p50_ms is None:
        return M6_2NullAnchor(
            cell_id=cell_id,
            cohort=cohort,
            max_tokens=max_tokens,
            m6_2_wall_p50_ms=None,
            m6_1_3_wall_p50_ms=m6_1_3_wall_p50_ms,
            m6_1_3_ci_half_width=m6_1_3_ci_half_width,
            drift_verdict="FAIL",
            drift_fraction=None,
            new_baseline_marker=False,
        )
    verdict = compute_drift_verdict(m6_2_wall_p50_ms, m6_1_3_wall_p50_ms, m6_1_3_ci_half_width)
    drift_fraction = (
        (m6_2_wall_p50_ms - m6_1_3_wall_p50_ms) / m6_1_3_ci_half_width
        if m6_1_3_ci_half_width > 0
        else 0.0
    )
    return M6_2NullAnchor(
        cell_id=cell_id,
        cohort=cohort,
        max_tokens=max_tokens,
        m6_2_wall_p50_ms=m6_2_wall_p50_ms,
        m6_1_3_wall_p50_ms=m6_1_3_wall_p50_ms,
        m6_1_3_ci_half_width=m6_1_3_ci_half_width,
        drift_verdict=verdict,
        drift_fraction=drift_fraction,
        new_baseline_marker=False,
    )


def make_new_baseline_anchor(
    *,
    cell_id: str,
    cohort: M6_1_2CohortKind,
    max_tokens: int,
    m6_2_wall_p50_ms: float | None,
) -> M6_2NullAnchor:
    """Build a new-baseline :class:`M6_2NullAnchor` (no M6.1.3 reference).

    ``new_baseline_marker=True``; ``drift_verdict=None``; the cell is excluded
    from the FR-014 sweep-level header count by construction.
    """
    return M6_2NullAnchor(
        cell_id=cell_id,
        cohort=cohort,
        max_tokens=max_tokens,
        m6_2_wall_p50_ms=m6_2_wall_p50_ms,
        m6_1_3_wall_p50_ms=None,
        m6_1_3_ci_half_width=None,
        drift_verdict=None,
        drift_fraction=None,
        new_baseline_marker=True,
    )


def compute_null_anchor_drift_header_fired(
    anchors: list[M6_2NullAnchor],
    *,
    threshold: int = M6_2_NULL_ANCHOR_DRIFT_COUNT_THRESHOLD,
) -> bool:
    """FR-014 sweep-level ``null_anchor_drift`` integrity header rule.

    Fires iff at least ``threshold`` cross-checkable cells (``new_baseline_marker
    is False``) carry ``drift_verdict ∈ {"WARN", "FAIL"}``. New-baseline cells
    are excluded from the count by construction.
    """
    drifted = sum(
        1 for a in anchors if (not a.new_baseline_marker) and a.drift_verdict in {"WARN", "FAIL"}
    )
    return drifted >= threshold
