"""M6.1.1 perturbation budget gate — FR-012 (round-2 Q3) tests."""

from __future__ import annotations

import re

import pytest
from vllm_grpc_bench.m6_1_1_perturbation import check_perturbation_budget, raise_if_exceeded
from vllm_grpc_bench.m6_1_1_types import (
    M6_1_1Cell,
    M6_1_1Cohort,
    MultiPointTimings,
    PerSegmentAggregate,
    PerturbationAudit,
    Phase1RunRecord,
)

_CHAT_STREAM_C1 = M6_1_1Cell(path="chat_stream", concurrency=1, hidden_size=4096)
_CHAT_STREAM_C8 = M6_1_1Cell(path="chat_stream", concurrency=8, hidden_size=4096)


def _mpt(cohort: M6_1_1Cohort, cell: M6_1_1Cell, perturbation_us: float) -> MultiPointTimings:
    return MultiPointTimings(
        cohort=cohort,
        cell=cell,
        engine_ttft_ms_mean=44.0,
        engine_ttft_ms_ci_half_width=0.5,
        per_segment=PerSegmentAggregate(
            seg_ab_ms_mean=2.0,
            seg_ab_ms_ci_half_width=0.1,
            seg_bc_ms_mean=40.0,
            seg_bc_ms_ci_half_width=0.1,
            seg_cd_ms_mean=2.0,
            seg_cd_ms_ci_half_width=0.1,
            n_samples=50,
        ),
        perturbation_total_us_mean=perturbation_us,
    )


def _make_record(timings: list[MultiPointTimings]) -> Phase1RunRecord:
    return Phase1RunRecord(
        run_id="r",
        run_started_at="t",
        run_completed_at="t",
        wall_clock_s=0.0,
        multi_point_timings=timings,
        phase_1_classifications={},
        perturbation_audit=PerturbationAudit(per_cohort_per_cell={}, exceeded=False),
        n_per_cohort=50,
    )


def test_all_within_budget_returns_not_exceeded() -> None:
    """All RPC perturbations ≤ 100 µs → exceeded=False (research R-2 expected case)."""
    timings = [
        _mpt("rest_https_edge", _CHAT_STREAM_C1, 0.1),
        _mpt("default_grpc", _CHAT_STREAM_C1, 0.2),
        _mpt("tuned_grpc_multiplexed", _CHAT_STREAM_C1, 0.05),
        _mpt("rest_https_edge", _CHAT_STREAM_C8, 100.0),
    ]
    audit = check_perturbation_budget(_make_record(timings))
    assert audit.exceeded is False
    assert audit.exceeded_pairs == []
    assert audit.budget_us == 500.0


def test_single_pair_over_budget_flags_only_that_pair() -> None:
    """One (cohort, cell) pair averaging 600 µs → exceeded=True, only that pair listed."""
    timings = [
        _mpt("rest_https_edge", _CHAT_STREAM_C1, 0.1),
        _mpt("default_grpc", _CHAT_STREAM_C1, 600.0),
        _mpt("tuned_grpc_multiplexed", _CHAT_STREAM_C1, 0.2),
    ]
    audit = check_perturbation_budget(_make_record(timings))
    assert audit.exceeded is True
    assert audit.exceeded_pairs == [("default_grpc", "chat_stream_c1_h4096")]


def test_at_threshold_does_not_exceed() -> None:
    """Exactly 500 µs → not exceeded (strict > comparison per FR-012)."""
    timings = [_mpt("rest_https_edge", _CHAT_STREAM_C1, 500.0)]
    audit = check_perturbation_budget(_make_record(timings))
    assert audit.exceeded is False


def test_raise_if_exceeded_no_exit_when_within_budget() -> None:
    audit = PerturbationAudit(per_cohort_per_cell={}, exceeded=False)
    raise_if_exceeded(audit)  # must not raise


def test_raise_if_exceeded_exits_code_4_with_message_match(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """SystemExit(4) + stderr matches contracts/cli.md exit-code-4 regex."""
    audit = PerturbationAudit(
        per_cohort_per_cell={("default_grpc", "chat_stream_c1_h4096"): 600.0},
        exceeded=True,
        exceeded_pairs=[("default_grpc", "chat_stream_c1_h4096")],
        budget_us=500.0,
    )
    with pytest.raises(SystemExit) as excinfo:
        raise_if_exceeded(audit)
    assert excinfo.value.code == 4
    err = capsys.readouterr().err
    # Per contracts/cli.md: `m6.1.1: perturbation > 500 µs on {cohort, cell}; ...`
    assert re.search(r"m6\.1\.1: perturbation > 500 µs on", err), err
    assert "cohort=default_grpc" in err
    assert "cell=chat_stream_c1_h4096" in err
    assert "re-run --m6_1_1-diagnose" in err


def test_raise_if_exceeded_multi_pair_reports_first_plus_count(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Multi-pair regression: stderr names first pair with '(plus N more)' suffix."""
    pairs = [
        ("default_grpc", "chat_stream_c1_h4096"),
        ("default_grpc", "chat_stream_c8_h4096"),
        ("tuned_grpc_multiplexed", "chat_stream_c4_h4096"),
    ]
    audit = PerturbationAudit(
        per_cohort_per_cell={p: 700.0 for p in pairs},
        exceeded=True,
        exceeded_pairs=pairs,
        budget_us=500.0,
    )
    with pytest.raises(SystemExit) as excinfo:
        raise_if_exceeded(audit)
    assert excinfo.value.code == 4
    err = capsys.readouterr().err
    assert "(plus 2 more)" in err
