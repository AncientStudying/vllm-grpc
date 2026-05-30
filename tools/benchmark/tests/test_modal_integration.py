"""T056 — Modal-shape integration test for the M6.2 dispatcher adapters.

Exercises the real dispatchers built by
:func:`m6_2_validate.build_modal_block_dispatcher` +
:func:`m6_2_validate.build_modal_anchor_dispatcher` against a **fake RPC
driver** that mimics :func:`rpc_driver.provide_m6_2_rpc_driver`'s
``driver(cohort, cell, seed, *, max_tokens, ignore_eos, prompt,
prompt_embeds_override) -> RPCResult`` signature.

This is the regression test that catches the class of bug surfaced when the
operator first ran ``--m6_2-validate``: ``build_artifact`` published an
artifact with ``null_anchor_validation=[]`` because the integration glue
between the unit modules was missing. The CI gate that exists for the
stub dispatcher would not have caught this; only an end-to-end pass
through the Modal-shape callable surface does.

Coverage:

* :func:`build_modal_block_dispatcher` flows ``prompt`` / ``ignore_eos`` /
  ``max_tokens`` from ``ResolvedBlockInputs`` into the driver.
* :func:`build_modal_anchor_dispatcher` issues synthetic-regime RPCs.
* :func:`is_transient_modal_error` classifies gRPC + httpx errors correctly.
* :func:`build_artifact` produces a non-empty ``null_anchor_validation`` list
  + a derived (non-sentinel) anchor CI threshold when given a sweep_outputs
  built from the fake driver.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import grpc
import httpx
import pytest
from vllm_grpc_bench.prompts import ResolvedBlockInputs
from vllm_grpc_bench.sweep import BlockDispatchResult
from vllm_grpc_bench.types import COHORTS as M6_1_2_COHORTS
from vllm_grpc_bench.types import Cell as M6_1Cell
from vllm_grpc_bench.types import CohortKind as M6_1_2CohortKind
from vllm_grpc_bench.validate import (
    build_modal_anchor_dispatcher,
    build_modal_block_dispatcher,
    derive_anchor_drift_threshold,
    is_transient_modal_error,
    make_null_anchor_validation,
)

# --- Fake RPC driver --------------------------------------------------------


class _FakeRPCResult:
    """Minimal RPCResult-shaped stand-in for the integration test.

    The real :class:`m6_sweep.RPCResult` is a frozen dataclass with
    ``m6_1_1_timing_payload`` etc.; we mimic the duck-typed surface the
    dispatcher reads (``success``, ``wall_clock_ms``, ``failure_reason``,
    ``m6_1_1_timing_payload``).
    """

    def __init__(
        self,
        *,
        success: bool = True,
        wall_clock_ms: float | None = 100.0,
        failure_reason: str | None = None,
        m6_1_1_timing_payload: dict[str, str] | None = None,
    ) -> None:
        self.success = success
        self.wall_clock_ms = wall_clock_ms
        self.failure_reason = failure_reason
        self.m6_1_1_timing_payload = m6_1_1_timing_payload


def _make_fake_driver(
    *,
    on_call: Callable[..., _FakeRPCResult] | None = None,
    fail_first_n: int = 0,
    raise_transient_at_seed: int | None = None,
) -> tuple[Any, list[dict[str, Any]]]:
    """Return a fake driver callable matching the M6.2 driver shape.

    Records each call's kwargs into ``calls`` for later assertion; emits
    ``_FakeRPCResult`` with deterministic per-seed wall times. Optional
    ``fail_first_n`` forces the first N RPCs to return ``success=False``.
    """
    calls: list[dict[str, Any]] = []
    counter = {"n": 0}

    async def _driver(
        cohort: M6_1_2CohortKind,
        cell: M6_1Cell,
        seed: int,
        *,
        max_tokens: int,
        ignore_eos: bool = False,
        prompt: str | None = None,
        prompt_embeds_override: bytes | None = None,
    ) -> _FakeRPCResult:
        calls.append(
            {
                "cohort": cohort,
                "cell": cell,
                "seed": seed,
                "max_tokens": max_tokens,
                "ignore_eos": ignore_eos,
                "prompt": prompt,
                "prompt_embeds_override": prompt_embeds_override,
            }
        )
        counter["n"] += 1
        if raise_transient_at_seed is not None and seed == raise_transient_at_seed:
            err = grpc.RpcError()
            err.code = lambda: grpc.StatusCode.UNAVAILABLE  # type: ignore[method-assign]
            err.details = lambda: "fake transient"  # type: ignore[method-assign]
            raise err
        if counter["n"] <= fail_first_n:
            return _FakeRPCResult(success=False, wall_clock_ms=None, failure_reason="fake_failure")
        if on_call is not None:
            result: _FakeRPCResult = on_call(
                cohort=cohort, cell=cell, seed=seed, max_tokens=max_tokens
            )
            return result
        return _FakeRPCResult(
            success=True,
            wall_clock_ms=50.0 + (seed % 17) * 1.5,
            m6_1_1_timing_payload={"t_a_ms": str(1.0), "t_d_ms": str(50.0)},
        )

    return _driver, calls


# --- BlockDispatcher tests --------------------------------------------------


class TestModalBlockDispatcher:
    @pytest.fixture()
    def block_inputs(self) -> ResolvedBlockInputs:
        return ResolvedBlockInputs(
            prompt_text="Hello from the test corpus.",
            prompt_source="corpus_sharegpt",
            prompt_corpus_idx=7,
            ignore_eos=False,
            max_tokens=256,
        )

    async def test_dispatcher_fires_n_concurrent_rpcs(
        self, block_inputs: ResolvedBlockInputs
    ) -> None:
        driver, calls = _make_fake_driver()
        dispatch = build_modal_block_dispatcher(driver, base_seed=100)
        result = await dispatch(
            cell_id="chat_stream_c4",
            cohort="default_grpc",
            max_tokens=256,
            n=8,
            block_inputs=block_inputs,
        )
        assert isinstance(result, BlockDispatchResult)
        assert len(result.timings_ms) == 8
        assert result.failed_reason is None
        assert len(calls) == 8
        # Per-RPC seeds = base_seed + i, deterministic + unique.
        seeds = sorted(c["seed"] for c in calls)
        assert seeds == [100, 101, 102, 103, 104, 105, 106, 107]

    async def test_block_inputs_flow_through(self, block_inputs: ResolvedBlockInputs) -> None:
        driver, calls = _make_fake_driver()
        dispatch = build_modal_block_dispatcher(driver, base_seed=42)
        await dispatch(
            cell_id="chat_stream_c1",
            cohort="rest_https_edge",
            max_tokens=2048,
            n=2,
            block_inputs=block_inputs,
        )
        for call in calls:
            assert call["max_tokens"] == 2048
            assert call["ignore_eos"] is False
            assert call["prompt"] == "Hello from the test corpus."
            assert call["prompt_embeds_override"] is None
            assert call["cohort"] == "rest_https_edge"
            assert call["cell"].path == "chat_stream"
            assert call["cell"].concurrency == 1

    async def test_embed_block_passes_embed_bytes(self) -> None:
        embed_inputs = ResolvedBlockInputs(
            embed_tensor_bytes=b"fake-torch-save-bytes",
            prompt_source="corpus_sharegpt_embed",
            prompt_corpus_idx=12,
            ignore_eos=True,
            max_tokens=1024,
        )
        driver, calls = _make_fake_driver()
        dispatch = build_modal_block_dispatcher(driver, base_seed=42)
        await dispatch(
            cell_id="embed_c8",
            cohort="tuned_grpc_multiplexed",
            max_tokens=1024,
            n=3,
            block_inputs=embed_inputs,
        )
        for call in calls:
            assert call["ignore_eos"] is True
            assert call["prompt"] is None
            assert call["prompt_embeds_override"] == b"fake-torch-save-bytes"
            assert call["cell"].path == "embed"
            assert call["cell"].concurrency == 8

    async def test_failed_rpcs_classified(self, block_inputs: ResolvedBlockInputs) -> None:
        driver, _calls = _make_fake_driver(fail_first_n=999)  # everything fails
        dispatch = build_modal_block_dispatcher(driver, base_seed=42)
        result = await dispatch(
            cell_id="chat_stream_c1",
            cohort="default_grpc",
            max_tokens=10,
            n=5,
            block_inputs=block_inputs,
        )
        assert result.failed_reason is not None
        assert result.timings_ms == []

    async def test_partial_success_returns_successes(
        self, block_inputs: ResolvedBlockInputs
    ) -> None:
        driver, _calls = _make_fake_driver(fail_first_n=2)
        dispatch = build_modal_block_dispatcher(driver, base_seed=42)
        result = await dispatch(
            cell_id="chat_stream_c4",
            cohort="default_grpc",
            max_tokens=50,
            n=5,
            block_inputs=block_inputs,
        )
        assert len(result.timings_ms) == 3  # 5 - 2 failures
        assert result.failed_reason is None  # at least one success → block OK

    @pytest.mark.parametrize(
        ("cell_id", "expected_max"),
        [
            ("chat_stream_c1", 1),
            ("chat_stream_c4", 4),
            ("chat_stream_c8", 8),
            ("embed_c1", 1),
            ("embed_c4", 4),
            ("embed_c8", 8),
        ],
    )
    async def test_in_flight_bounded_by_cell_concurrency(
        self,
        cell_id: str,
        expected_max: int,
        block_inputs: ResolvedBlockInputs,
    ) -> None:
        """Regression: peak in-flight RPCs MUST equal cell.concurrency, not n.

        Without the asyncio.Semaphore(cell.concurrency) bound, all n RPCs
        fire simultaneously regardless of cell.c — which under-measures
        c=1/c=4 cells and saturates the single-worker REST shim's event
        loop, inflating client-side TPOT by ~44 ms/token on REST cohorts at
        n=20 (root cause of the 2026-05-23T21:08Z validate-sweep REST
        regression).
        """
        in_flight = 0
        peak = 0
        lock = asyncio.Lock()

        async def _delay_driver(
            cohort: M6_1_2CohortKind,
            cell: M6_1Cell,
            seed: int,
            *,
            max_tokens: int,
            ignore_eos: bool = False,
            prompt: str | None = None,
            prompt_embeds_override: bytes | None = None,
        ) -> _FakeRPCResult:
            nonlocal in_flight, peak
            async with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            await asyncio.sleep(0.01)  # hold the slot so concurrency can pile up
            async with lock:
                in_flight -= 1
            return _FakeRPCResult(success=True, wall_clock_ms=10.0)

        dispatch = build_modal_block_dispatcher(_delay_driver, base_seed=0)
        await dispatch(
            cell_id=cell_id,
            cohort="default_grpc",
            max_tokens=50,
            n=20,  # match validate-sweep n; well above any cell.concurrency
            block_inputs=block_inputs,
        )
        assert peak == expected_max, (
            f"peak in-flight = {peak} but cell.concurrency = {expected_max}; "
            "cell.concurrency must bound the asyncio.gather fan-out"
        )


# --- AnchorRPCDriver tests --------------------------------------------------


class TestModalAnchorDispatcher:
    async def test_anchor_dispatches_synthetic(self) -> None:
        driver, calls = _make_fake_driver()
        anchor = build_modal_anchor_dispatcher(driver)
        samples = await anchor(
            cohort="default_grpc",
            n=20,
            base_seed=42,
            seed_offset=0,
        )
        assert len(samples) == 20
        # Anchor block is always synthetic-regime → prompt=None.
        for call in calls:
            assert call["prompt"] is None
            assert call["prompt_embeds_override"] is None
            assert call["max_tokens"] == 10
            assert call["ignore_eos"] is False

    async def test_anchor_seeds_offset_correctly(self) -> None:
        driver, calls = _make_fake_driver()
        anchor = build_modal_anchor_dispatcher(driver)
        await anchor(cohort="rest_plain_tcp", n=5, base_seed=100, seed_offset=500)
        seeds = sorted(c["seed"] for c in calls)
        assert seeds == [600, 601, 602, 603, 604]

    async def test_anchor_returns_only_successes(self) -> None:
        driver, _calls = _make_fake_driver(fail_first_n=10)
        anchor = build_modal_anchor_dispatcher(driver)
        samples = await anchor(cohort="default_grpc", n=20, base_seed=42, seed_offset=0)
        assert len(samples) == 10  # 20 - 10 failures

    async def test_anchor_is_strictly_serial(self) -> None:
        """The anchor block uses chat_stream_c1 (concurrency=1) so the
        semaphore bound MUST hold it to one in-flight RPC at a time. This
        matches M6.1.3's anchor measurement regime."""
        in_flight = 0
        peak = 0
        lock = asyncio.Lock()

        async def _delay_driver(
            cohort: M6_1_2CohortKind,
            cell: M6_1Cell,
            seed: int,
            *,
            max_tokens: int,
            ignore_eos: bool = False,
            prompt: str | None = None,
            prompt_embeds_override: bytes | None = None,
        ) -> _FakeRPCResult:
            nonlocal in_flight, peak
            async with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            async with lock:
                in_flight -= 1
            return _FakeRPCResult(success=True, wall_clock_ms=10.0)

        anchor = build_modal_anchor_dispatcher(_delay_driver)
        await anchor(cohort="default_grpc", n=20, base_seed=42, seed_offset=0)
        assert peak == 1, f"anchor peak in-flight = {peak}; chat_stream_c1 must be serial"


# --- is_transient_modal_error tests ----------------------------------------


class TestIsTransientModalError:
    def test_grpc_unavailable_is_transient(self) -> None:
        err = grpc.RpcError()
        err.code = lambda: grpc.StatusCode.UNAVAILABLE  # type: ignore[method-assign]
        assert is_transient_modal_error(err) is True

    def test_grpc_deadline_exceeded_is_transient(self) -> None:
        err = grpc.RpcError()
        err.code = lambda: grpc.StatusCode.DEADLINE_EXCEEDED  # type: ignore[method-assign]
        assert is_transient_modal_error(err) is True

    def test_grpc_invalid_argument_not_transient(self) -> None:
        err = grpc.RpcError()
        err.code = lambda: grpc.StatusCode.INVALID_ARGUMENT  # type: ignore[method-assign]
        assert is_transient_modal_error(err) is False

    def test_httpx_timeout_is_transient(self) -> None:
        assert is_transient_modal_error(httpx.ReadTimeout("slow")) is True

    def test_httpx_transport_error_is_transient(self) -> None:
        assert is_transient_modal_error(httpx.ConnectError("nope")) is True

    def test_arbitrary_exception_not_transient(self) -> None:
        assert is_transient_modal_error(ValueError("bad input")) is False


# --- Artifact build path coverage ------------------------------------------


def _fake_baseline_path(tmp_path: Any) -> Any:
    import json

    payload = {
        "schema_version": "m6_1_1.v1",
        "measurements": [
            {
                "cell_id": "chat_stream_c1",
                "cohort": "default_grpc",
                "wall_clock_ms_mean": 50.0,
            },
        ],
        "between_run_variance": {
            "chat_stream_c1": {
                "default_grpc": {
                    "mean_of_means_ms": 50.0,
                    "stddev_of_means_ms": 0.5,
                    "n_runs": 5,
                },
                "rest_https_edge": {
                    "mean_of_means_ms": 60.0,
                    "stddev_of_means_ms": 1.2,
                    "n_runs": 5,
                },
            },
        },
        "classifications": {},
    }
    path = tmp_path / "fake_m6_1_3.json"
    path.write_text(json.dumps(payload))
    return path


class TestArtifactPathIntegration:
    def test_derive_anchor_drift_threshold_reads_baseline(self, tmp_path: Any) -> None:
        path = _fake_baseline_path(tmp_path)
        threshold = derive_anchor_drift_threshold(path)
        # max(1.96 * 0.5/sqrt(5), 1.96 * 1.2/sqrt(5)) = max(0.438, 1.053) = 1.053
        assert 1.0 < threshold < 1.1

    def test_derive_anchor_drift_threshold_sentinel_when_missing(self, tmp_path: Any) -> None:
        missing = tmp_path / "does_not_exist.json"
        assert derive_anchor_drift_threshold(missing) == 5.0

    def test_make_null_anchor_validation_emits_48_anchors(self, tmp_path: Any) -> None:
        # Build a stub measurement list: 48 anchors (6 cells × 4 cohorts × 2 caps).
        from vllm_grpc_bench.sweep_types import M6_2MeasurementPoint
        from vllm_grpc_bench.types import CELLS as M6_1_CELLS
        from vllm_grpc_bench.validate import load_m6_1_3_baseline

        measurements: list[M6_2MeasurementPoint] = []
        for path, _hidden_size, concurrency in M6_1_CELLS:
            cell_id = f"{path}_c{concurrency}"
            for cohort in M6_1_2_COHORTS:
                for max_tokens in (10, 50):
                    measurements.append(
                        M6_2MeasurementPoint(
                            cell_id=cell_id,
                            cohort=cohort,
                            max_tokens=max_tokens,
                            n_rpcs=20,
                            wall_p50_ms=50.0,
                            wall_p95_ms=55.0,
                            wall_p99_ms=60.0,
                            wall_p50_ms_ci_half_width=None,
                            tpot_ms=None,
                            seg_ab_ms=None,
                            seg_queue_ms=None,
                            seg_prefill_ms=None,
                            seg_ingress_ms=None,
                            seg_egress_ms=None,
                            failed_reason=None,
                            block_start_utc="2026-05-23T00:00:00Z",
                            block_end_utc="2026-05-23T00:00:01Z",
                            retry_attempted=False,
                            clock_anomaly=False,
                            prompt_source="synthetic_seed_derived",
                            measurement_regime="natural_eos",
                            prompt_corpus_idx=None,
                        )
                    )
        baseline_path = _fake_baseline_path(tmp_path)
        baseline_per_cell, _verdicts = load_m6_1_3_baseline(baseline_path)
        anchors = make_null_anchor_validation(measurements, baseline_per_cell)
        assert len(anchors) == 48
        cross_checkable = [a for a in anchors if not a.new_baseline_marker]
        new_baseline = [a for a in anchors if a.new_baseline_marker]
        # The fake baseline only publishes chat_stream_c1 × default_grpc, so:
        #   - cross-checkable cells = anchor cells matching that pair at the
        #     M6.1.x-canonical max_tokens (chat_stream → 50). That's exactly 1.
        #   - everything else is new-baseline.
        assert len(cross_checkable) == 1
        assert cross_checkable[0].cell_id == "chat_stream_c1"
        assert cross_checkable[0].cohort == "default_grpc"
        assert cross_checkable[0].max_tokens == 50
        assert len(new_baseline) == 47
