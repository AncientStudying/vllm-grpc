"""M6.1 smoke gate (US3 / FR-012).

Operator-triggered pre-flight that exercises 2 cells × 3 cohorts × n=10
against the real prompt-embeds engine path. Surfaces wiring failures —
including the FR-006 torch-pin failure (caught at __main__ dispatch),
M6 baseline JSON failures, REST shim wiring failures, and gRPC torch.save
round-trip failures — within ~5 min before the operator commits to a ~80 min
full sweep.

The smoke gate MUST NOT run the FR-029 chat_stream control-drift check
(n=10 CIs too wide for meaningful overlap detection).
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Literal

from vllm_grpc_bench.m6_1_rpc_driver import provide_m6_1_rpc_driver
from vllm_grpc_bench.m6_1_sweep import BaselineTuple, _resolve_seq_len
from vllm_grpc_bench.m6_1_types import (
    M6_1_COHORTS,
    M6_1_RPC_RETRY_MAX,
    M6_1_SMOKE_N,
    M6_1Cell,
    M6_1CohortKind,
    M6_1SmokeOutcome,
    M6_1SmokeResult,
    make_smoke_cells,
)
from vllm_grpc_bench.m6_sweep import RPCDriver
from vllm_grpc_bench.modal_endpoint import ModalDeployError, provide_m6_endpoint


async def _run_one_pair(
    driver: RPCDriver,
    cell: M6_1Cell,
    cohort: M6_1CohortKind,
) -> M6_1SmokeOutcome:
    successes = 0
    last_failure: str | None = None
    for _ in range(M6_1_SMOKE_N):
        for _attempt in range(M6_1_RPC_RETRY_MAX + 1):
            # Smoke RPCs carry seed=0 (no measurement-RPC index — smoke is
            # NOT part of the FR-019 indexed sequence; smoke is wiring
            # validation only).
            result = await driver(cohort, cell, 0)
            if result.success:
                successes += 1
                break
            last_failure = result.failure_reason or "unknown"
    if successes == M6_1_SMOKE_N:
        return M6_1SmokeOutcome(
            cell=cell, cohort=cohort, status="ok", reason=f"{successes}/{M6_1_SMOKE_N} succ"
        )
    short = (last_failure or "no failures recorded")[:60]
    return M6_1SmokeOutcome(
        cell=cell,
        cohort=cohort,
        status="failed",
        reason=f"{successes}/{M6_1_SMOKE_N} succ — {short}",
    )


async def run_smoke_with_driver(driver: RPCDriver) -> M6_1SmokeResult:
    """Drive the full smoke matrix (2 cells × 3 cohorts × n=10)."""
    started = time.monotonic()
    outcomes: list[M6_1SmokeOutcome] = []
    for cell in make_smoke_cells():
        for cohort in M6_1_COHORTS:
            outcomes.append(await _run_one_pair(driver, cell, cohort))
    overall: Literal["ok", "failed"] = "ok" if all(o.status == "ok" for o in outcomes) else "failed"
    return M6_1SmokeResult(
        outcomes=outcomes,
        overall_status=overall,
        wall_clock_s=time.monotonic() - started,
    )


def emit_smoke_summary(result: M6_1SmokeResult, stream: Any = sys.stderr) -> None:
    """Emit one stderr summary line per (cell × cohort) pair (FR-012).

    Always prints a final one-line stderr note that the FR-029
    chat_stream control-drift check is full-sweep-only (FR-012 mandate),
    regardless of overall status.
    """
    for outcome in result.outcomes:
        c = outcome.cell
        print(
            f"cell={c.path}×c={c.concurrency} cohort={outcome.cohort} "
            f"status={outcome.status} reason={outcome.reason}",
            file=stream,
        )
    print(
        "note: chat_stream control-drift check is full-sweep-only "
        "(FR-012/FR-029) — will run after the n=100 sweep completes",
        file=stream,
    )


def smoke_exit_code(result: M6_1SmokeResult) -> int:
    """Map smoke outcome to exit code per contracts/cli.md §"Exit codes".

    Returns 0 if all 6 pairs ok, 1 if any pair failed. Pre-check failures
    (torch pin / baseline) collapse to exit code 2 at __main__ dispatch
    before we ever get here.
    """
    return 0 if result.overall_status == "ok" else 1


async def run_m6_1_smoke(
    args: argparse.Namespace,
    baseline_tuple: BaselineTuple,
) -> int:
    """Top-level smoke entrypoint invoked from ``__main__._run_m6_1``."""
    _ = baseline_tuple  # baseline already validated at dispatch time
    seq_len = _resolve_seq_len(str(args.m6_1_model))

    try:
        async with (
            provide_m6_endpoint(
                region=str(args.m6_1_modal_region),
                token_env=str(args.m6_1_modal_token_env),
                model_id=str(args.m6_1_model),
            ) as endpoints,
            provide_m6_1_rpc_driver(
                endpoints,
                seq_len=seq_len,
                base_seed=int(args.m6_1_base_seed),
            ) as (driver, _rtt),
        ):
            result = await run_smoke_with_driver(driver)
    except ModalDeployError as exc:
        print(f"Error: M6.1 smoke Modal deploy failed: {exc}", file=sys.stderr)
        return 2

    emit_smoke_summary(result)
    return smoke_exit_code(result)


__all__ = [
    "emit_smoke_summary",
    "run_m6_1_smoke",
    "run_smoke_with_driver",
    "smoke_exit_code",
]
