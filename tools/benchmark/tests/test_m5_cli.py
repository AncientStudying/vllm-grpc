"""T019 — M5 CLI flag wiring (contracts/m5-bench-cli.md).

These tests exercise the argparse surface and the `_validate_m5_args` /
`_build_m5_config` helpers; the actual sweep is not invoked.
"""

from __future__ import annotations

import argparse

import pytest
from vllm_grpc_bench.__main__ import (
    _build_m5_config,
    _build_parser,
    _validate_m5_args,
)


def _parse(*argv: str) -> argparse.Namespace:
    parser = _build_parser()
    return parser.parse_args(list(argv))


class TestFlagDefaults:
    def test_defaults(self) -> None:
        args = _parse("--m5")
        assert args.m5 is True
        assert args.m5_modal_region == "auto-far"
        assert args.m5_modal_token_env == "MODAL_BENCH_TOKEN"
        assert args.m5_rtt_validity_threshold_ms == 1.0
        assert args.m5_rtt_exercise_threshold_ms == 20.0
        assert args.m5_warmup_n == 32
        assert args.m5_skip_deploy is False
        assert args.m5_modal_endpoint is None

    def test_overrides(self) -> None:
        args = _parse(
            "--m5",
            "--m5-modal-region=eu-west-1",
            "--m5-rtt-validity-threshold-ms=0.5",
            "--m5-rtt-exercise-threshold-ms=15.0",
            "--m5-warmup-n=16",
        )
        assert args.m5_modal_region == "eu-west-1"
        assert args.m5_rtt_validity_threshold_ms == 0.5
        assert args.m5_rtt_exercise_threshold_ms == 15.0
        assert args.m5_warmup_n == 16


class TestValidation:
    def test_skip_deploy_requires_endpoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MODAL_BENCH_TOKEN", "abc")
        args = _parse("--m5", "--m5-skip-deploy")
        rc = _validate_m5_args(args)
        assert rc == 2

    def test_skip_deploy_with_endpoint_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MODAL_BENCH_TOKEN", "abc")
        args = _parse(
            "--m5",
            "--m5-skip-deploy",
            "--m5-modal-endpoint=r3.modal.host:54321",
        )
        rc = _validate_m5_args(args)
        assert rc == 0

    def test_m5_mutually_exclusive_with_m4(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MODAL_BENCH_TOKEN", "abc")
        args = _parse("--m5", "--m4")
        rc = _validate_m5_args(args)
        assert rc == 2

    def test_token_env_unset_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MODAL_BENCH_TOKEN", raising=False)
        args = _parse("--m5")
        rc = _validate_m5_args(args)
        assert rc == 2

    def test_custom_token_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TOKEN", "xyz")
        monkeypatch.delenv("MODAL_BENCH_TOKEN", raising=False)
        args = _parse("--m5", "--m5-modal-token-env=MY_TOKEN")
        assert _validate_m5_args(args) == 0

    def test_exercise_threshold_below_validity_threshold_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MODAL_BENCH_TOKEN", "abc")
        args = _parse(
            "--m5",
            "--m5-rtt-validity-threshold-ms=5.0",
            "--m5-rtt-exercise-threshold-ms=2.0",
        )
        rc = _validate_m5_args(args)
        assert rc == 2

    def test_expand_n_must_exceed_candidate_n(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MODAL_BENCH_TOKEN", "abc")
        args = _parse("--m5", "--candidate-n=200", "--expand-n=150")
        rc = _validate_m5_args(args)
        assert rc == 2

    def test_baseline_n_below_100_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MODAL_BENCH_TOKEN", "abc")
        args = _parse("--m5", "--baseline-n=50")
        rc = _validate_m5_args(args)
        assert rc == 2


class TestBuildConfig:
    def test_auto_far_resolves_to_us_east_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MODAL_BENCH_TOKEN", "abc")
        args = _parse("--m5")
        args.m4_pacing = "no_pacing"
        args.m4_shared_baseline = True
        config = _build_m5_config(args)
        assert config.modal_region == "us-east-1"  # type: ignore[attr-defined]

    def test_skip_deploy_endpoint_threaded_into_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MODAL_BENCH_TOKEN", "abc")
        args = _parse(
            "--m5",
            "--m5-skip-deploy",
            "--m5-modal-endpoint=r3.modal.host:54321",
        )
        args.m4_pacing = "no_pacing"
        args.m4_shared_baseline = True
        config = _build_m5_config(args)
        assert config.skip_deploy_endpoint == "r3.modal.host:54321"  # type: ignore[attr-defined]
