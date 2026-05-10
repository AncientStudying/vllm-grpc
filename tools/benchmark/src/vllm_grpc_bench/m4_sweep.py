"""M4 sweep orchestrator — shared-baseline + per-path frozen-channel + schema.

Sibling to ``m3_sweep`` (per ``research.md`` R-2). M3's module stays runnable
so the bytes report remains reproducible; the M4 entry point lives here and
is invoked from ``__main__.py`` via ``--m4``.

Public surface used by callers and tests:

- :func:`collect_shared_baseline_cohort_ids` — invariant #2 helper.
- :func:`detect_ci_overlap` — borderline-expand trigger (FR-002 / R-4).
- :func:`expand_cohort` — replace-not-append re-measurement (R-4).
- :func:`is_client_bound` — FR-004 / R-5 jitter-floor classifier.
- :func:`flag_noisy_baseline` — FR-005 / R-11 record-and-flag (never aborts).
- :func:`build_recommendations` — TTFT-first-class verdicts (FR-003 / R-10).
- :func:`validate_run` — the seven invariants from ``data-model.md``.
- :func:`run_m4_sweep` — top-level entry point.
"""

from __future__ import annotations

import statistics
import sys
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import replace
from typing import Any

import grpc

from vllm_grpc_bench.channel_config import (
    M1_BASELINE,
    ChannelConfig,
    presets_for_axis,
)
from vllm_grpc_bench.ci import is_winner
from vllm_grpc_bench.m3_sweep import (
    CITATIONS,
    _aggregate,
    _drive_chat_stream_cell,
    _drive_embed_cell,
    serve_in_process,
)
from vllm_grpc_bench.m3_types import (
    BenchmarkCell,
    ExpansionRecord,
    FrozenChannelBaseline,
    M4SweepConfig,
    Path_,
    Recommendation,
    Run,
    RunCohort,
    SchemaCandidatePerWidth,
    SchemaCandidateResult,
)
from vllm_grpc_bench.mock_engine import MockEngine, MockEngineConfig
from vllm_grpc_bench.ttft import ttft_estimate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def collect_shared_baseline_cohort_ids(cohorts: Iterable[RunCohort]) -> dict[str, str]:
    """Map ``path -> cohort_id`` for the M1_BASELINE cohorts (one per path).

    Raises ``ValueError`` if a path has more than one shared-baseline cohort
    (invariant #2).  A path with zero shared baselines is allowed by this
    helper — ``validate_run`` enforces full coverage against the run's
    ``paths`` list.
    """
    by_path: dict[str, list[str]] = {}
    for c in cohorts:
        if c.is_baseline and c.baseline_role == "m1_shared":
            by_path.setdefault(c.cell.path, []).append(c.cell.cell_id)
    out: dict[str, str] = {}
    for path, ids in by_path.items():
        if len(ids) > 1:
            raise ValueError(f"multiple shared-baseline cohorts for path {path!r}: {ids}")
        out[path] = ids[0]
    return out


def detect_ci_overlap(baseline: RunCohort, candidate: RunCohort, *, metric: str = "time") -> bool:
    """``True`` iff candidate CI overlaps baseline CI on ``metric``.

    Uses the symmetric overlap rule from R-4:
    ``cand.ci_low <= base.ci_high AND cand.ci_high >= base.ci_low``.
    """
    base = _metric_ci(baseline, metric)
    cand = _metric_ci(candidate, metric)
    if base is None or cand is None:
        return True
    base_low, base_high = base
    cand_low, cand_high = cand
    return cand_low <= base_high and cand_high >= base_low


async def expand_cohort(
    original: RunCohort,
    *,
    target_n: int,
    remeasure: Callable[[int], Awaitable[RunCohort]],
    reason: str = "ci_overlap",
) -> RunCohort:
    """Re-measure ``original`` at ``target_n`` and replace its samples (R-4).

    The replace-not-append rule is enforced here: the returned cohort's
    ``samples`` is the fresh batch, not the concatenation. Cross-batch
    system-noise variance is therefore confined to a single n=target_n
    measurement.
    """
    fresh = await remeasure(target_n)
    return replace(
        fresh,
        expansion_record=ExpansionRecord(
            initial_n=original.cell.iterations,
            initial_ci_overlapped=True,
            expanded=True,
            final_n=target_n,
            expansion_reason=reason,
        ),
    )


def is_client_bound(baseline: RunCohort, candidate: RunCohort) -> bool:
    """FR-004 / R-5: the candidate's transport contribution is below the
    baseline's own jitter floor.
    """
    baseline_values = [s.wall_clock_seconds for s in baseline.samples if s.error is None]
    if len(baseline_values) < 2:
        return False
    base_mean = statistics.fmean(baseline_values)
    base_stdev = statistics.stdev(baseline_values)
    delta = base_mean - candidate.time_mean
    return abs(delta) < base_stdev


def verdict_metric_cv(cohort: RunCohort) -> tuple[str, float | None]:
    """Return ``(metric_name, cv)`` for the cohort's verdict metric.

    The verdict metric is path-specific (FR-003): chat_stream cohorts are
    judged on TTFT, embed cohorts on total per-RPC wall-clock. The CV value
    reuses the per-cohort fields populated by ``_aggregate`` (``time_cv``)
    and ``_attach_ttft`` (``ttft_cv``); ``None`` means there were too few
    samples to compute it.
    """
    if cohort.cell.path == "chat_stream":
        return "ttft", cohort.ttft_cv
    return "time", cohort.time_cv


def flag_noisy_baseline(
    cohort: RunCohort, *, baseline_cv_warn: float
) -> RunCohort:
    """FR-005 / R-11: tag a baseline cohort whose verdict-metric CV exceeds
    ``baseline_cv_warn``. Never raises — the run always continues; the flag is
    a reader-facing signal in the published report.
    """
    _metric, cv = verdict_metric_cv(cohort)
    if cv is None:
        return cohort
    if cv > baseline_cv_warn:
        return replace(cohort, noisy_baseline=True)
    return cohort


def emit_noisy_baseline_warning(
    cohorts: Iterable[RunCohort], *, baseline_cv_warn: float
) -> list[str]:
    """Print a closing stderr warning for any baseline cohort whose verdict-metric
    CV exceeded ``baseline_cv_warn``. Returns the list of warned cohort ids so
    callers can include them in summaries / tests.
    """
    warned: list[str] = []
    for c in cohorts:
        if not c.is_baseline or not c.noisy_baseline:
            continue
        metric, cv = verdict_metric_cv(c)
        warned.append(c.cell.cell_id)
        print(
            f"WARNING: baseline cohort {c.cell.cell_id!r} CV({metric})="
            f"{cv:.4f} exceeds --baseline-cv-warn={baseline_cv_warn:.4f}; "
            "verdicts derived from this baseline carry extra uncertainty (FR-005).",
            file=sys.stderr,
        )
    return warned


def _metric_ci(cohort: RunCohort, metric: str) -> tuple[float, float] | None:
    if metric == "time":
        return cohort.time_ci_low, cohort.time_ci_high
    if metric == "ttft":
        if cohort.time_to_first_token_seconds is None:
            est = ttft_estimate(cohort)
            if est is None:
                return None
            _mean, low, high, _n = est
            return low, high
        _mean, low, high = cohort.time_to_first_token_seconds
        return low, high
    if metric == "bytes":
        return cohort.bytes_ci_low, cohort.bytes_ci_high
    raise ValueError(f"unknown metric {metric!r}")


def _metric_estimate(cohort: RunCohort, metric: str) -> tuple[float, float, float] | None:
    if metric == "time":
        return cohort.time_mean, cohort.time_ci_low, cohort.time_ci_high
    if metric == "ttft":
        if cohort.time_to_first_token_seconds is not None:
            mean, low, high = cohort.time_to_first_token_seconds
            return mean, low, high
        est = ttft_estimate(cohort)
        if est is None:
            return None
        mean, low, high, _n = est
        return mean, low, high
    if metric == "bytes":
        return cohort.bytes_mean, cohort.bytes_ci_low, cohort.bytes_ci_high
    raise ValueError(f"unknown metric {metric!r}")


# ---------------------------------------------------------------------------
# Recommendation builder (FR-003 / FR-008 / R-10)
# ---------------------------------------------------------------------------


def build_recommendations(
    cohorts: list[RunCohort],
    *,
    shared_baselines: dict[str, RunCohort],
) -> list[Recommendation]:
    """Apply FR-008 strict-CI-clearance against the per-path shared baseline.

    chat_stream cohorts use TTFT (FR-003 / R-10) as the primary verdict
    metric; embed cohorts use total per-RPC wall-clock. ``client_bound``
    cohorts are excluded from ``recommend`` tallies.
    """
    recs: list[Recommendation] = []
    for cohort in cohorts:
        if cohort.is_baseline:
            continue
        path = cohort.cell.path
        baseline = shared_baselines.get(path)
        if baseline is None:
            continue
        metric = "ttft" if path == "chat_stream" else "time"
        axis = cohort.cell.channel_config.axis
        if axis not in CITATIONS:
            continue
        citation = CITATIONS[axis]
        width = cohort.cell.hidden_size
        applies = frozenset({width})

        if cohort.client_bound:
            recs.append(
                Recommendation(
                    axis=axis,
                    applies_to_path=path,
                    applies_to_widths=applies,
                    verdict="client_bound",
                    baseline_ci_upper=0.0,
                    citation=citation,
                    notes=(
                        f"{cohort.cell.cell_id}: candidate delta below baseline jitter floor; "
                        "excluded from recommend tallies (FR-004 / R-5)"
                    ),
                    corpus_subset=cohort.cell.corpus_subset,
                )
            )
            continue

        cand_est = _metric_estimate(cohort, metric)
        base_est = _metric_estimate(baseline, metric)
        if cand_est is None or base_est is None:
            recs.append(
                Recommendation(
                    axis=axis,
                    applies_to_path=path,
                    applies_to_widths=applies,
                    verdict="not_measurable",
                    baseline_ci_upper=0.0,
                    citation=citation,
                    notes=f"insufficient {metric} data for {cohort.cell.cell_id}",
                    corpus_subset=cohort.cell.corpus_subset,
                )
            )
            continue
        cand_mean, cand_low, cand_high = cand_est
        base_mean, base_low, base_high = base_est

        # Minimizing metric: candidate wins iff cand_high < base_low.
        if is_winner(baseline_ci_high=-base_low, candidate_ci_low=-cand_high):
            delta_pct = ((cand_mean - base_mean) / base_mean * 100.0) if base_mean else 0.0
            recs.append(
                Recommendation(
                    axis=axis,
                    applies_to_path=path,
                    applies_to_widths=applies,
                    verdict="recommend",
                    winning_config=cohort.cell.channel_config,
                    winning_delta_pct=delta_pct,
                    winning_metric="ttft" if metric == "ttft" else "time",
                    baseline_ci_upper=-base_low,
                    candidate_ci_lower=-cand_high,
                    citation=citation,
                    notes=(
                        f"{metric}: baseline_mean={base_mean:.4g}, "
                        f"candidate_mean={cand_mean:.4g}, "
                        f"baseline_ci=[{base_low:.4g},{base_high:.4g}], "
                        f"candidate_ci_high={cand_high:.4g}"
                    ),
                    corpus_subset=cohort.cell.corpus_subset,
                )
            )
            continue

        # Otherwise no_winner — overlapping CIs even after expansion.
        recs.append(
            Recommendation(
                axis=axis,
                applies_to_path=path,
                applies_to_widths=applies,
                verdict="no_winner",
                baseline_ci_upper=base_high,
                citation=citation,
                notes=(
                    f"{metric}: candidate CI overlaps baseline CI; "
                    f"baseline_ci=[{base_low:.4g},{base_high:.4g}], "
                    f"candidate_ci=[{cand_low:.4g},{cand_high:.4g}]"
                ),
                corpus_subset=cohort.cell.corpus_subset,
            )
        )
    return recs


# ---------------------------------------------------------------------------
# Validation (T031 — invariants from data-model.md)
# ---------------------------------------------------------------------------


def validate_run(
    run: Run,
    *,
    m3_noise_bounded_cells: list[dict[str, Any]] | None = None,
) -> None:
    """Enforce the seven validation invariants. Raises ``ValueError`` on first
    violation (mapped to exit code 4 by ``__main__``).
    """
    # Invariant 1 — no noise_bounded recommendations in M4.
    for rec in run.recommendations:
        if rec.verdict == "noise_bounded":
            raise ValueError(
                f"M4 run emitted a noise_bounded recommendation for "
                f"{rec.axis}/{rec.applies_to_path}/{sorted(rec.applies_to_widths)}; "
                "FR-007 forbids this verdict in M4 reports."
            )

    # Invariant 2 — shared baseline coverage.
    if run.shared_baseline_cohort_ids is None:
        raise ValueError("M4 run missing shared baseline cohort ids")
    missing = [p for p in run.paths if p not in run.shared_baseline_cohort_ids]
    if missing:
        raise ValueError(f"shared baseline coverage incomplete; missing paths: {missing}")
    cohort_ids = {c.cell.cell_id for c in run.cohorts}
    for path, cohort_id in run.shared_baseline_cohort_ids.items():
        if cohort_id not in cohort_ids:
            raise ValueError(
                f"shared baseline cohort id {cohort_id!r} for path {path!r} "
                "not present in run.cohorts"
            )
        cohort = next(c for c in run.cohorts if c.cell.cell_id == cohort_id)
        if not cohort.is_baseline or cohort.baseline_role != "m1_shared":
            raise ValueError(
                f"shared baseline cohort {cohort_id!r} does not have "
                "is_baseline=True / baseline_role='m1_shared'"
            )

    # Invariant 3 — frozen baseline coverage (US3 only).
    if run.frozen_channel_baselines is not None:
        missing_frozen = [p for p in run.paths if p not in run.frozen_channel_baselines]
        if missing_frozen:
            raise ValueError(
                f"frozen baseline coverage incomplete; missing paths: {missing_frozen}"
            )
        for path, fb in run.frozen_channel_baselines.items():
            if fb.cohort_id not in cohort_ids:
                raise ValueError(
                    f"frozen baseline cohort id {fb.cohort_id!r} for path {path!r} "
                    "not present in run.cohorts"
                )
            cohort = next(c for c in run.cohorts if c.cell.cell_id == fb.cohort_id)
            if not cohort.is_baseline or cohort.baseline_role != "frozen_channel":
                raise ValueError(
                    f"frozen baseline cohort {fb.cohort_id!r} does not have "
                    "is_baseline=True / baseline_role='frozen_channel'"
                )

    # Invariant 4 — every non-baseline cohort has an expansion_record.
    for c in run.cohorts:
        if not c.is_baseline and c.expansion_record is None:
            raise ValueError(
                f"cohort {c.cell.cell_id!r} missing expansion_record "
                "(non-baseline cohorts must record the borderline-expand decision)"
            )

    # Invariant 5 — TTFT presence on measurable chat_stream cohorts.
    for c in run.cohorts:
        if c.cell.path == "chat_stream" and c.measurable and c.time_to_first_token_seconds is None:
            raise ValueError(
                f"chat_stream cohort {c.cell.cell_id!r} measurable=True but "
                "time_to_first_token_seconds is None (FR-003)"
            )

    # Invariant 6 — loopback caveat consistency.
    if run.loopback_caveat_axes is not None:
        axes_set = set(run.axes)
        bad = [a for a in run.loopback_caveat_axes if a not in axes_set]
        if bad:
            raise ValueError(f"loopback_caveat_axes {bad} are not in run.axes {sorted(axes_set)}")

    # Invariant 7 — supersession completeness.
    if m3_noise_bounded_cells:
        covered = {entry.m3_cell_id for entry in run.supersedes}
        missing_super = [
            cell["cell_id"]
            for cell in m3_noise_bounded_cells
            if cell.get("verdict") == "noise_bounded" and cell["cell_id"] not in covered
        ]
        if missing_super:
            raise ValueError(
                f"supersession entries missing for M3 noise_bounded cells: {missing_super}"
            )


# ---------------------------------------------------------------------------
# Cohort drivers (called by the sweep orchestrator)
# ---------------------------------------------------------------------------


def _engine_config(
    *,
    hidden_size: int,
    pace_tokens: bool,
    long_stream: bool,
    seed: int,
) -> MockEngineConfig:
    return MockEngineConfig(
        hidden_size=hidden_size,
        seed=seed,
        tokens_per_second=200.0 if not long_stream else 20.0,
        max_tokens_per_stream=2048 if long_stream else 64,
        pace_tokens=pace_tokens,
    )


async def _measure_cell(
    cell: BenchmarkCell,
    *,
    seed: int,
    pace_tokens: bool,
    warmup_n: int = 0,
) -> RunCohort:
    """Measure ``cell.iterations`` RPCs after ``warmup_n`` discarded warmup RPCs.

    The warmup RPCs reuse the same server + channel as the measurement, so
    cold-start cost (channel establishment, first-RPC HTTP/2 negotiation,
    protobuf descriptor caches, asyncio event-loop priming) is paid before
    the first measured sample. Without this, the first ~5–10 RPCs against
    a fresh process can dominate within-cohort variance and inflate the
    per-cohort CV that FR-005 records and surfaces to the report reader.

    The returned cohort has exactly ``cell.iterations`` samples; the
    discarded warmup samples are not visible to ``_aggregate`` and never
    surface in the published JSON.
    """
    long_stream = cell.corpus_subset == "m3_long_stream"
    engine_cfg = _engine_config(
        hidden_size=cell.hidden_size,
        pace_tokens=pace_tokens,
        long_stream=long_stream,
        seed=seed,
    )
    engine = MockEngine(engine_cfg)
    drive_cell = (
        replace(cell, iterations=cell.iterations + warmup_n) if warmup_n > 0 else cell
    )
    async with serve_in_process(engine, drive_cell.channel_config) as addr:
        if drive_cell.path == "embed":
            samples = await _drive_embed_cell(addr, drive_cell, seed)
        else:
            samples = await _drive_chat_stream_cell(
                addr, drive_cell, seed, long_stream=long_stream
            )
    measured = list(samples[warmup_n:]) if warmup_n > 0 else list(samples)
    cohort = _aggregate(cell, measured)
    return _attach_ttft(cohort)


def _attach_ttft(cohort: RunCohort) -> RunCohort:
    if cohort.cell.path != "chat_stream":
        return cohort
    from vllm_grpc_bench.m3_sweep import _coefficient_of_variation
    from vllm_grpc_bench.ttft import ttft_samples

    ttfts = ttft_samples(cohort)
    ttft_cv = _coefficient_of_variation(ttfts)
    if not cohort.measurable:
        return replace(cohort, ttft_cv=ttft_cv)
    est = ttft_estimate(cohort)
    if est is None:
        return replace(cohort, ttft_cv=ttft_cv)
    mean, low, high, _n = est
    return replace(
        cohort, time_to_first_token_seconds=(mean, low, high), ttft_cv=ttft_cv
    )


# ---------------------------------------------------------------------------
# Top-level orchestrator (T016)
# ---------------------------------------------------------------------------


async def measure_shared_baseline(
    *,
    path: Path_,
    hidden_size: int,
    seed: int,
    config: M4SweepConfig,
) -> RunCohort:
    """Measure a single shared M1_BASELINE cohort at ``hidden_size``."""
    corpus = "m1_embed" if path == "embed" else "m1_chat"
    cell = BenchmarkCell(
        path=path,
        hidden_size=hidden_size,
        channel_config=M1_BASELINE,
        corpus_subset=corpus,  # type: ignore[arg-type]
        iterations=config.baseline_n,
    )
    cohort = await _measure_cell(
        cell,
        seed=seed,
        pace_tokens=(config.pacing_mode == "paced"),
        warmup_n=config.warmup_n,
    )
    return replace(
        cohort,
        is_baseline=True,
        baseline_role="m1_shared",
        expansion_record=None,
    )


async def measure_candidate(
    *,
    cell: BenchmarkCell,
    baseline: RunCohort,
    seed: int,
    config: M4SweepConfig,
) -> RunCohort:
    """Measure one candidate cell with the borderline-expand cascade."""
    cohort = await _measure_cell(
        cell,
        seed=seed,
        pace_tokens=(config.pacing_mode == "paced"),
        warmup_n=config.warmup_n,
    )
    metric = "ttft" if cell.path == "chat_stream" else "time"
    overlapped = detect_ci_overlap(baseline, cohort, metric=metric)
    if overlapped and cohort.measurable:

        async def _remeasure(target_n: int) -> RunCohort:
            new_cell = replace(cell, iterations=target_n)
            return await _measure_cell(
                new_cell,
                seed=seed + 1,
                pace_tokens=(config.pacing_mode == "paced"),
                warmup_n=config.warmup_n,
            )

        cohort = await expand_cohort(
            cohort, target_n=config.expand_n, remeasure=_remeasure, reason="ci_overlap"
        )
    else:
        cohort = replace(
            cohort,
            expansion_record=ExpansionRecord(
                initial_n=cell.iterations,
                initial_ci_overlapped=False,
                expanded=False,
                final_n=cell.iterations,
            ),
        )

    if is_client_bound(baseline, cohort):
        cohort = replace(cohort, client_bound=True)
    return cohort


def _candidate_cells(
    *,
    axes: tuple[str, ...],
    widths: tuple[int, ...],
    paths: tuple[Path_, ...],
    iterations: int,
) -> list[BenchmarkCell]:
    """Plan the cartesian product of channel-axis candidate cells."""
    cells: list[BenchmarkCell] = []
    for axis in axes:
        configs = [
            c
            for c in presets_for_axis(axis)  # type: ignore[arg-type]
            if c.name != M1_BASELINE.name
        ]
        for cfg in configs:
            for w in widths:
                for path in paths:
                    corpus = "m1_embed" if path == "embed" else "m1_chat"
                    cells.append(
                        BenchmarkCell(
                            path=path,
                            hidden_size=w,
                            channel_config=cfg,
                            corpus_subset=corpus,  # type: ignore[arg-type]
                            iterations=iterations,
                        )
                    )
    return cells


async def run_m4_sweep(
    config: M4SweepConfig,
    *,
    progress: bool = True,
    is_loopback: bool = True,
) -> Run:
    """Run the full M4 sweep and return the populated ``Run`` record.

    The full schema-candidate flow (US3) is gated behind ``not skip_schema``
    and lives downstream of the channel sweep so US1+US2 can run in
    isolation when ``--skip-schema`` is set.
    """
    cohorts: list[RunCohort] = []
    shared_baselines: dict[str, RunCohort] = {}

    # Shared baseline measurement at the schema-canonical width — used as the
    # comparison point for every candidate cohort across all widths.
    for path in config.paths:
        baseline = await measure_shared_baseline(
            path=path,
            hidden_size=config.schema_canonical_width,
            seed=config.seed,
            config=config,
        )
        baseline = flag_noisy_baseline(
            baseline, baseline_cv_warn=config.baseline_cv_warn
        )
        cohorts.append(baseline)
        shared_baselines[path] = baseline
        if progress:
            metric, cv = verdict_metric_cv(baseline)
            cv_str = f"{cv:.4f}" if cv is not None else "n/a"
            noise_tag = " noisy_baseline=True" if baseline.noisy_baseline else ""
            print(
                f"[baseline] path={path} cohort={baseline.cell.cell_id} "
                f"n={baseline.n_successful} CV({metric})={cv_str}{noise_tag}",
                flush=True,
            )

    cells = _candidate_cells(
        axes=config.axes,
        widths=config.widths,
        paths=config.paths,
        iterations=config.candidate_n,
    )
    for idx, cell in enumerate(cells):
        baseline = shared_baselines[cell.path]
        cohort = await measure_candidate(
            cell=cell,
            baseline=baseline,
            seed=config.seed + (idx + 1) * 1000,
            config=config,
        )
        cohorts.append(cohort)
        if progress:
            print(
                f"[{idx + 1}/{len(cells)}] cell={cell.cell_id} "
                f"verdict={'client_bound' if cohort.client_bound else 'measured'}",
                flush=True,
            )

    # Per-path frozen-channel baselines (US2 / T029) — composed from the
    # per-axis winners. Implementation deferred to ``compose_frozen_baselines``
    # so US1 can ship without US2's full dependency on this step.
    frozen_baselines: dict[str, FrozenChannelBaseline] | None = None
    if not config.skip_schema:
        frozen_baselines, frozen_cohorts = await compose_frozen_baselines(
            shared_baselines=shared_baselines,
            sweep_cohorts=cohorts,
            config=config,
            seed=config.seed + 999_000,
        )
        cohorts.extend(frozen_cohorts)

    schema_results: list[SchemaCandidateResult] = []
    if not config.skip_schema:
        schema_results, schema_cohorts = await measure_schema_candidates(
            frozen_baselines=frozen_baselines or {},
            config=config,
            seed=config.seed + 999_900,
        )
        cohorts.extend(schema_cohorts)

    loopback_axes = sorted(set(config.axes) & config.loopback_caveat_axes) if is_loopback else []

    run = Run(
        mode="m4-time-axis-tuning",
        axes=list(config.axes),
        widths=list(config.widths),
        paths=list(config.paths),
        iterations_per_cell=config.candidate_n,
        seed=config.seed,
        cohorts=cohorts,
        pacing_mode=config.pacing_mode,
        shared_baseline_cohort_ids={
            path: shared_baselines[path].cell.cell_id for path in config.paths
        },
        frozen_channel_baselines=frozen_baselines,
        candidate_sizing_policy={
            "default_n": config.candidate_n,
            "expand_n": config.expand_n,
            "expand_rule": "ci_overlap",
        },
        loopback_caveat_axes=loopback_axes,
        schema_candidate_results=schema_results,
    )
    run.recommendations.extend(build_recommendations(cohorts, shared_baselines=shared_baselines))
    run.supersedes.extend(_build_supersedes_for_run(run))
    emit_noisy_baseline_warning(cohorts, baseline_cv_warn=config.baseline_cv_warn)
    return run


# Default location of M3's published time report. Used by the supersession
# step so an M4 sweep automatically populates the FR-007 "Supersedes M3" table
# without requiring a CLI flag.
M3_TIME_REPORT_PATH = "docs/benchmarks/m3-channel-tuning-time.json"


def _build_supersedes_for_run(run: Run) -> list[Any]:
    """Build SupersessionEntry list for ``run`` against the M3 time report.

    Builds M4 cell descriptors from each candidate cohort (skipping baselines)
    paired with its recommendation verdict, then delegates to
    :func:`vllm_grpc_bench.m4_supersede.build_supersession_entries`. Returns an
    empty list when the M3 report is absent (fresh runs before M3 is committed).
    """
    from vllm_grpc_bench.m4_supersede import build_supersession_entries

    # Verdict lookup: (axis, path, hidden_size) -> verdict literal.
    # build_recommendations emits one Recommendation per (axis, path, width),
    # so this key is unique within a run.
    verdict_by_apw: dict[tuple[str, str, int], str] = {}
    for rec in run.recommendations:
        for w in rec.applies_to_widths:
            verdict_by_apw[(rec.axis, rec.applies_to_path, int(w))] = rec.verdict

    m4_cells: list[dict[str, Any]] = []
    for c in run.cohorts:
        if c.is_baseline:
            continue
        axis = c.cell.channel_config.axis
        path = c.cell.path
        width = c.cell.hidden_size
        verdict = verdict_by_apw.get((axis, path, width), "no_winner")
        m4_cells.append(
            {
                "cell_id": c.cell.cell_id,
                "path": path,
                "hidden_size": width,
                "config_axis": axis,
                "config_name": c.cell.channel_config.name,
                "verdict": verdict,
            }
        )

    return build_supersession_entries(
        M3_TIME_REPORT_PATH, m4_cells, m4_pacing_mode=run.pacing_mode or "no_pacing"
    )


# ---------------------------------------------------------------------------
# US2 — per-path frozen-channel baseline composition (T029)
# ---------------------------------------------------------------------------


async def compose_frozen_baselines(
    *,
    shared_baselines: dict[str, RunCohort],
    sweep_cohorts: list[RunCohort],
    config: M4SweepConfig,
    seed: int,
) -> tuple[dict[str, FrozenChannelBaseline], list[RunCohort]]:
    """Build a per-path frozen-channel baseline at ``schema_canonical_width``.

    For each path, walk the channel-axis candidates and pick the per-axis
    winner via ``build_recommendations``. Where a path has no winner on a
    given axis, the frozen baseline keeps that axis at the M3 default. The
    composed config is then measured as its own cohort tagged
    ``baseline_role="frozen_channel"``.
    """
    recs = build_recommendations(sweep_cohorts, shared_baselines=shared_baselines)
    winners_by_path_axis: dict[str, dict[str, str]] = {p: {} for p in config.paths}
    for rec in recs:
        if rec.verdict != "recommend" or rec.winning_config is None:
            continue
        path = rec.applies_to_path
        if path == "both":
            continue
        if rec.applies_to_widths and config.schema_canonical_width not in rec.applies_to_widths:
            continue
        winners_by_path_axis.setdefault(path, {})[rec.axis] = rec.winning_config.name

    frozen_baselines: dict[str, FrozenChannelBaseline] = {}
    frozen_cohorts: list[RunCohort] = []
    for path in config.paths:
        per_axis = winners_by_path_axis.get(path, {})
        # M3 defaults for axes with no winner.
        for axis in config.axes:
            per_axis.setdefault(axis, "m1-default")
        # Build a composed ChannelConfig by union of the winning configs'
        # options. (M1_BASELINE has empty options; "m1-default" carries no
        # extra options, so unioning skipped axes with empty tuples is a no-op.)
        # ChannelConfig.name is kebab-case-only — translate `chat_stream` etc.
        path_token = path.replace("_", "-")
        composed = _compose_channel_config(
            name=f"frozen-{path_token}-h{config.schema_canonical_width}",
            per_axis_winners=per_axis,
        )
        corpus = "m1_embed" if path == "embed" else "m1_chat"
        cell = BenchmarkCell(
            path=path,
            hidden_size=config.schema_canonical_width,
            channel_config=composed,
            corpus_subset=corpus,  # type: ignore[arg-type]
            iterations=config.baseline_n,
        )
        cohort = await _measure_cell(
            cell,
            seed=seed,
            pace_tokens=(config.pacing_mode == "paced"),
            warmup_n=config.warmup_n,
        )
        cohort = replace(
            cohort,
            is_baseline=True,
            baseline_role="frozen_channel",
            expansion_record=None,
        )
        cohort = flag_noisy_baseline(cohort, baseline_cv_warn=config.baseline_cv_warn)
        frozen_cohorts.append(cohort)
        frozen_baselines[path] = FrozenChannelBaseline(
            path=path,
            cohort_id=cohort.cell.cell_id,
            channel_config_name=composed.name,
            per_axis_winners=dict(per_axis),
            measured_at_hidden_size=config.schema_canonical_width,
        )
    return frozen_baselines, frozen_cohorts


def _compose_channel_config(*, name: str, per_axis_winners: dict[str, str]) -> ChannelConfig:
    """Merge per-axis winning configs into one ``ChannelConfig`` (R-3)."""
    from vllm_grpc_bench.channel_config import preset_by_name

    server_options: list[Any] = []
    client_options: list[Any] = []
    compression = grpc.Compression.NoCompression
    for _axis, cfg_name in per_axis_winners.items():
        if cfg_name in ("m1-default", M1_BASELINE.name):
            continue
        try:
            cfg = preset_by_name(cfg_name)
        except KeyError:
            continue
        server_options.extend(cfg.server_options)
        client_options.extend(cfg.client_options)
        if cfg.compression is not grpc.Compression.NoCompression:
            compression = cfg.compression
    return ChannelConfig(
        name=name,
        axis="baseline",
        server_options=tuple(server_options),
        client_options=tuple(client_options),
        compression=compression,
        description=f"M4 frozen-channel composition: {sorted(per_axis_winners.items())}",
    )


# ---------------------------------------------------------------------------
# US3 — schema candidate measurement (T045)
# ---------------------------------------------------------------------------


def schema_widths_to_measure(
    *,
    primary_verdict_at_canonical: str,
    canonical_width: int,
    full_widths: tuple[int, ...],
) -> list[int]:
    """FR-013 cascade: 4096 first; cascade to 2048+8192 only on positive signal.

    ``primary_verdict_at_canonical`` is one of ``recommend``, ``borderline``
    (CIs touch even after expansion), ``no_winner``, ``not_measurable``,
    ``client_bound``. The cascade fires for the first two; otherwise the
    candidate is measured only at the canonical width.
    """
    if primary_verdict_at_canonical in ("recommend", "borderline"):
        return sorted(set(full_widths))
    return [canonical_width]


def resolve_schema_baseline(
    *,
    path: str,
    frozen_baselines: dict[str, str],
    shared_baselines: dict[str, str],
) -> str | None:
    """FR-011: pair each schema candidate with the per-path frozen baseline.

    Falls back to the shared M1_BASELINE for the path when the frozen
    baseline is unavailable; the caller is expected to record the fallback
    in ``SchemaCandidateResult.notes``.
    """
    if path in frozen_baselines:
        return frozen_baselines[path]
    return shared_baselines.get(path)


def classify_schema_result(
    *,
    candidate_name: str,
    proto_file: str,
    per_widths: list[SchemaCandidatePerWidth],
    notes: str | None = None,
) -> SchemaCandidateResult:
    """FR-014: a candidate is negative iff bytes and time are both
    ``no_winner`` at every measured width.
    """
    is_negative = bool(per_widths) and all(
        pw.bytes_verdict == "no_winner" and pw.time_verdict == "no_winner" for pw in per_widths
    )
    return SchemaCandidateResult(
        candidate_name=candidate_name,
        proto_file=proto_file,
        measured_widths=[pw.hidden_size for pw in per_widths],
        per_width=per_widths,
        is_negative_result=is_negative,
        notes=notes,
    )


async def measure_schema_candidates(
    *,
    frozen_baselines: dict[str, FrozenChannelBaseline],
    config: M4SweepConfig,
    seed: int,
) -> tuple[list[SchemaCandidateResult], list[RunCohort]]:
    """Author the schema-candidate result records (T045).

    The full proto-stub-driven byte/time measurement requires importing the
    generated candidate stubs and serializing messages through them. The
    candidate-cohort cells live alongside the channel cohorts in
    ``Run.cohorts`` (config_axis prefix ``schema:``); the per-candidate
    aggregate lives in ``Run.schema_candidate_results`` and is produced
    here.

    For now, when the candidate stubs cannot be imported (clean checkout
    without ``make proto`` yet), each candidate is written with an empty
    ``per_width`` list and a diagnostic note — the sweep does not silently
    drop it.
    """
    results: list[SchemaCandidateResult] = []
    cohorts: list[RunCohort] = []
    candidate_module_paths = {
        "packed_token_ids": "vllm_grpc.v1.m4_candidates.packed_token_ids_pb2",
        "oneof_flattened_input": "vllm_grpc.v1.m4_candidates.oneof_flattened_input_pb2",
        "chunk_granularity": "vllm_grpc.v1.m4_candidates.chunk_granularity_pb2",
    }
    for candidate_name in config.schema_candidates:
        proto_file = f"proto/vllm_grpc/v1/m4-candidates/{candidate_name}.proto"
        module_path = candidate_module_paths.get(candidate_name)
        notes: str | None = None
        if module_path is not None:
            try:
                __import__(module_path)
            except ImportError:
                notes = (
                    f"Candidate stub {module_path!r} not importable — "
                    "run `make proto` before measuring."
                )
        else:
            notes = f"Unknown candidate {candidate_name!r}; skipped."

        # Empty per_widths until the harness measures them — the contract
        # field is still emitted so the JSON shape is uniform.
        results.append(
            classify_schema_result(
                candidate_name=candidate_name,
                proto_file=proto_file,
                per_widths=[],
                notes=notes,
            )
        )
    return results, cohorts
