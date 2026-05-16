"""M6.1.1 contracts heading validator — FR-016 / round-3 Q2 tests."""

from __future__ import annotations

from pathlib import Path

from vllm_grpc_bench.m6_1_1_contracts_check import validate_contracts_heading


def test_valid_h2_heading_returns_line_and_path(tmp_path: Path) -> None:
    f = tmp_path / "instrumentation.md"
    f.write_text(
        "# Instrumentation\n\n"
        "Some text.\n\n"
        "## M6.1.1: Channel-Dependent Batching Effect\n\n"
        "Body of the section.\n",
        encoding="utf-8",
    )
    result = validate_contracts_heading(f)
    assert result is not None
    line, path = result
    assert line == "## M6.1.1: Channel-Dependent Batching Effect"
    assert path == str(f)


def test_missing_heading_returns_none(tmp_path: Path) -> None:
    f = tmp_path / "instrumentation.md"
    f.write_text(
        "# Instrumentation\n\n## M6: Engine Cost\n\nSome other section.\n",
        encoding="utf-8",
    )
    assert validate_contracts_heading(f) is None


def test_h3_level_does_not_match(tmp_path: Path) -> None:
    """`### M6.1.1: ...` (h3) does not match — heading level matters."""
    f = tmp_path / "instrumentation.md"
    f.write_text(
        "# Instrumentation\n\n"
        "## Some section\n\n"
        "### M6.1.1: Channel-Dependent Batching Effect\n\n"
        "Subsection body.\n",
        encoding="utf-8",
    )
    assert validate_contracts_heading(f) is None


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert validate_contracts_heading(tmp_path / "nonexistent.md") is None


def test_string_path_accepted(tmp_path: Path) -> None:
    """Accepts both Path and str arguments per spec contracts/cli.md."""
    f = tmp_path / "instrumentation.md"
    f.write_text("## M6.1.1: Topic\n", encoding="utf-8")
    result = validate_contracts_heading(str(f))
    assert result is not None
    assert result[0] == "## M6.1.1: Topic"


def test_first_match_wins_when_multiple_present(tmp_path: Path) -> None:
    f = tmp_path / "instrumentation.md"
    f.write_text(
        "## M6.1.1: First Topic\n\nBody\n\n## M6.1.1: Second Topic\n",
        encoding="utf-8",
    )
    result = validate_contracts_heading(f)
    assert result is not None
    assert result[0] == "## M6.1.1: First Topic"


def test_default_path_is_repo_root_contracts(tmp_path: Path, monkeypatch) -> None:
    """Default arg is ``contracts/instrumentation.md`` at repo root."""
    # Test that calling with no args falls back to the default path; in this
    # test we just confirm the default is read (not the content match).
    monkeypatch.chdir(tmp_path)
    # No file at the default path → returns None without raising
    assert validate_contracts_heading() is None
