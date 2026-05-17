"""One-shot live traceroute probe for the spike/m6-1-roadmap-additions branch.

Spawns the M5.2 ``serve_bench`` MockEngine app on Modal eu-west-1, reads the
three tunnel URLs from the handshake ``modal.Dict``, runs ``traceroute``
against each from this Mac in parallel, then signals teardown.

Purpose: capture per-cohort network paths from a real deploy to confirm the
DNS/IP-range architectural evidence that ``rest_https_edge`` (`*.modal.run`)
routes through AWS us-east-1 anycast while ``rest_plain_tcp`` / gRPC
(`*.modal.host`) route directly to the worker region.

Estimated cost: ~$0.05 (CPU-only, ~60-90s wallclock).

Output: stdout-only — copy/paste into the spike's findings note. The script
itself is throwaway and is NOT a model for harness integration; M6.1.2 will
land the proper per-sweep traceroute probe.

Usage:
    cd <repo-root>
    uv run python docs/spikes/m6-1-roadmap-additions/traceroute_probe.py
"""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

# Import the deploy script's app + serve_bench. The script lives under
# scripts/python/ and isn't a Python package; add its parent to sys.path so
# the import works.
_SCRIPTS_DIR = Path("/Users/bsansom/projects/vllm-grpc/scripts/python")
sys.path.insert(0, str(_SCRIPTS_DIR))

import modal  # noqa: E402
from modal_bench_rest_grpc_server import _DICT_NAME, app, serve_bench  # noqa: E402

REGION = "eu-west-1"
TOKEN = os.environ.get("MODAL_BENCH_TOKEN", "spike-probe-token-not-used")
READY_TIMEOUT_S = 180.0
TRACE_HOPS_MAX = 18
TRACE_PER_HOP_TIMEOUT_S = 2
TRACE_PROBES_PER_HOP = 1


def _parse_url(url: str) -> tuple[str, int | None]:
    """Extract (host, port) from a URL of form
    ``tcp+plaintext://host:port`` / ``http://host:port`` / ``https://host``.
    """
    if url.startswith("tcp+plaintext://"):
        rest = url[len("tcp+plaintext://") :]
    elif url.startswith("http://"):
        rest = url[len("http://") :]
    elif url.startswith("https://"):
        rest = url[len("https://") :]
        if ":" not in rest:
            return rest, 443
    else:
        rest = url
    if ":" in rest:
        host, port_s = rest.rsplit(":", 1)
        return host, int(port_s)
    return rest, None


def _traceroute(host: str) -> str:
    """Run traceroute -n with short hop timeout. Returns combined stdout+stderr."""
    cmd = [
        "traceroute",
        "-n",  # no DNS for hops (faster, more deterministic)
        "-w",
        str(TRACE_PER_HOP_TIMEOUT_S),
        "-q",
        str(TRACE_PROBES_PER_HOP),
        "-m",
        str(TRACE_HOPS_MAX),
        host,
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=TRACE_HOPS_MAX * TRACE_PER_HOP_TIMEOUT_S + 10,
        check=False,
    )
    return f"$ {' '.join(shlex.quote(c) for c in cmd)}\n{proc.stdout}\n{proc.stderr}"


async def _wait_for_ready(d: modal.Dict, deadline: float) -> None:
    while time.monotonic() < deadline:
        if await d.get.aio("ready", default=False):
            return
        await asyncio.sleep(1.0)
    raise TimeoutError(f"serve_bench did not signal ready within {READY_TIMEOUT_S}s")


async def main() -> int:
    print(f"[probe] spawning serve_bench on {REGION}", flush=True)
    started = time.monotonic()

    # Use app.run() context manager so the spawned function is associated
    # with this app session.
    async with app.run.aio():
        call = await serve_bench.spawn.aio(token=TOKEN, region=REGION)
        print(f"[probe] spawned call={call.object_id}", flush=True)

        d = modal.Dict.from_name(_DICT_NAME, create_if_missing=True)
        deadline = time.monotonic() + READY_TIMEOUT_S
        try:
            await _wait_for_ready(d, deadline)
        except TimeoutError as exc:
            print(f"[probe] ERROR: {exc}", flush=True)
            return 1

        print(f"[probe] ready in {time.monotonic() - started:.1f}s", flush=True)

        urls = {
            "rest_https_edge": str(await d.get.aio("rest_https_edge_url", default="")),
            "rest_plain_tcp": str(await d.get.aio("rest_plain_tcp_url", default="")),
            "grpc": str(await d.get.aio("grpc", default="")),
        }
        for cohort, url in urls.items():
            print(f"[probe] {cohort:18s} = {url}", flush=True)

        # Resolve to (host, port) — traceroute only needs host.
        hosts: dict[str, tuple[str, int | None]] = {
            cohort: _parse_url(url) for cohort, url in urls.items() if url
        }

        # Run traceroute against each host in parallel via thread pool —
        # subprocess.run blocks, so we use asyncio.to_thread.
        print(
            f"\n[probe] starting traceroutes (max {TRACE_HOPS_MAX} hops, "
            f"{TRACE_PER_HOP_TIMEOUT_S}s/hop)…",
            flush=True,
        )
        results = await asyncio.gather(
            *(asyncio.to_thread(_traceroute, host) for _, (host, _) in hosts.items())
        )

        print("\n" + "=" * 72)
        for (cohort, (host, port)), result in zip(hosts.items(), results, strict=True):
            print(f"\n--- {cohort} (host={host} port={port}) ---")
            print(result)

        # Signal teardown so serve_bench exits cleanly (otherwise it holds
        # tunnels until _FUNCTION_TIMEOUT_S, wasting credits).
        await d.put.aio("teardown", True)
        print("[probe] teardown signaled; waiting for graceful exit…", flush=True)
        # We don't await `call.get()` because that would re-raise serve_bench's
        # return value; the function exits within 1-2s of teardown=True.

    print(f"[probe] total wallclock: {time.monotonic() - started:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
