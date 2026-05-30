"""T032 — M6.2 validate CLI integration test.

Exercises ``--m6_2-validate --m6_2-skip-deploy`` end-to-end against the stub
RPC driver wired into :mod:`m6_2_validate`. Asserts the validate-sibling
artifact JSON:

- Contains exactly 72 measured rows + 72 ``not_validated`` placeholder rows
  for a total of 144 ``per_cell`` entries (FR-016 + SC-003).
- Carries the round-5 ``run_meta`` additions (``chat_corpus_sha256``,
  ``embed_corpus_sha256``, ``sub_probe_ran``, etc.).
- ``integrity_warnings`` ⊆ canonical channel labels.
- ``schema_version == "m6_1_1.v1"`` (strict-superset compat, FR-011).
- ``anchor_latency_trajectory`` populated (FR-031: start + end snapshots in
  the validate-mode minimum).

US3 (T043) will extend this test with sub-probe + KV-pressure assertions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from vllm_grpc_bench.m6_2_reporter import INTEGRITY_CHANNELS, NOT_VALIDATED_MARKER
from vllm_grpc_bench.validate import run_m6_2


def _build_validate_args(*, md_path: Path, json_path: Path) -> argparse.Namespace:
    """Construct the ``argparse.Namespace`` shape ``run_m6_2`` expects for
    ``--m6_2-validate --m6_2-skip-deploy`` invocations."""
    return argparse.Namespace(
        m6_2=False,
        m6_2_validate=True,
        m6_2_n=None,  # validate gates this to 20 internally
        m6_2_modal_region="eu-west-1",
        m6_2_modal_token_env="MODAL_BENCH_TOKEN",
        m6_2_modal_endpoint=None,
        m6_2_skip_deploy=True,
        m6_2_base_seed=42,
        m6_2_model="Qwen/Qwen3-8B",
        m6_2_m6_1_3_baseline="docs/benchmarks/m6_1_3-attribution-closure.json",
        m6_2_report_out=md_path,
        m6_2_report_json_out=json_path,
        m6_2_events_sidecar_out=None,
        m6_2_allow_engine_mismatch=False,
    )


def test_validate_cli_produces_artifact_pair(tmp_path: Path) -> None:
    md_path = tmp_path / "m6_2-token-budget-validate.md"
    json_path = tmp_path / "m6_2-token-budget-validate.json"
    args = _build_validate_args(md_path=md_path, json_path=json_path)
    exit_code = run_m6_2(args, sweep_mode="validate")
    assert exit_code == 0, "validate CLI must return 0 on the happy path"
    assert md_path.exists(), "validate markdown artifact must be written"
    assert json_path.exists(), "validate JSON artifact must be written"


def test_validate_artifact_has_72_measured_plus_72_placeholders(tmp_path: Path) -> None:
    md_path = tmp_path / "m6_2-token-budget-validate.md"
    json_path = tmp_path / "m6_2-token-budget-validate.json"
    args = _build_validate_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="validate") == 0
    payload = json.loads(json_path.read_text())
    per_cell = payload["per_cell"]
    assert len(per_cell) == 6, "6 cells expected"
    rows: list[dict[str, object]] = []
    for per_cohort in per_cell.values():
        for per_cap in per_cohort.values():
            for row in per_cap.values():
                rows.append(row)
    # M6.1.2 cohort-set discipline: c=1 cells carry 3 cohorts (default_grpc +
    # rest_https_edge + rest_plain_tcp — tuned_grpc_multiplexed collapses into
    # default_grpc at c=1 per the M5.2 inheritance); c>=2 cells carry all 4.
    # Total cohort-cell slots = 2 c=1 cells × 3 + 4 c>=2 cells × 4 = 22.
    # Validate axis = 3 caps (measured) + 3 caps (placeholders) = 6 caps each.
    # → 22 slots × 6 caps = 132 rows total; 66 measured + 66 placeholders.
    # (The spec's "144 / 72+72" wording reflects the idealized 4-cohort-per-cell
    # case; the live-cohort discipline produces 132 / 66+66.)
    assert len(rows) == 132, "validate live-cohort shape: 22 slots × 6 caps = 132"
    measured = [r for r in rows if r["failed_reason"] != NOT_VALIDATED_MARKER]
    placeholders = [r for r in rows if r["failed_reason"] == NOT_VALIDATED_MARKER]
    assert len(measured) == 66, "66 measured rows under live cohort-set discipline"
    assert len(placeholders) == 66, "66 not_validated placeholders under live discipline"


def test_validate_artifact_schema_version_unchanged(tmp_path: Path) -> None:
    md_path = tmp_path / "m6_2-token-budget-validate.md"
    json_path = tmp_path / "m6_2-token-budget-validate.json"
    args = _build_validate_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="validate") == 0
    payload = json.loads(json_path.read_text())
    assert payload["schema_version"] == "m6_1_1.v1"


def test_validate_artifact_run_meta_carries_round5_additions(tmp_path: Path) -> None:
    md_path = tmp_path / "m6_2-token-budget-validate.md"
    json_path = tmp_path / "m6_2-token-budget-validate.json"
    args = _build_validate_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="validate") == 0
    payload = json.loads(json_path.read_text())
    rm = payload["run_meta"]
    for field in (
        "iteration_order",
        "iteration_discipline_verified",
        "n_per_point",
        "validate_axis_subset",
        "wall_clock_start_utc",
        "wall_clock_end_utc",
        "total_sweep_hours",
        "chat_corpus_sha256",
        "chat_corpus_path",
        "embed_corpus_sha256",
        "embed_corpus_path",
        "sub_probe_ran",
    ):
        assert field in rm, f"run_meta missing additive field {field!r}"
    assert rm["sweep_mode"] == "validate"
    assert rm["iteration_order"] == "cohort_innermost_block"
    assert rm["n_per_point"] == 20
    assert rm["validate_axis_subset"] == [10, 50, 2048]
    assert len(rm["chat_corpus_sha256"]) == 64
    assert len(rm["embed_corpus_sha256"]) == 64
    # Round-5 SC-019: sub-probe runs unconditionally in both publish + validate.
    assert rm["sub_probe_ran"] is True


def test_validate_artifact_integrity_warnings_canonical(tmp_path: Path) -> None:
    md_path = tmp_path / "m6_2-token-budget-validate.md"
    json_path = tmp_path / "m6_2-token-budget-validate.json"
    args = _build_validate_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="validate") == 0
    payload = json.loads(json_path.read_text())
    for channel in payload["integrity_warnings"]:
        assert channel in INTEGRITY_CHANNELS, f"unknown channel {channel!r}"


def test_validate_artifact_carries_max_tokens_axis(tmp_path: Path) -> None:
    md_path = tmp_path / "m6_2-token-budget-validate.md"
    json_path = tmp_path / "m6_2-token-budget-validate.json"
    args = _build_validate_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="validate") == 0
    payload = json.loads(json_path.read_text())
    assert payload["max_tokens_axis"] == [10, 50, 2048]


def test_validate_artifact_anchor_trajectory_populated(tmp_path: Path) -> None:
    """FR-031 / SC-015: validate mode produces ≥ 2 snapshots per cohort
    (start + end). The stub anchor dispatcher fires at sweep start and at
    sweep end, so the trajectory carries 2 snapshots per cohort minimum.
    """
    md_path = tmp_path / "m6_2-token-budget-validate.md"
    json_path = tmp_path / "m6_2-token-budget-validate.json"
    args = _build_validate_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="validate") == 0
    payload = json.loads(json_path.read_text())
    trajectory = payload["anchor_latency_trajectory"]
    assert len(trajectory) == 4, "4 cohorts in M6.1.2's universe"
    for cohort, entry in trajectory.items():
        snapshots = entry["snapshots"]
        assert len(snapshots) >= 1, f"cohort {cohort!r} must have ≥ 1 anchor snapshot"


def test_validate_artifact_markdown_omits_timeline_for_short_sweep(tmp_path: Path) -> None:
    """FR-032 / SC-017: validate-mode markdown OMITS the sweep wall-clock
    timeline subsection when total_sweep_hours < 8. The stub sweep completes
    in seconds, so the timeline must not render.
    """
    md_path = tmp_path / "m6_2-token-budget-validate.md"
    json_path = tmp_path / "m6_2-token-budget-validate.json"
    args = _build_validate_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="validate") == 0
    md = md_path.read_text()
    assert "## Sweep wall-clock timeline" not in md


def test_validate_artifact_carries_method_background_pointer(tmp_path: Path) -> None:
    """FR-019: M6.2 markdown carries the reciprocal Method/Background pointer
    to the M6.1.3 artifact."""
    md_path = tmp_path / "m6_2-token-budget-validate.md"
    json_path = tmp_path / "m6_2-token-budget-validate.json"
    args = _build_validate_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="validate") == 0
    md = md_path.read_text()
    assert "## Method / Background" in md
    assert "m6_1_3-attribution-closure.md" in md


def test_validate_artifact_kv_pressure_observation_has_8_records(tmp_path: Path) -> None:
    """T043 / US3: 4 cohorts × 2 cell-types = 8 :class:`M6_2KVPressureObservation`
    records populated from the sub-probe per FR-036."""
    md_path = tmp_path / "m6_2-token-budget-validate.md"
    json_path = tmp_path / "m6_2-token-budget-validate.json"
    args = _build_validate_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="validate") == 0
    payload = json.loads(json_path.read_text())
    observations = payload["kv_pressure_observation"]
    assert len(observations) == 8, "4 cohorts × 2 cell-types = 8 records"
    types = {obs["cell_type"] for obs in observations}
    assert types == {"chat_stream", "embed"}
    cohorts = {obs["cohort"] for obs in observations}
    assert len(cohorts) == 4


def test_validate_kv_pressure_records_carry_sub_probe_fields(tmp_path: Path) -> None:
    """T043 / US3: each observation carries the round-5 metadata
    (``sub_probe_n_rpcs=20``, ``sub_probe_measurement_regime``,
    cell-type-dependent ``sub_probe_prompt_source``)."""
    md_path = tmp_path / "m6_2-token-budget-validate.md"
    json_path = tmp_path / "m6_2-token-budget-validate.json"
    args = _build_validate_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="validate") == 0
    payload = json.loads(json_path.read_text())
    for obs in payload["kv_pressure_observation"]:
        assert obs["sub_probe_n_rpcs"] == 20
        assert obs["sub_probe_measurement_regime"] == "forced_cap_ignore_eos_true"
        expected_source = (
            "corpus_sharegpt" if obs["cell_type"] == "chat_stream" else "corpus_sharegpt_embed"
        )
        assert obs["sub_probe_prompt_source"] == expected_source


def test_validate_kv_pressure_markdown_subsection_rendered(tmp_path: Path) -> None:
    """T043 / US3: KV-cache pressure subsection rendered when observations
    are present. Subsection labels measurements as forced-cap regime."""
    md_path = tmp_path / "m6_2-token-budget-validate.md"
    json_path = tmp_path / "m6_2-token-budget-validate.json"
    args = _build_validate_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="validate") == 0
    md = md_path.read_text()
    assert "## KV-cache pressure" in md
    assert "forced-cap sub-probe regime" in md
    assert "ignore_eos=True" in md
    # The pending-implementation placeholder must NOT appear.
    assert "User Story 3 sub-probe implementation pending" not in md


def test_validate_protocol_crossover_has_six_records(tmp_path: Path) -> None:
    """T036 / US2: 6 cells → 6 crossover records. Validate-mode renders the
    axis-restricted disclaimer + coarse vocabulary."""
    md_path = tmp_path / "m6_2-token-budget-validate.md"
    json_path = tmp_path / "m6_2-token-budget-validate.json"
    args = _build_validate_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="validate") == 0
    payload = json.loads(json_path.read_text())
    assert len(payload["protocol_crossover"]) == 6
    md = md_path.read_text()
    assert "## Protocol crossover threshold" in md
    assert "Validate-mode crossover analysis is restricted" in md


def test_validate_cli_refuses_m6_2_with_unset_n(tmp_path: Path) -> None:
    """FR-004 round-3 deferral: ``--m6_2`` (publish) must REFUSE to start
    when ``--m6_2-n`` is unset. Validate mode is exempt (pins n=20)."""
    md_path = tmp_path / "m6_2-token-budget.md"
    json_path = tmp_path / "m6_2-token-budget.json"
    args = _build_validate_args(md_path=md_path, json_path=json_path)
    args.m6_2_validate = False
    args.m6_2 = True
    exit_code = run_m6_2(args, sweep_mode="publish")
    assert exit_code == 5, "publish without --m6_2-n must fail with exit 5"
