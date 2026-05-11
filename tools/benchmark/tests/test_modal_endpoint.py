"""T018 — bearer-token plumbing in ``modal_endpoint.provide_endpoint``.

Full Modal contact happens in the secrets-gated integration test
(``tests/integration/test_m5_modal_smoke.py``). This unit test covers the
contract surface that can be exercised without the Modal SDK: env-var
sourcing, ``static_endpoint_provider`` yields, and the URL-scheme stripper.
"""

from __future__ import annotations

import grpc
import pytest
from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.mock_engine import MockEngine, MockEngineConfig
from vllm_grpc_bench.modal_endpoint import (
    ModalDeployError,
    _strip_scheme,
    provide_endpoint,
    static_endpoint_provider,
)


@pytest.mark.asyncio
async def test_provide_endpoint_refuses_when_token_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing bearer-token env var raises a clear ModalDeployError."""
    monkeypatch.delenv("MODAL_BENCH_TOKEN", raising=False)
    monkeypatch.delenv("M5_TEST_TOKEN", raising=False)
    engine = MockEngine(MockEngineConfig(hidden_size=2048, seed=0))
    with pytest.raises(ModalDeployError, match=r"MODAL_BENCH_TOKEN"):
        async with provide_endpoint(engine, M1_BASELINE, region="us-east-1") as _:
            pytest.fail("provide_endpoint should have raised before yielding")  # pragma: no cover


@pytest.mark.asyncio
async def test_static_endpoint_provider_yields_secure_endpoint_with_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``--m5-skip-deploy`` provider yields ``(host:port, ssl_creds, auth_md)``
    without contacting Modal.
    """
    monkeypatch.setenv("MODAL_BENCH_TOKEN", "test-bearer-abc")
    engine = MockEngine(MockEngineConfig(hidden_size=2048, seed=0))
    async with static_endpoint_provider(
        engine,
        M1_BASELINE,
        target="grpcs://r3.modal.host:54321",
    ) as (target, credentials, metadata):
        # Scheme is stripped to plain host:port.
        assert target == "r3.modal.host:54321"
        # secure_channel-compatible credentials.
        assert credentials is not None
        assert isinstance(credentials, grpc.ChannelCredentials)
        # Bearer-token metadata is the only header attached.
        assert metadata == (("authorization", "Bearer test-bearer-abc"),)


@pytest.mark.asyncio
async def test_static_endpoint_provider_refuses_unset_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Static provider also requires the bearer token to be set."""
    monkeypatch.delenv("MODAL_BENCH_TOKEN", raising=False)
    engine = MockEngine(MockEngineConfig(hidden_size=2048, seed=0))
    with pytest.raises(ModalDeployError, match=r"MODAL_BENCH_TOKEN"):
        async with static_endpoint_provider(engine, M1_BASELINE, target="r3.modal.host:54321") as _:
            pytest.fail("expected refusal")  # pragma: no cover


class TestStripScheme:
    """Endpoint URL parsing is independent of Modal's tunnel format."""

    @pytest.mark.parametrize(
        "incoming, expected",
        [
            ("tcp://r3.modal.host:54321", "r3.modal.host:54321"),
            ("grpcs://r3.modal.host:54321", "r3.modal.host:54321"),
            ("https://r3.modal.host:54321", "r3.modal.host:54321"),
            ("grpc://r3.modal.host:54321", "r3.modal.host:54321"),
            ("r3.modal.host:54321", "r3.modal.host:54321"),  # already bare
        ],
    )
    def test_strip_scheme(self, incoming: str, expected: str) -> None:
        assert _strip_scheme(incoming) == expected
