"""CLI surface tests for the de-prefixed sweep (FR-018a / SC-009).

The harness CLI is a single milestone-agnostic sweep: running the module is
the publish sweep; ``--validate`` selects the validate subset. There are no
milestone selectors and no ``--m[0-9]`` flags.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.__main__ import _build_parser, _validate_args


def _parse(*argv: str):
    """Parse the ``sweep`` subcommand (the de-prefixed M6.2 sweep)."""
    parser = _build_parser()
    return parser.parse_args(["sweep", *argv])


def _all_option_strings(parser):
    """Every flag across the main parser and all subparsers."""
    opts = list(parser._actions)
    out: list[str] = []
    for action in parser._actions:
        out.extend(action.option_strings)
        # Subparsers expose their sub-parsers via the _SubParsersAction.choices map.
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            for sub in choices.values():
                out.extend(o for a in sub._actions for o in a.option_strings)
    _ = opts
    return out


class TestNoMilestoneFlags:
    def test_help_has_zero_milestone_flags(self) -> None:
        """SC-009: no --m<N>/--m6_2-* flag anywhere (main parser + subcommands)."""
        options = _all_option_strings(_build_parser())
        offenders = [o for o in options if o.lstrip("-").startswith("m") and o[3:4].isdigit()]
        assert offenders == [], f"milestone-prefixed flags present: {offenders}"

    def test_sweep_publish_is_default_mode(self) -> None:
        """`sweep` with no --validate is the publish sweep."""
        args = _parse()
        assert getattr(args, "validate", False) is False

    def test_validate_flag_present(self) -> None:
        args = _parse("--validate")
        assert args.validate is True


class TestDefaultInheritance:
    def test_modal_region_default_eu_west_1(self) -> None:
        assert _parse("--validate").modal_region == "eu-west-1"

    def test_base_seed_default_42(self) -> None:
        assert _parse("--validate").base_seed == 42

    def test_model_default_qwen3_8b(self) -> None:
        assert _parse("--validate").model == "Qwen/Qwen3-8B"

    def test_baseline_default(self) -> None:
        assert str(_parse("--validate").baseline).endswith("m6_1_3-attribution-closure.json")

    def test_modal_token_env_default(self) -> None:
        assert _parse("--validate").modal_token_env == "MODAL_BENCH_TOKEN"


class TestExplicitNGate:
    """FR-004: publish-mode `n` is pinned at n=40 (sweep_types.PUBLISH_N),
    but the CLI gate STILL requires an explicit `--n` — no silent default."""

    def test_publish_default_n_is_none(self) -> None:
        args = _parse()
        assert args.n is None, "no silent default — operator MUST pass --n"

    def test_publish_n_constant_is_40(self) -> None:
        from vllm_grpc_bench.sweep_types import PUBLISH_N

        assert PUBLISH_N == 40

    def test_run_publish_without_n_raises_explicit_n_error(self) -> None:
        from vllm_grpc_bench.sweep import gate_publish_mode_n

        with pytest.raises(ValueError, match="FR-004 explicit-n gate"):
            gate_publish_mode_n(None, "publish")

    def test_run_publish_with_explicit_n_passes_through(self) -> None:
        from vllm_grpc_bench.sweep import gate_publish_mode_n

        assert gate_publish_mode_n(40, "publish") == 40
        assert gate_publish_mode_n(60, "publish") == 60

    def test_validate_with_n_not_20_is_rejected(self, capsys) -> None:
        args = _parse("--validate", "--n=40")
        rc = _validate_args(args)
        assert rc == 1
        assert "pinned at n=20" in capsys.readouterr().err

    def test_validate_with_n_20_ok(self) -> None:
        assert _validate_args(_parse("--validate", "--n=20")) == 0


class TestAsymmetricPromptsFlagNotPresent:
    def test_asymmetric_prompts_flag_rejected_by_parser(self) -> None:
        # FR-008 + spec round-3 Q1: the flag MUST NOT exist.
        with pytest.raises(SystemExit):
            _parse("--asymmetric-prompts")


class TestSubflagsPresent:
    def test_skip_deploy_present(self) -> None:
        assert _parse("--validate", "--skip-deploy").skip_deploy is True

    def test_report_overrides_present(self) -> None:
        args = _parse(
            "--validate",
            "--report-out=/tmp/out.md",
            "--report-json-out=/tmp/out.json",
        )
        assert str(args.report_out) == "/tmp/out.md"
        assert str(args.report_json_out) == "/tmp/out.json"

    def test_modal_endpoint_present(self) -> None:
        assert _parse("--validate", "--modal-endpoint=https://x.example").modal_endpoint == (
            "https://x.example"
        )

    def test_allow_engine_mismatch_present(self) -> None:
        assert _parse("--validate", "--allow-engine-mismatch").allow_engine_mismatch is True
