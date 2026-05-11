"""T011 — validation invariants for M5-introduced dataclasses.

Covers the dataclass-level guarantees from
``specs/017-m5-cross-host-validation/data-model.md``:

* ``RTTRecord`` rejects ``n < 1`` and negative ``samples_ms`` entries.
* ``SupersedesM4Entry.verdict_changed`` is True iff either the time-verdict
  or the bytes-verdict literal differs between M4 and M5; the field is
  auto-derived in ``__post_init__`` so callers cannot pass an inconsistent
  value.
* A ``RunCohort`` with ``discarded=True`` is silently filtered out by the
  ``non_discarded`` aggregation helper that M5 sweep code consumes; pre-M5
  cohorts (``discarded=False``) pass through unchanged so the helper is a
  no-op on M3/M4 paths.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.m3_types import (
    BenchmarkCell,
    Citation,
    M5CrossHostBaseline,
    RTTRecord,
    RunCohort,
    Sample,
    SupersedesM4Entry,
    non_discarded,
)


def _stub_cohort(*, discarded: bool, cell_id_suffix: str) -> RunCohort:
    """Minimal RunCohort instance for filter testing.

    M3/M4 cohorts have all M5 optional fields at their defaults; this helper
    builds one cohort and lets the caller flip only the ``discarded`` flag so
    the aggregation-filter test is unambiguous.
    """
    cell = BenchmarkCell(
        path="embed",
        hidden_size=2048,
        channel_config=M1_BASELINE,
        corpus_subset="m1_embed",
        iterations=1,
    )
    sample = Sample(
        cell_id=f"{cell.cell_id}|{cell_id_suffix}",
        iteration=0,
        request_wire_bytes=10,
        response_wire_bytes=10,
        wall_clock_seconds=0.001,
    )
    return RunCohort(
        cell=cell,
        samples=(sample,),
        n_successful=1,
        bytes_mean=20.0,
        bytes_ci_low=20.0,
        bytes_ci_high=20.0,
        time_mean=0.001,
        time_ci_low=0.001,
        time_ci_high=0.001,
        measurable=True,
        discarded=discarded,
    )


class TestRTTRecordValidation:
    """RTTRecord enforces FR-004's invariants at construction time."""

    def test_rejects_n_below_one(self) -> None:
        with pytest.raises(ValueError, match=r"RTTRecord\.n must be >= 1"):
            RTTRecord(n=0, median_ms=5.0, p95_ms=6.0, samples_ms=())

    def test_rejects_negative_n(self) -> None:
        with pytest.raises(ValueError, match=r"RTTRecord\.n must be >= 1"):
            RTTRecord(n=-3, median_ms=5.0, p95_ms=6.0, samples_ms=())

    def test_rejects_negative_samples(self) -> None:
        with pytest.raises(ValueError, match=r"samples_ms entries must be non-negative"):
            RTTRecord(n=3, median_ms=5.0, p95_ms=6.0, samples_ms=(5.0, -0.5, 7.0))

    def test_zero_sample_accepted(self) -> None:
        # Boundary: a perfectly-zero probe is allowed (sub-microsecond timer
        # quantisation on commodity hardware can land here).
        rec = RTTRecord(n=1, median_ms=0.0, p95_ms=0.0, samples_ms=(0.0,))
        assert rec.n == 1


class TestSupersedesM4EntryVerdictChanged:
    """SupersedesM4Entry.verdict_changed auto-derives from the M4/M5 verdicts."""

    def _make(
        self,
        *,
        m4_verdict_time: str,
        m4_verdict_bytes: str,
        m5_verdict_time: str,
        m5_verdict_bytes: str,
        expected_class: str = "verdict_confirmed",
        loopback: bool = False,
    ) -> SupersedesM4Entry:
        return SupersedesM4Entry(
            m4_axis="keepalive",
            m4_hidden_size=4096,
            m4_path="embed",
            m4_verdict_time=m4_verdict_time,  # type: ignore[arg-type]
            m4_verdict_bytes=m4_verdict_bytes,  # type: ignore[arg-type]
            m4_loopback_caveat=loopback,
            m5_verdict_time=m5_verdict_time,  # type: ignore[arg-type]
            m5_verdict_bytes=m5_verdict_bytes,  # type: ignore[arg-type]
            m5_supporting_ci_lower=0.010,
            m5_supporting_ci_upper=0.012,
            rationale="synthetic test fixture",
            expected_class=expected_class,  # type: ignore[arg-type]
        )

    def test_verdict_changed_true_when_time_differs(self) -> None:
        entry = self._make(
            m4_verdict_time="no_winner",
            m4_verdict_bytes="no_winner",
            m5_verdict_time="recommend",
            m5_verdict_bytes="no_winner",
            expected_class="loopback_resolution",
            loopback=True,
        )
        assert entry.verdict_changed is True

    def test_verdict_changed_true_when_bytes_differs(self) -> None:
        entry = self._make(
            m4_verdict_time="no_winner",
            m4_verdict_bytes="recommend",
            m5_verdict_time="no_winner",
            m5_verdict_bytes="no_winner",
        )
        assert entry.verdict_changed is True

    def test_verdict_changed_false_when_both_match(self) -> None:
        entry = self._make(
            m4_verdict_time="recommend",
            m4_verdict_bytes="no_winner",
            m5_verdict_time="recommend",
            m5_verdict_bytes="no_winner",
        )
        assert entry.verdict_changed is False

    def test_verdict_changed_overrides_caller_supplied_value(self) -> None:
        # verdict_changed is field(init=False) — callers cannot pass it.
        with pytest.raises(TypeError):
            SupersedesM4Entry(
                m4_axis="keepalive",
                m4_hidden_size=4096,
                m4_path="embed",
                m4_verdict_time="recommend",
                m4_verdict_bytes="no_winner",
                m4_loopback_caveat=False,
                m5_verdict_time="recommend",
                m5_verdict_bytes="no_winner",
                m5_supporting_ci_lower=0.0,
                m5_supporting_ci_upper=0.0,
                rationale="x",
                expected_class="verdict_confirmed",
                verdict_changed=True,  # type: ignore[call-arg]
            )

    def test_rationale_required(self) -> None:
        with pytest.raises(ValueError, match=r"rationale must be non-empty"):
            self._make(
                m4_verdict_time="recommend",
                m4_verdict_bytes="no_winner",
                m5_verdict_time="recommend",
                m5_verdict_bytes="no_winner",
            ).__class__(
                m4_axis="keepalive",
                m4_hidden_size=4096,
                m4_path="embed",
                m4_verdict_time="recommend",
                m4_verdict_bytes="no_winner",
                m4_loopback_caveat=False,
                m5_verdict_time="recommend",
                m5_verdict_bytes="no_winner",
                m5_supporting_ci_lower=0.0,
                m5_supporting_ci_upper=0.0,
                rationale="",
                expected_class="verdict_confirmed",
            )

    def test_inverted_ci_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"m5_supporting_ci_lower"):
            SupersedesM4Entry(
                m4_axis="keepalive",
                m4_hidden_size=4096,
                m4_path="embed",
                m4_verdict_time="recommend",
                m4_verdict_bytes="no_winner",
                m4_loopback_caveat=False,
                m5_verdict_time="recommend",
                m5_verdict_bytes="no_winner",
                m5_supporting_ci_lower=0.012,
                m5_supporting_ci_upper=0.010,
                rationale="x",
                expected_class="verdict_confirmed",
            )

    def test_citations_default_empty_tuple(self) -> None:
        entry = self._make(
            m4_verdict_time="recommend",
            m4_verdict_bytes="no_winner",
            m5_verdict_time="recommend",
            m5_verdict_bytes="no_winner",
        )
        assert entry.citations == ()

    def test_citations_attached_for_time_metric_change(self) -> None:
        # Smoke: the dataclass accepts a citations tuple — FR-017 wiring is
        # done by m5_supersede.build_supersedes_m4_table (US3 / T050a).
        citation = Citation(
            repo="grpc/grpc",
            file_path="src/core/ext/transport/chttp2/transport/chttp2_transport.cc",
            identifier="keepalive_watchdog_fired_locked",
            justification="keepalive ping timer trips on real-RTT transport",
        )
        entry = SupersedesM4Entry(
            m4_axis="keepalive",
            m4_hidden_size=4096,
            m4_path="embed",
            m4_verdict_time="no_winner",
            m4_verdict_bytes="no_winner",
            m4_loopback_caveat=True,
            m5_verdict_time="recommend",
            m5_verdict_bytes="no_winner",
            m5_supporting_ci_lower=0.010,
            m5_supporting_ci_upper=0.012,
            rationale="real RTT exposed keepalive's effect",
            expected_class="loopback_resolution",
            citations=(citation,),
        )
        assert entry.verdict_changed is True
        assert len(entry.citations) == 1
        assert entry.citations[0].repo == "grpc/grpc"


class TestM5CrossHostBaselineValidation:
    def test_rejects_n_below_baseline_minimum(self) -> None:
        with pytest.raises(ValueError, match=r"n must be >= 100"):
            M5CrossHostBaseline(
                path="embed",
                cohort_id="embed|h4096|m1-baseline|m1_embed",
                modal_app_name="vllm-grpc-bench-mock",
                modal_region="eu-west-1",
                measured_rtt=RTTRecord(n=32, median_ms=40.0, p95_ms=60.0, samples_ms=(40.0,) * 32),
                n=50,
            )

    def test_accepts_n_exactly_100(self) -> None:
        baseline = M5CrossHostBaseline(
            path="embed",
            cohort_id="embed|h4096|m1-baseline|m1_embed",
            modal_app_name="vllm-grpc-bench-mock",
            modal_region="eu-west-1",
            measured_rtt=RTTRecord(n=32, median_ms=40.0, p95_ms=60.0, samples_ms=(40.0,) * 32),
            n=100,
        )
        assert baseline.n == 100


class TestNonDiscardedFilter:
    """non_discarded(cohorts) silently skips warm-up cohorts (R-5)."""

    def test_discarded_cohort_is_filtered_out(self) -> None:
        kept = _stub_cohort(discarded=False, cell_id_suffix="kept")
        discarded = _stub_cohort(discarded=True, cell_id_suffix="warmup")
        result = list(non_discarded([discarded, kept]))
        assert result == [kept]

    def test_no_discarded_cohorts_is_passthrough(self) -> None:
        # M3/M4 cohorts all have discarded=False — the helper must not alter
        # the iteration order in that case (deterministic recommendation
        # builder relies on cohort run-order).
        a = _stub_cohort(discarded=False, cell_id_suffix="a")
        b = _stub_cohort(discarded=False, cell_id_suffix="b")
        c = _stub_cohort(discarded=False, cell_id_suffix="c")
        result = list(non_discarded([a, b, c]))
        assert result == [a, b, c]

    def test_empty_iterable(self) -> None:
        assert list(non_discarded([])) == []
