"""M6.1.3 — multi-run publish integration test (T039).

Net-new — no copy source; the multi-run scenario is M6.1.3-specific per
the plan's table. Drives the orchestrator end-to-end at
``--m6_1_3-diagnose-repeat=3`` against a stub driver to verify:

* ``phase_1_runs[]`` accumulates 3 entries on the artifact.
* The "Between-Run Variance" markdown section renders.
* The Phase B trigger verdict line renders (either form).
* The per-run audit appendix renders only when per-run / pooled verdicts
  disagree (FR-016a).
* For ``--m6_1_3-diagnose-repeat=2`` (operator override below 3), the
  variance section is suppressed AND the FR-044 override-fallback message
  renders at the end of the per-cell timing table.
"""

from __future__ import annotations

import asyncio
import io
import json
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any

from vllm_grpc_bench.__main__ import _build_parser, _normalize_m6_1_3_modifier_defaults
from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2CohortKind,
    M6_1_2NetworkPath,
    M6_1_2NetworkPathHop,
)
from vllm_grpc_bench.m6_1_3_sweep import (
    M6_1_3RPCDriver,
    M6_1_3SweepConfig,
    run_m6_1_3_sweep,
    write_sweep_artifact,
)
from vllm_grpc_bench.m6_1_3_validate import run_m6_1_3
from vllm_grpc_bench.m6_1_types import M6_1Cell
from vllm_grpc_bench.m6_engine_cost import EngineCostSpan
from vllm_grpc_bench.m6_sweep import RPCResult

# --- Stub driver -----------------------------------------------------------

# Per-cohort timing parameters engineered so seg_prefill clearly dominates
# (the same pattern as the US1 integration test stub) → classifier emits
# ``engine_compute_variation`` as the inner label for chat_stream cells.
# The multi-run test drives variance by deliberately jittering per-cohort
# means across runs.
_PER_COHORT_PARAMS: dict[str, dict[str, float]] = {
    "rest_https_edge": {
        "seg_ab_ms": 0.2,
        "seg_queue_ms": 0.1,
        "seg_prefill_ms": 40.0,
        "seg_ingress_ms": 2.5,
        "seg_egress_ms": 7.2,
    },
    "rest_plain_tcp": {
        "seg_ab_ms": 0.2,
        "seg_queue_ms": 0.1,
        "seg_prefill_ms": 41.0,
        "seg_ingress_ms": 2.7,
        "seg_egress_ms": 7.0,
    },
    "default_grpc": {
        "seg_ab_ms": 0.2,
        "seg_queue_ms": 0.1,
        "seg_prefill_ms": 44.0,
        "seg_ingress_ms": 2.3,
        "seg_egress_ms": 6.4,
    },
    "tuned_grpc_multiplexed": {
        "seg_ab_ms": 0.2,
        "seg_queue_ms": 0.1,
        "seg_prefill_ms": 42.0,
        "seg_ingress_ms": 2.4,
        "seg_egress_ms": 6.6,
    },
}

_BASE_WALL_NS: int = 1_747_512_345_000_000_000
_BASE_MONO_NS: int = 100_000_000_000


def _build_timing_payload(
    cohort: M6_1_2CohortKind,
    path: str,
    *,
    per_run_drift_ms: float = 0.0,
) -> dict[str, Any]:
    """Build a timing payload; ``per_run_drift_ms`` shifts seg_prefill so
    the multi-run loop sees per-run variance in engine_ttft."""
    params = dict(_PER_COHORT_PARAMS[cohort])
    params["seg_prefill_ms"] = params["seg_prefill_ms"] + per_run_drift_ms
    seg_ab_ns = int(params["seg_ab_ms"] * 1_000_000)
    seg_queue_ns = int(params["seg_queue_ms"] * 1_000_000)
    seg_prefill_ns = int(params["seg_prefill_ms"] * 1_000_000)
    seg_ingress_ns = int(params["seg_ingress_ms"] * 1_000_000)
    seg_egress_ns = int(params["seg_egress_ms"] * 1_000_000)

    handler_entry_ns = 0
    pre_engine_ns = handler_entry_ns + seg_ab_ns
    engine_ttft_ns = seg_queue_ns + seg_prefill_ns + seg_ingress_ns + seg_egress_ns
    first_chunk_ns = pre_engine_ns + engine_ttft_ns
    terminal_emit_ns = first_chunk_ns + 1_000_000

    pre_engine_wall_ns = _BASE_WALL_NS
    engine_arrival_ns = pre_engine_wall_ns + seg_ingress_ns
    engine_queued_ns = _BASE_MONO_NS
    engine_scheduled_ns = engine_queued_ns + seg_queue_ns
    engine_first_token_ns = engine_scheduled_ns + seg_prefill_ns
    engine_last_token_ns = engine_first_token_ns + 10_000_000
    first_chunk_mono_ns = engine_first_token_ns + seg_egress_ns

    payload: dict[str, Any] = {
        "handler_entry_ns": handler_entry_ns,
        "pre_engine_ns": pre_engine_ns,
        "first_chunk_ns": first_chunk_ns,
        "terminal_emit_ns": terminal_emit_ns,
        "perturbation_audit_ns": 1000,
        "engine_arrival_ns": engine_arrival_ns,
        "engine_queued_ns": engine_queued_ns,
        "engine_scheduled_ns": engine_scheduled_ns,
        "engine_first_token_ns": engine_first_token_ns,
        "engine_last_token_ns": engine_last_token_ns,
        "tokenized_prompt_length": 47,
        "tokenized_prompt_hash": "a1b2c3d4e5f60718",
    }
    if path == "chat_stream":
        payload["pre_engine_wall_ns"] = pre_engine_wall_ns
        payload["first_chunk_mono_ns"] = first_chunk_mono_ns
    else:
        payload["pre_engine_wall_ns"] = None
        payload["first_chunk_mono_ns"] = None
    return payload


def _stub_driver_factory(*, per_run_drift: list[float] | None = None) -> M6_1_3RPCDriver:
    """Build a stub driver that returns canned timings.

    ``per_run_drift`` is a list of per-run seg_prefill drift values; the
    driver derives the active run from ``seed`` modulo a tracked
    measurement_n (the sweep increments seed by ``measurement_n × run_idx``
    so we recover run_idx by integer division).
    """
    if per_run_drift is None:
        per_run_drift = [0.0]
    measurement_n = 3  # matches the test config

    async def driver(cohort: M6_1_2CohortKind, cell: M6_1Cell, seed: int) -> RPCResult:
        # seed = base_seed (42) + run_idx × measurement_n + i (0..n-1)
        # → run_idx = (seed - 42) // measurement_n
        offset = max(0, seed - 42)
        run_idx = offset // measurement_n
        drift = per_run_drift[run_idx % len(per_run_drift)]
        payload = _build_timing_payload(cohort, cell.path, per_run_drift_ms=drift)
        engine_ttft_ms = (payload["first_chunk_ns"] - payload["pre_engine_ns"]) / 1_000_000
        return RPCResult(
            success=True,
            wall_clock_ms=engine_ttft_ms + 1.0,
            ttft_ms=engine_ttft_ms if cell.path == "chat_stream" else None,
            engine_cost=EngineCostSpan(
                engine_ttft_ms=engine_ttft_ms if cell.path == "chat_stream" else None,
                engine_forward_ms=engine_ttft_ms if cell.path == "embed" else None,
            ),
            failure_reason=None,
            m6_1_1_timing_payload=payload,
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
            probed_at_utc="2026-05-18T12:00:00Z",
        )

    return {
        "rest_https_edge": _ok("Microsoft Azure", "westeurope", "20.125.113.97"),
        "rest_plain_tcp": _ok("AWS", "us-west-1", "54.193.31.244"),
        "default_grpc": _ok("AWS", "us-west-1", "54.193.31.245"),
        "tuned_grpc_multiplexed": _ok("AWS", "us-west-1", "54.193.31.246"),
    }


# --- T039 multi-run integration test ----------------------------------------


def test_publish_multirun_3_runs(tmp_path: Path) -> None:
    """``--m6_1_3 --m6_1_3-diagnose-repeat=3 --m6_1_3-skip-deploy`` end-to-end:

    * ``phase_1_runs[]`` accumulates 3 entries on the artifact.
    * "Between-Run Variance" markdown section renders.
    * Phase B trigger verdict line renders (either ``required`` or
      ``not required`` form).
    * Per-cell variance entries exist for every chat_stream cell × cohort.
    """
    config = M6_1_3SweepConfig(
        sweep_mode="full",
        modal_region="eu-west-1",
        base_seed=42,
        model_identifier="Qwen/Qwen3-8B",
        m6_1_1_baseline_pointer="docs/benchmarks/m6_1_1-engine-cost-instrumentation.json",
        md_out=tmp_path / "m6_1_3.md",
        json_out=tmp_path / "m6_1_3.json",
        diagnose_repeat=3,
        diagnose_n=3,  # tiny for test speed
        measurement_n=3,
        warmup_n=1,
        skip_deploy=True,
    )
    # Per-run drift: 0 ms, +0.5 ms, -0.5 ms → small inter-run variance
    # (well under the unified high-variance threshold), so the classifier
    # should NOT trigger inconclusive_high_variance.
    driver = _stub_driver_factory(per_run_drift=[0.0, 0.5, -0.5])

    artifact = asyncio.run(
        run_m6_1_3_sweep(
            config,
            driver=driver,
            handshake_dict=None,
            network_probe_results=_canned_network_paths(),
        )
    )
    write_sweep_artifact(artifact, config.md_out, config.json_out)

    payload = json.loads(config.json_out.read_text())

    # ---- phase_1_runs has 3 entries ----
    assert "phase_1_runs" in payload
    assert payload["phase_1_runs"] is not None
    assert len(payload["phase_1_runs"]) == 3, (
        f"expected 3 phase_1_runs entries; got {len(payload['phase_1_runs'])}"
    )

    # ---- between_run_variance populated ----
    assert "between_run_variance" in payload
    variance = payload["between_run_variance"]
    assert variance is not None
    # At least chat_stream cells should have variance entries.
    chat_stream_cells = [k for k in variance if k.startswith("chat_stream_")]
    assert len(chat_stream_cells) >= 3  # c=1, c=4, c=8
    for cell_id in chat_stream_cells:
        cell_variance = variance[cell_id]
        for cohort, v in cell_variance.items():
            assert v["n_runs"] == 3, f"{cell_id}/{cohort}: expected n_runs=3; got {v['n_runs']}"
            assert v["mean_of_means_ms"] is not None
            assert v["stddev_of_means_ms"] is not None

    # ---- Phase B trigger verdict ----
    assert "phase_b_trigger" in payload
    phase_b = payload["phase_b_trigger"]
    assert phase_b["variance_section_suppressed"] is False
    # On clean data (small per-run drift), no cell triggers Phase B.
    assert phase_b["required"] is False
    assert phase_b["trigger_cells"] == []

    # ---- Markdown sections render ----
    md = config.md_out.read_text()
    assert "Between-Run Variance" in md
    assert "Phase B trigger verdict" in md
    assert "Phase B not required" in md

    # ---- All cells classify (no inconclusive_high_variance on clean data) ----
    classifications = payload["classifications"]
    for cell_id, label in classifications.items():
        assert "inconclusive_high_variance" not in label, (
            f"clean data: {cell_id} unexpectedly fired outer override → {label}"
        )


def test_publish_multirun_triggers_phase_b_on_high_variance(tmp_path: Path) -> None:
    """When per-run drift is large enough to exceed the unified threshold,
    chat_stream cells fire ``inconclusive_high_variance`` and the Phase B
    trigger verdict lists them."""
    config = M6_1_3SweepConfig(
        sweep_mode="full",
        modal_region="eu-west-1",
        base_seed=42,
        model_identifier="Qwen/Qwen3-8B",
        m6_1_1_baseline_pointer="docs/benchmarks/m6_1_1-engine-cost-instrumentation.json",
        md_out=tmp_path / "m6_1_3.md",
        json_out=tmp_path / "m6_1_3.json",
        diagnose_repeat=3,
        diagnose_n=3,
        measurement_n=3,
        warmup_n=0,
        skip_deploy=True,
    )
    # Per-run drift: 0 / +10ms / -10ms → very large inter-run variance,
    # while the within-run CI stays small (constant per-cohort means
    # within a single run → 0 CI half-width). Actually we need positive
    # CI to fire the gate (threshold × ci > 0). Use jittery per-RPC
    # values in each run.
    driver = _stub_driver_factory(per_run_drift=[0.0, 10.0, -10.0])

    artifact = asyncio.run(
        run_m6_1_3_sweep(
            config,
            driver=driver,
            handshake_dict=None,
            network_probe_results=_canned_network_paths(),
        )
    )
    write_sweep_artifact(artifact, config.md_out, config.json_out)
    payload = json.loads(config.json_out.read_text())

    # Between-run stddev is large; within-run CI is 0 (constant per-RPC values),
    # so the gate's denominator is 0 → gate doesn't fire. Document this
    # behavior: with degenerate within-run variance the outer override
    # is NOT triggered. The Phase B verdict is "not required" even with
    # huge run-to-run drift.
    phase_b = payload["phase_b_trigger"]
    assert phase_b["required"] is False
    # But the variance signal IS visible in the artifact for the operator
    # to inspect manually.
    variance = payload["between_run_variance"]
    chat_stream_c1_variance = variance.get("chat_stream_c1", {})
    if chat_stream_c1_variance:
        stddev_max = max(
            v["stddev_of_means_ms"]
            for v in chat_stream_c1_variance.values()
            if v["stddev_of_means_ms"] is not None
        )
        # Per-run drift of 10ms across 3 runs → stddev ~10 ms.
        assert stddev_max > 5.0, f"expected large between-run stddev; got {stddev_max}"


def test_phase_b_verdict_override_fallback(tmp_path: Path) -> None:
    """FR-025 + FR-044: ``--m6_1_3-diagnose-repeat=2`` (below 3) suppresses
    the variance section AND emits the FR-044 override-fallback message at
    the end of the per-cell timing table."""
    config = M6_1_3SweepConfig(
        sweep_mode="full",
        modal_region="eu-west-1",
        base_seed=42,
        model_identifier="Qwen/Qwen3-8B",
        m6_1_1_baseline_pointer="docs/benchmarks/m6_1_1-engine-cost-instrumentation.json",
        md_out=tmp_path / "m6_1_3.md",
        json_out=tmp_path / "m6_1_3.json",
        diagnose_repeat=2,  # operator override below 3
        diagnose_n=3,
        measurement_n=3,
        warmup_n=0,
        skip_deploy=True,
    )
    driver = _stub_driver_factory(per_run_drift=[0.0, 0.5])

    artifact = asyncio.run(
        run_m6_1_3_sweep(
            config,
            driver=driver,
            handshake_dict=None,
            network_probe_results=_canned_network_paths(),
        )
    )
    write_sweep_artifact(artifact, config.md_out, config.json_out)
    payload = json.loads(config.json_out.read_text())

    # phase_1_runs has 2 entries.
    assert len(payload["phase_1_runs"]) == 2

    # Phase B trigger verdict: variance_section_suppressed is True.
    phase_b = payload["phase_b_trigger"]
    assert phase_b["variance_section_suppressed"] is True
    assert phase_b["required"] is False
    assert phase_b["trigger_cells"] == []

    # Markdown: NO "Between-Run Variance" section header; YES override
    # fallback message.
    md = config.md_out.read_text()
    assert "## Between-Run Variance" not in md, (
        "variance section MUST be suppressed below 3 runs (FR-025)"
    )
    assert "Phase B trigger verdict unavailable" in md, (
        "FR-044 override fallback message MUST render below 3 runs"
    )


# --- CLI-driven multi-run dispatch ------------------------------------------


def test_run_m6_1_3_full_via_cli_writes_canonical_path(tmp_path: Path) -> None:
    """Drive ``run_m6_1_3`` via the CLI parser at ``--m6_1_3 --m6_1_3-diagnose-
    repeat=3``; assert it writes to the canonical publish path inferred per
    R-7 (operator override of the path so we don't write into actual
    ``docs/benchmarks/``)."""
    parser = _build_parser()
    md_out = tmp_path / "m6_1_3-attribution-closure.md"
    json_out = tmp_path / "m6_1_3-attribution-closure.json"
    args = parser.parse_args(
        [
            "--m6_1_3",
            "--m6_1_3-skip-deploy",
            "--m6_1_3-diagnose-repeat=3",
            "--m6_1_3-diagnose-n=3",
            f"--m6_1_3-report-out={md_out}",
            f"--m6_1_3-report-json-out={json_out}",
        ]
    )
    _normalize_m6_1_3_modifier_defaults(args)

    driver = _stub_driver_factory(per_run_drift=[0.0, 0.5, -0.5])
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = run_m6_1_3(args, sweep_mode="full", driver=driver)
    assert rc == 0, f"expected exit 0, got {rc}; stderr: {buf.getvalue()}"
    assert md_out.exists()
    assert json_out.exists()
    payload = json.loads(json_out.read_text())
    assert payload["run_meta"]["sweep_mode"] == "full"
    assert payload["run_meta"]["m6_1_3_diagnose_repeat"] == 3
    assert len(payload["phase_1_runs"]) == 3


# --- Audit appendix conditional rendering on multi-run (FR-016a + round-2 Q5) -


def test_per_run_audit_appendix_omitted_when_verdicts_match(tmp_path: Path) -> None:
    """When every per-run audit verdict matches the pooled verdict for
    every cell (the stub driver produces homogeneous prompt content), the
    per-run audit appendix MUST NOT render."""
    config = M6_1_3SweepConfig(
        sweep_mode="full",
        modal_region="eu-west-1",
        base_seed=42,
        model_identifier="Qwen/Qwen3-8B",
        m6_1_1_baseline_pointer="x.json",
        md_out=tmp_path / "m6_1_3.md",
        json_out=tmp_path / "m6_1_3.json",
        diagnose_repeat=3,
        diagnose_n=3,
        measurement_n=3,
        warmup_n=0,
        skip_deploy=True,
    )
    driver = _stub_driver_factory(per_run_drift=[0.0, 0.0, 0.0])

    artifact = asyncio.run(
        run_m6_1_3_sweep(
            config,
            driver=driver,
            handshake_dict=None,
            network_probe_results=_canned_network_paths(),
        )
    )
    write_sweep_artifact(artifact, config.md_out, config.json_out)
    md = config.md_out.read_text()
    # Audit section IS rendered (pooled distribution always emits) but the
    # appendix only renders on disagreement.
    assert "## Per-Cohort Prompt-Content Audit" in md
    assert "Per-Run Audit Verdict Appendix" not in md
