"""TTFT (time-to-first-token) helpers shared by the M3 reanalyze and M4
sweep paths (R-10).

The math used here is identical to ``m3_sweep._ttft_estimate_for_cohort`` —
extracted so M3's published TTFT numbers and M4's first-class TTFT verdicts
come from the same code path. M3's helper continues to delegate here.
"""

from __future__ import annotations

from vllm_grpc_bench.ci import estimate
from vllm_grpc_bench.m3_types import RunCohort


def ttft_samples(cohort: RunCohort) -> list[float]:
    """Per-sample TTFT values (seconds) for a chat_stream cohort.

    Embed cohorts and any chat_stream sample with no first-token timestamp
    (errored RPC, non-streaming response) contribute nothing.
    """
    return [
        s.time_to_first_token_seconds
        for s in cohort.samples
        if s.time_to_first_token_seconds is not None and s.error is None
    ]


def ttft_estimate(cohort: RunCohort) -> tuple[float, float, float, int] | None:
    """``(mean, ci_low, ci_high, n)`` from per-sample TTFTs.

    Returns ``None`` if fewer than the ``ci.estimate`` floor (n=10) of
    samples carry a TTFT — e.g. embed cohorts always return ``None``, and
    chat_stream cohorts whose RPCs all errored also return ``None``.
    """
    ttfts = ttft_samples(cohort)
    if len(ttfts) < 10:
        return None
    est = estimate(ttfts)
    return est.mean, est.ci_low, est.ci_high, est.n
