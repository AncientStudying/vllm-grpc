"""T037 — schema candidates whose CIs overlap the baseline CI on both metrics
are appended to a negative-results appendix in the published report.
"""

from __future__ import annotations

from pathlib import Path

from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.m3_types import (
    BenchmarkCell,
    M5RunMetadata,
    RTTSummary,
    Run,
    RunCohort,
    Sample,
    SchemaCandidatePerWidth,
    SchemaCandidateResult,
)
from vllm_grpc_bench.reporter import write_m5_markdown


def _negative_run() -> Run:
    cell = BenchmarkCell(
        path="embed",
        hidden_size=4096,
        channel_config=M1_BASELINE,
        corpus_subset="m1_embed",
        iterations=100,
    )
    sample = Sample(
        cell_id=cell.cell_id,
        iteration=0,
        request_wire_bytes=100,
        response_wire_bytes=100,
        wall_clock_seconds=0.1,
    )
    cohort = RunCohort(
        cell=cell,
        samples=(sample,),
        n_successful=100,
        bytes_mean=200.0,
        bytes_ci_low=190.0,
        bytes_ci_high=210.0,
        time_mean=0.1,
        time_ci_low=0.09,
        time_ci_high=0.11,
        measurable=True,
    )
    negative_per_width = SchemaCandidatePerWidth(
        hidden_size=4096,
        frozen_baseline_cohort_id=cell.cell_id,
        candidate_cohort_id=cell.cell_id,
        bytes_verdict="no_winner",
        time_verdict="no_winner",
        primary_metric="time",
        delta_bytes_pct=0.5,
        delta_time_pct=0.2,
        ci_overlap_initial=True,
        expanded=False,
    )
    negative_result = SchemaCandidateResult(
        candidate_name="useless_candidate",
        proto_file="proto/vllm_grpc/v1/m4-candidates/useless.proto",
        measured_widths=[4096],
        per_width=[negative_per_width],
        is_negative_result=True,
        notes=None,
    )
    meta = M5RunMetadata(
        m5_methodology_version=1,
        m5_modal_app_name="x",
        m5_modal_region="r",
        m5_runtime_wallclock_seconds=1.0,
        m5_rtt_summary_ms=RTTSummary(min_ms=1.0, median_ms=1.0, p95_ms=1.0, max_ms=1.0),
        rtt_validity_threshold_ms=1.0,
        rtt_exercise_threshold_ms=20.0,
        warmup_n=0,
        server_bound_overhead_threshold_ms=50.0,
        server_bound_cohort_count=0,
    )
    return Run(
        mode="m5-cross-host-validation",
        axes=[],
        widths=[4096],
        paths=["embed"],
        iterations_per_cell=100,
        seed=0,
        cohorts=[cohort],
        m5_metadata=meta,
        schema_candidate_results=[negative_result],
    )


def test_negative_results_appendix_section_present(tmp_path: Path) -> None:
    run = _negative_run()
    out = tmp_path / "m5.md"
    write_m5_markdown(run, out)
    text = out.read_text()
    assert "Negative results — do not re-run speculatively" in text
    assert "`useless_candidate`" in text
