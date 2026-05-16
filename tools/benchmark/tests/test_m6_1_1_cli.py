"""Tests for the M6.1.1 CLI surface (T016).

Parallels ``test_m6_1_cli.py``. Asserts the M6.1.1 flag set per
``specs/023-m6-1-1-engine-cost-instrumentation/contracts/cli.md`` parses
with the right defaults, mutual exclusion is enforced (against itself and
all earlier mode flags), and the torch-pin + token-env pre-checks produce
the right exit codes.

Exit-code coverage for codes 1, 3, 5 (Phase 1 / Phase 2 orchestrator paths
— FR-001/4/16/17/18) lands with US1's ``test_m6_1_1_diagnose.py`` and
US2's ``test_m6_1_1_phase2.py``; those orchestrators are not yet wired in
the Phase 1+Phase 2 scope of this commit.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from vllm_grpc_bench.__main__ import _build_parser, _run_m6_1_1, _validate_m6_1_1_args


def _parse(*argv: str) -> argparse.Namespace:
    parser = _build_parser()
    return parser.parse_args(list(argv))


def _bypass_torch_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the torch-pin validator to a no-op for argparse-only tests."""
    from vllm_grpc_bench import m6_1_torch_pin

    monkeypatch.setattr(m6_1_torch_pin, "validate_torch_version", lambda: "2.11.0")


# --- Flag parsing -----------------------------------------------------------


def test_m6_1_1_diagnose_flag_defaults() -> None:
    ns = _parse("--m6_1_1-diagnose")
    assert ns.m6_1_1_diagnose is True
    assert ns.m6_1_1 is False
    assert ns.m6_1_1_modal_region == "eu-west-1"
    assert ns.m6_1_1_modal_token_env == "MODAL_BENCH_TOKEN"
    assert ns.m6_1_1_modal_endpoint is None
    assert ns.m6_1_1_skip_deploy is False
    assert ns.m6_1_1_base_seed == 42
    assert ns.m6_1_1_model == "Qwen/Qwen3-8B"
    assert ns.m6_1_1_m6_1_baseline == Path("docs/benchmarks/m6_1-real-prompt-embeds.json")
    assert ns.m6_1_1_report_out == Path("docs/benchmarks/m6_1_1-engine-cost-instrumentation.md")
    assert ns.m6_1_1_report_json_out == Path(
        "docs/benchmarks/m6_1_1-engine-cost-instrumentation.json"
    )
    assert ns.m6_1_1_events_sidecar_out == Path("docs/benchmarks/m6_1_1-events.jsonl")
    assert ns.m6_1_1_allow_engine_mismatch is False


def test_m6_1_1_phase_2_flag_defaults() -> None:
    ns = _parse("--m6_1_1")
    assert ns.m6_1_1 is True
    assert ns.m6_1_1_diagnose is False


def test_m6_1_1_modal_overrides_parse() -> None:
    ns = _parse(
        "--m6_1_1-diagnose",
        "--m6_1_1-modal-region=us-east-1",
        "--m6_1_1-base-seed=100",
        "--m6_1_1-model=Qwen/Qwen2.5-7B",
        "--m6_1_1-allow-engine-mismatch",
    )
    assert ns.m6_1_1_modal_region == "us-east-1"
    assert ns.m6_1_1_base_seed == 100
    assert ns.m6_1_1_model == "Qwen/Qwen2.5-7B"
    assert ns.m6_1_1_allow_engine_mismatch is True


# --- Mutual exclusion -------------------------------------------------------


def test_m6_1_1_diagnose_plus_m6_1_1_phase_2_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both mode flags together → exit code 2."""
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6_1_1-diagnose", "--m6_1_1")
    assert _validate_m6_1_1_args(ns) == 2


def test_m6_1_1_plus_m6_1_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """M6.1.1 + M6.1 → exit code 2 (M6.1.1 is parallel to M6.1, not stacked)."""
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6_1_1", "--m6_1")
    assert _validate_m6_1_1_args(ns) == 2


def test_m6_1_1_plus_m6_smoke_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6_1_1-diagnose", "--m6-smoke")
    assert _validate_m6_1_1_args(ns) == 2


def test_m6_1_1_plus_m5_2_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6_1_1", "--m5_2")
    assert _validate_m6_1_1_args(ns) == 2


@pytest.mark.parametrize("earlier_flag", ["--m3", "--m4", "--m5", "--m5_1"])
def test_m6_1_1_plus_earlier_mode_flag_rejected(
    earlier_flag: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6_1_1-diagnose", earlier_flag)
    assert _validate_m6_1_1_args(ns) == 2


# --- Skip-deploy preconditions ---------------------------------------------


def test_skip_deploy_without_endpoint_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse("--m6_1_1-diagnose", "--m6_1_1-skip-deploy")
    assert _validate_m6_1_1_args(ns) == 2


def test_skip_deploy_with_endpoint_validated_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    ns = _parse(
        "--m6_1_1-diagnose",
        "--m6_1_1-skip-deploy",
        "--m6_1_1-modal-endpoint=grpc=tcp+plaintext://x:50051",
    )
    assert _validate_m6_1_1_args(ns) == 0


# --- Token env precondition -------------------------------------------------


def test_missing_token_env_yields_exit_4(monkeypatch: pytest.MonkeyPatch) -> None:
    """No MODAL_BENCH_TOKEN env var → exit code 4 per contracts/cli.md mutex-table."""
    monkeypatch.delenv("MODAL_BENCH_TOKEN", raising=False)
    ns = _parse("--m6_1_1-diagnose")
    assert _validate_m6_1_1_args(ns) == 4


def test_custom_token_env_var_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODAL_BENCH_TOKEN", raising=False)
    monkeypatch.setenv("CUSTOM_TOK", "xyz")
    ns = _parse("--m6_1_1-diagnose", "--m6_1_1-modal-token-env=CUSTOM_TOK")
    assert _validate_m6_1_1_args(ns) == 0


# --- Torch-pin gate (FR-003 → exit code 2) ----------------------------------


def test_torch_pin_mismatch_exits_code_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """A wrong torch version on the client → SystemExit(2) per FR-003."""
    import torch

    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    monkeypatch.setattr(torch, "__version__", "9.9.9")
    ns = _parse("--m6_1_1-diagnose")
    with pytest.raises(SystemExit) as exc_info:
        _run_m6_1_1(ns)
    assert exc_info.value.code == 2


def test_torch_pin_bypass_allows_dispatch_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the torch-pin bypassed, _run_m6_1_1 reaches dispatch — the
    orchestrator is a NotImplementedError stub in Phase 1+2 foundational
    scope. The orchestrator-side exit codes (1, 3, 5) are covered by US1/US2
    tests once T023 / T029 land."""
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "tok-xyz")
    _bypass_torch_pin(monkeypatch)
    ns = _parse("--m6_1_1-diagnose")
    with pytest.raises(NotImplementedError, match="run_m6_1_1_diagnose lands in T023"):
        _run_m6_1_1(ns)
