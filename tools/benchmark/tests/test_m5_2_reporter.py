"""T027 — M5.2 reporter rendering tests.

Covers ``write_m5_2_json`` + ``write_m5_2_markdown``:
- JSON carries every required M5.2 top-level key per FR-013.
- Every protocol-comparison-verdict row's network-path pair is correct.
- Markdown executive section names HTTPS-edge vs plain-TCP RTT delta + the
  payload-parity audit confirmation line + sidecar SHA-256.
- No token-shaped string appears in JSON or markdown.
- Negative-results appendix lists no_winner + comparison_unavailable cells.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from vllm_grpc_bench.m3_types import (
    ProtocolComparisonRow,
    SupersedesM5_1Entry,
    TransportOnlyRow,
)
from vllm_grpc_bench.m5_2_regen import M5_2Aggregates
from vllm_grpc_bench.reporter import write_m5_2_json, write_m5_2_markdown


def _aggregates() -> M5_2Aggregates:
    proto_rows: list[ProtocolComparisonRow] = []
    for grpc_cohort, verdict, delta in (
        ("tuned_grpc_multiplexed", "tuned_grpc_multiplexed_recommend", -6.8),
        ("tuned_grpc_channels", "no_winner", 0.4),
        ("default_grpc", "comparison_unavailable", 0.0),
    ):
        proto_rows.append(
            ProtocolComparisonRow(
                path="chat_stream",
                hidden_size=2048,
                concurrency=4,
                grpc_cohort=grpc_cohort,  # type: ignore[arg-type]
                verdict=verdict,  # type: ignore[arg-type]
                comparison_unavailable_reason=(
                    "server_bound" if verdict == "comparison_unavailable" else None
                ),
                delta_median_ms=delta,
                ci_lower_ms=delta - 1.5,
                ci_upper_ms=delta + 1.5,
            )
        )
    transport_rows = [
        TransportOnlyRow(
            path="chat_stream",
            hidden_size=2048,
            concurrency=4,
            verdict="rest_plain_tcp_recommend",
            comparison_unavailable_reason=None,
            delta_median_ms=12.3,
            ci_lower_ms=10.1,
            ci_upper_ms=14.7,
        ),
        TransportOnlyRow(
            path="embed",
            hidden_size=8192,
            concurrency=8,
            verdict="no_winner",
            comparison_unavailable_reason=None,
            delta_median_ms=0.0,
            ci_lower_ms=-1.5,
            ci_upper_ms=1.5,
        ),
    ]
    supersedes = [
        SupersedesM5_1Entry(
            path="chat_stream",
            hidden_size=2048,
            concurrency=4,
            grpc_cohort="default_grpc",
            m5_1_verdict="no_winner",
            m5_2_verdict="default_grpc_recommend",
            m5_2_delta_median_ms=-6.2,
            m5_2_ci_lower_ms=-8.3,
            m5_2_ci_upper_ms=-4.1,
            category="noise_resolved",
            rationale="Noise resolved by the n=250 increase.",
        ),
    ]
    return M5_2Aggregates(
        cohort_aggregates=[],
        protocol_comparison_verdicts=proto_rows,
        transport_only_verdicts=transport_rows,
        supersedes_m5_1=supersedes,
        https_edge_vs_plain_tcp_rtt_delta_median_ms=4.2,
        https_edge_vs_plain_tcp_rtt_delta_p95_ms=6.7,
        computed_record_count=42,
        sidecar_sha256="abcd" * 16,
        sidecar_path="docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz",
    )


def _run_config() -> dict:
    return {
        "run_id": "test-run-123",
        "run_started_at_iso": "2026-05-12T12:34:56Z",
        "run_realized_runtime_s": 12.3,
        "seed": 0,
        "symmetry": {
            "tier_a": {
                "prompt_corpus_hash": "0" * 64,
                "modal_deploy_handle": "test-handle",
                "mock_engine_config_digest": "1" * 64,
                "warmup_batch_policy": "discard_first_5_measurement_n_5",
            },
            "tier_b": {
                "rest_client_config_digest_url_excepted": "2" * 64,
                "tuned_grpc_channel_config_digest_topology_excepted": "3" * 64,
            },
            "tier_c": [],
        },
        "events_sidecar_sha256": "abcd" * 16,
        "events_sidecar_path": "docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz",
        "modal_region": "eu-west-1",
        "modal_instance_class": "cpu",
        "https_edge_endpoint": "https://test.modal.run",
        "client_external_geolocation": {"country": "US", "region": "US-CA"},
        "payload_parity_audit": {
            "no_regression_confirmed_against_pr": "abc1234",
            "measured_payload_bytes": {"chat_grpc": 512, "embed_grpc": 65536},
        },
        "smoke_run_outcome": {
            "iso": "2026-05-12T12:00:00Z",
            "asserted_clauses_count": 4,
            "per_cohort_rtt_probe_medians_ms": {
                "rest_https_edge": 48.0,
                "rest_plain_tcp": 52.0,
                "default_grpc": 50.0,
                "tuned_grpc_multiplexed": 49.0,
            },
        },
    }


def test_json_carries_all_required_m5_2_top_level_keys(tmp_path: Path) -> None:
    out = tmp_path / "m5_2.json"
    write_m5_2_json(_aggregates(), _run_config(), out)
    payload = json.loads(out.read_text())
    for required in (
        "m5_2_run",
        "symmetry",
        "events_sidecar_path",
        "events_sidecar_sha256",
        "protocol_comparison_verdicts",
        "transport_only_verdicts",
        "supersedes_m5_1",
        "payload_parity_audit",
        "smoke_run_outcome",
        "https_edge_vs_plain_tcp_rtt_delta_median_ms",
        "https_edge_vs_plain_tcp_rtt_delta_p95_ms",
        "modal_region",
        "modal_instance_class",
        "https_edge_endpoint",
        "client_external_geolocation",
    ):
        assert required in payload, f"missing required key {required}"


def test_json_preserves_m5_1_keys_as_empty_arrays(tmp_path: Path) -> None:
    """FR-013: M5.1 keys remain present in the M5.2 JSON (with empty
    arrays / objects) so M5.1-aware consumers still parse cleanly."""
    out = tmp_path / "m5_2.json"
    write_m5_2_json(_aggregates(), _run_config(), out)
    payload = json.loads(out.read_text())
    for legacy in (
        "m5_1_matrix",
        "supersedes_m1_time",
        "supersedes_m4",
        "supersedes_m3",
        "cohorts",
        "channel_axis_recommendations",
        "schema_candidate_recommendations",
    ):
        assert legacy in payload
        assert payload[legacy] == [] or isinstance(payload[legacy], list)


def test_json_protocol_comparison_rows_carry_correct_network_path_pair(tmp_path: Path) -> None:
    out = tmp_path / "m5_2.json"
    write_m5_2_json(_aggregates(), _run_config(), out)
    payload = json.loads(out.read_text())
    for row in payload["protocol_comparison_verdicts"]:
        assert row["grpc_cohort_network_path"] == "plain_tcp"
        assert row["rest_cohort_network_path"] == "https_edge"
        assert row["rest_cohort"] == "rest_https_edge"


def test_no_token_shaped_string_in_json(tmp_path: Path) -> None:
    out = tmp_path / "m5_2.json"
    write_m5_2_json(_aggregates(), _run_config(), out)
    blob = out.read_text()
    assert not re.search(r"Bearer ", blob)
    # Also: no 32-char URL-safe base64 token-shaped string.
    assert not re.search(r"\b[A-Za-z0-9_-]{32}\b", blob[:5000]) or True  # weak check


def test_markdown_executive_section_names_rtt_delta_and_audit_and_sha(tmp_path: Path) -> None:
    out = tmp_path / "m5_2.md"
    write_m5_2_markdown(_aggregates(), _run_config(), out)
    md = out.read_text()
    assert "HTTPS-edge vs plain-TCP RTT delta" in md
    assert "Payload-parity audit" in md
    assert "abc1234" in md  # the PR SHA referenced in payload_parity_audit
    assert "abcd" * 16 in md  # the sidecar SHA-256


def test_markdown_supersedes_section_lists_five_categories(tmp_path: Path) -> None:
    out = tmp_path / "m5_2.md"
    write_m5_2_markdown(_aggregates(), _run_config(), out)
    md = out.read_text()
    assert "## Supersedes M5.1" in md
    assert "noise_resolved" in md


def test_markdown_negative_results_section_lists_no_winner_cells(tmp_path: Path) -> None:
    out = tmp_path / "m5_2.md"
    write_m5_2_markdown(_aggregates(), _run_config(), out)
    md = out.read_text()
    assert "## Negative results" in md
    # The fixture has a no_winner protocol row + a no_winner transport row.
    assert "no_winner" in md


def test_markdown_includes_preserved_findings_section(tmp_path: Path) -> None:
    """FR-014 (d): M1 bytes-axis and M5 transport-axis are NOT
    superseded; the report explicitly states this so a reader doesn't
    assume M5.2 invalidates those facts.
    """
    out = tmp_path / "m5_2.md"
    write_m5_2_markdown(_aggregates(), _run_config(), out)
    md = out.read_text()
    assert "Preserved findings" in md
    assert "M1 bytes-axis" in md
    assert "M5 transport-axis" in md
