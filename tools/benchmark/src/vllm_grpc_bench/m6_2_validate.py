"""M6.2 — single CLI entry function for both ``--m6_2`` and ``--m6_2-validate``.

Mirrors :mod:`m6_1_3_validate`'s R-7 + round-2 Q2 dispatch shape: both
top-level mode flags ship the same sweep shape; one entry function handles
both. The operator-intent distinction lives in the ``sweep_mode:
Literal["publish", "validate"]`` argument and is recorded in
``run_meta.sweep_mode`` on the published artifact.

Output paths per FR-015 (R-7 inheritance):

* ``--m6_2-validate`` (any modifier shape) →
  ``docs/benchmarks/m6_2-token-budget-validate.{md,json}``.
* ``--m6_2`` (publish) →
  ``docs/benchmarks/m6_2-token-budget.{md,json}``.
* Explicit ``--m6_2-report-out`` / ``--m6_2-report-json-out`` overrides
  take precedence regardless of mode.

Per ``contracts/cli.md`` exit codes:

* ``0`` — sweep completed; artifact written.
* ``2`` — Modal deploy / handshake failure.
* ``3`` — engine version mismatch and ``--m6_2-allow-engine-mismatch``
  not set (reserved; not exercised in the Foundational/US1 scope).
* ``4`` — sweep aborted by user (Ctrl-C; reserved).
* ``5`` — sweep failed mid-run; partial artifact may exist.
* ``6`` — corpus SHA drift detected at sweep start (SC-018).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal

from vllm_grpc_bench.m6_2_types import (
    M6_2_VALIDATE_MAX_TOKENS_AXIS,
    M6_2SweepMode,
)

__all__ = [
    "infer_output_path",
    "run_m6_2",
]


# --- Output-path inference (FR-015 + R-7 inheritance) ----------------------

_VALIDATE_MD = "docs/benchmarks/m6_2-token-budget-validate.md"
_VALIDATE_JSON = "docs/benchmarks/m6_2-token-budget-validate.json"
_CANONICAL_MD = "docs/benchmarks/m6_2-token-budget.md"
_CANONICAL_JSON = "docs/benchmarks/m6_2-token-budget.json"


def infer_output_path(
    args: argparse.Namespace,
    *,
    kind: Literal["md", "json"],
) -> str:
    """Resolve the M6.2 artifact output path per FR-015.

    Explicit ``--m6_2-report-out`` (md) or ``--m6_2-report-json-out`` (json)
    overrides take precedence; otherwise the path defaults to the
    canonical (publish) or validate sibling.
    """
    explicit_md = getattr(args, "m6_2_report_out", None)
    explicit_json = getattr(args, "m6_2_report_json_out", None)
    if kind == "md" and explicit_md is not None:
        return str(explicit_md)
    if kind == "json" and explicit_json is not None:
        return str(explicit_json)

    sweep_mode: M6_2SweepMode = "validate" if getattr(args, "m6_2_validate", False) else "publish"
    if sweep_mode == "validate":
        return _VALIDATE_MD if kind == "md" else _VALIDATE_JSON
    return _CANONICAL_MD if kind == "md" else _CANONICAL_JSON


def _resolve_axis(sweep_mode: M6_2SweepMode) -> tuple[int, ...]:
    """Validate mode uses the 3-point subset per FR-001 round-1 Q2; publish
    uses the full 6-point axis."""
    from vllm_grpc_bench.m6_2_types import M6_2_MAX_TOKENS_AXIS

    return M6_2_VALIDATE_MAX_TOKENS_AXIS if sweep_mode == "validate" else M6_2_MAX_TOKENS_AXIS


def run_m6_2(args: argparse.Namespace, *, sweep_mode: M6_2SweepMode) -> int:
    """Single entry function for both ``--m6_2`` and ``--m6_2-validate``.

    Returns the process exit code per ``contracts/cli.md``. The orchestration
    is delegated to :mod:`m6_2_sweep`; this function is responsible for:

    * FR-004 round-3 ``--m6_2-n`` deferral gate.
    * SC-018 corpus SHA validation gate at sweep start.
    * Output-path inference per FR-015.
    * Wiring the configured ``base_seed``, ``modal_region``, ``model``
      defaults from ``contracts/cli.md`` into the sweep inputs.
    * Recording ``run_meta`` fields (corpus SHAs, paths, sub_probe_ran).

    The actual RPC dispatcher / anchor dispatcher / topology probe wiring is
    deferred to US1's reporter integration tasks (T032 / T044) — they inject
    the stub or Modal-backed drivers via the foundational orchestrator's
    pluggable Protocol surfaces.
    """
    from vllm_grpc_bench.m6_2_sweep import gate_corpus_shas, gate_publish_mode_n

    args_m6_2_n: int | None = getattr(args, "m6_2_n", None)
    try:
        n_per_point = gate_publish_mode_n(args_m6_2_n, sweep_mode)
    except ValueError as exc:
        print(f"ERROR: {exc}", flush=True)
        return 5

    from vllm_grpc_bench.corpus import CorpusDriftError

    try:
        (
            chat_corpus_sha256,
            chat_corpus_path,
            embed_corpus_sha256,
            embed_corpus_path,
        ) = gate_corpus_shas()
    except CorpusDriftError as exc:
        print(f"ERROR: SC-018 corpus drift detected:\n{exc}", flush=True)
        return 6
    except FileNotFoundError as exc:
        print(f"ERROR: corpus missing (FR-035 Phase 1 prerequisite):\n{exc}", flush=True)
        return 6

    axis = _resolve_axis(sweep_mode)

    md_path = Path(infer_output_path(args, kind="md"))
    json_path = Path(infer_output_path(args, kind="json"))

    # Phase 2 foundational scope: the dispatcher / reporter wiring is
    # deferred to US1 (T032 / T044). We record the parsed configuration so
    # the call site can audit what would have been dispatched. Sub-probe
    # wiring (T039) and reporter wiring (T022-T030) plug into this slot.
    print(
        f"[m6_2_validate] sweep_mode={sweep_mode} "
        f"n_per_point={n_per_point} axis={axis} "
        f"chat_sha={chat_corpus_sha256[:12]}... embed_sha={embed_corpus_sha256[:12]}... "
        f"md_out={md_path} json_out={json_path}",
        flush=True,
    )
    print(
        "[m6_2_validate] Phase 2 foundational scope complete; reporter "
        "wiring is T022 / T032 / T044 territory.",
        flush=True,
    )
    _ = chat_corpus_path, embed_corpus_path  # recorded into run_meta by T022
    return 0
