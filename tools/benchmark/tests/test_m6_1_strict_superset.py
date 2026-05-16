"""Strict-superset compatibility test (T032 — SC-005).

Asserts that an M6.1 JSON output preserves all M6-shape fields an M6-aware
consumer would expect to find, so existing M6-aware readers continue to work
unmodified against M6.1's JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

from vllm_grpc_bench.m6_1_reporter import render_json

from tests.test_m6_1_reporter import _make_run  # type: ignore[import-not-found]


def test_json_preserves_m6_shape_top_level_keys() -> None:
    """An M6-aware consumer indexing top-level keys MUST find all of these."""
    run = _make_run()
    payload = render_json(run)
    m6_required_keys = {
        "schema_version",
        "run_id",
        "run_started_at",
        "run_completed_at",
        "modal_region",
        "modal_instance_class",
        "rtt_distribution",
        "cohorts",
        "protocol_comparison_verdicts",
        "transport_only_verdicts",
        "channel_axis_recommendations",
        "schema_candidate_recommendations",
        "shared_baseline_cohorts",
        "supersedes_m5_2_under_real_engine",
        "engine_cost_baseline",
        "m6_meta",
        "supersedes_m1_time",
        "supersedes_m3",
        "supersedes_m4",
        "supersedes_m5_1",
    }
    missing = m6_required_keys - set(payload.keys())
    assert not missing, f"M6.1 JSON is missing M6-strict-superset keys: {missing}"


def test_json_protocol_comparison_rows_have_m6_shape() -> None:
    run = _make_run()
    payload = render_json(run)
    rows = payload["protocol_comparison_verdicts"]
    assert len(rows) == 6
    for row in rows:
        assert "cell" in row
        assert "classification" in row
        assert "classifier_metric" in row
        assert "cohort_pair" in row
        assert "per_cohort_classifier_metric" in row
        for cohort_data in row["per_cohort_classifier_metric"].values():
            assert "mean_ms" in cohort_data
            assert "ci_lower_ms" in cohort_data
            assert "ci_upper_ms" in cohort_data


def test_json_m6_additive_fields_present() -> None:
    run = _make_run()
    payload = render_json(run)
    assert "supersedes_m6_under_enable_prompt_embeds" in payload
    assert "engine_path_differential" in payload
    assert "run_meta" in payload
    assert payload["run_meta"]["torch_version"] == "2.11.0"
    assert "m6_winner_deltas" in payload["run_meta"]


def test_json_round_trip_serialisable(tmp_path: Path) -> None:
    """The JSON output must survive disk round-trip without serialisation errors."""
    run = _make_run()
    payload = render_json(run)
    out = tmp_path / "report.json"
    out.write_text(json.dumps(payload, default=str))
    reloaded = json.loads(out.read_text())
    assert reloaded["schema_version"] == "m6_1.v1"
    assert len(reloaded["supersedes_m6_under_enable_prompt_embeds"]) == 6
    assert len(reloaded["engine_path_differential"]) == 6


def test_m6_meta_back_reference_passthrough_present() -> None:
    run = _make_run()
    payload = render_json(run)
    # FR-021: M6.1 JSON must carry the m6_meta back-reference so M6-aware
    # consumers indexing by `m6_meta` still resolve the M6 baseline's
    # recorded engine_version + m5_2_winner_deltas.
    assert payload["m6_meta"]["engine_version"] == "unknown"
    assert payload["m6_meta"]["model_identifier"] == "Qwen/Qwen3-8B"
