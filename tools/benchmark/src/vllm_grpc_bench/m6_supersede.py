"""M6 verdict classifier + M5.2 baseline reader (T022 / T031-T033 / T046).

Phase 2 carries the baseline-precondition loader + the M5.2 cohort-name
mapping helper (R-6). Phase 3 (US1) adds the full ``classify_cell``
implementation per Research R-7. Both smoke and full sweep validate the
M5.2 baseline file via :func:`load_and_validate_m5_2_baseline` before any
Modal compute is consumed (FR-014 sub-clause "M5.2 baseline file
precondition").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m6_types import (
    M6_BURIED_BY_ENGINE_FACTOR,
    M6_CELL_COMPLETE_FLOOR,
    M6_CELLS,
    M6_CHAT_MAX_TOKENS,
    M6Cell,
    M6Concurrency,
    M6Path,
)

_DEFAULT_M5_2_BASELINE_PATH = Path("docs/benchmarks/m5_2-transport-vs-tuning.json")


class M5_2BaselineMissingCellError(RuntimeError):
    """Raised when the M5.2 baseline JSON lacks a verdict row for an M6 cell.

    Maps to ``--m6`` exit code 1 and ``--m6-smoke`` exit code 2 per
    ``contracts/cli.md``. The error message names the failing cell.
    """

    def __init__(self, cell: tuple[M6Path, int, M6Concurrency], grpc_cohort: str):
        self.cell = cell
        self.grpc_cohort = grpc_cohort
        path, hidden_size, c = cell
        super().__init__(
            f"M5.2 baseline missing cell entry: path={path} hidden_size={hidden_size} "
            f"concurrency={c} grpc_cohort={grpc_cohort} (expected at "
            f"protocol_comparison_verdicts[] in the M5.2 baseline JSON)"
        )


def map_m6_grpc_cohort_to_m5_2_lookup(concurrency: M6Concurrency) -> str:
    """R-6 cohort-name reconciliation for M5.2 winner-delta lookup.

    M6's ``tuned_grpc_multiplexed`` cohort maps to M5.2's published
    ``tuned_grpc`` at c=1 (M5.2's c=1 sweeps used ``tuned_grpc`` because
    the multiplexed/channels distinction has no meaning at single
    concurrency), and to ``tuned_grpc_multiplexed`` at c≥2. M6's own
    published cohort name remains ``tuned_grpc_multiplexed`` for all 6
    cells — the mapping only affects the M5.2-baseline lookup direction.
    """
    return "tuned_grpc" if concurrency == 1 else "tuned_grpc_multiplexed"


def _find_baseline_row(
    verdicts: list[dict[str, Any]],
    path: M6Path,
    hidden_size: int,
    concurrency: M6Concurrency,
    grpc_cohort: str,
) -> dict[str, Any] | None:
    for row in verdicts:
        if (
            row.get("path") == path
            and int(row.get("hidden_size", -1)) == hidden_size
            and int(row.get("concurrency", -1)) == concurrency
            and row.get("grpc_cohort") == grpc_cohort
            and row.get("rest_cohort") == "rest_https_edge"
        ):
            return row
    return None


def load_and_validate_m5_2_baseline(
    path: Path = _DEFAULT_M5_2_BASELINE_PATH,
) -> dict[str, Any]:
    """Load + validate the M5.2 baseline JSON.

    Returns the parsed JSON object. Raises
    :class:`M5_2BaselineMissingCellError` if any of the 6 M6 cells lacks a
    matching ``protocol_comparison_verdicts[]`` row under the R-6 cohort
    mapping. Raises ``FileNotFoundError`` if the file is missing and
    ``json.JSONDecodeError`` if the file is not valid JSON.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"M5.2 baseline JSON not found at {path}; M6 cannot proceed without it "
            f"(FR-014 sub-clause 'M5.2 baseline file precondition')."
        )
    data: dict[str, Any] = json.loads(path.read_text())
    verdicts = data.get("protocol_comparison_verdicts")
    if not isinstance(verdicts, list):
        raise M5_2BaselineMissingCellError(
            cell=("embed", 4096, 1),
            grpc_cohort="(missing protocol_comparison_verdicts[] in baseline JSON)",
        )
    for cell_tuple in M6_CELLS:
        path_, h, c = cell_tuple
        grpc_cohort_name = map_m6_grpc_cohort_to_m5_2_lookup(c)
        row = _find_baseline_row(verdicts, path_, h, c, grpc_cohort_name)
        if row is None:
            raise M5_2BaselineMissingCellError(cell=(path_, h, c), grpc_cohort=grpc_cohort_name)
        # Also check the default_grpc row at the same cell — the classifier
        # consumes either grpc cohort depending on cohort_pair choice; we
        # validate the tuned cohort here since that's the M5.2-canonical
        # winner-direction source per R-5/R-6.
    return data


def get_m5_2_winner_delta(
    baseline: dict[str, Any],
    cell: M6Cell,
) -> tuple[float | None, str | None]:
    """Look up the M5.2 winner delta + verdict for a given M6 cell.

    Returns ``(|delta_median_ms|, verdict_string)``. If M5.2's verdict for
    the cell is ``no_winner``, the magnitude is None per FR-014's
    "M5.2 verdict was no_winner" sub-case.
    """
    verdicts = baseline.get("protocol_comparison_verdicts")
    if not isinstance(verdicts, list):
        return None, None
    grpc_cohort_name = map_m6_grpc_cohort_to_m5_2_lookup(cell.concurrency)
    row = _find_baseline_row(
        verdicts, cell.path, cell.hidden_size, cell.concurrency, grpc_cohort_name
    )
    if row is None:
        return None, None
    verdict_str = row.get("verdict")
    delta_raw = row.get("delta_median_ms")
    if verdict_str == "no_winner" or delta_raw is None:
        return None, verdict_str if isinstance(verdict_str, str) else None
    try:
        return abs(float(delta_raw)), verdict_str if isinstance(verdict_str, str) else None
    except (TypeError, ValueError):
        return None, verdict_str if isinstance(verdict_str, str) else None


# Re-export so callers can ``from m6_supersede import M6_*`` without
# touching m6_types directly for these classifier-specific constants.
__all__ = [
    "M5_2BaselineMissingCellError",
    "M6_BURIED_BY_ENGINE_FACTOR",
    "M6_CELL_COMPLETE_FLOOR",
    "M6_CHAT_MAX_TOKENS",
    "_DEFAULT_M5_2_BASELINE_PATH",
    "get_m5_2_winner_delta",
    "load_and_validate_m5_2_baseline",
    "map_m6_grpc_cohort_to_m5_2_lookup",
]
