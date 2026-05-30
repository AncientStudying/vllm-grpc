"""M6.1.3 — end-to-end integration test for ``--m6_1_3-validate`` (T025).

Drives the orchestrator → reporter path with a stub RPC driver + canned
topology-probe results — no Modal compute, no live network. The stub
driver returns per-RPC timing payloads engineered so that:

* All chat_stream cells × cohorts produce non-null ``seg_ingress_ms`` +
  ``seg_egress_ms`` per-cell means in the rendered JSON.
* The canonical 5-segment sum invariant holds (within ±1 ms per SC-002).
* The classifier emits one of the 7 base labels (NOT
  ``inconclusive_high_variance`` — that requires multi-run variance,
  deferred to US3).

The test asserts the resulting JSON artifact at ``json_out`` carries the
expected per-cell columns + classifier verdicts + run_meta values.
"""

from __future__ import annotations

import asyncio
import io
import json
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any

import pytest
from vllm_grpc_bench.__main__ import _build_parser
from vllm_grpc_bench.engine_cost import EngineCostSpan
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
from vllm_grpc_bench.m6_sweep import RPCResult

# --- Stub driver -----------------------------------------------------------

# Per-cohort timing parameters engineered so that:
# * seg_prefill is the dominant segment across cohorts (40-44 ms; spread 4 ms).
# * seg_ingress and seg_egress are small enough that their per-cohort
#   spreads stay below the 40% per-rule gate.
# * engine_ttft = seg_ab + seg_queue + seg_prefill + seg_ingress + seg_egress
#   per cohort, satisfying the SC-002 5-segment sum invariant.
#
# This yields ``engine_compute_variation`` as the classifier verdict for
# chat_stream cells, with non-null seg_ingress / seg_egress / seg_prefill
# columns in every per-(cell, cohort) row.
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

# Wall-clock anchor (time.time_ns-style). Arbitrary fixed epoch so the
# numbers stay readable; the deltas are what matters.
_BASE_WALL_NS: int = 1_747_512_345_000_000_000
# Monotonic-clock anchor (time.monotonic_ns-style).
_BASE_MONO_NS: int = 100_000_000_000


def _build_timing_payload_for_cohort(cohort: M6_1_2CohortKind, path: str) -> dict[str, Any]:
    """Build a timing payload dict that encodes the per-cohort segment
    means defined in :data:`_PER_COHORT_PARAMS`.

    The handler_entry / pre_engine / first_chunk / terminal_emit fields
    are on the perf_counter epoch (handler-internal). pre_engine_wall_ns
    + engine_arrival_ns share the wall-clock epoch (``time.time_ns``).
    first_chunk_mono_ns + engine_first_token_ns share the monotonic
    epoch (``time.monotonic_ns``).

    Embed cells (unary RPC) omit the proxy-edge fields per FR-003
    streaming-only constraint; the audit fields are populated regardless
    per FR-014.
    """
    params = _PER_COHORT_PARAMS[cohort]
    seg_ab_ns = int(params["seg_ab_ms"] * 1_000_000)
    seg_queue_ns = int(params["seg_queue_ms"] * 1_000_000)
    seg_prefill_ns = int(params["seg_prefill_ms"] * 1_000_000)
    seg_ingress_ns = int(params["seg_ingress_ms"] * 1_000_000)
    seg_egress_ns = int(params["seg_egress_ms"] * 1_000_000)

    # perf_counter timeline (anchored at 0; M6.1.1 segments).
    handler_entry_ns = 0
    pre_engine_ns = handler_entry_ns + seg_ab_ns
    # first_chunk_ns - pre_engine_ns ≈ engine_ttft = sum of 5 segments
    # minus seg_ab (since seg_ab is the handler-entry-to-pre-engine span).
    engine_ttft_ns = seg_queue_ns + seg_prefill_ns + seg_ingress_ns + seg_egress_ns
    first_chunk_ns = pre_engine_ns + engine_ttft_ns
    terminal_emit_ns = first_chunk_ns + 1_000_000  # 1 ms post-stream cleanup

    # Wall-clock timeline (proxy-edge ingress span).
    pre_engine_wall_ns = _BASE_WALL_NS
    engine_arrival_ns = pre_engine_wall_ns + seg_ingress_ns

    # Monotonic timeline (engine queue / scheduled / first_token + egress
    # span). engine_arrival_ns lives on wall-clock but engine_queued_ns
    # lives on monotonic; vLLM samples both at the same wall moment so
    # we anchor monotonic right at arrival in our fixture.
    engine_queued_ns = _BASE_MONO_NS
    engine_scheduled_ns = engine_queued_ns + seg_queue_ns
    engine_first_token_ns = engine_scheduled_ns + seg_prefill_ns
    engine_last_token_ns = engine_first_token_ns + 10_000_000  # +10 ms post-TTFT
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
    # FR-003 streaming-only: proxy-edge fields ONLY on chat_stream cells.
    if path == "chat_stream":
        payload["pre_engine_wall_ns"] = pre_engine_wall_ns
        payload["first_chunk_mono_ns"] = first_chunk_mono_ns
    else:
        payload["pre_engine_wall_ns"] = None
        payload["first_chunk_mono_ns"] = None
    return payload


def _stub_driver_factory() -> M6_1_3RPCDriver:
    """Build a stub RPC driver that returns canned timings per cohort."""

    async def driver(cohort: M6_1_2CohortKind, cell: M6_1Cell, seed: int) -> RPCResult:
        del seed
        payload = _build_timing_payload_for_cohort(cohort, cell.path)
        # engine_ttft_ms = first_chunk_ns - pre_engine_ns (perf_counter delta).
        engine_ttft_ms = (payload["first_chunk_ns"] - payload["pre_engine_ns"]) / 1_000_000
        return RPCResult(
            success=True,
            wall_clock_ms=engine_ttft_ms + 1.0,  # arbitrary small bump
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


# --- T025 integration test --------------------------------------------------


def test_validate_sweep_end_to_end(tmp_path: Path) -> None:
    """Run --m6_1_3-validate-style sweep end-to-end via the orchestrator +
    reporter; assert the JSON artifact contains the expected keys +
    per-cell rows + classifier verdicts.

    Per tasks.md T025 acceptance:

    * Validate-sibling JSON contains non-null seg_ingress_ms +
      seg_egress_ms per chat_stream cell × cohort.
    * Canonical 5-segment sum check holds (within ±1 ms per SC-002).
    * Classifier emits one of the 7 base labels (NOT
      inconclusive_high_variance — that's US3).
    """
    config = M6_1_3SweepConfig(
        sweep_mode="validate",
        modal_region="eu-west-1",
        base_seed=42,
        model_identifier="Qwen/Qwen3-8B",
        m6_1_1_baseline_pointer="docs/benchmarks/m6_1_1-engine-cost-instrumentation.json",
        md_out=tmp_path / "m6_1_3.md",
        json_out=tmp_path / "m6_1_3.json",
        diagnose_repeat=1,
        diagnose_n=3,  # tiny sample for test speed
        measurement_n=3,
        warmup_n=1,
        skip_deploy=True,
    )
    driver = _stub_driver_factory()

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

    # ---- Top-level shape ----
    assert payload["schema_version"] == "m6_1_1.v1"  # FR-010 no bump
    assert payload["dispatch_mode"] == "concurrent"
    assert payload["run_meta"]["sweep_mode"] == "validate"
    assert payload["run_meta"]["modal_region"] == "eu-west-1"
    assert payload["run_meta"]["base_seed"] == 42
    assert payload["run_meta"]["model_identifier"] == "Qwen/Qwen3-8B"
    assert payload["run_meta"]["m6_1_3_diagnose_repeat"] == 1
    assert payload["run_meta"]["m6_1_3_diagnose_n"] == 3
    assert payload["run_meta"]["m6_1_3_symmetric_prompts"] is False

    # ---- network_paths + cohort_set ----
    canonical = {
        "rest_https_edge",
        "rest_plain_tcp",
        "default_grpc",
        "tuned_grpc_multiplexed",
    }
    assert set(payload["network_paths"].keys()) == canonical
    assert set(payload["cohort_set"]) == canonical
    assert payload["cohort_set"] == sorted(payload["cohort_set"])

    # ---- Per-cell measurements ----
    # 2 cells at c=1 (3 cohorts each, FR-011 collapse) + 4 cells at c>=2 (4 cohorts):
    # 6 + 16 = 22 measurements.
    measurements = payload["measurements"]
    assert len(measurements) == 22

    # All measurements have positive attempt + success counts.
    for m in measurements:
        assert m["n_attempts"] == 3
        assert m["n_successes"] == 3
        assert m["top_failure_reasons"] == {}

    # ---- chat_stream cells × cohorts: non-null seg_ingress / seg_egress ----
    chat_stream_rows = [m for m in measurements if m["path"] == "chat_stream"]
    assert len(chat_stream_rows) > 0
    for m in chat_stream_rows:
        ps = m["per_segment"]
        assert ps is not None, f"missing per_segment for {m['cell_id']} / {m['cohort']}"
        assert ps["seg_ingress_ms_mean"] is not None, (
            f"seg_ingress_ms missing for {m['cell_id']} / {m['cohort']}"
        )
        assert ps["seg_egress_ms_mean"] is not None, (
            f"seg_egress_ms missing for {m['cell_id']} / {m['cohort']}"
        )
        # Non-zero (the stub drives 2.3 - 2.7 ms ingress, 6.4 - 7.2 ms egress).
        assert ps["seg_ingress_ms_mean"] > 0
        assert ps["seg_egress_ms_mean"] > 0

    # ---- Embed cells × cohorts: proxy-edge fields ARE present in the
    # per_segment block but as null (FR-003 streaming-only) ----
    embed_rows = [m for m in measurements if m["path"] == "embed"]
    assert len(embed_rows) > 0
    for m in embed_rows:
        ps = m["per_segment"]
        assert ps is not None
        # Unary RPCs omit proxy-edge wire keys; aggregator records ``None``.
        assert ps["seg_ingress_ms_mean"] is None, (
            f"embed cell unexpectedly has seg_ingress_ms_mean populated: {ps}"
        )
        assert ps["seg_egress_ms_mean"] is None

    # ---- Canonical 5-segment sum invariant per chat_stream cell × cohort ----
    for m in chat_stream_rows:
        ps = m["per_segment"]
        total = (
            ps["seg_ab_ms_mean"]
            + ps["seg_queue_ms_mean"]
            + ps["seg_prefill_ms_mean"]
            + ps["seg_ingress_ms_mean"]
            + ps["seg_egress_ms_mean"]
        )
        engine_ttft = m["engine_ttft_ms_mean"]
        assert engine_ttft is not None
        # Note: the stub's engine_ttft = seg_queue + seg_prefill + seg_ingress
        # + seg_egress (perf_counter delta from pre_engine to first_chunk),
        # which OMITS seg_ab. So the 5-segment sum equals engine_ttft + seg_ab.
        # The contract's 5-segment sum invariant is checked against the
        # END-TO-END span (which is ttft + seg_ab in this stub geometry),
        # so we test against that:
        end_to_end = engine_ttft + ps["seg_ab_ms_mean"]
        assert abs(total - end_to_end) <= 1.0, (
            f"5-segment sum {total} ms != end-to-end {end_to_end} ms (diff "
            f"{abs(total - end_to_end)} ms) for {m['cell_id']} / {m['cohort']}"
        )

    # ---- Classifier verdicts: one of the 7 base labels ----
    valid_base_labels = {
        "channel_dependent_batching",
        "queue_dependent_batching",
        "engine_compute_variation",
        "frontend_arrival_jitter",  # Dormant in M6.1.3 — should NEVER appear
        "inconclusive",
        "proxy_ingress_dominated",
        "proxy_egress_dominated",
    }
    classifications = payload["classifications"]
    assert len(classifications) >= 1
    for cell_id, label in classifications.items():
        # NOT inconclusive_high_variance — that's US3 territory.
        assert not label.startswith("inconclusive_high_variance"), (
            f"unexpected outer override in US1 single-run sweep: {cell_id} → {label}"
        )
        # Either a base label or a compound. Compound has "multi_factor_" prefix.
        if label.startswith("multi_factor_"):
            # Compound — at least one of the labels in the suffix should be
            # an active abbreviated identifier (not frontend_arrival per
            # round-4 Q1 dormancy).
            assert "frontend_arrival" not in label, (
                f"frontend_arrival appeared in compound: {label}"
            )
        else:
            assert label in valid_base_labels, (
                f"unexpected classifier label {label} for cell {cell_id}"
            )
        # In every case: frontend_arrival_jitter must NOT be the primary.
        assert label != "frontend_arrival_jitter", (
            f"frontend_arrival_jitter fired as primary (dormancy violation): {cell_id}"
        )

    # ---- Markdown sidecar carries the M6.1.3 sections ----
    md = config.md_out.read_text()
    assert "M6.1.3 — Phase 1 Attribution Closure" in md
    assert "Per-cell timing table" in md
    assert "Classifier verdicts" in md
    assert "Identifier legend" in md  # FR-009a + round-2 Q2
    assert "seg_ingress_ms" in md
    assert "seg_egress_ms" in md
    # Reciprocal cross-reference per FR-041.
    assert "m6_1_1-engine-cost-instrumentation.md" in md


# --- Output-path inference + dispatch wiring via the CLI -------------------


def test_run_m6_1_3_validate_via_cli_writes_validate_sibling_path(
    tmp_path: Path,
) -> None:
    """Drive ``run_m6_1_3`` via the CLI parser + injected driver; assert
    it writes to the validate-sibling path inferred per R-7.

    Forces ``--m6_1_3-report-out`` / ``-report-json-out`` to absolute paths
    inside ``tmp_path`` so the test doesn't write into the actual
    ``docs/benchmarks/`` directory.
    """
    parser = _build_parser()
    md_out = tmp_path / "m6_1_3-attribution-closure-validate.md"
    json_out = tmp_path / "m6_1_3-attribution-closure-validate.json"
    args = parser.parse_args(
        [
            "--m6_1_3-validate",
            "--m6_1_3-skip-deploy",
            f"--m6_1_3-report-out={md_out}",
            f"--m6_1_3-report-json-out={json_out}",
        ]
    )
    # Apply the mode-dependent default for diagnose_repeat.
    from vllm_grpc_bench.__main__ import _normalize_m6_1_3_modifier_defaults

    _normalize_m6_1_3_modifier_defaults(args)

    driver = _stub_driver_factory()
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = run_m6_1_3(args, sweep_mode="validate", driver=driver)
    assert rc == 0, f"expected exit 0, got {rc}; stderr was: {buf.getvalue()}"

    # Artifact landed at the inferred validate-sibling path.
    assert md_out.exists()
    assert json_out.exists()
    payload = json.loads(json_out.read_text())
    assert payload["run_meta"]["sweep_mode"] == "validate"


def test_run_m6_1_3_skip_deploy_without_driver_returns_5(tmp_path: Path) -> None:
    """When --m6_1_3-skip-deploy is set but no driver is injected, the
    entry function returns exit 5 per contracts/cli.md."""
    from vllm_grpc_bench.__main__ import _normalize_m6_1_3_modifier_defaults

    parser = _build_parser()
    args = parser.parse_args(
        [
            "--m6_1_3-validate",
            "--m6_1_3-skip-deploy",
            f"--m6_1_3-report-out={tmp_path / 'out.md'}",
            f"--m6_1_3-report-json-out={tmp_path / 'out.json'}",
        ]
    )
    _normalize_m6_1_3_modifier_defaults(args)
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = run_m6_1_3(args, sweep_mode="validate", driver=None)
    assert rc == 5
    assert "no driver was injected" in buf.getvalue()


# --- Mode-dispatch parity (validate vs full) -------------------------------


@pytest.mark.parametrize(
    "mode_flag,sweep_mode_literal",
    [
        ("--m6_1_3", "full"),
        ("--m6_1_3-validate", "validate"),
    ],
)
def test_sweep_mode_recorded_in_run_meta(
    tmp_path: Path, mode_flag: str, sweep_mode_literal: str
) -> None:
    """``run_meta.sweep_mode`` records the operator intent per round-2 Q2
    + ``contracts/cli.md`` Dispatch wiring. Both --m6_1_3 and
    --m6_1_3-validate route through the same entry function; only the
    sweep_mode metadata distinguishes them."""
    parser = _build_parser()
    md_out = tmp_path / f"{sweep_mode_literal}.md"
    json_out = tmp_path / f"{sweep_mode_literal}.json"
    args = parser.parse_args(
        [
            mode_flag,
            "--m6_1_3-skip-deploy",
            "--m6_1_3-diagnose-n=3",
            f"--m6_1_3-report-out={md_out}",
            f"--m6_1_3-report-json-out={json_out}",
        ]
    )
    from vllm_grpc_bench.__main__ import _normalize_m6_1_3_modifier_defaults

    _normalize_m6_1_3_modifier_defaults(args)

    driver = _stub_driver_factory()
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = run_m6_1_3(args, sweep_mode=sweep_mode_literal, driver=driver)  # type: ignore[arg-type]
    assert rc == 0, f"expected exit 0, got {rc}; stderr was: {buf.getvalue()}"

    payload = json.loads(json_out.read_text())
    assert payload["run_meta"]["sweep_mode"] == sweep_mode_literal
