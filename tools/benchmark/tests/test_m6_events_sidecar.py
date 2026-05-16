"""Tests for the M6 events sidecar extension (T017).

Asserts that:
- Warmup records have ``rpc_index is None`` and ``seed is None``
  (FR-021 / FR-025 validation rule).
- Measurement records have both set.
- engine_cost trio is path-discriminated (embed sets engine_forward_ms
  only; chat_stream sets engine_ttft_ms + engine_tpot_ms).
- M5.2-shape records (without the M6 additive fields) still read back
  cleanly through the same writer/reader pair (FR-016 strict superset).
"""

from __future__ import annotations

from pathlib import Path

from vllm_grpc_bench.m5_2_events import (
    EventsSidecarWriter,
    PerRequestEventRecord,
    read_sidecar_iter,
)


def _build_warmup_record() -> PerRequestEventRecord:
    return PerRequestEventRecord(
        cohort="tuned_grpc_multiplexed",
        path="embed",
        hidden_size=4096,
        concurrency=1,
        network_path="plain_tcp",
        request_uuid="uuid-warmup",
        issue_ts_ms=0.0,
        first_byte_ts_ms=None,
        done_ts_ms=10.0,
        rtt_at_issue_ms=2.0,
        phase="warmup",
        server_bound=False,
        request_body_bytes=100,
        response_body_bytes=200,
        status="ok",
        rpc_phase="warmup",
        rpc_index=None,
        seed=None,
        engine_forward_ms=12.5,
        engine_ttft_ms=None,
        engine_tpot_ms=None,
        success=True,
        failure_reason=None,
        retry_count=0,
    )


def _build_measurement_record_embed() -> PerRequestEventRecord:
    return PerRequestEventRecord(
        cohort="tuned_grpc_multiplexed",
        path="embed",
        hidden_size=4096,
        concurrency=4,
        network_path="plain_tcp",
        request_uuid="uuid-meas-embed",
        issue_ts_ms=10.0,
        first_byte_ts_ms=None,
        done_ts_ms=22.5,
        rtt_at_issue_ms=2.0,
        phase="measurement",
        server_bound=False,
        request_body_bytes=100,
        response_body_bytes=200,
        status="ok",
        rpc_phase="measurement",
        rpc_index=0,
        seed=42,
        engine_forward_ms=12.5,
        engine_ttft_ms=None,
        engine_tpot_ms=None,
        success=True,
        failure_reason=None,
        retry_count=0,
    )


def _build_measurement_record_chat_stream() -> PerRequestEventRecord:
    return PerRequestEventRecord(
        cohort="rest_https_edge",
        path="chat_stream",
        hidden_size=4096,
        concurrency=1,
        network_path="https_edge",
        request_uuid="uuid-meas-chat",
        issue_ts_ms=0.0,
        first_byte_ts_ms=100.0,
        done_ts_ms=2400.0,
        rtt_at_issue_ms=50.0,
        phase="measurement",
        server_bound=False,
        request_body_bytes=200,
        response_body_bytes=400,
        status="ok",
        rpc_phase="measurement",
        rpc_index=1,
        seed=43,
        engine_forward_ms=None,
        engine_ttft_ms=100.0,
        engine_tpot_ms=30.0,
        success=True,
        failure_reason=None,
        retry_count=0,
    )


def test_warmup_record_has_no_rpc_index_or_seed(tmp_path: Path) -> None:
    with EventsSidecarWriter(tmp_path, "run") as w:
        w.write(_build_warmup_record())
    out = list(read_sidecar_iter(w.result[0]))
    assert len(out) == 1
    rec = out[0]
    assert rec.rpc_phase == "warmup"
    assert rec.rpc_index is None
    assert rec.seed is None


def test_measurement_record_has_rpc_index_and_seed(tmp_path: Path) -> None:
    with EventsSidecarWriter(tmp_path, "run") as w:
        w.write(_build_measurement_record_embed())
    out = list(read_sidecar_iter(w.result[0]))
    assert len(out) == 1
    rec = out[0]
    assert rec.rpc_phase == "measurement"
    assert rec.rpc_index == 0
    assert rec.seed == 42


def test_embed_path_only_sets_engine_forward_ms(tmp_path: Path) -> None:
    rec = _build_measurement_record_embed()
    assert rec.engine_forward_ms == 12.5
    assert rec.engine_ttft_ms is None
    assert rec.engine_tpot_ms is None


def test_chat_stream_path_sets_both_ttft_and_tpot(tmp_path: Path) -> None:
    rec = _build_measurement_record_chat_stream()
    assert rec.engine_forward_ms is None
    assert rec.engine_ttft_ms == 100.0
    assert rec.engine_tpot_ms == 30.0


def test_m5_2_shape_record_still_reads(tmp_path: Path) -> None:
    """M5.2-shape readers MUST keep working: a record without the M6
    optional fields still round-trips cleanly (FR-016 strict superset).
    """
    rec = PerRequestEventRecord(
        cohort="default_grpc",
        path="embed",
        hidden_size=2048,
        concurrency=1,
        network_path="plain_tcp",
        request_uuid="uuid-m5-2",
        issue_ts_ms=0.0,
        first_byte_ts_ms=None,
        done_ts_ms=20.0,
        rtt_at_issue_ms=2.0,
        phase="measurement",
        server_bound=False,
        request_body_bytes=100,
        response_body_bytes=200,
        status="ok",
    )
    with EventsSidecarWriter(tmp_path, "run") as w:
        w.write(rec)
    out = list(read_sidecar_iter(w.result[0]))
    assert len(out) == 1
    assert out[0].cohort == "default_grpc"
    # M6 fields default to None on M5.2-shape records.
    assert out[0].rpc_phase is None
    assert out[0].engine_forward_ms is None
