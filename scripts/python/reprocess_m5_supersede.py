#!/usr/bin/env python3
"""Reprocess ``docs/benchmarks/m5-cross-host-validation.{md,json}`` after a
classifier refinement, without re-running the Modal sweep.

This script is the path to reclassify an existing M5 run when only the
``_classify_expected`` logic (or another pure-postprocess step) changes.
It loads the published M5 JSON, rebuilds ``supersedes_m4[]`` via the current
classifier, and rewrites both the JSON and the Markdown "Supersedes M4"
section in place. Cohort timings, RTT distribution, verdict literals,
recommendations — **none of these change**. Only the ``expected_class``
labels and the Markdown's grouping move.

Usage:

    uv run python scripts/python/reprocess_m5_supersede.py

The script reads ``docs/benchmarks/m5-cross-host-validation.json`` and
writes both ``m5-cross-host-validation.json`` and ``.md`` back in place.
Pass ``--m5-json``/``--m4-json``/``--md`` to override the default paths.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Make the workspace's tools/benchmark package importable so the script is
# runnable without a prior ``pip install`` (e.g., directly under ``uv run``).
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "tools" / "benchmark" / "src"))

from vllm_grpc_bench.channel_config import preset_by_name  # noqa: E402
from vllm_grpc_bench.m3_types import (  # noqa: E402
    Recommendation,
    Run,
    SupersedesM4Entry,
)
from vllm_grpc_bench.m5_supersede import build_supersedes_m4_table  # noqa: E402
from vllm_grpc_bench.reporter import _supersedes_m4_to_dict  # noqa: E402

_DEFAULT_M5_JSON = _ROOT / "docs" / "benchmarks" / "m5-cross-host-validation.json"
_DEFAULT_M5_MD = _ROOT / "docs" / "benchmarks" / "m5-cross-host-validation.md"
_DEFAULT_M4_JSON = _ROOT / "docs" / "benchmarks" / "m4-time-axis-tuning.json"


def _recommendation_from_dict(d: dict[str, Any]) -> Recommendation:
    """Minimal reverse-deserializer for ``Recommendation``.

    ``build_supersedes_m4_table`` only consumes a handful of fields from each
    rec (``axis``, ``applies_to_path``, ``applies_to_widths``, ``verdict``,
    ``baseline_ci_upper``, ``candidate_ci_lower``). We reconstruct only what
    the supersedes builder reads; we do not attempt to round-trip the full
    Recommendation back to the on-disk shape.
    """
    winning_config_name = d.get("winning_config")
    winning_config = preset_by_name(winning_config_name) if winning_config_name else None
    return Recommendation(
        axis=d["axis"],
        applies_to_path=d["applies_to_path"],
        applies_to_widths=frozenset(int(w) for w in d.get("applies_to_widths", [])),
        verdict=d["verdict"],
        baseline_ci_upper=float(d.get("baseline_ci_upper") or 0.0),
        citation=str(d.get("citation") or "n/a"),
        winning_config=winning_config,
        winning_delta_pct=d.get("winning_delta_pct"),
        winning_metric=d.get("winning_metric"),
        candidate_ci_lower=d.get("candidate_ci_lower"),
        notes=str(d.get("notes") or ""),
        corpus_subset=d.get("corpus_subset"),
    )


def _run_stub_for_supersedes(m5_payload: dict[str, Any]) -> Run:
    """Build the minimal ``Run`` that ``build_supersedes_m4_table`` reads.

    The supersedes builder only consumes ``run.recommendations``. We pass
    other ``Run`` fields as their defaults; nothing else is referenced in the
    join. This keeps the script free of a full deserializer — useful since
    the M5 JSON's full shape isn't reverse-mapped anywhere in the codebase.
    """
    recs = [_recommendation_from_dict(r) for r in m5_payload.get("recommendations", [])]
    run = Run(
        mode=m5_payload.get("mode", "m5-cross-host-validation"),
        axes=list(m5_payload.get("axes") or []),
        widths=list(m5_payload.get("widths") or []),
        paths=list(m5_payload.get("paths") or []),
        iterations_per_cell=int(m5_payload.get("iterations_per_cell") or 0),
        seed=int(m5_payload.get("seed") or 0),
        cohorts=[],
    )
    run.recommendations.extend(recs)
    return run


def _render_supersedes_section(
    entries: list[SupersedesM4Entry],
) -> list[str]:
    """Build the Markdown "Supersedes M4" section from a list of entries.

    Mirrors ``reporter.write_m5_markdown`` so reprocess output is identical to
    a fresh sweep's output. Returns the lines (without trailing newline)
    starting at the ``## Supersedes M4`` heading and ending just before the
    section that follows (Appendix or Executive summary). Empty list if
    ``entries`` is empty.
    """
    if not entries:
        return []
    normal_entries = [e for e in entries if e.expected_class != "unexpected_supersession"]
    normal_entries.sort(
        key=lambda e: (not e.verdict_changed, e.m4_path, e.m4_axis, e.m4_hidden_size)
    )
    unexpected = [e for e in entries if e.expected_class == "unexpected_supersession"]
    lines: list[str] = [
        "## Supersedes M4",
        "",
        (
            "| flag | M4 cell | M4 verdict (time/bytes) | M5 verdict (time/bytes) | "
            "M5 CI | class | rationale |"
        ),
        "|------|---------|-------------------------|-------------------------|-------|-------|-----------|",
    ]
    for e in normal_entries:
        marker = "**[changed]**" if e.verdict_changed else ""
        m4 = f"{e.m4_axis}/h{e.m4_hidden_size}/{e.m4_path}"
        m4v = f"{e.m4_verdict_time}/{e.m4_verdict_bytes}"
        m5v = f"{e.m5_verdict_time}/{e.m5_verdict_bytes}"
        ci = f"[{e.m5_supporting_ci_lower:.4g}, {e.m5_supporting_ci_upper:.4g}]"
        rationale = e.rationale
        if e.citations:
            cite_refs = "; ".join(
                f"{c.repo}:{c.file_path}" + (f"#{c.identifier}" if c.identifier else "")
                for c in e.citations
            )
            rationale = f"{rationale} (citations: {cite_refs})"
        lines.append(
            f"| {marker} | `{m4}` | {m4v} | {m5v} | {ci} | {e.expected_class} | {rationale} |"
        )
    if unexpected:
        lines += [
            "",
            "### Unexpected supersessions — investigate before adopting",
            "",
            (
                "| flag | M4 cell | M4 verdict (time/bytes) | M5 verdict (time/bytes) | "
                "M5 CI | rationale |"
            ),
            "|------|---------|-------------------------|-------------------------|-------|-----------|",
        ]
        for e in unexpected:
            m4 = f"{e.m4_axis}/h{e.m4_hidden_size}/{e.m4_path}"
            m4v = f"{e.m4_verdict_time}/{e.m4_verdict_bytes}"
            m5v = f"{e.m5_verdict_time}/{e.m5_verdict_bytes}"
            ci = f"[{e.m5_supporting_ci_lower:.4g}, {e.m5_supporting_ci_upper:.4g}]"
            lines.append(f"| **[unexpected]** | `{m4}` | {m4v} | {m5v} | {ci} | {e.rationale} |")
    return lines


def _replace_supersedes_section(md_text: str, new_section_lines: list[str]) -> str:
    """Splice the rebuilt section into the existing Markdown.

    The section runs from ``## Supersedes M4`` (inclusive) up to (but not
    including) the next ``## `` heading. If the run had zero supersession
    entries the section heading is absent; we skip in that case.
    """
    lines = md_text.split("\n")
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "## Supersedes M4")
    except StopIteration:
        # No supersedes section to replace; if new entries exist, insert
        # before the Appendix / Executive summary section. For the common
        # case (entries present in both old and new), the heading exists.
        return md_text
    # Find the next top-level heading after the supersedes section.
    end = start + 1
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    # Splice: lines[:start] + new_section_lines + ['']-separator + lines[end:]
    new_lines = lines[:start] + new_section_lines + [""] + lines[end:]
    return "\n".join(new_lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--m5-json", type=Path, default=_DEFAULT_M5_JSON)
    parser.add_argument("--m5-md", type=Path, default=_DEFAULT_M5_MD)
    parser.add_argument("--m4-json", type=Path, default=_DEFAULT_M4_JSON)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute the new supersedes table and print a class-count summary "
        "but do not modify any files.",
    )
    args = parser.parse_args(argv)

    if not args.m5_json.exists():
        print(f"ERROR: M5 JSON not found at {args.m5_json}", file=sys.stderr)
        return 2
    if not args.m4_json.exists():
        print(f"ERROR: M4 JSON not found at {args.m4_json}", file=sys.stderr)
        return 2

    m5_payload = json.loads(args.m5_json.read_text())
    run_stub = _run_stub_for_supersedes(m5_payload)
    new_entries = build_supersedes_m4_table(run_stub, args.m4_json)

    by_class: dict[str, int] = {}
    for e in new_entries:
        by_class[e.expected_class] = by_class.get(e.expected_class, 0) + 1
    print(f"Reprocessed supersedes_m4: {len(new_entries)} entries")
    for cls, count in sorted(by_class.items()):
        print(f"  {cls}: {count}")

    if args.dry_run:
        print("(dry-run; no files written)")
        return 0

    # Rewrite the JSON's supersedes_m4 array.
    m5_payload["supersedes_m4"] = [_supersedes_m4_to_dict(e) for e in new_entries]
    args.m5_json.write_text(json.dumps(m5_payload, indent=2, default=str))
    print(f"Wrote {args.m5_json}")

    # Splice the Markdown's Supersedes M4 section in place.
    if args.m5_md.exists():
        old_md = args.m5_md.read_text()
        new_section = _render_supersedes_section(new_entries)
        new_md = _replace_supersedes_section(old_md, new_section)
        args.m5_md.write_text(new_md)
        print(f"Wrote {args.m5_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
