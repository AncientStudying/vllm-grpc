"""T020 — M5.2-specific extensions to ``modal_endpoint``.

The ``with_rest_plain_tcp=True`` kwarg additively exposes the FastAPI
shim's plain-TCP URL and HTTPS-edge URL alongside M5.1's existing
plain-TCP REST URL. Default ``False`` preserves the M5.1 call signature
so existing call-sites continue to work unchanged.

M5.2 uses a SECOND in-container port (8001) for the HTTPS-edge forward
because Modal refuses two ``modal.forward`` calls to the same port — see
``scripts/python/modal_bench_rest_grpc_server.py`` for the rationale.
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
async def test_handshake_with_rest_plain_tcp_returns_all_four_urls() -> None:
    d = _FakeDict(
        {
            "ready": True,
            "grpc": "tcp+plaintext://abc.modal.host:50051",
            # M5.1's ``rest`` key is plain-TCP per M5.1's voiding of FR-019.
            "rest": "http://abc.modal.host:8000",
            "rest_plain_tcp_url": "tcp+plaintext://abc.modal.host:8000",
            "rest_https_edge_url": "https://abc.modal.run",
            "token": "tok",
        }
    )
    grpc_url, rest_url, rest_plain_tcp, rest_https_edge = await _wait_for_rest_grpc_handshake(
        d, timeout_s=2.0, expected_token="tok", with_rest_plain_tcp=True
    )
    assert grpc_url == "tcp+plaintext://abc.modal.host:50051"
    assert rest_url == "http://abc.modal.host:8000"
    assert rest_plain_tcp == "tcp+plaintext://abc.modal.host:8000"
    assert rest_https_edge == "https://abc.modal.run"


@pytest.mark.asyncio
async def test_handshake_without_with_rest_plain_tcp_returns_none_for_trailing() -> None:
    """Back-compat: M5.1 callers that don't pass ``with_rest_plain_tcp=True``
    get None for the trailing M5.2 URLs even when the dict contains them."""
    d = _FakeDict(
        {
            "ready": True,
            "grpc": "tcp+plaintext://abc.modal.host:50051",
            "rest": "http://abc.modal.host:8000",
            "rest_plain_tcp_url": "tcp+plaintext://abc.modal.host:8000",
            "rest_https_edge_url": "https://abc.modal.run",
            "token": "tok",
        }
    )
    _, _, rest_plain_tcp, rest_https_edge = await _wait_for_rest_grpc_handshake(
        d, timeout_s=2.0, expected_token="tok"
    )
    assert rest_plain_tcp is None
    assert rest_https_edge is None


@pytest.mark.asyncio
async def test_handshake_missing_rest_plain_tcp_url_raises_when_requested() -> None:
    """When ``with_rest_plain_tcp=True`` but the deploy didn't write the
    plain-TCP URL to the dict, the handshake helper raises with the
    missing key named."""
    d = _FakeDict(
        {
            "ready": True,
            "grpc": "tcp+plaintext://abc.modal.host:50051",
            "rest": "http://abc.modal.host:8000",
            "rest_https_edge_url": "https://abc.modal.run",
            "token": "tok",
            # No rest_plain_tcp_url key.
        }
    )
    with pytest.raises(ModalDeployError, match="rest_plain_tcp_url is empty"):
        await _wait_for_rest_grpc_handshake(
            d, timeout_s=2.0, expected_token="tok", with_rest_plain_tcp=True
        )


@pytest.mark.asyncio
async def test_handshake_missing_rest_https_edge_url_raises_when_requested() -> None:
    """When ``with_rest_plain_tcp=True`` but the deploy didn't write the
    HTTPS-edge URL to the dict, the handshake helper raises with the
    missing key named."""
    d = _FakeDict(
        {
            "ready": True,
            "grpc": "tcp+plaintext://abc.modal.host:50051",
            "rest": "http://abc.modal.host:8000",
            "rest_plain_tcp_url": "tcp+plaintext://abc.modal.host:8000",
            "token": "tok",
            # No rest_https_edge_url key.
        }
    )
    with pytest.raises(ModalDeployError, match="rest_https_edge_url is empty"):
        await _wait_for_rest_grpc_handshake(
            d, timeout_s=2.0, expected_token="tok", with_rest_plain_tcp=True
        )


def test_rest_grpc_endpoints_with_m5_2_fields() -> None:
    bundle = RESTGRPCEndpoints(
        grpc_url="abc.modal.host:50051",
        rest_url="http://abc.modal.host:8000",
        auth_token_env_var="MODAL_BENCH_TOKEN",
        rest_plain_tcp_url="tcp+plaintext://abc.modal.host:8000",
        rest_https_edge_url="https://abc.modal.run",
    )
    assert bundle.rest_plain_tcp_url == "tcp+plaintext://abc.modal.host:8000"
    assert bundle.rest_https_edge_url == "https://abc.modal.run"


def test_rest_grpc_endpoints_m5_2_fields_default_to_none() -> None:
    """M5.1 back-compat: omitting the M5.2 fields leaves them None."""
    bundle = RESTGRPCEndpoints(
        grpc_url="abc.modal.host:50051",
        rest_url="http://abc.modal.host:8000",
        auth_token_env_var="MODAL_BENCH_TOKEN",
    )
    assert bundle.rest_plain_tcp_url is None
    assert bundle.rest_https_edge_url is None


def test_rest_plain_tcp_url_uses_tcp_plaintext_scheme_prefix() -> None:
    """Plain-TCP URL convention: ``tcp+plaintext://host:port`` so the
    consuming REST client can recognize the path and use plain HTTP/1.1
    on the bare host:port."""
    bundle = RESTGRPCEndpoints(
        grpc_url="abc.modal.host:50051",
        rest_url="http://abc.modal.host:8000",
        auth_token_env_var="MODAL_BENCH_TOKEN",
        rest_plain_tcp_url="tcp+plaintext://abc.modal.host:8000",
        rest_https_edge_url="https://abc.modal.run",
    )
    assert bundle.rest_plain_tcp_url is not None
    assert bundle.rest_plain_tcp_url.startswith("tcp+plaintext://")
    assert bundle.rest_https_edge_url is not None
    assert bundle.rest_https_edge_url.startswith("https://")
