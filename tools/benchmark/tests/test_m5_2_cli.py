"""T028 — M5.2 CLI flag-wiring tests.

Asserts the ``--m5_2*`` flag family parses correctly per the contract:
- ``--m5_2`` toggles M5.2 mode.
- ``--m5_2`` is mutually exclusive with ``--m3``, ``--m4``, ``--m5``,
  ``--m5_1`` (exit code 2).
- ``--m5_2-smoke`` triggers the smoke codepath.
- ``--m5_2-modal-region`` accepts overrides.
- ``--m5_2-skip-deploy`` requires ``--m5_2-modal-endpoint`` (exit code 2).
- Missing ``MODAL_BENCH_TOKEN`` exits 4.
- ``--m5_2-n`` defaults to 250.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from vllm_grpc_bench.__main__ import (
    _build_parser,
    _parse_m5_2_endpoint,
    _validate_m5_2_args,
)


def _parse(argv: list[str]) -> argparse.Namespace:
    return _build_parser().parse_args(argv)


def test_m5_2_flag_default_off() -> None:
    args = _parse([])
    assert args.m5_2 is False
    assert args.m5_2_smoke is False


def test_m5_2_flag_default_n_is_250() -> None:
    args = _parse(["--m5_2"])
    assert args.m5_2 is True
    assert args.m5_2_n == 250


def test_m5_2_modal_region_default_is_eu_west_1() -> None:
    args = _parse(["--m5_2"])
    assert args.m5_2_modal_region == "eu-west-1"


def test_m5_2_modal_region_override() -> None:
    args = _parse(["--m5_2", "--m5_2-modal-region=us-west-2"])
    assert args.m5_2_modal_region == "us-west-2"


def test_m5_2_smoke_triggers_smoke_codepath() -> None:
    args = _parse(["--m5_2-smoke"])
    assert args.m5_2_smoke is True


def test_m5_2_warmup_n_default_is_20() -> None:
    args = _parse(["--m5_2"])
    assert args.m5_2_warmup_n == 20


def test_m5_2_rtt_thresholds_have_documented_defaults() -> None:
    args = _parse(["--m5_2"])
    assert args.m5_2_rtt_validity_threshold_ms == 1.0
    assert args.m5_2_rtt_exercise_threshold_ms == 20.0


def test_m5_2_modal_endpoint_parses_all_three_urls() -> None:
    parsed = _parse_m5_2_endpoint(
        "grpc=tcp+plaintext://abc.modal.host:50051,"
        "rest_https_edge=https://abc-shim.modal.run,"
        "rest_plain_tcp=tcp+plaintext://abc-shim.modal.host:8000"
    )
    assert parsed is not None
    grpc, edge, tcp = parsed
    assert grpc == "abc.modal.host:50051"
    assert edge == "https://abc-shim.modal.run"
    assert tcp == "tcp+plaintext://abc-shim.modal.host:8000"


def test_m5_2_modal_endpoint_returns_none_on_missing_parts() -> None:
    assert _parse_m5_2_endpoint("grpc=tcp+plaintext://abc.host:50051") is None


def test_m5_2_mutually_exclusive_with_m5_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "x")
    args = _parse(["--m5_2", "--m5_1"])
    rc = _validate_m5_2_args(args)
    assert rc == 2


def test_m5_2_mutually_exclusive_with_m5(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "x")
    args = _parse(["--m5_2", "--m5"])
    rc = _validate_m5_2_args(args)
    assert rc == 2


def test_m5_2_mutually_exclusive_with_m4(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "x")
    args = _parse(["--m5_2", "--m4"])
    rc = _validate_m5_2_args(args)
    assert rc == 2


def test_m5_2_mutually_exclusive_with_m3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "x")
    args = _parse(["--m5_2", "--m3"])
    rc = _validate_m5_2_args(args)
    assert rc == 2


def test_m5_2_skip_deploy_requires_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "x")
    args = _parse(["--m5_2", "--m5_2-skip-deploy"])
    rc = _validate_m5_2_args(args)
    assert rc == 2


def test_m5_2_skip_deploy_with_endpoint_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "x")
    args = _parse(
        [
            "--m5_2",
            "--m5_2-skip-deploy",
            "--m5_2-modal-endpoint=grpc=tcp+plaintext://h:50051,"
            "rest_https_edge=https://h.modal.run,"
            "rest_plain_tcp=tcp+plaintext://h:8000",
        ]
    )
    rc = _validate_m5_2_args(args)
    assert rc == 0


def test_missing_modal_bench_token_exits_4(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODAL_BENCH_TOKEN", raising=False)
    args = _parse(["--m5_2"])
    rc = _validate_m5_2_args(args)
    assert rc == 4


def test_rtt_threshold_inversion_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "x")
    args = _parse(
        [
            "--m5_2",
            "--m5_2-rtt-validity-threshold-ms=50.0",
            "--m5_2-rtt-exercise-threshold-ms=10.0",
        ]
    )
    rc = _validate_m5_2_args(args)
    assert rc == 2


def test_m5_2_events_sidecar_out_default_path() -> None:
    args = _parse(["--m5_2"])
    assert Path(args.m5_2_events_sidecar_out) == Path("bench-results/m5_2-full")


def test_m5_2_skip_geolocation_lookup_flag() -> None:
    args = _parse(["--m5_2", "--m5_2-skip-geolocation-lookup"])
    assert args.m5_2_skip_geolocation_lookup is True
