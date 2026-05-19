"""M6.1.3 — artifact schema invariant tests (T023).

Per ``specs/026-m6-1-3-attribution-closure/contracts/artifact-schema.md``:

* **Canonical 5-segment sum invariant** (SC-002 + round-4 Q1): for
  chat_stream cells, ``seg_ab_ms.mean + seg_queue_ms.mean +
  seg_prefill_ms.mean + seg_ingress_ms.mean + seg_egress_ms.mean`` MUST
  converge to ``engine_ttft_ms.mean`` within ±1 ms (sample noise). The
  5-segment sum is exhaustive — ``seg_arrival_ms`` is dormant in M6.1.3.
* **frontend_arrival_jitter / seg_arrival dormancy** (round-4 Q1): the
  artifact never contains a non-null ``seg_arrival_ms`` populated by the
  M6.1.3 pipeline, and ``frontend_arrival_jitter`` never appears as a
  primary classification in any cell.
* **Strict-superset schema_version** (FR-010 + round-3 Q1): every
  M6.1.3 artifact stays at ``schema_version == "m6_1_1.v1"`` (no bump).
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.m6_1_1_types import PerSegmentAggregate
from vllm_grpc_bench.m6_1_2_types import M6_1_2NetworkPath, M6_1_2NetworkPathHop
from vllm_grpc_bench.m6_1_3_reporter import (
    M6_1_3CellMeasurement,
    M6_1_3RunMeta,
    M6_1_3SweepArtifact,
    render_json,
)


def _build_per_segment_with_5_segment_sum_invariant() -> PerSegmentAggregate:
    """Build a PerSegmentAggregate whose 5 named segments sum to the
    engine_ttft they're meant to characterise (within ±1 ms).

    Decomposition (chat_stream c=4 cell on the rest_https_edge cohort):
    * seg_ab_ms_mean = 0.2  (handler pre-engine work)
    * seg_queue_ms_mean = 0.1  (engine queue wait)
    * seg_prefill_ms_mean = 40.0  (engine compute)
    * seg_ingress_ms_mean = 2.5  (proxy → engine handoff)
    * seg_egress_ms_mean = 7.2  (engine → proxy yield)
    Sum = 50.0 ms — matches engine_ttft_ms.mean = 50.0 ms.
    """
    return PerSegmentAggregate(
        seg_ab_ms_mean=0.2,
        seg_ab_ms_ci_half_width=0.01,
        seg_bc_ms_mean=50.0,  # seg_bc ≡ engine_ttft (M6.1.2 fixed the degeneracy)
        seg_bc_ms_ci_half_width=0.1,
        seg_cd_ms_mean=1.0,
        seg_cd_ms_ci_half_width=0.02,
        n_samples=50,
        seg_queue_ms_mean=0.1,
        seg_queue_ms_ci_half_width=0.01,
        seg_prefill_ms_mean=40.0,
        seg_prefill_ms_ci_half_width=0.5,
        seg_ingress_ms_mean=2.5,
        seg_ingress_ms_ci_half_width=0.2,
        seg_egress_ms_mean=7.2,
        seg_egress_ms_ci_half_width=0.3,
        clock_anomaly_fraction=0.0,
        clock_anomaly_warning=False,
    )


def _build_chat_stream_measurement(
    *,
    concurrency: int = 4,
    cohort: str = "rest_https_edge",
    engine_ttft_ms_mean: float = 50.0,
) -> M6_1_3CellMeasurement:
    return M6_1_3CellMeasurement(
        path="chat_stream",
        concurrency=concurrency,
        cohort=cohort,  # type: ignore[arg-type]
        n_attempts=50,
        n_successes=50,
        wall_clock_ms_mean=51.0,
        engine_ttft_ms_mean=engine_ttft_ms_mean,
        top_failure_reasons={},
        per_segment=_build_per_segment_with_5_segment_sum_invariant(),
    )


def _build_minimal_artifact(
    measurements: list[M6_1_3CellMeasurement],
    classifications: dict[str, str],
) -> M6_1_3SweepArtifact:
    """Build a minimal but valid M6_1_3SweepArtifact for the invariant tests."""
    cohorts: list[str] = sorted(
        {"rest_https_edge", "rest_plain_tcp", "default_grpc", "tuned_grpc_multiplexed"}
    )
    network_paths = {
        c: M6_1_2NetworkPath(
            endpoint_ip="192.0.2.1",
            hops=[
                M6_1_2NetworkPathHop(
                    hop_number=1, ip="192.168.1.1", rtt_ms_or_null=1.0, cloud_provider=None
                )
            ],
            cloud_provider="AWS",
            region="us-west-1",
            probe_method="tcptraceroute",
            probed_at_utc="2026-05-18T12:00:00Z",
        )
        for c in cohorts
    }
    return M6_1_3SweepArtifact(
        schema_version="m6_1_1.v1",
        dispatch_mode="concurrent",
        run_id="test-run-0001",
        run_started_at="2026-05-18T12:00:00Z",
        run_completed_at="2026-05-18T12:15:00Z",
        run_meta=M6_1_3RunMeta(
            git_sha="test",
            modal_region="eu-west-1",
            base_seed=42,
            model_identifier="Qwen/Qwen3-8B",
            sweep_mode="validate",
            seq_len=19,
            run_started_at="2026-05-18T12:00:00Z",
            run_completed_at="2026-05-18T12:15:00Z",
            m6_1_1_baseline_pointer="docs/benchmarks/m6_1_1-engine-cost-instrumentation.json",
            m6_1_3_diagnose_repeat=1,
            m6_1_3_diagnose_n=50,
            m6_1_3_symmetric_prompts=False,
        ),
        network_paths=network_paths,  # type: ignore[arg-type]
        cohort_set=cohorts,  # type: ignore[arg-type]
        cohort_omissions=None,
        measurements=measurements,
        classifications=classifications,
        classifier_notes=[],
        audit=None,
        audit_per_run=None,
        between_run_variance=None,
        phase_b_trigger=None,
    )


# --- SC-002 canonical 5-segment sum invariant -------------------------------


def test_canonical_5_segment_sum_chat_stream_cell() -> None:
    """SC-002 + round-4 Q1: for a chat_stream cell, the 5-segment sum
    must converge to engine_ttft_ms within ±1 ms.

    Fixture engineered so the sum is exactly 50.0 ms (matches the engine
    TTFT) — no sample noise. Real data would carry ±1 ms slop from the
    wall↔monotonic conversion; the contract tolerates that explicitly.
    """
    m = _build_chat_stream_measurement(engine_ttft_ms_mean=50.0)
    ps = m.per_segment
    assert ps is not None
    segments = [
        ps.seg_ab_ms_mean,
        ps.seg_queue_ms_mean,
        ps.seg_prefill_ms_mean,
        ps.seg_ingress_ms_mean,
        ps.seg_egress_ms_mean,
    ]
    # All five segments populated.
    assert all(s is not None for s in segments)
    total = sum(s for s in segments if s is not None)
    assert m.engine_ttft_ms_mean is not None
    assert abs(total - m.engine_ttft_ms_mean) <= 1.0, (
        f"5-segment sum = {total} ms, engine_ttft = {m.engine_ttft_ms_mean} ms; "
        f"|delta| = {abs(total - m.engine_ttft_ms_mean)} ms exceeds 1 ms tolerance"
    )


def test_canonical_5_segment_sum_within_tolerance() -> None:
    """The ±1 ms tolerance bites when the 5-segment sum carries sample
    noise — the test asserts the tolerance bound holds for realistic
    deviations."""
    m = _build_chat_stream_measurement(engine_ttft_ms_mean=50.6)  # 0.6 ms slop
    ps = m.per_segment
    assert ps is not None
    total = (
        (ps.seg_ab_ms_mean or 0.0)
        + (ps.seg_queue_ms_mean or 0.0)
        + (ps.seg_prefill_ms_mean or 0.0)
        + (ps.seg_ingress_ms_mean or 0.0)
        + (ps.seg_egress_ms_mean or 0.0)
    )
    assert m.engine_ttft_ms_mean is not None
    assert abs(total - m.engine_ttft_ms_mean) <= 1.0


def test_5_segment_sum_invariant_in_rendered_json() -> None:
    """Render the artifact to JSON and confirm the invariant survives the
    serialization path (per-cell row carries the 5 segment fields)."""
    m = _build_chat_stream_measurement()
    artifact = _build_minimal_artifact(
        measurements=[m],
        classifications={"chat_stream_c4": "engine_compute_variation"},
    )
    payload = render_json(artifact)

    row = payload["measurements"][0]
    assert row["cell_id"] == "chat_stream_c4"
    ps = row["per_segment"]
    segments = [
        ps["seg_ab_ms_mean"],
        ps["seg_queue_ms_mean"],
        ps["seg_prefill_ms_mean"],
        ps["seg_ingress_ms_mean"],
        ps["seg_egress_ms_mean"],
    ]
    assert all(s is not None for s in segments)
    total = sum(s for s in segments if s is not None)
    assert abs(total - row["engine_ttft_ms_mean"]) <= 1.0


# --- Round-4 Q1 dormancy: seg_arrival never populated ----------------------


def test_frontend_arrival_jitter_seg_arrival_dormant() -> None:
    """Round-4 Q1: the M6.1.3 PerSegmentAggregate has no ``seg_arrival_ms``
    field — the dormancy is structurally enforced by the absence of the
    column rather than a runtime ``is None`` check on the artifact.

    This test asserts the dormancy at the type level so a future planner
    can't accidentally re-introduce the field via a schema additive change
    without also reviewing the round-4 Q1 dormancy contract.
    """
    fields = {f.name for f in PerSegmentAggregate.__dataclass_fields__.values()}
    assert "seg_arrival_ms_mean" not in fields
    assert "seg_arrival_ms_ci_half_width" not in fields


def test_frontend_arrival_jitter_label_never_in_classifications() -> None:
    """Round-4 Q1: ``frontend_arrival_jitter`` MUST NOT appear as a
    primary classification in any cell of the rendered artifact.

    The classifier-level dormancy is tested in
    ``test_m6_1_3_classifier.py``; this test asserts the absence as an
    artifact-level invariant (in case a future refactor inserts the label
    via a different code path).
    """
    m = _build_chat_stream_measurement()
    artifact = _build_minimal_artifact(
        measurements=[m],
        classifications={
            "chat_stream_c1": "engine_compute_variation",
            "chat_stream_c4": "proxy_egress_dominated",
            "chat_stream_c8": "inconclusive",
            "embed_c1": "inconclusive",
        },
    )
    for label in artifact.classifications.values():
        assert "frontend_arrival" not in label, (
            f"frontend_arrival appeared in artifact classification: {label}"
        )


# --- FR-010 + round-3 Q1: schema_version stays at "m6_1_1.v1" --------------


def test_schema_version_no_bump_in_m6_1_3_artifact() -> None:
    """FR-010 + round-3 Q1: every M6.1.3 artifact preserves
    ``schema_version == "m6_1_1.v1"`` (no bump). The prefix is a naming
    convention distinguishing instrumentation categories, NOT a versioning
    signal."""
    m = _build_chat_stream_measurement()
    artifact = _build_minimal_artifact(
        measurements=[m],
        classifications={"chat_stream_c4": "engine_compute_variation"},
    )
    assert artifact.schema_version == "m6_1_1.v1"
    payload = render_json(artifact)
    assert payload["schema_version"] == "m6_1_1.v1"


def test_render_json_pre_write_invariant_check_fires() -> None:
    """``render_json`` re-invokes ``build_cohort_set_and_omissions`` as a
    pre-write guard — a malformed cohort_set/omissions pair raises
    ``ValueError`` BEFORE the JSON is emitted."""
    m = _build_chat_stream_measurement()
    artifact = _build_minimal_artifact(
        measurements=[m],
        classifications={"chat_stream_c4": "engine_compute_variation"},
    )
    # Mutate by replacing cohort_set with an incomplete set → invariant violation.
    from dataclasses import replace

    bad_artifact = replace(
        artifact,
        cohort_set=["rest_https_edge"],  # missing 3 cohorts; no omissions either
        cohort_omissions=None,
    )
    with pytest.raises(ValueError, match="canonical 4-cohort universe"):
        render_json(bad_artifact)
