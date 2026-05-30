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
  ``max - min`` spread exceeds the pooled-CI threshold; see B2 rule below).
- The sweep-level ``intra_sweep_latency_drift`` integrity header (fires when
  ≥ 2 of the 4 cohorts carry ``latency_drift_warning`` per SC-016).

Threshold rule (B2, 2026-05-23): the prior rule fired when ``max-min``
exceeded M6.1.3's baseline CI half-width alone. M6.1.3's CIs are sub-ms for
several cohorts so any natural intra-sweep variance tripped the gate. The
new rule applies the same pooled-CI-with-floor formula as SC-004
(see :mod:`m6_2_null_anchor`): ``threshold = max(m6_1_3_ci_hw,
snapshot_ci_hw, 10ms)`` where ``snapshot_ci_hw`` is the 95% normal-
approximation CI half-width over the trajectory's p50 samples.
"""

from __future__ import annotations

import datetime as _dt
import statistics
from collections.abc import Callable
from typing import Protocol

from vllm_grpc_bench.m6_1_2_types import M6_1_2_COHORTS, M6_1_2CohortKind
from vllm_grpc_bench.m6_2_null_anchor import (
    DRIFT_THRESHOLD_FLOOR_FRACTION,
    DRIFT_THRESHOLD_FLOOR_MS,
    pooled_ci_half_width,
)
from vllm_grpc_bench.m6_2_types import (
    M6_2_LATENCY_DRIFT_COHORT_COUNT_THRESHOLD,
    M6_2AnchorLatencySnapshot,
    M6_2AnchorLatencyTrajectory,
)

__all__ = [
    "AnchorRPCDriver",
    "WARMUP_SUPPRESSION_HOURS",
    "compute_anchor_block",
    "compute_anchor_latency_trajectory",
    "compute_insufficient_snapshots_header_fired",
    "compute_intra_sweep_drift_header_fired",
]


WARMUP_SUPPRESSION_HOURS: float = 0.05
"""C1 round-8 amendment (2026-05-23): snapshots with
``sweep_hour_mark < WARMUP_SUPPRESSION_HOURS`` (default 0.05 h = 3 min) are
dropped from the spread computation. Suppresses Modal cold-start +
cudagraph-capture warmup transients that inflated pre-fix validate
trajectories. 3 min covers Modal first-request + CUDA graph compilation
(~30-60 s) plus the engine-warmup overhead the chat_stream c=1
max_tokens=10 anchor block sees on first invocation."""


def _snapshot_ci_half_width(snapshots: list[M6_2AnchorLatencySnapshot]) -> float:
    """95% normal-approximation CI half-width (1.96 × stderr) over the
    trajectory's ``wall_p50_ms`` samples. Mirrors
    :func:`sweep._ci_half_width_95`. Returns 0.0 when ``n < 2``."""
    if len(snapshots) < 2:
        return 0.0
    p50s = [s.wall_p50_ms for s in snapshots]
    return float(1.96 * statistics.stdev(p50s) / (len(p50s) ** 0.5))


class AnchorRPCDriver(Protocol):
    """Sweep-supplied async callable that dispatches the anchor RPC block.

    The orchestrator wires this to a thin wrapper around the chat_stream
    gRPC driver primitive (``m6_rpc_driver._drive_grpc_chat``) configured for
    cell ``chat_stream_c1``, ``max_tokens=10``, ``ignore_eos=False``, and
    synthetic seed-derived prompts. Returns the per-RPC wall-clock latencies
    in milliseconds (one float per successful RPC; failed RPCs omitted).

    Async-shaped so real Modal adapters can fire RPCs via the shared
    ``provide_m6_2_rpc_driver`` callable without juggling a parallel
    synchronous client; the stub anchor dispatcher in tests is also async."""

    async def __call__(
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


async def compute_anchor_block(
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
    del max_tokens  # currently fixed at the M6.1.x synthetic default
    snapshots: dict[M6_1_2CohortKind, M6_2AnchorLatencySnapshot] = {}
    for cohort in cohorts:
        samples = await rpc_driver(
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
    *,
    baseline_p50_ms: float = 0.0,
    floor_ms: float = DRIFT_THRESHOLD_FLOOR_MS,
    floor_fraction: float = DRIFT_THRESHOLD_FLOOR_FRACTION,
    warmup_suppression_hours: float = WARMUP_SUPPRESSION_HOURS,
) -> dict[M6_1_2CohortKind, M6_2AnchorLatencyTrajectory]:
    """Reduce the per-cohort sequence of snapshots into trajectory entities,
    applying the round-8 B4 + C1 amendments.

    Per cohort:

    1. **C1 warmup drop**: snapshots with
       ``sweep_hour_mark < warmup_suppression_hours`` are dropped from the
       spread computation (cold-start transient suppression).
    2. **Insufficient post-warmup snapshots** (``len(post_warmup) < 2``):
       set ``insufficient_post_warmup_snapshots=True``,
       ``max_minus_min_wall_p50_ms=0.0``, ``latency_drift_warning=False``.
       Validate-mode start+end trajectories naturally land here.
    3. **B2 + B4 pooled-CI threshold**: ``latency_drift_warning=True`` iff
       ``spread > pooled_ci_half_width(baseline_ci, snapshot_ci, floor_ms,
       floor_fraction * baseline_p50_ms)`` where ``snapshot_ci`` is the 95%
       normal-approximation CI over the *post-warmup* ``wall_p50_ms``
       samples.

    The pre-warmup snapshots are retained in the persisted ``snapshots``
    list (the artifact-narrative reader can still see the cold-start
    p50/p95/p99 row) — only the drift computation excludes them.
    """
    out: dict[M6_1_2CohortKind, M6_2AnchorLatencyTrajectory] = {}
    for cohort, snapshots in snapshots_by_cohort.items():
        post_warmup = [s for s in snapshots if s.sweep_hour_mark >= warmup_suppression_hours]
        if len(post_warmup) < 2:
            out[cohort] = M6_2AnchorLatencyTrajectory(
                cohort=cohort,
                snapshots=list(snapshots),
                max_minus_min_wall_p50_ms=0.0,
                latency_drift_warning=False,
                insufficient_post_warmup_snapshots=True,
            )
            continue
        p50s = [s.wall_p50_ms for s in post_warmup]
        spread = max(p50s) - min(p50s)
        threshold = pooled_ci_half_width(
            m6_1_3_baseline_ci_half_width,
            _snapshot_ci_half_width(post_warmup),
            baseline_p50_ms=baseline_p50_ms,
            floor_ms=floor_ms,
            floor_fraction=floor_fraction,
        )
        out[cohort] = M6_2AnchorLatencyTrajectory(
            cohort=cohort,
            snapshots=list(snapshots),
            max_minus_min_wall_p50_ms=spread,
            latency_drift_warning=spread > threshold,
            insufficient_post_warmup_snapshots=False,
        )
    return out


def compute_insufficient_snapshots_header_fired(
    trajectories: dict[M6_1_2CohortKind, M6_2AnchorLatencyTrajectory],
) -> bool:
    """C1 soft-diagnostic header rule: fires when any cohort carries
    ``insufficient_post_warmup_snapshots=True``.

    Distinct from SC-016 ``intra_sweep_latency_drift`` (which fires on
    actual measured drift); this one signals that the trajectory's drift
    verdict couldn't be evaluated for at least one cohort because too few
    post-warmup snapshots were collected. NOT publish-blocking.
    """
    return any(t.insufficient_post_warmup_snapshots for t in trajectories.values())


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
