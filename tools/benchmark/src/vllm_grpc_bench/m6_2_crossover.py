"""M6.2 — Protocol-crossover threshold + KV-pressure inference (US2 + US3).

Two pure-function families:

- :func:`compute_per_cell_crossover` (US2 / FR-016 / spec round-1 Q3) — for
  each cell, walk the ``max_tokens`` axis ascending and detect the FIRST
  axis point where the symmetric mean-in-CI rule fires. The rule fires when
  EITHER the M6.1.3-winning cohort's M6.2 mean lies inside the M6.1.3-second
  cohort's CI, OR vice versa, at the same axis point. The first axis point
  where this happens is the cell's ``crossover_max_tokens``.

- :func:`compute_kv_pressure_inference` (US3 / FR-017a + spec round-3 Q3 +
  round-5 amendment) — for each ``(cohort, cell_type)``, compute the
  wall-clock-ratio ``R = wall_p50_ms(2048) / wall_p50_ms(1024)`` from the
  KV-pressure SUB-PROBE rows (NOT main-sweep budget-table c=8 rows). Threshold
  pinned at 2.2 per spec round-3 Q3 — above 2.2 → ``kv_pressure_inferred_<cell_type>``;
  at or below → ``kv_pressure_not_observable``. Best-effort engine-field
  capture + OOM-observed flag rendered alongside.

Both functions are unit-testable in isolation (``test_m6_2_crossover.py`` +
``test_m6_2_kv_pressure.py``). The orchestrator calls them after the main
sweep + sub-probe complete and feeds the results into the artifact.
"""

from __future__ import annotations

from dataclasses import dataclass

from vllm_grpc_bench.m6_1_2_types import M6_1_2_COHORTS, M6_1_2CohortKind
from vllm_grpc_bench.sweep_types import (
    M6_2_KV_PRESSURE_THRESHOLD,
    M6_2_MAX_TOKENS_AXIS,
    M6_2_SUB_PROBE_N,
    M6_2_VALIDATE_MAX_TOKENS_AXIS,
    M6_2CrossoverThreshold,
    M6_2KVPressureObservation,
    M6_2MeasurementPoint,
    M6_2SweepMode,
)

__all__ = [
    "INCONCLUSIVE_VERDICT_LABELS",
    "M6_1_3CohortBaseline",
    "SubProbeBlockResult",
    "compute_kv_pressure_inference",
    "compute_per_cell_crossover",
    "identify_winner_and_second",
    "symmetric_mean_in_ci",
]


# --- Constants --------------------------------------------------------------

INCONCLUSIVE_VERDICT_LABELS: frozenset[str] = frozenset(
    {
        "inconclusive",
    }
)
"""Base verdict labels that mean attribution was inconclusive in M6.1.3.

Used by :func:`compute_per_cell_crossover` to short-circuit on cells whose
M6.1.3 base verdict was inconclusive — no winner / second cohort can be
identified, so crossover detection is undefined per US2 #2. The outer
``inconclusive_high_variance(...)`` wrapper also matches via the
``label.startswith`` check (see :func:`_is_inconclusive_verdict`)."""


# --- Crossover compute (US2 / FR-016 / spec round-1 Q3) --------------------


@dataclass(frozen=True, slots=True)
class M6_1_3CohortBaseline:
    """One ``(cell, cohort)`` baseline measurement read from the M6.1.3
    artifact. ``wall_p50_ms`` is the published cohort mean (M6.1.3 doesn't
    publish per-cohort p50; the mean is the closest available proxy);
    ``wall_p50_ms_ci_half_width`` is the inferred CI half-width."""

    wall_p50_ms: float
    wall_p50_ms_ci_half_width: float


def _is_inconclusive_verdict(verdict: str) -> bool:
    """Match both ``"inconclusive"`` and ``"inconclusive_high_variance(...)"``
    forms — M6.1.3's classifier wraps an inner attribution in the outer
    high-variance label when between-run variance dominates."""
    if verdict in INCONCLUSIVE_VERDICT_LABELS:
        return True
    return verdict.startswith("inconclusive")


def identify_winner_and_second(
    cell_id: str,
    baseline: dict[M6_1_2CohortKind, M6_1_3CohortBaseline],
) -> tuple[M6_1_2CohortKind, M6_1_2CohortKind] | None:
    """Find the M6.1.3 winner + second cohort by ascending ``wall_p50_ms``.

    Returns ``None`` when the baseline has fewer than 2 cohorts (insufficient
    data for crossover detection). Ties on the floor are broken alphabetically
    by cohort name for determinism.
    """
    del cell_id  # reserved for future per-cell overrides
    if len(baseline) < 2:
        return None
    ordered = sorted(baseline.items(), key=lambda kv: (kv[1].wall_p50_ms, kv[0]))
    return ordered[0][0], ordered[1][0]


def symmetric_mean_in_ci(
    a: M6_2MeasurementPoint,
    b: M6_2MeasurementPoint,
) -> bool:
    """Spec round-1 Q3 symmetric rule: ``True`` iff EITHER ``a``'s p50 lies
    inside ``b``'s CI band OR ``b``'s p50 lies inside ``a``'s CI band.

    A block failure on either side (``wall_p50_ms is None`` or missing CI)
    yields ``False`` — crossover detection is undefined in that case.
    """
    if a.wall_p50_ms is None or b.wall_p50_ms is None:
        return False
    if a.wall_p50_ms_ci_half_width is None or b.wall_p50_ms_ci_half_width is None:
        return False
    a_lo = a.wall_p50_ms - a.wall_p50_ms_ci_half_width
    a_hi = a.wall_p50_ms + a.wall_p50_ms_ci_half_width
    b_lo = b.wall_p50_ms - b.wall_p50_ms_ci_half_width
    b_hi = b.wall_p50_ms + b.wall_p50_ms_ci_half_width
    return (b_lo <= a.wall_p50_ms <= b_hi) or (a_lo <= b.wall_p50_ms <= a_hi)


def compute_per_cell_crossover(
    per_cell_axis_rows: dict[str, dict[M6_1_2CohortKind, dict[int, M6_2MeasurementPoint]]],
    m6_1_3_baseline: dict[str, dict[M6_1_2CohortKind, M6_1_3CohortBaseline]],
    m6_1_3_base_verdicts: dict[str, str],
    *,
    sweep_mode: M6_2SweepMode,
) -> list[M6_2CrossoverThreshold]:
    """Per spec round-1 Q3 + round-5 contract.

    For each cell in ``m6_1_3_base_verdicts``:

    - If the base verdict is inconclusive (or wrapped in
      ``inconclusive_high_variance``): emit a record with
      ``crossover_max_tokens=None`` and the canonical evidence string from
      US2 #2.
    - Otherwise: identify winner + second from the M6.1.3 baseline; walk the
      axis ascending; emit the first axis point where the symmetric mean-in-CI
      rule fires. If the rule fires at the FIRST axis point (e.g. 10), emit
      the US2 #3 "M6.1.3 verdict not robust to M6.2 resampling" evidence. If
      the rule never fires across the axis: emit ``crossover_max_tokens=None``
      with "verdict survives across the axis" evidence.

    Validate mode iterates the 3-point axis subset ``{10, 50, 2048}``; the
    coarse 4-value vocabulary follows naturally from the axis itself.
    """
    axis = M6_2_VALIDATE_MAX_TOKENS_AXIS if sweep_mode == "validate" else M6_2_MAX_TOKENS_AXIS
    first_axis = axis[0]
    out: list[M6_2CrossoverThreshold] = []

    for cell_id, base_verdict in m6_1_3_base_verdicts.items():
        if _is_inconclusive_verdict(base_verdict):
            out.append(
                M6_2CrossoverThreshold(
                    cell_id=cell_id,
                    m6_1_3_winner_cohort=None,
                    m6_1_3_second_cohort=None,
                    crossover_max_tokens=None,
                    crossover_evidence=(
                        "base verdict was already inconclusive at the M6.1.3 baseline"
                    ),
                    m6_1_3_base_verdict=base_verdict,
                )
            )
            continue

        baseline = m6_1_3_baseline.get(cell_id, {})
        winner_second = identify_winner_and_second(cell_id, baseline)
        if winner_second is None:
            out.append(
                M6_2CrossoverThreshold(
                    cell_id=cell_id,
                    m6_1_3_winner_cohort=None,
                    m6_1_3_second_cohort=None,
                    crossover_max_tokens=None,
                    crossover_evidence=(
                        "M6.1.3 baseline did not publish ≥ 2 cohorts for this cell"
                    ),
                    m6_1_3_base_verdict=base_verdict,
                )
            )
            continue
        winner, second = winner_second

        per_cohort = per_cell_axis_rows.get(cell_id, {})
        winner_rows = per_cohort.get(winner, {})
        second_rows = per_cohort.get(second, {})

        found_crossover = False
        for max_tokens in axis:
            winner_row = winner_rows.get(max_tokens)
            second_row = second_rows.get(max_tokens)
            if winner_row is None or second_row is None:
                continue
            if not symmetric_mean_in_ci(winner_row, second_row):
                continue
            # Crossover detected at this axis point.
            if max_tokens == first_axis:
                evidence = "M6.1.3 verdict not robust to M6.2 resampling"
            else:
                evidence = (
                    f"winner_p50={winner_row.wall_p50_ms:.2f}ms "
                    f"± {winner_row.wall_p50_ms_ci_half_width or 0.0:.2f}ms "
                    f"overlaps second_p50={second_row.wall_p50_ms:.2f}ms "
                    f"± {second_row.wall_p50_ms_ci_half_width or 0.0:.2f}ms "
                    f"at max_tokens={max_tokens}"
                )
            out.append(
                M6_2CrossoverThreshold(
                    cell_id=cell_id,
                    m6_1_3_winner_cohort=winner,
                    m6_1_3_second_cohort=second,
                    crossover_max_tokens=max_tokens,
                    crossover_evidence=evidence,
                    m6_1_3_base_verdict=base_verdict,
                )
            )
            found_crossover = True
            break

        if not found_crossover:
            out.append(
                M6_2CrossoverThreshold(
                    cell_id=cell_id,
                    m6_1_3_winner_cohort=winner,
                    m6_1_3_second_cohort=second,
                    crossover_max_tokens=None,
                    crossover_evidence="verdict survives across the axis",
                    m6_1_3_base_verdict=base_verdict,
                )
            )
    return out


# --- KV-pressure inference (US3 / FR-017a + round-5 amendment) -------------


@dataclass(frozen=True, slots=True)
class SubProbeBlockResult:
    """One sub-probe block's per-block summary.

    Mirrors the shape :class:`sweep.BlockDispatchResult` produces but is
    aggregated into the percentile statistics the KV-pressure inference
    consumes. ``cell_type`` is ``"chat_stream"`` or ``"embed"``; ``cohort``
    + ``max_tokens`` identify the block; ``wall_p50_ms`` is the per-block
    median latency (None on block failure).

    ``kv_cache_used_fraction_peak`` is best-effort — populated from per-RPC
    trailing metadata when the engine exposes ``engine_kv_cache_used_fraction``;
    None when the engine doesn't (vLLM may or may not surface this depending
    on the model + scheduling policy).
    """

    cohort: M6_1_2CohortKind
    cell_type: str  # "chat_stream" | "embed"
    max_tokens: int
    n_rpcs: int  # always M6_2_SUB_PROBE_N (20) per FR-036
    wall_p50_ms: float | None
    wall_p95_ms: float | None
    failed_reason: str | None
    kv_cache_used_fraction_peak: float | None
    scheduling_stall_signals: str | None
    block_start_utc: str
    block_end_utc: str
    retry_attempted: bool


def _sub_probe_prompt_source_for(cell_type: str) -> str:
    if cell_type == "chat_stream":
        return "corpus_sharegpt"
    if cell_type == "embed":
        return "corpus_sharegpt_embed"
    raise ValueError(f"Unrecognized cell_type {cell_type!r}")


def compute_kv_pressure_inference(
    sub_probe_rows: list[SubProbeBlockResult],
) -> list[M6_2KVPressureObservation]:
    """Per spec round-5 FR-017a + round-3 Q3 (threshold 2.2).

    Consumes the sub-probe per-(cohort, cell_type, max_tokens) rows produced
    by :func:`m6_2_sub_probe.run_kv_pressure_sub_probe`. Emits one
    :class:`M6_2KVPressureObservation` per (cohort, cell_type) pair — 8 in
    total (4 cohorts × 2 cell-types).

    The wall-clock-ratio ``R = wall_p50_ms(2048) / wall_p50_ms(1024)``:

    - ``R > 2.2`` → ``kv_pressure_inferred_<cell_type>``.
    - ``R <= 2.2`` → ``kv_pressure_not_observable``.
    - Either sub-probe block missing or failed (``wall_p50_ms is None``) →
      ``ratio = None`` and ``kv_pressure_not_observable``.
    - OOM at ``(cohort, c=8, 2048)`` → ``oom_observed=True`` and inference
      stays ``kv_pressure_not_observable`` (cannot compute a meaningful ratio
      when the higher-cap block crashed).

    Engine fields (``kv_cache_used_fraction_peak`` /
    ``scheduling_stall_signals``) propagate from the 2048-cap block when
    present; ``None`` otherwise. They are best-effort observability — the
    inference fires regardless.
    """
    # Bucket the rows by (cell_type, cohort, max_tokens) for lookup.
    bucket: dict[tuple[str, M6_1_2CohortKind, int], SubProbeBlockResult] = {
        (row.cell_type, row.cohort, row.max_tokens): row for row in sub_probe_rows
    }

    out: list[M6_2KVPressureObservation] = []
    for cell_type in ("chat_stream", "embed"):
        for cohort in M6_1_2_COHORTS:
            row_1024 = bucket.get((cell_type, cohort, 1024))
            row_2048 = bucket.get((cell_type, cohort, 2048))

            oom = bool(
                row_2048 is not None and (row_2048.failed_reason or "").lower().endswith("oom")
            )

            if (
                row_1024 is None
                or row_2048 is None
                or row_1024.wall_p50_ms is None
                or row_2048.wall_p50_ms is None
            ):
                ratio: float | None = None
                label: str = "kv_pressure_not_observable"
            else:
                ratio = row_2048.wall_p50_ms / row_1024.wall_p50_ms
                if oom:
                    label = "kv_pressure_not_observable"
                elif ratio > M6_2_KV_PRESSURE_THRESHOLD:
                    label = f"kv_pressure_inferred_{cell_type}"
                else:
                    label = "kv_pressure_not_observable"

            engine_peak: float | None = None
            stall: str | None = None
            if row_2048 is not None:
                engine_peak = row_2048.kv_cache_used_fraction_peak
                stall = row_2048.scheduling_stall_signals

            out.append(
                M6_2KVPressureObservation(
                    cohort=cohort,
                    cell_type=cell_type,
                    wall_clock_ratio_c8_2048_over_1024=ratio,
                    wall_clock_inference_label=label,  # type: ignore[arg-type]
                    kv_cache_used_fraction_peak=engine_peak,
                    scheduling_stall_signals=stall,
                    oom_observed=oom,
                    sub_probe_n_rpcs=M6_2_SUB_PROBE_N,
                    sub_probe_prompt_source=_sub_probe_prompt_source_for(cell_type),  # type: ignore[arg-type]
                    sub_probe_measurement_regime="forced_cap_ignore_eos_true",
                )
            )
    return out
