"""M6.1.1 — FR-023 / FR-024 / FR-015c supersedence annotation writers.

M6.1.1's PR adds three additive annotations to M6.1's published artifacts:

* **JSON (FR-023)**: a top-level ``methodology_supersedence`` key on
  ``m6_1-real-prompt-embeds.json``. All other M6.1 keys are byte-stable —
  re-loading the JSON produces a dict that equals the pre-annotation dict
  except for the single new top-level key.
* **Markdown (FR-024)**: a one-line forward pointer inserted in M6.1's
  chat_stream verdict section, immediately under the existing heading.
* **Per-row notes (FR-015c)**: when ``phase_2_choice.embed_regression_acknowledged``
  is True, the affected (embed cell × cohort) rows of M6.1's
  ``supersedes_m6_under_enable_prompt_embeds`` table get inline notes.

All three writers are idempotent: re-applying produces the same result
(overwrites the existing annotation rather than duplicating).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Heading pattern in M6.1's markdown identifying the chat_stream verdict
# section. We try a few candidate headings in order of specificity — first
# match wins.
_CHAT_STREAM_VERDICT_HEADING_CANDIDATES: tuple[str, ...] = (
    "## chat_stream verdict",
    "## Chat Stream Verdict",
    "## Supersedes M6 under enable_prompt_embeds",
    "## supersedes_m6_under_enable_prompt_embeds",
)

_SUPERSEDENCE_MARKDOWN_LINE_PATTERN = re.compile(
    r"^> \*\*Methodology supersedence \(\d{4}-\d{2}-\d{2}\)\*\*:.*$",
    re.MULTILINE,
)


def write_methodology_supersedence_json(
    m6_1_path: str | Path,
    m6_1_1_report_path: str,
    phase_2_path: str,
    summary: str,
    schema_version: str = "m6_1_1.v1",
) -> None:
    """Write an additive ``methodology_supersedence`` top-level key to M6.1's JSON.

    Idempotent: if the key already exists it is overwritten, not duplicated.
    All other top-level keys are preserved byte-stable (insertion order,
    value bytes — tested by ``test_m6_1_1_supersedence`` for byte stability
    on every original key).
    """
    p = Path(m6_1_path)
    data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    data["methodology_supersedence"] = {
        "pointer": m6_1_1_report_path,
        "schema_version": schema_version,
        "phase_2_path": phase_2_path,
        "summary": summary,
    }
    # Match M6.1's existing JSON serialisation conventions (2-space indent,
    # trailing newline). M6.1 was written with `json.dumps(..., indent=2)`
    # which produces no trailing newline; we add one to mirror the existing
    # file's structure (most editors append one).
    serialised = json.dumps(data, indent=2, ensure_ascii=False)
    p.write_text(serialised + "\n", encoding="utf-8")


def write_methodology_supersedence_markdown(
    m6_1_md_path: str | Path,
    m6_1_1_md_path: str,
    date_yyyy_mm_dd: str,
) -> None:
    """Insert a one-line forward pointer below M6.1's chat_stream verdict heading.

    Idempotent: replaces an existing pointer line in-place; if no existing
    pointer line, inserts one immediately under the matched heading. If no
    heading matches, raises ``ValueError`` — the caller is expected to fix
    M6.1's markdown before re-invoking (this should never happen in
    practice — M6.1's verdict section is required by its own spec).
    """
    p = Path(m6_1_md_path)
    body = p.read_text(encoding="utf-8")
    new_line = (
        f"> **Methodology supersedence ({date_yyyy_mm_dd})**: "
        f"see `{m6_1_1_md_path}` for the diagnosis and resolution of the "
        "`engine_cost_drift_warning` reported on these chat_stream cells."
    )

    existing_match = _SUPERSEDENCE_MARKDOWN_LINE_PATTERN.search(body)
    if existing_match:
        body = _SUPERSEDENCE_MARKDOWN_LINE_PATTERN.sub(new_line, body, count=1)
        p.write_text(body, encoding="utf-8")
        return

    for heading in _CHAT_STREAM_VERDICT_HEADING_CANDIDATES:
        idx = body.find(heading + "\n")
        if idx == -1:
            continue
        insert_at = idx + len(heading) + 1
        new_body = body[:insert_at] + "\n" + new_line + "\n" + body[insert_at:]
        p.write_text(new_body, encoding="utf-8")
        return

    raise ValueError(
        f"could not locate a chat_stream verdict heading in {p}; "
        f"tried: {_CHAT_STREAM_VERDICT_HEADING_CANDIDATES!r}"
    )


def write_per_row_supersedence_notes(
    m6_1_md_path: str | Path,
    affected_rows: list[tuple[str, str]],
    m6_1_1_baseline_section_anchor: str,
    delta_pct_per_row: dict[tuple[str, str], float] | None = None,
) -> None:
    """Append per-row supersedence notes to M6.1's `supersedes_m6_under_enable_prompt_embeds` table.

    ``affected_rows`` is a list of ``(cell_str, cohort)`` tuples. For each,
    we find the table row whose first column contains ``cell_str`` and
    whose cohort cell matches ``cohort``, and append a final-column note.

    Idempotent: if the row already carries an
    ``embed_regression_acknowledged`` note, replace it rather than appending
    a duplicate.
    """
    p = Path(m6_1_md_path)
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    delta_pct_per_row = delta_pct_per_row or {}

    affected_set = set(affected_rows)
    new_lines: list[str] = []
    for line in lines:
        if not line.startswith("|") or "embed" not in line:
            new_lines.append(line)
            continue
        # Skip header / separator
        if "---" in line or "cohort" in line.lower() and "cell" in line.lower():
            new_lines.append(line)
            continue
        # Find which affected row (if any) this line corresponds to.
        matched_key: tuple[str, str] | None = None
        for cell_str, cohort in affected_set:
            if cell_str in line and cohort in line:
                matched_key = (cell_str, cohort)
                break
        if matched_key is None:
            new_lines.append(line)
            continue

        delta_pct = delta_pct_per_row.get(matched_key, 0.0)
        note = (
            f"⚠ embed_regression_acknowledged: post-symmetrisation mean shifted "
            f"{delta_pct:+.0%} (see {m6_1_1_baseline_section_anchor})"
        )
        # Remove any existing acknowledged note on the same row to keep
        # idempotency.
        cleaned = re.sub(
            r"⚠ embed_regression_acknowledged:[^|]*",
            "",
            line.rstrip("\n"),
        ).rstrip()
        if cleaned.endswith("|"):
            new_lines.append(f"{cleaned} {note} |\n")
        else:
            new_lines.append(f"{cleaned} | {note} |\n")
    p.write_text("".join(new_lines), encoding="utf-8")


__all__ = [
    "write_methodology_supersedence_json",
    "write_methodology_supersedence_markdown",
    "write_per_row_supersedence_notes",
]
