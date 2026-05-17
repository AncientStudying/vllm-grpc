"""M6.1.1 — FR-012 perturbation-budget hard gate (round-2 Q3).

The four checkpoint reads themselves add measurement overhead to each RPC.
``time.perf_counter_ns()`` runs ~50–200 ns per call on Linux/macOS, so four
calls per RPC × ~200 ns = ~800 ns is comfortably under the 500 µs budget
(~600× headroom — research R-2). The gate exists to catch future regressions
where someone adds logging at a checkpoint point or otherwise inflates the
per-call cost. A regression here would bias the FR-010 classifier toward
``inconclusive`` (or worse, flip a borderline cell's classification by
inflating its measured ``seg_ab`` / ``seg_bc`` spreads).

The gate aggregates per (cohort, cell) and exits with code 4 the moment any
pair's *mean* perturbation exceeds 500 µs. Per-RPC outliers do not trip the
gate — only the cell-level mean.
"""

from __future__ import annotations

import sys

from vllm_grpc_bench.m6_1_1_types import (
    PERTURBATION_BUDGET_NS,
    PerturbationAudit,
    Phase1RunRecord,
)


def check_perturbation_budget(record: Phase1RunRecord) -> PerturbationAudit:
    """Aggregate per (cohort, cell) mean perturbation; flag any pair over budget.

    Reads ``MultiPointTimings.perturbation_total_us_mean`` from the record's
    multi_point_timings list — these are already aggregated per (cohort, cell)
    so this function just compares each entry against the 500 µs budget.

    Returns a ``PerturbationAudit`` whose ``exceeded`` is ``True`` iff any
    aggregated pair exceeds the budget. ``exceeded_pairs`` lists the offending
    ``(cohort, cell_str)`` tuples in input order.
    """
    budget_us = PERTURBATION_BUDGET_NS / 1000.0  # 500.0 µs
    per_cohort_per_cell: dict[tuple[str, str], float] = {}
    exceeded_pairs: list[tuple[str, str]] = []

    for mpt in record.multi_point_timings:
        cell_str = _cell_str(mpt.cell)
        key = (mpt.cohort, cell_str)
        per_cohort_per_cell[key] = mpt.perturbation_total_us_mean
        if mpt.perturbation_total_us_mean > budget_us:
            exceeded_pairs.append(key)

    return PerturbationAudit(
        per_cohort_per_cell=per_cohort_per_cell,
        exceeded=bool(exceeded_pairs),
        exceeded_pairs=exceeded_pairs,
        budget_us=budget_us,
    )


def raise_if_exceeded(audit: PerturbationAudit) -> None:
    """Emit the FR-012 stderr message and exit code 4 when the budget is exceeded."""
    if not audit.exceeded:
        return

    # Format the first offending pair into the stderr message shape per
    # contracts/cli.md exit-code-4 line. (The full list is still surfaced for
    # operator triage on a multi-pair regression.)
    first_cohort, first_cell = audit.exceeded_pairs[0]
    if len(audit.exceeded_pairs) > 1:
        suffix = f" (plus {len(audit.exceeded_pairs) - 1} more)"
    else:
        suffix = ""
    print(
        f"m6.1.1: perturbation > {audit.budget_us:.0f} µs on "
        f"{{cohort={first_cohort}, cell={first_cell}}}{suffix}; "
        "reduce checkpoint cost and re-run --m6_1_1-diagnose",
        file=sys.stderr,
    )
    raise SystemExit(4)


def _cell_str(cell: object) -> str:
    """Render a cell as 'chat_stream_c1_h4096' etc. for sentinel keys."""
    # Avoid a direct M6_1_1Cell import dependency to keep this helper testable
    # with synthetic objects.
    path = getattr(cell, "path", "?")
    concurrency = getattr(cell, "concurrency", "?")
    hidden_size = getattr(cell, "hidden_size", "?")
    return f"{path}_c{concurrency}_h{hidden_size}"


__all__ = ["check_perturbation_budget", "raise_if_exceeded"]
