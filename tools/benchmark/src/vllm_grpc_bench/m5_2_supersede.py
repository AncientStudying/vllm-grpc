"""M5.2 Supersedes-M5.1 table builder (T035).

For every M5.1 cell M5.2's matrix covers, this module emits one
:class:`SupersedesM5_1Entry` per (cell × gRPC cohort) row. Each row
carries M5.1's verdict literal (against ``rest_plain_tcp``), M5.2's
protocol-comparison verdict (against ``rest_https_edge``), supporting
CI-bounded numbers, and a five-way category per FR-016 + research R-6:

* ``verdict_confirmed`` — literals match AND both CI-supported.
* ``verdict_changed``   — literals differ AND M5.1 was not no_winner.
* ``noise_resolved``    — M5.1 was no_winner; M5.2 has a CI-supported
  recommend.
* ``transport_dependent`` — M5.2's protocol-comparison verdict against
  rest_https_edge differs from what the same comparison would have been
  against rest_plain_tcp (i.e., the HTTPS-edge transport moved the
  verdict).
* ``confirmed_unavailable`` — both M5.1 and M5.2 are comparison_unavailable.

The builder is invoked at report-build time by the regenerator (per
FR-012b) — not at sweep time. The M5.1 published file at
``docs/benchmarks/m5_1-rest-vs-grpc.json`` is loaded read-only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m3_types import (
    M5_2CohortKind,
    ProtocolComparisonRow,
    ProtocolComparisonVerdict,
    SupersedesM5_1Category,
    SupersedesM5_1Entry,
    TransportOnlyRow,
)

_M5_1_PUBLISHED_PATH = Path("docs/benchmarks/m5_1-rest-vs-grpc.json")


class M5_1PublishedJsonUnavailable(RuntimeError):
    """Raised when the M5.1 published JSON is missing or schema-incompatible.

    Maps to regenerator exit code 9 per ``contracts/m5_2-regenerator.md``.
    The operator's pre-PR checklist explicitly lists "M5.1 published JSON
    present at ``docs/benchmarks/m5_1-rest-vs-grpc.json``" as a
    prerequisite.
    """


def load_m5_1_cells(path: Path = _M5_1_PUBLISHED_PATH) -> list[dict[str, Any]]:
    """Load M5.1's published per-cell verdicts as a list of dicts.

    Returns a list of objects from ``m5_1_matrix``. The shape is M5.1's
    ``M5_1Cell`` dataclass after dataclasses.asdict-style serialization.
    """
    if not path.exists():
        raise M5_1PublishedJsonUnavailable(
            f"M5.1 published JSON not found at {path}; M5.2's Supersedes-M5.1 "
            "table cannot be built without it. Run M5.1's sweep first (or "
            "check that the file is on disk + committed)."
        )
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise M5_1PublishedJsonUnavailable(
            f"M5.1 published JSON at {path} failed to parse: {exc}"
        ) from exc
    matrix = data.get("m5_1_matrix")
    if not isinstance(matrix, list):
        raise M5_1PublishedJsonUnavailable(
            f"M5.1 published JSON at {path} is missing the 'm5_1_matrix' "
            "top-level key or it's not a list"
        )
    return matrix


def _m5_1_cell_key(cell: dict[str, Any]) -> tuple[str, int, int]:
    return (cell["path"], int(cell["hidden_size"]), int(cell["concurrency"]))


def _m5_1_verdict_for_grpc_cohort(cell: dict[str, Any], grpc_cohort: M5_2CohortKind) -> str:
    """Pick M5.1's verdict literal for a given gRPC cohort in the M5.1 cell.

    M5.1 carries one row per gRPC sub-cohort in ``cell["verdicts"]``. The
    matching row's ``verdict`` field is M5.1's literal — returned as-is
    (free string) so M5.2's row preserves M5.1's exact wording.
    """
    for row in cell.get("verdicts", []):
        if row.get("grpc_sub_cohort") == grpc_cohort:
            return str(row.get("verdict", "no_winner"))
    return "comparison_unavailable"


def _category_for_row(
    m5_1_verdict: str,
    m5_2_verdict: ProtocolComparisonVerdict,
    *,
    transport_dependent: bool,
) -> SupersedesM5_1Category:
    """Decide the five-way category per research R-6.

    ``transport_dependent`` indicates that the same head-to-head against
    rest_plain_tcp would have produced a different M5.2 verdict than the
    one observed against rest_https_edge. That is the operative test for
    the "HTTPS-edge moved the verdict" case.
    """
    m5_1_unavailable = m5_1_verdict == "comparison_unavailable"
    m5_2_unavailable = m5_2_verdict == "comparison_unavailable"
    if m5_1_unavailable and m5_2_unavailable:
        return "confirmed_unavailable"
    if m5_1_verdict == "no_winner" and m5_2_verdict not in (
        "no_winner",
        "comparison_unavailable",
    ):
        return "noise_resolved"
    if transport_dependent and not m5_2_unavailable:
        return "transport_dependent"
    if m5_1_verdict == m5_2_verdict:
        return "verdict_confirmed"
    # Treat M5.1's ``rest_recommend`` as semantically equivalent to M5.2's
    # ``rest_https_edge_recommend`` for confirmation purposes — the rename
    # is part of M5.2's network-path-naming-honesty change, not a verdict
    # shift (per data-model.md "ComparisonVerdict stays in place unchanged").
    if (m5_1_verdict, m5_2_verdict) == ("rest_recommend", "rest_https_edge_recommend"):
        return "verdict_confirmed"
    return "verdict_changed"


def _build_rationale(
    m5_1_verdict: str,
    m5_2_verdict: ProtocolComparisonVerdict,
    delta_ms: float,
    ci_low: float,
    ci_high: float,
    category: SupersedesM5_1Category,
) -> str:
    """One-line free-text rationale rendered verbatim in the markdown."""
    base = (
        f"M5.1={m5_1_verdict!r}; M5.2={m5_2_verdict!r}; "
        f"delta={delta_ms:+.1f} ms (CI [{ci_low:+.1f}, {ci_high:+.1f}])."
    )
    if category == "noise_resolved":
        return base + " Noise resolved by the n=100 → n=250 resolution increase."
    if category == "transport_dependent":
        return (
            base + " HTTPS-edge transport cost moved the comparison; the network path is "
            "load-bearing."
        )
    if category == "confirmed_unavailable":
        return base + " Both M5.1 and M5.2 are comparison_unavailable."
    if category == "verdict_changed":
        return (
            base + " Verdict shifted; the n=250 resolution increase + HTTPS-edge "
            "transport surfaces the change."
        )
    return base + " M5.1's verdict holds at M5.2's resolution and transport."


def build_supersedes_m5_1(
    m5_2_protocol_rows: list[ProtocolComparisonRow],
    *,
    m5_2_transport_rows: list[TransportOnlyRow] | None = None,
    m5_1_cells: list[dict[str, Any]] | None = None,
    m5_1_published_path: Path = _M5_1_PUBLISHED_PATH,
) -> list[SupersedesM5_1Entry]:
    """Build the Supersedes-M5.1 table.

    ``m5_2_protocol_rows`` is the full protocol-comparison output from
    :func:`m5_2_sweep.emit_cell_verdicts`. ``m5_2_transport_rows`` is the
    matching transport-only output (used to detect ``transport_dependent``
    rows — when the transport-only verdict says rest_plain_tcp wins, the
    same M5.1-shaped comparison (which used rest_plain_tcp) would have
    yielded a different M5.2 verdict than the one observed against
    rest_https_edge).
    """
    if m5_1_cells is None:
        m5_1_cells = load_m5_1_cells(m5_1_published_path)
    by_key = {_m5_1_cell_key(c): c for c in m5_1_cells}
    transport_by_cell: dict[tuple[str, int, int], TransportOnlyRow] = {}
    for t_row in m5_2_transport_rows or []:
        transport_by_cell[(t_row.path, t_row.hidden_size, t_row.concurrency)] = t_row

    entries: list[SupersedesM5_1Entry] = []
    for row in m5_2_protocol_rows:
        key = (row.path, row.hidden_size, row.concurrency)
        m5_1_cell = by_key.get(key)
        if m5_1_cell is None:
            # M5.2 covered a cell M5.1 didn't publish; can't supersede.
            continue
        m5_1_verdict = _m5_1_verdict_for_grpc_cohort(m5_1_cell, row.grpc_cohort)

        # transport_dependent detection: the transport-only row at this
        # cell says either rest is faster than the other (HTTPS-edge moved
        # the comparison). When transport-only is no_winner OR
        # rest_https_edge_recommend, the HTTPS-edge isn't slower than
        # plain-TCP, so the protocol-comparison verdict against
        # rest_https_edge is at least as REST-friendly as the same
        # comparison against rest_plain_tcp would have been — the verdict
        # MAY still be transport_dependent if the M5.1 verdict literal
        # disagrees with M5.2's. We treat ``rest_plain_tcp_recommend`` on
        # the transport-only row as the strict indicator: the HTTPS-edge
        # has a measurable transport cost so a head-to-head against
        # plain-TCP would have favored the protocol that won against
        # rest_https_edge by a larger margin.
        transport_row = transport_by_cell.get(key)
        transport_dependent = bool(
            transport_row
            and transport_row.verdict == "rest_plain_tcp_recommend"
            and m5_1_verdict != row.verdict
        )

        category = _category_for_row(
            m5_1_verdict, row.verdict, transport_dependent=transport_dependent
        )
        rationale = _build_rationale(
            m5_1_verdict,
            row.verdict,
            row.delta_median_ms,
            row.ci_lower_ms,
            row.ci_upper_ms,
            category,
        )
        entries.append(
            SupersedesM5_1Entry(
                path=row.path,
                hidden_size=row.hidden_size,
                concurrency=row.concurrency,
                grpc_cohort=row.grpc_cohort,
                m5_1_verdict=m5_1_verdict,
                m5_2_verdict=row.verdict,
                m5_2_delta_median_ms=row.delta_median_ms,
                m5_2_ci_lower_ms=row.ci_lower_ms,
                m5_2_ci_upper_ms=row.ci_upper_ms,
                category=category,
                rationale=rationale,
            )
        )
    return entries
