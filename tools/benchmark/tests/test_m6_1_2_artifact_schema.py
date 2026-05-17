"""M6.1.2 — Artifact-schema strict-superset tests.

Covers (per ``specs/025-m6-1-2-methodology-discipline/tasks.md``):

* T010 — strict-superset compatibility: an M6.1.2 artifact augmented with
  the three new top-level keys (``network_paths``, ``cohort_set``,
  ``cohort_omissions``) round-trips through JSON without disturbing any
  M6.1.1-known top-level key (FR-004 + SC-006).
* T017-T019 — cohort_set / cohort_omissions invariants (FR-016): union
  equals canonical 4-cohort universe; intersection is empty; pre-write
  validation raises ``ValueError`` on violation; absent vs empty
  ``cohort_omissions`` are wire-equivalent (round-2 Q2); ``cohort_set`` is
  alphabetically sorted (reader-script stability); a c=1-only sweep
  excludes ``tuned_grpc_multiplexed`` via the FR-011 collapse rule.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2_COHORTS,
    M6_1_2CohortKind,
    M6_1_2CohortOmissions,
    build_cohort_set_and_omissions,
    cohorts_at_concurrency,
)

# --- Canonical 4-cohort universe -------------------------------------------

ALL_4: set[M6_1_2CohortKind] = set(M6_1_2_COHORTS)
CANONICAL = {"rest_https_edge", "rest_plain_tcp", "default_grpc", "tuned_grpc_multiplexed"}


# --- Synthetic artifact builder ---------------------------------------------


def _synthesize_m6_1_2_artifact(
    *,
    cohort_set: list[M6_1_2CohortKind] | None = None,
    cohort_omissions: M6_1_2CohortOmissions | None = None,
    network_paths: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an M6.1.2 artifact dict carrying every M6.1.1-known top-level
    key plus the three M6.1.2 additions. Avoids importing the M6.1.1
    reporter directly so this test fixture stays decoupled from any
    refactor of M6.1.1's internals."""
    # M6.1.1-shaped keys (sourced from m6_1_1_reporter.render_json).
    base: dict[str, Any] = {
        "schema_version": "m6_1_1.v1",
        "dispatch_mode": "concurrent",
        "run_id": "2026-05-17T12:00:00Z-deadbeef",
        "run_started_at": "2026-05-17T12:00:00Z",
        "run_completed_at": "2026-05-17T12:30:00Z",
        "run_meta": {
            "git_sha": "deadbeef",
            "modal_region": "eu-west-1",
            "M6_1_BASE_SEED": 42,
            "sweep_mode": "validate",
        },
        "phase_1_classifications": {},
        "phase_1_runs": [],
        "multi_point_timings": [],
        "phase_2_outcome": None,
        "phase_2_choice": None,
        "chat_stream_baseline_post_symmetrisation": {"phase_2_path": "phase_2_pending"},
        "embed_baseline_post_symmetrisation": {"phase_2_path": "phase_2_pending"},
        "embed_regression_check": None,
        "m6_1_baseline_pointer": "docs/benchmarks/m6_1-real-prompt-embeds.json",
        "methodology_supersedence": {},
        "classifier_notes": [],
    }
    if cohort_set is None:
        actual_run: set[M6_1_2CohortKind] = ALL_4 - set((cohort_omissions or {}).keys())
        cohort_set_sorted, omissions_out = build_cohort_set_and_omissions(
            actual_run, cohort_omissions
        )
    else:
        cohort_set_sorted, omissions_out = build_cohort_set_and_omissions(
            set(cohort_set), cohort_omissions
        )
    base["cohort_set"] = cohort_set_sorted
    if omissions_out is not None:
        base["cohort_omissions"] = omissions_out
    if network_paths is None:
        network_paths = {
            cohort: {
                "endpoint_ip": "192.0.2.1",
                "hops": [
                    {
                        "hop_number": 1,
                        "ip": "192.168.1.1",
                        "rtt_ms_or_null": 1.0,
                        "cloud_provider": None,
                    }
                ],
                "cloud_provider": "AWS",
                "region": "us-west-1",
                "probe_method": "tcptraceroute",
                "probed_at_utc": "2026-05-17T12:00:00Z",
            }
            for cohort in cohort_set_sorted
        }
    base["network_paths"] = network_paths
    return base


# --- T010: strict-superset evolution ---------------------------------------


_M6_1_1_KNOWN_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "schema_version",
    "dispatch_mode",
    "run_id",
    "run_started_at",
    "run_completed_at",
    "run_meta",
    "phase_1_classifications",
    "phase_1_runs",
    "multi_point_timings",
    "phase_2_outcome",
    "phase_2_choice",
    "chat_stream_baseline_post_symmetrisation",
    "embed_baseline_post_symmetrisation",
    "embed_regression_check",
    "m6_1_baseline_pointer",
    "methodology_supersedence",
    "classifier_notes",
)


def test_m6_1_2_artifact_parses_with_m6_1_1_reader() -> None:
    """FR-004 + SC-006: every M6.1.1-known top-level key is present in the
    M6.1.2 artifact, with values that round-trip through JSON unchanged."""
    artifact = _synthesize_m6_1_2_artifact()
    text = json.dumps(artifact)
    reloaded = json.loads(text)
    missing = [k for k in _M6_1_1_KNOWN_TOP_LEVEL_KEYS if k not in reloaded]
    assert missing == [], f"M6.1.2 artifact is missing M6.1.1 top-level keys: {missing}"
    for k in _M6_1_1_KNOWN_TOP_LEVEL_KEYS:
        assert reloaded[k] == artifact[k]


def test_network_paths_block_keys() -> None:
    """FR-003: every cohort entry in ``network_paths`` carries the minimum
    success-shape keys (or the error-shape keys)."""
    artifact = _synthesize_m6_1_2_artifact()
    assert isinstance(artifact["network_paths"], dict)
    assert len(artifact["network_paths"]) > 0
    required_success_keys = {
        "endpoint_ip",
        "hops",
        "cloud_provider",
        "region",
        "probe_method",
        "probed_at_utc",
    }
    for cohort, entry in artifact["network_paths"].items():
        assert isinstance(cohort, str)
        if "error" in entry:
            assert {"error", "probe_method", "probed_at_utc"} <= set(entry.keys())
        else:
            assert required_success_keys <= set(entry.keys())
            assert entry["probe_method"] == "tcptraceroute"


# --- T017: cohort_set / cohort_omissions invariant -------------------------


def test_cohort_set_omissions_invariant() -> None:
    """FR-016: union = canonical universe; intersection = ∅."""
    artifact = _synthesize_m6_1_2_artifact(
        cohort_omissions={"rest_plain_tcp": "test omission"},
    )
    union = set(artifact["cohort_set"]) | set(artifact["cohort_omissions"].keys())
    intersection = set(artifact["cohort_set"]) & set(artifact["cohort_omissions"].keys())
    assert union == CANONICAL
    assert intersection == set()


def test_invariant_violation_raises_before_write() -> None:
    """``build_cohort_set_and_omissions`` raises ValueError on a malformed
    pair — the reporter's pre-write validation."""
    with pytest.raises(ValueError, match="cohort_set"):
        build_cohort_set_and_omissions(
            cast(set[M6_1_2CohortKind], {"rest_https_edge"}),
            None,
        )


def test_invariant_violation_overlap_raises() -> None:
    """Overlap between cohort_set and cohort_omissions also raises."""
    with pytest.raises(ValueError, match="cohort_set"):
        build_cohort_set_and_omissions(
            cast(set[M6_1_2CohortKind], CANONICAL),
            {"rest_plain_tcp": "duplicated"},
        )


def test_absent_and_empty_cohort_omissions_equivalent() -> None:
    """Round-2 Q2: absent ``cohort_omissions`` key vs empty ``{}`` —
    both mean no intentional omissions; ``build_cohort_set_and_omissions``
    collapses empty dict to ``None``."""
    _, none_omissions = build_cohort_set_and_omissions(ALL_4, None)
    _, empty_omissions = build_cohort_set_and_omissions(ALL_4, {})
    assert none_omissions is None
    assert empty_omissions is None


# --- T018: alphabetical ordering of cohort_set -----------------------------


def test_cohort_set_alphabetical_ordering() -> None:
    """``cohort_set`` is sorted alphabetically per data-model.md note —
    reader-script stability across runs."""
    artifact = _synthesize_m6_1_2_artifact()
    assert artifact["cohort_set"] == sorted(artifact["cohort_set"])
    # And specifically: the canonical alphabetical order for the 4-cohort
    # universe is the one downstream readers will encounter.
    assert artifact["cohort_set"] == [
        "default_grpc",
        "rest_https_edge",
        "rest_plain_tcp",
        "tuned_grpc_multiplexed",
    ]


# --- T019: c=1-only sweep excludes tuned_grpc_multiplexed -------------------


def test_cohort_set_at_c1_excludes_tuned_multiplexed() -> None:
    """When the entire sweep ran at c=1, ``tuned_grpc_multiplexed`` is
    collapsed into ``default_grpc`` per FR-011. The collapse is
    STRUCTURAL — ``cohort_omissions`` MUST be absent (not used to record
    a structural collapse)."""
    at_c1 = cohorts_at_concurrency(1)
    assert "tuned_grpc_multiplexed" not in at_c1
    # When only c=1 cells ran, the canonical universe still must be covered
    # — but tuned_grpc_multiplexed must appear in cohort_omissions, not
    # be silently dropped, to satisfy FR-016. The current contract treats
    # the c=1 collapse as an intentional structural omission with a
    # well-known reason.
    cohorts_run: set[M6_1_2CohortKind] = set(at_c1)
    cohort_set_sorted, omissions = build_cohort_set_and_omissions(
        cohorts_run,
        {"tuned_grpc_multiplexed": "collapsed into default_grpc at c=1 per FR-011"},
    )
    assert "tuned_grpc_multiplexed" not in cohort_set_sorted
    assert omissions is not None
    assert "tuned_grpc_multiplexed" in omissions


def test_cohorts_at_concurrency_c_ge_2_returns_all_4() -> None:
    """At c >= 2, all 4 cohorts iterate."""
    for c in (2, 4, 8):
        assert set(cohorts_at_concurrency(c)) == CANONICAL


# --- Cohort iteration order: gRPC FIRST (Modal tunnel stickiness) ----------


def test_cohorts_at_concurrency_dispatches_grpc_first() -> None:
    """gRPC cohorts MUST come first in the iteration order so the Modal
    plain-TCP gRPC tunnel sees traffic before the REST-cohort phases
    extend the idle window past Modal's tunnel timeout.

    Regression: the first live Modal sweep iterated cohorts alphabetically
    (REST first, then gRPC), and ``embed × c=1 / default_grpc`` failed
    0/50 because the gRPC tunnel had been idle for ~15 min while the two
    REST cohorts ran. Both keepalive (M1_BASELINE_KEEPALIVE) and this
    iteration order are required defenses.
    """
    # At c=1, gRPC (collapsed to default_grpc per FR-011) comes first.
    c1_order = cohorts_at_concurrency(1)
    assert c1_order[0] == "default_grpc", (
        f"c=1 iteration must start with default_grpc; got {c1_order}"
    )

    # At c >= 2, BOTH gRPC cohorts come before either REST cohort.
    for c in (2, 4, 8):
        order = cohorts_at_concurrency(c)
        # Find positions of each cohort
        positions = {cohort: i for i, cohort in enumerate(order)}
        grpc_positions = {
            positions["default_grpc"],
            positions["tuned_grpc_multiplexed"],
        }
        rest_positions = {
            positions["rest_https_edge"],
            positions["rest_plain_tcp"],
        }
        assert max(grpc_positions) < min(rest_positions), (
            f"c={c} iteration must dispatch both gRPC cohorts before either "
            f"REST cohort; got {order}"
        )
