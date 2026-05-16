"""M5.2 per-request labelled-events JSONL sidecar (FR-012a + research R-4).

The harness writes one event record per request to a buffered un-gzipped
file under ``bench-results/m5_2-full/{run_id}.events.jsonl``. On context
exit the writer gzips the file (mtime=0 for byte-stable output), removes
the un-gzipped intermediate, and exposes ``(gzipped_path, sha256_hex)``
via the ``.result`` property. The companion regenerator decompresses via
``gzip.open(..., "rt", encoding="utf-8")`` and streams records back.

The schema, gzip discipline, SHA-256 protocol, and filter syntax are
pinned in ``specs/019-m5-2-transport-tuning/contracts/m5_2-events-jsonl-sidecar.md``.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import os
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, fields
from pathlib import Path
from types import TracebackType
from typing import Literal

from vllm_grpc_bench.m3_types import M5_2CohortKind, NetworkPath

_BUFFER_FLUSH_EVERY = 1000


@dataclass(frozen=True)
class PerRequestEventRecord:
    """One per-request event line in the gzipped JSONL sidecar.

    Field set is fixed in M5.2 per the events-sidecar contract. The
    serializer emits keys alphabetically (``sort_keys=True``); the reader
    accepts and ignores additional fields (warning to stderr) so future
    milestones can extend the schema additively.

    M6 (T016 — FR-021/FR-025/FR-008): adds optional fields ``rpc_phase``,
    ``rpc_index``, ``seed``, engine_cost trio, ``success``,
    ``failure_reason``, ``retry_count``. M5.2-shape readers MUST keep
    working (additive only; FR-016 strict superset). All M6 fields
    default to None so M5.2 callers that don't set them are unaffected.

    M6 validation rules (per data-model.md ``M6PerRequestEvent``):
    - ``rpc_phase == "warmup"`` ⇒ ``rpc_index is None`` AND ``seed is None``
    - ``rpc_phase == "measurement"`` ⇒ both set
    - embed path ⇒ engine_ttft_ms / engine_tpot_ms None
    - chat_stream path ⇒ engine_forward_ms None
    """

    cohort: M5_2CohortKind
    path: Literal["chat_stream", "embed"]
    hidden_size: int
    concurrency: int
    network_path: NetworkPath
    request_uuid: str
    issue_ts_ms: float
    first_byte_ts_ms: float | None
    done_ts_ms: float
    rtt_at_issue_ms: float
    phase: Literal["warmup", "measurement"]
    server_bound: bool
    request_body_bytes: int
    response_body_bytes: int
    status: str
    # --- M6 additive extensions (T016) — default None for M5.2 back-compat:
    rpc_phase: Literal["warmup", "measurement"] | None = None
    rpc_index: int | None = None
    seed: int | None = None
    engine_forward_ms: float | None = None
    engine_ttft_ms: float | None = None
    engine_tpot_ms: float | None = None
    success: bool | None = None
    failure_reason: str | None = None
    retry_count: int | None = None


# M5.2-original required fields (the M6 additive fields are optional —
# T016: M5.2-shape readers MUST keep working against pre-M6 sidecars).
_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "cohort",
        "path",
        "hidden_size",
        "concurrency",
        "network_path",
        "request_uuid",
        "issue_ts_ms",
        "first_byte_ts_ms",
        "done_ts_ms",
        "rtt_at_issue_ms",
        "phase",
        "server_bound",
        "request_body_bytes",
        "response_body_bytes",
        "status",
    }
)
_ALL_FIELDS: frozenset[str] = frozenset(f.name for f in fields(PerRequestEventRecord))
_M6_OPTIONAL_FIELDS: frozenset[str] = _ALL_FIELDS - _REQUIRED_FIELDS


def serialize_record(record: PerRequestEventRecord) -> str:
    """Encode one record to a single deterministic JSON line (no trailing \\n).

    Encoding rule per the contract: ``json.dumps(record.__dict__,
    sort_keys=True, separators=(",", ":"), ensure_ascii=False)``. The caller
    appends ``\\n`` when writing to the file.
    """
    return json.dumps(
        {f.name: getattr(record, f.name) for f in fields(record)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


class EventsSidecarWriter:
    """Context-managed JSONL-append-then-gzip writer.

    Usage::

        with EventsSidecarWriter(out_dir, run_id) as writer:
            writer.write(record)
            ...
        gzipped_path, sha256_hex = writer.result

    The un-gzipped intermediate lives at ``{out_dir}/{run_id}.events.jsonl``
    during the run. On ``__exit__`` the file is flushed, closed, gzipped to
    ``{run_id}.events.jsonl.gz`` (gzip ``mtime=0`` for byte-stable bytes),
    the intermediate is removed, and the SHA-256 of the gzipped file's bytes
    is computed. The ``.result`` property exposes both.
    """

    def __init__(self, out_dir: Path, run_id: str) -> None:
        self._out_dir = Path(out_dir)
        self._run_id = run_id
        self._intermediate_path = self._out_dir / f"{run_id}.events.jsonl"
        self._gzipped_path = self._out_dir / f"{run_id}.events.jsonl.gz"
        self._fp: io.TextIOWrapper | None = None
        self._records_since_flush = 0
        self._result: tuple[Path, str] | None = None

    def __enter__(self) -> EventsSidecarWriter:
        self._out_dir.mkdir(parents=True, exist_ok=True)
        # Truncate any stale intermediate from a previous crashed run.
        self._fp = self._intermediate_path.open("w", encoding="utf-8")
        return self

    def write(self, record: PerRequestEventRecord) -> None:
        if self._fp is None:
            raise RuntimeError("EventsSidecarWriter.write called outside context")
        self._fp.write(serialize_record(record))
        self._fp.write("\n")
        self._records_since_flush += 1
        if self._records_since_flush >= _BUFFER_FLUSH_EVERY:
            self._fp.flush()
            self._records_since_flush = 0

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fp is not None:
            self._fp.flush()
            self._fp.close()
            self._fp = None
        # Gzip with mtime=0 for deterministic output. GzipFile only closes
        # ``fileobj`` if it opened the file itself; pass an explicitly
        # context-managed handle so the disk fd is released cleanly.
        with (
            open(self._intermediate_path, "rb") as raw,
            open(self._gzipped_path, "wb") as raw_out,
            gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=raw_out,
                mtime=0,
            ) as gz,
        ):
            while True:
                chunk = raw.read(65536)
                if not chunk:
                    break
                gz.write(chunk)
        # Remove the un-gzipped intermediate so it never gets committed.
        with contextlib.suppress(OSError):
            os.remove(self._intermediate_path)
        sha = hashlib.sha256(self._gzipped_path.read_bytes()).hexdigest()
        self._result = (self._gzipped_path, sha)

    @property
    def result(self) -> tuple[Path, str]:
        if self._result is None:
            raise RuntimeError("EventsSidecarWriter.result accessed before context exit")
        return self._result


def _coerce_record_dict(raw: dict[str, object]) -> PerRequestEventRecord | None:
    """Build a PerRequestEventRecord from a dict, warning on unknown fields
    and returning None on missing required fields (the reader skips bad
    records and warns via stderr rather than raising).
    """
    missing = _REQUIRED_FIELDS - raw.keys()
    if missing:
        print(
            f"m5_2_events: skipping record missing required fields: {sorted(missing)}",
            file=sys.stderr,
        )
        return None
    # Unknown = not in REQUIRED nor in M6 optional fields. M5.2-shape records
    # without the M6 optional fields are still accepted unchanged.
    extra = raw.keys() - _ALL_FIELDS
    if extra:
        print(
            f"m5_2_events: record has unknown additional fields (ignored): {sorted(extra)}",
            file=sys.stderr,
        )

    def _opt_float(key: str) -> float | None:
        v = raw.get(key)
        return None if v is None else float(v)  # type: ignore[arg-type]

    def _opt_int(key: str) -> int | None:
        v = raw.get(key)
        return None if v is None else int(v)  # type: ignore[call-overload]

    def _opt_str(key: str) -> str | None:
        v = raw.get(key)
        return None if v is None else str(v)

    try:
        return PerRequestEventRecord(
            cohort=raw["cohort"],  # type: ignore[arg-type]
            path=raw["path"],  # type: ignore[arg-type]
            hidden_size=int(raw["hidden_size"]),  # type: ignore[call-overload]
            concurrency=int(raw["concurrency"]),  # type: ignore[call-overload]
            network_path=raw["network_path"],  # type: ignore[arg-type]
            request_uuid=str(raw["request_uuid"]),
            issue_ts_ms=float(raw["issue_ts_ms"]),  # type: ignore[arg-type]
            first_byte_ts_ms=(
                None if raw["first_byte_ts_ms"] is None else float(raw["first_byte_ts_ms"])  # type: ignore[arg-type]
            ),
            done_ts_ms=float(raw["done_ts_ms"]),  # type: ignore[arg-type]
            rtt_at_issue_ms=float(raw["rtt_at_issue_ms"]),  # type: ignore[arg-type]
            phase=raw["phase"],  # type: ignore[arg-type]
            server_bound=bool(raw["server_bound"]),
            request_body_bytes=int(raw["request_body_bytes"]),  # type: ignore[call-overload]
            response_body_bytes=int(raw["response_body_bytes"]),  # type: ignore[call-overload]
            status=str(raw["status"]),
            rpc_phase=raw.get("rpc_phase"),  # type: ignore[arg-type]
            rpc_index=_opt_int("rpc_index"),
            seed=_opt_int("seed"),
            engine_forward_ms=_opt_float("engine_forward_ms"),
            engine_ttft_ms=_opt_float("engine_ttft_ms"),
            engine_tpot_ms=_opt_float("engine_tpot_ms"),
            success=(None if raw.get("success") is None else bool(raw["success"])),
            failure_reason=_opt_str("failure_reason"),
            retry_count=_opt_int("retry_count"),
        )
    except (TypeError, ValueError) as exc:
        print(
            f"m5_2_events: skipping record with malformed field: {exc}",
            file=sys.stderr,
        )
        return None


def read_sidecar_iter(path: Path) -> Iterator[PerRequestEventRecord]:
    """Stream PerRequestEventRecord instances from a gzipped sidecar.

    On a JSON decode error or a missing required field: warns via stderr
    and skips the record (the writer flushes every N records, so a
    SIGKILL'd run leaves a partial trailing record which the reader
    silently drops).
    """
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.rstrip("\n")
            if not stripped.strip():
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:
                print(
                    f"m5_2_events: skipping record with JSON decode error: {exc}",
                    file=sys.stderr,
                )
                continue
            if not isinstance(raw, dict):
                print(
                    f"m5_2_events: skipping non-object JSON line: {type(raw).__name__}",
                    file=sys.stderr,
                )
                continue
            record = _coerce_record_dict(raw)
            if record is not None:
                yield record


# ---------------------------------------------------------------------------
# Section-header filter syntax for FR-012b field provenance.
#
# A filter expression is a conjunction of clauses separated by ``AND``. Each
# clause is one of:
#   - ``key=value``    — exact match on a single value.
#   - ``key IN {a,b,c}`` — match against an explicit set.
# Whitespace around the AND / = / IN / commas is ignored. Values are matched
# stringwise (after str()) for forward-compat with future int / bool fields.
# ---------------------------------------------------------------------------


_FILTER_AND = re.compile(r"\s+AND\s+", re.IGNORECASE)
_FILTER_IN = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+IN\s*\{([^{}]*)\}\s*$", re.IGNORECASE)
_FILTER_EQ = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.+?)\s*$")


def _parse_clause(clause: str) -> tuple[str, set[str]]:
    """Parse one clause into ``(field_name, accepted_string_values)``."""
    m_in = _FILTER_IN.match(clause)
    if m_in:
        key = m_in.group(1).strip()
        values_part = m_in.group(2).strip()
        values = {v.strip() for v in values_part.split(",") if v.strip()}
        if not values:
            raise ValueError(f"m5_2_events filter: empty IN-set in clause {clause!r}")
        return key, values
    m_eq = _FILTER_EQ.match(clause)
    if m_eq:
        key = m_eq.group(1).strip()
        value = m_eq.group(2).strip()
        return key, {value}
    raise ValueError(
        f"m5_2_events filter: cannot parse clause {clause!r}; expected "
        f"'key=value' or 'key IN {{a,b,c}}'"
    )


def apply_filter(
    records: Iterable[PerRequestEventRecord], filter_str: str
) -> Iterator[PerRequestEventRecord]:
    """Stream records matching the section-header filter expression.

    Empty filter string yields every record. Invalid filter expressions
    raise ``ValueError`` — the caller (regenerator or markdown writer) is
    expected to validate filter expressions at template-write time.
    """
    if not filter_str.strip():
        yield from records
        return
    clauses_raw = _FILTER_AND.split(filter_str)
    clauses = [_parse_clause(c) for c in clauses_raw if c.strip()]
    for r in records:
        match = True
        for key, accepted in clauses:
            value = getattr(r, key, None)
            if value is None or str(value) not in accepted:
                match = False
                break
        if match:
            yield r
