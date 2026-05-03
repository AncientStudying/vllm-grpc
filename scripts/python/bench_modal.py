#!/usr/bin/env python3
"""Sequential benchmark orchestration: REST and gRPC deployments on Modal A10G.

Runs both the vLLM native REST endpoint and the proxy→gRPC frontend sequentially,
collects harness results for each, and writes a head-to-head comparison report to
docs/benchmarks/.  No manual steps are required between the two deployments.

Usage (requires Modal token and pre-staged weights — see make download-weights):
    make bench-modal
    # or directly:
    uv run --with modal modal run scripts/python/bench_modal.py

Exit codes:
    0  Both runs completed; all output files written.
    1  Deployment failure, harness error, or proxy startup failure.

See specs/007-modal-real-baselines/plan.md for architecture notes.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import modal

# ── Constants ─────────────────────────────────────────────────────────────────

_VLLM_VERSION = "0.20.0"
_MODEL_NAME = "Qwen/Qwen3-0.6B"  # alias sent to vLLM via --served-model-name; must match corpus
_MODEL_PATH = "/mnt/weights"
_REST_PORT = 8000
_GRPC_PORT = 50051
_FUNCTION_TIMEOUT_S = 3600
_STOP_CHECK_INTERVAL_S = 5
_REST_STARTUP_POLLS = 120  # 5 s × 120 = 600 s max
_REST_POLL_INTERVAL_S = 5
_GRPC_STARTUP_POLLS = 120
_GRPC_POLL_INTERVAL_S = 5
_ADDR_POLL_TIMEOUT_S = 600
_PROXY_READY_POLLS = 20
_PROXY_POLL_INTERVAL_S = 1

# modal.Dict shared namespace (separate from modal_frontend_serve.py's "vllm-grpc-serve")
_DICT_NAME = "vllm-grpc-bench-modal"

# Identical corpus/concurrency enforced for both runs (R-006)
_CORPUS_PATH = "tools/benchmark/corpus/chat_nonstreaming.json"
_CONCURRENCY = "1,4,8"

_BENCH_OUTPUT_DIR = Path("bench-results")
_DOCS_BENCHMARKS = Path("docs/benchmarks")
_RESULTS_DIR = _BENCH_OUTPUT_DIR
_GRPC_DIRECT_RESULTS = _RESULTS_DIR / "results-grpc-direct.json"

# ── Modal app + shared resources ──────────────────────────────────────────────

app = modal.App("vllm-grpc-bench-modal")

_MODEL_VOLUME = modal.Volume.from_name("vllm-grpc-model-weights", create_if_missing=False)

# REST image: vLLM REST server + httpx for health polling
_rest_image = modal.Image.debian_slim(python_version="3.12").pip_install(
    f"vllm=={_VLLM_VERSION}",
    "httpx>=0.27",
)

# gRPC image: same as modal_frontend_serve.py (vLLM + grpcio + frontend wheel)
_grpc_image = (
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


# ── REST serve function ───────────────────────────────────────────────────────


@app.function(
    gpu="A10G",
    image=_rest_image,
    volumes={_MODEL_PATH: _MODEL_VOLUME},
    timeout=_FUNCTION_TIMEOUT_S,
)
def serve_rest_for_bench() -> dict[str, object]:
    """Start vLLM REST server, expose via TCP tunnel, block until stop signal."""
    import subprocess as _sub
    import time as _time

    import httpx as _httpx

    server_proc: _sub.Popen[bytes] | None = None

    def _kill_server() -> None:
        if server_proc is not None and server_proc.poll() is None:
            server_proc.kill()

    t_start = _time.monotonic()

    server_proc = _sub.Popen(
        [
            "python",
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--model",
            _MODEL_PATH,
            "--served-model-name",
            _MODEL_NAME,
            "--port",
            str(_REST_PORT),
            "--enable-prompt-embeds",
        ],
        stdout=_sub.DEVNULL,
        stderr=_sub.DEVNULL,
    )

    server_url = f"http://localhost:{_REST_PORT}"
    server_ready = False
    for _ in range(_REST_STARTUP_POLLS):
        _time.sleep(_REST_POLL_INTERVAL_S)
        if server_proc.poll() is not None:
            return {
                "ok": False,
                "error": "vLLM REST server exited unexpectedly during startup",
                "cold_start_s": _time.monotonic() - t_start,
            }
        try:
            r = _httpx.get(f"{server_url}/health", timeout=2.0)
            if r.status_code == 200:
                server_ready = True
                break
        except Exception:
            pass

    cold_start_s = _time.monotonic() - t_start
    if not server_ready:
        _kill_server()
        return {
            "ok": False,
            "error": (
                f"vLLM REST server did not become healthy within"
                f" {_REST_STARTUP_POLLS * _REST_POLL_INTERVAL_S}s"
            ),
            "cold_start_s": cold_start_s,
        }

    # modal.Dict API uses dynamic attribute access — suppress mypy warnings
    d = modal.Dict.from_name(_DICT_NAME, create_if_missing=True)
    with modal.forward(_REST_PORT, unencrypted=True) as tunnel:
        host, port = tunnel.tcp_socket
        d.put("rest_addr", f"{host}:{port}")
        d.put("rest_cold_start_s", cold_start_s)

        deadline = _time.monotonic() + (_FUNCTION_TIMEOUT_S - cold_start_s - 60)
        while _time.monotonic() < deadline:
            stop: object = d.get("rest_stop")
            if stop:
                break
            _time.sleep(_STOP_CHECK_INTERVAL_S)

    _kill_server()
    for key in ("rest_addr", "rest_cold_start_s", "rest_stop"):
        d.pop(key, None)
    return {"ok": True, "error": None, "cold_start_s": cold_start_s}


# ── gRPC serve function ───────────────────────────────────────────────────────


@app.function(
    gpu="A10G",
    image=_grpc_image,
    volumes={_MODEL_PATH: _MODEL_VOLUME},
    timeout=_FUNCTION_TIMEOUT_S,
)
def serve_grpc_for_bench() -> dict[str, object]:
    """Start gRPC frontend, expose via TCP tunnel, block until stop signal."""
    import os as _os
    import subprocess as _sub
    import time as _time

    import grpc
    from vllm_grpc.v1 import health_pb2, health_pb2_grpc  # type: ignore[import-untyped]

    frontend_proc: _sub.Popen[bytes] | None = None

    def _kill_frontend() -> None:
        if frontend_proc is not None and frontend_proc.poll() is None:
            frontend_proc.kill()

    t_start = _time.monotonic()

    env = {
        **_os.environ,
        "MODEL_NAME": _MODEL_PATH,
        "FRONTEND_HOST": "0.0.0.0",
        "FRONTEND_PORT": str(_GRPC_PORT),
    }
    frontend_proc = _sub.Popen(
        ["python", "-m", "vllm_grpc_frontend.main"],
        env=env,
        stdout=_sub.PIPE,
        stderr=_sub.STDOUT,
    )

    grpc_local = f"localhost:{_GRPC_PORT}"
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
                    "gRPC frontend exited unexpectedly during startup.\n"
                    + out.decode(errors="replace")[-2000:]
                ),
                "cold_start_s": _time.monotonic() - t_start,
            }
        try:
            with grpc.insecure_channel(grpc_local) as ch:
                stub = health_pb2_grpc.HealthStub(ch)
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

    # modal.Dict API uses dynamic attribute access — suppress mypy warnings
    d = modal.Dict.from_name(_DICT_NAME, create_if_missing=True)
    with modal.forward(_GRPC_PORT, unencrypted=True) as tunnel:
        host, port = tunnel.tcp_socket
        d.put("grpc_addr", f"{host}:{port}")
        d.put("grpc_cold_start_s", cold_start_s)

        deadline = _time.monotonic() + (_FUNCTION_TIMEOUT_S - cold_start_s - 60)
        while _time.monotonic() < deadline:
            stop: object = d.get("grpc_stop")
            if stop:
                break
            _time.sleep(_STOP_CHECK_INTERVAL_S)

    _kill_frontend()
    for key in ("grpc_addr", "grpc_cold_start_s", "grpc_stop"):
        d.pop(key, None)
    return {"ok": True, "error": None, "cold_start_s": cold_start_s}


# ── Local helpers ─────────────────────────────────────────────────────────────


def _poll_for_addr(d: Any, key: str, label: str) -> str:
    t_poll = time.monotonic()
    while True:
        val: object = d.get(key)
        if isinstance(val, str) and val:
            return val
        if time.monotonic() - t_poll > _ADDR_POLL_TIMEOUT_S:
            print(
                f"[FAIL] Timed out waiting for {label} tunnel address"
                f" after {_ADDR_POLL_TIMEOUT_S}s",
                file=sys.stderr,
            )
            sys.exit(1)
        time.sleep(2)


def _run_harness(proxy_url: str, native_url: str, output_dir: Path) -> Path:
    """Run benchmark harness subprocess; return path to results.json or exit 1."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "vllm_grpc_bench",
            "--proxy-url",
            proxy_url,
            "--native-url",
            native_url,
            "--corpus",
            _CORPUS_PATH,
            "--concurrency",
            _CONCURRENCY,
            "--output-dir",
            str(output_dir),
        ],
        check=False,
    )
    if result.returncode != 0:
        print(f"[FAIL] Harness subprocess exited with code {result.returncode}", file=sys.stderr)
        sys.exit(1)
    results_path = output_dir / "results.json"
    if not results_path.exists():
        print("[FAIL] Harness did not produce results.json", file=sys.stderr)
        sys.exit(1)
    return results_path


# ── Local entrypoint ──────────────────────────────────────────────────────────


@app.local_entrypoint()
def main() -> None:
    import asyncio

    from vllm_grpc_bench.compare import compare_cross, compare_three_way
    from vllm_grpc_bench.io import load_run
    from vllm_grpc_bench.reporter import write_cross_run_md, write_summary_md, write_three_way_md
    from vllm_grpc_bench.runner import (
        run_grpc_target,
        run_grpc_target_streaming,
        run_target_streaming,
    )

    # modal.Dict API uses dynamic attribute access — suppress mypy warnings
    d = modal.Dict.from_name(_DICT_NAME, create_if_missing=True)

    # Clear stale keys from any previous crashed run
    for key in (
        "rest_addr",
        "rest_cold_start_s",
        "rest_stop",
        "grpc_addr",
        "grpc_cold_start_s",
        "grpc_stop",
    ):
        d.pop(key, None)

    _BENCH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── REST phase ────────────────────────────────────────────────────────────
    print("[REST] Spawning Modal REST serve function...")
    serve_rest_for_bench.spawn()

    print(f"[REST] Waiting for tunnel address (timeout {_ADDR_POLL_TIMEOUT_S}s)...")
    rest_addr = _poll_for_addr(d, "rest_addr", "REST")
    rest_url = f"http://{rest_addr}"

    rest_cold_raw: object = d.get("rest_cold_start_s")
    rest_cold_start_s: float | None = (
        float(rest_cold_raw) if isinstance(rest_cold_raw, (int, float)) else None
    )

    print(f"[REST] Tunnel: {rest_addr}")
    if rest_cold_start_s is not None:
        print(f"[REST] Cold start: {rest_cold_start_s:.1f}s")

    rest_results_path: Path
    with tempfile.TemporaryDirectory() as tmp:
        print("[REST] Running harness...")
        result_json = _run_harness(rest_url, rest_url, Path(tmp))
        rest_results_path = _BENCH_OUTPUT_DIR / "results-rest.json"
        shutil.copy(result_json, rest_results_path)

    print("[REST] Non-streaming run complete. Keeping REST alive for streaming phase.\n")

    # ── gRPC phase ────────────────────────────────────────────────────────────
    print("[gRPC] Spawning Modal gRPC serve function...")
    serve_grpc_for_bench.spawn()

    print(f"[gRPC] Waiting for tunnel address (timeout {_ADDR_POLL_TIMEOUT_S}s)...")
    grpc_addr = _poll_for_addr(d, "grpc_addr", "gRPC")

    grpc_cold_raw: object = d.get("grpc_cold_start_s")
    grpc_cold_start_s: float | None = (
        float(grpc_cold_raw) if isinstance(grpc_cold_raw, (int, float)) else None
    )

    print(f"[gRPC] Tunnel: {grpc_addr}")
    if grpc_cold_start_s is not None:
        print(f"[gRPC] Cold start: {grpc_cold_start_s:.1f}s")

    # Start local proxy subprocess pointing at the gRPC tunnel
    print(f"[gRPC] Starting local proxy → {grpc_addr}")
    proxy_env = {**os.environ, "FRONTEND_ADDR": grpc_addr}
    proxy_proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "vllm_grpc_proxy.main:app", "--host", "0.0.0.0", "--port", "8000"],
        env=proxy_env,
    )

    # Wait for proxy /healthz to be ready
    proxy_url = "http://localhost:8000"
    proxy_ready = False
    for _ in range(_PROXY_READY_POLLS):
        time.sleep(_PROXY_POLL_INTERVAL_S)
        try:
            r = httpx.get(f"{proxy_url}/healthz", timeout=1.0)
            if r.status_code == 200:
                proxy_ready = True
                break
        except Exception:
            pass

    if not proxy_ready:
        proxy_proc.terminate()
        d.put("grpc_stop", True)
        print("[FAIL] Local proxy did not become healthy", file=sys.stderr)
        sys.exit(1)

    grpc_results_path: Path
    phase6_comparison_path: Path | None = None
    import socket
    import subprocess as _sub
    from datetime import UTC
    from datetime import datetime as _dt

    from vllm_grpc_bench.corpus import load_corpus
    from vllm_grpc_bench.metrics import (
        BenchmarkRun,
        RequestResult,
        RunMeta,
        compute_summaries,
    )

    corpus_samples = load_corpus(Path(_CORPUS_PATH))
    concurrency_levels = [int(c) for c in _CONCURRENCY.split(",")]

    try:
        git_sha = (
            _sub.check_output(["git", "rev-parse", "HEAD"], stderr=_sub.DEVNULL).decode().strip()
        )
    except Exception:
        git_sha = "unknown"

    try:
        with tempfile.TemporaryDirectory() as tmp:
            print("[gRPC] Running harness...")
            result_json = _run_harness(proxy_url, proxy_url, Path(tmp))
            grpc_results_path = _BENCH_OUTPUT_DIR / "results-grpc.json"
            shutil.copy(result_json, grpc_results_path)

        # ── gRPC-direct phase (proxy + Modal deployments still alive) ─────────
        print("[gRPC-direct] Running harness...")
        all_direct: list[RequestResult] = []
        for conc in concurrency_levels:
            print(f"[gRPC-direct]   concurrency={conc} ...")
            direct_results = asyncio.run(run_grpc_target(grpc_addr, corpus_samples, conc, 60.0))
            all_direct.extend(direct_results)

        grpc_direct_meta = RunMeta(
            timestamp=_dt.now(tz=UTC).isoformat(),
            git_sha=git_sha,
            hostname=socket.gethostname(),
            corpus_path=_CORPUS_PATH,
            concurrency_levels=concurrency_levels,
            proxy_url="N/A",
            native_url=grpc_addr,
            gpu_type="A10G",
            cold_start_s=grpc_cold_start_s,
        )
        grpc_direct_summaries = compute_summaries(all_direct)
        grpc_direct_run = BenchmarkRun(
            meta=grpc_direct_meta,
            summaries=grpc_direct_summaries,
            raw_results=all_direct,
        )
        _GRPC_DIRECT_RESULTS.parent.mkdir(parents=True, exist_ok=True)
        _GRPC_DIRECT_RESULTS.write_text(json.dumps(dataclasses.asdict(grpc_direct_run), indent=2))
        print(f"[gRPC-direct] Results written to {_GRPC_DIRECT_RESULTS}")

        # ── Streaming phase (REST + gRPC proxy both still alive) ──────────────
        print("[STREAM] Running streaming benchmark phase...")

        all_stream_rest: list[RequestResult] = []
        all_stream_proxy: list[RequestResult] = []
        all_stream_direct: list[RequestResult] = []

        for conc in concurrency_levels:
            print(f"[STREAM]   REST streaming @ concurrency={conc} ...")
            all_stream_rest.extend(
                asyncio.run(run_target_streaming("native", rest_url, corpus_samples, conc, 60.0))
            )
            print(f"[STREAM]   gRPC-proxy streaming @ concurrency={conc} ...")
            all_stream_proxy.extend(
                asyncio.run(run_target_streaming("proxy", proxy_url, corpus_samples, conc, 60.0))
            )
            print(f"[STREAM]   gRPC-direct streaming @ concurrency={conc} ...")
            all_stream_direct.extend(
                asyncio.run(run_grpc_target_streaming(grpc_addr, corpus_samples, conc, 60.0))
            )

        print("[STREAM] Streaming benchmark complete.\n")

        # ── Phase 6 completions benchmark ────────────────────────────────────
        print("[COMPLETIONS] Running Phase 6 completions wire-size benchmark...")

        from vllm_grpc_bench.corpus import load_completions_corpus
        from vllm_grpc_bench.reporter import write_wire_size_comparison_md
        from vllm_grpc_bench.runner import (
            run_completions_grpc_direct,
            run_completions_grpc_direct_embeds,
            run_completions_native_embeds,
            run_completions_native_text,
            run_completions_proxy_embeds,
            run_completions_proxy_text,
        )

        all_completions: list[RequestResult] = []

        # Text-prompt path: native REST + proxy REST + gRPC-direct
        try:
            text_samples = load_completions_corpus("text")
            print(f"[COMPLETIONS] Loaded {len(text_samples)} text samples.")
            for conc in concurrency_levels:
                print(f"[COMPLETIONS]   native-REST text @ concurrency={conc} ...")
                all_completions.extend(
                    asyncio.run(run_completions_native_text(rest_url, text_samples, conc, 60.0))
                )
            for conc in concurrency_levels:
                print(f"[COMPLETIONS]   proxy-REST text @ concurrency={conc} ...")
                all_completions.extend(
                    asyncio.run(run_completions_proxy_text(proxy_url, text_samples, conc, 60.0))
                )
            for conc in concurrency_levels:
                print(f"[COMPLETIONS]   gRPC-direct text @ concurrency={conc} ...")
                all_completions.extend(
                    asyncio.run(run_completions_grpc_direct(grpc_addr, text_samples, conc, 60.0))
                )
        except FileNotFoundError as exc:
            print(f"[COMPLETIONS] Skipping text corpus: {exc}", file=sys.stderr)

        # Embed-prompt path: native REST + proxy REST + gRPC-direct (skipped if no manifest)
        try:
            embed_samples = load_completions_corpus("embeds")
            print(f"[COMPLETIONS] Loaded {len(embed_samples)} embed samples.")
            for conc in concurrency_levels:
                print(f"[COMPLETIONS]   native-REST embeds @ concurrency={conc} ...")
                all_completions.extend(
                    asyncio.run(run_completions_native_embeds(rest_url, embed_samples, conc, 60.0))
                )
            for conc in concurrency_levels:
                print(f"[COMPLETIONS]   proxy-REST embeds @ concurrency={conc} ...")
                all_completions.extend(
                    asyncio.run(run_completions_proxy_embeds(proxy_url, embed_samples, conc, 60.0))
                )
            for conc in concurrency_levels:
                print(f"[COMPLETIONS]   gRPC-direct embeds @ concurrency={conc} ...")
                all_completions.extend(
                    asyncio.run(
                        run_completions_grpc_direct_embeds(grpc_addr, embed_samples, conc, 60.0)
                    )
                )
        except FileNotFoundError as exc:
            print(
                f"[COMPLETIONS] Skipping embed corpus (run gen_embed_corpus.py first): {exc}",
                file=sys.stderr,
            )
        except ImportError as exc:
            print(
                f"[COMPLETIONS] Skipping embed corpus (torch not available): {exc}",
                file=sys.stderr,
            )

        if all_completions:
            completions_summaries = compute_summaries(all_completions)
            phase6_comparison_path = _DOCS_BENCHMARKS / "phase-6-completions-comparison.md"
            write_wire_size_comparison_md(completions_summaries, phase6_comparison_path)
            print(f"[COMPLETIONS] Report written to {phase6_comparison_path}")
        else:
            print("[COMPLETIONS] No completions results collected — skipping report.")

    finally:
        print("[gRPC] Stopping local proxy.")
        proxy_proc.terminate()
        try:
            proxy_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proxy_proc.kill()

    print("[REST] Sending stop signal.")
    d.put("rest_stop", True)
    print("[REST] Deployment tearing down.")

    print("[gRPC] All runs complete. Sending stop signal.")
    d.put("grpc_stop", True)
    print("[gRPC] Deployment tearing down.\n")

    # ── Comparison + output files ─────────────────────────────────────────────
    print("[COMPARE] Loading result files...")
    rest_run = load_run(rest_results_path)
    grpc_run = load_run(grpc_results_path)

    # Attach Modal traceability metadata gathered from modal.Dict
    rest_run.meta.cold_start_s = rest_cold_start_s
    rest_run.meta.gpu_type = "A10G"
    grpc_run.meta.cold_start_s = grpc_cold_start_s
    grpc_run.meta.gpu_type = "A10G"

    print("[COMPARE] Computing cross-run comparison...")
    report = compare_cross(rest_run, grpc_run, label_a="REST", label_b="gRPC")

    print("[COMPARE] Computing three-way comparison...")
    three_way_report = compare_three_way(
        rest_run,
        grpc_run,
        grpc_direct_run,
        label_a="REST",
        label_b="gRPC-proxy",
        label_c="gRPC-direct",
    )

    _DOCS_BENCHMARKS.mkdir(parents=True, exist_ok=True)

    # REST baseline files — serialize in-memory run (has gpu_type/cold_start_s attached)
    rest_baseline_json = _DOCS_BENCHMARKS / "phase-3-modal-rest-baseline.json"
    rest_baseline_json.write_text(json.dumps(dataclasses.asdict(rest_run), indent=2))
    rest_md_dir = _BENCH_OUTPUT_DIR / "rest"
    write_summary_md(rest_run, rest_md_dir)
    rest_baseline_md = _DOCS_BENCHMARKS / "phase-3-modal-rest-baseline.md"
    shutil.copy(rest_md_dir / "summary.md", rest_baseline_md)

    # gRPC baseline files — serialize in-memory run (has gpu_type/cold_start_s attached)
    grpc_baseline_json = _DOCS_BENCHMARKS / "phase-3-modal-grpc-baseline.json"
    grpc_baseline_json.write_text(json.dumps(dataclasses.asdict(grpc_run), indent=2))
    grpc_md_dir = _BENCH_OUTPUT_DIR / "grpc"
    write_summary_md(grpc_run, grpc_md_dir)
    grpc_baseline_md = _DOCS_BENCHMARKS / "phase-3-modal-grpc-baseline.md"
    shutil.copy(grpc_md_dir / "summary.md", grpc_baseline_md)

    # Comparison report (phase-3 two-way)
    comparison_path = _DOCS_BENCHMARKS / "phase-3-modal-comparison.md"
    write_cross_run_md(report, comparison_path)

    # Phase 4.2 output files
    rest_42_json = _DOCS_BENCHMARKS / "phase-4.2-rest-baseline.json"
    rest_42_json.write_text(json.dumps(dataclasses.asdict(rest_run), indent=2))

    grpc_proxy_42_json = _DOCS_BENCHMARKS / "phase-4.2-grpc-proxy-baseline.json"
    grpc_proxy_42_json.write_text(json.dumps(dataclasses.asdict(grpc_run), indent=2))

    grpc_direct_42_json = _DOCS_BENCHMARKS / "phase-4.2-grpc-direct-baseline.json"
    grpc_direct_42_json.write_text(json.dumps(dataclasses.asdict(grpc_direct_run), indent=2))

    grpc_direct_42_md = _DOCS_BENCHMARKS / "phase-4.2-grpc-direct-baseline.md"
    write_summary_md(grpc_direct_run, _BENCH_OUTPUT_DIR / "grpc-direct")
    grpc_direct_md_src = _BENCH_OUTPUT_DIR / "grpc-direct" / "summary.md"
    shutil.copy(grpc_direct_md_src, grpc_direct_42_md)

    three_way_path = _DOCS_BENCHMARKS / "phase-4.2-three-way-comparison.md"
    write_three_way_md(three_way_report, three_way_path)

    # ── Phase 5 streaming report ──────────────────────────────────────────────
    stream_ts = _dt.now(tz=UTC).isoformat()
    stream_git_sha = git_sha

    def _make_stream_run(results: list[RequestResult], url: str) -> BenchmarkRun:
        meta = RunMeta(
            timestamp=stream_ts,
            git_sha=stream_git_sha,
            hostname=socket.gethostname(),
            corpus_path=_CORPUS_PATH,
            concurrency_levels=concurrency_levels,
            proxy_url=url,
            native_url=url,
            gpu_type="A10G",
        )
        return BenchmarkRun(meta=meta, summaries=compute_summaries(results), raw_results=results)

    stream_rest_run = _make_stream_run(all_stream_rest, rest_url)
    stream_proxy_run = _make_stream_run(all_stream_proxy, proxy_url)
    stream_direct_run = _make_stream_run(all_stream_direct, grpc_addr)

    stream_three_way = compare_three_way(
        stream_rest_run,
        stream_proxy_run,
        stream_direct_run,
        label_a="REST",
        label_b="gRPC-proxy",
        label_c="gRPC-direct",
    )

    phase5_comparison_path = _DOCS_BENCHMARKS / "phase-5-streaming-comparison.md"
    write_three_way_md(stream_three_way, phase5_comparison_path)

    phase5_rest_json = _DOCS_BENCHMARKS / "phase-5-rest-streaming.json"
    phase5_rest_json.write_text(json.dumps(dataclasses.asdict(stream_rest_run), indent=2))

    phase5_proxy_json = _DOCS_BENCHMARKS / "phase-5-grpc-proxy-streaming.json"
    phase5_proxy_json.write_text(json.dumps(dataclasses.asdict(stream_proxy_run), indent=2))

    phase5_direct_json = _DOCS_BENCHMARKS / "phase-5-grpc-direct-streaming.json"
    phase5_direct_json.write_text(json.dumps(dataclasses.asdict(stream_direct_run), indent=2))

    print("Results written:")
    output_paths = [
        rest_results_path,
        grpc_results_path,
        _GRPC_DIRECT_RESULTS,
        rest_baseline_json,
        rest_baseline_md,
        grpc_baseline_json,
        grpc_baseline_md,
        comparison_path,
        rest_42_json,
        grpc_proxy_42_json,
        grpc_direct_42_json,
        grpc_direct_42_md,
        three_way_path,
        phase5_rest_json,
        phase5_proxy_json,
        phase5_direct_json,
        phase5_comparison_path,
    ]
    if phase6_comparison_path is not None:
        output_paths.append(phase6_comparison_path)
    for p in output_paths:
        print(f"  {p}")
