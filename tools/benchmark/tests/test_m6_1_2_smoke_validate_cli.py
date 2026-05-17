"""M6.1.2 — End-to-end integration test for ``--m6_1_2-validate`` (T034).

Drives the orchestrator → reporter path with a stub RPC driver +
canned topology-probe results — no Modal compute, no live network. The
test asserts the resulting JSON artifact at ``json_out``:

* Parses cleanly.
* Contains the FR-029 canonical top-level keys plus the M6.1.2-new
  ``network_paths``, ``cohort_set``, ``cohort_omissions`` keys.
* Contains per-cell rows for all 4 cohorts at ``c >= 2`` and 3 cohorts at
  ``c = 1`` (per FR-011 collapse rule).
* Records ``run_meta.sweep_mode == "validate"`` (post-/speckit-analyze C1
  remediation: mode lives in metadata, not parallel code).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from vllm_grpc_bench.m6_1_2_sweep import (
    M6_1_2RPCDriver,
    M6_1_2SweepConfig,
    run_m6_1_2_sweep,
    write_sweep_artifact,
)
from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2CohortKind,
    M6_1_2NetworkPath,
    M6_1_2NetworkPathHop,
)
from vllm_grpc_bench.m6_1_types import M6_1Cell
from vllm_grpc_bench.m6_engine_cost import EngineCostSpan
from vllm_grpc_bench.m6_sweep import RPCResult


def _stub_driver_factory() -> M6_1_2RPCDriver:
    """Build a stub RPC driver that returns canned timings per cohort."""

    async def driver(cohort: M6_1_2CohortKind, cell: M6_1Cell, seed: int) -> RPCResult:
        base_ms = {
            "rest_https_edge": 250.0,
            "rest_plain_tcp": 220.0,
            "default_grpc": 200.0,
            "tuned_grpc_multiplexed": 195.0,
        }[cohort]
        ttft = base_ms * 0.4
        return RPCResult(
            success=True,
            wall_clock_ms=base_ms,
            ttft_ms=ttft if cell.path == "chat_stream" else None,
            engine_cost=EngineCostSpan(
                engine_ttft_ms=ttft if cell.path == "chat_stream" else None,
                engine_forward_ms=12.0 if cell.path == "embed" else None,
            ),
            failure_reason=None,
        )

    return driver


def _canned_network_paths() -> dict[M6_1_2CohortKind, M6_1_2NetworkPath]:
    def _ok(csp: str, region: str, ip: str) -> M6_1_2NetworkPath:
        return M6_1_2NetworkPath(
            endpoint_ip=ip,
            hops=[
                M6_1_2NetworkPathHop(
                    hop_number=1,
                    ip="192.168.1.1",
                    rtt_ms_or_null=1.0,
                    cloud_provider=None,
                )
            ],
            cloud_provider=csp,  # type: ignore[arg-type]
            region=region,
            probe_method="tcptraceroute",
            probed_at_utc="2026-05-17T12:00:00Z",
        )

    return {
        "rest_https_edge": _ok("Microsoft Azure", "westeurope", "20.125.113.97"),
        "rest_plain_tcp": _ok("AWS", "us-west-1", "54.193.31.244"),
        "default_grpc": _ok("AWS", "us-west-1", "54.193.31.245"),
        "tuned_grpc_multiplexed": _ok("AWS", "us-west-1", "54.193.31.246"),
    }


def test_validate_sweep_end_to_end(tmp_path: Path) -> None:
    """Run --m6_1_2-validate-style sweep end-to-end via the orchestrator
    + reporter; assert the JSON artifact contains the expected keys + rows."""
    config = M6_1_2SweepConfig(
        sweep_mode="validate",
        modal_region="eu-west-1",
        base_seed=42,
        model_identifier="Qwen/Qwen3-8B",
        m6_1_1_baseline_pointer="docs/benchmarks/m6_1_1-engine-cost-instrumentation.json",
        md_out=tmp_path / "m6_1_2.md",
        json_out=tmp_path / "m6_1_2.json",
        measurement_n=3,  # keep the integration test fast
        warmup_n=1,
        skip_deploy=True,
    )
    driver = _stub_driver_factory()

    artifact = asyncio.run(
        run_m6_1_2_sweep(
            config,
            driver=driver,
            handshake_dict=None,
            network_probe_results=_canned_network_paths(),
        )
    )
    write_sweep_artifact(artifact, config.md_out, config.json_out)

    payload = json.loads(config.json_out.read_text())

    # Top-level shape
    assert payload["dispatch_mode"] == "concurrent"
    assert payload["run_meta"]["sweep_mode"] == "validate"
    assert payload["run_meta"]["modal_region"] == "eu-west-1"
    assert payload["run_meta"]["base_seed"] == 42
    assert payload["run_meta"]["model_identifier"] == "Qwen/Qwen3-8B"

    # network_paths + cohort_set
    canonical = {
        "rest_https_edge",
        "rest_plain_tcp",
        "default_grpc",
        "tuned_grpc_multiplexed",
    }
    assert set(payload["network_paths"].keys()) == canonical
    assert set(payload["cohort_set"]) == canonical
    assert payload["cohort_set"] == sorted(payload["cohort_set"])
    # cohort_omissions absent (or empty) — no intentional omissions in
    # the canonical validation sweep (all 4 cohorts run at c>=2).
    assert "cohort_omissions" not in payload or payload.get("cohort_omissions") in (None, {})

    # Per-cell rows: at c=1, 3 cohorts iterate (FR-011 collapse); at c=4/8,
    # all 4 cohorts iterate. Cells: 6 (embed×{1,4,8} + chat_stream×{1,4,8}).
    measurements = payload["measurements"]
    # Per-cell breakdown: 2 cells at c=1 × 3 cohorts + 4 cells at c>=2 × 4 cohorts
    expected_pairs = 2 * 3 + 4 * 4  # = 22
    assert len(measurements) == expected_pairs

    c1_pairs = [m for m in measurements if m["concurrency"] == 1]
    c_ge_2_pairs = [m for m in measurements if m["concurrency"] >= 2]
    c1_cohorts = {m["cohort"] for m in c1_pairs}
    c_ge_2_cohorts = {m["cohort"] for m in c_ge_2_pairs}
    assert c1_cohorts == {"rest_https_edge", "rest_plain_tcp", "default_grpc"}
    assert c_ge_2_cohorts == canonical

    # All measurements have positive attempt count + matching success count
    # (the stub driver always returns success).
    for m in measurements:
        assert m["n_attempts"] == 3
        assert m["n_successes"] == 3

    # Markdown sidecar exists and contains the cohort set heading.
    md = config.md_out.read_text()
    assert "M6.1.2 — Methodology Discipline" in md
    assert "Network paths" in md
    assert "Per-cell measurements" in md
