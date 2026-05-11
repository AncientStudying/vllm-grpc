"""T013 — bearer-token + dual-protocol handshake plumbing in
``modal_endpoint.provide_rest_grpc_endpoint``.

Full Modal contact happens in the secrets-gated integration test
(``tests/integration/test_m5_1_modal_smoke.py``). This unit test covers the
contract surface that can be exercised without the Modal SDK: env-var
refusal, bearer-token-env-var name plumbing on the returned bundle, the
M5.1 handshake-dict polling helper (faked dict), the regression assertion
that the legacy gRPC-only ``provide_endpoint`` path is unchanged, and the
clear-error path when ``rest`` is missing from the dict.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.mock_engine import MockEngine, MockEngineConfig
from vllm_grpc_bench.modal_endpoint import (
    ModalDeployError,
    RESTGRPCEndpoints,
    _wait_for_rest_grpc_handshake,
    provide_endpoint,
    provide_rest_grpc_endpoint,
)


class _FakeDictGet:
    """Mimics modal.Dict.from_name(...).get.aio interface for testing."""

    def __init__(self, dict_obj: _FakeDict) -> None:
        self._d = dict_obj

    async def aio(self, key: str, default: object = None) -> object:
        return self._d.contents.get(key, default)


class _FakeDictPut:
    def __init__(self, dict_obj: _FakeDict) -> None:
        self._d = dict_obj

    async def aio(self, key: str, value: object) -> None:
        self._d.contents[key] = value


class _FakeDictPop:
    def __init__(self, dict_obj: _FakeDict) -> None:
        self._d = dict_obj

    async def aio(self, key: str) -> None:
        self._d.contents.pop(key, None)


class _FakeDict:
    def __init__(self, initial: dict[str, object] | None = None) -> None:
        self.contents: dict[str, object] = dict(initial or {})
        self.get = _FakeDictGet(self)
        self.put = _FakeDictPut(self)
        self.pop = _FakeDictPop(self)


@pytest.mark.asyncio
async def test_provide_rest_grpc_endpoint_refuses_when_token_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T013 (regression-style on env-var refusal): missing bearer-token env
    var raises a clear ModalDeployError before any Modal SDK contact."""
    monkeypatch.delenv("MODAL_BENCH_TOKEN", raising=False)
    with pytest.raises(ModalDeployError, match=r"MODAL_BENCH_TOKEN"):
        async with provide_rest_grpc_endpoint(region="eu-west-1") as _:
            pytest.fail("expected ModalDeployError before yielding")  # pragma: no cover


@pytest.mark.asyncio
async def test_legacy_grpc_only_provide_endpoint_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T013 (b) — the legacy ``provide_endpoint`` call path remains unchanged.

    We exercise the env-var refusal branch (the only contract surface that
    runs without a real Modal SDK) to confirm the signature still accepts
    ``(engine, channel_config, *, region, token_env)`` with the M5-style
    semantics.
    """
    monkeypatch.delenv("MODAL_BENCH_TOKEN", raising=False)
    engine = MockEngine(MockEngineConfig(hidden_size=2048, seed=0))
    with pytest.raises(ModalDeployError, match=r"MODAL_BENCH_TOKEN"):
        async with provide_endpoint(engine, M1_BASELINE, region="us-east-1") as _:
            pytest.fail("expected refusal")  # pragma: no cover


@pytest.mark.asyncio
async def test_wait_for_rest_grpc_handshake_returns_both_urls() -> None:
    """T013 (a) — given a faked ``modal.Dict`` populated with ``ready=True``,
    ``grpc``, ``rest``, and a matching ``token``, the handshake helper
    returns the (grpc_url, rest_url) tuple.
    """
    d = _FakeDict(
        {
            "ready": True,
            "grpc": "tcp+plaintext://abc.modal.host:50051",
            "rest": "https://abc.modal.host",
            "token": "test-token-123",
        }
    )
    grpc_url, rest_url = await _wait_for_rest_grpc_handshake(
        d, timeout_s=2.0, expected_token="test-token-123"
    )
    assert grpc_url == "tcp+plaintext://abc.modal.host:50051"
    assert rest_url == "https://abc.modal.host"


@pytest.mark.asyncio
async def test_wait_for_rest_grpc_handshake_missing_rest_raises_within_timeout() -> None:
    """T013 (c) — when ``rest`` is missing from the dict (and ``ready`` never
    flips), the handshake helper raises a clear error within timeout.
    Note: when ``ready=False`` for the whole window we get a timeout; when
    ``ready=True`` is set without rest_url, we get the empty-URL message.
    """
    d = _FakeDict(
        {
            "ready": True,
            "grpc": "tcp+plaintext://abc.modal.host:50051",
            "rest": "",
            "token": "test-token-123",
        }
    )
    with pytest.raises(ModalDeployError, match=r"REST URL is empty"):
        await _wait_for_rest_grpc_handshake(d, timeout_s=2.0, expected_token="test-token-123")


@pytest.mark.asyncio
async def test_wait_for_rest_grpc_handshake_token_mismatch_raises() -> None:
    """Token-echo mismatch surfaces as ModalDeployError."""
    d = _FakeDict(
        {
            "ready": True,
            "grpc": "tcp+plaintext://abc.modal.host:50051",
            "rest": "https://abc.modal.host",
            "token": "stale-other-app-token",
        }
    )
    with pytest.raises(ModalDeployError, match=r"another Modal app"):
        await _wait_for_rest_grpc_handshake(d, timeout_s=2.0, expected_token="my-token")


@pytest.mark.asyncio
async def test_wait_for_rest_grpc_handshake_times_out_when_not_ready() -> None:
    d = _FakeDict({"ready": False})
    with pytest.raises(ModalDeployError, match=r"timed out"):
        await _wait_for_rest_grpc_handshake(d, timeout_s=0.6, expected_token="anything")


def test_rest_grpc_endpoints_records_env_var_not_token() -> None:
    """T013 (d) — bearer-token env-var name (not value) is what the bundle
    carries. The token value itself never enters the dataclass.
    """
    bundle = RESTGRPCEndpoints(
        grpc_url="abc.modal.host:50051",
        rest_url="https://abc.modal.host",
        auth_token_env_var="MODAL_BENCH_TOKEN",
    )
    assert bundle.auth_token_env_var == "MODAL_BENCH_TOKEN"
    # Sanity: no token-value-shaped strings are stored.
    for v in (bundle.grpc_url, bundle.rest_url, bundle.auth_token_env_var):
        assert "Bearer" not in v
