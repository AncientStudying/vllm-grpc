"""T035 — M5 frozen-channel baseline composition (FR-010).

Builds a tiny M5 sweep with one path and measures whether the resulting
``Run.frozen_channel_baselines`` carries a cohort per path with the
per-axis winners (or m1-default fallback when no axis winner exists). The
combined config is measured as its own cohort against the cross-host
endpoint at ``schema_canonical_width``.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.m3_sweep import serve_in_process_adapter
from vllm_grpc_bench.m3_types import M4SweepConfig
from vllm_grpc_bench.m5_sweep import M5SweepConfig, run_m5_sweep


def _config_with_schema() -> M5SweepConfig:
    base = M4SweepConfig(
        baseline_n=100,
        candidate_n=100,
        expand_n=101,
        widths=(2048,),
        paths=("embed",),
        axes=("max_message_size",),
        schema_candidates=("packed_token_ids",),
        schema_canonical_width=2048,
        skip_schema=False,
        seed=42,
        warmup_n=0,
    )
    return M5SweepConfig(
        base=base,
        modal_region="stub",
        rtt_validity_threshold_ms=0.0,
        rtt_exercise_threshold_ms=20.0,
        warmup_n=0,
        rtt_probe_n=2,
    )


@pytest.mark.asyncio
async def test_frozen_channel_baseline_emitted_per_path() -> None:
    config = _config_with_schema()
    run = await run_m5_sweep(config, endpoint_provider=serve_in_process_adapter, progress=False)
    assert run.frozen_channel_baselines is not None
    assert "embed" in run.frozen_channel_baselines
    fb = run.frozen_channel_baselines["embed"]
    # The cohort id points into Run.cohorts and is tagged frozen_channel.
    frozen_cohort = next(c for c in run.cohorts if c.cell.cell_id == fb.cohort_id)
    assert frozen_cohort.is_baseline is True
    assert frozen_cohort.baseline_role == "frozen_channel"
    assert frozen_cohort.cell.iterations >= config.base.baseline_n
    # measured_at_hidden_size = schema_canonical_width.
    assert fb.measured_at_hidden_size == config.base.schema_canonical_width


@pytest.mark.asyncio
async def test_frozen_baseline_inherits_m5_instrumentation() -> None:
    """T038 — frozen-channel cohorts carry RTT records like channel cohorts."""
    config = _config_with_schema()
    run = await run_m5_sweep(config, endpoint_provider=serve_in_process_adapter, progress=False)
    frozen = [c for c in run.cohorts if c.baseline_role == "frozen_channel"]
    assert frozen
    for c in frozen:
        assert c.rtt_record is not None
        assert c.server_overhead_estimate_ms is not None
