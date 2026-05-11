"""T045 / T046 / T050b — Supersedes M4 table builder + citations.

The builder reads a synthetic ``m4-time-axis-tuning.json`` (constructed in
tmp) and an in-memory M5 ``Run``. Tests cover every value of the
four-value ``expected_class`` classifier plus the FR-017 citation emission
rule (citations populated only for time-metric verdict-changed entries).
"""

from __future__ import annotations

import json
from pathlib import Path

from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.m3_types import (
    M5RunMetadata,
    Recommendation,
    RTTSummary,
    Run,
)
from vllm_grpc_bench.m5_supersede import build_supersedes_m4_table


def _write_m4_report(
    path: Path,
    *,
    recommendations: list[dict[str, object]],
    loopback_caveat_axes: list[str] | None = None,
) -> Path:
    payload: dict[str, object] = {
        "mode": "m4-time-axis-tuning",
        "axes": ["max_message_size", "keepalive", "compression", "http2_framing"],
        "widths": [4096],
        "paths": ["embed", "chat_stream"],
        "loopback_caveat_axes": loopback_caveat_axes or [],
        "recommendations": recommendations,
        "cohorts": [],
    }
    path.write_text(json.dumps(payload))
    return path


def _m5_run_with_recs(recs: list[Recommendation]) -> Run:
    meta = M5RunMetadata(
        m5_methodology_version=1,
        m5_modal_app_name="x",
        m5_modal_region="r",
        m5_runtime_wallclock_seconds=1.0,
        m5_rtt_summary_ms=RTTSummary(min_ms=80.0, median_ms=80.0, p95_ms=120.0, max_ms=150.0),
        rtt_validity_threshold_ms=1.0,
        rtt_exercise_threshold_ms=20.0,
        warmup_n=32,
        server_bound_overhead_threshold_ms=50.0,
        server_bound_cohort_count=0,
    )
    run = Run(
        mode="m5-cross-host-validation",
        axes=["keepalive"],
        widths=[4096],
        paths=["embed"],
        iterations_per_cell=100,
        seed=0,
        cohorts=[],
        m5_metadata=meta,
    )
    run.recommendations.extend(recs)
    return run


def _rec(
    axis: str,
    path: str,
    width: int,
    verdict: str,
    *,
    candidate_ci_lower: float = 0.080,
    baseline_ci_upper: float = 0.041,
) -> Recommendation:
    """``baseline_ci_upper`` and ``candidate_ci_lower`` are stored as negated
    CIs for minimizing metrics (see ``m4_sweep.build_recommendations``); the
    invariant ``candidate_ci_lower > baseline_ci_upper`` holds on the
    negated values when the candidate strictly clears the baseline.
    """
    return Recommendation(
        axis=axis,  # type: ignore[arg-type]
        applies_to_path=path,  # type: ignore[arg-type]
        applies_to_widths=frozenset({width}),
        verdict=verdict,  # type: ignore[arg-type]
        baseline_ci_upper=baseline_ci_upper,
        citation="x",
        winning_config=M1_BASELINE if verdict == "recommend" else None,
        winning_delta_pct=-5.4 if verdict == "recommend" else None,
        winning_metric="ttft" if verdict == "recommend" else None,
        candidate_ci_lower=candidate_ci_lower if verdict == "recommend" else None,
        notes="",
        corpus_subset="m1_embed" if path == "embed" else "m1_chat",  # type: ignore[arg-type]
    )


class TestExpectedClassClassifier:
    """T045 — every value of expected_class is exercised."""

    def test_verdict_confirmed(self, tmp_path: Path) -> None:
        m4_path = _write_m4_report(
            tmp_path / "m4.json",
            recommendations=[
                {
                    "axis": "max_message_size",
                    "applies_to_path": "embed",
                    "applies_to_widths": [4096],
                    "verdict": "no_winner",
                }
            ],
        )
        run = _m5_run_with_recs([_rec("max_message_size", "embed", 4096, "no_winner")])
        entries = build_supersedes_m4_table(run, m4_path)
        # Verdicts match and there's no loopback caveat → no entry emitted.
        assert entries == []

    def test_loopback_resolution(self, tmp_path: Path) -> None:
        m4_path = _write_m4_report(
            tmp_path / "m4.json",
            recommendations=[
                {
                    "axis": "keepalive",
                    "applies_to_path": "embed",
                    "applies_to_widths": [4096],
                    "verdict": "no_winner",
                }
            ],
            loopback_caveat_axes=["keepalive"],
        )
        run = _m5_run_with_recs([_rec("keepalive", "embed", 4096, "recommend")])
        entries = build_supersedes_m4_table(run, m4_path)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.expected_class == "loopback_resolution"
        assert entry.verdict_changed is True
        assert entry.m4_loopback_caveat is True
        # Time-metric verdict changed → citations populated.
        assert len(entry.citations) >= 1
        assert entry.citations[0].repo in ("grpc/grpc", "vllm-project/vllm")

    def test_transport_resolution(self, tmp_path: Path) -> None:
        # M4 had no loopback caveat AND axis is keepalive/http2_framing AND
        # verdict changed.
        m4_path = _write_m4_report(
            tmp_path / "m4.json",
            recommendations=[
                {
                    "axis": "http2_framing",
                    "applies_to_path": "embed",
                    "applies_to_widths": [4096],
                    "verdict": "no_winner",
                }
            ],
            loopback_caveat_axes=[],  # no loopback caveat
        )
        run = _m5_run_with_recs([_rec("http2_framing", "embed", 4096, "recommend")])
        entries = build_supersedes_m4_table(run, m4_path)
        assert len(entries) == 1
        assert entries[0].expected_class == "transport_resolution"
        # Time-metric verdict changed → citations populated.
        assert entries[0].citations

    def test_unexpected_supersession(self, tmp_path: Path) -> None:
        # Axis is max_message_size (non-RTT-bounded) and verdict changed.
        m4_path = _write_m4_report(
            tmp_path / "m4.json",
            recommendations=[
                {
                    "axis": "max_message_size",
                    "applies_to_path": "embed",
                    "applies_to_widths": [4096],
                    "verdict": "no_winner",
                }
            ],
            loopback_caveat_axes=[],
        )
        run = _m5_run_with_recs([_rec("max_message_size", "embed", 4096, "recommend")])
        entries = build_supersedes_m4_table(run, m4_path)
        assert len(entries) == 1
        assert entries[0].expected_class == "unexpected_supersession"


class TestSupersedesM4BoundaryCases:
    """T046 / T050b."""

    def test_zero_entries_when_m4_all_match_and_no_loopback(self, tmp_path: Path) -> None:
        m4_path = _write_m4_report(
            tmp_path / "m4.json",
            recommendations=[
                {
                    "axis": "max_message_size",
                    "applies_to_path": "embed",
                    "applies_to_widths": [4096],
                    "verdict": "no_winner",
                },
                {
                    "axis": "compression",
                    "applies_to_path": "embed",
                    "applies_to_widths": [4096],
                    "verdict": "no_winner",
                },
            ],
            loopback_caveat_axes=[],
        )
        run = _m5_run_with_recs(
            [
                _rec("max_message_size", "embed", 4096, "no_winner"),
                _rec("compression", "embed", 4096, "no_winner"),
            ]
        )
        entries = build_supersedes_m4_table(run, m4_path)
        assert entries == []

    def test_citations_only_on_time_metric_verdict_changes(self, tmp_path: Path) -> None:
        """T050b — citations are empty for verdict-confirmed rows."""
        m4_path = _write_m4_report(
            tmp_path / "m4.json",
            recommendations=[
                {
                    "axis": "keepalive",
                    "applies_to_path": "embed",
                    "applies_to_widths": [4096],
                    "verdict": "no_winner",
                }
            ],
            loopback_caveat_axes=["keepalive"],
        )
        # M5 confirms M4's no_winner verdict but the loopback caveat still
        # requires an entry. verdict_changed = False → citations empty.
        run = _m5_run_with_recs([_rec("keepalive", "embed", 4096, "no_winner")])
        entries = build_supersedes_m4_table(run, m4_path)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.verdict_changed is False
        assert entry.expected_class == "verdict_confirmed"
        # FR-017: no citations on verdict-confirmed rows.
        assert entry.citations == ()


class TestReadAbsentReportGracefully:
    def test_missing_m4_report_returns_empty(self, tmp_path: Path) -> None:
        run = _m5_run_with_recs([])
        entries = build_supersedes_m4_table(run, tmp_path / "does_not_exist.json")
        assert entries == []
