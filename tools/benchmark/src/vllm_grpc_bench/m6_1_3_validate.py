"""M6.1.3 — Phase 1 Attribution Closure: single CLI entry function for both
``--m6_1_3`` and ``--m6_1_3-validate`` mode flags.

Per ``specs/026-m6-1-3-attribution-closure/contracts/cli.md`` "Dispatch
wiring" + R-7 + round-2 Q2: both top-level flags ship the same sweep
shape; one entry function handles both. The operator-intent distinction
lives in the ``sweep_mode: Literal["full", "validate"]`` argument and is
recorded in ``run_meta.sweep_mode`` on the published artifact.

Output paths are inferred per R-7 from the mode + modifier combination:

* ``--m6_1_3-validate`` (any modifier shape) →
  ``docs/benchmarks/m6_1_3-attribution-closure-validate.{md,json}``.
* ``--m6_1_3`` with default modifiers (repeat=5, n=50) →
  ``docs/benchmarks/m6_1_3-attribution-closure.{md,json}`` (canonical
  publish).
* ``--m6_1_3 --m6_1_3-diagnose-repeat=1 --m6_1_3-diagnose-n=200`` →
  ``docs/benchmarks/m6_1_3-attribution-closure-phase-b.{md,json}``
  (Phase B sibling per FR-038 + round-2 Q1).
* Explicit ``--m6_1_3-report-out`` / ``--m6_1_3-report-json-out``
  overrides take precedence regardless of mode.

Dispatch shape (matches M6.1.2 per round-2 Q2):

* **Injected driver** — caller hands the function a driver (typically a
  stub for the integration test). The topology probe is skipped at the
  driver layer; the orchestrator records per-cohort ``subprocess_error``
  entries when no handshake dict is available.
* **Modal-backed** — open ``provide_m6_endpoint`` +
  ``provide_m6_1_2_rpc_driver``, run the sweep against the live deploy,
  tear down on exit. This is the operator path for the validate / publish
  Modal sweeps in Phase 6.
* **Skip-deploy without driver** — misuse; returns exit 5 with a stderr
  message. This shape only makes sense from tests that inject a driver.

Per ``contracts/cli.md`` "Exit codes":

* ``0`` — sweep completed; artifact written.
* ``2`` — Modal deploy / handshake failure.
* ``3`` — engine version mismatch and ``--m6_1_3-allow-engine-mismatch``
  not set (reserved; not exercised in the Foundational/US1 scope).
* ``4`` — sweep aborted by user (Ctrl-C; reserved).
* ``5`` — sweep failed mid-run; partial artifact may exist.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Literal

from vllm_grpc_bench.m6_1_3_sweep import (
    M6_1_3RPCDriver,
    M6_1_3SweepConfig,
    build_config_from_args,
    run_m6_1_3_sweep,
    write_sweep_artifact,
)
from vllm_grpc_bench.m6_1_3_types import M6_1_3SweepMode

# --- Output-path inference (R-7 + contracts/cli.md + contracts/artifact-schema.md) ---

_VALIDATE_MD = "docs/benchmarks/m6_1_3-attribution-closure-validate.md"
_VALIDATE_JSON = "docs/benchmarks/m6_1_3-attribution-closure-validate.json"
_CANONICAL_MD = "docs/benchmarks/m6_1_3-attribution-closure.md"
_CANONICAL_JSON = "docs/benchmarks/m6_1_3-attribution-closure.json"
_PHASE_B_MD = "docs/benchmarks/m6_1_3-attribution-closure-phase-b.md"
_PHASE_B_JSON = "docs/benchmarks/m6_1_3-attribution-closure-phase-b.json"

# Phase B detection per R-7: the Phase B mode is signalled by the
# combination of --m6_1_3 (sweep_mode == "full") + repeat=1 + n != 50.
_PHASE_B_REPEAT_TRIGGER = 1
_DEFAULT_N = 50


def infer_output_path(args: argparse.Namespace, *, kind: Literal["md", "json"]) -> str:
    """Resolve the M6.1.3 artifact output path per R-7 + FR-038.

    Precedence (highest to lowest):

    1. Explicit ``--m6_1_3-report-out`` / ``--m6_1_3-report-json-out``
       operator override (any non-None value wins).
    2. ``--m6_1_3-validate`` mode → validate sibling path.
    3. ``--m6_1_3`` with Phase B modifier combo (repeat=1 + n != 50) →
       Phase B sibling path.
    4. ``--m6_1_3`` with default modifiers (or any other combo on the
       full sweep) → canonical publish path.

    ``kind`` selects between the ``.md`` and ``.json`` companion paths.
    """
    explicit_attr = "m6_1_3_report_out" if kind == "md" else "m6_1_3_report_json_out"
    explicit = getattr(args, explicit_attr, None)
    if explicit is not None:
        return str(explicit)

    if getattr(args, "m6_1_3_validate", False):
        return _VALIDATE_MD if kind == "md" else _VALIDATE_JSON

    repeat = int(getattr(args, "m6_1_3_diagnose_repeat", 5))
    n_per_cohort = int(getattr(args, "m6_1_3_diagnose_n", _DEFAULT_N))
    if repeat == _PHASE_B_REPEAT_TRIGGER and n_per_cohort != _DEFAULT_N:
        return _PHASE_B_MD if kind == "md" else _PHASE_B_JSON

    return _CANONICAL_MD if kind == "md" else _CANONICAL_JSON


def _build_config(args: argparse.Namespace, *, sweep_mode: M6_1_3SweepMode) -> M6_1_3SweepConfig:
    """Resolve output paths + delegate to the sweep's config builder.

    Forces ``args.m6_1_3_report_out`` / ``-report-json-out`` to the
    inferred values when the operator didn't override them so the sweep
    orchestrator sees concrete paths.
    """
    md_out = infer_output_path(args, kind="md")
    json_out = infer_output_path(args, kind="json")
    # Surface the inferred paths back to args so build_config_from_args
    # consumes them — the orchestrator + reporter both read from there.
    args.m6_1_3_report_out = Path(md_out)
    args.m6_1_3_report_json_out = Path(json_out)
    return build_config_from_args(args, sweep_mode=sweep_mode)


def run_m6_1_3(
    args: argparse.Namespace,
    *,
    sweep_mode: M6_1_3SweepMode,
    driver: M6_1_3RPCDriver | None = None,
) -> int:
    """Dispatch the M6.1.3 sweep.

    Three dispatch shapes:

    * **Injected driver** (any ``skip_deploy`` value) — caller hands the
      function a driver (typically a stub for integration tests). Runs
      against the driver, writes the artifact, returns 0.
    * **Modal-backed** (``skip_deploy=False``, no driver) — open
      ``provide_m6_endpoint`` + ``provide_m6_1_2_rpc_driver``, run the
      sweep against the live deploy, tear down on exit.
    * **Skip-deploy without driver** (``skip_deploy=True``, no driver) —
      misuse; returns exit 5 with a stderr message. Only sensible from
      tests that inject a driver.
    """
    config = _build_config(args, sweep_mode=sweep_mode)

    if driver is not None:
        return _run_with_injected_driver(config, driver)

    if config.skip_deploy:
        print(
            "[m6_1_3] --m6_1_3-skip-deploy was set but no driver was "
            "injected; cannot run a sweep without an RPC dispatcher.",
            file=sys.stderr,
            flush=True,
        )
        return 5

    return _run_modal_backed(args, config)


# --- Injected-driver path ---------------------------------------------------


def _run_with_injected_driver(config: M6_1_3SweepConfig, driver: M6_1_3RPCDriver) -> int:
    try:
        artifact = asyncio.run(run_m6_1_3_sweep(config, driver=driver, network_probe_results=None))
    except Exception as exc:  # noqa: BLE001
        print(f"[m6_1_3] sweep failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 5

    write_sweep_artifact(artifact, config.md_out, config.json_out)
    return 0


# --- Modal-backed path ------------------------------------------------------


def _run_modal_backed(args: argparse.Namespace, config: M6_1_3SweepConfig) -> int:
    """Open Modal deploy + RPC driver, run the sweep, tear down.

    Maps :class:`ModalDeployError` → exit 2; any other exception → exit 5.
    The Modal lifecycle is owned by ``provide_m6_endpoint``'s ``async
    with`` — teardown fires on every exit path including exceptions
    inside the sweep.
    """
    from vllm_grpc_bench.modal_endpoint import ModalDeployError

    try:
        return asyncio.run(_modal_backed_sweep(args, config))
    except ModalDeployError as exc:
        print(f"[m6_1_3] Modal deploy/handshake failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"[m6_1_3] sweep failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 5


async def _modal_backed_sweep(args: argparse.Namespace, config: M6_1_3SweepConfig) -> int:
    """Async helper that owns the deploy + driver + sweep + write cycle.

    Pins ``seq_len`` via :func:`pin_seq_len_at_sweep_start` BEFORE opening
    the driver — same precaution as M6.1.2 to keep embed payloads under
    the gRPC server's default 4 MiB receive limit.
    """
    from dataclasses import replace

    from vllm_grpc_bench.m6_1_rpc_driver import provide_m6_1_2_rpc_driver
    from vllm_grpc_bench.m6_1_seq_len import pin_seq_len_at_sweep_start
    from vllm_grpc_bench.modal_endpoint import provide_m6_endpoint

    token_env = str(getattr(args, "m6_1_3_modal_token_env", "MODAL_BENCH_TOKEN"))

    pinned_seq_len = pin_seq_len_at_sweep_start(config.model_identifier)
    print(
        f"[m6_1_3] pinned seq_len={pinned_seq_len} for model={config.model_identifier} "
        f"(was config default {config.seq_len}; embed payload size = "
        f"seq_len × hidden_size × 2 bytes)",
        file=sys.stderr,
        flush=True,
    )
    config = replace(config, seq_len=pinned_seq_len)

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
        handshake_dict: dict[str, object] = {
            "rest_https_edge_url": endpoints.rest_https_edge_url or "",
            "rest_plain_tcp_url": endpoints.rest_plain_tcp_url or "",
            "grpc": endpoints.grpc_url,
        }
        artifact = await run_m6_1_3_sweep(
            config,
            driver=driver,
            handshake_dict=handshake_dict,
        )

    write_sweep_artifact(artifact, config.md_out, config.json_out)
    return 0


__all__ = ["infer_output_path", "run_m6_1_3"]
