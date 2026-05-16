"""M6.1.1 client-side timing extractors — FR-007 / FR-008 (R-3) tests."""

from __future__ import annotations

import pytest
from vllm_grpc_bench.m6_1_1_timing import (
    compute_per_segment_delta,
    extract_grpc_timings,
    extract_rest_timings,
)
from vllm_grpc_bench.m6_1_1_types import TimingCheckpoint


def _valid_sub_object() -> dict[str, int]:
    return {
        "handler_entry_ns": 1_000_000,
        "pre_engine_ns": 2_500_000,
        "first_chunk_ns": 42_500_000,
        "terminal_emit_ns": 44_000_000,
        "perturbation_audit_ns": 240,
    }


def _valid_grpc_md() -> dict[str, str]:
    return {
        "engine-ttft-ms": "43.5",  # existing M6 key — extractor ignores it
        "m6_1_1_t_handler_entry": "1000000",
        "m6_1_1_t_pre_engine": "2500000",
        "m6_1_1_t_first_chunk": "42500000",
        "m6_1_1_t_terminal_emit": "44000000",
        "m6_1_1_t_perturbation_audit_ns": "240",
    }


# --- REST extractor ---------------------------------------------------------


def test_extract_rest_happy_path() -> None:
    terminal = {
        "id": "chatcmpl-x",
        "choices": [],
        "engine_cost": {"engine_ttft_ms": 43.5, "engine_tpot_ms": 12.7},
        "m6_1_1_timings": _valid_sub_object(),
    }
    ckpt = extract_rest_timings(terminal)
    assert ckpt is not None
    assert ckpt.handler_entry_ns == 1_000_000
    assert ckpt.pre_engine_ns == 2_500_000
    assert ckpt.first_chunk_ns == 42_500_000
    assert ckpt.terminal_emit_ns == 44_000_000
    assert ckpt.perturbation_audit_ns == 240


def test_extract_rest_returns_none_when_subobject_absent() -> None:
    """An M6 / M6.1 server doesn't emit the m6_1_1_timings sub-object."""
    terminal = {
        "id": "chatcmpl-x",
        "choices": [],
        "engine_cost": {"engine_ttft_ms": 43.5, "engine_tpot_ms": 12.7},
    }
    assert extract_rest_timings(terminal) is None


def test_extract_rest_returns_none_when_subobject_non_dict() -> None:
    """Malformed payload (sub-object replaced by a non-dict)."""
    terminal = {"m6_1_1_timings": "not a dict"}
    assert extract_rest_timings(terminal) is None


def test_extract_rest_returns_none_when_field_missing() -> None:
    sub = _valid_sub_object()
    del sub["first_chunk_ns"]
    terminal = {"m6_1_1_timings": sub}
    assert extract_rest_timings(terminal) is None


def test_extract_rest_returns_none_when_field_non_integer() -> None:
    sub = _valid_sub_object()
    sub["pre_engine_ns"] = "not a number"  # type: ignore[assignment]
    terminal = {"m6_1_1_timings": sub}
    assert extract_rest_timings(terminal) is None


def test_extract_rest_accepts_string_integers() -> None:
    """JSON numbers can arrive as ints; strings of digits also accepted via int()."""
    sub = {k: str(v) for k, v in _valid_sub_object().items()}
    terminal = {"m6_1_1_timings": sub}
    ckpt = extract_rest_timings(terminal)
    assert ckpt is not None
    assert ckpt.handler_entry_ns == 1_000_000


# --- gRPC extractor ---------------------------------------------------------


def test_extract_grpc_happy_path() -> None:
    ckpt = extract_grpc_timings(_valid_grpc_md())
    assert ckpt is not None
    assert ckpt.handler_entry_ns == 1_000_000
    assert ckpt.terminal_emit_ns == 44_000_000
    assert ckpt.perturbation_audit_ns == 240


def test_extract_grpc_returns_none_when_keys_absent() -> None:
    """An M6 / M6.1 server doesn't emit the m6_1_1_t_* keys."""
    md_without_m6_1_1 = {
        "engine-ttft-ms": "43.5",
        "engine-tpot-ms": "12.7",
    }
    assert extract_grpc_timings(md_without_m6_1_1) is None


def test_extract_grpc_returns_none_when_single_key_missing() -> None:
    md = _valid_grpc_md()
    del md["m6_1_1_t_terminal_emit"]
    assert extract_grpc_timings(md) is None


def test_extract_grpc_returns_none_when_value_non_numeric() -> None:
    md = _valid_grpc_md()
    md["m6_1_1_t_pre_engine"] = "not a number"
    assert extract_grpc_timings(md) is None


def test_extract_grpc_preserves_existing_m6_keys_unread() -> None:
    """Adding new keys doesn't affect the M6 keys — the extractor only reads its own."""
    md = _valid_grpc_md()
    ckpt = extract_grpc_timings(md)
    assert ckpt is not None
    # M6 keys are preserved in the input dict (extractor doesn't mutate).
    assert md["engine-ttft-ms"] == "43.5"


# --- compute_per_segment_delta ----------------------------------------------


def test_compute_per_segment_delta_ns_to_ms() -> None:
    ckpt = TimingCheckpoint(
        handler_entry_ns=1_000_000,
        pre_engine_ns=2_500_000,
        first_chunk_ns=42_500_000,
        terminal_emit_ns=44_000_000,
        perturbation_audit_ns=240,
    )
    delta = compute_per_segment_delta(ckpt)
    assert delta.seg_ab_ms == pytest.approx(1.5)
    assert delta.seg_bc_ms == pytest.approx(40.0)
    assert delta.seg_cd_ms == pytest.approx(1.5)


def test_per_segment_monotonicity_implicit_in_well_formed_input() -> None:
    """Well-formed checkpoints (each ts > previous) yield non-negative segment deltas."""
    ckpt = TimingCheckpoint(
        handler_entry_ns=100,
        pre_engine_ns=200,
        first_chunk_ns=300,
        terminal_emit_ns=400,
        perturbation_audit_ns=10,
    )
    delta = compute_per_segment_delta(ckpt)
    assert delta.seg_ab_ms >= 0
    assert delta.seg_bc_ms >= 0
    assert delta.seg_cd_ms >= 0
