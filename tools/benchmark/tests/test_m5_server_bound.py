"""T015 — server_bound classifier (research.md R-4 / FR-005).

The classifier flags cohorts whose dominant per-RPC cost is server-side rather
than transport+serialization. Calculation:

    server_overhead_estimate_ms =
        cohort_median_wallclock_ms − rtt_median_ms − m4_client_overhead_floor_ms

Flag is True iff:
    server_overhead_estimate_ms > max(2 × rtt_median_ms, 50ms)
    AND the cohort's CV exceeds 2× M4's loopback CV (when known).

These tests exercise the boundary cases with synthetic inputs so the formula
stays auditable.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.m3_types import BenchmarkCell, RTTRecord, RunCohort, Sample
from vllm_grpc_bench.m5_sweep import classify_server_bound


def _stub_cohort(*, time_mean_seconds: float, time_cv: float | None = 0.04) -> RunCohort:
    cell = BenchmarkCell(
        path="chat_stream",
        hidden_size=4096,
        channel_config=M1_BASELINE,
        corpus_subset="m1_chat",
        iterations=100,
    )
    sample = Sample(
        cell_id=cell.cell_id,
        iteration=0,
        request_wire_bytes=100,
        response_wire_bytes=100,
        wall_clock_seconds=time_mean_seconds,
    )
    return RunCohort(
        cell=cell,
        samples=(sample,),
        n_successful=100,
        bytes_mean=200.0,
        bytes_ci_low=190.0,
        bytes_ci_high=210.0,
        time_mean=time_mean_seconds,
        time_ci_low=time_mean_seconds * 0.95,
        time_ci_high=time_mean_seconds * 1.05,
        measurable=True,
        time_cv=time_cv,
    )


class TestClassifyServerBound:
    """Direct unit tests on the classifier formula."""

    def test_flags_high_server_overhead_with_high_cv(self) -> None:
        # median_wallclock=200ms, rtt=80ms, client_floor=2ms →
        # server_overhead=118ms; threshold=max(160, 50)=160ms → 118<160 so
        # no flag from the overhead side. Build a clearer case below.
        cohort = _stub_cohort(time_mean_seconds=0.500, time_cv=0.20)
        rtt = RTTRecord(n=32, median_ms=80.0, p95_ms=120.0, samples_ms=(80.0,) * 32)
        # server_overhead = 500 - 80 - 2 = 418ms; threshold=max(160, 50)=160ms
        # → overhead dominates. cv=0.20, loopback_cv=0.05, 2*0.05=0.10 → 0.20>0.10 → True
        estimate, flag = classify_server_bound(
            cohort,
            rtt,
            m4_client_overhead_floor_ms=2.0,
            m4_loopback_cv=0.05,
        )
        assert estimate == pytest.approx(418.0, abs=0.1)
        assert flag is True

    def test_no_flag_when_overhead_comparable_to_rtt(self) -> None:
        # cohort_median = 200ms, rtt=80ms, floor=2ms → server_overhead=118ms
        # threshold = max(2*80=160, 50)=160 → 118<160 → no flag
        cohort = _stub_cohort(time_mean_seconds=0.200, time_cv=0.20)
        rtt = RTTRecord(n=32, median_ms=80.0, p95_ms=120.0, samples_ms=(80.0,) * 32)
        estimate, flag = classify_server_bound(
            cohort,
            rtt,
            m4_client_overhead_floor_ms=2.0,
            m4_loopback_cv=0.05,
        )
        assert estimate == pytest.approx(118.0, abs=0.1)
        assert flag is False

    def test_no_flag_when_cv_comparable_to_loopback(self) -> None:
        # overhead dominates but CV is comparable to M4's loopback CV → no flag
        cohort = _stub_cohort(time_mean_seconds=0.500, time_cv=0.06)
        rtt = RTTRecord(n=32, median_ms=80.0, p95_ms=120.0, samples_ms=(80.0,) * 32)
        # cv=0.06, 2*0.05=0.10 → 0.06<0.10 → CV gate prevents the flag
        _, flag = classify_server_bound(
            cohort,
            rtt,
            m4_client_overhead_floor_ms=2.0,
            m4_loopback_cv=0.05,
        )
        assert flag is False

    def test_fifty_ms_floor_prevents_false_positives_at_low_rtt(self) -> None:
        # rtt=5ms → 2*rtt=10ms but floor=50ms → threshold=50ms.
        # cohort_median=60ms, floor=2ms → overhead=53ms → just over 50ms.
        cohort = _stub_cohort(time_mean_seconds=0.060, time_cv=0.20)
        rtt = RTTRecord(n=32, median_ms=5.0, p95_ms=8.0, samples_ms=(5.0,) * 32)
        estimate, flag = classify_server_bound(
            cohort,
            rtt,
            m4_client_overhead_floor_ms=2.0,
            m4_loopback_cv=0.05,
        )
        assert estimate == pytest.approx(53.0, abs=0.1)
        assert flag is True

    def test_unknown_loopback_cv_falls_back_to_overhead_only(self) -> None:
        cohort = _stub_cohort(time_mean_seconds=0.500, time_cv=None)
        rtt = RTTRecord(n=32, median_ms=80.0, p95_ms=120.0, samples_ms=(80.0,) * 32)
        # No CV gate when m4_loopback_cv is None — the flag is set on the
        # overhead-only signal.
        _, flag = classify_server_bound(
            cohort,
            rtt,
            m4_client_overhead_floor_ms=2.0,
            m4_loopback_cv=None,
        )
        assert flag is True
