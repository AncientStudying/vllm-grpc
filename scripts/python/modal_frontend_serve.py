#!/usr/bin/env python3
"""Long-lived Modal serve: deploys vllm-grpc-frontend on A10G with a TCP tunnel.

Starts the gRPC frontend on a Modal A10G container, opens a modal.forward() TCP
tunnel on port 50051, and publishes the tunnel address via modal.Dict so a
locally-running proxy can connect to it.  The developer exports FRONTEND_ADDR
from the printed address and runs `make run-proxy` in a second terminal.

The serve function blocks until a stop signal is received (via Ctrl+C in the
terminal running this script) or the 1-hour function timeout is reached.  No
generator/yield pattern is used — the function sleeps in a polling loop, which
keeps the modal.forward() context manager alive and the tunnel open.

Usage (requires Modal token and pre-staged weights — see make download-weights):
    make modal-serve-frontend
    # or directly:
    uv run --with modal modal run scripts/python/modal_frontend_serve.py

Exit codes:
    0  Teardown completed cleanly (Ctrl+C received).
    1  Tunnel address not available within _ADDR_POLL_TIMEOUT_S seconds.

See docs/decisions/0002-modal-deployment.md for architecture notes.
"""

from __future__ import annotations

import sys
import time

import modal

_VLLM_VERSION = "0.20.0"
_MODEL_PATH = "/mnt/weights"
_GRPC_PORT = 50051
_GRPC_STARTUP_POLLS = 120  # 5 s × 120 = 600 s max
_GRPC_POLL_INTERVAL_S = 5
_FUNCTION_TIMEOUT_S = 3600  # 1-hour max; guards against runaway GPU cost
_STOP_CHECK_INTERVAL_S = 5
_ADDR_POLL_TIMEOUT_S = 600  # local entrypoint gives up after this many seconds

# modal.Dict key names (shared between serve_frontend and main)
_DICT_NAME = "vllm-grpc-serve"
_DICT_KEY_ADDR = "frontend_addr"
_DICT_KEY_COLD_START = "cold_start_s"
_DICT_KEY_STOP = "stop_signal"

app = modal.App("vllm-grpc-frontend-serve")

_MODEL_VOLUME = modal.Volume.from_name("vllm-grpc-model-weights", create_if_missing=False)

# Image: same package set as modal_frontend_smoke.py EXCEPT:
#   - vllm-grpc-proxy NOT installed (proxy runs on the developer's local machine)
#   - uvicorn, fastapi, httpx NOT installed (not needed in the container)
_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        f"vllm=={_VLLM_VERSION}",
        "grpcio>=1.65",
        "grpcio-tools>=1.65",
    )
    .add_local_dir("proto", "/build/proto", copy=True)
    .add_local_dir("packages/gen", "/build/packages/gen", copy=True)
    .add_local_dir("packages/frontend", "/build/packages/frontend", copy=True)
    .run_commands(
        "python -m grpc_tools.protoc"
        " -I /build/proto"
        " --python_out=/build/packages/gen/src"
        " --grpc_python_out=/build/packages/gen/src"
        " /build/proto/vllm_grpc/v1/health.proto"
        " /build/proto/vllm_grpc/v1/chat.proto",
        "pip install /build/packages/gen",
        "pip install /build/packages/frontend",
    )
)


@app.function(
    gpu="A10G",
    image=_image,
    volumes={_MODEL_PATH: _MODEL_VOLUME},
    timeout=_FUNCTION_TIMEOUT_S,
)
def serve_frontend() -> dict[str, object]:
    """Start gRPC frontend, expose via TCP tunnel, block until stop signal."""
    import os
    import subprocess
    import time as _time

    import grpc
    from vllm_grpc.v1 import health_pb2, health_pb2_grpc  # type: ignore[import-untyped]

    frontend_proc: subprocess.Popen[bytes] | None = None

    def _kill_frontend() -> None:
        if frontend_proc is not None and frontend_proc.poll() is None:
            frontend_proc.kill()

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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # ── Step 2: poll gRPC health ─────────────────────────────────────────────
    grpc_addr = f"localhost:{_GRPC_PORT}"
    grpc_ready = False
    for _ in range(_GRPC_STARTUP_POLLS):
        _time.sleep(_GRPC_POLL_INTERVAL_S)
        if frontend_proc.poll() is not None:
            out = b""
            if frontend_proc.stdout:
                out = frontend_proc.stdout.read()
            return {
                "ok": False,
                "error": (
                    "gRPC frontend process exited unexpectedly during startup.\n"
                    + out.decode(errors="replace")[-2000:]
                ),
                "cold_start_s": _time.monotonic() - t_start,
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
        _kill_frontend()
        return {
            "ok": False,
            "error": (
                f"gRPC server did not become healthy within"
                f" {_GRPC_STARTUP_POLLS * _GRPC_POLL_INTERVAL_S}s"
            ),
            "cold_start_s": cold_start_s,
        }

    # ── Step 3: open tunnel, publish address via modal.Dict ──────────────────
    d = modal.Dict.from_name(_DICT_NAME, create_if_missing=True)
    with modal.forward(_GRPC_PORT, unencrypted=True) as tunnel:
        host, port = tunnel.tcp_socket
        d.put(_DICT_KEY_ADDR, f"{host}:{port}")
        d.put(_DICT_KEY_COLD_START, cold_start_s)

        # ── Step 4: sleep loop — tunnel stays open until exit ─────────────────
        # Reserve 60 s before the function timeout for cleanup.
        deadline = _time.monotonic() + (_FUNCTION_TIMEOUT_S - cold_start_s - 60)
        while _time.monotonic() < deadline:
            stop: object = d.get(_DICT_KEY_STOP)
            if stop:
                break
            _time.sleep(_STOP_CHECK_INTERVAL_S)
    # modal.forward() __exit__ runs here; tunnel is now closed.

    # ── Step 5: clean up ─────────────────────────────────────────────────────
    _kill_frontend()
    for key in (_DICT_KEY_ADDR, _DICT_KEY_COLD_START, _DICT_KEY_STOP):
        d.pop(key, None)

    return {"ok": True, "error": None, "cold_start_s": cold_start_s}


@app.local_entrypoint()
def main() -> None:
    # ── Step 1: clear stale entries from any previous crashed run ────────────
    d = modal.Dict.from_name(_DICT_NAME, create_if_missing=True)
    for key in (_DICT_KEY_ADDR, _DICT_KEY_COLD_START, _DICT_KEY_STOP):
        d.pop(key, None)

    # ── Step 2: spawn serve function as background task ──────────────────────
    print("[INFO] Deploying gRPC frontend to Modal A10G...")
    serve_frontend.spawn()

    # ── Step 3: poll for tunnel address ──────────────────────────────────────
    t_poll = time.monotonic()
    addr: str | None = None
    while True:
        val: object = d.get(_DICT_KEY_ADDR)
        if isinstance(val, str) and val:
            addr = val
            break
        if time.monotonic() - t_poll > _ADDR_POLL_TIMEOUT_S:
            print(
                f"[FAIL] Timed out waiting for tunnel address after {_ADDR_POLL_TIMEOUT_S}s",
                file=sys.stderr,
            )
            sys.exit(1)
        time.sleep(2)

    cold_start_raw: object = d.get(_DICT_KEY_COLD_START)
    cold_start_f = float(cold_start_raw) if isinstance(cold_start_raw, (int, float)) else 0.0

    # ── Step 4: print tunnel address for the developer ───────────────────────
    print(f"[INFO] cold_start_s = {cold_start_f:.1f}")
    print(f"[OK]   export FRONTEND_ADDR={addr}")
    print("[INFO] Set FRONTEND_ADDR and run: make run-proxy")
    print("[INFO] Press Ctrl+C to tear down.")

    # ── Step 5: block until Ctrl+C, then send teardown signal ────────────────
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] Sending teardown signal...")
        d.put(_DICT_KEY_STOP, True)
        print("[INFO] Container will stop within 30s. Exiting.")
