"""T040 — Supersedes-M1-time-axis table builder tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from vllm_grpc_bench.m3_types import CellVerdict, M5_1Cell
from vllm_grpc_bench.m5_1_supersede import (
    build_supersedes_m1_time,
    load_m1_time_axis_cells,
)


def _verdict(grpc_sub_cohort: str, verdict: str, delta: float) -> CellVerdict:
    return CellVerdict(
        grpc_sub_cohort=grpc_sub_cohort,  # type: ignore[arg-type]
        verdict=verdict,  # type: ignore[arg-type]
        delta_pct=delta,
        ci_pct=(delta - 3.0, delta + 3.0),
        metric="ttft",
    )


def _cell(
    path: str,
    hidden_size: int,
    concurrency: int,
    grpc_verdict: str,
    grpc_delta: float,
) -> M5_1Cell:
    return M5_1Cell(
        path=path,  # type: ignore[arg-type]
        hidden_size=hidden_size,  # type: ignore[arg-type]
        concurrency=concurrency,  # type: ignore[arg-type]
        rest_cohort_key=f"rest:{path}:h{hidden_size}:c{concurrency}",
        default_grpc_cohort_key=f"grpc-default:{path}:h{hidden_size}:c{concurrency}",
        tuned_grpc_multiplexed_cohort_key=f"grpc-tuned-mux:{path}:h{hidden_size}:c{concurrency}",
        tuned_grpc_channels_cohort_key=(
            f"grpc-tuned-ch:{path}:h{hidden_size}:c{concurrency}" if concurrency >= 2 else None
        ),
        verdicts=[
            _verdict(
                "tuned_grpc_multiplexed" if concurrency >= 2 else "tuned_grpc",
                grpc_verdict,
                grpc_delta,
            ),
            _verdict("default_grpc", "no_winner", -1.0),
        ],
        comparison_unavailable=False,
        comparison_unavailable_reason=None,
        rtt_ms_median=52.0,
        rtt_ms_p95=58.0,
        low_rtt_caveat=False,
    )


def test_load_m1_time_axis_cells_returns_six_rows() -> None:
    """T040 (a): hand-curated fixture is loadable and shape-correct."""
    cells = load_m1_time_axis_cells()
    assert len(cells) == 6
    paths = {c[0] for c in cells}
    assert paths == {"chat_completion", "embed_completion"}
    concurrencies = {c[1] for c in cells}
    assert concurrencies == {1, 4, 8}


def test_load_m1_time_axis_cells_missing_raises() -> None:
    with pytest.raises(FileNotFoundError, match=r"M1 time-axis fixture"):
        load_m1_time_axis_cells(Path("/no/such/file.json"))


def test_build_supersedes_emits_one_per_m1_cell() -> None:
    """T040 (b): one SupersedesM1Entry per M1 (path, c) M5.1 covers."""
    matrix = []
    for path in ("chat_stream", "embed"):
        for w in (2048, 4096, 8192):
            for c in (1, 4, 8):
                matrix.append(_cell(path, w, c, "tuned_grpc_multiplexed_recommend", -20.0))
    entries = build_supersedes_m1_time(matrix)
    assert len(entries) == 6
    # Path naming preserves M1's literal ("chat_completion", not "chat_stream").
    paths = {e.m1_path for e in entries}
    assert paths == {"chat_completion", "embed_completion"}


def test_classification_verdict_confirmed_when_all_widths_match_m1() -> None:
    """T040 (c): every width matches M1's gRPC-faster direction → verdict_confirmed."""
    # M1 c=8 embed = "gRPC faster" — fixture row 5.
    matrix = []
    for w in (2048, 4096, 8192):
        matrix.append(_cell("embed", w, 8, "tuned_grpc_multiplexed_recommend", -25.0))
    # Add other matrix entries so the joiner finds embed:c8 rows.
    entries = build_supersedes_m1_time(matrix)
    embed_c8 = next(e for e in entries if e.m1_path == "embed_completion" and e.m1_concurrency == 8)
    assert embed_c8.classification == "verdict_confirmed"


def test_classification_verdict_changed_when_widths_contradict() -> None:
    """T040 (c): if every width contradicts M1, classification == verdict_changed.
    M1 c=1 chat = "REST faster". M5.1 says gRPC at every width → changed.
    """
    matrix = []
    for w in (2048, 4096, 8192):
        matrix.append(_cell("chat_stream", w, 1, "tuned_grpc_recommend", -20.0))
    entries = build_supersedes_m1_time(matrix)
    chat_c1 = next(e for e in entries if e.m1_path == "chat_completion" and e.m1_concurrency == 1)
    assert chat_c1.classification == "verdict_changed"
    # Rationale carries MockEngine continuity caveat per Edge Case 2.
    assert "MockEngine" in chat_c1.rationale


def test_classification_mixed_when_widths_split() -> None:
    """T040 (c): widths split between confirm and change → classification == 'mixed'.
    M1 c=4 embed = "gRPC faster". M5.1: h2048 grpc, h4096 grpc, h8192 no_winner.
    """
    matrix = [
        _cell("embed", 2048, 4, "tuned_grpc_multiplexed_recommend", -22.0),
        _cell("embed", 4096, 4, "tuned_grpc_multiplexed_recommend", -18.0),
        _cell("embed", 8192, 4, "no_winner", -2.0),
    ]
    entries = build_supersedes_m1_time(matrix)
    embed_c4 = next(e for e in entries if e.m1_path == "embed_completion" and e.m1_concurrency == 4)
    assert embed_c4.classification == "mixed"


def test_comparison_basis_always_set() -> None:
    """T040 (d): every emitted entry carries the M5.1↔M1 comparison_basis."""
    matrix = [_cell("chat_stream", 2048, 1, "tuned_grpc_recommend", -20.0)]
    entries = build_supersedes_m1_time(matrix)
    for entry in entries:
        assert entry.comparison_basis == "m1_real_vllm_vs_m5_1_mock_engine"


def test_rationale_contains_mock_engine_caveat_on_verdict_changed() -> None:
    """T040 (e): rationale text contains MockEngine continuity caveat when
    verdict changes from M1 (Edge Case 2).
    """
    matrix = [_cell("chat_stream", 2048, 1, "tuned_grpc_recommend", -20.0)]
    entries = build_supersedes_m1_time(matrix)
    chat_c1 = next(e for e in entries if e.m1_path == "chat_completion" and e.m1_concurrency == 1)
    assert chat_c1.classification == "verdict_changed"
    assert "MockEngine" in chat_c1.rationale
    assert "M7" in chat_c1.rationale  # references the future real-engine validation
