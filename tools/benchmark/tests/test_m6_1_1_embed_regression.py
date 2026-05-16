"""M6.1.1 embed regression check — FR-015b tests (T028)."""

from __future__ import annotations

from typing import Any

from vllm_grpc_bench.m6_1_1_embed_regression import compute_embed_regression
from vllm_grpc_bench.m6_1_1_types import M6_1_1Cell, M6_1_1Cohort, Phase2Choice

_EMBED_C1 = M6_1_1Cell(path="embed", concurrency=1, hidden_size=4096)
_EMBED_C4 = M6_1_1Cell(path="embed", concurrency=4, hidden_size=4096)
_EMBED_C8 = M6_1_1Cell(path="embed", concurrency=8, hidden_size=4096)
_COHORTS: tuple[M6_1_1Cohort, M6_1_1Cohort, M6_1_1Cohort] = (
    "rest_https_edge",
    "default_grpc",
    "tuned_grpc_multiplexed",
)


def _m6_1_baseline(c1: float, c4: float, c8: float) -> dict[str, Any]:
    return {
        "schema_version": "m6_1.v1",
        "engine_cost_baseline": [
            {
                "cell": {"path": "embed", "concurrency": 1, "hidden_size": 4096},
                "engine_cost_mean_ms": c1,
            },
            {
                "cell": {"path": "embed", "concurrency": 4, "hidden_size": 4096},
                "engine_cost_mean_ms": c4,
            },
            {
                "cell": {"path": "embed", "concurrency": 8, "hidden_size": 4096},
                "engine_cost_mean_ms": c8,
            },
            {
                "cell": {"path": "chat_stream", "concurrency": 1, "hidden_size": 4096},
                "engine_cost_mean_ms": 44.0,
            },
        ],
    }


def _all_nine_within_tolerance(scale: float = 1.0) -> dict[tuple[M6_1_1Cell, M6_1_1Cohort], float]:
    """9 entries (3 embed cells × 3 cohorts) all at ``scale × baseline``."""
    out: dict[tuple[M6_1_1Cell, M6_1_1Cohort], float] = {}
    for cell, baseline in [(_EMBED_C1, 338.0), (_EMBED_C4, 100.0), (_EMBED_C8, 95.0)]:
        for cohort in _COHORTS:
            out[(cell, cohort)] = baseline * scale
    return out


# --- Happy-path: within tolerance -------------------------------------------


def test_all_within_2pct_yields_no_warnings() -> None:
    baseline = _m6_1_baseline(338.0, 100.0, 95.0)
    measured = _all_nine_within_tolerance(scale=1.02)  # +2% across the board
    result = compute_embed_regression(measured, baseline)
    assert result.n_warnings == 0
    assert result.all_within_tolerance is True
    assert len(result.per_entry) == 9
    assert all(not e.embed_regression_warning for e in result.per_entry)


def test_exactly_at_threshold_does_not_warn() -> None:
    """|delta_pct| == 0.05 → not a warning (strict > comparison)."""
    baseline = _m6_1_baseline(100.0, 100.0, 100.0)
    measured: dict[tuple[M6_1_1Cell, M6_1_1Cohort], float] = {
        (_EMBED_C1, "rest_https_edge"): 105.0,  # exactly +5%
    }
    result = compute_embed_regression(measured, baseline)
    assert result.n_warnings == 0
    assert result.per_entry[0].delta_pct == 0.05


# --- Warning path -----------------------------------------------------------


def test_one_entry_at_plus_6pct_yields_one_warning() -> None:
    baseline = _m6_1_baseline(338.0, 100.0, 95.0)
    measured = _all_nine_within_tolerance(scale=1.02)
    # Bump one entry to +6% drift on the embed c=1 / default_grpc cohort.
    measured[(_EMBED_C1, "default_grpc")] = 338.0 * 1.06
    result = compute_embed_regression(measured, baseline)
    assert result.n_warnings == 1
    assert result.all_within_tolerance is False
    warning_entries = [e for e in result.per_entry if e.embed_regression_warning]
    assert len(warning_entries) == 1
    assert warning_entries[0].cell == _EMBED_C1
    assert warning_entries[0].cohort == "default_grpc"
    assert warning_entries[0].delta_pct > 0.05


def test_one_entry_at_minus_7pct_yields_one_warning() -> None:
    baseline = _m6_1_baseline(338.0, 100.0, 95.0)
    measured = _all_nine_within_tolerance(scale=1.0)
    measured[(_EMBED_C4, "tuned_grpc_multiplexed")] = 100.0 * 0.93
    result = compute_embed_regression(measured, baseline)
    assert result.n_warnings == 1
    warning = next(e for e in result.per_entry if e.embed_regression_warning)
    assert warning.delta_pct < -0.05


# --- Acknowledgement path (FR-015b path ii, round-2 Q2) --------------------


def test_acknowledged_warnings_propagate_to_per_entry() -> None:
    baseline = _m6_1_baseline(338.0, 100.0, 95.0)
    measured = _all_nine_within_tolerance(scale=1.02)
    measured[(_EMBED_C1, "default_grpc")] = 338.0 * 1.07
    choice = Phase2Choice(
        embed_regression_acknowledged=True,
        embed_regression_justification="post-symmetrisation cross-cohort variance",
    )
    result = compute_embed_regression(measured, baseline, phase_2_choice=choice)
    assert result.n_warnings == 1
    assert result.acknowledged_count == 9  # all 9 entries flagged acknowledged
    warning = next(e for e in result.per_entry if e.embed_regression_warning)
    assert warning.embed_regression_acknowledged is True
    assert warning.operator_justification is not None
    assert "post-symmetrisation" in warning.operator_justification


def test_no_phase_2_choice_defaults_to_unacknowledged() -> None:
    baseline = _m6_1_baseline(338.0, 100.0, 95.0)
    measured = _all_nine_within_tolerance(scale=1.0)
    result = compute_embed_regression(measured, baseline, phase_2_choice=None)
    assert result.acknowledged_count == 0
    assert all(not e.embed_regression_acknowledged for e in result.per_entry)


def test_acknowledged_without_warning_has_no_justification_on_entry() -> None:
    """Acknowledgement only carries justification text on entries that fired."""
    baseline = _m6_1_baseline(338.0, 100.0, 95.0)
    measured = _all_nine_within_tolerance(scale=1.0)  # no warnings
    choice = Phase2Choice(
        embed_regression_acknowledged=True,
        embed_regression_justification="defensive ack",
    )
    result = compute_embed_regression(measured, baseline, phase_2_choice=choice)
    # No warnings fired → no per-entry justification text (the ack is
    # bookkeeping, not a per-entry annotation).
    assert all(e.operator_justification is None for e in result.per_entry)


# --- Edge cases -------------------------------------------------------------


def test_missing_baseline_cell_skips_entry() -> None:
    """A measurement for a cell that M6.1 didn't publish is silently dropped."""
    baseline = _m6_1_baseline(338.0, 100.0, 95.0)
    # Remove c=8 from the baseline.
    baseline["engine_cost_baseline"] = [
        e for e in baseline["engine_cost_baseline"] if e["cell"]["concurrency"] != 8
    ]
    measured = _all_nine_within_tolerance(scale=1.02)
    result = compute_embed_regression(measured, baseline)
    # c=8 entries (3 cohorts) skipped → 6 entries remain.
    assert len(result.per_entry) == 6


def test_zero_baseline_skips_entry() -> None:
    """A zero baseline (delta_pct would be undefined) is skipped."""
    baseline = _m6_1_baseline(0.0, 100.0, 95.0)
    measured = _all_nine_within_tolerance(scale=1.0)
    result = compute_embed_regression(measured, baseline)
    # c=1 entries (3 cohorts) skipped due to zero baseline.
    assert len(result.per_entry) == 6


def test_chat_stream_measurements_are_ignored() -> None:
    """compute_embed_regression considers only embed cells."""
    baseline = _m6_1_baseline(338.0, 100.0, 95.0)
    measured: dict[tuple[M6_1_1Cell, M6_1_1Cohort], float] = {
        (_EMBED_C1, "rest_https_edge"): 338.0,
        (
            M6_1_1Cell(path="chat_stream", concurrency=1, hidden_size=4096),
            "rest_https_edge",
        ): 47.0,  # chat_stream — must be filtered out.
    }
    result = compute_embed_regression(measured, baseline)
    assert len(result.per_entry) == 1
    assert result.per_entry[0].cell.path == "embed"


def test_empty_measurement_dict_returns_empty_check() -> None:
    baseline = _m6_1_baseline(338.0, 100.0, 95.0)
    result = compute_embed_regression({}, baseline)
    assert result.per_entry == []
    assert result.n_warnings == 0
    assert result.all_within_tolerance is True
