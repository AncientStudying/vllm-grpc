"""Tests for m6_engine_cost parsers + drift function + aggregation (T013 / T051)."""

from __future__ import annotations

from typing import Any

from vllm_grpc_bench.m6_engine_cost import (
    aggregate_engine_cost_per_cell,
    compute_drift_warning,
    parse_grpc_trailing_metadata,
    parse_rest_response,
)
from vllm_grpc_bench.m6_types import EngineCostSpan

# --- parse_grpc_trailing_metadata --------------------------------------------


def test_parse_grpc_trailing_metadata_embed_happy_path() -> None:
    md = [("engine-forward-ms", "12.345")]
    span = parse_grpc_trailing_metadata(md, "embed")
    assert span is not None
    assert span.engine_forward_ms == 12.345
    assert span.engine_ttft_ms is None
    assert span.engine_tpot_ms is None


def test_parse_grpc_trailing_metadata_chat_stream_happy_path() -> None:
    md = [("engine-ttft-ms", "234.567"), ("engine-tpot-ms", "41.234")]
    span = parse_grpc_trailing_metadata(md, "chat_stream")
    assert span is not None
    assert span.engine_forward_ms is None
    assert span.engine_ttft_ms == 234.567
    assert span.engine_tpot_ms == 41.234


def test_parse_grpc_trailing_metadata_missing_embed_key_returns_none() -> None:
    assert parse_grpc_trailing_metadata([], "embed") is None


def test_parse_grpc_trailing_metadata_missing_chat_stream_key_returns_none() -> None:
    md = [("engine-ttft-ms", "100.0")]  # missing engine-tpot-ms
    assert parse_grpc_trailing_metadata(md, "chat_stream") is None


def test_parse_grpc_trailing_metadata_unparseable_value_returns_none() -> None:
    md = [("engine-forward-ms", "not_a_float")]
    assert parse_grpc_trailing_metadata(md, "embed") is None


# --- parse_rest_response -----------------------------------------------------


def test_parse_rest_response_embed_happy_path() -> None:
    body = {
        "object": "list",
        "data": [{"embedding": [1, 2, 3]}],
        "engine_cost": {"engine_forward_ms": 12.345},
    }
    span = parse_rest_response(body, "embed")
    assert span is not None
    assert span.engine_forward_ms == 12.345


def test_parse_rest_response_chat_stream_happy_path() -> None:
    body = {
        "id": "x",
        "choices": [{"finish_reason": "length"}],
        "engine_cost": {"engine_ttft_ms": 200.0, "engine_tpot_ms": 30.0},
    }
    span = parse_rest_response(body, "chat_stream")
    assert span is not None
    assert span.engine_ttft_ms == 200.0
    assert span.engine_tpot_ms == 30.0


def test_parse_rest_response_missing_engine_cost_returns_none() -> None:
    assert parse_rest_response({"data": []}, "embed") is None


def test_parse_rest_response_partial_chat_stream_returns_none() -> None:
    body = {"engine_cost": {"engine_ttft_ms": 200.0}}  # missing engine_tpot_ms
    assert parse_rest_response(body, "chat_stream") is None


# --- compute_drift_warning ---------------------------------------------------


def test_drift_warning_exact_10pct_does_not_trigger() -> None:
    # 100 vs 110 — exactly 10% disagreement; FR-014 says ">10%"
    means: dict[Any, float] = {
        "rest_https_edge": 100.0,
        "default_grpc": 110.0,
        "tuned_grpc_multiplexed": 100.0,
    }
    assert compute_drift_warning(means) is False


def test_drift_warning_10_1_pct_triggers() -> None:
    means: dict[Any, float] = {
        "rest_https_edge": 100.0,
        "default_grpc": 110.11,
        "tuned_grpc_multiplexed": 100.0,
    }
    assert compute_drift_warning(means) is True


def test_drift_warning_zero_value_skipped() -> None:
    # Degenerate case: division by zero would crash; FR-014 sub-clause skips.
    means: dict[Any, float] = {
        "rest_https_edge": 0.0,
        "default_grpc": 100.0,
        "tuned_grpc_multiplexed": 100.0,
    }
    # The 0-vs-100 pair is skipped; the 100-vs-100 pair has 0% disagreement.
    assert compute_drift_warning(means) is False


def test_drift_warning_single_cohort_returns_false() -> None:
    single: dict[Any, float] = {"rest_https_edge": 100.0}
    assert compute_drift_warning(single) is False


# --- aggregate_engine_cost_per_cell -----------------------------------------


def test_aggregate_engine_cost_embed_happy_path() -> None:
    spans = [EngineCostSpan(engine_forward_ms=v) for v in [10.0, 11.0, 12.0] * 5]  # n=15
    agg = aggregate_engine_cost_per_cell(spans, "embed")
    assert agg.engine_forward_mean_ms is not None
    assert abs(agg.engine_forward_mean_ms - 11.0) < 1e-6
    assert agg.engine_forward_ci_half_width_ms is not None
    assert agg.engine_forward_ci_half_width_ms > 0
    assert agg.engine_ttft_mean_ms is None


def test_aggregate_engine_cost_chat_stream_happy_path() -> None:
    spans = [
        EngineCostSpan(engine_ttft_ms=200.0 + i, engine_tpot_ms=30.0 + i * 0.1) for i in range(20)
    ]
    agg = aggregate_engine_cost_per_cell(spans, "chat_stream")
    assert agg.engine_ttft_mean_ms is not None
    assert agg.engine_tpot_mean_ms is not None
    assert agg.engine_forward_mean_ms is None


def test_aggregate_engine_cost_empty_returns_empty_aggregate() -> None:
    agg = aggregate_engine_cost_per_cell([], "embed")
    assert agg.engine_forward_mean_ms is None


# --- T051: precision test vs independent reference calculation --------------


def test_aggregate_engine_cost_embed_mean_and_ci_match_reference() -> None:
    """T051: aggregate output matches independent ``ci.estimate`` calc.

    Given a deterministic embed sample set, the aggregator's mean and 95%
    CI half-width must match what ``ci.estimate`` produces directly. This
    is the contract between Phase 2's parser/aggregator and Phase 3's
    classifier — the classifier's CI-overlap test depends on this match.
    """
    import math
    import statistics

    from vllm_grpc_bench.ci import estimate

    samples = [10.0, 11.0, 9.0, 10.5, 11.5, 10.2, 9.8, 10.7, 10.3, 9.9] * 3  # n=30
    spans = [EngineCostSpan(engine_forward_ms=s) for s in samples]
    agg = aggregate_engine_cost_per_cell(spans, "embed")
    ref = estimate(samples)
    assert agg.engine_forward_mean_ms is not None
    assert agg.engine_forward_ci_half_width_ms is not None
    assert math.isclose(agg.engine_forward_mean_ms, ref.mean, abs_tol=1e-9)
    ref_half = (ref.ci_high - ref.ci_low) / 2.0
    assert math.isclose(agg.engine_forward_ci_half_width_ms, ref_half, abs_tol=1e-9)
    # Sanity-check the reference calc against the textbook mean.
    assert math.isclose(ref.mean, statistics.mean(samples), abs_tol=1e-9)


def test_aggregate_engine_cost_chat_stream_ttft_and_tpot_independent() -> None:
    """For chat_stream cells, ttft and tpot aggregations are independent
    (different sample sets per the data-model.md contract).
    """
    import math

    from vllm_grpc_bench.ci import estimate

    ttft = [200.0 + i * 0.5 for i in range(30)]
    tpot = [30.0 + i * 0.1 for i in range(30)]
    spans = [EngineCostSpan(engine_ttft_ms=ttft[i], engine_tpot_ms=tpot[i]) for i in range(30)]
    agg = aggregate_engine_cost_per_cell(spans, "chat_stream")
    assert agg.engine_ttft_mean_ms is not None
    assert agg.engine_tpot_mean_ms is not None
    ref_ttft = estimate(ttft)
    ref_tpot = estimate(tpot)
    assert math.isclose(agg.engine_ttft_mean_ms, ref_ttft.mean, abs_tol=1e-9)
    assert math.isclose(agg.engine_tpot_mean_ms, ref_tpot.mean, abs_tol=1e-9)
    assert agg.engine_forward_mean_ms is None
