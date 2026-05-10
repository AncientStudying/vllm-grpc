"""US1 / FR-002 — shared-baseline orchestration and borderline-expand.

T007 — shared-baseline orchestrator records exactly one M1_BASELINE cohort
per path for the whole run.

T008 — borderline-expand mechanic — a candidate cohort whose initial 95% CI
overlaps the baseline's 95% CI is replaced (not appended) by an n=expand_n
re-measurement; non-overlapping cohort is not.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.channel_config import (
    COMPRESSION_GZIP,
    M1_BASELINE,
    MAX_MSG_16MIB,
)
from vllm_grpc_bench.m3_types import (
    BenchmarkCell,
    ExpansionRecord,
    RunCohort,
    Sample,
)


def _make_samples(values: list[float], cell_id: str) -> tuple[Sample, ...]:
    return tuple(
        Sample(
            cell_id=cell_id,
            iteration=i,
            request_wire_bytes=100,
            response_wire_bytes=100,
            wall_clock_seconds=v,
            tokens_emitted=4,
            time_to_first_token_seconds=v * 0.5,
        )
        for i, v in enumerate(values)
    )


def _make_cohort(
    *,
    path: str,
    config_name: str = "m1-baseline",
    corpus: str = "m1_embed",
    hidden_size: int = 4096,
    iterations: int = 100,
    time_mean: float = 0.01,
    time_ci_low: float = 0.0095,
    time_ci_high: float = 0.0105,
    is_baseline: bool = False,
    baseline_role: str | None = None,
    expansion_record: ExpansionRecord | None = None,
    ttft: tuple[float, float, float] | None = None,
) -> RunCohort:
    cfg = (
        M1_BASELINE
        if config_name == "m1-baseline"
        else (COMPRESSION_GZIP if config_name == "compression-gzip" else MAX_MSG_16MIB)
    )
    cell = BenchmarkCell(
        path=path,  # type: ignore[arg-type]
        hidden_size=hidden_size,
        channel_config=cfg,
        corpus_subset=corpus,  # type: ignore[arg-type]
        iterations=iterations,
    )
    return RunCohort(
        cell=cell,
        samples=_make_samples([time_mean] * iterations, cell.cell_id),
        n_successful=iterations,
        bytes_mean=200.0,
        bytes_ci_low=199.0,
        bytes_ci_high=201.0,
        time_mean=time_mean,
        time_ci_low=time_ci_low,
        time_ci_high=time_ci_high,
        measurable=True,
        is_baseline=is_baseline,
        baseline_role=baseline_role,  # type: ignore[arg-type]
        expansion_record=expansion_record,
        time_to_first_token_seconds=ttft,
    )


class TestSharedBaselineOrchestration:
    """T007 — exactly one M1_BASELINE cohort per path for the whole run."""

    def test_one_baseline_per_path(self) -> None:
        from vllm_grpc_bench.m4_sweep import collect_shared_baseline_cohort_ids

        embed_b = _make_cohort(
            path="embed",
            corpus="m1_embed",
            is_baseline=True,
            baseline_role="m1_shared",
        )
        chat_b = _make_cohort(
            path="chat_stream",
            corpus="m1_chat",
            is_baseline=True,
            baseline_role="m1_shared",
            ttft=(0.005, 0.0048, 0.0052),
        )
        candidate = _make_cohort(
            path="embed",
            config_name="compression-gzip",
            corpus="m1_embed",
            expansion_record=ExpansionRecord(
                initial_n=100,
                initial_ci_overlapped=False,
                expanded=False,
                final_n=100,
            ),
        )
        ids = collect_shared_baseline_cohort_ids([embed_b, chat_b, candidate])
        assert ids == {
            "embed": embed_b.cell.cell_id,
            "chat_stream": chat_b.cell.cell_id,
        }

    def test_multiple_baselines_per_path_rejected(self) -> None:
        from vllm_grpc_bench.m4_sweep import collect_shared_baseline_cohort_ids

        embed_a = _make_cohort(
            path="embed",
            corpus="m1_embed",
            is_baseline=True,
            baseline_role="m1_shared",
        )
        embed_b = _make_cohort(
            path="embed",
            corpus="m1_embed",
            is_baseline=True,
            baseline_role="m1_shared",
        )
        with pytest.raises(ValueError, match="multiple"):
            collect_shared_baseline_cohort_ids([embed_a, embed_b])


class TestBorderlineExpand:
    """T008 — borderline-expand: CI overlap → re-measure at expand_n; replace samples."""

    def test_overlapping_ci_triggers_expand(self) -> None:
        from vllm_grpc_bench.m4_sweep import detect_ci_overlap

        baseline = _make_cohort(
            path="embed",
            corpus="m1_embed",
            time_ci_low=0.010,
            time_ci_high=0.012,
        )
        # Candidate CI overlaps baseline CI ([0.011, 0.013] ∩ [0.010, 0.012])
        candidate = _make_cohort(
            path="embed",
            config_name="compression-gzip",
            corpus="m1_embed",
            time_ci_low=0.011,
            time_ci_high=0.013,
        )
        assert detect_ci_overlap(baseline, candidate, metric="time") is True

    def test_non_overlapping_ci_no_expand(self) -> None:
        from vllm_grpc_bench.m4_sweep import detect_ci_overlap

        baseline = _make_cohort(
            path="embed",
            corpus="m1_embed",
            time_ci_low=0.010,
            time_ci_high=0.012,
        )
        # Candidate CI [0.0090, 0.0095] strictly clears baseline.
        candidate = _make_cohort(
            path="embed",
            config_name="compression-gzip",
            corpus="m1_embed",
            time_ci_low=0.0090,
            time_ci_high=0.0095,
        )
        assert detect_ci_overlap(baseline, candidate, metric="time") is False

    @pytest.mark.asyncio
    async def test_expansion_replaces_samples_not_appends(self) -> None:
        """Per R-4: expanded cohorts have the n=initial_n samples replaced
        by a fresh n=final_n batch — NOT a 100+150 = 250 mixed batch.
        """
        from vllm_grpc_bench.m4_sweep import expand_cohort

        original = _make_cohort(
            path="embed",
            config_name="compression-gzip",
            corpus="m1_embed",
            iterations=100,
        )

        async def remeasure(target_n: int) -> RunCohort:
            return _make_cohort(
                path="embed",
                config_name="compression-gzip",
                corpus="m1_embed",
                iterations=target_n,
                time_mean=0.0093,
                time_ci_low=0.0091,
                time_ci_high=0.0095,
            )

        expanded = await expand_cohort(
            original, target_n=250, remeasure=remeasure, reason="ci_overlap"
        )
        assert expanded.cell.iterations == 250
        # Samples are *replaced*, not appended: the new sample tuple length is
        # exactly target_n, not original_n + delta.
        assert len(expanded.samples) == 250
        assert expanded.expansion_record is not None
        assert expanded.expansion_record.expanded is True
        assert expanded.expansion_record.final_n == 250
        assert expanded.expansion_record.expansion_reason == "ci_overlap"


class TestEndpointProviderDefaultPreservesM4:
    """T010 — bit-identical-M4-reproduction guard for the endpoint_provider refactor.

    Calling ``run_m4_sweep(config)`` without an explicit ``endpoint_provider``
    must produce a Run with the same *deterministic* structural fingerprint
    (cohort cell-id set, recommendation count, shared-baseline mapping,
    M5-field defaults) as passing ``serve_in_process_adapter`` explicitly.

    Per-cohort sample counts deliberately are not part of the fingerprint:
    the borderline-expand cascade (R-4) is timing-dependent, so a candidate
    whose initial CI happens to overlap the baseline gets re-measured at
    ``expand_n``, and that overlap is a property of the measurement noise on
    the host rather than of the endpoint provider.
    """

    @pytest.mark.asyncio
    async def test_default_run_m4_sweep_matches_explicit_adapter_fingerprint(self) -> None:
        from vllm_grpc_bench.m3_sweep import serve_in_process_adapter
        from vllm_grpc_bench.m3_types import M4SweepConfig
        from vllm_grpc_bench.m4_sweep import run_m4_sweep

        config = M4SweepConfig(
            axes=("max_message_size",),
            widths=(4096,),
            paths=("embed",),
            schema_canonical_width=4096,
            skip_schema=True,
            baseline_n=100,
            candidate_n=100,
            expand_n=250,
            warmup_n=0,
            seed=0,
        )
        run_default = await run_m4_sweep(config, progress=False, is_loopback=True)
        run_explicit = await run_m4_sweep(
            config,
            progress=False,
            is_loopback=True,
            endpoint_provider=serve_in_process_adapter,
        )

        # Same cohort set (cell_id is deterministic from config + channel preset).
        assert {c.cell.cell_id for c in run_default.cohorts} == {
            c.cell.cell_id for c in run_explicit.cohorts
        }
        # Same recommendation count (one per axis × path × width).
        assert len(run_default.recommendations) == len(run_explicit.recommendations)
        # Same axes/widths/paths recommendation coverage (deterministic from config).
        default_rec_keys = {
            (r.axis, r.applies_to_path, tuple(sorted(r.applies_to_widths)))
            for r in run_default.recommendations
        }
        explicit_rec_keys = {
            (r.axis, r.applies_to_path, tuple(sorted(r.applies_to_widths)))
            for r in run_explicit.recommendations
        }
        assert default_rec_keys == explicit_rec_keys
        # Same shared-baseline mapping.
        assert run_default.shared_baseline_cohort_ids == run_explicit.shared_baseline_cohort_ids
        # M5 fields default to absent / False on M4-default runs (FR-014 strict
        # superset; non-M5 cohorts must remain zero-valued so M4 readers keep
        # working without code changes).
        for cohort in (*run_default.cohorts, *run_explicit.cohorts):
            assert cohort.rtt_record is None
            assert cohort.server_bound is False
            assert cohort.low_rtt_caveat is False
            assert cohort.discarded is False
            assert cohort.server_overhead_estimate_ms is None
        assert run_default.m5_metadata is None
        assert run_default.m5_cross_host_baselines == {}
        assert run_default.supersedes_m4 == []
