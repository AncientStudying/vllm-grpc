"""M6.1 sweep orchestrator — composes M6's per-cell helpers + M6.1 classifier.

Reuses the round-robin per c-batch sequencer + warmup + per-cohort aggregator
from :mod:`vllm_grpc_bench.m6_sweep` (FR-007 / R-9 — engine config and sequencing
unchanged from M6) and adds M6.1-specific composition:

* pre-RPC torch-pin gate (FR-006) — actually invoked from ``__main__._run_m6_1``
* pre-RPC M6 baseline loader (FR-008/FR-009) — invoked from ``__main__._run_m6_1``
* seq_len pinning at sweep start (FR-028)
* per-cell classification against M6 baseline (FR-010 / R-8)
* post-sweep chat_stream control-drift check (FR-029)
* engine-path differential computation (FR-020 / SC-007)
* hand-off to :mod:`vllm_grpc_bench.m6_1_reporter`
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _datetime
import math
import socket
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m6_1_drift_check import check_chat_stream_control_drift
from vllm_grpc_bench.m6_1_seed import compute_rpc_seed
from vllm_grpc_bench.m6_1_supersede import (
    classify_cell,
    cohort_pair_for,
    compute_engine_path_differential,
)
from vllm_grpc_bench.m6_1_torch_pin import _EXPECTED_TORCH_VERSION
from vllm_grpc_bench.m6_1_types import (
    M6_1_COHORTS,
    M6_1_MEASUREMENT_N,
    M6_1_PROMPT_EMBED_HIDDEN_SIZE,
    M6_1_WARMUP_N,
    EnginePathDifferentialRow,
    M6_1Cell,
    M6_1CellRecord,
    M6_1CohortKind,
    M6_1PerCohortAggregate,
    M6_1RPCMeasurement,
    M6_1Run,
    M6_1RunMeta,
    SupersedesM6Row,
    cell_key,
    make_cells,
)
from vllm_grpc_bench.m6_sweep import (
    RPCDriver,
    RPCResult,
    _aggregate_cohort,
    _c_batch_sizes_for_measurement,
    _c_batch_sizes_for_warmup,
    _run_one_rpc_with_retry,
)

_DEFAULT_SEQ_LEN_FALLBACK: int = 8


# --- Progress reporter -------------------------------------------------------


class ProgressReporter:
    """Mirrors :class:`m6_sweep.ProgressReporter` for M6.1 stderr lines."""

    def __init__(self) -> None:
        self.total_pairs: int = 18
        self.completed_pairs: int = 0
        self.start_time: float = 0.0

    def emit_startup(
        self,
        *,
        model: str,
        region: str,
        torch_version: str,
        engine_version: str,
    ) -> None:
        self.start_time = time.monotonic()
        print(
            f"M6.1 sweep: 6 cells × 3 cohorts × n={M6_1_MEASUREMENT_N}, "
            f"runtime ETA ≤90 min, model={model}, region={region}, "
            f"torch={torch_version}, vllm={engine_version}",
            file=sys.stderr,
        )

    def emit_cell_cohort(
        self,
        cell: M6_1Cell,
        cohort: M6_1CohortKind,
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
            f"[{self.completed_pairs}/{self.total_pairs}] {cell.path} × "
            f"c={cell.concurrency} / {cohort} — {successes}/{M6_1_MEASUREMENT_N} succ — "
            f"{elapsed_ms:.0f} ms — ETA {eta_min}m",
            file=sys.stderr,
        )

    def emit_completion(self, report_path: str, tally: str) -> None:
        print(
            f"M6.1 sweep complete: verdict table at {report_path} ({tally})",
            file=sys.stderr,
        )


# --- Per-cell sweep loop (parallel to m6_sweep.run_cell) --------------------


class _MeasurementRpcIndexIterator:
    """Mirror of :class:`m6_seed.MeasurementRpcIndexIterator` for M6.1.

    Warmup RPCs do not advance the counter (FR-019 / FR-015).
    """

    def __init__(self) -> None:
        self._next: int = 0

    def allocate(self, count: int) -> list[int]:
        out = list(range(self._next, self._next + count))
        self._next += count
        return out


async def _run_warmup_m6_1(
    driver: RPCDriver,
    cell: M6_1Cell,
) -> dict[M6_1CohortKind, int]:
    """Warmup phase per FR-015 — silently retry until 10 successes per cohort.

    M6.0a (FR-001 / FR-005a): mirrors :func:`m6_sweep._run_warmup` — within
    a (cohort, c-batch) the ``size`` warmup attempts run concurrently via
    ``asyncio.gather``; each attempt keeps its inner retry-until-success
    loop intact. Cohort iteration stays sequential per FR-005.
    """
    c = cell.concurrency
    successes: dict[M6_1CohortKind, int] = {k: 0 for k in M6_1_COHORTS}
    sizes = _c_batch_sizes_for_warmup(c)

    async def _warmup_one(cohort_ref: M6_1CohortKind) -> int:
        for _attempt in range(4):
            result = await driver(cohort_ref, cell, 0)
            if result.success:
                return 1
        return 0

    for size in sizes:
        for cohort in M6_1_COHORTS:
            attempt_results = await asyncio.gather(*(_warmup_one(cohort) for _ in range(size)))
            successes[cohort] += sum(attempt_results)
    return successes


async def _run_measurement_m6_1(
    driver: RPCDriver,
    cell: M6_1Cell,
    rpc_indices: list[int],
    base_seed: int,
) -> dict[M6_1CohortKind, list[M6_1RPCMeasurement]]:
    """M6.0a (FR-001 / FR-002): per-(cohort × c-batch) ``asyncio.gather``
    dispatch — cohort iteration sequential; within a cohort, ``c``
    concurrent RPCs. Mirrors :func:`m6_sweep._run_measurement`.
    """
    c = cell.concurrency
    sizes = _c_batch_sizes_for_measurement(c)
    per_cohort: dict[M6_1CohortKind, list[M6_1RPCMeasurement]] = {k: [] for k in M6_1_COHORTS}
    rpc_iter = iter(rpc_indices)

    async def _one(
        cohort_ref: M6_1CohortKind, idx: int, seed: int
    ) -> tuple[int, int, RPCResult, int]:
        result, retry_count = await _run_one_rpc_with_retry(driver, cohort_ref, cell, seed)
        return idx, seed, result, retry_count

    for size in sizes:
        batch_indices: list[int] = []
        for _ in range(size):
            try:
                batch_indices.append(next(rpc_iter))
            except StopIteration:
                break
        if not batch_indices:
            break
        batch_seeds = [compute_rpc_seed(idx, base_seed) for idx in batch_indices]
        for cohort in M6_1_COHORTS:
            results = await asyncio.gather(
                *(
                    _one(cohort, idx, seed)
                    for idx, seed in zip(batch_indices, batch_seeds, strict=True)
                )
            )
            for idx, seed, result, retry_count in results:
                per_cohort[cohort].append(
                    M6_1RPCMeasurement(
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


def _make_incomplete_cell_aggregates(
    cell: M6_1Cell,
) -> dict[M6_1CohortKind, M6_1PerCohortAggregate]:
    from vllm_grpc_bench.m6_engine_cost import aggregate_engine_cost_per_cell

    out: dict[M6_1CohortKind, M6_1PerCohortAggregate] = {}
    for kind in M6_1_COHORTS:
        out[kind] = M6_1PerCohortAggregate(
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
    return out


def _build_cell_record(
    cell: M6_1Cell,
    per_cohort_aggregates: dict[M6_1CohortKind, M6_1PerCohortAggregate],
    m6_winner_deltas: dict[str, float | None],
    m6_winner_directions: dict[str, str | None],
) -> M6_1CellRecord:
    """Apply :func:`classify_cell` and return the full M6.1 cell record."""
    key = cell_key(cell)
    delta = m6_winner_deltas.get(key)
    direction = m6_winner_directions.get(key)
    classification, reason, engine_cost_mean, drift_warning, drift_surface = classify_cell(
        None,
        cell,
        per_cohort_aggregates,
        m6_winner_delta_ms=delta,
        m6_winner_direction=direction,
    )
    return M6_1CellRecord(
        cell=cell,
        per_cohort=per_cohort_aggregates,
        classification=classification,
        classification_reason=reason,
        classifier_metric="wall_clock_ms" if cell.path == "embed" else "ttft_ms",
        cohort_pair=cohort_pair_for(cell),
        m6_winner_delta_ms=delta,
        m6_winner_direction=direction,  # type: ignore[arg-type]
        engine_cost_mean_ms=engine_cost_mean,
        engine_cost_drift_warning=drift_warning,
        per_cohort_engine_cost_mean_ms=drift_surface,
        chat_stream_control_drift_warning=False,  # filled in post-sweep
    )


async def run_one_cell(
    driver: RPCDriver,
    cell: M6_1Cell,
    rpc_iter: _MeasurementRpcIndexIterator,
    m6_winner_deltas: dict[str, float | None],
    m6_winner_directions: dict[str, str | None],
    *,
    base_seed: int,
    progress: ProgressReporter | None = None,
) -> tuple[M6_1CellRecord, dict[M6_1CohortKind, list[M6_1RPCMeasurement]]]:
    warmup_successes = await _run_warmup_m6_1(driver, cell)
    if any(s < M6_1_WARMUP_N for s in warmup_successes.values()):
        empty_aggs = _make_incomplete_cell_aggregates(cell)
        record = _build_cell_record(cell, empty_aggs, m6_winner_deltas, m6_winner_directions)
        if progress is not None:
            for kind in M6_1_COHORTS:
                progress.emit_cell_cohort(cell, kind, 0, 0.0)
        return record, {k: [] for k in M6_1_COHORTS}

    indices = rpc_iter.allocate(M6_1_MEASUREMENT_N)
    start = time.monotonic()
    per_cohort_measurements = await _run_measurement_m6_1(
        driver, cell, indices, base_seed=base_seed
    )
    elapsed_ms = (time.monotonic() - start) * 1000.0

    per_cohort_aggregates: dict[M6_1CohortKind, M6_1PerCohortAggregate] = {}
    for kind in M6_1_COHORTS:
        # Reuse M6's aggregator (shapes are identical).
        m6_agg = _aggregate_cohort(cell, kind, per_cohort_measurements[kind])
        per_cohort_aggregates[kind] = M6_1PerCohortAggregate(
            cohort=kind,
            n_attempted=m6_agg.n_attempted,
            n_successes=m6_agg.n_successes,
            failure_count=m6_agg.failure_count,
            classifier_metric_mean_ms=m6_agg.classifier_metric_mean_ms,
            classifier_metric_ci_half_width_ms=m6_agg.classifier_metric_ci_half_width_ms,
            total_wall_clock_mean_ms=m6_agg.total_wall_clock_mean_ms,
            total_wall_clock_ci_half_width_ms=m6_agg.total_wall_clock_ci_half_width_ms,
            engine_cost_mean=m6_agg.engine_cost_mean,
        )

    record = _build_cell_record(cell, per_cohort_aggregates, m6_winner_deltas, m6_winner_directions)

    if progress is not None:
        per_cohort_elapsed = elapsed_ms / len(M6_1_COHORTS)
        for kind in M6_1_COHORTS:
            successes = per_cohort_aggregates[kind].n_successes
            progress.emit_cell_cohort(cell, kind, successes, per_cohort_elapsed)

    return record, per_cohort_measurements


async def run_full_sweep_with_driver(
    driver: RPCDriver,
    m6_winner_deltas: dict[str, float | None],
    m6_winner_directions: dict[str, str | None],
    *,
    base_seed: int = 42,
    progress: ProgressReporter | None = None,
) -> tuple[
    list[M6_1CellRecord],
    dict[M6_1Cell, dict[M6_1CohortKind, list[M6_1RPCMeasurement]]],
]:
    """Drive the full 6-cell sweep — parameterised over driver for testability."""
    rpc_iter = _MeasurementRpcIndexIterator()
    records: list[M6_1CellRecord] = []
    measurements: dict[M6_1Cell, dict[M6_1CohortKind, list[M6_1RPCMeasurement]]] = {}
    for cell in make_cells():
        record, per_cohort_meas = await run_one_cell(
            driver,
            cell,
            rpc_iter,
            m6_winner_deltas,
            m6_winner_directions,
            base_seed=base_seed,
            progress=progress,
        )
        records.append(record)
        measurements[cell] = per_cohort_meas
    return records, measurements


def apply_chat_stream_drift_flags(
    cells: list[M6_1CellRecord],
    m6_baseline_rows: list[dict[str, Any]],
) -> list[M6_1CellRecord]:
    """Update each cell record with the FR-029 drift flag and return the new list."""
    flags = check_chat_stream_control_drift(cells, m6_baseline_rows)
    out: list[M6_1CellRecord] = []
    for c in cells:
        flag = flags.get((c.cell.path, c.cell.concurrency), False)
        if flag == c.chat_stream_control_drift_warning:
            out.append(c)
            continue
        out.append(
            M6_1CellRecord(
                cell=c.cell,
                per_cohort=c.per_cohort,
                classification=c.classification,
                classification_reason=c.classification_reason,
                classifier_metric=c.classifier_metric,
                cohort_pair=c.cohort_pair,
                m6_winner_delta_ms=c.m6_winner_delta_ms,
                m6_winner_direction=c.m6_winner_direction,
                engine_cost_mean_ms=c.engine_cost_mean_ms,
                engine_cost_drift_warning=c.engine_cost_drift_warning,
                per_cohort_engine_cost_mean_ms=c.per_cohort_engine_cost_mean_ms,
                chat_stream_control_drift_warning=flag,
            )
        )
    return out


def build_supersedes_rows(
    cells: list[M6_1CellRecord],
    m6_winner_directions: dict[str, str | None],
) -> list[SupersedesM6Row]:
    rows: list[SupersedesM6Row] = []
    for c in cells:
        key = cell_key(c.cell)
        direction = m6_winner_directions.get(key)
        winner_cohort: M6_1CohortKind | None = None
        if direction == "rest_wins":
            winner_cohort = "rest_https_edge"
        elif direction == "grpc_wins":
            winner_cohort = "tuned_grpc_multiplexed"
        per_cohort_means: dict[M6_1CohortKind, float] = {
            kind: c.per_cohort[kind].classifier_metric_mean_ms for kind in M6_1_COHORTS
        }
        per_cohort_ci: dict[M6_1CohortKind, tuple[float, float]] = {}
        for kind in M6_1_COHORTS:
            agg = c.per_cohort[kind]
            half = agg.classifier_metric_ci_half_width_ms
            mean = agg.classifier_metric_mean_ms
            per_cohort_ci[kind] = (mean - half, mean + half)
        rows.append(
            SupersedesM6Row(
                cell=c.cell,
                classification=c.classification,
                m6_1_classifier_metric_mean_per_cohort=per_cohort_means,
                m6_1_classifier_metric_ci_per_cohort=per_cohort_ci,
                m6_winner_cohort=winner_cohort,
                m6_winner_delta_ms=c.m6_winner_delta_ms,
                m6_winner_direction=c.m6_winner_direction,
                engine_cost_mean_ms=c.engine_cost_mean_ms,
                engine_cost_drift_warning=c.engine_cost_drift_warning,
                chat_stream_control_drift_warning=c.chat_stream_control_drift_warning,
                notes=c.classification_reason,
            )
        )
    return rows


def build_differential_rows(
    cells: list[M6_1CellRecord],
    m6_baseline_rows: list[dict[str, Any]],
) -> list[EnginePathDifferentialRow]:
    """Compute the EnginePathDifferentialRow for every cell (US2 / SC-007)."""
    by_cell: dict[tuple[str, int, int], dict[str, Any]] = {}
    for row in m6_baseline_rows:
        cell_obj = row.get("cell")
        if not isinstance(cell_obj, dict):
            continue
        by_cell[(cell_obj["path"], cell_obj["hidden_size"], cell_obj["concurrency"])] = row

    rows: list[EnginePathDifferentialRow] = []
    for c in cells:
        m6_row = by_cell.get((c.cell.path, c.cell.hidden_size, c.cell.concurrency), {})
        kwargs = compute_engine_path_differential(c, m6_row)
        rows.append(EnginePathDifferentialRow(**kwargs))  # type: ignore[arg-type]
    return rows


def summarize_verdict_tally(cells: list[M6_1CellRecord]) -> str:
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


# --- Top-level entry point invoked from __main__ -----------------------------

BaselineTuple = tuple[
    dict[str, float | None],
    dict[str, str | None],
    str,  # m6_baseline_engine_version
    dict[str, Any],  # m6_meta passthrough
]


def _read_pinned_vllm_version() -> str:
    import re

    project_root = Path(__file__).resolve().parents[4]
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return "unknown"
    text = pyproject.read_text()
    m = re.search(r'"vllm==([0-9][^";\s]*)', text)
    return m.group(1) if m else "unknown"


def _resolve_seq_len(model_identifier: str) -> int:
    """Attempt to pin seq_len; fall back to a safe default if HuggingFace unreachable."""
    try:
        from vllm_grpc_bench.m6_1_seq_len import pin_seq_len_at_sweep_start

        return pin_seq_len_at_sweep_start(model_identifier)
    except Exception:  # noqa: BLE001
        return _DEFAULT_SEQ_LEN_FALLBACK


async def run_m6_1_sweep(
    args: argparse.Namespace,
    baseline_tuple: BaselineTuple,
) -> int:
    """Execute the M6.1 full sweep end-to-end (T024).

    Exit codes per contracts/cli.md:
    * 0 — success
    * 3 — Modal deploy / sweep mid-run failure
    """
    from vllm_grpc_bench.m6_1_reporter import write_m6_1_report
    from vllm_grpc_bench.m6_1_rpc_driver import provide_m6_1_rpc_driver
    from vllm_grpc_bench.modal_endpoint import ModalDeployError, provide_m6_endpoint

    m6_winner_deltas, m6_winner_directions, m6_baseline_engine_version, m6_meta = baseline_tuple
    # Materialise the M6 baseline rows for drift + differential post-processing.
    import json

    baseline_payload = json.loads(Path(args.m6_1_m6_baseline).read_text())
    m6_baseline_rows = baseline_payload.get("supersedes_m5_2_under_real_engine", [])

    torch_version = _EXPECTED_TORCH_VERSION
    engine_version = _read_pinned_vllm_version()
    progress = ProgressReporter()
    progress.emit_startup(
        model=args.m6_1_model,
        region=args.m6_1_modal_region,
        torch_version=torch_version,
        engine_version=engine_version,
    )

    seq_len = _resolve_seq_len(str(args.m6_1_model))
    started_at = _datetime.datetime.now(_datetime.UTC)
    cold_start_started = time.monotonic()
    cold_start_s = 0.0
    cells: list[M6_1CellRecord] = []
    rtt_distribution: dict[Any, Any] = {}

    try:
        async with provide_m6_endpoint(
            region=str(args.m6_1_modal_region),
            token_env=str(args.m6_1_modal_token_env),
            model_id=str(args.m6_1_model),
        ) as endpoints:
            cold_start_s = time.monotonic() - cold_start_started
            async with provide_m6_1_rpc_driver(
                endpoints,
                seq_len=seq_len,
                base_seed=int(args.m6_1_base_seed),
            ) as (driver, rtt):
                rtt_distribution = dict(rtt)
                cells, _measurements = await run_full_sweep_with_driver(
                    driver,
                    m6_winner_deltas,
                    m6_winner_directions,
                    base_seed=int(args.m6_1_base_seed),
                    progress=progress,
                )
    except ModalDeployError as exc:
        print(f"Error: M6.1 Modal deploy failed: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"Error: M6.1 sweep aborted mid-run: {exc}", file=sys.stderr)
        return 3

    # FR-029 post-sweep drift check (full-sweep only — NOT called by smoke).
    cells = apply_chat_stream_drift_flags(cells, m6_baseline_rows)

    try:
        git_sha = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        git_sha = "unknown"

    run_id = args.m6_1_run_id or f"{started_at.strftime('%Y-%m-%dT%H:%M:%SZ')}-{git_sha[:7]}"

    meta = M6_1RunMeta(
        git_sha=git_sha,
        hostname=socket.gethostname(),
        modal_function_id="vllm-grpc-bench-rest-grpc-m6/serve_bench_real_engine",
        gpu_type="A10G",
        modal_region=str(args.m6_1_modal_region),
        model_identifier=str(args.m6_1_model),
        hidden_size=M6_1_PROMPT_EMBED_HIDDEN_SIZE,
        M6_1_BASE_SEED=int(args.m6_1_base_seed),
        seq_len=seq_len,
        engine_version=engine_version,
        m6_baseline_engine_version=m6_baseline_engine_version,
        torch_version=torch_version,
        m6_winner_deltas=m6_winner_deltas,
        cold_start_s=cold_start_s,
        max_model_len=2048,
        gpu_memory_utilization=0.92,
        run_started_at=started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        run_completed_at=_datetime.datetime.now(_datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    completed_at = _datetime.datetime.now(_datetime.UTC)
    supersedes_rows = build_supersedes_rows(cells, m6_winner_directions)
    differential_rows = build_differential_rows(cells, m6_baseline_rows)
    run = M6_1Run(
        run_id=run_id,
        run_started_at=meta.run_started_at,
        run_completed_at=completed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        run_meta=meta,
        smoke_result=None,
        cells=cells,
        rtt_distribution=rtt_distribution,
        supersedes_m6_under_enable_prompt_embeds=supersedes_rows,
        engine_path_differential=differential_rows,
        m6_meta=m6_meta,
    )

    report_md = Path(args.m6_1_report_out)
    report_json = Path(args.m6_1_report_json_out)
    write_m6_1_report(run, report_md, report_json)

    tally = summarize_verdict_tally(cells)
    progress.emit_completion(str(report_md), tally)
    print(str(report_md))
    return 0


# Re-export helpful names for tests.
RPCDriver = RPCDriver
RPCResult = RPCResult

__all__ = [
    "BaselineTuple",
    "ProgressReporter",
    "RPCDriver",
    "RPCResult",
    "apply_chat_stream_drift_flags",
    "build_differential_rows",
    "build_supersedes_rows",
    "run_full_sweep_with_driver",
    "run_m6_1_sweep",
    "run_one_cell",
    "summarize_verdict_tally",
]

# Suppress unused-import warning — asyncio is referenced indirectly by the
# event loop callers; Callable / Awaitable kept for downstream typing.
_ = (asyncio, Callable, Awaitable)
