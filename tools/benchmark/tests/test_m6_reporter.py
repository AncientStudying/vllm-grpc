"""Tests for the M6 markdown + JSON reporter (T040, T041, T043).

Covers:
- Executive section contains FR-015 mandatory strings within the first
  ~screenful (SC-005).
- Verdict table renders all 5 terminal classifications correctly.
- ``⚠ engine drift`` marker + per-cohort footnote when drift fires.
- JSON companion is a strict superset of M5.2's schema (FR-016) —
  M5.2-shape fields all present.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from vllm_grpc_bench.m3_types import RTTRecord
from vllm_grpc_bench.m6_reporter import (
    build_m6_run,
    render_engine_cost_per_rpc_table,
    render_executive_summary,
    render_json,
    render_markdown,
    render_supersedes_m5_2_table,
    write_json,
    write_markdown,
)
from vllm_grpc_bench.m6_types import (
    EngineCostAggregate,
    M6Cell,
    M6CellRecord,
    M6CohortKind,
    M6PerCohortAggregate,
    M6RunMeta,
    VerdictClassification,
)


def _make_agg(
    cohort: M6CohortKind,
    mean: float,
    half: float,
    *,
    engine_forward: float | None = None,
    engine_ttft: float | None = None,
    engine_tpot: float | None = None,
    n_successes: int = 100,
) -> M6PerCohortAggregate:
    return M6PerCohortAggregate(
        cohort=cohort,
        n_attempted=100,
        n_successes=n_successes,
        failure_count=100 - n_successes,
        classifier_metric_mean_ms=mean,
        classifier_metric_ci_half_width_ms=half,
        total_wall_clock_mean_ms=mean,
        total_wall_clock_ci_half_width_ms=half,
        engine_cost_mean=EngineCostAggregate(
            engine_forward_mean_ms=engine_forward,
            engine_forward_ci_half_width_ms=0.5 if engine_forward is not None else None,
            engine_ttft_mean_ms=engine_ttft,
            engine_ttft_ci_half_width_ms=1.0 if engine_ttft is not None else None,
            engine_tpot_mean_ms=engine_tpot,
            engine_tpot_ci_half_width_ms=0.2 if engine_tpot is not None else None,
        ),
    )


def _make_cell_record(
    path: str,
    c: int,
    classification: VerdictClassification,
    *,
    drift: bool = False,
    n_successes: int = 100,
    m5_2_winner_delta_ms: float | None = 51.0,
    m5_2_winner_direction: str | None = "grpc_wins",
) -> M6CellRecord:
    cell = M6Cell(path=path, hidden_size=4096, concurrency=c)  # type: ignore[arg-type]
    engine_forward = 12.0 if path == "embed" else None
    engine_ttft = 200.0 if path == "chat_stream" else None
    engine_tpot = 30.0 if path == "chat_stream" else None
    per_cohort: dict[M6CohortKind, M6PerCohortAggregate] = {
        "rest_https_edge": _make_agg(
            "rest_https_edge",
            150.0,
            5.0,
            engine_forward=engine_forward,
            engine_ttft=engine_ttft,
            engine_tpot=engine_tpot,
            n_successes=n_successes,
        ),
        "default_grpc": _make_agg(
            "default_grpc",
            100.0,
            5.0,
            engine_forward=engine_forward,
            engine_ttft=engine_ttft,
            engine_tpot=engine_tpot,
            n_successes=n_successes,
        ),
        "tuned_grpc_multiplexed": _make_agg(
            "tuned_grpc_multiplexed",
            99.0,
            5.0,
            engine_forward=engine_forward,
            engine_ttft=engine_ttft,
            engine_tpot=engine_tpot,
            n_successes=n_successes,
        ),
    }
    per_cohort_engine_means: dict[M6CohortKind, float] | None = None
    if drift:
        per_cohort_engine_means = {
            "rest_https_edge": 12.0,
            "default_grpc": 12.0,
            "tuned_grpc_multiplexed": 25.0,  # >10% disagreement
        }
    return M6CellRecord(
        cell=cell,
        per_cohort=per_cohort,
        classification=classification,
        classification_reason=f"synthetic {classification}",
        classifier_metric="wall_clock_ms" if path == "embed" else "ttft_ms",
        cohort_pair=("rest_https_edge", "tuned_grpc_multiplexed"),
        m5_2_winner_delta_ms=m5_2_winner_delta_ms,
        m5_2_winner_direction=m5_2_winner_direction,  # type: ignore[arg-type]
        engine_cost_mean_ms=engine_forward or engine_ttft or 0.0,
        engine_cost_drift_warning=drift,
        per_cohort_engine_cost_mean_ms=per_cohort_engine_means,
    )


def _make_run(cells: list[M6CellRecord]) -> object:
    meta = M6RunMeta(
        git_sha="abc123",
        hostname="test-host",
        modal_function_id="fn-test",
        gpu_type="A10G",
        modal_region="eu-west-1",
        model_identifier="Qwen/Qwen3-7B",
        engine_version="0.20.1",
        cold_start_s=28.4,
        m5_2_winner_deltas={
            "embed_c1_h4096": 51.0,
            "embed_c4_h4096": None,
            "embed_c8_h4096": None,
            "chat_stream_c1_h4096": None,
            "chat_stream_c4_h4096": None,
            "chat_stream_c8_h4096": None,
        },
        m6_base_seed=42,
    )
    rtt_distribution: dict[M6CohortKind, RTTRecord] = {
        cast(M6CohortKind, kind): RTTRecord(
            n=5,
            median_ms=52.0,
            p95_ms=54.0,
            samples_ms=tuple(50.0 + i for i in range(5)),
        )
        for kind in ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed")
    }
    return build_m6_run(
        run_id="2026-05-15T12:00:00Z-abc123",
        run_started_at="2026-05-15T12:00:00Z",
        run_completed_at="2026-05-15T13:30:00Z",
        meta=meta,
        cells=cells,
        rtt_distribution=rtt_distribution,
    )


# --- Executive section (T040 / SC-005) ---------------------------------------


def test_executive_section_contains_fr_015_strings() -> None:
    cells = [
        _make_cell_record("embed", 1, "verdict_survives"),
        _make_cell_record("embed", 4, "no_winner_at_n100"),
        _make_cell_record("embed", 8, "verdict_changed"),
        _make_cell_record("chat_stream", 1, "verdict_buried_by_engine"),
        _make_cell_record("chat_stream", 4, "cell_incomplete", n_successes=50),
        _make_cell_record("chat_stream", 8, "verdict_survives"),
    ]
    run = _make_run(cells)
    md = render_markdown(run)  # type: ignore[arg-type]
    # All FR-015 required strings appear within the first 2000 characters
    # of the report (SC-005 first-screenful test).
    first_screen = md[:2000]
    assert "vLLM" in first_screen
    assert "Qwen/Qwen3-7B" in first_screen
    assert "4096" in first_screen
    assert "A10G" in first_screen
    assert "eu-west-1" in first_screen
    assert "M6_BASE_SEED" in first_screen
    # FR-020 bytes-axis preservation note.
    assert "Bytes axis" in first_screen
    assert "NOT re-measured" in first_screen


def test_executive_summary_renders_clean() -> None:
    cells = [_make_cell_record("embed", 1, "verdict_survives")] * 6
    run = _make_run(cells)
    summary = render_executive_summary(run)  # type: ignore[arg-type]
    assert summary.startswith("## Executive Summary")
    assert "Verdict tally" in summary


# --- Verdict-table renderer (T041) -------------------------------------------


def test_verdict_table_contains_all_five_classifications() -> None:
    """All 5 terminal classifications render correctly in the table.

    cell_incomplete appears as the Classification value (not folded into
    a verdict bucket).
    """
    cells = [
        _make_cell_record("embed", 1, "verdict_survives"),
        _make_cell_record("embed", 4, "verdict_changed", m5_2_winner_direction="rest_wins"),
        _make_cell_record("embed", 8, "verdict_buried_by_engine"),
        _make_cell_record("chat_stream", 1, "no_winner_at_n100", m5_2_winner_delta_ms=None),
        _make_cell_record("chat_stream", 4, "cell_incomplete", n_successes=50),
        _make_cell_record("chat_stream", 8, "verdict_survives"),
    ]
    run = _make_run(cells)
    table = render_supersedes_m5_2_table(run)  # type: ignore[arg-type]
    assert "## Supersedes M5.2 Under Real Engine" in table
    # All 5 classifications present.
    for c in (
        "verdict_survives",
        "verdict_changed",
        "verdict_buried_by_engine",
        "no_winner_at_n100",
        "cell_incomplete",
    ):
        assert c in table, f"missing classification {c!r}"
    # Exactly 6 data rows (rows that start with "| 1 |" through "| 6 |").
    for i in range(1, 7):
        assert f"| {i} |" in table


def test_verdict_table_drift_marker(tmp_path: Path) -> None:
    """When ``engine_cost_drift_warning`` is True the Notes column carries
    the ⚠ engine drift marker AND per-cohort engine_cost values are surfaced.
    """
    cells = [_make_cell_record("embed", 1, "verdict_survives", drift=True)] + [
        _make_cell_record("embed", 4, "no_winner_at_n100"),
        _make_cell_record("embed", 8, "no_winner_at_n100"),
        _make_cell_record("chat_stream", 1, "no_winner_at_n100", m5_2_winner_delta_ms=None),
        _make_cell_record("chat_stream", 4, "no_winner_at_n100", m5_2_winner_delta_ms=None),
        _make_cell_record("chat_stream", 8, "no_winner_at_n100", m5_2_winner_delta_ms=None),
    ]
    run = _make_run(cells)
    table = render_supersedes_m5_2_table(run)  # type: ignore[arg-type]
    assert "⚠ engine drift" in table
    # Per-cohort engine_cost values appear in the Notes column for the drift row.
    assert "per-cohort engine_cost:" in table


def test_t053_drift_warning_json_payload(tmp_path: Path) -> None:
    """T053 (strengthened) / T050: per-cohort engine_cost means surface in
    the JSON companion's ``per_cohort_engine_cost_mean_ms`` field ONLY when
    drift fires; rows without drift carry ``None`` per FR-014 sub-clause /
    data-model.md M6CellRecord validation rule.

    Synthetic per-cohort engine_cost means disagree by 12% on the first
    cell only (above the >10% threshold).
    """
    cells = [
        _make_cell_record("embed", 1, "verdict_survives", drift=True),
        _make_cell_record("embed", 4, "no_winner_at_n100"),
        _make_cell_record("embed", 8, "no_winner_at_n100"),
        _make_cell_record("chat_stream", 1, "no_winner_at_n100", m5_2_winner_delta_ms=None),
        _make_cell_record("chat_stream", 4, "no_winner_at_n100", m5_2_winner_delta_ms=None),
        _make_cell_record("chat_stream", 8, "no_winner_at_n100", m5_2_winner_delta_ms=None),
    ]
    run = _make_run(cells)
    doc = render_json(run)  # type: ignore[arg-type]
    sm5_2 = doc["supersedes_m5_2_under_real_engine"]
    drift_rows = [r for r in sm5_2 if r["engine_cost_drift_warning"]]
    non_drift_rows = [r for r in sm5_2 if not r["engine_cost_drift_warning"]]
    assert len(drift_rows) == 1
    assert drift_rows[0]["per_cohort_engine_cost_mean_ms"] is not None
    # Drift row's per-cohort mapping has all 3 cohorts.
    assert set(drift_rows[0]["per_cohort_engine_cost_mean_ms"].keys()) == {
        "rest_https_edge",
        "default_grpc",
        "tuned_grpc_multiplexed",
    }
    # Non-drift rows MUST carry None per FR-014 sub-clause / data-model.md.
    for row in non_drift_rows:
        assert row["per_cohort_engine_cost_mean_ms"] is None


# --- Engine Cost Per RPC table (T040 — Phase 4 territory but tested here) ----


def test_engine_cost_per_rpc_table_path_discriminated() -> None:
    """Embed rows show engine_forward_ms; chat_stream rows show TTFT + TPOT."""
    cells = [
        _make_cell_record("embed", 1, "verdict_survives"),
        _make_cell_record("embed", 4, "no_winner_at_n100"),
        _make_cell_record("embed", 8, "no_winner_at_n100"),
        _make_cell_record("chat_stream", 1, "verdict_survives", m5_2_winner_delta_ms=10.0),
        _make_cell_record("chat_stream", 4, "no_winner_at_n100", m5_2_winner_delta_ms=10.0),
        _make_cell_record("chat_stream", 8, "no_winner_at_n100", m5_2_winner_delta_ms=10.0),
    ]
    run = _make_run(cells)
    table = render_engine_cost_per_rpc_table(run)  # type: ignore[arg-type]
    assert "## Engine Cost Per RPC" in table
    # Embed rows have "n/a" in the chat_stream columns.
    embed_rows = [line for line in table.splitlines() if "embed × c=" in line]
    for row in embed_rows:
        # 5 columns separated by " | "; the 3rd (TTFT) and 4th (TPOT) are n/a
        cols = [c.strip() for c in row.split("|") if c.strip()]
        # cols: [cell_label, forward, ttft, tpot, drift_warning]
        assert cols[2] == "n/a"
        assert cols[3] == "n/a"
    chat_rows = [line for line in table.splitlines() if "chat_stream × c=" in line]
    for row in chat_rows:
        cols = [c.strip() for c in row.split("|") if c.strip()]
        assert cols[1] == "n/a"  # forward
        assert cols[2] != "n/a"  # ttft
        assert cols[3] != "n/a"  # tpot


# --- JSON companion strict-superset compatibility (T043 / FR-016) ------------


def test_json_companion_carries_m5_2_strict_superset_fields() -> None:
    cells = [_make_cell_record("embed", 1, "verdict_survives")] + [
        _make_cell_record("embed", 4, "no_winner_at_n100"),
        _make_cell_record("embed", 8, "no_winner_at_n100"),
        _make_cell_record("chat_stream", 1, "verdict_survives", m5_2_winner_delta_ms=10.0),
        _make_cell_record("chat_stream", 4, "no_winner_at_n100", m5_2_winner_delta_ms=10.0),
        _make_cell_record("chat_stream", 8, "no_winner_at_n100", m5_2_winner_delta_ms=10.0),
    ]
    run = _make_run(cells)
    doc = render_json(run)  # type: ignore[arg-type]

    # M5.2-strict-superset preserved fields.
    for key in (
        "schema_version",
        "run_id",
        "run_started_at",
        "run_completed_at",
        "harness_version_sha",
        "modal_region",
        "modal_instance_class",
        "modal_metadata",
        "rtt_distribution",
        "cohorts",
        "protocol_comparison_verdicts",
        "transport_only_verdicts",
        "channel_axis_recommendations",
        "schema_candidate_recommendations",
        "shared_baseline_cohorts",
        "supersedes_m5_2_under_real_engine",
        "engine_cost_baseline",
        "m6_meta",
    ):
        assert key in doc, f"M5.2-strict-superset field {key!r} missing from M6 JSON"
    assert doc["schema_version"] == "m6.v1"

    # protocol_comparison_verdicts: one row per cell, with M5.2-shape fields.
    pcv = doc["protocol_comparison_verdicts"]
    assert isinstance(pcv, list)
    assert len(pcv) == 6
    for row in pcv:
        for required in (
            "path",
            "hidden_size",
            "concurrency",
            "grpc_cohort",
            "rest_cohort",
            "delta_median_ms",
            "ci_lower_ms",
            "ci_upper_ms",
            "verdict",
        ):
            assert required in row, f"M5.2-shape field {required!r} missing"
        # At c=1 the row uses ``tuned_grpc`` per R-6; at c≥2 ``tuned_grpc_multiplexed``.
        if int(row["concurrency"]) == 1:
            assert row["grpc_cohort"] == "tuned_grpc"
        else:
            assert row["grpc_cohort"] == "tuned_grpc_multiplexed"

    # supersedes_m5_2_under_real_engine carries M6 classification.
    sm5_2 = doc["supersedes_m5_2_under_real_engine"]
    assert len(sm5_2) == 6
    assert sm5_2[0]["classification"] == "verdict_survives"

    # engine_cost_baseline carries the M6 → M7 hand-off.
    baseline = doc["engine_cost_baseline"]
    assert len(baseline) == 6

    # m6_meta carries the M5.2-winner-delta snapshot (FR-018).
    meta = doc["m6_meta"]
    assert "m5_2_winner_deltas" in meta
    assert len(meta["m5_2_winner_deltas"]) == 6
    assert meta["m6_base_seed"] == 42


def test_json_companion_serializes_cleanly(tmp_path: Path) -> None:
    """write_json round-trips through json.loads cleanly."""
    cells = [_make_cell_record("embed", 1, "verdict_survives")] + [
        _make_cell_record("embed", 4, "no_winner_at_n100"),
        _make_cell_record("embed", 8, "no_winner_at_n100"),
        _make_cell_record("chat_stream", 1, "verdict_survives", m5_2_winner_delta_ms=10.0),
        _make_cell_record("chat_stream", 4, "no_winner_at_n100", m5_2_winner_delta_ms=10.0),
        _make_cell_record("chat_stream", 8, "no_winner_at_n100", m5_2_winner_delta_ms=10.0),
    ]
    run = _make_run(cells)
    out = tmp_path / "m6.json"
    write_json(run, out)  # type: ignore[arg-type]
    loaded = json.loads(out.read_text())
    assert loaded["schema_version"] == "m6.v1"
    assert len(loaded["protocol_comparison_verdicts"]) == 6


def test_write_markdown_emits_file(tmp_path: Path) -> None:
    cells = [_make_cell_record("embed", 1, "verdict_survives")] * 6
    run = _make_run(cells)
    out = tmp_path / "m6.md"
    write_markdown(run, out)  # type: ignore[arg-type]
    text = out.read_text()
    assert "M6 — Real-Engine Mini-Validation" in text
    assert "Supersedes M5.2 Under Real Engine" in text
