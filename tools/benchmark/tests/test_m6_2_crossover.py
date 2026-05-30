"""T036 — M6.2 protocol crossover unit tests.

Exercises :func:`m6_2_crossover.compute_per_cell_crossover` directly with
synthetic per-cell axis rows + M6.1.3 baseline data. Covers spec round-1 Q3
+ US2 #2 + US2 #3 + validate-mode coarse vocabulary.
"""

from __future__ import annotations

from vllm_grpc_bench.m6_2_crossover import (
    INCONCLUSIVE_VERDICT_LABELS,
    M6_1_3CohortBaseline,
    compute_per_cell_crossover,
    identify_winner_and_second,
    symmetric_mean_in_ci,
)
from vllm_grpc_bench.sweep_types import (
    M6_2_MAX_TOKENS_AXIS,
    M6_2_VALIDATE_MAX_TOKENS_AXIS,
    M6_2MeasurementPoint,
)


def _point(
    *,
    cell_id: str,
    cohort: str,
    max_tokens: int,
    wall_p50_ms: float,
    ci_half: float = 1.0,
) -> M6_2MeasurementPoint:
    return M6_2MeasurementPoint(
        cell_id=cell_id,
        cohort=cohort,  # type: ignore[arg-type]
        max_tokens=max_tokens,
        n_rpcs=20,
        wall_p50_ms=wall_p50_ms,
        wall_p95_ms=wall_p50_ms * 1.5,
        wall_p99_ms=wall_p50_ms * 2.0,
        wall_p50_ms_ci_half_width=ci_half,
        tpot_ms=None,
        seg_ab_ms=None,
        seg_queue_ms=None,
        seg_prefill_ms=None,
        seg_ingress_ms=None,
        seg_egress_ms=None,
        failed_reason=None,
        block_start_utc="2026-05-20T00:00:00Z",
        block_end_utc="2026-05-20T00:00:05Z",
        retry_attempted=False,
        clock_anomaly=False,
        prompt_source="corpus_sharegpt",
        measurement_regime="natural_eos",
        prompt_corpus_idx=0,
    )


# --- symmetric_mean_in_ci predicate ----------------------------------------


def test_symmetric_rule_fires_when_a_mean_in_b_ci() -> None:
    a = _point(cell_id="x", cohort="default_grpc", max_tokens=10, wall_p50_ms=50.0, ci_half=10.0)
    b = _point(
        cell_id="x",
        cohort="rest_https_edge",
        max_tokens=10,
        wall_p50_ms=45.0,  # a's mean 50 is inside b's [35, 55] CI
        ci_half=10.0,
    )
    assert symmetric_mean_in_ci(a, b) is True


def test_symmetric_rule_fires_when_b_mean_in_a_ci_but_not_vice_versa() -> None:
    a = _point(
        cell_id="x",
        cohort="default_grpc",
        max_tokens=10,
        wall_p50_ms=50.0,
        ci_half=20.0,  # wide CI
    )
    b = _point(
        cell_id="x",
        cohort="rest_https_edge",
        max_tokens=10,
        wall_p50_ms=60.0,
        ci_half=1.0,  # tight CI
    )
    # b's mean 60 is inside a's [30, 70] CI; a's mean 50 NOT in b's [59, 61].
    assert symmetric_mean_in_ci(a, b) is True


def test_symmetric_rule_does_not_fire_when_neither_mean_in_other_ci() -> None:
    a = _point(cell_id="x", cohort="default_grpc", max_tokens=10, wall_p50_ms=50.0, ci_half=1.0)
    b = _point(
        cell_id="x",
        cohort="rest_https_edge",
        max_tokens=10,
        wall_p50_ms=100.0,
        ci_half=1.0,
    )
    assert symmetric_mean_in_ci(a, b) is False


def test_symmetric_rule_returns_false_on_block_failure() -> None:
    a = _point(cell_id="x", cohort="default_grpc", max_tokens=10, wall_p50_ms=50.0, ci_half=1.0)
    a_failed = M6_2MeasurementPoint(
        cell_id="x",
        cohort="default_grpc",  # type: ignore[arg-type]
        max_tokens=10,
        n_rpcs=20,
        wall_p50_ms=None,
        wall_p95_ms=None,
        wall_p99_ms=None,
        wall_p50_ms_ci_half_width=None,
        tpot_ms=None,
        seg_ab_ms=None,
        seg_queue_ms=None,
        seg_prefill_ms=None,
        seg_ingress_ms=None,
        seg_egress_ms=None,
        failed_reason="grpc_timeout",
        block_start_utc="2026-05-20T00:00:00Z",
        block_end_utc="2026-05-20T00:00:01Z",
        retry_attempted=False,
        clock_anomaly=False,
        prompt_source="corpus_sharegpt",
        measurement_regime="natural_eos",
        prompt_corpus_idx=0,
    )
    assert symmetric_mean_in_ci(a, a_failed) is False
    assert symmetric_mean_in_ci(a_failed, a) is False


# --- identify_winner_and_second --------------------------------------------


def test_winner_second_identified_by_lowest_p50() -> None:
    baseline = {
        "default_grpc": M6_1_3CohortBaseline(wall_p50_ms=50.0, wall_p50_ms_ci_half_width=1.0),
        "rest_https_edge": M6_1_3CohortBaseline(wall_p50_ms=60.0, wall_p50_ms_ci_half_width=1.0),
        "rest_plain_tcp": M6_1_3CohortBaseline(wall_p50_ms=70.0, wall_p50_ms_ci_half_width=1.0),
    }
    result = identify_winner_and_second("chat_stream_c1", baseline)  # type: ignore[arg-type]
    assert result == ("default_grpc", "rest_https_edge")


def test_winner_second_returns_none_when_only_one_cohort() -> None:
    baseline = {
        "default_grpc": M6_1_3CohortBaseline(wall_p50_ms=50.0, wall_p50_ms_ci_half_width=1.0),
    }
    result = identify_winner_and_second("chat_stream_c1", baseline)  # type: ignore[arg-type]
    assert result is None


# --- compute_per_cell_crossover ---------------------------------------------


def _make_axis_rows(
    *,
    cell_id: str,
    winner: str,
    second: str,
    winner_per_cap: dict[int, tuple[float, float]],
    second_per_cap: dict[int, tuple[float, float]],
) -> dict[str, dict[str, dict[int, M6_2MeasurementPoint]]]:
    """Build a per_cell axis-rows dict for one cell with two cohorts."""
    return {
        cell_id: {
            winner: {
                cap: _point(
                    cell_id=cell_id,
                    cohort=winner,
                    max_tokens=cap,
                    wall_p50_ms=p50,
                    ci_half=ci,
                )
                for cap, (p50, ci) in winner_per_cap.items()
            },
            second: {
                cap: _point(
                    cell_id=cell_id,
                    cohort=second,
                    max_tokens=cap,
                    wall_p50_ms=p50,
                    ci_half=ci,
                )
                for cap, (p50, ci) in second_per_cap.items()
            },
        }
    }


def test_inconclusive_base_verdict_emits_none_with_us2_q2_evidence() -> None:
    rows = _make_axis_rows(
        cell_id="chat_stream_c1",
        winner="default_grpc",
        second="rest_https_edge",
        winner_per_cap={cap: (50.0, 1.0) for cap in M6_2_MAX_TOKENS_AXIS},
        second_per_cap={cap: (60.0, 1.0) for cap in M6_2_MAX_TOKENS_AXIS},
    )
    baseline = {
        "chat_stream_c1": {
            "default_grpc": M6_1_3CohortBaseline(50.0, 1.0),
            "rest_https_edge": M6_1_3CohortBaseline(60.0, 1.0),
        }
    }
    verdicts = {"chat_stream_c1": "inconclusive"}
    [result] = compute_per_cell_crossover(rows, baseline, verdicts, sweep_mode="publish")  # type: ignore[arg-type]
    assert result.crossover_max_tokens is None
    assert "inconclusive at the M6.1.3 baseline" in result.crossover_evidence
    assert result.m6_1_3_winner_cohort is None
    assert result.m6_1_3_second_cohort is None


def test_inconclusive_high_variance_wrapper_also_short_circuits() -> None:
    """``inconclusive_high_variance(<inner>)`` should be treated the same as
    plain ``inconclusive`` per spec round-1 Q3 (the high-variance outer
    wrapper means attribution is dominated by between-run noise)."""
    rows = _make_axis_rows(
        cell_id="chat_stream_c1",
        winner="default_grpc",
        second="rest_https_edge",
        winner_per_cap={cap: (50.0, 1.0) for cap in M6_2_MAX_TOKENS_AXIS},
        second_per_cap={cap: (60.0, 1.0) for cap in M6_2_MAX_TOKENS_AXIS},
    )
    baseline = {
        "chat_stream_c1": {
            "default_grpc": M6_1_3CohortBaseline(50.0, 1.0),
            "rest_https_edge": M6_1_3CohortBaseline(60.0, 1.0),
        }
    }
    verdicts = {"chat_stream_c1": "inconclusive_high_variance(channel_dependent_batching)"}
    [result] = compute_per_cell_crossover(rows, baseline, verdicts, sweep_mode="publish")  # type: ignore[arg-type]
    assert result.crossover_max_tokens is None
    assert "inconclusive" in result.crossover_evidence.lower()


def test_crossover_detected_at_interior_cap() -> None:
    """Winner + second separated at the null-anchor caps; CIs overlap at an
    interior cap → crossover emitted at that cap."""
    rows = _make_axis_rows(
        cell_id="chat_stream_c4",
        winner="default_grpc",
        second="rest_https_edge",
        winner_per_cap={
            10: (50.0, 1.0),
            50: (60.0, 1.0),
            256: (200.0, 5.0),
            512: (400.0, 10.0),
            1024: (800.0, 20.0),
            2048: (1600.0, 40.0),
        },
        second_per_cap={
            10: (80.0, 1.0),
            50: (90.0, 1.0),
            256: (210.0, 5.0),  # within winner's CI ([195, 205])? 210 NOT in [195, 205]
            # → no crossover at 256
            512: (405.0, 10.0),  # within winner's [390, 410]? 405 IN [390, 410] → crossover here
            1024: (810.0, 20.0),
            2048: (1610.0, 40.0),
        },
    )
    baseline = {
        "chat_stream_c4": {
            "default_grpc": M6_1_3CohortBaseline(50.0, 1.0),
            "rest_https_edge": M6_1_3CohortBaseline(80.0, 1.0),
        }
    }
    verdicts = {"chat_stream_c4": "channel_dependent_batching"}
    [result] = compute_per_cell_crossover(rows, baseline, verdicts, sweep_mode="publish")  # type: ignore[arg-type]
    assert result.crossover_max_tokens == 512
    assert result.m6_1_3_winner_cohort == "default_grpc"
    assert result.m6_1_3_second_cohort == "rest_https_edge"
    assert "overlaps" in result.crossover_evidence


def test_crossover_at_first_axis_point_emits_us2_q3_evidence() -> None:
    """If the symmetric rule fires at the FIRST axis point (max_tokens=10),
    the evidence string is the canonical US2 #3 "M6.1.3 verdict not robust"
    text, NOT the per-row overlap details."""
    rows = _make_axis_rows(
        cell_id="chat_stream_c4",
        winner="default_grpc",
        second="rest_https_edge",
        winner_per_cap={
            cap: (50.0, 10.0) for cap in M6_2_MAX_TOKENS_AXIS
        },  # wide CI → overlap from start
        second_per_cap={cap: (55.0, 10.0) for cap in M6_2_MAX_TOKENS_AXIS},
    )
    baseline = {
        "chat_stream_c4": {
            "default_grpc": M6_1_3CohortBaseline(50.0, 1.0),
            "rest_https_edge": M6_1_3CohortBaseline(55.0, 1.0),
        }
    }
    verdicts = {"chat_stream_c4": "channel_dependent_batching"}
    [result] = compute_per_cell_crossover(rows, baseline, verdicts, sweep_mode="publish")  # type: ignore[arg-type]
    assert result.crossover_max_tokens == 10
    assert result.crossover_evidence == "M6.1.3 verdict not robust to M6.2 resampling"


def test_crossover_never_fires_emits_survives_evidence() -> None:
    rows = _make_axis_rows(
        cell_id="chat_stream_c4",
        winner="default_grpc",
        second="rest_https_edge",
        winner_per_cap={cap: (50.0, 1.0) for cap in M6_2_MAX_TOKENS_AXIS},
        second_per_cap={cap: (200.0, 1.0) for cap in M6_2_MAX_TOKENS_AXIS},
    )
    baseline = {
        "chat_stream_c4": {
            "default_grpc": M6_1_3CohortBaseline(50.0, 1.0),
            "rest_https_edge": M6_1_3CohortBaseline(200.0, 1.0),
        }
    }
    verdicts = {"chat_stream_c4": "channel_dependent_batching"}
    [result] = compute_per_cell_crossover(rows, baseline, verdicts, sweep_mode="publish")  # type: ignore[arg-type]
    assert result.crossover_max_tokens is None
    assert result.crossover_evidence == "verdict survives across the axis"
    assert result.m6_1_3_winner_cohort == "default_grpc"
    assert result.m6_1_3_second_cohort == "rest_https_edge"


def test_validate_mode_uses_coarse_axis() -> None:
    """Validate mode walks the 3-point subset ``{10, 50, 2048}`` — interior
    caps unobservable. The crossover_max_tokens vocabulary naturally follows
    the subset."""
    rows = _make_axis_rows(
        cell_id="chat_stream_c4",
        winner="default_grpc",
        second="rest_https_edge",
        winner_per_cap={cap: (50.0, 1.0) for cap in M6_2_VALIDATE_MAX_TOKENS_AXIS},
        second_per_cap={
            10: (80.0, 1.0),
            50: (90.0, 1.0),
            2048: (1600.0, 100.0),  # wide CI → overlap at 2048
        },
    )
    # Wait — winner_per_cap at 2048 is 50.0 but second is 1600. Need CIs to
    # produce overlap: rewrite winner's 2048 value.
    rows["chat_stream_c4"]["default_grpc"][2048] = _point(
        cell_id="chat_stream_c4",
        cohort="default_grpc",
        max_tokens=2048,
        wall_p50_ms=1550.0,
        ci_half=100.0,
    )
    baseline = {
        "chat_stream_c4": {
            "default_grpc": M6_1_3CohortBaseline(50.0, 1.0),
            "rest_https_edge": M6_1_3CohortBaseline(80.0, 1.0),
        }
    }
    verdicts = {"chat_stream_c4": "channel_dependent_batching"}
    [result] = compute_per_cell_crossover(rows, baseline, verdicts, sweep_mode="validate")  # type: ignore[arg-type]
    assert result.crossover_max_tokens == 2048


def test_validate_mode_interior_caps_invisible() -> None:
    """If the only overlap is at an interior cap (e.g. 512), validate mode
    can't see it — the result is ``crossover_max_tokens=None`` since the
    validate axis skips 256 / 512 / 1024."""
    rows = _make_axis_rows(
        cell_id="chat_stream_c4",
        winner="default_grpc",
        second="rest_https_edge",
        winner_per_cap={
            10: (50.0, 1.0),
            50: (60.0, 1.0),
            2048: (1600.0, 1.0),
        },
        second_per_cap={
            10: (200.0, 1.0),
            50: (210.0, 1.0),
            2048: (1800.0, 1.0),  # separated at 2048
        },
    )
    baseline = {
        "chat_stream_c4": {
            "default_grpc": M6_1_3CohortBaseline(50.0, 1.0),
            "rest_https_edge": M6_1_3CohortBaseline(200.0, 1.0),
        }
    }
    verdicts = {"chat_stream_c4": "channel_dependent_batching"}
    [result] = compute_per_cell_crossover(rows, baseline, verdicts, sweep_mode="validate")  # type: ignore[arg-type]
    assert result.crossover_max_tokens is None
    assert result.crossover_evidence == "verdict survives across the axis"


def test_baseline_with_fewer_than_two_cohorts_emits_skip_evidence() -> None:
    rows = _make_axis_rows(
        cell_id="chat_stream_c1",
        winner="default_grpc",
        second="rest_https_edge",
        winner_per_cap={cap: (50.0, 1.0) for cap in M6_2_MAX_TOKENS_AXIS},
        second_per_cap={cap: (60.0, 1.0) for cap in M6_2_MAX_TOKENS_AXIS},
    )
    baseline = {
        "chat_stream_c1": {
            "default_grpc": M6_1_3CohortBaseline(50.0, 1.0),
        }
    }
    verdicts = {"chat_stream_c1": "channel_dependent_batching"}
    [result] = compute_per_cell_crossover(rows, baseline, verdicts, sweep_mode="publish")  # type: ignore[arg-type]
    assert result.crossover_max_tokens is None
    assert "did not publish" in result.crossover_evidence


def test_inconclusive_verdict_labels_frozen_set() -> None:
    """Regression: ``"inconclusive"`` is the canonical label; the
    high-variance wrapper is matched via prefix in ``_is_inconclusive_verdict``."""
    assert "inconclusive" in INCONCLUSIVE_VERDICT_LABELS
