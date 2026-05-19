"""M6.1.3 — between-run variance + Phase B trigger unit tests (T032).

Exercises :mod:`vllm_grpc_bench.m6_1_3_variance` against the contract
scenarios in ``contracts/artifact-schema.md`` variance section +
``contracts/classifier.md`` outer-override section + FR-024 / FR-025 /
FR-026 / FR-027 / FR-043 / FR-044 + round-2 Q3:

* ``compute_between_run_variance`` shape — keyed by (cell, cohort) with
  ``M6_1_3BetweenRunVarianceCell(mean_of_means_ms, stddev_of_means_ms,
  n_runs)``.
* Cohort-unhealthy drop (FR-027): a cohort with 0 successes in 1 of N
  runs has ``n_runs == N - 1``.
* Cohort-unhealthy null-at-3+-failures (FR-027): emits ``None``
  ``mean_of_means_ms`` / ``stddev_of_means_ms`` once ≥ 3 failures.
* ``compute_phase_b_trigger`` fires on ``inconclusive_high_variance``
  cells; emits empty trigger list on clean data.
* Variance section suppressed (FR-025): ``should_render_variance_section``
  returns False below 3 runs.
"""

from __future__ import annotations

from typing import cast

from vllm_grpc_bench.m6_1_1_types import PerSegmentAggregate
from vllm_grpc_bench.m6_1_2_types import M6_1_2CohortKind
from vllm_grpc_bench.m6_1_3_reporter import M6_1_3CellMeasurement
from vllm_grpc_bench.m6_1_3_types import (
    M6_1_3BetweenRunVarianceCell,
)
from vllm_grpc_bench.m6_1_3_variance import (
    compute_between_run_variance,
    compute_cell_ci_halfwidth_ms,
    compute_phase_b_trigger,
    reduce_cell_variance,
    should_fire_inconclusive_high_variance,
    should_render_variance_section,
)

# --- Test fixture builders --------------------------------------------------


def _empty_per_segment() -> PerSegmentAggregate:
    """Minimal PerSegmentAggregate for fixture measurements (variance
    compute doesn't consume any per_segment fields; only the cell
    identity + engine_ttft_ms_mean + n_successes matter)."""
    return PerSegmentAggregate(
        seg_ab_ms_mean=0.0,
        seg_ab_ms_ci_half_width=0.0,
        seg_bc_ms_mean=0.0,
        seg_bc_ms_ci_half_width=0.0,
        seg_cd_ms_mean=0.0,
        seg_cd_ms_ci_half_width=0.0,
        n_samples=10,
    )


def _make_measurement(
    *,
    path: str = "chat_stream",
    concurrency: int = 1,
    cohort: M6_1_2CohortKind = "rest_https_edge",
    engine_ttft_ms_mean: float | None = 50.0,
    n_successes: int = 10,
) -> M6_1_3CellMeasurement:
    return M6_1_3CellMeasurement(
        path=path,
        concurrency=concurrency,
        cohort=cohort,
        n_attempts=10,
        n_successes=n_successes,
        wall_clock_ms_mean=engine_ttft_ms_mean,
        engine_ttft_ms_mean=engine_ttft_ms_mean,
        top_failure_reasons={},
        per_segment=_empty_per_segment() if n_successes > 0 else None,
    )


def _build_phase_1_runs(
    *,
    n_runs: int,
    per_run_per_cohort_ttft: list[dict[M6_1_2CohortKind, float | None]],
    cell_path: str = "chat_stream",
    concurrency: int = 1,
) -> list[list[M6_1_3CellMeasurement]]:
    """Build a phase_1_runs list with per-run per-cohort TTFT values.

    ``per_run_per_cohort_ttft[run_idx][cohort]`` is the TTFT (or
    ``None`` to simulate cohort failure in that run). Length must match
    ``n_runs``.
    """
    assert len(per_run_per_cohort_ttft) == n_runs
    runs: list[list[M6_1_3CellMeasurement]] = []
    for ttft_per_cohort in per_run_per_cohort_ttft:
        per_run: list[M6_1_3CellMeasurement] = []
        for cohort, ttft in ttft_per_cohort.items():
            n_successes = 0 if ttft is None else 10
            per_run.append(
                _make_measurement(
                    path=cell_path,
                    concurrency=concurrency,
                    cohort=cohort,
                    engine_ttft_ms_mean=ttft,
                    n_successes=n_successes,
                )
            )
        runs.append(per_run)
    return runs


# --- compute_between_run_variance shape -------------------------------------


def test_compute_between_run_variance_shape() -> None:
    """FR-024: returns ``{cell_id: {cohort: M6_1_3BetweenRunVarianceCell}}``
    keyed by cell_id then cohort with mean_of_means + stddev_of_means +
    n_runs."""
    phase_1_runs = _build_phase_1_runs(
        n_runs=5,
        per_run_per_cohort_ttft=[
            {"rest_https_edge": 50.0, "default_grpc": 48.0},
            {"rest_https_edge": 51.0, "default_grpc": 48.5},
            {"rest_https_edge": 50.5, "default_grpc": 48.2},
            {"rest_https_edge": 50.2, "default_grpc": 48.1},
            {"rest_https_edge": 50.8, "default_grpc": 48.3},
        ],
    )
    variance = compute_between_run_variance(phase_1_runs)
    assert "chat_stream_c1" in variance
    cell = variance["chat_stream_c1"]
    assert "rest_https_edge" in cell
    assert "default_grpc" in cell

    rest = cell["rest_https_edge"]
    assert isinstance(rest, M6_1_3BetweenRunVarianceCell)
    assert rest.n_runs == 5
    assert rest.mean_of_means_ms is not None
    assert abs(rest.mean_of_means_ms - 50.5) < 0.1
    assert rest.stddev_of_means_ms is not None
    assert rest.stddev_of_means_ms > 0


# --- FR-027 cohort-unhealthy drop -------------------------------------------


def test_cohort_unhealthy_drop_per_run() -> None:
    """FR-027: a cohort with 0 successful RPCs in 1 of 5 runs has its
    contribution dropped — ``n_runs == 4`` for that cell × cohort."""
    phase_1_runs = _build_phase_1_runs(
        n_runs=5,
        per_run_per_cohort_ttft=[
            {"rest_https_edge": 50.0, "default_grpc": 48.0},
            {"rest_https_edge": 51.0, "default_grpc": None},  # default_grpc fails
            {"rest_https_edge": 50.5, "default_grpc": 48.2},
            {"rest_https_edge": 50.2, "default_grpc": 48.1},
            {"rest_https_edge": 50.8, "default_grpc": 48.3},
        ],
    )
    variance = compute_between_run_variance(phase_1_runs)
    cell = variance["chat_stream_c1"]
    # default_grpc only contributed 4 runs.
    assert cell["default_grpc"].n_runs == 4
    # rest_https_edge unaffected.
    assert cell["rest_https_edge"].n_runs == 5
    # And the means/stddev for default_grpc are still computed from 4 runs.
    assert cell["default_grpc"].mean_of_means_ms is not None
    assert cell["default_grpc"].stddev_of_means_ms is not None


def test_cohort_unhealthy_null_at_3_plus_failures() -> None:
    """FR-027: a cohort with 0 successful RPCs in 3+ of 5 runs has
    ``mean_of_means_ms`` / ``stddev_of_means_ms`` emitted as ``None``."""
    phase_1_runs = _build_phase_1_runs(
        n_runs=5,
        per_run_per_cohort_ttft=[
            {"rest_https_edge": 50.0, "default_grpc": None},
            {"rest_https_edge": 51.0, "default_grpc": None},
            {"rest_https_edge": 50.5, "default_grpc": None},  # 3rd failure
            {"rest_https_edge": 50.2, "default_grpc": 48.1},
            {"rest_https_edge": 50.8, "default_grpc": 48.3},
        ],
    )
    variance = compute_between_run_variance(phase_1_runs)
    cell = variance["chat_stream_c1"]
    default_grpc = cell["default_grpc"]
    assert default_grpc.mean_of_means_ms is None
    assert default_grpc.stddev_of_means_ms is None
    assert default_grpc.n_runs == 2  # Only 2 healthy
    # rest_https_edge unaffected.
    assert cell["rest_https_edge"].mean_of_means_ms is not None


# --- should_fire_inconclusive_high_variance (FR-026 + round-2 Q3 unified) ---


def test_should_fire_inconclusive_high_variance_above_threshold() -> None:
    """FR-026: stddev_of_means_ms = 8.0, ci_halfwidth_ms = 4.0,
    threshold = 1.0 → 8 > 1 × 4 → True."""
    variance = M6_1_3BetweenRunVarianceCell(
        mean_of_means_ms=42.0,
        stddev_of_means_ms=8.0,
        n_runs=5,
    )
    assert (
        should_fire_inconclusive_high_variance(variance, cell_ci_halfwidth_ms=4.0, threshold=1.0)
        is True
    )


def test_should_fire_inconclusive_high_variance_below_threshold() -> None:
    """FR-026: low between-run stddev (well under threshold × CI) → False."""
    variance = M6_1_3BetweenRunVarianceCell(
        mean_of_means_ms=42.0,
        stddev_of_means_ms=2.0,
        n_runs=5,
    )
    assert (
        should_fire_inconclusive_high_variance(variance, cell_ci_halfwidth_ms=4.0, threshold=1.0)
        is False
    )


def test_should_fire_inconclusive_high_variance_handles_none() -> None:
    """When the variance estimate is unavailable (FR-027 cohort_unhealthy
    drop produces ``stddev_of_means_ms = None``), the gate returns
    False (no signal to act on)."""
    variance = M6_1_3BetweenRunVarianceCell(
        mean_of_means_ms=None,
        stddev_of_means_ms=None,
        n_runs=1,
    )
    assert (
        should_fire_inconclusive_high_variance(variance, cell_ci_halfwidth_ms=4.0, threshold=1.0)
        is False
    )


def test_should_fire_inconclusive_high_variance_handles_zero_ci() -> None:
    """Degenerate cell with zero within-run CI half-width: the gate
    returns False (no meaningful comparison)."""
    variance = M6_1_3BetweenRunVarianceCell(
        mean_of_means_ms=42.0,
        stddev_of_means_ms=8.0,
        n_runs=5,
    )
    assert (
        should_fire_inconclusive_high_variance(variance, cell_ci_halfwidth_ms=0.0, threshold=1.0)
        is False
    )


# --- compute_phase_b_trigger (FR-043 + FR-044 + round-2 Q3) ----------------


def test_phase_b_trigger_fires_on_high_variance() -> None:
    """A cell carrying ``inconclusive_high_variance`` enters the
    Phase B trigger set; the verdict has ``required=True`` and lists the
    trigger cells alphabetically."""
    classifications = {
        "chat_stream_c1": "engine_compute_variation",
        "chat_stream_c4": "inconclusive_high_variance (proxy_egress_dominated)",
        "chat_stream_c8": "inconclusive_high_variance (engine_compute_variation)",
        "embed_c1": "channel_dependent_batching",
    }
    verdict = compute_phase_b_trigger(classifications, variance_section_suppressed=False)
    assert verdict.required is True
    assert verdict.trigger_cells == ["chat_stream_c4", "chat_stream_c8"]
    assert verdict.variance_section_suppressed is False


def test_phase_b_trigger_absent_on_clean_data() -> None:
    """No cell carries ``inconclusive_high_variance`` → ``required=False``
    + empty trigger list."""
    classifications = {
        "chat_stream_c1": "engine_compute_variation",
        "chat_stream_c4": "proxy_egress_dominated",
        "embed_c1": "channel_dependent_batching",
    }
    verdict = compute_phase_b_trigger(classifications, variance_section_suppressed=False)
    assert verdict.required is False
    assert verdict.trigger_cells == []
    assert verdict.variance_section_suppressed is False


def test_phase_b_trigger_suppressed_when_variance_section_suppressed() -> None:
    """FR-044 + FR-025: when the variance section is suppressed (< 3
    runs), the Phase B trigger verdict is unavailable — the reporter
    renders the FR-044 override fallback instead."""
    classifications = {
        "chat_stream_c1": "engine_compute_variation",
    }
    verdict = compute_phase_b_trigger(classifications, variance_section_suppressed=True)
    assert verdict.required is False
    assert verdict.trigger_cells == []
    assert verdict.variance_section_suppressed is True


# --- should_render_variance_section (FR-025) -------------------------------


def test_variance_section_suppressed_below_3_runs() -> None:
    """FR-025: ``should_render_variance_section`` returns True iff
    ``len(phase_1_runs) >= 3``."""
    assert should_render_variance_section([]) is False
    assert should_render_variance_section([[]]) is False
    assert should_render_variance_section([[], []]) is False
    assert should_render_variance_section([[], [], []]) is True
    assert should_render_variance_section([[], [], [], [], []]) is True


def test_variance_compute_still_runs_below_3_runs() -> None:
    """The compute itself produces valid (n_runs, mean, stddev) output
    on a 2-run sweep; only the reporter's ``should_render_variance_section``
    gate suppresses the section. This lets a future tool inspect the
    variance numbers programmatically even on a small sweep."""
    phase_1_runs = _build_phase_1_runs(
        n_runs=2,
        per_run_per_cohort_ttft=[
            {"rest_https_edge": 50.0},
            {"rest_https_edge": 51.0},
        ],
    )
    variance = compute_between_run_variance(phase_1_runs)
    assert "chat_stream_c1" in variance
    assert variance["chat_stream_c1"]["rest_https_edge"].n_runs == 2
    # stddev computed from 2 samples is valid.
    assert variance["chat_stream_c1"]["rest_https_edge"].stddev_of_means_ms is not None


# --- reduce_cell_variance: per-cohort → cell-level collapse ----------------


def test_reduce_cell_variance_picks_max_stddev() -> None:
    """The classifier-facing per-cell variance value is the cohort with
    the largest stddev_of_means (worst-case gate)."""
    per_cohort: dict[M6_1_2CohortKind, M6_1_3BetweenRunVarianceCell] = {
        "rest_https_edge": M6_1_3BetweenRunVarianceCell(
            mean_of_means_ms=50.0, stddev_of_means_ms=2.0, n_runs=5
        ),
        "default_grpc": M6_1_3BetweenRunVarianceCell(
            mean_of_means_ms=48.0, stddev_of_means_ms=8.0, n_runs=5
        ),
        "tuned_grpc_multiplexed": M6_1_3BetweenRunVarianceCell(
            mean_of_means_ms=47.0, stddev_of_means_ms=4.0, n_runs=5
        ),
    }
    reduced = reduce_cell_variance(per_cohort)
    assert reduced is not None
    assert reduced.stddev_of_means_ms == 8.0
    assert reduced.mean_of_means_ms == 48.0


def test_reduce_cell_variance_returns_none_on_all_unhealthy() -> None:
    """When every cohort had ``stddev_of_means_ms = None`` (FR-027
    cohort_unhealthy collapse for all cohorts), the reduced value is
    ``None``."""
    per_cohort: dict[M6_1_2CohortKind, M6_1_3BetweenRunVarianceCell] = {
        cast(M6_1_2CohortKind, "rest_https_edge"): M6_1_3BetweenRunVarianceCell(
            mean_of_means_ms=None, stddev_of_means_ms=None, n_runs=0
        ),
        cast(M6_1_2CohortKind, "default_grpc"): M6_1_3BetweenRunVarianceCell(
            mean_of_means_ms=None, stddev_of_means_ms=None, n_runs=1
        ),
    }
    assert reduce_cell_variance(per_cohort) is None


# --- compute_cell_ci_halfwidth_ms ------------------------------------------


def test_compute_cell_ci_halfwidth_ms_uses_max() -> None:
    """The cell-level CI half-width is the MAX across cohorts (most-
    conservative threshold denominator)."""
    per_cohort: dict[M6_1_2CohortKind, float] = {
        "rest_https_edge": 2.0,
        "default_grpc": 4.0,
        "tuned_grpc_multiplexed": 1.5,
    }
    assert compute_cell_ci_halfwidth_ms(per_cohort) == 4.0


def test_compute_cell_ci_halfwidth_ms_handles_empty() -> None:
    """No cohort has a positive CI estimate → return 0.0 (the gate
    will treat as 'no meaningful comparison')."""
    assert compute_cell_ci_halfwidth_ms({}) == 0.0
    per_cohort: dict[M6_1_2CohortKind, float] = {
        "rest_https_edge": 0.0,
        "default_grpc": 0.0,
    }
    assert compute_cell_ci_halfwidth_ms(per_cohort) == 0.0
