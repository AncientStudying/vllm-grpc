"""New-home coverage for the de-prefixed ``types`` module (T023).

Asserts the closed 4-member cohort universe (SC-003 / clarify Q1), the
concurrency-collapse rule of :func:`cohorts_at_concurrency` (FR-011), and the
hoisted :class:`RPCResult` shape (formerly ``m6_sweep.RPCResult``).
"""

from __future__ import annotations

import typing

from vllm_grpc_bench.types import (
    COHORTS,
    CohortKind,
    RPCResult,
    cohorts_at_concurrency,
)


def test_cohort_kind_has_exactly_four_members() -> None:
    """The cohort universe is the closed 4-element forward set (SC-003)."""
    members = typing.get_args(CohortKind)
    assert len(members) == 4
    assert set(members) == {
        "rest_https_edge",
        "rest_plain_tcp",
        "default_grpc",
        "tuned_grpc_multiplexed",
    }


def test_cohorts_tuple_matches_cohort_kind() -> None:
    """``COHORTS`` is the runtime tuple mirror of the ``CohortKind`` literal."""
    assert len(COHORTS) == 4
    assert set(COHORTS) == set(typing.get_args(CohortKind))


def test_cohorts_at_concurrency_one_collapses_grpc() -> None:
    """At c==1 the two gRPC cohorts collapse to a single ``default_grpc`` (FR-011)."""
    cohorts = cohorts_at_concurrency(1)
    assert cohorts == ("default_grpc", "rest_https_edge", "rest_plain_tcp")
    assert "tuned_grpc_multiplexed" not in cohorts


def test_cohorts_at_concurrency_ge_two_is_all_four() -> None:
    """At c>=2 all four cohorts iterate, gRPC cohorts first."""
    for c in (2, 4, 8):
        cohorts = cohorts_at_concurrency(c)
        assert set(cohorts) == set(COHORTS)
        assert cohorts[:2] == ("default_grpc", "tuned_grpc_multiplexed")


def test_rpc_result_is_frozen() -> None:
    """``RPCResult`` is an immutable measurement record."""
    result = RPCResult(
        success=True,
        wall_clock_ms=12.5,
        ttft_ms=3.0,
        engine_cost=None,
        failure_reason=None,
    )
    assert result.success is True
    assert result.wall_clock_ms == 12.5
    assert result.m6_1_1_timing_payload is None
    import dataclasses

    try:
        result.success = False  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:  # pragma: no cover - frozen dataclass must reject mutation
        raise AssertionError("RPCResult should be frozen")
