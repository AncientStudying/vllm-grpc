from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_m3_smoke_returns_zero_and_writes_artefact(tmp_path: Path, monkeypatch: object) -> None:
    """Run --m3 --smoke as a subprocess and confirm exit 0 + smoke artefact."""
    cwd = tmp_path
    bench_results = cwd / "bench-results"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "vllm_grpc_bench",
            "--m3",
            "--smoke",
            "--axis",
            "max_message_size",
            "--width",
            "2048",
            "--path",
            "embed",
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"stderr=\n{proc.stderr}\nstdout=\n{proc.stdout}"
    smoke_files = list(bench_results.glob("m3-smoke-*.json"))
    assert smoke_files, f"no smoke artefact under {bench_results}"
    payload = json.loads(smoke_files[0].read_text())
    assert payload["mode"] == "smoke"
    assert payload["axis"] == "max_message_size"
    assert payload["width"] == 2048
    assert payload["path"] == "embed"
    assert any(c["n_successful"] >= 1 for c in payload["cohorts"])
