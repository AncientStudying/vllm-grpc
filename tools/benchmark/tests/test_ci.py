from __future__ import annotations

import math

import pytest
from vllm_grpc_bench.ci import _T_CRITICAL_AT_95, estimate, is_winner


class TestEstimate:
    def test_mean_and_stddev_against_hand_checked(self) -> None:
        # Hand-checked sample: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        # mean = 5.5, sample stddev (ddof=1) = sqrt(82.5/9) ≈ 3.0277
        e = estimate(list(range(1, 11)))
        assert e.n == 10
        assert e.mean == pytest.approx(5.5, abs=1e-9)
        assert e.stddev == pytest.approx(math.sqrt(82.5 / 9), rel=1e-6)

    def test_constant_sample_zero_stddev(self) -> None:
        e = estimate([7.0] * 30)
        assert e.mean == pytest.approx(7.0)
        assert e.stddev == pytest.approx(0.0)
        assert e.ci_low == pytest.approx(7.0)
        assert e.ci_high == pytest.approx(7.0)

    def test_n1_collapses_ci(self) -> None:
        e = estimate([3.14])
        assert e.n == 1
        assert e.ci_low == e.ci_high == e.mean

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            estimate([])

    def test_below_floor_raises(self) -> None:
        # n in [2, 9] is rejected because the t-critical table starts at n=10
        with pytest.raises(ValueError):
            estimate([1.0, 2.0])  # n=2 < 10


class TestTCriticalTable:
    def test_n30_within_half_percent_of_published(self) -> None:
        # Published two-sided t_{0.025, df=29} ≈ 2.0452 (NIST tables)
        published = 2.0452
        table = _T_CRITICAL_AT_95[30]
        rel_err = abs(table - published) / published
        assert rel_err < 0.005, f"n=30 critical value drift: {rel_err:.4%}"


class TestIsWinner:
    def test_strict_clearance_wins(self) -> None:
        # Candidate ci_low must be STRICTLY greater than baseline ci_high
        assert is_winner(baseline_ci_high=10.0, candidate_ci_low=10.0001)

    def test_equal_does_not_win(self) -> None:
        assert not is_winner(baseline_ci_high=10.0, candidate_ci_low=10.0)

    def test_just_below_baseline_loses(self) -> None:
        assert not is_winner(baseline_ci_high=10.0, candidate_ci_low=9.9999)
