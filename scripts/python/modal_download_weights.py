#!/usr/bin/env python3
"""One-time Modal function to pre-stage Qwen/Qwen3-0.6B into a persistent cloud volume.

Idempotent: safe to re-run; skips download if /mnt/weights/config.json already exists.

Usage (requires Modal token: modal token new):
    make download-weights
    # or directly:
    uv run --with modal modal run scripts/python/modal_download_weights.py

Exit codes:
    0  Weights are in the volume (newly downloaded or already present).
    1  Download failed.
"""

from __future__ import annotations

import sys
import time

import modal

_MODEL = "Qwen/Qwen3-0.6B"
_MOUNT_PATH = "/mnt/weights"
_DOWNLOAD_TIMEOUT_S = 600

app = modal.App("vllm-grpc-download-weights")

_MODEL_VOLUME = modal.Volume.from_name("vllm-grpc-model-weights", create_if_missing=True)

_image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "huggingface_hub>=0.23",
)


@app.function(
    image=_image,
    volumes={_MOUNT_PATH: _MODEL_VOLUME},
    timeout=_DOWNLOAD_TIMEOUT_S,
)
def download_weights() -> dict[str, object]:
    """Download model weights into the persistent volume (CPU-only; no GPU needed)."""
    import time as _time
    from pathlib import Path

    sentinel = Path(f"{_MOUNT_PATH}/config.json")
    if sentinel.exists():
        return {"ok": True, "skipped": True, "elapsed_s": 0.0}

    from huggingface_hub import snapshot_download

    t0 = _time.monotonic()
    snapshot_download(repo_id=_MODEL, local_dir=_MOUNT_PATH)
    _MODEL_VOLUME.commit()
    elapsed = _time.monotonic() - t0
    return {"ok": True, "skipped": False, "elapsed_s": elapsed}


@app.local_entrypoint()
def main() -> None:
    t0 = time.monotonic()
    result = download_weights.remote()
    wall_clock = time.monotonic() - t0

    ok = result.get("ok")
    if result.get("skipped"):
        print(f"[OK] Weights already present at {_MOUNT_PATH} — skipping download.")
    elif ok:
        elapsed = result.get("elapsed_s", 0.0)
        print(f"[OK] Download complete. Volume committed. ({elapsed:.1f}s inside container)")
    else:
        error = result.get("error", "unknown error")
        print(f"[FAIL] {error}", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] Total wall-clock time: {wall_clock:.1f}s")
