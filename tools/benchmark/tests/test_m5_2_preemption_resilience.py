"""M5.2 preemption-aware URL-refresh resilience tests.

When Modal preempts the running ``serve_bench`` Function and restarts it
on a new worker, the new worker writes fresh tunnel URLs to the same
``modal.Dict``. Cached harness URLs from the original handshake become
stale, and every cohort dispatch fails with ``httpx.ConnectError`` until
the harness refreshes its URLs.

These tests lock in:
1. ``_is_connect_error`` correctly identifies the exception classes the
   refresh path is meant to handle (and ignores unrelated exceptions).
2. ``run_m5_2_sweep`` calls ``refresh_endpoints_fn`` exactly when a cell
   fails with a connect error AND a refresh callable is configured.
3. The retry is bounded to ONE attempt per cell — refresh fails or
   returns ``None`` falls back to the existing failed_cell path.
4. A successful refresh mutates the sweep config's URLs in place so
   subsequent cells use the fresh ones.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from vllm_grpc_bench.m5_2_sweep import (
    CellSpec,
    M5_2CellMeasurement,
    M5_2SweepConfig,
    _is_connect_error,
    run_m5_2_sweep,
)
from vllm_grpc_bench.modal_endpoint import RESTGRPCEndpoints


def test_is_connect_error_identifies_httpx_connect_error() -> None:
    exc = httpx.ConnectError("All connection attempts failed")
    assert _is_connect_error(exc)


def test_is_connect_error_identifies_httpx_read_error() -> None:
    exc = httpx.ReadError("connection reset")
    assert _is_connect_error(exc)


def test_is_connect_error_identifies_grpc_aio_unavailable() -> None:
    """Regression test for the overnight-sweep bug where cell 11
    (embed:h2048:c4) hit a Modal preemption mid-RTT-probe. The probe
    raised ``grpc.aio.AioRpcError`` with ``StatusCode.UNAVAILABLE``
    against the preempted worker; the original ``_is_connect_error``
    docstring claimed this case was covered, but the implementation only
    checked httpx classes — so the cell skipped the URL-refresh retry
    and was logged as a hard failure. This test pins the fix in place.
    """
    import grpc
    from grpc.aio import AioRpcError

    exc = AioRpcError(
        code=grpc.StatusCode.UNAVAILABLE,
        initial_metadata=grpc.aio.Metadata(),
        trailing_metadata=grpc.aio.Metadata(),
        details="failed to connect to all addresses",
        debug_error_string=None,
    )
    assert _is_connect_error(exc)


def test_is_connect_error_identifies_grpc_aio_internal_and_cancelled() -> None:
    """HTTP/2 GOAWAY mid-flight surfaces as INTERNAL; transport close
    mid-stream surfaces as CANCELLED. Both are observed during Modal
    preemption windows and MUST trigger the refresh path."""
    import grpc
    from grpc.aio import AioRpcError

    for code in (grpc.StatusCode.INTERNAL, grpc.StatusCode.CANCELLED):
        exc = AioRpcError(
            code=code,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
            details=f"transport: {code.name}",
            debug_error_string=None,
        )
        assert _is_connect_error(exc), f"{code.name} should be treated as connect-style"


def test_is_connect_error_ignores_grpc_aio_application_errors() -> None:
    """Application-level gRPC errors (INVALID_ARGUMENT, NOT_FOUND, etc.)
    are NOT preemption; they're real bugs. The refresh path must NOT
    swallow them.
    """
    import grpc
    from grpc.aio import AioRpcError

    for code in (
        grpc.StatusCode.INVALID_ARGUMENT,
        grpc.StatusCode.NOT_FOUND,
        grpc.StatusCode.PERMISSION_DENIED,
    ):
        exc = AioRpcError(
            code=code,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
            details=f"app-level: {code.name}",
            debug_error_string=None,
        )
        assert not _is_connect_error(exc), f"{code.name} must not trigger refresh"


def test_is_connect_error_walks_chained_exceptions() -> None:
    """A chained exception (e.g. cohort runner wraps a httpx error in
    a RuntimeError) MUST still trigger the refresh path."""
    inner = httpx.ConnectError("inner")
    outer = RuntimeError("wrapper")
    try:
        try:
            raise inner
        except httpx.ConnectError:
            raise outer from inner
    except RuntimeError as caught:
        assert _is_connect_error(caught)


def test_is_connect_error_ignores_unrelated_runtime_errors() -> None:
    """A vanilla RuntimeError (e.g. a verdict-emitter bug) must NOT
    trigger the refresh path — those are real code-level failures."""
    assert not _is_connect_error(RuntimeError("vanilla error"))
    assert not _is_connect_error(ValueError("oops"))


@pytest.mark.asyncio
async def test_sweep_retries_failed_cell_when_refresh_returns_fresh_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a cell raises ConnectError, the sweep calls refresh_endpoints_fn;
    if it returns fresh URLs, the sweep retries the cell ONCE and that
    retry succeeds → the cell ends up in protocol_comparison_verdicts,
    NOT in failed_cells."""
    from vllm_grpc_bench import m5_2_sweep

    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok")

    cell = CellSpec(path="embed", hidden_size=2048, concurrency=1)

    # Counter to make dispatch_cell fail the first time, succeed the second.
    dispatch_calls = {"n": 0}

    async def _flaky_dispatch(c: CellSpec, **kwargs) -> M5_2CellMeasurement:
        dispatch_calls["n"] += 1
        if dispatch_calls["n"] == 1:
            raise httpx.ConnectError("All connection attempts failed")
        return _fake_measurement(c)

    refresh_calls = {"n": 0}

    async def _refresh() -> RESTGRPCEndpoints:
        refresh_calls["n"] += 1
        return RESTGRPCEndpoints(
            grpc_url="new.modal.host:50051",
            rest_url="http://new.modal.host:8000",
            auth_token_env_var="MODAL_BENCH_TOKEN",
            rest_plain_tcp_url="tcp+plaintext://new.modal.host:8000",
            rest_https_edge_url="https://new.modal.run",
        )

    monkeypatch.setattr(m5_2_sweep, "dispatch_cell", _flaky_dispatch)
    monkeypatch.setattr(m5_2_sweep, "frozen_tuned_channel_config", lambda *_a, **_k: None)

    cfg = M5_2SweepConfig(
        rest_https_edge_url="https://stale.modal.run",
        rest_plain_tcp_url="http://stale.modal.host:8000",
        grpc_target="stale.modal.host:50051",
        run_id="refresh-test",
        events_sidecar_out_dir=tmp_path,
        cells_override=(cell,),
        n_per_cohort=3,
        warmup_n=0,
        refresh_endpoints_fn=_refresh,
    )

    run = await run_m5_2_sweep(cfg, progress=False)

    assert dispatch_calls["n"] == 2, "dispatch_cell should be called twice (fail + retry)"
    assert refresh_calls["n"] == 1, "refresh should be called exactly once"
    assert run.failed_cells == [], "successful retry should NOT leave the cell in failed_cells"
    assert len(run.protocol_comparison_verdicts) >= 1
    # The sweep config was mutated in place with fresh URLs.
    assert cfg.grpc_target == "new.modal.host:50051"
    assert cfg.rest_https_edge_url == "https://new.modal.run"
    # Plain-TCP URL is re-prefixed with http:// for httpx consumption.
    assert cfg.rest_plain_tcp_url == "http://new.modal.host:8000"


@pytest.mark.asyncio
async def test_sweep_retries_on_same_urls_when_refresh_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Transient-failure fallback: when refresh returns ``None`` (URLs
    unchanged — no preemption), the sweep STILL retries the cell ONCE on
    the same URLs because the cohort runner builds fresh httpx / gRPC
    clients each dispatch, and that's usually enough to clear a stale-
    connection failure. Two dispatches both failing → failed_cell.
    """
    from vllm_grpc_bench import m5_2_sweep

    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok")

    dispatch_calls = {"n": 0}

    async def _always_fail(c: CellSpec, **kwargs) -> M5_2CellMeasurement:
        dispatch_calls["n"] += 1
        raise httpx.ConnectError("All connection attempts failed")

    async def _refresh_returns_none() -> RESTGRPCEndpoints | None:
        return None

    monkeypatch.setattr(m5_2_sweep, "dispatch_cell", _always_fail)
    monkeypatch.setattr(m5_2_sweep, "frozen_tuned_channel_config", lambda *_a, **_k: None)

    cfg = M5_2SweepConfig(
        rest_https_edge_url="https://stale.modal.run",
        rest_plain_tcp_url="http://stale.modal.host:8000",
        grpc_target="stale.modal.host:50051",
        run_id="no-preemption-test",
        events_sidecar_out_dir=tmp_path,
        cells_override=(CellSpec(path="embed", hidden_size=2048, concurrency=1),),
        n_per_cohort=3,
        warmup_n=0,
        refresh_endpoints_fn=_refresh_returns_none,
    )

    run = await run_m5_2_sweep(cfg, progress=False)
    # Initial dispatch + 1 fallback retry on same URLs; both fail → failed_cell.
    assert dispatch_calls["n"] == 2
    assert len(run.failed_cells) == 1
    assert run.failed_cells[0]["exception_type"] == "ConnectError"


@pytest.mark.asyncio
async def test_sweep_fallback_retry_succeeds_on_transient_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the connect-style error is a transient blip (one stale TCP
    connection, server backpressure clearing, etc.) and refresh returns
    ``None`` (no preemption), the fallback retry on the same URLs
    succeeds. This is the path that would have saved cell 18
    (embed:h8192:c8) during the overnight sweep.
    """
    from vllm_grpc_bench import m5_2_sweep

    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok")

    cell = CellSpec(path="embed", hidden_size=2048, concurrency=1)
    dispatch_calls = {"n": 0}

    async def _flaky_dispatch(c: CellSpec, **kwargs) -> M5_2CellMeasurement:
        dispatch_calls["n"] += 1
        if dispatch_calls["n"] == 1:
            raise httpx.ReadError("transient server-side connection close")
        return _fake_measurement(c)

    async def _refresh_returns_none() -> RESTGRPCEndpoints | None:
        return None

    monkeypatch.setattr(m5_2_sweep, "dispatch_cell", _flaky_dispatch)
    monkeypatch.setattr(m5_2_sweep, "frozen_tuned_channel_config", lambda *_a, **_k: None)

    cfg = M5_2SweepConfig(
        rest_https_edge_url="https://stable.modal.run",
        rest_plain_tcp_url="http://stable.modal.host:8000",
        grpc_target="stable.modal.host:50051",
        run_id="transient-recovery-test",
        events_sidecar_out_dir=tmp_path,
        cells_override=(cell,),
        n_per_cohort=3,
        warmup_n=0,
        refresh_endpoints_fn=_refresh_returns_none,
    )

    run = await run_m5_2_sweep(cfg, progress=False)
    assert dispatch_calls["n"] == 2, "fallback retry must run on same URLs"
    assert run.failed_cells == [], "second attempt succeeded — cell should not be marked failed"
    assert len(run.protocol_comparison_verdicts) >= 1
    # URLs were NOT mutated since refresh returned None.
    assert cfg.grpc_target == "stable.modal.host:50051"


@pytest.mark.asyncio
async def test_sweep_with_no_refresh_callable_still_retries_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``refresh_endpoints_fn`` is None (e.g. skip-deploy mode), the
    sweep still retries connect-style errors ONCE on the same URLs (the
    transient-failure fallback path). Two dispatches both failing →
    failed_cell.
    """
    from vllm_grpc_bench import m5_2_sweep

    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok")

    dispatch_calls = {"n": 0}

    async def _always_fail(c: CellSpec, **kwargs) -> M5_2CellMeasurement:
        dispatch_calls["n"] += 1
        raise httpx.ConnectError("dead")

    monkeypatch.setattr(m5_2_sweep, "dispatch_cell", _always_fail)
    monkeypatch.setattr(m5_2_sweep, "frozen_tuned_channel_config", lambda *_a, **_k: None)

    cfg = M5_2SweepConfig(
        rest_https_edge_url="https://stale.modal.run",
        rest_plain_tcp_url="http://stale.modal.host:8000",
        grpc_target="stale.modal.host:50051",
        run_id="no-refresh-test",
        events_sidecar_out_dir=tmp_path,
        cells_override=(CellSpec(path="embed", hidden_size=2048, concurrency=1),),
        n_per_cohort=3,
        warmup_n=0,
        # refresh_endpoints_fn defaults to None
    )

    run = await run_m5_2_sweep(cfg, progress=False)
    assert dispatch_calls["n"] == 2
    assert len(run.failed_cells) == 1


@pytest.mark.asyncio
async def test_sweep_only_retries_once_per_cell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retry budget is bounded: if the cell fails AGAIN after the refresh-
    triggered retry, it lands in failed_cells. No infinite retry loop."""
    from vllm_grpc_bench import m5_2_sweep

    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok")

    dispatch_calls = {"n": 0}

    async def _always_fail(c: CellSpec, **kwargs) -> M5_2CellMeasurement:
        dispatch_calls["n"] += 1
        raise httpx.ConnectError("still dead")

    async def _refresh() -> RESTGRPCEndpoints:
        return RESTGRPCEndpoints(
            grpc_url="new.modal.host:50051",
            rest_url="http://new.modal.host:8000",
            auth_token_env_var="MODAL_BENCH_TOKEN",
            rest_plain_tcp_url="tcp+plaintext://new.modal.host:8000",
            rest_https_edge_url="https://new.modal.run",
        )

    monkeypatch.setattr(m5_2_sweep, "dispatch_cell", _always_fail)
    monkeypatch.setattr(m5_2_sweep, "frozen_tuned_channel_config", lambda *_a, **_k: None)

    cfg = M5_2SweepConfig(
        rest_https_edge_url="https://stale.modal.run",
        rest_plain_tcp_url="http://stale.modal.host:8000",
        grpc_target="stale.modal.host:50051",
        run_id="bounded-retry-test",
        events_sidecar_out_dir=tmp_path,
        cells_override=(CellSpec(path="embed", hidden_size=2048, concurrency=1),),
        n_per_cohort=3,
        warmup_n=0,
        refresh_endpoints_fn=_refresh,
    )

    run = await run_m5_2_sweep(cfg, progress=False)
    # dispatch_cell called TWICE (initial + 1 retry), then gave up.
    assert dispatch_calls["n"] == 2
    assert len(run.failed_cells) == 1


def _fake_measurement(cell: CellSpec) -> M5_2CellMeasurement:
    from vllm_grpc_bench.m3_types import RTTRecord, Sample
    from vllm_grpc_bench.m5_1_grpc_cohort import GRPCCohortResult
    from vllm_grpc_bench.rest_cohort import (
        RESTCohortRecord,
        RESTCohortResult,
        RESTCohortSample,
    )

    def _rest(np: str) -> RESTCohortResult:
        return RESTCohortResult(
            samples=tuple(
                RESTCohortSample(
                    wall_clock_seconds=0.01 + 0.001 * i,
                    shim_overhead_ms=0.3,
                    request_bytes=100,
                    response_bytes=200,
                )
                for i in range(3)
            ),
            record=RESTCohortRecord(
                shim_overhead_ms_median=0.3,
                shim_overhead_ms_p95=0.4,
                connections_opened=1,
                connections_keepalive_reused=2,
                request_bytes_median=100,
                request_bytes_p95=100,
                response_bytes_median=200,
                response_bytes_p95=200,
            ),
            rtt_record=RTTRecord(n=2, median_ms=50.0, p95_ms=55.0, samples_ms=(50.0, 55.0)),
            network_path=np,  # type: ignore[arg-type]
        )

    def _grpc(kind: str) -> GRPCCohortResult:
        return GRPCCohortResult(
            samples=tuple(
                Sample(
                    cell_id="test",
                    iteration=i,
                    request_wire_bytes=50,
                    response_wire_bytes=80,
                    wall_clock_seconds=0.012,
                    time_to_first_token_seconds=0.005,
                )
                for i in range(3)
            ),
            rtt_record=RTTRecord(n=2, median_ms=48.0, p95_ms=52.0, samples_ms=(48.0, 52.0)),
            sub_cohort_kind=kind,  # type: ignore[arg-type]
            channels_opened=1,
        )

    return M5_2CellMeasurement(
        cell=cell,
        rest_https_edge=_rest("https_edge"),
        rest_plain_tcp=_rest("plain_tcp"),
        default_grpc=_grpc("default_grpc"),
        tuned_multiplexed=None,
        tuned_channels=None,
        tuned_grpc=_grpc("tuned_grpc") if cell.concurrency == 1 else None,
    )
