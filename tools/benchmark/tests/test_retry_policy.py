"""T019 — FR-033 in-window retry-once dispatch wrapper."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from vllm_grpc_bench.prompts import ResolvedBlockInputs
from vllm_grpc_bench.sweep import (
    BlockDispatchResult,
    run_block_with_retry,
)


def _block_inputs() -> ResolvedBlockInputs:
    return ResolvedBlockInputs(
        prompt_text="hello",
        prompt_source="synthetic_seed_derived",
        prompt_corpus_idx=None,
        ignore_eos=False,
        max_tokens=10,
    )


class _CountingDispatcher:
    """Records calls and returns prearranged outcomes per invocation."""

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def __call__(self, **_: Any) -> BlockDispatchResult:
        idx = self.calls
        self.calls += 1
        outcome = self.outcomes[idx]
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, BlockDispatchResult)
        return outcome


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, ConnectionError | TimeoutError)


class TestRetrySucceedsAfterTransient:
    def test_first_attempt_succeeds_no_retry(self) -> None:
        success = BlockDispatchResult(
            timings_ms=[10.0, 12.0, 14.0],
            failed_reason=None,
            per_rpc_metadata=[],
        )
        dispatcher = _CountingDispatcher([success])
        result, _start, _end, retry_attempted = asyncio.run(
            run_block_with_retry(
                cell_id="chat_stream_c1",
                cohort="default_grpc",
                max_tokens=10,
                n=20,
                block_inputs=_block_inputs(),
                dispatcher=dispatcher,
                is_transient=_is_transient,
            )
        )
        assert result.failed_reason is None
        assert retry_attempted is False
        assert dispatcher.calls == 1

    def test_transient_then_success_retry_attempted_true(self) -> None:
        success = BlockDispatchResult(
            timings_ms=[10.0],
            failed_reason=None,
            per_rpc_metadata=[],
        )
        dispatcher = _CountingDispatcher([TimeoutError("transient"), success])
        result, _start, _end, retry_attempted = asyncio.run(
            run_block_with_retry(
                cell_id="chat_stream_c1",
                cohort="default_grpc",
                max_tokens=10,
                n=20,
                block_inputs=_block_inputs(),
                dispatcher=dispatcher,
                is_transient=_is_transient,
            )
        )
        assert result.failed_reason is None
        assert retry_attempted is True
        assert dispatcher.calls == 2


class TestRetryFailsAfterBothAttempts:
    def test_both_attempts_transient_failure_marked_failed(self) -> None:
        dispatcher = _CountingDispatcher([TimeoutError("first"), ConnectionError("second")])
        result, _start, _end, retry_attempted = asyncio.run(
            run_block_with_retry(
                cell_id="chat_stream_c1",
                cohort="default_grpc",
                max_tokens=10,
                n=20,
                block_inputs=_block_inputs(),
                dispatcher=dispatcher,
                is_transient=_is_transient,
            )
        )
        assert result.failed_reason is not None
        assert retry_attempted is True
        assert dispatcher.calls == 2


class TestNonTransientNoRetry:
    def test_non_transient_first_attempt_fails_no_retry(self) -> None:
        dispatcher = _CountingDispatcher([ValueError("schema mismatch")])
        result, _start, _end, retry_attempted = asyncio.run(
            run_block_with_retry(
                cell_id="chat_stream_c1",
                cohort="default_grpc",
                max_tokens=10,
                n=20,
                block_inputs=_block_inputs(),
                dispatcher=dispatcher,
                is_transient=_is_transient,
            )
        )
        assert result.failed_reason is not None
        assert retry_attempted is False
        assert dispatcher.calls == 1


class TestRetryStaysInTimeWindow:
    def test_retry_block_start_utc_within_same_window(self) -> None:
        # block_start_utc must be captured BEFORE the first attempt; the
        # retry uses the same start so the recorded time window contains
        # both attempts.
        dispatcher = _CountingDispatcher(
            [
                TimeoutError("transient"),
                BlockDispatchResult(timings_ms=[10.0], failed_reason=None, per_rpc_metadata=[]),
            ]
        )
        result, block_start_utc, block_end_utc, retry_attempted = asyncio.run(
            run_block_with_retry(
                cell_id="chat_stream_c1",
                cohort="default_grpc",
                max_tokens=10,
                n=20,
                block_inputs=_block_inputs(),
                dispatcher=dispatcher,
                is_transient=_is_transient,
            )
        )
        assert result.failed_reason is None
        assert retry_attempted is True
        assert block_start_utc <= block_end_utc


class TestNoEndOfSweepRetry:
    """The retry policy is in-window only; once the wrapper returns a failed
    row, callers MUST NOT re-invoke the wrapper for that block at the end of
    the sweep (FR-033 forbidden behavior). This test pins the wrapper's
    semantic contract: it has no internal retry budget that an end-of-sweep
    pass could exhaust."""

    def test_wrapper_returns_after_single_retry_attempt(self) -> None:
        dispatcher = _CountingDispatcher(
            [
                TimeoutError("first"),
                TimeoutError("second"),
                pytest.fail.Exception("third call should NOT happen"),  # type: ignore[attr-defined]
            ]
        )
        # NOTE: we expect the wrapper to stop after two calls regardless of
        # how many outcomes we queue up.
        try:
            asyncio.run(
                run_block_with_retry(
                    cell_id="chat_stream_c1",
                    cohort="default_grpc",
                    max_tokens=10,
                    n=20,
                    block_inputs=_block_inputs(),
                    dispatcher=dispatcher,
                    is_transient=_is_transient,
                )
            )
        except Exception:
            # The third outcome should never fire — this branch indicates
            # the wrapper retried more than once.
            pytest.fail("Wrapper attempted retry beyond the in-window budget")
        assert dispatcher.calls == 2
