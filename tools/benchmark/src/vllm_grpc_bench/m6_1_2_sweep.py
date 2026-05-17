"""M6.1.2 — Methodology Discipline: sweep orchestrator.

Sequencing (per R-8 + data-model.md "Cohort iteration semantics"):

1. Modal deploy + handshake (reuses M6.1's ``provide_m6_endpoint`` —
   UNCHANGED per FR-022). When ``--m6_1_2-skip-deploy`` is set, the
   orchestrator takes a stub driver from the caller for harness wiring
   confidence-builder runs.
2. Topology probe across the 4 cohorts (FR-001 / FR-001a / FR-002a) via
   :func:`m6_1_2_network_probe.run_topology_probe`. Emits FR-005a /
   FR-006 warnings to stderr.
3. Cell × cohort iteration with :func:`cohorts_at_concurrency` collapsing
   ``tuned_grpc_multiplexed`` into ``default_grpc`` at c=1 per FR-011.
4. Hand the collected payload to :func:`m6_1_2_reporter.write_m6_1_2_report`.

Every stderr emission carries the ``_stderr_ts()`` ISO-8601 prefix per
FR-018 / FR-020 / R-7.
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
from typing import Any

from vllm_grpc_bench.m6_1_2_network_probe import (
    emit_probe_warnings,
    run_topology_probe,
)
from vllm_grpc_bench.m6_1_2_reporter import (
    M6_1_2CellMeasurement,
    M6_1_2RunMeta,
    M6_1_2SweepArtifact,
    write_m6_1_2_report,
)
from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2_COHORTS,
    M6_1_CELLS,
    M6_1_2CohortKind,
    M6_1_2NetworkPath,
    M6_1_2NetworkPathError,
    M6_1_2SweepMode,
    M6_1Path,
    build_cohort_set_and_omissions,
    cohorts_at_concurrency,
)
from vllm_grpc_bench.m6_1_types import M6_1_CONCURRENCIES, M6_1Cell
from vllm_grpc_bench.m6_sweep import RPCResult

_ = M6_1_CONCURRENCIES  # documents the c=1/4/8 domain that c is drawn from

# --- Constants --------------------------------------------------------------

_DEFAULT_MEASUREMENT_N: int = 50
_DEFAULT_WARMUP_N: int = 10


# --- _stderr_ts() ----------------------------------------------------------


def _stderr_ts() -> str:
    """ISO-8601 UTC bracket prefix for stderr lines. R-7 + FR-018 / FR-020."""
    return datetime.now(UTC).strftime("[%Y-%m-%dT%H:%M:%SZ]")


def _now_iso_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Driver type alias ------------------------------------------------------

M6_1_2RPCDriver = Callable[[M6_1_2CohortKind, M6_1Cell, int], Awaitable[RPCResult]]


# --- Sweep configuration ----------------------------------------------------


@dataclass(frozen=True)
class M6_1_2SweepConfig:
    """Inputs required to run an M6.1.2 sweep.

    Built from :class:`argparse.Namespace` by ``m6_1_2_validate.run_m6_1_2``.
    """

    sweep_mode: M6_1_2SweepMode
    modal_region: str
    base_seed: int
    model_identifier: str
    m6_1_1_baseline_pointer: str
    md_out: Path
    json_out: Path
    seq_len: int = 512
    measurement_n: int = _DEFAULT_MEASUREMENT_N
    warmup_n: int = _DEFAULT_WARMUP_N
    skip_deploy: bool = False


# --- Cell iteration helper --------------------------------------------------


def _iter_cells_cohorts() -> list[tuple[M6_1Path, int, M6_1_2CohortKind]]:
    """Expand M6_1_CELLS × cohorts_at_concurrency(c) into a flat list."""
    pairs: list[tuple[M6_1Path, int, M6_1_2CohortKind]] = []
    for path, _hidden_size, c in M6_1_CELLS:
        for cohort in cohorts_at_concurrency(c):
            pairs.append((path, c, cohort))
    return pairs


# --- Aggregate measurement results ------------------------------------------


_MAX_TOP_FAILURE_REASONS: int = 5


def _summarize_cell(
    path: M6_1Path,
    concurrency: int,
    cohort: M6_1_2CohortKind,
    results: list[RPCResult],
) -> M6_1_2CellMeasurement:
    wall_clocks = [r.wall_clock_ms for r in results if r.wall_clock_ms is not None]
    ttfts: list[float] = []
    for r in results:
        cost = r.engine_cost
        if cost is None:
            continue
        ttft = getattr(cost, "engine_ttft_ms", None)
        if ttft is not None:
            ttfts.append(float(ttft))

    # Failure-reason histogram (top-N by count). Empty when every RPC
    # succeeded. Lets downstream readers diagnose 0/N-success cohorts from
    # the published artifact alone.
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

    return M6_1_2CellMeasurement(
        path=path,
        concurrency=concurrency,
        cohort=cohort,
        n_attempts=len(results),
        n_successes=sum(1 for r in results if r.success),
        wall_clock_ms_mean=statistics.fmean(wall_clocks) if wall_clocks else None,
        engine_ttft_ms_mean=statistics.fmean(ttfts) if ttfts else None,
        top_failure_reasons=top_failures,
    )


# --- Sweep orchestration ----------------------------------------------------


async def run_m6_1_2_sweep(
    config: M6_1_2SweepConfig,
    *,
    driver: M6_1_2RPCDriver,
    handshake_dict: dict[str, object] | None = None,
    network_probe_ranges: dict[str, dict[str, Any]] | None = None,
    network_probe_results: dict[M6_1_2CohortKind, M6_1_2NetworkPath | M6_1_2NetworkPathError]
    | None = None,
) -> M6_1_2SweepArtifact:
    """Execute the sweep and return the artifact payload.

    Two injection points let the integration test (T034) drive the sweep
    without Modal: ``driver`` (stub RPC driver) and either
    ``network_probe_results`` (canned probe outputs) or ``handshake_dict``
    (real handshake passed to :func:`run_topology_probe`).
    """
    run_started_at = _now_iso_utc()
    started_mono = time.monotonic()
    run_id = f"{run_started_at}-{uuid.uuid4().hex[:8]}"

    # Step 1+2: topology probe (parallel, 30s per-cohort timeout).
    if network_probe_results is not None:
        network_paths = network_probe_results
    elif handshake_dict is not None:
        print(
            f"{_stderr_ts()} M6.1.2 topology probe: 4 cohorts in parallel (per-cohort timeout 30s)",
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
        # Skip-deploy path with no canned probes — record an error per cohort
        # so the artifact still satisfies the FR-016 cohort universe invariant.
        probed_at = _now_iso_utc()
        network_paths = {
            cohort: M6_1_2NetworkPathError(
                error="subprocess_error",
                probe_method="tcptraceroute",
                probed_at_utc=probed_at,
                detail="--m6_1_2-skip-deploy: no handshake dict to probe",
            )
            for cohort in M6_1_2_COHORTS
        }

    # Step 3: per-cell, per-cohort warmup + measurement.
    measurements: list[M6_1_2CellMeasurement] = []
    cohorts_actually_run: set[M6_1_2CohortKind] = set()
    pairs = _iter_cells_cohorts()
    total_pairs = len(pairs)
    print(
        f"{_stderr_ts()} M6.1.2 {config.sweep_mode} sweep: {total_pairs} (cell, cohort) "
        f"pairs × n={config.measurement_n}, region={config.modal_region}, "
        f"model={config.model_identifier}",
        file=sys.stderr,
        flush=True,
    )

    for idx, (path, c, cohort) in enumerate(pairs, start=1):
        # c comes from M6_1_CELLS which is closed over Literal[1, 4, 8];
        # the cast is sound by construction.
        cell = M6_1Cell(path=path, hidden_size=4096, concurrency=c)  # type: ignore[arg-type]

        # Warmup: concurrent gather at seed=0 per M6.0a (FR-001 / FR-005a)
        # + smoke/warmup convention (feedback_smoke_warmup_seed_zero memory).
        # Results discarded — purpose is engine warm-state stabilisation.
        if config.warmup_n > 0:
            await asyncio.gather(*(driver(cohort, cell, 0) for _ in range(config.warmup_n)))

        # Measurement: c-in-flight bounded via asyncio.Semaphore(c) so the
        # engine sees a steady c-in-flight stream, mirroring M6.1.1's
        # _measure_cell pattern (m6_1_1_sweep.py:316-328). seed = base_seed + i
        # so the SET of (cohort, seed) records is reproducible.
        sem = asyncio.Semaphore(c)

        async def _one(
            i: int,
            cohort_ref: M6_1_2CohortKind = cohort,
            cell_ref: M6_1Cell = cell,
            sem_ref: asyncio.Semaphore = sem,
        ) -> RPCResult:
            async with sem_ref:
                return await driver(cohort_ref, cell_ref, config.base_seed + i)

        results = await asyncio.gather(*(_one(i) for i in range(config.measurement_n)))
        summary = _summarize_cell(path, c, cohort, list(results))
        measurements.append(summary)
        cohorts_actually_run.add(cohort)
        n_succ = summary.n_successes
        n_att = summary.n_attempts
        # Surface the dominant failure reason on the progress line when any
        # RPC failed, so live diagnosis doesn't require waiting for the
        # artifact (which only writes on full-sweep completion). For a
        # complete cohort failure (0/N) the failure_reason is the single
        # most useful signal — it tells the operator whether to chase a
        # network/auth/quota issue without re-running the whole sweep.
        failure_tail = ""
        if n_succ < n_att and summary.top_failure_reasons:
            top_reason, top_count = next(iter(summary.top_failure_reasons.items()))
            failure_tail = f" — top failure ({top_count}/{n_att - n_succ}): {top_reason}"
        print(
            f"{_stderr_ts()} [{idx}/{total_pairs}] {path} × c={c} / {cohort} "
            f"— {n_succ}/{n_att} succ{failure_tail}",
            file=sys.stderr,
            flush=True,
        )

    run_completed_at = _now_iso_utc()
    elapsed_min = (time.monotonic() - started_mono) / 60.0
    print(
        f"{_stderr_ts()} M6.1.2 {config.sweep_mode} sweep complete in {elapsed_min:.1f} min",
        file=sys.stderr,
        flush=True,
    )

    # FR-016 invariant: cohorts_run ∪ omissions == canonical universe.
    # M6.1.2's default sweep covers all 4 cohorts at c >= 2 (so the universe
    # is naturally covered). Document the c=1 collapse via cohort_omissions.
    intentional_omissions = _compute_omissions(cohorts_actually_run)
    cohort_set, omissions = build_cohort_set_and_omissions(
        cohorts_actually_run, intentional_omissions
    )

    return M6_1_2SweepArtifact(
        schema_version="m6_1_2.v1",
        dispatch_mode="concurrent",
        run_id=run_id,
        run_started_at=run_started_at,
        run_completed_at=run_completed_at,
        run_meta=M6_1_2RunMeta(
            git_sha="",  # populated by the caller from git context if available
            modal_region=config.modal_region,
            base_seed=config.base_seed,
            model_identifier=config.model_identifier,
            sweep_mode=config.sweep_mode,
            seq_len=config.seq_len,
            run_started_at=run_started_at,
            run_completed_at=run_completed_at,
            m6_1_1_baseline_pointer=config.m6_1_1_baseline_pointer,
        ),
        network_paths=network_paths,
        cohort_set=cohort_set,
        cohort_omissions=omissions,
        measurements=measurements,
        classifier_notes=[],
    )


def _compute_omissions(
    cohorts_run: set[M6_1_2CohortKind],
) -> dict[M6_1_2CohortKind, str] | None:
    """Return per-cohort intentional omissions if the run didn't cover the
    canonical 4-cohort universe.

    For M6.1.2's default 6-cell × 4-cohort sweep, all 4 cohorts iterate at
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
    artifact: M6_1_2SweepArtifact,
    md_path: Path,
    json_path: Path,
) -> None:
    """Thin wrapper around :func:`write_m6_1_2_report` for callers that
    want the orchestrator to own artifact emission."""
    write_m6_1_2_report(artifact, md_path, json_path)


def build_config_from_args(
    args: argparse.Namespace, *, sweep_mode: M6_1_2SweepMode
) -> M6_1_2SweepConfig:
    """Build :class:`M6_1_2SweepConfig` from a parsed argparse namespace.

    Reads the ``--m6_1_2-*`` flags defined in ``__main__.py`` per
    ``contracts/cli.md``. ``sweep_mode`` is supplied by the dispatch
    wiring (``"full"`` for ``--m6_1_2``; ``"validate"`` for
    ``--m6_1_2-validate``).
    """
    return M6_1_2SweepConfig(
        sweep_mode=sweep_mode,
        modal_region=str(args.m6_1_2_modal_region),
        base_seed=int(args.m6_1_2_base_seed),
        model_identifier=str(args.m6_1_2_model),
        m6_1_1_baseline_pointer=str(args.m6_1_2_m6_1_1_baseline),
        md_out=Path(str(args.m6_1_2_report_out)),
        json_out=Path(str(args.m6_1_2_report_json_out)),
        skip_deploy=bool(args.m6_1_2_skip_deploy),
    )


__all__ = [
    "M6_1_2RPCDriver",
    "M6_1_2SweepConfig",
    "build_config_from_args",
    "run_m6_1_2_sweep",
    "write_sweep_artifact",
]
