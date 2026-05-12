"""T020 — M5.2-specific extensions to ``modal_endpoint``.

The ``with_rest_plain_tcp=True`` kwarg additively exposes the FastAPI shim's
plain-TCP URL alongside the M5.1 HTTPS-edge URL. Default ``False`` preserves
the M5.1 call signature so existing call-sites continue to work unchanged.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.modal_endpoint import (
    ModalDeployError,
    RESTGRPCEndpoints,
    _wait_for_rest_grpc_handshake,
)


class _FakeDictGet:
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
async def test_handshake_with_rest_plain_tcp_returns_all_three_urls() -> None:
    d = _FakeDict(
        {
            "ready": True,
            "grpc": "tcp+plaintext://abc.modal.host:50051",
            "rest": "https://abc.modal.run",
            "rest_plain_tcp_url": "tcp+plaintext://abc.modal.host:8000",
            "token": "tok",
        }
    )
    grpc_url, rest_url, rest_plain_tcp = await _wait_for_rest_grpc_handshake(
        d, timeout_s=2.0, expected_token="tok", with_rest_plain_tcp=True
    )
    assert grpc_url == "tcp+plaintext://abc.modal.host:50051"
    assert rest_url == "https://abc.modal.run"
    assert rest_plain_tcp == "tcp+plaintext://abc.modal.host:8000"


@pytest.mark.asyncio
async def test_handshake_without_with_rest_plain_tcp_returns_none_for_third() -> None:
    """Back-compat: M5.1 callers that don't pass with_rest_plain_tcp=True
    still get the M5.1 2-tuple of (grpc, rest) — and the third element is
    None — even when the Dict contains a rest_plain_tcp_url key."""
    d = _FakeDict(
        {
            "ready": True,
            "grpc": "tcp+plaintext://abc.modal.host:50051",
            "rest": "https://abc.modal.run",
            "rest_plain_tcp_url": "tcp+plaintext://abc.modal.host:8000",
            "token": "tok",
        }
    )
    _, _, rest_plain_tcp = await _wait_for_rest_grpc_handshake(
        d, timeout_s=2.0, expected_token="tok"
    )
    assert rest_plain_tcp is None


@pytest.mark.asyncio
async def test_handshake_missing_rest_plain_tcp_url_raises_when_requested() -> None:
    """When ``with_rest_plain_tcp=True`` is set but the deploy never wrote
    the third URL to the Dict (e.g., operator forgot to redeploy the Modal
    app after pulling the M5.2 change), the handshake helper raises a
    clear ModalDeployError naming the missing key.
    """
    d = _FakeDict(
        {
            "ready": True,
            "grpc": "tcp+plaintext://abc.modal.host:50051",
            "rest": "https://abc.modal.run",
            "token": "tok",
            # No rest_plain_tcp_url key.
        }
    )
    with pytest.raises(ModalDeployError, match="rest_plain_tcp_url is empty"):
        await _wait_for_rest_grpc_handshake(
            d, timeout_s=2.0, expected_token="tok", with_rest_plain_tcp=True
        )


def test_rest_grpc_endpoints_with_third_url_field() -> None:
    bundle = RESTGRPCEndpoints(
        grpc_url="abc.modal.host:50051",
        rest_url="https://abc.modal.run",
        auth_token_env_var="MODAL_BENCH_TOKEN",
        rest_plain_tcp_url="tcp+plaintext://abc.modal.host:8000",
    )
    assert bundle.rest_plain_tcp_url == "tcp+plaintext://abc.modal.host:8000"


def test_rest_grpc_endpoints_third_url_defaults_to_none() -> None:
    """M5.1 back-compat: omitting the third URL leaves the field None."""
    bundle = RESTGRPCEndpoints(
        grpc_url="abc.modal.host:50051",
        rest_url="https://abc.modal.run",
        auth_token_env_var="MODAL_BENCH_TOKEN",
    )
    assert bundle.rest_plain_tcp_url is None


def test_rest_plain_tcp_url_uses_tcp_plaintext_scheme_prefix() -> None:
    """The scheme prefix convention is ``tcp+plaintext://host:port`` so the
    consuming REST client can recognize the plain-TCP path and use plain
    HTTP/1.1 (no TLS) on the bare host:port pair.
    """
    bundle = RESTGRPCEndpoints(
        grpc_url="abc.modal.host:50051",
        rest_url="https://abc.modal.run",
        auth_token_env_var="MODAL_BENCH_TOKEN",
        rest_plain_tcp_url="tcp+plaintext://abc.modal.host:8000",
    )
    assert bundle.rest_plain_tcp_url is not None
    assert bundle.rest_plain_tcp_url.startswith("tcp+plaintext://")
