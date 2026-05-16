"""M6.1.1 supersedence writers — FR-023 / FR-024 / FR-015c unit tests.

All writers are tested against synthetic fixtures in tmp_path; no real M6.1
files are mutated. Tests assert byte-stability on every original key (the
contract M6.1's published JSON must satisfy after M6.1.1's annotation lands).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from vllm_grpc_bench.m6_1_1_supersedence import (
    write_methodology_supersedence_json,
    write_methodology_supersedence_markdown,
    write_per_row_supersedence_notes,
)

# --- JSON writer ------------------------------------------------------------


def _make_m6_1_json(tmp_path: Path) -> Path:
    """A small but representative M6.1 JSON fixture (no methodology_supersedence yet)."""
    data = {
        "schema_version": "m6_1.v1",
        "run_id": "run-1",
        "run_meta": {"engine_version": "0.20.1", "torch_version": "2.11.0"},
        "engine_cost_baseline": [
            {
                "cell": {"path": "embed", "concurrency": 1, "hidden_size": 4096},
                "engine_cost_mean_ms": 338.1,
            },
        ],
        "supersedes_m6_under_enable_prompt_embeds": [],
    }
    p = tmp_path / "m6_1.json"
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p


def test_json_annotation_adds_key_byte_stable_on_originals(tmp_path: Path) -> None:
    p = _make_m6_1_json(tmp_path)
    before = json.loads(p.read_text(encoding="utf-8"))
    write_methodology_supersedence_json(
        m6_1_path=p,
        m6_1_1_report_path="docs/benchmarks/m6_1_1-engine-cost-instrumentation.md",
        phase_2_path="phase_2a_verified",
        summary="Instrumentation_artifact cleared via Phase 2(a) symmetrisation.",
    )
    after = json.loads(p.read_text(encoding="utf-8"))
    # Every M6.1 original key preserved byte-stable
    for key, val in before.items():
        assert key in after
        assert after[key] == val
    # New key present with correct shape
    ms = after["methodology_supersedence"]
    assert ms["phase_2_path"] == "phase_2a_verified"
    assert ms["schema_version"] == "m6_1_1.v1"
    assert ms["summary"].startswith("Instrumentation_artifact")
    assert ms["pointer"] == "docs/benchmarks/m6_1_1-engine-cost-instrumentation.md"


def test_json_annotation_overwrites_existing_not_duplicates(tmp_path: Path) -> None:
    """Re-invoking the writer overwrites the existing annotation in place."""
    p = _make_m6_1_json(tmp_path)
    write_methodology_supersedence_json(
        m6_1_path=p,
        m6_1_1_report_path="path1",
        phase_2_path="phase_2_pending",
        summary="first",
    )
    write_methodology_supersedence_json(
        m6_1_path=p,
        m6_1_1_report_path="path2",
        phase_2_path="phase_2a_verified",
        summary="second",
    )
    after = json.loads(p.read_text(encoding="utf-8"))
    assert after["methodology_supersedence"]["pointer"] == "path2"
    assert after["methodology_supersedence"]["summary"] == "second"
    # Exactly one methodology_supersedence key
    assert list(after.keys()).count("methodology_supersedence") == 1


# --- Markdown writer --------------------------------------------------------


def _make_m6_1_md(tmp_path: Path) -> Path:
    body = "# M6.1\n\nSome intro.\n\n## chat_stream verdict\n\nThe chat_stream verdict text.\n"
    p = tmp_path / "m6_1.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_md_annotation_inserts_below_chat_stream_verdict_heading(tmp_path: Path) -> None:
    p = _make_m6_1_md(tmp_path)
    write_methodology_supersedence_markdown(
        m6_1_md_path=p,
        m6_1_1_md_path="docs/benchmarks/m6_1_1-engine-cost-instrumentation.md",
        date_yyyy_mm_dd="2026-05-17",
    )
    body = p.read_text(encoding="utf-8")
    # Verify the inserted line sits below the verdict heading
    heading_idx = body.find("## chat_stream verdict\n")
    pointer_idx = body.find("> **Methodology supersedence (2026-05-17)**:")
    assert heading_idx != -1
    assert pointer_idx > heading_idx
    # The original "chat_stream verdict text." line is preserved further
    # down the file.
    assert "The chat_stream verdict text." in body
    # And the new line ends with the m6_1_1 markdown pointer
    assert "m6_1_1-engine-cost-instrumentation.md" in body


def test_md_annotation_idempotent_replaces_existing(tmp_path: Path) -> None:
    p = _make_m6_1_md(tmp_path)
    write_methodology_supersedence_markdown(p, "old.md", "2026-05-01")
    write_methodology_supersedence_markdown(p, "new.md", "2026-05-17")
    body = p.read_text(encoding="utf-8")
    # Exactly one pointer line
    assert body.count("> **Methodology supersedence") == 1
    # Most-recent date + path won
    assert "(2026-05-17)" in body
    assert "new.md" in body
    assert "old.md" not in body
    assert "(2026-05-01)" not in body


def test_md_annotation_raises_when_no_heading_match(tmp_path: Path) -> None:
    p = tmp_path / "missing_heading.md"
    p.write_text("# Some doc\n\n## Different section\n", encoding="utf-8")
    with pytest.raises(ValueError, match="could not locate a chat_stream verdict heading"):
        write_methodology_supersedence_markdown(p, "x.md", "2026-05-17")


# --- Per-row supersedence notes ---------------------------------------------


def _make_m6_1_md_with_table(tmp_path: Path) -> Path:
    body = (
        "# M6.1\n"
        "\n"
        "## chat_stream verdict\n"
        "\n"
        "The chat_stream verdict text.\n"
        "\n"
        "## Supersedes M6 under enable_prompt_embeds\n"
        "\n"
        "| cell | cohort | mean_ms | notes |\n"
        "|------|--------|---------|-------|\n"
        "| embed_c1_h4096 | rest_https_edge | 338.1 | base |\n"
        "| embed_c1_h4096 | default_grpc | 339.5 | base |\n"
        "| embed_c4_h4096 | tuned_grpc_multiplexed | 95.4 | base |\n"
        "| chat_stream_c1_h4096 | rest_https_edge | 43.7 | base |\n"
    )
    p = tmp_path / "m6_1.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_per_row_notes_added_only_to_affected_rows(tmp_path: Path) -> None:
    p = _make_m6_1_md_with_table(tmp_path)
    affected = [
        ("embed_c1_h4096", "rest_https_edge"),
        ("embed_c4_h4096", "tuned_grpc_multiplexed"),
    ]
    write_per_row_supersedence_notes(
        m6_1_md_path=p,
        affected_rows=affected,
        m6_1_1_baseline_section_anchor="m6_1_1-engine-cost-instrumentation.json#embed_baseline_post_symmetrisation",
        delta_pct_per_row={
            ("embed_c1_h4096", "rest_https_edge"): -0.07,
            ("embed_c4_h4096", "tuned_grpc_multiplexed"): 0.06,
        },
    )
    body = p.read_text(encoding="utf-8")
    # Affected rows carry the note
    assert "embed_regression_acknowledged: post-symmetrisation mean shifted -7%" in body
    assert "embed_regression_acknowledged: post-symmetrisation mean shifted +6%" in body
    # Non-affected embed row has no note appended
    lines = body.splitlines()
    default_grpc_row = next(
        line for line in lines if "embed_c1_h4096" in line and "default_grpc" in line
    )
    assert "embed_regression_acknowledged" not in default_grpc_row
    # chat_stream row is unaffected even though it doesn't contain "embed"
    cs_row = next(line for line in lines if "chat_stream_c1_h4096" in line)
    assert "embed_regression_acknowledged" not in cs_row


def test_per_row_notes_idempotent_replaces_existing(tmp_path: Path) -> None:
    p = _make_m6_1_md_with_table(tmp_path)
    affected = [("embed_c1_h4096", "rest_https_edge")]
    write_per_row_supersedence_notes(
        p,
        affected,
        "anchor",
        delta_pct_per_row={("embed_c1_h4096", "rest_https_edge"): -0.05},
    )
    write_per_row_supersedence_notes(
        p,
        affected,
        "anchor",
        delta_pct_per_row={("embed_c1_h4096", "rest_https_edge"): -0.10},
    )
    body = p.read_text(encoding="utf-8")
    # Exactly one acknowledged note on the affected row
    affected_row = next(
        line for line in body.splitlines() if "embed_c1_h4096" in line and "rest_https_edge" in line
    )
    assert affected_row.count("embed_regression_acknowledged") == 1
    # Latest delta wins
    assert "-10%" in affected_row
    assert "-5%" not in affected_row
