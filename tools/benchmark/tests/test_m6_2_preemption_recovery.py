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

from types import SimpleNamespace
from typing import Any

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
                httpx.ConnectError("[Errno 8] nodename nor servname provided, or not known")
            )
            is True
        )

    def test_read_error_with_endpoint_fragment_fires(self) -> None:
        assert (
            is_modal_endpoint_death(httpx.ReadError("connection reset by peer mid-stream")) is True
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
        assert is_modal_endpoint_death(httpx.RemoteProtocolError("invalid frame")) is False


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


# T074b / T074c — block-level recovery wrapper + budget enforcement ---------


@pytest.fixture
def _fake_rpc_success() -> Any:
    """Build an RPCResult-shaped success record. The dispatcher inspects
    ``success`` / ``wall_clock_ms`` / ``m6_1_1_timing_payload`` /
    ``engine_cost`` via ``getattr``, so a small SimpleNamespace satisfies
    the duck-type."""
    from types import SimpleNamespace

    return SimpleNamespace(
        success=True,
        wall_clock_ms=42.0,
        m6_1_1_timing_payload={},
        engine_cost=None,
        failure_reason=None,
    )


class _RecordingDriver:
    """Test double for an M6_2RPCDriver. Each call appends its
    (cohort, cell, seed, kwargs) tuple to ``calls`` and returns the
    next ``yield_each`` element (either an RPCResult-shaped object or an
    exception to raise).

    Cycles back to the start of ``yield_each`` once exhausted so a test
    can drive an arbitrary number of RPCs."""

    def __init__(self, yield_each: list[Any]) -> None:
        self.yield_each = yield_each
        self.calls: list[tuple[Any, ...]] = []
        self._idx = 0

    async def __call__(
        self,
        cohort: Any,
        cell: Any,
        seed: int,
        *,
        max_tokens: int,
        ignore_eos: bool,
        prompt: Any,
        prompt_embeds_override: Any,
    ) -> Any:
        self.calls.append((cohort, cell, seed, max_tokens, ignore_eos))
        value = self.yield_each[self._idx % len(self.yield_each)]
        self._idx += 1
        if isinstance(value, BaseException):
            raise value
        return value


def _dead_endpoint_exc() -> grpc.RpcError:
    return _FakeRpcError(
        code=grpc.StatusCode.UNAVAILABLE,
        details="failed to connect to all addresses",
    )


def _block_inputs(prompt: str = "hello") -> dict[str, Any]:
    return {
        "prompt_text": prompt,
        "embed_tensor_bytes": None,
        "ignore_eos": False,
        "prompt_source": "synthetic_seed_derived",
        "prompt_corpus_idx": None,
    }


class TestBlockDispatcherRecoveryHappyPath:
    """T074b: when all n RPCs fail with endpoint-death AND make_driver
    is supplied, the dispatcher refreshes the driver and retries the
    block. A second-try success closes the recovery cycle cleanly."""

    @pytest.mark.asyncio
    async def test_recovery_on_first_preemption_succeeds(self, _fake_rpc_success: Any) -> None:
        from vllm_grpc_bench.m6_2_validate import build_modal_block_dispatcher

        dead = _RecordingDriver(yield_each=[_dead_endpoint_exc()])
        fresh = _RecordingDriver(yield_each=[_fake_rpc_success])

        async def make_driver() -> Any:
            return fresh

        dispatcher = build_modal_block_dispatcher(dead, base_seed=42, make_driver=make_driver)
        result = await dispatcher(
            cell_id="embed_c1",
            cohort="default_grpc",
            max_tokens=10,
            n=4,
            block_inputs=_block_inputs(),
        )
        assert result.failed_reason is None, "post-recovery block must succeed"
        assert len(result.timings_ms) == 4
        # All 4 RPCs against the dead driver, then 4 RPCs against the fresh one.
        assert len(dead.calls) == 4
        assert len(fresh.calls) == 4
        assert dispatcher.preemption_events() == 1  # type: ignore[attr-defined]
        assert dispatcher.preemption_budget == 2  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_no_recovery_when_make_driver_is_none(self, _fake_rpc_success: Any) -> None:
        """Backward compatibility: ``make_driver=None`` (the default)
        disables recovery entirely. The pre-T074 behaviour is preserved
        and the block fails with the usual aggregation path."""
        from vllm_grpc_bench.m6_2_validate import build_modal_block_dispatcher

        dead = _RecordingDriver(yield_each=[_dead_endpoint_exc()])
        dispatcher = build_modal_block_dispatcher(dead, base_seed=42)
        result = await dispatcher(
            cell_id="embed_c1",
            cohort="default_grpc",
            max_tokens=10,
            n=4,
            block_inputs=_block_inputs(),
        )
        assert result.failed_reason is not None, "no recovery → block must fail"
        assert "grpc" in result.failed_reason.lower()
        assert len(dead.calls) == 4  # only the original attempt
        assert dispatcher.preemption_events() == 0  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_no_recovery_when_only_some_rpcs_fail(self, _fake_rpc_success: Any) -> None:
        """Only a WHOLE-block endpoint-death pattern triggers recovery.
        Mixed success / failure stays on the normal aggregation path
        (some timings recorded, ``failed_reason=None`` if at least one
        RPC succeeded)."""
        from vllm_grpc_bench.m6_2_validate import build_modal_block_dispatcher

        # Interleave 2 successes and 2 dead-endpoint exceptions.
        driver = _RecordingDriver(
            yield_each=[
                _fake_rpc_success,
                _dead_endpoint_exc(),
                _fake_rpc_success,
                _dead_endpoint_exc(),
            ]
        )

        async def make_driver() -> Any:
            raise AssertionError("make_driver MUST NOT be invoked on partial failure")

        dispatcher = build_modal_block_dispatcher(driver, base_seed=42, make_driver=make_driver)
        result = await dispatcher(
            cell_id="embed_c1",
            cohort="default_grpc",
            max_tokens=10,
            n=4,
            block_inputs=_block_inputs(),
        )
        assert len(result.timings_ms) == 2  # the two successes
        assert dispatcher.preemption_events() == 0  # type: ignore[attr-defined]


class TestBlockDispatcherRecoveryBudget:
    """T074c FR-026 budget enforcement: after
    ``M6_2_PREEMPTION_RECURRENCE_THRESHOLD`` successful recoveries, the
    next detected preemption raises :class:`PreemptionBudgetExhausted`
    so the orchestrator can abort the sweep cleanly."""

    @pytest.mark.asyncio
    async def test_budget_exhausted_raises_after_threshold(self, _fake_rpc_success: Any) -> None:
        from vllm_grpc_bench.m6_2_validate import (
            PreemptionBudgetExhausted,
            build_modal_block_dispatcher,
        )

        always_dead = _RecordingDriver(yield_each=[_dead_endpoint_exc()])

        async def make_driver() -> Any:
            # The "refreshed" driver is ALSO dead — Modal kept getting
            # preempted on the new container too. Realistic worst case.
            return _RecordingDriver(yield_each=[_dead_endpoint_exc()])

        dispatcher = build_modal_block_dispatcher(
            always_dead, base_seed=42, make_driver=make_driver, preemption_budget=2
        )
        with pytest.raises(PreemptionBudgetExhausted, match="FR-026"):
            await dispatcher(
                cell_id="embed_c1",
                cohort="default_grpc",
                max_tokens=10,
                n=4,
                block_inputs=_block_inputs(),
            )
        # Counter should reflect the 2 successful (well, attempted)
        # recoveries before the 3rd detection raised.
        assert dispatcher.preemption_events() == 2  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_recovery_failed_raises_when_make_driver_throws(
        self,
    ) -> None:
        from vllm_grpc_bench.m6_2_validate import (
            PreemptionRecoveryFailed,
            build_modal_block_dispatcher,
        )

        dead = _RecordingDriver(yield_each=[_dead_endpoint_exc()])

        async def make_driver() -> Any:
            raise TimeoutError("Modal endpoint refresh timed out — new container never published")

        dispatcher = build_modal_block_dispatcher(dead, base_seed=42, make_driver=make_driver)
        with pytest.raises(PreemptionRecoveryFailed, match="TimeoutError"):
            await dispatcher(
                cell_id="embed_c1",
                cohort="default_grpc",
                max_tokens=10,
                n=4,
                block_inputs=_block_inputs(),
            )
        # Recovery never completed → counter stays at 0 (the recovery
        # cycle wasn't successful, so we don't count it against the
        # FR-026 budget).
        assert dispatcher.preemption_events() == 0  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_budget_constant_is_two(self) -> None:
        """The FR-026 threshold is load-bearing for the sweep-abort
        contract; a silent drift would change when the orchestrator
        gives up vs spins forever."""
        from vllm_grpc_bench.m6_2_validate import (
            M6_2_PREEMPTION_RECURRENCE_THRESHOLD,
        )

        assert M6_2_PREEMPTION_RECURRENCE_THRESHOLD == 2

    @pytest.mark.asyncio
    async def test_recovery_within_budget_succeeds(self, _fake_rpc_success: Any) -> None:
        """Two preemptions in a row, both recover successfully (third
        block succeeds) → no abort, the dispatcher returns a normal
        BlockDispatchResult."""
        from vllm_grpc_bench.m6_2_validate import build_modal_block_dispatcher

        dead1 = _RecordingDriver(yield_each=[_dead_endpoint_exc()])
        dead2 = _RecordingDriver(yield_each=[_dead_endpoint_exc()])
        fresh = _RecordingDriver(yield_each=[_fake_rpc_success])
        sequence = iter([dead2, fresh])

        async def make_driver() -> Any:
            return next(sequence)

        dispatcher = build_modal_block_dispatcher(
            dead1, base_seed=42, make_driver=make_driver, preemption_budget=2
        )
        result = await dispatcher(
            cell_id="embed_c1",
            cohort="default_grpc",
            max_tokens=10,
            n=4,
            block_inputs=_block_inputs(),
        )
        assert result.failed_reason is None, "second-recovery success must succeed"
        assert len(result.timings_ms) == 4
        assert dispatcher.preemption_events() == 2  # type: ignore[attr-defined]


class TestBuildModalMakeDriverCallable:
    """T074d: the production ``make_driver`` factory wraps
    ``modal_endpoint.refresh_rest_grpc_urls`` (real Modal Dict polling) and
    ``m6_2_rpc_driver.provide_m6_2_rpc_driver`` (real gRPC channel +
    httpx client). Both are monkey-patched so the test exercises the
    factory's lifecycle wiring without a Modal connection.
    """

    @pytest.mark.asyncio
    async def test_initial_driver_returned_from_provide(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import contextlib as _contextlib

        from vllm_grpc_bench.m6_2_validate import build_modal_make_driver_callable

        opened_endpoints: list[Any] = []
        closed_count = {"n": 0}

        @_contextlib.asynccontextmanager
        async def _fake_provide_driver(eps: Any, *, seq_len: int, base_seed: int) -> Any:
            opened_endpoints.append(eps)
            driver = _RecordingDriver(yield_each=[])
            try:
                yield driver, {}
            finally:
                closed_count["n"] += 1

        monkeypatch.setattr(
            "vllm_grpc_bench.m6_2_rpc_driver.provide_m6_2_rpc_driver",
            _fake_provide_driver,
        )
        initial_endpoints = SimpleNamespace(
            grpc_url="host:1",
            rest_url="https://rest.example/",
            auth_token_env_var="X",
            rest_plain_tcp_url="http://tcp.example/",
            rest_https_edge_url="https://edge.example/",
        )

        async with _contextlib.AsyncExitStack() as outer_stack:
            (
                initial_driver,
                _make_driver,
                get_current_endpoints,
            ) = await build_modal_make_driver_callable(
                initial_endpoints=initial_endpoints,
                seq_len=19,
                base_seed=42,
                outer_stack=outer_stack,
            )
            assert isinstance(initial_driver, _RecordingDriver)
            assert opened_endpoints == [initial_endpoints]
            assert get_current_endpoints() is initial_endpoints
        # Outer stack closes the driver context at exit.
        assert closed_count["n"] == 1

    @pytest.mark.asyncio
    async def test_make_driver_refreshes_and_swaps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the Modal Dict publishes fresh URLs (gRPC URL differs),
        make_driver closes the old driver context, opens a new one against
        the refreshed URLs, and returns the new driver."""
        import contextlib as _contextlib

        from vllm_grpc_bench.m6_2_validate import build_modal_make_driver_callable

        initial_endpoints = SimpleNamespace(
            grpc_url="old-host:1",
            rest_url="https://old.example/",
            auth_token_env_var="X",
            rest_plain_tcp_url="http://old.example/",
            rest_https_edge_url="https://old.example/",
        )
        refreshed_endpoints = SimpleNamespace(
            grpc_url="new-host:2",
            rest_url="https://new.example/",
            auth_token_env_var="X",
            rest_plain_tcp_url="http://new.example/",
            rest_https_edge_url="https://new.example/",
        )

        async def _fake_refresh(cached: Any, *, poll_timeout_s: float = 600.0) -> Any:
            return refreshed_endpoints

        opened_endpoints: list[Any] = []
        close_log: list[int] = []

        @_contextlib.asynccontextmanager
        async def _fake_provide_driver(eps: Any, *, seq_len: int, base_seed: int) -> Any:
            opened_endpoints.append(eps)
            idx = len(opened_endpoints) - 1
            driver = _RecordingDriver(yield_each=[])
            try:
                yield driver, {}
            finally:
                close_log.append(idx)

        monkeypatch.setattr(
            "vllm_grpc_bench.modal_endpoint.refresh_rest_grpc_urls",
            _fake_refresh,
        )
        monkeypatch.setattr(
            "vllm_grpc_bench.m6_2_rpc_driver.provide_m6_2_rpc_driver",
            _fake_provide_driver,
        )

        async with _contextlib.AsyncExitStack() as outer_stack:
            (
                initial_driver,
                make_driver,
                get_current_endpoints,
            ) = await build_modal_make_driver_callable(
                initial_endpoints=initial_endpoints,
                seq_len=19,
                base_seed=42,
                outer_stack=outer_stack,
            )
            assert get_current_endpoints() is initial_endpoints

            new_driver = await make_driver()
            assert isinstance(new_driver, _RecordingDriver)
            assert new_driver is not initial_driver
            assert opened_endpoints == [initial_endpoints, refreshed_endpoints]
            # Old (index 0) driver context closed by the recovery, new (1)
            # still open until the outer stack exits.
            assert close_log == [0]
            assert get_current_endpoints() is refreshed_endpoints

        # Outer stack exit closes the second driver context.
        assert close_log == [0, 1]

    @pytest.mark.asyncio
    async def test_make_driver_raises_when_refresh_times_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When refresh_rest_grpc_urls returns None (no fresh URLs within
        timeout), make_driver raises RuntimeError. The dispatcher wraps
        that in PreemptionRecoveryFailed; either way the orchestrator
        aborts cleanly."""
        import contextlib as _contextlib

        from vllm_grpc_bench.m6_2_validate import build_modal_make_driver_callable

        initial_endpoints = SimpleNamespace(
            grpc_url="host:1",
            rest_url="https://rest.example/",
            auth_token_env_var="X",
            rest_plain_tcp_url="http://tcp.example/",
            rest_https_edge_url="https://edge.example/",
        )

        async def _fake_refresh_returns_none(cached: Any, *, poll_timeout_s: float = 600.0) -> Any:
            return None

        @_contextlib.asynccontextmanager
        async def _fake_provide_driver(eps: Any, *, seq_len: int, base_seed: int) -> Any:
            yield _RecordingDriver(yield_each=[]), {}

        monkeypatch.setattr(
            "vllm_grpc_bench.modal_endpoint.refresh_rest_grpc_urls",
            _fake_refresh_returns_none,
        )
        monkeypatch.setattr(
            "vllm_grpc_bench.m6_2_rpc_driver.provide_m6_2_rpc_driver",
            _fake_provide_driver,
        )

        async with _contextlib.AsyncExitStack() as outer_stack:
            (
                _initial,
                make_driver,
                _get,
            ) = await build_modal_make_driver_callable(
                initial_endpoints=initial_endpoints,
                seq_len=19,
                base_seed=42,
                outer_stack=outer_stack,
                refresh_timeout_s=1.0,
            )
            with pytest.raises(RuntimeError, match="no fresh URLs"):
                await make_driver()

    @pytest.mark.asyncio
    async def test_make_driver_survives_multiple_recoveries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two consecutive preemption recoveries (the FR-026 budget) — both
        succeed. Each one swaps in a fresh driver and the outer stack
        accumulates the contexts for cleanup."""
        import contextlib as _contextlib

        from vllm_grpc_bench.m6_2_validate import build_modal_make_driver_callable

        endpoints_seq = [
            SimpleNamespace(
                grpc_url=f"host-{i}:1",
                rest_url=f"https://h{i}.example/",
                auth_token_env_var="X",
                rest_plain_tcp_url=f"http://h{i}.example/",
                rest_https_edge_url=f"https://h{i}.example/",
            )
            for i in range(3)
        ]
        refresh_calls = iter(endpoints_seq[1:])

        async def _fake_refresh(cached: Any, *, poll_timeout_s: float = 600.0) -> Any:
            return next(refresh_calls)

        opened: list[Any] = []
        closed: list[int] = []

        @_contextlib.asynccontextmanager
        async def _fake_provide_driver(eps: Any, *, seq_len: int, base_seed: int) -> Any:
            idx = len(opened)
            opened.append(eps)
            try:
                yield _RecordingDriver(yield_each=[]), {}
            finally:
                closed.append(idx)

        monkeypatch.setattr(
            "vllm_grpc_bench.modal_endpoint.refresh_rest_grpc_urls",
            _fake_refresh,
        )
        monkeypatch.setattr(
            "vllm_grpc_bench.m6_2_rpc_driver.provide_m6_2_rpc_driver",
            _fake_provide_driver,
        )

        async with _contextlib.AsyncExitStack() as outer_stack:
            (
                _initial,
                make_driver,
                get_endpoints,
            ) = await build_modal_make_driver_callable(
                initial_endpoints=endpoints_seq[0],
                seq_len=19,
                base_seed=42,
                outer_stack=outer_stack,
            )
            await make_driver()
            assert get_endpoints() is endpoints_seq[1]
            await make_driver()
            assert get_endpoints() is endpoints_seq[2]
            assert opened == endpoints_seq
            # Two driver contexts closed during recovery; the third still
            # open until the outer stack exit.
            assert closed == [0, 1]
        # Outer stack exit closes the final driver context.
        assert closed == [0, 1, 2]


class TestAnchorDispatcherRecovery:
    """T074e: the FR-031 anchor dispatcher gets the same recovery loop
    as the block dispatcher. When all n anchor RPCs fail with
    endpoint-death shapes AND make_driver is supplied, the dispatcher
    emits PREEMPTION_DETECTED phase=anchor, refreshes the driver,
    emits PREEMPTION_RECOVERED phase=anchor, and retries the anchor.
    """

    @pytest.mark.asyncio
    async def test_anchor_recovery_on_first_preemption_succeeds(
        self, _fake_rpc_success: Any
    ) -> None:
        from vllm_grpc_bench.m6_2_validate import build_modal_anchor_dispatcher

        dead = _RecordingDriver(yield_each=[_dead_endpoint_exc()])
        fresh = _RecordingDriver(yield_each=[_fake_rpc_success])

        async def make_driver() -> Any:
            return fresh

        anchor = build_modal_anchor_dispatcher(dead, make_driver=make_driver)
        timings = await anchor(cohort="default_grpc", n=4, base_seed=42, seed_offset=0)
        assert len(timings) == 4, "post-recovery anchor returns all successful timings"
        assert timings[0] == _fake_rpc_success.wall_clock_ms
        # 4 RPCs against the dead driver, then 4 against the fresh one.
        assert len(dead.calls) == 4
        assert len(fresh.calls) == 4
        assert anchor.preemption_events() == 1  # type: ignore[attr-defined]
        assert anchor.preemption_budget == 2  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_anchor_no_recovery_when_make_driver_is_none(self) -> None:
        """Backward compatibility: omit ``make_driver`` and the anchor
        dispatcher behaves like the pre-T074e implementation — exceptions
        are swallowed and the anchor returns an empty list of timings."""
        from vllm_grpc_bench.m6_2_validate import build_modal_anchor_dispatcher

        dead = _RecordingDriver(yield_each=[_dead_endpoint_exc()])
        anchor = build_modal_anchor_dispatcher(dead)
        timings = await anchor(cohort="default_grpc", n=4, base_seed=42, seed_offset=0)
        assert timings == [], "no recovery + all-fail → empty timings (legacy shape)"
        assert len(dead.calls) == 4  # only the original attempt
        assert anchor.preemption_events() == 0  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_anchor_no_recovery_when_only_some_rpcs_fail(
        self, _fake_rpc_success: Any
    ) -> None:
        """Partial-failure anchor blocks: the recovery predicate fires only
        on a whole-block endpoint-death pattern, so a mix of successes and
        failures returns the successful timings without invoking
        make_driver."""
        from vllm_grpc_bench.m6_2_validate import build_modal_anchor_dispatcher

        driver = _RecordingDriver(
            yield_each=[
                _fake_rpc_success,
                _dead_endpoint_exc(),
                _fake_rpc_success,
                _dead_endpoint_exc(),
            ]
        )

        async def make_driver() -> Any:
            raise AssertionError("make_driver MUST NOT be invoked on partial failure")

        anchor = build_modal_anchor_dispatcher(driver, make_driver=make_driver)
        timings = await anchor(cohort="default_grpc", n=4, base_seed=42, seed_offset=0)
        assert len(timings) == 2  # the two successes
        assert anchor.preemption_events() == 0  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_anchor_budget_exhausted_raises(self) -> None:
        """The 3rd consecutive anchor preemption raises
        :class:`PreemptionBudgetExhausted` — same shape as the block
        dispatcher path. The orchestrator's outer except clause catches
        either."""
        from vllm_grpc_bench.m6_2_validate import (
            PreemptionBudgetExhausted,
            build_modal_anchor_dispatcher,
        )

        always_dead = _RecordingDriver(yield_each=[_dead_endpoint_exc()])

        async def make_driver() -> Any:
            # The "refreshed" driver is also dead — Modal kept preempting
            # the new container too.
            return _RecordingDriver(yield_each=[_dead_endpoint_exc()])

        anchor = build_modal_anchor_dispatcher(
            always_dead, make_driver=make_driver, preemption_budget=2
        )
        with pytest.raises(PreemptionBudgetExhausted, match="FR-026"):
            await anchor(cohort="default_grpc", n=4, base_seed=42, seed_offset=0)
        # 2 successful (well, attempted) recoveries before the 3rd
        # detection raised — same accounting as the block dispatcher.
        assert anchor.preemption_events() == 2  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_anchor_recovery_failed_raises(self) -> None:
        """If make_driver itself throws (Modal Dict polling timed out),
        the dispatcher wraps it in :class:`PreemptionRecoveryFailed`."""
        from vllm_grpc_bench.m6_2_validate import (
            PreemptionRecoveryFailed,
            build_modal_anchor_dispatcher,
        )

        dead = _RecordingDriver(yield_each=[_dead_endpoint_exc()])

        async def make_driver() -> Any:
            raise TimeoutError("Modal endpoint refresh timed out — new container never published")

        anchor = build_modal_anchor_dispatcher(dead, make_driver=make_driver)
        with pytest.raises(PreemptionRecoveryFailed, match="TimeoutError"):
            await anchor(cohort="default_grpc", n=4, base_seed=42, seed_offset=0)
        assert anchor.preemption_events() == 0  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_anchor_counter_starts_at_zero(self, _fake_rpc_success: Any) -> None:
        from vllm_grpc_bench.m6_2_validate import build_modal_anchor_dispatcher

        driver = _RecordingDriver(yield_each=[_fake_rpc_success])
        anchor = build_modal_anchor_dispatcher(driver)
        assert anchor.preemption_events() == 0  # type: ignore[attr-defined]
        assert anchor.preemption_budget == 2  # type: ignore[attr-defined]


class TestArtifactPreemptionEventsField:
    """T074f: the per-dispatcher preemption counters flow into
    :class:`m6_2_types.M6_2RunMeta`'s ``preemption_events`` field via
    :func:`build_artifact`. The field is rendered in the markdown
    run_meta block + serialised to the JSON artifact for post-hoc audit.
    """

    @pytest.mark.asyncio
    async def test_preemption_events_threads_into_run_meta(self, _fake_rpc_success: Any) -> None:
        """When the dispatcher recovers from a preemption, the sweep's
        accumulated counter must end up in
        ``artifact.run_meta.preemption_events`` so the JSON consumer can
        confirm the recovery happened."""
        from vllm_grpc_bench.m6_2_types import M6_2RunMeta

        # Direct constructor exercise — the orchestrator threads the
        # counter into build_artifact via the ``preemption_events`` kwarg.
        rm = M6_2RunMeta(
            git_sha="abc1234",
            modal_region="eu-west-1",
            base_seed=42,
            model_identifier="Qwen/Qwen3-8B",
            dispatch_mode="concurrent",
            symmetric_prompts_enabled=True,
            schema_version="m6_1_1.v1",
            sweep_mode="validate",
            m6_1_3_baseline_artifact_path="docs/benchmarks/m6_1_3-attribution-closure.json",
            iteration_order="cohort_innermost_block",
            iteration_discipline_verified=True,
            n_per_point=20,
            validate_axis_subset=[10, 50, 2048],
            wall_clock_start_utc="2026-05-24T00:00:00Z",
            wall_clock_end_utc="2026-05-24T03:00:00Z",
            total_sweep_hours=3.0,
            modal_spend_usd_estimate=None,
            chat_corpus_sha256="0" * 64,
            chat_corpus_path="x",
            embed_corpus_sha256="1" * 64,
            embed_corpus_path="y",
            sub_probe_ran=True,
            preemption_events=3,
        )
        assert rm.preemption_events == 3

    @pytest.mark.asyncio
    async def test_dispatcher_counter_sum_is_what_orchestrator_persists(
        self, _fake_rpc_success: Any
    ) -> None:
        """End-to-end shape check: the orchestrator reads
        ``block_dispatcher.preemption_events() + anchor_dispatcher.preemption_events()``
        and threads the sum into ``build_artifact(preemption_events=...)``.
        This test exercises the dispatcher → sum path against the same
        fixtures used in the recovery-loop tests."""
        from vllm_grpc_bench.m6_2_validate import (
            build_modal_anchor_dispatcher,
            build_modal_block_dispatcher,
        )

        # Block dispatcher: one preemption recovery.
        block_dead = _RecordingDriver(yield_each=[_dead_endpoint_exc()])
        block_fresh = _RecordingDriver(yield_each=[_fake_rpc_success])

        async def block_make_driver() -> Any:
            return block_fresh

        block_dispatcher = build_modal_block_dispatcher(
            block_dead, base_seed=42, make_driver=block_make_driver
        )
        await block_dispatcher(
            cell_id="embed_c1",
            cohort="default_grpc",
            max_tokens=10,
            n=4,
            block_inputs=_block_inputs(),
        )

        # Anchor dispatcher: two preemption recoveries.
        anchor_dead = _RecordingDriver(yield_each=[_dead_endpoint_exc()])
        anchor_seq = iter(
            [
                _RecordingDriver(yield_each=[_dead_endpoint_exc()]),
                _RecordingDriver(yield_each=[_fake_rpc_success]),
            ]
        )

        async def anchor_make_driver() -> Any:
            return next(anchor_seq)

        anchor_dispatcher = build_modal_anchor_dispatcher(
            anchor_dead, make_driver=anchor_make_driver
        )
        await anchor_dispatcher(cohort="default_grpc", n=4, base_seed=42, seed_offset=0)

        # The orchestrator's expression for run_meta.preemption_events:
        total = int(block_dispatcher.preemption_events()) + int(  # type: ignore[attr-defined]
            anchor_dispatcher.preemption_events()  # type: ignore[attr-defined]
        )
        assert total == 1 + 2


class TestBlockDispatcherPreemptionEvents:
    """Counter exposure: the dispatcher's ``preemption_events`` attribute
    is the source of truth for the orchestrator to populate
    ``run_meta.preemption_events`` after the sweep completes."""

    @pytest.mark.asyncio
    async def test_counter_starts_at_zero(self, _fake_rpc_success: Any) -> None:
        from vllm_grpc_bench.m6_2_validate import build_modal_block_dispatcher

        driver = _RecordingDriver(yield_each=[_fake_rpc_success])
        dispatcher = build_modal_block_dispatcher(driver, base_seed=42)
        assert dispatcher.preemption_events() == 0  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_counter_increments_per_recovery(self, _fake_rpc_success: Any) -> None:
        from vllm_grpc_bench.m6_2_validate import build_modal_block_dispatcher

        dead = _RecordingDriver(yield_each=[_dead_endpoint_exc()])
        sequence = iter(
            [
                _RecordingDriver(yield_each=[_dead_endpoint_exc()]),
                _RecordingDriver(yield_each=[_fake_rpc_success]),
            ]
        )

        async def make_driver() -> Any:
            return next(sequence)

        dispatcher = build_modal_block_dispatcher(dead, base_seed=42, make_driver=make_driver)
        assert dispatcher.preemption_events() == 0  # type: ignore[attr-defined]
        await dispatcher(
            cell_id="embed_c1",
            cohort="default_grpc",
            max_tokens=10,
            n=2,
            block_inputs=_block_inputs(),
        )
        assert dispatcher.preemption_events() == 2  # type: ignore[attr-defined]
