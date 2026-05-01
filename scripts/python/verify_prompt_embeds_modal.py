#!/usr/bin/env python3
"""Verify prompt_embeds support on Modal A10G with vLLM.

Deploys a vLLM server (--enable-prompt-embeds) on a Modal A10G GPU, sends a
prompt_embeds completion request, and prints timing + pass/fail results.

Usage (requires Modal token):
    uv run --with modal --with vllm modal run scripts/python/verify_prompt_embeds_modal.py

Exit codes:
    0  Server accepted prompt_embeds and returned a completion.
    1  Server unreachable, returned an error, or response was malformed.
"""

from __future__ import annotations

import sys

import modal

_VLLM_VERSION = "0.20.0"
_MODEL = "Qwen/Qwen3-0.6B"
_PORT = 8000
_MAX_MODEL_LEN = 512
_HIDDEN_SIZE = 1024  # Qwen3-0.6B hidden dimension
_STARTUP_POLL_INTERVAL_S = 5
_STARTUP_MAX_POLLS = 120  # 10 minutes

app = modal.App("vllm-prompt-embeds-verify")

_image = modal.Image.debian_slim(python_version="3.12").pip_install(
    f"vllm=={_VLLM_VERSION}",
    "httpx",
    "torch",
)


@app.function(
    gpu="A10G",
    image=_image,
    timeout=600,
)
def _verify_on_gpu(seq_len: int, max_tokens: int) -> dict[str, object]:
    """Run vLLM serve + prompt_embeds verification inside the Modal container."""
    import base64
    import io
    import subprocess
    import time

    import httpx
    import torch

    server = subprocess.Popen(
        [
            "python",
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--model",
            _MODEL,
            "--enable-prompt-embeds",
            "--max-model-len",
            str(_MAX_MODEL_LEN),
            "--port",
            str(_PORT),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    base_url = f"http://localhost:{_PORT}"
    ready = False
    for _ in range(_STARTUP_MAX_POLLS):
        try:
            r = httpx.get(f"{base_url}/health", timeout=2.0)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(_STARTUP_POLL_INTERVAL_S)

    if not ready:
        server.kill()
        return {"ok": False, "error": "vLLM server did not become healthy within 600s"}

    tensor = torch.zeros(seq_len, _HIDDEN_SIZE, dtype=torch.float32)
    buf = io.BytesIO()
    torch.save(tensor, buf)
    embed_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=300.0) as client:
            response = client.post(
                f"{base_url}/v1/completions",
                json={
                    "model": _MODEL,
                    "prompt_embeds": embed_b64,
                    "max_tokens": max_tokens,
                },
            )
    except Exception as exc:
        server.kill()
        return {"ok": False, "error": str(exc)}

    elapsed = time.monotonic() - t0
    server.kill()

    if response.status_code != 200:
        return {
            "ok": False,
            "error": f"HTTP {response.status_code}: {response.text[:500]}",
        }

    data: dict[str, object] = response.json()
    usage = data.get("usage")
    tokens_generated: object = "?"
    if isinstance(usage, dict):
        tokens_generated = usage.get("completion_tokens", "?")

    return {
        "ok": True,
        "elapsed_s": elapsed,
        "tokens_generated": tokens_generated,
    }


@app.local_entrypoint()
def main() -> None:
    result = _verify_on_gpu.remote(seq_len=8, max_tokens=50)

    ok = result.get("ok")
    if ok:
        print(f"[OK] Server responded in {result['elapsed_s']:.2f}s")
        print(f"[OK] Tokens generated: {result['tokens_generated']}")
        print("[OK] prompt_embeds accepted — Modal A10G environment is viable")
        sys.exit(0)
    else:
        print(f"[FAIL] {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
