"""M6.1.1 Phase 1 diagnostic mini-sweep orchestrator (FR-005, FR-013, round-3 Q1).

Drives the 6-cell × 3-cohort × n=50 mini-sweep against the deployed Modal
app, classifies each chat_stream cell via the FR-010 magnitude-equivalence
formula, and applies the FR-017 / FR-018 re-run / split gates. Reads and
appends to ``docs/benchmarks/m6_1_1-engine-cost-instrumentation.json``'s
``phase_1_runs[]`` array per round-3 Q1.

The Modal-dependent sweep itself lives in :func:`_run_phase_1_sweep`, which
T024 tests replace with a synthetic generator so the gate logic is unit
-testable without a live deployment.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m6_1_1_classifier import classify_cell
from vllm_grpc_bench.m6_1_1_perturbation import (
    check_perturbation_budget,
    raise_if_exceeded,
)
from vllm_grpc_bench.m6_1_1_types import (
    M6_1_1Cell,
    M6_1_1Cohort,
    MultiPointTimings,
    Phase1Classification,
    Phase1RunRecord,
)

# Type alias for the sweep hook — accepts the parsed args + baseline payload,
# returns a Phase1RunRecord ready to append to phase_1_runs[].
SweepHook = Callable[[argparse.Namespace, dict[str, Any]], Phase1RunRecord]


# --- Baseline loader --------------------------------------------------------


class M6_1_1BaselineError(RuntimeError):
    """Raised when M6.1's baseline JSON is missing, malformed, or incomplete
    in a way that blocks M6.1.1 Phase 1 (FR-001 / FR-004)."""


def load_m6_1_baseline(path: Path) -> dict[str, Any]:
    """Load M6.1's published JSON and validate the required fields are present.

    Returns the parsed top-level dict on success. Raises
    :class:`M6_1_1BaselineError` with an actionable message on missing file,
    malformed JSON, or missing per-cohort engine_cost data.
    """
    if not path.is_file():
        raise M6_1_1BaselineError(f"M6.1 baseline not found at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise M6_1_1BaselineError(f"M6.1 baseline at {path} unparseable: {exc}") from exc
    if not isinstance(data, dict):
        raise M6_1_1BaselineError(f"M6.1 baseline at {path} is not a JSON object")
    if data.get("schema_version") != "m6_1.v1":
        raise M6_1_1BaselineError(
            f"M6.1 baseline at {path} schema_version != 'm6_1.v1' "
            f"(got {data.get('schema_version')!r})"
        )
    if "engine_cost_baseline" not in data:
        raise M6_1_1BaselineError(f"M6.1 baseline at {path} missing 'engine_cost_baseline' section")
    return data


def check_engine_version(
    baseline: Mapping[str, Any],
    deployed: str | None,
    *,
    allow_mismatch: bool,
) -> tuple[bool, str | None]:
    """Compare M6.1's recorded engine_version against the deployed version.

    Returns ``(ok, message)``. ``ok == False`` indicates exit code 1 unless
    ``allow_mismatch`` is True. ``deployed=None`` skips the check (used in
    tests where the deployment isn't queried).
    """
    if deployed is None:
        return True, None
    recorded = baseline.get("run_meta", {}).get("engine_version")
    if not isinstance(recorded, str) or not recorded:
        return True, None  # baseline doesn't record an engine_version; skip
    if recorded == deployed:
        return True, None
    msg = f"engine_version mismatch: M6.1 baseline recorded {recorded!r}, deployed {deployed!r}"
    return (
        (True, f"{msg} (--m6_1_1-allow-engine-mismatch acknowledged)")
        if allow_mismatch
        else (
            False,
            msg,
        )
    )


# --- Phase 1 run record I/O (round-3 Q1 append-on-re-read) -----------------


def read_existing_phase_1_runs(report_json_path: Path) -> list[dict[str, Any]]:
    """Read the existing ``phase_1_runs[]`` array from the M6.1.1 JSON.

    Best-effort per Research R-7:
    * FileNotFoundError → returns ``[]`` (first run).
    * JSON parse error → stderr warning + returns ``[]`` (round-3 Q1: first
      run's data is unrecoverable; operator advised to commit between runs).
    * Missing ``phase_1_runs`` key → returns ``[]``.

    Returns the raw list-of-dict shape so the caller can append the new
    record without round-tripping through M6_1_1Run.
    """
    if not report_json_path.is_file():
        return []
    try:
        data = json.loads(report_json_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(
            f"m6.1.1: existing report at {report_json_path} is unreadable "
            f"({exc}); starting fresh phase_1_runs[]",
            file=sys.stderr,
        )
        return []
    if not isinstance(data, dict):
        return []
    existing = data.get("phase_1_runs")
    if not isinstance(existing, list):
        return []
    return existing


# --- Re-run / split gates (FR-017 / FR-018 / round-2 Q4) --------------------


def evaluate_phase_1_gates(
    phase_1_runs: list[Phase1RunRecord],
) -> tuple[int, str | None]:
    """Decide whether the accumulated Phase 1 data is actionable.

    Returns ``(exit_code, message)``:
    * ``(0, None)`` — uniform actionable classification on the most recent
      run (one of ``instrumentation_artifact`` / ``channel_dependent_batching``);
      Phase 2 can run.
    * ``(0, "drift_not_reproduced_confirmed")`` — two independent runs both
      returned uniform ``drift_not_reproduced``; M6.1 flag preserved as
      published.
    * ``(3, message)`` — single run with mixed / inconclusive / uniform
      ``drift_not_reproduced``; operator must re-run ``--m6_1_1-diagnose``.
    * ``(5, message)`` — two runs still divergent / inconclusive after
      reconfirmation; ``phase_2_path = "split_required"``.

    The gate operates on the chat_stream cells only (embed cells are
    audit-only controls per FR-011).
    """
    if not phase_1_runs:
        return 3, "no Phase 1 runs recorded; re-run --m6_1_1-diagnose"

    def _classifications(run: Phase1RunRecord) -> list[Phase1Classification]:
        return [v for k, v in run.phase_1_classifications.items() if k.startswith("chat_stream_")]

    latest = phase_1_runs[-1]
    latest_labels = _classifications(latest)
    if not latest_labels:
        return 3, "no chat_stream classifications recorded; re-run --m6_1_1-diagnose"

    latest_unique = set(latest_labels)

    # Single-run actionable: uniform instrumentation_artifact or
    # channel_dependent_batching → Phase 2 can run.
    if latest_unique == {"instrumentation_artifact"} or latest_unique == {
        "channel_dependent_batching"
    }:
        return 0, None

    # Single-run drift_not_reproduced: needs a confirming second run.
    if latest_unique == {"drift_not_reproduced"}:
        if len(phase_1_runs) < 2:
            return 3, (
                "uniform drift_not_reproduced on a single run; "
                "re-run --m6_1_1-diagnose to confirm before closing"
            )
        prior_labels = _classifications(phase_1_runs[-2])
        if set(prior_labels) == {"drift_not_reproduced"}:
            return 0, "drift_not_reproduced_confirmed"
        # Prior run was actionable; treat as inconsistent → re-run signal.
        return 3, (
            "uniform drift_not_reproduced now but prior run was actionable; "
            "re-run --m6_1_1-diagnose to disambiguate"
        )

    # Mixed or inconclusive on the latest run.
    if len(phase_1_runs) < 2:
        return 3, (
            f"non-uniform classifications {sorted(latest_unique)}; "
            "re-run --m6_1_1-diagnose before any Phase 2 path"
        )

    # Two runs and still divergent → split_required (round-2 Q4).
    prior_labels = _classifications(phase_1_runs[-2])
    prior_unique = set(prior_labels)
    if (
        latest_unique == prior_unique
        and len(latest_unique) == 1
        and latest_unique <= {"instrumentation_artifact", "channel_dependent_batching"}
    ):
        return 0, None
    return 5, (
        "still-divergent after 2 Phase 1 runs; open successor sub-milestones "
        "M6.1.1a / M6.1.1b before any code or doc change"
    )


# --- Phase 1 sweep hook (real impl + test-replaceable) ----------------------


def _run_phase_1_sweep(
    args: argparse.Namespace,
    baseline: dict[str, Any],
) -> Phase1RunRecord:
    """Run the 6-cell × 3-cohort × n=50 Phase 1 sweep on the deployed Modal app.

    The real implementation is deferred — the Modal deploy + cohort runner
    integration is exercised end-to-end against Modal directly (manual
    operator step per quickstart.md). T024 tests replace this function with
    a synthetic generator so the gate logic is unit-testable.
    """
    del args, baseline
    raise NotImplementedError(
        "Phase 1 sweep is wired against Modal; for unit tests, replace "
        "_run_phase_1_sweep via monkeypatch. The Modal-integration end-to-end "
        "test lives in T024's --m6_1_1-diagnose live invocation per quickstart."
    )


# --- Orchestrator entry point (called from __main__._run_m6_1_1) ------------


async def run_m6_1_1_diagnose(
    args: argparse.Namespace,
    *,
    sweep_hook: SweepHook | None = None,
    write_report: Callable[[argparse.Namespace, list[Phase1RunRecord], str | None], None]
    | None = None,
    deployed_engine_version: str | None = None,
) -> int:
    """Phase 1 mini-sweep orchestrator. Returns the M6.1.1 exit code.

    Steps (per T023):
    1. Torch-pin gate already ran in ``__main__._run_m6_1_1``.
    2. Load M6.1 baseline (exit 1 on missing / malformed).
    3. Engine version check vs deployed (exit 1 on mismatch unless allowed).
    4. Run the 6×3×n=50 sweep via ``sweep_hook`` (defaults to
       :func:`_run_phase_1_sweep`).
    5. Compute perturbation audit; exit 4 if budget exceeded.
    6. Apply FR-017 / FR-018 gates (exit 3 / 5 as appropriate).
    7. Write the M6.1.1 report (reporter is wired in T025; until then this
       function returns 0 with the new Phase1RunRecord accumulated in
       ``phase_1_runs[]`` — tests inspect via ``write_report``).
    """
    # Step 2: load M6.1 baseline.
    try:
        baseline = load_m6_1_baseline(Path(args.m6_1_1_m6_1_baseline))
    except M6_1_1BaselineError as exc:
        print(f"m6.1.1: {exc}; see --m6_1_1-m6-1-baseline", file=sys.stderr)
        return 1

    # Step 3: engine version comparison.
    ok, msg = check_engine_version(
        baseline,
        deployed_engine_version,
        allow_mismatch=bool(getattr(args, "m6_1_1_allow_engine_mismatch", False)),
    )
    if not ok:
        print(f"m6.1.1: {msg}; see --m6_1_1-allow-engine-mismatch", file=sys.stderr)
        return 1
    if msg:
        print(f"m6.1.1: {msg}", file=sys.stderr)

    # Step 4: run the Phase 1 sweep (hook is replaceable for tests).
    hook = sweep_hook or _run_phase_1_sweep
    new_run = hook(args, baseline)

    # Step 5: perturbation budget gate (FR-012, round-2 Q3).
    audit = check_perturbation_budget(new_run)
    new_run = _replace_audit(new_run, audit)
    if audit.exceeded:
        raise_if_exceeded(audit)  # raises SystemExit(4)

    # Step 6: append-on-re-read + apply gates.
    report_path = Path(args.m6_1_1_report_json_out)
    existing_runs = read_existing_phase_1_runs(report_path)
    accumulated_records = _existing_plus_new(existing_runs, new_run)
    exit_code, gate_message = evaluate_phase_1_gates(accumulated_records)
    if gate_message:
        print(f"m6.1.1: {gate_message}", file=sys.stderr)

    # Step 7: write the report (T025 reporter wires here).
    if write_report is not None:
        write_report(args, accumulated_records, gate_message)
    return exit_code


def _replace_audit(run: Phase1RunRecord, audit: Any) -> Phase1RunRecord:
    """Return a copy of ``run`` with the recomputed ``perturbation_audit``."""
    from dataclasses import replace

    return replace(run, perturbation_audit=audit)


def _existing_plus_new(
    existing_runs: list[dict[str, Any]],
    new_run: Phase1RunRecord,
) -> list[Phase1RunRecord]:
    """Rehydrate the existing list-of-dict Phase1RunRecord entries and
    append the new run. Best-effort: malformed prior records are dropped
    with a stderr warning (round-3 Q1)."""
    out: list[Phase1RunRecord] = []
    for idx, raw in enumerate(existing_runs):
        try:
            out.append(_rehydrate_phase_1_run(raw))
        except (TypeError, KeyError, ValueError) as exc:
            print(
                f"m6.1.1: existing phase_1_runs[{idx}] malformed ({exc}); "
                "dropping from accumulator",
                file=sys.stderr,
            )
    out.append(new_run)
    return out


def _rehydrate_phase_1_run(raw: dict[str, Any]) -> Phase1RunRecord:
    """Rehydrate a dict (as written by the reporter) back into Phase1RunRecord.

    Only fields exercised by the gate evaluator are required —
    multi_point_timings + perturbation_audit are not strictly needed for
    gate logic so they're populated as empty/default if missing.
    """
    from vllm_grpc_bench.m6_1_1_types import PerturbationAudit

    classifications = {str(k): v for k, v in (raw.get("phase_1_classifications") or {}).items()}
    return Phase1RunRecord(
        run_id=str(raw.get("run_id", "")),
        run_started_at=str(raw.get("run_started_at", "")),
        run_completed_at=str(raw.get("run_completed_at", "")),
        wall_clock_s=float(raw.get("wall_clock_s", 0.0)),
        multi_point_timings=[],
        phase_1_classifications=classifications,
        perturbation_audit=PerturbationAudit(per_cohort_per_cell={}, exceeded=False),
        n_per_cohort=int(raw.get("n_per_cohort", 50)),
    )


def cell_key(cell: M6_1_1Cell) -> str:
    """Render a cell as 'chat_stream_c1_h4096' / 'embed_c8_h4096' for the
    phase_1_classifications dict + perturbation_audit keys."""
    return f"{cell.path}_c{cell.concurrency}_h{cell.hidden_size}"


def per_cohort_for_cell(
    cell: M6_1_1Cell,
    multi_point_timings: list[MultiPointTimings],
) -> dict[M6_1_1Cohort, MultiPointTimings] | None:
    """Build the per-cohort dict for one cell from a flat list. Returns
    None when any of the three expected cohorts is missing (the cell isn't
    classifiable)."""
    out: dict[M6_1_1Cohort, MultiPointTimings] = {}
    for mpt in multi_point_timings:
        if mpt.cell == cell:
            out[mpt.cohort] = mpt
    expected = {"rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"}
    if set(out) >= expected:
        return out
    return None


def classify_run(
    run: Phase1RunRecord, chat_stream_cells: list[M6_1_1Cell]
) -> dict[str, Phase1Classification]:
    """Apply :func:`classify_cell` to each chat_stream cell in the run.

    Returns a dict keyed by ``cell_key(cell)``. Cells missing per-cohort
    data are excluded (they would otherwise raise in the classifier).
    """
    out: dict[str, Phase1Classification] = {}
    for cell in chat_stream_cells:
        per_cohort = per_cohort_for_cell(cell, run.multi_point_timings)
        if per_cohort is None:
            continue
        out[cell_key(cell)] = classify_cell(cell, per_cohort)
    return out


__all__ = [
    "M6_1_1BaselineError",
    "cell_key",
    "check_engine_version",
    "classify_run",
    "evaluate_phase_1_gates",
    "load_m6_1_baseline",
    "per_cohort_for_cell",
    "read_existing_phase_1_runs",
    "run_m6_1_1_diagnose",
]
