"""Tests for m6_supersede baseline loader + cohort mapping (T023)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from vllm_grpc_bench.m6_supersede import (
    M5_2BaselineMissingCellError,
    classify_cell,
    get_m5_2_winner_delta,
    load_and_validate_m5_2_baseline,
    map_m6_grpc_cohort_to_m5_2_lookup,
    snapshot_m5_2_winner_deltas,
)
from vllm_grpc_bench.m6_types import (
    EngineCostAggregate,
    M6Cell,
    M6CohortKind,
    M6PerCohortAggregate,
)

# --- map_m6_grpc_cohort_to_m5_2_lookup (R-6) ---------------------------------


def test_cohort_mapping_c1_to_tuned_grpc() -> None:
    assert map_m6_grpc_cohort_to_m5_2_lookup(1) == "tuned_grpc"


def test_cohort_mapping_c4_to_tuned_grpc_multiplexed() -> None:
    assert map_m6_grpc_cohort_to_m5_2_lookup(4) == "tuned_grpc_multiplexed"


def test_cohort_mapping_c8_to_tuned_grpc_multiplexed() -> None:
    assert map_m6_grpc_cohort_to_m5_2_lookup(8) == "tuned_grpc_multiplexed"


# --- load_and_validate_m5_2_baseline -----------------------------------------


def _make_baseline_row(
    path: str, hidden_size: int, concurrency: int, grpc_cohort: str, verdict: str = "no_winner"
) -> dict[str, object]:
    return {
        "path": path,
        "hidden_size": hidden_size,
        "concurrency": concurrency,
        "grpc_cohort": grpc_cohort,
        "rest_cohort": "rest_https_edge",
        "delta_median_ms": -10.5,
        "ci_lower_ms": -12.0,
        "ci_upper_ms": -9.0,
        "verdict": verdict,
    }


def _make_complete_baseline() -> dict[str, object]:
    """Six rows covering all M6 cells, using R-6 cohort naming."""
    verdicts = []
    for path_ in ("embed", "chat_stream"):
        # c=1 uses tuned_grpc
        verdicts.append(_make_baseline_row(path_, 4096, 1, "tuned_grpc"))
        # c=4 and c=8 use tuned_grpc_multiplexed
        verdicts.append(_make_baseline_row(path_, 4096, 4, "tuned_grpc_multiplexed"))
        verdicts.append(_make_baseline_row(path_, 4096, 8, "tuned_grpc_multiplexed"))
    return {"protocol_comparison_verdicts": verdicts}


def test_load_complete_baseline_succeeds(tmp_path: Path) -> None:
    p = tmp_path / "baseline.json"
    p.write_text(json.dumps(_make_complete_baseline()))
    data = load_and_validate_m5_2_baseline(p)
    assert "protocol_comparison_verdicts" in data


def test_load_missing_file_raises_filenotfound(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_and_validate_m5_2_baseline(tmp_path / "missing.json")


def test_load_missing_cell_raises_named_error(tmp_path: Path) -> None:
    baseline = _make_complete_baseline()
    # Drop the embed × c=1 row.
    verdicts_list = baseline["protocol_comparison_verdicts"]
    assert isinstance(verdicts_list, list)
    verdicts_list[:] = [
        r for r in verdicts_list if not (r["path"] == "embed" and r["concurrency"] == 1)
    ]
    p = tmp_path / "baseline.json"
    p.write_text(json.dumps(baseline))
    with pytest.raises(M5_2BaselineMissingCellError) as exc_info:
        load_and_validate_m5_2_baseline(p)
    err = exc_info.value
    assert err.cell == ("embed", 4096, 1)
    assert err.grpc_cohort == "tuned_grpc"


def test_load_missing_protocol_comparison_key_raises(tmp_path: Path) -> None:
    p = tmp_path / "baseline.json"
    p.write_text(json.dumps({"cohorts": []}))
    with pytest.raises(M5_2BaselineMissingCellError):
        load_and_validate_m5_2_baseline(p)


# --- get_m5_2_winner_delta ---------------------------------------------------


def test_get_winner_delta_returns_abs_magnitude() -> None:
    baseline = _make_complete_baseline()
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=1)
    # Pre-existing row has verdict "no_winner" — returns None.
    delta, verdict = get_m5_2_winner_delta(baseline, cell)
    assert delta is None
    assert verdict == "no_winner"


def test_get_winner_delta_for_tuned_grpc_recommend() -> None:
    baseline = _make_complete_baseline()
    verdicts_list = baseline["protocol_comparison_verdicts"]
    assert isinstance(verdicts_list, list)
    # Set the embed × c=1 row's verdict to a tuned_grpc_recommend with magnitude 51.0.
    for row in verdicts_list:
        if (
            row["path"] == "embed"
            and row["concurrency"] == 1
            and row["grpc_cohort"] == "tuned_grpc"
        ):
            row["verdict"] = "tuned_grpc_recommend"
            row["delta_median_ms"] = -51.0
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=1)
    delta, verdict = get_m5_2_winner_delta(baseline, cell)
    assert delta == 51.0
    assert verdict == "tuned_grpc_recommend"


# --- classify_cell (T034, T035) ----------------------------------------------


def _make_per_cohort_aggregate(
    cohort: M6CohortKind,
    mean_ms: float,
    ci_half_width_ms: float,
    *,
    n_successes: int = 100,
    engine_forward_mean_ms: float | None = None,
    engine_ttft_mean_ms: float | None = None,
    engine_tpot_mean_ms: float | None = None,
) -> M6PerCohortAggregate:
    return M6PerCohortAggregate(
        cohort=cohort,
        n_attempted=100,
        n_successes=n_successes,
        failure_count=100 - n_successes,
        classifier_metric_mean_ms=mean_ms,
        classifier_metric_ci_half_width_ms=ci_half_width_ms,
        total_wall_clock_mean_ms=mean_ms,
        total_wall_clock_ci_half_width_ms=ci_half_width_ms,
        engine_cost_mean=EngineCostAggregate(
            engine_forward_mean_ms=engine_forward_mean_ms,
            engine_ttft_mean_ms=engine_ttft_mean_ms,
            engine_tpot_mean_ms=engine_tpot_mean_ms,
        ),
    )


def _baseline_with(
    path: str,
    c: int,
    grpc_cohort: str,
    verdict: str,
    delta_median_ms: float,
) -> dict[str, object]:
    """Build a 6-cell baseline whose embed × c=1 (or matching path/c) row
    carries the given verdict + delta, with all other rows defaulting to
    no_winner.
    """
    base = _make_complete_baseline()
    verdicts_list = base["protocol_comparison_verdicts"]
    assert isinstance(verdicts_list, list)
    for row in verdicts_list:
        if row["path"] == path and row["concurrency"] == c and row["grpc_cohort"] == grpc_cohort:
            row["verdict"] = verdict
            row["delta_median_ms"] = delta_median_ms
    return base


def test_classify_cell_incomplete_branch() -> None:
    """FR-023: any cohort < 80 successes → cell_incomplete."""
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=1)
    per_cohort: dict[M6CohortKind, M6PerCohortAggregate] = {
        "rest_https_edge": _make_per_cohort_aggregate(
            "rest_https_edge", 100.0, 2.0, engine_forward_mean_ms=12.0
        ),
        "default_grpc": _make_per_cohort_aggregate(
            "default_grpc", 95.0, 2.0, n_successes=79, engine_forward_mean_ms=12.0
        ),
        "tuned_grpc_multiplexed": _make_per_cohort_aggregate(
            "tuned_grpc_multiplexed", 90.0, 2.0, engine_forward_mean_ms=12.0
        ),
    }
    record = classify_cell(cell, per_cohort, _make_complete_baseline())
    assert record.classification == "cell_incomplete"


def test_classify_cell_verdict_survives_branch() -> None:
    """Non-overlapping CIs + same direction as M5.2 → verdict_survives."""
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=1)
    # M5.2 says tuned_grpc wins by 51 ms (gRPC wins direction).
    baseline = _baseline_with("embed", 1, "tuned_grpc", "tuned_grpc_recommend", -51.0)
    per_cohort: dict[M6CohortKind, M6PerCohortAggregate] = {
        "rest_https_edge": _make_per_cohort_aggregate(
            "rest_https_edge", 150.0, 5.0, engine_forward_mean_ms=12.0
        ),
        "default_grpc": _make_per_cohort_aggregate(
            "default_grpc", 99.0, 5.0, engine_forward_mean_ms=12.0
        ),
        # gRPC is faster (grpc_wins). Non-overlapping CIs vs rest_https_edge.
        "tuned_grpc_multiplexed": _make_per_cohort_aggregate(
            "tuned_grpc_multiplexed", 100.0, 5.0, engine_forward_mean_ms=12.0
        ),
    }
    record = classify_cell(cell, per_cohort, baseline)
    assert record.classification == "verdict_survives"
    assert record.m5_2_winner_delta_ms == 51.0
    assert record.m5_2_winner_direction == "grpc_wins"


def test_classify_cell_verdict_changed_branch() -> None:
    """Non-overlapping CIs + opposite direction to M5.2 → verdict_changed."""
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=1)
    # M5.2 says tuned_grpc wins. M6 has REST winning.
    baseline = _baseline_with("embed", 1, "tuned_grpc", "tuned_grpc_recommend", -51.0)
    per_cohort: dict[M6CohortKind, M6PerCohortAggregate] = {
        # REST is faster — opposite of M5.2's gRPC win direction.
        "rest_https_edge": _make_per_cohort_aggregate(
            "rest_https_edge", 100.0, 5.0, engine_forward_mean_ms=12.0
        ),
        "default_grpc": _make_per_cohort_aggregate(
            "default_grpc", 199.0, 5.0, engine_forward_mean_ms=12.0
        ),
        "tuned_grpc_multiplexed": _make_per_cohort_aggregate(
            "tuned_grpc_multiplexed", 150.0, 5.0, engine_forward_mean_ms=12.0
        ),
    }
    record = classify_cell(cell, per_cohort, baseline)
    assert record.classification == "verdict_changed"


def test_classify_cell_buried_by_engine_branch() -> None:
    """Overlapping CIs + engine_cost ≥ 5× M5.2 winner delta → verdict_buried_by_engine.

    M5.2 winner delta is 51 ms; 5× threshold = 255 ms. Engine cost mean 260 ms
    crosses that threshold AND CIs overlap.
    """
    cell = M6Cell(path="chat_stream", hidden_size=4096, concurrency=1)
    baseline = _baseline_with("chat_stream", 1, "tuned_grpc", "tuned_grpc_recommend", -51.0)
    per_cohort: dict[M6CohortKind, M6PerCohortAggregate] = {
        "rest_https_edge": _make_per_cohort_aggregate(
            "rest_https_edge", 300.0, 100.0, engine_ttft_mean_ms=260.0
        ),
        "default_grpc": _make_per_cohort_aggregate(
            "default_grpc", 290.0, 100.0, engine_ttft_mean_ms=260.0
        ),
        "tuned_grpc_multiplexed": _make_per_cohort_aggregate(
            "tuned_grpc_multiplexed", 295.0, 100.0, engine_ttft_mean_ms=260.0
        ),
    }
    record = classify_cell(cell, per_cohort, baseline)
    assert record.classification == "verdict_buried_by_engine"
    assert record.engine_cost_mean_ms >= 5 * 51.0


def test_classify_cell_no_winner_at_n100_overlapping_cis_with_small_engine() -> None:
    """Overlapping CIs AND engine_cost < 5× M5.2 winner delta → no_winner_at_n100."""
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=1)
    baseline = _baseline_with("embed", 1, "tuned_grpc", "tuned_grpc_recommend", -51.0)
    per_cohort: dict[M6CohortKind, M6PerCohortAggregate] = {
        "rest_https_edge": _make_per_cohort_aggregate(
            "rest_https_edge", 200.0, 50.0, engine_forward_mean_ms=12.0
        ),
        "default_grpc": _make_per_cohort_aggregate(
            "default_grpc", 195.0, 50.0, engine_forward_mean_ms=12.0
        ),
        "tuned_grpc_multiplexed": _make_per_cohort_aggregate(
            "tuned_grpc_multiplexed", 198.0, 50.0, engine_forward_mean_ms=12.0
        ),
    }
    record = classify_cell(cell, per_cohort, baseline)
    assert record.classification == "no_winner_at_n100"


def test_classify_cell_m5_2_no_winner_sub_case() -> None:
    """When M5.2 was no_winner, M6 cannot produce survives/changed — must
    fall back to no_winner_at_n100 regardless of M6 CIs (FR-014 sub-case).
    """
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=1)
    baseline = _make_complete_baseline()  # all rows default to no_winner
    per_cohort: dict[M6CohortKind, M6PerCohortAggregate] = {
        "rest_https_edge": _make_per_cohort_aggregate(
            "rest_https_edge", 100.0, 2.0, engine_forward_mean_ms=12.0
        ),
        "default_grpc": _make_per_cohort_aggregate(
            "default_grpc", 200.0, 2.0, engine_forward_mean_ms=12.0
        ),
        "tuned_grpc_multiplexed": _make_per_cohort_aggregate(
            "tuned_grpc_multiplexed", 199.0, 2.0, engine_forward_mean_ms=12.0
        ),
    }
    record = classify_cell(cell, per_cohort, baseline)
    assert record.classification == "no_winner_at_n100"
    assert record.m5_2_winner_delta_ms is None


def test_classify_cell_r6_cohort_mapping_c1() -> None:
    """At c=1 the classifier consults the M5.2 ``tuned_grpc`` row (R-6)."""
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=1)
    baseline = _baseline_with("embed", 1, "tuned_grpc", "tuned_grpc_recommend", -42.0)
    per_cohort: dict[M6CohortKind, M6PerCohortAggregate] = {
        "rest_https_edge": _make_per_cohort_aggregate("rest_https_edge", 100.0, 2.0),
        "default_grpc": _make_per_cohort_aggregate("default_grpc", 99.0, 2.0),
        "tuned_grpc_multiplexed": _make_per_cohort_aggregate("tuned_grpc_multiplexed", 50.0, 2.0),
    }
    record = classify_cell(cell, per_cohort, baseline)
    assert record.m5_2_winner_delta_ms == 42.0


def test_classify_cell_r6_cohort_mapping_c4() -> None:
    """At c≥2 the classifier consults the M5.2 ``tuned_grpc_multiplexed`` row (R-6)."""
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=4)
    baseline = _baseline_with(
        "embed", 4, "tuned_grpc_multiplexed", "tuned_grpc_multiplexed_recommend", -33.0
    )
    per_cohort: dict[M6CohortKind, M6PerCohortAggregate] = {
        "rest_https_edge": _make_per_cohort_aggregate("rest_https_edge", 100.0, 2.0),
        "default_grpc": _make_per_cohort_aggregate("default_grpc", 99.0, 2.0),
        "tuned_grpc_multiplexed": _make_per_cohort_aggregate("tuned_grpc_multiplexed", 60.0, 2.0),
    }
    record = classify_cell(cell, per_cohort, baseline)
    assert record.m5_2_winner_delta_ms == 33.0


def test_classify_cell_deterministic() -> None:
    """T035: invoking classify_cell twice with identical inputs returns
    byte-identical M6CellRecord (FR-014 'deterministic; operator post-hoc
    re-classification not permitted').
    """
    cell = M6Cell(path="embed", hidden_size=4096, concurrency=1)
    baseline = _baseline_with("embed", 1, "tuned_grpc", "tuned_grpc_recommend", -51.0)
    per_cohort: dict[M6CohortKind, M6PerCohortAggregate] = {
        "rest_https_edge": _make_per_cohort_aggregate(
            "rest_https_edge", 100.0, 5.0, engine_forward_mean_ms=12.0
        ),
        "default_grpc": _make_per_cohort_aggregate(
            "default_grpc", 99.0, 5.0, engine_forward_mean_ms=12.0
        ),
        "tuned_grpc_multiplexed": _make_per_cohort_aggregate(
            "tuned_grpc_multiplexed", 90.0, 5.0, engine_forward_mean_ms=12.0
        ),
    }
    r1 = classify_cell(cell, per_cohort, baseline)
    r2 = classify_cell(cell, per_cohort, baseline)
    assert r1 == r2


def test_snapshot_m5_2_winner_deltas_keys_and_values() -> None:
    """T033: snapshot_m5_2_winner_deltas produces one entry per M6 cell,
    with absolute magnitudes (or None for no_winner rows).
    """
    baseline = _baseline_with("embed", 1, "tuned_grpc", "tuned_grpc_recommend", -51.0)
    snap = snapshot_m5_2_winner_deltas(baseline)
    assert len(snap) == 6
    assert snap["embed_c1_h4096"] == 51.0
    # All other cells are no_winner in the synthetic baseline → None.
    for key in (
        "embed_c4_h4096",
        "embed_c8_h4096",
        "chat_stream_c1_h4096",
        "chat_stream_c4_h4096",
        "chat_stream_c8_h4096",
    ):
        assert snap[key] is None, f"expected None for {key}, got {snap[key]}"
