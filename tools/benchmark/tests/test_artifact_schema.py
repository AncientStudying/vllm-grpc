"""T031 — M6.2 artifact schema unit tests.

Exercises :mod:`reporter` directly: renders ``M6_2SweepArtifact``
fixtures and asserts:

- 144-row latency budget table completeness in publish + validate modes
  (publish: 144 measurements/failures; validate: 72 measured + 72
  ``not_validated`` placeholders) per SC-003.
- Strict-superset compat with M6.1.3-vintage readers (FR-011 / SC-007):
  ``schema_version == "m6_1_1.v1"``; all M6.2-additive keys are added at the
  top level without colliding with M6.1.3 keys.
- Validate-mode ``not_validated`` rendering for interior caps.
- Per-row ``prompt_source`` + ``measurement_regime`` + ``prompt_corpus_idx``
  field discipline (round-5 FR-034 / FR-035).
- ``run_meta`` schema (every additive field present).
- ``failure_summary`` always present (SC-014).
- ``integrity_warnings`` ⊆ canonical channel labels.
- SC-011 clock-anomaly gate at the 0.5% threshold.
"""

from __future__ import annotations

import json
from typing import Any

from vllm_grpc_bench.reporter import (
    EARLY_EOS_AUDIT_MIN_MAX_TOKENS,
    EARLY_EOS_RATIO_THRESHOLD,
    INTEGRITY_CHANNELS,
    NOT_VALIDATED_MARKER,
    SC011_CLOCK_ANOMALY_FRACTION_THRESHOLD,
    build_integrity_warnings,
    compute_clock_anomaly_fraction,
    compute_implied_output_tokens,
    fill_validate_mode_placeholders,
    render_json,
    render_markdown,
    write_m6_2_report,
)
from vllm_grpc_bench.sweep_types import (
    M6_2_MAX_TOKENS_AXIS,
    M6_2_VALIDATE_MAX_TOKENS_AXIS,
    M6_2AnchorLatencySnapshot,
    M6_2AnchorLatencyTrajectory,
    M6_2MeasurementPoint,
    M6_2NullAnchor,
    M6_2RunMeta,
    M6_2SweepArtifact,
    M6_2SweepMode,
)
from vllm_grpc_bench.types import CELLS as M6_1_CELLS
from vllm_grpc_bench.types import COHORTS as M6_1_2_COHORTS
from vllm_grpc_bench.types import M6_1_2NetworkPath


def _measurement(
    *,
    cell_id: str,
    cohort: str,
    max_tokens: int,
    wall_p50_ms: float | None = 50.0,
    failed_reason: str | None = None,
    prompt_source: str = "synthetic_seed_derived",
    prompt_corpus_idx: int | None = None,
    clock_anomaly: bool = False,
    n_rpcs: int = 20,
    tpot_ms: float | None = None,
    seg_prefill_ms: float | None = None,
    seg_egress_ms: float | None = None,
    measurement_regime: str = "natural_eos",
) -> M6_2MeasurementPoint:
    return M6_2MeasurementPoint(
        cell_id=cell_id,
        cohort=cohort,  # type: ignore[arg-type]
        max_tokens=max_tokens,
        n_rpcs=n_rpcs,
        wall_p50_ms=None if failed_reason else wall_p50_ms,
        wall_p95_ms=None if failed_reason else (wall_p50_ms or 0.0) * 1.5,
        wall_p99_ms=None if failed_reason else (wall_p50_ms or 0.0) * 2.0,
        wall_p50_ms_ci_half_width=None if failed_reason else 1.0,
        tpot_ms=tpot_ms,
        seg_ab_ms=None,
        seg_queue_ms=None,
        seg_prefill_ms=seg_prefill_ms,
        seg_ingress_ms=None,
        seg_egress_ms=seg_egress_ms,
        failed_reason=failed_reason,
        block_start_utc="2026-05-20T00:00:00Z",
        block_end_utc="2026-05-20T00:00:05Z",
        retry_attempted=False,
        clock_anomaly=clock_anomaly,
        prompt_source=prompt_source,  # type: ignore[arg-type]
        measurement_regime=measurement_regime,  # type: ignore[arg-type]
        prompt_corpus_idx=prompt_corpus_idx,
    )


def _run_meta(
    *,
    sweep_mode: M6_2SweepMode,
    iteration_discipline_verified: bool = True,
    n_per_point: int = 20,
    total_sweep_hours: float = 2.4,
    sub_probe_ran: bool = False,
) -> M6_2RunMeta:
    return M6_2RunMeta(
        git_sha="abc1234",
        modal_region="eu-west-1",
        base_seed=42,
        model_identifier="Qwen/Qwen3-8B",
        dispatch_mode="concurrent",
        symmetric_prompts_enabled=True,
        schema_version="m6_1_1.v1",
        sweep_mode=sweep_mode,
        m6_1_3_baseline_artifact_path="docs/benchmarks/m6_1_3-attribution-closure.json",
        iteration_order="cohort_innermost_block",
        iteration_discipline_verified=iteration_discipline_verified,
        n_per_point=n_per_point,
        validate_axis_subset=(
            list(M6_2_VALIDATE_MAX_TOKENS_AXIS) if sweep_mode == "validate" else None
        ),
        wall_clock_start_utc="2026-05-20T00:00:00Z",
        wall_clock_end_utc="2026-05-20T02:24:00Z",
        total_sweep_hours=total_sweep_hours,
        modal_spend_usd_estimate=4.0,
        chat_corpus_sha256="0" * 64,
        chat_corpus_path="tools/benchmark/corpus/chat_sharegpt_1000.json",
        embed_corpus_sha256="1" * 64,
        embed_corpus_path="tools/benchmark/corpus/completions_embeds_qwen3_8b/",
        sub_probe_ran=sub_probe_ran,
    )


def _build_artifact(
    *,
    sweep_mode: M6_2SweepMode,
    measured_axis: tuple[int, ...],
    failures: dict[tuple[str, str, int], str] | None = None,
    network_paths: dict[str, list[Any]] | None = None,
    anchor_trajectories: dict[str, M6_2AnchorLatencyTrajectory] | None = None,
    null_anchor_validation: list[M6_2NullAnchor] | None = None,
    iteration_discipline_verified: bool = True,
    clock_anomaly_rows: set[tuple[str, str, int]] | None = None,
) -> M6_2SweepArtifact:
    failures = failures or {}
    clock_anomaly_rows = clock_anomaly_rows or set()
    per_cell: dict[str, dict[str, dict[int, M6_2MeasurementPoint]]] = {}
    for path, _hidden, concurrency in M6_1_CELLS:
        cell_id = f"{path}_c{concurrency}"
        per_cell[cell_id] = {}
        for cohort in M6_1_2_COHORTS:
            per_cell[cell_id][cohort] = {}
            for max_tokens in measured_axis:
                key = (cell_id, cohort, max_tokens)
                per_cell[cell_id][cohort][max_tokens] = _measurement(
                    cell_id=cell_id,
                    cohort=cohort,
                    max_tokens=max_tokens,
                    failed_reason=failures.get(key),
                    clock_anomaly=key in clock_anomaly_rows,
                )
    per_cell_filled = fill_validate_mode_placeholders(
        per_cell,  # type: ignore[arg-type]
        sweep_mode=sweep_mode,
        block_start_utc="2026-05-20T02:24:00Z",
        block_end_utc="2026-05-20T02:24:00Z",
    )
    artifact = M6_2SweepArtifact(
        schema_version="m6_1_1.v1",
        dispatch_mode="concurrent",
        run_id="2026-05-20T00:00:00Z-deadbeef",
        run_started_at="2026-05-20T00:00:00Z",
        run_completed_at="2026-05-20T02:24:00Z",
        run_meta=_run_meta(
            sweep_mode=sweep_mode,
            iteration_discipline_verified=iteration_discipline_verified,
        ),
        per_cell=per_cell_filled,  # type: ignore[arg-type]
        network_paths=network_paths or {cohort: [] for cohort in M6_1_2_COHORTS},  # type: ignore[arg-type]
        cohort_set=list(M6_1_2_COHORTS),
        cohort_omissions=None,
        null_anchor_validation=null_anchor_validation or [],
        max_tokens_axis=list(
            M6_2_VALIDATE_MAX_TOKENS_AXIS if sweep_mode == "validate" else M6_2_MAX_TOKENS_AXIS
        ),
        protocol_crossover=[],
        kv_pressure_observation=[],
        anchor_latency_trajectory=anchor_trajectories or {},  # type: ignore[arg-type]
        failure_summary={},
        integrity_warnings=[],
    )
    artifact.integrity_warnings = build_integrity_warnings(artifact)
    return artifact


# --- 144-row completeness (SC-003) -----------------------------------------


def test_publish_artifact_has_144_rows() -> None:
    """The data-model.md states 6 cells × 4 cohorts × 6 caps = 144, but this
    fixture synthesizes 4 cohorts at every cell (ignoring the c=1 cohort
    collapse — the in-process orchestrator-driven path naturally honors the
    cohort-set discipline). Here we synthesize the full 144-row publish shape
    to exercise the SC-003 reporter path; the live-cohort discipline (132 rows
    with c=1 collapsed) is exercised by ``test_m6_2_validate_cli.py``."""
    artifact = _build_artifact(sweep_mode="publish", measured_axis=M6_2_MAX_TOKENS_AXIS)
    rows = [
        point
        for per_cohort in artifact.per_cell.values()
        for per_cap in per_cohort.values()
        for point in per_cap.values()
    ]
    assert len(rows) == 144, "publish synthetic fixture: 6 cells × 4 cohorts × 6 caps = 144"


def test_validate_artifact_has_72_measured_plus_72_placeholders() -> None:
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    rows = [
        point
        for per_cohort in artifact.per_cell.values()
        for per_cap in per_cohort.values()
        for point in per_cap.values()
    ]
    assert len(rows) == 144, "validate must render 72 measured + 72 placeholders = 144"
    measured = [r for r in rows if r.failed_reason != NOT_VALIDATED_MARKER]
    placeholders = [r for r in rows if r.failed_reason == NOT_VALIDATED_MARKER]
    assert len(measured) == 72, "exactly 72 measured rows in validate mode"
    assert len(placeholders) == 72, "exactly 72 not_validated placeholders in validate mode"
    for r in placeholders:
        assert r.max_tokens in (256, 512, 1024)
        assert r.wall_p50_ms is None
        assert r.measurement_regime == "natural_eos"


# --- Strict-superset compat (FR-011 / SC-007) ------------------------------


def test_schema_version_unchanged() -> None:
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    payload = render_json(artifact)
    assert payload["schema_version"] == "m6_1_1.v1"


def test_strict_superset_compat_with_m6_1_3() -> None:
    """M6.1.3-vintage readers can JSON-decode the M6.2 artifact without error
    (unknown keys are ignored cleanly)."""
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    payload = render_json(artifact)
    serialized = json.dumps(payload)
    reloaded = json.loads(serialized)
    # M6.1.3-vintage readers expect these keys:
    for key in (
        "schema_version",
        "dispatch_mode",
        "run_id",
        "run_started_at",
        "run_completed_at",
        "run_meta",
        "network_paths",
        "cohort_set",
    ):
        assert key in reloaded, f"M6.1.3-vintage key {key!r} present"
    # M6.2 additive top-level keys:
    for key in (
        "per_cell",
        "null_anchor_validation",
        "max_tokens_axis",
        "protocol_crossover",
        "kv_pressure_observation",
        "anchor_latency_trajectory",
        "failure_summary",
        "integrity_warnings",
    ):
        assert key in reloaded, f"M6.2 additive key {key!r} present"


# --- Per-row field discipline (round-5 FR-034 / FR-035) --------------------


def test_per_row_prompt_source_present_on_every_row() -> None:
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    payload = render_json(artifact)
    for cell_id, per_cohort in payload["per_cell"].items():
        for cohort, per_cap in per_cohort.items():
            for max_tokens, row in per_cap.items():
                assert "prompt_source" in row, f"prompt_source on {cell_id}/{cohort}/{max_tokens}"
                assert "measurement_regime" in row
                assert "prompt_corpus_idx" in row


def test_prompt_corpus_idx_is_none_iff_synthetic_regime() -> None:
    artifact = _build_artifact(sweep_mode="publish", measured_axis=M6_2_MAX_TOKENS_AXIS)
    for per_cohort in artifact.per_cell.values():
        for per_cap in per_cohort.values():
            for point in per_cap.values():
                if point.prompt_source in ("synthetic_seed_derived", "synthetic_random_tensor"):
                    assert point.prompt_corpus_idx is None
                # Note: corpus-regime rows (corpus_sharegpt*) should have
                # prompt_corpus_idx populated when produced by the
                # orchestrator; in this synthetic fixture we don't exercise
                # the corpus regime side, which is covered separately by
                # test_prompts.


# --- run_meta schema --------------------------------------------------------


def test_run_meta_has_all_additive_fields() -> None:
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    payload = render_json(artifact)
    rm = payload["run_meta"]
    for field in (
        "iteration_order",
        "iteration_discipline_verified",
        "n_per_point",
        "validate_axis_subset",
        "wall_clock_start_utc",
        "wall_clock_end_utc",
        "total_sweep_hours",
        "modal_spend_usd_estimate",
        "chat_corpus_sha256",
        "chat_corpus_path",
        "embed_corpus_sha256",
        "embed_corpus_path",
        "sub_probe_ran",
        "preemption_events",
    ):
        assert field in rm, f"run_meta missing additive field {field!r}"
    assert rm["iteration_order"] == "cohort_innermost_block"
    assert rm["validate_axis_subset"] == list(M6_2_VALIDATE_MAX_TOKENS_AXIS)


def test_run_meta_preemption_events_defaults_to_zero() -> None:
    """T074f: happy-path sweeps (no Modal preemption) record
    ``preemption_events=0``. Non-zero values indicate the sweep survived
    one or more Modal worker restarts via T074's recovery loop."""
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    payload = render_json(artifact)
    assert payload["run_meta"]["preemption_events"] == 0


def test_run_meta_preemption_events_renders_in_markdown() -> None:
    """The reporter surfaces the field in the run_meta block so operators
    can see at a glance whether the sweep encountered preemption."""
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    md = render_markdown(artifact, sweep_mode="validate")
    assert "- preemption_events: `0`" in md


# --- failure_summary always present (SC-014) -------------------------------


def test_failure_summary_present_even_when_empty() -> None:
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    payload = render_json(artifact)
    assert "failure_summary" in payload
    assert payload["failure_summary"] == {}


# --- integrity_warnings channel discipline ---------------------------------


def test_integrity_warnings_canonical_only() -> None:
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    payload = render_json(artifact)
    for channel in payload["integrity_warnings"]:
        assert channel in INTEGRITY_CHANNELS, f"unknown channel {channel!r}"


def test_iteration_discipline_broken_fires_soft_diagnostic() -> None:
    artifact = _build_artifact(
        sweep_mode="validate",
        measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS,
        iteration_discipline_verified=False,
    )
    assert "iteration_discipline_broken" in artifact.integrity_warnings


def test_failure_summary_threshold_fires_at_three_failures() -> None:
    """FR-029 / SC-014: ≥ 3 failed cells fires the sweep-level header."""
    failures = {
        ("chat_stream_c1", "default_grpc", 50): "grpc_timeout",
        ("chat_stream_c1", "rest_https_edge", 50): "grpc_timeout",
        ("chat_stream_c1", "rest_plain_tcp", 50): "grpc_timeout",
    }
    artifact = _build_artifact(
        sweep_mode="validate",
        measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS,
        failures=failures,
    )
    assert "failure_summary_threshold" in artifact.integrity_warnings


def test_failure_summary_threshold_does_not_fire_at_two_failures() -> None:
    failures = {
        ("chat_stream_c1", "default_grpc", 50): "grpc_timeout",
        ("chat_stream_c1", "rest_https_edge", 50): "grpc_timeout",
    }
    artifact = _build_artifact(
        sweep_mode="validate",
        measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS,
        failures=failures,
    )
    assert "failure_summary_threshold" not in artifact.integrity_warnings


def test_cohort_csp_mismatch_fires_on_consecutive_provider_change() -> None:
    network_paths: dict[str, list[Any]] = {cohort: [] for cohort in M6_1_2_COHORTS}
    network_paths["default_grpc"] = [
        M6_1_2NetworkPath(
            endpoint_ip="10.0.0.1",
            hops=[],
            cloud_provider="AWS",
            region="eu-west-1",
            probe_method="tcptraceroute",
            probed_at_utc="2026-05-20T00:00:00Z",
        ),
        M6_1_2NetworkPath(
            endpoint_ip="10.0.0.2",
            hops=[],
            cloud_provider="GCP",
            region="europe-west1",
            probe_method="tcptraceroute",
            probed_at_utc="2026-05-20T01:00:00Z",
        ),
    ]
    artifact = _build_artifact(
        sweep_mode="validate",
        measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS,
        network_paths=network_paths,
    )
    assert "cohort_csp_mismatch" in artifact.integrity_warnings


def test_intra_sweep_latency_drift_fires_at_two_of_four_cohorts() -> None:
    snapshots_drifted = [
        M6_2AnchorLatencySnapshot(
            wall_p50_ms=50.0,
            wall_p95_ms=55.0,
            wall_p99_ms=60.0,
            snapshot_timestamp="2026-05-20T00:00:00Z",
            sweep_hour_mark=0.0,
        ),
        M6_2AnchorLatencySnapshot(
            wall_p50_ms=100.0,  # spread = 50 > 5.0 threshold
            wall_p95_ms=110.0,
            wall_p99_ms=120.0,
            snapshot_timestamp="2026-05-20T02:00:00Z",
            sweep_hour_mark=2.0,
        ),
    ]
    snapshots_stable = [
        M6_2AnchorLatencySnapshot(
            wall_p50_ms=50.0,
            wall_p95_ms=55.0,
            wall_p99_ms=60.0,
            snapshot_timestamp="2026-05-20T00:00:00Z",
            sweep_hour_mark=0.0,
        ),
        M6_2AnchorLatencySnapshot(
            wall_p50_ms=50.5,  # spread = 0.5 < 5.0
            wall_p95_ms=55.0,
            wall_p99_ms=60.0,
            snapshot_timestamp="2026-05-20T02:00:00Z",
            sweep_hour_mark=2.0,
        ),
    ]
    trajectories: dict[str, M6_2AnchorLatencyTrajectory] = {
        "default_grpc": M6_2AnchorLatencyTrajectory(
            cohort="default_grpc",  # type: ignore[arg-type]
            snapshots=snapshots_drifted,
            max_minus_min_wall_p50_ms=50.0,
            latency_drift_warning=True,
        ),
        "rest_https_edge": M6_2AnchorLatencyTrajectory(
            cohort="rest_https_edge",  # type: ignore[arg-type]
            snapshots=snapshots_drifted,
            max_minus_min_wall_p50_ms=50.0,
            latency_drift_warning=True,
        ),
        "rest_plain_tcp": M6_2AnchorLatencyTrajectory(
            cohort="rest_plain_tcp",  # type: ignore[arg-type]
            snapshots=snapshots_stable,
            max_minus_min_wall_p50_ms=0.5,
            latency_drift_warning=False,
        ),
        "tuned_grpc_multiplexed": M6_2AnchorLatencyTrajectory(
            cohort="tuned_grpc_multiplexed",  # type: ignore[arg-type]
            snapshots=snapshots_stable,
            max_minus_min_wall_p50_ms=0.5,
            latency_drift_warning=False,
        ),
    }
    artifact = _build_artifact(
        sweep_mode="validate",
        measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS,
        anchor_trajectories=trajectories,
    )
    assert "intra_sweep_latency_drift" in artifact.integrity_warnings


# --- Null anchor drift header ----------------------------------------------


def test_null_anchor_drift_fires_at_two_cross_checkable_warns() -> None:
    null_anchors = [
        M6_2NullAnchor(
            cell_id="chat_stream_c1",
            cohort="default_grpc",  # type: ignore[arg-type]
            max_tokens=50,
            m6_2_wall_p50_ms=100.0,
            m6_1_3_wall_p50_ms=50.0,
            m6_1_3_ci_half_width=1.0,
            drift_verdict="FAIL",
            drift_fraction=50.0,
            new_baseline_marker=False,
        ),
        M6_2NullAnchor(
            cell_id="embed_c1",
            cohort="default_grpc",  # type: ignore[arg-type]
            max_tokens=10,
            m6_2_wall_p50_ms=80.0,
            m6_1_3_wall_p50_ms=50.0,
            m6_1_3_ci_half_width=1.0,
            drift_verdict="WARN",
            drift_fraction=30.0,
            new_baseline_marker=False,
        ),
    ]
    artifact = _build_artifact(
        sweep_mode="validate",
        measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS,
        null_anchor_validation=null_anchors,
    )
    assert "null_anchor_drift" in artifact.integrity_warnings


def test_null_anchor_drift_excludes_new_baseline_from_count() -> None:
    null_anchors = [
        M6_2NullAnchor(
            cell_id="chat_stream_c1",
            cohort="default_grpc",  # type: ignore[arg-type]
            max_tokens=50,
            m6_2_wall_p50_ms=100.0,
            m6_1_3_wall_p50_ms=50.0,
            m6_1_3_ci_half_width=1.0,
            drift_verdict="FAIL",
            drift_fraction=50.0,
            new_baseline_marker=False,
        ),
        # New-baseline cells excluded — verdict=None doesn't count.
        M6_2NullAnchor(
            cell_id="embed_c1",
            cohort="default_grpc",  # type: ignore[arg-type]
            max_tokens=10,
            m6_2_wall_p50_ms=80.0,
            m6_1_3_wall_p50_ms=None,
            m6_1_3_ci_half_width=None,
            drift_verdict=None,
            drift_fraction=None,
            new_baseline_marker=True,
        ),
        M6_2NullAnchor(
            cell_id="embed_c4",
            cohort="default_grpc",  # type: ignore[arg-type]
            max_tokens=10,
            m6_2_wall_p50_ms=80.0,
            m6_1_3_wall_p50_ms=None,
            m6_1_3_ci_half_width=None,
            drift_verdict=None,
            drift_fraction=None,
            new_baseline_marker=True,
        ),
    ]
    artifact = _build_artifact(
        sweep_mode="validate",
        measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS,
        null_anchor_validation=null_anchors,
    )
    # Only 1 cross-checkable drifted (< 2 threshold) → header does NOT fire.
    assert "null_anchor_drift" not in artifact.integrity_warnings


# --- SC-011 clock-anomaly gate ---------------------------------------------


def test_clock_anomaly_fraction_below_threshold_does_not_fire() -> None:
    artifact = _build_artifact(sweep_mode="publish", measured_axis=M6_2_MAX_TOKENS_AXIS)
    rows = [
        p
        for per_c in artifact.per_cell.values()
        for per_t in per_c.values()
        for p in per_t.values()
    ]
    # No anomalies → fraction = 0.0
    assert compute_clock_anomaly_fraction(rows) == 0.0
    assert "clock_anomaly_warning" not in artifact.integrity_warnings


def test_clock_anomaly_fraction_at_threshold_fires() -> None:
    # 144 publish rows total; need ≥ 0.005 fraction → ≥ 1 anomaly suffices.
    # Use a high-density anomaly set to push fraction well above 0.5%.
    anomalies = {
        ("chat_stream_c1", "default_grpc", 10),
        ("chat_stream_c1", "default_grpc", 50),
        ("chat_stream_c1", "default_grpc", 256),
        ("chat_stream_c1", "default_grpc", 512),
        ("chat_stream_c1", "default_grpc", 1024),
        ("chat_stream_c1", "default_grpc", 2048),
    }
    artifact = _build_artifact(
        sweep_mode="publish",
        measured_axis=M6_2_MAX_TOKENS_AXIS,
        clock_anomaly_rows=anomalies,
    )
    rows = [
        p
        for per_c in artifact.per_cell.values()
        for per_t in per_c.values()
        for p in per_t.values()
    ]
    fraction = compute_clock_anomaly_fraction(rows)
    assert fraction >= SC011_CLOCK_ANOMALY_FRACTION_THRESHOLD
    assert "clock_anomaly_warning" in artifact.integrity_warnings


def test_clock_anomaly_fraction_excludes_not_validated_placeholders() -> None:
    """SC-011 fraction is computed over rows with n_rpcs > 0; validate-mode
    placeholders (n_rpcs=0) MUST be excluded from numerator and denominator."""
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    rows = [
        p
        for per_c in artifact.per_cell.values()
        for per_t in per_c.values()
        for p in per_t.values()
    ]
    # 72 placeholders have n_rpcs=0; they must not affect the fraction.
    fraction = compute_clock_anomaly_fraction(rows)
    assert fraction == 0.0


# --- Markdown rendering smoke ----------------------------------------------


def test_render_markdown_publish_has_all_primary_sections() -> None:
    artifact = _build_artifact(sweep_mode="publish", measured_axis=M6_2_MAX_TOKENS_AXIS)
    md = render_markdown(artifact, sweep_mode="publish")
    for header in (
        "## Production latency budget",
        "## TPOT curves",
        "## Engine-cost decomposition curves",
        "## Protocol crossover threshold",
        "## KV-cache pressure",
        "## Null anchor validation",
        "## Anchor latency trajectory",
        "## Failure summary",
        "## Sweep wall-clock timeline",
        "## Method / Background",
    ):
        assert header in md, f"missing markdown section {header!r}"


def test_render_markdown_validate_omits_timeline_if_short() -> None:
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    md = render_markdown(artifact, sweep_mode="validate")
    assert "## Sweep wall-clock timeline" not in md


def test_render_markdown_validate_carries_crossover_disclaimer() -> None:
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    md = render_markdown(artifact, sweep_mode="validate")
    assert "Validate-mode crossover analysis is restricted" in md
    assert "{10, 50, 2048}" in md


# --- write_m6_2_report integration -----------------------------------------


def test_write_m6_2_report_emits_md_and_json(tmp_path: Any) -> None:
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    md_path = tmp_path / "m6_2-token-budget-validate.md"
    json_path = tmp_path / "m6_2-token-budget-validate.json"
    write_m6_2_report(artifact, md_path, json_path, sweep_mode="validate")
    assert md_path.exists()
    assert json_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload["schema_version"] == "m6_1_1.v1"
    assert payload["run_meta"]["sweep_mode"] == "validate"
    assert payload["run_meta"]["iteration_order"] == "cohort_innermost_block"


# --- Prompt-driven early-EOS audit (Section 1b) ----------------------------


def test_compute_implied_output_tokens_back_of_envelope() -> None:
    """``(wall - prefill - egress) / tpot`` with the c8/default_grpc[2048]
    field values reproduces the ~273-token figure logged in the operator
    note on the 2026-05-24 validate sweep."""
    point = _measurement(
        cell_id="chat_stream_c8",
        cohort="default_grpc",
        max_tokens=2048,
        wall_p50_ms=10341.64,
        tpot_ms=37.54,
        seg_prefill_ms=77.26,
        seg_egress_ms=1.99,
    )
    implied = compute_implied_output_tokens(point)
    assert implied is not None
    assert 270.0 < implied < 280.0


def test_compute_implied_output_tokens_returns_none_when_tpot_missing() -> None:
    point = _measurement(
        cell_id="chat_stream_c1",
        cohort="default_grpc",
        max_tokens=2048,
        wall_p50_ms=10000.0,
        tpot_ms=None,
    )
    assert compute_implied_output_tokens(point) is None


def test_compute_implied_output_tokens_returns_none_on_zero_tpot() -> None:
    point = _measurement(
        cell_id="chat_stream_c1",
        cohort="default_grpc",
        max_tokens=2048,
        wall_p50_ms=10000.0,
        tpot_ms=0.0,
    )
    assert compute_implied_output_tokens(point) is None


def test_early_eos_audit_silent_when_no_cells_flagged() -> None:
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    md = render_markdown(artifact, sweep_mode="validate")
    assert "## Prompt-driven early-EOS audit" not in md


def test_early_eos_audit_fires_on_short_response_at_2048() -> None:
    """A chat_stream cell whose ``implied_output_tokens / max_tokens`` falls
    below ``EARLY_EOS_RATIO_THRESHOLD`` at ``max_tokens >= 256`` is
    surfaced in the audit section with its cell_id, cohort, and corpus_idx
    so the reader can correlate to the offending prompt."""
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    # Inject the c8/default_grpc[2048] shape from the 2026-05-24 sweep.
    artifact.per_cell["chat_stream_c8"]["default_grpc"][2048] = _measurement(
        cell_id="chat_stream_c8",
        cohort="default_grpc",
        max_tokens=2048,
        wall_p50_ms=10341.64,
        tpot_ms=37.54,
        seg_prefill_ms=77.26,
        seg_egress_ms=1.99,
        prompt_source="corpus_sharegpt",
        prompt_corpus_idx=62,
    )
    md = render_markdown(artifact, sweep_mode="validate")
    assert "## Prompt-driven early-EOS audit" in md
    assert "`chat_stream_c8`" in md.split("## Prompt-driven early-EOS audit", 1)[1]
    # corpus_idx must appear in the audit table so the reader can map it
    # back to the offending prompt.
    audit_block = md.split("## Prompt-driven early-EOS audit", 1)[1].split("## ", 1)[0]
    assert " 62 " in audit_block


def test_early_eos_audit_skips_embed_cells() -> None:
    """``tpot_ms`` is chat_stream-only; embed cells with a wall-clock
    matching the same shape must not be surfaced."""
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    artifact.per_cell["embed_c8"]["default_grpc"][2048] = _measurement(
        cell_id="embed_c8",
        cohort="default_grpc",
        max_tokens=2048,
        wall_p50_ms=10000.0,
        tpot_ms=37.0,
        seg_prefill_ms=77.0,
        seg_egress_ms=2.0,
        prompt_source="corpus_sharegpt_embed",
        prompt_corpus_idx=99,
    )
    md = render_markdown(artifact, sweep_mode="validate")
    assert "## Prompt-driven early-EOS audit" not in md


def test_early_eos_audit_skips_small_max_tokens() -> None:
    """At ``max_tokens < EARLY_EOS_AUDIT_MIN_MAX_TOKENS`` a small implied
    token count is the *expected* hit-the-cap regime, not an audit signal."""
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    # max_tokens=50 with implied≈10 → ratio 0.2 (well below threshold)
    # but the cell is below the audit gate, so must not fire.
    artifact.per_cell["chat_stream_c1"]["default_grpc"][50] = _measurement(
        cell_id="chat_stream_c1",
        cohort="default_grpc",
        max_tokens=50,
        wall_p50_ms=400.0,
        tpot_ms=37.0,
        seg_prefill_ms=10.0,
        seg_egress_ms=1.0,
        prompt_source="synthetic_seed_derived",
        prompt_corpus_idx=None,
    )
    assert EARLY_EOS_AUDIT_MIN_MAX_TOKENS > 50
    md = render_markdown(artifact, sweep_mode="validate")
    assert "## Prompt-driven early-EOS audit" not in md


def test_early_eos_audit_threshold_boundary() -> None:
    """A cell at exactly ``EARLY_EOS_RATIO_THRESHOLD`` does not fire
    (strict ``<``); a cell just below does."""
    # ratio = 0.5 exactly → 1024 tokens at max_tokens=2048
    on_threshold = _measurement(
        cell_id="chat_stream_c4",
        cohort="default_grpc",
        max_tokens=2048,
        wall_p50_ms=1024 * 37.0 + 77.0 + 1.0,
        tpot_ms=37.0,
        seg_prefill_ms=77.0,
        seg_egress_ms=1.0,
        prompt_corpus_idx=51,
    )
    implied = compute_implied_output_tokens(on_threshold)
    assert implied is not None
    assert abs(implied - 1024.0) < 1e-6
    assert (implied / 2048) == EARLY_EOS_RATIO_THRESHOLD

    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    artifact.per_cell["chat_stream_c4"]["default_grpc"][2048] = on_threshold
    md = render_markdown(artifact, sweep_mode="validate")
    assert "## Prompt-driven early-EOS audit" not in md, "ratio == threshold must NOT fire"

    # Now drop one token below threshold: ratio = 1023/2048 < 0.5.
    just_below = _measurement(
        cell_id="chat_stream_c4",
        cohort="default_grpc",
        max_tokens=2048,
        wall_p50_ms=1023 * 37.0 + 77.0 + 1.0,
        tpot_ms=37.0,
        seg_prefill_ms=77.0,
        seg_egress_ms=1.0,
        prompt_corpus_idx=51,
    )
    artifact.per_cell["chat_stream_c4"]["default_grpc"][2048] = just_below
    md = render_markdown(artifact, sweep_mode="validate")
    assert "## Prompt-driven early-EOS audit" in md


def test_early_eos_audit_silent_when_tpot_unpopulated() -> None:
    """Fake-driver fixtures that don't carry the M6.1.1 timing payload
    must not be flagged (insufficient evidence). This is the common
    integration-test shape."""
    artifact = _build_artifact(sweep_mode="validate", measured_axis=M6_2_VALIDATE_MAX_TOKENS_AXIS)
    # default _measurement leaves tpot_ms=None → audit must skip.
    md = render_markdown(artifact, sweep_mode="validate")
    assert "## Prompt-driven early-EOS audit" not in md
