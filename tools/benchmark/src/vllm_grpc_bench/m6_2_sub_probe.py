"""M6.2 — KV-pressure sub-probe orchestrator (round-5 FR-036 / FR-017a).

The sub-probe is a **separate**, **additive** measurement loop that runs
alongside or after the main 144-point sweep. Per FR-036:

- 16 blocks total: 4 cohorts × 2 cell-types ``{chat_stream, embed}`` × 2 caps
  ``{1024, 2048}``.
- Each block dispatches ``n=M6_2_SUB_PROBE_N`` (20) RPCs at
  ``ignore_eos=True`` so the engine runs to the forced cap on every RPC.
- Each block uses the **corpus regime** (ShareGPT for chat, Qwen3-8B
  prompt-embeddings for embed) via :func:`m6_2_prompt_source.resolve_block_inputs`
  with ``ignore_eos_override=True``.
- Sub-probe rows are emitted to :class:`m6_2_crossover.SubProbeBlockResult`
  (NOT :class:`m6_2_types.M6_2MeasurementPoint`) — they DO NOT pollute the
  latency budget table. Only the c=8 cell type matters for FR-017a's
  wall-clock-ratio inference; the sub-probe runs at the conventional ``c=8``
  cell ids (``chat_stream_c8`` + ``embed_c8``).
- FR-030 cohort-innermost discipline applies within each ``(cell_type,
  max_tokens)`` tuple (4 cohorts back-to-back before advancing).
- FR-032 per-block UTC timestamps + FR-033 in-window retry-once apply.
- Sub-probe runs in BOTH publish and validate modes per SC-019.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable

from vllm_grpc_bench.corpus import (
    CompletionEmbedSample,
    RequestSample,
)
from vllm_grpc_bench.m6_1_2_types import M6_1_2_COHORTS, M6_1_2CohortKind
from vllm_grpc_bench.m6_2_crossover import SubProbeBlockResult
from vllm_grpc_bench.m6_2_prompt_source import resolve_block_inputs
from vllm_grpc_bench.m6_2_sweep import BlockDispatcher, RetryClassifier
from vllm_grpc_bench.m6_2_types import (
    M6_2_SUB_PROBE_MAX_TOKENS,
    M6_2_SUB_PROBE_N,
)

__all__ = [
    "SUB_PROBE_CELL_IDS",
    "SUB_PROBE_CELL_TYPES",
    "iter_sub_probe_tuples",
    "run_kv_pressure_sub_probe",
]


SUB_PROBE_CELL_TYPES: tuple[str, str] = ("chat_stream", "embed")
"""Cell-types the sub-probe iterates per FR-036 (both kinds matter for the
wall-clock-ratio inference per FR-017a)."""


SUB_PROBE_CELL_IDS: dict[str, str] = {
    "chat_stream": "chat_stream_c8",
    "embed": "embed_c8",
}
"""Conventional cell-id mapping: the sub-probe targets the ``c=8`` cell
because FR-017a's wall-clock-ratio inference is concerned with the
high-concurrency regime where KV-pressure manifests as wall-clock slowdown."""


def _now_iso_utc() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iter_sub_probe_tuples() -> list[tuple[str, int, M6_1_2CohortKind]]:
    """Full per-block dispatch sequence as ``(cell_type, max_tokens, cohort)``.

    FR-030 discipline within each ``(cell_type, max_tokens)`` tuple: all 4
    cohorts back-to-back before advancing. Returns the canonical 16-tuple
    sequence (2 cell-types × 2 caps × 4 cohorts).
    """
    out: list[tuple[str, int, M6_1_2CohortKind]] = []
    for cell_type in SUB_PROBE_CELL_TYPES:
        for max_tokens in M6_2_SUB_PROBE_MAX_TOKENS:
            for cohort in M6_1_2_COHORTS:
                out.append((cell_type, max_tokens, cohort))
    return out


def _percentile(samples: list[float], p: float) -> float:
    """Linear-interpolation percentile (matches the M6.2 reporter convention)."""
    if not samples:
        raise ValueError("percentile of empty sample set")
    sorted_samples = sorted(samples)
    if len(sorted_samples) == 1:
        return sorted_samples[0]
    idx = (p / 100.0) * (len(sorted_samples) - 1)
    low = int(idx)
    high = min(low + 1, len(sorted_samples) - 1)
    weight = idx - low
    return sorted_samples[low] * (1.0 - weight) + sorted_samples[high] * weight


async def run_kv_pressure_sub_probe(
    *,
    dispatcher: BlockDispatcher,
    is_transient: RetryClassifier,
    base_seed: int,
    chat_corpus: list[RequestSample],
    embed_corpus: list[CompletionEmbedSample],
    n: int = M6_2_SUB_PROBE_N,
    now_iso_utc: Callable[[], str] = _now_iso_utc,
) -> list[SubProbeBlockResult]:
    """Drive the 16-block sub-probe loop per FR-036.

    Per FR-030 cohort-innermost discipline: for each ``(cell_type,
    max_tokens)`` tuple, all 4 cohorts dispatch back-to-back. Per FR-032:
    each block carries ``block_start_utc`` + ``block_end_utc``. Per FR-033:
    transient errors retry once in-window; non-transient errors fail the
    block immediately (``failed_reason`` is populated).

    Each block calls :func:`m6_2_prompt_source.resolve_block_inputs` with
    ``ignore_eos_override=True`` so the prompt-source resolver returns the
    corpus regime + ``ignore_eos=True`` flag the wire builder will translate.
    """
    from vllm_grpc_bench.m6_2_sweep import run_block_with_retry

    out: list[SubProbeBlockResult] = []
    for iter_idx, (cell_type, max_tokens, cohort) in enumerate(iter_sub_probe_tuples()):
        cell_id = SUB_PROBE_CELL_IDS[cell_type]
        block_inputs = resolve_block_inputs(
            cell=cell_id,
            max_tokens=max_tokens,
            iter_idx=iter_idx,
            cohort=cohort,
            base_seed=base_seed,
            chat_corpus=chat_corpus,
            embed_corpus=embed_corpus,
            ignore_eos_override=True,
        )
        (
            result,
            block_start_utc,
            block_end_utc,
            retry_attempted,
        ) = await run_block_with_retry(
            cell_id=cell_id,
            cohort=cohort,
            max_tokens=max_tokens,
            n=n,
            block_inputs=block_inputs,
            dispatcher=dispatcher,
            is_transient=is_transient,
            now_iso_utc=now_iso_utc,
        )
        out.append(
            _build_sub_probe_row(
                cohort=cohort,
                cell_type=cell_type,
                max_tokens=max_tokens,
                n=n,
                timings_ms=result.timings_ms,
                failed_reason=result.failed_reason,
                per_rpc_metadata=result.per_rpc_metadata,
                block_start_utc=block_start_utc,
                block_end_utc=block_end_utc,
                retry_attempted=retry_attempted,
            )
        )
    return out


def _build_sub_probe_row(
    *,
    cohort: M6_1_2CohortKind,
    cell_type: str,
    max_tokens: int,
    n: int,
    timings_ms: list[float],
    failed_reason: str | None,
    per_rpc_metadata: list[dict[str, str]],
    block_start_utc: str,
    block_end_utc: str,
    retry_attempted: bool,
) -> SubProbeBlockResult:
    """Aggregate per-RPC timings + trailing metadata into one sub-probe row."""
    if failed_reason is not None or not timings_ms:
        return SubProbeBlockResult(
            cohort=cohort,
            cell_type=cell_type,
            max_tokens=max_tokens,
            n_rpcs=n,
            wall_p50_ms=None,
            wall_p95_ms=None,
            failed_reason=failed_reason or "no_successful_rpcs",
            kv_cache_used_fraction_peak=None,
            scheduling_stall_signals=None,
            block_start_utc=block_start_utc,
            block_end_utc=block_end_utc,
            retry_attempted=retry_attempted,
        )

    p50 = _percentile(timings_ms, 50.0)
    p95 = _percentile(timings_ms, 95.0)
    engine_peak = _extract_engine_kv_fraction_peak(per_rpc_metadata)
    stall = _extract_scheduling_stall_signals(per_rpc_metadata)
    return SubProbeBlockResult(
        cohort=cohort,
        cell_type=cell_type,
        max_tokens=max_tokens,
        n_rpcs=n,
        wall_p50_ms=p50,
        wall_p95_ms=p95,
        failed_reason=None,
        kv_cache_used_fraction_peak=engine_peak,
        scheduling_stall_signals=stall,
        block_start_utc=block_start_utc,
        block_end_utc=block_end_utc,
        retry_attempted=retry_attempted,
    )


def _extract_engine_kv_fraction_peak(
    per_rpc_metadata: list[dict[str, str]],
) -> float | None:
    """Best-effort extraction of the peak ``engine_kv_cache_used_fraction``
    field from per-RPC trailing metadata. Returns ``None`` if no RPC
    surfaces the field (vLLM doesn't always expose it).
    """
    values: list[float] = []
    for meta in per_rpc_metadata:
        raw = meta.get("engine_kv_cache_used_fraction") or meta.get("kv_cache_used_fraction")
        if raw is None:
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    return max(values)


def _extract_scheduling_stall_signals(
    per_rpc_metadata: list[dict[str, str]],
) -> str | None:
    """Best-effort extraction of ``scheduling_stall`` markers from per-RPC
    trailing metadata. Returns a comma-joined deduplicated string when any
    RPC surfaces the field, ``None`` otherwise.
    """
    seen: set[str] = set()
    for meta in per_rpc_metadata:
        for key in ("scheduling_stall", "engine_scheduling_stall"):
            val = meta.get(key)
            if val:
                seen.add(val)
    if not seen:
        return None
    return ",".join(sorted(seen))
