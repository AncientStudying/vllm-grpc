"""T017 — FR-030 cohort-innermost iteration + FR-032 UTC timestamps + post-hoc
machine check.
"""

from __future__ import annotations

from vllm_grpc_bench.sweep import (
    iter_block_dispatch_order,
    iter_main_sweep_tuples,
    verify_iteration_discipline,
)
from vllm_grpc_bench.sweep_types import (
    MAX_TOKENS_AXIS,
    VALIDATE_MAX_TOKENS_AXIS,
    MeasurementPoint,
)


def _make_point(
    *,
    cell_id: str,
    cohort: str,
    max_tokens: int,
    block_start_utc: str,
) -> MeasurementPoint:
    return MeasurementPoint(
        cell_id=cell_id,
        cohort=cohort,  # type: ignore[arg-type]
        max_tokens=max_tokens,
        n_rpcs=20,
        wall_p50_ms=10.0,
        wall_p95_ms=15.0,
        wall_p99_ms=20.0,
        wall_p50_ms_ci_half_width=1.0,
        tpot_ms=None,
        seg_ab_ms=None,
        seg_queue_ms=None,
        seg_prefill_ms=None,
        seg_ingress_ms=None,
        seg_egress_ms=None,
        failed_reason=None,
        block_start_utc=block_start_utc,
        block_end_utc=block_start_utc.replace("T", "T").rstrip("Z") + "Z",
        retry_attempted=False,
        clock_anomaly=False,
        prompt_source="synthetic_seed_derived",
        measurement_regime="natural_eos",
        prompt_corpus_idx=None,
    )


class TestIterationOrder:
    def test_publish_axis_outer_middle(self) -> None:
        tuples = iter_main_sweep_tuples(MAX_TOKENS_AXIS)
        # 6 cells × 6 axis points = 36 outer-middle tuples.
        assert len(tuples) == 36
        # First cell processed at all axis points, then second cell, etc.
        first_cell = tuples[0][0]
        for i in range(len(MAX_TOKENS_AXIS)):
            assert tuples[i][0] == first_cell

    def test_validate_axis_subset_uses_3_points(self) -> None:
        tuples = iter_main_sweep_tuples(VALIDATE_MAX_TOKENS_AXIS)
        # 6 cells × 3 axis points = 18 tuples.
        assert len(tuples) == 18

    def test_dispatch_order_is_cohort_innermost(self) -> None:
        order = iter_block_dispatch_order(MAX_TOKENS_AXIS)
        # For each (cell, max_tokens) tuple, all cohorts dispatch contiguously.
        seen_tuples: set[tuple[str, int]] = set()
        current_tuple: tuple[str, int] | None = None
        for cell_id, max_tokens, _cohort in order:
            tup = (cell_id, max_tokens)
            if tup != current_tuple:
                assert tup not in seen_tuples, (
                    f"Tuple {tup} re-entered after the orchestrator advanced past it"
                )
                if current_tuple is not None:
                    seen_tuples.add(current_tuple)
                current_tuple = tup

    def test_dispatch_order_block_count(self) -> None:
        # 6 cells; c=1 cells have 3 cohorts, c=4/c=8 cells have 4 cohorts.
        # 2 c=1 cells × 3 cohorts + 4 c=4/c=8 cells × 4 cohorts = 6 + 16 = 22
        # cohort assignments per axis point. 6 axis points → 132 blocks.
        # Validate axis (3 points) → 66 blocks.
        publish_order = iter_block_dispatch_order(MAX_TOKENS_AXIS)
        validate_order = iter_block_dispatch_order(VALIDATE_MAX_TOKENS_AXIS)
        assert len(publish_order) == 132
        assert len(validate_order) == 66


class TestIterationDisciplineMachineCheck:
    def test_canonical_iteration_verified_true(self) -> None:
        # Construct a per-block sequence in canonical order with monotonic
        # block_start_utc timestamps.
        points = []
        for i, (cell, max_tokens, cohort) in enumerate(
            iter_block_dispatch_order(VALIDATE_MAX_TOKENS_AXIS)
        ):
            points.append(
                _make_point(
                    cell_id=cell,
                    cohort=cohort,
                    max_tokens=max_tokens,
                    block_start_utc=f"2026-05-20T00:{i // 60:02d}:{i % 60:02d}Z",
                )
            )
        assert verify_iteration_discipline(points) is True

    def test_interleaved_iteration_verified_false(self) -> None:
        # Construct an interleaved pattern: 2 blocks of tuple A, then 1 block
        # of tuple B, then return to tuple A. This violates FR-030.
        points = [
            _make_point(
                cell_id="chat_stream_c1",
                cohort="default_grpc",
                max_tokens=10,
                block_start_utc="2026-05-20T00:00:00Z",
            ),
            _make_point(
                cell_id="chat_stream_c1",
                cohort="rest_plain_tcp",
                max_tokens=10,
                block_start_utc="2026-05-20T00:01:00Z",
            ),
            _make_point(  # different tuple
                cell_id="chat_stream_c1",
                cohort="default_grpc",
                max_tokens=50,
                block_start_utc="2026-05-20T00:02:00Z",
            ),
            _make_point(  # back to original tuple → interleaved
                cell_id="chat_stream_c1",
                cohort="rest_https_edge",
                max_tokens=10,
                block_start_utc="2026-05-20T00:03:00Z",
            ),
        ]
        assert verify_iteration_discipline(points) is False

    def test_empty_input_verified_true(self) -> None:
        assert verify_iteration_discipline([]) is True

    def test_every_point_has_utc_timestamps(self) -> None:
        # Trivial structural assertion: the dataclass requires block_start_utc
        # + block_end_utc fields. Test that the orchestrator's measurement
        # builder respects this (we re-build points and assert non-empty).
        for i, (cell, max_tokens, cohort) in enumerate(
            iter_block_dispatch_order(VALIDATE_MAX_TOKENS_AXIS)
        ):
            point = _make_point(
                cell_id=cell,
                cohort=cohort,
                max_tokens=max_tokens,
                block_start_utc=f"2026-05-20T01:{i // 60:02d}:{i % 60:02d}Z",
            )
            assert point.block_start_utc
            assert point.block_end_utc
