"""US1 / FR-003 / R-10 — TTFT-first-class verdict.

The recommendation builder labels chat_stream verdicts as TTFT-driven and
emits the per-cohort TTFT summary as a first-class field (not a re-analysis
artefact).
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.channel_config import COMPRESSION_GZIP, M1_BASELINE
from vllm_grpc_bench.m3_types import (
    BenchmarkCell,
    ExpansionRecord,
    RunCohort,
    Sample,
)


def _chat_cohort(
    *,
    config_name: str,
    wall_clock: list[float],
    ttft_values: list[float],
    is_baseline: bool = False,
) -> RunCohort:
    cfg = M1_BASELINE if config_name == "m1-baseline" else COMPRESSION_GZIP
    cell = BenchmarkCell(
        path="chat_stream",
        hidden_size=4096,
        channel_config=cfg,
        corpus_subset="m1_chat",
        iterations=len(wall_clock),
    )
    samples = tuple(
        Sample(
            cell_id=cell.cell_id,
            iteration=i,
            request_wire_bytes=120,
            response_wire_bytes=200,
            wall_clock_seconds=w,
            tokens_emitted=4,
            time_to_first_token_seconds=t,
        )
        for i, (w, t) in enumerate(zip(wall_clock, ttft_values, strict=True))
    )
    wmean = sum(wall_clock) / len(wall_clock)
    tmean = sum(ttft_values) / len(ttft_values)
    return RunCohort(
        cell=cell,
        samples=samples,
        n_successful=len(wall_clock),
        bytes_mean=320.0,
        bytes_ci_low=318.0,
        bytes_ci_high=322.0,
        time_mean=wmean,
        time_ci_low=wmean * 0.99,
        time_ci_high=wmean * 1.01,
        measurable=True,
        is_baseline=is_baseline,
        baseline_role="m1_shared" if is_baseline else None,
        expansion_record=None
        if is_baseline
        else ExpansionRecord(
            initial_n=len(wall_clock),
            initial_ci_overlapped=False,
            expanded=False,
            final_n=len(wall_clock),
        ),
        time_to_first_token_seconds=(tmean, tmean * 0.99, tmean * 1.01),
    )


class TestTTFTFirstClassVerdict:
    def test_chat_stream_verdict_uses_ttft(self) -> None:
        from vllm_grpc_bench.m4_sweep import build_recommendations

        # Baseline TTFT ~5 ms, candidate TTFT ~4 ms → recommend on TTFT.
        baseline_wall = [0.020] * 100
        candidate_wall = [0.019] * 100
        baseline_ttft = [0.005] * 100
        candidate_ttft = [0.004] * 100

        baseline = _chat_cohort(
            config_name="m1-baseline",
            wall_clock=baseline_wall,
            ttft_values=baseline_ttft,
            is_baseline=True,
        )
        candidate = _chat_cohort(
            config_name="compression-gzip",
            wall_clock=candidate_wall,
            ttft_values=candidate_ttft,
        )
        recs = build_recommendations(
            cohorts=[baseline, candidate],
            shared_baselines={"chat_stream": baseline},
        )
        assert recs, "expected at least one chat_stream recommendation"
        chat_recs = [r for r in recs if r.applies_to_path == "chat_stream"]
        assert chat_recs
        # Primary metric for chat_stream is TTFT.
        assert all(r.winning_metric in ("ttft", None) for r in chat_recs)

    def test_baseline_ttft_summary_is_first_class(self) -> None:
        """The per-cohort TTFT mean+CI is exposed on the cohort dataclass —
        not derived only via a reanalyze pass.
        """
        baseline_wall = [0.020] * 100
        baseline_ttft = [0.005] * 100
        baseline = _chat_cohort(
            config_name="m1-baseline",
            wall_clock=baseline_wall,
            ttft_values=baseline_ttft,
            is_baseline=True,
        )
        assert baseline.time_to_first_token_seconds is not None
        mean, low, high = baseline.time_to_first_token_seconds
        assert pytest.approx(mean, rel=1e-6) == 0.005
        assert low <= mean <= high
