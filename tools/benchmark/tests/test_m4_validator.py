"""US2 / T024 — validate_run forbids constructing a Recommendation with
verdict='noise_bounded' from the M4 sweep (FR-007).

The forbidden literal is preserved in the ``Verdict`` Literal for M3 report
compatibility, but the M4 sweep's recommendation builder must never emit it.
``validate_run`` is the gate.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.m3_types import (
    BenchmarkCell,
    Recommendation,
    Run,
    RunCohort,
)
from vllm_grpc_bench.m4_sweep import validate_run


def _baseline_cohort(path: str = "embed") -> RunCohort:
    cell = BenchmarkCell(
        path=path,  # type: ignore[arg-type]
        hidden_size=4096,
        channel_config=M1_BASELINE,
        corpus_subset="m1_embed" if path == "embed" else "m1_chat",  # type: ignore[arg-type]
        iterations=100,
    )
    return RunCohort(
        cell=cell,
        samples=tuple(),
        n_successful=100,
        bytes_mean=200.0,
        bytes_ci_low=199.0,
        bytes_ci_high=201.0,
        time_mean=0.01,
        time_ci_low=0.0095,
        time_ci_high=0.0105,
        is_baseline=True,
        baseline_role="m1_shared",
        time_to_first_token_seconds=(0.005, 0.0048, 0.0052) if path == "chat_stream" else None,
    )


def test_validate_run_rejects_noise_bounded_recommendation() -> None:
    embed_b = _baseline_cohort("embed")
    chat_b = _baseline_cohort("chat_stream")
    bad_rec = Recommendation(
        axis="compression",
        applies_to_path="chat_stream",
        applies_to_widths=frozenset({4096}),
        verdict="noise_bounded",
        baseline_ci_upper=0.0,
        citation="x",
        notes="forced for test",
    )
    run = Run(
        mode="m4-time-axis-tuning",
        axes=["compression"],
        widths=[4096],
        paths=["embed", "chat_stream"],
        iterations_per_cell=100,
        seed=0,
        cohorts=[embed_b, chat_b],
        pacing_mode="no_pacing",
        shared_baseline_cohort_ids={
            "embed": embed_b.cell.cell_id,
            "chat_stream": chat_b.cell.cell_id,
        },
        loopback_caveat_axes=[],
        recommendations=[bad_rec],
    )
    with pytest.raises(ValueError, match="noise_bounded"):
        validate_run(run)
