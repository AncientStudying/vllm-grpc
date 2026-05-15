"""Tests for m6_supersede baseline loader + cohort mapping (T023)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from vllm_grpc_bench.m6_supersede import (
    M5_2BaselineMissingCellError,
    get_m5_2_winner_delta,
    load_and_validate_m5_2_baseline,
    map_m6_grpc_cohort_to_m5_2_lookup,
)
from vllm_grpc_bench.m6_types import M6Cell

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
