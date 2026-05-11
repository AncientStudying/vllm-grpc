"""T034 — Modal-secrets-gated end-to-end smoke for M5.

Deploys the Modal bench app via ``app.run.aio()``, runs a single tiny cohort
against it (no full sweep), and asserts the published JSON carries an RTT
record with a non-loopback median and the run is region-tagged. The test is
gated by the presence of ``MODAL_TOKEN_ID`` / ``MODAL_TOKEN_SECRET`` /
``MODAL_BENCH_TOKEN`` in the env; without them, pytest skips.

A clean exit verifies teardown (``modal app list | grep
vllm-grpc-bench-mock`` returns empty after the test, per the task spec —
operator-checked, not asserted in code).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REQUIRED_ENV = ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "MODAL_BENCH_TOKEN")

pytestmark = pytest.mark.skipif(
    not all(os.environ.get(k) for k in _REQUIRED_ENV),
    reason=("Modal smoke test requires " + ", ".join(_REQUIRED_ENV) + " in the environment"),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.mark.slow
def test_m5_modal_smoke_emits_rtt_and_region(tmp_path: Path) -> None:
    """Tiny end-to-end: deploy → 1 baseline cohort + 1 candidate cohort → teardown."""
    out_dir = tmp_path / "m5-smoke"
    out_dir.mkdir()
    env = dict(os.environ)
    env["BENCH_M5_DOCS_DIR"] = str(out_dir)

    cmd = [
        sys.executable,
        "-m",
        "vllm_grpc_bench",
        "--m5",
        "--m5-modal-region=eu-west-1",
        "--baseline-n=100",
        "--candidate-n=100",
        "--expand-n=101",
        "--widths=4096",
        "--paths=embed",
        "--axes=max_message_size",
        "--schema-candidates=",
        "--skip-schema",
        "--m5-warmup-n=8",
        "--out",
        str(out_dir),
    ]
    result = subprocess.run(
        cmd,
        cwd=_repo_root(),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=15 * 60,
    )
    assert result.returncode == 0, (
        f"M5 smoke exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    report_path = _repo_root() / "docs" / "benchmarks" / "m5-cross-host-validation.json"
    assert report_path.exists(), f"missing report file {report_path}"
    payload = json.loads(report_path.read_text())
    # Region is recorded.
    assert payload["m5_modal_region"] == "eu-west-1"
    # At least one shared-baseline cohort + one candidate cohort.
    non_discarded_cohorts = [c for c in payload["cohorts"] if not c["discarded"]]
    assert len(non_discarded_cohorts) >= 2
    for c in non_discarded_cohorts:
        # Every M5 cohort carries an RTT record.
        rtt = c.get("rtt_record")
        assert rtt is not None
        # Real-wire median is well above the loopback floor.
        assert rtt["median_ms"] > 1.0, c["cell_id"]
        # M5 cells never carry the loopback caveat (FR-007).
        assert c["loopback_caveat"] is False

    # Sanity: the Modal app was torn down (no orphan registered).
    if shutil.which("modal"):
        listing = subprocess.run(
            ["modal", "app", "list"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert "vllm-grpc-bench-mock" not in listing.stdout, (
            "Modal app vllm-grpc-bench-mock still listed after smoke test — teardown likely failed"
        )
