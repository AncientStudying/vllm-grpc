"""Tests for ``m6_1_supersede`` — M6 baseline loader + verdict classifier.

Covers T012 (loader preconditions) and T023 (classifier 5-category coverage,
FR-010 sub-clause regression).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from vllm_grpc_bench.m6_1_supersede import (
    M6BaselineMissingCellError,
    classify_cell,
    compute_engine_cost_drift_warning,
    compute_engine_cost_mean_ms,
    load_and_validate_m6_baseline,
)
from vllm_grpc_bench.m6_1_types import (
    EngineCostAggregate,
    M6_1Cell,
    M6_1PerCohortAggregate,
)

# --- Helpers ----------------------------------------------------------------


def _make_synthetic_baseline_row(
    path: str,
    concurrency: int,
    classification: str,
    rest_mean: float = 200.0,
    grpc_mean: float = 100.0,
    engine_cost_mean_ms: float = 5.0,
) -> dict[str, object]:
    return {
        "cell": {"path": path, "hidden_size": 4096, "concurrency": concurrency},
        "classification": classification,
        "classifier_metric": "wall_clock_ms" if path == "embed" else "ttft_ms",
        "cohort_pair": ["rest_https_edge", "tuned_grpc_multiplexed"],
        "m5_2_winner_cohort": "tuned_grpc_multiplexed",
        "m5_2_winner_delta_ms": None,
        "m5_2_winner_direction": None,
        "engine_cost_mean_ms": engine_cost_mean_ms,
        "engine_cost_drift_warning": False,
        "per_cohort_engine_cost_mean_ms": None,
        "per_cohort_classifier_metric": {
            "rest_https_edge": {
                "mean_ms": rest_mean,
                "ci_lower_ms": rest_mean - 1.0,
                "ci_upper_ms": rest_mean + 1.0,
                "n_successes": 100,
            },
            "default_grpc": {
                "mean_ms": (rest_mean + grpc_mean) / 2.0,
                "ci_lower_ms": (rest_mean + grpc_mean) / 2.0 - 1.0,
                "ci_upper_ms": (rest_mean + grpc_mean) / 2.0 + 1.0,
                "n_successes": 100,
            },
            "tuned_grpc_multiplexed": {
                "mean_ms": grpc_mean,
                "ci_lower_ms": grpc_mean - 1.0,
                "ci_upper_ms": grpc_mean + 1.0,
                "n_successes": 100,
            },
        },
        "notes": "synthetic",
    }


def _make_full_synthetic_baseline(
    classifications: dict[tuple[str, int], str] | None = None,
    engine_version: str | None = "unknown",
) -> dict[str, object]:
    """Produce a synthetic M6 baseline JSON document with all 6 cells."""
    classifications = classifications or {}
    cells = [
        ("embed", 1),
        ("embed", 4),
        ("embed", 8),
        ("chat_stream", 1),
        ("chat_stream", 4),
        ("chat_stream", 8),
    ]
    rows = [
        _make_synthetic_baseline_row(
            path,
            concurrency,
            classifications.get((path, concurrency), "verdict_survives"),
        )
        for (path, concurrency) in cells
    ]
    meta: dict[str, object] = {
        "cold_start_s": 28.0,
        "git_sha": "deadbeef",
        "gpu_type": "A10G",
        "hostname": "test",
        "m5_2_winner_deltas": {},
        "m6_base_seed": 42,
        "model_identifier": "Qwen/Qwen3-8B",
    }
    if engine_version is not None:
        meta["engine_version"] = engine_version
    return {
        "supersedes_m5_2_under_real_engine": rows,
        "m6_meta": meta,
    }


def _write_baseline(tmp_path: Path, payload: dict[str, object]) -> Path:
    p = tmp_path / "m6_baseline.json"
    p.write_text(json.dumps(payload))
    return p


# --- Loader tests (T012) ----------------------------------------------------


def test_loader_returns_deltas_for_all_6_cells(tmp_path: Path) -> None:
    payload = _make_full_synthetic_baseline()
    path = _write_baseline(tmp_path, payload)
    deltas, directions, version, meta = load_and_validate_m6_baseline(path)
    assert set(deltas.keys()) == {
        "embed_c1_h4096",
        "embed_c4_h4096",
        "embed_c8_h4096",
        "chat_stream_c1_h4096",
        "chat_stream_c4_h4096",
        "chat_stream_c8_h4096",
    }
    # All synthetic rows use verdict_survives → all deltas non-None.
    assert all(v is not None for v in deltas.values())
    assert all(d in {"rest_wins", "grpc_wins"} for d in directions.values())
    assert version == "unknown"
    assert meta["model_identifier"] == "Qwen/Qwen3-8B"


def test_loader_raises_missing_cell_error(tmp_path: Path) -> None:
    payload = _make_full_synthetic_baseline()
    # Drop the (embed, c=4) row.
    rows = list(payload["supersedes_m5_2_under_real_engine"])  # type: ignore[arg-type]
    rows = [r for r in rows if r["cell"]["concurrency"] != 4 or r["cell"]["path"] != "embed"]
    payload["supersedes_m5_2_under_real_engine"] = rows
    path = _write_baseline(tmp_path, payload)
    with pytest.raises(M6BaselineMissingCellError) as exc_info:
        load_and_validate_m6_baseline(path)
    assert exc_info.value.cell == ("embed", 4096, 4)


def test_loader_returns_none_delta_for_no_usable_baseline(tmp_path: Path) -> None:
    payload = _make_full_synthetic_baseline(
        classifications={
            ("embed", 1): "no_winner_at_n100",
            ("embed", 4): "cell_incomplete",
            ("embed", 8): "verdict_buried_by_engine",
            ("chat_stream", 1): "verdict_survives",
            ("chat_stream", 4): "verdict_changed",
            ("chat_stream", 8): "verdict_survives",
        }
    )
    path = _write_baseline(tmp_path, payload)
    deltas, directions, _version, _meta = load_and_validate_m6_baseline(path)
    assert deltas["embed_c1_h4096"] is None
    assert deltas["embed_c4_h4096"] is None
    assert deltas["embed_c8_h4096"] is None
    assert directions["embed_c1_h4096"] is None
    assert deltas["chat_stream_c1_h4096"] is not None
    assert deltas["chat_stream_c4_h4096"] is not None


def test_loader_defaults_engine_version_to_unknown_when_absent(tmp_path: Path) -> None:
    payload = _make_full_synthetic_baseline(engine_version=None)
    path = _write_baseline(tmp_path, payload)
    _deltas, _directions, version, _meta = load_and_validate_m6_baseline(path)
    assert version == "unknown"


def test_loader_reads_explicit_engine_version(tmp_path: Path) -> None:
    payload = _make_full_synthetic_baseline(engine_version="0.20.1")
    path = _write_baseline(tmp_path, payload)
    _deltas, _directions, version, _meta = load_and_validate_m6_baseline(path)
    assert version == "0.20.1"


# --- Classifier helper tests (T023) -----------------------------------------


def _make_agg(
    cohort: str,
    mean_ms: float,
    ci_half_width_ms: float = 1.0,
    n_successes: int = 100,
    engine_forward_mean_ms: float | None = None,
    engine_ttft_mean_ms: float | None = None,
) -> M6_1PerCohortAggregate:
    return M6_1PerCohortAggregate(
        cohort=cohort,  # type: ignore[arg-type]
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
        ),
    )


def _embed_per_cohort(
    rest: float, default: float, grpc: float, ci: float = 1.0, engine_cost: float = 5.0
) -> dict[str, M6_1PerCohortAggregate]:
    return {
        "rest_https_edge": _make_agg(
            "rest_https_edge", rest, ci, engine_forward_mean_ms=engine_cost
        ),
        "default_grpc": _make_agg("default_grpc", default, ci, engine_forward_mean_ms=engine_cost),
        "tuned_grpc_multiplexed": _make_agg(
            "tuned_grpc_multiplexed", grpc, ci, engine_forward_mean_ms=engine_cost
        ),
    }


def test_engine_cost_mean_unweighted_average() -> None:
    pc = _embed_per_cohort(rest=200.0, default=200.0, grpc=200.0)
    pc["rest_https_edge"] = _make_agg("rest_https_edge", 200.0, engine_forward_mean_ms=10.0)
    pc["default_grpc"] = _make_agg("default_grpc", 200.0, engine_forward_mean_ms=20.0)
    pc["tuned_grpc_multiplexed"] = _make_agg(
        "tuned_grpc_multiplexed", 200.0, engine_forward_mean_ms=30.0
    )
    mean, per_cohort = compute_engine_cost_mean_ms(pc, "embed")
    assert mean == pytest.approx(20.0)
    assert per_cohort == {
        "rest_https_edge": 10.0,
        "default_grpc": 20.0,
        "tuned_grpc_multiplexed": 30.0,
    }


def test_engine_cost_drift_warning_above_10_pct() -> None:
    assert compute_engine_cost_drift_warning(
        {"rest_https_edge": 10.0, "default_grpc": 10.0, "tuned_grpc_multiplexed": 12.0}
    )
    assert not compute_engine_cost_drift_warning(
        {"rest_https_edge": 10.0, "default_grpc": 10.5, "tuned_grpc_multiplexed": 10.9}
    )


def test_classify_verdict_survives() -> None:
    cell = M6_1Cell(path="embed", hidden_size=4096, concurrency=1)
    pc = _embed_per_cohort(rest=200.0, default=150.0, grpc=100.0, ci=1.0)
    verdict, reason, ecost, drift, _ = classify_cell(
        None, cell, pc, m6_winner_delta_ms=80.0, m6_winner_direction="grpc_wins"
    )
    assert verdict == "verdict_survives"
    assert "non-overlapping" in reason
    assert ecost == pytest.approx(5.0)
    assert drift is False


def test_classify_verdict_changed_direction_flip() -> None:
    cell = M6_1Cell(path="embed", hidden_size=4096, concurrency=1)
    pc = _embed_per_cohort(rest=100.0, default=150.0, grpc=200.0, ci=1.0)
    verdict, reason, _, _, _ = classify_cell(
        None, cell, pc, m6_winner_delta_ms=80.0, m6_winner_direction="grpc_wins"
    )
    assert verdict == "verdict_changed"
    assert "OPPOSITE" in reason


def test_classify_verdict_buried_by_engine() -> None:
    cell = M6_1Cell(path="embed", hidden_size=4096, concurrency=1)
    pc = _embed_per_cohort(rest=200.0, default=200.0, grpc=200.0, ci=5.0, engine_cost=100.0)
    verdict, _reason, _, _, _ = classify_cell(
        None, cell, pc, m6_winner_delta_ms=10.0, m6_winner_direction="grpc_wins"
    )
    assert verdict == "verdict_buried_by_engine"


def test_classify_no_winner_at_n100_overlap_small_engine_cost() -> None:
    cell = M6_1Cell(path="embed", hidden_size=4096, concurrency=1)
    pc = _embed_per_cohort(rest=200.0, default=200.0, grpc=200.0, ci=5.0, engine_cost=1.0)
    verdict, _reason, _, _, _ = classify_cell(
        None, cell, pc, m6_winner_delta_ms=10.0, m6_winner_direction="grpc_wins"
    )
    assert verdict == "no_winner_at_n100"


def test_classify_cell_incomplete_low_n() -> None:
    cell = M6_1Cell(path="embed", hidden_size=4096, concurrency=1)
    pc = _embed_per_cohort(rest=200.0, default=150.0, grpc=100.0)
    pc["default_grpc"] = _make_agg(
        "default_grpc", 150.0, n_successes=60, engine_forward_mean_ms=5.0
    )
    verdict, reason, _, _, _ = classify_cell(
        None, cell, pc, m6_winner_delta_ms=80.0, m6_winner_direction="grpc_wins"
    )
    assert verdict == "cell_incomplete"
    assert "60" in reason


def test_classify_fr_010_subclause_buried_by_engine_in_m6_yields_no_winner() -> None:
    """FR-010 sub-clause: cells whose M6 verdict was buried_by_engine classify as
    no_winner_at_n100 regardless of M6.1 CI overlap."""
    cell = M6_1Cell(path="embed", hidden_size=4096, concurrency=1)
    # Strong non-overlap → M6.1 alone would call this verdict_survives.
    pc = _embed_per_cohort(rest=200.0, default=150.0, grpc=100.0, ci=1.0)
    # M6 had no usable winner delta (e.g., M6 verdict was buried_by_engine).
    verdict, _reason, _, _, _ = classify_cell(
        None, cell, pc, m6_winner_delta_ms=None, m6_winner_direction=None
    )
    assert verdict == "no_winner_at_n100"


def test_classify_fr_010_subclause_no_winner_at_n100_in_m6() -> None:
    cell = M6_1Cell(path="embed", hidden_size=4096, concurrency=1)
    pc = _embed_per_cohort(rest=200.0, default=150.0, grpc=100.0, ci=1.0)
    verdict, _reason, _, _, _ = classify_cell(
        None, cell, pc, m6_winner_delta_ms=None, m6_winner_direction=None
    )
    assert verdict == "no_winner_at_n100"
