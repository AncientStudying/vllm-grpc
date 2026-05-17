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


def _opt_int(value: Any) -> int:
    """Coerce a value to int, returning 0 on missing/invalid input.

    Used for the M6.1.2 engine-internal fields: when an upstream server
    pre-dates the M6.1.2 instrumentation upgrade (or vLLM didn't populate
    the corresponding ``RequestStateStats`` field) the wire keys are
    absent — the extractor returns a checkpoint with ``0`` for those
    fields, and ``TimingCheckpoint.has_engine_stats`` returns False.
    """
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def extract_rest_timings(sse_terminal_event: dict[str, Any]) -> TimingCheckpoint | None:
    """Read the ``m6_1_1_timings`` sub-object from a REST terminal payload.

    Accepts both shapes:

    * Chat stream — sub-object at ``terminal["m6_1_1_timings"]``.
    * Embed unary — same key on the JSONResponse body.

    Returns ``None`` when:
    * the ``m6_1_1_timings`` sub-object is absent (M6 / M6.1 server), or
    * any of the five original four-checkpoint fields is missing or
      non-integer (partial extraction is treated as a miss so the FR-010
      classifier never sees half-populated timings).

    M6.1.2 engine-internal fields (``engine_*_ns``) are best-effort: when
    absent, they default to 0 and ``ckpt.has_engine_stats`` returns False;
    downstream consumers skip the queue/prefill segments accordingly.
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
            engine_arrival_ns=_opt_int(sub.get("engine_arrival_ns")),
            engine_queued_ns=_opt_int(sub.get("engine_queued_ns")),
            engine_scheduled_ns=_opt_int(sub.get("engine_scheduled_ns")),
            engine_first_token_ns=_opt_int(sub.get("engine_first_token_ns")),
            engine_last_token_ns=_opt_int(sub.get("engine_last_token_ns")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def extract_grpc_timings(trailing_md: dict[str, str]) -> TimingCheckpoint | None:
    """Read the ``m6_1_1_t_*`` keys from gRPC trailing metadata.

    gRPC trailing metadata values are ASCII strings; we ``int()``-parse them.
    Returns ``None`` when any of the five original four-checkpoint keys is
    missing or non-numeric — same best-effort semantics as
    :func:`extract_rest_timings`. M6.1.2 engine-internal keys default to 0
    when absent.
    """
    try:
        return TimingCheckpoint(
            handler_entry_ns=int(trailing_md["m6_1_1_t_handler_entry"]),
            pre_engine_ns=int(trailing_md["m6_1_1_t_pre_engine"]),
            first_chunk_ns=int(trailing_md["m6_1_1_t_first_chunk"]),
            terminal_emit_ns=int(trailing_md["m6_1_1_t_terminal_emit"]),
            perturbation_audit_ns=int(trailing_md["m6_1_1_t_perturbation_audit_ns"]),
            engine_arrival_ns=_opt_int(trailing_md.get("m6_1_1_t_engine_arrival_ns")),
            engine_queued_ns=_opt_int(trailing_md.get("m6_1_1_t_engine_queued_ns")),
            engine_scheduled_ns=_opt_int(trailing_md.get("m6_1_1_t_engine_scheduled_ns")),
            engine_first_token_ns=_opt_int(trailing_md.get("m6_1_1_t_engine_first_token_ns")),
            engine_last_token_ns=_opt_int(trailing_md.get("m6_1_1_t_engine_last_token_ns")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def compute_per_segment_delta(ckpt: TimingCheckpoint) -> PerSegmentDelta:
    """Pure ns→ms conversion per FR-009. Thin alias for
    :meth:`PerSegmentDelta.from_checkpoint`."""
    return PerSegmentDelta.from_checkpoint(ckpt)


def timing_checkpoint_to_payload(
    ckpt: TimingCheckpoint | None,
) -> dict[str, int] | None:
    """Convert a :class:`TimingCheckpoint` to a ``dict[str, int]`` payload.

    Used by RPC drivers to populate ``RPCResult.m6_1_1_timing_payload``
    without introducing an m6_sweep / m6_types → m6_1_1_types import
    cycle. The dict shape mirrors :class:`TimingCheckpoint`'s fields so
    re-hydration via ``TimingCheckpoint(**payload)`` is mechanical.
    """
    if ckpt is None:
        return None
    return {
        "handler_entry_ns": ckpt.handler_entry_ns,
        "pre_engine_ns": ckpt.pre_engine_ns,
        "first_chunk_ns": ckpt.first_chunk_ns,
        "terminal_emit_ns": ckpt.terminal_emit_ns,
        "perturbation_audit_ns": ckpt.perturbation_audit_ns,
        "engine_arrival_ns": ckpt.engine_arrival_ns,
        "engine_queued_ns": ckpt.engine_queued_ns,
        "engine_scheduled_ns": ckpt.engine_scheduled_ns,
        "engine_first_token_ns": ckpt.engine_first_token_ns,
        "engine_last_token_ns": ckpt.engine_last_token_ns,
    }


__all__ = [
    "compute_per_segment_delta",
    "extract_grpc_timings",
    "extract_rest_timings",
    "timing_checkpoint_to_payload",
]
