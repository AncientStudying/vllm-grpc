"""M6.1.2 — Unit tests for ``m6_1_2_network_probe``.

Covers (per ``specs/025-m6-1-2-methodology-discipline/tasks.md`` T006-T009):

* CSP attribution helper (T006): canned IP-range JSON drives the AWS / Azure /
  GCP / unknown attribution paths without live network access.
* Hop parser (T007): canned ``tcptraceroute``-style stdout including success
  lines, asterisks, and empty input.
* Probe timeout / binary-missing / subprocess-error (T008): ``subprocess.run``
  is monkeypatched to raise the relevant exception classes.
* Parallel-across-cohorts execution (T009): four mock subprocess invocations
  with varying durations complete in less than serial wall-clock.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from typing import Any

import pytest
from vllm_grpc_bench.m6_1_2_network_probe import (
    _probe_one_cohort,
    attribute_cloud_provider,
    parse_tcptraceroute_output,
    run_topology_probe,
)
from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2NetworkPath,
    M6_1_2NetworkPathError,
)

# --- Canned IP-range fixtures -----------------------------------------------


@pytest.fixture
def aws_ranges() -> dict[str, Any]:
    return {
        "prefixes": [
            {"ip_prefix": "54.193.0.0/16", "region": "us-west-1"},
            {"ip_prefix": "52.0.0.0/8", "region": "us-east-1"},
        ],
        "ipv6_prefixes": [],
    }


@pytest.fixture
def azure_ranges() -> dict[str, Any]:
    return {
        "values": [
            {
                "name": "AzureCloud",
                "properties": {
                    "region": "westeurope",
                    "addressPrefixes": ["20.125.0.0/16", "104.44.0.0/16"],
                },
            },
        ],
    }


@pytest.fixture
def gcp_ranges() -> dict[str, Any]:
    return {
        "prefixes": [
            {"ipv4Prefix": "8.8.0.0/16", "scope": "global"},
            {"ipv4Prefix": "35.190.0.0/16", "scope": "us-central1"},
        ],
    }


@pytest.fixture
def all_ranges(
    aws_ranges: dict[str, Any],
    azure_ranges: dict[str, Any],
    gcp_ranges: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {"aws": aws_ranges, "azure": azure_ranges, "gcp": gcp_ranges}


# --- T006: CSP attribution --------------------------------------------------


def test_attribute_aws_ip(all_ranges: dict[str, dict[str, Any]]) -> None:
    csp, region = attribute_cloud_provider("54.193.31.244", ranges=all_ranges)
    assert csp == "AWS"
    assert region == "us-west-1"


def test_attribute_azure_ip(all_ranges: dict[str, dict[str, Any]]) -> None:
    csp, region = attribute_cloud_provider("20.125.113.97", ranges=all_ranges)
    assert csp == "Microsoft Azure"
    assert region == "westeurope"


def test_attribute_gcp_ip(all_ranges: dict[str, dict[str, Any]]) -> None:
    csp, region = attribute_cloud_provider("35.190.10.20", ranges=all_ranges)
    assert csp == "GCP"
    assert region == "us-central1"


def test_attribute_unknown_ip(
    all_ranges: dict[str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the whois fallback to fail so we exercise the final ("unknown", None).
    monkeypatch.setattr(
        "vllm_grpc_bench.m6_1_2_network_probe._whois_lookup",
        lambda ip, timeout=5.0: None,
    )
    csp, region = attribute_cloud_provider("203.0.113.42", ranges=all_ranges)
    assert csp == "unknown"
    assert region is None


# --- T007: hop parser -------------------------------------------------------


_SAMPLE_TCPTRACEROUTE_SUCCESS = """
Selected device en0, address 192.168.2.30, port 60123
Tracing the path to r439.modal.host (54.193.31.244) on TCP port 43209, 18 hops max
 1  192.168.2.1  3.740 ms
 2  192.168.1.1  5.047 ms
 3  *
 4  173.219.208.88  13.024 ms
 5  173.219.197.48  16.555 ms
 9  51.10.39.124  59.152 ms
"""


def test_parse_tcptraceroute_output_success() -> None:
    hops = parse_tcptraceroute_output(_SAMPLE_TCPTRACEROUTE_SUCCESS)
    assert [h.hop_number for h in hops] == [1, 2, 3, 4, 5, 9]
    assert [h.ip for h in hops] == [
        "192.168.2.1",
        "192.168.1.1",
        None,
        "173.219.208.88",
        "173.219.197.48",
        "51.10.39.124",
    ]
    assert hops[0].rtt_ms_or_null == 3.740
    assert hops[2].rtt_ms_or_null is None
    # cloud_provider always None at parse time (annotation happens later).
    assert all(h.cloud_provider is None for h in hops)


def test_parse_tcptraceroute_output_asterisks() -> None:
    output = " 1  *\n 2  *\n 3  *\n"
    hops = parse_tcptraceroute_output(output)
    assert len(hops) == 3
    assert all(h.ip is None and h.rtt_ms_or_null is None for h in hops)
    assert [h.hop_number for h in hops] == [1, 2, 3]


def test_parse_tcptraceroute_output_empty() -> None:
    assert parse_tcptraceroute_output("") == []
    assert parse_tcptraceroute_output("noise without hop lines\n") == []


# --- T008: subprocess failure modes -----------------------------------------


def test_probe_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_timeout(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd=["tcptraceroute"], timeout=30)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    result = _probe_one_cohort("host.example", 443, timeout=30, ranges={})
    assert isinstance(result, M6_1_2NetworkPathError)
    assert result.error == "probe_timeout"
    assert result.probe_method == "tcptraceroute"


def test_probe_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_fnf(*_args: object, **_kwargs: object) -> object:
        raise FileNotFoundError("tcptraceroute")

    monkeypatch.setattr(subprocess, "run", _raise_fnf)
    result = _probe_one_cohort("host.example", 443, timeout=30, ranges={})
    assert isinstance(result, M6_1_2NetworkPathError)
    assert result.error == "tcptraceroute_unavailable"


def test_probe_subprocess_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Proc:
        returncode = 2
        stdout = ""
        stderr = "tcptraceroute: bind: Permission denied\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Proc())
    result = _probe_one_cohort("host.example", 443, timeout=30, ranges={})
    assert isinstance(result, M6_1_2NetworkPathError)
    assert result.error == "subprocess_error"
    assert result.detail == "tcptraceroute: bind: Permission denied"


# --- T009: parallel-across-cohorts ------------------------------------------


def test_probe_runs_parallel_across_cohorts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per FR-001a: 4 cohorts probed in parallel; total wall-clock < serial sum."""

    # Each subprocess.run sleeps 0.5s; serial would be 2.0s, parallel ~0.5s.
    SLEEP_S = 0.5

    class _Proc:
        returncode = 0
        stdout = " 1  192.168.2.1  1.0 ms\n"
        stderr = ""

    def _slow_run(*_args: object, **_kwargs: object) -> _Proc:
        time.sleep(SLEEP_S)
        return _Proc()

    monkeypatch.setattr(subprocess, "run", _slow_run)
    # Stub the DNS lookup so we don't hit the real resolver.
    monkeypatch.setattr(
        "vllm_grpc_bench.m6_1_2_network_probe.socket.gethostbyname",
        lambda _host: "127.0.0.1",
    )

    handshake: dict[str, object] = {
        "rest_https_edge_url": "https://edge.example/path",
        "rest_plain_tcp_url": "tcp+plaintext://plain.example:1234",
        "grpc": "tcp+plaintext://grpc.example:5678",
    }

    started = time.monotonic()
    results = asyncio.run(
        run_topology_probe(
            handshake_dict=handshake,
            per_cohort_timeout_seconds=5.0,
            ranges={"aws": {}, "azure": {}, "gcp": {}},
        )
    )
    elapsed = time.monotonic() - started

    # Serial would be ~2.0s (4 × 0.5s). Parallel should be well under 2.0s.
    assert elapsed < 1.5, f"expected parallel execution; got {elapsed:.2f}s"
    # 4 cohorts -> 4 entries. default_grpc and tuned_grpc_multiplexed share
    # the same handshake key but each probes independently.
    assert set(results.keys()) == {
        "rest_https_edge",
        "rest_plain_tcp",
        "default_grpc",
        "tuned_grpc_multiplexed",
    }
    assert all(isinstance(r, M6_1_2NetworkPath) for r in results.values())
