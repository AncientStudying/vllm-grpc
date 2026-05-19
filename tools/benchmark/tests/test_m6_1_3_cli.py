"""M6.1.3 — argparse / CLI unit tests.

Per ``specs/026-m6-1-3-attribution-closure/contracts/cli.md`` + tasks.md
T017: spec-level guards against silent default drift + per-mode modifier
defaults + output-path inference per R-7 + full pairwise mutual-exclusion
sweep against the 14 prior mode flags listed in FR-034.

The four required test families:

* ``test_m6_1_3_inheritable_defaults_match_m6_1_2`` — FR-036 + round-3 Q2
  carry-over: ``--m6_1_3-modal-region`` / ``-base-seed`` / ``-model``
  defaults MUST match M6.1.2's verbatim (which match M6.1.1's). Fails
  loudly if any drifts.
* ``test_m6_1_3_modifier_defaults_per_mode`` — FR-022 + FR-023:
  ``--m6_1_3`` defaults to repeat=5 + n=50; ``--m6_1_3-validate`` to
  repeat=1 + n=50.
* ``test_m6_1_3_output_path_inference_per_mode`` — FR-038 + round-2 Q1 +
  R-7: three-path scheme (validate sibling / canonical / Phase B sibling)
  + operator override.
* ``test_m6_1_3_mutual_exclusion`` — FR-034: pairwise sweep against the
  14 prior mode flags + the m6_1_3 ↔ m6_1_3-validate self-exclusion.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr
from pathlib import Path

import pytest
from vllm_grpc_bench.__main__ import (
    _build_parser,
    _normalize_m6_1_3_modifier_defaults,
    _validate_m6_1_3_args,
)
from vllm_grpc_bench.m6_1_3_validate import infer_output_path

# ---- Default-inheritance regression test (FR-036) -------------------------


def test_m6_1_3_inheritable_defaults_match_m6_1_2() -> None:
    """FR-036 + round-3 Q2 carry-over: --m6_1_3 defaults for modal-region,
    base-seed, model MUST match M6.1.2's verbatim. Spec-level guard
    against silent drift."""
    parser = _build_parser()
    args = parser.parse_args(["--m6_1_3-validate"])
    assert args.m6_1_3_modal_region == "eu-west-1"
    assert args.m6_1_3_base_seed == 42
    assert args.m6_1_3_model == "Qwen/Qwen3-8B"

    # Cross-check: same as M6.1.2's defaults (which inherits M6.1.1's).
    m6_1_2_args = parser.parse_args(["--m6_1_2-validate"])
    assert args.m6_1_3_modal_region == m6_1_2_args.m6_1_2_modal_region
    assert args.m6_1_3_base_seed == m6_1_2_args.m6_1_2_base_seed
    assert args.m6_1_3_model == m6_1_2_args.m6_1_2_model


# ---- Modifier defaults per mode (FR-022 + FR-023) -------------------------


def test_m6_1_3_modifier_defaults_per_mode() -> None:
    """FR-022 + FR-023: --m6_1_3 defaults repeat=5 / n=50 (Phase A);
    --m6_1_3-validate defaults repeat=1 / n=50."""
    parser = _build_parser()

    args_publish = parser.parse_args(["--m6_1_3"])
    _normalize_m6_1_3_modifier_defaults(args_publish)
    assert args_publish.m6_1_3_diagnose_repeat == 5
    assert args_publish.m6_1_3_diagnose_n == 50

    args_validate = parser.parse_args(["--m6_1_3-validate"])
    _normalize_m6_1_3_modifier_defaults(args_validate)
    assert args_validate.m6_1_3_diagnose_repeat == 1
    assert args_validate.m6_1_3_diagnose_n == 50


def test_m6_1_3_explicit_repeat_overrides_per_mode_default() -> None:
    """The mode-aware default applies only when the operator didn't
    pass --m6_1_3-diagnose-repeat explicitly. An explicit value wins."""
    parser = _build_parser()

    args = parser.parse_args(["--m6_1_3-validate", "--m6_1_3-diagnose-repeat=3"])
    _normalize_m6_1_3_modifier_defaults(args)
    assert args.m6_1_3_diagnose_repeat == 3

    args2 = parser.parse_args(["--m6_1_3", "--m6_1_3-diagnose-repeat=1"])
    _normalize_m6_1_3_modifier_defaults(args2)
    assert args2.m6_1_3_diagnose_repeat == 1


# ---- Output-path inference (FR-038 + round-2 Q1 + R-7) --------------------


def test_m6_1_3_output_path_inference_per_mode() -> None:
    """FR-038 + round-2 Q1 + R-7: validate writes to validate sibling;
    --m6_1_3 default writes to canonical; --m6_1_3 with Phase B modifiers
    (repeat=1, n=200) writes to Phase B sibling."""
    parser = _build_parser()

    args_validate = parser.parse_args(["--m6_1_3-validate"])
    _normalize_m6_1_3_modifier_defaults(args_validate)
    assert (
        infer_output_path(args_validate, kind="md")
        == "docs/benchmarks/m6_1_3-attribution-closure-validate.md"
    )
    assert (
        infer_output_path(args_validate, kind="json")
        == "docs/benchmarks/m6_1_3-attribution-closure-validate.json"
    )

    args_publish = parser.parse_args(["--m6_1_3"])
    _normalize_m6_1_3_modifier_defaults(args_publish)
    assert (
        infer_output_path(args_publish, kind="md")
        == "docs/benchmarks/m6_1_3-attribution-closure.md"
    )
    assert (
        infer_output_path(args_publish, kind="json")
        == "docs/benchmarks/m6_1_3-attribution-closure.json"
    )

    args_phase_b = parser.parse_args(
        [
            "--m6_1_3",
            "--m6_1_3-diagnose-repeat=1",
            "--m6_1_3-diagnose-n=200",
        ]
    )
    _normalize_m6_1_3_modifier_defaults(args_phase_b)
    assert (
        infer_output_path(args_phase_b, kind="md")
        == "docs/benchmarks/m6_1_3-attribution-closure-phase-b.md"
    )
    assert (
        infer_output_path(args_phase_b, kind="json")
        == "docs/benchmarks/m6_1_3-attribution-closure-phase-b.json"
    )


def test_m6_1_3_output_path_explicit_override_wins(tmp_path: Path) -> None:
    """Operator override via --m6_1_3-report-out / --m6_1_3-report-json-out
    takes precedence over the inferred path regardless of mode."""
    parser = _build_parser()
    md = tmp_path / "operator.md"
    js = tmp_path / "operator.json"
    args = parser.parse_args(
        [
            "--m6_1_3-validate",
            f"--m6_1_3-report-out={md}",
            f"--m6_1_3-report-json-out={js}",
        ]
    )
    assert infer_output_path(args, kind="md") == str(md)
    assert infer_output_path(args, kind="json") == str(js)


# ---- Mutual-exclusion sweep (FR-034) --------------------------------------


def test_m6_1_3_self_mutual_exclusion() -> None:
    """--m6_1_3 + --m6_1_3-validate → rejected by _validate_m6_1_3_args."""
    parser = _build_parser()
    args = parser.parse_args(["--m6_1_3", "--m6_1_3-validate"])
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = _validate_m6_1_3_args(args)
    assert rc != 0
    assert "mutually exclusive" in buf.getvalue()


# Prior mode flags per contracts/cli.md "Mutual exclusion" + FR-034.
# Each tuple is (cli_flag, the namespace attr name) — argparse rewrites
# hyphens to underscores but the validator uses ``getattr`` on attrs.
_PRIOR_MODE_FLAGS: list[tuple[str, str]] = [
    ("--m6_1_2-validate", "m6_1_2_validate"),
    ("--m6_1_2", "m6_1_2"),
    ("--m6_1_1-diagnose", "m6_1_1_diagnose"),
    ("--m6_1_1", "m6_1_1"),
    ("--m6_1", "m6_1"),
    ("--m6_1-smoke", "m6_1_smoke"),
    ("--m6", "m6"),
    ("--m6-smoke", "m6_smoke"),
    ("--m5_2", "m5_2"),
    ("--m5_2-smoke", "m5_2_smoke"),
    ("--m5_1", "m5_1"),
    ("--m5", "m5"),
    ("--m4", "m4"),
    ("--m3", "m3"),
]


@pytest.mark.parametrize(
    "m6_1_3_flag",
    ["--m6_1_3", "--m6_1_3-validate"],
)
@pytest.mark.parametrize("prior_flag,_attr", _PRIOR_MODE_FLAGS)
def test_m6_1_3_mutual_exclusion_against_prior_modes(
    m6_1_3_flag: str, prior_flag: str, _attr: str
) -> None:
    """FR-034: --m6_1_3 / --m6_1_3-validate are mutually exclusive with
    every prior mode flag the project supports. A pairwise parametrised
    sweep catches future regressions where a new prior-mode flag is
    added without extending M6.1.3's exclusion list."""
    parser = _build_parser()
    args = parser.parse_args([m6_1_3_flag, prior_flag])
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = _validate_m6_1_3_args(args)
    assert rc != 0, (
        f"_validate_m6_1_3_args accepted {m6_1_3_flag} + {prior_flag}; "
        "FR-034 mutual-exclusion guard failed"
    )


def test_m6_1_3_validate_alone_accepted() -> None:
    """Sanity: --m6_1_3-validate alone is accepted by the validator."""
    parser = _build_parser()
    args = parser.parse_args(["--m6_1_3-validate"])
    assert _validate_m6_1_3_args(args) == 0


def test_m6_1_3_alone_accepted() -> None:
    """Sanity: --m6_1_3 alone is accepted by the validator."""
    parser = _build_parser()
    args = parser.parse_args(["--m6_1_3"])
    assert _validate_m6_1_3_args(args) == 0


# ---- Full sub-flag set parses (FR-035) ------------------------------------


def test_m6_1_3_full_subflag_set_parses() -> None:
    """Every documented --m6_1_3-* sub-flag is captured in the Namespace
    with the right Python attribute name."""
    parser = _build_parser()
    args = parser.parse_args(
        [
            "--m6_1_3-validate",
            "--m6_1_3-diagnose-repeat=3",
            "--m6_1_3-diagnose-n=200",
            "--m6_1_3-symmetric-prompts",
            "--m6_1_3-modal-region=us-west-2",
            "--m6_1_3-modal-token-env=OTHER_TOKEN_ENV",
            "--m6_1_3-modal-endpoint=https://example",
            "--m6_1_3-skip-deploy",
            "--m6_1_3-base-seed=99",
            "--m6_1_3-model=test/Other-Model",
            "--m6_1_3-m6-1-1-baseline=/tmp/baseline.json",
            "--m6_1_3-report-out=/tmp/out.md",
            "--m6_1_3-report-json-out=/tmp/out.json",
            "--m6_1_3-events-sidecar-out=/tmp/events.jsonl",
            "--m6_1_3-allow-engine-mismatch",
        ]
    )
    assert args.m6_1_3_validate is True
    assert args.m6_1_3_diagnose_repeat == 3
    assert args.m6_1_3_diagnose_n == 200
    assert args.m6_1_3_symmetric_prompts is True
    assert args.m6_1_3_modal_region == "us-west-2"
    assert args.m6_1_3_modal_token_env == "OTHER_TOKEN_ENV"
    assert args.m6_1_3_modal_endpoint == "https://example"
    assert args.m6_1_3_skip_deploy is True
    assert args.m6_1_3_base_seed == 99
    assert args.m6_1_3_model == "test/Other-Model"
    assert args.m6_1_3_m6_1_1_baseline == Path("/tmp/baseline.json")
    assert args.m6_1_3_report_out == Path("/tmp/out.md")
    assert args.m6_1_3_report_json_out == Path("/tmp/out.json")
    assert args.m6_1_3_events_sidecar_out == Path("/tmp/events.jsonl")
    assert args.m6_1_3_allow_engine_mismatch is True


# ---- M6.1.1 / M6.1.2-frozen regression (FR-037 carry-over) ----------------


def test_m6_1_2_validate_unaffected_by_m6_1_3_addition() -> None:
    """FR-037 carry-over: the M6.1.2 argparse block stays frozen as M6.1.3
    lands. M6.1.2's validator must still accept --m6_1_2-validate alone
    AND must REJECT --m6_1_2-validate + --m6_1_3.

    This guards against a future planner accidentally renaming or dropping
    an M6.1.2 flag while adding M6.1.3.
    """
    from vllm_grpc_bench.__main__ import _validate_m6_1_2_args

    parser = _build_parser()
    args_solo = parser.parse_args(["--m6_1_2-validate"])
    assert args_solo.m6_1_2_validate is True
    assert args_solo.m6_1_2_modal_region == "eu-west-1"
    assert args_solo.m6_1_2_base_seed == 42
    assert args_solo.m6_1_2_model == "Qwen/Qwen3-8B"
    assert _validate_m6_1_2_args(args_solo) == 0

    args_clash = parser.parse_args(["--m6_1_2-validate", "--m6_1_3"])
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = _validate_m6_1_2_args(args_clash)
    assert rc != 0
