"""M6.1.2 — Methodology Discipline: report writer.

Produces the per-sweep JSON + markdown artifact at the canonical paths
(``docs/benchmarks/m6_1_2-methodology-discipline.{md,json}`` per FR-029)
or wherever ``--m6_1_2-report-out`` / ``--m6_1_2-report-json-out`` point.

Strict-superset over M6.1.1's manifest shape (FR-004 + FR-016): every
M6.1.1-known top-level key is preserved verbatim and three NEW top-level
keys are added — ``network_paths`` (per-cohort topology evidence),
``cohort_set`` (cohorts that actually ran, alphabetically sorted),
``cohort_omissions`` (design-intentional omissions, optional). The
``run_meta.sweep_mode`` nested key records ``"full"`` vs ``"validate"``
operator-intent per ``contracts/cli.md`` Dispatch wiring.

The FR-016 invariant (``cohort_set ∪ cohort_omissions = canonical universe;
∩ = ∅``) is enforced PRE-WRITE — invalid pairs raise ``ValueError`` before
the JSON is emitted.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2CohortKind,
    M6_1_2CohortOmissions,
    M6_1_2NetworkPath,
    M6_1_2NetworkPathError,
    M6_1_2SweepMode,
    build_cohort_set_and_omissions,
)


@dataclass(frozen=True)
class M6_1_2CellMeasurement:
    """Per-(cell, cohort) measurement summary written into the artifact."""

    path: str  # "embed" | "chat_stream"
    concurrency: int
    cohort: M6_1_2CohortKind
    n_attempts: int
    n_successes: int
    wall_clock_ms_mean: float | None
    engine_ttft_ms_mean: float | None


@dataclass(frozen=True)
class M6_1_2RunMeta:
    """Per-sweep run metadata (subset of M6.1.1's RunMeta + sweep_mode)."""

    git_sha: str
    modal_region: str
    base_seed: int
    model_identifier: str
    sweep_mode: M6_1_2SweepMode
    seq_len: int
    run_started_at: str
    run_completed_at: str
    m6_1_1_baseline_pointer: str


@dataclass(frozen=True)
class M6_1_2SweepArtifact:
    """The full M6.1.2 artifact payload handed to the reporter."""

    schema_version: str
    dispatch_mode: str
    run_id: str
    run_started_at: str
    run_completed_at: str
    run_meta: M6_1_2RunMeta
    network_paths: dict[M6_1_2CohortKind, M6_1_2NetworkPath | M6_1_2NetworkPathError]
    cohort_set: list[M6_1_2CohortKind]
    cohort_omissions: M6_1_2CohortOmissions | None
    measurements: list[M6_1_2CellMeasurement]
    classifier_notes: list[str] = field(default_factory=list)


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert non-JSON-serialisable values to JSON-safe shapes.

    Mirrors ``m6_1_1_reporter._sanitize_for_json``: tuple keys collapse to
    ``"part0|part1|..."``; dataclass instances are converted via
    ``dataclasses.asdict``.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _sanitize_for_json(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            key = "|".join(str(part) for part in k) if isinstance(k, tuple) else k
            out[key] = _sanitize_for_json(v)
        return out
    if isinstance(obj, list):
        return [_sanitize_for_json(item) for item in obj]
    return obj


def _network_path_to_dict(
    entry: M6_1_2NetworkPath | M6_1_2NetworkPathError,
) -> dict[str, Any]:
    """Convert a network-path entry to its wire-shape dict.

    The error and success shapes are discriminated by the presence of the
    ``error`` key per ``contracts/network-paths.md``.
    """
    return _sanitize_for_json(entry)  # type: ignore[no-any-return]


def render_json(artifact: M6_1_2SweepArtifact) -> dict[str, Any]:
    """Render the M6.1.2 artifact dict ready for ``json.dumps``.

    Performs the FR-016 pre-write invariant check by re-invoking
    :func:`build_cohort_set_and_omissions` on the artifact's
    ``cohort_set`` + ``cohort_omissions`` — raises ``ValueError`` if the
    pair is malformed.
    """
    # FR-016 invariant guard (pre-write).
    build_cohort_set_and_omissions(set(artifact.cohort_set), artifact.cohort_omissions)

    payload: dict[str, Any] = {
        "schema_version": artifact.schema_version,
        "dispatch_mode": artifact.dispatch_mode,
        "run_id": artifact.run_id,
        "run_started_at": artifact.run_started_at,
        "run_completed_at": artifact.run_completed_at,
        "run_meta": _sanitize_for_json(artifact.run_meta),
        "measurements": [_sanitize_for_json(m) for m in artifact.measurements],
        "classifier_notes": list(artifact.classifier_notes),
        # === M6.1.2 NEW top-level keys (strict-superset addition) ===
        "network_paths": {
            cohort: _network_path_to_dict(entry) for cohort, entry in artifact.network_paths.items()
        },
        "cohort_set": list(artifact.cohort_set),
    }
    if artifact.cohort_omissions:
        payload["cohort_omissions"] = dict(artifact.cohort_omissions)
    return payload


def render_markdown(artifact: M6_1_2SweepArtifact) -> str:
    """Render a human-readable markdown companion.

    Includes a "Network paths" section citing the ``network_paths`` block
    and a per-cell table summarising measurements per cohort. Companion to
    the JSON; the JSON is authoritative for downstream readers.
    """
    lines: list[str] = []
    lines.append("# M6.1.2 — Methodology Discipline")
    lines.append("")
    lines.append(f"- run_id: `{artifact.run_id}`")
    lines.append(f"- sweep_mode: `{artifact.run_meta.sweep_mode}`")
    lines.append(f"- modal_region: `{artifact.run_meta.modal_region}`")
    lines.append(f"- model: `{artifact.run_meta.model_identifier}`")
    lines.append(f"- base_seed: `{artifact.run_meta.base_seed}`")
    lines.append(f"- run_started_at: `{artifact.run_started_at}`")
    lines.append(f"- run_completed_at: `{artifact.run_completed_at}`")
    lines.append("")
    lines.append("## Cohort set")
    lines.append("")
    for c in artifact.cohort_set:
        lines.append(f"- `{c}`")
    if artifact.cohort_omissions:
        lines.append("")
        lines.append("### Intentional omissions")
        lines.append("")
        for cohort, reason in sorted(artifact.cohort_omissions.items()):
            lines.append(f"- `{cohort}` — {reason}")
    lines.append("")
    lines.append("## Network paths")
    lines.append("")
    lines.append(
        "Per-sweep topology evidence captured via `tcptraceroute`. See "
        "[`contracts/network-paths.md`](../../specs/025-m6-1-2-methodology-discipline/"
        "contracts/network-paths.md) for the wire shape."
    )
    lines.append("")
    lines.append("| cohort | cloud_provider | region | endpoint_ip | probe_status |")
    lines.append("|--------|----------------|--------|-------------|--------------|")
    for cohort, entry in artifact.network_paths.items():
        if isinstance(entry, M6_1_2NetworkPath):
            lines.append(
                f"| `{cohort}` | {entry.cloud_provider} | "
                f"{entry.region or '—'} | `{entry.endpoint_ip}` | ok |"
            )
        else:
            lines.append(f"| `{cohort}` | — | — | — | error: `{entry.error}` |")
    lines.append("")
    lines.append("## Per-cell measurements")
    lines.append("")
    lines.append(
        "| path | concurrency | cohort | n_succ/n_att | wall_clock_ms_mean | engine_ttft_ms_mean |"
    )
    lines.append(
        "|------|-------------|--------|--------------|--------------------|---------------------|"
    )
    for m in artifact.measurements:
        wall = f"{m.wall_clock_ms_mean:.2f}" if m.wall_clock_ms_mean is not None else "—"
        ttft = f"{m.engine_ttft_ms_mean:.2f}" if m.engine_ttft_ms_mean is not None else "—"
        lines.append(
            f"| {m.path} | {m.concurrency} | `{m.cohort}` | "
            f"{m.n_successes}/{m.n_attempts} | {wall} | {ttft} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def write_m6_1_2_report(
    artifact: M6_1_2SweepArtifact,
    md_path: Path,
    json_path: Path,
) -> None:
    """Write the markdown report + JSON companion atomically.

    Both files are overwritten on each invocation. The FR-016 invariant
    check fires inside :func:`render_json` BEFORE either file is written —
    if the invariant is violated, ``ValueError`` is raised and no partial
    artifact lands on disk.
    """
    payload = render_json(artifact)  # validates first
    md = render_markdown(artifact)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "M6_1_2CellMeasurement",
    "M6_1_2RunMeta",
    "M6_1_2SweepArtifact",
    "render_json",
    "render_markdown",
    "write_m6_1_2_report",
]
