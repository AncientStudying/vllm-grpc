"""M6.1.1 — client-side wire-format extractors (FR-007 / FR-008, R-3).

Two extractors share a single ``TimingCheckpoint`` output shape:

* :func:`extract_rest_timings` reads the ``m6_1_1_timings`` sub-object on a
  REST terminal SSE event JSON payload (chat_stream) or on the embed
  JSONResponse body (FR-011 audit-only controls).
* :func:`extract_grpc_timings` reads the five ``m6_1_1_t_*`` prefixed
  trailing-metadata keys from a gRPC ChatServicer / CompletionsServicer
  response.

Both extractors are **best-effort**: they return ``None`` when M6.1.1
instrumentation isn't present on the wire (e.g., when the bench client is
talking to an M6 / M6.1 server). The existing per-RPC event assembly
silently skips the M6.1.1 fields when the extractor returns ``None``.

Per-segment deltas (``seg_ab_ms``, ``seg_bc_ms``, ``seg_cd_ms``) are
derived via :meth:`PerSegmentDelta.from_checkpoint` in
``m6_1_1_types.py`` so the conversion lives next to the dataclass.
"""

from __future__ import annotations

from typing import Any

from vllm_grpc_bench.m6_1_1_types import PerSegmentDelta, TimingCheckpoint


def extract_rest_timings(sse_terminal_event: dict[str, Any]) -> TimingCheckpoint | None:
    """Read the ``m6_1_1_timings`` sub-object from a REST terminal payload.

    Accepts both shapes:

    * Chat stream — sub-object at ``terminal["m6_1_1_timings"]``.
    * Embed unary — same key on the JSONResponse body.

    Returns ``None`` when:
    * the ``m6_1_1_timings`` sub-object is absent (M6 / M6.1 server), or
    * any required field is missing or non-integer (partial extraction is
      treated as a miss so the FR-010 classifier never sees half-populated
      timings).
    """
    sub = sse_terminal_event.get("m6_1_1_timings")
    if not isinstance(sub, dict):
        return None
    try:
        return TimingCheckpoint(
            handler_entry_ns=int(sub["handler_entry_ns"]),
            pre_engine_ns=int(sub["pre_engine_ns"]),
            first_chunk_ns=int(sub["first_chunk_ns"]),
            terminal_emit_ns=int(sub["terminal_emit_ns"]),
            perturbation_audit_ns=int(sub["perturbation_audit_ns"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def extract_grpc_timings(trailing_md: dict[str, str]) -> TimingCheckpoint | None:
    """Read the five ``m6_1_1_t_*`` keys from gRPC trailing metadata.

    gRPC trailing metadata values are ASCII strings; we ``int()``-parse them.
    Returns ``None`` when any required key is missing or non-numeric — same
    best-effort semantics as :func:`extract_rest_timings`.
    """
    try:
        return TimingCheckpoint(
            handler_entry_ns=int(trailing_md["m6_1_1_t_handler_entry"]),
            pre_engine_ns=int(trailing_md["m6_1_1_t_pre_engine"]),
            first_chunk_ns=int(trailing_md["m6_1_1_t_first_chunk"]),
            terminal_emit_ns=int(trailing_md["m6_1_1_t_terminal_emit"]),
            perturbation_audit_ns=int(trailing_md["m6_1_1_t_perturbation_audit_ns"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def compute_per_segment_delta(ckpt: TimingCheckpoint) -> PerSegmentDelta:
    """Pure ns→ms conversion per FR-009. Thin alias for
    :meth:`PerSegmentDelta.from_checkpoint`."""
    return PerSegmentDelta.from_checkpoint(ckpt)


__all__ = [
    "compute_per_segment_delta",
    "extract_grpc_timings",
    "extract_rest_timings",
]
