"""T074a — Modal-preemption mid-sweep detection classifier.

Exercises :func:`vllm_grpc_bench.m6_2_validate.is_modal_endpoint_death` and
the matching block-level predicate :func:`block_failed_with_endpoint_death`
against synthetic exception shapes drawn from the 2026-05-24 13:44 UTC
validate run that died at Modal worker preemption.

The classifier distinguishes endpoint-DEATH errors (Modal container gone,
endpoint URL stale, transport layer refusing the connection) from
generic transient errors (DEADLINE_EXCEEDED, slow-but-alive endpoints).
Endpoint-death exceptions trigger T074b's whole-block recovery path;
generic transient errors stay on FR-033's retry-once policy.
"""

from __future__ import annotations

import grpc
import httpx
import pytest
from vllm_grpc_bench.m6_2_validate import (
    block_failed_with_endpoint_death,
    is_modal_endpoint_death,
)


class _FakeRpcError(grpc.RpcError):
    """Minimal grpc.RpcError mock that exposes ``code()`` + ``details()``
    the way the real grpc.aio AioRpcError does. We don't import
    ``grpc.aio.AioRpcError`` directly because constructing one requires
    a live channel; this mock satisfies the duck-typed API the classifier
    actually inspects."""

    def __init__(self, code: grpc.StatusCode, details: str) -> None:
        super().__init__()
        self._code = code
        self._details = details

    def code(self) -> grpc.StatusCode:
        return self._code

    def details(self) -> str:
        return self._details


class TestIsModalEndpointDeathGrpc:
    """gRPC-side endpoint-death recognition.

    The signature observed in the live failed sweep was
    ``StatusCode.UNAVAILABLE`` with details containing
    "failed to connect to all addresses". The classifier requires BOTH
    the code AND the message fragment so it doesn't trip on
    UNAVAILABLE-with-different-cause (e.g. Modal frontend restart that
    completes within seconds — that's the FR-033 retry-once territory).
    """

    def test_unavailable_with_failed_to_connect_fragment_fires(self) -> None:
        exc = _FakeRpcError(
            code=grpc.StatusCode.UNAVAILABLE,
            details=(
                "failed to connect to all addresses; "
                "last error: UNKNOWN: ipv4:100.26.248.115:40471: F[ailed]"
            ),
        )
        assert is_modal_endpoint_death(exc) is True

    def test_cancelled_with_endpoint_fragment_fires(self) -> None:
        """A gRPC channel that gives up mid-call after the container died
        often surfaces as CANCELLED rather than UNAVAILABLE."""
        exc = _FakeRpcError(
            code=grpc.StatusCode.CANCELLED,
            details="connection refused after partial response",
        )
        assert is_modal_endpoint_death(exc) is True

    def test_unavailable_without_endpoint_fragment_does_not_fire(self) -> None:
        """Plain UNAVAILABLE without a transport-layer fragment is
        treated as a single-RPC transient — FR-033 retries it once."""
        exc = _FakeRpcError(
            code=grpc.StatusCode.UNAVAILABLE,
            details="server temporarily overloaded",
        )
        assert is_modal_endpoint_death(exc) is False

    def test_deadline_exceeded_does_not_fire(self) -> None:
        """Alive-but-slow endpoints surface as DEADLINE_EXCEEDED; that's
        :func:`is_transient_modal_error` territory, not preemption."""
        exc = _FakeRpcError(
            code=grpc.StatusCode.DEADLINE_EXCEEDED,
            details="failed to connect to all addresses",  # message would match, but code excludes
        )
        assert is_modal_endpoint_death(exc) is False

    def test_resource_exhausted_does_not_fire(self) -> None:
        exc = _FakeRpcError(
            code=grpc.StatusCode.RESOURCE_EXHAUSTED,
            details="kv cache full",
        )
        assert is_modal_endpoint_death(exc) is False

    def test_internal_does_not_fire(self) -> None:
        exc = _FakeRpcError(
            code=grpc.StatusCode.INTERNAL,
            details="internal error",
        )
        assert is_modal_endpoint_death(exc) is False

    def test_unauthenticated_does_not_fire(self) -> None:
        """UNAUTHENTICATED is a config error, never a preemption."""
        exc = _FakeRpcError(
            code=grpc.StatusCode.UNAUTHENTICATED,
            details="bearer token rejected",
        )
        assert is_modal_endpoint_death(exc) is False

    def test_message_match_is_case_insensitive(self) -> None:
        exc = _FakeRpcError(
            code=grpc.StatusCode.UNAVAILABLE,
            details="FAILED TO CONNECT TO ALL ADDRESSES",
        )
        assert is_modal_endpoint_death(exc) is True

    @pytest.mark.parametrize(
        "fragment",
        [
            "failed to connect to all addresses",
            "all connection attempts failed",
            "nodename nor servname provided",
            "name or service not known",
            "connection refused",
            "connection reset by peer",
            "no route to host",
            "broken pipe",
        ],
    )
    def test_each_message_fragment_recognised(self, fragment: str) -> None:
        exc = _FakeRpcError(
            code=grpc.StatusCode.UNAVAILABLE,
            details=f"prefix {fragment} suffix",
        )
        assert is_modal_endpoint_death(exc) is True


class TestIsModalEndpointDeathRest:
    """REST (httpx) endpoint-death recognition.

    The signatures observed in the live failed sweep:
    - ``httpx.ConnectError("All connection attempts failed")``
    - ``httpx.ConnectError("[Errno 8] nodename nor servname provided, or not known")``
    - ``httpx.ReadError(...)`` mid-stream

    ``httpx.ConnectError`` is treated as endpoint death unconditionally
    — by definition the connect failed, which means the cached URL is
    no longer reachable. ``ReadError`` is more ambiguous and requires
    an endpoint-death message fragment.
    """

    def test_connect_error_fires_unconditionally(self) -> None:
        assert is_modal_endpoint_death(httpx.ConnectError("anything")) is True

    def test_connect_error_with_dns_failure_fires(self) -> None:
        assert (
            is_modal_endpoint_death(
                httpx.ConnectError(
                    "[Errno 8] nodename nor servname provided, or not known"
                )
            )
            is True
        )

    def test_read_error_with_endpoint_fragment_fires(self) -> None:
        assert (
            is_modal_endpoint_death(
                httpx.ReadError("connection reset by peer mid-stream")
            )
            is True
        )

    def test_read_error_without_endpoint_fragment_does_not_fire(self) -> None:
        """Plain ReadError without a transport fragment could be a slow
        server giving up — FR-033 retry-once territory, not preemption."""
        assert is_modal_endpoint_death(httpx.ReadError("server closed stream")) is False

    def test_timeout_does_not_fire(self) -> None:
        """Timeout means alive-but-slow. Distinct from endpoint death."""
        assert is_modal_endpoint_death(httpx.ReadTimeout("read timed out")) is False
        assert is_modal_endpoint_death(httpx.ConnectTimeout("connect timed out")) is False

    def test_remote_protocol_error_does_not_fire(self) -> None:
        """HTTP/2 protocol error — server is alive but speaking
        incorrectly. Could recover on retry; not preemption."""
        assert (
            is_modal_endpoint_death(httpx.RemoteProtocolError("invalid frame"))
            is False
        )


class TestIsModalEndpointDeathNonNetwork:
    """Non-network exceptions must NEVER be misclassified as preemption —
    that would mask genuine bugs behind silent retry attempts."""

    def test_type_error_does_not_fire(self) -> None:
        assert is_modal_endpoint_death(TypeError("bad type")) is False

    def test_key_error_does_not_fire(self) -> None:
        assert is_modal_endpoint_death(KeyError("missing")) is False

    def test_runtime_error_does_not_fire(self) -> None:
        assert is_modal_endpoint_death(RuntimeError("oops")) is False

    def test_assertion_error_does_not_fire(self) -> None:
        assert is_modal_endpoint_death(AssertionError("bad assumption")) is False

    def test_value_error_does_not_fire(self) -> None:
        assert is_modal_endpoint_death(ValueError("bad value")) is False


class TestBlockFailedWithEndpointDeath:
    """The whole-block predicate gates T074b's recovery path.

    Recovery only triggers when EVERY RPC in the block failed with the
    endpoint-death signature — a single bad RPC could be transient. A
    Modal preemption, by contrast, kills every in-flight connection.
    """

    def _death_exc(self) -> grpc.RpcError:
        return _FakeRpcError(
            code=grpc.StatusCode.UNAVAILABLE,
            details="failed to connect to all addresses",
        )

    def test_all_n_death_exceptions_fires(self) -> None:
        exceptions = [self._death_exc() for _ in range(20)]
        assert block_failed_with_endpoint_death(exceptions, n=20) is True

    def test_one_success_one_death_does_not_fire(self) -> None:
        """Mixed outcomes — at least one RPC reached the engine — means
        the endpoint is still alive enough that a refresh isn't needed."""

        class _Success:
            success = True
            wall_clock_ms = 1.0
            m6_1_1_timing_payload: dict[str, object] = {}

        results: list[object] = [_Success(), self._death_exc()]
        assert block_failed_with_endpoint_death(results, n=2) is False

    def test_all_n_mixed_failure_types_does_not_fire(self) -> None:
        """All-fail but with different shapes — could be the engine
        wedged rather than the endpoint vanished. Treat as a normal
        block failure (FR-029), not a preemption."""
        results: list[object] = [
            self._death_exc(),
            _FakeRpcError(grpc.StatusCode.DEADLINE_EXCEEDED, "slow"),
            _FakeRpcError(grpc.StatusCode.RESOURCE_EXHAUSTED, "kv full"),
        ]
        assert block_failed_with_endpoint_death(results, n=3) is False

    def test_short_results_list_does_not_fire(self) -> None:
        """``len(results) != n`` — partial collection, treat conservatively
        as not-preemption so the caller's normal aggregation handles it."""
        exceptions = [self._death_exc() for _ in range(3)]
        assert block_failed_with_endpoint_death(exceptions, n=20) is False

    def test_empty_results_does_not_fire(self) -> None:
        assert block_failed_with_endpoint_death([], n=20) is False
        # n=0 edge case — vacuously all-failed, but no RPCs means no
        # signal worth recovering against.
        assert block_failed_with_endpoint_death([], n=0) is False

    def test_all_rest_connect_errors_fires(self) -> None:
        results: list[object] = [
            httpx.ConnectError("All connection attempts failed") for _ in range(20)
        ]
        assert block_failed_with_endpoint_death(results, n=20) is True

    def test_mixed_grpc_and_rest_endpoint_deaths_fires(self) -> None:
        """A whole sweep block dispatches against one cohort at a time,
        so this case is unlikely in practice — but the predicate is
        cohort-agnostic, and Modal's preemption is whole-container, so
        any all-endpoint-death pattern qualifies."""
        results: list[object] = [
            self._death_exc(),
            httpx.ConnectError("All connection attempts failed"),
            httpx.ReadError("connection refused"),
        ]
        assert block_failed_with_endpoint_death(results, n=3) is True
