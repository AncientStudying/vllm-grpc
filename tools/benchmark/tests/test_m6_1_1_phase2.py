"""M6.1.1 Phase 2 orchestrator — branch + gate tests (T030)."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import pytest
from vllm_grpc_bench.m6_1_1_phase2 import (
    Phase2OutcomeBundle,
    read_phase_1_classifications,
    run_m6_1_1_phase_2,
)
from vllm_grpc_bench.m6_1_1_types import (
    BaselineCellEntry,
    EmbedRegressionCheckResult,
    EmbedRegressionResult,
    M6_1_1Cell,
    M6_1_1Cohort,
    Phase2Choice,
)

# --- Fixtures ---------------------------------------------------------------


def _make_baseline(path: Path, *, engine_version: str = "0.20.1") -> Path:
    p = path / "m6_1-baseline.json"
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


def _make_phase_1_report(
    path: Path,
    classifications: dict[str, str],
) -> Path:
    p = path / "m6_1_1-report.json"
    p.write_text(
        json.dumps({"phase_1_classifications": classifications}),
        encoding="utf-8",
    )
    return p


def _make_args(
    tmp_path: Path,
    *,
    phase_1_classifications: dict[str, str] | None = None,
    allow_engine_mismatch: bool = False,
) -> argparse.Namespace:
    baseline = _make_baseline(tmp_path)
    if phase_1_classifications is not None:
        report = _make_phase_1_report(tmp_path, phase_1_classifications)
    else:
        report = tmp_path / "m6_1_1-report.json"
    return argparse.Namespace(
        m6_1_1_m6_1_baseline=baseline,
        m6_1_1_report_json_out=report,
        m6_1_1_allow_engine_mismatch=allow_engine_mismatch,
    )


def _verified_sweep_result(
    *,
    embed_warnings: int = 0,
) -> tuple:
    """Build a synthetic verified-sweep result (9 chat_stream + 9 embed cells)."""
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
                    regression_warning=False if embed_warnings == 0 else None,
                )
            )

    # Construct an EmbedRegressionCheckResult with the requested warning count
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

    drift_cleared = {f"chat_stream_c{c}_h4096": True for c in (1, 4, 8)}
    drift_warning = {f"chat_stream_c{c}_h4096": False for c in (1, 4, 8)}
    return (
        chat_cells,
        embed_cells,
        embed_reg,
        drift_cleared,
        drift_warning,
        True,
        "expected under symmetrisation",
    )


# --- read_phase_1_classifications ------------------------------------------


def test_read_phase_1_classifications_missing_file_returns_none(tmp_path: Path) -> None:
    assert read_phase_1_classifications(tmp_path / "missing.json") is None


def test_read_phase_1_classifications_unparseable_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "report.json"
    p.write_text("not valid json", encoding="utf-8")
    assert read_phase_1_classifications(p) is None


def test_read_phase_1_classifications_round_trips(tmp_path: Path) -> None:
    p = tmp_path / "report.json"
    p.write_text(
        json.dumps(
            {"phase_1_classifications": {"chat_stream_c1_h4096": "instrumentation_artifact"}}
        ),
        encoding="utf-8",
    )
    out = read_phase_1_classifications(p)
    assert out == {"chat_stream_c1_h4096": "instrumentation_artifact"}


def test_read_phase_1_classifications_missing_section_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "report.json"
    p.write_text(json.dumps({"schema_version": "m6_1_1.v1"}), encoding="utf-8")
    assert read_phase_1_classifications(p) is None


# --- Pre-check gates --------------------------------------------------------


def test_phase_2_missing_baseline_returns_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(
        m6_1_1_m6_1_baseline=tmp_path / "missing.json",
        m6_1_1_report_json_out=tmp_path / "out.json",
        m6_1_1_allow_engine_mismatch=False,
    )
    rc = asyncio.run(run_m6_1_1_phase_2(args))
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_phase_2_missing_phase_1_report_returns_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _make_args(tmp_path, phase_1_classifications=None)
    rc = asyncio.run(run_m6_1_1_phase_2(args))
    assert rc == 1
    assert "--m6_1_1 requires a prior --m6_1_1-diagnose" in capsys.readouterr().err


def test_phase_2_engine_version_mismatch_returns_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _make_args(
        tmp_path,
        phase_1_classifications={
            "chat_stream_c1_h4096": "instrumentation_artifact",
            "chat_stream_c4_h4096": "instrumentation_artifact",
            "chat_stream_c8_h4096": "instrumentation_artifact",
        },
    )
    rc = asyncio.run(run_m6_1_1_phase_2(args, deployed_engine_version="0.21.0"))
    assert rc == 1
    assert "engine_version mismatch" in capsys.readouterr().err


# --- Phase 2(a) dispatch ----------------------------------------------------


def test_uniform_instrumentation_artifact_runs_phase_2a_sweep(tmp_path: Path) -> None:
    args = _make_args(
        tmp_path,
        phase_1_classifications={
            "chat_stream_c1_h4096": "instrumentation_artifact",
            "chat_stream_c4_h4096": "instrumentation_artifact",
            "chat_stream_c8_h4096": "instrumentation_artifact",
        },
    )
    captured: list[Phase2OutcomeBundle] = []

    rc = asyncio.run(
        run_m6_1_1_phase_2(
            args,
            sweep_hook=lambda a, b: _verified_sweep_result(),
            write_report=lambda a, bundle: captured.append(bundle),
        )
    )
    assert rc == 0
    assert len(captured) == 1
    bundle = captured[0]
    assert bundle.phase_2_path == "phase_2a_verified"
    assert bundle.chat_stream_baseline is not None
    assert bundle.chat_stream_baseline.baseline_source == "m6_1_1"
    assert bundle.chat_stream_baseline.cells is not None
    assert len(bundle.chat_stream_baseline.cells) == 9
    assert bundle.embed_baseline is not None
    assert bundle.embed_baseline.cells is not None
    assert len(bundle.embed_baseline.cells) == 9
    assert bundle.embed_regression_check is not None
    assert bundle.embed_regression_check.n_warnings == 0


def test_phase_2a_embed_regression_warning_blocks_without_ack(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _make_args(
        tmp_path,
        phase_1_classifications={
            "chat_stream_c1_h4096": "instrumentation_artifact",
            "chat_stream_c4_h4096": "instrumentation_artifact",
            "chat_stream_c8_h4096": "instrumentation_artifact",
        },
    )
    rc = asyncio.run(
        run_m6_1_1_phase_2(
            args,
            sweep_hook=lambda a, b: _verified_sweep_result(embed_warnings=1),
        )
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "embed regression check fired" in err
    assert "embed_regression_acknowledged" in err


def test_phase_2a_embed_regression_warning_proceeds_with_ack(tmp_path: Path) -> None:
    args = _make_args(
        tmp_path,
        phase_1_classifications={
            "chat_stream_c1_h4096": "instrumentation_artifact",
            "chat_stream_c4_h4096": "instrumentation_artifact",
            "chat_stream_c8_h4096": "instrumentation_artifact",
        },
    )
    rc = asyncio.run(
        run_m6_1_1_phase_2(
            args,
            sweep_hook=lambda a, b: _verified_sweep_result(embed_warnings=2),
            phase_2_choice=Phase2Choice(
                embed_regression_acknowledged=True,
                embed_regression_justification="confirmed reduction",
            ),
        )
    )
    assert rc == 0


# --- Phase 2(b) dispatch ----------------------------------------------------


def test_uniform_channel_dependent_batching_with_heading_returns_exit_0(
    tmp_path: Path,
) -> None:
    contracts_md = tmp_path / "instrumentation.md"
    contracts_md.write_text(
        "## M6.1.1: Channel-Dependent Batching Effect\n\nBody text.\n",
        encoding="utf-8",
    )
    args = _make_args(
        tmp_path,
        phase_1_classifications={
            "chat_stream_c1_h4096": "channel_dependent_batching",
            "chat_stream_c4_h4096": "channel_dependent_batching",
            "chat_stream_c8_h4096": "channel_dependent_batching",
        },
    )
    captured: list[Phase2OutcomeBundle] = []
    rc = asyncio.run(
        run_m6_1_1_phase_2(
            args,
            write_report=lambda a, bundle: captured.append(bundle),
            contracts_path=contracts_md,
        )
    )
    assert rc == 0
    assert captured[0].phase_2_path == "phase_2b_documented"
    assert captured[0].chat_stream_baseline is not None
    assert captured[0].chat_stream_baseline.baseline_source == "m6_1"
    assert captured[0].chat_stream_baseline.cells is None  # no fresh sweep
    # The outcome captures the matched heading line
    outcome = captured[0].outcome
    from vllm_grpc_bench.m6_1_1_types import Phase2bDocumentedOutcome

    assert isinstance(outcome, Phase2bDocumentedOutcome)
    assert outcome.contracts_heading_text.startswith("## M6.1.1: ")


def test_phase_2b_missing_heading_returns_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    contracts_md = tmp_path / "instrumentation.md"
    contracts_md.write_text("# instrumentation\n\nno M6.1.1 heading\n", encoding="utf-8")
    args = _make_args(
        tmp_path,
        phase_1_classifications={
            "chat_stream_c1_h4096": "channel_dependent_batching",
            "chat_stream_c4_h4096": "channel_dependent_batching",
            "chat_stream_c8_h4096": "channel_dependent_batching",
        },
    )
    rc = asyncio.run(run_m6_1_1_phase_2(args, contracts_path=contracts_md))
    assert rc == 1
    err = capsys.readouterr().err
    assert "^## M6.1.1: `" in err
    assert "update contracts/instrumentation.md" in err


# --- Non-actionable Phase 1 states (round-3 Q2 case (c)) -------------------


def test_drift_not_reproduced_state_returns_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _make_args(
        tmp_path,
        phase_1_classifications={
            "chat_stream_c1_h4096": "drift_not_reproduced",
            "chat_stream_c4_h4096": "drift_not_reproduced",
            "chat_stream_c8_h4096": "drift_not_reproduced",
        },
    )
    rc = asyncio.run(run_m6_1_1_phase_2(args))
    assert rc == 1
    err = capsys.readouterr().err
    assert "drift_not_reproduced" in err
    assert "drift_not_reproduced_confirmed" in err


def test_mixed_classifications_returns_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _make_args(
        tmp_path,
        phase_1_classifications={
            "chat_stream_c1_h4096": "instrumentation_artifact",
            "chat_stream_c4_h4096": "channel_dependent_batching",
            "chat_stream_c8_h4096": "inconclusive",
        },
    )
    rc = asyncio.run(run_m6_1_1_phase_2(args))
    assert rc == 1
    err = capsys.readouterr().err
    assert "non-uniform" in err


def test_uniform_inconclusive_returns_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _make_args(
        tmp_path,
        phase_1_classifications={
            "chat_stream_c1_h4096": "inconclusive",
            "chat_stream_c4_h4096": "inconclusive",
            "chat_stream_c8_h4096": "inconclusive",
        },
    )
    rc = asyncio.run(run_m6_1_1_phase_2(args))
    assert rc == 1
    err = capsys.readouterr().err
    assert "inconclusive" in err
    assert "split_required" in err
