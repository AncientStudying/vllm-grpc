"""T014 / T016 / T017 / T038 — m5_sweep end-to-end with a stub endpoint provider.

The stub provider reuses ``serve_in_process_adapter`` so the tests exercise
the M5 orchestration (warm-up, shared baseline, channel sweep) without
contacting Modal. The orchestrator's own behavior — RTT probe, server_bound
classification, low_rtt_caveat annotation, warm-up discard — is verifiable
against the in-process server even though the measured RTT is sub-millisecond
(below the FR-004 validity threshold). Tests therefore configure
``rtt_validity_threshold_ms=0`` so the orchestrator does not refuse on the
local-loopback shortcut.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.m3_sweep import serve_in_process_adapter
from vllm_grpc_bench.m3_types import M4SweepConfig, RTTRecord
from vllm_grpc_bench.m5_sweep import (
    M5SweepConfig,
    annotate_low_rtt_caveat,
    run_m5_sweep,
)


def _small_config(**overrides: object) -> M5SweepConfig:
    """Tiny config suitable for in-process testing (≤ 30 s)."""
    base = M4SweepConfig(
        baseline_n=100,
        candidate_n=100,
        expand_n=250,
        widths=(2048,),
        paths=("embed",),
        axes=("max_message_size",),
        schema_canonical_width=2048,
        skip_schema=True,
        seed=42,
        warmup_n=0,
    )
    defaults: dict[str, object] = {
        "base": base,
        "modal_region": "stub",
        "rtt_validity_threshold_ms": 0.0,  # Allow loopback (≪ 1 ms) for tests.
        "rtt_exercise_threshold_ms": 20.0,
        "warmup_n": 2,
        "rtt_probe_n": 4,
        "skip_deploy_endpoint": None,
    }
    defaults.update(overrides)
    return M5SweepConfig(**defaults)  # type: ignore[arg-type]


# Reduce cohort sizes for speed — patch M4SweepConfig defaults via override.
def _fast_config(**overrides: object) -> M5SweepConfig:
    # M4SweepConfig invariants force baseline_n / candidate_n >= 100. Embed
    # cohorts in-process run ~1-2 ms per RPC so 100 iters is ~150 ms each;
    # restricting to one axis preset, one width, one path keeps the full
    # sweep under 5 seconds per test.
    base = M4SweepConfig(
        baseline_n=100,
        candidate_n=100,
        expand_n=101,  # minimum permitted (expand_n > candidate_n)
        widths=(2048,),
        paths=("embed",),
        axes=("max_message_size",),
        schema_canonical_width=2048,
        skip_schema=True,
        seed=42,
        warmup_n=0,
    )
    defaults: dict[str, object] = {
        "base": base,
        "modal_region": "stub",
        "rtt_validity_threshold_ms": 0.0,
        "rtt_exercise_threshold_ms": 20.0,
        "warmup_n": 2,
        "rtt_probe_n": 2,
        "skip_deploy_endpoint": None,
    }
    defaults.update(overrides)
    return M5SweepConfig(**defaults)  # type: ignore[arg-type]


class TestLowRttCaveatAnnotator:
    """T014 — annotator flips iff median RTT < threshold."""

    def test_below_threshold_sets_caveat(self) -> None:
        rec = RTTRecord(n=4, median_ms=12.0, p95_ms=15.0, samples_ms=(12.0,) * 4)
        assert annotate_low_rtt_caveat(rec, threshold_ms=20.0) is True

    def test_at_threshold_no_caveat(self) -> None:
        rec = RTTRecord(n=4, median_ms=20.0, p95_ms=25.0, samples_ms=(20.0,) * 4)
        # Strict less-than: a record sitting exactly at the threshold is NOT caveated.
        assert annotate_low_rtt_caveat(rec, threshold_ms=20.0) is False

    def test_above_threshold_no_caveat(self) -> None:
        rec = RTTRecord(n=4, median_ms=80.0, p95_ms=120.0, samples_ms=(80.0,) * 4)
        assert annotate_low_rtt_caveat(rec, threshold_ms=20.0) is False


@pytest.mark.asyncio
async def test_warmup_cohort_tagged_discarded_and_excluded_from_aggregates() -> None:
    """T016 — warmup cohort lands in Run.cohorts with discarded=True; the
    run's rtt summary and recommendations exclude it.
    """
    config = _fast_config(warmup_n=2)
    run = await run_m5_sweep(config, endpoint_provider=serve_in_process_adapter, progress=False)
    warmup_cohorts = [c for c in run.cohorts if c.discarded]
    assert len(warmup_cohorts) == 1  # one per path; paths=("embed",)
    assert warmup_cohorts[0].cell.iterations == 2
    # The run-level RTT summary excludes warm-up cohorts (R-5 / non_discarded).
    # All non-discarded cohorts carry an RTT record on the M5 path.
    non_warm = [c for c in run.cohorts if not c.discarded]
    assert len(non_warm) >= 1
    for c in non_warm:
        assert c.rtt_record is not None
    # Methodology recorded the warmup_n the operator chose.
    assert run.m5_metadata is not None
    assert run.m5_metadata.warmup_n == 2


@pytest.mark.asyncio
async def test_warmup_n_zero_logs_warning(capsys: pytest.CaptureFixture[str]) -> None:
    """T016 — warmup_n=0 emits a closing stderr warning but the run continues."""
    config = _fast_config(warmup_n=0)
    run = await run_m5_sweep(config, endpoint_provider=serve_in_process_adapter, progress=False)
    err = capsys.readouterr().err
    assert "warmup-n=0" in err.lower() or "warmup_n" in err.lower()
    # No discarded cohorts on the warmup-disabled path.
    assert all(not c.discarded for c in run.cohorts)


@pytest.mark.asyncio
async def test_m5_shared_baseline_is_distinct_cohort_per_path() -> None:
    """T017 — exactly one M5 shared-baseline per path, sized at >= baseline_n,
    NOT a copy of any other cohort. The cohort metadata records modal_region.
    """
    config = _fast_config(warmup_n=0)
    run = await run_m5_sweep(config, endpoint_provider=serve_in_process_adapter, progress=False)
    baselines = [c for c in run.cohorts if c.is_baseline and c.baseline_role == "m1_shared"]
    assert len(baselines) == 1  # one per path; paths=("embed",)
    assert baselines[0].cell.iterations >= config.base.baseline_n
    # Metadata is keyed by path and references the cohort by id.
    assert run.m5_cross_host_baselines["embed"].cohort_id == baselines[0].cell.cell_id
    assert run.m5_cross_host_baselines["embed"].modal_region == "stub"


@pytest.mark.asyncio
async def test_every_non_discarded_cohort_has_rtt_record() -> None:
    """T038 — schema candidates inherit the cross-host instrumentation; here we
    cover the channel-sweep path: every cohort carries an RTT record.
    """
    config = _fast_config(warmup_n=0)
    run = await run_m5_sweep(config, endpoint_provider=serve_in_process_adapter, progress=False)
    for c in run.cohorts:
        if c.discarded:
            continue
        assert c.rtt_record is not None
        assert c.rtt_record.n >= 1
        # server_overhead_estimate_ms is set as a float (even if negative).
        assert c.server_overhead_estimate_ms is not None
        # M5 cells never carry the loopback caveat (FR-007).
        # (loopback_caveat is M4-only; on M5 cohorts the field stays at the
        # M4 schema's default. In the strict-superset JSON it is emitted as
        # False — the run's loopback_caveat_axes list is empty for M5.)
    assert run.loopback_caveat_axes == []


@pytest.mark.asyncio
async def test_run_methodology_records_thresholds_and_region() -> None:
    """The M5 metadata block captures the gate thresholds + Modal region."""
    config = _fast_config(
        rtt_validity_threshold_ms=0.0,
        rtt_exercise_threshold_ms=15.0,
        warmup_n=0,
    )
    run = await run_m5_sweep(config, endpoint_provider=serve_in_process_adapter, progress=False)
    assert run.m5_metadata is not None
    assert run.m5_metadata.m5_modal_region == "stub"
    assert run.m5_metadata.rtt_validity_threshold_ms == 0.0
    assert run.m5_metadata.rtt_exercise_threshold_ms == 15.0
    # All loopback cohorts will have median_ms < 15 ms → low_rtt_caveat=True
    non_warm = [c for c in run.cohorts if not c.discarded]
    assert any(c.low_rtt_caveat for c in non_warm)
