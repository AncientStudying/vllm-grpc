"""M5.1 Supersedes-M1-time-axis table builder.

Per FR-020 + research.md R-5: for every M1 time-axis cell M5.1's matrix
covers, emit a :class:`SupersedesM1Entry` carrying the M1 verdict, the
M5.1 verdicts across widths, the supporting deltas + CIs, classification
(``verdict_confirmed`` / ``verdict_changed`` / ``mixed``), and a rationale
sentence. The classification logic compares M5.1's verdict against M1's
qualitative-direction inference; on a confirm vs change disagreement
across widths the row is classified ``mixed``.

M1 published cells under ``chat_completion`` and ``embed_completion`` map
to M5.1's ``chat_stream`` and ``embed`` matrix paths via:

    {"chat_completion": "chat_stream", "embed_completion": "embed"}

The mapping is applied when joining M1 cells to M5.1 matrix entries; the
``m1_path`` field on the emitted entry retains M1's literal naming so a
reader cross-referencing M1's reports can locate the source row directly.
"""

from __future__ import annotations

import json
from pathlib import Path

from vllm_grpc_bench.m3_types import (
    CellVerdict,
    ComparisonVerdict,
    M5_1Cell,
    SupersedesM1Entry,
)

_DEFAULT_FIXTURE = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "m1_time_axis_cells.json"
)

_M1_TO_M5_1_PATH: dict[str, str] = {
    "chat_completion": "chat_stream",
    "embed_completion": "embed",
}


def load_m1_time_axis_cells(
    fixture_path: Path = _DEFAULT_FIXTURE,
) -> list[tuple[str, int, str, str]]:
    """Load M1's time-axis cell list from ``fixture_path``.

    Returns a list of ``(m1_path, m1_concurrency, m1_verdict_literal,
    m1_source_report)`` tuples — the four fields ``build_supersedes_m1_time``
    consumes.
    """
    if not fixture_path.exists():
        raise FileNotFoundError(
            f"M1 time-axis fixture not found at {fixture_path}; "
            "expected hand-curated JSON per research.md R-5"
        )
    data = json.loads(fixture_path.read_text())
    out: list[tuple[str, int, str, str]] = []
    for entry in data:
        out.append(
            (
                entry["m1_path"],
                int(entry["m1_concurrency"]),
                entry["m1_verdict_literal"],
                entry["m1_source_report"],
            )
        )
    return out


def _m1_verdict_direction(m1_literal: str) -> str:
    """Infer M1's verdict direction from its prose literal.

    Returns one of ``"grpc"``, ``"rest"``, ``"no_winner"`` so the builder
    can compare against M5.1's structured ComparisonVerdict.
    """
    lower = m1_literal.lower()
    if "no_winner" in lower or "no winner" in lower:
        return "no_winner"
    if "grpc faster" in lower or "grpc-recommend" in lower or "tuned-grpc" in lower:
        return "grpc"
    if "rest faster" in lower or "rest-recommend" in lower:
        return "rest"
    return "no_winner"


def _m5_1_verdict_direction(verdict: ComparisonVerdict) -> str:
    """Map a structured M5.1 ComparisonVerdict literal to one of the three
    qualitative directions used to classify supersession rows.
    """
    if verdict in (
        "tuned_grpc_multiplexed_recommend",
        "tuned_grpc_channels_recommend",
        "tuned_grpc_recommend",
    ):
        return "grpc"
    if verdict == "rest_recommend":
        return "rest"
    return "no_winner"


def _best_grpc_verdict_at_cell(cell: M5_1Cell) -> CellVerdict | None:
    """Pick the best-of-tuned-gRPC verdict for the cell.

    M5.1's matrix carries 2 (at c=1) or 3 verdicts per cell. The
    supersession row reflects the strongest tuned-gRPC outcome (per
    Clarifications 2026-05-11; the default-gRPC row is informational only,
    not the canonical head-to-head).
    """
    candidates = [
        v
        for v in cell.verdicts
        if v.grpc_sub_cohort in ("tuned_grpc_multiplexed", "tuned_grpc_channels", "tuned_grpc")
    ]
    if not candidates:
        return None
    # Prefer the most-negative-delta one (gRPC most-faster).
    return min(candidates, key=lambda v: v.delta_pct)


def build_supersedes_m1_time(
    m5_1_matrix: list[M5_1Cell],
    m1_cells: list[tuple[str, int, str, str]] | None = None,
    *,
    fixture_path: Path = _DEFAULT_FIXTURE,
) -> list[SupersedesM1Entry]:
    """Build the Supersedes-M1-time-axis table per FR-020.

    For each M1 cell, joins M5.1 matrix entries on (mapped path, concurrency)
    across all three widths and emits one ``SupersedesM1Entry`` summarizing
    the supersession outcome.
    """
    if m1_cells is None:
        m1_cells = load_m1_time_axis_cells(fixture_path)

    # Index M5.1 matrix by (m5_1_path, concurrency, hidden_size).
    by_key: dict[tuple[str, int, int], M5_1Cell] = {}
    for cell in m5_1_matrix:
        by_key[(cell.path, cell.concurrency, cell.hidden_size)] = cell

    entries: list[SupersedesM1Entry] = []
    for m1_path, m1_concurrency, m1_verdict_literal, m1_source_report in m1_cells:
        mapped = _M1_TO_M5_1_PATH.get(m1_path)
        if mapped is None:
            continue
        verdicts_per_width: dict[int, ComparisonVerdict] = {}
        deltas_per_width: dict[int, float] = {}
        cis_per_width: dict[int, tuple[float, float]] = {}
        for w in (2048, 4096, 8192):
            matrix_cell = by_key.get((mapped, m1_concurrency, w))
            if matrix_cell is None:
                continue
            best = _best_grpc_verdict_at_cell(matrix_cell)
            if best is None:
                continue
            verdicts_per_width[w] = best.verdict
            deltas_per_width[w] = best.delta_pct
            cis_per_width[w] = best.ci_pct
        if not verdicts_per_width:
            continue

        m1_dir = _m1_verdict_direction(m1_verdict_literal)
        m5_1_directions = {_m5_1_verdict_direction(v) for v in verdicts_per_width.values()}
        if m5_1_directions == {m1_dir}:
            classification = "verdict_confirmed"
        elif m1_dir in m5_1_directions and len(m5_1_directions) > 1:
            classification = "mixed"
        else:
            classification = "verdict_changed"

        rationale = _build_rationale(m1_dir, classification, verdicts_per_width, deltas_per_width)
        entries.append(
            SupersedesM1Entry(
                m1_path=m1_path,  # type: ignore[arg-type]
                m1_concurrency=m1_concurrency,
                m1_verdict_literal=m1_verdict_literal,
                m1_source_report=m1_source_report,
                m5_1_verdict_per_width=verdicts_per_width,
                m5_1_supporting_delta_pct=deltas_per_width,
                m5_1_supporting_ci_pct=cis_per_width,
                classification=classification,  # type: ignore[arg-type]
                rationale=rationale,
            )
        )
    return entries


def _build_rationale(
    m1_dir: str,
    classification: str,
    verdicts_per_width: dict[int, ComparisonVerdict],
    deltas_per_width: dict[int, float],
) -> str:
    """One-sentence rationale; MockEngine caveat appended on verdict_changed."""
    summary = ", ".join(
        f"h{w}: {verdicts_per_width[w]} (Δ {deltas_per_width[w]:+.1f}%)"
        for w in sorted(verdicts_per_width)
    )
    base = f"M5.1 cross-host pattern: {summary}."
    if classification == "verdict_changed":
        return (
            base + " Verdict differs from M1's loopback-era finding; note that"
            " M5.1 measures MockEngine (engine cost held constant) while M1"
            " measured real vLLM — M7 will re-validate under real-engine"
            " cost. Per Edge Case 2."
        )
    if classification == "mixed":
        return (
            base + " Widths split between confirm and change — read the per-width"
            " row before generalizing the M1 result."
        )
    return base + " M1's directional finding holds across M5.1's widths."
