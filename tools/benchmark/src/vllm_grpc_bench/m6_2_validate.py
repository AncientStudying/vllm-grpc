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
import json
import subprocess
import uuid
from pathlib import Path
from typing import Literal

from vllm_grpc_bench.corpus import (
    CompletionEmbedSample,
    RequestSample,
)
from vllm_grpc_bench.m6_1_2_types import M6_1_2CohortKind
from vllm_grpc_bench.m6_2_crossover import M6_1_3CohortBaseline
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
    "load_m6_1_3_baseline",
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


# --- M6.1.3 baseline loader (US2 crossover input) --------------------------


def load_m6_1_3_baseline(
    baseline_path: str | Path,
) -> tuple[
    dict[str, dict[M6_1_2CohortKind, M6_1_3CohortBaseline]],
    dict[str, str],
]:
    """Read the M6.1.3 artifact and return ``(per_cell_baseline, base_verdicts)``.

    ``per_cell_baseline[cell_id][cohort]`` is a
    :class:`m6_2_crossover.M6_1_3CohortBaseline` (wall_p50_ms + CI half-width).
    ``base_verdicts[cell_id]`` is the M6.1.3 classifier label.

    Source mapping:

    - ``wall_p50_ms`` ← M6.1.3's ``measurements[].wall_clock_ms_mean`` (mean
      is the closest available per-cohort proxy; M6.1.3 doesn't publish a
      per-cohort p50).
    - ``wall_p50_ms_ci_half_width`` ← per-(cell, cohort)
      ``between_run_variance.stddev_of_means_ms`` × 1.96 / sqrt(n_runs) when
      available, else 0.0 (the crossover compute falls back to the symmetric
      mean-in-CI rule's failure path when the CI is degenerate).
    - ``base_verdicts`` ← ``classifications`` dict from the artifact.

    Returns ``({}, {})`` if the baseline file is missing or malformed; the
    crossover compute then emits the canonical "did not publish" evidence
    for every cell.
    """
    path = Path(baseline_path)
    if not path.exists():
        return {}, {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}, {}

    baseline_per_cell: dict[str, dict[M6_1_2CohortKind, M6_1_3CohortBaseline]] = {}
    for measurement in data.get("measurements", []):
        cell_id = measurement.get("cell_id")
        cohort = measurement.get("cohort")
        wall_mean = measurement.get("wall_clock_ms_mean")
        if cell_id is None or cohort is None or wall_mean is None:
            continue
        baseline_per_cell.setdefault(cell_id, {})[cohort] = M6_1_3CohortBaseline(
            wall_p50_ms=float(wall_mean),
            wall_p50_ms_ci_half_width=0.0,  # see between_run_variance section
        )

    # Enrich with between_run_variance-derived CI half-widths when present.
    variance = data.get("between_run_variance") or {}
    for cell_id, per_cohort in variance.items():
        for cohort, var in (per_cohort or {}).items():
            stddev = var.get("stddev_of_means_ms")
            n_runs = var.get("n_runs", 1)
            if stddev is None or n_runs is None or n_runs < 2:
                continue
            try:
                ci_half = 1.96 * float(stddev) / (float(n_runs) ** 0.5)
            except (TypeError, ValueError):
                continue
            entry = baseline_per_cell.get(cell_id, {}).get(cohort)
            if entry is None:
                continue
            baseline_per_cell[cell_id][cohort] = M6_1_3CohortBaseline(
                wall_p50_ms=entry.wall_p50_ms,
                wall_p50_ms_ci_half_width=ci_half,
            )

    base_verdicts: dict[str, str] = {}
    for cell_id, label in (data.get("classifications") or {}).items():
        if isinstance(label, str):
            base_verdicts[cell_id] = label
    return baseline_per_cell, base_verdicts


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
    sub_probe_rows: object = None,  # list[SubProbeBlockResult] | None
    sub_probe_ran: bool = False,
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
    from vllm_grpc_bench.m6_2_crossover import (
        SubProbeBlockResult,
        compute_kv_pressure_inference,
        compute_per_cell_crossover,
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

    # US2 crossover compute. Reads M6.1.3 baseline (cohort means + classifier
    # labels) and runs the symmetric mean-in-CI rule against M6.2's per-cohort
    # axis rows. Cells without a baseline entry emit canonical "did not
    # publish" evidence.
    baseline_per_cell, base_verdicts = load_m6_1_3_baseline(m6_1_3_baseline_path)
    protocol_crossover = compute_per_cell_crossover(
        per_cell_filled,
        baseline_per_cell,
        base_verdicts,
        sweep_mode=sweep_mode,
    )

    # US3 KV-pressure inference. Consumes the sub-probe rows (NOT the
    # main-sweep budget-table c=8 rows) per FR-036 / FR-017a amendment.
    # 8 records emitted: 4 cohorts × 2 cell-types.
    typed_sub_probe_rows: list[SubProbeBlockResult] = []
    if sub_probe_rows is not None:
        if not isinstance(sub_probe_rows, list):
            raise TypeError(f"sub_probe_rows must be a list, got {type(sub_probe_rows).__name__}")
        for row in sub_probe_rows:
            if not isinstance(row, SubProbeBlockResult):
                raise TypeError(
                    f"sub_probe_rows entries must be SubProbeBlockResult, got {type(row).__name__}"
                )
            typed_sub_probe_rows.append(row)
    kv_pressure_observation = compute_kv_pressure_inference(typed_sub_probe_rows)

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
        sub_probe_ran=sub_probe_ran,
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
        protocol_crossover=protocol_crossover,
        kv_pressure_observation=kv_pressure_observation,
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


# --- Main-sweep + sub-probe driver -----------------------------------------


async def _drive_main_sweep_and_sub_probe(
    *,
    inputs: object,  # M6_2SweepInputs
    dispatcher: object,
    anchor_dispatcher: object,
    chat_corpus: list[RequestSample],
    embed_corpus: list[CompletionEmbedSample],
    base_seed: int,
) -> tuple[object, list[object]]:
    """Drive the main sweep + sub-probe sequentially in a single asyncio
    runtime. Sub-probe always runs after the main sweep completes per SC-019;
    both publish and validate modes invoke it.
    """
    from vllm_grpc_bench.m6_2_sub_probe import run_kv_pressure_sub_probe
    from vllm_grpc_bench.m6_2_sweep import (
        M6_2SweepInputs,
    )
    from vllm_grpc_bench.m6_2_sweep import (
        run_m6_2_sweep as _run_m6_2_sweep,
    )

    if not isinstance(inputs, M6_2SweepInputs):
        raise TypeError(
            f"_drive_main_sweep_and_sub_probe inputs must be M6_2SweepInputs, "
            f"got {type(inputs).__name__}"
        )

    sweep_outputs = await _run_m6_2_sweep(inputs)
    sub_probe_results = await run_kv_pressure_sub_probe(
        dispatcher=dispatcher,  # type: ignore[arg-type]
        is_transient=_stub_is_transient,
        base_seed=base_seed,
        chat_corpus=chat_corpus,
        embed_corpus=embed_corpus,
    )
    del anchor_dispatcher  # not needed by the sub-probe (it dispatches via the main dispatcher)
    return sweep_outputs, list(sub_probe_results)


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
    sub_probe_rows = asyncio.run(
        _drive_main_sweep_and_sub_probe(
            inputs=inputs,
            dispatcher=dispatcher,
            anchor_dispatcher=anchor_dispatcher,
            chat_corpus=chat_corpus,
            embed_corpus=embed_corpus,
            base_seed=base_seed,
        )
    )
    sweep_outputs, sub_probe_results = sub_probe_rows

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
        sub_probe_rows=sub_probe_results,
        sub_probe_ran=True,
    )
    write_m6_2_report(artifact, md_path, json_path, sweep_mode=sweep_mode)
    print(
        f"[m6_2_validate] sweep_mode={sweep_mode} n_per_point={n_per_point} "
        f"axis={list(axis)} md_out={md_path} json_out={json_path}",
        flush=True,
    )
    return 0
