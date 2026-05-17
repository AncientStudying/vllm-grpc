"""M6 sweep orchestrator (T026-T028, T036-T038).

Implements the round-robin per c-batch sweep loop per Research R-8/R-9
plus per-cell aggregation, progress output, and RunMeta assembly.

The sweep is parameterized over an ``RPCDriver`` callable so tests can
inject synthetic latencies + failures without standing up Modal compute.
Production callers (CLI dispatch in ``__main__.py``) inject the real gRPC
+ REST drivers that consume the M6 instrumentation surface added in Phase 2.
"""

from __future__ import annotations

import asyncio
import math
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from vllm_grpc_bench.ci import estimate
from vllm_grpc_bench.m6_engine_cost import aggregate_engine_cost_per_cell
from vllm_grpc_bench.m6_seed import (
    DEFAULT_M6_BASE_SEED,
    MeasurementRpcIndexIterator,
    compute_rpc_seed,
)
from vllm_grpc_bench.m6_supersede import classify_cell
from vllm_grpc_bench.m6_types import (
    M6_CELL_COMPLETE_FLOOR,
    M6_COHORTS,
    M6_MEASUREMENT_N,
    M6_RPC_RETRY_MAX,
    M6_WARMUP_N,
    EngineCostSpan,
    M6Cell,
    M6CellRecord,
    M6CohortKind,
    M6PerCohortAggregate,
    M6RPCMeasurement,
    make_cells,
)

# --- RPC driver interface ----------------------------------------------------


@dataclass(frozen=True)
class RPCResult:
    """One RPC's measurement, as returned by an ``RPCDriver``.

    ``wall_clock_ms`` is the total per-RPC wall-clock (always set on
    success). ``ttft_ms`` is set ONLY for chat_stream cells (None for
    embed). ``engine_cost`` is the server-instrumented per-RPC cost
    parsed from the trailing metadata / SSE payload; None on
    instrumentation gap.

    ``m6_1_1_timing_payload`` is the four-checkpoint timing data parsed
    from the M6.1.1 wire format (``m6_1_1_timings`` SSE sub-object or
    ``m6_1_1_t_*`` trailing-metadata keys). Stored as a ``dict[str, int]``
    to keep m6_sweep / m6_types free of an m6_1_1_types import cycle;
    M6.1.1 callers re-hydrate to ``TimingCheckpoint`` via
    ``TimingCheckpoint(**payload)``. ``None`` on pre-M6.1.1 servers.
    """

    success: bool
    wall_clock_ms: float | None
    ttft_ms: float | None
    engine_cost: EngineCostSpan | None
    failure_reason: str | None
    m6_1_1_timing_payload: dict[str, int] | None = None


RPCDriver = Callable[[M6CohortKind, M6Cell, int], Awaitable[RPCResult]]
"""Async callable that drives one RPC for ``(cohort, cell, seed)``."""


# --- Progress reporter -------------------------------------------------------


def _stderr_ts() -> str:
    """ISO-8601 UTC bracket prefix for stderr progress lines, so log readers
    can correlate emissions with wall-clock time during long sweeps
    (spike/m6-1-roadmap-additions item #3). Matches the run_id timestamp
    format used elsewhere in the project."""
    return datetime.now(UTC).strftime("[%Y-%m-%dT%H:%M:%SZ]")


@dataclass
class ProgressReporter:
    """Emits stderr progress lines per contracts/cli.md.

    18 progress lines total (6 cells × 3 cohorts) plus a startup banner
    and a completion banner. Caller invokes :meth:`emit_startup` once,
    :meth:`emit_cell_cohort` after each (cell × cohort) measurement
    completes, and :meth:`emit_completion` at the end of the sweep.

    Each emission carries an ISO-8601 UTC timestamp prefix (item #3 from
    spike/m6-1-roadmap-additions) so multi-hour sweep logs are
    timestamp-correlatable without external tooling.
    """

    total_pairs: int = 18
    completed_pairs: int = 0
    start_time: float = 0.0

    def emit_startup(self, *, model: str, region: str) -> None:
        self.start_time = time.monotonic()
        print(
            f"{_stderr_ts()} M6 sweep: 6 cells × 3 cohorts × n={M6_MEASUREMENT_N}, "
            f"runtime ETA ≤90 min, model={model}, region={region}",
            file=sys.stderr,
        )

    def emit_cell_cohort(
        self,
        cell: M6Cell,
        cohort: M6CohortKind,
        successes: int,
        elapsed_ms: float,
    ) -> None:
        self.completed_pairs += 1
        elapsed_total = time.monotonic() - self.start_time
        if self.completed_pairs > 0:
            per_pair = elapsed_total / self.completed_pairs
            remaining = (self.total_pairs - self.completed_pairs) * per_pair
            eta_min = max(0, math.ceil(remaining / 60.0))
        else:
            eta_min = 0
        print(
            f"{_stderr_ts()} [{self.completed_pairs}/{self.total_pairs}] {cell.path} × "
            f"c={cell.concurrency} / {cohort} — {successes}/{M6_MEASUREMENT_N} succ — "
            f"{elapsed_ms:.0f} ms — ETA {eta_min}m",
            file=sys.stderr,
        )

    def emit_completion(self, report_path: str, tally: str) -> None:
        print(
            f"{_stderr_ts()} M6 sweep complete: verdict table at {report_path} ({tally})",
            file=sys.stderr,
        )


# --- Round-robin per c-batch sequencer (Research R-8, R-9) ------------------


def _c_batch_sizes_for_measurement(c: int, n: int = M6_MEASUREMENT_N) -> list[int]:
    """Return the per-round c-batch sizes for the measurement phase.

    Per Research R-9: at c=8 (n=100), we run 13 rounds where the last
    cohort drops the final 4 RPCs to keep n=100 exact (FR-004 invariant).

    For c=1, c=4: ``n / c`` is an integer so all rounds are full c-batches.
    """
    if n % c == 0:
        return [c] * (n // c)
    # Truncation rule: full rounds of c + a final partial round of (n % c).
    full_rounds = n // c
    remainder = n % c
    return [c] * full_rounds + [remainder]


def _c_batch_sizes_for_warmup(c: int, n: int = M6_WARMUP_N) -> list[int]:
    """Warmup uses the same per-c-batch rotation as measurement (R-8 / FR-022).

    At c=1: ``[1] * n`` (10 sequential rounds; no concurrent fan-out
    possible at c=1).
    At c=4: ``[4, 4, 2]`` for n=10 — 2 full c-batches plus a final partial
    round bringing the total to exactly ``n``.
    At c=8: ``[8, 2]`` for n=10.
    """
    if n % c == 0:
        return [c] * (n // c)
    full_rounds = n // c
    remainder = n % c
    return [c] * full_rounds + [remainder]


# --- Per-cell sweep loop -----------------------------------------------------


async def _run_one_rpc_with_retry(
    driver: RPCDriver,
    cohort: M6CohortKind,
    cell: M6Cell,
    seed: int,
    *,
    max_retries: int = M6_RPC_RETRY_MAX,
) -> tuple[RPCResult, int]:
    """Drive one RPC with up to ``max_retries`` attempts. Returns
    ``(final_result, retry_count)`` where retry_count is 0..max_retries.
    """
    last: RPCResult | None = None
    for attempt in range(max_retries + 1):
        last = await driver(cohort, cell, seed)
        if last.success:
            return last, attempt
    assert last is not None
    return last, max_retries


async def _run_warmup(
    driver: RPCDriver,
    cell: M6Cell,
    *,
    cohorts: tuple[M6CohortKind, ...] = M6_COHORTS,
) -> dict[M6CohortKind, int]:
    """Warmup phase per FR-021 — silently retry until 10 successes per cohort.

    Returns per-cohort success counts. If any cohort cannot accumulate 10
    successes (the retry pool is exhausted) the caller treats the cell as
    cell_incomplete and skips measurement (FR-023).

    M6.0a (FR-001 / FR-005a): dispatch is concurrent within a (cohort,
    c-batch). Each warmup attempt keeps its inner retry-until-success loop;
    only the outer "fire ``size`` warmups per cohort" loop becomes
    ``asyncio.gather``. Cohort iteration stays sequential per FR-005.
    """
    c = cell.concurrency
    successes: dict[M6CohortKind, int] = {k: 0 for k in cohorts}
    sizes = _c_batch_sizes_for_warmup(c)

    async def _warmup_one(cohort_ref: M6CohortKind) -> int:
        for _attempt in range(M6_RPC_RETRY_MAX + 1):
            # Warmup RPCs carry seed=0 (no measurement-RPC index).
            result = await driver(cohort_ref, cell, 0)
            if result.success:
                return 1
        return 0

    for size in sizes:
        for cohort in cohorts:
            attempt_results = await asyncio.gather(*(_warmup_one(cohort) for _ in range(size)))
            successes[cohort] += sum(attempt_results)
    return successes


async def _run_measurement(
    driver: RPCDriver,
    cell: M6Cell,
    rpc_indices: list[int],
    base_seed: int,
    *,
    cohorts: tuple[M6CohortKind, ...] = M6_COHORTS,
) -> dict[M6CohortKind, list[M6RPCMeasurement]]:
    """Round-robin per c-batch measurement (Research R-8 / R-9).

    Each round fires the same number of RPCs per cohort. The i-th
    measurement RPC of every cohort within a cell shares the same
    rpc_index, so the seed mapping is cohort-independent (FR-025).

    M6.0a (FR-001 / FR-002): dispatch is concurrent within a
    (cohort, c-batch) — ``asyncio.gather`` over ``batch_indices``. Cohort
    iteration stays sequential (M5.1-canonical orchestration). The
    round-robin per-c-batch index allocator is unchanged, so
    ``compute_rpc_seed(idx, base_seed)`` produces a cohort-symmetric seed
    sequence bit-identical to the pre-fix harness.
    """
    c = cell.concurrency
    sizes = _c_batch_sizes_for_measurement(c)
    per_cohort: dict[M6CohortKind, list[M6RPCMeasurement]] = {k: [] for k in cohorts}
    rpc_iter = iter(rpc_indices)

    async def _one(
        cohort_ref: M6CohortKind, idx: int, seed: int
    ) -> tuple[int, int, RPCResult, int]:
        result, retry_count = await _run_one_rpc_with_retry(driver, cohort_ref, cell, seed)
        return idx, seed, result, retry_count

    for size in sizes:
        # Pre-allocate the rpc_indices for this c-batch (shared across cohorts).
        batch_indices: list[int] = []
        for _ in range(size):
            try:
                batch_indices.append(next(rpc_iter))
            except StopIteration:
                break
        if not batch_indices:
            break
        batch_seeds = [compute_rpc_seed(idx, base_seed) for idx in batch_indices]
        for cohort in cohorts:
            results = await asyncio.gather(
                *(
                    _one(cohort, idx, seed)
                    for idx, seed in zip(batch_indices, batch_seeds, strict=True)
                )
            )
            for idx, seed, result, retry_count in results:
                per_cohort[cohort].append(
                    M6RPCMeasurement(
                        rpc_index=idx,
                        cell=cell,
                        cohort=cohort,
                        seed=seed,
                        success=result.success,
                        failure_reason=result.failure_reason,
                        wall_clock_ms=result.wall_clock_ms,
                        ttft_ms=result.ttft_ms,
                        engine_cost=result.engine_cost,
                        retry_count=retry_count,
                    )
                )
    return per_cohort


def _aggregate_cohort(
    cell: M6Cell,
    cohort: M6CohortKind,
    measurements: list[M6RPCMeasurement],
) -> M6PerCohortAggregate:
    """Build the per-cohort aggregate from a list of per-RPC measurements."""
    successful = [m for m in measurements if m.success]
    n_attempted = len(measurements)
    n_successes = len(successful)

    if successful:
        wall_clocks = [m.wall_clock_ms for m in successful if m.wall_clock_ms is not None]
        wall_est = estimate(wall_clocks) if wall_clocks else None
        if cell.path == "chat_stream":
            metric_values = [m.ttft_ms for m in successful if m.ttft_ms is not None]
        else:
            metric_values = [m.wall_clock_ms for m in successful if m.wall_clock_ms is not None]
        metric_est = estimate(metric_values) if metric_values else None
        engine_spans = [m.engine_cost for m in successful if m.engine_cost is not None]
        engine_agg = aggregate_engine_cost_per_cell(engine_spans, cell.path)
    else:
        wall_est = None
        metric_est = None
        engine_agg = aggregate_engine_cost_per_cell([], cell.path)

    def _half(est: Any) -> float:
        if est is None:
            return 0.0
        return float((est.ci_high - est.ci_low) / 2.0)

    return M6PerCohortAggregate(
        cohort=cohort,
        n_attempted=n_attempted,
        n_successes=n_successes,
        failure_count=n_attempted - n_successes,
        classifier_metric_mean_ms=metric_est.mean if metric_est is not None else 0.0,
        classifier_metric_ci_half_width_ms=_half(metric_est),
        total_wall_clock_mean_ms=wall_est.mean if wall_est is not None else 0.0,
        total_wall_clock_ci_half_width_ms=_half(wall_est),
        engine_cost_mean=engine_agg,
    )


def _make_incomplete_cell_aggregates(
    cell: M6Cell,
    warmup_successes: dict[M6CohortKind, int],
) -> dict[M6CohortKind, M6PerCohortAggregate]:
    """Build placeholder aggregates for a cell that failed warmup."""
    out: dict[M6CohortKind, M6PerCohortAggregate] = {}
    for kind, succ in warmup_successes.items():
        # n_successes==0 (warmup failed) signals cell_incomplete to the
        # classifier (FR-023; floor is 80).
        out[kind] = M6PerCohortAggregate(
            cohort=kind,
            n_attempted=0,
            n_successes=0,
            failure_count=0,
            classifier_metric_mean_ms=0.0,
            classifier_metric_ci_half_width_ms=0.0,
            total_wall_clock_mean_ms=0.0,
            total_wall_clock_ci_half_width_ms=0.0,
            engine_cost_mean=aggregate_engine_cost_per_cell([], cell.path),
        )
        _ = succ
    return out


async def run_cell(
    driver: RPCDriver,
    cell: M6Cell,
    rpc_iter: MeasurementRpcIndexIterator,
    baseline: dict[str, Any],
    *,
    base_seed: int = DEFAULT_M6_BASE_SEED,
    progress: ProgressReporter | None = None,
) -> tuple[M6CellRecord, dict[M6CohortKind, list[M6RPCMeasurement]]]:
    """Run one cell (warmup + measurement) and produce the classified record.

    Returns ``(record, per_cohort_measurements)`` so callers can persist
    the events sidecar (Phase 3 emit) separately from the aggregate
    classification.
    """
    warmup_successes = await _run_warmup(driver, cell)
    if any(s < M6_WARMUP_N for s in warmup_successes.values()):
        # Warmup couldn't accumulate the floor; skip measurement and mark
        # the cell as cell_incomplete (FR-023).
        empty_aggs = _make_incomplete_cell_aggregates(cell, warmup_successes)
        record = classify_cell(cell, empty_aggs, baseline)
        if progress is not None:
            for kind in M6_COHORTS:
                progress.emit_cell_cohort(cell, kind, 0, 0.0)
        return record, {k: [] for k in M6_COHORTS}

    indices = rpc_iter.allocate(M6_MEASUREMENT_N)
    start = time.monotonic()
    per_cohort_measurements = await _run_measurement(driver, cell, indices, base_seed=base_seed)
    elapsed_ms = (time.monotonic() - start) * 1000.0

    per_cohort_aggregates: dict[M6CohortKind, M6PerCohortAggregate] = {
        kind: _aggregate_cohort(cell, kind, per_cohort_measurements[kind]) for kind in M6_COHORTS
    }
    record = classify_cell(cell, per_cohort_aggregates, baseline)

    if progress is not None:
        # Estimate per-cohort elapsed as roughly equal share (the sweep
        # measures all cohorts within the same cell-elapsed window).
        per_cohort_elapsed = elapsed_ms / len(M6_COHORTS)
        for kind in M6_COHORTS:
            successes = per_cohort_aggregates[kind].n_successes
            progress.emit_cell_cohort(cell, kind, successes, per_cohort_elapsed)

    return record, per_cohort_measurements


async def run_sweep(
    driver: RPCDriver,
    baseline: dict[str, Any],
    *,
    base_seed: int = DEFAULT_M6_BASE_SEED,
    progress: ProgressReporter | None = None,
) -> tuple[list[M6CellRecord], dict[M6Cell, dict[M6CohortKind, list[M6RPCMeasurement]]]]:
    """Drive the full 6-cell sweep.

    Returns the list of classified cell records (in iteration order) plus
    a per-cell map of per-cohort measurement lists for events-sidecar
    persistence.
    """
    rpc_iter = MeasurementRpcIndexIterator()
    cells = make_cells()
    records: list[M6CellRecord] = []
    measurements: dict[M6Cell, dict[M6CohortKind, list[M6RPCMeasurement]]] = {}
    for cell in cells:
        record, per_cohort_meas = await run_cell(
            driver, cell, rpc_iter, baseline, base_seed=base_seed, progress=progress
        )
        records.append(record)
        measurements[cell] = per_cohort_meas
    return records, measurements


def summarize_verdict_tally(cells: list[M6CellRecord]) -> str:
    """One-line summary for the completion banner (e.g.
    '4 verdict_survives / 1 verdict_changed / 1 cell_incomplete').

    Ordering follows FR-014's enumeration of verdict literals plus
    FR-023's ``cell_incomplete`` (the 5th terminal classification, placed
    last so degenerate cells stand out): survives → changed →
    buried_by_engine → no_winner → cell_incomplete. Matches the example
    output in ``quickstart.md`` Step 2.
    """
    counts: dict[str, int] = {}
    for cell in cells:
        counts[cell.classification] = counts.get(cell.classification, 0) + 1
    order = (
        "verdict_survives",
        "verdict_changed",
        "verdict_buried_by_engine",
        "no_winner_at_n100",
        "cell_incomplete",
    )
    return " / ".join(f"{counts[k]} {k}" for k in order if k in counts)


__all__ = [
    "M6_CELL_COMPLETE_FLOOR",
    "ProgressReporter",
    "RPCDriver",
    "RPCResult",
    "_aggregate_cohort",
    "_c_batch_sizes_for_measurement",
    "_c_batch_sizes_for_warmup",
    "run_cell",
    "run_sweep",
    "summarize_verdict_tally",
]
