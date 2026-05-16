"""M6.1.1 Phase 1 diagnose orchestrator — gate-logic + I/O tests (T024)."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import pytest
from vllm_grpc_bench.m6_1_1_diagnose import (
    M6_1_1BaselineError,
    check_engine_version,
    evaluate_phase_1_gates,
    load_m6_1_baseline,
    read_existing_phase_1_runs,
    run_m6_1_1_diagnose,
)
from vllm_grpc_bench.m6_1_1_types import (
    PerturbationAudit,
    Phase1Classification,
    Phase1RunRecord,
)

# --- Baseline loader (FR-001 / FR-004) --------------------------------------


def test_load_baseline_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(M6_1_1BaselineError, match="not found"):
        load_m6_1_baseline(tmp_path / "missing.json")


def test_load_baseline_unparseable_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not valid json {{", encoding="utf-8")
    with pytest.raises(M6_1_1BaselineError, match="unparseable"):
        load_m6_1_baseline(p)


def test_load_baseline_wrong_schema_version_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema_version": "m6.v1"}), encoding="utf-8")
    with pytest.raises(M6_1_1BaselineError, match="schema_version"):
        load_m6_1_baseline(p)


def test_load_baseline_missing_engine_cost_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema_version": "m6_1.v1"}), encoding="utf-8")
    with pytest.raises(M6_1_1BaselineError, match="engine_cost_baseline"):
        load_m6_1_baseline(p)


def test_load_baseline_happy_path(tmp_path: Path) -> None:
    p = tmp_path / "good.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": "m6_1.v1",
                "engine_cost_baseline": [],
                "run_meta": {"engine_version": "0.20.1"},
            }
        ),
        encoding="utf-8",
    )
    data = load_m6_1_baseline(p)
    assert data["schema_version"] == "m6_1.v1"


# --- Engine version check (FR-004) ------------------------------------------


def test_engine_version_match_returns_ok() -> None:
    baseline = {"run_meta": {"engine_version": "0.20.1"}}
    ok, msg = check_engine_version(baseline, "0.20.1", allow_mismatch=False)
    assert ok is True
    assert msg is None


def test_engine_version_mismatch_blocks_without_allow_flag() -> None:
    baseline = {"run_meta": {"engine_version": "0.20.1"}}
    ok, msg = check_engine_version(baseline, "0.21.0", allow_mismatch=False)
    assert ok is False
    assert msg is not None
    assert "0.20.1" in msg
    assert "0.21.0" in msg


def test_engine_version_mismatch_with_allow_flag_returns_ok_with_annotation() -> None:
    baseline = {"run_meta": {"engine_version": "0.20.1"}}
    ok, msg = check_engine_version(baseline, "0.21.0", allow_mismatch=True)
    assert ok is True
    assert msg is not None
    assert "acknowledged" in msg


def test_engine_version_skipped_when_deployed_unknown() -> None:
    """deployed=None skips the check entirely (used by unit tests)."""
    baseline = {"run_meta": {"engine_version": "0.20.1"}}
    ok, msg = check_engine_version(baseline, None, allow_mismatch=False)
    assert ok is True
    assert msg is None


# --- phase_1_runs[] append-on-re-read (round-3 Q1, Research R-7) ------------


def test_read_existing_phase_1_runs_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_existing_phase_1_runs(tmp_path / "missing.json") == []


def test_read_existing_phase_1_runs_unparseable_returns_empty_with_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = tmp_path / "report.json"
    p.write_text("not valid json", encoding="utf-8")
    result = read_existing_phase_1_runs(p)
    assert result == []
    err = capsys.readouterr().err
    assert "unreadable" in err
    assert "starting fresh phase_1_runs" in err


def test_read_existing_phase_1_runs_round_trips(tmp_path: Path) -> None:
    p = tmp_path / "report.json"
    runs = [
        {
            "run_id": "run-1",
            "phase_1_classifications": {"chat_stream_c1_h4096": "drift_not_reproduced"},
        },
    ]
    p.write_text(json.dumps({"phase_1_runs": runs}), encoding="utf-8")
    out = read_existing_phase_1_runs(p)
    assert len(out) == 1
    assert out[0]["run_id"] == "run-1"


def test_read_existing_phase_1_runs_missing_key_returns_empty(tmp_path: Path) -> None:
    """A report missing phase_1_runs (e.g., an embryonic schema) → []."""
    p = tmp_path / "report.json"
    p.write_text(json.dumps({"schema_version": "m6_1_1.v1"}), encoding="utf-8")
    assert read_existing_phase_1_runs(p) == []


# --- FR-017 / FR-018 / round-2 Q4 gate evaluator ---------------------------


def _run_with_labels(*labels: Phase1Classification) -> Phase1RunRecord:
    classifications = {f"chat_stream_c{i + 1}_h4096": lab for i, lab in enumerate(labels)}
    return Phase1RunRecord(
        run_id="r",
        run_started_at="t",
        run_completed_at="t",
        wall_clock_s=0.0,
        multi_point_timings=[],
        phase_1_classifications=classifications,
        perturbation_audit=PerturbationAudit(per_cohort_per_cell={}, exceeded=False),
        n_per_cohort=50,
    )


def test_gate_uniform_instrumentation_artifact_actionable() -> None:
    runs = [
        _run_with_labels(
            "instrumentation_artifact", "instrumentation_artifact", "instrumentation_artifact"
        )
    ]
    code, _ = evaluate_phase_1_gates(runs)
    assert code == 0


def test_gate_uniform_channel_dependent_batching_actionable() -> None:
    runs = [
        _run_with_labels(
            "channel_dependent_batching",
            "channel_dependent_batching",
            "channel_dependent_batching",
        )
    ]
    code, _ = evaluate_phase_1_gates(runs)
    assert code == 0


def test_gate_uniform_drift_not_reproduced_single_run_triggers_rerun() -> None:
    runs = [
        _run_with_labels("drift_not_reproduced", "drift_not_reproduced", "drift_not_reproduced")
    ]
    code, msg = evaluate_phase_1_gates(runs)
    assert code == 3
    assert msg is not None
    assert "re-run" in msg


def test_gate_uniform_drift_not_reproduced_two_runs_confirms() -> None:
    """Two independent runs both uniform drift_not_reproduced → exit 0
    with the 'drift_not_reproduced_confirmed' signal in the message."""
    runs = [
        _run_with_labels("drift_not_reproduced", "drift_not_reproduced", "drift_not_reproduced"),
        _run_with_labels("drift_not_reproduced", "drift_not_reproduced", "drift_not_reproduced"),
    ]
    code, msg = evaluate_phase_1_gates(runs)
    assert code == 0
    assert msg == "drift_not_reproduced_confirmed"


def test_gate_mixed_single_run_triggers_rerun() -> None:
    runs = [
        _run_with_labels("instrumentation_artifact", "channel_dependent_batching", "inconclusive")
    ]
    code, msg = evaluate_phase_1_gates(runs)
    assert code == 3
    assert msg is not None
    assert "non-uniform" in msg


def test_gate_inconclusive_single_run_triggers_rerun() -> None:
    runs = [_run_with_labels("inconclusive", "inconclusive", "inconclusive")]
    code, msg = evaluate_phase_1_gates(runs)
    assert code == 3
    assert msg is not None


def test_gate_still_divergent_after_two_runs_triggers_split() -> None:
    runs = [
        _run_with_labels("instrumentation_artifact", "channel_dependent_batching", "inconclusive"),
        _run_with_labels("channel_dependent_batching", "instrumentation_artifact", "inconclusive"),
    ]
    code, msg = evaluate_phase_1_gates(runs)
    assert code == 5
    assert msg is not None
    assert "split_required" in msg or "successor sub-milestones" in msg


def test_gate_no_runs_returns_rerun_signal() -> None:
    code, msg = evaluate_phase_1_gates([])
    assert code == 3
    assert msg is not None


def test_gate_no_chat_stream_classifications_returns_rerun() -> None:
    """An embed-only run record (no chat_stream classifications) should
    be treated as missing data, not as a uniform actionable result."""
    run = Phase1RunRecord(
        run_id="r",
        run_started_at="t",
        run_completed_at="t",
        wall_clock_s=0.0,
        multi_point_timings=[],
        phase_1_classifications={"embed_c1_h4096": "instrumentation_artifact"},  # type: ignore[dict-item]
        perturbation_audit=PerturbationAudit(per_cohort_per_cell={}, exceeded=False),
        n_per_cohort=50,
    )
    code, msg = evaluate_phase_1_gates([run])
    assert code == 3
    assert msg is not None


# --- Orchestrator end-to-end (FR-001 / FR-012 / FR-017 / FR-018 wiring) ----


def _baseline_path(tmp_path: Path, *, engine_version: str = "0.20.1") -> Path:
    p = tmp_path / "m6_1-baseline.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": "m6_1.v1",
                "engine_cost_baseline": [],
                "run_meta": {"engine_version": engine_version},
            }
        ),
        encoding="utf-8",
    )
    return p


def _make_args(tmp_path: Path, *, allow_engine_mismatch: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        m6_1_1_m6_1_baseline=_baseline_path(tmp_path),
        m6_1_1_report_json_out=tmp_path / "m6_1_1.json",
        m6_1_1_allow_engine_mismatch=allow_engine_mismatch,
    )


def test_orchestrator_missing_baseline_returns_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(
        m6_1_1_m6_1_baseline=tmp_path / "missing.json",
        m6_1_1_report_json_out=tmp_path / "out.json",
        m6_1_1_allow_engine_mismatch=False,
    )
    rc = asyncio.run(
        run_m6_1_1_diagnose(
            args,
            sweep_hook=lambda a, b: _run_with_labels(
                "instrumentation_artifact", "instrumentation_artifact", "instrumentation_artifact"
            ),
        )
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "not found" in err


def test_orchestrator_engine_version_mismatch_returns_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _make_args(tmp_path, allow_engine_mismatch=False)
    rc = asyncio.run(
        run_m6_1_1_diagnose(
            args,
            sweep_hook=lambda a, b: _run_with_labels(
                "instrumentation_artifact", "instrumentation_artifact", "instrumentation_artifact"
            ),
            deployed_engine_version="0.21.0",
        )
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "engine_version mismatch" in err


def test_orchestrator_engine_version_mismatch_with_allow_flag_proceeds(tmp_path: Path) -> None:
    args = _make_args(tmp_path, allow_engine_mismatch=True)
    rc = asyncio.run(
        run_m6_1_1_diagnose(
            args,
            sweep_hook=lambda a, b: _run_with_labels(
                "instrumentation_artifact", "instrumentation_artifact", "instrumentation_artifact"
            ),
            deployed_engine_version="0.21.0",
        )
    )
    assert rc == 0


def test_orchestrator_perturbation_exceeded_exits_code_4(tmp_path: Path) -> None:
    from vllm_grpc_bench.m6_1_1_types import M6_1_1Cell, MultiPointTimings, PerSegmentAggregate

    def sweep(args: argparse.Namespace, baseline: dict) -> Phase1RunRecord:
        cell = M6_1_1Cell(path="chat_stream", concurrency=1, hidden_size=4096)
        # All three cohorts on c=1, one over budget (650 µs).
        mpts = [
            MultiPointTimings(
                cohort=c,  # type: ignore[arg-type]
                cell=cell,
                engine_ttft_ms_mean=44.0,
                engine_ttft_ms_ci_half_width=0.5,
                per_segment=PerSegmentAggregate(
                    seg_ab_ms_mean=2.0,
                    seg_ab_ms_ci_half_width=0.1,
                    seg_bc_ms_mean=40.0,
                    seg_bc_ms_ci_half_width=0.1,
                    seg_cd_ms_mean=2.0,
                    seg_cd_ms_ci_half_width=0.1,
                    n_samples=50,
                ),
                perturbation_total_us_mean=650.0 if c == "default_grpc" else 0.2,
            )
            for c in ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed")
        ]
        return Phase1RunRecord(
            run_id="r",
            run_started_at="t",
            run_completed_at="t",
            wall_clock_s=0.0,
            multi_point_timings=mpts,
            phase_1_classifications={"chat_stream_c1_h4096": "instrumentation_artifact"},
            perturbation_audit=PerturbationAudit(per_cohort_per_cell={}, exceeded=False),
            n_per_cohort=50,
        )

    args = _make_args(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(run_m6_1_1_diagnose(args, sweep_hook=sweep))
    assert exc_info.value.code == 4


def test_orchestrator_uniform_actionable_returns_exit_0(tmp_path: Path) -> None:
    args = _make_args(tmp_path)
    rc = asyncio.run(
        run_m6_1_1_diagnose(
            args,
            sweep_hook=lambda a, b: _run_with_labels(
                "instrumentation_artifact", "instrumentation_artifact", "instrumentation_artifact"
            ),
        )
    )
    assert rc == 0


def test_orchestrator_mixed_classifications_returns_exit_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _make_args(tmp_path)
    rc = asyncio.run(
        run_m6_1_1_diagnose(
            args,
            sweep_hook=lambda a, b: _run_with_labels(
                "instrumentation_artifact", "channel_dependent_batching", "inconclusive"
            ),
        )
    )
    assert rc == 3
    assert "re-run" in capsys.readouterr().err


def test_orchestrator_append_on_re_read_accumulates_runs(tmp_path: Path) -> None:
    """Second invocation reads the prior report and accumulates the new
    Phase 1 record so the gate evaluator sees both runs (round-3 Q1)."""
    args = _make_args(tmp_path)
    # First invocation writes a single-run drift_not_reproduced report.
    captured_records: list[list[Phase1RunRecord]] = []

    def write_report(_a, records, _msg):
        # Persist the records as the m6_1_1 report so the next invocation
        # finds them on disk.
        Path(args.m6_1_1_report_json_out).write_text(
            json.dumps(
                {
                    "schema_version": "m6_1_1.v1",
                    "phase_1_runs": [
                        {
                            "run_id": r.run_id,
                            "phase_1_classifications": dict(r.phase_1_classifications),
                            "wall_clock_s": r.wall_clock_s,
                            "n_per_cohort": r.n_per_cohort,
                        }
                        for r in records
                    ],
                }
            ),
            encoding="utf-8",
        )
        captured_records.append(records)

    rc1 = asyncio.run(
        run_m6_1_1_diagnose(
            args,
            sweep_hook=lambda a, b: _run_with_labels(
                "drift_not_reproduced", "drift_not_reproduced", "drift_not_reproduced"
            ),
            write_report=write_report,
            supersedence_hook=lambda **_: None,
        )
    )
    assert rc1 == 3  # single-run drift_not_reproduced needs a confirming re-run.

    # Second invocation should see the prior run in phase_1_runs[] and
    # close at drift_not_reproduced_confirmed (exit 0).
    rc2 = asyncio.run(
        run_m6_1_1_diagnose(
            args,
            sweep_hook=lambda a, b: _run_with_labels(
                "drift_not_reproduced", "drift_not_reproduced", "drift_not_reproduced"
            ),
            write_report=write_report,
            supersedence_hook=lambda **_: None,
        )
    )
    assert rc2 == 0
    # The second invocation's write_report should see 2 runs accumulated.
    assert len(captured_records[-1]) == 2
