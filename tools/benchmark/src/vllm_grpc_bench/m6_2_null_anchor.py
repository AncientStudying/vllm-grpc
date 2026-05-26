"""M6.2 — null-anchor cross-milestone comparison helpers (FR-012 / FR-013 / FR-014).

Pairs each M6.2 anchor measurement (at ``max_tokens ∈ {10, 50}``) against the
M6.1.3 published CI. The 48-cell anchor pool splits per FR-012 into:

- **22 cross-checkable cells**: cells M6.1.3 published a CI for. The verdict
  is computed via the pooled-CI-with-floor rule (see
  :func:`compute_drift_verdict`).
- **26 new-baseline cells**: cells M6.1.3 did NOT publish (the 2 cohort
  omissions × 13 cells, or the chat_stream × max_tokens=10 + embed ×
  max_tokens=50 quadrants depending on the cross-checkable definition). Each
  carries ``new_baseline_marker = True`` and ``drift_verdict = None``.

The FR-014 sweep-level ``null_anchor_drift`` integrity header fires when
≥ ``M6_2_NULL_ANCHOR_DRIFT_COUNT_THRESHOLD`` (2 by default) cross-checkable
cells carry ``drift_verdict ∈ {WARN, FAIL}``. New-baseline cells are
excluded from this count by construction (their verdict is ``None``).

Threshold rule (B2, 2026-05-23): the prior rule compared ``|delta|`` against
M6.1.3's CI half-width alone. M6.1.3's CIs were measured under tighter
conditions than M6.2's per-block n=20 sweeps, so sub-ms baseline CIs made
the gate trip at 100σ+ on operationally-insignificant deltas. The pooled
rule respects both the baseline precision and the current sweep's per-block
variance, with a 10 ms floor that prevents pathological tiny CIs (either
side) from firing on noise.
"""

from __future__ import annotations

from vllm_grpc_bench.m6_1_2_types import M6_1_2CohortKind
from vllm_grpc_bench.m6_2_types import (
    M6_2_NULL_ANCHOR_DRIFT_COUNT_THRESHOLD,
    M6_2DriftVerdict,
    M6_2NullAnchor,
)

__all__ = [
    "DRIFT_THRESHOLD_FLOOR_FRACTION",
    "DRIFT_THRESHOLD_FLOOR_MS",
    "DRIFT_THRESHOLD_WARN_MULTIPLIER",
    "compute_drift_verdict",
    "compute_null_anchor_drift_header_fired",
    "make_new_baseline_anchor",
    "make_null_anchor",
    "pooled_ci_half_width",
]

DRIFT_THRESHOLD_FLOOR_MS: float = 10.0
"""B2 absolute lower bound on the per-cell drift threshold (ms). Prevents
sub-ms baseline CIs (M6.1.3 ``chat_stream_c1`` ``default_grpc`` published a
0.14 ms CI) from flagging operationally-insignificant drift as a sweep-level
failure."""

DRIFT_THRESHOLD_FLOOR_FRACTION: float = 0.025
"""B4 relative-magnitude lower bound on the per-cell drift threshold,
expressed as a fraction of the M6.1.3 baseline ``wall_p50_ms``. Round-8
amendment (2026-05-23) — extends the B2 absolute floor with a relative
co-floor that suppresses operationally-insignificant drift on cells whose
baseline p50 is large enough that the 10 ms absolute floor (B2) is the
dominant denominator. Pinned at 2.5% (~2× M6.1.3's observed within-baseline
re-anchor drift) so genuine ~5–10% regressions remain visible while
sub-3% drift on naturally-slow cells (e.g., chat_stream at max_tokens=2048
with p50 in the tens of seconds) is treated as PASS."""

DRIFT_THRESHOLD_WARN_MULTIPLIER: float = 3.0
"""Multiplier separating WARN from FAIL on the pooled-CI scale. ``PASS`` when
``|delta| <= pooled``; ``WARN`` when ``pooled < |delta| <= 3 * pooled``;
``FAIL`` beyond. The 3× upper band keeps FAIL roughly at the operationally
"this is real drift, not measurement noise" point."""


def pooled_ci_half_width(
    m6_1_3_ci_half_width: float,
    m6_2_ci_half_width: float = 0.0,
    *,
    baseline_p50_ms: float = 0.0,
    floor_ms: float = DRIFT_THRESHOLD_FLOOR_MS,
    floor_fraction: float = DRIFT_THRESHOLD_FLOOR_FRACTION,
) -> float:
    """Compute the per-cell drift threshold (ms) under the round-8 B2+B4 rule.

    ``pooled = max(m6_1_3_ci_half_width, m6_2_ci_half_width, floor_ms,
    floor_fraction * baseline_p50_ms)``. Negative inputs are coerced to 0
    before the max.

    The ``baseline_p50_ms=0.0`` default reduces to the pre-B4 B2 behavior so
    callers that don't have the baseline p50 in scope still get a
    well-defined threshold; threading the actual baseline activates B4.
    """
    return max(
        max(m6_1_3_ci_half_width, 0.0),
        max(m6_2_ci_half_width, 0.0),
        floor_ms,
        max(baseline_p50_ms, 0.0) * max(floor_fraction, 0.0),
    )


def compute_drift_verdict(
    m6_2_wall_p50_ms: float,
    m6_1_3_wall_p50_ms: float,
    m6_1_3_ci_half_width: float,
    m6_2_ci_half_width: float = 0.0,
    *,
    floor_ms: float = DRIFT_THRESHOLD_FLOOR_MS,
    floor_fraction: float = DRIFT_THRESHOLD_FLOOR_FRACTION,
    warn_multiplier: float = DRIFT_THRESHOLD_WARN_MULTIPLIER,
) -> M6_2DriftVerdict:
    """Pooled-CI-with-floor verdict rule (B2 + B4 round-8 amendment).

    ``pooled = max(m6_1_3_ci_half_width, m6_2_ci_half_width, floor_ms,
    floor_fraction * m6_1_3_wall_p50_ms)``.
    ``PASS``: ``|m6_2 - m6_1_3| <= pooled``.
    ``WARN``: ``pooled < |m6_2 - m6_1_3| <= warn_multiplier * pooled``.
    ``FAIL``: ``|m6_2 - m6_1_3| > warn_multiplier * pooled``.

    ``m6_2_ci_half_width=0.0`` (default) reduces to a single-sided pooling
    against the baseline + floor, which is the right behavior for callers
    that don't have the M6.2 per-block CI in scope.
    """
    delta = abs(m6_2_wall_p50_ms - m6_1_3_wall_p50_ms)
    pooled = pooled_ci_half_width(
        m6_1_3_ci_half_width,
        m6_2_ci_half_width,
        baseline_p50_ms=m6_1_3_wall_p50_ms,
        floor_ms=floor_ms,
        floor_fraction=floor_fraction,
    )
    if delta <= pooled:
        return "PASS"
    if delta <= warn_multiplier * pooled:
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
    m6_2_ci_half_width: float = 0.0,
) -> M6_2NullAnchor:
    """Build a cross-checkable :class:`M6_2NullAnchor` (M6.1.3 baseline present).

    ``m6_2_wall_p50_ms=None`` (M6.2 anchor block failed) yields
    ``drift_verdict="FAIL"`` and ``drift_fraction=None``.

    ``drift_fraction`` is preserved as a diagnostic and is computed against
    the pooled CI half-width (not the bare M6.1.3 CI) so the reported value
    matches the threshold-band placement of the verdict.
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
    verdict = compute_drift_verdict(
        m6_2_wall_p50_ms,
        m6_1_3_wall_p50_ms,
        m6_1_3_ci_half_width,
        m6_2_ci_half_width,
    )
    pooled = pooled_ci_half_width(
        m6_1_3_ci_half_width,
        m6_2_ci_half_width,
        baseline_p50_ms=m6_1_3_wall_p50_ms,
    )
    drift_fraction = (m6_2_wall_p50_ms - m6_1_3_wall_p50_ms) / pooled if pooled > 0 else 0.0
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
