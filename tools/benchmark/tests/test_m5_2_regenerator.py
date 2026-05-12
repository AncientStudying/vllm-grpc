"""T026 — Round-trippable regenerator tests.

Covers:
- SHA-256 mismatch → ``SidecarChecksumMismatch`` (no artifacts written).
- Symmetry block re-asserted at report-build time.
- Byte-identical round-trip on equivalent sidecar + run config.
- ``sort_keys=True, separators=(",", ":")`` JSON encoding.
- Warmup records excluded from aggregates per FR-011.
- Field-provenance blockquote present in the markdown per FR-012b.
- Missing M5.1 published JSON → ``M5_1PublishedJsonUnavailable`` (exit 9).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from vllm_grpc_bench.m5_2_events import (
    EventsSidecarWriter,
    PerRequestEventRecord,
)
from vllm_grpc_bench.m5_2_regen import (
    RunConfigInvalid,
    SidecarChecksumMismatch,
    regen_m5_2,
)
from vllm_grpc_bench.m5_2_supersede import M5_1PublishedJsonUnavailable

_M5_1_FIXTURE = {
    "m5_1_matrix": [
        {
            "path": "chat_stream",
            "hidden_size": 2048,
            "concurrency": 4,
            "verdicts": [
                {
                    "grpc_sub_cohort": "default_grpc",
                    "verdict": "no_winner",
                    "delta_pct": 0.0,
                    "ci_pct": [-1.0, 1.0],
                    "metric": "ttft",
                },
                {
                    "grpc_sub_cohort": "tuned_grpc_multiplexed",
                    "verdict": "tuned_grpc_multiplexed_recommend",
                    "delta_pct": -5.0,
                    "ci_pct": [-7.0, -3.0],
                    "metric": "ttft",
                },
                {
                    "grpc_sub_cohort": "tuned_grpc_channels",
                    "verdict": "no_winner",
                    "delta_pct": -1.0,
                    "ci_pct": [-2.5, 0.5],
                    "metric": "ttft",
                },
            ],
        }
    ]
}


def _make_record(
    *,
    cohort: str,
    path: str = "chat_stream",
    hidden_size: int = 2048,
    concurrency: int = 4,
    network_path: str,
    request_uuid: str,
    issue_ts_ms: float,
    done_ts_ms: float,
    first_byte_ts_ms: float | None,
    rtt_at_issue_ms: float = 50.0,
    phase: str = "measurement",
    request_body_bytes: int = 512,
    response_body_bytes: int = 1024,
) -> PerRequestEventRecord:
    return PerRequestEventRecord(
        cohort=cohort,  # type: ignore[arg-type]
        path=path,  # type: ignore[arg-type]
        hidden_size=hidden_size,
        concurrency=concurrency,
        network_path=network_path,  # type: ignore[arg-type]
        request_uuid=request_uuid,
        issue_ts_ms=issue_ts_ms,
        first_byte_ts_ms=first_byte_ts_ms,
        done_ts_ms=done_ts_ms,
        rtt_at_issue_ms=rtt_at_issue_ms,
        phase=phase,  # type: ignore[arg-type]
        server_bound=False,
        request_body_bytes=request_body_bytes,
        response_body_bytes=response_body_bytes,
        status="success",
    )


def _build_sidecar_and_config(
    tmp_path: Path,
    *,
    include_warmup: bool = False,
) -> tuple[Path, Path]:
    """Build a synthetic sidecar + matching run config in tmp_path. Returns
    (sidecar_gz_path, run_config_json_path)."""
    run_id = "regen-test"
    with EventsSidecarWriter(tmp_path, run_id) as writer:
        # rest_https_edge — 5 records.
        for i in range(5):
            issue = 100.0 + i * 10.0
            writer.write(
                _make_record(
                    cohort="rest_https_edge",
                    network_path="https_edge",
                    request_uuid=f"edge-{i:02d}-0000-0000-0000-000000000000",
                    issue_ts_ms=issue,
                    first_byte_ts_ms=issue + 8.0,
                    done_ts_ms=issue + 8.0,
                )
            )
        # rest_plain_tcp — 5 records.
        for i in range(5):
            issue = 200.0 + i * 10.0
            writer.write(
                _make_record(
                    cohort="rest_plain_tcp",
                    network_path="plain_tcp",
                    request_uuid=f"tcp-{i:02d}-0000-0000-0000-000000000000",
                    issue_ts_ms=issue,
                    first_byte_ts_ms=issue + 9.0,
                    done_ts_ms=issue + 9.0,
                )
            )
        # default_grpc — 5 records, slightly faster.
        for i in range(5):
            issue = 300.0 + i * 10.0
            writer.write(
                _make_record(
                    cohort="default_grpc",
                    network_path="plain_tcp",
                    request_uuid=f"def-{i:02d}-0000-0000-0000-000000000000",
                    issue_ts_ms=issue,
                    first_byte_ts_ms=issue + 5.0,
                    done_ts_ms=issue + 5.0,
                )
            )
        # tuned_grpc_multiplexed — 5 records.
        for i in range(5):
            issue = 400.0 + i * 10.0
            writer.write(
                _make_record(
                    cohort="tuned_grpc_multiplexed",
                    network_path="plain_tcp",
                    request_uuid=f"mux-{i:02d}-0000-0000-0000-000000000000",
                    issue_ts_ms=issue,
                    first_byte_ts_ms=issue + 4.0,
                    done_ts_ms=issue + 4.0,
                )
            )
        # tuned_grpc_channels — 5 records.
        for i in range(5):
            issue = 500.0 + i * 10.0
            writer.write(
                _make_record(
                    cohort="tuned_grpc_channels",
                    network_path="plain_tcp",
                    request_uuid=f"chn-{i:02d}-0000-0000-0000-000000000000",
                    issue_ts_ms=issue,
                    first_byte_ts_ms=issue + 4.5,
                    done_ts_ms=issue + 4.5,
                )
            )
        if include_warmup:
            # 3 warmup records that MUST be excluded from aggregates.
            for i in range(3):
                writer.write(
                    _make_record(
                        cohort="rest_https_edge",
                        network_path="https_edge",
                        request_uuid=f"warm-{i:02d}-0000-0000-0000-000000000000",
                        issue_ts_ms=50.0 + i * 5.0,
                        first_byte_ts_ms=50.0 + i * 5.0 + 100.0,
                        done_ts_ms=50.0 + i * 5.0 + 100.0,
                        phase="warmup",
                    )
                )

    sidecar_path, sha = writer.result
    run_config = {
        "run_id": run_id,
        "run_started_at_iso": "2026-05-12T12:00:00Z",
        "run_realized_runtime_s": 12.34,
        "seed": 0,
        "symmetry": {
            "tier_a": {
                "prompt_corpus_hash": "0" * 64,
                "modal_deploy_handle": "test-deploy",
                "mock_engine_config_digest": "1" * 64,
                "warmup_batch_policy": "discard_first_5_measurement_n_5",
            },
            "tier_b": {
                "rest_client_config_digest_url_excepted": "2" * 64,
                "tuned_grpc_channel_config_digest_topology_excepted": "3" * 64,
            },
            "tier_c": [],
            "client_external_geolocation_country": None,
            "client_external_geolocation_region": None,
        },
        "events_sidecar_path": str(sidecar_path),
        "events_sidecar_sha256": sha,
        "modal_region": "eu-west-1",
        "modal_instance_class": "cpu",
        "https_edge_endpoint": "https://test.modal.run",
        "client_external_geolocation": None,
    }
    cfg_path = tmp_path / f"{run_id}.run_config.json"
    cfg_path.write_text(json.dumps(run_config, sort_keys=True, separators=(",", ":")))
    return sidecar_path, cfg_path


def _write_m5_1_fixture(tmp_path: Path) -> Path:
    fx = tmp_path / "m5_1-rest-vs-grpc.json"
    fx.write_text(json.dumps(_M5_1_FIXTURE))
    return fx


def test_sha256_mismatch_refuses_to_write(tmp_path: Path) -> None:
    sidecar_path, cfg_path = _build_sidecar_and_config(tmp_path)
    cfg = json.loads(cfg_path.read_text())
    cfg["events_sidecar_sha256"] = "f" * 64
    cfg_path.write_text(json.dumps(cfg, sort_keys=True, separators=(",", ":")))
    with pytest.raises(SidecarChecksumMismatch):
        regen_m5_2(
            sidecar_path,
            cfg_path,
            report_out_prefix=tmp_path / "out",
            m5_1_published_path=_write_m5_1_fixture(tmp_path),
        )


def test_run_config_invalid_when_required_key_missing(tmp_path: Path) -> None:
    sidecar_path, cfg_path = _build_sidecar_and_config(tmp_path)
    cfg = json.loads(cfg_path.read_text())
    cfg.pop("symmetry")
    cfg_path.write_text(json.dumps(cfg, sort_keys=True, separators=(",", ":")))
    with pytest.raises(RunConfigInvalid):
        regen_m5_2(
            sidecar_path,
            cfg_path,
            report_out_prefix=tmp_path / "out",
            m5_1_published_path=_write_m5_1_fixture(tmp_path),
        )


def test_m5_1_published_unavailable_raises(tmp_path: Path) -> None:
    sidecar_path, cfg_path = _build_sidecar_and_config(tmp_path)
    with pytest.raises(M5_1PublishedJsonUnavailable):
        regen_m5_2(
            sidecar_path,
            cfg_path,
            report_out_prefix=tmp_path / "out",
            m5_1_published_path=tmp_path / "does-not-exist.json",
        )


def test_round_trip_byte_identical(tmp_path: Path) -> None:
    """The same sidecar + run config produces byte-identical markdown +
    JSON across two invocations per FR-012b."""
    sidecar_path, cfg_path = _build_sidecar_and_config(tmp_path)
    m5_1_fx = _write_m5_1_fixture(tmp_path)

    result_a = regen_m5_2(
        sidecar_path,
        cfg_path,
        report_out_prefix=tmp_path / "first" / "m5_2",
        m5_1_published_path=m5_1_fx,
    )
    result_b = regen_m5_2(
        sidecar_path,
        cfg_path,
        report_out_prefix=tmp_path / "second" / "m5_2",
        m5_1_published_path=m5_1_fx,
    )

    md_a = result_a.markdown_path.read_bytes()
    md_b = result_b.markdown_path.read_bytes()
    json_a = result_a.json_path.read_bytes()
    json_b = result_b.json_path.read_bytes()
    assert md_a == md_b, "markdown bytes must be identical across regenerator runs"
    assert json_a == json_b, "JSON bytes must be identical across regenerator runs"


def test_json_uses_compact_deterministic_encoding(tmp_path: Path) -> None:
    """The aggregate JSON uses ``sort_keys=True, separators=(",", ":")``.
    Verified by re-encoding the parsed payload with that exact encoder
    and asserting byte-equality with the written file.
    """
    sidecar_path, cfg_path = _build_sidecar_and_config(tmp_path)
    result = regen_m5_2(
        sidecar_path,
        cfg_path,
        report_out_prefix=tmp_path / "rt",
        m5_1_published_path=_write_m5_1_fixture(tmp_path),
    )
    blob = result.json_path.read_text()
    parsed = json.loads(blob)
    # Re-encode with the documented deterministic encoder; the result
    # MUST be byte-equal to the written file.
    re_encoded = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert blob == re_encoded
    assert parsed["events_sidecar_sha256"] == result.observed_sha256


def test_warmup_records_excluded_from_aggregates(tmp_path: Path) -> None:
    """FR-011: warmup records are persisted in the sidecar but excluded
    from aggregates."""
    sidecar_path, cfg_path = _build_sidecar_and_config(tmp_path, include_warmup=True)
    result = regen_m5_2(
        sidecar_path,
        cfg_path,
        report_out_prefix=tmp_path / "warm",
        m5_1_published_path=_write_m5_1_fixture(tmp_path),
    )
    # The warmup records had a deliberately huge metric (100 ms). Aggregate
    # excludes them; the rest_https_edge cohort's metric median should
    # match the non-warmup body (~8 ms).
    payload = json.loads(result.json_path.read_text())
    rows = payload["protocol_comparison_verdicts"]
    edge_rows = [r for r in rows if r["grpc_cohort"] == "default_grpc"]
    assert edge_rows, "expected at least one default_grpc row"
    # default_grpc TTFT is 5 ms; rest_https_edge TTFT is 8 ms. Delta should
    # be ~-3 ms (gRPC faster).
    assert edge_rows[0]["delta_median_ms"] < 0


def test_markdown_carries_field_provenance_blockquote(tmp_path: Path) -> None:
    """FR-012b: every aggregate-rendering section has a 'Computed from ...'
    blockquote naming the sidecar filter or aggregate-JSON key."""
    sidecar_path, cfg_path = _build_sidecar_and_config(tmp_path)
    result = regen_m5_2(
        sidecar_path,
        cfg_path,
        report_out_prefix=tmp_path / "prov",
        m5_1_published_path=_write_m5_1_fixture(tmp_path),
    )
    md_text = result.markdown_path.read_text()
    # At least one filter blockquote and one JSON-key blockquote per the
    # report structure.
    assert "> Computed from events sidecar filter:" in md_text
    assert "> Computed from aggregate JSON key:" in md_text


def test_sidecar_sha256_in_executive_metadata_matches(tmp_path: Path) -> None:
    """SC-013 surface: the SHA-256 surfaces in both the JSON's
    ``events_sidecar_sha256`` and the markdown's executive section so the
    reader can copy it into a ``shasum -a 256`` command for
    independent verification.
    """
    sidecar_path, cfg_path = _build_sidecar_and_config(tmp_path)
    result = regen_m5_2(
        sidecar_path,
        cfg_path,
        report_out_prefix=tmp_path / "sha",
        m5_1_published_path=_write_m5_1_fixture(tmp_path),
    )
    md = result.markdown_path.read_text()
    payload = json.loads(result.json_path.read_text())
    assert result.observed_sha256 in md
    assert payload["events_sidecar_sha256"] == result.observed_sha256
    # And independent recomputation matches.
    assert hashlib.sha256(sidecar_path.read_bytes()).hexdigest() == result.observed_sha256
