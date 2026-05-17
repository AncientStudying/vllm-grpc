"""M6.1.1 Modal sweep wrappers — wires the Phase 1 / Phase 2(a) orchestrators
to the live M6.1 Modal deployment + RPC driver infrastructure.

Reuses M6.1's stack verbatim:
* :func:`modal_endpoint.provide_m6_endpoint` to deploy / reuse the Modal app.
* :func:`m6_1_rpc_driver.provide_m6_1_rpc_driver` to open the gRPC + REST
  clients and yield a per-RPC dispatcher.
* :func:`m6_1_seq_len.pin_seq_len_at_sweep_start` to fix ``seq_len`` at the
  sweep start.

Adds M6.1.1-specific aggregation on top of M6.1's per-RPC ``RPCResult``
(which now carries ``m6_1_1_timing_payload`` — see ``m6_sweep.RPCResult``).

The Phase 1 (``--m6_1_1-diagnose``) variant runs at n=50 measurement RPCs
per cohort per cell + n=10 warmup, classifies each chat_stream cell via
``classify_cell``, and returns a :class:`Phase1RunRecord`.

The Phase 2(a) (``--m6_1_1``) variant runs at n=100 + n=10 warmup,
computes embed regression vs M6.1's published baseline, builds 9-cell
chat_stream + embed baseline sentinels, and returns the
:class:`Phase2aSweepResult` tuple the orchestrator's hook expects.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from vllm_grpc_bench.ci import estimate
from vllm_grpc_bench.m6_1_1_classifier import classify_cell
from vllm_grpc_bench.m6_1_1_embed_regression import compute_embed_regression
from vllm_grpc_bench.m6_1_1_types import (
    CHAT_STREAM_DRIFT_CLEARED_TOLERANCE,
    BaselineCellEntry,
    EmbedRegressionCheckResult,
    M6_1_1Cell,
    M6_1_1Cohort,
    MultiPointTimings,
    PerSegmentAggregate,
    PerturbationAudit,
    Phase1Classification,
    Phase1RunRecord,
    Phase2Choice,
)
from vllm_grpc_bench.m6_1_seq_len import pin_seq_len_at_sweep_start
from vllm_grpc_bench.m6_1_types import (
    M6_1_CELLS,
    M6_1_COHORTS,
    M6_1Cell,
)
from vllm_grpc_bench.m6_sweep import RPCDriver, RPCResult

# --- Progress reporter (stderr lines as the sweep advances) ----------------


def _stderr_ts() -> str:
    """ISO-8601 UTC bracket prefix for stderr progress lines, so log readers
    can correlate emissions with wall-clock time during long sweeps
    (spike/m6-1-roadmap-additions item #3). Matches the run_id timestamp
    format used elsewhere in the project."""
    return datetime.now(UTC).strftime("[%Y-%m-%dT%H:%M:%SZ]")


class M6_1_1ProgressReporter:
    """Streams per-cell × per-cohort progress to stderr so the operator
    has visibility during the ~30–75 min sweep wall-clock.

    Total pair count is fixed at 18 (6 cells × 3 cohorts). Each
    ``emit_cell_cohort`` call updates the rolling ETA based on the
    measured per-pair wall-clock.

    Each emission carries an ISO-8601 UTC timestamp prefix (item #3 from
    spike/m6-1-roadmap-additions).
    """

    def __init__(self, *, phase: str, n: int, eta_minutes_total: int) -> None:
        self.phase = phase
        self.n = n
        self.eta_minutes_total = eta_minutes_total
        self.total_pairs = 18
        self.completed_pairs = 0
        self.start_time: float = 0.0

    def emit_startup(self, *, model: str, region: str, seq_len: int) -> None:
        self.start_time = time.monotonic()
        print(
            f"{_stderr_ts()} M6.1.1 {self.phase} sweep: 6 cells × 3 cohorts × n={self.n}, "
            f"runtime ETA ≤{self.eta_minutes_total} min, model={model}, "
            f"region={region}, seq_len={seq_len}",
            file=sys.stderr,
            flush=True,
        )

    def emit_cell_cohort(
        self,
        cell: M6_1_1Cell,
        cohort: M6_1_1Cohort,
        successes: int,
        elapsed_s: float,
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
            f"c={cell.concurrency} / {cohort} — {successes}/{self.n} succ — "
            f"{elapsed_s * 1000:.0f} ms — ETA {eta_min}m",
            file=sys.stderr,
            flush=True,
        )

    def emit_cold_start(self, cold_start_s: float) -> None:
        print(
            f"{_stderr_ts()} M6.1.1 cold-start (Modal deploy + model load): {cold_start_s:.1f} s",
            file=sys.stderr,
            flush=True,
        )

    def emit_completion(self, report_path: str) -> None:
        elapsed_min = (time.monotonic() - self.start_time) / 60.0
        print(
            f"{_stderr_ts()} M6.1.1 {self.phase} sweep complete in {elapsed_min:.1f} min; "
            f"report at {report_path}",
            file=sys.stderr,
            flush=True,
        )


# --- Aggregation helpers ----------------------------------------------------


def aggregate_multi_point_timings(
    per_cohort_results: dict[M6_1_1Cohort, list[RPCResult]],
    cell: M6_1_1Cell,
) -> list[MultiPointTimings]:
    """Convert per-cohort ``RPCResult`` lists to ``MultiPointTimings`` aggregates.

    Each cohort's successful samples are reduced to:
    * ``engine_ttft_ms_mean`` + 95% CI half-width (chat_stream cells) or
      ``engine_forward_ms_mean`` (embed cells)
    * per-segment means + CIs from the four-checkpoint timing data
    * ``perturbation_total_us_mean`` from the self-measured audit

    Cohorts with zero successful M6.1.1-instrumented samples produce a
    zero-filled aggregate (``n_samples == 0``); callers can detect this
    via the per-segment ``n_samples`` field.
    """
    out: list[MultiPointTimings] = []
    for cohort in M6_1_COHORTS:
        results = per_cohort_results.get(cohort, [])
        timings: list[dict[str, int]] = [
            r.m6_1_1_timing_payload
            for r in results
            if r.success and r.m6_1_1_timing_payload is not None
        ]
        engine_ttft_samples = [
            r.engine_cost.engine_ttft_ms
            for r in results
            if r.success and r.engine_cost is not None and r.engine_cost.engine_ttft_ms is not None
        ]
        engine_forward_samples = [
            r.engine_cost.engine_forward_ms
            for r in results
            if r.success
            and r.engine_cost is not None
            and r.engine_cost.engine_forward_ms is not None
        ]
        # Use engine_ttft for chat_stream, engine_forward for embed.
        ms_samples = engine_ttft_samples if cell.path == "chat_stream" else engine_forward_samples

        seg_ab = [(t["pre_engine_ns"] - t["handler_entry_ns"]) * 1e-6 for t in timings]
        seg_bc = [(t["first_chunk_ns"] - t["pre_engine_ns"]) * 1e-6 for t in timings]
        seg_cd = [(t["terminal_emit_ns"] - t["first_chunk_ns"]) * 1e-6 for t in timings]
        perturbation_us = [t["perturbation_audit_ns"] / 1000.0 for t in timings]

        # M6.1.2 — engine-internal segments derived from vLLM RequestStateStats
        # monotonic timestamps. Sample only timings where all four engine-core
        # ts fields are populated (has_engine_stats); falls back to None when
        # the upstream server doesn't emit the new keys.
        engine_stats_timings = [
            t
            for t in timings
            if t.get("engine_queued_ns", 0) > 0
            and t.get("engine_scheduled_ns", 0) > 0
            and t.get("engine_first_token_ns", 0) > 0
            and t.get("engine_last_token_ns", 0) > 0
        ]
        if engine_stats_timings:
            seg_queue = [
                (t["engine_scheduled_ns"] - t["engine_queued_ns"]) * 1e-6
                for t in engine_stats_timings
            ]
            seg_prefill = [
                (t["engine_first_token_ns"] - t["engine_scheduled_ns"]) * 1e-6
                for t in engine_stats_timings
            ]
            seg_queue_mean: float | None = _mean_or_zero(seg_queue)
            seg_queue_ci: float | None = _ci_half_width(seg_queue)
            seg_prefill_mean: float | None = _mean_or_zero(seg_prefill)
            seg_prefill_ci: float | None = _ci_half_width(seg_prefill)
        else:
            seg_queue_mean = None
            seg_queue_ci = None
            seg_prefill_mean = None
            seg_prefill_ci = None

        out.append(
            MultiPointTimings(
                cohort=cohort,
                cell=cell,
                engine_ttft_ms_mean=_mean_or_zero(ms_samples),
                engine_ttft_ms_ci_half_width=_ci_half_width(ms_samples),
                per_segment=PerSegmentAggregate(
                    seg_ab_ms_mean=_mean_or_zero(seg_ab),
                    seg_ab_ms_ci_half_width=_ci_half_width(seg_ab),
                    seg_bc_ms_mean=_mean_or_zero(seg_bc),
                    seg_bc_ms_ci_half_width=_ci_half_width(seg_bc),
                    seg_cd_ms_mean=_mean_or_zero(seg_cd),
                    seg_cd_ms_ci_half_width=_ci_half_width(seg_cd),
                    n_samples=len(timings),
                    seg_queue_ms_mean=seg_queue_mean,
                    seg_queue_ms_ci_half_width=seg_queue_ci,
                    seg_prefill_ms_mean=seg_prefill_mean,
                    seg_prefill_ms_ci_half_width=seg_prefill_ci,
                ),
                perturbation_total_us_mean=_mean_or_zero(perturbation_us),
            )
        )
    return out


def _mean_or_zero(samples: list[float]) -> float:
    return sum(samples) / len(samples) if samples else 0.0


def _ci_half_width(samples: list[float]) -> float:
    # The shared M3 estimate() helper requires n >= 10 (project floor per
    # spec SC-003). For smaller sample sizes (synthetic tests, edge cases)
    # return 0.0 rather than raise — the M6.1.1 measurement sweep uses
    # n >= 50 in practice so this fallback never fires in production.
    if len(samples) < 10:
        return 0.0
    est = estimate(samples)
    return (est.ci_high - est.ci_low) / 2.0


def _cell_key(cell: M6_1_1Cell) -> str:
    return f"{cell.path}_c{cell.concurrency}_h{cell.hidden_size}"


def _make_cells() -> list[M6_1_1Cell]:
    """All 6 M6.1.1 cells (3 embed + 3 chat_stream)."""
    return [M6_1_1Cell(path=p, hidden_size=h, concurrency=c) for (p, h, c) in M6_1_CELLS]


def _make_chat_stream_cells() -> list[M6_1_1Cell]:
    return [c for c in _make_cells() if c.path == "chat_stream"]


def _make_embed_cells() -> list[M6_1_1Cell]:
    return [c for c in _make_cells() if c.path == "embed"]


# --- Cell-level measurement loop -------------------------------------------


async def _measure_cell(
    driver: RPCDriver,
    cell: M6_1_1Cell,
    *,
    n_measurement: int,
    n_warmup: int,
    base_seed: int,
    reporter: M6_1_1ProgressReporter | None = None,
) -> dict[M6_1_1Cohort, list[RPCResult]]:
    """Run ``n_warmup`` + ``n_measurement`` RPCs per cohort for one cell.

    Returns per-cohort ``RPCResult`` lists for the measurement phase only —
    warmup results are discarded (their purpose is engine warm-state
    stabilisation, not measurement). Reuses M6.1's RPCDriver signature
    (driver dispatches by ``(cohort, M6_1Cell, seed)``).

    When a ``reporter`` is supplied, ``emit_cell_cohort`` fires after each
    (cell, cohort) pair completes so the operator sees per-pair progress.
    """
    # Cast M6.1.1 cell ↔ M6.1 cell (they're aliases — same shape).
    m6_1_cell = M6_1Cell(path=cell.path, hidden_size=cell.hidden_size, concurrency=cell.concurrency)

    # M6.0a (FR-001 / FR-005a): warmup dispatches concurrently per cohort
    # via asyncio.gather. seed=0 per the smoke/warmup convention
    # (feedback_smoke_warmup_seed_zero memory).
    for cohort in M6_1_COHORTS:
        if n_warmup > 0:
            await asyncio.gather(*(driver(cohort, m6_1_cell, 0) for _ in range(n_warmup)))

    # M6.0a (FR-001 / FR-002): measurement dispatches under an
    # asyncio.Semaphore(c)-bounded gather so the engine sees a steady
    # c-in-flight stream. Cohort iteration stays sequential per FR-005.
    # ``seed = base_seed + i`` is a pure function of ``i`` so the SET of
    # ``(cohort, seed)`` records is bit-identical to the pre-fix harness.
    per_cohort: dict[M6_1_1Cohort, list[RPCResult]] = {k: [] for k in M6_1_COHORTS}
    for cohort in M6_1_COHORTS:
        cohort_start = time.monotonic()
        sem = asyncio.Semaphore(cell.concurrency)

        async def _one(
            i: int,
            cohort_ref: M6_1_1Cohort = cohort,
            sem_ref: asyncio.Semaphore = sem,
        ) -> RPCResult:
            async with sem_ref:
                return await driver(cohort_ref, m6_1_cell, base_seed + i)

        results = await asyncio.gather(*(_one(i) for i in range(n_measurement)))
        per_cohort[cohort].extend(results)
        if reporter is not None:
            successes = sum(1 for r in results if r.success)
            reporter.emit_cell_cohort(cell, cohort, successes, time.monotonic() - cohort_start)
    return per_cohort


# --- Phase 1 sweep wrapper -------------------------------------------------


async def run_m6_1_1_phase_1_sweep(
    args: argparse.Namespace,
    baseline: dict[str, Any],
    *,
    driver_factory: Callable[..., Awaitable[Any]] | None = None,
) -> Phase1RunRecord:
    """Drive the 6-cell × 3-cohort × n=50 Phase 1 mini-sweep on Modal.

    ``driver_factory`` is an optional override used by tests to inject a
    mocked driver context manager (so the live Modal path doesn't run in
    unit tests). The default uses :func:`provide_m6_endpoint` +
    :func:`provide_m6_1_rpc_driver` per M6.1's lifecycle.
    """
    del baseline  # currently unused — reserved for future engine-version-aware logic
    run_id = _make_run_id()
    started_at = datetime.now(UTC)
    t0 = time.monotonic()

    seq_len = pin_seq_len_at_sweep_start(str(getattr(args, "m6_1_1_model", "Qwen/Qwen3-8B")))
    base_seed = int(getattr(args, "m6_1_1_base_seed", 42))
    reporter = M6_1_1ProgressReporter(phase="Phase 1 diagnose", n=50, eta_minutes_total=45)
    reporter.emit_startup(
        model=str(getattr(args, "m6_1_1_model", "Qwen/Qwen3-8B")),
        region=str(getattr(args, "m6_1_1_modal_region", "eu-west-1")),
        seq_len=seq_len,
    )

    all_timings: list[MultiPointTimings] = []
    cold_start_t0 = time.monotonic()
    async with _open_endpoint_and_driver(args, seq_len, base_seed, driver_factory) as driver:
        reporter.emit_cold_start(time.monotonic() - cold_start_t0)
        for cell in _make_cells():
            per_cohort = await _measure_cell(
                driver,
                cell,
                n_measurement=50,
                n_warmup=10,
                base_seed=base_seed,
                reporter=reporter,
            )
            all_timings.extend(aggregate_multi_point_timings(per_cohort, cell))

    # Classify the 3 chat_stream cells via the FR-010 magnitude-equivalence
    # formula. Embed cells are audit-only controls (FR-011) — no
    # classification recorded.
    classifications: dict[str, Phase1Classification] = {}
    for cell in _make_chat_stream_cells():
        per_cohort_dict: dict[M6_1_1Cohort, MultiPointTimings] = {
            t.cohort: t for t in all_timings if t.cell == cell
        }
        if len(per_cohort_dict) == len(M6_1_COHORTS):
            classifications[_cell_key(cell)] = classify_cell(cell, per_cohort_dict)

    record = Phase1RunRecord(
        run_id=run_id,
        run_started_at=started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        run_completed_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        wall_clock_s=time.monotonic() - t0,
        multi_point_timings=all_timings,
        phase_1_classifications=classifications,
        perturbation_audit=PerturbationAudit(per_cohort_per_cell={}, exceeded=False),
        n_per_cohort=50,
    )
    reporter.emit_completion(
        str(
            getattr(
                args, "m6_1_1_report_out", "docs/benchmarks/m6_1_1-engine-cost-instrumentation.md"
            )
        )
    )
    return record


# --- Phase 2(a) sweep wrapper ----------------------------------------------


async def run_m6_1_1_phase_2a_sweep(
    args: argparse.Namespace,
    baseline: dict[str, Any],
    *,
    driver_factory: Callable[..., Awaitable[Any]] | None = None,
    phase_2_choice: Phase2Choice | None = None,
) -> tuple[
    list[BaselineCellEntry],
    list[BaselineCellEntry],
    EmbedRegressionCheckResult | None,
    dict[str, bool],
    dict[str, bool],
    bool,
    str,
]:
    """Drive the 6-cell × 3-cohort × n=100 Phase 2(a) verification sweep.

    Returns the tuple shape :class:`Phase2aSweepHook` expects:
    ``(chat_stream_cells, embed_cells, embed_regression, drift_cleared,
    drift_warning, ctrl_warning, ctrl_note)``.
    """
    seq_len = pin_seq_len_at_sweep_start(str(getattr(args, "m6_1_1_model", "Qwen/Qwen3-8B")))
    base_seed = int(getattr(args, "m6_1_1_base_seed", 42))
    reporter = M6_1_1ProgressReporter(phase="Phase 2(a) verification", n=100, eta_minutes_total=75)
    reporter.emit_startup(
        model=str(getattr(args, "m6_1_1_model", "Qwen/Qwen3-8B")),
        region=str(getattr(args, "m6_1_1_modal_region", "eu-west-1")),
        seq_len=seq_len,
    )

    chat_stream_entries: list[BaselineCellEntry] = []
    embed_entries: list[BaselineCellEntry] = []
    # Map (cell, cohort) -> measured engine_forward_ms_mean for the embed
    # regression check.
    embed_per_cohort_means: dict[tuple[M6_1_1Cell, M6_1_1Cohort], float] = {}
    # Map cell -> per-cohort engine_ttft_ms means for the drift-cleared check.
    chat_stream_per_cohort_means: dict[M6_1_1Cell, dict[M6_1_1Cohort, float]] = {}

    cold_start_t0 = time.monotonic()
    async with _open_endpoint_and_driver(args, seq_len, base_seed, driver_factory) as driver:
        reporter.emit_cold_start(time.monotonic() - cold_start_t0)
        for cell in _make_cells():
            per_cohort = await _measure_cell(
                driver,
                cell,
                n_measurement=100,
                n_warmup=10,
                base_seed=base_seed,
                reporter=reporter,
            )
            timings = aggregate_multi_point_timings(per_cohort, cell)
            for t in timings:
                entry = _baseline_entry_from_timing(t, cell)
                if cell.path == "chat_stream":
                    chat_stream_entries.append(entry)
                    chat_stream_per_cohort_means.setdefault(cell, {})[t.cohort] = (
                        t.engine_ttft_ms_mean
                    )
                else:
                    embed_entries.append(entry)
                    embed_per_cohort_means[(cell, t.cohort)] = t.engine_ttft_ms_mean

    # FR-015b embed regression check vs M6.1's published baseline.
    embed_regression = compute_embed_regression(
        embed_per_cohort_means, baseline, phase_2_choice=phase_2_choice
    )

    # Mark embed entries with the per-(cell × cohort) regression warning flag.
    embed_entries = _annotate_embed_entries_with_regression(embed_entries, embed_regression)

    # FR-015 drift-cleared per chat_stream cell: each cohort within 5% of
    # the unweighted cohort-average.
    drift_cleared = _compute_drift_cleared(chat_stream_per_cohort_means)
    drift_warning = {k: not v for k, v in drift_cleared.items()}

    # chat_stream_control_drift_warning: expected to fire under symmetrisation
    # because we just moved the engine_ttft bracket. Per round-1 Q2 this is
    # informational, not a failure.
    ctrl_warning = True
    ctrl_note = (
        "expected — reflects bracketing change in Phase 2(a) symmetrisation; "
        "not infrastructure drift (round-1 Q2)"
    )
    reporter.emit_completion(
        str(
            getattr(
                args, "m6_1_1_report_out", "docs/benchmarks/m6_1_1-engine-cost-instrumentation.md"
            )
        )
    )
    return (
        chat_stream_entries,
        embed_entries,
        embed_regression,
        drift_cleared,
        drift_warning,
        ctrl_warning,
        ctrl_note,
    )


def _baseline_entry_from_timing(mpt: MultiPointTimings, cell: M6_1_1Cell) -> BaselineCellEntry:
    """Convert a ``MultiPointTimings`` to a ``BaselineCellEntry`` for the
    Phase 2(a) sentinel-object payload."""
    if cell.path == "chat_stream":
        return BaselineCellEntry(
            cell=cell,
            cohort=mpt.cohort,
            engine_ttft_ms_mean=mpt.engine_ttft_ms_mean,
            engine_ttft_ms_ci_half_width=mpt.engine_ttft_ms_ci_half_width,
            # TPOT not aggregated here; reuse M6.1's TPOT writer when needed.
            engine_tpot_ms_mean=None,
            engine_tpot_ms_ci_half_width=None,
            engine_forward_ms_mean=None,
            engine_forward_ms_ci_half_width=None,
            n_successes=mpt.per_segment.n_samples,
            regression_warning=None,
        )
    return BaselineCellEntry(
        cell=cell,
        cohort=mpt.cohort,
        engine_ttft_ms_mean=None,
        engine_ttft_ms_ci_half_width=None,
        engine_tpot_ms_mean=None,
        engine_tpot_ms_ci_half_width=None,
        engine_forward_ms_mean=mpt.engine_ttft_ms_mean,  # repurposed for embed
        engine_forward_ms_ci_half_width=mpt.engine_ttft_ms_ci_half_width,
        n_successes=mpt.per_segment.n_samples,
        regression_warning=False,  # populated by _annotate_embed_entries_with_regression
    )


def _annotate_embed_entries_with_regression(
    embed_entries: list[BaselineCellEntry],
    embed_regression: EmbedRegressionCheckResult,
) -> list[BaselineCellEntry]:
    """Set ``regression_warning`` on each embed entry per FR-015c."""
    warning_keys = {
        (e.cell, e.cohort) for e in embed_regression.per_entry if e.embed_regression_warning
    }
    out: list[BaselineCellEntry] = []
    for entry in embed_entries:
        warning = (entry.cell, entry.cohort) in warning_keys
        if warning == entry.regression_warning:
            out.append(entry)
            continue
        out.append(
            BaselineCellEntry(
                cell=entry.cell,
                cohort=entry.cohort,
                engine_ttft_ms_mean=entry.engine_ttft_ms_mean,
                engine_ttft_ms_ci_half_width=entry.engine_ttft_ms_ci_half_width,
                engine_tpot_ms_mean=entry.engine_tpot_ms_mean,
                engine_tpot_ms_ci_half_width=entry.engine_tpot_ms_ci_half_width,
                engine_forward_ms_mean=entry.engine_forward_ms_mean,
                engine_forward_ms_ci_half_width=entry.engine_forward_ms_ci_half_width,
                n_successes=entry.n_successes,
                regression_warning=warning,
            )
        )
    return out


def _compute_drift_cleared(
    chat_stream_per_cohort_means: dict[M6_1_1Cell, dict[M6_1_1Cohort, float]],
) -> dict[str, bool]:
    """Per chat_stream cell: each cohort within 5% of unweighted cohort-average → cleared."""
    out: dict[str, bool] = {}
    for cell, per_cohort in chat_stream_per_cohort_means.items():
        means = list(per_cohort.values())
        if not means:
            out[_cell_key(cell)] = False
            continue
        avg = sum(means) / len(means)
        if avg == 0.0:
            out[_cell_key(cell)] = False
            continue
        max_spread = max(abs(m - avg) / avg for m in means)
        out[_cell_key(cell)] = max_spread <= CHAT_STREAM_DRIFT_CLEARED_TOLERANCE
    return out


# --- Modal endpoint + driver context manager -------------------------------


def _open_endpoint_and_driver(
    args: argparse.Namespace,
    seq_len: int,
    base_seed: int,
    driver_factory: Callable[..., Awaitable[Any]] | None,
) -> Any:
    """Open the Modal endpoint + M6.1 RPC driver in a single async-with.

    Returns an async context manager that yields the ``RPCDriver`` callable.
    Tests pass ``driver_factory`` to short-circuit the live Modal path —
    ``driver_factory(args, seq_len, base_seed)`` should return an async
    context manager yielding a synthetic driver.
    """
    if driver_factory is not None:
        return driver_factory(args, seq_len, base_seed)
    return _live_endpoint_and_driver(args, seq_len, base_seed)


from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def _live_endpoint_and_driver(
    args: argparse.Namespace,
    seq_len: int,
    base_seed: int,
) -> Any:
    """Default async context manager — opens M6.1 Modal endpoint + driver."""
    from vllm_grpc_bench.m6_1_rpc_driver import provide_m6_1_rpc_driver
    from vllm_grpc_bench.modal_endpoint import provide_m6_endpoint

    async with (
        provide_m6_endpoint(
            region=str(getattr(args, "m6_1_1_modal_region", "eu-west-1")),
            token_env=str(getattr(args, "m6_1_1_modal_token_env", "MODAL_BENCH_TOKEN")),
            model_id=str(getattr(args, "m6_1_1_model", "Qwen/Qwen3-8B")),
        ) as endpoints,
        provide_m6_1_rpc_driver(
            endpoints,
            seq_len=seq_len,
            base_seed=base_seed,
        ) as (driver, _rtt),
    ):
        yield driver


# --- Run ID --------------------------------------------------------------


def _make_run_id() -> str:
    try:
        git_sha = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )[:7]
    except (subprocess.CalledProcessError, FileNotFoundError):
        git_sha = uuid.uuid4().hex[:7]
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{ts}-{git_sha}"


def _hostname() -> str:
    return socket.gethostname()


__all__ = [
    "aggregate_multi_point_timings",
    "run_m6_1_1_phase_1_sweep",
    "run_m6_1_1_phase_2a_sweep",
]
