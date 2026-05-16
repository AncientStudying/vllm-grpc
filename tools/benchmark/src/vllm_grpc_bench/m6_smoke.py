"""M6 smoke gate (T054-T056).

Operator-triggered pre-flight that exercises 2 cells × 3 cohorts × n=10
against the real engine (FR-011). Surfaces wiring failures within ~5 min
(SC-004) so a sweep that would otherwise burn ~80 min of Modal A10G
compute on a misconfigured harness fails fast.

Smoke is NOT a CI gate — no persistent diagnostic file is written; the
operator's terminal is the only consumer (FR-011). Stderr carries one
summary line per (cell × cohort) pair; stdout is empty.

This module never invokes the full sweep regardless of smoke outcome
(FR-012 / US3 acceptance scenario 3). The CLI dispatch enforces that
contract by routing ``--m6-smoke`` and ``--m6`` to disjoint code paths.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Literal

from vllm_grpc_bench.m6_sweep import RPCDriver
from vllm_grpc_bench.m6_types import (
    M6_RPC_RETRY_MAX,
    M6_SMOKE_CELLS,
    M6_SMOKE_N,
    M6Cell,
    M6CohortKind,
    M6SmokeOutcome,
    M6SmokeResult,
    make_smoke_cells,
)

_SMOKE_COHORTS: tuple[M6CohortKind, ...] = (
    "rest_https_edge",
    "default_grpc",
    "tuned_grpc_multiplexed",
)


async def _run_one_pair(
    driver: RPCDriver,
    cell: M6Cell,
    cohort: M6CohortKind,
) -> M6SmokeOutcome:
    """Run n=10 RPCs with FR-023 retries; outcome is ok iff all 10 succeed.

    The reason string is bounded to ~60 chars per data-model.md
    M6SmokeOutcome validation rules — operators read this in a terminal
    summary line, not as structured data.
    """
    successes = 0
    last_failure: str | None = None
    for _ in range(M6_SMOKE_N):
        for _attempt in range(M6_RPC_RETRY_MAX + 1):
            # Smoke RPCs carry seed=0 (no measurement-RPC index — smoke is
            # not part of the FR-025 indexed sequence).
            result = await driver(cohort, cell, 0)
            if result.success:
                successes += 1
                break
            last_failure = result.failure_reason or "unknown"
    if successes == M6_SMOKE_N:
        return M6SmokeOutcome(
            cell=cell,
            cohort=cohort,
            status="ok",
            reason=f"{successes}/{M6_SMOKE_N} succ",
        )
    short_reason = (last_failure or "no failures recorded")[:60]
    return M6SmokeOutcome(
        cell=cell,
        cohort=cohort,
        status="failed",
        reason=f"{successes}/{M6_SMOKE_N} succ — {short_reason}",
    )


async def run_smoke(driver: RPCDriver) -> M6SmokeResult:
    """Drive the full smoke matrix (T054).

    Returns the aggregated result with 6 outcomes (2 cells × 3 cohorts).
    Per FR-012, this function never advances to the full sweep; the
    CLI dispatch enforces the disjoint code path.
    """
    started = time.monotonic()
    outcomes: list[M6SmokeOutcome] = []
    for cell in make_smoke_cells():
        for cohort in _SMOKE_COHORTS:
            outcomes.append(await _run_one_pair(driver, cell, cohort))
    overall: Literal["ok", "failed"] = "ok" if all(o.status == "ok" for o in outcomes) else "failed"
    return M6SmokeResult(
        outcomes=outcomes,
        overall_status=overall,
        wall_clock_s=time.monotonic() - started,
    )


def emit_smoke_summary(result: M6SmokeResult, stream: Any = sys.stderr) -> None:
    """Emit one stderr summary line per (cell × cohort) pair (T055 / FR-011).

    Format per contracts/cli.md §"Stdout / stderr contract":
    ``cell=<path>×c=<c> cohort=<cohort> status=<ok|failed> reason=<short string>``.
    No startup banner, no completion banner — smoke is short.
    """
    for outcome in result.outcomes:
        c = outcome.cell
        print(
            f"cell={c.path}×c={c.concurrency} cohort={outcome.cohort} "
            f"status={outcome.status} reason={outcome.reason}",
            file=stream,
        )


def smoke_exit_code(result: M6SmokeResult) -> int:
    """Map smoke outcome to exit code per contracts/cli.md §"Exit codes".

    0 — all 6 pairs ok; 1 — one or more pairs failed (FR-011).
    """
    return 0 if result.overall_status == "ok" else 1


__all__ = [
    "M6_SMOKE_CELLS",
    "M6_SMOKE_N",
    "emit_smoke_summary",
    "run_smoke",
    "smoke_exit_code",
]
