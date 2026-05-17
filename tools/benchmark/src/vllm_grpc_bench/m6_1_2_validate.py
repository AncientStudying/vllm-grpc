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
* Modal-deploy orchestration via ``provide_m6_endpoint`` +
  ``provide_m6_1_2_rpc_driver`` (the 4-cohort sibling of M6.1's
  ``provide_m6_1_rpc_driver``). The Modal deploy already publishes
  ``rest_https_edge_url`` / ``rest_plain_tcp_url`` / gRPC tunnel URL on
  the shared ``modal.Dict`` (M5.2-era wiring, confirmed by Spike #2);
  M6.1.2 reads those three keys, translates them into the handshake
  dict shape that ``run_topology_probe`` expects, and tears down on exit.
* Artifact persistence via ``m6_1_2_reporter.write_m6_1_2_report``.

The function returns ``int`` exit codes per ``contracts/cli.md`` "Exit
codes":

* ``0`` — sweep completed; artifact written.
* ``2`` — Modal deploy / handshake failure.
* ``5`` — sweep failed mid-run (post-deploy exception, write failure, or
  ``--m6_1_2-skip-deploy`` without an injected driver).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from vllm_grpc_bench.m6_1_2_sweep import (
    M6_1_2RPCDriver,
    M6_1_2SweepConfig,
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

    Three dispatch shapes:

    * **Injected driver** (any ``skip_deploy`` value) — caller hands the
      function a driver (typically a stub for integration tests). The
      topology probe is skipped at the driver layer; the orchestrator
      falls back to recording per-cohort ``subprocess_error`` entries
      since no handshake dict is available (see
      :func:`run_m6_1_2_sweep`).
    * **Modal-backed** (``skip_deploy=False``, no driver) — open
      ``provide_m6_endpoint`` + ``provide_m6_1_2_rpc_driver``, run the
      sweep against the live deploy, tear down on exit. This is the
      ``--m6_1_2-validate`` / ``--m6_1_2`` operator path.
    * **Skip-deploy without driver** (``skip_deploy=True``, no driver) —
      misuse; returns exit 5 with a stderr message. This shape only
      makes sense from tests that inject a driver.
    """
    config = build_config_from_args(args, sweep_mode=sweep_mode)

    if driver is not None:
        return _run_with_injected_driver(config, driver)

    if config.skip_deploy:
        print(
            "[m6_1_2] --m6_1_2-skip-deploy was set but no driver was "
            "injected; cannot run a sweep without an RPC dispatcher.",
            file=sys.stderr,
            flush=True,
        )
        return 5

    return _run_modal_backed(args, config)


# --- Injected-driver path ---------------------------------------------------


def _run_with_injected_driver(config: M6_1_2SweepConfig, driver: M6_1_2RPCDriver) -> int:
    try:
        artifact = asyncio.run(run_m6_1_2_sweep(config, driver=driver, network_probe_results=None))
    except Exception as exc:  # noqa: BLE001
        print(f"[m6_1_2] sweep failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 5

    write_sweep_artifact(artifact, config.md_out, config.json_out)
    return 0


# --- Modal-backed path ------------------------------------------------------


def _run_modal_backed(args: argparse.Namespace, config: M6_1_2SweepConfig) -> int:
    """Open Modal deploy + M6.1.2 RPC driver, run the sweep, tear down.

    Maps :class:`ModalDeployError` → exit 2 (per ``contracts/cli.md``);
    any other exception → exit 5. The Modal lifecycle is owned by
    ``provide_m6_endpoint``'s ``async with`` — teardown fires on every
    exit path including exceptions inside the sweep.
    """
    # Local import: ``provide_m6_endpoint`` imports modal which is a heavy
    # dependency; deferring keeps `--help` / argparse-only tests fast.
    from vllm_grpc_bench.modal_endpoint import ModalDeployError

    try:
        return asyncio.run(_modal_backed_sweep(args, config))
    except ModalDeployError as exc:
        print(f"[m6_1_2] Modal deploy/handshake failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"[m6_1_2] sweep failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 5


async def _modal_backed_sweep(args: argparse.Namespace, config: M6_1_2SweepConfig) -> int:
    """Async helper that owns the deploy + driver + sweep + write cycle.

    Split out of :func:`_run_modal_backed` so the synchronous wrapper can
    map exceptions to exit codes uniformly.
    """
    from vllm_grpc_bench.m6_1_rpc_driver import provide_m6_1_2_rpc_driver
    from vllm_grpc_bench.modal_endpoint import provide_m6_endpoint

    token_env = str(getattr(args, "m6_1_2_modal_token_env", "MODAL_BENCH_TOKEN"))

    async with (
        provide_m6_endpoint(
            region=config.modal_region,
            token_env=token_env,
            model_id=config.model_identifier,
        ) as endpoints,
        provide_m6_1_2_rpc_driver(
            endpoints,
            seq_len=config.seq_len,
            base_seed=config.base_seed,
        ) as (driver, _rtt),
    ):
        # Translate the RESTGRPCEndpoints bundle into the handshake dict
        # shape that run_topology_probe expects (one key per cohort URL).
        # `default_grpc` and `tuned_grpc_multiplexed` share the gRPC URL.
        handshake_dict: dict[str, object] = {
            "rest_https_edge_url": endpoints.rest_https_edge_url or "",
            "rest_plain_tcp_url": endpoints.rest_plain_tcp_url or "",
            "grpc": endpoints.grpc_url,
        }
        artifact = await run_m6_1_2_sweep(
            config,
            driver=driver,
            handshake_dict=handshake_dict,
        )

    # Write happens outside the async-with: deploy + driver context are
    # released before disk I/O, so a long write doesn't hold the Modal
    # function alive past teardown.
    write_sweep_artifact(artifact, config.md_out, config.json_out)
    return 0


__all__ = ["run_m6_1_2"]
