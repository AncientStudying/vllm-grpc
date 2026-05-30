"""T042 — M6.2 KV-pressure sub-probe orchestrator unit tests (FR-036).

Exercises :func:`m6_2_sub_probe.run_kv_pressure_sub_probe` directly with a
stub dispatcher. Covers the 16-block contract, ``n=20`` discipline,
``ignore_eos=True`` propagation through the prompt-source resolver, FR-030
cohort-innermost ordering within each ``(cell_type, max_tokens)`` tuple, and
the FR-033 in-window retry policy.
"""

from __future__ import annotations

import asyncio

import pytest
from vllm_grpc_bench.corpus import (
    CompletionEmbedSample,
    RequestSample,
)
from vllm_grpc_bench.m6_1_2_types import M6_1_2_COHORTS
from vllm_grpc_bench.m6_2_sub_probe import (
    SUB_PROBE_CELL_IDS,
    SUB_PROBE_CELL_TYPES,
    iter_sub_probe_tuples,
    run_kv_pressure_sub_probe,
)
from vllm_grpc_bench.sweep import BlockDispatchResult
from vllm_grpc_bench.sweep_types import M6_2_SUB_PROBE_MAX_TOKENS, M6_2_SUB_PROBE_N

# --- Stub corpora ----------------------------------------------------------


def _fake_chat_corpus(size: int = 32) -> list[RequestSample]:
    return [
        RequestSample(
            id=f"chat-{i}",
            messages=[{"role": "user", "content": f"prompt {i}"}],
            model="Qwen/Qwen3-8B",
            max_tokens=50,
            temperature=0.0,
            seed=i,
        )
        for i in range(size)
    ]


def _fake_embed_corpus(size: int = 32) -> list[CompletionEmbedSample]:
    return [
        CompletionEmbedSample(
            id=i,
            tensor_bytes=b"\x00" * 16,
            max_tokens=10,
            seed=i,
            seq_len=8,
            bucket="short",
        )
        for i in range(size)
    ]


# --- Stub dispatcher with call recording -----------------------------------


class _RecordingDispatcher:
    """Stub :class:`BlockDispatcher` that records every call's kwargs.

    Returns a deterministic 20-element timing list per block so the per-block
    aggregation produces non-None percentiles.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def __call__(
        self,
        *,
        cell_id: str,
        cohort: str,
        max_tokens: int,
        n: int,
        block_inputs: object,
    ) -> BlockDispatchResult:
        self.calls.append(
            {
                "cell_id": cell_id,
                "cohort": cohort,
                "max_tokens": max_tokens,
                "n": n,
                "block_inputs": block_inputs,
            }
        )
        base = 50.0 + max_tokens / 50.0
        return BlockDispatchResult(
            timings_ms=[base + i * 0.1 for i in range(n)],
            failed_reason=None,
            per_rpc_metadata=[],
        )


def _is_transient(_exc: BaseException) -> bool:
    return False


# --- Iteration order -------------------------------------------------------


def test_sub_probe_iterates_16_tuples_cohort_innermost() -> None:
    """FR-030 cohort-innermost: for each (cell_type, max_tokens) tuple, all
    4 cohorts dispatch back-to-back before advancing."""
    tuples = iter_sub_probe_tuples()
    assert len(tuples) == 16, "4 cohorts × 2 cell-types × 2 caps = 16"
    # Group consecutive runs and check each group is 4 cohorts of the same
    # (cell_type, max_tokens) tuple.
    idx = 0
    for cell_type in SUB_PROBE_CELL_TYPES:
        for max_tokens in M6_2_SUB_PROBE_MAX_TOKENS:
            for cohort in M6_1_2_COHORTS:
                assert tuples[idx] == (cell_type, max_tokens, cohort), (
                    f"position {idx} should be {(cell_type, max_tokens, cohort)}"
                )
                idx += 1


def test_sub_probe_cell_ids_target_c8() -> None:
    """The sub-probe always dispatches against the ``c=8`` cell variants
    (FR-017a focuses on the high-concurrency KV-pressure regime)."""
    assert SUB_PROBE_CELL_IDS["chat_stream"] == "chat_stream_c8"
    assert SUB_PROBE_CELL_IDS["embed"] == "embed_c8"


# --- run_kv_pressure_sub_probe contract ------------------------------------


def test_run_sub_probe_emits_16_rows_with_n_20() -> None:
    dispatcher = _RecordingDispatcher()
    chat = _fake_chat_corpus()
    embed = _fake_embed_corpus()
    rows = asyncio.run(
        run_kv_pressure_sub_probe(
            dispatcher=dispatcher,  # type: ignore[arg-type]
            is_transient=_is_transient,
            base_seed=42,
            chat_corpus=chat,
            embed_corpus=embed,
        )
    )
    assert len(rows) == 16
    for row in rows:
        assert row.n_rpcs == M6_2_SUB_PROBE_N
        assert row.failed_reason is None
        assert row.wall_p50_ms is not None


def test_dispatcher_called_with_ignore_eos_true_per_block_inputs() -> None:
    """The sub-probe MUST pass ``ignore_eos=True`` in the block_inputs to
    the dispatcher (via the prompt-source resolver's override)."""
    dispatcher = _RecordingDispatcher()
    asyncio.run(
        run_kv_pressure_sub_probe(
            dispatcher=dispatcher,  # type: ignore[arg-type]
            is_transient=_is_transient,
            base_seed=42,
            chat_corpus=_fake_chat_corpus(),
            embed_corpus=_fake_embed_corpus(),
        )
    )
    assert len(dispatcher.calls) == 16
    for call in dispatcher.calls:
        block_inputs = call["block_inputs"]
        # ResolvedBlockInputs is a TypedDict; access via mapping interface
        assert isinstance(block_inputs, dict)
        assert block_inputs.get("ignore_eos") is True


def test_dispatcher_called_with_c8_cell_ids() -> None:
    dispatcher = _RecordingDispatcher()
    asyncio.run(
        run_kv_pressure_sub_probe(
            dispatcher=dispatcher,  # type: ignore[arg-type]
            is_transient=_is_transient,
            base_seed=42,
            chat_corpus=_fake_chat_corpus(),
            embed_corpus=_fake_embed_corpus(),
        )
    )
    cell_ids = {call["cell_id"] for call in dispatcher.calls}
    assert cell_ids == {"chat_stream_c8", "embed_c8"}


def test_dispatcher_called_at_each_sub_probe_cap() -> None:
    dispatcher = _RecordingDispatcher()
    asyncio.run(
        run_kv_pressure_sub_probe(
            dispatcher=dispatcher,  # type: ignore[arg-type]
            is_transient=_is_transient,
            base_seed=42,
            chat_corpus=_fake_chat_corpus(),
            embed_corpus=_fake_embed_corpus(),
        )
    )
    caps = {call["max_tokens"] for call in dispatcher.calls}
    assert caps == set(M6_2_SUB_PROBE_MAX_TOKENS)


def test_dispatcher_called_for_each_cohort() -> None:
    dispatcher = _RecordingDispatcher()
    asyncio.run(
        run_kv_pressure_sub_probe(
            dispatcher=dispatcher,  # type: ignore[arg-type]
            is_transient=_is_transient,
            base_seed=42,
            chat_corpus=_fake_chat_corpus(),
            embed_corpus=_fake_embed_corpus(),
        )
    )
    cohorts = {call["cohort"] for call in dispatcher.calls}
    assert cohorts == set(M6_1_2_COHORTS)


# --- Cell-type distinction --------------------------------------------------


def test_sub_probe_rows_separate_chat_and_embed_cell_types() -> None:
    dispatcher = _RecordingDispatcher()
    rows = asyncio.run(
        run_kv_pressure_sub_probe(
            dispatcher=dispatcher,  # type: ignore[arg-type]
            is_transient=_is_transient,
            base_seed=42,
            chat_corpus=_fake_chat_corpus(),
            embed_corpus=_fake_embed_corpus(),
        )
    )
    chat_rows = [r for r in rows if r.cell_type == "chat_stream"]
    embed_rows = [r for r in rows if r.cell_type == "embed"]
    assert len(chat_rows) == 8  # 4 cohorts × 2 caps
    assert len(embed_rows) == 8


# --- Retry policy ----------------------------------------------------------


class _TransientOnceDispatcher:
    """First call to ``(cell_id, cohort, max_tokens)`` raises a transient
    error; subsequent calls succeed. Records whether retry was attempted."""

    def __init__(self) -> None:
        self.attempts: dict[tuple[str, str, int], int] = {}

    async def __call__(
        self,
        *,
        cell_id: str,
        cohort: str,
        max_tokens: int,
        n: int,
        block_inputs: object,
    ) -> BlockDispatchResult:
        del block_inputs
        key = (cell_id, cohort, max_tokens)
        self.attempts[key] = self.attempts.get(key, 0) + 1
        if self.attempts[key] == 1:
            raise TimeoutError("transient deadline exceeded")
        return BlockDispatchResult(
            timings_ms=[50.0 + i * 0.1 for i in range(n)],
            failed_reason=None,
            per_rpc_metadata=[],
        )


def test_in_window_retry_once_succeeds_on_second_attempt() -> None:
    """FR-033: transient first attempt → retry once within the same time
    window. The sub-probe inherits the main-sweep retry policy via
    :func:`sweep.run_block_with_retry`."""
    dispatcher = _TransientOnceDispatcher()
    rows = asyncio.run(
        run_kv_pressure_sub_probe(
            dispatcher=dispatcher,  # type: ignore[arg-type]
            is_transient=lambda exc: True,
            base_seed=42,
            chat_corpus=_fake_chat_corpus(),
            embed_corpus=_fake_embed_corpus(),
        )
    )
    for row in rows:
        assert row.retry_attempted is True
        assert row.failed_reason is None
        assert row.wall_p50_ms is not None


# --- Failed-block handling -------------------------------------------------


class _AlwaysFailDispatcher:
    async def __call__(
        self,
        *,
        cell_id: str,
        cohort: str,
        max_tokens: int,
        n: int,
        block_inputs: object,
    ) -> BlockDispatchResult:
        del cell_id, cohort, max_tokens, n, block_inputs
        return BlockDispatchResult(
            timings_ms=[],
            failed_reason="grpc_timeout",
            per_rpc_metadata=[],
        )


def test_failed_blocks_emit_rows_with_failed_reason() -> None:
    dispatcher = _AlwaysFailDispatcher()
    rows = asyncio.run(
        run_kv_pressure_sub_probe(
            dispatcher=dispatcher,  # type: ignore[arg-type]
            is_transient=_is_transient,
            base_seed=42,
            chat_corpus=_fake_chat_corpus(),
            embed_corpus=_fake_embed_corpus(),
        )
    )
    assert len(rows) == 16
    for row in rows:
        assert row.failed_reason == "grpc_timeout"
        assert row.wall_p50_ms is None


@pytest.mark.asyncio
async def test_dispatcher_receives_block_inputs_with_corpus_regime() -> None:
    """Sub-probe blocks use the corpus regime (corpus_sharegpt for chat,
    corpus_sharegpt_embed for embed) per FR-034 / FR-035."""
    dispatcher = _RecordingDispatcher()
    await run_kv_pressure_sub_probe(
        dispatcher=dispatcher,  # type: ignore[arg-type]
        is_transient=_is_transient,
        base_seed=42,
        chat_corpus=_fake_chat_corpus(),
        embed_corpus=_fake_embed_corpus(),
    )
    for call in dispatcher.calls:
        block_inputs = call["block_inputs"]
        assert isinstance(block_inputs, dict)
        prompt_source = block_inputs.get("prompt_source")
        if call["cell_id"] == "chat_stream_c8":
            assert prompt_source == "corpus_sharegpt"
        else:
            assert prompt_source == "corpus_sharegpt_embed"
