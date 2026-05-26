#!/usr/bin/env python3
"""monitor_m6_2_sweep.py — observe an in-flight M6.2 sweep.

Combines three signals into one re-runnable monitor (supersedes the two
one-off analyses written ad-hoc during the 2026-05-23 / 2026-05-24
validate sweeps):

1. **Sweep stderr log**: parse ``[m6_2 *]`` progress events emitted by
   ``m6_2_sweep._progress`` for block / tuple / anchor / sub-probe state.
   Computes ``blocks_done / expected_blocks`` and a per-tick throughput
   for ETA estimation.
2. **Process liveness**: optionally watch the orchestrator PID.
3. **Network throughput**: per-interface byte counters (``psutil``
   ``net_io_counters`` if available, else ``/proc/net/dev`` on Linux,
   else ``netstat -ibn`` on macOS) so the operator can confirm Modal
   traffic is flowing even when no new progress events have landed in
   the last interval.

Usage::

    python scripts/python/monitor_m6_2_sweep.py \\
        --log path/to/sweep.stderr.log \\
        [--pid 12345] [--json-out path/to/m6_2-token-budget-validate.json] \\
        [--interval 60] [--once] [--iface en0]

By default, prints one line per ``--interval`` seconds and exits when the
artifact JSON appears OR when the PID dies OR when stdin closes. Pass
``--once`` to print a single snapshot and exit (useful from cron).

Output format (one line per tick, parseable by downstream tools)::

    [YYYY-MM-DDTHH:MM:SSZ] elapsed=Xh Ym blocks=A/B (P%) tuple=C/D \\
        cell=<cell_id × max_tokens> recent_wall_p50_ms=Z eta=Xh Ym \\
        net_rate=N.MB/s alive=yes|no|unknown
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

# Match the `_progress` line format from m6_2_sweep:
#   [2026-05-24T13:20:39Z] [m6_2 TAG] k1=v1 k2=v2 ...
_PROGRESS_LINE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+\[m6_2\s+(?P<tag>[A-Z_]+)\]\s*(?P<fields>.*)$"
)


class ProgressEvent(NamedTuple):
    ts: str
    tag: str
    fields: dict[str, str]


def parse_progress_events(log_path: Path) -> list[ProgressEvent]:
    """Read the sweep stderr log and return every ``[m6_2 *]`` event,
    in file order. Lines that don't match the progress format are
    skipped silently (clock-anomaly lines, deploy noise, etc.)."""
    events: list[ProgressEvent] = []
    if not log_path.exists():
        return events
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return events
    for line in text.splitlines():
        m = _PROGRESS_LINE_RE.match(line)
        if not m:
            continue
        raw_fields = m.group("fields").strip()
        fields: dict[str, str] = {}
        for token in raw_fields.split():
            if "=" not in token:
                continue
            k, v = token.split("=", 1)
            fields[k] = v
        events.append(ProgressEvent(ts=m.group("ts"), tag=m.group("tag"), fields=fields))
    return events


def _parse_utc(ts: str) -> _dt.datetime | None:
    try:
        return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_artifact_present(
    json_path: Path | None,
    sweep_start_utc: str | None,
) -> bool:
    """Return ``True`` iff the artifact JSON at ``json_path`` was written
    AFTER the current sweep's ``SWEEP_START`` event.

    T075 fix: the pre-T075 monitor checked only ``path.exists()``, which
    false-positived when a previous (e.g. failed / preempted) sweep had
    left a stale artifact on disk. In ``--interval`` mode the auto-exit
    condition (``state.sweep_end_utc is not None AND artifact_present``)
    would then fire prematurely on a fresh sweep that hadn't yet
    overwritten the stale file — the operator would think the sweep was
    done when it was actually still in the sub-probe / artifact-write
    phase.

    The post-T075 predicate compares the file's mtime against the
    SWEEP_START UTC timestamp parsed from the live progress log. A file
    that predates the sweep's start by even one second is treated as
    stale and reports ``False``.

    Returns ``False`` when:

    * ``json_path`` is ``None`` (no artifact requested).
    * The file doesn't exist yet.
    * ``sweep_start_utc`` is ``None`` (the SWEEP_START event hasn't
      landed in the log yet — the monitor was launched before the
      sweep started its work).
    * The file's mtime predates the sweep_start_utc (stale leftover
      from a previous run).
    * The file's mtime is readable but the sweep_start_utc string is
      unparseable (defensive — refuse to claim presence on malformed
      input).
    """
    if json_path is None or not json_path.exists():
        return False
    if sweep_start_utc is None:
        return False
    start = _parse_utc(sweep_start_utc)
    if start is None:
        return False
    try:
        mtime = json_path.stat().st_mtime
    except OSError:
        return False
    start_unix = start.timestamp()
    return mtime > start_unix


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    return f"{h}h {m:02d}m"


def is_process_alive(pid: int) -> bool | None:
    """``True`` if the PID exists, ``False`` if not, ``None`` if the
    check is unsupported (Windows without psutil etc.)."""
    try:
        import os

        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack rights to signal it — counts as alive.
        return True
    except OSError:
        return None
    return True


def read_net_bytes(iface: str | None) -> int | None:
    """Cumulative bytes_sent + bytes_recv for ``iface`` (or all, if None).

    Returns ``None`` when no platform-supported reader is available.
    """
    try:
        import psutil  # type: ignore[import-untyped]

        counters = psutil.net_io_counters(pernic=True) if iface else psutil.net_io_counters()
        if iface:
            row = counters.get(iface)
            if row is None:
                return None
            return int(row.bytes_sent) + int(row.bytes_recv)
        return int(counters.bytes_sent) + int(counters.bytes_recv)
    except ImportError:
        pass
    # Linux fallback.
    proc_net = Path("/proc/net/dev")
    if proc_net.exists():
        try:
            total = 0
            for line in proc_net.read_text().splitlines()[2:]:
                if iface and not line.lstrip().startswith(f"{iface}:"):
                    continue
                parts = line.split()
                if len(parts) < 10:
                    continue
                # /proc/net/dev format: iface: recv_bytes recv_pkts ... xmit_bytes ...
                total += int(parts[1]) + int(parts[9])
            return total
        except (OSError, ValueError):
            return None
    # macOS fallback via netstat -ibn.
    netstat = shutil.which("netstat")
    if netstat is not None:
        try:
            out = subprocess.run(
                [netstat, "-ibn"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout
            total = 0
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) < 10:
                    continue
                if iface and parts[0] != iface:
                    continue
                # netstat -ibn columns:
                # Name Mtu Network Address Ipkts Ierrs Ibytes Opkts Oerrs Obytes ...
                try:
                    total += int(parts[6]) + int(parts[9])
                except (ValueError, IndexError):
                    continue
            return total
        except (subprocess.SubprocessError, OSError):
            return None
    return None


class SweepState(NamedTuple):
    sweep_start_utc: str | None
    sweep_end_utc: str | None
    mode: str | None
    expected_blocks: int | None
    expected_tuples: int | None
    blocks_done: int
    tuple_idx: int | None
    current_cell: str | None
    current_max_tokens: str | None
    last_block_wall_p50_ms: float | None
    last_event_ts: str | None
    subprobe_state: str  # 'pending' / 'running' / 'done'


def derive_sweep_state(events: list[ProgressEvent]) -> SweepState:
    """Fold a list of progress events into a single snapshot of where
    the sweep is. Tolerates duplicate / out-of-order lines (latest wins
    for scalars; counters take the max value seen)."""
    state: dict[str, Any] = {
        "sweep_start_utc": None,
        "sweep_end_utc": None,
        "mode": None,
        "expected_blocks": None,
        "expected_tuples": None,
        "blocks_done": 0,
        "tuple_idx": None,
        "current_cell": None,
        "current_max_tokens": None,
        "last_block_wall_p50_ms": None,
        "last_event_ts": None,
        "subprobe_state": "pending",
    }
    for ev in events:
        state["last_event_ts"] = ev.ts
        if ev.tag == "SWEEP_START":
            state["sweep_start_utc"] = ev.fields.get("utc") or ev.ts
            state["mode"] = ev.fields.get("mode")
            try:
                state["expected_blocks"] = int(ev.fields.get("expected_blocks", "0")) or None
                state["expected_tuples"] = int(ev.fields.get("expected_tuples", "0")) or None
            except ValueError:
                pass
        elif ev.tag == "TUPLE_START":
            i_field = ev.fields.get("i", "")
            if "/" in i_field:
                with contextlib.suppress(ValueError):
                    state["tuple_idx"] = int(i_field.split("/", 1)[0])
            state["current_cell"] = ev.fields.get("cell")
            state["current_max_tokens"] = ev.fields.get("max_tokens")
        elif ev.tag == "BLOCK_DONE":
            i_field = ev.fields.get("i", "")
            if "/" in i_field:
                try:
                    cur = int(i_field.split("/", 1)[0])
                    if cur > state["blocks_done"]:
                        state["blocks_done"] = cur
                except ValueError:
                    pass
            wall = ev.fields.get("wall_p50_ms")
            if wall and wall != "—":
                with contextlib.suppress(ValueError):
                    state["last_block_wall_p50_ms"] = float(wall)
        elif ev.tag == "SUBPROBE_START":
            state["subprobe_state"] = "running"
        elif ev.tag == "SUBPROBE_END":
            state["subprobe_state"] = "done"
        elif ev.tag == "SWEEP_END":
            state["sweep_end_utc"] = ev.fields.get("utc") or ev.ts
    return SweepState(**state)


def compute_eta_seconds(state: SweepState, now_utc: _dt.datetime) -> float | None:
    """Linear-extrapolation ETA: elapsed × (expected - done) / done.

    Returns ``None`` until at least one block has completed."""
    if not state.sweep_start_utc or not state.blocks_done or not state.expected_blocks:
        return None
    start = _parse_utc(state.sweep_start_utc)
    if start is None:
        return None
    elapsed = (now_utc - start).total_seconds()
    if elapsed <= 0 or state.blocks_done >= state.expected_blocks:
        return 0.0
    remaining_blocks = state.expected_blocks - state.blocks_done
    return elapsed * remaining_blocks / state.blocks_done


def format_status_line(
    *,
    now_utc: _dt.datetime,
    state: SweepState,
    net_rate_mbps: float | None,
    alive: bool | None,
    artifact_json_present: bool,
) -> str:
    """One-line status report. Designed so a cron-spawned grep can pull
    out fields without state across runs."""
    if state.sweep_start_utc:
        start = _parse_utc(state.sweep_start_utc)
        elapsed_s = (now_utc - start).total_seconds() if start else None
    else:
        elapsed_s = None

    if state.expected_blocks and state.blocks_done:
        pct = 100.0 * state.blocks_done / state.expected_blocks
        pct_str = f"({pct:.0f}%)"
    else:
        pct_str = "(—)"

    blocks = (
        f"{state.blocks_done}/{state.expected_blocks}"
        if state.expected_blocks
        else f"{state.blocks_done}/—"
    )
    tuple_str = (
        f"{state.tuple_idx}/{state.expected_tuples}"
        if state.tuple_idx and state.expected_tuples
        else "—"
    )
    cell_str = "—"
    if state.current_cell and state.current_max_tokens:
        cell_str = f"{state.current_cell}×{state.current_max_tokens}"

    eta_s = compute_eta_seconds(state, now_utc)

    alive_str = "unknown" if alive is None else ("yes" if alive else "no")

    net_str = f"{net_rate_mbps:.2f}MB/s" if net_rate_mbps is not None else "—"
    wall_str = (
        f"{state.last_block_wall_p50_ms:.0f}ms" if state.last_block_wall_p50_ms is not None else "—"
    )

    ts = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    artifact_str = "yes" if artifact_json_present else "no"
    return (
        f"[{ts}] elapsed={_fmt_duration(elapsed_s)} "
        f"blocks={blocks} {pct_str} tuple={tuple_str} cell={cell_str} "
        f"recent_wall_p50={wall_str} eta={_fmt_duration(eta_s)} "
        f"net_rate={net_str} subprobe={state.subprobe_state} "
        f"alive={alive_str} artifact={artifact_str}"
    )


def iter_ticks(interval_s: float, once: bool) -> Iterator[None]:
    """Yield once if ``--once``; else yield forever at ``--interval`` cadence."""
    while True:
        yield None
        if once:
            return
        time.sleep(interval_s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Monitor an in-flight M6.2 sweep via its progress log + optional PID + network rate."
        ),
    )
    parser.add_argument(
        "--log",
        type=Path,
        required=True,
        help="Path to the tee'd stderr log of the running sweep (read each tick).",
    )
    parser.add_argument(
        "--pid",
        type=int,
        default=None,
        help="Optional orchestrator PID for liveness checking.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help=(
            "Optional artifact JSON path. Monitor exits when this file "
            "appears (sweep wrote its output)."
        ),
    )
    parser.add_argument(
        "--iface",
        type=str,
        default=None,
        help="Optional network interface name (e.g. en0); defaults to all-interfaces total.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Seconds between progress prints (default 60s). Ignored under --once.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print one status line and exit (use this from cron / launchd).",
    )
    args = parser.parse_args(argv)

    last_net_bytes: int | None = None
    last_net_ts: float | None = None

    for _ in iter_ticks(args.interval, args.once):
        now_utc = _dt.datetime.now(_dt.UTC)
        now_perf = time.monotonic()

        events = parse_progress_events(args.log)
        state = derive_sweep_state(events)

        cur_net = read_net_bytes(args.iface)
        net_rate_mbps: float | None = None
        if cur_net is not None and last_net_bytes is not None and last_net_ts is not None:
            dt = now_perf - last_net_ts
            if dt > 0:
                net_rate_mbps = (cur_net - last_net_bytes) / dt / 1_000_000.0
        last_net_bytes = cur_net
        last_net_ts = now_perf

        alive = is_process_alive(args.pid) if args.pid else None
        # T075: artifact_present must be true ONLY when the on-disk file
        # was written AFTER the current sweep's SWEEP_START event.
        # ``compute_artifact_present`` enforces the mtime > start check so
        # a stale leftover from a previous (e.g. preempted) sweep doesn't
        # trip the --interval auto-exit prematurely. The
        # ``sweep_end_utc is not None`` gate is preserved so a fresh-but-
        # incomplete artifact (mid-write race) still reports False until
        # the sweep itself has signalled completion.
        artifact_present = state.sweep_end_utc is not None and compute_artifact_present(
            args.json_out, state.sweep_start_utc
        )

        line = format_status_line(
            now_utc=now_utc,
            state=state,
            net_rate_mbps=net_rate_mbps,
            alive=alive,
            artifact_json_present=artifact_present,
        )
        print(line, flush=True)

        # Exit conditions (only when running in --interval mode).
        if not args.once:
            if alive is False:
                exit_ts = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                print(
                    f"[{exit_ts}] orchestrator PID {args.pid} no longer alive — exiting monitor.",
                    flush=True,
                )
                return 0
            if state.sweep_end_utc is not None and artifact_present:
                exit_ts = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                print(
                    f"[{exit_ts}] sweep completed (SWEEP_END seen + artifact "
                    "present) — exiting monitor.",
                    flush=True,
                )
                return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
