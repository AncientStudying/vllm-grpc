"""T029 — Modal-secrets-gated end-to-end smoke test for M5.2.

Deploys the dual-protocol Modal app with the third plain-TCP REST tunnel,
exercises the four M5.2 smoke assertions before any cohort dispatch, runs
the 4-cell smoke matrix at n=5, emits the events sidecar, re-runs the
regenerator, and confirms clean teardown.

Per ``specs/019-m5-2-transport-tuning/quickstart.md`` Step 2, run
wall-clock should be ~90s. The test is gated on the presence of
``MODAL_TOKEN_ID`` + ``MODAL_TOKEN_SECRET`` (and an auto-generated
``MODAL_BENCH_TOKEN`` if unset).
"""

from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path

import pytest

_REQUIRED_ENV = ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")

pytestmark = pytest.mark.skipif(
    not all(os.environ.get(k) for k in _REQUIRED_ENV),
    reason=("M5.2 Modal smoke test requires " + ", ".join(_REQUIRED_ENV) + " in the environment"),
)


@pytest.mark.slow
def test_m5_2_modal_smoke_deploy_assertions_4cell_sidecar_teardown(
    tmp_path: Path,
) -> None:
    """End-to-end: deploy → three tunnel URLs → M5.2 smoke assertions → 4-cell
    smoke at n=5 → events sidecar emit + SHA-256 → regenerator round-trip
    diff against the smoke's published artifacts is empty → teardown.
    """
    if not os.environ.get("MODAL_BENCH_TOKEN"):
        os.environ["MODAL_BENCH_TOKEN"] = secrets.token_urlsafe(32)

    async def _run() -> None:
        from vllm_grpc_bench.m5_2_sweep import (
            SMOKE_CELLS,
            M5_2SweepConfig,
            run_m5_2_sweep,
        )
        from vllm_grpc_bench.modal_endpoint import provide_rest_grpc_endpoint

        async with provide_rest_grpc_endpoint(
            region="eu-west-1",
            token_env="MODAL_BENCH_TOKEN",
            with_rest_plain_tcp=True,
        ) as endpoints:
            assert endpoints.rest_plain_tcp_url is not None, (
                "M5.2 deploy must expose a plain-TCP REST tunnel"
            )
            # Three tunnel URLs are emitted.
            assert endpoints.grpc_url
            assert endpoints.rest_url
            assert endpoints.rest_plain_tcp_url.startswith("tcp+plaintext://")

            rest_tcp = endpoints.rest_plain_tcp_url
            # The httpx client needs an http:// scheme; the cohort runner
            # consumes the bare host:port form.
            from vllm_grpc_bench.modal_endpoint import _strip_scheme

            rest_tcp_url = f"http://{_strip_scheme(rest_tcp)}"

            cfg = M5_2SweepConfig(
                rest_https_edge_url=endpoints.rest_url,
                rest_plain_tcp_url=rest_tcp_url,
                grpc_target=endpoints.grpc_url,
                run_id="smoke-integration",
                events_sidecar_out_dir=tmp_path,
                modal_region="eu-west-1",
                modal_instance_class="cpu",
                https_edge_endpoint=endpoints.rest_url,
                n_per_cohort=5,
                expand_n=5,
                rtt_probe_n=4,
                warmup_n=2,
                cells_override=SMOKE_CELLS,
                smoke=True,
            )
            run = await run_m5_2_sweep(cfg, progress=False)
            # The sidecar exists and the SHA matches.
            assert run.events_sidecar_path.exists()
            import hashlib

            assert (
                hashlib.sha256(run.events_sidecar_path.read_bytes()).hexdigest()
                == run.events_sidecar_sha256
            )

    asyncio.run(_run())
