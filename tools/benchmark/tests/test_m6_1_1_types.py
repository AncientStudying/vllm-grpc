"""M6.1.1 types — dataclass round-trip + __post_init__ validators.

Project convention is stdlib ``@dataclass(frozen=True)`` (matches M6.1's
``m6_1_types.py``), not Pydantic v2 dataclasses. Round-trip tests therefore
use ``dataclasses.asdict`` + ``json.dumps`` + ``json.loads`` rather than
Pydantic's ``model_dump_json`` / ``model_validate_json``. Literal-type
runtime validation is not enforced by stdlib dataclasses; the literal
membership is checked by ``mypy --strict`` and by downstream callers (the
classifier, the CLI dispatch, the reporter).
"""

from __future__ import annotations

import dataclasses
import json
from typing import get_args

import pytest
from vllm_grpc_bench.m6_1_1_types import (
    ATTRIBUTION_THRESHOLD,
    CHAT_STREAM_DRIFT_CLEARED_TOLERANCE,
    DRIFT_NOT_REPRODUCED_THRESHOLD,
    EMBED_REGRESSION_TOLERANCE,
    M6_1_1_BASE_SEED,
    PERTURBATION_BUDGET_NS,
    BaselineCellEntry,
    BaselineSentinel,
    DriftNotReproducedConfirmedOutcome,
    M6_1_1Cell,
    M6_1_1Run,
    M6_1_1RunMeta,
    MultiPointTimings,
    PerSegmentAggregate,
    PerSegmentDelta,
    PerturbationAudit,
    Phase1Classification,
    Phase1RunRecord,
    Phase2aVerifiedOutcome,
    Phase2bDocumentedOutcome,
    Phase2Path,
    SplitRequiredOutcome,
    TimingCheckpoint,
)

# --- Constants --------------------------------------------------------------


def test_constants_match_spec() -> None:
    assert M6_1_1_BASE_SEED == 42
    assert PERTURBATION_BUDGET_NS == 500_000
    assert pytest.approx(0.05) == DRIFT_NOT_REPRODUCED_THRESHOLD
    assert pytest.approx(0.80) == ATTRIBUTION_THRESHOLD
    assert pytest.approx(0.05) == EMBED_REGRESSION_TOLERANCE
    assert pytest.approx(0.05) == CHAT_STREAM_DRIFT_CLEARED_TOLERANCE


# --- Literal membership (runtime introspection) -----------------------------


def test_phase1_classification_literal_members() -> None:
    """The five Phase 1 outcomes per FR-010 / M6.1.2 5-bucket upgrade.

    ``engine_compute_variation`` was added when the classifier was upgraded
    to use vLLM RequestStateStats-derived segments (seg_queue / seg_prefill)
    instead of the degenerate seg_bc rule.
    """
    assert set(get_args(Phase1Classification)) == {
        "instrumentation_artifact",
        "channel_dependent_batching",
        "engine_compute_variation",
        "drift_not_reproduced",
        "inconclusive",
    }


def test_phase2_path_literal_members() -> None:
    """The five terminal/transient phase_2_path values per round-2 Q4 / Q1 / Q2 / round-3 Q2."""
    assert set(get_args(Phase2Path)) == {
        "phase_2a_verified",
        "phase_2b_documented",
        "phase_2_pending",
        "drift_not_reproduced_confirmed",
        "split_required",
    }


# --- Round-trip through JSON ------------------------------------------------


def test_cell_round_trip_via_asdict() -> None:
    """M6_1_1Cell dataclasses.asdict + JSON round-trip preserves identity."""
    cell = M6_1_1Cell(path="embed", concurrency=1, hidden_size=4096)
    blob = json.dumps(dataclasses.asdict(cell))
    rehydrated = M6_1_1Cell(**json.loads(blob))
    assert rehydrated == cell


def test_timing_checkpoint_to_per_segment_delta_ns_to_ms() -> None:
    """PerSegmentDelta.from_checkpoint converts ns -> ms via 1e-6 (FR-009)."""
    ckpt = TimingCheckpoint(
        handler_entry_ns=1_000_000,  # 1.0 ms
        pre_engine_ns=2_500_000,  # 2.5 ms  -> seg_ab = 1.5 ms
        first_chunk_ns=42_500_000,  # 42.5 ms -> seg_bc = 40.0 ms
        terminal_emit_ns=44_000_000,  # 44.0 ms -> seg_cd = 1.5 ms
        perturbation_audit_ns=200,
    )
    delta = PerSegmentDelta.from_checkpoint(ckpt)
    assert delta.seg_ab_ms == pytest.approx(1.5)
    assert delta.seg_bc_ms == pytest.approx(40.0)
    assert delta.seg_cd_ms == pytest.approx(1.5)


# --- M6_1_1Run __post_init__ validators -------------------------------------


def _make_run_meta(phase_2_path: Phase2Path) -> M6_1_1RunMeta:
    return M6_1_1RunMeta(
        git_sha="deadbeef",
        hostname="modal-eu-west-1",
        modal_function_id=None,
        gpu_type="A10G",
        modal_region="eu-west-1",
        model_identifier="Qwen/Qwen3-8B",
        hidden_size=4096,
        cold_start_s=12.3,
        max_model_len=2048,
        gpu_memory_utilization=0.92,
        engine_version="0.20.1",
        m6_1_baseline_engine_version="0.20.1",
        torch_version="2.11.0",
        M6_1_1_BASE_SEED=42,
        seq_len=512,
        phase_1_n=50,
        phase_2_path=phase_2_path,
        run_started_at="2026-05-17T09:00:00Z",
        run_completed_at="2026-05-17T09:30:00Z",
    )


def _make_phase_1_run() -> Phase1RunRecord:
    return Phase1RunRecord(
        run_id="run-1",
        run_started_at="2026-05-17T09:00:00Z",
        run_completed_at="2026-05-17T09:30:00Z",
        wall_clock_s=1800.0,
        multi_point_timings=[],
        phase_1_classifications={"chat_stream_c1_h4096": "instrumentation_artifact"},
        perturbation_audit=PerturbationAudit(
            per_cohort_per_cell={},
            exceeded=False,
        ),
        n_per_cohort=50,
    )


def _make_sentinel(path: Phase2Path) -> BaselineSentinel:
    return BaselineSentinel(
        phase_2_path=path,
        baseline_source="not_applicable",
        pointer=None,
        cells=None,
    )


def test_run_rejects_empty_phase_1_runs() -> None:
    """A published M6.1.1 report MUST contain at least one Phase 1 run (round-3 Q1)."""
    with pytest.raises(ValueError, match="phase_1_runs must be non-empty"):
        M6_1_1Run(
            schema_version="m6_1_1.v1",
            run_id="r",
            run_started_at="t",
            run_completed_at="t",
            run_meta=_make_run_meta("phase_2_pending"),
            phase_1_classifications={},
            phase_1_runs=[],
            multi_point_timings=[],
            phase_2_outcome=None,
            phase_2_choice=None,
            chat_stream_baseline_post_symmetrisation=_make_sentinel("phase_2_pending"),
            embed_baseline_post_symmetrisation=_make_sentinel("phase_2_pending"),
            embed_regression_check=None,
            m6_1_baseline_pointer="docs/benchmarks/m6_1-real-prompt-embeds.json",
            methodology_supersedence="",
        )


def test_run_pending_accepts_none_outcome() -> None:
    run = M6_1_1Run(
        schema_version="m6_1_1.v1",
        run_id="r",
        run_started_at="t",
        run_completed_at="t",
        run_meta=_make_run_meta("phase_2_pending"),
        phase_1_classifications={},
        phase_1_runs=[_make_phase_1_run()],
        multi_point_timings=[],
        phase_2_outcome=None,
        phase_2_choice=None,
        chat_stream_baseline_post_symmetrisation=_make_sentinel("phase_2_pending"),
        embed_baseline_post_symmetrisation=_make_sentinel("phase_2_pending"),
        embed_regression_check=None,
        m6_1_baseline_pointer="docs/benchmarks/m6_1-real-prompt-embeds.json",
        methodology_supersedence="",
    )
    assert run.phase_2_outcome is None
    assert run.run_meta.phase_2_path == "phase_2_pending"


def test_run_rejects_outcome_mismatch_with_phase_2_path() -> None:
    """A Phase2bDocumentedOutcome under phase_2_path="phase_2a_verified" is rejected."""
    with pytest.raises(ValueError, match="inconsistent with run_meta.phase_2_path"):
        M6_1_1Run(
            schema_version="m6_1_1.v1",
            run_id="r",
            run_started_at="t",
            run_completed_at="t",
            run_meta=_make_run_meta("phase_2a_verified"),
            phase_1_classifications={},
            phase_1_runs=[_make_phase_1_run()],
            multi_point_timings=[],
            phase_2_outcome=Phase2bDocumentedOutcome(
                contracts_heading_path="contracts/instrumentation.md",
                contracts_heading_text="## M6.1.1: x",
            ),
            phase_2_choice=None,
            chat_stream_baseline_post_symmetrisation=_make_sentinel("phase_2a_verified"),
            embed_baseline_post_symmetrisation=_make_sentinel("phase_2a_verified"),
            embed_regression_check=None,
            m6_1_baseline_pointer="docs/benchmarks/m6_1-real-prompt-embeds.json",
            methodology_supersedence="",
        )


@pytest.mark.parametrize(
    "path,outcome_factory",
    [
        (
            "phase_2a_verified",
            lambda: Phase2aVerifiedOutcome(
                drift_cleared_per_cell={},
                engine_cost_drift_warning_per_cell={},
                chat_stream_control_drift_warning=True,
                chat_stream_control_drift_note="expected under symmetrisation",
            ),
        ),
        (
            "phase_2b_documented",
            lambda: Phase2bDocumentedOutcome(
                contracts_heading_path="contracts/instrumentation.md",
                contracts_heading_text="## M6.1.1: Channel-Dependent Batching Effect",
            ),
        ),
        (
            "drift_not_reproduced_confirmed",
            lambda: DriftNotReproducedConfirmedOutcome(
                note="drift not reproduced in two independent runs",
                confirming_run_ids=("run-1", "run-2"),
            ),
        ),
        (
            "split_required",
            lambda: SplitRequiredOutcome(
                per_cell_classifications_after_reconfirmation={
                    "chat_stream_c1_h4096": "instrumentation_artifact",
                    "chat_stream_c8_h4096": "channel_dependent_batching",
                },
                proposed_split_shape="M6.1.1a / M6.1.1b",
                operator_note="heterogeneous classifications persist across two runs",
            ),
        ),
    ],
)
def test_run_accepts_consistent_outcome_for_each_phase_2_path(
    path: Phase2Path,
    outcome_factory: object,
) -> None:
    run = M6_1_1Run(
        schema_version="m6_1_1.v1",
        run_id="r",
        run_started_at="t",
        run_completed_at="t",
        run_meta=_make_run_meta(path),
        phase_1_classifications={},
        phase_1_runs=[_make_phase_1_run()],
        multi_point_timings=[],
        phase_2_outcome=outcome_factory(),  # type: ignore[operator]
        phase_2_choice=None,
        chat_stream_baseline_post_symmetrisation=_make_sentinel(path),
        embed_baseline_post_symmetrisation=_make_sentinel(path),
        embed_regression_check=None,
        m6_1_baseline_pointer="docs/benchmarks/m6_1-real-prompt-embeds.json",
        methodology_supersedence="",
    )
    assert run.run_meta.phase_2_path == path
    assert run.phase_2_outcome is not None


# --- Multi-point timings + aggregates ---------------------------------------


def test_multi_point_timings_construction() -> None:
    """Sanity check: MultiPointTimings carries the cohort + cell + means."""
    cell = M6_1_1Cell(path="chat_stream", concurrency=1, hidden_size=4096)
    mpt = MultiPointTimings(
        cohort="rest_https_edge",
        cell=cell,
        engine_ttft_ms_mean=43.5,
        engine_ttft_ms_ci_half_width=0.6,
        per_segment=PerSegmentAggregate(
            seg_ab_ms_mean=2.1,
            seg_ab_ms_ci_half_width=0.1,
            seg_bc_ms_mean=40.0,
            seg_bc_ms_ci_half_width=0.5,
            seg_cd_ms_mean=1.4,
            seg_cd_ms_ci_half_width=0.05,
            n_samples=50,
        ),
        perturbation_total_us_mean=0.8,
    )
    assert mpt.cell == cell
    assert mpt.per_segment.n_samples == 50


# --- Sentinel baseline ------------------------------------------------------


def test_baseline_sentinel_under_phase_2_pending_carries_no_cells() -> None:
    """Under non-Phase-2(a) outcomes the sentinel has baseline_source != 'm6_1_1'
    and cells is None (round-2 Q1 dispatch table)."""
    sentinel = BaselineSentinel(
        phase_2_path="phase_2_pending",
        baseline_source="not_applicable",
        pointer=None,
        cells=None,
    )
    assert sentinel.cells is None
    assert sentinel.pointer is None


def test_baseline_sentinel_under_phase_2a_verified_carries_cells() -> None:
    """Under Phase 2(a) the sentinel populates 9 cell entries."""
    cell = M6_1_1Cell(path="chat_stream", concurrency=1, hidden_size=4096)
    entry = BaselineCellEntry(
        cell=cell,
        cohort="rest_https_edge",
        engine_ttft_ms_mean=42.0,
        engine_ttft_ms_ci_half_width=0.5,
        engine_tpot_ms_mean=8.0,
        engine_tpot_ms_ci_half_width=0.1,
        engine_forward_ms_mean=None,
        engine_forward_ms_ci_half_width=None,
        n_successes=100,
        regression_warning=None,
    )
    sentinel = BaselineSentinel(
        phase_2_path="phase_2a_verified",
        baseline_source="m6_1_1",
        pointer="docs/benchmarks/m6_1_1-engine-cost-instrumentation.json",
        cells=[entry],
    )
    assert sentinel.cells is not None
    assert len(sentinel.cells) == 1
    assert sentinel.cells[0].engine_ttft_ms_mean == 42.0
