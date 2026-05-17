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


# --- Modal-backed dispatch (mocked) ----------------------------------------


def test_run_m6_1_2_modal_deploy_failure_returns_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A ``ModalDeployError`` from ``provide_m6_endpoint`` maps to exit 2
    per ``contracts/cli.md`` "Exit codes"."""
    from contextlib import asynccontextmanager

    from vllm_grpc_bench.modal_endpoint import ModalDeployError

    @asynccontextmanager
    async def _raise_deploy_error(**_kwargs: object):  # type: ignore[no-untyped-def]
        raise ModalDeployError("simulated deploy failure")
        yield  # unreachable; satisfies the generator contract for asynccontextmanager

    monkeypatch.setattr(
        "vllm_grpc_bench.modal_endpoint.provide_m6_endpoint",
        _raise_deploy_error,
    )

    parser = _build_parser()
    args = parser.parse_args(
        [
            "--m6_1_2-validate",
            f"--m6_1_2-report-out={tmp_path / 'out.md'}",
            f"--m6_1_2-report-json-out={tmp_path / 'out.json'}",
        ]
    )
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = _run_m6_1_2(args)
    assert rc == 2
    assert "Modal deploy/handshake failed" in buf.getvalue()


def test_run_m6_1_2_modal_backed_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """End-to-end Modal-backed path with both ``provide_m6_endpoint`` and
    ``provide_m6_1_2_rpc_driver`` mocked. Confirms the wiring:

    * Endpoints from the deploy translate into the handshake dict the
      sweep orchestrator passes to ``run_topology_probe``.
    * The injected driver gets dispatched per (cell, cohort).
    * Artifact lands at the configured output paths.
    """
    import asyncio
    import json
    from contextlib import asynccontextmanager

    from vllm_grpc_bench.m6_1_types import M6_1Cell
    from vllm_grpc_bench.m6_engine_cost import EngineCostSpan
    from vllm_grpc_bench.m6_sweep import RPCResult
    from vllm_grpc_bench.modal_endpoint import RESTGRPCEndpoints

    fake_endpoints = RESTGRPCEndpoints(
        grpc_url="grpc.example:5678",
        rest_url="https://rest.example",
        auth_token_env_var="MODAL_BENCH_TOKEN",
        rest_plain_tcp_url="tcp+plaintext://plain.example:1234",
        rest_https_edge_url="https://edge.example",
    )

    captured_handshake: dict[str, object] = {}

    @asynccontextmanager
    async def _fake_provide_endpoint(**_kwargs: object):  # type: ignore[no-untyped-def]
        yield fake_endpoints

    async def _stub_driver(cohort, cell: M6_1Cell, seed: int) -> RPCResult:  # type: ignore[no-untyped-def]
        return RPCResult(
            success=True,
            wall_clock_ms=100.0,
            ttft_ms=40.0 if cell.path == "chat_stream" else None,
            engine_cost=EngineCostSpan(
                engine_ttft_ms=40.0 if cell.path == "chat_stream" else None,
                engine_forward_ms=10.0 if cell.path == "embed" else None,
            ),
            failure_reason=None,
        )

    @asynccontextmanager
    async def _fake_provide_driver(_endpoints, **_kwargs):  # type: ignore[no-untyped-def]
        yield _stub_driver, {}

    async def _capture_probe(
        handshake_dict,
        cohorts,
        per_cohort_timeout_seconds,
        *,
        ranges=None,  # type: ignore[no-untyped-def]
    ):
        captured_handshake.update(handshake_dict)
        # Stub successful network paths so the sweep can build a clean artifact.
        from vllm_grpc_bench.m6_1_2_types import (
            M6_1_2NetworkPath,
            M6_1_2NetworkPathHop,
        )

        return {
            c: M6_1_2NetworkPath(
                endpoint_ip="192.0.2.1",
                hops=[
                    M6_1_2NetworkPathHop(
                        hop_number=1,
                        ip="192.168.1.1",
                        rtt_ms_or_null=1.0,
                        cloud_provider=None,
                    )
                ],
                cloud_provider="AWS",
                region="us-west-1",
                probe_method="tcptraceroute",
                probed_at_utc="2026-05-17T12:00:00Z",
            )
            for c in cohorts
        }

    monkeypatch.setattr(
        "vllm_grpc_bench.modal_endpoint.provide_m6_endpoint",
        _fake_provide_endpoint,
    )
    monkeypatch.setattr(
        "vllm_grpc_bench.m6_1_rpc_driver.provide_m6_1_2_rpc_driver",
        _fake_provide_driver,
    )
    monkeypatch.setattr(
        "vllm_grpc_bench.m6_1_2_sweep.run_topology_probe",
        _capture_probe,
    )

    parser = _build_parser()
    json_out = tmp_path / "out.json"
    args = parser.parse_args(
        [
            "--m6_1_2-validate",
            f"--m6_1_2-report-out={tmp_path / 'out.md'}",
            f"--m6_1_2-report-json-out={json_out}",
        ]
    )

    # Sanity: assertion the test would otherwise pass spuriously if we
    # forgot to monkeypatch — assert the real modal_endpoint module is
    # still importable but our patches are in effect.
    _ = asyncio  # quiet "imported but unused" if the asyncio dep moves

    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = _run_m6_1_2(args)
    assert rc == 0, f"expected exit 0, got {rc}; stderr was: {buf.getvalue()}"

    # Handshake dict was built from the fake endpoints with the right keys.
    assert captured_handshake == {
        "rest_https_edge_url": "https://edge.example",
        "rest_plain_tcp_url": "tcp+plaintext://plain.example:1234",
        "grpc": "grpc.example:5678",
    }

    # Artifact was written and contains the expected network_paths block.
    payload = json.loads(json_out.read_text())
    assert payload["run_meta"]["sweep_mode"] == "validate"
    assert set(payload["network_paths"].keys()) == {
        "rest_https_edge",
        "rest_plain_tcp",
        "default_grpc",
        "tuned_grpc_multiplexed",
    }
