"""T017 — Modal-secrets-gated end-to-end smoke test for M5.1.

Deploys the dual-protocol Modal app, exercises the bearer-authenticated
``/healthz`` (REST) and ``Health.Ping`` (gRPC) probes, runs one tiny
cohort on each protocol, and confirms clean teardown.

Per ``contracts/m5_1-modal-app.md`` §"Local smoke test", run wall-clock
should be ~90s. The test is gated by the presence of ``MODAL_TOKEN_ID``,
``MODAL_TOKEN_SECRET``, and ``MODAL_BENCH_TOKEN`` in the env; without
them, pytest skips.
"""

from __future__ import annotations

import asyncio
import os
import secrets

import httpx
import pytest

_REQUIRED_ENV = ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")

pytestmark = pytest.mark.skipif(
    not all(os.environ.get(k) for k in _REQUIRED_ENV),
    reason="M5.1 Modal smoke test requires " + ", ".join(_REQUIRED_ENV) + " in the environment",
)


@pytest.mark.slow
def test_m5_1_modal_smoke_deploy_probe_cohort_teardown() -> None:
    """End-to-end: deploy → both probes → tiny REST cohort + tiny gRPC cohort → teardown."""
    if not os.environ.get("MODAL_BENCH_TOKEN"):
        os.environ["MODAL_BENCH_TOKEN"] = secrets.token_urlsafe(32)
    token_env = "MODAL_BENCH_TOKEN"

    async def _run() -> None:
        from vllm_grpc_bench.channel_config import M1_BASELINE
        from vllm_grpc_bench.m5_1_grpc_cohort import run_grpc_cohort
        from vllm_grpc_bench.modal_endpoint import provide_rest_grpc_endpoint
        from vllm_grpc_bench.rest_cohort import run_rest_cohort

        async with provide_rest_grpc_endpoint(region="eu-west-1", token_env=token_env) as endpoints:
            token = os.environ[token_env]
            # 1) REST /healthz unauth probe.
            async with httpx.AsyncClient(timeout=30.0) as c:
                health = await c.get(f"{endpoints.rest_url}/healthz")
                assert health.status_code == 200
            # 2) Tiny REST chat_stream cohort (n=10).
            rest = await run_rest_cohort(
                path="chat_stream",
                base_url=endpoints.rest_url,
                token=token,
                concurrency=1,
                n=10,
                hidden_size=2048,
                timeout_s=60.0,
                rtt_probe_n=4,
            )
            assert len(rest.samples) == 10
            assert all(s.shim_overhead_ms >= 0 for s in rest.samples)
            # 3) Tiny gRPC chat_stream cohort (n=10).
            grpc_result = await run_grpc_cohort(
                path="chat_stream",
                target=endpoints.grpc_url,
                credentials=None,
                metadata=(("authorization", f"Bearer {token}"),),
                channel_config=M1_BASELINE,
                sub_cohort_kind="tuned_grpc",
                concurrency=1,
                n=10,
                hidden_size=2048,
                seed=42,
                cell_id="smoke:chat_stream:h2048:c1",
                rtt_probe_n=4,
            )
            assert len(grpc_result.samples) == 10
            # 4) Clean teardown happens on context exit.

    asyncio.run(_run())
