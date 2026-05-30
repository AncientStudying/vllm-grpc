"""T021 — argparse + mutual exclusion + round-3 deferral + default inheritance.

Per ``specs/027-m6-2-token-budget/contracts/cli.md`` FR-020.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.__main__ import _build_parser


def _parse(*argv: str):
    parser = _build_parser()
    return parser.parse_args(list(argv))


class TestFlagsPresent:
    def test_m6_2_flag_present(self) -> None:
        args = _parse("--m6_2", "--m6_2-n=40")
        assert args.m6_2 is True

    def test_m6_2_validate_flag_present(self) -> None:
        args = _parse("--m6_2-validate")
        assert args.m6_2_validate is True


class TestDefaultInheritance:
    def test_modal_region_default_eu_west_1(self) -> None:
        args = _parse("--m6_2-validate")
        assert args.m6_2_modal_region == "eu-west-1"

    def test_base_seed_default_42(self) -> None:
        args = _parse("--m6_2-validate")
        assert args.m6_2_base_seed == 42

    def test_model_default_qwen3_8b(self) -> None:
        args = _parse("--m6_2-validate")
        assert args.m6_2_model == "Qwen/Qwen3-8B"

    def test_m6_1_3_baseline_default(self) -> None:
        args = _parse("--m6_2-validate")
        assert str(args.m6_2_m6_1_3_baseline).endswith("m6_1_3-attribution-closure.json")

    def test_modal_token_env_default(self) -> None:
        args = _parse("--m6_2-validate")
        assert args.m6_2_modal_token_env == "MODAL_BENCH_TOKEN"


class TestExplicitNGate:
    """FR-004 round-3 closure (2026-05-24): publish-mode `n` is pinned at
    `n=40` (`m6_2_types.M6_2_PUBLISH_N`), but the CLI gate STILL requires
    an explicit `--m6_2-n` flag — no silent default — so an operator
    cannot launch the publish sweep at the wrong n by omission."""

    def test_publish_default_n_is_none(self) -> None:
        args = _parse("--m6_2")
        assert args.m6_2_n is None, "no silent default — operator MUST pass --m6_2-n"

    def test_publish_n_constant_is_40(self) -> None:
        """Round-3 closure regression guard: pinning n=40 is load-bearing
        for FR-021 cost cap + FR-023 wall-clock cap. A silent drift would
        invalidate both."""
        from vllm_grpc_bench.m6_2_types import M6_2_PUBLISH_N

        assert M6_2_PUBLISH_N == 40

    def test_run_publish_without_n_raises_explicit_n_error(self) -> None:
        from vllm_grpc_bench.sweep import gate_publish_mode_n

        with pytest.raises(ValueError, match="FR-004 explicit-n gate"):
            gate_publish_mode_n(None, "publish")

    def test_run_publish_with_explicit_n_passes_through(self) -> None:
        """The canonical n=40 launches cleanly; other n values are
        accepted (operator override) but the canonical value is
        documented in the gate error message."""
        from vllm_grpc_bench.sweep import gate_publish_mode_n

        assert gate_publish_mode_n(40, "publish") == 40
        assert gate_publish_mode_n(60, "publish") == 60

    def test_validate_with_n_not_20_argparse_error(self, capsys) -> None:
        from vllm_grpc_bench.__main__ import _validate_m6_2_args

        args = _parse("--m6_2-validate", "--m6_2-n=40")
        rc = _validate_m6_2_args(args)
        assert rc == 1
        captured = capsys.readouterr()
        assert "pinned at n=20" in captured.err


class TestAsymmetricPromptsFlagNotPresent:
    def test_asymmetric_prompts_flag_rejected_by_parser(self) -> None:
        # FR-008 + spec round-3 Q1: the flag MUST NOT exist.
        with pytest.raises(SystemExit):
            _parse("--m6_2-asymmetric-prompts")


class TestMutualExclusion:
    def test_m6_2_and_m6_2_validate_mutually_exclusive(self, capsys) -> None:
        from vllm_grpc_bench.__main__ import _validate_m6_2_args

        args = _parse("--m6_2", "--m6_2-n=40", "--m6_2-validate")
        rc = _validate_m6_2_args(args)
        assert rc == 1
        captured = capsys.readouterr()
        assert "mutually exclusive" in captured.err

    def test_m6_2_excludes_m6_1_3(self, capsys) -> None:
        from vllm_grpc_bench.__main__ import _validate_m6_2_args

        args = _parse("--m6_2", "--m6_2-n=40", "--m6_1_3")
        rc = _validate_m6_2_args(args)
        assert rc == 1


class TestSubflagsPresent:
    def test_skip_deploy_present(self) -> None:
        args = _parse("--m6_2-validate", "--m6_2-skip-deploy")
        assert args.m6_2_skip_deploy is True

    def test_report_overrides_present(self) -> None:
        args = _parse(
            "--m6_2-validate",
            "--m6_2-report-out=/tmp/out.md",
            "--m6_2-report-json-out=/tmp/out.json",
        )
        assert str(args.m6_2_report_out) == "/tmp/out.md"
        assert str(args.m6_2_report_json_out) == "/tmp/out.json"

    def test_modal_endpoint_present(self) -> None:
        args = _parse("--m6_2-validate", "--m6_2-modal-endpoint=https://x.example")
        assert args.m6_2_modal_endpoint == "https://x.example"

    def test_allow_engine_mismatch_present(self) -> None:
        args = _parse("--m6_2-validate", "--m6_2-allow-engine-mismatch")
        assert args.m6_2_allow_engine_mismatch is True
