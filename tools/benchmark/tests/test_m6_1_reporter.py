"""Tests for ``m6_1_reporter`` — markdown + JSON output (T027)."""

from __future__ import annotations

import json
from pathlib import Path

from vllm_grpc_bench.m3_types import RTTRecord
from vllm_grpc_bench.m6_1_reporter import (
    render_engine_path_differential,
    render_executive_summary,
    render_json,
    render_markdown,
    render_supersedes_m6_table,
    write_m6_1_report,
)
from vllm_grpc_bench.m6_1_types import (
    EngineCostAggregate,
    EnginePathDifferentialRow,
    M6_1Cell,
    M6_1CellRecord,
    M6_1PerCohortAggregate,
    M6_1Run,
    M6_1RunMeta,
    SupersedesM6Row,
)


def _agg(cohort: str, mean: float, half: float = 1.0, n: int = 100) -> M6_1PerCohortAggregate:
    return M6_1PerCohortAggregate(
        cohort=cohort,  # type: ignore[arg-type]
        n_attempted=100,
        n_successes=n,
        failure_count=100 - n,
        classifier_metric_mean_ms=mean,
        classifier_metric_ci_half_width_ms=half,
        total_wall_clock_mean_ms=mean,
        total_wall_clock_ci_half_width_ms=half,
        engine_cost_mean=EngineCostAggregate(
            engine_forward_mean_ms=5.0,
            engine_forward_ci_half_width_ms=0.1,
            engine_ttft_mean_ms=5.0,
            engine_ttft_ci_half_width_ms=0.1,
            engine_tpot_mean_ms=1.0,
            engine_tpot_ci_half_width_ms=0.05,
        ),
    )


def _make_cell(
    path: str,
    concurrency: int,
    classification: str,
    chat_stream_drift: bool = False,
    n_succ: int = 100,
) -> M6_1CellRecord:
    pc = {
        "rest_https_edge": _agg("rest_https_edge", 200.0, n=n_succ),
        "default_grpc": _agg("default_grpc", 150.0, n=n_succ),
        "tuned_grpc_multiplexed": _agg("tuned_grpc_multiplexed", 100.0, n=n_succ),
    }
    return M6_1CellRecord(
        cell=M6_1Cell(path=path, hidden_size=4096, concurrency=concurrency),  # type: ignore[arg-type]
        per_cohort=pc,
        classification=classification,  # type: ignore[arg-type]
        classification_reason=f"synthetic {classification}",
        classifier_metric="wall_clock_ms" if path == "embed" else "ttft_ms",
        cohort_pair=("rest_https_edge", "tuned_grpc_multiplexed"),
        m6_winner_delta_ms=80.0 if classification != "no_winner_at_n100" else None,
        m6_winner_direction="grpc_wins" if classification != "no_winner_at_n100" else None,
        engine_cost_mean_ms=5.0,
        engine_cost_drift_warning=False,
        per_cohort_engine_cost_mean_ms=None,
        chat_stream_control_drift_warning=chat_stream_drift,
    )


def _make_supersedes_row(cell_record: M6_1CellRecord) -> SupersedesM6Row:
    return SupersedesM6Row(
        cell=cell_record.cell,
        classification=cell_record.classification,
        m6_1_classifier_metric_mean_per_cohort={
            k: agg.classifier_metric_mean_ms for k, agg in cell_record.per_cohort.items()
        },
        m6_1_classifier_metric_ci_per_cohort={
            k: (
                agg.classifier_metric_mean_ms - agg.classifier_metric_ci_half_width_ms,
                agg.classifier_metric_mean_ms + agg.classifier_metric_ci_half_width_ms,
            )
            for k, agg in cell_record.per_cohort.items()
        },
        m6_winner_cohort="tuned_grpc_multiplexed"
        if cell_record.m6_winner_direction == "grpc_wins"
        else "rest_https_edge"
        if cell_record.m6_winner_direction == "rest_wins"
        else None,
        m6_winner_delta_ms=cell_record.m6_winner_delta_ms,
        m6_winner_direction=cell_record.m6_winner_direction,
        engine_cost_mean_ms=cell_record.engine_cost_mean_ms,
        engine_cost_drift_warning=cell_record.engine_cost_drift_warning,
        chat_stream_control_drift_warning=cell_record.chat_stream_control_drift_warning,
        notes=cell_record.classification_reason,
    )


def _make_differential_row(cell_record: M6_1CellRecord) -> EnginePathDifferentialRow:
    return EnginePathDifferentialRow(
        cell=cell_record.cell,
        per_cohort_classifier_metric_delta_ms={
            "rest_https_edge": 12.3,
            "default_grpc": 11.7,
            "tuned_grpc_multiplexed": 11.2,
        },
        per_cohort_classifier_metric_delta_ci_half_width_ms={
            "rest_https_edge": 1.8,
            "default_grpc": 1.6,
            "tuned_grpc_multiplexed": 1.5,
        },
        engine_cost_mean_delta_ms=11.7,
        engine_cost_mean_delta_ci_half_width_ms=1.0,
        per_cohort_n_successes={k: agg.n_successes for k, agg in cell_record.per_cohort.items()},
    )


def _make_run(
    *,
    mix: bool = True,
    chat_stream_drift_flag: bool = True,
) -> M6_1Run:
    classifications = (
        [
            ("embed", 1, "verdict_survives"),
            ("embed", 4, "verdict_changed"),
            ("embed", 8, "no_winner_at_n100"),
            ("chat_stream", 1, "verdict_buried_by_engine"),
            ("chat_stream", 4, "cell_incomplete"),
            ("chat_stream", 8, "verdict_survives"),
        ]
        if mix
        else [
            ("embed", 1, "verdict_survives"),
            ("embed", 4, "verdict_survives"),
            ("embed", 8, "verdict_survives"),
            ("chat_stream", 1, "verdict_survives"),
            ("chat_stream", 4, "verdict_survives"),
            ("chat_stream", 8, "verdict_survives"),
        ]
    )
    cells = []
    for path, c, classification in classifications:
        cells.append(
            _make_cell(
                path,
                c,
                classification,
                chat_stream_drift=(chat_stream_drift_flag and path == "chat_stream" and c == 8),
                n_succ=65 if classification == "cell_incomplete" else 100,
            )
        )
    return M6_1Run(
        run_id="2026-05-16T12:00:00Z-deadbe7",
        run_started_at="2026-05-16T12:00:00Z",
        run_completed_at="2026-05-16T13:25:00Z",
        run_meta=M6_1RunMeta(
            git_sha="deadbeefcafef00d",
            hostname="ben-mbp.local",
            modal_function_id="fn-test",
            gpu_type="A10G",
            modal_region="eu-west-1",
            model_identifier="Qwen/Qwen3-8B",
            hidden_size=4096,
            M6_1_BASE_SEED=42,
            seq_len=8,
            engine_version="0.20.1",
            m6_baseline_engine_version="unknown",
            torch_version="2.11.0",
            m6_winner_deltas={
                "embed_c1_h4096": 80.0,
                "embed_c4_h4096": 80.0,
                "embed_c8_h4096": None,
                "chat_stream_c1_h4096": 80.0,
                "chat_stream_c4_h4096": None,
                "chat_stream_c8_h4096": 80.0,
            },
            cold_start_s=28.4,
            max_model_len=2048,
            gpu_memory_utilization=0.92,
            run_started_at="2026-05-16T12:00:00Z",
            run_completed_at="2026-05-16T13:25:00Z",
        ),
        smoke_result=None,
        cells=cells,
        rtt_distribution={
            "rest_https_edge": RTTRecord(
                n=32, median_ms=12.0, p95_ms=15.0, samples_ms=(12.0,) * 32
            ),
            "default_grpc": RTTRecord(n=32, median_ms=8.0, p95_ms=10.0, samples_ms=(8.0,) * 32),
            "tuned_grpc_multiplexed": RTTRecord(
                n=32, median_ms=8.0, p95_ms=10.0, samples_ms=(8.0,) * 32
            ),
        },
        supersedes_m6_under_enable_prompt_embeds=[_make_supersedes_row(c) for c in cells],
        engine_path_differential=[_make_differential_row(c) for c in cells],
        m6_meta={"engine_version": "unknown", "model_identifier": "Qwen/Qwen3-8B"},
    )


def test_executive_summary_includes_pinned_versions() -> None:
    run = _make_run()
    out = render_executive_summary(run)
    assert "torch: 2.11.0" in out or "Pinned client torch**: 2.11.0" in out
    assert "Prompt-embeds seq_len" in out
    assert "M6_1_BASE_SEED" in out
    assert "vLLM 0.20.1" in out


def test_supersedes_table_lists_six_cells() -> None:
    run = _make_run()
    table = render_supersedes_m6_table(run)
    assert table.count("|") > 6 * 8  # 6 rows × 8 columns of |
    assert "verdict_survives" in table
    assert "verdict_changed" in table
    assert "no_winner_at_n100" in table
    assert "verdict_buried_by_engine" in table
    assert "cell_incomplete" in table


def test_engine_path_differential_section_present() -> None:
    run = _make_run()
    section = render_engine_path_differential(run)
    assert "Engine Path Differential" in section
    # 6 rows expected (one per cell).
    rows = [line for line in section.splitlines() if line.startswith(("| embed", "| chat_stream"))]
    assert len(rows) == 6


def test_chat_stream_drift_warning_surfaced() -> None:
    run = _make_run()
    table = render_supersedes_m6_table(run)
    # The (chat_stream, c=8) row was constructed with the drift flag set.
    assert "⚠ chat_stream drift" in table


def test_methodology_section_mentions_engine_version_comparison() -> None:
    run = _make_run()
    md = render_markdown(run)
    assert "Engine version comparison" in md
    assert "0.20.1" in md
    assert "unknown" in md


def test_full_markdown_render(tmp_path: Path) -> None:
    run = _make_run()
    md_path = tmp_path / "report.md"
    json_path = tmp_path / "report.json"
    write_m6_1_report(run, md_path, json_path)
    assert md_path.exists()
    assert json_path.exists()


def test_json_companion_has_all_required_top_level_keys(tmp_path: Path) -> None:
    run = _make_run()
    payload = render_json(run)
    required = {
        "schema_version",
        "run_id",
        "run_started_at",
        "run_completed_at",
        "supersedes_m6_under_enable_prompt_embeds",
        "engine_path_differential",
        "run_meta",
        "m6_meta",
        "cohorts",
        "protocol_comparison_verdicts",
        "engine_cost_baseline",
    }
    missing = required - set(payload.keys())
    assert not missing, f"Missing keys: {missing}"
    assert payload["schema_version"] == "m6_1.v1"
    assert len(payload["supersedes_m6_under_enable_prompt_embeds"]) == 6
    assert len(payload["engine_path_differential"]) == 6


def test_json_run_meta_carries_m6_1_fields() -> None:
    run = _make_run()
    payload = render_json(run)
    rm = payload["run_meta"]
    assert rm["seq_len"] == 8
    assert rm["torch_version"] == "2.11.0"
    assert rm["M6_1_BASE_SEED"] == 42
    assert "m6_winner_deltas" in rm


def test_json_strict_superset_m6_aware_consumer_compat(tmp_path: Path) -> None:
    """SC-005: serialise + reload → JSON valid, M6-shape fields present."""
    run = _make_run()
    payload = render_json(run)
    # Round-trip through JSON serialisation to ensure no non-serialisable values.
    text = json.dumps(payload, default=str)
    reloaded = json.loads(text)
    assert reloaded["schema_version"] == "m6_1.v1"
    assert reloaded["engine_cost_baseline"] is not None
    assert reloaded["cohorts"] is not None
    assert "supersedes_m5_2_under_real_engine" in reloaded
