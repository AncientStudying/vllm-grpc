#!/usr/bin/env python3
"""Lifecycle-managed smoke test: deploys vllm-grpc-frontend + proxy on Modal A10G.

Starts the gRPC frontend and proxy as subprocesses inside a single Modal function,
sends one chat completion request through the full proxy→gRPC→vLLM path, verifies
the response, then tears everything down on return.

Usage (requires Modal token and pre-staged weights — see make download-weights):
    make smoke-grpc-frontend
    # or directly:
    uv run --with modal modal run scripts/python/modal_frontend_smoke.py

Exit codes:
    0  Smoke test passed (non-empty completion returned).
    1  Deployment failed, server timeout, or unexpected response.

See docs/decisions/0002-modal-deployment.md for architecture notes.
"""

from __future__ import annotations

import sys
import time

import modal

_VLLM_VERSION = "0.20.0"
_MODEL = "Qwen/Qwen3-0.6B"
_MODEL_PATH = "/mnt/weights"
_GRPC_PORT = 50051
_PROXY_PORT = 8000
_GRPC_STARTUP_POLLS = 120  # 5 s × 120 = 600 s max
_GRPC_POLL_INTERVAL_S = 5
_PROXY_STARTUP_POLLS = 30  # 1 s × 30 = 30 s max
_PROXY_POLL_INTERVAL_S = 1
_REQUEST_TIMEOUT_S = 60.0
_FUNCTION_TIMEOUT_S = 900

_SMOKE_MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is 2 + 2?"},
]

app = modal.App("vllm-grpc-frontend-smoke")

_MODEL_VOLUME = modal.Volume.from_name("vllm-grpc-model-weights", create_if_missing=False)

_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        f"vllm=={_VLLM_VERSION}",
        "grpcio>=1.65",
        "grpcio-tools>=1.65",
        "fastapi>=0.115",
        "uvicorn[standard]>=0.30",
        "httpx>=0.27",
    )
    .add_local_dir("proto", "/build/proto", copy=True)
    .add_local_dir("packages/gen", "/build/packages/gen", copy=True)
    .add_local_dir("packages/frontend", "/build/packages/frontend", copy=True)
    .add_local_dir("packages/proxy", "/build/packages/proxy", copy=True)
    .run_commands(
        "python -m grpc_tools.protoc"
        " -I /build/proto"
        " --python_out=/build/packages/gen/src"
        " --grpc_python_out=/build/packages/gen/src"
        " /build/proto/vllm_grpc/v1/health.proto"
        " /build/proto/vllm_grpc/v1/chat.proto",
        "pip install /build/packages/gen",
        "pip install /build/packages/frontend",
        "pip install /build/packages/proxy",
    )
)


@app.function(
    gpu="A10G",
    image=_image,
    volumes={_MODEL_PATH: _MODEL_VOLUME},
    timeout=_FUNCTION_TIMEOUT_S,
)
def smoke_test() -> dict[str, object]:
    """Run proxy→gRPC→vLLM smoke test inside the Modal container."""
    import os
    import subprocess
    import time as _time

    import grpc
    import httpx
    from vllm_grpc.v1 import health_pb2, health_pb2_grpc  # type: ignore[import-untyped]

    frontend_proc: subprocess.Popen[bytes] | None = None
    proxy_proc: subprocess.Popen[bytes] | None = None

    def _kill_all() -> None:
        for proc in (proxy_proc, frontend_proc):
            if proc is not None and proc.poll() is None:
                proc.kill()

    t_start = _time.monotonic()

    # ── Step 1: start gRPC frontend ──────────────────────────────────────────
    env = {
        **os.environ,
        "MODEL_NAME": _MODEL_PATH,
        "FRONTEND_HOST": "0.0.0.0",
        "FRONTEND_PORT": str(_GRPC_PORT),
    }
    frontend_proc = subprocess.Popen(
        ["python", "-m", "vllm_grpc_frontend.main"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # ── Step 2: poll gRPC health ─────────────────────────────────────────────
    grpc_addr = f"localhost:{_GRPC_PORT}"
    grpc_ready = False
    for _ in range(_GRPC_STARTUP_POLLS):
        _time.sleep(_GRPC_POLL_INTERVAL_S)
        if frontend_proc.poll() is not None:
            return {
                "ok": False,
                "error": "gRPC frontend process exited unexpectedly during startup",
                "cold_start_s": _time.monotonic() - t_start,
                "request_latency_s": 0.0,
                "completion_text": None,
                "model": _MODEL_PATH,
                "seed": 42,
                "max_tokens": 20,
            }
        try:
            with grpc.insecure_channel(grpc_addr) as channel:
                stub = health_pb2_grpc.HealthStub(channel)
                stub.Ping(health_pb2.HealthRequest(), timeout=2.0)
            grpc_ready = True
            break
        except grpc.RpcError:
            pass

    cold_start_s = _time.monotonic() - t_start
    if not grpc_ready:
        _kill_all()
        return {
            "ok": False,
            "error": (
                f"gRPC server did not become healthy within"
                f" {_GRPC_STARTUP_POLLS * _GRPC_POLL_INTERVAL_S}s"
            ),
            "cold_start_s": cold_start_s,
            "request_latency_s": 0.0,
            "completion_text": None,
            "model": _MODEL_PATH,
            "seed": 42,
            "max_tokens": 20,
        }

    # ── Step 3: start proxy ───────────────────────────────────────────────────
    proxy_env = {**os.environ, "FRONTEND_ADDR": grpc_addr}
    proxy_proc = subprocess.Popen(
        ["uvicorn", "vllm_grpc_proxy.main:app", "--host", "0.0.0.0", "--port", str(_PROXY_PORT)],
        env=proxy_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # ── Step 4: poll proxy /healthz ───────────────────────────────────────────
    proxy_url = f"http://localhost:{_PROXY_PORT}"
    proxy_ready = False
    for _ in range(_PROXY_STARTUP_POLLS):
        _time.sleep(_PROXY_POLL_INTERVAL_S)
        if proxy_proc.poll() is not None:
            _kill_all()
            return {
                "ok": False,
                "error": "Proxy process exited unexpectedly during startup",
                "cold_start_s": cold_start_s,
                "request_latency_s": 0.0,
                "completion_text": None,
                "model": _MODEL_PATH,
                "seed": 42,
                "max_tokens": 20,
            }
        try:
            r = httpx.get(f"{proxy_url}/healthz", timeout=2.0)
            if r.status_code == 200:
                proxy_ready = True
                break
        except Exception:
            pass

    if not proxy_ready:
        _kill_all()
        return {
            "ok": False,
            "error": (
                f"Proxy did not become healthy within"
                f" {_PROXY_STARTUP_POLLS * _PROXY_POLL_INTERVAL_S}s"
            ),
            "cold_start_s": cold_start_s,
            "request_latency_s": 0.0,
            "completion_text": None,
            "model": _MODEL_PATH,
            "seed": 42,
            "max_tokens": 20,
        }

    # ── Step 5: send smoke-test request ──────────────────────────────────────
    t_req = _time.monotonic()
    try:
        response = httpx.post(
            f"{proxy_url}/v1/chat/completions",
            json={
                "model": _MODEL,
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

    # ── Step 6: verify and clean up ───────────────────────────────────────────
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
