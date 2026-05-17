"""M6.1.2 — argparse / CLI unit tests.

Per ``specs/025-m6-1-2-methodology-discipline/tasks.md`` T033 + T033a:

* ``test_m6_1_2_inheritable_defaults_match_m6_1_1`` — FR-027 + round-3 Q2
  default-inheritance regression: ``--m6_1_2-modal-region`` /
  ``-base-seed`` / ``-model`` MUST match M6.1.1's verbatim, sourced from
  ``__main__.py`` defaults.
* ``test_m6_1_2_modes_mutually_exclusive`` — ``--m6_1_2`` +
  ``--m6_1_2-validate`` → argparse + dispatch rejects (exit 1).
* ``test_m6_1_2_rejects_against_m6_1_1_diagnose`` — cross-milestone
  mutual exclusion per FR-026.
* ``test_m6_1_2_full_subflag_set_parses`` — every ``--m6_1_2-*`` flag
  documented in ``contracts/cli.md`` parses to the expected attribute.
* ``test_m6_1_1_diagnose_unchanged_post_m6_1_2`` (T033a / G1 remediation):
  the M6.1.1 argparse block is byte-frozen — defaults survive M6.1.2's
  addition.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr
from pathlib import Path

import pytest
from vllm_grpc_bench.__main__ import (
    _build_parser,
    _run_m6_1_2,
    _validate_m6_1_1_args,
    _validate_m6_1_2_args,
)


def test_m6_1_2_inheritable_defaults_match_m6_1_1() -> None:
    """FR-027 + round-3 Q2: --m6_1_2 defaults for modal-region, base-seed,
    model MUST match M6.1.1's verbatim. Spec-level guard against silent
    drift."""
    parser = _build_parser()
    args = parser.parse_args(["--m6_1_2-validate"])
    assert args.m6_1_2_modal_region == "eu-west-1"
    assert args.m6_1_2_base_seed == 42
    assert args.m6_1_2_model == "Qwen/Qwen3-8B"
    # Cross-check: same as M6.1.1's defaults.
    m6_1_1_args = parser.parse_args(["--m6_1_1-diagnose"])
    assert args.m6_1_2_modal_region == m6_1_1_args.m6_1_1_modal_region
    assert args.m6_1_2_base_seed == m6_1_1_args.m6_1_1_base_seed
    assert args.m6_1_2_model == m6_1_1_args.m6_1_1_model


def test_m6_1_2_modes_mutually_exclusive() -> None:
    """--m6_1_2 + --m6_1_2-validate → rejected by _validate_m6_1_2_args."""
    parser = _build_parser()
    args = parser.parse_args(["--m6_1_2", "--m6_1_2-validate"])
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = _validate_m6_1_2_args(args)
    assert rc != 0
    assert "mutually exclusive" in buf.getvalue()


def test_m6_1_2_rejects_against_m6_1_1_diagnose() -> None:
    """FR-026: --m6_1_2-validate is mutually exclusive with --m6_1_1-diagnose."""
    parser = _build_parser()
    args = parser.parse_args(["--m6_1_2-validate", "--m6_1_1-diagnose"])
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = _validate_m6_1_2_args(args)
    assert rc != 0


def test_m6_1_2_rejects_against_m6() -> None:
    """FR-026: --m6_1_2 is mutually exclusive with --m6 family flags."""
    parser = _build_parser()
    args = parser.parse_args(["--m6_1_2", "--m6"])
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = _validate_m6_1_2_args(args)
    assert rc != 0


def test_m6_1_2_validate_alone_accepted() -> None:
    """Sanity: --m6_1_2-validate alone is accepted."""
    parser = _build_parser()
    args = parser.parse_args(["--m6_1_2-validate"])
    assert _validate_m6_1_2_args(args) == 0


def test_m6_1_2_full_subflag_set_parses() -> None:
    """Every documented --m6_1_2-* sub-flag is captured in the Namespace
    with the right Python attribute name."""
    parser = _build_parser()
    args = parser.parse_args(
        [
            "--m6_1_2-validate",
            "--m6_1_2-modal-region=us-west-2",
            "--m6_1_2-modal-token-env=OTHER_TOKEN_ENV",
            "--m6_1_2-modal-endpoint=https://example",
            "--m6_1_2-skip-deploy",
            "--m6_1_2-base-seed=99",
            "--m6_1_2-model=test/Other-Model",
            "--m6_1_2-m6-1-1-baseline=/tmp/baseline.json",
            "--m6_1_2-report-out=/tmp/out.md",
            "--m6_1_2-report-json-out=/tmp/out.json",
            "--m6_1_2-events-sidecar-out=/tmp/events.jsonl",
            "--m6_1_2-allow-engine-mismatch",
        ]
    )
    assert args.m6_1_2_validate is True
    assert args.m6_1_2_modal_region == "us-west-2"
    assert args.m6_1_2_modal_token_env == "OTHER_TOKEN_ENV"
    assert args.m6_1_2_modal_endpoint == "https://example"
    assert args.m6_1_2_skip_deploy is True
    assert args.m6_1_2_base_seed == 99
    assert args.m6_1_2_model == "test/Other-Model"
    assert args.m6_1_2_m6_1_1_baseline == Path("/tmp/baseline.json")
    assert args.m6_1_2_report_out == Path("/tmp/out.md")
    assert args.m6_1_2_report_json_out == Path("/tmp/out.json")
    assert args.m6_1_2_events_sidecar_out == Path("/tmp/events.jsonl")
    assert args.m6_1_2_allow_engine_mismatch is True


# --- T033a: M6.1.1-frozen regression (G1 remediation) ----------------------


def test_m6_1_1_diagnose_unchanged_post_m6_1_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-028 (G1 remediation): the M6.1.1 argparse block is byte-frozen.

    Adding the M6.1.2 flags must not silently rename or drift any
    --m6_1_1-* default. If a future planner accidentally edits the
    M6.1.1 block while adding M6.1.2 flags, this test fails and blocks
    merge.
    """
    # Set the bearer-token env var so _validate_m6_1_1_args doesn't bail
    # on the env-var precondition (the precondition is M6.1.1's, not part
    # of what we're regression-testing).
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "test-token")

    parser = _build_parser()
    args = parser.parse_args(["--m6_1_1-diagnose"])
    assert args.m6_1_1_diagnose is True
    assert args.m6_1_1_modal_region == "eu-west-1"
    assert args.m6_1_1_base_seed == 42
    assert args.m6_1_1_model == "Qwen/Qwen3-8B"
    # And the M6.1.1 args validator still accepts the flag without a new
    # mutual-exclusion conflict.
    rc = _validate_m6_1_1_args(args)
    assert rc == 0


# --- Dispatch: _run_m6_1_2 returns expected exit codes ---------------------


def test_run_m6_1_2_skip_deploy_without_driver_returns_5(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When --m6_1_2-skip-deploy is set but no driver is injected at
    dispatch time, the entry function returns exit code 5 per
    contracts/cli.md."""
    parser = _build_parser()
    args = parser.parse_args(
        [
            "--m6_1_2-validate",
            "--m6_1_2-skip-deploy",
            f"--m6_1_2-report-out={tmp_path / 'out.md'}",
            f"--m6_1_2-report-json-out={tmp_path / 'out.json'}",
        ]
    )
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = _run_m6_1_2(args)
    assert rc == 5
