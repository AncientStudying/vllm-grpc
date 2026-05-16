"""End-to-end MVP test for the M6 sweep (US1 acceptance criteria).

Exercises the full Phase 3 pipeline against a mock RPC driver:
- ``run_sweep`` → classify all 6 cells
- ``build_m6_run`` → assemble M6Run
- ``write_markdown`` + ``write_json`` → publish artifacts
- Validate that:
  - All 6 cells receive exactly one terminal classification (SC-002).
  - Markdown executive section names the model + GPU + region (SC-005).
  - JSON companion is a strict superset of M5.2's schema (FR-016 / SC-007).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

from vllm_grpc_bench.m3_types import RTTRecord
from vllm_grpc_bench.m6_reporter import build_m6_run, write_json, write_markdown
from vllm_grpc_bench.m6_supersede import (
    load_and_validate_m5_2_baseline,
    snapshot_m5_2_winner_deltas,
)
from vllm_grpc_bench.m6_sweep import RPCResult, run_sweep
from vllm_grpc_bench.m6_types import EngineCostSpan, M6Cell, M6CohortKind, M6RunMeta


def _fake_engine_cost(path: str) -> EngineCostSpan:
    if path == "embed":
        return EngineCostSpan(engine_forward_ms=12.0)
    return EngineCostSpan(engine_ttft_ms=200.0, engine_tpot_ms=30.0)


async def _good_driver(cohort: M6CohortKind, cell: M6Cell, seed: int) -> RPCResult:
    """Always-successful mock driver. Cohort-specific means so the
    classifier sees realistic differences.
    """
    cohort_offsets: dict[M6CohortKind, float] = {
        "rest_https_edge": 150.0,
        "default_grpc": 110.0,
        "tuned_grpc_multiplexed": 100.0,
    }
    base = cohort_offsets[cohort]
    return RPCResult(
        success=True,
        wall_clock_ms=base + (seed % 5),  # tiny per-RPC jitter for non-zero CIs
        ttft_ms=(base * 0.4) if cell.path == "chat_stream" else None,
        engine_cost=_fake_engine_cost(cell.path),
        failure_reason=None,
    )


def test_full_sweep_classifies_all_six_cells_and_writes_artifacts(tmp_path: Path) -> None:
    """SC-001 / SC-002 / SC-005 / SC-007: full sweep end-to-end MVP.

    Uses the published M5.2 baseline so the R-6 cohort mapping is real.
    """
    real_baseline = Path("docs/benchmarks/m5_2-transport-vs-tuning.json")
    if not real_baseline.exists():
        return
    baseline = load_and_validate_m5_2_baseline(real_baseline)

    cells, _measurements = asyncio.run(run_sweep(_good_driver, baseline))
    # SC-002: each of the 6 M6 cells receives exactly one terminal classification.
    assert len(cells) == 6
    valid_classifications = {
        "verdict_survives",
        "verdict_changed",
        "verdict_buried_by_engine",
        "no_winner_at_n100",
        "cell_incomplete",
    }
    for cell in cells:
        assert cell.classification in valid_classifications

    # Build the run + write the artifacts.
    meta = M6RunMeta(
        git_sha="testsha",
        hostname="test-host",
        modal_function_id="fn-test",
        gpu_type="A10G",
        modal_region="eu-west-1",
        model_identifier="Qwen/Qwen3-8B",
        engine_version="0.20.1",
        cold_start_s=28.4,
        m5_2_winner_deltas=snapshot_m5_2_winner_deltas(baseline),
        m6_base_seed=42,
    )
    rtt_distribution: dict[M6CohortKind, RTTRecord] = {
        cast(M6CohortKind, kind): RTTRecord(
            n=5,
            median_ms=52.0,
            p95_ms=54.0,
            samples_ms=tuple(50.0 + i for i in range(5)),
        )
        for kind in ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed")
    }
    run = build_m6_run(
        run_id="test-run",
        run_started_at="2026-05-15T12:00:00Z",
        run_completed_at="2026-05-15T13:30:00Z",
        meta=meta,
        cells=cells,
        rtt_distribution=rtt_distribution,
    )

    md_path = tmp_path / "m6.md"
    json_path = tmp_path / "m6.json"
    write_markdown(run, md_path)
    write_json(run, json_path)

    # SC-005: executive section names the inference engine, model, GPU,
    # region within the first screenful.
    md_text = md_path.read_text()
    first_screen = md_text[:2000]
    assert "vLLM" in first_screen
    assert "Qwen/Qwen3-8B" in first_screen
    assert "A10G" in first_screen
    assert "eu-west-1" in first_screen

    # SC-007 / FR-016: M5.2-strict-superset fields present in JSON.
    doc = json.loads(json_path.read_text())
    for key in (
        "schema_version",
        "cohorts",
        "protocol_comparison_verdicts",
        "transport_only_verdicts",
        "supersedes_m5_2_under_real_engine",
        "engine_cost_baseline",
        "m6_meta",
    ):
        assert key in doc
    assert doc["schema_version"] == "m6.v1"

    # protocol_comparison_verdicts has one row per cell with M5.2-shape fields.
    pcv = doc["protocol_comparison_verdicts"]
    assert len(pcv) == 6
    for row in pcv:
        for required in ("path", "hidden_size", "concurrency", "grpc_cohort", "verdict"):
            assert required in row

    # m6_meta.m5_2_winner_deltas snapshot has all 6 cells.
    assert len(doc["m6_meta"]["m5_2_winner_deltas"]) == 6
