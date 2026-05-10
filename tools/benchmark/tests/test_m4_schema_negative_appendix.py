"""US3 / T039 / FR-014 / Constitution V — Negative-results appendix.

A schema candidate with overlapping CIs on **both** bytes and time at all
measured widths is recorded as a negative result with full supporting
numbers. Constitution V (Honest Measurement): no metric may be selectively
omitted.
"""

from __future__ import annotations

from vllm_grpc_bench.m3_types import (
    SchemaCandidatePerWidth,
    SchemaCandidateResult,
)
from vllm_grpc_bench.m4_sweep import classify_schema_result


def _per_width(
    *,
    width: int,
    bytes_v: str,
    time_v: str,
) -> SchemaCandidatePerWidth:
    return SchemaCandidatePerWidth(
        hidden_size=width,
        frozen_baseline_cohort_id="frozen",
        candidate_cohort_id=f"cand-{width}",
        bytes_verdict=bytes_v,  # type: ignore[arg-type]
        time_verdict=time_v,  # type: ignore[arg-type]
        primary_metric="time",
        delta_bytes_pct=0.1,
        delta_time_pct=-0.2,
        ci_overlap_initial=True,
        expanded=False,
    )


class TestNegativeResultClassification:
    def test_all_no_winner_marks_negative(self) -> None:
        per_widths = [
            _per_width(width=2048, bytes_v="no_winner", time_v="no_winner"),
            _per_width(width=4096, bytes_v="no_winner", time_v="no_winner"),
            _per_width(width=8192, bytes_v="no_winner", time_v="no_winner"),
        ]
        result = classify_schema_result(
            candidate_name="oneof_flattened_input",
            proto_file="proto/vllm_grpc/v1/m4-candidates/oneof_flattened_input.proto",
            per_widths=per_widths,
        )
        assert result.is_negative_result is True
        assert isinstance(result, SchemaCandidateResult)

    def test_one_recommend_clears_negative(self) -> None:
        per_widths = [
            _per_width(width=2048, bytes_v="no_winner", time_v="no_winner"),
            _per_width(width=4096, bytes_v="no_winner", time_v="recommend"),
            _per_width(width=8192, bytes_v="no_winner", time_v="no_winner"),
        ]
        result = classify_schema_result(
            candidate_name="packed_token_ids",
            proto_file="x",
            per_widths=per_widths,
        )
        assert result.is_negative_result is False
