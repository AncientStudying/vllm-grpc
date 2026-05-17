"""T062: quickstart.md stderr format validation.

Asserts the harness emits the EXACT stderr lines documented in
``specs/020-m6-real-engine-mini-validation/quickstart.md`` so an
operator following the quickstart sees the expected output. If the
implementation drifts from the documented format, this test fails.
"""

from __future__ import annotations

import asyncio
import io
import re

from vllm_grpc_bench.m6_smoke import emit_smoke_summary, run_smoke
from vllm_grpc_bench.m6_sweep import (
    ProgressReporter,
    RPCResult,
    summarize_verdict_tally,
)
from vllm_grpc_bench.m6_types import (
    EngineCostAggregate,
    EngineCostSpan,
    M6Cell,
    M6CellRecord,
    M6CohortKind,
    M6PerCohortAggregate,
)

# --- Smoke stderr lines (quickstart Step 1, line 41) -------------------------


def test_smoke_summary_matches_quickstart_format() -> None:
    """quickstart.md Step 1 line 41:
    ``cell=embed×c=1 cohort=rest_https_edge status=ok reason=10/10 succ``.
    """

    async def driver(cohort: M6CohortKind, cell: M6Cell, seed: int) -> RPCResult:
        return RPCResult(
            success=True,
            wall_clock_ms=100.0,
            ttft_ms=50.0 if cell.path == "chat_stream" else None,
            engine_cost=(
                EngineCostSpan(engine_forward_ms=12.0)
                if cell.path == "embed"
                else EngineCostSpan(engine_ttft_ms=200.0, engine_tpot_ms=30.0)
            ),
            failure_reason=None,
        )

    result = asyncio.run(run_smoke(driver))
    stream = io.StringIO()
    emit_smoke_summary(result, stream=stream)
    lines = [line for line in stream.getvalue().splitlines() if line.strip()]

    # Exactly the quickstart's documented 6 lines (2 cells × 3 cohorts).
    assert len(lines) == 6
    # The first 3 lines are embed × c=1 (cells iterate before cohorts per
    # m6_smoke.run_smoke), in cohort order rest_https_edge / default_grpc /
    # tuned_grpc_multiplexed.
    assert lines[0].startswith("cell=embed×c=1 cohort=rest_https_edge status=ok reason=10/10")
    assert lines[1].startswith("cell=embed×c=1 cohort=default_grpc status=ok reason=10/10")
    assert lines[2].startswith(
        "cell=embed×c=1 cohort=tuned_grpc_multiplexed status=ok reason=10/10"
    )
    assert lines[3].startswith("cell=chat_stream×c=1 cohort=rest_https_edge status=ok reason=10/10")
    assert lines[4].startswith("cell=chat_stream×c=1 cohort=default_grpc status=ok reason=10/10")
    assert lines[5].startswith(
        "cell=chat_stream×c=1 cohort=tuned_grpc_multiplexed status=ok reason=10/10"
    )


# --- Full-sweep stderr lines (quickstart Step 2, lines 69-76) ----------------


# Pattern for the ISO-8601 UTC timestamp prefix added in
# spike/m6-1-roadmap-additions item #3 (each progress line is now
# ``[YYYY-MM-DDTHH:MM:SSZ] <quickstart-documented body>``).
_TS_PREFIX_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\] ")


def _strip_ts_prefix(line: str) -> str:
    """Strip the timestamp prefix from a progress line; assert one is present.
    Lets the existing exact-body assertions continue to read cleanly."""
    match = _TS_PREFIX_RE.match(line)
    assert match is not None, f"missing ISO-8601 timestamp prefix on line: {line!r}"
    return line[match.end() :]


def test_full_sweep_startup_banner_matches_quickstart() -> None:
    """quickstart.md Step 2 line 69:
    ``M6 sweep: 6 cells × 3 cohorts × n=100, runtime ETA ≤90 min, model=<id>, region=<region>``.
    Body comes after the ISO-8601 timestamp prefix.
    """
    progress = ProgressReporter()
    stream = io.StringIO()
    # Patch stderr -> stream
    import sys

    original_stderr = sys.stderr
    try:
        sys.stderr = stream
        progress.emit_startup(model="Qwen/Qwen3-8B", region="eu-west-1")
    finally:
        sys.stderr = original_stderr
    line = stream.getvalue().strip()
    body = _strip_ts_prefix(line)
    expected = (
        "M6 sweep: 6 cells × 3 cohorts × n=100, runtime ETA ≤90 min, "
        "model=Qwen/Qwen3-8B, region=eu-west-1"
    )
    assert body == expected


def test_full_sweep_progress_line_matches_quickstart() -> None:
    """quickstart.md Step 2 line 70:
    ``[1/18] embed × c=1 / rest_https_edge — 100/100 succ — 8230 ms — ETA 87m``.
    Body comes after the ISO-8601 timestamp prefix.
    """
    progress = ProgressReporter()
    progress.emit_startup(model="Qwen/Qwen3-8B", region="eu-west-1")
    stream = io.StringIO()
    import sys

    original_stderr = sys.stderr
    try:
        sys.stderr = stream
        progress.emit_cell_cohort(
            M6Cell(path="embed", hidden_size=4096, concurrency=1),
            "rest_https_edge",
            successes=100,
            elapsed_ms=8230.0,
        )
    finally:
        sys.stderr = original_stderr
    line = stream.getvalue().strip()
    body = _strip_ts_prefix(line)
    # Pattern: [N/18] <path> × c=<c> / <cohort> — <succ>/100 succ — <ms> ms — ETA <m>m
    pattern = (
        r"^\[1/18\] embed × c=1 / rest_https_edge — 100/100 succ "
        r"— \d+ ms — ETA \d+m$"
    )
    assert re.match(pattern, body), f"body did not match quickstart pattern: {body!r}"


def test_full_sweep_completion_banner_matches_quickstart() -> None:
    """quickstart.md Step 2 line 76: ``M6 sweep complete: verdict table
    at <path> (4 verdict_survives / 1 verdict_changed / 1 cell_incomplete)``.
    Body comes after the ISO-8601 timestamp prefix.
    """
    progress = ProgressReporter()
    progress.emit_startup(model="Qwen/Qwen3-8B", region="eu-west-1")
    stream = io.StringIO()
    import sys

    original_stderr = sys.stderr
    try:
        sys.stderr = stream
        progress.emit_completion(
            "docs/benchmarks/m6-real-engine-mini-validation.md",
            "4 verdict_survives / 1 verdict_changed / 1 cell_incomplete",
        )
    finally:
        sys.stderr = original_stderr
    line = stream.getvalue().strip()
    body = _strip_ts_prefix(line)
    expected = (
        "M6 sweep complete: verdict table at "
        "docs/benchmarks/m6-real-engine-mini-validation.md "
        "(4 verdict_survives / 1 verdict_changed / 1 cell_incomplete)"
    )
    assert body == expected


# --- Verdict tally ordering (priority-based, FR-014 enumeration) -------------


def _make_cell_record(path: str, c: int, classification: str) -> M6CellRecord:
    cell = M6Cell(path=path, hidden_size=4096, concurrency=c)  # type: ignore[arg-type]
    agg = M6PerCohortAggregate(
        cohort="rest_https_edge",
        n_attempted=100,
        n_successes=100,
        failure_count=0,
        classifier_metric_mean_ms=100.0,
        classifier_metric_ci_half_width_ms=5.0,
        total_wall_clock_mean_ms=100.0,
        total_wall_clock_ci_half_width_ms=5.0,
        engine_cost_mean=EngineCostAggregate(engine_forward_mean_ms=12.0),
    )
    return M6CellRecord(
        cell=cell,
        per_cohort={"rest_https_edge": agg},
        classification=classification,  # type: ignore[arg-type]
        classification_reason="synthetic",
        classifier_metric="wall_clock_ms" if path == "embed" else "ttft_ms",
        cohort_pair=("rest_https_edge", "tuned_grpc_multiplexed"),
        m5_2_winner_delta_ms=None,
        m5_2_winner_direction=None,
        engine_cost_mean_ms=12.0,
        engine_cost_drift_warning=False,
        per_cohort_engine_cost_mean_ms=None,
    )


def test_summarize_verdict_tally_priority_order() -> None:
    """Tally ordering follows FR-014 enumeration + FR-023 cell_incomplete
    last (matches quickstart.md Step 2 example).
    """
    cells = [
        _make_cell_record("embed", 1, "verdict_survives"),
        _make_cell_record("embed", 4, "verdict_survives"),
        _make_cell_record("embed", 8, "verdict_survives"),
        _make_cell_record("chat_stream", 1, "verdict_survives"),
        _make_cell_record("chat_stream", 4, "verdict_changed"),
        _make_cell_record("chat_stream", 8, "cell_incomplete"),
    ]
    tally = summarize_verdict_tally(cells)
    assert tally == "4 verdict_survives / 1 verdict_changed / 1 cell_incomplete"


def test_summarize_verdict_tally_omits_missing_classifications() -> None:
    cells = [_make_cell_record("embed", 1, "verdict_survives") for _ in range(6)]
    tally = summarize_verdict_tally(cells)
    assert tally == "6 verdict_survives"
