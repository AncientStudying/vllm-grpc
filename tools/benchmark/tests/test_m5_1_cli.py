"""T016 — M5.1 CLI flag wiring tests."""

from __future__ import annotations

import argparse

import pytest
from vllm_grpc_bench.__main__ import (
    _build_m5_1_config,
    _build_parser,
    _strip_endpoint_scheme,
    _validate_m5_1_args,
)


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = _build_parser()
    return parser.parse_args(argv)


def test_m5_1_flag_is_recognized() -> None:
    """T016 (a): --m5_1 triggers the M5.1 code path (sets args.m5_1 True)."""
    args = _parse(["--m5_1"])
    assert args.m5_1 is True


def test_m5_1_default_region_is_eu_west_1() -> None:
    args = _parse(["--m5_1"])
    assert args.m5_1_modal_region == "eu-west-1"


def test_m5_1_region_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """T016 (c): --m5_1-modal-region overrides default."""
    args = _parse(["--m5_1", "--m5_1-modal-region=us-west-2"])
    assert args.m5_1_modal_region == "us-west-2"


def test_m5_1_conflicts_with_m5(monkeypatch: pytest.MonkeyPatch) -> None:
    """T016 (b): --m5_1 + --m5 exits with code 2."""
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok")
    args = _parse(["--m5_1", "--m5"])
    assert _validate_m5_1_args(args) == 2


def test_m5_1_conflicts_with_m3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok")
    args = _parse(["--m5_1", "--m3"])
    assert _validate_m5_1_args(args) == 2


def test_m5_1_skip_deploy_requires_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """T016 (d): --m5_1-skip-deploy without --m5_1-modal-endpoint → exit 2."""
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok")
    args = _parse(["--m5_1", "--m5_1-skip-deploy"])
    assert _validate_m5_1_args(args) == 2


def test_m5_1_missing_token_env_returns_4(monkeypatch: pytest.MonkeyPatch) -> None:
    """T016 (e): missing MODAL_BENCH_TOKEN env var → exit 4."""
    monkeypatch.delenv("MODAL_BENCH_TOKEN", raising=False)
    args = _parse(["--m5_1"])
    assert _validate_m5_1_args(args) == 4


def test_m5_1_token_env_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUSTOM_TOKEN", "tok")
    monkeypatch.delenv("MODAL_BENCH_TOKEN", raising=False)
    args = _parse(["--m5_1", "--m5_1-modal-token-env=CUSTOM_TOKEN"])
    assert _validate_m5_1_args(args) == 0


def test_m5_1_rtt_thresholds_must_be_consistent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok")
    args = _parse(
        [
            "--m5_1",
            "--m5_1-rtt-validity-threshold-ms=10",
            "--m5_1-rtt-exercise-threshold-ms=5",
        ]
    )
    assert _validate_m5_1_args(args) == 2


def test_strip_endpoint_scheme_normalizes_urls() -> None:
    """Endpoint scheme stripper handles all Modal tunnel formats."""
    assert _strip_endpoint_scheme("tcp+plaintext://a.modal.host:50051") == "a.modal.host:50051"
    assert _strip_endpoint_scheme("tcp://a.modal.host:50051") == "a.modal.host:50051"
    assert _strip_endpoint_scheme("grpcs://a.modal.host:50051") == "a.modal.host:50051"
    assert _strip_endpoint_scheme("a.modal.host:50051") == "a.modal.host:50051"


def test_m5_1_smoke_flag_shrinks_config() -> None:
    """--m5_1-smoke must produce a sweep config with n=10, rtt_probe_n=4,
    and the 3-cell SMOKE_CELLS override set.
    """
    args = _parse(["--m5_1", "--m5_1-smoke"])
    cfg = _build_m5_1_config(args, rest_url="http://test", grpc_target="t:50051")
    assert cfg.n_per_cohort == 10
    assert cfg.rtt_probe_n == 4
    assert cfg.cells_override is not None
    assert len(cfg.cells_override) == 3


def test_m5_1_without_smoke_uses_full_18_cell_defaults() -> None:
    """Absence of --m5_1-smoke must NOT shrink the cell set or n."""
    args = _parse(["--m5_1"])
    cfg = _build_m5_1_config(args, rest_url="http://test", grpc_target="t:50051")
    assert cfg.n_per_cohort == 100
    assert cfg.cells_override is None


def test_m5_1_endpoint_pair_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """--m5_1-modal-endpoint accepts the 'grpc=...,rest=...' form."""
    args = _parse(
        [
            "--m5_1",
            "--m5_1-skip-deploy",
            "--m5_1-modal-endpoint",
            "grpc=tcp+plaintext://a.modal.host:50051,rest=https://a.modal.host",
        ]
    )
    # The validator passes (skip-deploy + endpoint both set).
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok")
    assert _validate_m5_1_args(args) == 0
