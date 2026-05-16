"""M6.1.1 reporter — markdown + JSON shape tests (T026)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from vllm_grpc_bench.m6_1_1_reporter import (
    assert_strict_superset,
    build_sentinel,
    render_json,
    render_markdown,
    write_m6_1_1_report,
)
from vllm_grpc_bench.m6_1_1_types import (
    DriftNotReproducedConfirmedOutcome,
    M6_1_1Cell,
    M6_1_1Run,
    M6_1_1RunMeta,
    MultiPointTimings,
    PerSegmentAggregate,
    PerturbationAudit,
    Phase1RunRecord,
    Phase2aVerifiedOutcome,
    Phase2bDocumentedOutcome,
    Phase2Path,
    SplitRequiredOutcome,
)


def _meta(phase_2_path: Phase2Path) -> M6_1_1RunMeta:
    return M6_1_1RunMeta(
        git_sha="deadbeef",
        hostname="modal",
        modal_function_id=None,
        gpu_type="A10G",
        modal_region="eu-west-1",
        model_identifier="Qwen/Qwen3-8B",
        hidden_size=4096,
        cold_start_s=12.0,
        max_model_len=2048,
        gpu_memory_utilization=0.92,
        engine_version="0.20.1",
        m6_1_baseline_engine_version="0.20.1",
        torch_version="2.11.0",
        M6_1_1_BASE_SEED=42,
        seq_len=512,
        phase_1_n=50,
        phase_2_path=phase_2_path,
        run_started_at="2026-05-17T09:00:00Z",
        run_completed_at="2026-05-17T09:30:00Z",
    )


def _phase_1_run(*, run_id: str = "run-1") -> Phase1RunRecord:
    cell = M6_1_1Cell(path="chat_stream", concurrency=1, hidden_size=4096)
    mpts = [
        MultiPointTimings(
            cohort=c,  # type: ignore[arg-type]
            cell=cell,
            engine_ttft_ms_mean=43.5 + i,
            engine_ttft_ms_ci_half_width=0.5,
            per_segment=PerSegmentAggregate(
                seg_ab_ms_mean=2.0,
                seg_ab_ms_ci_half_width=0.1,
                seg_bc_ms_mean=40.0,
                seg_bc_ms_ci_half_width=0.1,
                seg_cd_ms_mean=1.5,
                seg_cd_ms_ci_half_width=0.1,
                n_samples=50,
            ),
            perturbation_total_us_mean=0.24,
        )
        for i, c in enumerate(("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"))
    ]
    return Phase1RunRecord(
        run_id=run_id,
        run_started_at="2026-05-17T09:00:00Z",
        run_completed_at="2026-05-17T09:30:00Z",
        wall_clock_s=1800.0,
        multi_point_timings=mpts,
        phase_1_classifications={
            "chat_stream_c1_h4096": "instrumentation_artifact",
        },
        perturbation_audit=PerturbationAudit(per_cohort_per_cell={}, exceeded=False),
        n_per_cohort=50,
    )


def _run(
    phase_2_path: Phase2Path = "phase_2_pending", *, n_runs: int = 1, outcome=None
) -> M6_1_1Run:
    return M6_1_1Run(
        schema_version="m6_1_1.v1",
        run_id="2026-05-17T09:30:00Z-deadbe7",
        run_started_at="2026-05-17T09:00:00Z",
        run_completed_at="2026-05-17T09:30:00Z",
        run_meta=_meta(phase_2_path),
        phase_1_classifications={"chat_stream_c1_h4096": "instrumentation_artifact"},
        phase_1_runs=[_phase_1_run(run_id=f"run-{i + 1}") for i in range(n_runs)],
        multi_point_timings=[],
        phase_2_outcome=outcome,
        phase_2_choice=None,
        chat_stream_baseline_post_symmetrisation=build_sentinel(phase_2_path),
        embed_baseline_post_symmetrisation=build_sentinel(phase_2_path, is_embed=True),
        embed_regression_check=None,
        m6_1_baseline_pointer="docs/benchmarks/m6_1-real-prompt-embeds.json",
        methodology_supersedence="",
    )


# --- Sentinel builders ------------------------------------------------------


@pytest.mark.parametrize(
    "phase_2_path,expected_source",
    [
        ("phase_2a_verified", "m6_1_1"),
        ("phase_2b_documented", "m6_1"),
        ("drift_not_reproduced_confirmed", "m6_1"),
        ("phase_2_pending", "not_applicable"),
        ("split_required", "not_applicable"),
    ],
)
def test_sentinel_dispatch_by_phase_2_path(phase_2_path: Phase2Path, expected_source: str) -> None:
    sentinel = build_sentinel(phase_2_path)
    assert sentinel.phase_2_path == phase_2_path
    assert sentinel.baseline_source == expected_source


def test_sentinel_under_phase_2a_verified_carries_self_pointer() -> None:
    sentinel = build_sentinel("phase_2a_verified")
    assert sentinel.pointer == "docs/benchmarks/m6_1_1-engine-cost-instrumentation.json"


def test_sentinel_under_phase_2b_points_to_m6_1() -> None:
    sentinel = build_sentinel("phase_2b_documented")
    assert sentinel.pointer == "docs/benchmarks/m6_1-real-prompt-embeds.json"


# --- Markdown 6-section structure (FR-020) ----------------------------------


@pytest.mark.parametrize(
    "phase_2_path",
    [
        "phase_2a_verified",
        "phase_2b_documented",
        "phase_2_pending",
        "drift_not_reproduced_confirmed",
        "split_required",
    ],
)
def test_markdown_contains_all_six_sections_in_order(phase_2_path: Phase2Path) -> None:
    outcome = None
    if phase_2_path == "phase_2a_verified":
        outcome = Phase2aVerifiedOutcome(
            drift_cleared_per_cell={"chat_stream_c1_h4096": True},
            engine_cost_drift_warning_per_cell={"chat_stream_c1_h4096": False},
            chat_stream_control_drift_warning=False,
            chat_stream_control_drift_note="",
        )
    elif phase_2_path == "phase_2b_documented":
        outcome = Phase2bDocumentedOutcome(
            contracts_heading_path="contracts/instrumentation.md",
            contracts_heading_text="## M6.1.1: Channel-Dependent Batching Effect",
        )
    elif phase_2_path == "drift_not_reproduced_confirmed":
        outcome = DriftNotReproducedConfirmedOutcome(
            note="non-reproduction in two independent runs",
            confirming_run_ids=("run-1", "run-2"),
        )
    elif phase_2_path == "split_required":
        outcome = SplitRequiredOutcome(
            per_cell_classifications_after_reconfirmation={},
            proposed_split_shape="M6.1.1a / M6.1.1b",
            operator_note="persistent divergence",
        )
    body = render_markdown(_run(phase_2_path, outcome=outcome))
    sections = [
        "# M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation",
        "## Methodology",
        "## Multi-Point Timing Table",
        "## Root-Cause Attribution",
        "## Phase 2 Outcome",
        "## Methodology Supersedence",
    ]
    last_idx = -1
    for s in sections:
        idx = body.find(s)
        assert idx != -1, f"Missing section: {s!r}"
        assert idx > last_idx, f"Section out of order: {s!r} appears before previous section"
        last_idx = idx


def test_markdown_under_phase_2_pending_describes_next_steps() -> None:
    body = render_markdown(_run("phase_2_pending"))
    assert "Phase 2 not yet run" in body
    assert "--m6_1_1" in body


def test_markdown_multi_point_table_renders_one_subsection_per_run() -> None:
    """phase_1_runs[] length 2 → markdown renders both run sub-sections."""
    body = render_markdown(_run(n_runs=2))
    assert "Run 1 — `run-1`" in body
    assert "Run 2 — `run-2`" in body


def test_markdown_root_cause_attribution_includes_formula_narrative() -> None:
    body = render_markdown(_run())
    assert "Root-Cause Attribution" in body
    assert "instrumentation_artifact" in body
    # Narrative for the classification is present (SC-010 reproducibility hint)
    assert "≥80%" in body
    assert "Phase 2(a) symmetrisation" in body


# --- JSON companion shape (FR-021) ------------------------------------------


def test_json_has_all_top_level_keys_under_phase_2_pending() -> None:
    payload = render_json(_run("phase_2_pending"))
    expected_keys = {
        "schema_version",
        "run_id",
        "run_started_at",
        "run_completed_at",
        "run_meta",
        "phase_1_classifications",
        "phase_1_runs",
        "multi_point_timings",
        "phase_2_outcome",
        "phase_2_choice",
        "chat_stream_baseline_post_symmetrisation",
        "embed_baseline_post_symmetrisation",
        "embed_regression_check",
        "m6_1_baseline_pointer",
        "methodology_supersedence",
    }
    assert set(payload.keys()) == expected_keys


def test_json_schema_version_is_m6_1_1_v1() -> None:
    payload = render_json(_run())
    assert payload["schema_version"] == "m6_1_1.v1"


def test_json_sentinel_under_phase_2_pending_carries_not_applicable() -> None:
    payload = render_json(_run("phase_2_pending"))
    cs = payload["chat_stream_baseline_post_symmetrisation"]
    assert cs["baseline_source"] == "not_applicable"
    assert cs["pointer"] is None
    assert cs["cells"] is None


def test_json_phase_2_outcome_none_when_pending() -> None:
    payload = render_json(_run("phase_2_pending"))
    assert payload["phase_2_outcome"] is None


def test_json_phase_2_outcome_dict_when_verified() -> None:
    outcome = Phase2aVerifiedOutcome(
        drift_cleared_per_cell={"chat_stream_c1_h4096": True},
        engine_cost_drift_warning_per_cell={"chat_stream_c1_h4096": False},
        chat_stream_control_drift_warning=True,
        chat_stream_control_drift_note="expected under symmetrisation",
    )
    payload = render_json(_run("phase_2a_verified", outcome=outcome))
    assert payload["phase_2_outcome"]["chat_stream_control_drift_warning"] is True


def test_json_phase_1_runs_preserves_most_recent_at_end() -> None:
    """phase_1_runs is append-ordered (round-3 Q1) — most recent at index -1."""
    payload = render_json(_run(n_runs=2))
    assert len(payload["phase_1_runs"]) == 2
    assert payload["phase_1_runs"][0]["run_id"] == "run-1"
    assert payload["phase_1_runs"][1]["run_id"] == "run-2"


def test_json_round_trips_via_json_dumps() -> None:
    """The rendered payload must be JSON-serialisable (Pydantic-free path)."""
    payload = render_json(_run())
    blob = json.dumps(payload)
    parsed = json.loads(blob)
    assert parsed["schema_version"] == "m6_1_1.v1"


# --- write_m6_1_1_report end-to-end ----------------------------------------


def test_write_m6_1_1_report_produces_both_files(tmp_path: Path) -> None:
    run = _run("phase_2_pending")
    md_path = tmp_path / "out" / "m6_1_1.md"
    json_path = tmp_path / "out" / "m6_1_1.json"
    write_m6_1_1_report(run, md_path, json_path)
    assert md_path.is_file()
    assert json_path.is_file()
    assert "# M6.1.1" in md_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "m6_1_1.v1"


def test_write_m6_1_1_report_overwrites_on_re_invocation(tmp_path: Path) -> None:
    """Round-3 Q1: each invocation overwrites; phase_1_runs[] is the
    accumulator (managed by the orchestrator, not the reporter)."""
    md_path = tmp_path / "m6_1_1.md"
    json_path = tmp_path / "m6_1_1.json"
    write_m6_1_1_report(_run("phase_2_pending"), md_path, json_path)
    write_m6_1_1_report(
        _run(
            "phase_2a_verified",
            outcome=Phase2aVerifiedOutcome(
                drift_cleared_per_cell={},
                engine_cost_drift_warning_per_cell={},
                chat_stream_control_drift_warning=False,
                chat_stream_control_drift_note="",
            ),
        ),
        md_path,
        json_path,
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["run_meta"]["phase_2_path"] == "phase_2a_verified"


# --- FR-022 strict-superset check -------------------------------------------


def test_strict_superset_passes_with_aliased_m6_1_keys() -> None:
    """M6.1's engine_cost_baseline + supersedes_m6_under_enable_prompt_embeds
    are reachable via M6.1.1's sentinel-aliased keys."""
    payload = render_json(_run())
    assert_strict_superset(
        payload,
        m6_1_keys=[
            "engine_cost_baseline",  # aliased to chat_stream_baseline_post_symmetrisation
            "supersedes_m6_under_enable_prompt_embeds",  # aliased to methodology_supersedence
            "schema_version",
            "run_id",
            "run_meta",
        ],
    )


def test_strict_superset_fails_when_required_key_absent() -> None:
    payload = render_json(_run())
    with pytest.raises(AssertionError, match="missing M6.1 keys"):
        assert_strict_superset(payload, m6_1_keys=["nonexistent_key"])


# --- Reproducer sanity check (SC-010) ---------------------------------------


def test_markdown_includes_per_cohort_timing_data_for_hand_classification(tmp_path: Path) -> None:
    """SC-010: the operator can reproduce the classification by hand from
    the published multi-point timing table. Verify the cohort means + segment
    deltas are all present in the rendered table."""
    body = render_markdown(_run())
    # All three cohorts mentioned in the timing table
    assert "rest_https_edge" in body
    assert "default_grpc" in body
    assert "tuned_grpc_multiplexed" in body
    # All three segment columns present
    assert "seg_ab_ms" in body
    assert "seg_bc_ms" in body
    assert "seg_cd_ms" in body
