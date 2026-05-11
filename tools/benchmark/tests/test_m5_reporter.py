"""T020 — M5 report layout (strict-superset JSON + Markdown).

Tests build a tiny synthetic ``Run`` carrying the M5 fields and assert that
both ``write_m5_json`` and ``write_m5_markdown`` emit the schema documented in
``contracts/m5-report-schema.md`` (and the Markdown section order matches
``quickstart.md`` "Reading the report").
"""

from __future__ import annotations

import json
from pathlib import Path

from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.m3_types import (
    BenchmarkCell,
    Citation,
    M5CrossHostBaseline,
    M5RunMetadata,
    Recommendation,
    RTTRecord,
    RTTSummary,
    Run,
    RunCohort,
    Sample,
    SupersedesM4Entry,
)
from vllm_grpc_bench.reporter import write_m5_json, write_m5_markdown


def _make_run() -> Run:
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
        request_wire_bytes=20_000,
        response_wire_bytes=200,
        wall_clock_seconds=0.150,
    )
    rtt = RTTRecord(n=4, median_ms=80.0, p95_ms=120.0, samples_ms=(80.0,) * 4)
    cohort = RunCohort(
        cell=cell,
        samples=(sample,),
        n_successful=100,
        bytes_mean=20_200.0,
        bytes_ci_low=20_100.0,
        bytes_ci_high=20_300.0,
        time_mean=0.150,
        time_ci_low=0.145,
        time_ci_high=0.155,
        measurable=True,
        is_baseline=True,
        baseline_role="m1_shared",
        rtt_record=rtt,
        server_overhead_estimate_ms=12.0,
        server_bound=False,
        low_rtt_caveat=False,
        discarded=False,
    )
    warmup_cohort = RunCohort(
        cell=cell,
        samples=(),
        n_successful=0,
        bytes_mean=0.0,
        bytes_ci_low=0.0,
        bytes_ci_high=0.0,
        time_mean=0.150,
        time_ci_low=0.0,
        time_ci_high=0.0,
        measurable=False,
        rtt_record=rtt,
        discarded=True,
    )
    super_entry = SupersedesM4Entry(
        m4_axis="keepalive",
        m4_hidden_size=4096,
        m4_path="chat_stream",
        m4_verdict_time="no_winner",
        m4_verdict_bytes="no_winner",
        m4_loopback_caveat=True,
        m5_verdict_time="recommend",
        m5_verdict_bytes="no_winner",
        m5_supporting_ci_lower=0.041,
        m5_supporting_ci_upper=0.067,
        rationale="real RTT exposed a 5.4% TTFT reduction under keepalive=enabled",
        expected_class="loopback_resolution",
        citations=(
            Citation(
                repo="grpc/grpc",
                file_path="src/core/lib/transport/transport.h",
                identifier=None,
                justification="HTTP/2 KEEPALIVE behavior under non-loopback RTT",
            ),
        ),
    )
    rec = Recommendation(
        axis="max_message_size",
        applies_to_path="embed",
        applies_to_widths=frozenset({4096}),
        verdict="no_winner",
        baseline_ci_upper=0.155,
        citation="grpcio: channel_args.cc",
        notes="CIs overlap",
        corpus_subset="m1_embed",
    )
    meta = M5RunMetadata(
        m5_methodology_version=1,
        m5_modal_app_name="vllm-grpc-bench-mock",
        m5_modal_region="eu-west-1",
        m5_runtime_wallclock_seconds=4831.2,
        m5_rtt_summary_ms=RTTSummary(min_ms=28.4, median_ms=87.1, p95_ms=142.6, max_ms=215.8),
        rtt_validity_threshold_ms=1.0,
        rtt_exercise_threshold_ms=20.0,
        warmup_n=32,
        server_bound_overhead_threshold_ms=50.0,
        server_bound_cohort_count=0,
    )
    baseline_metadata = M5CrossHostBaseline(
        path="embed",
        cohort_id=cohort.cell.cell_id,
        modal_app_name="vllm-grpc-bench-mock",
        modal_region="eu-west-1",
        measured_rtt=rtt,
        n=100,
    )
    run = Run(
        mode="m5-cross-host-validation",
        axes=["max_message_size"],
        widths=[4096],
        paths=["embed"],
        iterations_per_cell=100,
        seed=0,
        cohorts=[warmup_cohort, cohort],
        pacing_mode="no_pacing",
        shared_baseline_cohort_ids={"embed": cohort.cell.cell_id},
        loopback_caveat_axes=[],
        m5_metadata=meta,
        m5_cross_host_baselines={"embed": baseline_metadata},
        supersedes_m4=[super_entry],
    )
    run.recommendations.append(rec)
    return run


def test_write_m5_json_emits_top_level_fields(tmp_path: Path) -> None:
    run = _make_run()
    out = tmp_path / "m5.json"
    write_m5_json(run, out)
    payload = json.loads(out.read_text())
    # Top-level M5 fields per contract m5-report-schema.md.
    assert payload["mode"] == "m5-cross-host-validation"
    assert payload["m5_methodology_version"] == 1
    assert payload["m5_modal_app_name"] == "vllm-grpc-bench-mock"
    assert payload["m5_modal_region"] == "eu-west-1"
    assert payload["rtt_validity_threshold_ms"] == 1.0
    assert payload["rtt_exercise_threshold_ms"] == 20.0
    assert payload["warmup_n"] == 32
    assert payload["server_bound_overhead_threshold_ms"] == 50.0
    assert payload["server_bound_cohort_count"] == 0
    # Run-level RTT summary.
    rtt_summary = payload["m5_rtt_summary_ms"]
    assert rtt_summary["median"] == 87.1
    # Per-cohort additions are present.
    cohort_payload = next(c for c in payload["cohorts"] if not c["discarded"])
    assert cohort_payload["rtt_record"]["n"] == 4
    assert cohort_payload["server_overhead_estimate_ms"] == 12.0
    assert cohort_payload["server_bound"] is False
    assert cohort_payload["low_rtt_caveat"] is False
    # M4-reader compat: every M5 cohort emits loopback_caveat=false.
    assert cohort_payload["loopback_caveat"] is False
    # Warm-up cohort: discarded=true.
    warmup_payload = next(c for c in payload["cohorts"] if c["discarded"])
    assert warmup_payload["discarded"] is True


def test_write_m5_json_emits_supersedes_m4_entries(tmp_path: Path) -> None:
    run = _make_run()
    out = tmp_path / "m5.json"
    write_m5_json(run, out)
    payload = json.loads(out.read_text())
    assert len(payload["supersedes_m4"]) == 1
    entry = payload["supersedes_m4"][0]
    assert entry["verdict_changed"] is True
    assert entry["expected_class"] == "loopback_resolution"
    assert entry["citations"][0]["repo"] == "grpc/grpc"


def test_write_m5_markdown_section_order(tmp_path: Path) -> None:
    """Section order matches quickstart.md "Reading the report"."""
    run = _make_run()
    out = tmp_path / "m5.md"
    write_m5_markdown(run, out)
    text = out.read_text()

    methodology_pos = text.index("## Methodology")
    verdicts_pos = text.index("## Verdicts")
    supersedes_pos = text.index("## Supersedes M4")
    summary_pos = text.index("## Executive summary")
    assert methodology_pos < verdicts_pos < supersedes_pos < summary_pos


def test_write_m5_markdown_supersedes_visual_distinction(tmp_path: Path) -> None:
    run = _make_run()
    out = tmp_path / "m5.md"
    write_m5_markdown(run, out)
    text = out.read_text()
    # Verdict-changed rows carry a leading **[changed]** marker (SC-004).
    assert "**[changed]**" in text


def test_write_m5_markdown_methodology_carries_thresholds(tmp_path: Path) -> None:
    run = _make_run()
    out = tmp_path / "m5.md"
    write_m5_markdown(run, out)
    text = out.read_text()
    assert "validity=1.0 ms" in text
    assert "exercise=20.0 ms" in text
    assert "eu-west-1" in text


def test_write_m5_markdown_unexpected_supersession_in_separate_subheading(
    tmp_path: Path,
) -> None:
    """T050 — unexpected supersessions land under their own sub-heading."""
    run = _make_run()
    # Append an unexpected_supersession entry alongside the loopback one.
    run.supersedes_m4.append(
        SupersedesM4Entry(
            m4_axis="max_message_size",
            m4_hidden_size=4096,
            m4_path="embed",
            m4_verdict_time="no_winner",
            m4_verdict_bytes="no_winner",
            m4_loopback_caveat=False,
            m5_verdict_time="recommend",
            m5_verdict_bytes="no_winner",
            m5_supporting_ci_lower=0.010,
            m5_supporting_ci_upper=0.012,
            rationale="max_message_size supersession — investigate",
            expected_class="unexpected_supersession",
        )
    )
    out = tmp_path / "m5.md"
    write_m5_markdown(run, out)
    text = out.read_text()
    assert "Unexpected supersessions" in text
    assert "**[unexpected]**" in text


def test_write_m5_markdown_supersedes_sorted_changed_first(tmp_path: Path) -> None:
    """T047 — verdict-changed rows sort before verdict-confirmed rows."""
    run = _make_run()
    # Append a verdict_confirmed entry (verdicts match, loopback caveat True).
    run.supersedes_m4.append(
        SupersedesM4Entry(
            m4_axis="compression",
            m4_hidden_size=4096,
            m4_path="embed",
            m4_verdict_time="no_winner",
            m4_verdict_bytes="no_winner",
            m4_loopback_caveat=True,
            m5_verdict_time="no_winner",
            m5_verdict_bytes="no_winner",
            m5_supporting_ci_lower=0.0,
            m5_supporting_ci_upper=0.0,
            rationale="M5 confirms M4 verdict",
            expected_class="verdict_confirmed",
        )
    )
    out = tmp_path / "m5.md"
    write_m5_markdown(run, out)
    text = out.read_text()
    # The verdict-changed (loopback_resolution) row appears before the
    # verdict-confirmed row.
    changed_pos = text.index("**[changed]**")
    confirmed_pos = text.index("M5 confirms M4 verdict")
    assert changed_pos < confirmed_pos
