"""M6.1.1 — FR-016 contracts heading validator (round-3 Q2).

Phase 2(b) (``channel_dependent_batching`` outcome) gates milestone closure
on the operator updating ``contracts/instrumentation.md`` with an
``m6_1_1``-keyed h2 heading capturing the per-cohort batching
interpretation. This validator scans the file for a line matching
``^## M6.1.1: `` and returns the matched line + path for the published
report's audit trail.

A miss → ``None`` → caller emits exit code 1 with stderr telling the
operator to add the heading.
"""

from __future__ import annotations

import re
from pathlib import Path

_HEADING_PATTERN = re.compile(r"^## M6\.1\.1: ")


def validate_contracts_heading(
    path: str | Path = "contracts/instrumentation.md",
) -> tuple[str, str] | None:
    """Search ``path`` line-by-line for a heading matching ``^## M6.1.1: ``.

    Returns ``(matched_line_verbatim, str(path))`` on first match. The line
    is stripped of its trailing newline but preserved otherwise. Returns
    ``None`` if the file is missing or no matching line exists.

    The h2 level matters: ``### M6.1.1: ...`` (h3) does not match — the
    contract reserves the top-level structure key for milestone-scoped
    findings.
    """
    p = Path(path)
    if not p.is_file():
        return None
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            if _HEADING_PATTERN.match(line):
                return (line.rstrip("\n"), str(p))
    return None


__all__ = ["validate_contracts_heading"]
