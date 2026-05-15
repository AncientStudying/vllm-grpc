"""Tests for the M6 smoke gate (T057, T058, T059).

Covers:
- T057: smoke matrix coverage — exactly 2 cells × 3 cohorts × n=10 (60
  total RPCs). Each cohort sees both smoke cells.
- T058: exit-code mapping — 0 on all-pass, 1 when any pair fails. Stderr
  summary names the failing pair.
- T059: ``--m6-smoke`` does NOT advance to the full sweep regardless of
  outcome (FR-012 / US3 acceptance scenario 3).
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from unittest.mock import patch

import pytest
from vllm_grpc_bench.m6_smoke import emit_smoke_summary, run_smoke, smoke_exit_code
from vllm_grpc_bench.m6_sweep import RPCResult
from vllm_grpc_bench.m6_types import EngineCostSpan, M6Cell, M6CohortKind


def _fake_engine_cost(path: str) -> EngineCostSpan:
    if path == "embed":
        return EngineCostSpan(engine_forward_ms=12.0)
    return EngineCostSpan(engine_ttft_ms=200.0, engine_tpot_ms=30.0)


def _always_ok_driver() -> tuple[
    object,
    list[tuple[M6CohortKind, str, int]],
]:
    calls: list[tuple[M6CohortKind, str, int]] = []

    async def driver(cohort: M6CohortKind, cell: M6Cell, seed: int) -> RPCResult:
        calls.append((cohort, cell.path, cell.concurrency))
        return RPCResult(
            success=True,
            wall_clock_ms=100.0,
            ttft_ms=50.0 if cell.path == "chat_stream" else None,
            engine_cost=_fake_engine_cost(cell.path),
            failure_reason=None,
        )

    return driver, calls


# --- T057: smoke matrix coverage ---------------------------------------------


def test_smoke_runs_exactly_six_pairs() -> None:
    driver, calls = _always_ok_driver()
    result = asyncio.run(run_smoke(driver))  # type: ignore[arg-type]
    assert len(result.outcomes) == 6
    # Exactly 2 cells × 3 cohorts × n=10 = 60 RPCs.
    assert len(calls) == 60


def test_smoke_exercises_only_smoke_cells() -> None:
    """T057: the smoke matrix is ``(embed, h=4096, c=1)`` and
    ``(chat_stream, h=4096, c=1)``.
    """
    driver, calls = _always_ok_driver()
    asyncio.run(run_smoke(driver))  # type: ignore[arg-type]
    cells_seen = {(p, c) for (_cohort, p, c) in calls}
    assert cells_seen == {("embed", 1), ("chat_stream", 1)}


def test_smoke_exercises_all_three_cohorts() -> None:
    driver, calls = _always_ok_driver()
    asyncio.run(run_smoke(driver))  # type: ignore[arg-type]
    cohorts_seen = {cohort for (cohort, _p, _c) in calls}
    assert cohorts_seen == {"rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"}


def test_smoke_per_cell_cohort_pair_runs_n10() -> None:
    """Each (cell × cohort) pair must drive exactly 10 RPCs (n=M6_SMOKE_N)."""
    driver, calls = _always_ok_driver()
    asyncio.run(run_smoke(driver))  # type: ignore[arg-type]
    from collections import Counter

    pair_counts = Counter(calls)
    for count in pair_counts.values():
        assert count == 10


# --- T058: exit-code + stderr summary ----------------------------------------


def test_smoke_exit_code_zero_on_all_pass() -> None:
    driver, _calls = _always_ok_driver()
    result = asyncio.run(run_smoke(driver))  # type: ignore[arg-type]
    assert result.overall_status == "ok"
    assert smoke_exit_code(result) == 0


def test_smoke_exit_code_one_on_any_failure() -> None:
    """Inject failures on one cohort. Exit code MUST be 1; stderr summary
    MUST name the failing pair with status=failed.
    """

    async def driver(cohort: M6CohortKind, cell: M6Cell, seed: int) -> RPCResult:
        # default_grpc on chat_stream always fails (even after retries).
        if cohort == "default_grpc" and cell.path == "chat_stream":
            return RPCResult(
                success=False,
                wall_clock_ms=None,
                ttft_ms=None,
                engine_cost=None,
                failure_reason="grpc channel reset",
            )
        return RPCResult(
            success=True,
            wall_clock_ms=100.0,
            ttft_ms=50.0 if cell.path == "chat_stream" else None,
            engine_cost=_fake_engine_cost(cell.path),
            failure_reason=None,
        )

    result = asyncio.run(run_smoke(driver))
    assert result.overall_status == "failed"
    assert smoke_exit_code(result) == 1

    stream = io.StringIO()
    emit_smoke_summary(result, stream=stream)
    out = stream.getvalue()
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 6, f"expected 6 summary lines, got {len(lines)}: {lines}"

    failed_lines = [line for line in lines if "status=failed" in line]
    ok_lines = [line for line in lines if "status=ok" in line]
    assert len(failed_lines) == 1
    assert len(ok_lines) == 5

    failed_line = failed_lines[0]
    assert "cell=chat_stream×c=1" in failed_line
    assert "cohort=default_grpc" in failed_line
    assert "reason=" in failed_line


def test_smoke_summary_format_matches_contract() -> None:
    """T055 / contracts/cli.md format: each line is
    ``cell=<path>×c=<c> cohort=<cohort> status=<ok|failed> reason=<short>``.
    """
    driver, _calls = _always_ok_driver()
    result = asyncio.run(run_smoke(driver))  # type: ignore[arg-type]
    stream = io.StringIO()
    emit_smoke_summary(result, stream=stream)
    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    for line in lines:
        assert line.startswith("cell=")
        assert " cohort=" in line
        assert " status=" in line
        assert " reason=" in line


# --- T059: smoke does NOT trigger full sweep (FR-012) ------------------------


def test_smoke_dispatch_does_not_invoke_full_sweep(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """T059 / FR-012: --m6-smoke MUST NOT call _run_m6_full_sweep
    regardless of smoke outcome. The CLI dispatch routes ``--m6-smoke``
    to ``_run_m6_smoke`` (disjoint code path from ``--m6``).
    """
    from vllm_grpc_bench.__main__ import _build_parser, _run_m6

    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    real_baseline = Path("docs/benchmarks/m5_2-transport-vs-tuning.json")
    if not real_baseline.exists():
        pytest.skip(f"baseline JSON not at {real_baseline}; skipping")

    parser = _build_parser()
    ns = parser.parse_args(["--m6-smoke", f"--m6-m5-2-baseline={real_baseline}"])

    sweep_calls: list[object] = []

    def _fake_full_sweep(*args_, **kwargs_):  # type: ignore[no-untyped-def]
        sweep_calls.append((args_, kwargs_))
        return 0

    with patch(
        "vllm_grpc_bench.__main__._run_m6_full_sweep",
        side_effect=_fake_full_sweep,
    ):
        rc = _run_m6(ns)

    # The full sweep MUST NOT have been invoked.
    assert len(sweep_calls) == 0
    # The smoke dispatch returns exit code 2 because the production Modal
    # driver is not yet wired — that's the seam, NOT a full-sweep call.
    assert rc == 2
