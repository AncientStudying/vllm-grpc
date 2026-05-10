from __future__ import annotations

import subprocess
import sys


def test_p2_revision_without_frozen_channel_exits_2() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "vllm_grpc_bench",
            "--m3",
            "--p2-revision",
            "foo",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 2, f"got {proc.returncode}; stderr=\n{proc.stderr}"
    # Stderr must name the missing flag clearly:
    assert "--frozen-channel" in proc.stderr


def test_p2_revision_with_unknown_frozen_channel_exits_2() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "vllm_grpc_bench",
            "--m3",
            "--p2-revision",
            "foo",
            "--frozen-channel",
            "does-not-exist",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 2, f"got {proc.returncode}; stderr=\n{proc.stderr}"


def test_invalid_width_exits_2() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "vllm_grpc_bench",
            "--m3",
            "--smoke",
            "--width",
            "bogus",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 2, f"got {proc.returncode}; stderr=\n{proc.stderr}"
