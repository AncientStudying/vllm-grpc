"""Generate the M4 'Supersedes M3' table from M3's published time report.

Reads ``docs/benchmarks/m3-channel-tuning-time.json`` (or any path passed
to :func:`build_supersession_entries`) and emits one
:class:`vllm_grpc_bench.m3_types.SupersessionEntry` per M3 cell whose
recommendation verdict is ``noise_bounded``. The M4-side cell is matched on
``(path, hidden_size, axis, config_name)`` against the supplied list of
M4-cell descriptors.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m3_types import SupersessionEntry


def _normalize_axis(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def build_supersession_entries(
    m3_time_json_path: str | Path,
    m4_cells: Iterable[dict[str, Any]],
    *,
    m4_pacing_mode: str = "no_pacing",
) -> list[SupersessionEntry]:
    """Produce supersession entries for M3 ``noise_bounded`` recommendations.

    ``m4_cells`` is an iterable of dicts at minimum carrying
    ``cell_id``, ``path``, ``hidden_size``, ``config_axis``,
    ``config_name``, and ``verdict``. ``m4_pacing_mode`` describes the M4 run
    that produced the cells (used in the rationale string). The function
    returns one entry per matched pair; M3 noise_bounded recommendations with
    no M4 match are skipped (the harness should never emit such — the sweep
    covers every M3 cell — but skipping prevents the supersession table from
    being spuriously incomplete during partial M4 runs).
    """
    m3_path = Path(m3_time_json_path)
    if not m3_path.exists():
        return []
    payload = json.loads(m3_path.read_text())
    recs = payload.get("recommendations", []) or []
    pacing_phrase = "no-pacing" if m4_pacing_mode == "no_pacing" else "paced"

    m4_index: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for cell in m4_cells:
        key = (
            str(cell["path"]),
            int(cell["hidden_size"]),
            str(cell.get("config_axis", "")),
            str(cell.get("config_name", "")),
        )
        m4_index[key] = cell

    entries: list[SupersessionEntry] = []
    for rec in recs:
        if rec.get("verdict") != "noise_bounded":
            continue
        axis = _normalize_axis(rec.get("axis"))
        path = str(rec.get("applies_to_path", ""))
        widths = rec.get("applies_to_widths") or []
        winning_config = rec.get("winning_config") or "m1-baseline"
        for w in widths:
            try:
                width = int(w)
            except (TypeError, ValueError):
                continue
            key = (path, width, axis or "", str(winning_config))
            m4_cell = m4_index.get(key)
            if m4_cell is None:
                # Try matching by axis only when config_name didn't carry over.
                for stored_key, stored_cell in m4_index.items():
                    if (
                        stored_key[0] == path
                        and stored_key[1] == width
                        and stored_key[2] == (axis or "")
                    ):
                        m4_cell = stored_cell
                        break
            if m4_cell is None:
                continue
            m4_verdict = m4_cell.get("verdict", "no_winner")
            if m4_verdict == "noise_bounded":
                # FR-007 invariant; refuse to emit.
                continue
            m3_cell_id = f"{path}|h{width}|{axis or 'unknown'}|{winning_config}"
            rationale = (
                f"M4 re-measurement under shared baseline + {pacing_phrase} "
                f"produced {m4_verdict} for ({path}, h{width}, {axis})."
            )
            entries.append(
                SupersessionEntry(
                    m3_cell_id=m3_cell_id,
                    m3_verdict="noise_bounded",
                    m4_cell_id=str(m4_cell["cell_id"]),
                    m4_verdict=m4_verdict,
                    rationale=rationale,
                )
            )
    return entries
