"""T044 — M6.2 publish-mode CLI integration test.

Exercises ``--m6_2 --m6_2-n=50 --m6_2-skip-deploy`` end-to-end against the
stub RPC driver. ``n=50`` is used for test speed (the spec's round-3 publish
``n`` decision is still deferred per FR-004; T048 will pin it). Asserts the
canonical publish-mode artifact shape:

- Full 6-point axis × 4-cohort × 6-cell table (132 rows under the M6.1.2
  live-cohort discipline; idealized 144 per data-model.md).
- Zero ``not_validated`` placeholders (publish measures the full axis).
- Full 6-point crossover vocabulary (validate-mode coarse 4-value subset
  does NOT apply).
- ``iteration_discipline_verified=true`` (stub run is contiguous).
- "Sweep wall-clock timeline" subsection renders unconditionally in publish
  mode (FR-032).
- All 4 publish-blocking-eligible integrity warning channels render
  conditionally (the stub data hits none of them).
- Sub-probe contract: 16 blocks × n=20 × ``ignore_eos=True`` per T042;
  ``run_meta.sub_probe_ran=true``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from vllm_grpc_bench.m6_2_reporter import INTEGRITY_CHANNELS, NOT_VALIDATED_MARKER
from vllm_grpc_bench.m6_2_validate import run_m6_2


def _build_publish_args(*, md_path: Path, json_path: Path, n: int = 50) -> argparse.Namespace:
    """Construct the ``argparse.Namespace`` shape ``run_m6_2`` expects for
    ``--m6_2 --m6_2-n=<n> --m6_2-skip-deploy`` invocations."""
    return argparse.Namespace(
        m6_2=True,
        m6_2_validate=False,
        m6_2_n=n,
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


def test_publish_cli_produces_artifact_pair(tmp_path: Path) -> None:
    md_path = tmp_path / "m6_2-token-budget.md"
    json_path = tmp_path / "m6_2-token-budget.json"
    args = _build_publish_args(md_path=md_path, json_path=json_path)
    exit_code = run_m6_2(args, sweep_mode="publish")
    assert exit_code == 0, "publish CLI must return 0 on the happy path"
    assert md_path.exists(), "publish markdown artifact must be written"
    assert json_path.exists(), "publish JSON artifact must be written"


def test_publish_artifact_has_full_6_point_axis(tmp_path: Path) -> None:
    md_path = tmp_path / "m6_2-token-budget.md"
    json_path = tmp_path / "m6_2-token-budget.json"
    args = _build_publish_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="publish") == 0
    payload = json.loads(json_path.read_text())
    assert payload["max_tokens_axis"] == [10, 50, 256, 512, 1024, 2048]


def test_publish_artifact_has_no_not_validated_placeholders(tmp_path: Path) -> None:
    md_path = tmp_path / "m6_2-token-budget.md"
    json_path = tmp_path / "m6_2-token-budget.json"
    args = _build_publish_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="publish") == 0
    payload = json.loads(json_path.read_text())
    rows: list[dict[str, object]] = []
    for per_cohort in payload["per_cell"].values():
        for per_cap in per_cohort.values():
            for row in per_cap.values():
                rows.append(row)
    placeholders = [r for r in rows if r["failed_reason"] == NOT_VALIDATED_MARKER]
    assert len(placeholders) == 0, "publish mode must not emit not_validated placeholders"


def test_publish_artifact_row_count_matches_live_cohort_discipline(tmp_path: Path) -> None:
    """Live cohort-set discipline: 2 c=1 cells × 3 cohorts + 4 c>=2 cells × 4
    cohorts = 22 slots; × 6 caps = 132 publish rows."""
    md_path = tmp_path / "m6_2-token-budget.md"
    json_path = tmp_path / "m6_2-token-budget.json"
    args = _build_publish_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="publish") == 0
    payload = json.loads(json_path.read_text())
    rows: list[dict[str, object]] = []
    for per_cohort in payload["per_cell"].values():
        for per_cap in per_cohort.values():
            for row in per_cap.values():
                rows.append(row)
    assert len(rows) == 132


def test_publish_artifact_iteration_discipline_verified_true(tmp_path: Path) -> None:
    md_path = tmp_path / "m6_2-token-budget.md"
    json_path = tmp_path / "m6_2-token-budget.json"
    args = _build_publish_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="publish") == 0
    payload = json.loads(json_path.read_text())
    assert payload["run_meta"]["iteration_discipline_verified"] is True
    assert "iteration_discipline_broken" not in payload["integrity_warnings"]


def test_publish_artifact_wall_clock_timeline_renders(tmp_path: Path) -> None:
    """Publish mode renders the wall-clock timeline unconditionally per
    FR-032 (validate omits it when sweep < 8h)."""
    md_path = tmp_path / "m6_2-token-budget.md"
    json_path = tmp_path / "m6_2-token-budget.json"
    args = _build_publish_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="publish") == 0
    md = md_path.read_text()
    assert "## Sweep wall-clock timeline" in md


def test_publish_artifact_integrity_warnings_canonical(tmp_path: Path) -> None:
    md_path = tmp_path / "m6_2-token-budget.md"
    json_path = tmp_path / "m6_2-token-budget.json"
    args = _build_publish_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="publish") == 0
    payload = json.loads(json_path.read_text())
    for channel in payload["integrity_warnings"]:
        assert channel in INTEGRITY_CHANNELS, f"unknown channel {channel!r}"


def test_publish_artifact_sub_probe_contract(tmp_path: Path) -> None:
    """Per SC-019: sub-probe runs unconditionally in both publish + validate.
    8 KV-pressure observations (4 cohorts × 2 cell-types), each carrying the
    forced-cap regime markers."""
    md_path = tmp_path / "m6_2-token-budget.md"
    json_path = tmp_path / "m6_2-token-budget.json"
    args = _build_publish_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="publish") == 0
    payload = json.loads(json_path.read_text())
    assert payload["run_meta"]["sub_probe_ran"] is True
    observations = payload["kv_pressure_observation"]
    assert len(observations) == 8
    for obs in observations:
        assert obs["sub_probe_n_rpcs"] == 20
        assert obs["sub_probe_measurement_regime"] == "forced_cap_ignore_eos_true"


def test_publish_artifact_crossover_table_six_records(tmp_path: Path) -> None:
    """Publish mode renders the full 6-point crossover vocabulary (validate
    uses the coarse 4-value subset). One record per cell."""
    md_path = tmp_path / "m6_2-token-budget.md"
    json_path = tmp_path / "m6_2-token-budget.json"
    args = _build_publish_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="publish") == 0
    payload = json.loads(json_path.read_text())
    assert len(payload["protocol_crossover"]) == 6


def test_publish_artifact_markdown_omits_validate_disclaimer(tmp_path: Path) -> None:
    """The crossover axis-restricted disclaimer is validate-mode-only per
    FR-016. Publish mode must NOT carry that callout."""
    md_path = tmp_path / "m6_2-token-budget.md"
    json_path = tmp_path / "m6_2-token-budget.json"
    args = _build_publish_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="publish") == 0
    md = md_path.read_text()
    assert "Validate-mode crossover analysis is restricted" not in md


def test_publish_artifact_run_meta_validate_axis_subset_is_null(tmp_path: Path) -> None:
    md_path = tmp_path / "m6_2-token-budget.md"
    json_path = tmp_path / "m6_2-token-budget.json"
    args = _build_publish_args(md_path=md_path, json_path=json_path)
    assert run_m6_2(args, sweep_mode="publish") == 0
    payload = json.loads(json_path.read_text())
    assert payload["run_meta"]["validate_axis_subset"] is None
    assert payload["run_meta"]["sweep_mode"] == "publish"
    assert payload["run_meta"]["n_per_point"] == 50
