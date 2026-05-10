"""US1 / FR-005 / R-11 — within-cohort CV is recorded, never aborts the run.

The earlier design (commit history) made CV overflow a fatal exit-3 abort.
The current model records per-cohort CV on every cohort, flags baselines
above ``--baseline-cv-warn`` with ``noisy_baseline=True``, and emits a
closing stderr warning. The run always proceeds to completion so that all
measurement data lands in the published report for post-hoc analysis.
"""

from __future__ import annotations

from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.m3_types import BenchmarkCell, RunCohort, Sample


def _baseline_cohort(
    values: list[float], *, time_cv: float | None = None, hidden_size: int = 4096
) -> RunCohort:
    cell = BenchmarkCell(
        path="embed",
        hidden_size=hidden_size,
        channel_config=M1_BASELINE,
        corpus_subset="m1_embed",
        iterations=len(values),
    )
    samples = tuple(
        Sample(
            cell_id=cell.cell_id,
            iteration=i,
            request_wire_bytes=100,
            response_wire_bytes=100,
            wall_clock_seconds=v,
        )
        for i, v in enumerate(values)
    )
    mean = sum(values) / len(values)
    return RunCohort(
        cell=cell,
        samples=samples,
        n_successful=len(values),
        bytes_mean=200.0,
        bytes_ci_low=199.0,
        bytes_ci_high=201.0,
        time_mean=mean,
        time_ci_low=mean * 0.99,
        time_ci_high=mean * 1.01,
        measurable=True,
        is_baseline=True,
        baseline_role="m1_shared",
        time_cv=time_cv,
    )


def _chat_baseline_cohort(
    walls: list[float], ttfts: list[float], *, time_cv=None, ttft_cv=None
) -> RunCohort:
    """chat_stream baseline cohort with independent wall/TTFT series."""
    assert len(walls) == len(ttfts)
    cell = BenchmarkCell(
        path="chat_stream",
        hidden_size=4096,
        channel_config=M1_BASELINE,
        corpus_subset="m1_chat",
        iterations=len(walls),
    )
    samples = tuple(
        Sample(
            cell_id=cell.cell_id,
            iteration=i,
            request_wire_bytes=100,
            response_wire_bytes=100,
            wall_clock_seconds=w,
            time_to_first_token_seconds=t,
            tokens_emitted=32,
        )
        for i, (w, t) in enumerate(zip(walls, ttfts, strict=True))
    )
    wall_mean = sum(walls) / len(walls)
    return RunCohort(
        cell=cell,
        samples=samples,
        n_successful=len(walls),
        bytes_mean=200.0,
        bytes_ci_low=199.0,
        bytes_ci_high=201.0,
        time_mean=wall_mean,
        time_ci_low=wall_mean * 0.99,
        time_ci_high=wall_mean * 1.01,
        measurable=True,
        is_baseline=True,
        baseline_role="m1_shared",
        time_cv=time_cv,
        ttft_cv=ttft_cv,
    )


class TestVerdictMetricCV:
    """``verdict_metric_cv`` returns the CV that drives the noisy-baseline flag."""

    def test_embed_uses_time_cv(self) -> None:
        from vllm_grpc_bench.m4_sweep import verdict_metric_cv

        cohort = _baseline_cohort([0.010] * 100, time_cv=0.0123)
        metric, cv = verdict_metric_cv(cohort)
        assert metric == "time"
        assert cv == 0.0123

    def test_chat_stream_uses_ttft_cv(self) -> None:
        from vllm_grpc_bench.m4_sweep import verdict_metric_cv

        # Wall-clock noisy (high time_cv), TTFT tight — chat_stream uses TTFT
        # so the gate must read ttft_cv, not time_cv. Mirrors the real shape:
        # under no-pacing, total wall-clock is dominated by per-token asyncio
        # yield jitter and is not the verdict metric.
        cohort = _chat_baseline_cohort(
            [0.010] * 100, [0.001] * 100, time_cv=0.20, ttft_cv=0.01
        )
        metric, cv = verdict_metric_cv(cohort)
        assert metric == "ttft"
        assert cv == 0.01


class TestFlagNoisyBaseline:
    """``flag_noisy_baseline`` records (does not raise) when CV exceeds threshold."""

    def test_under_threshold_returns_clean(self) -> None:
        from vllm_grpc_bench.m4_sweep import flag_noisy_baseline

        cohort = _baseline_cohort([0.010] * 100, time_cv=0.03)
        flagged = flag_noisy_baseline(cohort, baseline_cv_warn=0.05)
        assert flagged.noisy_baseline is False

    def test_over_threshold_sets_noisy_flag(self) -> None:
        """Critical contract: never raises, always returns the cohort."""
        from vllm_grpc_bench.m4_sweep import flag_noisy_baseline

        cohort = _baseline_cohort([0.010] * 100, time_cv=0.12)
        flagged = flag_noisy_baseline(cohort, baseline_cv_warn=0.05)
        assert flagged.noisy_baseline is True
        # Original cohort untouched (frozen dataclass).
        assert cohort.noisy_baseline is False

    def test_chat_stream_threshold_uses_ttft_cv(self) -> None:
        from vllm_grpc_bench.m4_sweep import flag_noisy_baseline

        # Wall-clock CV is huge but TTFT CV is tiny — chat_stream must NOT be
        # flagged because the verdict metric (TTFT) is well-behaved.
        cohort = _chat_baseline_cohort(
            [0.010] * 100, [0.001] * 100, time_cv=0.30, ttft_cv=0.01
        )
        flagged = flag_noisy_baseline(cohort, baseline_cv_warn=0.05)
        assert flagged.noisy_baseline is False

    def test_chat_stream_high_ttft_cv_is_flagged(self) -> None:
        from vllm_grpc_bench.m4_sweep import flag_noisy_baseline

        cohort = _chat_baseline_cohort(
            [0.010] * 100, [0.001] * 100, time_cv=0.01, ttft_cv=0.15
        )
        flagged = flag_noisy_baseline(cohort, baseline_cv_warn=0.05)
        assert flagged.noisy_baseline is True

    def test_missing_cv_passes_through(self) -> None:
        """Cohorts with too few samples to compute CV are not flagged."""
        from vllm_grpc_bench.m4_sweep import flag_noisy_baseline

        cohort = _baseline_cohort([0.010] * 100, time_cv=None)
        flagged = flag_noisy_baseline(cohort, baseline_cv_warn=0.05)
        assert flagged.noisy_baseline is False


class TestEmitNoisyBaselineWarning:
    def test_warns_only_for_flagged_baselines(self, capsys) -> None:
        from dataclasses import replace

        from vllm_grpc_bench.m4_sweep import emit_noisy_baseline_warning

        # Different widths give distinct cell_ids so the assertions below can
        # distinguish them.
        clean = _baseline_cohort([0.010] * 100, time_cv=0.03, hidden_size=2048)
        noisy = _baseline_cohort([0.010] * 100, time_cv=0.12, hidden_size=4096)
        noisy = replace(noisy, noisy_baseline=True)

        warned = emit_noisy_baseline_warning([clean, noisy], baseline_cv_warn=0.05)
        captured = capsys.readouterr()
        assert warned == [noisy.cell.cell_id]
        assert "WARNING" in captured.err
        assert noisy.cell.cell_id in captured.err
        assert "baseline-cv-warn=0.0500" in captured.err
        assert clean.cell.cell_id not in captured.err

    def test_silent_when_no_baselines_noisy(self, capsys) -> None:
        from vllm_grpc_bench.m4_sweep import emit_noisy_baseline_warning

        clean1 = _baseline_cohort([0.010] * 100, time_cv=0.03, hidden_size=2048)
        clean2 = _baseline_cohort([0.010] * 100, time_cv=0.04, hidden_size=4096)
        warned = emit_noisy_baseline_warning(
            [clean1, clean2], baseline_cv_warn=0.05
        )
        captured = capsys.readouterr()
        assert warned == []
        assert captured.err == ""

    def test_ignores_non_baseline_cohorts(self, capsys) -> None:
        """Candidate cohorts with high CV are not warned about — only baselines."""
        from dataclasses import replace

        from vllm_grpc_bench.m4_sweep import emit_noisy_baseline_warning

        candidate = _baseline_cohort([0.010] * 100, time_cv=0.12)
        candidate = replace(
            candidate, is_baseline=False, baseline_role=None, noisy_baseline=True
        )
        warned = emit_noisy_baseline_warning(
            [candidate], baseline_cv_warn=0.05
        )
        captured = capsys.readouterr()
        assert warned == []
        assert captured.err == ""


class TestNoAbort:
    """Smoke test that the public surface no longer carries the abort path."""

    def test_no_baseline_cv_error_in_module(self) -> None:
        from vllm_grpc_bench import m4_sweep

        assert not hasattr(m4_sweep, "BaselineCVError"), (
            "BaselineCVError was removed when FR-005 moved to record-and-report; "
            "see research.md R-11."
        )
        assert not hasattr(m4_sweep, "check_baseline_cv"), (
            "check_baseline_cv was renamed to flag_noisy_baseline (returns the "
            "cohort, never raises); see research.md R-11."
        )
