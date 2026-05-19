"""M6.1.3 — Phase 1 Attribution Closure: sweep orchestrator.

Mirrors :mod:`m6_1_2_sweep`'s structure (topology probe → cell × cohort
warmup + measurement → artifact build) and ADDS:

* Per-RPC :func:`compute_proxy_edge_segments` derivation of
  ``seg_ingress_ms`` / ``seg_egress_ms`` from the M6.1.3 wire keys
  (``pre_engine_wall_ns``, ``first_chunk_mono_ns``) + vLLM's
  ``RequestStateStats`` timestamps (``engine_arrival_ns``,
  ``engine_first_token_ns``).
* The FR-006 negative-value clock-anomaly assertion (per-RPC + cell-level
  downgrade gate per SC-013).
* Per-cell-cohort :class:`M6_1_3CellMeasurement` aggregation extending
  M6.1.2's wall-clock + engine_ttft summary with the per-segment block
  (PerSegmentAggregate with the 2 new derived segments).
* Classifier wiring: after each cell's per-cohort measurements complete,
  the 7-bucket classifier emits a label per ``contracts/classifier.md``.

Per FR-022 the multi-run loop (``repeat=5``) is US3 (T036) territory; the
US1 skeleton runs a single sweep and leaves ``between_run_variance`` at
``None`` on the published artifact.

Per FR-030 + R-2, the topology probe is invoked ONCE at sweep start
(matches M6.1.2's pattern verbatim per FR-032 — inherited).

Every stderr emission carries the ``_stderr_ts()`` ISO-8601 prefix per
FR-018 / FR-020 / R-7 (inherited from M6.1.2).
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from vllm_grpc_bench.m6_1_1_types import PerSegmentAggregate
from vllm_grpc_bench.m6_1_2_network_probe import emit_probe_warnings, run_topology_probe
from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2_COHORTS,
    M6_1_CELLS,
    M6_1_2CohortKind,
    M6_1_2NetworkPath,
    M6_1_2NetworkPathError,
    M6_1Path,
    build_cohort_set_and_omissions,
    cohorts_at_concurrency,
)
from vllm_grpc_bench.m6_1_3_audit import (
    compute_per_run_verdicts,
    compute_pooled_verdict,
)
from vllm_grpc_bench.m6_1_3_classifier import classify_m6_1_3
from vllm_grpc_bench.m6_1_3_reporter import (
    M6_1_3CellMeasurement,
    M6_1_3RunMeta,
    M6_1_3SweepArtifact,
    _cell_id,
    _ci_half_width_95,
    aggregate_per_cohort_for_cell,
    write_m6_1_3_report,
)
from vllm_grpc_bench.m6_1_3_types import (
    DEFAULT_THRESHOLDS,
    M6_1_3AuditSample,
    M6_1_3ClassifierThresholds,
    M6_1_3SweepMode,
)
from vllm_grpc_bench.m6_1_3_variance import (
    compute_between_run_variance,
    compute_cell_ci_halfwidth_ms,
    compute_phase_b_trigger,
    reduce_cell_variance,
    should_render_variance_section,
)
from vllm_grpc_bench.m6_1_types import M6_1_CONCURRENCIES, M6_1Cell
from vllm_grpc_bench.m6_sweep import RPCResult

_ = M6_1_CONCURRENCIES  # documents the c=1/4/8 domain that c is drawn from


# --- Constants --------------------------------------------------------------

_DEFAULT_MEASUREMENT_N: int = 50
_DEFAULT_WARMUP_N: int = 10
_MAX_TOP_FAILURE_REASONS: int = 5

# FR-028 round-3 Q3: the multi-run orchestrator allows up to 2 Modal tunnel
# preemptions per multi-run sequence before aborting the remaining runs.
# The third preemption triggers a "multi-run incomplete" warning.
_MAX_PREEMPTIONS: int = 2

# Substrings the orchestrator treats as Modal-tunnel-preemption signals.
# When an exception's repr matches any of these, the multi-run loop
# counts it as a preemption rather than re-raising.
_MODAL_PREEMPTION_MARKERS: tuple[str, ...] = (
    "modal.run",
    "modal.host",
    "UNAVAILABLE",
    "Connection refused",
    "tunnel rotated",
)


# --- _stderr_ts() ----------------------------------------------------------


def _stderr_ts() -> str:
    """ISO-8601 UTC bracket prefix for stderr lines. R-7 + FR-018 / FR-020."""
    return datetime.now(UTC).strftime("[%Y-%m-%dT%H:%M:%SZ]")


def _now_iso_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Driver type alias ------------------------------------------------------

M6_1_3RPCDriver = Callable[[M6_1_2CohortKind, M6_1Cell, int], Awaitable[RPCResult]]


# --- Sweep configuration ----------------------------------------------------


@dataclass(frozen=True)
class M6_1_3SweepConfig:
    """Inputs required to run an M6.1.3 sweep.

    Built from :class:`argparse.Namespace` by
    :func:`m6_1_3_validate.run_m6_1_3` via :func:`build_config_from_args`.
    """

    sweep_mode: M6_1_3SweepMode
    modal_region: str
    base_seed: int
    model_identifier: str
    m6_1_1_baseline_pointer: str
    md_out: Path
    json_out: Path
    # M6.1.3 modifier values per FR-022 + FR-023 + FR-019.
    diagnose_repeat: int = 5
    diagnose_n: int = 50
    symmetric_prompts: bool = False
    seq_len: int = 512
    measurement_n: int = _DEFAULT_MEASUREMENT_N
    warmup_n: int = _DEFAULT_WARMUP_N
    skip_deploy: bool = False
    classifier_thresholds: M6_1_3ClassifierThresholds = DEFAULT_THRESHOLDS


# --- Per-RPC proxy-edge derivation (FR-005 + FR-006 + R-3) ------------------


@dataclass(frozen=True)
class _ProxyEdgeRow:
    """Per-RPC derived seg_ingress_ms / seg_egress_ms (FR-005)."""

    seg_ingress_ms: float | None
    seg_egress_ms: float | None
    is_clock_anomaly: bool


def compute_proxy_edge_segments(
    timing_payload: dict[str, Any] | None,
) -> _ProxyEdgeRow:
    """Per-RPC derivation of seg_ingress_ms / seg_egress_ms per FR-005.

    Sources:
    * ``seg_ingress_ms = engine_arrival_ns - pre_engine_wall_ns`` — both on
      the wall-clock (``time.time_ns``) epoch.
    * ``seg_egress_ms = first_chunk_mono_ns - engine_first_token_ns`` — both
      on the monotonic-clock (``time.monotonic_ns``) epoch.

    Per FR-006, a negative value indicates a clock anomaly: the row is
    marked ``is_clock_anomaly=True``, both segments are set to ``None``,
    and the offending raw ``_ns`` values are logged to stderr. The
    aggregator excludes anomalous rows from the per-cohort mean/CI compute.

    Returns ``_ProxyEdgeRow`` with both segments set to ``None`` when the
    timing payload is absent or lacks the required M6.1.3 wire fields
    (pre-M6.1.3 vintage, or unary RPC rows per FR-003 streaming-only).
    """
    if timing_payload is None:
        return _ProxyEdgeRow(None, None, False)

    pre_engine_wall_ns = timing_payload.get("pre_engine_wall_ns")
    first_chunk_mono_ns = timing_payload.get("first_chunk_mono_ns")
    engine_arrival_ns = timing_payload.get("engine_arrival_ns")
    engine_first_token_ns = timing_payload.get("engine_first_token_ns")

    seg_ingress_ms: float | None = None
    seg_egress_ms: float | None = None
    is_clock_anomaly = False

    if pre_engine_wall_ns is not None and engine_arrival_ns:
        # engine_arrival_ns > 0 means vLLM populated arrival_time.
        delta_ns = int(engine_arrival_ns) - int(pre_engine_wall_ns)
        seg_ingress_ms = delta_ns * 1e-6
        if seg_ingress_ms < 0:
            # FR-006 negative-value assertion. Log raw _ns values for
            # diagnostic stderr trail per R-3 + SC-013.
            print(
                f"{_stderr_ts()} [clock-anomaly] seg_ingress_ms={seg_ingress_ms:.3f} "
                f"(engine_arrival_ns={engine_arrival_ns}, "
                f"pre_engine_wall_ns={pre_engine_wall_ns})",
                file=sys.stderr,
                flush=True,
            )
            is_clock_anomaly = True
            seg_ingress_ms = None

    if first_chunk_mono_ns is not None and engine_first_token_ns:
        delta_ns = int(first_chunk_mono_ns) - int(engine_first_token_ns)
        seg_egress_ms = delta_ns * 1e-6
        if seg_egress_ms < 0:
            print(
                f"{_stderr_ts()} [clock-anomaly] seg_egress_ms={seg_egress_ms:.3f} "
                f"(first_chunk_mono_ns={first_chunk_mono_ns}, "
                f"engine_first_token_ns={engine_first_token_ns})",
                file=sys.stderr,
                flush=True,
            )
            is_clock_anomaly = True
            seg_egress_ms = None

    return _ProxyEdgeRow(seg_ingress_ms, seg_egress_ms, is_clock_anomaly)


# --- Per-cell-cohort aggregation -------------------------------------------


def _mean_or_zero(samples: list[float]) -> float:
    return sum(samples) / len(samples) if samples else 0.0


def _aggregate_per_segment(
    results: list[RPCResult],
    *,
    thresholds: M6_1_3ClassifierThresholds,
) -> PerSegmentAggregate | None:
    """Aggregate per-cohort per-RPC results into a PerSegmentAggregate.

    Reads each RPCResult's ``m6_1_1_timing_payload`` to derive:
    * M6.1.1 perf_counter segments (seg_ab / seg_bc / seg_cd)
    * M6.1.2 engine-internal segments (seg_queue / seg_prefill)
    * M6.1.3 derived segments (seg_ingress / seg_egress) via
      :func:`compute_proxy_edge_segments`

    Per FR-006: rows where ``compute_proxy_edge_segments`` flagged a clock
    anomaly are EXCLUDED from the per-segment mean/CI compute for the new
    M6.1.3 segments but are still counted in the M6.1.1 / M6.1.2 segments
    (the anomaly is specific to the wall↔monotonic conversion in the
    proxy-edge derivation, not the perf_counter / engine timestamps).

    Returns ``None`` when no successful RPC populated the timing payload.
    """
    timings: list[dict[str, int]] = [
        cast(dict[str, int], r.m6_1_1_timing_payload)
        for r in results
        if r.success and r.m6_1_1_timing_payload is not None
    ]
    if not timings:
        return None

    seg_ab = [(t["pre_engine_ns"] - t["handler_entry_ns"]) * 1e-6 for t in timings]
    seg_bc = [(t["first_chunk_ns"] - t["pre_engine_ns"]) * 1e-6 for t in timings]
    seg_cd = [(t["terminal_emit_ns"] - t["first_chunk_ns"]) * 1e-6 for t in timings]

    # M6.1.2 engine-internal segments. Skip rows where any engine field is 0.
    engine_stats_timings = [
        t
        for t in timings
        if t.get("engine_queued_ns", 0) > 0
        and t.get("engine_scheduled_ns", 0) > 0
        and t.get("engine_first_token_ns", 0) > 0
        and t.get("engine_last_token_ns", 0) > 0
    ]
    seg_queue_mean: float | None = None
    seg_queue_ci: float | None = None
    seg_prefill_mean: float | None = None
    seg_prefill_ci: float | None = None
    if engine_stats_timings:
        seg_queue = [
            (t["engine_scheduled_ns"] - t["engine_queued_ns"]) * 1e-6 for t in engine_stats_timings
        ]
        seg_prefill = [
            (t["engine_first_token_ns"] - t["engine_scheduled_ns"]) * 1e-6
            for t in engine_stats_timings
        ]
        seg_queue_mean = _mean_or_zero(seg_queue)
        seg_queue_ci = _ci_half_width_95(seg_queue)
        seg_prefill_mean = _mean_or_zero(seg_prefill)
        seg_prefill_ci = _ci_half_width_95(seg_prefill)

    # M6.1.3 proxy-edge segments (FR-005 + FR-006).
    seg_ingress_samples: list[float] = []
    seg_egress_samples: list[float] = []
    anomaly_count = 0
    for t in timings:
        row = compute_proxy_edge_segments(t)
        if row.is_clock_anomaly:
            anomaly_count += 1
            continue
        if row.seg_ingress_ms is not None:
            seg_ingress_samples.append(row.seg_ingress_ms)
        if row.seg_egress_ms is not None:
            seg_egress_samples.append(row.seg_egress_ms)
    clock_anomaly_fraction = anomaly_count / len(timings) if timings else 0.0
    clock_anomaly_warning = clock_anomaly_fraction > thresholds.clock_anomaly_max_fraction

    seg_ingress_mean: float | None = None
    seg_ingress_ci: float | None = None
    seg_egress_mean: float | None = None
    seg_egress_ci: float | None = None
    if seg_ingress_samples:
        seg_ingress_mean = _mean_or_zero(seg_ingress_samples)
        seg_ingress_ci = _ci_half_width_95(seg_ingress_samples)
    if seg_egress_samples:
        seg_egress_mean = _mean_or_zero(seg_egress_samples)
        seg_egress_ci = _ci_half_width_95(seg_egress_samples)

    return PerSegmentAggregate(
        seg_ab_ms_mean=_mean_or_zero(seg_ab),
        seg_ab_ms_ci_half_width=_ci_half_width_95(seg_ab),
        seg_bc_ms_mean=_mean_or_zero(seg_bc),
        seg_bc_ms_ci_half_width=_ci_half_width_95(seg_bc),
        seg_cd_ms_mean=_mean_or_zero(seg_cd),
        seg_cd_ms_ci_half_width=_ci_half_width_95(seg_cd),
        n_samples=len(timings),
        seg_queue_ms_mean=seg_queue_mean,
        seg_queue_ms_ci_half_width=seg_queue_ci,
        seg_prefill_ms_mean=seg_prefill_mean,
        seg_prefill_ms_ci_half_width=seg_prefill_ci,
        seg_ingress_ms_mean=seg_ingress_mean,
        seg_ingress_ms_ci_half_width=seg_ingress_ci,
        seg_egress_ms_mean=seg_egress_mean,
        seg_egress_ms_ci_half_width=seg_egress_ci,
        clock_anomaly_fraction=clock_anomaly_fraction,
        clock_anomaly_warning=clock_anomaly_warning,
    )


def _summarize_cell(
    path: M6_1Path,
    concurrency: int,
    cohort: M6_1_2CohortKind,
    results: list[RPCResult],
    *,
    thresholds: M6_1_3ClassifierThresholds,
) -> M6_1_3CellMeasurement:
    """Reduce per-RPC results to a single M6_1_3CellMeasurement summary."""
    wall_clocks = [r.wall_clock_ms for r in results if r.wall_clock_ms is not None]
    ttfts: list[float] = []
    for r in results:
        cost = r.engine_cost
        if cost is None:
            continue
        ttft = getattr(cost, "engine_ttft_ms", None)
        if ttft is not None:
            ttfts.append(float(ttft))

    failure_counter: dict[str, int] = {}
    for r in results:
        if r.success:
            continue
        reason = r.failure_reason or "<unknown>"
        failure_counter[reason] = failure_counter.get(reason, 0) + 1
    top_failures = dict(
        sorted(failure_counter.items(), key=lambda kv: kv[1], reverse=True)[
            :_MAX_TOP_FAILURE_REASONS
        ]
    )

    per_segment = _aggregate_per_segment(results, thresholds=thresholds)

    # M6.1.3 — extract per-RPC audit samples (FR-013 + FR-014 + R-9). The
    # samples are wire-canonical-sourced: they come directly from the
    # extractor-populated timing payload, NOT a parallel emission path.
    # Sidecar / audit-table renderings derive from this same list.
    audit_samples: list[tuple[int, str]] = []
    for r in results:
        if not r.success or r.m6_1_1_timing_payload is None:
            continue
        length_raw = r.m6_1_1_timing_payload.get("tokenized_prompt_length")
        hash_raw = r.m6_1_1_timing_payload.get("tokenized_prompt_hash")
        if length_raw is None or hash_raw is None:
            continue
        audit_samples.append((int(length_raw), str(hash_raw)))

    return M6_1_3CellMeasurement(
        path=path,
        concurrency=concurrency,
        cohort=cohort,
        n_attempts=len(results),
        n_successes=sum(1 for r in results if r.success),
        wall_clock_ms_mean=statistics.fmean(wall_clocks) if wall_clocks else None,
        engine_ttft_ms_mean=statistics.fmean(ttfts) if ttfts else None,
        top_failure_reasons=top_failures,
        per_segment=per_segment,
        audit_samples=audit_samples,
    )


# --- Modal preemption detection (FR-028 + R-5) ------------------------------


def _is_modal_preemption(exc: BaseException) -> bool:
    """Heuristic check: does this exception look like a Modal tunnel
    preemption?

    The M5.2 pattern detects preemption via connection errors against
    Modal-hosted URLs (``*.modal.run`` / ``*.modal.host``) or specific
    gRPC status strings (``UNAVAILABLE``). We match on either the
    exception repr or its message text. Conservative: only counts
    exceptions whose text clearly indicates a Modal-side connection
    issue, so a programming error in the orchestrator still propagates.
    """
    text = f"{type(exc).__name__}: {exc}"
    return any(marker in text for marker in _MODAL_PREEMPTION_MARKERS)


# --- Cell iteration helper --------------------------------------------------


def _iter_cells_cohorts() -> list[tuple[M6_1Path, int, M6_1_2CohortKind]]:
    """Expand M6_1_CELLS × cohorts_at_concurrency(c) into a flat list."""
    pairs: list[tuple[M6_1Path, int, M6_1_2CohortKind]] = []
    for path, _hidden_size, c in M6_1_CELLS:
        for cohort in cohorts_at_concurrency(c):
            pairs.append((path, c, cohort))
    return pairs


# --- Single-run phase 1 measurement (extracted for multi-run wrapping) -----


async def _run_phase1_once(
    *,
    config: M6_1_3SweepConfig,
    driver: M6_1_3RPCDriver,
    pairs: list[tuple[M6_1Path, int, M6_1_2CohortKind]],
    run_idx: int,
    cohorts_seen: set[M6_1_2CohortKind],
) -> list[M6_1_3CellMeasurement]:
    """Run one phase-1 sweep iteration (all cell × cohort pairs).

    Returns the per-(cell, cohort) measurements for this run.
    ``cohorts_seen`` is mutated as cohorts run (the caller uses it to
    build ``cohort_set`` in the artifact). Preemption / connection
    errors are NOT caught here — they propagate to the multi-run loop
    in :func:`run_m6_1_3_sweep`.
    """
    measurements: list[M6_1_3CellMeasurement] = []
    total_pairs = len(pairs)
    for idx, (path, c, cohort) in enumerate(pairs, start=1):
        cell = M6_1Cell(path=path, hidden_size=4096, concurrency=c)  # type: ignore[arg-type]

        if config.warmup_n > 0:
            await asyncio.gather(*(driver(cohort, cell, 0) for _ in range(config.warmup_n)))

        sem = asyncio.Semaphore(c)

        async def _one(
            i: int,
            cohort_ref: M6_1_2CohortKind = cohort,
            cell_ref: M6_1Cell = cell,
            sem_ref: asyncio.Semaphore = sem,
        ) -> RPCResult:
            async with sem_ref:
                # Seed offset by run_idx × measurement_n so each run sees
                # a non-overlapping seed range — preserves M6.1.2's per-RPC
                # determinism while keeping per-run RPC content fresh.
                seed = config.base_seed + run_idx * config.measurement_n + i
                return await driver(cohort_ref, cell_ref, seed)

        results = await asyncio.gather(*(_one(i) for i in range(config.measurement_n)))
        summary = _summarize_cell(
            path, c, cohort, list(results), thresholds=config.classifier_thresholds
        )
        measurements.append(summary)
        cohorts_seen.add(cohort)

        n_succ = summary.n_successes
        n_att = summary.n_attempts
        failure_tail = ""
        if n_succ < n_att and summary.top_failure_reasons:
            top_reason, top_count = next(iter(summary.top_failure_reasons.items()))
            failure_tail = f" — top failure ({top_count}/{n_att - n_succ}): {top_reason}"
        print(
            f"{_stderr_ts()} [run {run_idx + 1}][{idx}/{total_pairs}] "
            f"{path} × c={c} / {cohort} — {n_succ}/{n_att} succ{failure_tail}",
            file=sys.stderr,
            flush=True,
        )
    return measurements


# --- Sweep orchestration ----------------------------------------------------


async def run_m6_1_3_sweep(
    config: M6_1_3SweepConfig,
    *,
    driver: M6_1_3RPCDriver,
    handshake_dict: dict[str, object] | None = None,
    network_probe_ranges: dict[str, dict[str, Any]] | None = None,
    network_probe_results: dict[M6_1_2CohortKind, M6_1_2NetworkPath | M6_1_2NetworkPathError]
    | None = None,
) -> M6_1_3SweepArtifact:
    """Execute the M6.1.3 sweep and return the artifact payload.

    Per US1 scope: single-run sweep (no multi-run loop yet — US3 T036
    adds the multi-run extension). ``between_run_variance`` stays
    ``None`` on the returned artifact; the reporter omits the variance
    section accordingly.

    Two injection points let the integration test drive the sweep
    without Modal: ``driver`` (stub RPC driver) and either
    ``network_probe_results`` (canned probe outputs) or ``handshake_dict``
    (real handshake passed to :func:`run_topology_probe`).
    """
    run_started_at = _now_iso_utc()
    started_mono = time.monotonic()
    run_id = f"{run_started_at}-{uuid.uuid4().hex[:8]}"

    # Step 1+2: topology probe (parallel, 30s per-cohort timeout) — inherited
    # verbatim from M6.1.2 per FR-032.
    if network_probe_results is not None:
        network_paths = network_probe_results
    elif handshake_dict is not None:
        print(
            f"{_stderr_ts()} M6.1.3 topology probe: 4 cohorts in parallel (per-cohort timeout 30s)",
            file=sys.stderr,
            flush=True,
        )
        network_paths = await run_topology_probe(
            handshake_dict=handshake_dict,
            cohorts=M6_1_2_COHORTS,
            per_cohort_timeout_seconds=30.0,
            ranges=network_probe_ranges,
        )
        emit_probe_warnings(network_paths)
    else:
        probed_at = _now_iso_utc()
        network_paths = {
            cohort: M6_1_2NetworkPathError(
                error="subprocess_error",
                probe_method="tcptraceroute",
                probed_at_utc=probed_at,
                detail="--m6_1_3-skip-deploy: no handshake dict to probe",
            )
            for cohort in M6_1_2_COHORTS
        }

    # Step 3: multi-run loop per FR-022. Each run independently warms up
    # + measures each (cell, cohort) pair; per-run measurements accumulate
    # into ``phase_1_runs`` for the post-loop variance compute.
    phase_1_runs: list[list[M6_1_3CellMeasurement]] = []
    cohorts_actually_run: set[M6_1_2CohortKind] = set()
    pairs = _iter_cells_cohorts()
    total_pairs = len(pairs)
    n_runs_planned = max(1, config.diagnose_repeat)
    print(
        f"{_stderr_ts()} M6.1.3 {config.sweep_mode} sweep: {n_runs_planned} run(s) × "
        f"{total_pairs} (cell, cohort) pairs × n={config.measurement_n}, "
        f"region={config.modal_region}, model={config.model_identifier}, "
        f"repeat={config.diagnose_repeat}, "
        f"symmetric_prompts={config.symmetric_prompts}",
        file=sys.stderr,
        flush=True,
    )

    preemption_count = 0
    multi_run_incomplete = False
    for run_idx in range(n_runs_planned):
        if n_runs_planned > 1:
            print(
                f"{_stderr_ts()} M6.1.3 run {run_idx + 1}/{n_runs_planned} starting",
                file=sys.stderr,
                flush=True,
            )
        try:
            run_measurements = await _run_phase1_once(
                config=config,
                driver=driver,
                pairs=pairs,
                run_idx=run_idx,
                cohorts_seen=cohorts_actually_run,
            )
        except Exception as exc:  # noqa: BLE001
            # FR-028 + R-5: detect Modal tunnel preemption (connection errors
            # against *.modal.run / *.modal.host URLs). The actual URL
            # refresh is operator-driven (re-deploy + re-run the sweep);
            # the orchestrator's responsibility is to count, log, and abort
            # after the pinned threshold of 2 preemptions.
            if _is_modal_preemption(exc):
                preemption_count += 1
                print(
                    f"{_stderr_ts()} [FR-028] Modal tunnel preemption detected "
                    f"on run {run_idx + 1}/{n_runs_planned} (count={preemption_count}/"
                    f"{_MAX_PREEMPTIONS}): {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                if preemption_count > _MAX_PREEMPTIONS:
                    print(
                        f"{_stderr_ts()} [FR-028] preemption count exceeded "
                        f"threshold ({_MAX_PREEMPTIONS}); aborting remaining "
                        "runs — multi-run incomplete",
                        file=sys.stderr,
                        flush=True,
                    )
                    multi_run_incomplete = True
                    break
                continue
            # Non-preemption exception: re-raise so the caller maps it to
            # the appropriate exit code.
            raise
        phase_1_runs.append(run_measurements)

    run_completed_at = _now_iso_utc()
    elapsed_min = (time.monotonic() - started_mono) / 60.0
    print(
        f"{_stderr_ts()} M6.1.3 {config.sweep_mode} sweep complete in {elapsed_min:.1f} min "
        f"({len(phase_1_runs)}/{n_runs_planned} runs)",
        file=sys.stderr,
        flush=True,
    )

    # Representative measurements: use the last successful run for the
    # canonical per-cell view. For multi-run sweeps the variance signal
    # is the headline output; the per-cell timings are a snapshot.
    measurements: list[M6_1_3CellMeasurement] = phase_1_runs[-1] if phase_1_runs else []

    # Step 4a: between-run variance per FR-024 (computed across all
    # successful runs in phase_1_runs). The reporter suppresses the
    # variance section on < 3 runs per FR-025; the compute itself still
    # runs so other consumers can inspect partial data programmatically.
    variance_section_suppressed = not should_render_variance_section(phase_1_runs)
    between_run_variance = compute_between_run_variance(phase_1_runs) if phase_1_runs else {}

    # Step 4b: classifier — per cell, with the 7-bucket extension + the
    # FR-026 outer-override gate (between_run_variance + ci_halfwidth
    # threaded through). The classifier uses the LAST-run per-cohort
    # data as the representative inner-label input; the variance comes
    # from the multi-run pool.
    classifications: dict[str, str] = {}
    classifier_notes: list[str] = []
    cell_signatures_raw: set[tuple[str, int]] = {(m.path, m.concurrency) for m in measurements}
    cell_signatures: list[tuple[M6_1Path, int]] = [
        (cast(M6_1Path, p), c) for p, c in sorted(cell_signatures_raw)
    ]
    for path, c in cell_signatures:
        per_cohort = aggregate_per_cohort_for_cell(measurements, path, c)
        cid = _cell_id(path, c)
        if not per_cohort:
            classifications[cid] = "inconclusive"
            continue
        cell = M6_1Cell(path=path, hidden_size=4096, concurrency=c)  # type: ignore[arg-type]

        # Multi-run signal (variance suppressed on < 3 runs → outer-override
        # gate cannot fire either; classifier receives ``None`` variance).
        cell_variance_per_cohort = (
            between_run_variance.get(cid, {}) if not variance_section_suppressed else {}
        )
        cell_variance = (
            reduce_cell_variance(cell_variance_per_cohort) if cell_variance_per_cohort else None
        )

        # Within-run CI half-width: max across cohorts (most-conservative
        # gate). Computed from the representative measurements.
        per_cohort_cis = {
            cohort_key: float(getattr(mpt, "engine_ttft_ms_ci_half_width", 0.0))
            for cohort_key, mpt in per_cohort.items()
        }
        ci_halfwidth_ms = compute_cell_ci_halfwidth_ms(per_cohort_cis)

        label = classify_m6_1_3(
            cell,
            per_cohort,
            between_run_variance=cell_variance,
            ci_halfwidth_ms=ci_halfwidth_ms,
            thresholds=config.classifier_thresholds,
        )
        classifications[cid] = label

        # FR-027 cohort-unhealthy note: surface a classifier note when
        # any cohort dropped out of variance compute (mean_of_means_ms is
        # None) so the operator sees the partial-data signal in the
        # published artifact.
        for cohort_name, variance_cell in cell_variance_per_cohort.items():
            if variance_cell.mean_of_means_ms is None:
                classifier_notes.append(
                    f"cohort_unhealthy: cell {cid} cohort {cohort_name} "
                    f"contributed only {variance_cell.n_runs} successful "
                    f"run(s) of {len(phase_1_runs)} planned (FR-027)"
                )

    if multi_run_incomplete:
        classifier_notes.append(
            f"multi-run incomplete: {len(phase_1_runs)} of {n_runs_planned} "
            "runs collected before preemption-threshold abort (FR-028)"
        )

    # Step 4c: Phase B trigger verdict per FR-043 / FR-044 / round-2 Q3.
    phase_b_trigger = compute_phase_b_trigger(
        classifications,
        variance_section_suppressed=variance_section_suppressed,
    )

    # Step 4d: per-cohort prompt-content audit (FR-016 + FR-016a + round-1 Q5).
    # Build the flat audit-sample list across ALL runs; the per-run grouping
    # uses run_idx so the FR-016a conditional appendix can compare per-run
    # verdicts against the pooled verdict.
    audit_flat: list[M6_1_3AuditSample] = []
    for run_idx, run_measurements in enumerate(phase_1_runs):
        for m in run_measurements:
            cell_id_for_m = _cell_id(m.path, m.concurrency)
            for length, prompt_hash in m.audit_samples:
                audit_flat.append(
                    M6_1_3AuditSample(
                        run_idx=run_idx,
                        cell_id=cell_id_for_m,
                        cohort=m.cohort,
                        tokenized_prompt_length=length,
                        tokenized_prompt_hash=prompt_hash,
                    )
                )
    audit_pooled = compute_pooled_verdict(audit_flat) if audit_flat else None
    audit_per_run = compute_per_run_verdicts(audit_flat) if audit_flat else None

    # FR-016 invariant: cohorts_run ∪ omissions == canonical universe.
    intentional_omissions = _compute_omissions(cohorts_actually_run)
    cohort_set, omissions = build_cohort_set_and_omissions(
        cohorts_actually_run, intentional_omissions
    )

    return M6_1_3SweepArtifact(
        schema_version="m6_1_1.v1",  # NO BUMP per FR-010 + round-3 Q1
        dispatch_mode="concurrent",
        run_id=run_id,
        run_started_at=run_started_at,
        run_completed_at=run_completed_at,
        run_meta=M6_1_3RunMeta(
            git_sha="",
            modal_region=config.modal_region,
            base_seed=config.base_seed,
            model_identifier=config.model_identifier,
            sweep_mode=config.sweep_mode,
            seq_len=config.seq_len,
            run_started_at=run_started_at,
            run_completed_at=run_completed_at,
            m6_1_1_baseline_pointer=config.m6_1_1_baseline_pointer,
            m6_1_3_diagnose_repeat=config.diagnose_repeat,
            m6_1_3_diagnose_n=config.diagnose_n,
            m6_1_3_symmetric_prompts=config.symmetric_prompts,
        ),
        network_paths=network_paths,
        cohort_set=cohort_set,
        cohort_omissions=omissions,
        measurements=measurements,
        classifications=classifications,
        classifier_notes=classifier_notes,
        audit=audit_pooled,
        audit_per_run=audit_per_run,
        # US3: variance + Phase B trigger wired. The reporter suppresses
        # the variance section on < 3 runs per FR-025; the data is still
        # present on the artifact so other consumers can inspect it.
        between_run_variance=between_run_variance if between_run_variance else None,
        phase_b_trigger=phase_b_trigger,
        phase_1_runs=phase_1_runs,
    )


def _compute_omissions(
    cohorts_run: set[M6_1_2CohortKind],
) -> dict[M6_1_2CohortKind, str] | None:
    """Return per-cohort intentional omissions if the run didn't cover the
    canonical 4-cohort universe.

    For M6.1.3's default 6-cell × 4-cohort sweep, all 4 cohorts iterate at
    c >= 2 so the universe is covered. A degraded c=1-only sweep would
    collapse ``tuned_grpc_multiplexed`` per FR-011 — record that as an
    intentional structural omission.
    """
    canonical: set[M6_1_2CohortKind] = set(M6_1_2_COHORTS)
    missing = canonical - cohorts_run
    if not missing:
        return None
    out: dict[M6_1_2CohortKind, str] = {}
    for cohort in missing:
        if cohort == "tuned_grpc_multiplexed":
            out[cohort] = "collapsed into default_grpc at c=1 per FR-011"
        else:
            out[cohort] = "cohort not exercised by this sweep configuration"
    return out


def write_sweep_artifact(
    artifact: M6_1_3SweepArtifact,
    md_path: Path,
    json_path: Path,
) -> None:
    """Thin wrapper around :func:`write_m6_1_3_report`."""
    write_m6_1_3_report(artifact, md_path, json_path)


def build_config_from_args(
    args: argparse.Namespace, *, sweep_mode: M6_1_3SweepMode
) -> M6_1_3SweepConfig:
    """Build :class:`M6_1_3SweepConfig` from a parsed argparse namespace.

    Reads the ``--m6_1_3-*`` flags defined in ``__main__.py``. ``sweep_mode``
    is supplied by the dispatch wiring. Output paths are pre-resolved by
    :func:`m6_1_3_validate.infer_output_path` and passed in as ``md_out``
    / ``json_out``.
    """
    return M6_1_3SweepConfig(
        sweep_mode=sweep_mode,
        modal_region=str(args.m6_1_3_modal_region),
        base_seed=int(args.m6_1_3_base_seed),
        model_identifier=str(args.m6_1_3_model),
        m6_1_1_baseline_pointer=str(args.m6_1_3_m6_1_1_baseline),
        md_out=Path(str(args.m6_1_3_report_out)),
        json_out=Path(str(args.m6_1_3_report_json_out)),
        diagnose_repeat=int(args.m6_1_3_diagnose_repeat),
        diagnose_n=int(args.m6_1_3_diagnose_n),
        symmetric_prompts=bool(args.m6_1_3_symmetric_prompts),
        skip_deploy=bool(args.m6_1_3_skip_deploy),
    )


__all__ = [
    "M6_1_3RPCDriver",
    "M6_1_3SweepConfig",
    "build_config_from_args",
    "compute_proxy_edge_segments",
    "run_m6_1_3_sweep",
    "write_sweep_artifact",
]
