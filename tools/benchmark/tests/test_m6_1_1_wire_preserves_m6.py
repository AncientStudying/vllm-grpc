"""M6 / M6.1 wire-format preservation regression test (T037).

Synthetic M6 / M6.1 server responses parsed by:
* the M6 engine_cost extractor (``parse_grpc_trailing_metadata`` / ``parse_rest_response``)
* the M6.1.1 timing extractor (``extract_grpc_timings`` / ``extract_rest_timings``)

The M6 extractor MUST produce identical ``EngineCostSpan`` data regardless
of whether the M6.1.1 ``m6_1_1_timings`` sub-object / ``m6_1_1_t_*`` keys
are present. The M6.1.1 extractor MUST return ``None`` when those fields
are absent (best-effort fallback per Research R-3).
"""

from __future__ import annotations

from vllm_grpc_bench.m6_1_1_timing import extract_grpc_timings, extract_rest_timings
from vllm_grpc_bench.m6_engine_cost import parse_grpc_trailing_metadata, parse_rest_response

# --- REST: M6.1.1 fields don't perturb M6 engine_cost extraction -----------


def _rest_chat_stream_payload_m6_only() -> dict:
    """M6 / M6.1 terminal SSE event (no m6_1_1_timings sub-object)."""
    return {
        "id": "chatcmpl-x",
        "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
        "engine_cost": {
            "engine_ttft_ms": 43.5,
            "engine_tpot_ms": 12.7,
        },
    }


def _rest_chat_stream_payload_m6_1_1() -> dict:
    """M6.1.1 terminal SSE event (M6 fields preserved + m6_1_1_timings sub-object)."""
    payload = _rest_chat_stream_payload_m6_only()
    payload["m6_1_1_timings"] = {
        "handler_entry_ns": 1_000_000,
        "pre_engine_ns": 2_500_000,
        "first_chunk_ns": 42_500_000,
        "terminal_emit_ns": 44_000_000,
        "perturbation_audit_ns": 240,
    }
    return payload


def test_m6_extractor_returns_same_span_with_or_without_m6_1_1_subobject() -> None:
    """The M6 engine_cost extractor reads the existing fields verbatim and
    ignores unknown keys — adding m6_1_1_timings must NOT perturb its output."""
    m6_only = _rest_chat_stream_payload_m6_only()
    m6_1_1 = _rest_chat_stream_payload_m6_1_1()
    span_without = parse_rest_response(m6_only, "chat_stream")
    span_with = parse_rest_response(m6_1_1, "chat_stream")
    assert span_without == span_with
    assert span_with is not None
    assert span_with.engine_ttft_ms == 43.5
    assert span_with.engine_tpot_ms == 12.7


def test_m6_extractor_handles_embed_response_unchanged() -> None:
    """Embed cell's engine_cost.engine_forward_ms remains readable when the
    M6.1.1 sub-object is added to the embed JSONResponse body (FR-011)."""
    m6_only = {"engine_cost": {"engine_forward_ms": 338.1}}
    m6_1_1 = {
        "engine_cost": {"engine_forward_ms": 338.1},
        "m6_1_1_timings": {
            "handler_entry_ns": 1_000_000,
            "pre_engine_ns": 2_000_000,
            "first_chunk_ns": 300_000_000,
            "terminal_emit_ns": 338_100_000,
            "perturbation_audit_ns": 240,
        },
    }
    span_without = parse_rest_response(m6_only, "embed")
    span_with = parse_rest_response(m6_1_1, "embed")
    assert span_without == span_with
    assert span_with is not None
    assert span_with.engine_forward_ms == 338.1


def test_m6_1_1_extractor_returns_none_for_m6_payload() -> None:
    """The M6.1.1 extractor returns None on M6 / M6.1 payloads (best-effort)."""
    assert extract_rest_timings(_rest_chat_stream_payload_m6_only()) is None


def test_m6_1_1_extractor_returns_ckpt_for_m6_1_1_payload() -> None:
    ckpt = extract_rest_timings(_rest_chat_stream_payload_m6_1_1())
    assert ckpt is not None
    assert ckpt.handler_entry_ns == 1_000_000


# --- gRPC: M6.1.1 trailing keys don't perturb M6 engine_cost extraction ----


def _grpc_chat_stream_md_m6_only() -> list[tuple[str, str]]:
    return [
        ("engine-ttft-ms", "43.5"),
        ("engine-tpot-ms", "12.7"),
    ]


def _grpc_chat_stream_md_m6_1_1() -> list[tuple[str, str]]:
    return _grpc_chat_stream_md_m6_only() + [
        ("m6_1_1_t_handler_entry", "1000000"),
        ("m6_1_1_t_pre_engine", "2500000"),
        ("m6_1_1_t_first_chunk", "42500000"),
        ("m6_1_1_t_terminal_emit", "44000000"),
        ("m6_1_1_t_perturbation_audit_ns", "240"),
    ]


def test_m6_grpc_extractor_returns_same_span_with_or_without_m6_1_1_keys() -> None:
    span_without = parse_grpc_trailing_metadata(_grpc_chat_stream_md_m6_only(), "chat_stream")
    span_with = parse_grpc_trailing_metadata(_grpc_chat_stream_md_m6_1_1(), "chat_stream")
    assert span_without == span_with
    assert span_with is not None
    assert span_with.engine_ttft_ms == 43.5


def test_m6_grpc_extractor_handles_embed_call_unchanged() -> None:
    m6_only: list[tuple[str, str]] = [("engine-forward-ms", "338.1")]
    m6_1_1 = m6_only + [
        ("m6_1_1_t_handler_entry", "1000000"),
        ("m6_1_1_t_pre_engine", "2000000"),
        ("m6_1_1_t_first_chunk", "300000000"),
        ("m6_1_1_t_terminal_emit", "338100000"),
        ("m6_1_1_t_perturbation_audit_ns", "240"),
    ]
    span_without = parse_grpc_trailing_metadata(m6_only, "embed")
    span_with = parse_grpc_trailing_metadata(m6_1_1, "embed")
    assert span_without == span_with
    assert span_with is not None
    assert span_with.engine_forward_ms == 338.1


def test_m6_1_1_grpc_extractor_returns_none_on_m6_md() -> None:
    md = {k: v for k, v in _grpc_chat_stream_md_m6_only()}
    assert extract_grpc_timings(md) is None


def test_m6_1_1_grpc_extractor_returns_ckpt_on_m6_1_1_md() -> None:
    md = {k: v for k, v in _grpc_chat_stream_md_m6_1_1()}
    ckpt = extract_grpc_timings(md)
    assert ckpt is not None
    assert ckpt.handler_entry_ns == 1_000_000
