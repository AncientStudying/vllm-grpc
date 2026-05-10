"""Diagnose embed/h4096/m1-baseline CV noise.

Runs the shared-baseline measurement N times back-to-back (same machinery
the M4 sweep uses) and dumps per-cohort distribution stats so we can tell
whether the high CV comes from a few outliers or a genuinely wide central
distribution.

Run from repo root:
    uv run python specs/016-m4-time-axis-tuning/diag_baseline_cv.py

Optional:
    REPEATS=5 WARMUP=10 N=100 GC_DISABLE=1 uv run python ...
"""

from __future__ import annotations

import asyncio
import gc
import os
import statistics
import time

from vllm_grpc_bench.m3_types import M4SweepConfig
from vllm_grpc_bench.m4_sweep import measure_shared_baseline


def _pct(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if q <= 0:
        return sorted_values[0]
    if q >= 1:
        return sorted_values[-1]
    idx = q * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


async def main() -> None:
    repeats = int(os.environ.get("REPEATS", "5"))
    warmup = int(os.environ.get("WARMUP", "10"))
    n = int(os.environ.get("N", "100"))
    gc_disable = os.environ.get("GC_DISABLE", "0") == "1"

    config = M4SweepConfig(
        baseline_n=n,
        candidate_n=n,
        warmup_n=warmup,
        baseline_cv_warn=1.0,  # post-FR-005-rework field; warn-only, never aborts
    )
    print(
        f"diag: repeats={repeats} warmup={warmup} n={n} gc_disable={gc_disable} "
        f"width={config.schema_canonical_width}"
    )
    print(
        f"{'run':>3} {'cv':>7} {'mean_ms':>8} {'p50_ms':>8} {'p99_ms':>8} "
        f"{'max_ms':>8} {'top3_ms':>20}"
    )
    if gc_disable:
        gc.disable()
    try:
        for run in range(1, repeats + 1):
            t0 = time.perf_counter()
            cohort = await measure_shared_baseline(
                path="embed",
                hidden_size=config.schema_canonical_width,
                seed=42 + run,
                config=config,
            )
            elapsed = time.perf_counter() - t0
            walls = sorted(
                s.wall_clock_seconds for s in cohort.samples if s.error is None
            )
            mean = statistics.fmean(walls)
            cv = statistics.stdev(walls) / mean if mean > 0 else 0.0
            top3 = sorted(walls, reverse=True)[:3]
            print(
                f"{run:>3d} {cv:>7.4f} {mean*1000:>8.2f} "
                f"{_pct(walls, 0.50)*1000:>8.2f} {_pct(walls, 0.99)*1000:>8.2f} "
                f"{walls[-1]*1000:>8.2f} "
                f"{[round(x*1000,2) for x in top3]!s:>20s}  "
                f"(elapsed={elapsed:.1f}s)"
            )
    finally:
        if gc_disable:
            gc.enable()


if __name__ == "__main__":
    asyncio.run(main())
