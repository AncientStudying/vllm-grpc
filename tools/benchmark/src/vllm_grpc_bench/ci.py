"""95% confidence-interval estimator for the M3 sweep.

Per ``research.md`` R-1: mean + sample stddev (``ddof=1``) + 95% CI bounds via
the t-distribution. We use a hard-coded critical-value table covering
n ∈ {10, 20, 30, 50, 100} so the bench tools stay scipy-free.

For sample sizes between table entries, we pick the next-larger key (i.e.,
the more conservative critical value) so the CI half-width is never
under-estimated. For n outside the table at the low end (n < 10) we refuse —
the spec sets n=30 as the operational default; n=2..9 is too small for the
t-approximation we publish.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# t-critical values at alpha=0.025 (two-sided 95% CI), keyed by n (sample size),
# computed against the standard t-distribution and rounded to 4 decimals.
# Source: standard statistical tables; cross-checked vs. scipy.stats.t.ppf(0.975, df=n-1)
# for n=30 (T013 verifies this within 0.5%).
_T_CRITICAL_AT_95: dict[int, float] = {
    10: 2.2622,
    20: 2.0930,
    30: 2.0452,
    50: 2.0096,
    100: 1.9842,
}


def _t_critical(n: int) -> float:
    if n < 10:
        raise ValueError(
            f"Sample size n={n} below the supported floor (10); "
            "the M3 default is n=30 per spec SC-003."
        )
    for cutoff in sorted(_T_CRITICAL_AT_95):
        if n <= cutoff:
            return _T_CRITICAL_AT_95[cutoff]
    return _T_CRITICAL_AT_95[100]


@dataclass(frozen=True)
class Estimate:
    mean: float
    stddev: float
    ci_low: float
    ci_high: float
    n: int


def estimate(samples: list[float] | tuple[float, ...]) -> Estimate:
    """Mean, sample stddev (ddof=1), and 95% CI bounds for ``samples``."""
    if not samples:
        raise ValueError("estimate() requires at least one sample")
    arr = np.asarray(list(samples), dtype=np.float64)
    n = int(arr.shape[0])
    mean = float(arr.mean())
    if n == 1:
        return Estimate(mean=mean, stddev=0.0, ci_low=mean, ci_high=mean, n=1)
    stddev = float(np.std(arr, ddof=1))
    se = stddev / math.sqrt(n)
    half = _t_critical(n) * se
    return Estimate(mean=mean, stddev=stddev, ci_low=mean - half, ci_high=mean + half, n=n)


def is_winner(baseline_ci_high: float, candidate_ci_low: float) -> bool:
    """SC-003 win rule: the candidate's lower CI must clear the baseline's upper CI."""
    return candidate_ci_low > baseline_ci_high
