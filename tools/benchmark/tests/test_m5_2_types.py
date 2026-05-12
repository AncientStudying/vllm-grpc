"""Tests for M5.2 additive dataclasses + Literal types in m3_types.py (T009).

Asserts the verdict literals, cohort-kind literal, supersede-category literal,
and the new dataclasses load + construct cleanly. Also asserts the M5.1
backward-compat regression case: importing the pre-M5.2 types still works
unchanged.
"""

from __future__ import annotations

import typing

import pytest
from vllm_grpc_bench.m3_types import (
    M5_2CohortKind,
    M5_2Run,
    NetworkPath,
    ProtocolComparisonRow,
    ProtocolComparisonVerdict,
    RESTCohortRecord,
    RestHttpsEdgeCohortRecord,
    SupersedesM5_1Category,
    SupersedesM5_1Entry,
    TransportOnlyRow,
    TransportOnlyVerdict,
)


def _literal_values(alias: object) -> tuple[str, ...]:
    return tuple(typing.get_args(alias))


def test_protocol_comparison_verdict_contains_required_literals() -> None:
    expected = {
        "tuned_grpc_multiplexed_recommend",
        "tuned_grpc_channels_recommend",
        "tuned_grpc_recommend",
        "default_grpc_recommend",
        "rest_https_edge_recommend",
        "no_winner",
        "comparison_unavailable",
    }
    assert set(_literal_values(ProtocolComparisonVerdict)) == expected


def test_transport_only_verdict_contains_required_literals() -> None:
    expected = {
        "rest_https_edge_recommend",
        "rest_plain_tcp_recommend",
        "no_winner",
        "comparison_unavailable",
    }
    assert set(_literal_values(TransportOnlyVerdict)) == expected


def test_m5_2_cohort_kind_contains_all_six_cohort_names() -> None:
    expected = {
        "rest_https_edge",
        "rest_plain_tcp",
        "default_grpc",
        "tuned_grpc_multiplexed",
        "tuned_grpc_channels",
        "tuned_grpc",
    }
    assert set(_literal_values(M5_2CohortKind)) == expected


def test_network_path_literal() -> None:
    assert set(_literal_values(NetworkPath)) == {"https_edge", "plain_tcp"}


def test_supersedes_m5_1_category_includes_confirmed_unavailable() -> None:
    expected = {
        "verdict_changed",
        "verdict_confirmed",
        "noise_resolved",
        "transport_dependent",
        "confirmed_unavailable",
    }
    assert set(_literal_values(SupersedesM5_1Category)) == expected


def test_m5_1_rest_cohort_record_remains_importable() -> None:
    """Backward-compat: the M5.1 dataclass MUST still be importable from
    m3_types after the M5.2 additions land."""
    rec = RESTCohortRecord(
        shim_overhead_ms_median=0.4,
        shim_overhead_ms_p95=0.9,
        connections_opened=4,
        connections_keepalive_reused=96,
        request_bytes_median=312,
        request_bytes_p95=312,
        response_bytes_median=1842,
        response_bytes_p95=1894,
    )
    assert rec.connections_opened == 4


def test_rest_https_edge_cohort_record_constructable() -> None:
    rec = RestHttpsEdgeCohortRecord(
        shim_overhead_ms_median=0.4,
        shim_overhead_ms_p95=0.9,
        connections_opened=4,
        connections_keepalive_reused=96,
        request_bytes_median=312,
        request_bytes_p95=312,
        response_bytes_median=1842,
        response_bytes_p95=1894,
        https_edge_endpoint="https://abc.modal.run",
        tls_handshake_ms_first_request=14.2,
        measured_rtt_ms_median=48.0,
        measured_rtt_ms_p95=55.0,
        client_external_geolocation_country="US",
        client_external_geolocation_region="US-CA",
    )
    assert rec.network_path == "https_edge"
    assert rec.https_edge_endpoint == "https://abc.modal.run"


def test_supersedes_m5_1_entry_rejects_inverted_ci_bounds() -> None:
    with pytest.raises(ValueError, match="m5_2_ci_lower_ms"):
        SupersedesM5_1Entry(
            path="chat_stream",
            hidden_size=2048,
            concurrency=4,
            grpc_cohort="default_grpc",
            m5_1_verdict="no_winner",
            m5_2_verdict="default_grpc_recommend",
            m5_2_delta_median_ms=-6.2,
            m5_2_ci_lower_ms=-4.1,
            m5_2_ci_upper_ms=-8.3,
            category="noise_resolved",
            rationale="bogus inverted",
        )


def test_supersedes_m5_1_entry_requires_rationale() -> None:
    with pytest.raises(ValueError, match="rationale"):
        SupersedesM5_1Entry(
            path="embed",
            hidden_size=4096,
            concurrency=1,
            grpc_cohort="tuned_grpc",
            m5_1_verdict="rest_recommend",
            m5_2_verdict="rest_https_edge_recommend",
            m5_2_delta_median_ms=3.2,
            m5_2_ci_lower_ms=1.0,
            m5_2_ci_upper_ms=5.4,
            category="verdict_confirmed",
            rationale="",
        )


def test_protocol_comparison_row_default_network_path_pair() -> None:
    row = ProtocolComparisonRow(
        path="chat_stream",
        hidden_size=4096,
        concurrency=4,
        grpc_cohort="tuned_grpc_multiplexed",
        verdict="tuned_grpc_multiplexed_recommend",
        comparison_unavailable_reason=None,
        delta_median_ms=-6.8,
        ci_lower_ms=-8.2,
        ci_upper_ms=-5.4,
    )
    assert row.rest_cohort == "rest_https_edge"
    assert row.grpc_cohort_network_path == "plain_tcp"
    assert row.rest_cohort_network_path == "https_edge"


def test_transport_only_row_constructable() -> None:
    row = TransportOnlyRow(
        path="embed",
        hidden_size=8192,
        concurrency=8,
        verdict="rest_plain_tcp_recommend",
        comparison_unavailable_reason=None,
        delta_median_ms=12.3,
        ci_lower_ms=10.1,
        ci_upper_ms=14.7,
    )
    assert row.verdict == "rest_plain_tcp_recommend"


def test_m5_2_run_accepts_empty_cohort_lists() -> None:
    """Degenerate-run sanity: a run with no cohorts is still a valid M5_2Run.
    The aggregate JSON regenerator emits empty arrays in this case rather
    than failing on schema validation per FR-013's strict-superset rule.
    """
    from vllm_grpc_bench.m5_2_symmetry import (
        CrossCohortInvariants,
        IntraProtocolPairInvariants,
        SymmetryBlock,
    )

    block = SymmetryBlock(
        tier_a=CrossCohortInvariants(
            prompt_corpus_hash="0" * 64,
            modal_deploy_handle="test-handle",
            mock_engine_config_digest="1" * 64,
            warmup_batch_policy="discard_first_5_measurement_n_5",
        ),
        tier_b=IntraProtocolPairInvariants(
            rest_client_config_digest_url_excepted="2" * 64,
            tuned_grpc_channel_config_digest_topology_excepted=None,
        ),
        tier_c=[],
        client_external_geolocation_country=None,
        client_external_geolocation_region=None,
    )

    run = M5_2Run(
        run_id="test-run",
        run_started_at_iso="2026-05-12T12:00:00Z",
        run_realized_runtime_s=1.0,
        seed=0,
        symmetry=block,
        events_sidecar_path="bench-results/m5_2-full/test.events.jsonl.gz",
        events_sidecar_sha256="3" * 64,
        payload_parity_audit_no_regression_confirmed_against_pr="abc1234",
        payload_parity_audit_measured_payload_bytes={},
        smoke_run_outcome_iso="2026-05-12T11:50:00Z",
        smoke_run_asserted_clauses_count=4,
        smoke_run_per_cohort_rtt_probe_medians_ms={},
        rest_https_edge_cohorts=[],
        rest_plain_tcp_cohorts=[],
        grpc_cohorts=[],
        protocol_comparison_verdicts=[],
        transport_only_verdicts=[],
        supersedes_m5_1=[],
        modal_region="eu-west-1",
        modal_instance_class="cpu",
        https_edge_endpoint="https://example.modal.run",
        client_external_geolocation_country=None,
        client_external_geolocation_region=None,
        https_edge_vs_plain_tcp_rtt_delta_median_ms=0.0,
        https_edge_vs_plain_tcp_rtt_delta_p95_ms=0.0,
    )
    assert run.run_id == "test-run"
    assert run.protocol_comparison_verdicts == []
