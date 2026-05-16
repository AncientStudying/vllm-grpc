"""M6.1.1 Phase 2 orchestrator (FR-014, FR-015, FR-016, round-3 Q2).

Dispatched from ``__main__._run_m6_1_1`` when ``--m6_1_1`` is passed.
Branches on the most-recent Phase 1 classification per round-3 Q2:

* uniform ``instrumentation_artifact`` → Phase 2(a): the operator's
  symmetrisation code change is already committed; this run drives the
  n=100 verification sweep, computes the embed regression check (FR-015b),
  emits fresh chat_stream + embed baselines (FR-015a / FR-015c), and flips
  ``phase_2_path = "phase_2a_verified"``.
* uniform ``channel_dependent_batching`` → Phase 2(b): NO Modal sweep.
  Validates ``contracts/instrumentation.md`` carries an ``m6_1_1``-keyed
  heading (FR-016) and flips ``phase_2_path = "phase_2b_documented"``.
* any other state → exit code 1 with actionable stderr.

The Modal-dependent sweep itself lives in :func:`_run_phase_2a_sweep`,
which T030 tests replace with a synthetic generator so the branch logic
is unit-testable without a live deployment.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m6_1_1_contracts_check import validate_contracts_heading
from vllm_grpc_bench.m6_1_1_diagnose import (
    M6_1_1BaselineError,
    check_engine_version,
    load_m6_1_baseline,
)
from vllm_grpc_bench.m6_1_1_supersedence import (
    apply_supersedence,
    default_summary_for,
)
from vllm_grpc_bench.m6_1_1_types import (
    BaselineCellEntry,
    BaselineSentinel,
    EmbedRegressionCheckResult,
    Phase1Classification,
    Phase2aVerifiedOutcome,
    Phase2bDocumentedOutcome,
    Phase2Choice,
)

# Type alias for the Phase 2(a) sweep hook. Returns the verification sweep
# result: 9 chat_stream baseline entries, 9 embed baseline entries, an
# optional embed regression result, and the cleared/drift flags per cell.
Phase2aSweepResult = tuple[
    list[BaselineCellEntry],  # chat_stream baseline cells (9)
    list[BaselineCellEntry],  # embed baseline cells (9)
    EmbedRegressionCheckResult | None,
    dict[str, bool],  # drift_cleared_per_cell — cell_key -> cleared
    dict[str, bool],  # engine_cost_drift_warning_per_cell
    bool,  # chat_stream_control_drift_warning
    str,  # chat_stream_control_drift_note
]
Phase2aSweepHook = Callable[[argparse.Namespace, dict[str, Any]], Phase2aSweepResult]

ReportWriter = Callable[[argparse.Namespace, "Phase2OutcomeBundle"], None]

# Supersedence hook: applies M6.1 supersedence annotations at terminal close.
# Tests intercept by passing a no-op or capture-list lambda.
SupersedenceHook = Callable[..., None]


# --- Outcome bundle (passed to reporter writer) ----------------------------


@dataclass
class Phase2OutcomeBundle:
    """Aggregated Phase 2 outcome — what the reporter consumes."""

    phase_2_path: str
    outcome: Phase2aVerifiedOutcome | Phase2bDocumentedOutcome | None
    chat_stream_baseline: BaselineSentinel | None = None
    embed_baseline: BaselineSentinel | None = None
    embed_regression_check: EmbedRegressionCheckResult | None = None
    phase_2_choice: Phase2Choice | None = None
    error_message: str | None = None


# --- Read the prior phase_1_classifications -------------------------------


def read_phase_1_classifications(report_json_path: Path) -> dict[str, Phase1Classification] | None:
    """Read ``phase_1_classifications`` from the M6.1.1 JSON written by
    ``--m6_1_1-diagnose``. Returns None when the file or section is absent
    (the operator needs to run ``--m6_1_1-diagnose`` first)."""
    if not report_json_path.is_file():
        return None
    try:
        data = json.loads(report_json_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("phase_1_classifications")
    if not isinstance(raw, dict):
        return None
    return {str(k): v for k, v in raw.items() if isinstance(v, str)}  # type: ignore[misc]


# --- Classify the most-recent Phase 1 to a Phase 2 dispatch ----------------


def _uniform_chat_stream_label(
    classifications: Mapping[str, Phase1Classification],
) -> Phase1Classification | None:
    """Return the single classification when ALL chat_stream cells share it.

    Returns None when classifications are missing, non-uniform, or refer to
    non-chat_stream cells.
    """
    cs_labels = {v for k, v in classifications.items() if k.startswith("chat_stream_")}
    if len(cs_labels) == 1:
        return next(iter(cs_labels))
    return None


# --- Phase 2(a) sweep hook (real impl + test-replaceable) ------------------


def _run_phase_2a_sweep(
    args: argparse.Namespace,
    baseline: dict[str, Any],
) -> Phase2aSweepResult:
    """Run the 6-cell × 3-cohort × n=100 verification sweep on Modal.

    The real implementation is deferred to the Modal-integration end-to-end
    work. T030 tests replace this function with a synthetic generator so the
    branch logic is unit-testable. The signature documents the expected
    return shape for the future implementation.
    """
    del args, baseline
    raise NotImplementedError(
        "Phase 2(a) verification sweep is wired against Modal; for unit "
        "tests, replace _run_phase_2a_sweep via monkeypatch. The Modal-"
        "integration end-to-end test lives in T030's --m6_1_1 live "
        "invocation per quickstart."
    )


# --- Phase 2 orchestrator entry point --------------------------------------


async def run_m6_1_1_phase_2(  # noqa: PLR0911 — branch logic has many distinct exit points
    args: argparse.Namespace,
    *,
    sweep_hook: Phase2aSweepHook | None = None,
    write_report: ReportWriter | None = None,
    deployed_engine_version: str | None = None,
    contracts_path: str | Path = "contracts/instrumentation.md",
    phase_2_choice: Phase2Choice | None = None,
    supersedence_hook: SupersedenceHook | None = None,
    date_yyyy_mm_dd: str | None = None,
) -> int:
    """Phase 2 orchestrator. Returns the M6.1.1 exit code."""
    # Pre-check 1: M6.1 baseline exists + parseable (FR-001).
    try:
        baseline = load_m6_1_baseline(Path(args.m6_1_1_m6_1_baseline))
    except M6_1_1BaselineError as exc:
        print(f"m6.1.1: {exc}; see --m6_1_1-m6-1-baseline", file=sys.stderr)
        return 1

    # Pre-check 2: engine version (FR-004).
    ok, msg = check_engine_version(
        baseline,
        deployed_engine_version,
        allow_mismatch=bool(getattr(args, "m6_1_1_allow_engine_mismatch", False)),
    )
    if not ok:
        print(f"m6.1.1: {msg}; see --m6_1_1-allow-engine-mismatch", file=sys.stderr)
        return 1

    # Pre-check 3: prior Phase 1 report exists (FR-014 dependency).
    report_path = Path(args.m6_1_1_report_json_out)
    classifications = read_phase_1_classifications(report_path)
    if classifications is None:
        print(
            "m6.1.1: --m6_1_1 requires a prior --m6_1_1-diagnose to produce "
            f"classifiable results; no phase_1_classifications found at {report_path}",
            file=sys.stderr,
        )
        return 1

    uniform_label = _uniform_chat_stream_label(classifications)
    # Default supersedence hook + date (tests can override).
    if supersedence_hook is None:
        supersedence_hook = apply_supersedence
    if date_yyyy_mm_dd is None:
        date_yyyy_mm_dd = datetime.now(UTC).strftime("%Y-%m-%d")

    # Round-3 Q2 dispatch.
    if uniform_label == "instrumentation_artifact":
        return _dispatch_phase_2a(
            args,
            baseline,
            sweep_hook=sweep_hook,
            write_report=write_report,
            phase_2_choice=phase_2_choice,
            supersedence_hook=supersedence_hook,
            date_yyyy_mm_dd=date_yyyy_mm_dd,
        )
    if uniform_label == "channel_dependent_batching":
        return _dispatch_phase_2b(
            args,
            write_report=write_report,
            contracts_path=contracts_path,
            supersedence_hook=supersedence_hook,
            date_yyyy_mm_dd=date_yyyy_mm_dd,
        )
    if uniform_label == "drift_not_reproduced":
        print(
            "m6.1.1: Phase 1 returned uniform drift_not_reproduced — Phase 2 is "
            "not applicable. Re-run --m6_1_1-diagnose to confirm and close at "
            "drift_not_reproduced_confirmed.",
            file=sys.stderr,
        )
        return 1
    # Mixed / inconclusive / split_required signal from Phase 1.
    if uniform_label is None:
        print(
            f"m6.1.1: non-uniform Phase 1 classifications {sorted(set(classifications.values()))}; "
            "re-run --m6_1_1-diagnose to disambiguate before any Phase 2 path",
            file=sys.stderr,
        )
        return 1
    # uniform_label == "inconclusive"
    print(
        "m6.1.1: Phase 1 returned uniform inconclusive — re-run --m6_1_1-diagnose; "
        "if still inconclusive after a second run, the harness flips to split_required.",
        file=sys.stderr,
    )
    return 1


def _dispatch_phase_2a(
    args: argparse.Namespace,
    baseline: dict[str, Any],
    *,
    sweep_hook: Phase2aSweepHook | None,
    write_report: ReportWriter | None,
    phase_2_choice: Phase2Choice | None,
    supersedence_hook: SupersedenceHook,
    date_yyyy_mm_dd: str,
) -> int:
    """Phase 2(a) dispatch: n=100 verification sweep + fresh baselines."""
    hook = sweep_hook or _run_phase_2a_sweep
    (
        chat_stream_cells,
        embed_cells,
        embed_regression_check,
        drift_cleared,
        drift_warning,
        ctrl_warning,
        ctrl_note,
    ) = hook(args, baseline)

    # FR-015b: if any embed regression warning fires and the operator hasn't
    # acknowledged it, refuse to close (round-2 Q2).
    if embed_regression_check is not None and not embed_regression_check.all_within_tolerance:
        acknowledged = bool(phase_2_choice and phase_2_choice.embed_regression_acknowledged)
        if not acknowledged:
            print(
                f"m6.1.1: embed regression check fired {embed_regression_check.n_warnings} "
                "warning(s); either revert the symmetrisation or acknowledge via "
                "phase_2_choice.embed_regression_acknowledged=True",
                file=sys.stderr,
            )
            return 1

    outcome = Phase2aVerifiedOutcome(
        drift_cleared_per_cell=drift_cleared,
        engine_cost_drift_warning_per_cell=drift_warning,
        chat_stream_control_drift_warning=ctrl_warning,
        chat_stream_control_drift_note=ctrl_note,
    )

    bundle = Phase2OutcomeBundle(
        phase_2_path="phase_2a_verified",
        outcome=outcome,
        chat_stream_baseline=BaselineSentinel(
            phase_2_path="phase_2a_verified",
            baseline_source="m6_1_1",
            pointer="docs/benchmarks/m6_1_1-engine-cost-instrumentation.json",
            cells=chat_stream_cells,
        ),
        embed_baseline=BaselineSentinel(
            phase_2_path="phase_2a_verified",
            baseline_source="m6_1_1",
            pointer="docs/benchmarks/m6_1_1-engine-cost-instrumentation.json",
            cells=embed_cells,
        ),
        embed_regression_check=embed_regression_check,
        phase_2_choice=phase_2_choice,
    )
    if write_report is not None:
        write_report(args, bundle)
    # T032: write M6.1 supersedence annotations on the same PR (FR-023 / FR-024).
    _write_supersedence_at_close(
        args,
        supersedence_hook=supersedence_hook,
        phase_2_path="phase_2a_verified",
        date_yyyy_mm_dd=date_yyyy_mm_dd,
        embed_regression_check=embed_regression_check,
        phase_2_choice=phase_2_choice,
    )
    return 0


def _dispatch_phase_2b(
    args: argparse.Namespace,
    *,
    write_report: ReportWriter | None,
    contracts_path: str | Path,
    supersedence_hook: SupersedenceHook,
    date_yyyy_mm_dd: str,
) -> int:
    """Phase 2(b) dispatch: validate the contracts heading; no Modal sweep."""
    match = validate_contracts_heading(contracts_path)
    if match is None:
        print(
            f"m6.1.1: --m6_1_1 (Phase 2b) requires `^## M6.1.1: ` in {contracts_path}; "
            "update contracts/instrumentation.md with the channel-dependent-batching "
            "section heading and re-run",
            file=sys.stderr,
        )
        return 1
    matched_line, matched_path = match
    outcome = Phase2bDocumentedOutcome(
        contracts_heading_path=matched_path,
        contracts_heading_text=matched_line,
    )
    bundle = Phase2OutcomeBundle(
        phase_2_path="phase_2b_documented",
        outcome=outcome,
        chat_stream_baseline=BaselineSentinel(
            phase_2_path="phase_2b_documented",
            baseline_source="m6_1",
            pointer="docs/benchmarks/m6_1-real-prompt-embeds.json",
            cells=None,
        ),
        embed_baseline=BaselineSentinel(
            phase_2_path="phase_2b_documented",
            baseline_source="m6_1",
            pointer="docs/benchmarks/m6_1-real-prompt-embeds.json",
            cells=None,
        ),
    )
    if write_report is not None:
        write_report(args, bundle)
    # T032: write M6.1 supersedence annotations on the same PR (FR-023 / FR-024).
    _write_supersedence_at_close(
        args,
        supersedence_hook=supersedence_hook,
        phase_2_path="phase_2b_documented",
        date_yyyy_mm_dd=date_yyyy_mm_dd,
        embed_regression_check=None,
        phase_2_choice=None,
    )
    return 0


def _write_supersedence_at_close(
    args: argparse.Namespace,
    *,
    supersedence_hook: SupersedenceHook,
    phase_2_path: str,
    date_yyyy_mm_dd: str,
    embed_regression_check: EmbedRegressionCheckResult | None,
    phase_2_choice: Phase2Choice | None,
) -> None:
    """Invoke the supersedence writer at a terminal close.

    Derives M6.1's markdown path from the JSON baseline path (same stem,
    ``.md`` suffix) and points the annotation at the M6.1.1 report.
    """
    m6_1_json_path = Path(args.m6_1_1_m6_1_baseline)
    m6_1_md_path = m6_1_json_path.with_suffix(".md")
    m6_1_1_md_path = str(Path(args.m6_1_1_report_json_out).with_suffix(".md"))

    affected_rows: list[tuple[str, str]] | None = None
    delta_pct_per_row: dict[tuple[str, str], float] | None = None
    if (
        embed_regression_check is not None
        and phase_2_choice is not None
        and phase_2_choice.embed_regression_acknowledged
    ):
        affected_rows = []
        delta_pct_per_row = {}
        for entry in embed_regression_check.per_entry:
            if not entry.embed_regression_warning:
                continue
            cell_str = f"{entry.cell.path}_c{entry.cell.concurrency}_h{entry.cell.hidden_size}"
            key = (cell_str, entry.cohort)
            affected_rows.append(key)
            delta_pct_per_row[key] = entry.delta_pct

    supersedence_hook(
        phase_2_path=phase_2_path,
        summary=default_summary_for(phase_2_path),
        m6_1_1_md_path=m6_1_1_md_path,
        m6_1_md_path=m6_1_md_path,
        m6_1_json_path=m6_1_json_path,
        date_yyyy_mm_dd=date_yyyy_mm_dd,
        affected_rows=affected_rows,
        delta_pct_per_row=delta_pct_per_row,
    )


__all__ = [
    "Phase2OutcomeBundle",
    "read_phase_1_classifications",
    "run_m6_1_1_phase_2",
]
