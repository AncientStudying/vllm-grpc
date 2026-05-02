#!/usr/bin/env python3
"""Lifecycle-managed smoke test: deploys vLLM's native OpenAI REST server on Modal A10G.

Starts vLLM's built-in OpenAI-compatible server as a subprocess inside a single Modal
function, sends the same chat completion request used in the gRPC frontend smoke test
(same prompt, same seed, same max_tokens), verifies the response, then tears down.

Usage (requires Modal token and pre-staged weights — see make download-weights):
    make smoke-rest
    # or directly:
    uv run --with modal modal run scripts/python/modal_vllm_rest.py

Exit codes:
    0  Smoke test passed (non-empty completion returned).
    1  Deployment failed, server timeout, or unexpected response.

Compare completion_text with the gRPC frontend smoke test (make smoke-grpc-frontend)
to verify token-level equivalence (SC-003 in specs/005-modal-grpc-frontend/spec.md).

See docs/decisions/0002-modal-deployment.md for architecture notes.
"""

from __future__ import annotations

import sys
import time

import modal

_VLLM_VERSION = "0.20.0"
_MODEL = "Qwen/Qwen3-0.6B"
_MODEL_PATH = "/mnt/weights"
_REST_PORT = 8000
_REST_STARTUP_POLLS = 120  # 5 s × 120 = 600 s max
_REST_POLL_INTERVAL_S = 5
_REQUEST_TIMEOUT_S = 60.0
_FUNCTION_TIMEOUT_S = 900

_SMOKE_MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is 2 + 2?"},
]

app = modal.App("vllm-grpc-rest-smoke")

_MODEL_VOLUME = modal.Volume.from_name("vllm-grpc-model-weights", create_if_missing=False)

_image = modal.Image.debian_slim(python_version="3.12").pip_install(
    f"vllm=={_VLLM_VERSION}",
    "httpx>=0.27",
)


@app.function(
    gpu="A10G",
    image=_image,
    volumes={_MODEL_PATH: _MODEL_VOLUME},
    timeout=_FUNCTION_TIMEOUT_S,
)
def smoke_test() -> dict[str, object]:
    """Run REST smoke test inside the Modal container."""
    import subprocess
    import time as _time

    import httpx

    server_proc: subprocess.Popen[bytes] | None = None

    def _kill_all() -> None:
        if server_proc is not None and server_proc.poll() is None:
            server_proc.kill()

    t_start = _time.monotonic()

    # ── Step 1: start vLLM REST server ───────────────────────────────────────
    server_proc = subprocess.Popen(
        [
            "python",
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--model",
            _MODEL_PATH,
            "--port",
            str(_REST_PORT),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # ── Step 2: poll /health ──────────────────────────────────────────────────
    server_url = f"http://localhost:{_REST_PORT}"
    server_ready = False
    for _ in range(_REST_STARTUP_POLLS):
        _time.sleep(_REST_POLL_INTERVAL_S)
        if server_proc.poll() is not None:
            return {
                "ok": False,
                "error": "vLLM REST server process exited unexpectedly during startup",
                "cold_start_s": _time.monotonic() - t_start,
                "request_latency_s": 0.0,
                "completion_text": None,
                "model": _MODEL_PATH,
                "seed": 42,
                "max_tokens": 20,
            }
        try:
            r = httpx.get(f"{server_url}/health", timeout=2.0)
            if r.status_code == 200:
                server_ready = True
                break
        except Exception:
            pass

    cold_start_s = _time.monotonic() - t_start
    if not server_ready:
        _kill_all()
        return {
            "ok": False,
            "error": (
                f"vLLM REST server did not become healthy within"
                f" {_REST_STARTUP_POLLS * _REST_POLL_INTERVAL_S}s"
            ),
            "cold_start_s": cold_start_s,
            "request_latency_s": 0.0,
            "completion_text": None,
            "model": _MODEL_PATH,
            "seed": 42,
            "max_tokens": 20,
        }

    # ── Step 3: send smoke-test request ──────────────────────────────────────
    t_req = _time.monotonic()
    try:
        response = httpx.post(
            f"{server_url}/v1/chat/completions",
            json={
                "model": _MODEL_PATH,
                "messages": _SMOKE_MESSAGES,
                "max_tokens": 20,
                "seed": 42,
            },
            timeout=_REQUEST_TIMEOUT_S,
        )
    except Exception as exc:
        _kill_all()
        return {
            "ok": False,
            "error": f"Request failed: {exc}",
            "cold_start_s": cold_start_s,
            "request_latency_s": _time.monotonic() - t_req,
            "completion_text": None,
            "model": _MODEL_PATH,
            "seed": 42,
            "max_tokens": 20,
        }

    request_latency_s = _time.monotonic() - t_req

    # ── Step 4: verify and clean up ───────────────────────────────────────────
    _kill_all()

    if response.status_code != 200:
        return {
            "ok": False,
            "error": f"HTTP {response.status_code}: {response.text[:500]}",
            "cold_start_s": cold_start_s,
            "request_latency_s": request_latency_s,
            "completion_text": None,
            "model": _MODEL_PATH,
            "seed": 42,
            "max_tokens": 20,
        }

    data: dict[str, object] = response.json()
    choices = data.get("choices")
    completion_text: str | None = None
    if isinstance(choices, list) and len(choices) > 0:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str) and content:
                    completion_text = content

    if completion_text is None:
        return {
            "ok": False,
            "error": f"Unexpected response shape: {str(data)[:200]}",
            "cold_start_s": cold_start_s,
            "request_latency_s": request_latency_s,
            "completion_text": None,
            "model": _MODEL_PATH,
            "seed": 42,
            "max_tokens": 20,
        }

    return {
        "ok": True,
        "error": None,
        "cold_start_s": cold_start_s,
        "request_latency_s": request_latency_s,
        "completion_text": completion_text,
        "model": _MODEL_PATH,
        "seed": 42,
        "max_tokens": 20,
    }


@app.local_entrypoint()
def main() -> None:
    t0 = time.monotonic()
    result = smoke_test.remote()
    wall_clock = time.monotonic() - t0

    ok = result.get("ok")
    cold_start = result.get("cold_start_s", 0.0)
    request_latency = result.get("request_latency_s", 0.0)
    completion = result.get("completion_text")

    print(f"[INFO] cold_start_s       = {cold_start:.1f}")
    print(f"[INFO] request_latency_s  = {request_latency:.3f}")
    print(f"[INFO] wall_clock_s       = {wall_clock:.1f}")

    if ok:
        print(f"[OK]  completion_text = {completion!r}")
        print("[OK]  Smoke test PASSED. Tearing down.")
    else:
        error = result.get("error", "unknown error")
        print(f"[FAIL] {error}", file=sys.stderr)
        sys.exit(1)
