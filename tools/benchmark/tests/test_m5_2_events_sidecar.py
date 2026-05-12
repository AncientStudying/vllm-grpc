"""Tests for the M5.2 per-request JSONL events sidecar writer/reader (T013).

Asserts the FR-012a contract: deterministic encoding, gzip round-trip, SHA-256
verification, partial-record recovery, and the section-header filter syntax
(``key=value AND ... AND key IN {a,b,c}``).
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest
from vllm_grpc_bench.m5_2_events import (
    EventsSidecarWriter,
    PerRequestEventRecord,
    apply_filter,
    read_sidecar_iter,
    serialize_record,
)


def _make_record(
    *,
    cohort: str = "rest_https_edge",
    path: str = "chat_stream",
    hidden_size: int = 2048,
    concurrency: int = 4,
    network_path: str = "https_edge",
    request_uuid: str = "550e8400-e29b-41d4-a716-446655440000",
    issue_ts_ms: float = 100.0,
    first_byte_ts_ms: float | None = 110.0,
    done_ts_ms: float = 150.0,
    rtt_at_issue_ms: float = 50.0,
    phase: str = "measurement",
    server_bound: bool = False,
    request_body_bytes: int = 1247,
    response_body_bytes: int = 8930,
    status: str = "success",
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
        server_bound=server_bound,
        request_body_bytes=request_body_bytes,
        response_body_bytes=response_body_bytes,
        status=status,
    )


def test_serialize_record_is_sorted_and_compact() -> None:
    rec = _make_record()
    line = serialize_record(rec)
    # ``sort_keys=True`` puts ``cohort`` before ``concurrency``; ``status``
    # comes near the end alphabetically.
    assert line.startswith('{"cohort":"rest_https_edge","concurrency":4,')
    # ``separators=(",", ":")`` removes whitespace between tokens.
    assert ", " not in line
    assert ": " not in line


def test_writer_round_trip_preserves_every_field(tmp_path: Path) -> None:
    rec = _make_record()
    with EventsSidecarWriter(tmp_path, "test-run") as writer:
        writer.write(rec)
    gz_path, sha = writer.result
    assert gz_path.exists()
    # SHA matches a re-read of the bytes.
    assert sha == hashlib.sha256(gz_path.read_bytes()).hexdigest()
    # Round-trip via the reader.
    records = list(read_sidecar_iter(gz_path))
    assert len(records) == 1
    assert records[0] == rec


def test_writer_produces_deterministic_bytes_across_runs(tmp_path: Path) -> None:
    """Re-running the writer on equivalent in-memory state produces
    byte-identical gzipped output. ``mtime=0`` is what makes this hold.
    """
    rec_a = _make_record()
    rec_b = _make_record(request_uuid="b" * 36, issue_ts_ms=200.0, done_ts_ms=250.0)

    with EventsSidecarWriter(tmp_path / "first", "run") as w:
        w.write(rec_a)
        w.write(rec_b)
    first_path, first_sha = w.result

    with EventsSidecarWriter(tmp_path / "second", "run") as w:
        w.write(rec_a)
        w.write(rec_b)
    second_path, second_sha = w.result

    assert first_sha == second_sha
    assert first_path.read_bytes() == second_path.read_bytes()


def test_intermediate_un_gzipped_file_is_removed(tmp_path: Path) -> None:
    rec = _make_record()
    with EventsSidecarWriter(tmp_path, "run") as w:
        w.write(rec)
    intermediate = tmp_path / "run.events.jsonl"
    assert not intermediate.exists(), "intermediate un-gzipped JSONL must be cleaned up"


def test_reader_skips_partial_trailing_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A SIGKILL'd writer leaves a partial trailing record. The reader skips
    it silently (warns via stderr) and yields the well-formed records.
    """
    rec = _make_record()
    intermediate = tmp_path / "run.events.jsonl"
    intermediate.write_text(serialize_record(rec) + "\n" + '{"cohort":"rest_htt')
    gz_path = tmp_path / "run.events.jsonl.gz"
    with (
        open(gz_path, "wb") as raw_out,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw_out, mtime=0) as out,
    ):
        out.write(intermediate.read_bytes())

    records = list(read_sidecar_iter(gz_path))
    assert len(records) == 1
    err = capsys.readouterr().err
    assert "JSON decode error" in err or "missing required" in err


def test_reader_warns_on_unknown_additional_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Forward-compat: an extra field in a JSONL line warns but does not
    raise. The record still yields with the M5.2 fields populated."""
    rec = _make_record()
    line = json.dumps(
        {**rec.__dict__, "future_field_from_m5_3": "ignored"},
        sort_keys=True,
        separators=(",", ":"),
    )
    gz_path = tmp_path / "future.events.jsonl.gz"
    with (
        open(gz_path, "wb") as raw_out,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw_out, mtime=0) as out,
    ):
        out.write((line + "\n").encode("utf-8"))

    records = list(read_sidecar_iter(gz_path))
    assert len(records) == 1
    err = capsys.readouterr().err
    assert "future_field_from_m5_3" in err


def test_filter_eq_chain_selects_one_cohort() -> None:
    a = _make_record(cohort="rest_https_edge")
    b = _make_record(cohort="rest_plain_tcp")
    c = _make_record(cohort="default_grpc")
    out = list(
        apply_filter(
            [a, b, c],
            "cohort=rest_https_edge AND phase=measurement AND status=success",
        )
    )
    assert out == [a]


def test_filter_in_set_matches_multiple_cohorts() -> None:
    a = _make_record(cohort="rest_https_edge")
    b = _make_record(cohort="rest_plain_tcp")
    c = _make_record(cohort="default_grpc")
    out = list(apply_filter([a, b, c], "cohort IN {rest_https_edge,default_grpc}"))
    assert {r.cohort for r in out} == {"rest_https_edge", "default_grpc"}


def test_filter_excludes_warmup_records() -> None:
    warm = _make_record(phase="warmup")
    meas = _make_record(phase="measurement")
    out = list(apply_filter([warm, meas], "phase=measurement"))
    assert out == [meas]


def test_filter_rejects_malformed_clause() -> None:
    with pytest.raises(ValueError, match="cannot parse clause"):
        list(apply_filter([_make_record()], "cohort EQUALS rest_https_edge"))


def test_empty_filter_yields_every_record() -> None:
    a = _make_record(cohort="rest_https_edge")
    b = _make_record(cohort="default_grpc")
    assert list(apply_filter([a, b], "")) == [a, b]
