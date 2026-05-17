"""M6.1.1 sidecar JSONL events writer tests (T036)."""

from __future__ import annotations

import json
from pathlib import Path

from vllm_grpc_bench.m6_1_1_reporter import write_sidecar_events


def _sample_event() -> dict:
    return {
        "cell_str": "chat_stream_c4_h4096",
        "cohort": "tuned_grpc_multiplexed",
        "rpc_index": 23,
        "wall_clock_ms": 89.4,
        "engine_ttft_ms": 41.2,
        "m6_1_1_timings": {
            "handler_entry_ns": 1716480000000000000,
            "pre_engine_ns": 1716480000003200000,
            "first_chunk_ns": 1716480000046700000,
            "terminal_emit_ns": 1716480000089200000,
            "perturbation_audit_ns": 240,
        },
    }


def test_first_write_creates_file_with_separator_then_events(tmp_path: Path) -> None:
    sidecar = tmp_path / "events.jsonl"
    write_sidecar_events(sidecar, run_id="run-1", events=[_sample_event()])
    lines = sidecar.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    sep = json.loads(lines[0])
    assert sep == {"_run_separator": True, "run_id": "run-1"}
    event = json.loads(lines[1])
    assert event["cell_str"] == "chat_stream_c4_h4096"


def test_second_write_appends_separator_and_events(tmp_path: Path) -> None:
    """Each invocation prepends a separator then appends events; the sidecar
    is append-only across runs (round-3 Q1)."""
    sidecar = tmp_path / "events.jsonl"
    write_sidecar_events(sidecar, run_id="run-1", events=[_sample_event()])
    write_sidecar_events(
        sidecar,
        run_id="run-2",
        events=[_sample_event(), _sample_event()],
    )
    lines = sidecar.read_text(encoding="utf-8").splitlines()
    # Layout: sep1, ev1, sep2, ev2, ev3
    assert len(lines) == 5
    assert json.loads(lines[0])["run_id"] == "run-1"
    assert "_run_separator" not in json.loads(lines[1])
    assert json.loads(lines[2])["run_id"] == "run-2"
    assert json.loads(lines[2])["_run_separator"] is True


def test_empty_events_writes_only_separator(tmp_path: Path) -> None:
    sidecar = tmp_path / "events.jsonl"
    write_sidecar_events(sidecar, run_id="run-1", events=[])
    lines = sidecar.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"_run_separator": True, "run_id": "run-1"}


def test_parent_directory_is_created_if_missing(tmp_path: Path) -> None:
    sidecar = tmp_path / "nested" / "deeper" / "events.jsonl"
    write_sidecar_events(sidecar, run_id="r", events=[_sample_event()])
    assert sidecar.is_file()


def test_events_are_one_jsonl_line_each(tmp_path: Path) -> None:
    """Each event line is valid JSON; no newlines inside event payloads."""
    sidecar = tmp_path / "events.jsonl"
    write_sidecar_events(
        sidecar,
        run_id="r",
        events=[
            {"a": 1, "b": "with spaces"},
            {"c": [1, 2, 3], "d": {"nested": "yes"}},
        ],
    )
    lines = sidecar.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # separator + 2 events
    for line in lines[1:]:
        decoded = json.loads(line)
        assert isinstance(decoded, dict)


def test_unicode_content_preserved(tmp_path: Path) -> None:
    """``ensure_ascii=False`` so cohort names and unicode survive round-trip."""
    sidecar = tmp_path / "events.jsonl"
    write_sidecar_events(sidecar, run_id="r", events=[{"note": "perturbation 0.24 µs"}])
    body = sidecar.read_text(encoding="utf-8")
    assert "µs" in body
