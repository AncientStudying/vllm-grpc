"""M6.1.2 — Methodology Discipline: shared types, literals, and cohort-iteration helpers.

Data shapes follow ``specs/025-m6-1-2-methodology-discipline/data-model.md``.

M6.1.2 mirrors M6.1.1's module-naming convention and extends M6.1's cell + cohort
universe by one cohort (``rest_plain_tcp``), reusing the M6.1 cell matrix
(``M6_1_CELLS``) verbatim per R-2 (research.md). Three additive top-level
artifact JSON keys are described here: ``network_paths`` (per-cohort topology
evidence), ``cohort_set`` (cohorts that actually ran), ``cohort_omissions``
(design-intentional omissions, never runtime failures).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Reuse M6.1's cell matrix + path enum verbatim per R-2.
from vllm_grpc_bench.m6_1_types import M6_1_CELLS, M6_1Path

# --- Cohort universe (R-3) ---------------------------------------------------

M6_1_2CohortKind = Literal[
    "rest_https_edge",
    "rest_plain_tcp",
    "default_grpc",
    "tuned_grpc_multiplexed",
]
"""The closed 4-element cohort universe for M6.1.2 sweeps (FR-016).

M6.1.1's ``M6_1_COHORTS`` is the 3-element subset (no ``rest_plain_tcp``);
M6.1.1's tuple stays frozen per FR-028. M6.1.2 extends by one cohort
(restored from M5.2 per Story 2)."""

M6_1_2_COHORTS: tuple[M6_1_2CohortKind, ...] = (
    "rest_https_edge",
    "rest_plain_tcp",
    "default_grpc",
    "tuned_grpc_multiplexed",
)

_CANONICAL_COHORT_UNIVERSE: frozenset[M6_1_2CohortKind] = frozenset(M6_1_2_COHORTS)

# --- Cloud provider enum (cohort-level) -------------------------------------

M6_1_2CloudProvider = Literal[
    "AWS",
    "Microsoft Azure",
    "GCP",
    "unknown",
]
"""Closed enum for the COHORT-level ``network_paths.<cohort>.cloud_provider``
field. Per-hop annotations may additionally hold transit-ASN strings
(``"Telia"``, ``"Cogent"``, etc.) per round-3 Q1 — the per-hop field is
best-effort and not strictly closed."""

# --- Network path entities (FR-003 wire shape) -------------------------------


@dataclass(frozen=True)
class M6_1_2NetworkPathHop:
    """One hop in a per-cohort ``tcptraceroute`` path.

    ``ip`` and ``rtt_ms_or_null`` are None when the hop was an asterisk
    (filtered). ``cloud_provider`` is best-effort per FR-003 + round-3 Q1.
    """

    hop_number: int
    ip: str | None
    rtt_ms_or_null: float | None
    cloud_provider: str | None


@dataclass(frozen=True)
class M6_1_2NetworkPath:
    """Per-cohort successful topology-probe result (FR-003 wire shape)."""

    endpoint_ip: str
    hops: list[M6_1_2NetworkPathHop]
    cloud_provider: M6_1_2CloudProvider
    region: str | None
    probe_method: Literal["tcptraceroute"]
    probed_at_utc: str


@dataclass(frozen=True)
class M6_1_2NetworkPathError:
    """Per-cohort failed topology-probe result (FR-005 wire shape).

    Discriminator from ``M6_1_2NetworkPath``: presence of the ``error`` field.
    """

    error: Literal[
        "tcptraceroute_unavailable",
        "probe_timeout",
        "subprocess_error",
        "parse_error",
    ]
    probe_method: Literal["tcptraceroute"]
    probed_at_utc: str
    detail: str | None = None


# --- Cohort omissions (FR-016) ----------------------------------------------

M6_1_2CohortOmissions = dict[M6_1_2CohortKind, str]
"""Map of design-intentional cohort omissions; cohort name → one-line reason.

Per round-2 Q2: absence of the key on the artifact is equivalent to an empty
dict — both mean "no intentional omissions". Runtime cohort failures (a
cohort that ran but every RPC errored) do NOT appear here; they appear in
per-cell error rows.
"""


# --- Cohort iteration helpers (FR-011 + FR-016) ------------------------------


def cohorts_at_concurrency(c: int) -> tuple[M6_1_2CohortKind, ...]:
    """Return the cohort tuple to iterate for a cell with the given concurrency.

    Per FR-011 (M5.2-inherited tuned-pair collapse rule, ``m5_2_sweep.py:228-237``):

    * At ``c == 1``: ``("default_grpc", "rest_https_edge", "rest_plain_tcp")``
      — ``default_grpc`` and ``tuned_grpc_multiplexed`` collapse to a single
      gRPC cohort whose ``cohort_kind`` is ``"default_grpc"``.
    * At ``c >= 2``: ``("default_grpc", "tuned_grpc_multiplexed",
      "rest_https_edge", "rest_plain_tcp")`` — all 4 cohorts.

    **Iteration order**: gRPC cohorts dispatch FIRST within each cell so the
    Modal plain-TCP gRPC tunnel sees traffic before the REST-cohort phases
    extend the idle window. The first live-Modal sweep hit
    ``embed × c=1 / default_grpc → 0/50 succ`` because the gRPC tunnel had
    been idle for ~15 min while the two REST cohorts ran. Keepalive
    (``M1_BASELINE_KEEPALIVE``) is the primary defense; this iteration
    order is belt-and-suspenders.

    Note that the wire-format ``cohort_set`` field is sorted alphabetically
    (see :func:`build_cohort_set_and_omissions`); iteration order doesn't
    leak into the published artifact.
    """
    if c == 1:
        return ("default_grpc", "rest_https_edge", "rest_plain_tcp")
    return ("default_grpc", "tuned_grpc_multiplexed", "rest_https_edge", "rest_plain_tcp")


def build_cohort_set_and_omissions(
    actual_cohorts_run: set[M6_1_2CohortKind],
    intentional_omissions: M6_1_2CohortOmissions | None,
) -> tuple[list[M6_1_2CohortKind], M6_1_2CohortOmissions | None]:
    """Validate the FR-016 invariant and return the wire-shape pair.

    Per ``contracts/artifact-schema.md`` (FR-016):

    * ``set(cohort_set) ∪ set(cohort_omissions.keys()) == canonical 4-cohort universe``
    * ``set(cohort_set) ∩ set(cohort_omissions.keys()) == ∅``

    Returns ``(sorted(cohort_set), omissions or None)`` — empty omissions
    dict collapses to ``None`` so absent / empty are wire-equivalent per
    round-2 Q2.
    """
    omissions_keys: frozenset[M6_1_2CohortKind] = (
        frozenset(intentional_omissions.keys()) if intentional_omissions else frozenset()
    )
    union = frozenset(actual_cohorts_run) | omissions_keys
    intersection = frozenset(actual_cohorts_run) & omissions_keys
    if union != _CANONICAL_COHORT_UNIVERSE:
        missing = _CANONICAL_COHORT_UNIVERSE - union
        extra = union - _CANONICAL_COHORT_UNIVERSE
        raise ValueError(
            "cohort_set ∪ cohort_omissions must equal the canonical 4-cohort universe "
            f"{sorted(_CANONICAL_COHORT_UNIVERSE)}; got union {sorted(union)} "
            f"(missing: {sorted(missing)}, extra: {sorted(extra)})"
        )
    if intersection:
        raise ValueError(
            "cohort_set ∩ cohort_omissions must be empty; cohorts appearing in both: "
            f"{sorted(intersection)}"
        )
    sorted_set: list[M6_1_2CohortKind] = sorted(actual_cohorts_run)
    omissions_out: M6_1_2CohortOmissions | None = (
        intentional_omissions if intentional_omissions else None
    )
    return sorted_set, omissions_out


# --- Sweep mode metadata literal --------------------------------------------

M6_1_2SweepMode = Literal["full", "validate"]
"""Recorded in ``run_meta.sweep_mode`` so downstream readers can distinguish
PR-merge publishable artifacts (``--m6_1_2``) from harness-wiring
confidence-builder runs (``--m6_1_2-validate``). Per ``contracts/cli.md``
"Dispatch wiring" + post-/speckit-analyze C1 remediation."""


__all__ = [
    "M6_1_2_COHORTS",
    "M6_1_CELLS",
    "M6_1Path",
    "M6_1_2CloudProvider",
    "M6_1_2CohortKind",
    "M6_1_2CohortOmissions",
    "M6_1_2NetworkPath",
    "M6_1_2NetworkPathError",
    "M6_1_2NetworkPathHop",
    "M6_1_2SweepMode",
    "build_cohort_set_and_omissions",
    "cohorts_at_concurrency",
]
