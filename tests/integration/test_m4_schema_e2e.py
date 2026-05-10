"""US3 / T048 — end-to-end small-fixture M4 sweep with schema candidates.

Confirms that an ``--m4`` run with schema candidates enabled:

- Completes without raising (passes ``validate_run``).
- Records one ``SchemaCandidateResult`` per requested candidate.
- Renders the Schema Candidates section in the markdown report.
- Surfaces the Negative-results appendix when a candidate is classified
  ``is_negative_result=True`` (FR-014).

The candidate cohort measurement still relies on the proto-stub-driven
serialization machinery from T045's full implementation. For now this
integration test verifies the *plumbing* (results list, reporter
sections, classification) and feeds the negative-result appendix a
synthetic per-width record so the FR-014 path is exercised end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from vllm_grpc_bench.m3_types import (
    M4SweepConfig,
    SchemaCandidatePerWidth,
)
from vllm_grpc_bench.m4_sweep import (
    classify_schema_result,
    run_m4_sweep,
    validate_run,
)
from vllm_grpc_bench.reporter import write_m4_json, write_m4_markdown


@pytest.mark.asyncio
async def test_m4_with_schema_candidates_end_to_end(tmp_path: Path) -> None:
    config = M4SweepConfig(
        pacing_mode="no_pacing",
        baseline_n=100,
        candidate_n=100,
        expand_n=200,
        baseline_cv_max=10.0,
        widths=(4096,),
        paths=("embed",),
        axes=("compression",),
        schema_candidates=("packed_token_ids",),
        schema_canonical_width=4096,
    )
    run = await run_m4_sweep(config, progress=False)

    # Inject a synthetic negative-result per-width record so FR-014's
    # appendix path is exercised in the report. (The full T045
    # measurement loop will populate this from real cohorts.)
    sc = run.schema_candidate_results[0]
    negative = classify_schema_result(
        candidate_name=sc.candidate_name,
        proto_file=sc.proto_file,
        per_widths=[
            SchemaCandidatePerWidth(
                hidden_size=4096,
                frozen_baseline_cohort_id=run.shared_baseline_cohort_ids["embed"],
                candidate_cohort_id=f"embed|h4096|schema:{sc.candidate_name}|m1_embed",
                bytes_verdict="no_winner",
                time_verdict="no_winner",
                primary_metric="time",
                delta_bytes_pct=0.0,
                delta_time_pct=0.0,
                ci_overlap_initial=True,
                expanded=False,
            )
        ],
        notes="negative-result fixture for T048 integration test",
    )
    run.schema_candidate_results[0] = negative
    assert negative.is_negative_result is True

    validate_run(run)

    # Schema Candidates section + Negative-results appendix render in the markdown.
    md_path = tmp_path / "m4-time-axis-tuning.md"
    write_m4_markdown(run, md_path)
    md_text = md_path.read_text()
    assert "Schema candidates" in md_text
    assert sc.candidate_name in md_text
    assert "Negative results" in md_text

    # JSON exposes the results array under schema_candidate_results.
    json_path = tmp_path / "m4-time-axis-tuning.json"
    write_m4_json(run, json_path)
    payload = json.loads(json_path.read_text())
    assert "schema_candidate_results" in payload
    assert payload["schema_candidate_results"][0]["candidate_name"] == sc.candidate_name
    assert payload["schema_candidate_results"][0]["is_negative_result"] is True
