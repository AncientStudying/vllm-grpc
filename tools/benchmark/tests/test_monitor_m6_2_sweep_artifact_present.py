"""T075 — monitor's stale-artifact false-positive fix.

Surfaced by the 2026-05-24 16:17 UTC validate run: the pre-T075 monitor
reported ``artifact=yes`` while the orchestrator was still in the
sub-probe phase because the previous (failed 13:44 UTC) sweep had left
``docs/benchmarks/m6_2-token-budget-validate.json`` on disk at 10:01.
The check only asked ``path.exists()``, ignoring whether the file
predated the current sweep's ``SWEEP_START``.

The fix adds :func:`compute_artifact_present(json_path, sweep_start_utc)`
to ``scripts/python/monitor_m6_2_sweep.py``. The predicate compares the
file's mtime against the SWEEP_START UTC and returns ``True`` only when
the file was written AFTER the sweep started.

These tests exercise the predicate against:

1. No file on disk → False.
2. File present but predates SWEEP_START → False (stale).
3. File present and postdates SWEEP_START → True (fresh).
4. ``sweep_start_utc=None`` (monitor launched pre-sweep) → False.
5. Malformed sweep_start_utc → False (defensive).
6. ``json_path=None`` (no artifact requested) → False.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

_MONITOR_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "python"
    / "monitor_m6_2_sweep.py"
)
_spec = importlib.util.spec_from_file_location("monitor_m6_2_sweep", _MONITOR_SCRIPT)
assert _spec is not None and _spec.loader is not None
_monitor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_monitor)

compute_artifact_present = _monitor.compute_artifact_present


def _set_mtime(path: Path, iso_utc: str) -> None:
    """Touch ``path`` to the given ISO-8601 UTC timestamp so the test
    can simulate a "file written at X" condition without sleeping."""
    import datetime as _dt

    dt = _dt.datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    epoch = dt.timestamp()
    os.utime(path, (epoch, epoch))


class TestComputeArtifactPresent:
    def test_returns_false_when_path_is_none(self) -> None:
        assert compute_artifact_present(None, "2026-05-24T16:17:01Z") is False

    def test_returns_false_when_file_does_not_exist(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.json"
        assert compute_artifact_present(missing, "2026-05-24T16:17:01Z") is False

    def test_returns_false_when_sweep_start_is_none(self, tmp_path: Path) -> None:
        """The SWEEP_START event hasn't landed yet — the monitor was
        launched before the sweep started writing progress events. We
        can't compare mtime to a non-existent start time, so refuse to
        claim presence."""
        artifact = tmp_path / "present.json"
        artifact.write_text("{}")
        assert compute_artifact_present(artifact, None) is False

    def test_returns_false_when_artifact_predates_sweep_start(
        self, tmp_path: Path
    ) -> None:
        """The 2026-05-24 production regression: a previous failed sweep
        left a stale artifact at 10:01 UTC; the current sweep started
        at 16:17 UTC. The predicate must NOT treat the stale file as
        present (which would trigger the monitor's auto-exit prematurely)."""
        stale = tmp_path / "validate.json"
        stale.write_text("{}")
        _set_mtime(stale, "2026-05-24T10:01:00Z")
        assert compute_artifact_present(stale, "2026-05-24T16:17:01Z") is False

    def test_returns_true_when_artifact_postdates_sweep_start(
        self, tmp_path: Path
    ) -> None:
        """Happy path: the sweep wrote its artifact after SWEEP_START
        fired. The predicate reports presence so the monitor's auto-exit
        can trigger correctly."""
        fresh = tmp_path / "validate.json"
        fresh.write_text("{}")
        _set_mtime(fresh, "2026-05-24T20:30:00Z")
        assert compute_artifact_present(fresh, "2026-05-24T16:17:01Z") is True

    def test_returns_false_when_sweep_start_is_unparseable(
        self, tmp_path: Path
    ) -> None:
        """Defensive: a malformed sweep_start_utc string (e.g. from a
        future SWEEP_START schema migration that breaks _parse_utc)
        must not crash the monitor and must not claim presence."""
        artifact = tmp_path / "validate.json"
        artifact.write_text("{}")
        _set_mtime(artifact, "2026-05-24T20:30:00Z")
        assert compute_artifact_present(artifact, "not-a-timestamp") is False

    def test_mtime_within_one_second_of_sweep_start_is_treated_as_fresh(
        self, tmp_path: Path
    ) -> None:
        """Boundary case: a sweep that writes its artifact at exactly
        sweep_start + epsilon should still report present (the predicate
        uses strict ``>`` against sweep_start, so even a 1-second-later
        mtime counts as fresh). Validates the off-by-one boundary."""
        artifact = tmp_path / "validate.json"
        artifact.write_text("{}")
        # sweep_start at T, file mtime at T+1s
        _set_mtime(artifact, "2026-05-24T16:17:02Z")
        assert compute_artifact_present(artifact, "2026-05-24T16:17:01Z") is True


class TestMonitorRegression20260524:
    """Regression anchor against the specific signature from the
    2026-05-24 16:17 UTC validate run: pre-T075 monitor reported
    ``artifact=yes`` against a 10:01 stale file; post-T075 monitor must
    report ``artifact=no``."""

    def test_2026_05_24_stale_artifact_no_longer_false_positives(
        self, tmp_path: Path
    ) -> None:
        # The exact scenario from production:
        #   stale artifact: docs/benchmarks/m6_2-token-budget-validate.json
        #                   mtime = 2026-05-24T15:01:52Z (10:01:52 CDT)
        #   current sweep:  SWEEP_START at 2026-05-24T16:17:01Z
        # Pre-fix predicate returned True (false positive); post-fix
        # predicate returns False (correct).
        stale = tmp_path / "m6_2-token-budget-validate.json"
        stale.write_text("{}")
        _set_mtime(stale, "2026-05-24T15:01:52Z")
        assert compute_artifact_present(stale, "2026-05-24T16:17:01Z") is False

    def test_2026_05_24_post_sweep_artifact_correctly_reports_present(
        self, tmp_path: Path
    ) -> None:
        """The flip side: once the sweep completes and writes its fresh
        artifact (mtime will be ~20:30 UTC for the 3.5-4 h validate
        sweep), the predicate must report True so the monitor's
        auto-exit triggers cleanly."""
        fresh = tmp_path / "m6_2-token-budget-validate.json"
        fresh.write_text("{}")
        _set_mtime(fresh, "2026-05-24T20:30:00Z")
        assert compute_artifact_present(fresh, "2026-05-24T16:17:01Z") is True


def test_compute_artifact_present_is_exported() -> None:
    """The helper is part of the monitor's public API surface so the
    test suite + future operator scripts can import it without going
    through importlib gymnastics in production."""
    assert callable(compute_artifact_present)
    assert compute_artifact_present.__name__ == "compute_artifact_present"
    # Brief docstring sanity-check so a future refactor that strips the
    # docstring catches a test failure.
    assert compute_artifact_present.__doc__ is not None
    assert "T075" in compute_artifact_present.__doc__
