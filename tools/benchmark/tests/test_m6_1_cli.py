"""Tests for the M6.1 CLI surface (T016).

Parallels ``test_m6_cli.py``. Asserts the M6.1 flag set per ``contracts/cli.md``
parses with the right defaults, mutual exclusion is enforced, and the
torch-pin + baseline pre-checks produce the right exit codes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from vllm_grpc_bench.__main__ import _build_parser, _run_m6_1, _validate_m6_1_args

# --- Flag parsing -------------------------------------------------------------


def _parse(*argv: str) -> argparse.Namespace:
    parser = _build_parser()
    return parser.parse_args(list(argv))


def test_m6_1_flag_defaults() -> None:
    ns = _parse("--m6_1")
    assert ns.m6_1 is True
    assert ns.m6_1_smoke is False
    assert ns.m6_1_modal_region == "eu-west-1"
    assert ns.m6_1_modal_token_env == "MODAL_BENCH_TOKEN"
    assert ns.m6_1_modal_endpoint is None
    assert ns.m6_1_skip_deploy is False
    assert ns.m6_1_base_seed == 42
    assert ns.m6_1_model == "Qwen/Qwen3-8B"
    assert ns.m6_1_rtt_validity_ms == 1.0
    assert ns.m6_1_rtt_exercise_ms == 20.0
    assert ns.m6_1_shim_overhead_warn_pct == 5.0
    assert ns.m6_1_run_id is None
    assert ns.m6_1_m6_baseline == Path("docs/benchmarks/m6-real-engine-mini-validation.json")
    assert ns.m6_1_report_out == Path("docs/benchmarks/m6_1-real-prompt-embeds.md")
    assert ns.m6_1_report_json_out == Path("docs/benchmarks/m6_1-real-prompt-embeds.json")


def test_m6_1_smoke_flag_defaults() -> None:
    ns = _parse("--m6_1-smoke")
    assert ns.m6_1 is False
    assert ns.m6_1_smoke is True


def test_m6_1_flag_overrides() -> None:
    ns = _parse(
        "--m6_1",
        "--m6_1-modal-region=us-east-1",
        "--m6_1-base-seed=99",
        "--m6_1-model=Qwen/Qwen3-32B",
        "--m6_1-skip-deploy",
        "--m6_1-modal-endpoint=grpc=tcp+plaintext://x:50051,rest_https_edge=https://y.modal.run",
    )
    assert ns.m6_1_modal_region == "us-east-1"
    assert ns.m6_1_base_seed == 99
    assert ns.m6_1_model == "Qwen/Qwen3-32B"
    assert ns.m6_1_skip_deploy is True
    assert ns.m6_1_modal_endpoint is not None


# --- Mutual exclusion ---------------------------------------------------------


def test_m6_1_and_m6_1_smoke_rejected_together(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6_1", "--m6_1-smoke")
    assert _validate_m6_1_args(ns) == 2


def test_m6_1_and_m6_rejected_together(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6_1", "--m6")
    assert _validate_m6_1_args(ns) == 2


def test_m6_1_and_m5_2_rejected_together(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6_1", "--m5_2")
    assert _validate_m6_1_args(ns) == 2


def test_m6_1_skip_deploy_without_endpoint_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6_1", "--m6_1-skip-deploy")
    assert _validate_m6_1_args(ns) == 2


def test_m6_1_rtt_threshold_ordering_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6_1", "--m6_1-rtt-validity-ms=5.0", "--m6_1-rtt-exercise-ms=2.0")
    assert _validate_m6_1_args(ns) == 2


def test_m6_1_token_env_missing_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODAL_BENCH_TOKEN", raising=False)
    ns = _parse("--m6_1")
    assert _validate_m6_1_args(ns) == 4


def test_m6_1_validation_passes_with_clean_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6_1")
    assert _validate_m6_1_args(ns) == 0


# --- Dispatch: torch-pin + baseline pre-checks --------------------------------


def test_m6_1_dispatch_aborts_on_torch_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """T025 (d): torch-pin gate raises SystemExit(2) BEFORE baseline loader."""
    import torch

    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    monkeypatch.setattr(torch, "__version__", "9.9.9")
    real_baseline = Path("docs/benchmarks/m6-real-engine-mini-validation.json")
    if not real_baseline.exists():
        pytest.skip(f"baseline JSON not at {real_baseline}; skipping")
    ns = _parse("--m6_1", f"--m6_1-m6-baseline={real_baseline}")
    with pytest.raises(SystemExit) as exc_info:
        _run_m6_1(ns)
    assert exc_info.value.code == 2


def test_m6_1_dispatch_aborts_on_missing_baseline_full_sweep(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    missing = tmp_path / "missing.json"
    ns = _parse("--m6_1", f"--m6_1-m6-baseline={missing}")
    assert _run_m6_1(ns) == 1


def test_m6_1_dispatch_aborts_on_missing_baseline_smoke(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    missing = tmp_path / "missing.json"
    ns = _parse("--m6_1-smoke", f"--m6_1-m6-baseline={missing}")
    assert _run_m6_1(ns) == 2


def test_m6_1_dispatch_baseline_missing_cell_full_sweep(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"supersedes_m5_2_under_real_engine": []}))
    ns = _parse("--m6_1", f"--m6_1-m6-baseline={baseline}")
    assert _run_m6_1(ns) == 1
