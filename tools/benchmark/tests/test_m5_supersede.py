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
        # Axis is max_message_size (non-RTT-bound) and verdict changed from
        # no_winner → recommend (NOT a bound-classifier transition: neither
        # side is a bound verdict literal).
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

    def test_bound_classifier_transition_client_bound_to_no_winner(self, tmp_path: Path) -> None:
        """Refinement — M4's ``client_bound`` was a loopback jitter-floor
        artifact; on real wire that floor is dominated by RTT, so M5 sees
        the CI honestly as ``no_winner``. The verdict literally changed but
        the *information* is the same; this should classify as
        ``bound_classifier_transition``, not ``unexpected_supersession``.
        """
        m4_path = _write_m4_report(
            tmp_path / "m4.json",
            recommendations=[
                {
                    "axis": "max_message_size",
                    "applies_to_path": "embed",
                    "applies_to_widths": [4096],
                    "verdict": "client_bound",
                }
            ],
            loopback_caveat_axes=[],
        )
        run = _m5_run_with_recs([_rec("max_message_size", "embed", 4096, "no_winner")])
        entries = build_supersedes_m4_table(run, m4_path)
        assert len(entries) == 1
        assert entries[0].expected_class == "bound_classifier_transition"
        assert entries[0].verdict_changed is True

    def test_bound_classifier_transition_no_winner_to_server_bound(self, tmp_path: Path) -> None:
        """M5's ``server_bound`` classifier (R-4) fires on cells where
        remote-server overhead dominates transport — a classification M4
        structurally cannot fire (loopback's "server" is the same process
        as the client). The transition is methodology-driven, not data-
        driven; classify as ``bound_classifier_transition``.
        """
        from vllm_grpc_bench.m3_types import Recommendation

        m4_path = _write_m4_report(
            tmp_path / "m4.json",
            recommendations=[
                {
                    "axis": "compression",
                    "applies_to_path": "embed",
                    "applies_to_widths": [4096],
                    "verdict": "no_winner",
                }
            ],
            loopback_caveat_axes=[],
        )
        # The Recommendation dataclass enforces recommend-only invariants on
        # winning_config / candidate_ci_lower, so we build a server_bound
        # rec inline (those invariants don't apply to non-recommend verdicts).
        server_bound_rec = Recommendation(
            axis="compression",
            applies_to_path="embed",
            applies_to_widths=frozenset({4096}),
            verdict="server_bound",
            baseline_ci_upper=0.0,
            citation="x",
            notes="server overhead dominates",
            corpus_subset="m1_embed",
        )
        run = _m5_run_with_recs([server_bound_rec])
        entries = build_supersedes_m4_table(run, m4_path)
        assert len(entries) == 1
        assert entries[0].expected_class == "bound_classifier_transition"

    def test_loopback_resolution_takes_precedence_over_bound_transition(
        self, tmp_path: Path
    ) -> None:
        """Precedence guard: when M4 had a loopback caveat AND the verdict
        change happens to match the bound-classifier pattern, the
        ``loopback_resolution`` label wins. The headline M5 case must keep
        its existing label.
        """
        m4_path = _write_m4_report(
            tmp_path / "m4.json",
            recommendations=[
                {
                    "axis": "keepalive",
                    "applies_to_path": "embed",
                    "applies_to_widths": [2048],
                    "verdict": "client_bound",
                }
            ],
            loopback_caveat_axes=["keepalive"],
        )
        run = _m5_run_with_recs([_rec("keepalive", "embed", 2048, "recommend")])
        entries = build_supersedes_m4_table(run, m4_path)
        assert len(entries) == 1
        # loopback_resolution is checked BEFORE bound_classifier_transition;
        # the M4 loopback caveat takes priority even though the verdict
        # change also matches the bound-transition pattern.
        assert entries[0].expected_class == "loopback_resolution"


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
