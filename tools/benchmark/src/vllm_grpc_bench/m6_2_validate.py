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
import asyncio
import datetime as _dt
import subprocess
import uuid
from pathlib import Path
from typing import Literal

from vllm_grpc_bench.m6_2_types import (
    M6_2_VALIDATE_MAX_TOKENS_AXIS,
    M6_2RunMeta,
    M6_2SweepArtifact,
    M6_2SweepMode,
)

__all__ = [
    "build_artifact",
    "build_stub_anchor_dispatcher",
    "build_stub_dispatcher",
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


# --- Stub dispatcher for --m6_2-skip-deploy / tests ------------------------


def _stub_seed(cell_id: str, cohort: str, max_tokens: int) -> int:
    """Stable hash → int for deterministic per-block stub latency synthesis."""
    return abs(hash((cell_id, cohort, max_tokens))) % (2**31)


def build_stub_dispatcher() -> object:
    """Return a deterministic stub :class:`BlockDispatcher` for tests and
    ``--m6_2-skip-deploy`` invocations.

    Emits a list of ``n`` per-block timings shaped by the cell concurrency,
    cohort, and max_tokens — enough variance for the artifact assembler to
    compute non-degenerate percentiles. Returns an object whose
    ``__call__`` matches the :class:`BlockDispatcher` Protocol.
    """
    from vllm_grpc_bench.m6_2_sweep import BlockDispatchResult

    class _StubDispatcher:
        async def __call__(
            self,
            *,
            cell_id: str,
            cohort: str,
            max_tokens: int,
            n: int,
            block_inputs: object,
        ) -> BlockDispatchResult:
            del block_inputs  # not used in the stub
            seed = _stub_seed(cell_id, cohort, max_tokens)
            base = 50.0 + (max_tokens / 50.0) * 8.0  # rough cap scaling
            cohort_bias = (abs(hash(cohort)) % 17) * 1.3
            concurrency_bias = 1.4 if "c8" in cell_id else (1.2 if "c4" in cell_id else 1.0)
            timings = [
                (base + cohort_bias) * concurrency_bias + ((seed + i * 9973) % 1000) / 100.0
                for i in range(n)
            ]
            return BlockDispatchResult(
                timings_ms=timings,
                failed_reason=None,
                per_rpc_metadata=[],
            )

    return _StubDispatcher()


def build_stub_anchor_dispatcher() -> object:
    """Return a deterministic stub :class:`AnchorRPCDriver`."""

    def _stub_anchor(*, cohort: str, n: int, base_seed: int, seed_offset: int) -> list[float]:
        del seed_offset
        base = 60.0 + (base_seed % 17) * 0.5
        cohort_bias = (abs(hash(cohort)) % 13) * 1.1
        return [base + cohort_bias + (i % 7) * 0.3 for i in range(n)]

    return _stub_anchor


def _stub_is_transient(exc: BaseException) -> bool:  # noqa: ARG001 - kept for protocol shape
    """Stub retry classifier: never retries (errors fail the block immediately).

    Tests can override this with a more interesting predicate; the default
    matches the validate-mode behavior where transient retry is a publish-time
    concern."""
    return False


# --- Artifact assembly -----------------------------------------------------


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        return out.stdout.strip() or "unknown"
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"


def build_artifact(
    *,
    sweep_mode: M6_2SweepMode,
    sweep_outputs: object,  # M6_2SweepOutputs (avoid import cycle)
    chat_corpus_sha256: str,
    chat_corpus_path: str,
    embed_corpus_sha256: str,
    embed_corpus_path: str,
    n_per_point: int,
    base_seed: int,
    modal_region: str,
    model_identifier: str,
    run_id: str | None = None,
    m6_1_3_baseline_path: str = "docs/benchmarks/m6_1_3-attribution-closure.json",
) -> M6_2SweepArtifact:
    """Assemble :class:`M6_2SweepArtifact` from the sweep outputs + ancillary
    inputs collected by :func:`run_m6_2`. US1-MVP scope:

    * Production-budget rows: populated from the sweep's
      ``MeasurementPoint`` list.
    * ``not_validated`` placeholders for validate-mode interior caps: inserted
      via :func:`m6_2_reporter.fill_validate_mode_placeholders`.
    * Anchor-latency trajectory: computed from the sweep's per-cohort anchor
      snapshots.
    * Null-anchor / crossover / KV-pressure: left empty for US1 MVP;
      US2 / US3 populate these in subsequent tasks (T034 / T037 / T039).
    * ``integrity_warnings``: composed via
      :func:`m6_2_reporter.build_integrity_warnings` from the assembled
      artifact's other fields.
    """
    from vllm_grpc_bench.m6_2_anchor_trajectory import (
        compute_anchor_latency_trajectory,
    )
    from vllm_grpc_bench.m6_2_reporter import (
        build_integrity_warnings,
        fill_validate_mode_placeholders,
    )
    from vllm_grpc_bench.m6_2_sweep import M6_2SweepOutputs
    from vllm_grpc_bench.m6_2_types import (
        M6_1_2_COHORTS,
        M6_2_MAX_TOKENS_AXIS,
    )

    if not isinstance(sweep_outputs, M6_2SweepOutputs):
        raise TypeError(
            f"build_artifact() expected M6_2SweepOutputs, got {type(sweep_outputs).__name__}"
        )

    # Pivot the measurements list into the per_cell shape per artifact-schema.md.
    per_cell: dict[str, dict[str, dict[int, object]]] = {}
    for point in sweep_outputs.measurements:
        per_cell.setdefault(point.cell_id, {}).setdefault(point.cohort, {})[point.max_tokens] = (
            point
        )

    # Validate-mode placeholders for the unmeasured interior caps.
    per_cell_filled = fill_validate_mode_placeholders(
        per_cell,  # type: ignore[arg-type]
        sweep_mode=sweep_mode,
        block_start_utc=sweep_outputs.wall_clock_start_utc,
        block_end_utc=sweep_outputs.wall_clock_end_utc,
    )

    # Anchor-latency trajectory. Threshold from M6.1.3 baseline CI half-width
    # is a publish-mode concern; the US1 MVP uses a generous default (drift
    # warning fires only on extreme spread); real wiring lives in T030 once
    # the baseline reader is generalized.
    anchor_trajectory = compute_anchor_latency_trajectory(
        sweep_outputs.anchor_snapshots,
        m6_1_3_baseline_ci_half_width=5.0,
    )

    started = sweep_outputs.wall_clock_start_utc
    ended = sweep_outputs.wall_clock_end_utc
    total_hours = _hours_between(started, ended)

    run_meta = M6_2RunMeta(
        git_sha=_git_sha(),
        modal_region=modal_region,
        base_seed=base_seed,
        model_identifier=model_identifier,
        dispatch_mode="concurrent",
        symmetric_prompts_enabled=True,
        schema_version="m6_1_1.v1",
        sweep_mode=sweep_mode,
        m6_1_3_baseline_artifact_path=m6_1_3_baseline_path,
        iteration_order="cohort_innermost_block",
        iteration_discipline_verified=sweep_outputs.iteration_discipline_verified,
        n_per_point=n_per_point,
        validate_axis_subset=(
            list(M6_2_VALIDATE_MAX_TOKENS_AXIS) if sweep_mode == "validate" else None
        ),
        wall_clock_start_utc=started,
        wall_clock_end_utc=ended,
        total_sweep_hours=total_hours,
        modal_spend_usd_estimate=None,
        chat_corpus_sha256=chat_corpus_sha256,
        chat_corpus_path=chat_corpus_path,
        embed_corpus_sha256=embed_corpus_sha256,
        embed_corpus_path=embed_corpus_path,
        sub_probe_ran=False,  # US3 wiring (T039) will flip this to True
    )

    artifact = M6_2SweepArtifact(
        schema_version="m6_1_1.v1",
        dispatch_mode="concurrent",
        run_id=run_id or f"{started}-{uuid.uuid4().hex[:8]}",
        run_started_at=started,
        run_completed_at=ended,
        run_meta=run_meta,
        per_cell=per_cell_filled,
        network_paths={cohort: [] for cohort in M6_1_2_COHORTS},
        cohort_set=list(M6_1_2_COHORTS),
        cohort_omissions=None,
        null_anchor_validation=[],  # US1-MVP: empty; full wiring is downstream
        max_tokens_axis=list(
            M6_2_VALIDATE_MAX_TOKENS_AXIS if sweep_mode == "validate" else M6_2_MAX_TOKENS_AXIS
        ),
        protocol_crossover=[],
        kv_pressure_observation=[],
        anchor_latency_trajectory=anchor_trajectory,
        failure_summary={},
        integrity_warnings=[],
    )
    # Compute failure_summary tally + integrity_warnings from the assembled
    # artifact so the rendering matches the JSON serialization byte-for-byte.
    artifact.failure_summary = _tally_failure_summary(artifact)
    artifact.integrity_warnings = build_integrity_warnings(artifact)
    return artifact


def _tally_failure_summary(artifact: M6_2SweepArtifact) -> dict[str, int]:
    """Count ``failed_<reason>`` markers across the table, excluding the
    validate-mode ``not_validated`` placeholders."""
    from vllm_grpc_bench.m6_2_reporter import NOT_VALIDATED_MARKER

    counts: dict[str, int] = {}
    for per_cohort in artifact.per_cell.values():
        for per_cap in per_cohort.values():
            for point in per_cap.values():
                if point.failed_reason is None or point.failed_reason == NOT_VALIDATED_MARKER:
                    continue
                counts[point.failed_reason] = counts.get(point.failed_reason, 0) + 1
    return counts


def _hours_between(start_utc: str, end_utc: str) -> float:
    try:
        start = _dt.datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
        end = _dt.datetime.fromisoformat(end_utc.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (end - start).total_seconds() / 3600.0


# --- Entry function --------------------------------------------------------


def run_m6_2(args: argparse.Namespace, *, sweep_mode: M6_2SweepMode) -> int:
    """Single entry function for both ``--m6_2`` and ``--m6_2-validate``.

    Returns the process exit code per ``contracts/cli.md``. Orchestrates:

    * FR-004 round-3 ``--m6_2-n`` deferral gate.
    * SC-018 corpus SHA validation gate at sweep start.
    * Dispatcher selection (stub vs Modal-backed) based on
      ``--m6_2-skip-deploy``.
    * Sweep execution via :func:`m6_2_sweep.run_m6_2_sweep`.
    * Artifact assembly via :func:`build_artifact`.
    * Reporter write via :func:`m6_2_reporter.write_m6_2_report`.
    """
    from vllm_grpc_bench.corpus import CorpusDriftError
    from vllm_grpc_bench.m6_2_prompt_source import load_chat_corpus, load_embed_corpus
    from vllm_grpc_bench.m6_2_reporter import write_m6_2_report
    from vllm_grpc_bench.m6_2_sweep import (
        M6_2SweepInputs,
        gate_corpus_shas,
        gate_publish_mode_n,
        run_m6_2_sweep,
    )

    args_m6_2_n: int | None = getattr(args, "m6_2_n", None)
    try:
        n_per_point = gate_publish_mode_n(args_m6_2_n, sweep_mode)
    except ValueError as exc:
        print(f"ERROR: {exc}", flush=True)
        return 5

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

    chat_corpus = load_chat_corpus()
    embed_corpus = load_embed_corpus()

    axis = _resolve_axis(sweep_mode)
    md_path = Path(infer_output_path(args, kind="md"))
    json_path = Path(infer_output_path(args, kind="json"))
    base_seed = int(getattr(args, "m6_2_base_seed", 42))
    modal_region = str(getattr(args, "m6_2_modal_region", "eu-west-1"))
    model_identifier = str(getattr(args, "m6_2_model", "Qwen/Qwen3-8B"))
    skip_deploy = bool(getattr(args, "m6_2_skip_deploy", False))

    if not skip_deploy:
        # Real Modal deploy path is wired by T044's publish-CLI integration.
        # For the US1 MVP, fail clearly so operators know to use the stub
        # path (--m6_2-skip-deploy) or the publish-CLI Modal harness.
        print(
            "ERROR: Modal-backed dispatcher wiring is deferred to T044 / T047. "
            "Use --m6_2-skip-deploy for now, or wait for the publish-CLI harness.",
            flush=True,
        )
        return 2

    dispatcher = build_stub_dispatcher()
    anchor_dispatcher = build_stub_anchor_dispatcher()

    inputs = M6_2SweepInputs(
        sweep_mode=sweep_mode,
        n=n_per_point,
        axis=axis,
        base_seed=base_seed,
        chat_corpus=chat_corpus,
        embed_corpus=embed_corpus,
        dispatcher=dispatcher,  # type: ignore[arg-type]
        anchor_dispatcher=anchor_dispatcher,  # type: ignore[arg-type]
        is_transient=_stub_is_transient,
        topology_probe=None,
    )
    sweep_outputs = asyncio.run(run_m6_2_sweep(inputs))

    artifact = build_artifact(
        sweep_mode=sweep_mode,
        sweep_outputs=sweep_outputs,
        chat_corpus_sha256=chat_corpus_sha256,
        chat_corpus_path=chat_corpus_path,
        embed_corpus_sha256=embed_corpus_sha256,
        embed_corpus_path=embed_corpus_path,
        n_per_point=n_per_point,
        base_seed=base_seed,
        modal_region=modal_region,
        model_identifier=model_identifier,
    )
    write_m6_2_report(artifact, md_path, json_path, sweep_mode=sweep_mode)
    print(
        f"[m6_2_validate] sweep_mode={sweep_mode} n_per_point={n_per_point} "
        f"axis={list(axis)} md_out={md_path} json_out={json_path}",
        flush=True,
    )
    return 0
