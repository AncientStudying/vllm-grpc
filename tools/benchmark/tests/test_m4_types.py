"""Unit tests for M4 dataclasses and the seven validation invariants.

Covers ``data-model.md`` § "Validation invariants":

1. No ``noise_bounded`` verdicts on M4 cohorts/recommendations.
2. Shared baseline coverage — one M1 cohort per path.
3. Frozen baseline coverage (US3 only) — one frozen cohort per path.
4. Expansion records — every non-baseline cohort has one.
5. TTFT presence on chat_stream — every measurable chat_stream cohort has TTFT.
6. Loopback caveat consistency — the deterministic ``{keepalive,
   http2_framing} ∩ axes`` set on single-host runs.
7. Supersession completeness — every M3 ``noise_bounded`` cell has a
   supersession entry.

The validation function lives in ``vllm_grpc_bench.m4_sweep.validate_run``.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.m3_types import (
    BenchmarkCell,
    ExpansionRecord,
    FrozenChannelBaseline,
    M4SweepConfig,
    Run,
    RunCohort,
    SupersessionEntry,
)


def _make_cohort(
    *,
    path: str = "embed",
    hidden_size: int = 4096,
    config_name: str = "m1-baseline",
    corpus: str = "m1_embed",
    iterations: int = 100,
    measurable: bool = True,
    is_baseline: bool = False,
    baseline_role: str | None = None,
    expansion_record: ExpansionRecord | None = None,
    client_bound: bool = False,
    ttft: tuple[float, float, float] | None = None,
) -> RunCohort:
    cell = BenchmarkCell(
        path=path,  # type: ignore[arg-type]
        hidden_size=hidden_size,
        channel_config=M1_BASELINE if config_name == "m1-baseline" else _named_cfg(config_name),
        corpus_subset=corpus,  # type: ignore[arg-type]
        iterations=iterations,
    )
    return RunCohort(
        cell=cell,
        samples=tuple(),
        n_successful=iterations,
        bytes_mean=100.0,
        bytes_ci_low=99.0,
        bytes_ci_high=101.0,
        time_mean=0.01,
        time_ci_low=0.0095,
        time_ci_high=0.0105,
        measurable=measurable,
        is_baseline=is_baseline,
        baseline_role=baseline_role,  # type: ignore[arg-type]
        expansion_record=expansion_record,
        client_bound=client_bound,
        time_to_first_token_seconds=ttft,
    )


def _named_cfg(name: str):
    from vllm_grpc_bench.channel_config import COMPRESSION_GZIP, MAX_MSG_16MIB

    if name == "max-msg-16mib":
        return MAX_MSG_16MIB
    if name == "compression-gzip":
        return COMPRESSION_GZIP
    return M1_BASELINE


# ---------------------------------------------------------------------------
# Dataclass-level invariants
# ---------------------------------------------------------------------------


class TestExpansionRecord:
    def test_default_no_expansion_uniform_shape(self) -> None:
        rec = ExpansionRecord(
            initial_n=100,
            initial_ci_overlapped=False,
            expanded=False,
            final_n=100,
            expansion_reason=None,
        )
        assert rec.final_n == 100
        assert rec.expansion_reason is None

    def test_expanded_requires_larger_final_n(self) -> None:
        with pytest.raises(ValueError, match="final_n > initial_n"):
            ExpansionRecord(
                initial_n=100,
                initial_ci_overlapped=True,
                expanded=True,
                final_n=100,
                expansion_reason="ci_overlap",
            )

    def test_not_expanded_requires_equal_final_n(self) -> None:
        with pytest.raises(ValueError, match="final_n == initial_n"):
            ExpansionRecord(
                initial_n=100,
                initial_ci_overlapped=False,
                expanded=False,
                final_n=250,
                expansion_reason=None,
            )

    def test_final_n_below_initial_rejected(self) -> None:
        with pytest.raises(ValueError, match="final_n must be >= initial_n"):
            ExpansionRecord(
                initial_n=100,
                initial_ci_overlapped=False,
                expanded=False,
                final_n=50,
                expansion_reason=None,
            )


class TestSupersessionEntry:
    def test_well_formed(self) -> None:
        entry = SupersessionEntry(
            m3_cell_id="chat_stream|h4096|compression|m4_chat",
            m3_verdict="noise_bounded",
            m4_cell_id="chat_stream|h4096|compression|m4_chat",
            m4_verdict="recommend",
            rationale="no-pacing exposed 4.2% TTFT win under compression",
        )
        assert entry.m4_verdict == "recommend"

    def test_rejects_noise_bounded_in_m4_verdict(self) -> None:
        with pytest.raises(ValueError, match="noise_bounded"):
            SupersessionEntry(
                m3_cell_id="x",
                m3_verdict="noise_bounded",
                m4_cell_id="y",
                m4_verdict="noise_bounded",
                rationale="r",
            )

    def test_rationale_required(self) -> None:
        with pytest.raises(ValueError, match="rationale"):
            SupersessionEntry(
                m3_cell_id="x",
                m3_verdict="noise_bounded",
                m4_cell_id="y",
                m4_verdict="recommend",
                rationale="",
            )


class TestM4SweepConfig:
    def test_defaults(self) -> None:
        cfg = M4SweepConfig()
        assert cfg.pacing_mode == "no_pacing"
        assert cfg.shared_baseline is True
        assert cfg.baseline_n == 100
        assert cfg.candidate_n == 100
        assert cfg.expand_n == 250
        assert cfg.baseline_cv_warn == 0.05
        assert cfg.loopback_caveat_axes == frozenset({"keepalive", "http2_framing"})

    def test_baseline_n_floor(self) -> None:
        with pytest.raises(ValueError, match="baseline_n"):
            M4SweepConfig(baseline_n=50)

    def test_expand_n_must_exceed_candidate_n(self) -> None:
        with pytest.raises(ValueError, match="expand_n must be > candidate_n"):
            M4SweepConfig(candidate_n=250, expand_n=250)

    def test_schema_canonical_width_in_widths(self) -> None:
        with pytest.raises(ValueError, match="schema_canonical_width"):
            M4SweepConfig(widths=(2048,), schema_canonical_width=4096)


class TestFrozenChannelBaseline:
    def test_basic(self) -> None:
        baseline = FrozenChannelBaseline(
            path="chat_stream",
            cohort_id="chat_stream|h4096|frozen|m4_chat",
            channel_config_name="frozen-chat_stream-h4096",
            per_axis_winners={
                "max_message_size": "m1-default",
                "compression": "compression-gzip",
            },
            measured_at_hidden_size=4096,
        )
        assert baseline.path == "chat_stream"
        assert baseline.measured_at_hidden_size == 4096


# ---------------------------------------------------------------------------
# Run-level validation invariants — exercised through ``m4_sweep.validate_run``
# ---------------------------------------------------------------------------


def _baseline_pair(width: int = 4096) -> tuple[RunCohort, RunCohort]:
    embed_baseline = _make_cohort(
        path="embed",
        hidden_size=width,
        config_name="m1-baseline",
        corpus="m1_embed",
        is_baseline=True,
        baseline_role="m1_shared",
    )
    chat_baseline = _make_cohort(
        path="chat_stream",
        hidden_size=width,
        config_name="m1-baseline",
        corpus="m1_chat",
        is_baseline=True,
        baseline_role="m1_shared",
        ttft=(0.005, 0.0048, 0.0052),
    )
    return embed_baseline, chat_baseline


def _build_minimal_run(
    *,
    cohorts: list[RunCohort] | None = None,
    shared_ids: dict[str, str] | None = None,
    loopback: list[str] | None = None,
    supersedes: list[SupersessionEntry] | None = None,
) -> Run:
    if cohorts is None:
        embed_b, chat_b = _baseline_pair()
        cohorts = [embed_b, chat_b]
    if shared_ids is None:
        shared_ids = {
            "embed": next(c.cell.cell_id for c in cohorts if c.cell.path == "embed"),
            "chat_stream": next(c.cell.cell_id for c in cohorts if c.cell.path == "chat_stream"),
        }
    return Run(
        mode="m4-time-axis-tuning",
        axes=["compression"],
        widths=[4096],
        paths=["embed", "chat_stream"],
        iterations_per_cell=100,
        seed=0,
        cohorts=cohorts,
        pacing_mode="no_pacing",
        shared_baseline_cohort_ids=shared_ids,
        loopback_caveat_axes=loopback if loopback is not None else [],
        supersedes=supersedes if supersedes is not None else [],
    )


class TestValidateRun:
    """The seven invariants from ``data-model.md`` § Validation invariants."""

    def test_minimal_run_valid(self) -> None:
        from vllm_grpc_bench.m4_sweep import validate_run

        run = _build_minimal_run()
        validate_run(run)  # no raise

    def test_invariant_1_no_noise_bounded_recommendation(self) -> None:
        from vllm_grpc_bench.m3_types import Recommendation
        from vllm_grpc_bench.m4_sweep import validate_run

        run = _build_minimal_run()
        bad_rec = Recommendation(
            axis="compression",
            applies_to_path="chat_stream",
            applies_to_widths=frozenset({4096}),
            verdict="noise_bounded",
            baseline_ci_upper=0.0,
            citation="x",
            notes="forced for test",
        )
        run.recommendations.append(bad_rec)
        with pytest.raises(ValueError, match="noise_bounded"):
            validate_run(run)

    def test_invariant_2_shared_baseline_coverage(self) -> None:
        from vllm_grpc_bench.m4_sweep import validate_run

        embed_b, _chat_b = _baseline_pair()
        run = _build_minimal_run(
            cohorts=[embed_b],
            shared_ids={"embed": embed_b.cell.cell_id},
        )
        with pytest.raises(ValueError, match="shared baseline"):
            validate_run(run)

    def test_invariant_3_frozen_baseline_coverage(self) -> None:
        from vllm_grpc_bench.m4_sweep import validate_run

        embed_b, chat_b = _baseline_pair()
        frozen_chat = _make_cohort(
            path="chat_stream",
            hidden_size=4096,
            config_name="m1-baseline",
            corpus="m1_chat",
            is_baseline=True,
            baseline_role="frozen_channel",
            ttft=(0.005, 0.0048, 0.0052),
        )
        cohorts = [embed_b, chat_b, frozen_chat]
        run = Run(
            mode="m4-time-axis-tuning",
            axes=["compression"],
            widths=[4096],
            paths=["embed", "chat_stream"],
            iterations_per_cell=100,
            seed=0,
            cohorts=cohorts,
            pacing_mode="no_pacing",
            shared_baseline_cohort_ids={
                "embed": embed_b.cell.cell_id,
                "chat_stream": chat_b.cell.cell_id,
            },
            frozen_channel_baselines={
                # only chat_stream — embed missing → invariant #3 violation
                "chat_stream": FrozenChannelBaseline(
                    path="chat_stream",
                    cohort_id=frozen_chat.cell.cell_id,
                    channel_config_name="frozen-chat_stream-h4096",
                    per_axis_winners={},
                    measured_at_hidden_size=4096,
                )
            },
            loopback_caveat_axes=[],
        )
        with pytest.raises(ValueError, match="frozen baseline"):
            validate_run(run)

    def test_invariant_4_expansion_record_presence(self) -> None:
        from vllm_grpc_bench.m4_sweep import validate_run

        embed_b, chat_b = _baseline_pair()
        candidate = _make_cohort(
            path="embed",
            hidden_size=4096,
            config_name="compression-gzip",
            corpus="m1_embed",
            expansion_record=None,  # invariant violation
        )
        run = _build_minimal_run(cohorts=[embed_b, chat_b, candidate])
        with pytest.raises(ValueError, match="expansion_record"):
            validate_run(run)

    def test_invariant_5_ttft_presence_on_chat_stream(self) -> None:
        from vllm_grpc_bench.m4_sweep import validate_run

        embed_b, _chat_b = _baseline_pair()
        chat_no_ttft = _make_cohort(
            path="chat_stream",
            hidden_size=4096,
            config_name="m1-baseline",
            corpus="m1_chat",
            is_baseline=True,
            baseline_role="m1_shared",
            ttft=None,  # invariant violation
        )
        run = _build_minimal_run(cohorts=[embed_b, chat_no_ttft])
        with pytest.raises(ValueError, match="time_to_first_token_seconds"):
            validate_run(run)

    def test_invariant_6_loopback_caveat_consistency(self) -> None:
        from vllm_grpc_bench.m4_sweep import validate_run

        # Loopback caveat axis lists `keepalive` even though `axes` only
        # contains `compression` — invariant violation (subset rule).
        run = _build_minimal_run(loopback=["keepalive"])
        with pytest.raises(ValueError, match="loopback"):
            validate_run(run)

    def test_invariant_7_supersession_completeness(self) -> None:
        from vllm_grpc_bench.m4_sweep import validate_run

        # Build a run that names an M3 noise_bounded cell but has no
        # SupersessionEntry covering it. We model the M3-side claims as a
        # plain dict so this test is self-contained.
        embed_b, chat_b = _baseline_pair()
        candidate = _make_cohort(
            path="chat_stream",
            hidden_size=4096,
            config_name="compression-gzip",
            corpus="m1_chat",
            expansion_record=ExpansionRecord(
                initial_n=100,
                initial_ci_overlapped=False,
                expanded=False,
                final_n=100,
                expansion_reason=None,
            ),
            ttft=(0.0042, 0.004, 0.0044),
        )
        m3_unsupersededs = [
            {
                "cell_id": "chat_stream|h4096|compression|m4_chat",
                "verdict": "noise_bounded",
            }
        ]
        run = _build_minimal_run(cohorts=[embed_b, chat_b, candidate])
        with pytest.raises(ValueError, match="supersession"):
            validate_run(run, m3_noise_bounded_cells=m3_unsupersededs)
