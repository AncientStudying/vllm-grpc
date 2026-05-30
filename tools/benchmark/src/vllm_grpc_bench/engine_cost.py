"""Engine-cost extraction + aggregation (v0.0.1 home).

Implements the harness-side parsers for the gRPC trailing-metadata and REST
JSON-payload wire formats published by the gRPC frontend and the REST shim
per ``contracts/instrumentation.md``. Also exposes the pairwise drift
warning function used by the verdict classifier (FR-014 sub-clause) and the
per-cell engine-cost aggregator used by the JSON companion's
``engine_cost_baseline[]`` section.

This is the single de-prefixed home for the cost parsers (imported by
``rpc_driver``). It is also the home for the path-discriminated cost
dataclasses (``EngineCostSpan``, ``EngineCostAggregate``): hosting them here
keeps the module a dependency leaf (it imports only :mod:`ci`), which avoids
the ``engine_cost -> types -> m6_sweep -> engine_cost`` import cycle that a
types-home facade would introduce. The legacy ``m6_types`` re-exports these
two dataclasses from here so existing consumers keep a single nominal type.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from vllm_grpc_bench.ci import estimate

# --- Cost types (own home — keeps this module a dependency leaf) -------------

M6Path = Literal["embed", "chat_stream"]
M6CohortKind = Literal["rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"]
M6_DRIFT_WARNING_PCT: float = 0.10  # FR-014 sub-clause (>10%)


@dataclass(frozen=True)
class EngineCostSpan:
    """Server-instrumented per-RPC engine cost (FR-008). Path-discriminated.

    Validation: ``engine_forward_ms is not None`` XOR
    (``engine_ttft_ms is not None`` AND ``engine_tpot_ms is not None``).
    """

    engine_forward_ms: float | None = None
    engine_ttft_ms: float | None = None
    engine_tpot_ms: float | None = None


@dataclass(frozen=True)
class EngineCostAggregate:
    """Cohort-level mean engine cost (path-discriminated)."""

    engine_forward_mean_ms: float | None = None
    engine_forward_ci_half_width_ms: float | None = None
    engine_ttft_mean_ms: float | None = None
    engine_ttft_ci_half_width_ms: float | None = None
    engine_tpot_mean_ms: float | None = None
    engine_tpot_ci_half_width_ms: float | None = None


# --- Parsers (T011) ----------------------------------------------------------


def parse_grpc_trailing_metadata(
    metadata: Sequence[tuple[str, str]] | Iterable[tuple[str, str]],
    path: M6Path,
) -> EngineCostSpan | None:
    """Read engine_cost values from gRPC trailing metadata.

    Returns ``None`` if any required key is missing or any value is not
    parseable as a float. Callers treat None as an instrumentation gap and
    record the parent RPC as engine-cost-failed (the transport-level
    success/failure of the RPC is decided by the cohort reader, not here).
    """
    md = {k: v for k, v in metadata}
    try:
        if path == "embed":
            return EngineCostSpan(
                engine_forward_ms=float(md["engine-forward-ms"]),
                engine_ttft_ms=None,
                engine_tpot_ms=None,
            )
        return EngineCostSpan(
            engine_forward_ms=None,
            engine_ttft_ms=float(md["engine-ttft-ms"]),
            engine_tpot_ms=float(md["engine-tpot-ms"]),
        )
    except (KeyError, ValueError, TypeError):
        return None


def parse_rest_response(response_json: Mapping[str, Any], path: M6Path) -> EngineCostSpan | None:
    """Read engine_cost values from REST JSON payload (top-level ``engine_cost``).

    For chat_stream, ``response_json`` is the FINAL SSE event's data payload.
    Returns None on missing or unparseable fields.
    """
    ec_raw = response_json.get("engine_cost")
    if not isinstance(ec_raw, Mapping):
        return None
    try:
        if path == "embed":
            return EngineCostSpan(
                engine_forward_ms=float(ec_raw["engine_forward_ms"]),
                engine_ttft_ms=None,
                engine_tpot_ms=None,
            )
        return EngineCostSpan(
            engine_forward_ms=None,
            engine_ttft_ms=float(ec_raw["engine_ttft_ms"]),
            engine_tpot_ms=float(ec_raw["engine_tpot_ms"]),
        )
    except (KeyError, ValueError, TypeError):
        return None


# --- Drift warning (T012) ----------------------------------------------------


def compute_drift_warning(per_cohort_engine_cost_mean_ms: Mapping[M6CohortKind, float]) -> bool:
    """Return True iff any pair of cohorts disagrees by more than 10%.

    Per FR-014 sub-clause: pairwise threshold ``> 0.10 * min(a, b)``.
    Skips pairs where ``min(a, b) <= 0`` (degenerate / zero engine cost).
    """
    means = list(per_cohort_engine_cost_mean_ms.values())
    if len(means) < 2:
        return False
    for i in range(len(means)):
        for j in range(i + 1, len(means)):
            a, b = means[i], means[j]
            base = min(a, b)
            if base <= 0:
                continue
            if abs(a - b) / base > M6_DRIFT_WARNING_PCT:
                return True
    return False


# --- Per-cell aggregation (T045) --------------------------------------------


def aggregate_engine_cost_per_cell(
    spans: Iterable[EngineCostSpan],
    path: M6Path,
) -> EngineCostAggregate:
    """Mean + 95% CI half-width per path-discriminated engine-cost field.

    For embed cells aggregates only ``engine_forward_ms`` and leaves the
    chat_stream fields as None. For chat_stream cells aggregates both
    ``engine_ttft_ms`` and ``engine_tpot_ms`` and leaves the embed field
    as None.
    """
    if path == "embed":
        values = [s.engine_forward_ms for s in spans if s.engine_forward_ms is not None]
        if not values:
            return EngineCostAggregate()
        est = estimate(values)
        half = (est.ci_high - est.ci_low) / 2.0
        return EngineCostAggregate(
            engine_forward_mean_ms=est.mean,
            engine_forward_ci_half_width_ms=half,
        )
    # chat_stream — collect both fields independently (they share the same
    # sample set; we never have one without the other on a successful RPC).
    spans_list = list(spans)
    ttft = [s.engine_ttft_ms for s in spans_list if s.engine_ttft_ms is not None]
    tpot = [s.engine_tpot_ms for s in spans_list if s.engine_tpot_ms is not None]
    if not ttft and not tpot:
        return EngineCostAggregate()
    ttft_mean: float | None = None
    ttft_half: float | None = None
    tpot_mean: float | None = None
    tpot_half: float | None = None
    if ttft:
        est_ttft = estimate(ttft)
        ttft_mean = est_ttft.mean
        ttft_half = (est_ttft.ci_high - est_ttft.ci_low) / 2.0
    if tpot:
        est_tpot = estimate(tpot)
        tpot_mean = est_tpot.mean
        tpot_half = (est_tpot.ci_high - est_tpot.ci_low) / 2.0
    return EngineCostAggregate(
        engine_ttft_mean_ms=ttft_mean,
        engine_ttft_ci_half_width_ms=ttft_half,
        engine_tpot_mean_ms=tpot_mean,
        engine_tpot_ci_half_width_ms=tpot_half,
    )
