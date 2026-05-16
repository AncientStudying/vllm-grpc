"""M6.1.1 supersedence pointer-target validation test (T034 / SC-006).

After an M6.1.1 close lands on main, M6.1's published JSON should carry a
``methodology_supersedence`` annotation whose ``pointer`` field resolves
to an existing file relative to the repository root. This test fires once
the M6.1.1 PR merges (and the annotation is present); it's a no-op on
branches where M6.1.1 hasn't closed yet.

The test catches typos and path drift in CI before merge: if the
annotation lands but the pointer target doesn't exist, the test fails
loudly. If the annotation isn't present yet (e.g., this test running on
M6.1.1's own PR branch before the Phase 2 close has been committed), the
test is skipped with a clear message.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_M6_1_BASELINE = _REPO_ROOT / "docs" / "benchmarks" / "m6_1-real-prompt-embeds.json"


def test_methodology_supersedence_pointer_resolves() -> None:
    """The pointer in M6.1's methodology_supersedence (when present) names
    an existing file relative to the repo root."""
    if not _M6_1_BASELINE.is_file():
        pytest.skip(f"M6.1 baseline at {_M6_1_BASELINE} not present")
    data = json.loads(_M6_1_BASELINE.read_text(encoding="utf-8"))
    ms = data.get("methodology_supersedence")
    if ms is None:
        pytest.skip(
            "M6.1.1 has not yet annotated M6.1's published JSON with "
            "methodology_supersedence — test fires once Phase 2 closes."
        )
    pointer = ms.get("pointer")
    assert pointer, (
        "methodology_supersedence.pointer is empty; M6.1.1's writer must "
        "emit a path to its own published markdown report."
    )
    target = _REPO_ROOT / pointer
    assert target.is_file(), (
        f"methodology_supersedence.pointer references {pointer!r} which "
        f"resolves to {target} — file does not exist. Fix the writer's "
        "pointer path or stop annotating M6.1 until the M6.1.1 markdown "
        "is committed."
    )


def test_methodology_supersedence_pointer_targets_m6_1_1_artifact() -> None:
    """Sanity check on the pointer's shape — it should reference M6.1.1's
    published markdown under ``docs/benchmarks/``, not an unrelated file."""
    if not _M6_1_BASELINE.is_file():
        pytest.skip(f"M6.1 baseline at {_M6_1_BASELINE} not present")
    data = json.loads(_M6_1_BASELINE.read_text(encoding="utf-8"))
    ms = data.get("methodology_supersedence")
    if ms is None:
        pytest.skip("methodology_supersedence not yet present")
    pointer = str(ms.get("pointer", ""))
    assert "m6_1_1" in pointer, (
        f"methodology_supersedence.pointer={pointer!r} should reference an "
        "m6_1_1 artifact; double-check the writer is emitting the right path."
    )
    assert pointer.endswith(".md"), (
        f"methodology_supersedence.pointer={pointer!r} should point at the "
        "M6.1.1 markdown report (operator-facing), not the JSON companion."
    )
