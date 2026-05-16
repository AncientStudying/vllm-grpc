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
from datetime import UTC, datetime
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
) -> Any:
    """Run the 6-cell × 3-cohort × n=50 Phase 1 sweep on the deployed Modal app.

    Returns an awaitable that resolves to :class:`Phase1RunRecord`. The
    orchestrator awaits it (the hook supports both sync and async
    returns — see ``run_m6_1_1_diagnose`` step 4).

    Wires :func:`m6_1_1_sweep.run_m6_1_1_phase_1_sweep` which reuses M6.1's
    Modal endpoint + RPC driver infrastructure.
    """
    from vllm_grpc_bench.m6_1_1_sweep import run_m6_1_1_phase_1_sweep

    return run_m6_1_1_phase_1_sweep(args, baseline)


# --- Orchestrator entry point (called from __main__._run_m6_1_1) ------------


async def run_m6_1_1_diagnose(
    args: argparse.Namespace,
    *,
    sweep_hook: SweepHook | None = None,
    write_report: Callable[[argparse.Namespace, list[Phase1RunRecord], str | None], None]
    | None = None,
    deployed_engine_version: str | None = None,
    supersedence_hook: Callable[..., None] | None = None,
    date_yyyy_mm_dd: str | None = None,
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
    # Tests typically pass a sync lambda returning Phase1RunRecord; the
    # production hook (Modal sweep) is async. Accept either by inspecting
    # the return value.
    import inspect

    hook = sweep_hook or _run_phase_1_sweep
    sweep_result: Any = hook(args, baseline)
    if inspect.isawaitable(sweep_result):
        sweep_result = await sweep_result
    new_run: Phase1RunRecord = sweep_result

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

    # Step 7: write the report. Production callers pass no override —
    # default to the canonical reporter that materialises the M6_1_1Run
    # and writes both the markdown and JSON companion to disk.
    if write_report is None:
        _default_write_report(args, accumulated_records, gate_message)
    else:
        write_report(args, accumulated_records, gate_message)

    # T032: at the drift_not_reproduced_confirmed close, write M6.1
    # supersedence annotations on the SAME PR (FR-023 / FR-024).
    if gate_message == "drift_not_reproduced_confirmed":
        _write_drift_not_reproduced_supersedence(
            args,
            supersedence_hook=supersedence_hook,
            date_yyyy_mm_dd=date_yyyy_mm_dd,
        )
    return exit_code


def _default_write_report(
    args: argparse.Namespace,
    accumulated_records: list[Phase1RunRecord],
    gate_message: str | None,
) -> None:
    """Default reporter wired into the production dispatch path.

    Builds an :class:`M6_1_1Run` from the accumulated phase_1_runs[] +
    gate state and writes the markdown + JSON companion via
    :func:`m6_1_1_reporter.write_m6_1_1_report`.

    The reporter handles the sentinel-object dispatch under each
    ``phase_2_path`` value per round-2 Q1 / Q2.
    """
    from vllm_grpc_bench.m6_1_1_reporter import build_sentinel, write_m6_1_1_report
    from vllm_grpc_bench.m6_1_1_types import (
        M6_1_1Run,
        M6_1_1RunMeta,
        Phase2Path,
    )

    latest = accumulated_records[-1]
    phase_2_path: Phase2Path = (
        "drift_not_reproduced_confirmed"
        if gate_message == "drift_not_reproduced_confirmed"
        else "phase_2_pending"
    )

    meta = M6_1_1RunMeta(
        git_sha=_git_sha(),
        hostname=_hostname(),
        modal_function_id=None,
        gpu_type="A10G",
        modal_region=str(getattr(args, "m6_1_1_modal_region", "eu-west-1")),
        model_identifier=str(getattr(args, "m6_1_1_model", "Qwen/Qwen3-8B")),
        hidden_size=4096,
        cold_start_s=0.0,
        max_model_len=2048,
        gpu_memory_utilization=0.92,
        engine_version="0.20.1",
        m6_1_baseline_engine_version="0.20.1",
        torch_version="2.11.0",
        M6_1_1_BASE_SEED=int(getattr(args, "m6_1_1_base_seed", 42)),
        seq_len=512,
        phase_1_n=latest.n_per_cohort,
        phase_2_path=phase_2_path,
        run_started_at=latest.run_started_at,
        run_completed_at=latest.run_completed_at,
    )

    run = M6_1_1Run(
        schema_version="m6_1_1.v1",
        run_id=latest.run_id,
        run_started_at=latest.run_started_at,
        run_completed_at=latest.run_completed_at,
        run_meta=meta,
        phase_1_classifications=latest.phase_1_classifications,
        phase_1_runs=accumulated_records,
        multi_point_timings=latest.multi_point_timings,
        phase_2_outcome=None,
        phase_2_choice=None,
        chat_stream_baseline_post_symmetrisation=build_sentinel(phase_2_path),
        embed_baseline_post_symmetrisation=build_sentinel(phase_2_path, is_embed=True),
        embed_regression_check=None,
        m6_1_baseline_pointer=str(
            getattr(
                args,
                "m6_1_1_m6_1_baseline",
                "docs/benchmarks/m6_1-real-prompt-embeds.json",
            )
        ),
        methodology_supersedence="",
    )

    md_path = Path(
        getattr(args, "m6_1_1_report_out", "docs/benchmarks/m6_1_1-engine-cost-instrumentation.md")
    )
    json_path = Path(args.m6_1_1_report_json_out)
    write_m6_1_1_report(run, md_path, json_path)
    print(f"m6.1.1: report written to {md_path} and {json_path}", file=sys.stderr)


def _git_sha() -> str:
    import subprocess

    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()[:7]
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _hostname() -> str:
    import socket

    return socket.gethostname()


def _write_drift_not_reproduced_supersedence(
    args: argparse.Namespace,
    *,
    supersedence_hook: Callable[..., None] | None,
    date_yyyy_mm_dd: str | None,
) -> None:
    """Apply M6.1 supersedence at the drift_not_reproduced_confirmed close."""
    from vllm_grpc_bench.m6_1_1_supersedence import (
        apply_supersedence,
        default_summary_for,
    )

    if supersedence_hook is None:
        supersedence_hook = apply_supersedence
    if date_yyyy_mm_dd is None:
        date_yyyy_mm_dd = datetime.now(UTC).strftime("%Y-%m-%d")

    m6_1_json_path = Path(args.m6_1_1_m6_1_baseline)
    m6_1_md_path = m6_1_json_path.with_suffix(".md")
    m6_1_1_md_path = str(Path(args.m6_1_1_report_json_out).with_suffix(".md"))

    supersedence_hook(
        phase_2_path="drift_not_reproduced_confirmed",
        summary=default_summary_for("drift_not_reproduced_confirmed"),
        m6_1_1_md_path=m6_1_1_md_path,
        m6_1_md_path=m6_1_md_path,
        m6_1_json_path=m6_1_json_path,
        date_yyyy_mm_dd=date_yyyy_mm_dd,
    )


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
