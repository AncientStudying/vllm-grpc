"""M6.1.2 — Progress + warning stderr format tests (Story 3 / SC-005).

Per ``specs/025-m6-1-2-methodology-discipline/tasks.md`` T024:

* ``test_m6_1_2_warning_lines_have_iso_prefix`` — synthesize the FR-005a
  all-fail scenario and the FR-006 cohort-CSP-mismatch scenario, capture
  stderr, assert both warning lines match
  ``^\\[\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z\\]`` per FR-020 +
  round-2 Q5.
* ``test_m6_1_2_stderr_ts_helper_format`` — direct unit test on the
  helper used by both the warning emitters and (Phase 6) the sweep
  orchestrator.
"""

from __future__ import annotations

import io
import re
from contextlib import redirect_stderr

from vllm_grpc_bench.m6_1_2_network_probe import _stderr_ts, emit_probe_warnings
from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2NetworkPath,
    M6_1_2NetworkPathError,
    M6_1_2NetworkPathHop,
)

_TS_PREFIX_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\] ")


def test_stderr_ts_helper_format() -> None:
    """``_stderr_ts()`` returns a bracketed ISO-8601 UTC second-precision
    string. Mirrors the format used across m6_sweep / m6_1_sweep /
    m6_1_1_sweep per R-7."""
    prefix = _stderr_ts()
    assert _TS_PREFIX_RE.match(prefix + " probe-tail")


def _build_success_path(cloud_provider: str = "AWS") -> M6_1_2NetworkPath:
    return M6_1_2NetworkPath(
        endpoint_ip="192.0.2.1",
        hops=[
            M6_1_2NetworkPathHop(
                hop_number=1,
                ip="192.168.1.1",
                rtt_ms_or_null=1.0,
                cloud_provider=None,
            )
        ],
        cloud_provider=cloud_provider,  # type: ignore[arg-type]  # tests exercise mismatch
        region="us-west-1",
        probe_method="tcptraceroute",
        probed_at_utc="2026-05-17T12:00:00Z",
    )


def _build_error_path(error: str = "probe_timeout") -> M6_1_2NetworkPathError:
    return M6_1_2NetworkPathError(
        error=error,  # type: ignore[arg-type]  # tests pass literal values
        probe_method="tcptraceroute",
        probed_at_utc="2026-05-17T12:00:00Z",
        detail=None,
    )


def test_m6_1_2_warning_lines_have_iso_prefix_all_fail() -> None:
    """FR-005a: every cohort probe failed → loud warning at sweep start;
    line must carry the ISO-8601 prefix per FR-020."""
    results = {
        "rest_https_edge": _build_error_path("tcptraceroute_unavailable"),
        "rest_plain_tcp": _build_error_path("tcptraceroute_unavailable"),
        "default_grpc": _build_error_path("tcptraceroute_unavailable"),
        "tuned_grpc_multiplexed": _build_error_path("tcptraceroute_unavailable"),
    }
    buf = io.StringIO()
    with redirect_stderr(buf):
        emit_probe_warnings(results)  # type: ignore[arg-type]
    lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    assert lines, "expected at least one warning line"
    for line in lines:
        assert _TS_PREFIX_RE.match(line), f"warning line missing ISO-8601 prefix: {line!r}"
        assert "WARNING" in line


def test_m6_1_2_warning_lines_have_iso_prefix_cohort_csp_mismatch() -> None:
    """FR-006: cohort entered a different CSP than spike-expected → loud
    warning; line must carry the ISO-8601 prefix per FR-020."""
    # rest_https_edge is expected to be Microsoft Azure; supply AWS instead.
    results = {
        "rest_https_edge": _build_success_path(cloud_provider="AWS"),
        "rest_plain_tcp": _build_success_path(cloud_provider="AWS"),
        "default_grpc": _build_success_path(cloud_provider="AWS"),
        "tuned_grpc_multiplexed": _build_success_path(cloud_provider="AWS"),
    }
    buf = io.StringIO()
    with redirect_stderr(buf):
        emit_probe_warnings(results)  # type: ignore[arg-type]
    lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    assert lines, "expected at least one mismatch warning line"
    mismatch_lines = [line for line in lines if "rest_https_edge" in line]
    assert mismatch_lines, "expected a mismatch warning for rest_https_edge"
    for line in mismatch_lines:
        assert _TS_PREFIX_RE.match(line)
        assert "topology has changed" in line


def test_no_warnings_when_topology_matches_expectation() -> None:
    """Sanity: when every cohort matches the spike-expected CSP, no
    cohort-CSP-mismatch warnings fire."""
    results = {
        "rest_https_edge": _build_success_path(cloud_provider="Microsoft Azure"),
        "rest_plain_tcp": _build_success_path(cloud_provider="AWS"),
        "default_grpc": _build_success_path(cloud_provider="AWS"),
        "tuned_grpc_multiplexed": _build_success_path(cloud_provider="AWS"),
    }
    buf = io.StringIO()
    with redirect_stderr(buf):
        emit_probe_warnings(results)  # type: ignore[arg-type]
    assert buf.getvalue() == ""
