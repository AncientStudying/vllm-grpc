"""M6.2 — Phase-1 resume / checkpoint plumbing for the publish + validate sweeps.

The 2026-05-24 publish sweep died at i=39/132 (Modal preemption →
``tuned_grpc_multiplexed`` shared-channel driver swallowed the failure
signal → harness preemption-recovery never fired). The fix to recovery is
shipped separately; this module addresses the orthogonal problem: even
with recovery working, a 5h sweep that dies at hour 5 should be resumable
from where it stopped rather than re-run from scratch.

The contract:

* While the sweep runs, every successful ``BLOCK_DONE`` and every
  ``ANCHOR_END`` snapshot is appended as one JSON line to a sidecar
  checkpoint file (``<artifact>.checkpoint.jsonl`` by default). The file
  is flushed + fsynced after every write, so the on-disk state survives
  ``kill -9``, Modal worker death, network drop, etc.
* The first line of the file is a header carrying the run identity
  (git_sha, corpus SHAs, sweep_mode, axis, n_per_point, base_seed,
  model_identifier, modal_region). Resuming requires every field to match
  the current invocation — mismatch raises :class:`CheckpointMismatchError`
  with a precise diagnostic so the operator can choose to restart cleanly
  or merge manually.
* On ``--m6_2-resume <path>``, the loader returns the pre-populated
  ``measurements`` list + ``anchor_snapshots`` dict. The orchestrator
  threads them into :class:`M6_2SweepInputs`; the sweep loop skips any
  ``(cell, cohort, max_tokens)`` block already in the checkpoint and
  continues appending to the same checkpoint file. Per-RPC seed
  allocation is preserved because the dispatcher derives seeds from
  ``base_seed + len(measurements)`` (= ``iter_idx``), which the
  pre-population restores faithfully.

Out of scope for Phase 1 (handled by the docstring TODO at the bottom):

* ``--m6_2-resume-retry-failed`` — re-run blocks whose ``failed_reason``
  is set instead of treating them as completed. Phase 2.
* Preserving the original anchor cadence across the resume boundary.
  Phase 1 lets the resumed-run wall-clock anchor schedule drift relative
  to the original; documented in ``quickstart.md`` (T080).
* Checkpoint cleanup. Phase 1 leaves the JSONL on disk after a successful
  artifact write so the audit trail is intact; ``m6_2_validate`` prints
  the path so the operator can rotate / delete manually.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from vllm_grpc_bench.m6_1_2_types import M6_1_2_COHORTS, M6_1_2CohortKind
from vllm_grpc_bench.m6_2_types import (
    M6_2AnchorLatencySnapshot,
    M6_2MeasurementPoint,
    M6_2MeasurementRegime,
    M6_2PromptSource,
    M6_2SweepMode,
)

__all__ = [
    "RESUME_SCHEMA_VERSION",
    "CheckpointHeader",
    "CheckpointMismatchError",
    "append_anchor",
    "append_measurement",
    "completed_block_keys",
    "load_checkpoint",
    "validate_checkpoint_against_current_run",
    "write_checkpoint_header",
]


RESUME_SCHEMA_VERSION: str = "m6_2_resume.v1"
"""Bump when the JSONL line schema changes incompatibly. v1 = the layout
shipped on 2026-05-25: header line + per-block measurement lines + per-
anchor snapshot lines, all carrying a ``kind`` discriminator."""


@dataclass(slots=True, kw_only=True, frozen=True)
class CheckpointHeader:
    """Run-identity header pinned in the first line of the JSONL.

    Every field is part of the integrity gate: resuming requires the
    current invocation to match all of them exactly. ``run_id`` and
    ``run_started_at`` are NOT integrity-gated (they identify the
    original run; the resumed run keeps the same ``run_id`` so the
    final artifact threads through unchanged).
    """

    schema_version: str  # RESUME_SCHEMA_VERSION at write time
    run_id: str
    run_started_at: str  # ISO-8601 UTC
    sweep_mode: M6_2SweepMode
    n_per_point: int
    axis: tuple[int, ...]
    base_seed: int
    model_identifier: str
    modal_region: str
    git_sha: str
    chat_corpus_sha256: str
    embed_corpus_sha256: str


class CheckpointMismatchError(RuntimeError):
    """Raised by :func:`validate_checkpoint_against_current_run` when one
    or more integrity-gated fields differ between the checkpoint header
    and the current invocation.

    The orchestrator surfaces the message verbatim to the operator and
    exits non-zero so the operator can either (a) restart cleanly without
    ``--m6_2-resume``, or (b) re-invoke with the exact parameters the
    checkpoint expects.
    """


# --- Writers --------------------------------------------------------------


def _write_line_fsynced(path: Path, payload: dict[str, Any], *, mode: str) -> None:
    """Append one JSON line to ``path`` and fsync. ``mode`` is ``"w"`` for
    the header (truncate) or ``"a"`` for appends.

    Each call opens + closes the file rather than holding it open, so an
    orchestrator crash mid-write leaves at most one partial line at EOF
    that the loader can detect and ignore (see :func:`load_checkpoint`'s
    line-by-line ``json.loads`` with try/except)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode, encoding="utf-8") as f:
        f.write(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def write_checkpoint_header(path: Path, header: CheckpointHeader) -> None:
    """Truncate ``path`` and write the single header line.

    Called at sweep start. If a stale checkpoint file exists at ``path``
    it is discarded — the caller is expected to have already decided
    whether to resume (in which case ``write_checkpoint_header`` is NOT
    called; appends proceed against the existing file)."""
    payload: dict[str, Any] = {
        "kind": "header",
        "schema_version": header.schema_version,
        "run_id": header.run_id,
        "run_started_at": header.run_started_at,
        "sweep_mode": header.sweep_mode,
        "n_per_point": header.n_per_point,
        "axis": list(header.axis),
        "base_seed": header.base_seed,
        "model_identifier": header.model_identifier,
        "modal_region": header.modal_region,
        "git_sha": header.git_sha,
        "chat_corpus_sha256": header.chat_corpus_sha256,
        "embed_corpus_sha256": header.embed_corpus_sha256,
    }
    _write_line_fsynced(path, payload, mode="w")


def append_measurement(path: Path, measurement: M6_2MeasurementPoint) -> None:
    """Append a single ``M6_2MeasurementPoint`` JSON line + fsync.

    The serialised payload is ``dataclasses.asdict(measurement)`` plus a
    ``"kind": "measurement"`` discriminator. The loader inverts via
    ``M6_2MeasurementPoint(**payload)``."""
    payload = {"kind": "measurement", **asdict(measurement)}
    _write_line_fsynced(path, payload, mode="a")


def append_anchor(
    path: Path,
    cohort: M6_1_2CohortKind,
    snapshot: M6_2AnchorLatencySnapshot,
) -> None:
    """Append one anchor snapshot JSON line + fsync.

    Anchor snapshots are dispatched per-cohort, so the line carries the
    cohort label alongside the snapshot fields. The loader rebuilds the
    per-cohort dict structure expected by the orchestrator."""
    payload = {"kind": "anchor", "cohort": cohort, **asdict(snapshot)}
    _write_line_fsynced(path, payload, mode="a")


# --- Reader / loader -----------------------------------------------------


@dataclass(slots=True, kw_only=True)
class _LoadedCheckpoint:
    """Internal: shape returned by :func:`load_checkpoint`. Not exported;
    the public surface is the 3-tuple returned form."""

    header: CheckpointHeader
    measurements: list[M6_2MeasurementPoint]
    anchor_snapshots: dict[M6_1_2CohortKind, list[M6_2AnchorLatencySnapshot]]


def load_checkpoint(
    path: Path,
) -> tuple[
    CheckpointHeader,
    list[M6_2MeasurementPoint],
    dict[M6_1_2CohortKind, list[M6_2AnchorLatencySnapshot]],
]:
    """Read every line of ``path`` and rebuild ``(header, measurements,
    anchor_snapshots)``.

    Robustness:

    * The first non-empty line MUST be a header with ``kind=="header"``
      and matching :data:`RESUME_SCHEMA_VERSION`; otherwise raise
      :class:`CheckpointMismatchError` (the orchestrator surfaces it).
    * Partial / truncated final lines (caused by a crash mid-fsync) are
      silently dropped. ``json.JSONDecodeError`` on the tail line is
      treated as a clean EOF.
    * Unknown ``kind`` values are silently ignored (forward compat).
    """
    if not path.exists():
        raise CheckpointMismatchError(
            f"checkpoint file not found at {path!s}; cannot resume. "
            f"Re-run without --m6_2-resume to start a fresh sweep."
        )

    header: CheckpointHeader | None = None
    measurements: list[M6_2MeasurementPoint] = []
    anchor_snapshots: dict[M6_1_2CohortKind, list[M6_2AnchorLatencySnapshot]] = {}

    with open(path, encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                # Tail-line partial write from a crash; safe to drop.
                # Mid-file corruption would still parse the preceding
                # lines; trailing garbage gets skipped here.
                continue
            if not isinstance(payload, dict):
                continue
            kind = payload.get("kind")
            if kind == "header":
                header = _parse_header(payload, path=path, line_no=line_no)
            elif kind == "measurement":
                measurements.append(_parse_measurement(payload, path=path, line_no=line_no))
            elif kind == "anchor":
                cohort, snapshot = _parse_anchor(payload, path=path, line_no=line_no)
                anchor_snapshots.setdefault(cohort, []).append(snapshot)
            # Unknown kinds: silently ignore (forward compat).

    if header is None:
        raise CheckpointMismatchError(
            f"checkpoint at {path!s} is missing a header line; "
            f"file is unreadable as an M6.2 checkpoint. Re-run without "
            f"--m6_2-resume to start a fresh sweep."
        )
    return header, measurements, anchor_snapshots


def _parse_header(payload: dict[str, Any], *, path: Path, line_no: int) -> CheckpointHeader:
    """Extract a :class:`CheckpointHeader` from a parsed JSON dict and
    enforce schema-version compatibility."""
    schema = payload.get("schema_version")
    if schema != RESUME_SCHEMA_VERSION:
        raise CheckpointMismatchError(
            f"checkpoint at {path!s} line {line_no}: schema_version "
            f"{schema!r} != expected {RESUME_SCHEMA_VERSION!r}. The "
            f"checkpoint format has changed; re-run without "
            f"--m6_2-resume to start a fresh sweep."
        )
    try:
        return CheckpointHeader(
            schema_version=str(payload["schema_version"]),
            run_id=str(payload["run_id"]),
            run_started_at=str(payload["run_started_at"]),
            sweep_mode=cast(M6_2SweepMode, str(payload["sweep_mode"])),
            n_per_point=int(payload["n_per_point"]),
            axis=tuple(int(x) for x in payload["axis"]),
            base_seed=int(payload["base_seed"]),
            model_identifier=str(payload["model_identifier"]),
            modal_region=str(payload["modal_region"]),
            git_sha=str(payload["git_sha"]),
            chat_corpus_sha256=str(payload["chat_corpus_sha256"]),
            embed_corpus_sha256=str(payload["embed_corpus_sha256"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CheckpointMismatchError(
            f"checkpoint at {path!s} line {line_no}: header is malformed "
            f"({type(exc).__name__}: {exc}). Re-run without --m6_2-resume."
        ) from exc


def _parse_measurement(
    payload: dict[str, Any], *, path: Path, line_no: int
) -> M6_2MeasurementPoint:
    """Reconstruct an :class:`M6_2MeasurementPoint` from a JSON payload."""
    fields = {k: v for k, v in payload.items() if k != "kind"}
    try:
        return M6_2MeasurementPoint(
            cell_id=str(fields["cell_id"]),
            cohort=cast(M6_1_2CohortKind, str(fields["cohort"])),
            max_tokens=int(fields["max_tokens"]),
            n_rpcs=int(fields["n_rpcs"]),
            wall_p50_ms=_opt_float(fields.get("wall_p50_ms")),
            wall_p95_ms=_opt_float(fields.get("wall_p95_ms")),
            wall_p99_ms=_opt_float(fields.get("wall_p99_ms")),
            wall_p50_ms_ci_half_width=_opt_float(fields.get("wall_p50_ms_ci_half_width")),
            tpot_ms=_opt_float(fields.get("tpot_ms")),
            seg_ab_ms=_opt_float(fields.get("seg_ab_ms")),
            seg_queue_ms=_opt_float(fields.get("seg_queue_ms")),
            seg_prefill_ms=_opt_float(fields.get("seg_prefill_ms")),
            seg_ingress_ms=_opt_float(fields.get("seg_ingress_ms")),
            seg_egress_ms=_opt_float(fields.get("seg_egress_ms")),
            failed_reason=_opt_str(fields.get("failed_reason")),
            block_start_utc=str(fields["block_start_utc"]),
            block_end_utc=str(fields["block_end_utc"]),
            retry_attempted=bool(fields["retry_attempted"]),
            clock_anomaly=bool(fields["clock_anomaly"]),
            prompt_source=cast(M6_2PromptSource, str(fields["prompt_source"])),
            measurement_regime=cast(M6_2MeasurementRegime, str(fields["measurement_regime"])),
            prompt_corpus_idx=_opt_int(fields.get("prompt_corpus_idx")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CheckpointMismatchError(
            f"checkpoint at {path!s} line {line_no}: measurement is malformed "
            f"({type(exc).__name__}: {exc})."
        ) from exc


def _parse_anchor(
    payload: dict[str, Any], *, path: Path, line_no: int
) -> tuple[M6_1_2CohortKind, M6_2AnchorLatencySnapshot]:
    """Reconstruct ``(cohort, M6_2AnchorLatencySnapshot)`` from a JSON payload."""
    try:
        cohort = cast(M6_1_2CohortKind, str(payload["cohort"]))
        snapshot = M6_2AnchorLatencySnapshot(
            wall_p50_ms=float(payload["wall_p50_ms"]),
            wall_p95_ms=float(payload["wall_p95_ms"]),
            wall_p99_ms=float(payload["wall_p99_ms"]),
            snapshot_timestamp=str(payload["snapshot_timestamp"]),
            sweep_hour_mark=float(payload["sweep_hour_mark"]),
        )
        return cohort, snapshot
    except (KeyError, TypeError, ValueError) as exc:
        raise CheckpointMismatchError(
            f"checkpoint at {path!s} line {line_no}: anchor snapshot is malformed "
            f"({type(exc).__name__}: {exc})."
        ) from exc


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


# --- Integrity gate ------------------------------------------------------


def validate_checkpoint_against_current_run(
    header: CheckpointHeader,
    *,
    sweep_mode: M6_2SweepMode,
    n_per_point: int,
    axis: tuple[int, ...],
    base_seed: int,
    model_identifier: str,
    modal_region: str,
    git_sha: str,
    chat_corpus_sha256: str,
    embed_corpus_sha256: str,
) -> None:
    """Compare every integrity-gated field between the loaded
    ``header`` and the current invocation. Raise
    :class:`CheckpointMismatchError` with a multi-line diagnostic listing
    every field that diverged.

    Mismatched fields surface together (not first-error-only) so the
    operator can see the full delta at a glance and decide whether to
    re-invoke with corrected flags or restart from scratch."""
    mismatches: list[str] = []

    def _check(label: str, current: Any, checkpoint: Any) -> None:
        if current != checkpoint:
            mismatches.append(f"  - {label}: current={current!r} checkpoint={checkpoint!r}")

    _check("sweep_mode", sweep_mode, header.sweep_mode)
    _check("n_per_point", n_per_point, header.n_per_point)
    _check("axis", tuple(axis), header.axis)
    _check("base_seed", base_seed, header.base_seed)
    _check("model_identifier", model_identifier, header.model_identifier)
    _check("modal_region", modal_region, header.modal_region)
    _check("git_sha", git_sha, header.git_sha)
    _check("chat_corpus_sha256", chat_corpus_sha256, header.chat_corpus_sha256)
    _check("embed_corpus_sha256", embed_corpus_sha256, header.embed_corpus_sha256)

    if mismatches:
        joined = "\n".join(mismatches)
        raise CheckpointMismatchError(
            "M6.2 checkpoint integrity gate failed — the current invocation does not "
            "match the checkpoint that was started:\n"
            f"{joined}\n"
            "Re-invoke with the parameters the checkpoint expects, OR restart cleanly "
            "without --m6_2-resume."
        )


def completed_block_keys(
    measurements: list[M6_2MeasurementPoint],
) -> frozenset[tuple[str, M6_1_2CohortKind, int]]:
    """Build the lookup set used by the sweep loop's skip predicate.

    Phase 1: every measurement in the checkpoint (success OR failed) is
    treated as completed. Phase 2 will add ``--m6_2-resume-retry-failed``
    to selectively re-run blocks where ``failed_reason`` is set."""
    return frozenset((m.cell_id, m.cohort, m.max_tokens) for m in measurements)


def normalised_anchor_snapshots(
    snapshots: dict[M6_1_2CohortKind, list[M6_2AnchorLatencySnapshot]],
) -> dict[M6_1_2CohortKind, list[M6_2AnchorLatencySnapshot]]:
    """Return a copy of ``snapshots`` with every M6.1.2 cohort key
    present (empty list when no snapshot was captured for that cohort).

    The orchestrator's anchor-trajectory compute expects every cohort key
    to exist even when empty; pre-population from a partial checkpoint
    must preserve that shape."""
    return {cohort: list(snapshots.get(cohort, [])) for cohort in M6_1_2_COHORTS}
