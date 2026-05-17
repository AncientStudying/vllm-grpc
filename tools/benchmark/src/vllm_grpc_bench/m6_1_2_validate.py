"""M6.1.2 — Methodology Discipline: single CLI entry function for both
``--m6_1_2`` and ``--m6_1_2-validate`` mode flags.

Per ``contracts/cli.md`` "Dispatch wiring" + post-/speckit-analyze C1
remediation: both flags ship the same sweep shape (FR-024), so one entry
function handles both. The operator-intent distinction lives in the
``sweep_mode: Literal["full", "validate"]`` argument and is recorded in
``run_meta.sweep_mode`` on the published artifact.

This module owns:

* Argparse-to-config conversion (delegated to
  ``m6_1_2_sweep.build_config_from_args``).
* Modal-deploy orchestration (TODO at full integration — for this slice
  the function gracefully no-ops on ``--m6_1_2-skip-deploy``).
* Artifact persistence via ``m6_1_2_reporter.write_m6_1_2_report``.

The function returns ``int`` exit codes per ``contracts/cli.md`` "Exit
codes":

* ``0`` — sweep completed; artifact written.
* ``2`` — Modal deploy / handshake failure.
* ``5`` — sweep failed mid-run.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from vllm_grpc_bench.m6_1_2_sweep import (
    M6_1_2RPCDriver,
    build_config_from_args,
    run_m6_1_2_sweep,
    write_sweep_artifact,
)
from vllm_grpc_bench.m6_1_2_types import M6_1_2SweepMode


def run_m6_1_2(
    args: argparse.Namespace,
    *,
    sweep_mode: M6_1_2SweepMode,
    driver: M6_1_2RPCDriver | None = None,
) -> int:
    """Dispatch the M6.1.2 sweep.

    When ``args.m6_1_2_skip_deploy`` is True the caller MUST supply
    ``driver``; otherwise this is a Modal-backed sweep and the function
    will (in the full integration) build the driver via
    ``provide_m6_1_2_rpc_driver``. Modal-backed integration is out of
    scope for the in-session lint-chain slice — when ``skip_deploy`` is
    False and no driver is provided, the function returns exit code 2
    with a stderr message.
    """
    config = build_config_from_args(args, sweep_mode=sweep_mode)

    if driver is None:
        if not config.skip_deploy:
            print(
                "[m6_1_2] Modal-backed sweeps require integration that is "
                "scheduled for a follow-up commit; run with "
                "--m6_1_2-skip-deploy + an injected driver for now.",
                file=sys.stderr,
                flush=True,
            )
            return 2
        print(
            "[m6_1_2] --m6_1_2-skip-deploy was set but no driver was "
            "injected; cannot run a sweep without an RPC dispatcher.",
            file=sys.stderr,
            flush=True,
        )
        return 5

    try:
        artifact = asyncio.run(run_m6_1_2_sweep(config, driver=driver, network_probe_results=None))
    except Exception as exc:  # noqa: BLE001
        print(f"[m6_1_2] sweep failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 5

    write_sweep_artifact(artifact, config.md_out, config.json_out)
    return 0


__all__ = ["run_m6_1_2"]
