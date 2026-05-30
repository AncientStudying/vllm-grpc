"""New-home coverage for the de-prefixed ``timing`` module (T023).

Asserts the hoisted timing surface (formerly ``m6_1_1_timing`` /
``m6_1_1_types``): both wire extractors round-trip a full checkpoint, the
``has_engine_stats`` gate, the ns→ms segment derivation, and the
payload/​re-hydration round-trip used by RPC drivers.
"""

from __future__ import annotations

from vllm_grpc_bench.timing import (
    PerSegmentDelta,
    TimingCheckpoint,
    compute_per_segment_delta,
    extract_grpc_timings,
    extract_rest_timings,
    timing_checkpoint_to_payload,
)


def _full_checkpoint() -> TimingCheckpoint:
    return TimingCheckpoint(
        handler_entry_ns=1_000,
        pre_engine_ns=3_000,
        first_chunk_ns=8_000,
        terminal_emit_ns=15_000,
        perturbation_audit_ns=16_000,
        engine_queued_ns=4_000,
        engine_scheduled_ns=5_000,
        engine_first_token_ns=7_000,
        engine_last_token_ns=14_000,
    )


def test_has_engine_stats_true_when_all_populated() -> None:
    assert _full_checkpoint().has_engine_stats is True


def test_has_engine_stats_false_when_missing() -> None:
    ckpt = TimingCheckpoint(
        handler_entry_ns=1_000,
        pre_engine_ns=3_000,
        first_chunk_ns=8_000,
        terminal_emit_ns=15_000,
        perturbation_audit_ns=16_000,
    )
    assert ckpt.has_engine_stats is False


def test_per_segment_delta_ns_to_ms() -> None:
    """Segments are pure ns→ms subtractions of the perf-counter checkpoints."""
    delta = compute_per_segment_delta(_full_checkpoint())
    assert delta.seg_ab_ms == (3_000 - 1_000) * 1e-6
    assert delta.seg_bc_ms == (8_000 - 3_000) * 1e-6
    assert delta.seg_cd_ms == (15_000 - 8_000) * 1e-6
    assert delta.seg_queue_ms == (5_000 - 4_000) * 1e-6
    assert delta.seg_prefill_ms == (7_000 - 5_000) * 1e-6


def test_per_segment_delta_engine_segments_none_without_stats() -> None:
    ckpt = TimingCheckpoint(
        handler_entry_ns=1_000,
        pre_engine_ns=3_000,
        first_chunk_ns=8_000,
        terminal_emit_ns=15_000,
        perturbation_audit_ns=16_000,
    )
    delta = PerSegmentDelta.from_checkpoint(ckpt)
    assert delta.seg_queue_ms is None
    assert delta.seg_prefill_ms is None


def test_extract_rest_timings_round_trips() -> None:
    ckpt = _full_checkpoint()
    payload = timing_checkpoint_to_payload(ckpt)
    assert payload is not None
    extracted = extract_rest_timings({"m6_1_1_timings": payload})
    assert extracted == ckpt


def test_extract_rest_timings_missing_subobject_is_none() -> None:
    assert extract_rest_timings({}) is None
    assert extract_rest_timings({"m6_1_1_timings": "not-a-dict"}) is None


def test_extract_rest_timings_partial_is_none() -> None:
    """A missing required checkpoint field is a miss, not a half-populated record."""
    assert extract_rest_timings({"m6_1_1_timings": {"handler_entry_ns": 1}}) is None


def test_extract_grpc_timings_round_trips() -> None:
    trailing_md = {
        "m6_1_1_t_handler_entry": "1000",
        "m6_1_1_t_pre_engine": "3000",
        "m6_1_1_t_first_chunk": "8000",
        "m6_1_1_t_terminal_emit": "15000",
        "m6_1_1_t_perturbation_audit_ns": "16000",
        "m6_1_1_t_engine_queued_ns": "4000",
        "m6_1_1_t_engine_scheduled_ns": "5000",
        "m6_1_1_t_engine_first_token_ns": "7000",
        "m6_1_1_t_engine_last_token_ns": "14000",
    }
    extracted = extract_grpc_timings(trailing_md)
    assert extracted is not None
    assert extracted.handler_entry_ns == 1_000
    assert extracted.has_engine_stats is True


def test_extract_grpc_timings_missing_key_is_none() -> None:
    assert extract_grpc_timings({}) is None


def test_timing_checkpoint_to_payload_none_passthrough() -> None:
    assert timing_checkpoint_to_payload(None) is None


def test_payload_rehydrates_to_equal_checkpoint() -> None:
    """``TimingCheckpoint(**payload)`` reconstructs the original (driver contract)."""
    ckpt = _full_checkpoint()
    payload = timing_checkpoint_to_payload(ckpt)
    assert payload is not None
    assert TimingCheckpoint(**payload) == ckpt  # type: ignore[arg-type]
