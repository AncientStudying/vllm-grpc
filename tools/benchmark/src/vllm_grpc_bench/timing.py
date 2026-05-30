"""Timing extraction/segmentation helpers (v0.0.1 generic home).

De-prefixed surface of the former ``m6_1_1_timing`` / ``m6_1_1_types`` timing
API. The definitions were hoisted in-place at Phase 4 (T020); this module no
longer imports from any milestone-prefixed source.

Two extractors share a single ``TimingCheckpoint`` output shape:

* :func:`extract_rest_timings` reads the ``m6_1_1_timings`` sub-object on a
  REST terminal SSE event JSON payload (chat_stream) or on the embed
  JSONResponse body.
* :func:`extract_grpc_timings` reads the ``m6_1_1_t_*`` prefixed
  trailing-metadata keys from a gRPC response.

Both extractors are **best-effort**: they return ``None`` when the
instrumentation isn't present on the wire.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TimingCheckpoint:
    """Per-RPC timing checkpoints captured server-side and emitted on the wire.

    The original four-checkpoint scheme uses ``time.perf_counter_ns()`` for
    ``handler_entry_ns``, ``pre_engine_ns``, ``first_chunk_ns``,
    ``terminal_emit_ns`` (single monotonic clock; subtractable directly). The
    five engine-internal timestamps are pulled from vLLM's
    ``RequestStateStats``; the four ``_ts``-suffixed fields are on vLLM's
    engine-core monotonic clock (subtractable among themselves but NOT against
    the ``perf_counter_ns()`` checkpoints).
    """

    handler_entry_ns: int
    pre_engine_ns: int
    first_chunk_ns: int
    terminal_emit_ns: int
    perturbation_audit_ns: int
    engine_arrival_ns: int = 0
    engine_queued_ns: int = 0
    engine_scheduled_ns: int = 0
    engine_first_token_ns: int = 0
    engine_last_token_ns: int = 0
    pre_engine_wall_ns: int | None = None
    first_chunk_mono_ns: int | None = None
    tokenized_prompt_length: int | None = None
    tokenized_prompt_hash: str | None = None

    @property
    def has_engine_stats(self) -> bool:
        """True iff all four engine-core monotonic timestamps are populated.

        ``engine_arrival_ns`` is excluded because it's on a different clock
        and is informational only.
        """
        return (
            self.engine_queued_ns > 0
            and self.engine_scheduled_ns > 0
            and self.engine_first_token_ns > 0
            and self.engine_last_token_ns > 0
        )

    @property
    def has_proxy_edge_probes(self) -> bool:
        """True iff both proxy-edge anchors are populated (FR-005)."""
        return self.pre_engine_wall_ns is not None and self.first_chunk_mono_ns is not None


@dataclass(frozen=True)
class PerSegmentDelta:
    """Per-RPC durations derived from the timing checkpoints (FR-009).

    The original three segments (``seg_ab``, ``seg_bc``, ``seg_cd``) come from
    the ``perf_counter_ns()`` checkpoints. The two engine-internal segments
    (``seg_queue``, ``seg_prefill``) come from vLLM's engine-core monotonic
    timestamps; they are ``None`` when ``ckpt.has_engine_stats`` is False.
    """

    seg_ab_ms: float
    seg_bc_ms: float
    seg_cd_ms: float
    seg_queue_ms: float | None = None
    seg_prefill_ms: float | None = None

    @classmethod
    def from_checkpoint(cls, ckpt: TimingCheckpoint) -> PerSegmentDelta:
        seg_queue_ms: float | None = None
        seg_prefill_ms: float | None = None
        if ckpt.has_engine_stats:
            seg_queue_ms = (ckpt.engine_scheduled_ns - ckpt.engine_queued_ns) * 1e-6
            seg_prefill_ms = (ckpt.engine_first_token_ns - ckpt.engine_scheduled_ns) * 1e-6
        return cls(
            seg_ab_ms=(ckpt.pre_engine_ns - ckpt.handler_entry_ns) * 1e-6,
            seg_bc_ms=(ckpt.first_chunk_ns - ckpt.pre_engine_ns) * 1e-6,
            seg_cd_ms=(ckpt.terminal_emit_ns - ckpt.first_chunk_ns) * 1e-6,
            seg_queue_ms=seg_queue_ms,
            seg_prefill_ms=seg_prefill_ms,
        )


def _opt_int(value: Any) -> int:
    """Coerce a value to int, returning 0 on missing/invalid input."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _opt_int_or_none(md: dict[str, Any], key: str) -> int | None:
    """Returns ``None`` on missing/invalid input (distinguishes absent from zero)."""
    value = md.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_str_or_none(md: dict[str, Any], key: str) -> str | None:
    """Returns ``None`` on missing input (for the tokenized-prompt-hash wire key)."""
    value = md.get(key)
    if value is None:
        return None
    return str(value)


def extract_rest_timings(sse_terminal_event: dict[str, Any]) -> TimingCheckpoint | None:
    """Read the ``m6_1_1_timings`` sub-object from a REST terminal payload.

    Returns ``None`` when the sub-object is absent or any of the five original
    four-checkpoint fields is missing/non-integer (partial extraction is a miss
    so the classifier never sees half-populated timings). Engine-internal
    fields are best-effort (default 0; ``ckpt.has_engine_stats`` False).
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
            pre_engine_wall_ns=_opt_int_or_none(sub, "pre_engine_wall_ns"),
            first_chunk_mono_ns=_opt_int_or_none(sub, "first_chunk_mono_ns"),
            tokenized_prompt_length=_opt_int_or_none(sub, "tokenized_prompt_length"),
            tokenized_prompt_hash=_opt_str_or_none(sub, "tokenized_prompt_hash"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def extract_grpc_timings(trailing_md: dict[str, str]) -> TimingCheckpoint | None:
    """Read the ``m6_1_1_t_*`` keys from gRPC trailing metadata.

    Values are ASCII strings; we ``int()``-parse them. Returns ``None`` when
    any of the five original four-checkpoint keys is missing/non-numeric.
    Engine-internal keys default to 0 when absent.
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
            pre_engine_wall_ns=_opt_int_or_none(trailing_md, "m6_1_1_t_pre_engine_wall_ns"),
            first_chunk_mono_ns=_opt_int_or_none(trailing_md, "m6_1_1_t_first_chunk_mono_ns"),
            tokenized_prompt_length=_opt_int_or_none(trailing_md, "m6_1_3_tokenized_prompt_length"),
            tokenized_prompt_hash=_opt_str_or_none(trailing_md, "m6_1_3_tokenized_prompt_hash"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def compute_per_segment_delta(ckpt: TimingCheckpoint) -> PerSegmentDelta:
    """Pure ns→ms conversion per FR-009. Thin alias for
    :meth:`PerSegmentDelta.from_checkpoint`."""
    return PerSegmentDelta.from_checkpoint(ckpt)


def timing_checkpoint_to_payload(
    ckpt: TimingCheckpoint | None,
) -> dict[str, int | str | None] | None:
    """Convert a :class:`TimingCheckpoint` to a payload dict.

    Used by RPC drivers to populate ``RPCResult.m6_1_1_timing_payload`` without
    introducing a timing-types import cycle. The dict shape mirrors
    :class:`TimingCheckpoint`'s fields so re-hydration via
    ``TimingCheckpoint(**payload)`` is mechanical.
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
        "pre_engine_wall_ns": ckpt.pre_engine_wall_ns,
        "first_chunk_mono_ns": ckpt.first_chunk_mono_ns,
        "tokenized_prompt_length": ckpt.tokenized_prompt_length,
        "tokenized_prompt_hash": ckpt.tokenized_prompt_hash,
    }


__all__ = [
    "PerSegmentDelta",
    "TimingCheckpoint",
    "compute_per_segment_delta",
    "extract_grpc_timings",
    "extract_rest_timings",
    "timing_checkpoint_to_payload",
]
