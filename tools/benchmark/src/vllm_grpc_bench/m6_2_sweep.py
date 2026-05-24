"""M6.2 — Token-Budget Characterization: sweep orchestrator skeleton.

Mirrors :mod:`m6_1_3_sweep`'s structure (topology probe + warmup + per-cell
× per-cohort measurement + per-RPC instrumentation extraction) and refactors
per ``specs/027-m6-2-token-budget/contracts/iteration-order.md`` round-4 +
round-5 amendments:

* FR-030 cohort-innermost block iteration over ``(cell × max_tokens ×
  cohort)``.
* FR-031 4-hour anchor re-measurement via
  :mod:`m6_2_anchor_trajectory.compute_anchor_block`.
* FR-032 per-block UTC timestamps + post-hoc
  ``iteration_discipline_verified`` machine check.
* FR-033 in-window retry-once dispatch wrapper.
* FR-009 ``network_paths`` topology probe co-firing at 4h marks.
* FR-004 round-3 ``--m6_2-n`` deferral gate (publish refuses to start until
  ``args.m6_2_n`` is pinned).
* SC-018 corpus-SHA validation gate at sweep start (``CorpusDriftError``
  aborts).
* Round-5 three-regime prompt-source dispatch via
  :mod:`m6_2_prompt_source.resolve_block_inputs`.

Removes M6.1.3's multi-run / between-run variance / Phase B / audit-pooling
logic (those concerns don't recur in M6.2's headline deliverable).

Inherits verbatim from imported modules:
* M6.0a concurrent dispatch (``m6_sweep``).
* M6.1.x classifier instrumentation + 5-segment decomposition
  (``m6_1_3_sweep``, ``m6_1_1_timing``).
* M6.1.2 4-cohort iteration + topology probe (``m6_1_2_*``).

The orchestrator is structured around small, separately-testable pure
functions (iteration order, retry policy, discipline check) plus a single
async entry that wires them to RPC dispatch. The pure functions are the
contract surface T017 / T019 / T031 exercise; the entry is exercised by
T032 / T044 against the stub driver.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import statistics
import sys
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from vllm_grpc_bench.corpus import (
    CompletionEmbedSample,
    RequestSample,
)
from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2_COHORTS,
    M6_1_2CohortKind,
    cohorts_at_concurrency,
)
from vllm_grpc_bench.m6_1_types import M6_1_CELLS, M6_1Path
from vllm_grpc_bench.m6_2_anchor_trajectory import (
    AnchorRPCDriver,
    compute_anchor_block,
)
from vllm_grpc_bench.m6_2_prompt_source import (
    ResolvedBlockInputs,
    load_chat_corpus,
    load_chat_corpus_provenance,
    load_embed_corpus,
    load_embed_corpus_manifest,
    resolve_block_inputs,
)
from vllm_grpc_bench.m6_2_types import (
    M6_2_FAILURE_SUMMARY_CELL_COUNT_THRESHOLD,
    M6_2_MAX_TOKENS_AXIS,
    M6_2AnchorLatencySnapshot,
    M6_2MeasurementPoint,
    M6_2SweepMode,
)

__all__ = [
    "ANCHOR_CADENCE_HOURS",
    "BlockDispatchResult",
    "BlockDispatcher",
    "M6_2SweepInputs",
    "M6_2SweepOutputs",
    "RetryClassifier",
    "compute_failure_summary_header_fired",
    "iter_block_dispatch_order",
    "iter_main_sweep_tuples",
    "run_block_with_retry",
    "run_m6_2_sweep",
    "should_run_anchor_at",
    "verify_iteration_discipline",
    # Per-block aggregator (exported for unit tests + future reporters)
    "_aggregate_block_metrics",
    "_AggregatedRPCMetrics",
]


# --- Constants --------------------------------------------------------------

ANCHOR_CADENCE_HOURS: float = 4.0
"""FR-031 anchor re-measurement cadence (publish mode). Validate mode
collapses to start + end only when total wall-clock < 8 h."""


# --- Pure iteration helpers (FR-030 / FR-032) -------------------------------


def _cell_id_of(path: M6_1Path, concurrency: int) -> str:
    return f"{path}_c{concurrency}"


def iter_main_sweep_tuples(
    axis: tuple[int, ...] = M6_2_MAX_TOKENS_AXIS,
) -> list[tuple[str, int, int]]:
    """Outer × middle iteration sequence over ``(cell_id, concurrency, max_tokens)``.

    Concurrency is preserved on the tuple so ``cohorts_at_concurrency(c)`` can
    be called downstream without re-parsing the cell id."""
    out: list[tuple[str, int, int]] = []
    for path, _hidden_size, concurrency in M6_1_CELLS:
        cell_id = _cell_id_of(path, concurrency)
        for max_tokens in axis:
            out.append((cell_id, concurrency, max_tokens))
    return out


def iter_block_dispatch_order(
    axis: tuple[int, ...] = M6_2_MAX_TOKENS_AXIS,
) -> list[tuple[str, int, M6_1_2CohortKind]]:
    """Full per-block dispatch sequence as ``(cell_id, max_tokens, cohort)``.

    FR-030 cohort-innermost: for each ``(cell, max_tokens)`` tuple, all
    cohorts at that concurrency dispatch back-to-back before advancing.
    """
    out: list[tuple[str, int, M6_1_2CohortKind]] = []
    for cell_id, concurrency, max_tokens in iter_main_sweep_tuples(axis):
        for cohort in cohorts_at_concurrency(concurrency):
            out.append((cell_id, max_tokens, cohort))
    return out


def verify_iteration_discipline(points: Iterable[M6_2MeasurementPoint]) -> bool:
    """FR-032 post-hoc machine check: ``True`` iff every ``(cell, max_tokens)``
    tuple's cohort blocks form a contiguous, non-interleaved time window.

    Algorithm: order all blocks by ``block_start_utc``; walk the sequence
    grouping by ``(cell_id, max_tokens)`` tuple. Discipline is "broken" if
    after the first block of any tuple appears, a block from a DIFFERENT
    tuple appears, and then a block from the original tuple reappears.
    """
    points_list = list(points)
    if not points_list:
        return True
    sorted_points = sorted(points_list, key=lambda p: p.block_start_utc)
    seen_tuples: set[tuple[str, int]] = set()
    current_tuple: tuple[str, int] | None = None
    for point in sorted_points:
        tup = (point.cell_id, point.max_tokens)
        if tup == current_tuple:
            continue
        # Transitioning into a new tuple.
        if tup in seen_tuples:
            # We previously left this tuple and are coming back — interleaved.
            return False
        if current_tuple is not None:
            seen_tuples.add(current_tuple)
        current_tuple = tup
    return True


# --- FR-033 in-window retry dispatch wrapper --------------------------------


@dataclass(slots=True, kw_only=True)
class BlockDispatchResult:
    """Outcome of a single ``(cell, cohort, max_tokens)`` block dispatch.

    ``timings_ms`` is the per-RPC wall-clock latency list (empty on failure).
    ``failed_reason`` is ``None`` on success; a classifier-friendly string
    (e.g. ``"grpc_timeout"``, ``"oom"``) on failure.
    """

    timings_ms: list[float]
    failed_reason: str | None
    # Per-RPC trailing-metadata dicts (passed through to the segment
    # decomposition for FR-005 / FR-007 inheritance). Empty on failure.
    per_rpc_metadata: list[dict[str, str]]


class BlockDispatcher(Protocol):
    """Pluggable dispatch surface called for each ``(cell, cohort,
    max_tokens)`` block. Concrete implementations live in the validate /
    publish CLI entry, the stub-driver test fixture, and Modal-deploy paths.
    """

    async def __call__(
        self,
        *,
        cell_id: str,
        cohort: M6_1_2CohortKind,
        max_tokens: int,
        n: int,
        block_inputs: ResolvedBlockInputs,
    ) -> BlockDispatchResult: ...


class RetryClassifier(Protocol):
    """Classifies an exception as transient (retryable in-window) or
    non-transient (block fails permanently). The orchestrator wires this to
    a concrete predicate; tests inject a stub."""

    def __call__(self, exc: BaseException) -> bool: ...


def _now_iso_utc() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stderr_ts() -> str:
    """Bracketed ISO-8601 UTC prefix for stderr diagnostic lines.

    Mirrors `m6_1_3_sweep._stderr_ts` so clock-anomaly logging fits the
    project-wide stderr emission style (FR-018 / R-7 inherited convention)."""
    return _dt.datetime.now(_dt.UTC).strftime("[%Y-%m-%dT%H:%M:%SZ]")


def _progress(tag: str, **fields: object) -> None:
    """Emit a single-line progress event to stderr.

    Format (machine-parseable by ``scripts/python/monitor_m6_2_sweep.py``):
    ``[YYYY-MM-DDTHH:MM:SSZ] [m6_2 <TAG>] k1=v1 k2=v2 ...``.

    Lines are flushed eagerly so a tee'd log can be tail'd in near-real-time
    by the monitor script. Values are stringified verbatim; numeric fields
    SHOULD already carry their unit suffix (e.g. ``elapsed_s=42.5``) so the
    monitor doesn't need a per-field unit table."""
    parts = [f"{_stderr_ts()} [m6_2 {tag}]"]
    parts.extend(f"{k}={v}" for k, v in fields.items())
    print(" ".join(parts), file=sys.stderr, flush=True)


def _count_expected_blocks(axis: tuple[int, ...]) -> int:
    """Total measurement blocks the orchestrator will execute against
    ``axis``: ``sum(len(cohorts_at_concurrency(c)) for each (cell, max_tokens))``.

    Used by the sweep-start progress banner so a monitor consumer can
    compute completion percentage as ``blocks_done / expected_blocks``.
    Validate-mode axis subset {10, 50, 2048} → 66 blocks; publish-mode full
    axis {10, 50, 256, 512, 1024, 2048} → 132 blocks under the M6.1.2
    live-cohort discipline."""
    total = 0
    for _cell_id, concurrency, _max_tokens in iter_main_sweep_tuples(axis):
        total += len(cohorts_at_concurrency(concurrency))
    return total


def _count_expected_tuples(axis: tuple[int, ...]) -> int:
    """Total (cell, max_tokens) tuples the orchestrator iterates against
    ``axis``. Each tuple contains 3 (c=1) or 4 (c=4/c=8) cohort blocks per
    FR-006. Used by the per-tuple progress line so the monitor can report
    "tuple X/Y" completion."""
    return sum(1 for _ in iter_main_sweep_tuples(axis))


async def run_block_with_retry(
    *,
    cell_id: str,
    cohort: M6_1_2CohortKind,
    max_tokens: int,
    n: int,
    block_inputs: ResolvedBlockInputs,
    dispatcher: BlockDispatcher,
    is_transient: RetryClassifier,
    now_iso_utc: Callable[[], str] = _now_iso_utc,
) -> tuple[BlockDispatchResult, str, str, bool]:
    """FR-033 in-window retry-once wrapper.

    Returns ``(result, block_start_utc, block_end_utc, retry_attempted)``.

    First attempt: if it raises a transient exception, retries ONCE within
    the same time window. If retry succeeds, the returned result is the
    retry's; ``retry_attempted=True``. If both fail, the result's
    ``failed_reason`` is the second failure's classified reason and
    ``retry_attempted=True``.

    Non-transient exceptions fail the block immediately with no retry
    (``retry_attempted=False``).
    """
    block_start_utc = now_iso_utc()
    retry_attempted = False
    try:
        result = await dispatcher(
            cell_id=cell_id,
            cohort=cohort,
            max_tokens=max_tokens,
            n=n,
            block_inputs=block_inputs,
        )
    except BaseException as exc:
        if not is_transient(exc):
            block_end_utc = now_iso_utc()
            return (
                BlockDispatchResult(
                    timings_ms=[],
                    failed_reason=_classify_exception(exc),
                    per_rpc_metadata=[],
                ),
                block_start_utc,
                block_end_utc,
                retry_attempted,
            )
        # Transient → in-window retry once.
        retry_attempted = True
        try:
            result = await dispatcher(
                cell_id=cell_id,
                cohort=cohort,
                max_tokens=max_tokens,
                n=n,
                block_inputs=block_inputs,
            )
        except BaseException as exc2:
            block_end_utc = now_iso_utc()
            return (
                BlockDispatchResult(
                    timings_ms=[],
                    failed_reason=_classify_exception(exc2),
                    per_rpc_metadata=[],
                ),
                block_start_utc,
                block_end_utc,
                retry_attempted,
            )

    # If dispatcher returned a failure result (no exception raised) and the
    # failure is transient-coded, retry once.
    if result.failed_reason is not None and result.failed_reason in _TRANSIENT_FAILURE_REASONS:
        retry_attempted = True
        try:
            result = await dispatcher(
                cell_id=cell_id,
                cohort=cohort,
                max_tokens=max_tokens,
                n=n,
                block_inputs=block_inputs,
            )
        except BaseException as exc:
            block_end_utc = now_iso_utc()
            return (
                BlockDispatchResult(
                    timings_ms=[],
                    failed_reason=_classify_exception(exc),
                    per_rpc_metadata=[],
                ),
                block_start_utc,
                block_end_utc,
                retry_attempted,
            )

    block_end_utc = now_iso_utc()
    return result, block_start_utc, block_end_utc, retry_attempted


_TRANSIENT_FAILURE_REASONS: frozenset[str] = frozenset(
    {
        "grpc_unavailable",
        "grpc_deadline_exceeded",
        "grpc_resource_exhausted",
        "grpc_internal",
        "asyncio_timeout",
        "rest_transient",
        "single_rpc_engine_oom",
    }
)


def _classify_exception(exc: BaseException) -> str:
    """Best-effort exception → failed_reason classifier. Mirrors M6.1.x's
    error classification table for the rows that surface in the artifact's
    failure_summary. The orchestrator's exact predicate is the
    ``is_transient`` classifier passed in; this helper provides the
    canonical string label."""
    name = type(exc).__name__
    msg = str(exc).lower()
    if "deadline" in msg or "TimeoutError" in name:
        return "grpc_deadline_exceeded"
    if "unavailable" in msg:
        return "grpc_unavailable"
    if "resource_exhausted" in msg or "out of memory" in msg or "oom" in msg:
        return "single_rpc_engine_oom"
    if "rpcerror" in name.lower():
        return "grpc_internal"
    if "httpx" in name.lower() or "connection" in msg:
        return "rest_transient"
    return f"unexpected_{name}"


# --- FR-031 anchor cadence rule --------------------------------------------


def should_run_anchor_at(
    sweep_hour_mark: float,
    sweep_mode: M6_2SweepMode,
    *,
    total_sweep_hours: float | None = None,
    cadence_hours: float = ANCHOR_CADENCE_HOURS,
    epsilon_hours: float = 0.05,
) -> bool:
    """Return True iff the orchestrator should fire an anchor block at the
    given sweep-hour mark.

    Sweep start (``0``) and sweep end (``total_sweep_hours``) always fire.
    Otherwise: publish mode fires every ``cadence_hours``; validate mode
    fires the same cadence only if ``total_sweep_hours >= 8 h``.
    """
    if sweep_hour_mark <= epsilon_hours:
        return True
    if total_sweep_hours is not None and abs(sweep_hour_mark - total_sweep_hours) <= epsilon_hours:
        return True
    if sweep_mode == "validate" and (total_sweep_hours is None or total_sweep_hours < 8.0):
        return False
    multiples = sweep_hour_mark / cadence_hours
    return abs(multiples - round(multiples)) <= (epsilon_hours / cadence_hours)


# --- FR-029 failure summary sweep-level header ------------------------------


def compute_failure_summary_header_fired(
    points: Iterable[M6_2MeasurementPoint],
    *,
    cell_threshold: int = M6_2_FAILURE_SUMMARY_CELL_COUNT_THRESHOLD,
) -> bool:
    """FR-029 sweep-level ``failure_summary_threshold`` integrity header
    rule: fire if either
    (a) the cumulative count of failed (cell, cohort, max_tokens) blocks
        across the sweep is >= ``cell_threshold``, OR
    (b) any ``(cell, max_tokens)`` tuple sees ALL its cohort blocks fail.
    """
    points_list = list(points)
    failed = [p for p in points_list if p.failed_reason is not None]
    if len(failed) >= cell_threshold:
        return True
    tuple_groups: dict[tuple[str, int], list[M6_2MeasurementPoint]] = {}
    for p in points_list:
        tuple_groups.setdefault((p.cell_id, p.max_tokens), []).append(p)
    for blocks in tuple_groups.values():
        if blocks and all(b.failed_reason is not None for b in blocks):
            return True
    return False


# --- Orchestrator entry skeleton --------------------------------------------


@dataclass(slots=True, kw_only=True)
class M6_2SweepInputs:
    """Sweep inputs assembled by ``m6_2_validate.run_m6_2(...)`` and handed
    to :func:`run_m6_2_sweep`.

    ``axis`` controls the publish-vs-validate axis subset; ``n`` is the
    round-3-pinned (publish) or 20 (validate) per-block sample size;
    ``dispatcher`` + ``anchor_dispatcher`` are pluggable so the validate-CLI
    tests can inject a stub. ``is_transient`` is the FR-033 retry predicate.
    """

    sweep_mode: M6_2SweepMode
    n: int
    axis: tuple[int, ...]
    base_seed: int
    chat_corpus: list[RequestSample]
    embed_corpus: list[CompletionEmbedSample]
    dispatcher: BlockDispatcher
    anchor_dispatcher: AnchorRPCDriver
    is_transient: RetryClassifier
    topology_probe: Callable[[], Awaitable[dict[M6_1_2CohortKind, Any]]] | None = None
    """FR-009 network-paths probe (m6_1_2_network_probe.run_topology_probe).

    Fires at sweep start + end (validate sweeps < 8 h); publish sweeps
    additionally fire at every 4 h mark per the same cadence as the anchor
    block. ``None`` disables the probe (stub / test paths)."""


@dataclass(slots=True, kw_only=True)
class M6_2SweepOutputs:
    """Sweep outputs handed back to ``m6_2_validate.run_m6_2(...)`` which
    then ships them to the reporter.

    The orchestrator emits the per-block ``M6_2MeasurementPoint`` rows + the
    per-cohort anchor snapshots + the per-cohort topology-probe trajectory;
    the reporter (T022-T030) renders these into the full markdown + JSON.
    """

    measurements: list[M6_2MeasurementPoint]
    anchor_snapshots: dict[M6_1_2CohortKind, list[M6_2AnchorLatencySnapshot]]
    iteration_discipline_verified: bool
    wall_clock_start_utc: str
    wall_clock_end_utc: str
    network_paths: dict[M6_1_2CohortKind, list[Any]] | None = None


def gate_publish_mode_n(args_m6_2_n: int | None, sweep_mode: M6_2SweepMode) -> int:
    """FR-004 explicit-n gate.

    Publish mode REFUSES to start when ``args.m6_2_n is None`` — the
    operator MUST pass ``--m6_2-n=<N>`` to make the sample-size choice
    explicit at the command line (no silent default). The canonical
    round-3-pinned production value is :data:`m6_2_types.M6_2_PUBLISH_N`
    (currently ``40``, pinned 2026-05-24 against the validate-sweep
    measured CI half-widths). Validate mode coerces to the hard-pinned
    ``n=20`` per FR-001 round-1 Q2. Returns the resolved ``n``.
    """
    if sweep_mode == "publish":
        if args_m6_2_n is None:
            raise ValueError(
                "FR-004 explicit-n gate: --m6_2 cannot start without an explicit "
                "--m6_2-n value. The round-3-pinned production value is n=40 "
                "(see m6_2_types.M6_2_PUBLISH_N). Pass --m6_2-n=40 to launch the "
                "canonical publish sweep, or pass a different n to override."
            )
        return args_m6_2_n
    if args_m6_2_n is not None and args_m6_2_n != 20:
        raise ValueError(
            f"--m6_2-validate is pinned at n=20 per FR-001 round-1 Q2; got "
            f"--m6_2-n={args_m6_2_n}. Drop the flag or pass n=20 explicitly."
        )
    return 20


def gate_corpus_shas(
    chat_corpus_path: Any | None = None,
    embed_corpus_dir: Any | None = None,
) -> tuple[str, str, str, str]:
    """SC-018 sweep-start corpus-SHA validation gate.

    Calls :func:`load_chat_corpus` + :func:`load_embed_corpus` (both of
    which raise :class:`CorpusDriftError` on SHA mismatch) and returns
    ``(chat_sha, chat_path, embed_sha, embed_path)`` so the orchestrator can
    record them in ``run_meta``. Re-raises :class:`CorpusDriftError` and
    :class:`FileNotFoundError` to abort the sweep.
    """
    chat_corpus = load_chat_corpus()  # raises CorpusDriftError on mismatch
    embed_corpus = load_embed_corpus()  # raises CorpusDriftError on mismatch
    del chat_corpus, embed_corpus  # corpora themselves are loaded again by the orchestrator
    chat_provenance = load_chat_corpus_provenance()
    embed_manifest = load_embed_corpus_manifest()
    return (
        str(chat_provenance["corpus_sha256"]),
        str(chat_provenance.get("corpus_path", "tools/benchmark/corpus/chat_sharegpt_1000.json")),
        str(embed_manifest["corpus_sha256"]),
        "tools/benchmark/corpus/completions_embeds_qwen3_8b/",
    )


async def run_m6_2_sweep(inputs: M6_2SweepInputs) -> M6_2SweepOutputs:
    """Drive the M6.2 sweep iteration end-to-end.

    Iteration: FR-030 cohort-innermost over ``M6_1_CELLS × axis × cohorts``.
    Per-block: FR-032 UTC timestamps + FR-033 in-window retry. Anchor blocks
    fire at sweep start, every 4 h (per :func:`should_run_anchor_at`), and at
    sweep end.

    This is the foundational orchestrator; US3's sub-probe (T039) wires into
    the same iteration sequence after the main loop. US1's reporter (T022)
    consumes the returned :class:`M6_2SweepOutputs` to render the artifact.
    """
    sweep_start_utc = _now_iso_utc()
    sweep_start_perf = asyncio.get_event_loop().time()

    measurements: list[M6_2MeasurementPoint] = []
    anchor_snapshots: dict[M6_1_2CohortKind, list[M6_2AnchorLatencySnapshot]] = {}
    network_paths_trajectory: dict[M6_1_2CohortKind, list[Any]] = {
        cohort: [] for cohort in M6_1_2_COHORTS
    }

    expected_blocks = _count_expected_blocks(inputs.axis)
    expected_tuples = _count_expected_tuples(inputs.axis)
    _progress(
        "SWEEP_START",
        mode=inputs.sweep_mode,
        n=inputs.n,
        axis=",".join(str(c) for c in inputs.axis),
        expected_blocks=expected_blocks,
        expected_tuples=expected_tuples,
        utc=sweep_start_utc,
    )

    # FR-009 topology probe at sweep start.
    _progress("TOPOLOGY_PROBE_START", phase="sweep_start")
    await _capture_topology_probe(network_paths_trajectory, inputs.topology_probe)
    _progress("TOPOLOGY_PROBE_END", phase="sweep_start")

    # Anchor at sweep start (t = 0h).
    _progress("ANCHOR_START", sweep_hour_mark=f"{0.0:.2f}")
    anchor_t0_perf = asyncio.get_event_loop().time()
    await _capture_anchor_block(
        snapshots_by_cohort=anchor_snapshots,
        rpc_driver=inputs.anchor_dispatcher,
        base_seed=inputs.base_seed,
        sweep_hour_mark=0.0,
    )
    _progress(
        "ANCHOR_END",
        sweep_hour_mark=f"{0.0:.2f}",
        duration_s=f"{asyncio.get_event_loop().time() - anchor_t0_perf:.1f}",
        cohorts_captured=len(anchor_snapshots),
    )

    for tuple_idx_minus_one, (cell_id, concurrency, max_tokens) in enumerate(
        iter_main_sweep_tuples(inputs.axis)
    ):
        tuple_idx = tuple_idx_minus_one + 1
        elapsed_h = (asyncio.get_event_loop().time() - sweep_start_perf) / 3600.0
        _progress(
            "TUPLE_START",
            i=f"{tuple_idx}/{expected_tuples}",
            cell=cell_id,
            max_tokens=max_tokens,
            cohorts=len(cohorts_at_concurrency(concurrency)),
            elapsed_h=f"{elapsed_h:.3f}",
            blocks_done=len(measurements),
        )
        tuple_start_perf = asyncio.get_event_loop().time()
        for cohort in cohorts_at_concurrency(concurrency):
            iter_idx = len(measurements)
            block_inputs = resolve_block_inputs(
                cell=cell_id,
                max_tokens=max_tokens,
                iter_idx=iter_idx,
                cohort=cohort,
                base_seed=inputs.base_seed,
                chat_corpus=inputs.chat_corpus,
                embed_corpus=inputs.embed_corpus,
                ignore_eos_override=None,
            )
            block_perf_start = asyncio.get_event_loop().time()
            (
                result,
                block_start_utc,
                block_end_utc,
                retry_attempted,
            ) = await run_block_with_retry(
                cell_id=cell_id,
                cohort=cohort,
                max_tokens=max_tokens,
                n=inputs.n,
                block_inputs=block_inputs,
                dispatcher=inputs.dispatcher,
                is_transient=inputs.is_transient,
            )
            measurement = _build_measurement_point(
                cell_id=cell_id,
                cohort=cohort,
                max_tokens=max_tokens,
                n=inputs.n,
                result=result,
                block_start_utc=block_start_utc,
                block_end_utc=block_end_utc,
                retry_attempted=retry_attempted,
                block_inputs=block_inputs,
            )
            measurements.append(measurement)
            block_duration_s = asyncio.get_event_loop().time() - block_perf_start
            _progress(
                "BLOCK_DONE",
                i=f"{len(measurements)}/{expected_blocks}",
                cell=cell_id,
                cohort=cohort,
                max_tokens=max_tokens,
                duration_s=f"{block_duration_s:.1f}",
                wall_p50_ms=(
                    f"{measurement.wall_p50_ms:.1f}"
                    if measurement.wall_p50_ms is not None
                    else "—"
                ),
                failed=measurement.failed_reason or "no",
                retry=str(retry_attempted),
            )

        _progress(
            "TUPLE_END",
            i=f"{tuple_idx}/{expected_tuples}",
            cell=cell_id,
            max_tokens=max_tokens,
            duration_s=f"{asyncio.get_event_loop().time() - tuple_start_perf:.1f}",
        )

        # After each `(cell, max_tokens)` tuple, check whether the 4h anchor
        # cadence has elapsed. Capture at the cadence + at sweep end.
        elapsed_hours = (asyncio.get_event_loop().time() - sweep_start_perf) / 3600.0
        if should_run_anchor_at(
            sweep_hour_mark=elapsed_hours,
            sweep_mode=inputs.sweep_mode,
        ):
            _progress("ANCHOR_START", sweep_hour_mark=f"{elapsed_hours:.2f}")
            anchor_perf = asyncio.get_event_loop().time()
            await _capture_anchor_block(
                snapshots_by_cohort=anchor_snapshots,
                rpc_driver=inputs.anchor_dispatcher,
                base_seed=inputs.base_seed,
                sweep_hour_mark=elapsed_hours,
            )
            _progress(
                "ANCHOR_END",
                sweep_hour_mark=f"{elapsed_hours:.2f}",
                duration_s=f"{asyncio.get_event_loop().time() - anchor_perf:.1f}",
            )

    sweep_end_utc = _now_iso_utc()
    elapsed_hours = (asyncio.get_event_loop().time() - sweep_start_perf) / 3600.0
    # Anchor at sweep end if we haven't already captured one at this mark.
    last_marks = [s.sweep_hour_mark for snapshots in anchor_snapshots.values() for s in snapshots]
    if not last_marks or max(last_marks) < elapsed_hours - 0.05:
        _progress("ANCHOR_START", sweep_hour_mark=f"{elapsed_hours:.2f}", phase="sweep_end")
        anchor_perf = asyncio.get_event_loop().time()
        await _capture_anchor_block(
            snapshots_by_cohort=anchor_snapshots,
            rpc_driver=inputs.anchor_dispatcher,
            base_seed=inputs.base_seed,
            sweep_hour_mark=elapsed_hours,
        )
        _progress(
            "ANCHOR_END",
            sweep_hour_mark=f"{elapsed_hours:.2f}",
            duration_s=f"{asyncio.get_event_loop().time() - anchor_perf:.1f}",
            phase="sweep_end",
        )

    # FR-009 topology probe at sweep end.
    _progress("TOPOLOGY_PROBE_START", phase="sweep_end")
    await _capture_topology_probe(network_paths_trajectory, inputs.topology_probe)
    _progress("TOPOLOGY_PROBE_END", phase="sweep_end")

    _progress(
        "SWEEP_END",
        mode=inputs.sweep_mode,
        blocks_done=len(measurements),
        elapsed_h=f"{elapsed_hours:.3f}",
        utc=sweep_end_utc,
    )

    return M6_2SweepOutputs(
        measurements=measurements,
        anchor_snapshots=anchor_snapshots,
        iteration_discipline_verified=verify_iteration_discipline(measurements),
        wall_clock_start_utc=sweep_start_utc,
        wall_clock_end_utc=sweep_end_utc,
        network_paths=network_paths_trajectory if inputs.topology_probe is not None else None,
    )


# --- Per-block aggregation of per-RPC timing payloads -----------------------

_CLOCK_ANOMALY_MAX_FRACTION: float = 0.005
"""SC-011 cell-level clock-anomaly gate (0.5% of RPCs flagged).

Inherited from M6.1.3's `M6_1_3ClassifierThresholds.clock_anomaly_max_fraction`.
When a block's fraction of clock-anomalous RPCs (negative `seg_ingress_ms`
or `seg_egress_ms` from wall↔monotonic clock-source mismatch) exceeds this
threshold, the row's `clock_anomaly` flag fires."""


@dataclass(slots=True, kw_only=True)
class _AggregatedRPCMetrics:
    """Per-block statistical summary derived from `(timings_ms, per_rpc_metadata)`.

    Wall percentiles come from `timings_ms` directly. Segment means + TPOT
    come from the per-RPC payload dict (M6.1.1 timing checkpoints +
    `engine_cost.engine_tpot_ms` threaded through by
    `m6_2_validate.build_modal_block_dispatcher`).

    Each field is `None` when its source data is missing — e.g., REST cohorts
    without the M6.1.3 proxy-edge anchors leave `seg_ingress_ms` /
    `seg_egress_ms` as `None`; embed cohorts (unary RPC) leave `tpot_ms` as
    `None` because there's no per-token rate to measure.
    """

    wall_p50_ms: float
    wall_p95_ms: float
    wall_p99_ms: float
    wall_p50_ms_ci_half_width: float
    tpot_ms: float | None
    seg_ab_ms: float | None
    seg_queue_ms: float | None
    seg_prefill_ms: float | None
    seg_ingress_ms: float | None
    seg_egress_ms: float | None
    clock_anomaly_fraction: float
    clock_anomaly: bool


def _ci_half_width_95(samples: list[float]) -> float:
    """95% normal-approximation CI half-width (1.96 × stderr).

    Mirrors `m6_1_3_reporter._ci_half_width_95` verbatim. Returns 0.0 when
    `n < 2` (stdev undefined).
    """
    if len(samples) < 2:
        return 0.0
    return float(1.96 * statistics.stdev(samples) / (len(samples) ** 0.5))


def _parse_int(md: dict[str, str], key: str) -> int | None:
    """Best-effort int parser. Returns `None` if the key is absent or the
    value isn't a parseable integer."""
    raw = md.get(key)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_float(md: dict[str, str], key: str) -> float | None:
    """Best-effort float parser. Returns `None` on absent / unparseable."""
    raw = md.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _mean_or_none(samples: list[float]) -> float | None:
    if not samples:
        return None
    return sum(samples) / len(samples)


def _aggregate_block_metrics(
    timings_ms: list[float],
    per_rpc_metadata: list[dict[str, str]],
    *,
    cell_id: str = "",
    cohort: str = "",
) -> _AggregatedRPCMetrics:
    """Aggregate per-RPC timings + metadata dicts into a single block summary.

    Wall percentiles + CI half-width derive from `timings_ms`. Segment means
    derive from `per_rpc_metadata` entries containing M6.1.1 timing checkpoint
    keys (handler_entry_ns / pre_engine_ns / first_chunk_ns / terminal_emit_ns)
    + M6.1.2 engine-internal keys (engine_queued_ns / engine_scheduled_ns /
    engine_first_token_ns) + M6.1.3 proxy-edge keys (pre_engine_wall_ns /
    first_chunk_mono_ns / engine_arrival_ns). TPOT comes from the
    `engine_tpot_ms` key threaded in by `build_modal_block_dispatcher`.

    Per FR-006 + SC-011: rows where a derived segment goes negative (clock
    anomaly from wall↔monotonic conversion in the proxy-edge derivation) are
    excluded from that segment's mean and counted toward the cell-level
    `clock_anomaly_fraction`. Negative values are logged to stderr for
    diagnostic trace.

    `cell_id` / `cohort` are passed through for clock-anomaly stderr logging
    only — neither affects the returned aggregates.
    """
    sorted_t = sorted(timings_ms)
    wall_p50 = _percentile(sorted_t, 50.0)
    wall_p95 = _percentile(sorted_t, 95.0)
    wall_p99 = _percentile(sorted_t, 99.0)
    wall_ci = _ci_half_width_95(timings_ms)

    # Per-RPC seg_ab / seg_bc / seg_cd from the M6.1.1 perf_counter checkpoints.
    seg_ab: list[float] = []
    for md in per_rpc_metadata:
        h = _parse_int(md, "handler_entry_ns")
        p = _parse_int(md, "pre_engine_ns")
        if h is None or p is None:
            continue
        seg_ab.append((p - h) * 1e-6)

    # Per-RPC seg_queue / seg_prefill from the M6.1.2 engine-internal stats.
    # Skip rows where any engine-stat field is 0 (vLLM didn't populate).
    seg_queue: list[float] = []
    seg_prefill: list[float] = []
    for md in per_rpc_metadata:
        q = _parse_int(md, "engine_queued_ns") or 0
        s = _parse_int(md, "engine_scheduled_ns") or 0
        f = _parse_int(md, "engine_first_token_ns") or 0
        if q > 0 and s > 0 and f > 0:
            seg_queue.append((s - q) * 1e-6)
            seg_prefill.append((f - s) * 1e-6)

    # Per-RPC seg_ingress / seg_egress from the M6.1.3 proxy-edge anchors.
    # FR-006 clock-anomaly gate: negative deltas are logged + excluded.
    seg_ingress: list[float] = []
    seg_egress: list[float] = []
    anomaly_count = 0
    for md in per_rpc_metadata:
        rpc_anomalous = False
        pre_wall = _parse_int(md, "pre_engine_wall_ns")
        engine_arr = _parse_int(md, "engine_arrival_ns") or 0
        if pre_wall is not None and engine_arr > 0:
            delta_ms = (engine_arr - pre_wall) * 1e-6
            if delta_ms < 0:
                print(
                    f"{_stderr_ts()} [clock-anomaly] {cell_id}/{cohort} "
                    f"seg_ingress_ms={delta_ms:.3f} "
                    f"(engine_arrival_ns={engine_arr}, pre_engine_wall_ns={pre_wall})",
                    file=sys.stderr,
                    flush=True,
                )
                rpc_anomalous = True
            else:
                seg_ingress.append(delta_ms)

        first_mono = _parse_int(md, "first_chunk_mono_ns")
        engine_first = _parse_int(md, "engine_first_token_ns") or 0
        if first_mono is not None and engine_first > 0:
            delta_ms = (first_mono - engine_first) * 1e-6
            if delta_ms < 0:
                print(
                    f"{_stderr_ts()} [clock-anomaly] {cell_id}/{cohort} "
                    f"seg_egress_ms={delta_ms:.3f} "
                    f"(first_chunk_mono_ns={first_mono}, engine_first_token_ns={engine_first})",
                    file=sys.stderr,
                    flush=True,
                )
                rpc_anomalous = True
            else:
                seg_egress.append(delta_ms)

        if rpc_anomalous:
            anomaly_count += 1

    n_total = len(per_rpc_metadata)
    clock_anomaly_fraction = anomaly_count / n_total if n_total > 0 else 0.0
    clock_anomaly = clock_anomaly_fraction > _CLOCK_ANOMALY_MAX_FRACTION

    # Per-RPC engine_tpot_ms from `engine_cost.engine_tpot_ms` (only present on
    # chat_stream cells; embed cells leave it absent because TPOT is undefined
    # for unary RPCs).
    tpot_samples: list[float] = []
    for md in per_rpc_metadata:
        v = _parse_float(md, "engine_tpot_ms")
        if v is not None:
            tpot_samples.append(v)

    return _AggregatedRPCMetrics(
        wall_p50_ms=wall_p50,
        wall_p95_ms=wall_p95,
        wall_p99_ms=wall_p99,
        wall_p50_ms_ci_half_width=wall_ci,
        tpot_ms=_mean_or_none(tpot_samples),
        seg_ab_ms=_mean_or_none(seg_ab),
        seg_queue_ms=_mean_or_none(seg_queue),
        seg_prefill_ms=_mean_or_none(seg_prefill),
        seg_ingress_ms=_mean_or_none(seg_ingress),
        seg_egress_ms=_mean_or_none(seg_egress),
        clock_anomaly_fraction=clock_anomaly_fraction,
        clock_anomaly=clock_anomaly,
    )


def _build_measurement_point(
    *,
    cell_id: str,
    cohort: M6_1_2CohortKind,
    max_tokens: int,
    n: int,
    result: BlockDispatchResult,
    block_start_utc: str,
    block_end_utc: str,
    retry_attempted: bool,
    block_inputs: ResolvedBlockInputs,
) -> M6_2MeasurementPoint:
    """Build a per-block :class:`M6_2MeasurementPoint` from a dispatch result.

    On successful blocks the per-RPC payloads (from
    `BlockDispatchResult.per_rpc_metadata`) are aggregated via
    :func:`_aggregate_block_metrics` into the M6.2 per-cell row's
    `wall_p50_ms_ci_half_width`, `tpot_ms`, and the five
    `seg_{ab,queue,prefill,ingress,egress}_ms` segment means. Per FR-006 +
    SC-011 clock-anomalous rows are excluded from the affected segment's
    mean and counted toward the row's `clock_anomaly` flag.
    """
    if result.failed_reason is not None or not result.timings_ms:
        return M6_2MeasurementPoint(
            cell_id=cell_id,
            cohort=cohort,
            max_tokens=max_tokens,
            n_rpcs=n,
            wall_p50_ms=None,
            wall_p95_ms=None,
            wall_p99_ms=None,
            wall_p50_ms_ci_half_width=None,
            tpot_ms=None,
            seg_ab_ms=None,
            seg_queue_ms=None,
            seg_prefill_ms=None,
            seg_ingress_ms=None,
            seg_egress_ms=None,
            failed_reason=result.failed_reason or "no_successful_rpcs",
            block_start_utc=block_start_utc,
            block_end_utc=block_end_utc,
            retry_attempted=retry_attempted,
            clock_anomaly=False,
            prompt_source=block_inputs["prompt_source"],
            measurement_regime="natural_eos",
            prompt_corpus_idx=block_inputs.get("prompt_corpus_idx"),
        )
    agg = _aggregate_block_metrics(
        result.timings_ms,
        result.per_rpc_metadata,
        cell_id=cell_id,
        cohort=cohort,
    )
    return M6_2MeasurementPoint(
        cell_id=cell_id,
        cohort=cohort,
        max_tokens=max_tokens,
        n_rpcs=n,
        wall_p50_ms=agg.wall_p50_ms,
        wall_p95_ms=agg.wall_p95_ms,
        wall_p99_ms=agg.wall_p99_ms,
        wall_p50_ms_ci_half_width=agg.wall_p50_ms_ci_half_width,
        tpot_ms=agg.tpot_ms,
        seg_ab_ms=agg.seg_ab_ms,
        seg_queue_ms=agg.seg_queue_ms,
        seg_prefill_ms=agg.seg_prefill_ms,
        seg_ingress_ms=agg.seg_ingress_ms,
        seg_egress_ms=agg.seg_egress_ms,
        failed_reason=None,
        block_start_utc=block_start_utc,
        block_end_utc=block_end_utc,
        retry_attempted=retry_attempted,
        clock_anomaly=agg.clock_anomaly,
        prompt_source=block_inputs["prompt_source"],
        measurement_regime="natural_eos",
        prompt_corpus_idx=block_inputs.get("prompt_corpus_idx"),
    )


def _percentile(sorted_samples: list[float], p: float) -> float:
    if not sorted_samples:
        return 0.0
    if len(sorted_samples) == 1:
        return sorted_samples[0]
    idx = (p / 100.0) * (len(sorted_samples) - 1)
    low = int(idx)
    high = min(low + 1, len(sorted_samples) - 1)
    weight = idx - low
    return sorted_samples[low] * (1.0 - weight) + sorted_samples[high] * weight


async def _capture_anchor_block(
    *,
    snapshots_by_cohort: dict[M6_1_2CohortKind, list[M6_2AnchorLatencySnapshot]],
    rpc_driver: AnchorRPCDriver,
    base_seed: int,
    sweep_hour_mark: float,
) -> None:
    """Invoke :func:`compute_anchor_block` and append the per-cohort
    snapshots to ``snapshots_by_cohort``."""
    new_snapshots = await compute_anchor_block(
        cohorts=list(M6_1_2_COHORTS),
        rpc_driver=rpc_driver,
        base_seed=base_seed,
        sweep_hour_mark=sweep_hour_mark,
    )
    for cohort, snapshot in new_snapshots.items():
        snapshots_by_cohort.setdefault(cohort, []).append(snapshot)


async def _capture_topology_probe(
    trajectory_by_cohort: dict[M6_1_2CohortKind, list[Any]],
    probe: Callable[[], Awaitable[dict[M6_1_2CohortKind, Any]]] | None,
) -> None:
    """FR-009: fire one topology-probe pass + append per-cohort results.

    Each call appends one entry per cohort to ``trajectory_by_cohort[cohort]``;
    over a sweep, the per-cohort list grows into the FR-009 trajectory the
    reporter renders. ``probe=None`` is a no-op (test / stub paths).
    """
    if probe is None:
        return
    try:
        result = await probe()
    except Exception:  # noqa: BLE001
        # Probe failures NEVER abort the sweep per FR-001a; the absent entries
        # in `trajectory_by_cohort` are themselves the warning signal that the
        # reporter surfaces via its FR-009 / SC-010 channel.
        return
    for cohort, entry in result.items():
        trajectory_by_cohort.setdefault(cohort, []).append(entry)
