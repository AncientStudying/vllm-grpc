"""T041 — M6.2 KV-pressure inference unit tests (FR-017a + round-5 amendment).

Exercises :func:`m6_2_crossover.compute_kv_pressure_inference` directly with
synthetic sub-probe rows. Covers:

- ``R > 2.2`` → ``kv_pressure_inferred_<cell_type>``.
- ``R <= 2.2`` → ``kv_pressure_not_observable``.
- Inference consumes SUB-PROBE rows (NOT budget-table c=8 rows) — synthesized
  divergent budget-table values must not affect the ratio.
- OOM at ``(cohort, c=8, max_tokens=2048)`` → ``oom_observed=True`` AND label
  pins to ``kv_pressure_not_observable``.
- ``kv_cache_used_fraction_peak`` propagates from the 2048 sub-probe row.
- Engine field absent → inference still fires (best-effort field).
- 8 records emitted (4 cohorts × 2 cell-types) when all sub-probe rows present.
"""

from __future__ import annotations

from vllm_grpc_bench.m6_1_2_types import M6_1_2_COHORTS
from vllm_grpc_bench.m6_2_crossover import (
    SubProbeBlockResult,
    compute_kv_pressure_inference,
)
from vllm_grpc_bench.m6_2_types import M6_2_SUB_PROBE_N


def _row(
    *,
    cohort: str,
    cell_type: str,
    max_tokens: int,
    wall_p50_ms: float | None = 100.0,
    failed_reason: str | None = None,
    engine_peak: float | None = None,
    stall: str | None = None,
) -> SubProbeBlockResult:
    return SubProbeBlockResult(
        cohort=cohort,  # type: ignore[arg-type]
        cell_type=cell_type,
        max_tokens=max_tokens,
        n_rpcs=M6_2_SUB_PROBE_N,
        wall_p50_ms=None if failed_reason else wall_p50_ms,
        wall_p95_ms=None if failed_reason else (wall_p50_ms or 0.0) * 1.5,
        failed_reason=failed_reason,
        kv_cache_used_fraction_peak=engine_peak,
        scheduling_stall_signals=stall,
        block_start_utc="2026-05-20T00:00:00Z",
        block_end_utc="2026-05-20T00:00:05Z",
        retry_attempted=False,
    )


def _full_sub_probe_set(
    *,
    p50_at_1024: float = 100.0,
    p50_at_2048: float = 250.0,
) -> list[SubProbeBlockResult]:
    """16-row sub-probe shape (4 cohorts × 2 cell-types × 2 caps)."""
    rows: list[SubProbeBlockResult] = []
    for cell_type in ("chat_stream", "embed"):
        for cohort in M6_1_2_COHORTS:
            rows.append(
                _row(cohort=cohort, cell_type=cell_type, max_tokens=1024, wall_p50_ms=p50_at_1024)
            )
            rows.append(
                _row(cohort=cohort, cell_type=cell_type, max_tokens=2048, wall_p50_ms=p50_at_2048)
            )
    return rows


# --- Eight records emitted -------------------------------------------------


def test_emits_eight_records_when_all_blocks_present() -> None:
    rows = _full_sub_probe_set()
    out = compute_kv_pressure_inference(rows)
    assert len(out) == 8, "4 cohorts × 2 cell-types = 8 records"
    types = {obs.cell_type for obs in out}
    assert types == {"chat_stream", "embed"}
    cohorts = {obs.cohort for obs in out}
    assert cohorts == set(M6_1_2_COHORTS)


# --- Ratio rule ------------------------------------------------------------


def test_ratio_above_threshold_emits_inferred_label() -> None:
    """R = 250/100 = 2.5 > 2.2 threshold → kv_pressure_inferred_<cell_type>."""
    rows = _full_sub_probe_set(p50_at_1024=100.0, p50_at_2048=250.0)
    out = compute_kv_pressure_inference(rows)
    for obs in out:
        assert obs.wall_clock_ratio_c8_2048_over_1024 is not None
        assert obs.wall_clock_ratio_c8_2048_over_1024 > 2.2
        assert obs.wall_clock_inference_label == f"kv_pressure_inferred_{obs.cell_type}"


def test_ratio_at_or_below_threshold_emits_not_observable() -> None:
    """R = 200/100 = 2.0 → kv_pressure_not_observable."""
    rows = _full_sub_probe_set(p50_at_1024=100.0, p50_at_2048=200.0)
    out = compute_kv_pressure_inference(rows)
    for obs in out:
        assert obs.wall_clock_inference_label == "kv_pressure_not_observable"


def test_ratio_at_exactly_threshold_does_not_fire() -> None:
    """R == 2.2 — strict ``> 2.2`` rule per FR-017a means no inference."""
    rows = _full_sub_probe_set(p50_at_1024=100.0, p50_at_2048=220.0)
    out = compute_kv_pressure_inference(rows)
    for obs in out:
        assert obs.wall_clock_inference_label == "kv_pressure_not_observable"


# --- OOM handling ----------------------------------------------------------


def test_oom_at_2048_pins_label_to_not_observable() -> None:
    """OOM at ``(cohort, c=8, max_tokens=2048)`` → ``oom_observed=True`` AND
    label stays ``kv_pressure_not_observable`` (cannot compute a meaningful
    ratio when the higher-cap block crashed)."""
    rows: list[SubProbeBlockResult] = []
    for cell_type in ("chat_stream", "embed"):
        for cohort in M6_1_2_COHORTS:
            rows.append(
                _row(cohort=cohort, cell_type=cell_type, max_tokens=1024, wall_p50_ms=100.0)
            )
            if cohort == "default_grpc":
                rows.append(
                    _row(
                        cohort=cohort,
                        cell_type=cell_type,
                        max_tokens=2048,
                        failed_reason="single_rpc_engine_oom",
                    )
                )
            else:
                rows.append(
                    _row(cohort=cohort, cell_type=cell_type, max_tokens=2048, wall_p50_ms=250.0)
                )
    out = compute_kv_pressure_inference(rows)
    for obs in out:
        if obs.cohort == "default_grpc":
            assert obs.oom_observed is True
            assert obs.wall_clock_inference_label == "kv_pressure_not_observable"
            assert obs.wall_clock_ratio_c8_2048_over_1024 is None
        else:
            assert obs.oom_observed is False


# --- Engine field propagation ----------------------------------------------


def test_engine_field_propagates_from_2048_block() -> None:
    rows: list[SubProbeBlockResult] = []
    for cell_type in ("chat_stream", "embed"):
        for cohort in M6_1_2_COHORTS:
            rows.append(
                _row(cohort=cohort, cell_type=cell_type, max_tokens=1024, wall_p50_ms=100.0)
            )
            rows.append(
                _row(
                    cohort=cohort,
                    cell_type=cell_type,
                    max_tokens=2048,
                    wall_p50_ms=250.0,
                    engine_peak=0.85,
                )
            )
    out = compute_kv_pressure_inference(rows)
    for obs in out:
        assert obs.kv_cache_used_fraction_peak == 0.85


def test_engine_field_absent_inference_still_fires() -> None:
    rows = _full_sub_probe_set(p50_at_1024=100.0, p50_at_2048=300.0)  # R = 3.0
    out = compute_kv_pressure_inference(rows)
    for obs in out:
        assert obs.kv_cache_used_fraction_peak is None
        assert obs.wall_clock_inference_label == f"kv_pressure_inferred_{obs.cell_type}"


# --- Missing sub-probe blocks ----------------------------------------------


def test_missing_2048_block_emits_not_observable() -> None:
    rows: list[SubProbeBlockResult] = []
    for cell_type in ("chat_stream", "embed"):
        for cohort in M6_1_2_COHORTS:
            rows.append(
                _row(cohort=cohort, cell_type=cell_type, max_tokens=1024, wall_p50_ms=100.0)
            )
    out = compute_kv_pressure_inference(rows)
    for obs in out:
        assert obs.wall_clock_ratio_c8_2048_over_1024 is None
        assert obs.wall_clock_inference_label == "kv_pressure_not_observable"


def test_failed_1024_block_emits_not_observable() -> None:
    rows: list[SubProbeBlockResult] = []
    for cell_type in ("chat_stream", "embed"):
        for cohort in M6_1_2_COHORTS:
            rows.append(
                _row(
                    cohort=cohort,
                    cell_type=cell_type,
                    max_tokens=1024,
                    failed_reason="grpc_timeout",
                )
            )
            rows.append(
                _row(cohort=cohort, cell_type=cell_type, max_tokens=2048, wall_p50_ms=250.0)
            )
    out = compute_kv_pressure_inference(rows)
    for obs in out:
        assert obs.wall_clock_inference_label == "kv_pressure_not_observable"


# --- Sub-probe-vs-budget-table distinction ---------------------------------


def test_inference_uses_sub_probe_rows_not_budget_table() -> None:
    """FR-017a amended: the ratio MUST come from sub-probe wall_p50, not from
    the main-sweep budget-table c=8 rows. This test synthesizes ONLY sub-probe
    rows and asserts the ratio computed from them — there's no budget-table
    leakage path in :func:`compute_kv_pressure_inference`'s signature.
    """
    rows = _full_sub_probe_set(p50_at_1024=100.0, p50_at_2048=250.0)
    out = compute_kv_pressure_inference(rows)
    for obs in out:
        # Ratio must be exactly 250/100 = 2.5 from sub-probe data, regardless
        # of whatever budget-table c=8 rows might contain (not passed in).
        assert obs.wall_clock_ratio_c8_2048_over_1024 == 2.5


# --- Sub-probe metadata fields ---------------------------------------------


def test_sub_probe_metadata_fields_populated() -> None:
    rows = _full_sub_probe_set()
    out = compute_kv_pressure_inference(rows)
    for obs in out:
        assert obs.sub_probe_n_rpcs == M6_2_SUB_PROBE_N
        assert obs.sub_probe_measurement_regime == "forced_cap_ignore_eos_true"
        expected_source = (
            "corpus_sharegpt" if obs.cell_type == "chat_stream" else "corpus_sharegpt_embed"
        )
        assert obs.sub_probe_prompt_source == expected_source
