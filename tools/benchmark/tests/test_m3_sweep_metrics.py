"""Tests for the time/TTFT metric paths in ``m3_sweep.build_recommendations``.

Covers Phase A (US3) deliverables:

- ``metric="ttft"`` per-cohort estimate matches a hand-checked computation.
- Immediate-predecessor M1_BASELINE pairing (R-12) — when multiple baselines
  exist at the same ``(path, hidden_size, corpus_subset)``, the candidate is
  paired with the most recent preceding baseline in cohort run-order.
- ``noise_bounded`` verdict (FR-005) emitted when the predecessor pairing
  claims a win but the win does not survive at least one alternative
  same-cell M1_BASELINE.
- Bytes-path behaviour unchanged — fed the same group as a sanity check, the
  bytes path returns the verdict it would have under PR #17.
"""

from __future__ import annotations

import statistics

from vllm_grpc_bench.channel_config import (
    KEEPALIVE_AGGRESSIVE,
    KEEPALIVE_RELAXED,
    M1_BASELINE,
    MAX_MSG_16MIB,
    MAX_MSG_UNLIMITED,
)
from vllm_grpc_bench.ci import estimate
from vllm_grpc_bench.m3_sweep import _ttft_estimate_for_cohort, build_recommendations
from vllm_grpc_bench.m3_types import BenchmarkCell, Recommendation, RunCohort, Sample

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _make_cohort(
    *,
    path: str,
    hidden_size: int,
    config,  # type: ignore[no-untyped-def]
    corpus_subset: str,
    bytes_values: list[float] | None = None,
    time_values: list[float] | None = None,
    ttft_values: list[float] | None = None,
    iterations: int = 30,
) -> RunCohort:
    """Construct a RunCohort with synthetic sample data.

    Provide explicit per-iteration values for whichever metrics the test needs;
    the cohort-level mean+CI fields are derived via ``estimate()``.
    """
    bytes_values = bytes_values or [100.0] * iterations
    time_values = time_values or [0.1] * iterations
    samples: list[Sample] = []
    cell = BenchmarkCell(
        path=path,  # type: ignore[arg-type]
        hidden_size=hidden_size,
        channel_config=config,
        corpus_subset=corpus_subset,  # type: ignore[arg-type]
        iterations=iterations,
    )
    for i in range(iterations):
        ttft = ttft_values[i] if ttft_values else None
        samples.append(
            Sample(
                cell_id=cell.cell_id,
                iteration=i,
                request_wire_bytes=int(bytes_values[i] // 2),
                response_wire_bytes=int(bytes_values[i] - bytes_values[i] // 2),
                wall_clock_seconds=time_values[i],
                tokens_emitted=32 if path == "chat_stream" else None,
                time_to_first_token_seconds=ttft,
                mean_inter_token_seconds=None,
                inter_token_seconds_stddev=None,
            )
        )
    bytes_est = estimate(bytes_values)
    time_est = estimate(time_values)
    return RunCohort(
        cell=cell,
        samples=tuple(samples),
        n_successful=iterations,
        bytes_mean=bytes_est.mean,
        bytes_ci_low=bytes_est.ci_low,
        bytes_ci_high=bytes_est.ci_high,
        time_mean=time_est.mean,
        time_ci_low=time_est.ci_low,
        time_ci_high=time_est.ci_high,
        measurable=True,
    )


# ---------------------------------------------------------------------------
# TTFT computation
# ---------------------------------------------------------------------------


def test_ttft_estimate_matches_hand_computed_mean_and_ci() -> None:
    """``_ttft_estimate_for_cohort`` should return the same numbers as
    feeding the per-sample TTFTs into ``ci.estimate`` directly."""
    ttfts = [0.010, 0.011, 0.012, 0.011, 0.010, 0.013, 0.011, 0.010, 0.012, 0.011] * 3
    cohort = _make_cohort(
        path="chat_stream",
        hidden_size=4096,
        config=M1_BASELINE,
        corpus_subset="m1_chat",
        ttft_values=ttfts,
    )
    result = _ttft_estimate_for_cohort(cohort)
    assert result is not None
    mean, ci_low, ci_high, n = result
    expected = estimate(ttfts)
    assert n == 30
    assert abs(mean - expected.mean) < 1e-12
    assert abs(ci_low - expected.ci_low) < 1e-12
    assert abs(ci_high - expected.ci_high) < 1e-12
    assert abs(mean - statistics.fmean(ttfts)) < 1e-12


def test_ttft_estimate_returns_none_when_too_few_valid_samples() -> None:
    """ci.estimate refuses n<10; _ttft_estimate_for_cohort returns None when
    fewer than 10 samples carry a non-None TTFT."""
    # 30-iteration cohort but only 9 samples have a TTFT — the rest are None
    # (e.g. samples where the streaming RPC failed or never yielded a token).
    ttfts: list[float | None] = [0.010] * 9 + [None] * 21
    cohort = _make_cohort(
        path="chat_stream",
        hidden_size=4096,
        config=M1_BASELINE,
        corpus_subset="m1_chat",
        ttft_values=ttfts,  # type: ignore[arg-type]
    )
    assert _ttft_estimate_for_cohort(cohort) is None


def test_ttft_estimate_skips_failed_and_none_samples() -> None:
    """Samples with error!=None or TTFT=None are filtered out before
    aggregation; if the remainder is <10, return None."""
    ttfts = [0.010] * 10 + [None] * 20  # type: ignore[list-item]
    cohort = _make_cohort(
        path="chat_stream",
        hidden_size=4096,
        config=M1_BASELINE,
        corpus_subset="m1_chat",
        ttft_values=ttfts,  # type: ignore[arg-type]
    )
    result = _ttft_estimate_for_cohort(cohort)
    assert result is not None
    _mean, _low, _high, n = result
    assert n == 10  # Only the non-None samples count


# ---------------------------------------------------------------------------
# Immediate-predecessor pairing (R-12)
# ---------------------------------------------------------------------------


def test_immediate_predecessor_pairing_picks_most_recent_baseline() -> None:
    """When multiple M1_BASELINE cohorts at the same cell exist in run-order,
    a candidate is paired with the most-recent-preceding one — not the first."""
    # Run-order:
    #   baseline_A → keepalive-aggressive (cand_A) → baseline_B → keepalive-relaxed (cand_B)
    # Predecessor pairing: cand_A with baseline_A, cand_B with baseline_B.
    # Make baseline_A SLOW and baseline_B FAST so the wrong pairing yields a
    # different verdict from the correct one.
    cohorts: list[RunCohort] = [
        _make_cohort(  # baseline_A — slow
            path="embed",
            hidden_size=4096,
            config=M1_BASELINE,
            corpus_subset="m1_embed",
            time_values=[0.10] * 30,
        ),
        _make_cohort(  # keepalive-aggressive vs baseline_A: significantly faster
            path="embed",
            hidden_size=4096,
            config=KEEPALIVE_AGGRESSIVE,
            corpus_subset="m1_embed",
            time_values=[0.05] * 30,  # half — clears CI bar trivially
        ),
        _make_cohort(  # baseline_B — fast (matches cand_A's speed)
            path="embed",
            hidden_size=4096,
            config=M1_BASELINE,
            corpus_subset="m1_embed",
            time_values=[0.05] * 30,
        ),
        _make_cohort(  # keepalive-relaxed vs baseline_B: same speed → no win
            path="embed",
            hidden_size=4096,
            config=KEEPALIVE_RELAXED,
            corpus_subset="m1_embed",
            time_values=[0.05] * 30,
        ),
    ]
    recs = build_recommendations(cohorts, axis="keepalive", metric="time")
    # Both candidates' predecessor pairings should produce winner-vs-baseline_A
    # for cand_A (50% improvement) but at least one alt-baseline (baseline_B)
    # disagrees → noise_bounded.
    # cand_B vs baseline_B is no_winner (no improvement). The alt-baseline
    # baseline_A is even worse, so cand_B doesn't win against it either; verdict
    # is no_winner robustly.
    # Since both cands are in the same (path, width, corpus) group, only ONE
    # recommendation comes back — the noise-bounded one for the "would-be
    # winner" case.
    assert len(recs) == 1, f"expected 1 rec, got {len(recs)}: {recs}"
    rec = recs[0]
    assert rec.axis == "keepalive"
    assert rec.applies_to_path == "embed"
    assert rec.applies_to_widths == frozenset({4096})
    # The predecessor-paired win for cand_A would not survive against
    # baseline_B, so the verdict is noise_bounded.
    assert rec.verdict == "noise_bounded", rec
    assert rec.notes  # FR-005 invariant


def test_no_winner_with_consistent_baselines() -> None:
    """When no candidate beats its predecessor baseline, no_winner is robust
    and the cell is NOT demoted to noise_bounded."""
    cohorts: list[RunCohort] = [
        _make_cohort(
            path="embed",
            hidden_size=2048,
            config=M1_BASELINE,
            corpus_subset="m1_embed",
            time_values=[0.10] * 30,
        ),
        _make_cohort(
            path="embed",
            hidden_size=2048,
            config=MAX_MSG_16MIB,
            corpus_subset="m1_embed",
            time_values=[0.10] * 30,  # identical — no win
        ),
        _make_cohort(
            path="embed",
            hidden_size=2048,
            config=MAX_MSG_UNLIMITED,
            corpus_subset="m1_embed",
            time_values=[0.10] * 30,
        ),
    ]
    recs = build_recommendations(cohorts, axis="max_message_size", metric="time")
    assert len(recs) == 1
    assert recs[0].verdict == "no_winner"


def test_recommend_when_win_survives_all_baselines() -> None:
    """When the predecessor pairing claims a win and ALL alternative same-cell
    baselines also lose to the candidate, the verdict is recommend."""
    # Single baseline at this cell — no alternatives to check, win is robust.
    cohorts: list[RunCohort] = [
        _make_cohort(
            path="embed",
            hidden_size=4096,
            config=M1_BASELINE,
            corpus_subset="m1_embed",
            time_values=[0.10] * 30,
        ),
        _make_cohort(
            path="embed",
            hidden_size=4096,
            config=MAX_MSG_16MIB,
            corpus_subset="m1_embed",
            time_values=[0.05] * 30,  # 50% improvement, trivially clears CI
        ),
    ]
    recs = build_recommendations(cohorts, axis="max_message_size", metric="time")
    assert len(recs) == 1
    rec = recs[0]
    assert rec.verdict == "recommend"
    assert rec.winning_config is not None and rec.winning_config.name == "max-msg-16mib"
    assert rec.winning_metric == "time"
    assert rec.candidate_ci_lower is not None
    assert rec.candidate_ci_lower > rec.baseline_ci_upper  # SC-003 invariant


# ---------------------------------------------------------------------------
# noise_bounded emission
# ---------------------------------------------------------------------------


def test_noise_bounded_when_alternative_baseline_disagrees() -> None:
    """If the predecessor pairing claims a win but a DIFFERENT same-cell
    baseline would NOT, the verdict is demoted to noise_bounded."""
    # Setup — predecessor must be BETWEEN the two baselines in run-order:
    #   baseline_A (slow) → candidate (fast) → baseline_B (fast)
    # candidate's predecessor = baseline_A, which it beats → would-be win.
    # alternative baseline_B is fast, doesn't lose to candidate → noise_bounded.
    cohorts: list[RunCohort] = [
        _make_cohort(
            path="chat_stream",
            hidden_size=4096,
            config=M1_BASELINE,
            corpus_subset="m1_chat",
            time_values=[0.20] * 30,  # slow baseline
        ),
        _make_cohort(
            path="chat_stream",
            hidden_size=4096,
            config=KEEPALIVE_AGGRESSIVE,
            corpus_subset="m1_chat",
            time_values=[0.10] * 30,  # candidate, much faster than baseline_A
        ),
        _make_cohort(
            path="chat_stream",
            hidden_size=4096,
            config=M1_BASELINE,
            corpus_subset="m1_chat",
            time_values=[0.10] * 30,  # second baseline matches candidate's speed
        ),
    ]
    recs = build_recommendations(cohorts, axis="keepalive", metric="time")
    assert len(recs) == 1
    rec = recs[0]
    assert rec.verdict == "noise_bounded", rec
    assert "cross-batch baseline drift" in rec.notes.lower() or "spread" in rec.notes.lower()
    # FR-005 invariant: noise_bounded must have populated notes naming the noise source
    assert rec.notes
    assert "M4" in rec.notes  # Hand-off note


def test_noise_bounded_invariant_rejects_empty_notes() -> None:
    """The Recommendation dataclass refuses noise_bounded with empty notes."""
    import pytest

    with pytest.raises(ValueError, match="notes field"):
        Recommendation(
            axis="keepalive",
            applies_to_path="chat_stream",
            applies_to_widths=frozenset({4096}),
            verdict="noise_bounded",
            baseline_ci_upper=0.5,
            citation="some citation",
            notes="",
        )


# ---------------------------------------------------------------------------
# TTFT metric path (chat_stream-only)
# ---------------------------------------------------------------------------


def test_ttft_metric_only_emits_chat_stream_recommendations() -> None:
    """metric="ttft" should skip embed cells (TTFT is undefined off streaming)."""
    cohorts: list[RunCohort] = [
        _make_cohort(  # embed cell — no TTFT
            path="embed",
            hidden_size=4096,
            config=M1_BASELINE,
            corpus_subset="m1_embed",
        ),
        _make_cohort(
            path="embed",
            hidden_size=4096,
            config=MAX_MSG_16MIB,
            corpus_subset="m1_embed",
        ),
        _make_cohort(  # chat_stream cell — has TTFT
            path="chat_stream",
            hidden_size=4096,
            config=M1_BASELINE,
            corpus_subset="m1_chat",
            ttft_values=[0.010] * 30,
        ),
        _make_cohort(
            path="chat_stream",
            hidden_size=4096,
            config=MAX_MSG_16MIB,
            corpus_subset="m1_chat",
            ttft_values=[0.010] * 30,
        ),
    ]
    recs = build_recommendations(cohorts, axis="max_message_size", metric="ttft")
    paths = {r.applies_to_path for r in recs}
    assert paths == {"chat_stream"}, recs


def test_ttft_recommendation_carries_ttft_winning_metric_label() -> None:
    """When ttft metric produces a recommend, winning_metric must be 'ttft'."""
    cohorts: list[RunCohort] = [
        _make_cohort(
            path="chat_stream",
            hidden_size=4096,
            config=M1_BASELINE,
            corpus_subset="m1_chat",
            ttft_values=[0.020] * 30,
        ),
        _make_cohort(
            path="chat_stream",
            hidden_size=4096,
            config=KEEPALIVE_AGGRESSIVE,
            corpus_subset="m1_chat",
            ttft_values=[0.010] * 30,  # half TTFT
        ),
    ]
    recs = build_recommendations(cohorts, axis="keepalive", metric="ttft")
    assert len(recs) == 1
    rec = recs[0]
    assert rec.verdict == "recommend"
    assert rec.winning_metric == "ttft"


# ---------------------------------------------------------------------------
# Bytes-path no-regression sanity check
# ---------------------------------------------------------------------------


def test_bytes_path_unchanged_for_simple_no_winner_case() -> None:
    """With identical bytes across baseline + candidates, the bytes path
    emits no_winner exactly like PR #17 did."""
    cohorts: list[RunCohort] = [
        _make_cohort(
            path="embed",
            hidden_size=2048,
            config=M1_BASELINE,
            corpus_subset="m1_embed",
            bytes_values=[131143.0] * 30,
        ),
        _make_cohort(
            path="embed",
            hidden_size=2048,
            config=MAX_MSG_16MIB,
            corpus_subset="m1_embed",
            bytes_values=[131143.0] * 30,
        ),
        _make_cohort(
            path="embed",
            hidden_size=2048,
            config=MAX_MSG_UNLIMITED,
            corpus_subset="m1_embed",
            bytes_values=[131143.0] * 30,
        ),
    ]
    recs = build_recommendations(cohorts, axis="max_message_size", metric="bytes")
    assert len(recs) == 1
    assert recs[0].verdict == "no_winner"
    # Bytes path doesn't populate corpus_subset (PR #17 behavior preserved).
    assert recs[0].corpus_subset is None


def test_corpus_subset_separates_long_stream_recommendations_on_time_path() -> None:
    """The time-axis path groups by (path, width, corpus_subset) so the
    long-stream cohort gets its own verdict, distinct from the m1_chat one."""
    cohorts: list[RunCohort] = [
        # m1_chat cohort
        _make_cohort(
            path="chat_stream",
            hidden_size=4096,
            config=M1_BASELINE,
            corpus_subset="m1_chat",
            time_values=[0.20] * 30,
        ),
        _make_cohort(
            path="chat_stream",
            hidden_size=4096,
            config=KEEPALIVE_AGGRESSIVE,
            corpus_subset="m1_chat",
            time_values=[0.20] * 30,  # no win
        ),
        # m3_long_stream cohort (separate baseline + candidate)
        _make_cohort(
            path="chat_stream",
            hidden_size=4096,
            config=M1_BASELINE,
            corpus_subset="m3_long_stream",
            time_values=[50.0] * 30,
        ),
        _make_cohort(
            path="chat_stream",
            hidden_size=4096,
            config=KEEPALIVE_AGGRESSIVE,
            corpus_subset="m3_long_stream",
            time_values=[50.0] * 30,  # no win
        ),
    ]
    recs = build_recommendations(cohorts, axis="keepalive", metric="time")
    # Two recommendations — one per corpus_subset.
    assert len(recs) == 2
    corpus_subsets = {r.corpus_subset for r in recs}
    assert corpus_subsets == {"m1_chat", "m3_long_stream"}
    for r in recs:
        assert r.verdict == "no_winner"
