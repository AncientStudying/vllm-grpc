"""T025 — Supersedes-M5.1 table builder tests.

Verifies the five-way category logic per FR-016 + research R-6 against a
small in-memory M5.1 cell fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from vllm_grpc_bench.m3_types import (
    ProtocolComparisonRow,
    TransportOnlyRow,
)
from vllm_grpc_bench.m5_2_supersede import (
    M5_1PublishedJsonUnavailable,
    build_supersedes_m5_1,
    load_m5_1_cells,
)


def _m5_1_cell(
    path: str,
    hidden_size: int,
    concurrency: int,
    *,
    grpc_cohort: str,
    verdict: str,
) -> dict:
    return {
        "path": path,
        "hidden_size": hidden_size,
        "concurrency": concurrency,
        "verdicts": [
            {
                "grpc_sub_cohort": grpc_cohort,
                "verdict": verdict,
                "delta_pct": -5.0,
                "ci_pct": [-7.0, -3.0],
                "metric": "ttft" if path == "chat_stream" else "wallclock",
            }
        ],
    }


def _m5_2_protocol_row(
    *,
    path: str,
    hidden_size: int,
    concurrency: int,
    grpc_cohort: str,
    verdict: str,
    delta_ms: float = -5.0,
    ci_low: float = -7.0,
    ci_high: float = -3.0,
) -> ProtocolComparisonRow:
    return ProtocolComparisonRow(
        path=path,  # type: ignore[arg-type]
        hidden_size=hidden_size,
        concurrency=concurrency,
        grpc_cohort=grpc_cohort,  # type: ignore[arg-type]
        verdict=verdict,  # type: ignore[arg-type]
        comparison_unavailable_reason=None,
        delta_median_ms=delta_ms,
        ci_lower_ms=ci_low,
        ci_upper_ms=ci_high,
    )


def _m5_2_transport_row(
    *, path: str, hidden_size: int, concurrency: int, verdict: str
) -> TransportOnlyRow:
    return TransportOnlyRow(
        path=path,  # type: ignore[arg-type]
        hidden_size=hidden_size,
        concurrency=concurrency,
        verdict=verdict,  # type: ignore[arg-type]
        comparison_unavailable_reason=None,
        delta_median_ms=0.0,
        ci_lower_ms=-1.0,
        ci_upper_ms=1.0,
    )


def test_verdict_confirmed_when_literals_match() -> None:
    m5_1_cells = [
        _m5_1_cell(
            "chat_stream",
            2048,
            4,
            grpc_cohort="default_grpc",
            verdict="default_grpc_recommend",
        )
    ]
    rows = [
        _m5_2_protocol_row(
            path="chat_stream",
            hidden_size=2048,
            concurrency=4,
            grpc_cohort="default_grpc",
            verdict="default_grpc_recommend",
        )
    ]
    entries = build_supersedes_m5_1(rows, m5_1_cells=m5_1_cells)
    assert len(entries) == 1
    assert entries[0].category == "verdict_confirmed"


def test_verdict_changed_when_literals_differ() -> None:
    m5_1_cells = [
        _m5_1_cell(
            "chat_stream",
            2048,
            4,
            grpc_cohort="default_grpc",
            verdict="default_grpc_recommend",
        )
    ]
    rows = [
        _m5_2_protocol_row(
            path="chat_stream",
            hidden_size=2048,
            concurrency=4,
            grpc_cohort="default_grpc",
            verdict="rest_https_edge_recommend",
        )
    ]
    entries = build_supersedes_m5_1(rows, m5_1_cells=m5_1_cells)
    assert entries[0].category == "verdict_changed"


def test_noise_resolved_when_m5_1_no_winner_and_m5_2_recommends() -> None:
    """M5.2-headline category — the n=100 → n=250 resolution increase
    resolved an M5.1 no_winner verdict to a CI-supported recommend."""
    m5_1_cells = [
        _m5_1_cell(
            "embed",
            4096,
            8,
            grpc_cohort="default_grpc",
            verdict="no_winner",
        )
    ]
    rows = [
        _m5_2_protocol_row(
            path="embed",
            hidden_size=4096,
            concurrency=8,
            grpc_cohort="default_grpc",
            verdict="default_grpc_recommend",
        )
    ]
    entries = build_supersedes_m5_1(rows, m5_1_cells=m5_1_cells)
    assert entries[0].category == "noise_resolved"
    assert "resolved" in entries[0].rationale
    assert "n=250" in entries[0].rationale


def test_transport_dependent_when_transport_only_says_plain_tcp_wins() -> None:
    """When the transport-only row's verdict is rest_plain_tcp_recommend
    AND the M5.1 verdict literal disagrees with M5.2's, the category is
    transport_dependent (HTTPS-edge moved the comparison)."""
    m5_1_cells = [
        _m5_1_cell(
            "chat_stream",
            2048,
            4,
            grpc_cohort="default_grpc",
            verdict="default_grpc_recommend",
        )
    ]
    rows = [
        _m5_2_protocol_row(
            path="chat_stream",
            hidden_size=2048,
            concurrency=4,
            grpc_cohort="default_grpc",
            verdict="rest_https_edge_recommend",
        )
    ]
    transport_rows = [
        _m5_2_transport_row(
            path="chat_stream",
            hidden_size=2048,
            concurrency=4,
            verdict="rest_plain_tcp_recommend",
        )
    ]
    entries = build_supersedes_m5_1(rows, m5_2_transport_rows=transport_rows, m5_1_cells=m5_1_cells)
    assert entries[0].category == "transport_dependent"


def test_confirmed_unavailable_when_both_are_comparison_unavailable() -> None:
    m5_1_cells = [
        _m5_1_cell(
            "embed",
            8192,
            8,
            grpc_cohort="default_grpc",
            verdict="comparison_unavailable",
        )
    ]
    rows = [
        _m5_2_protocol_row(
            path="embed",
            hidden_size=8192,
            concurrency=8,
            grpc_cohort="default_grpc",
            verdict="comparison_unavailable",
        )
    ]
    entries = build_supersedes_m5_1(rows, m5_1_cells=m5_1_cells)
    assert entries[0].category == "confirmed_unavailable"


def test_m5_1_rest_recommend_confirms_against_m5_2_rest_https_edge() -> None:
    """M5.1's ``rest_recommend`` literal is the rest_plain_tcp recommend
    (it was M5.1's only REST cohort). M5.2 renames it to
    ``rest_https_edge_recommend`` against the new HTTPS-edge baseline.
    The rename alone is NOT a verdict change — it's a network-path-naming
    honesty fix per data-model.md.
    """
    m5_1_cells = [
        _m5_1_cell(
            "chat_stream",
            4096,
            1,
            grpc_cohort="tuned_grpc",
            verdict="rest_recommend",
        )
    ]
    rows = [
        _m5_2_protocol_row(
            path="chat_stream",
            hidden_size=4096,
            concurrency=1,
            grpc_cohort="tuned_grpc",
            verdict="rest_https_edge_recommend",
        )
    ]
    entries = build_supersedes_m5_1(rows, m5_1_cells=m5_1_cells)
    assert entries[0].category == "verdict_confirmed"


def test_loader_raises_when_published_json_missing(tmp_path: Path) -> None:
    bad = tmp_path / "missing.json"
    with pytest.raises(M5_1PublishedJsonUnavailable):
        load_m5_1_cells(bad)


def test_loader_raises_when_published_json_malformed(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all")
    with pytest.raises(M5_1PublishedJsonUnavailable):
        load_m5_1_cells(bad)


def test_verdict_changed_rationale_uses_topology_aware_language() -> None:
    """Rationale strings MUST frame ``verdict_changed`` rows as
    topology-dependent rather than implying M5.1 was wrong.

    M5.1 measured REST + gRPC over the SAME plain-TCP network path (a
    deliberate controlled experiment isolating protocol cost). M5.2
    measures REST over Modal's HTTPS edge against gRPC over plain-TCP
    (the hobbyist-renting-GPU topology). Both are honest, topology-
    specific measurements. The rationale MUST name which deployment
    shape each verdict applies to so an enterprise reader doesn't
    generalize an M5.2 verdict to a flat-network deployment without
    an HTTPS edge in front of REST.
    """
    m5_1_cells = [
        _m5_1_cell(
            "chat_stream",
            4096,
            1,
            grpc_cohort="tuned_grpc",
            verdict="tuned_grpc_recommend",
        )
    ]
    rows = [
        _m5_2_protocol_row(
            path="chat_stream",
            hidden_size=4096,
            concurrency=1,
            grpc_cohort="tuned_grpc",
            verdict="rest_https_edge_recommend",
            delta_ms=35.5,
            ci_low=34.9,
            ci_high=36.3,
        )
    ]
    entries = build_supersedes_m5_1(rows, m5_1_cells=m5_1_cells)
    rationale = entries[0].rationale
    assert entries[0].category == "verdict_changed"
    # MUST surface both topology labels.
    assert "same-network-path topology" in rationale, rationale
    assert "HTTPS-edge topology" in rationale, rationale
    # MUST tell the reader to pick by deployment shape, not treat one as
    # superseding the other.
    assert "pick by deployment shape" in rationale, rationale
    # MUST NOT use language implying M5.1 was hiding something / wrong.
    forbidden = ("shifted", "surfaces the change", "was wrong", "superseded")
    for phrase in forbidden:
        assert phrase not in rationale, (
            f"rationale must avoid {phrase!r} — that framing implies M5.1 was "
            f"measuring the wrong thing rather than measuring a different topology"
        )


def test_verdict_confirmed_rationale_names_both_topologies() -> None:
    """``verdict_confirmed`` means the finding generalizes across both
    topologies — the rationale MUST say so explicitly so an enterprise
    reader can rely on the verdict for their flat-network deployment.
    """
    m5_1_cells = [
        _m5_1_cell(
            "chat_stream",
            2048,
            4,
            grpc_cohort="default_grpc",
            verdict="rest_recommend",
        )
    ]
    rows = [
        _m5_2_protocol_row(
            path="chat_stream",
            hidden_size=2048,
            concurrency=4,
            grpc_cohort="default_grpc",
            verdict="rest_https_edge_recommend",
        )
    ]
    entries = build_supersedes_m5_1(rows, m5_1_cells=m5_1_cells)
    rationale = entries[0].rationale
    assert entries[0].category == "verdict_confirmed"
    assert "generalizes" in rationale or "both deployment shapes" in rationale, rationale


def test_transport_dependent_rationale_names_network_path_as_load_bearing() -> None:
    """``transport_dependent`` is the M5.2-specific category that names
    the HTTPS-edge transport cost as the operative variable. The
    rationale MUST surface the network-path-vs-protocol distinction so
    a reader can locate the verdict in their own topology.
    """
    m5_1_cells = [
        _m5_1_cell(
            "chat_stream",
            2048,
            4,
            grpc_cohort="default_grpc",
            verdict="default_grpc_recommend",
        )
    ]
    rows = [
        _m5_2_protocol_row(
            path="chat_stream",
            hidden_size=2048,
            concurrency=4,
            grpc_cohort="default_grpc",
            verdict="rest_https_edge_recommend",
        )
    ]
    transport_rows = [
        _m5_2_transport_row(
            path="chat_stream",
            hidden_size=2048,
            concurrency=4,
            verdict="rest_plain_tcp_recommend",
        )
    ]
    entries = build_supersedes_m5_1(rows, m5_2_transport_rows=transport_rows, m5_1_cells=m5_1_cells)
    rationale = entries[0].rationale
    assert entries[0].category == "transport_dependent"
    assert "Network path is load-bearing" in rationale, rationale
    assert "rest_plain_tcp" in rationale, rationale


def test_confirmed_unavailable_rationale_names_both_topologies_inconclusive() -> None:
    m5_1_cells = [
        _m5_1_cell(
            "embed",
            8192,
            8,
            grpc_cohort="default_grpc",
            verdict="comparison_unavailable",
        )
    ]
    rows = [
        _m5_2_protocol_row(
            path="embed",
            hidden_size=8192,
            concurrency=8,
            grpc_cohort="default_grpc",
            verdict="comparison_unavailable",
        )
    ]
    entries = build_supersedes_m5_1(rows, m5_1_cells=m5_1_cells)
    rationale = entries[0].rationale
    assert entries[0].category == "confirmed_unavailable"
    assert "inconclusive" in rationale, rationale
    assert "both topologies" in rationale, rationale


def test_loader_accepts_real_m5_1_published_json_shape() -> None:
    """Read the actual M5.1 published JSON. Per project memory, this file
    must exist for the Supersedes-M5.1 table to build."""
    cells = load_m5_1_cells(Path("docs/benchmarks/m5_1-rest-vs-grpc.json"))
    assert len(cells) == 18
    for c in cells:
        assert "path" in c
        assert "hidden_size" in c
        assert "concurrency" in c
        assert "verdicts" in c
