"""M6.2 — intra-sweep anchor-latency trajectory (FR-031 + SC-016).

The 4-hour-mark re-anchor mechanism. Every 4 sweep hours (publish mode) or
at sweep start + end (validate mode), the orchestrator pauses interior-cap
RPCs and runs an anchor block: chat_stream c=1 × max_tokens=10 × n=20 using
the SYNTHETIC prompt regime (NOT corpus) — preserves byte-comparability with
M6.1.3's published anchor CI so the per-cohort spread is interpretable as
network/temporal drift rather than prompt-source drift (R-3).

The collected trajectory feeds three artifacts:

- Per-cohort ``M6_2AnchorLatencyTrajectory`` records (rendered as the "Anchor
  latency trajectory" markdown subsection per FR-031).
- The per-cohort ``latency_drift_warning`` flag (fires when the trajectory's
  ``max - min`` spread exceeds M6.1.3's baseline CI half-width).
- The sweep-level ``intra_sweep_latency_drift`` integrity header (fires when
  ≥ 2 of the 4 cohorts carry ``latency_drift_warning`` per SC-016).
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable
from typing import Protocol

from vllm_grpc_bench.m6_1_2_types import M6_1_2_COHORTS, M6_1_2CohortKind
from vllm_grpc_bench.m6_2_types import (
    M6_2_LATENCY_DRIFT_COHORT_COUNT_THRESHOLD,
    M6_2AnchorLatencySnapshot,
    M6_2AnchorLatencyTrajectory,
)

__all__ = [
    "AnchorRPCDriver",
    "compute_anchor_block",
    "compute_anchor_latency_trajectory",
    "compute_intra_sweep_drift_header_fired",
]


class AnchorRPCDriver(Protocol):
    """Sweep-supplied callable that dispatches the anchor RPC block.

    The orchestrator wires this to a thin wrapper around the chat_stream
    gRPC driver primitive (``m6_rpc_driver._drive_grpc_chat``) configured for
    cell ``chat_stream_c1``, ``max_tokens=10``, ``ignore_eos=False``, and
    synthetic seed-derived prompts. Returns the per-RPC wall-clock latencies
    in milliseconds (one float per successful RPC; failed RPCs omitted)."""

    def __call__(
        self,
        *,
        cohort: M6_1_2CohortKind,
        n: int,
        base_seed: int,
        seed_offset: int,
    ) -> list[float]: ...


def _now_iso_utc() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _percentile(samples: list[float], p: float) -> float:
    """Linear-interpolation percentile (matches M6.1.x reporter convention)."""
    if not samples:
        raise ValueError("percentile of empty sample set")
    sorted_samples = sorted(samples)
    if len(sorted_samples) == 1:
        return sorted_samples[0]
    idx = (p / 100.0) * (len(sorted_samples) - 1)
    low = int(idx)
    high = min(low + 1, len(sorted_samples) - 1)
    weight = idx - low
    return sorted_samples[low] * (1.0 - weight) + sorted_samples[high] * weight


def compute_anchor_block(
    cohorts: list[M6_1_2CohortKind],
    rpc_driver: AnchorRPCDriver,
    base_seed: int,
    sweep_hour_mark: float,
    *,
    cell_id: str = "chat_stream_c1",
    max_tokens: int = 10,
    n: int = 20,
    seed_offset: int = 0,
    now_iso_utc: Callable[[], str] = _now_iso_utc,
) -> dict[M6_1_2CohortKind, M6_2AnchorLatencySnapshot]:
    """Run one anchor block across all 4 cohorts at the given sweep-hour mark.

    ``cell_id`` and ``max_tokens`` are conventionally fixed at chat_stream_c1
    + max_tokens=10; the keyword-only arguments exist so the orchestrator can
    inject alternatives for diagnostics or future milestones without
    re-implementing the per-snapshot summary statistics.

    The synthetic prompt regime is the responsibility of ``rpc_driver`` — this
    function only orchestrates the per-cohort summary statistics + UTC
    timestamp capture. Failed cohorts (empty ``rpc_driver`` return) are
    skipped silently and produce no snapshot for that cohort.
    """
    del cell_id  # currently fixed; reserved for future-milestone overrides
    snapshots: dict[M6_1_2CohortKind, M6_2AnchorLatencySnapshot] = {}
    for cohort in cohorts:
        samples = rpc_driver(
            cohort=cohort,
            n=n,
            base_seed=base_seed,
            seed_offset=seed_offset,
        )
        if not samples:
            continue
        snapshots[cohort] = M6_2AnchorLatencySnapshot(
            wall_p50_ms=_percentile(samples, 50.0),
            wall_p95_ms=_percentile(samples, 95.0),
            wall_p99_ms=_percentile(samples, 99.0),
            snapshot_timestamp=now_iso_utc(),
            sweep_hour_mark=sweep_hour_mark,
        )
    return snapshots


def compute_anchor_latency_trajectory(
    snapshots_by_cohort: dict[M6_1_2CohortKind, list[M6_2AnchorLatencySnapshot]],
    m6_1_3_baseline_ci_half_width: float,
) -> dict[M6_1_2CohortKind, M6_2AnchorLatencyTrajectory]:
    """Reduce the per-cohort sequence of snapshots into trajectory entities.

    For each cohort, compute the ``wall_p50_ms`` spread across snapshots and
    set ``latency_drift_warning=True`` iff ``spread > baseline_ci_half_width``
    (FR-031). Cohorts with fewer than 2 snapshots get
    ``max_minus_min_wall_p50_ms=0.0`` + ``latency_drift_warning=False`` (no
    meaningful spread can be computed)."""
    out: dict[M6_1_2CohortKind, M6_2AnchorLatencyTrajectory] = {}
    for cohort, snapshots in snapshots_by_cohort.items():
        if len(snapshots) < 2:
            spread = 0.0
            warning = False
        else:
            p50s = [s.wall_p50_ms for s in snapshots]
            spread = max(p50s) - min(p50s)
            warning = spread > m6_1_3_baseline_ci_half_width
        out[cohort] = M6_2AnchorLatencyTrajectory(
            cohort=cohort,
            snapshots=list(snapshots),
            max_minus_min_wall_p50_ms=spread,
            latency_drift_warning=warning,
        )
    return out


def compute_intra_sweep_drift_header_fired(
    trajectories: dict[M6_1_2CohortKind, M6_2AnchorLatencyTrajectory],
) -> bool:
    """SC-016: fire the sweep-level ``intra_sweep_latency_drift`` integrity
    header when ≥ 2 of 4 cohorts carry per-cohort ``latency_drift_warning``.

    The cohort universe is M6.1.2's 4-cohort set; trajectories for cohorts
    absent from ``trajectories`` (e.g., cohort dropped due to consistent
    failure) count as "no drift detected" — they do not fire the warning.
    """
    drifted = sum(1 for t in trajectories.values() if t.latency_drift_warning)
    return drifted >= M6_2_LATENCY_DRIFT_COHORT_COUNT_THRESHOLD


def default_cohorts() -> list[M6_1_2CohortKind]:
    """Return a fresh list of the 4 canonical M6.1.2 cohorts."""
    return list(M6_1_2_COHORTS)
