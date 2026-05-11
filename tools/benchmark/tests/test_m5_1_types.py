"""Tests for M5.1 additive dataclasses + Literal types in m3_types.py (T011)."""

from __future__ import annotations

import typing

import pytest
from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.m3_types import (
    BenchmarkCell,
    CellVerdict,
    ComparisonVerdict,
    GRPCSubCohortKind,
    M5_1Cell,
    M5_1RunMetadata,
    RESTCohortRecord,
    RunCohort,
    ShimOverheadRecord,
    SupersedesM1Entry,
)


def _literal_values(alias: object) -> tuple[str, ...]:
    return tuple(typing.get_args(alias))


def test_comparison_verdict_literal_contains_required_values() -> None:
    expected = {
        "tuned_grpc_multiplexed_recommend",
        "tuned_grpc_channels_recommend",
        "tuned_grpc_recommend",
        "rest_recommend",
        "no_winner",
        "comparison_unavailable",
    }
    assert set(_literal_values(ComparisonVerdict)) == expected


def test_grpc_sub_cohort_kind_literal_contains_required_values() -> None:
    expected = {
        "tuned_grpc_multiplexed",
        "tuned_grpc_channels",
        "tuned_grpc",
        "default_grpc",
    }
    assert set(_literal_values(GRPCSubCohortKind)) == expected


def test_run_cohort_m5_only_fields_remain_valid() -> None:
    """Backward-compat (data-model.md): a cohort constructed with no M5.1
    fields must still be a valid RunCohort and leave the new fields at None.
    """
    cell = BenchmarkCell(
        path="embed",
        hidden_size=4096,
        channel_config=M1_BASELINE,
        corpus_subset="m1_embed",
        iterations=10,
    )
    cohort = RunCohort(
        cell=cell,
        samples=(),
        n_successful=10,
        bytes_mean=1.0,
        bytes_ci_low=0.9,
        bytes_ci_high=1.1,
        time_mean=0.01,
        time_ci_low=0.009,
        time_ci_high=0.011,
    )
    assert cohort.protocol is None
    assert cohort.grpc_channel_model is None
    assert cohort.connection_count is None
    assert cohort.shim_overhead_ms is None
    assert cohort.comparison_cell_key is None
    assert cohort.rest_cohort_record is None


def test_m5_1_cell_accepts_list_of_cell_verdicts() -> None:
    verdict = CellVerdict(
        grpc_sub_cohort="tuned_grpc_multiplexed",
        verdict="tuned_grpc_multiplexed_recommend",
        delta_pct=-18.4,
        ci_pct=(-22.1, -14.7),
        metric="ttft",
    )
    cell = M5_1Cell(
        path="chat_stream",
        hidden_size=2048,
        concurrency=4,
        rest_cohort_key="rest:chat_stream:h2048:c4",
        default_grpc_cohort_key="grpc-default:chat_stream:h2048:c4",
        tuned_grpc_multiplexed_cohort_key="grpc-tuned-mux:chat_stream:h2048:c4",
        tuned_grpc_channels_cohort_key="grpc-tuned-ch:chat_stream:h2048:c4",
        verdicts=[verdict],
        comparison_unavailable=False,
        comparison_unavailable_reason=None,
        rtt_ms_median=52.3,
        rtt_ms_p95=58.1,
        low_rtt_caveat=False,
    )
    assert cell.verdicts[0].verdict == "tuned_grpc_multiplexed_recommend"
    assert cell.comparison_cell_key == "chat_stream:h2048:c4"


def test_supersedes_m1_entry_rejects_invalid_classification() -> None:
    with pytest.raises(ValueError, match="classification"):
        SupersedesM1Entry(
            m1_path="chat_completion",
            m1_concurrency=1,
            m1_verdict_literal="REST faster",
            m1_source_report="docs/benchmarks/phase-3-modal-comparison.md",
            m5_1_verdict_per_width={2048: "no_winner"},
            m5_1_supporting_delta_pct={2048: 0.0},
            m5_1_supporting_ci_pct={2048: (-1.0, 1.0)},
            classification="bogus_value",  # type: ignore[arg-type]
            rationale="non-empty",
        )


def test_supersedes_m1_entry_default_basis_set() -> None:
    entry = SupersedesM1Entry(
        m1_path="chat_completion",
        m1_concurrency=1,
        m1_verdict_literal="REST faster (c=1 small-body chat)",
        m1_source_report="docs/benchmarks/phase-3-modal-comparison.md#chat-c1",
        m5_1_verdict_per_width={2048: "tuned_grpc_multiplexed_recommend"},
        m5_1_supporting_delta_pct={2048: -23.2},
        m5_1_supporting_ci_pct={2048: (-25.1, -21.3)},
        classification="verdict_changed",
        rationale="On real wire, multiplexing dominates.",
    )
    assert entry.comparison_basis == "m1_real_vllm_vs_m5_1_mock_engine"


def test_rest_cohort_record_and_shim_overhead_record_constructable() -> None:
    rec = RESTCohortRecord(
        shim_overhead_ms_median=0.38,
        shim_overhead_ms_p95=0.92,
        connections_opened=4,
        connections_keepalive_reused=96,
        request_bytes_median=312,
        request_bytes_p95=312,
        response_bytes_median=1842,
        response_bytes_p95=1894,
    )
    assert rec.connections_opened == 4
    so = ShimOverheadRecord(
        shim_overhead_ms_median_across_run=0.42,
        shim_overhead_ms_p95_across_run=1.05,
        shim_overhead_ms_max_across_run=4.7,
        shim_overhead_material_in_any_cohort=False,
    )
    assert so.shim_overhead_material_in_any_cohort is False


def test_m5_1_run_metadata_constructable() -> None:
    meta = M5_1RunMetadata(
        modal_app_handle="vllm-grpc-bench-rest-grpc-mock",
        modal_region="eu-west-1",
        modal_instance_class="cpu",
        rest_shim_version_sha="abc123",
        rest_shim_uvicorn_workers=1,
        auth_token_env_var="MODAL_BENCH_TOKEN",
        shim_overhead=ShimOverheadRecord(
            shim_overhead_ms_median_across_run=0.4,
            shim_overhead_ms_p95_across_run=1.0,
            shim_overhead_ms_max_across_run=2.0,
            shim_overhead_material_in_any_cohort=False,
        ),
        supersedes_m1_time=[],
        m5_1_matrix=[],
    )
    assert meta.rest_shim_uvicorn_workers == 1
    assert meta.modal_instance_class == "cpu"
