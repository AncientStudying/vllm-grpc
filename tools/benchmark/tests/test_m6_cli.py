"""Tests for the M6 CLI surface (T025).

Parallels ``test_m5_2_cli.py``. Asserts the documented flag set per
``contracts/cli.md`` parses with the right defaults, mutual exclusion is
enforced, and the baseline-precondition path produces the right exit codes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from vllm_grpc_bench.__main__ import _build_parser, _run_m6, _validate_m6_args

# --- Flag parsing -------------------------------------------------------------


def _parse(*argv: str) -> argparse.Namespace:
    parser = _build_parser()
    return parser.parse_args(list(argv))


def test_m6_flag_defaults() -> None:
    ns = _parse("--m6")
    assert ns.m6 is True
    assert ns.m6_smoke is False
    assert ns.m6_modal_region == "eu-west-1"
    assert ns.m6_modal_token_env == "MODAL_BENCH_TOKEN"
    assert ns.m6_modal_endpoint is None
    assert ns.m6_skip_deploy is False
    assert ns.m6_base_seed == 42
    assert ns.m6_model == "Qwen/Qwen3-7B"
    assert ns.m6_rtt_validity_ms == 1.0
    assert ns.m6_rtt_exercise_ms == 20.0
    assert ns.m6_shim_overhead_warn_pct == 5.0
    assert ns.m6_run_id is None
    assert ns.m6_m5_2_baseline == Path("docs/benchmarks/m5_2-transport-vs-tuning.json")
    assert ns.m6_report_out == Path("docs/benchmarks/m6-real-engine-mini-validation.md")
    assert ns.m6_report_json_out == Path("docs/benchmarks/m6-real-engine-mini-validation.json")


def test_m6_smoke_flag_defaults() -> None:
    ns = _parse("--m6-smoke")
    assert ns.m6 is False
    assert ns.m6_smoke is True


def test_m6_flag_overrides() -> None:
    ns = _parse(
        "--m6",
        "--m6-modal-region=us-east-1",
        "--m6-base-seed=99",
        "--m6-model=Qwen/Qwen3-32B",
        "--m6-skip-deploy",
        "--m6-modal-endpoint=grpc=tcp+plaintext://x:50051,rest_https_edge=https://y.modal.run",
    )
    assert ns.m6_modal_region == "us-east-1"
    assert ns.m6_base_seed == 99
    assert ns.m6_model == "Qwen/Qwen3-32B"
    assert ns.m6_skip_deploy is True
    assert ns.m6_modal_endpoint is not None


# --- Mutual exclusion ---------------------------------------------------------


def test_m6_and_m6_smoke_rejected_together(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6", "--m6-smoke")
    rc = _validate_m6_args(ns)
    assert rc == 2


def test_m6_and_m5_2_rejected_together(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6", "--m5_2")
    rc = _validate_m6_args(ns)
    assert rc == 2


def test_m6_and_m5_1_rejected_together(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6", "--m5_1")
    rc = _validate_m6_args(ns)
    assert rc == 2


def test_m6_skip_deploy_without_endpoint_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6", "--m6-skip-deploy")
    rc = _validate_m6_args(ns)
    assert rc == 2


def test_m6_rtt_threshold_ordering_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6", "--m6-rtt-validity-ms=5.0", "--m6-rtt-exercise-ms=2.0")
    rc = _validate_m6_args(ns)
    assert rc == 2


def test_m6_token_env_missing_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODAL_BENCH_TOKEN", raising=False)
    ns = _parse("--m6")
    rc = _validate_m6_args(ns)
    assert rc == 4


def test_m6_validation_passes_with_clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6")
    assert _validate_m6_args(ns) == 0


# --- Dispatch (baseline-precondition path) ------------------------------------


def test_m6_dispatch_aborts_on_missing_baseline_full_sweep(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    missing = tmp_path / "missing.json"
    ns = _parse("--m6", f"--m6-m5-2-baseline={missing}")
    # Exit code 1 per contracts/cli.md (full-sweep baseline-precondition fail).
    assert _run_m6(ns) == 1


def test_m6_smoke_dispatch_aborts_on_missing_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    missing = tmp_path / "missing.json"
    ns = _parse("--m6-smoke", f"--m6-m5-2-baseline={missing}")
    # Exit code 2 per contracts/cli.md (smoke baseline-precondition fail).
    assert _run_m6(ns) == 2


def test_m6_dispatch_baseline_missing_cell_full_sweep(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    # Baseline JSON exists but lacks the required cells.
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"protocol_comparison_verdicts": []}))
    ns = _parse("--m6", f"--m6-m5-2-baseline={baseline}")
    assert _run_m6(ns) == 1


def test_m6_dispatch_invokes_sweep_when_baseline_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When the baseline JSON loads cleanly the dispatch enters
    ``_run_m6_full_sweep`` and exits cleanly with code 2 because the
    production Modal driver is not yet wired (T044 leaves a clear seam).
    """
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    real_baseline = Path("docs/benchmarks/m5_2-transport-vs-tuning.json")
    if not real_baseline.exists():
        pytest.skip(f"baseline JSON not at {real_baseline}; skipping")
    ns = _parse("--m6", f"--m6-m5-2-baseline={real_baseline}")
    rc = _run_m6(ns)
    # Modal driver not yet wired → exit code 2 (sweep abort mid-launch).
    assert rc == 2


def test_m6_smoke_dispatch_routes_to_smoke_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Phase 5 (US3): --m6-smoke dispatches to ``_run_m6_smoke``. The
    smoke runner exits with code 2 because the production Modal driver
    is not yet wired (the same seam the full sweep uses).
    """
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    real_baseline = Path("docs/benchmarks/m5_2-transport-vs-tuning.json")
    if not real_baseline.exists():
        pytest.skip(f"baseline JSON not at {real_baseline}; skipping")
    ns = _parse("--m6-smoke", f"--m6-m5-2-baseline={real_baseline}")
    rc = _run_m6(ns)
    assert rc == 2
