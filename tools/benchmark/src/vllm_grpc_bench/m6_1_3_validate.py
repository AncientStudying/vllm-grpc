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

This module is the M6.1.3 Foundational-phase skeleton: it owns the
single-entry-function + path-inference + sweep_mode-recording surface
that downstream M6.1.3 work (US1 T021 sweep orchestrator wiring + US2
T030 reporter audit section + US3 T036 multi-run extension) builds on.
The orchestrator dispatch (``run_m6_1_3_sweep(...)``) is intentionally
deferred to T021 — this skeleton returns exit 5 with a clear stderr
message when invoked before the orchestrator lands so an accidental
invocation cannot silently no-op.

The function returns ``int`` exit codes per ``contracts/cli.md`` "Exit
codes":

* ``0`` — sweep completed; artifact written.
* ``2`` — Modal deploy / handshake failure.
* ``3`` — Engine version mismatch and ``--m6_1_3-allow-engine-mismatch``
  not set.
* ``4`` — Sweep aborted by user (Ctrl-C).
* ``5`` — Sweep failed mid-run, partial artifact may exist; foundational
  skeleton returns 5 when invoked before the US1 T021 orchestrator wiring
  lands.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Literal

from vllm_grpc_bench.m6_1_3_types import M6_1_3SweepMode

# --- Output-path inference (R-7 + contracts/cli.md + contracts/artifact-schema.md) ---

# Canonical M6.1.3 artifact paths per FR-038 + round-2 Q1.
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

    # --m6_1_3 (sweep_mode == "full") below this point. Phase B is the
    # specific repeat=1 + n != 50 combination.
    repeat = int(getattr(args, "m6_1_3_diagnose_repeat", 5))
    n_per_cohort = int(getattr(args, "m6_1_3_diagnose_n", _DEFAULT_N))
    if repeat == _PHASE_B_REPEAT_TRIGGER and n_per_cohort != _DEFAULT_N:
        return _PHASE_B_MD if kind == "md" else _PHASE_B_JSON

    return _CANONICAL_MD if kind == "md" else _CANONICAL_JSON


# --- Entry function (single-dispatch pattern; matches M6.1.2 round-2 Q2) ----


def run_m6_1_3(
    args: argparse.Namespace,
    *,
    sweep_mode: M6_1_3SweepMode,
) -> int:
    """Dispatch the M6.1.3 sweep.

    Foundational-phase skeleton: resolves the inferred output paths per R-7,
    records ``sweep_mode`` for downstream reporter wiring, and returns exit
    5 with a clear stderr message indicating the US1 T021 orchestrator
    wiring is not yet in place. The path-inference + sweep-mode-recording
    surface is the load-bearing API for the Foundational checkpoint —
    downstream tasks (US1 T021 sweep orchestrator, US2 T029 audit hook-up,
    US3 T036 multi-run extension) call this function with the same shape.
    """
    md_out = Path(infer_output_path(args, kind="md"))
    json_out = Path(infer_output_path(args, kind="json"))

    print(
        f"[m6_1_3] foundational scaffold only: sweep_mode={sweep_mode}, "
        f"md_out={md_out}, json_out={json_out}; "
        "sweep orchestrator wiring lands in US1 T021 — re-run after that "
        "task is complete.",
        file=sys.stderr,
        flush=True,
    )
    return 5


__all__ = ["infer_output_path", "run_m6_1_3"]
