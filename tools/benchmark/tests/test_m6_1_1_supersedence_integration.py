"""M6.1.1 supersedence integration test (T033).

End-to-end test: drive run_m6_1_1_diagnose / run_m6_1_1_phase_2 against
tmp_path-built M6.1 fixtures and verify the supersedence writers fire on
the expected close paths (FR-023 / FR-024 / FR-015c). Uses the real
``apply_supersedence`` writer (not a no-op hook) so byte-stability + line
insertion behave as M6.1.1's PR would in production.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from vllm_grpc_bench.m6_1_1_diagnose import run_m6_1_1_diagnose
from vllm_grpc_bench.m6_1_1_phase2 import run_m6_1_1_phase_2
from vllm_grpc_bench.m6_1_1_types import (
    BaselineCellEntry,
    EmbedRegressionCheckResult,
    EmbedRegressionResult,
    M6_1_1Cell,
    M6_1_1Cohort,
    PerturbationAudit,
    Phase1Classification,
    Phase1RunRecord,
    Phase2Choice,
)


def _make_m6_1_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    """Write a minimal M6.1 JSON + markdown pair to tmp_path."""
    json_path = tmp_path / "m6_1-real-prompt-embeds.json"
    md_path = tmp_path / "m6_1-real-prompt-embeds.md"
    json_path.write_text(
        json.dumps(
            {
                "schema_version": "m6_1.v1",
                "run_meta": {"engine_version": "0.20.1"},
                "engine_cost_baseline": [
                    {
                        "cell": {"path": "embed", "concurrency": 1, "hidden_size": 4096},
                        "engine_cost_mean_ms": 338.0,
                    },
                    {
                        "cell": {"path": "chat_stream", "concurrency": 1, "hidden_size": 4096},
                        "engine_cost_mean_ms": 44.0,
                    },
                ],
                "supersedes_m6_under_enable_prompt_embeds": [],
            }
        ),
        encoding="utf-8",
    )
    md_path.write_text(
        "# M6.1\n\n## chat_stream verdict\n\nThe chat_stream verdict text.\n",
        encoding="utf-8",
    )
    return json_path, md_path


def _make_args(tmp_path: Path) -> tuple[argparse.Namespace, Path]:
    """Build args + a Phase 1 report path under tmp_path."""
    json_path, _ = _make_m6_1_fixtures(tmp_path)
    report_path = tmp_path / "m6_1_1-engine-cost-instrumentation.json"
    args = argparse.Namespace(
        m6_1_1_m6_1_baseline=json_path,
        m6_1_1_report_json_out=report_path,
        m6_1_1_allow_engine_mismatch=False,
    )
    return args, report_path


def _write_phase_1_report(
    report_path: Path,
    classifications: dict[str, str],
) -> None:
    report_path.write_text(
        json.dumps({"phase_1_classifications": classifications}),
        encoding="utf-8",
    )


def _run_with_labels(*labels: Phase1Classification) -> Phase1RunRecord:
    return Phase1RunRecord(
        run_id="r",
        run_started_at="t",
        run_completed_at="t",
        wall_clock_s=0.0,
        multi_point_timings=[],
        phase_1_classifications={
            f"chat_stream_c{i + 1}_h4096": lab for i, lab in enumerate(labels)
        },
        perturbation_audit=PerturbationAudit(per_cohort_per_cell={}, exceeded=False),
        n_per_cohort=50,
    )


def _verified_sweep_result(*, embed_warnings: int = 0) -> tuple:
    """Build a synthetic verified-sweep result; matches phase2 test fixture shape."""
    chat_cells: list[BaselineCellEntry] = []
    embed_cells: list[BaselineCellEntry] = []
    cohorts: tuple[M6_1_1Cohort, ...] = (
        "rest_https_edge",
        "default_grpc",
        "tuned_grpc_multiplexed",
    )
    for concurrency in (1, 4, 8):
        for cohort in cohorts:
            chat_cells.append(
                BaselineCellEntry(
                    cell=M6_1_1Cell(path="chat_stream", concurrency=concurrency, hidden_size=4096),
                    cohort=cohort,
                    engine_ttft_ms_mean=42.0,
                    engine_ttft_ms_ci_half_width=0.5,
                    engine_tpot_ms_mean=8.0,
                    engine_tpot_ms_ci_half_width=0.1,
                    engine_forward_ms_mean=None,
                    engine_forward_ms_ci_half_width=None,
                    n_successes=100,
                    regression_warning=None,
                )
            )
            embed_cells.append(
                BaselineCellEntry(
                    cell=M6_1_1Cell(path="embed", concurrency=concurrency, hidden_size=4096),
                    cohort=cohort,
                    engine_ttft_ms_mean=None,
                    engine_ttft_ms_ci_half_width=None,
                    engine_tpot_ms_mean=None,
                    engine_tpot_ms_ci_half_width=None,
                    engine_forward_ms_mean=338.0,
                    engine_forward_ms_ci_half_width=2.0,
                    n_successes=100,
                    regression_warning=False,
                )
            )
    per_entry = [
        EmbedRegressionResult(
            cell=e.cell,
            cohort=e.cohort,
            m6_1_engine_forward_ms_mean=338.0,
            m6_1_1_engine_forward_ms_mean=e.engine_forward_ms_mean or 338.0,
            delta_pct=0.0 if idx >= embed_warnings else 0.07,
            embed_regression_warning=(idx < embed_warnings),
        )
        for idx, e in enumerate(embed_cells)
    ]
    embed_reg = EmbedRegressionCheckResult(
        per_entry=per_entry,
        n_warnings=embed_warnings,
        all_within_tolerance=(embed_warnings == 0),
        acknowledged_count=0,
    )
    return (
        chat_cells,
        embed_cells,
        embed_reg,
        {f"chat_stream_c{c}_h4096": True for c in (1, 4, 8)},
        {f"chat_stream_c{c}_h4096": False for c in (1, 4, 8)},
        True,
        "expected under symmetrisation",
    )


# --- Phase 2(a) verified close → supersedence writes -----------------------


def test_phase_2a_verified_writes_supersedence_to_m6_1_files(tmp_path: Path) -> None:
    args, report = _make_args(tmp_path)
    _write_phase_1_report(
        report,
        {f"chat_stream_c{c}_h4096": "instrumentation_artifact" for c in (1, 4, 8)},
    )
    rc = asyncio.run(
        run_m6_1_1_phase_2(
            args,
            sweep_hook=lambda a, b: _verified_sweep_result(),
            date_yyyy_mm_dd="2026-05-17",
        )
    )
    assert rc == 0
    # M6.1 JSON now has methodology_supersedence with phase_2a_verified
    after = json.loads(args.m6_1_1_m6_1_baseline.read_text(encoding="utf-8"))
    assert "methodology_supersedence" in after
    ms = after["methodology_supersedence"]
    assert ms["phase_2_path"] == "phase_2a_verified"
    assert "instrumentation_artifact" in ms["summary"]
    # M6.1 markdown has the forward pointer line
    md = args.m6_1_1_m6_1_baseline.with_suffix(".md").read_text(encoding="utf-8")
    assert "Methodology supersedence (2026-05-17)" in md
    assert "m6_1_1-engine-cost-instrumentation.md" in md


def test_phase_2a_verified_preserves_m6_1_other_keys_byte_stable(tmp_path: Path) -> None:
    """FR-023 / SC-006: all M6.1 keys except methodology_supersedence are unchanged."""
    args, report = _make_args(tmp_path)
    before = json.loads(args.m6_1_1_m6_1_baseline.read_text(encoding="utf-8"))
    _write_phase_1_report(
        report,
        {f"chat_stream_c{c}_h4096": "instrumentation_artifact" for c in (1, 4, 8)},
    )
    asyncio.run(
        run_m6_1_1_phase_2(
            args,
            sweep_hook=lambda a, b: _verified_sweep_result(),
            date_yyyy_mm_dd="2026-05-17",
        )
    )
    after = json.loads(args.m6_1_1_m6_1_baseline.read_text(encoding="utf-8"))
    for key, val in before.items():
        assert key in after, f"M6.1 key {key!r} lost after supersedence"
        assert after[key] == val, f"M6.1 key {key!r} mutated"


# --- Phase 2(b) documented close → supersedence with batching summary ------


def test_phase_2b_documented_writes_supersedence_with_batching_summary(
    tmp_path: Path,
) -> None:
    args, report = _make_args(tmp_path)
    _write_phase_1_report(
        report,
        {f"chat_stream_c{c}_h4096": "channel_dependent_batching" for c in (1, 4, 8)},
    )
    contracts_md = tmp_path / "instrumentation.md"
    contracts_md.write_text(
        "## M6.1.1: Channel-Dependent Batching Effect\n\nBody.\n", encoding="utf-8"
    )
    rc = asyncio.run(
        run_m6_1_1_phase_2(
            args,
            contracts_path=contracts_md,
            date_yyyy_mm_dd="2026-05-17",
        )
    )
    assert rc == 0
    after = json.loads(args.m6_1_1_m6_1_baseline.read_text(encoding="utf-8"))
    ms = after["methodology_supersedence"]
    assert ms["phase_2_path"] == "phase_2b_documented"
    assert "channel_dependent_batching" in ms["summary"]


# --- drift_not_reproduced_confirmed close (diagnose-side) ------------------


def test_drift_not_reproduced_confirmed_writes_supersedence(tmp_path: Path) -> None:
    args, report = _make_args(tmp_path)
    # Seed phase_1_runs[0] with a uniform drift_not_reproduced run.
    report.write_text(
        json.dumps(
            {
                "schema_version": "m6_1_1.v1",
                "phase_1_runs": [
                    {
                        "run_id": "run-1",
                        "phase_1_classifications": {
                            f"chat_stream_c{c}_h4096": "drift_not_reproduced" for c in (1, 4, 8)
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    rc = asyncio.run(
        run_m6_1_1_diagnose(
            args,
            sweep_hook=lambda a, b: _run_with_labels(
                "drift_not_reproduced", "drift_not_reproduced", "drift_not_reproduced"
            ),
            date_yyyy_mm_dd="2026-05-17",
        )
    )
    assert rc == 0
    after = json.loads(args.m6_1_1_m6_1_baseline.read_text(encoding="utf-8"))
    ms = after["methodology_supersedence"]
    assert ms["phase_2_path"] == "drift_not_reproduced_confirmed"
    assert "two independent" in ms["summary"]


# --- split_required: NO supersedence (round-2 Q4) --------------------------


def test_split_required_does_not_write_supersedence(tmp_path: Path) -> None:
    """Under split_required, M6.1's files are NOT modified — the annotation
    is deferred to the successor sub-milestones."""
    args, report = _make_args(tmp_path)
    # Seed two divergent runs to trigger split_required.
    report.write_text(
        json.dumps(
            {
                "schema_version": "m6_1_1.v1",
                "phase_1_runs": [
                    {
                        "run_id": "run-1",
                        "phase_1_classifications": {
                            "chat_stream_c1_h4096": "instrumentation_artifact",
                            "chat_stream_c4_h4096": "channel_dependent_batching",
                            "chat_stream_c8_h4096": "inconclusive",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    before = json.loads(args.m6_1_1_m6_1_baseline.read_text(encoding="utf-8"))
    rc = asyncio.run(
        run_m6_1_1_diagnose(
            args,
            sweep_hook=lambda a, b: _run_with_labels(
                "channel_dependent_batching", "instrumentation_artifact", "inconclusive"
            ),
            date_yyyy_mm_dd="2026-05-17",
        )
    )
    assert rc == 5
    after = json.loads(args.m6_1_1_m6_1_baseline.read_text(encoding="utf-8"))
    # M6.1 JSON unmodified (no methodology_supersedence key added).
    assert "methodology_supersedence" not in after
    assert before == after


# --- embed_regression_acknowledged → per-row notes appended ----------------


def test_phase_2a_with_embed_regression_acknowledged_appends_per_row_notes(
    tmp_path: Path,
) -> None:
    """FR-015c: when the operator acknowledges an embed regression, per-row
    notes are appended to the supersedes_m6_under_enable_prompt_embeds table."""
    args, report = _make_args(tmp_path)
    # Add a few embed rows to M6.1's markdown so the per-row writer has
    # something to annotate.
    md_path = args.m6_1_1_m6_1_baseline.with_suffix(".md")
    md_path.write_text(
        "# M6.1\n\n"
        "## chat_stream verdict\n\n"
        "Verdict text.\n\n"
        "## Supersedes M6 under enable_prompt_embeds\n\n"
        "| cell | cohort | mean_ms | notes |\n"
        "|------|--------|---------|-------|\n"
        "| embed_c1_h4096 | rest_https_edge | 338.0 | base |\n"
        "| embed_c1_h4096 | default_grpc | 339.5 | base |\n",
        encoding="utf-8",
    )
    _write_phase_1_report(
        report,
        {f"chat_stream_c{c}_h4096": "instrumentation_artifact" for c in (1, 4, 8)},
    )
    choice = Phase2Choice(
        embed_regression_acknowledged=True,
        embed_regression_justification="known cross-cohort variance",
    )
    rc = asyncio.run(
        run_m6_1_1_phase_2(
            args,
            sweep_hook=lambda a, b: _verified_sweep_result(embed_warnings=1),
            phase_2_choice=choice,
            date_yyyy_mm_dd="2026-05-17",
        )
    )
    assert rc == 0
    md = md_path.read_text(encoding="utf-8")
    # The first warning entry is (embed_c1_h4096, rest_https_edge) per the
    # synthetic fixture ordering (3 cells × 3 cohorts; idx 0 fires).
    assert "embed_regression_acknowledged" in md


# --- pointer field resolves to an existing file (SC-006) -------------------


def test_supersedence_pointer_targets_existing_file_relative_to_repo_root(
    tmp_path: Path,
) -> None:
    """After Phase 2 close, the pointer field in M6.1's
    methodology_supersedence resolves to an existing file. We exercise the
    pointer-target invariant against the tmp_path-derived M6.1.1 markdown
    that the orchestrator emits alongside the JSON."""
    args, report = _make_args(tmp_path)
    # Stage an M6.1.1 markdown alongside the JSON so the pointer target
    # resolves under tmp_path (the orchestrator doesn't actually create
    # the M6.1.1 markdown without a reporter; we simulate the post-close
    # state by writing a placeholder).
    expected_m6_1_1_md = args.m6_1_1_report_json_out.with_suffix(".md")
    expected_m6_1_1_md.write_text("# M6.1.1 (stub)\n", encoding="utf-8")
    _write_phase_1_report(
        report,
        {f"chat_stream_c{c}_h4096": "instrumentation_artifact" for c in (1, 4, 8)},
    )
    asyncio.run(
        run_m6_1_1_phase_2(
            args,
            sweep_hook=lambda a, b: _verified_sweep_result(),
            date_yyyy_mm_dd="2026-05-17",
        )
    )
    after = json.loads(args.m6_1_1_m6_1_baseline.read_text(encoding="utf-8"))
    pointer = after["methodology_supersedence"]["pointer"]
    # The pointer is stored as the M6.1.1 markdown path string. In this
    # test it points to tmp_path/m6_1_1-engine-cost-instrumentation.md.
    assert Path(pointer).is_file()
