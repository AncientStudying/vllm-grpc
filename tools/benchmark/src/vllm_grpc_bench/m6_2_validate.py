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
import sys
import uuid
from pathlib import Path
from typing import Any, Literal

import grpc
import httpx

from vllm_grpc_bench.corpus import (
    CompletionEmbedSample,
    RequestSample,
)
from vllm_grpc_bench.m6_1_2_types import M6_1_2_COHORTS, M6_1_2CohortKind
from vllm_grpc_bench.m6_1_types import M6_1_CELLS, M6_1Cell
from vllm_grpc_bench.m6_2_crossover import M6_1_3CohortBaseline
from vllm_grpc_bench.m6_2_types import (
    M6_2_NULL_ANCHOR_MAX_TOKENS,
    M6_2_VALIDATE_MAX_TOKENS_AXIS,
    M6_2NullAnchor,
    M6_2RunMeta,
    M6_2SweepArtifact,
    M6_2SweepMode,
)

__all__ = [
    "build_artifact",
    "build_modal_anchor_dispatcher",
    "build_modal_block_dispatcher",
    "build_stub_anchor_dispatcher",
    "build_stub_dispatcher",
    "derive_anchor_drift_threshold",
    "infer_output_path",
    "is_transient_modal_error",
    "load_m6_1_3_baseline",
    "make_null_anchor_validation",
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
    """Return a deterministic stub :class:`AnchorRPCDriver` (async)."""

    async def _stub_anchor(*, cohort: str, n: int, base_seed: int, seed_offset: int) -> list[float]:
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


# --- Real (Modal-backed) classifier + dispatchers --------------------------


_GRPC_TRANSIENT_CODES = frozenset(
    {
        grpc.StatusCode.UNAVAILABLE,
        grpc.StatusCode.DEADLINE_EXCEEDED,
        grpc.StatusCode.ABORTED,
        grpc.StatusCode.INTERNAL,
        grpc.StatusCode.RESOURCE_EXHAUSTED,
    }
)
"""gRPC status codes treated as transient by :func:`is_transient_modal_error`.

* ``UNAVAILABLE`` — connection reset, Modal frontend restart.
* ``DEADLINE_EXCEEDED`` — RPC slow but not necessarily wedged.
* ``ABORTED`` — tunnel-level transient.
* ``INTERNAL`` — most often a Modal-side transient at high concurrency.
* ``RESOURCE_EXHAUSTED`` — KV / scheduler back-pressure that may pass with
  a retry once the in-flight RPC drains.

``UNAUTHENTICATED`` / ``PERMISSION_DENIED`` / ``INVALID_ARGUMENT`` are
explicitly NOT transient (configuration or input bugs)."""


def is_transient_modal_error(exc: BaseException) -> bool:
    """FR-033 in-window retry classifier for the real Modal dispatch path.

    Returns ``True`` on transient network-shaped errors (gRPC code in
    :data:`_GRPC_TRANSIENT_CODES`, httpx transport errors / timeouts),
    ``False`` otherwise. ``False`` is the safe default — non-transient
    exceptions fail the block once, preserving FR-033's "retry exactly once,
    in-window" contract.
    """
    if isinstance(exc, grpc.RpcError):
        try:
            code = exc.code()
        except AttributeError:
            return False
        return code in _GRPC_TRANSIENT_CODES
    return isinstance(
        exc,
        httpx.TransportError | httpx.TimeoutException | httpx.RemoteProtocolError,
    )


def _cell_from_cell_id(cell_id: str) -> M6_1Cell:
    """Resolve a cell id (e.g. ``"chat_stream_c4"``) into an :class:`M6_1Cell`."""
    for path, hidden_size, concurrency in M6_1_CELLS:
        if cell_id == f"{path}_c{concurrency}":
            return M6_1Cell(path=path, hidden_size=hidden_size, concurrency=concurrency)
    raise ValueError(f"unknown M6.2 cell id {cell_id!r}; not in M6_1_CELLS")


def build_modal_block_dispatcher(
    driver: Any,  # M6_2RPCDriver — `Any` to avoid an import cycle at the type level
    *,
    base_seed: int,
) -> Any:
    """Build a :class:`BlockDispatcher` that fires N concurrent RPCs via
    :func:`provide_m6_2_rpc_driver`'s driver callable.

    The dispatcher:

    * Resolves ``cell_id`` → :class:`M6_1Cell` via :func:`_cell_from_cell_id`.
    * Allocates per-RPC seeds from ``base_seed`` + the block's iteration
      index (the orchestrator already advances ``iter_idx`` by block, so we
      stripe per-RPC seeds within the block).
    * Reads ``prompt`` (chat) / ``prompt_embeds_override`` (embed) +
      ``ignore_eos`` from the :class:`ResolvedBlockInputs` produced by
      :mod:`m6_2_prompt_source`.
    * Awaits all ``n`` RPCs in parallel via :func:`asyncio.gather`.
    * Aggregates results into :class:`BlockDispatchResult`: per-RPC wall
      times for successful RPCs, the first non-None ``failure_reason`` for
      the block (with ``no_successful_rpcs`` sentinel when every RPC failed),
      and per-RPC ``m6_1_1_timing_payload`` dicts for the segment
      decomposition.
    """
    from vllm_grpc_bench.m6_2_prompt_source import ResolvedBlockInputs
    from vllm_grpc_bench.m6_2_sweep import BlockDispatchResult

    async def _dispatcher(
        *,
        cell_id: str,
        cohort: M6_1_2CohortKind,
        max_tokens: int,
        n: int,
        block_inputs: ResolvedBlockInputs,
    ) -> BlockDispatchResult:
        cell = _cell_from_cell_id(cell_id)
        prompt = block_inputs.get("prompt_text")
        prompt_embeds_override = block_inputs.get("embed_tensor_bytes")
        ignore_eos = bool(block_inputs.get("ignore_eos", False))

        async def _one_rpc(i: int) -> Any:
            seed = base_seed + i
            return await driver(
                cohort,
                cell,
                seed,
                max_tokens=max_tokens,
                ignore_eos=ignore_eos,
                prompt=prompt,
                prompt_embeds_override=prompt_embeds_override,
            )

        results = await asyncio.gather(*[_one_rpc(i) for i in range(n)], return_exceptions=True)

        timings_ms: list[float] = []
        per_rpc_metadata: list[dict[str, str]] = []
        first_failure: str | None = None
        for r in results:
            if isinstance(r, BaseException):
                if first_failure is None:
                    first_failure = _classify_dispatcher_exc(r)
                continue
            # r is RPCResult-shaped (m6_sweep.RPCResult). Avoid an isinstance
            # check on RPCResult to keep this dispatcher framework-agnostic for
            # the integration test's fake driver.
            if getattr(r, "success", False) and getattr(r, "wall_clock_ms", None) is not None:
                timings_ms.append(float(r.wall_clock_ms))
                md: dict[str, str] = {}
                payload = getattr(r, "m6_1_1_timing_payload", None)
                if isinstance(payload, dict):
                    # Skip None values: timing_checkpoint_to_payload emits None
                    # for pre-M6.1.3 wire vintage on `pre_engine_wall_ns` /
                    # `first_chunk_mono_ns` / audit fields. Carrying the literal
                    # string "None" through would break downstream int parsing.
                    for k, v in payload.items():
                        if v is None:
                            continue
                        md[k] = str(v)
                engine_cost = getattr(r, "engine_cost", None)
                if engine_cost is not None:
                    # Thread engine_cost fields into per_rpc_metadata so the
                    # aggregator can compute tpot_ms / engine_ttft_ms / engine_forward_ms
                    # alongside the M6.1.1 segment checkpoints. Keys mirror
                    # `EngineCostSpan` attribute names verbatim.
                    for attr in ("engine_tpot_ms", "engine_ttft_ms", "engine_forward_ms"):
                        v = getattr(engine_cost, attr, None)
                        if v is not None:
                            md[attr] = str(v)
                if md:
                    per_rpc_metadata.append(md)
            else:
                if first_failure is None:
                    reason = getattr(r, "failure_reason", None)
                    first_failure = str(reason) if reason else "unknown_failure"

        if not timings_ms:
            return BlockDispatchResult(
                timings_ms=[],
                failed_reason=first_failure or "no_successful_rpcs",
                per_rpc_metadata=[],
            )
        return BlockDispatchResult(
            timings_ms=timings_ms,
            failed_reason=None,
            per_rpc_metadata=per_rpc_metadata,
        )

    return _dispatcher


def _classify_dispatcher_exc(exc: BaseException) -> str:
    """Map a raised exception to a short ``failed_reason`` string that the
    classifier downstream can pattern-match (e.g. ``"grpc_unavailable"`` vs
    ``"httpx_timeout"``)."""
    if isinstance(exc, grpc.RpcError):
        try:
            code = exc.code().name.lower()
        except (AttributeError, ValueError):
            code = "unknown"
        return f"grpc_{code}"
    if isinstance(exc, httpx.TimeoutException):
        return "httpx_timeout"
    if isinstance(exc, httpx.HTTPError):
        return f"httpx_{type(exc).__name__.lower()}"
    return f"{type(exc).__name__.lower()}"


def build_modal_anchor_dispatcher(
    driver: Any,  # M6_2RPCDriver
    *,
    anchor_cell: M6_1Cell | None = None,
    anchor_max_tokens: int = 10,
) -> Any:
    """Build an :class:`AnchorRPCDriver` that fires the FR-031 anchor block
    against the real driver.

    The anchor block uses SYNTHETIC prompts (``prompt=None`` → builder falls
    back to ``_build_chat_prompt(seed)``), preserving byte-comparability with
    M6.1.3's published anchors per R-3 of research.md. Always at
    ``chat_stream_c1 × max_tokens=10`` unless the caller overrides.
    """
    from vllm_grpc_bench.m6_1_types import M6_1Cell as _M6_1Cell

    cell = anchor_cell or _M6_1Cell(path="chat_stream", hidden_size=4096, concurrency=1)

    async def _anchor(
        *, cohort: M6_1_2CohortKind, n: int, base_seed: int, seed_offset: int
    ) -> list[float]:
        async def _one(i: int) -> float | None:
            seed = base_seed + seed_offset + i
            try:
                result = await driver(
                    cohort,
                    cell,
                    seed,
                    max_tokens=anchor_max_tokens,
                    ignore_eos=False,
                    prompt=None,
                    prompt_embeds_override=None,
                )
            except (grpc.RpcError, httpx.HTTPError):
                return None
            if getattr(result, "success", False) and result.wall_clock_ms is not None:
                return float(result.wall_clock_ms)
            return None

        raw = await asyncio.gather(*[_one(i) for i in range(n)])
        return [v for v in raw if v is not None]

    return _anchor


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


# --- Real anchor CI half-width derivation (T054) ---------------------------


def derive_anchor_drift_threshold(baseline_path: str | Path) -> float:
    """Read M6.1.3's ``between_run_variance`` at ``chat_stream_c1`` (the
    cell the anchor block exercises) and return the MAX CI half-width across
    the cohorts that M6.1.3 published.

    The drift-warning rule in :func:`m6_2_anchor_trajectory.compute_anchor_latency_trajectory`
    fires when the per-cohort ``max - min`` spread across anchor snapshots
    exceeds this threshold. Using the per-cohort MAX (rather than the per-cohort
    mean / min) is the most conservative choice: a tight cohort's threshold
    would fire on benign network jitter the looser cohorts already absorb.

    Falls back to ``5.0`` ms if the baseline file is unreadable or carries no
    ``between_run_variance.chat_stream_c1`` block — preserves the previous
    sentinel behavior so the call site never throws.
    """
    path = Path(baseline_path)
    if not path.exists():
        return 5.0
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return 5.0
    brv = (data.get("between_run_variance") or {}).get("chat_stream_c1") or {}
    cis: list[float] = []
    for cohort_data in brv.values():
        if not isinstance(cohort_data, dict):
            continue
        stddev = cohort_data.get("stddev_of_means_ms")
        n_runs = cohort_data.get("n_runs")
        if stddev is None or n_runs is None or n_runs < 2:
            continue
        try:
            cis.append(1.96 * float(stddev) / (float(n_runs) ** 0.5))
        except (TypeError, ValueError):
            continue
    return max(cis) if cis else 5.0


# --- Null-anchor assembly (T053) --------------------------------------------


def _cross_checkable_max_tokens(path: str) -> int:
    """The single ``max_tokens`` axis value at which an M6.1.x baseline exists
    for this cell type.

    M6.1.x used ``max_tokens=50`` for ``chat_stream`` cells and ``max_tokens=10``
    for ``embed`` cells (the M6.x synthetic caps). The other axis point in
    ``M6_2_NULL_ANCHOR_MAX_TOKENS`` is a NEW baseline (no M6.1.x reference).
    """
    return 50 if path == "chat_stream" else 10


def make_null_anchor_validation(
    measurements: list[Any],  # list[M6_2MeasurementPoint]
    baseline_per_cell: dict[str, dict[M6_1_2CohortKind, M6_1_3CohortBaseline]],
) -> list[M6_2NullAnchor]:
    """FR-012 / FR-013 null-anchor assembly across the 48 anchor cells.

    Iterates ``M6_1_CELLS × M6_1_2_COHORTS × {10, 50}`` (= 48 cells), pairing
    each with the M6.2 measurement at that (cell_id, cohort, max_tokens).
    For each, decides cross-checkable vs new-baseline by whether M6.1.3
    published a baseline at the ``max_tokens`` value matched to the cell
    type (``chat_stream`` → ``max_tokens=50``; ``embed`` → ``max_tokens=10``).

    Cross-checkable cells call :func:`m6_2_null_anchor.make_null_anchor` with
    the M6.1.3 wall_p50 + CI half-width. New-baseline cells call
    :func:`m6_2_null_anchor.make_new_baseline_anchor` carrying only the M6.2
    wall_p50 (or ``None`` if the anchor block failed).
    """
    from vllm_grpc_bench.m6_2_null_anchor import (
        make_new_baseline_anchor,
        make_null_anchor,
    )

    by_key: dict[tuple[str, M6_1_2CohortKind, int], Any] = {}
    for point in measurements:
        if point.max_tokens not in M6_2_NULL_ANCHOR_MAX_TOKENS:
            continue
        by_key[(point.cell_id, point.cohort, point.max_tokens)] = point

    anchors: list[M6_2NullAnchor] = []
    for path, _hidden_size, concurrency in M6_1_CELLS:
        cell_id = f"{path}_c{concurrency}"
        baseline_max_tokens = _cross_checkable_max_tokens(path)
        cohorts_for_cell = baseline_per_cell.get(cell_id, {})
        for cohort in M6_1_2_COHORTS:
            for max_tokens in M6_2_NULL_ANCHOR_MAX_TOKENS:
                point = by_key.get((cell_id, cohort, max_tokens))
                m6_2_p50: float | None = None
                if point is not None and point.wall_p50_ms is not None:
                    m6_2_p50 = point.wall_p50_ms
                baseline_entry = (
                    cohorts_for_cell.get(cohort) if max_tokens == baseline_max_tokens else None
                )
                if baseline_entry is not None and baseline_entry.wall_p50_ms_ci_half_width > 0.0:
                    m6_2_ci_hw = 0.0
                    if point is not None:
                        # M6.2's per-block CI half-width is computed by the
                        # per-segment aggregator (see ``_aggregate_block_metrics``
                        # in m6_2_sweep). Thread it into the pooled-CI rule so
                        # cells whose own variance is larger than the M6.1.3
                        # baseline CI don't trip on noise. ``None`` for cells
                        # whose CI couldn't be computed (n<2) → 0.0 → floor.
                        ci_attr = getattr(point, "wall_p50_ms_ci_half_width", None)
                        if isinstance(ci_attr, int | float):
                            m6_2_ci_hw = float(ci_attr)
                    anchors.append(
                        make_null_anchor(
                            cell_id=cell_id,
                            cohort=cohort,
                            max_tokens=max_tokens,
                            m6_2_wall_p50_ms=m6_2_p50,
                            m6_1_3_wall_p50_ms=baseline_entry.wall_p50_ms,
                            m6_1_3_ci_half_width=baseline_entry.wall_p50_ms_ci_half_width,
                            m6_2_ci_half_width=m6_2_ci_hw,
                        )
                    )
                else:
                    anchors.append(
                        make_new_baseline_anchor(
                            cell_id=cell_id,
                            cohort=cohort,
                            max_tokens=max_tokens,
                            m6_2_wall_p50_ms=m6_2_p50,
                        )
                    )
    return anchors


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
    network_paths: dict[M6_1_2CohortKind, list[Any]] | None = None,
) -> M6_2SweepArtifact:
    """Assemble :class:`M6_2SweepArtifact` from the sweep outputs + ancillary
    inputs collected by :func:`run_m6_2`.

    Sections populated:

    * Production-budget rows: from the sweep's ``MeasurementPoint`` list.
    * ``not_validated`` placeholders for validate-mode interior caps: via
      :func:`m6_2_reporter.fill_validate_mode_placeholders`.
    * Anchor-latency trajectory: from per-cohort anchor snapshots. The
      drift threshold is derived from M6.1.3's
      ``between_run_variance.chat_stream_c1`` per :func:`derive_anchor_drift_threshold`
      (T054) — the previous hardcoded 5.0 ms sentinel only fires now when the
      baseline file is unreadable or absent.
    * Null-anchor validation: 48-cell list assembled by
      :func:`make_null_anchor_validation` (T053) — 22 cross-checkable cells
      verdict against M6.1.3's published CI; 26 new-baseline cells carry
      ``new_baseline_marker=True``.
    * Crossover (US2): symmetric mean-in-CI rule against M6.1.3 base verdicts.
    * KV-pressure (US3): wall-clock-ratio inference consuming sub-probe rows.
    * ``network_paths``: threaded from the sweep's topology probe (T055).
    * ``integrity_warnings``: composed via
      :func:`m6_2_reporter.build_integrity_warnings`.
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

    # M6.1.3 baseline load (used for both anchor CI threshold + crossover input
    # + null-anchor cross-checkable verdicts).
    baseline_per_cell, base_verdicts = load_m6_1_3_baseline(m6_1_3_baseline_path)

    # Anchor-latency trajectory (FR-031 / SC-016). T054 wires the threshold
    # from M6.1.3's between_run_variance.chat_stream_c1 — the cell the anchor
    # block exercises. Sentinel 5.0 ms fallback if the baseline JSON is
    # unavailable.
    anchor_trajectory = compute_anchor_latency_trajectory(
        sweep_outputs.anchor_snapshots,
        m6_1_3_baseline_ci_half_width=derive_anchor_drift_threshold(m6_1_3_baseline_path),
    )

    # US2 crossover compute. Reads M6.1.3 baseline (cohort means + classifier
    # labels) and runs the symmetric mean-in-CI rule against M6.2's per-cohort
    # axis rows. Cells without a baseline entry emit canonical "did not
    # publish" evidence.
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

    null_anchor_validation = make_null_anchor_validation(
        sweep_outputs.measurements, baseline_per_cell
    )
    resolved_network_paths: dict[M6_1_2CohortKind, list[Any]] = (
        {c: list(network_paths.get(c, [])) for c in M6_1_2_COHORTS}
        if network_paths is not None
        else {c: [] for c in M6_1_2_COHORTS}
    )

    artifact = M6_2SweepArtifact(
        schema_version="m6_1_1.v1",
        dispatch_mode="concurrent",
        run_id=run_id or f"{started}-{uuid.uuid4().hex[:8]}",
        run_started_at=started,
        run_completed_at=ended,
        run_meta=run_meta,
        per_cell=per_cell_filled,
        network_paths=resolved_network_paths,
        cohort_set=list(M6_1_2_COHORTS),
        cohort_omissions=None,
        null_anchor_validation=null_anchor_validation,
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
    is_transient: Any = None,
) -> tuple[object, list[object]]:
    """Drive the main sweep + sub-probe sequentially in a single asyncio
    runtime. Sub-probe always runs after the main sweep completes per SC-019;
    both publish and validate modes invoke it.

    ``is_transient`` is the FR-033 retry classifier for the sub-probe blocks.
    Defaults to :func:`_stub_is_transient` (never retries) when omitted, so
    test paths preserve their existing behavior.
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
        is_transient=is_transient if is_transient is not None else _stub_is_transient,
        base_seed=base_seed,
        chat_corpus=chat_corpus,
        embed_corpus=embed_corpus,
    )
    del anchor_dispatcher  # not needed by the sub-probe (it dispatches via the main dispatcher)
    return sweep_outputs, list(sub_probe_results)


# --- Real Modal-backed dispatch path ---------------------------------------


async def _run_modal_backed(
    args: argparse.Namespace,
    *,
    sweep_mode: M6_2SweepMode,
    n_per_point: int,
    chat_corpus: list[RequestSample],
    embed_corpus: list[CompletionEmbedSample],
    chat_corpus_sha256: str,
    chat_corpus_path: str,
    embed_corpus_sha256: str,
    embed_corpus_path: str,
    md_path: Path,
    json_path: Path,
    base_seed: int,
    modal_region: str,
    model_identifier: str,
) -> int:
    """Open Modal deploy + M6.2 RPC driver, run the sweep with real adapters,
    write the artifact. Returns the exit code per ``contracts/cli.md``.

    Mirrors :func:`m6_1_3_validate._run_modal_backed` (T013 / FR-028) but:

    * Uses :func:`m6_2_rpc_driver.provide_m6_2_rpc_driver` so the driver
      callable threads the M6.2 kwargs (max_tokens / ignore_eos / prompt /
      prompt_embeds_override) per block.
    * Wraps the driver in :func:`build_modal_block_dispatcher` +
      :func:`build_modal_anchor_dispatcher` to match the sweep's
      ``BlockDispatcher`` + ``AnchorRPCDriver`` Protocols.
    * Wires the FR-009 topology probe (``m6_1_2_network_probe.run_topology_probe``)
      against the handshake dict at sweep start + end.
    """
    from dataclasses import replace

    from vllm_grpc_bench.m6_1_2_network_probe import run_topology_probe
    from vllm_grpc_bench.m6_1_seq_len import pin_seq_len_at_sweep_start
    from vllm_grpc_bench.m6_2_reporter import write_m6_2_report
    from vllm_grpc_bench.m6_2_rpc_driver import provide_m6_2_rpc_driver
    from vllm_grpc_bench.m6_2_sweep import M6_2SweepInputs
    from vllm_grpc_bench.modal_endpoint import ModalDeployError, provide_m6_endpoint

    token_env = str(getattr(args, "m6_2_modal_token_env", "MODAL_BENCH_TOKEN"))

    pinned_seq_len = pin_seq_len_at_sweep_start(model_identifier)
    print(
        f"[m6_2_validate] pinned seq_len={pinned_seq_len} for model={model_identifier}",
        file=sys.stderr,
        flush=True,
    )
    axis = _resolve_axis(sweep_mode)

    try:
        async with (
            provide_m6_endpoint(
                region=modal_region,
                token_env=token_env,
                model_id=model_identifier,
            ) as endpoints,
            provide_m6_2_rpc_driver(
                endpoints,
                seq_len=pinned_seq_len,
                base_seed=base_seed,
            ) as (driver, _rtt),
        ):
            handshake_dict: dict[str, object] = {
                "rest_https_edge_url": endpoints.rest_https_edge_url or "",
                "rest_plain_tcp_url": endpoints.rest_plain_tcp_url or "",
                "grpc": endpoints.grpc_url,
            }
            del replace  # imported above for parity with M6.1.3; unused here
            block_dispatcher = build_modal_block_dispatcher(driver, base_seed=base_seed)
            anchor_dispatcher = build_modal_anchor_dispatcher(driver)

            async def _topology_probe() -> dict[M6_1_2CohortKind, Any]:
                return await run_topology_probe(handshake_dict)

            inputs = M6_2SweepInputs(
                sweep_mode=sweep_mode,
                n=n_per_point,
                axis=axis,
                base_seed=base_seed,
                chat_corpus=chat_corpus,
                embed_corpus=embed_corpus,
                dispatcher=block_dispatcher,
                anchor_dispatcher=anchor_dispatcher,
                is_transient=is_transient_modal_error,
                topology_probe=_topology_probe,
            )
            sweep_outputs, sub_probe_results = await _drive_main_sweep_and_sub_probe(
                inputs=inputs,
                dispatcher=block_dispatcher,
                anchor_dispatcher=anchor_dispatcher,
                chat_corpus=chat_corpus,
                embed_corpus=embed_corpus,
                base_seed=base_seed,
                is_transient=is_transient_modal_error,
            )
    except ModalDeployError as exc:
        print(
            f"[m6_2_validate] Modal deploy/handshake failed: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 2
    except Exception as exc:  # noqa: BLE001
        print(
            f"[m6_2_validate] sweep failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 5

    network_paths = getattr(sweep_outputs, "network_paths", None)
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
        network_paths=network_paths,
    )
    write_m6_2_report(artifact, md_path, json_path, sweep_mode=sweep_mode)
    print(
        f"[m6_2_validate] sweep_mode={sweep_mode} n_per_point={n_per_point} "
        f"axis={list(axis)} md_out={md_path} json_out={json_path}",
        flush=True,
    )
    return 0


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
        return asyncio.run(
            _run_modal_backed(
                args,
                sweep_mode=sweep_mode,
                n_per_point=n_per_point,
                chat_corpus=chat_corpus,
                embed_corpus=embed_corpus,
                chat_corpus_sha256=chat_corpus_sha256,
                chat_corpus_path=chat_corpus_path,
                embed_corpus_sha256=embed_corpus_sha256,
                embed_corpus_path=embed_corpus_path,
                md_path=md_path,
                json_path=json_path,
                base_seed=base_seed,
                modal_region=modal_region,
                model_identifier=model_identifier,
            )
        )

    # --m6_2-skip-deploy path: stub dispatcher for tests + local artifact
    # smoke-runs. Modal is never contacted.
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
        network_paths=getattr(sweep_outputs, "network_paths", None),
    )
    write_m6_2_report(artifact, md_path, json_path, sweep_mode=sweep_mode)
    print(
        f"[m6_2_validate] sweep_mode={sweep_mode} n_per_point={n_per_point} "
        f"axis={list(axis)} md_out={md_path} json_out={json_path}",
        flush=True,
    )
    return 0
